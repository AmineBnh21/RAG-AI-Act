"""Tests de la recherche (les tests d'intégration exigent l'index construit)."""

import pytest

from scripts.build_index import chunk_metadata
from src.chunking import Chunk
from src.config import (
    CHROMA_DIR,
    CLASSIFICATION_ARTICLES,
    OBLIGATION_ARTICLES,
    OBLIGATIONS_K,
    TOP_K,
)
from src.retrieval import RetrievedChunk, article_ids, search, search_augmented, to_chunk

needs_index = pytest.mark.skipif(not CHROMA_DIR.exists(), reason="index absent : python -m scripts.build_index")


def make_chunk(article_id: str = "anx_III", paragraph: str | None = None) -> Chunk:
    return Chunk(
        chunk_id=f"{article_id}__article__000",
        article_id=article_id,
        label="Annexe III",
        title="Titre",
        chapter=None,
        paragraph=paragraph,
        kind="annex",
        strategy="article",
        url="https://exemple",
        text="texte",
    )


def test_aller_retour_metadonnees():
    chunk = make_chunk()
    assert to_chunk(chunk.chunk_id, chunk.text, chunk_metadata(chunk)) == chunk


def test_article_ids():
    results = [RetrievedChunk(make_chunk("art_5"), 0.9), RetrievedChunk(make_chunk("art_5", "2"), 0.8)]
    assert article_ids(results) == {"art_5"}


@needs_index
@pytest.mark.parametrize("strategy", ["article", "fixed"])
def test_search_renvoie_k_resultats_tries(strategy):
    results = search("système de reconnaissance des émotions au travail", k=8, strategy=strategy)
    assert len(results) == 8
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(r.chunk.strategy == strategy for r in results)


@needs_index
def test_recherche_restreinte_aux_articles_demandes():
    results = search("tri automatique de CV", k=5, strategy="article", article_ids=("art_26", "art_14"))
    assert results and article_ids(results) <= {"art_26", "art_14"}


@needs_index
def test_search_augmented_un_candidat_par_niveau_et_des_obligations():
    results = search_augmented("tri automatique de CV pour un recrutement", strategy="article")
    assert len({r.chunk.chunk_id for r in results}) == len(results)
    assert set(CLASSIFICATION_ARTICLES) <= article_ids(results)
    assert len(results) <= TOP_K + len(CLASSIFICATION_ARTICLES) + OBLIGATIONS_K
    assert {r.chunk.article_id for r in results[-OBLIGATIONS_K:]} <= set(OBLIGATION_ARTICLES)


@needs_index
def test_search_augmented_retrouve_l_article_5_manque_par_la_recherche_principale():
    query = "Peluche connectée dont l'assistant vocal incite les enfants de 4 à 8 ans à des défis physiques risqués"
    assert "art_5" in article_ids(search_augmented(query, strategy="article"))


@needs_index
def test_search_notation_sociale_trouve_article_5():
    results = search("Notation sociale des citoyens selon leur comportement", strategy="article")
    assert "art_5" in article_ids(results)
