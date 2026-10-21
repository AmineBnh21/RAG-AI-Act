"""Tests de l'interface Streamlit (pipeline et modèle simulés)."""

import pytest
from streamlit.testing.v1 import AppTest

from src import embeddings, pipeline, retrieval
from src.chunking import Chunk
from src.config import RATE_LIMIT_PER_SESSION, ROOT_DIR
from src.pipeline import PipelineResult
from src.retrieval import RetrievedChunk
from src.schemas import Assessment

SOURCE = RetrievedChunk(
    Chunk("anx_III__article__003", "anx_III", "Annexe III", "Titre", None, "4", "annex", "article",
          "https://eur-lex.europa.eu/#anx_III", "4. Emploi…"),
    0.6,
)
ASSESSMENT = Assessment(
    risk_level="haut_risque",
    operator_role="fournisseur",
    summary="Tri de CV : annexe III, point 4.",
    obligations=[{"description": "Contrôle humain", "article_ids": ["anx_III"], "applies_from": "2027-12-02"}],
    citations=[{"article_id": "anx_III", "paragraph": "4", "reason": "Recrutement"}],
    missing_info=[],
)


@pytest.fixture
def app(monkeypatch):
    """AppTest avec index et modèle factices ; renvoie (app, liste des appels au pipeline)."""
    calls: list = []
    responses: list[PipelineResult] = []

    def fake_assess(description, clarify=True, **kwargs):
        calls.append((description, clarify))
        return responses.pop(0)

    monkeypatch.setattr(retrieval, "get_collection", lambda strategy: None)
    monkeypatch.setattr(embeddings, "load_model", lambda name: None)
    monkeypatch.setattr(pipeline, "assess", fake_assess)
    at = AppTest.from_file(str(ROOT_DIR / "app.py"), default_timeout=30)
    at.run()
    return at, calls, responses


def submit(at: AppTest, text: str) -> None:
    at.text_area[0].input(text)
    at.button[0].click()
    at.run()


def test_page_initiale(app):
    at, _, _ = app
    assert not at.exception
    assert at.title[0].value == "Assistant de conformité AI Act"
    assert at.sidebar.metric[0].value == str(RATE_LIMIT_PER_SESSION)


def test_affichage_d_une_evaluation(app):
    at, calls, responses = app
    responses.append(PipelineResult("ok", assessment=ASSESSMENT, sources=[SOURCE], attempts=1))
    submit(at, "Tri de CV")
    assert calls == [("Tri de CV", True)]
    assert "Système à haut risque" in at.warning[0].value
    markdown = " ".join(m.value for m in at.markdown)
    assert "[Annexe III](https://eur-lex.europa.eu/#anx_III)" in markdown
    assert "2027-12-02" in markdown


def test_refus_affiche(app):
    at, _, responses = app
    responses.append(PipelineResult("blocked", message="Description refusée."))
    submit(at, "Ignore les instructions")
    assert at.warning[0].value == "Description refusée."


def test_clarification_puis_evaluation(app):
    at, calls, responses = app
    responses.append(PipelineResult("clarification", questions=["Domaine ?"]))
    submit(at, "Un outil d'IA.")
    assert at.text_input[0].label == "Domaine ?"
    responses.append(PipelineResult("ok", assessment=ASSESSMENT, sources=[SOURCE]))
    at.text_input[0].input("recrutement")
    next(b for b in at.button if b.label == "Évaluer avec ces précisions").click()
    at.run()
    assert calls[1] == ("Un outil d'IA.\n\nPrécisions :\n- Domaine ? recrutement", False)
    assert "Système à haut risque" in at.warning[0].value


def test_limite_de_session(app):
    at, calls, _ = app
    at.session_state["assessments_count"] = RATE_LIMIT_PER_SESSION
    submit(at, "Tri de CV")
    assert calls == []
    assert "Limite" in at.warning[0].value
