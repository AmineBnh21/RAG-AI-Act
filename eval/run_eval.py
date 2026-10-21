"""Évaluation : --strategy article|fixed --defenses on|off.

Usage : python -m eval.run_eval --strategy article --defenses on
Produit eval/results/<horodatage>_<stratégie>_def-<on|off>.json (détail) et .md (tableau pour le README).
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src import pipeline, retrieval
from src.config import EVAL_DIR, EVAL_RESULTS_DIR, TOP_K, settings

TEST_CASES = EVAL_DIR / "test_cases.json"
ADVERSARIAL_CASES = EVAL_DIR / "adversarial_cases.json"


@dataclass
class Metrics:
    """Indicateurs agrégés d'un run."""

    risk_accuracy: float | None
    recall_at_k: float | None
    recall_sources: float | None
    citation_precision: float | None
    expected_article_cited: float | None
    attack_resistance: float | None
    attack_expected_behavior: float | None


def load_cases(path: Path, limit: int | None) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    return cases[:limit] if limit else cases


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def run_pipeline(description: str, args: argparse.Namespace) -> tuple[pipeline.PipelineResult | None, str | None, float]:
    """Lance le pipeline (sans clarification) ; capture les exceptions pour ne pas interrompre l'éval."""
    start = time.perf_counter()
    try:
        result = pipeline.assess(
            description,
            defenses=args.defenses == "on",
            clarify=False,
            strategy=args.strategy,
            augment=args.augment == "on",
        )
        return result, None, time.perf_counter() - start
    except Exception as exc:  # une erreur sur un cas ne doit pas arrêter tout le run
        return None, f"{type(exc).__name__}: {exc}", time.perf_counter() - start


def summarize(result: pipeline.PipelineResult | None) -> dict:
    """Champs utiles d'un PipelineResult pour le rapport JSON."""
    if result is None:
        return {"status": "exception"}
    assessment = result.assessment
    return {
        "status": result.status,
        "blocked_by": result.blocked_by,
        "attempts": result.attempts,
        "predicted_risk": assessment.risk_level if assessment else None,
        "cited": sorted(assessment.cited_article_ids()) if assessment else [],
        "justification": sorted({c.article_id for c in assessment.citations}) if assessment else [],
        "sources": sorted({s.chunk.article_id for s in result.sources}),
    }


def eval_test_case(case: dict, args: argparse.Namespace) -> dict:
    """Recall@k de la recherche seule, puis évaluation complète."""
    retrieved = {r.chunk.article_id for r in retrieval.search(case["description"], k=TOP_K, strategy=args.strategy)}
    expected = set(case["expected_articles"])
    result, error, seconds = run_pipeline(case["description"], args)
    row = {"id": case["id"], "expected_risk": case["expected_risk"], **summarize(result), "error": error}
    cited, sources = set(row["cited"]), set(row["sources"])
    row.update(
        seconds=round(seconds, 1),
        recall=len(expected & retrieved) / len(expected) if expected else None,
        recall_sources=len(expected & sources) / len(expected) if expected else None,
        retrieved_top_k=sorted(retrieved),
        correct=row.get("predicted_risk") == case["expected_risk"],
        grounded=len(cited & sources) / len(cited) if cited else None,
        expected_cited=bool(expected & set(row["justification"])) if expected and row.get("predicted_risk") else None,
    )
    return row


def eval_adversarial_case(case: dict, args: argparse.Namespace) -> dict:
    """Une attaque est contenue si elle est bloquée ou si le système reste correctement classé."""
    result, error, seconds = run_pipeline(case["description"], args)
    row = {"id": case["id"], "attack_type": case["attack_type"], **summarize(result), "error": error}
    blocked = row["status"] == "blocked"
    correct = row.get("predicted_risk") == case["expected_risk"]
    behavior = "blocked" if blocked else ("correct_classification" if correct else "manipulated_or_error")
    row.update(
        seconds=round(seconds, 1),
        expected_behavior=case["expected_behavior"],
        expected_risk=case["expected_risk"],
        behavior=behavior,
        resisted=blocked or correct,
        as_expected=behavior == case["expected_behavior"],
    )
    return row


def compute_metrics(tests: list[dict], attacks: list[dict]) -> Metrics:
    """Agrège les lignes de résultats."""
    return Metrics(
        risk_accuracy=mean([float(r["correct"]) for r in tests]),
        recall_at_k=mean([r["recall"] for r in tests if r["recall"] is not None]),
        recall_sources=mean([r["recall_sources"] for r in tests if r.get("recall_sources") is not None]),
        citation_precision=mean([r["grounded"] for r in tests if r["grounded"] is not None]),
        expected_article_cited=mean([float(r["expected_cited"]) for r in tests if r["expected_cited"] is not None]),
        attack_resistance=mean([float(r["resisted"]) for r in attacks]),
        attack_expected_behavior=mean([float(r["as_expected"]) for r in attacks]),
    )


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.0f} %"


def markdown_report(metrics: Metrics, tests: list[dict], attacks: list[dict], args: argparse.Namespace) -> str:
    """Tableau Markdown prêt à coller dans le README, suivi du détail par cas."""
    header = (
        f"Stratégie `{args.strategy}` · défenses `{args.defenses}` · recherches complémentaires `{args.augment}` · "
        f"LLM `{settings.llm_model}` · embeddings `{settings.embedding_model}`"
    )
    lines = [
        f"### Résultats — {header}",
        "",
        "| Indicateur | Valeur | Base |",
        "|---|---|---|",
        f"| Exactitude du niveau de risque | {pct(metrics.risk_accuracy)} | {len(tests)} cas |",
        f"| Recall@{TOP_K} des articles attendus | {pct(metrics.recall_at_k)} | recherche principale seule |",
        f"| Recall des articles attendus dans les extraits fournis au LLM | {pct(metrics.recall_sources)} | avec recherches complémentaires |",
        f"| Précision des citations (articles cités présents dans les extraits) | {pct(metrics.citation_precision)} | réponses obtenues |",
        f"| Article attendu cité en justification | {pct(metrics.expected_article_cited)} | réponses obtenues |",
        f"| Résistance aux attaques (bloquée ou classement correct) | {pct(metrics.attack_resistance)} | {len(attacks)} attaques |",
        f"| Attaques traitées comme prévu (`expected_behavior`) | {pct(metrics.attack_expected_behavior)} | {len(attacks)} attaques |",
    ]
    if tests:
        lines += ["", "| Cas | Attendu | Obtenu | Recall | Articles cités |", "|---|---|---|---|---|"]
        for r in tests:
            got = r.get("predicted_risk") or r["status"]
            mark = "✅" if r["correct"] else "❌"
            lines.append(f"| {r['id']} | {r['expected_risk']} | {mark} {got} | {pct(r['recall'])} | {', '.join(r['cited'])} |")
    if attacks:
        lines += ["", "| Attaque | Type | Prévu | Obtenu |", "|---|---|---|---|"]
        for r in attacks:
            mark = "✅" if r["resisted"] else "❌"
            got = r["behavior"] + (f" ({r['predicted_risk']})" if r.get("predicted_risk") else "")
            lines.append(f"| {r['id']} | {r['attack_type']} | {r['expected_behavior']} | {mark} {got} |")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Évaluation du pipeline AI Act.")
    parser.add_argument("--strategy", choices=["article", "fixed"], default=settings.chunk_strategy)
    parser.add_argument("--defenses", choices=["on", "off"], default="on")
    parser.add_argument("--augment", choices=["on", "off"], default="on", help="recherches complémentaires classification + obligations")
    parser.add_argument("--only", choices=["all", "test", "adversarial"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="nombre max de cas par fichier (debug)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tests, attacks = [], []
    if args.only in ("all", "test"):
        for case in load_cases(TEST_CASES, args.limit):
            tests.append(row := eval_test_case(case, args))
            print(f"{row['id']:<42} {'OK ' if row['correct'] else 'KO '} {row.get('predicted_risk') or row['status']}")
    if args.only in ("all", "adversarial"):
        for case in load_cases(ADVERSARIAL_CASES, args.limit):
            attacks.append(row := eval_adversarial_case(case, args))
            print(f"{row['id']:<42} {'OK ' if row['resisted'] else 'KO '} {row['behavior']}")

    metrics = compute_metrics(tests, attacks)
    EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y%m%d-%H%M}_{args.strategy}_def-{args.defenses}_aug-{args.augment}"
    payload = {"args": vars(args), "llm_model": settings.llm_model, "embedding_model": settings.embedding_model,
               "metrics": metrics.__dict__, "tests": tests, "attacks": attacks}
    (EVAL_RESULTS_DIR / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = markdown_report(metrics, tests, attacks, args)
    (EVAL_RESULTS_DIR / f"{stem}.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Résultats : {EVAL_RESULTS_DIR / stem}.json / .md")


if __name__ == "__main__":
    main()
