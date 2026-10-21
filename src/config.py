"""Configuration centrale : lecture du .env, chemins et constantes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# Chemins
DATA_DIR = ROOT_DIR / "data"
SOURCE_HTML = DATA_DIR / "ai_act_fr_2026-07-27.html"
ARTICLES_JSON = DATA_DIR / "articles.json"
CHROMA_DIR = ROOT_DIR / "chroma_db"
EVAL_DIR = ROOT_DIR / "eval"
EVAL_RESULTS_DIR = EVAL_DIR / "results"

# Source EUR-Lex
EURLEX_BASE_URL = "https://eur-lex.europa.eu/legal-content/FR/TXT/HTML/?uri=CELEX:02024R1689-20260727"

# Chunking
MIN_PARAGRAPH_CHARS = 200
MAX_PARAGRAPH_CHARS = 2000
FIXED_CHUNK_SIZE = 800
FIXED_CHUNK_OVERLAP = 150
COLLECTION_PREFIX = "ai_act_"

# Retrieval et génération
TOP_K = 8
CLASSIFICATION_K = 4  # chunks supplémentaires tirés des seuls articles de classification
# Articles qui déterminent le niveau de risque : champ (2), interdictions (5), haut risque (6, annexes I et III),
# transparence (50).
CLASSIFICATION_ARTICLES = ("art_2", "art_5", "art_6", "art_50", "anx_I", "anx_III")
OBLIGATIONS_K = 4  # chunks supplémentaires tirés des seuls articles d'obligations
# Articles qui imposent des obligations aux opérateurs : maîtrise de l'IA, exigences et obligations
# haut risque (chap. III, sect. 2-3), conformité et enregistrement, transparence, modèles à usage général,
# surveillance après commercialisation et incidents.
OBLIGATION_ARTICLES = (
    "art_4",
    *(f"art_{n}" for n in range(8, 28)),
    "art_43", "art_47", "art_48", "art_49", "art_50",
    "art_53", "art_55", "art_72", "art_73",
)
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 2000
LLM_TIMEOUT_S = 60
MAX_RETRIES = 1

# Sécurité
MAX_INPUT_CHARS = 3000
DESCRIPTION_TAG = "description_utilisateur"
RATE_LIMIT_PER_SESSION = 10

ChunkStrategy = Literal["article", "fixed"]
STRATEGIES: tuple[ChunkStrategy, ...] = ("article", "fixed")
EMBEDDING_BATCH_SIZE = 32


def collection_name(strategy: ChunkStrategy) -> str:
    """Nom de la collection Chroma d'une stratégie (ai_act_article, ai_act_fixed)."""
    return f"{COLLECTION_PREFIX}{strategy}"


class Settings(BaseModel):
    """Paramètres lus depuis l'environnement."""

    model_config = ConfigDict(frozen=True)

    llm_base_url: str = "https://api.mistral.ai/v1"
    llm_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    llm_model: str = "mistral-small-latest"
    embedding_model: str = "BAAI/bge-m3"
    chunk_strategy: ChunkStrategy = "article"

    @property
    def collection_name(self) -> str:
        """Nom de la collection Chroma de la stratégie active."""
        return collection_name(self.chunk_strategy)


def load_settings() -> Settings:
    """Construit les Settings à partir des variables d'environnement non vides."""
    keys = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "EMBEDDING_MODEL", "CHUNK_STRATEGY"]
    values = {k.lower(): os.environ[k] for k in keys if os.environ.get(k)}
    return Settings(**values)


settings = load_settings()
