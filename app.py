"""Interface Streamlit.

Usage : streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from src import pipeline
from src.clarification import with_answers
from src.config import MAX_INPUT_CHARS, RATE_LIMIT_PER_SESSION, settings
from src.embeddings import load_model
from src.pipeline import PipelineResult
from src.retrieval import IndexNotReadyError, RetrievedChunk, get_collection
from src.schemas import Assessment
from src.security import rate_limit_reached, record_assessment

RISK_DISPLAY = {
    "interdit": ("Pratique interdite", st.error),
    "haut_risque": ("Système à haut risque", st.warning),
    "risque_limite": ("Risque limité (obligations de transparence)", st.info),
    "risque_minimal": ("Risque minimal", st.success),
    "hors_champ": ("Hors du champ de l'AI Act", st.info),
    "indetermine": ("Indéterminé : informations insuffisantes", st.info),
}
ROLE_LABELS = {
    "fournisseur": "Fournisseur",
    "deployeur": "Déployeur",
    "les_deux": "Fournisseur et déployeur",
    "inconnu": "Rôle non déterminé",
}
EXAMPLES = {
    "": "",
    "Tri automatique de CV": (
        "Notre start-up développe un logiciel SaaS qui analyse automatiquement les CV reçus par les entreprises "
        "clientes, attribue un score à chaque candidat et écarte ceux dont le score est inférieur à un seuil, "
        "sans revue humaine."
    ),
    "Chatbot de service client": (
        "Notre site e-commerce utilise un chatbot basé sur un modèle de langage acheté à un éditeur, qui répond aux "
        "questions des clients sur leurs commandes et les retours, sans prendre de décision à leur sujet."
    ),
    "Notation sociale municipale": (
        "Une municipalité veut déployer un système d'IA qui attribue à chaque habitant un score de civisme à partir "
        "de ses amendes et de ses publications sur les réseaux sociaux ; un score faible fait perdre la priorité "
        "pour l'accès aux logements sociaux."
    ),
    "Description trop vague": "Nous utilisons un outil d'IA pour améliorer nos processus internes.",
}


@st.cache_resource(show_spinner="Chargement du modèle d'embedding et de l'index…")
def warm_up() -> str | None:
    """Charge le modèle et vérifie l'index une seule fois par serveur ; renvoie un message d'erreur éventuel."""
    try:
        get_collection(settings.chunk_strategy)
    except IndexNotReadyError as exc:
        return str(exc)
    load_model(settings.embedding_model)
    return None


def run(description: str, clarify: bool = True) -> None:
    """Lance une évaluation si le quota de la session le permet, et mémorise le résultat."""
    if rate_limit_reached(st.session_state):
        st.session_state.result = PipelineResult(
            "blocked", message=f"Limite de {RATE_LIMIT_PER_SESSION} évaluations par session atteinte."
        )
        return
    record_assessment(st.session_state)
    with st.spinner("Analyse en cours (recherche dans le règlement puis évaluation)…"):
        st.session_state.result = pipeline.assess(description, clarify=clarify)
    st.session_state.evaluated_description = description


def article_link(article_id: str, sources: list[RetrievedChunk]) -> str:
    """Lien Markdown vers l'article sur EUR-Lex, à partir des extraits récupérés."""
    chunk = next((s.chunk for s in sources if s.chunk.article_id == article_id), None)
    return f"[{chunk.label}]({chunk.url})" if chunk else article_id


def render_assessment(assessment: Assessment, sources: list[RetrievedChunk]) -> None:
    """Niveau de risque, résumé, obligations, articles justificatifs et extraits utilisés."""
    label, box = RISK_DISPLAY[assessment.risk_level]
    box(f"**{label}** — {ROLE_LABELS[assessment.operator_role]}")
    st.write(assessment.summary)

    if assessment.obligations:
        st.subheader("Obligations")
        for obligation in assessment.obligations:
            links = ", ".join(article_link(a, sources) for a in obligation.article_ids)
            date = f" — applicable à partir du **{obligation.applies_from}**" if obligation.applies_from else ""
            st.markdown(f"- {obligation.description} ({links}){date}")

    if assessment.citations:
        st.subheader("Articles qui justifient l'évaluation")
        for citation in assessment.citations:
            paragraph = f", §{citation.paragraph}" if citation.paragraph else ""
            st.markdown(f"- {article_link(citation.article_id, sources)}{paragraph} : {citation.reason}")

    if assessment.missing_info:
        st.subheader("Informations à préciser")
        st.markdown("\n".join(f"- {info}" for info in assessment.missing_info))

    with st.expander(f"Extraits du règlement utilisés ({len(sources)})"):
        for source in sources:
            st.markdown(f"**{source.chunk.chunk_id}** · similarité {source.score:.2f} · [EUR-Lex]({source.chunk.url})")
            st.caption(source.chunk.text)


def render_clarification(result: PipelineResult) -> None:
    """Questions de clarification ; les réponses complètent la description avant une nouvelle évaluation."""
    st.info("Quelques informations manquent pour évaluer ce système de façon fiable.")
    with st.form("clarification"):
        answers = {q: st.text_input(q, key=f"answer_{i}") for i, q in enumerate(result.questions)}
        submitted = st.form_submit_button("Évaluer avec ces précisions", type="primary")
    if submitted:
        run(with_answers(st.session_state.evaluated_description, answers), clarify=False)
        st.rerun()
    if st.button("Évaluer sans préciser"):
        run(st.session_state.evaluated_description, clarify=False)
        st.rerun()


def render_result(result: PipelineResult) -> None:
    """Aiguillage selon le statut du pipeline."""
    if result.status == "ok":
        render_assessment(result.assessment, result.sources)
    elif result.status == "clarification":
        render_clarification(result)
    elif result.status == "blocked":
        st.warning(result.message)
    else:
        st.error(result.message)


def sidebar() -> None:
    used = st.session_state.get("assessments_count", 0)
    st.sidebar.header("À propos")
    st.sidebar.markdown(
        "Assistant RAG qui évalue un système d'IA au regard du **règlement (UE) 2024/1689 (AI Act)**, "
        "version consolidée au 27/07/2026, et cite les articles exacts qui justifient chaque affirmation."
    )
    st.sidebar.metric("Évaluations restantes", max(RATE_LIMIT_PER_SESSION - used, 0))
    st.sidebar.caption(
        f"LLM : `{settings.llm_model}` · embeddings : `{settings.embedding_model}` · "
        f"chunking : `{settings.chunk_strategy}`"
    )
    st.sidebar.caption("Outil d'aide à l'analyse : ne constitue pas un avis juridique.")


def main() -> None:
    st.set_page_config(page_title="Assistant AI Act", page_icon="⚖️", layout="wide")
    st.title("Assistant de conformité AI Act")
    sidebar()
    if error := warm_up():
        st.error(error)
        st.stop()

    example = st.selectbox("Exemple (facultatif)", list(EXAMPLES), format_func=lambda k: k or "—")
    with st.form("description_form"):
        description = st.text_area(
            "Décrivez votre système d'IA : ce qu'il fait, pour qui, sur quelles données, quelles décisions il prend.",
            value=EXAMPLES[example],
            height=180,
            max_chars=MAX_INPUT_CHARS,
        )
        submitted = st.form_submit_button("Évaluer", type="primary")
    if submitted:
        run(description)

    if result := st.session_state.get("result"):
        render_result(result)


main()
