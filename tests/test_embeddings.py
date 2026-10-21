"""Tests des préfixes e5 et des métadonnées Chroma (sans charger le modèle)."""

import pytest

from scripts.build_index import chunk_metadata
from src.chunking import Chunk
from src.config import collection_name
from src.embeddings import needs_prefix, with_prefix


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("intfloat/multilingual-e5-small", True),
        ("intfloat/multilingual-e5-large-instruct", True),
        ("BAAI/bge-m3", False),
    ],
)
def test_needs_prefix(model, expected):
    assert needs_prefix(model) is expected


def test_prefixes_e5():
    model = "intfloat/multilingual-e5-small"
    assert with_prefix(["texte"], "query", model) == ["query: texte"]
    assert with_prefix(["texte"], "passage", model) == ["passage: texte"]


def test_pas_de_prefixe_pour_bge():
    assert with_prefix(["texte"], "query", "BAAI/bge-m3") == ["texte"]


def test_noms_de_collection():
    assert collection_name("article") == "ai_act_article"
    assert collection_name("fixed") == "ai_act_fixed"


def test_metadonnees_sans_none():
    chunk = Chunk(
        chunk_id="anx_III__article__000",
        article_id="anx_III",
        label="Annexe III",
        title="Titre",
        chapter=None,
        paragraph=None,
        kind="annex",
        strategy="article",
        url="https://exemple#anx_III",
        text="texte",
    )
    metadata = chunk_metadata(chunk)
    assert metadata["chapter"] == "" and metadata["paragraph"] == ""
    assert all(isinstance(v, str) for v in metadata.values())
