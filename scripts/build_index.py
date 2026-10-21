"""articles.json -> chunks -> collections ChromaDB.

Usage : python -m scripts.build_index [--strategy article|fixed|all]
"""

from __future__ import annotations

import argparse
import time

import chromadb

from src.chunking import METADATA_FIELDS, Chunk, build_chunks, load_corpus
from src.config import STRATEGIES, ChunkStrategy, collection_name, settings
from src.embeddings import embed_passages
from src.retrieval import get_client

ADD_BATCH_SIZE = 256


def chunk_metadata(chunk: Chunk) -> dict[str, str]:
    """Métadonnées Chroma (pas de None autorisé : remplacé par une chaîne vide)."""
    data = chunk.to_dict()
    return {field: data[field] or "" for field in METADATA_FIELDS}


def build_collection(client: chromadb.ClientAPI, strategy: ChunkStrategy, corpus: list[dict]) -> int:
    """(Re)crée la collection d'une stratégie et y indexe tous les chunks."""
    name = collection_name(strategy)
    if name in {c.name for c in client.list_collections()}:
        client.delete_collection(name)
    collection = client.create_collection(
        name,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={"embedding_model": settings.embedding_model, "strategy": strategy},
    )
    chunks = build_chunks(corpus, strategy)
    embeddings = embed_passages([c.text for c in chunks])
    for start in range(0, len(chunks), ADD_BATCH_SIZE):
        batch = chunks[start : start + ADD_BATCH_SIZE]
        collection.add(
            ids=[c.chunk_id for c in batch],
            documents=[c.text for c in batch],
            metadatas=[chunk_metadata(c) for c in batch],
            embeddings=embeddings[start : start + ADD_BATCH_SIZE],
        )
    return collection.count()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Construit les index ChromaDB.")
    parser.add_argument("--strategy", choices=[*STRATEGIES, "all"], default="all")
    return parser.parse_args()


def main() -> None:
    """Indexe la ou les stratégies demandées."""
    args = parse_args()
    strategies = STRATEGIES if args.strategy == "all" else (args.strategy,)
    corpus = load_corpus()
    client = get_client()
    print(f"Modèle d'embedding : {settings.embedding_model}")
    for strategy in strategies:
        start = time.perf_counter()
        count = build_collection(client, strategy, corpus)
        print(f"{collection_name(strategy)} : {count} chunks indexés en {time.perf_counter() - start:.0f} s")


if __name__ == "__main__":
    main()
