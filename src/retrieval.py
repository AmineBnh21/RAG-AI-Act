"""Recherche des top-k chunks dans ChromaDB.

Usage rapide : python -m src.retrieval "description du système"
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache

import chromadb
from chromadb.api.models.Collection import Collection

from src.chunking import METADATA_FIELDS, Chunk
from src.config import (
    CHROMA_DIR,
    CLASSIFICATION_ARTICLES,
    CLASSIFICATION_K,
    OBLIGATION_ARTICLES,
    OBLIGATIONS_K,
    TOP_K,
    ChunkStrategy,
    collection_name,
    settings,
)
from src.embeddings import embed_query


class IndexNotReadyError(RuntimeError):
    """Index absent ou construit avec un autre modèle d'embedding."""


@dataclass(frozen=True)
class RetrievedChunk:
    """Chunk renvoyé par la recherche, avec son score de similarité cosinus (1 = identique)."""

    chunk: Chunk
    score: float


@lru_cache(maxsize=1)
def get_client() -> chromadb.ClientAPI:
    """Client Chroma persistant dans chroma_db/."""
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


@lru_cache(maxsize=2)
def get_collection(strategy: ChunkStrategy) -> Collection:
    """Collection d'une stratégie, après vérification du modèle d'embedding."""
    name = collection_name(strategy)
    try:
        collection = get_client().get_collection(name)
    except Exception as exc:  # Chroma lève des types différents selon les versions
        raise IndexNotReadyError(f"Collection « {name} » introuvable : lance python -m scripts.build_index") from exc
    indexed_model = (collection.metadata or {}).get("embedding_model")
    if indexed_model != settings.embedding_model:
        raise IndexNotReadyError(
            f"« {name} » a été indexée avec {indexed_model}, mais EMBEDDING_MODEL={settings.embedding_model} : "
            "relance python -m scripts.build_index"
        )
    return collection


def to_chunk(chunk_id: str, text: str, metadata: dict) -> Chunk:
    """Reconstruit un Chunk depuis Chroma (les chaînes vides redeviennent None)."""
    fields = {field: metadata.get(field) or None for field in METADATA_FIELDS}
    return Chunk(chunk_id=chunk_id, text=text, **fields)


def search(
    query: str,
    k: int = TOP_K,
    strategy: ChunkStrategy | None = None,
    article_ids: tuple[str, ...] | None = None,
) -> list[RetrievedChunk]:
    """Top-k chunks les plus proches de la requête ; `article_ids` restreint la recherche à ces articles."""
    collection = get_collection(strategy or settings.chunk_strategy)
    result = collection.query(
        query_embeddings=[embed_query(query)],
        n_results=k,
        where={"article_id": {"$in": list(article_ids)}} if article_ids else None,
        include=["documents", "metadatas", "distances"],
    )
    rows = zip(result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0])
    return [RetrievedChunk(to_chunk(cid, doc, meta), 1 - dist) for cid, doc, meta, dist in rows]


AUGMENTATIONS: tuple[tuple[tuple[str, ...], int], ...] = (
    (CLASSIFICATION_ARTICLES, CLASSIFICATION_K),
    (OBLIGATION_ARTICLES, OBLIGATIONS_K),
)


def search_augmented(
    query: str,
    k: int = TOP_K,
    strategy: ChunkStrategy | None = None,
    augmentations: tuple[tuple[tuple[str, ...], int], ...] = AUGMENTATIONS,
) -> list[RetrievedChunk]:
    """Recherche principale, puis pour chaque (articles, n) les n meilleurs chunks de ces articles, sans doublon.

    Garantit que le LLM voit les candidats de classification et d'obligations les plus proches,
    même quand la recherche principale ne les remonte pas.
    """
    results = search(query, k, strategy)
    for article_ids, n in augmentations:
        seen = {r.chunk.chunk_id for r in results}
        extra = search(query, n + len(results), strategy, article_ids)
        results += [r for r in extra if r.chunk.chunk_id not in seen][:n]
    return results


def article_ids(results: list[RetrievedChunk]) -> set[str]:
    """Identifiants d'articles présents dans les résultats (pour valider les citations)."""
    return {r.chunk.article_id for r in results}


if __name__ == "__main__":
    for r in search(" ".join(sys.argv[1:]) or "notation sociale des citoyens"):
        print(f"{r.score:.3f}  {r.chunk.chunk_id:<28} {r.chunk.text[:90]}")
