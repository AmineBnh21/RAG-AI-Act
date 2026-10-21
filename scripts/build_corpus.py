"""Extraction du HTML EUR-Lex vers data/articles.json.

Usage : python -m scripts.build_corpus
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from src.config import ARTICLES_JSON, EURLEX_BASE_URL, SOURCE_HTML

ARTICLE_ID = re.compile(r"^art_\w+$")
ANNEX_ID = re.compile(r"^anx_[IVX]+$")
ARTICLE_LABEL = re.compile(r"Article\s*(\d+)\s*(bis|ter|quater|quinquies|sexies)?", re.I)
DELETION_MARK = re.compile(r"—{3,}")
NOISE_SELECTORS = ["p.modref", "#TOC", "p.footnote", "script", ".arrow", "a.anchorarrow"]
BLOCK_TAGS = {"p", "div", "table", "tr", "ul", "ol", "li", "hr", "br"}


def normalize(text: str) -> str:
    """Normalise les espaces, apostrophes typographiques et marqueurs de suppression."""
    text = DELETION_MARK.sub(" ", text.replace("\xa0", " ").replace("’", "'"))
    return re.sub(r"\s+", " ", text).strip()


def load_soup(path: Path = SOURCE_HTML) -> BeautifulSoup:
    """Charge le HTML et supprime le bruit (marqueurs ▼, TOC, notes, scripts)."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    for selector in NOISE_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()
    return soup


def is_list_item(el: Tag) -> bool:
    """Vrai pour un point de liste EUR-Lex (grille label | contenu)."""
    return "grid-list" in (el.get("class") or [])


def list_item_lines(item: Tag) -> list[str]:
    """Point de liste : le label « a) » est collé à la première ligne du contenu."""
    label_div = item.find("div", class_="grid-list-column-1", recursive=False)
    body_div = item.find("div", class_="grid-list-column-2", recursive=False)
    label = normalize(label_div.get_text()) if label_div else ""
    body = block_lines(body_div) if body_div else []
    if not body:
        return [label] if label else []
    return [normalize(f"{label} {body[0]}"), *body[1:]]


def element_lines(el: Tag) -> list[str]:
    """Texte d'un élément bloc, une ligne par bloc."""
    return list_item_lines(el) if is_list_item(el) else block_lines(el)


def block_lines(el: Tag) -> list[str]:
    """Texte des enfants d'un élément, une ligne par bloc."""
    lines: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        text = normalize("".join(buffer))
        if text:
            lines.append(text)
        buffer.clear()

    for child in el.children:
        if isinstance(child, NavigableString):
            buffer.append(str(child))
        elif child.name in BLOCK_TAGS:
            flush()
            lines.extend(element_lines(child))
        else:
            buffer.append(child.get_text())
    flush()
    return lines


def paragraph_number(div: Tag) -> str | None:
    """Numéro d'un paragraphe (« 1 bis ») ; None pour les paragraphes cités (« «5. »)."""
    span = div.find("span", class_="no-parag", recursive=False)
    if span is None:
        return None
    raw = normalize(span.get_text())
    if raw.startswith("«"):
        return None
    return re.sub(r"\s*[.)]$", "", raw)


def split_paragraphs(article: Tag) -> list[dict]:
    """Découpe un article en paragraphes numérotés ; les alinéas sans numéro rejoignent le précédent."""
    paragraphs: list[dict] = []
    for child in article.find_all(recursive=False):
        classes = child.get("class") or []
        if "title-article-norm" in classes or "eli-title" in classes:
            continue
        num = paragraph_number(child) if child.name == "div" and "norm" in classes else None
        if num is not None:
            child.find("span", class_="no-parag", recursive=False).decompose()
        text = "\n".join(element_lines(child))
        if not text:
            continue
        if num is not None or not paragraphs:
            paragraphs.append({"num": num, "text": text})
        else:
            paragraphs[-1]["text"] += "\n" + text
    return paragraphs


def format_label(raw: str) -> str:
    """« Article 4bis » -> « Article 4 bis » ; « Article premier » inchangé."""
    raw = normalize(raw)
    match = ARTICLE_LABEL.fullmatch(raw)
    if not match:
        return raw
    number, suffix = match.groups()
    return f"Article {number} {suffix.lower()}" if suffix else f"Article {number}"


def division_title(div: Tag) -> str:
    """« CHAPITRE II — PRATIQUES INTERDITES ... » à partir des titres enfants directs."""
    parts = [
        normalize(p.get_text())
        for cls in ("title-division-1", "title-division-2")
        for p in div.find_all("p", class_=cls, recursive=False)
    ]
    return " — ".join(p for p in parts if p)


def enclosing_divisions(article: Tag) -> tuple[str | None, str | None]:
    """Chapitre et section contenant l'article."""
    chapter = section = None
    for parent in article.parents:
        parent_id = parent.get("id") or ""
        if re.fullmatch(r"cpt_[IVX]+\.sct_\d+", parent_id) and section is None:
            section = division_title(parent)
        elif re.fullmatch(r"cpt_[IVX]+", parent_id):
            chapter = division_title(parent)
            break
    return chapter, section


def parse_article(article: Tag) -> dict:
    """Construit l'entrée JSON d'un article."""
    title_tag = article.select_one("p.stitle-article-norm")
    chapter, section = enclosing_divisions(article)
    return {
        "id": article["id"],
        "kind": "article",
        "label": format_label(article.find("p", class_="title-article-norm").get_text()),
        "title": normalize(title_tag.get_text()) if title_tag else None,
        "chapter": chapter,
        "section": section,
        "url": f"{EURLEX_BASE_URL}#{article['id']}",
        "paragraphs": split_paragraphs(article),
    }


def split_annex(annex: Tag) -> list[dict]:
    """Découpe une annexe : un paragraphe par point numéroté de premier niveau (1., 2., ...)."""
    paragraphs: list[dict] = []
    for child in annex.find_all(recursive=False):
        classes = child.get("class") or []
        if "title-annex-1" in classes or "title-annex-2" in classes:
            continue
        lines = element_lines(child) if child.name in BLOCK_TAGS else [normalize(child.get_text())]
        lines = [line for line in lines if line]
        if not lines:
            continue
        point = re.match(r"^(\d+)\.\s", lines[0]) if is_list_item(child) else None
        if point or not paragraphs:
            paragraphs.append({"num": point.group(1) if point else None, "text": "\n".join(lines)})
        else:
            paragraphs[-1]["text"] += "\n" + "\n".join(lines)
    return paragraphs


def parse_annex(annex: Tag) -> dict:
    """Construit l'entrée JSON d'une annexe (titre : title-annex-2, sinon second title-annex-1)."""
    title_tag = annex.find("p", class_="title-annex-2")
    if title_tag is None:
        headings = annex.find_all("p", class_="title-annex-1", recursive=False)
        title_tag = headings[1] if len(headings) > 1 else None
    roman = annex["id"].removeprefix("anx_")
    return {
        "id": annex["id"],
        "kind": "annex",
        "label": f"Annexe {roman}",
        "title": normalize(title_tag.get_text()) if title_tag else None,
        "chapter": None,
        "section": None,
        "url": f"{EURLEX_BASE_URL}#{annex['id']}",
        "paragraphs": split_annex(annex),
    }


def build_corpus(path: Path = SOURCE_HTML) -> list[dict]:
    """Extrait tous les articles puis toutes les annexes."""
    soup = load_soup(path)
    articles = soup.find_all("div", class_="eli-subdivision", id=ARTICLE_ID)
    annexes = soup.find_all("div", id=ANNEX_ID)
    return [parse_article(a) for a in articles] + [parse_annex(a) for a in annexes]


def main() -> None:
    """Écrit data/articles.json et affiche un résumé."""
    corpus = build_corpus()
    ARTICLES_JSON.write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")
    n_articles = sum(e["kind"] == "article" for e in corpus)
    print(f"{n_articles} articles, {len(corpus) - n_articles} annexes -> {ARTICLES_JSON}")


if __name__ == "__main__":
    main()
