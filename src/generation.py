"""Appel du LLM (SDK openai, URL configurable) et parsing de la sortie JSON."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import TYPE_CHECKING

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from src.config import LLM_MAX_TOKENS, LLM_TEMPERATURE, LLM_TIMEOUT_S, settings
from src.prompts import ASSESSMENT_SYSTEM, assessment_user_prompt
from src.schemas import Assessment

if TYPE_CHECKING:
    from src.retrieval import RetrievedChunk

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class GenerationError(RuntimeError):
    """Échec de l'appel LLM ou réponse inexploitable (message sans donnée sensible)."""


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    """Client compatible OpenAI pointant vers LLM_BASE_URL."""
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        timeout=LLM_TIMEOUT_S,
        max_retries=2,
    )


def chat_json(system: str, user: str) -> str:
    """Appel LLM en mode JSON, température 0 ; renvoie le texte brut de la réponse."""
    try:
        response = get_client().chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
    except OpenAIError as exc:
        raise GenerationError(f"Appel LLM échoué ({type(exc).__name__})") from exc
    content = response.choices[0].message.content
    if not content:
        raise GenerationError("Réponse LLM vide")
    return content


def parse_json(raw: str) -> dict:
    """Décode le JSON renvoyé, en tolérant un éventuel bloc ```json```."""
    try:
        data = json.loads(_CODE_FENCE.sub("", raw.strip()))
    except json.JSONDecodeError as exc:
        raise GenerationError(f"JSON invalide : {exc.msg} (position {exc.pos})") from exc
    if not isinstance(data, dict):
        raise GenerationError("La réponse JSON n'est pas un objet")
    return data


def parse_assessment(raw: str) -> Assessment:
    """Valide la réponse du LLM contre le schéma Assessment."""
    try:
        return Assessment.model_validate(parse_json(raw))
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(map(str, e['loc']))} : {e['msg']}" for e in exc.errors()[:5])
        raise GenerationError(f"Format invalide : {errors}") from exc


def assess(description: str, results: list[RetrievedChunk], feedback: str | None = None) -> Assessment:
    """Évalue la description à partir des chunks récupérés ; `feedback` sert au retry."""
    raw = chat_json(ASSESSMENT_SYSTEM, assessment_user_prompt(description, results, feedback))
    return parse_assessment(raw)
