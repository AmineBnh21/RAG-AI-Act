"""Filtre d'entrée, validation des citations et rate limit."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from src.config import DESCRIPTION_TAG, MAX_INPUT_CHARS, RATE_LIMIT_PER_SESSION

if TYPE_CHECKING:
    from src.retrieval import RetrievedChunk
    from src.schemas import Assessment

INJECTION_THRESHOLD = 2
UNCITED_RISK_LEVELS = {"risque_minimal", "indetermine"}  # niveaux admis sans citation
RATE_LIMIT_KEY = "assessments_count"
TOPIC_MAX_TOKENS = 100

# Toute balise ouvrante ou fermante qui imite un délimiteur du prompt (espaces et casse tolérés)
_DELIMITER = re.compile(rf"<\s*/?\s*({DESCRIPTION_TAG}|extraits?|system)\b[^>]*>", re.IGNORECASE)

# (motif, poids) appliqués au texte normalisé : minuscules, sans accents.
# Poids 2 = injection quasi certaine à lui seul ; poids 1 = indice qui doit se cumuler.
INJECTION_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\b(ignore|oublie|ne tiens pas compte d)\w*\s+(\w+\s+){0,4}(instructions?|consignes?|regles?|prompt)"), 2),
    (re.compile(r"\b(ignore|disregard|forget)\s+(\w+\s+){0,3}(instructions?|rules|prompts?|guidelines)"), 2),
    (re.compile(r"\b(tu es|vous etes|tu deviens) (maintenant|desormais|a present)\b"), 2),
    (re.compile(r"\b(you are now|from now on you|act as|pretend to be|fais semblant|joue le role)\b"), 2),
    (re.compile(r"\b(system prompt|prompt systeme|instructions? (du )?systeme|message systeme)\b"), 2),
    (re.compile(r"\b(revele|affiche|montre|repete|donne)\w*\s+(\w+\s+){0,3}(prompt|instructions|consignes)"), 2),
    (re.compile(r"\b(classe|classifie|qualifie|categorise)\w*\s+(ce|cet|le|mon|notre)\s+(systeme|outil|logiciel|produit)\s+(comme|en)\b"), 2),
    (re.compile(r"\bclassify\s+(this|the|my|our)\s+(system|tool|product)\s+as\b"), 2),
    (re.compile(r"\b(risk_level|operator_role|missing_info)\b"), 2),
    (re.compile(r"\b(nouvelles? (instructions?|consignes?)|new instructions)\b"), 1),
    (re.compile(r"\b(reponds|answer|respond|output)\w*\s+(uniquement|seulement|only)\b"), 1),
    (re.compile(r"\b(jailbreak|developer mode|mode developpeur)\b"), 1),
    (re.compile(r"\b(haut_risque|risque_limite|risque_minimal|hors_champ)\b"), 1),  # valeurs JSON internes
    (re.compile(rf"<\s*/?\s*({DESCRIPTION_TAG}|system|extrait)"), 1),
]

InputCode = Literal["ok", "empty", "too_long", "injection", "off_topic"]

REFUSAL_MESSAGES: dict[InputCode, str] = {
    "empty": "La description est vide. Décrivez le système d'IA à évaluer.",
    "too_long": f"La description dépasse {MAX_INPUT_CHARS} caractères. Résumez-la en gardant l'essentiel.",
    "injection": (
        "La description contient des instructions adressées à l'assistant (changement de rôle, niveau de risque "
        "imposé…). Elle a été refusée : décrivez uniquement le système d'IA."
    ),
    "off_topic": (
        "Cette description ne semble pas décrire un système d'IA. Précisez ce que fait le système, "
        "pour qui et à partir de quelles données."
    ),
}


@dataclass(frozen=True)
class InputCheck:
    """Résultat du filtre d'entrée."""

    code: InputCode
    score: int = 0
    matches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.code == "ok"

    @property
    def message(self) -> str | None:
        """Message affichable à l'utilisateur en cas de refus."""
        return REFUSAL_MESSAGES.get(self.code)


def escape_delimiters(text: str) -> str:
    """Neutralise les balises de délimitation présentes dans l'entrée utilisateur."""
    return _DELIMITER.sub(lambda m: m.group(0).replace("<", "&lt;").replace(">", "&gt;"), text)


def normalize_for_matching(text: str) -> str:
    """Minuscules, sans accents, apostrophes et espaces uniformisés."""
    text = unicodedata.normalize("NFKD", text.replace("’", "'"))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", text)


def injection_score(text: str) -> tuple[int, list[str]]:
    """Score d'injection (somme des poids des motifs trouvés) et extraits correspondants."""
    normalized = normalize_for_matching(text)
    score, matches = 0, []
    for pattern, weight in INJECTION_PATTERNS:
        found = pattern.search(normalized)
        if found:
            score += weight
            matches.append(found.group(0))
    return score, matches


def check_input(description: str) -> InputCheck:
    """Contrôles sans LLM : vide, longueur, injection."""
    if not description.strip():
        return InputCheck("empty")
    if len(description) > MAX_INPUT_CHARS:
        return InputCheck("too_long")
    score, matches = injection_score(description)
    if score >= INJECTION_THRESHOLD:
        return InputCheck("injection", score, matches)
    return InputCheck("ok", score, matches)


def check_topic(description: str) -> InputCheck:
    """Vérification LLM courte : la description parle-t-elle d'un système d'IA ?"""
    from src.generation import ask_model  # import local : generation -> prompts -> security
    from src.prompts import TOPIC_SYSTEM, delimited
    from src.schemas import TopicCheck

    result = ask_model(TOPIC_SYSTEM, delimited(description), TopicCheck, max_tokens=TOPIC_MAX_TOKENS)
    return InputCheck("ok") if result.is_ai_system else InputCheck("off_topic", matches=[result.reason])


def invalid_citations(assessment: Assessment, results: list[RetrievedChunk]) -> set[str]:
    """Articles cités (citations et obligations) absents des chunks récupérés."""
    retrieved = {r.chunk.article_id for r in results}
    return assessment.cited_article_ids() - retrieved


def validate_citations(assessment: Assessment, results: list[RetrievedChunk]) -> str | None:
    """None si les citations sont présentes et justifiées, sinon un message d'erreur pour le retry.

    Toute conclusion positive (interdit, haut risque, risque limité, hors champ) doit citer au moins un article ;
    « risque_minimal » et « indetermine » se justifient par l'absence d'article applicable.
    """
    if assessment.risk_level not in UNCITED_RISK_LEVELS and not assessment.citations:
        return "aucune citation : toute conclusion doit être justifiée par au moins un article des extraits"
    invalid = invalid_citations(assessment, results)
    if not invalid:
        return None
    allowed = sorted({r.chunk.article_id for r in results})
    return f"articles cités absents des extraits : {sorted(invalid)}. Articles autorisés : {allowed}"


def rate_limit_reached(state: MutableMapping, limit: int = RATE_LIMIT_PER_SESSION) -> bool:
    """Vrai si la session a déjà consommé ses évaluations (state = st.session_state)."""
    return state.get(RATE_LIMIT_KEY, 0) >= limit


def record_assessment(state: MutableMapping) -> int:
    """Comptabilise une évaluation et renvoie le nombre restant."""
    state[RATE_LIMIT_KEY] = state.get(RATE_LIMIT_KEY, 0) + 1
    return max(RATE_LIMIT_PER_SESSION - state[RATE_LIMIT_KEY], 0)
