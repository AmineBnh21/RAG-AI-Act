"""Tests des stratégies de chunking."""

import pytest

from src.chunking import (
    build_chunks,
    chunk_by_article,
    chunk_fixed,
    header,
    load_corpus,
    merge_short,
    sliding_windows,
    split_long,
    top_level_point,
)
from src.config import FIXED_CHUNK_OVERLAP, FIXED_CHUNK_SIZE, MAX_PARAGRAPH_CHARS, MIN_PARAGRAPH_CHARS


def entry(paragraphs: list[dict], kind: str = "article", title: str | None = "Titre") -> dict:
    """Entrée de corpus minimale pour les tests unitaires."""
    return {
        "id": "art_99" if kind == "article" else "anx_IX",
        "kind": kind,
        "label": "Article 99" if kind == "article" else "Annexe IX",
        "title": title,
        "chapter": "CHAPITRE X" if kind == "article" else None,
        "section": None,
        "url": "https://exemple#art_99",
        "paragraphs": paragraphs,
    }


@pytest.fixture(scope="module")
def corpus() -> list[dict]:
    return load_corpus()


# --- Fusion des paragraphes courts ---------------------------------------------------------


def test_paragraphe_court_fusionne_avec_le_suivant():
    paras = [{"num": "1", "text": "court"}, {"num": "2", "text": "x" * 300}]
    assert merge_short(paras) == [{"nums": ["1", "2"], "text": "court\n" + "x" * 300}]


def test_dernier_paragraphe_court_rejoint_le_precedent():
    paras = [{"num": "1", "text": "x" * 300}, {"num": "2", "text": "court"}]
    assert merge_short(paras) == [{"nums": ["1", "2"], "text": "x" * 300 + "\ncourt"}]


def test_paragraphes_longs_inchanges():
    paras = [{"num": "1", "text": "x" * 300}, {"num": None, "text": "y" * 300}]
    assert [m["nums"] for m in merge_short(paras)] == [["1"], []]


# --- Découpage des paragraphes longs -------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "previous", "expected"),
    [
        ("a) texte", None, "a"),
        ("b bis) texte", "b", "b"),
        ("12) texte", "11", "12"),
        ("ii) texte", "c", None),
        ("i) texte", "c", None),
        ("i) texte", "h", "i"),
        ("texte sans point", "a", None),
    ],
)
def test_top_level_point(line, previous, expected):
    assert top_level_point(line, previous) == expected


def test_texte_court_non_decoupe():
    assert split_long("a) court") == ["a) court"]


def test_decoupe_sur_les_points_avec_introduction_repetee():
    lead = "Les pratiques suivantes sont interdites:"
    points = [f"{c}) " + c * 900 for c in "abc"]
    parts = split_long("\n".join([lead, *points]), max_chars=2000)
    assert len(parts) == 2
    assert all(p.startswith(lead + "\n") for p in parts)
    assert all(len(p) <= 2000 for p in parts)
    assert parts[1].endswith(points[2])


def test_sous_points_romains_restent_avec_leur_parent():
    lines = ["Intro:", "a) " + "a" * 800, "b) " + "b" * 300, "i) " + "i" * 300, "ii) " + "j" * 300, "c) " + "c" * 800]
    parts = split_long("\n".join(lines), max_chars=2000)
    owner = next(p for p in parts if "\nb) " in p)
    assert "\ni) " in owner and "\nii) " in owner


# --- En-têtes ------------------------------------------------------------------------------


def test_header_article():
    assert header(entry([]), ["1", "1 bis"]) == "Article 99 — Titre — §1, 1 bis"


def test_header_annexe_et_sans_titre():
    assert header(entry([], kind="annex"), ["3"]) == "Annexe IX — Titre — point 3"
    assert header(entry([], title=None), []) == "Article 99"


# --- Stratégie fixed -----------------------------------------------------------------------


def test_fenetres_glissantes():
    text = "".join(chr(ord("a") + i % 26) for i in range(2000))
    windows = sliding_windows(text)
    assert all(len(w) <= FIXED_CHUNK_SIZE for w in windows)
    assert windows[1][:FIXED_CHUNK_OVERLAP] == windows[0][-FIXED_CHUNK_OVERLAP:]
    assert windows[-1].endswith(text[-50:])


def test_texte_court_une_seule_fenetre():
    assert sliding_windows("abc") == ["abc"]


def test_chunk_fixed_sans_entete():
    chunks = chunk_fixed(entry([{"num": "1", "text": "x" * 1000}]))
    assert chunks[0].text.startswith("1. xxx")
    assert all(c.paragraph is None and c.strategy == "fixed" for c in chunks)


def test_chunk_by_article_prefixe():
    chunks = chunk_by_article(entry([{"num": "1", "text": "x" * 300}]))
    assert chunks[0].text == "Article 99 — Titre — §1 : " + "x" * 300
    assert chunks[0].paragraph == "1"
    assert chunks[0].chunk_id == "art_99__article__000"


# --- Corpus réel ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ["article", "fixed"])
def test_ids_uniques_et_corpus_couvert(corpus, strategy):
    chunks = build_chunks(corpus, strategy)
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert {c.article_id for c in chunks} == {e["id"] for e in corpus}


def test_tailles_strategie_article(corpus):
    by_id = {e["id"]: e for e in corpus}
    for chunk in build_chunks(corpus, "article"):
        nums = chunk.paragraph.split(", ") if chunk.paragraph else []
        head = header(by_id[chunk.article_id], nums)
        assert chunk.text.startswith(head + " : ")
        body = chunk.text[len(head) + 3 :]
        whole = "\n".join(p["text"] for p in by_id[chunk.article_id]["paragraphs"])
        assert min(MIN_PARAGRAPH_CHARS, len(whole)) <= len(body) <= MAX_PARAGRAPH_CHARS


def test_tailles_strategie_fixed(corpus):
    assert all(len(c.text) <= FIXED_CHUNK_SIZE for c in build_chunks(corpus, "fixed"))


def test_annexe_iii_un_chunk_par_point(corpus):
    annex = next(e for e in corpus if e["id"] == "anx_III")
    assert [c.paragraph for c in chunk_by_article(annex)] == [str(n) for n in range(1, 9)]
