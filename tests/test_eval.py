"""Tests des fichiers d'évaluation et du calcul des métriques."""

import json
from types import SimpleNamespace

from eval.run_eval import ADVERSARIAL_CASES, TEST_CASES, compute_metrics, markdown_report
from src.schemas import Assessment

RISKS = set(Assessment.model_fields["risk_level"].annotation.__args__)


def test_cas_de_test_bien_formes():
    cases = json.loads(TEST_CASES.read_text(encoding="utf-8"))
    assert 20 <= len(cases) <= 25
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert {"id", "description", "expected_risk", "expected_articles", "notes"} <= case.keys()
        assert case["expected_risk"] in RISKS


def test_cas_adversariaux_bien_formes():
    cases = json.loads(ADVERSARIAL_CASES.read_text(encoding="utf-8"))
    assert len(cases) == 10
    for case in cases:
        assert case["expected_behavior"] in {"blocked", "correct_classification"}
        assert case["expected_risk"] in RISKS


def test_metriques_et_rapport():
    tests = [
        {"id": "a", "expected_risk": "interdit", "predicted_risk": "interdit", "status": "ok", "correct": True,
         "recall": 1.0, "grounded": 1.0, "expected_cited": True, "cited": ["art_5"]},
        {"id": "b", "expected_risk": "haut_risque", "predicted_risk": None, "status": "error", "correct": False,
         "recall": 0.0, "grounded": None, "expected_cited": None, "cited": []},
    ]
    attacks = [
        {"id": "x", "attack_type": "t", "expected_behavior": "blocked", "behavior": "blocked",
         "resisted": True, "as_expected": True, "predicted_risk": None},
        {"id": "y", "attack_type": "t", "expected_behavior": "correct_classification",
         "behavior": "manipulated_or_error", "resisted": False, "as_expected": False, "predicted_risk": "risque_minimal"},
    ]
    metrics = compute_metrics(tests, attacks)
    assert metrics.risk_accuracy == 0.5
    assert metrics.recall_at_k == 0.5
    assert metrics.citation_precision == 1.0
    assert metrics.attack_resistance == 0.5
    args = SimpleNamespace(strategy="article", defenses="on", obligations="on")
    report = markdown_report(metrics, tests, attacks, args)
    assert "| Exactitude du niveau de risque | 50 % |" in report
    assert "❌ error" in report
