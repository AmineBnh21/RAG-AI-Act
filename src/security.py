"""Filtre d'entrée, validation des citations et rate limit."""

from __future__ import annotations

import re

from src.config import DESCRIPTION_TAG

# Toute balise ouvrante ou fermante qui imite un délimiteur du prompt (espaces et casse tolérés)
_DELIMITER = re.compile(rf"<\s*/?\s*({DESCRIPTION_TAG}|extraits?|system)\b[^>]*>", re.IGNORECASE)


def escape_delimiters(text: str) -> str:
    """Neutralise les balises de délimitation présentes dans l'entrée utilisateur."""
    return _DELIMITER.sub(lambda m: m.group(0).replace("<", "&lt;").replace(">", "&gt;"), text)
