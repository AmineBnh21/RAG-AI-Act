"""Tests de build_corpus (parsing EUR-Lex)."""

import re

import pytest

from scripts.build_corpus import build_corpus, format_label, normalize


@pytest.fixture(scope="module")
def corpus() -> dict[str, dict]:
    """Corpus complet extrait du HTML source, indexé par id."""
    return {entry["id"]: entry for entry in build_corpus()}


def articles(corpus: dict[str, dict]) -> list[dict]:
    return [e for e in corpus.values() if e["kind"] == "article"]


def all_texts(corpus: dict[str, dict]) -> list[str]:
    return [p["text"] for e in corpus.values() for p in e["paragraphs"]]


def test_normalize_espaces_et_apostrophes():
    assert normalize("  d’IA\xa0 \n  haut   risque ") == "d'IA haut risque"


def test_normalize_supprime_marqueur_de_suppression():
    assert normalize("avant ————— après") == "avant après"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Article\xa05", "Article 5"),
        ("Article\xa04bis", "Article 4 bis"),
        ("Article 75 quinquies", "Article 75 quinquies"),
        ("Article\xa0premier", "Article premier"),
    ],
)
def test_format_label(raw, expected):
    assert format_label(raw) == expected


def test_113_articles_numerotes_plus_bis(corpus):
    ids = {e["id"] for e in articles(corpus)}
    numbered = {i for i in ids if re.fullmatch(r"art_\d+", i)}
    assert numbered == {f"art_{n}" for n in range(1, 114)}
    assert ids - numbered == {"art_4a", "art_60a", "art_75a", "art_75b", "art_75c", "art_75d"}


def test_14_annexes(corpus):
    annexes = [e for e in corpus.values() if e["kind"] == "annex"]
    assert len(annexes) == 14
    assert {"anx_I", "anx_III", "anx_XIV"} <= {e["id"] for e in annexes}


def test_aucun_bruit_dans_le_texte(corpus):
    for text in all_texts(corpus):
        assert "▼" not in text
        assert "—————" not in text
        assert "———" not in text
        assert "\xa0" not in text


def test_aucune_entree_vide(corpus):
    assert all(e["paragraphs"] for e in corpus.values())
    assert all(p["text"] for p in (p for e in corpus.values() for p in e["paragraphs"]))


def test_chaque_article_a_un_chapitre(corpus):
    assert all(e["chapter"] for e in articles(corpus))
    assert all(e["chapter"] is None for e in corpus.values() if e["kind"] == "annex")


def test_autres_annexes_en_un_bloc(corpus):
    others = [e for e in corpus.values() if e["kind"] == "annex" and e["id"] != "anx_III"]
    assert all(len(e["paragraphs"]) == 1 for e in others)


def test_article_5(corpus):
    art = corpus["art_5"]
    assert art["label"] == "Article 5"
    assert art["title"] == "Pratiques interdites en matière d'IA"
    assert art["chapter"] == "CHAPITRE II — PRATIQUES INTERDITES EN MATIÈRE D'IA"
    assert art["section"] is None
    assert art["url"].endswith("CELEX:02024R1689-20260727#art_5")
    assert {"1", "1 bis", "1 ter"} <= {p["num"] for p in art["paragraphs"]}


def test_points_de_liste_sur_une_ligne(corpus):
    text = corpus["art_5"]["paragraphs"][0]["text"]
    assert "\na) la mise sur le marché" in text
    assert "\nb bis) la mise sur le marché" in text


def test_labels_bis_ter(corpus):
    assert corpus["art_4a"]["label"] == "Article 4 bis"
    assert corpus["art_75b"]["label"] == "Article 75 ter"
    assert corpus["art_75d"]["label"] == "Article 75 quinquies"
    assert corpus["art_1"]["label"] == "Article premier"


def test_section_remplie(corpus):
    assert corpus["art_6"]["chapter"].startswith("CHAPITRE III")
    assert corpus["art_6"]["section"].startswith("SECTION 1 — Classification")


def test_paragraphes_cites_non_numerotes(corpus):
    """Les « «5. » des articles modificatifs ne sont pas de vrais paragraphes."""
    nums = [p["num"] for e in corpus.values() for p in e["paragraphs"] if p["num"]]
    assert not any(n.startswith("«") for n in nums)


def test_annexe_iii_decoupee_par_point(corpus):
    annex = corpus["anx_III"]
    assert annex["label"] == "Annexe III"
    assert annex["title"].startswith("Systèmes d'IA à haut risque")
    points = [p["num"] for p in annex["paragraphs"] if p["num"] is not None]
    assert points == [str(n) for n in range(1, 9)]
    assert annex["paragraphs"][1]["text"].startswith("1. Biométrie")
