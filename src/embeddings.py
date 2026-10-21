"""Chargement du modèle sentence-transformers et calcul des embeddings (préfixes e5 gérés ici)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from sentence_transformers import SentenceTransformer

from src.config import EMBEDDING_BATCH_SIZE, settings

TextKind = Literal["query", "passage"]


def needs_prefix(model_name: str) -> bool:
    """Les modèles e5 attendent les préfixes « query: » / « passage: »."""
    return "e5" in model_name.lower().split("/")[-1]


def with_prefix(texts: list[str], kind: TextKind, model_name: str) -> list[str]:
    """Ajoute le préfixe e5 si le modèle l'exige, sinon renvoie les textes tels quels."""
    if not needs_prefix(model_name):
        return list(texts)
    return [f"{kind}: {text}" for text in texts]


@lru_cache(maxsize=2)
def load_model(model_name: str = settings.embedding_model) -> SentenceTransformer:
    """Charge le modèle une seule fois par processus."""
    return SentenceTransformer(model_name)


def embed(texts: list[str], kind: TextKind, model_name: str = settings.embedding_model) -> list[list[float]]:
    """Embeddings normalisés (similarité cosinus = produit scalaire)."""
    vectors = load_model(model_name).encode(
        with_prefix(texts, kind, model_name),
        batch_size=EMBEDDING_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > EMBEDDING_BATCH_SIZE,
    )
    return vectors.tolist()


def embed_passages(texts: list[str], model_name: str = settings.embedding_model) -> list[list[float]]:
    """Embeddings des chunks à indexer."""
    return embed(texts, "passage", model_name)


def embed_query(text: str, model_name: str = settings.embedding_model) -> list[float]:
    """Embedding d'une requête utilisateur."""
    return embed([text], "query", model_name)[0]
