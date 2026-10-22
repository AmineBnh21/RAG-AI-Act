"""Prépare dist/hf_space/ : le dossier à envoyer sur un Hugging Face Space (SDK Docker).

Usage : python -m scripts.export_space                      # dossier complet du Space
        python -m scripts.export_space --index-only deploy\chroma_db   # index seul (Streamlit Cloud)
Copie uniquement ce dont l'application a besoin et exporte un index Chroma propre
contenant la seule collection de la stratégie active (pas de ré-indexation sur le Space).
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import chromadb

from src.config import ROOT_DIR, collection_name, settings
from src.retrieval import get_collection

DIST_DIR = ROOT_DIR / "dist" / "hf_space"
FILES = ["app.py", "requirements.txt", "Dockerfile", ".dockerignore"]
DIRS = ["src"]
SPACE_README = ROOT_DIR / "deploy" / "space_README.md"
EXPORT_BATCH_SIZE = 256


def copy_sources() -> None:
    """Copie le code de l'application et le README du Space."""
    for name in FILES:
        shutil.copy2(ROOT_DIR / name, DIST_DIR / name)
    for name in DIRS:
        shutil.copytree(ROOT_DIR / name, DIST_DIR / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(SPACE_README, DIST_DIR / "README.md")


def export_index(target_dir: Path) -> int:
    """Recopie la collection active (embeddings compris) dans un nouvel index Chroma."""
    source = get_collection(settings.chunk_strategy)  # vérifie aussi le modèle d'embedding
    data = source.get(include=["embeddings", "documents", "metadatas"])
    target = chromadb.PersistentClient(path=str(target_dir)).create_collection(
        collection_name(settings.chunk_strategy),
        configuration={"hnsw": {"space": "cosine"}},
        metadata=source.metadata,
    )
    for start in range(0, len(data["ids"]), EXPORT_BATCH_SIZE):
        end = start + EXPORT_BATCH_SIZE
        target.add(
            ids=data["ids"][start:end],
            embeddings=data["embeddings"][start:end],
            documents=data["documents"][start:end],
            metadatas=data["metadatas"][start:end],
        )
    return target.count()


def reset_dir(path: Path) -> None:
    """Vide le dossier de sortie pour repartir d'un export propre."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-only", type=Path, help="exporter seulement l'index dans ce dossier")
    args = parser.parse_args()
    if args.index_only:
        target = args.index_only if args.index_only.is_absolute() else ROOT_DIR / args.index_only
        reset_dir(target)
        print(f"{target} prêt : {export_index(target)} chunks, modèle {settings.embedding_model}")
        return
    reset_dir(DIST_DIR)
    copy_sources()
    count = export_index(DIST_DIR / "chroma_db")
    print(f"{DIST_DIR} prêt : collection {collection_name(settings.chunk_strategy)} ({count} chunks), "
          f"modèle {settings.embedding_model}")


if __name__ == "__main__":
    main()
