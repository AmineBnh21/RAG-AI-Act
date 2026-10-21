"""Modèles Pydantic de sortie : Citation, Obligation, Assessment."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

RiskLevel = Literal["interdit", "haut_risque", "risque_limite", "risque_minimal", "hors_champ", "indetermine"]
OperatorRole = Literal["fournisseur", "deployeur", "les_deux", "inconnu"]

# « art_5 », « art_4a », « art_75d », « anx_III »
ArticleId = Annotated[str, StringConstraints(pattern=r"^(art_\d+[a-d]?|anx_[IVX]+)$")]


class Citation(BaseModel):
    """Article ou annexe qui justifie l'évaluation."""

    article_id: ArticleId
    paragraph: str | None = None
    reason: str  # pourquoi cet article s'applique


class Obligation(BaseModel):
    """Obligation applicable, avec ses articles sources et sa date d'application."""

    description: str
    article_ids: list[ArticleId] = Field(min_length=1)
    applies_from: str | None = None  # date ISO si connue (ex. "2027-12-02")

    @field_validator("applies_from")
    @classmethod
    def check_date(cls, value: str | None) -> str | None:
        """La date, si présente, doit être au format ISO AAAA-MM-JJ."""
        if value is not None:
            date.fromisoformat(value)
        return value


class Assessment(BaseModel):
    """Évaluation complète renvoyée par le LLM."""

    risk_level: RiskLevel
    operator_role: OperatorRole
    summary: str
    obligations: list[Obligation]
    citations: list[Citation]
    missing_info: list[str]

    def cited_article_ids(self) -> set[str]:
        """Tous les articles cités, dans les citations et dans les obligations."""
        return {c.article_id for c in self.citations} | {i for o in self.obligations for i in o.article_ids}


class TopicCheck(BaseModel):
    """Réponse de la vérification « la description décrit-elle un système d'IA ? »."""

    is_ai_system: bool
    reason: str


KeyInfo = Literal["domaine", "utilisateurs", "personnes_concernees", "biometrie", "decisions_automatisees", "role"]


class KeyInfoExtraction(BaseModel):
    """Réponse de la clarification : chaque info clé extraite de la description, ou None si absente."""

    domaine: str | None = None
    utilisateurs: str | None = None
    personnes_concernees: str | None = None
    biometrie: str | None = None
    decisions_automatisees: str | None = None
    role: str | None = None

    def missing(self) -> list[KeyInfo]:
        """Infos clés non trouvées (None ou chaîne vide)."""
        return [key for key, value in self.model_dump().items() if not (value or "").strip()]
