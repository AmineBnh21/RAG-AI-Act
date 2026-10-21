"""Orchestration : assess(description) -> PipelineResult (contenant l'Assessment)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src import clarification, generation, retrieval, security
from src.config import MAX_RETRIES, TOP_K, ChunkStrategy
from src.generation import GenerationError, LLMUnavailableError
from src.retrieval import RetrievedChunk
from src.schemas import Assessment

Status = Literal["ok", "blocked", "clarification", "error"]

ERROR_UNAVAILABLE = "Le service d'analyse est momentanément indisponible. Réessayez dans quelques instants."
ERROR_UNRELIABLE = (
    "L'évaluation n'a pas pu être produite de façon fiable (réponse invalide ou citations non justifiées). "
    "Reformulez ou précisez la description."
)


@dataclass(frozen=True)
class PipelineResult:
    """Résultat renvoyé à l'interface et à l'évaluation."""

    status: Status
    assessment: Assessment | None = None
    message: str | None = None  # message utilisateur (refus, erreur)
    questions: list[str] = field(default_factory=list)
    sources: list[RetrievedChunk] = field(default_factory=list)
    attempts: int = 0
    blocked_by: str | None = None  # code du filtre (injection, off_topic…) ou dernière erreur interne


def screen(description: str) -> PipelineResult | None:
    """Filtre d'entrée : règles locales puis vérification LLM du sujet. None si la description passe.

    Une réponse mal formée du vérificateur de sujet laisse passer (le filtre d'injection a déjà tourné).
    """
    check = security.check_input(description)
    if check.ok:
        try:
            check = security.check_topic(description)
        except LLMUnavailableError:
            return PipelineResult("error", message=ERROR_UNAVAILABLE, blocked_by="topic_check")
        except GenerationError:
            return None
    if not check.ok:
        return PipelineResult("blocked", message=check.message, blocked_by=check.code)
    return None


def ask_clarification(description: str) -> PipelineResult | None:
    """Questions à poser si des infos critiques manquent ; None pour passer à l'évaluation."""
    try:
        needed = clarification.check(description)
    except LLMUnavailableError:
        return PipelineResult("error", message=ERROR_UNAVAILABLE, blocked_by="clarification")
    except GenerationError:
        return None
    return PipelineResult("clarification", questions=needed.questions) if needed.needed else None


def generate(description: str, sources: list[RetrievedChunk], defenses: bool) -> PipelineResult:
    """Génération + validation (format, citations) avec au plus MAX_RETRIES nouvel essai."""
    feedback: str | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            assessment = generation.assess(description, sources, feedback)
        except LLMUnavailableError as exc:
            return PipelineResult("error", message=ERROR_UNAVAILABLE, sources=sources, attempts=attempt, blocked_by=str(exc))
        except GenerationError as exc:
            feedback = str(exc)
            continue
        feedback = security.validate_citations(assessment, sources) if defenses else None
        if feedback is None:
            return PipelineResult("ok", assessment=assessment, sources=sources, attempts=attempt)
    return PipelineResult("error", message=ERROR_UNRELIABLE, sources=sources, attempts=attempt, blocked_by=feedback)


def assess(
    description: str,
    *,
    defenses: bool = True,
    clarify: bool = True,
    strategy: ChunkStrategy | None = None,
    k: int = TOP_K,
    obligations: bool = True,
) -> PipelineResult:
    """Pipeline complet.

    `defenses=False` désactive filtre d'entrée et validation des citations (éval) ;
    `obligations=False` supprime la recherche complémentaire dans les articles d'obligations.
    """
    if defenses and (refusal := screen(description)):
        return refusal
    if clarify and (questions := ask_clarification(description)):
        return questions
    if obligations:
        sources = retrieval.search_with_obligations(description, k=k, strategy=strategy)
    else:
        sources = retrieval.search(description, k=k, strategy=strategy)
    return generate(description, sources, defenses)
