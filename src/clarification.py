"""Détection des informations clés manquantes et questions de clarification."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.generation import ask_model
from src.prompts import CLARIFICATION_QUESTIONS, CLARIFICATION_SYSTEM, delimited
from src.schemas import KeyInfo, KeyInfoExtraction

CRITICAL: tuple[KeyInfo, ...] = ("domaine", "personnes_concernees", "decisions_automatisees")
MIN_CRITICAL_MISSING = 2
MAX_QUESTIONS = 3
CLARIFICATION_MAX_TOKENS = 300


@dataclass(frozen=True)
class Clarification:
    """Infos manquantes détectées et questions à poser (vide si on peut évaluer)."""

    missing: list[KeyInfo]
    questions: list[str] = field(default_factory=list)

    @property
    def needed(self) -> bool:
        return bool(self.questions)


def questions_for(missing: list[KeyInfo]) -> list[str]:
    """Au plus 3 questions si au moins 2 infos critiques manquent ; critiques en premier."""
    critical = [key for key in CRITICAL if key in missing]
    if len(critical) < MIN_CRITICAL_MISSING:
        return []
    others = [key for key in CLARIFICATION_QUESTIONS if key in missing and key not in CRITICAL]
    return [CLARIFICATION_QUESTIONS[key] for key in [*critical, *others][:MAX_QUESTIONS]]


def with_answers(description: str, answers: dict[str, str]) -> str:
    """Ajoute les réponses aux questions de clarification à la description."""
    lines = [f"- {question} {answer.strip()}" for question, answer in answers.items() if answer.strip()]
    return description if not lines else f"{description}\n\nPrécisions :\n" + "\n".join(lines)


def check(description: str) -> Clarification:
    """Appel LLM qui extrait les infos clés, puis règle de décision déterministe sur les champs vides."""
    result = ask_model(CLARIFICATION_SYSTEM, delimited(description), KeyInfoExtraction, CLARIFICATION_MAX_TOKENS)
    missing = result.missing()
    return Clarification(missing, questions_for(missing))
