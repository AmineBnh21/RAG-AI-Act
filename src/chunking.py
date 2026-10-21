"""Découpage des articles en chunks : stratégies "article" et "fixed"."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import (
    ARTICLES_JSON,
    FIXED_CHUNK_OVERLAP,
    FIXED_CHUNK_SIZE,
    MAX_PARAGRAPH_CHARS,
    MIN_PARAGRAPH_CHARS,
    ChunkStrategy,
)

# Début d'un point de liste : « a) », « b bis) », « 12) », « iii) »
LIST_POINT = re.compile(r"^([a-z]{1,4}|\d{1,3})( (bis|ter|quater|quinquies|sexies))?\) ")
ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}
MAX_LEAD_CHARS = 300  # phrase d'introduction répétée dans chaque sous-chunk si elle est courte


@dataclass(frozen=True)
class Chunk:
    """Unité indexée dans ChromaDB."""

    chunk_id: str
    article_id: str
    label: str
    title: str | None
    chapter: str | None
    paragraph: str | None
    kind: str
    strategy: str
    url: str
    text: str

    def to_dict(self) -> dict:
        """Représentation dict (pour Chroma et les tests)."""
        return asdict(self)


def load_corpus(path: Path = ARTICLES_JSON) -> list[dict]:
    """Charge data/articles.json."""
    return json.loads(path.read_text(encoding="utf-8"))


def merge_short(paragraphs: list[dict], min_chars: int = MIN_PARAGRAPH_CHARS) -> list[dict]:
    """Fusionne les paragraphes trop courts avec le suivant (le dernier rejoint le précédent)."""
    merged: list[dict] = []
    pending: dict | None = None
    for para in paragraphs:
        nums = [para["num"]] if para["num"] else []
        current = {"nums": nums, "text": para["text"]}
        if pending:
            current = {"nums": pending["nums"] + nums, "text": f"{pending['text']}\n{para['text']}"}
        if len(current["text"]) < min_chars:
            pending = current
        else:
            merged.append(current)
            pending = None
    if pending:
        if merged:
            last = merged[-1]
            merged[-1] = {"nums": last["nums"] + pending["nums"], "text": f"{last['text']}\n{pending['text']}"}
        else:
            merged.append(pending)
    return merged


def top_level_point(line: str, previous: str | None) -> str | None:
    """Label du point de premier niveau (« a », « 12 ») ; None pour un sous-point romain i), ii)…

    « i) » après « h) » (ou « v) » après « u) », « x) » après « w) ») reste une lettre.
    """
    match = LIST_POINT.match(line)
    if not match:
        return None
    label = match.group(1)
    if label in ROMAN:
        follows_letter = previous is not None and len(label) == 1 and ord(label) == ord(previous) + 1
        return label if follows_letter else None
    return label


def split_long(text: str, max_chars: int = MAX_PARAGRAPH_CHARS) -> list[str]:
    """Découpe un texte trop long sur les points de liste a), b)…, puis sur les lignes si besoin.

    La phrase d'introduction (avant le premier point) est répétée dans chaque morceau si elle est courte.
    """
    if len(text) <= max_chars:
        return [text]
    lines = text.split("\n")
    first_point = next((i for i, line in enumerate(lines) if LIST_POINT.match(line)), len(lines))
    lead = "\n".join(lines[:first_point])
    repeat_lead = 0 < len(lead) <= MAX_LEAD_CHARS

    units: list[str] = [] if repeat_lead else ([lead] if lead else [])
    previous: str | None = None
    for line in lines[first_point:]:
        label = top_level_point(line, previous)
        if label or not units:
            units.append(line)
            previous = label or previous
        else:
            units[-1] += "\n" + line

    budget = max_chars - (len(lead) + 1 if repeat_lead else 0)
    pieces = [part for unit in units for part in (unit.split("\n") if len(unit) > budget else [unit])]
    return [f"{lead}\n{block}" if repeat_lead else block for block in pack(pieces, budget)]


def pack(pieces: list[str], max_chars: int) -> list[str]:
    """Regroupe des morceaux consécutifs tant que la taille reste sous max_chars."""
    blocks: list[str] = []
    for piece in pieces:
        if blocks and len(blocks[-1]) + 1 + len(piece) <= max_chars:
            blocks[-1] += "\n" + piece
        else:
            blocks.append(piece)
    return blocks


def header(entry: dict, nums: list[str]) -> str:
    """En-tête « Article 5 — Titre — §1 » (« point 1 » pour les annexes)."""
    parts = [entry["label"]]
    if entry["title"]:
        parts.append(entry["title"])
    if nums:
        marker = "point" if entry["kind"] == "annex" else "§"
        sep = " " if marker == "point" else ""
        parts.append(f"{marker}{sep}{', '.join(nums)}")
    return " — ".join(parts)


def make_chunk(entry: dict, strategy: str, index: int, paragraph: str | None, text: str) -> Chunk:
    """Construit un Chunk à partir d'une entrée du corpus."""
    return Chunk(
        chunk_id=f"{entry['id']}__{strategy}__{index:03d}",
        article_id=entry["id"],
        label=entry["label"],
        title=entry["title"],
        chapter=entry["chapter"],
        paragraph=paragraph,
        kind=entry["kind"],
        strategy=strategy,
        url=entry["url"],
        text=text,
    )


def chunk_by_article(entry: dict) -> list[Chunk]:
    """Stratégie "article" : un chunk par paragraphe, préfixé par l'en-tête."""
    chunks: list[Chunk] = []
    for group in merge_short(entry["paragraphs"]):
        head = header(entry, group["nums"])
        paragraph = ", ".join(group["nums"]) or None
        for part in split_long(group["text"]):
            chunks.append(make_chunk(entry, "article", len(chunks), paragraph, f"{head} : {part}"))
    return chunks


def raw_text(entry: dict) -> str:
    """Texte brut de l'entrée, numéros de paragraphe inclus pour les articles."""
    if entry["kind"] != "article":
        return "\n".join(p["text"] for p in entry["paragraphs"])
    return "\n".join(f"{p['num']}. {p['text']}" if p["num"] else p["text"] for p in entry["paragraphs"])


def sliding_windows(text: str, size: int = FIXED_CHUNK_SIZE, overlap: int = FIXED_CHUNK_OVERLAP) -> list[str]:
    """Fenêtres de `size` caractères avec `overlap` caractères de chevauchement."""
    step = size - overlap
    windows = []
    for start in range(0, len(text), step):
        windows.append(text[start : start + size])
        if start + size >= len(text):
            break
    return windows


def chunk_fixed(entry: dict) -> list[Chunk]:
    """Stratégie "fixed" : fenêtres glissantes sur le texte brut, sans en-tête."""
    return [
        make_chunk(entry, "fixed", i, None, window)
        for i, window in enumerate(sliding_windows(raw_text(entry)))
    ]


def build_chunks(corpus: list[dict], strategy: ChunkStrategy) -> list[Chunk]:
    """Découpe tout le corpus selon la stratégie demandée."""
    chunker = {"article": chunk_by_article, "fixed": chunk_fixed}[strategy]
    return [chunk for entry in corpus for chunk in chunker(entry)]
