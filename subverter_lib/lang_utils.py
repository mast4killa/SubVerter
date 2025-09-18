#!/usr/bin/env python3
from __future__ import annotations

"""
Language utilities for SubVerter.

Provides:
- Mapping from ISO 639-2 to ISO 639-1 codes.
- Normalisation of language codes to ISO 639-1.
- Filtering of candidate language detections against an allowed list.
"""

# Common ISO 639-2 to ISO 639-1 language code mapping
ISO639_MAP: dict[str, str] = {
    "eng": "en", "fra": "fr", "fre": "fr", "deu": "de", "ger": "de", "spa": "es",
    "ita": "it", "nld": "nl", "dut": "nl", "por": "pt", "rus": "ru", "jpn": "ja",
    "zho": "zh", "chi": "zh", "ara": "ar", "tur": "tr", "pol": "pl", "swe": "sv",
    "nor": "no", "fin": "fi", "dan": "da", "ces": "cs", "cze": "cs", "ell": "el",
    "gre": "el", "kor": "ko",
}


def normalize_lang_code(code: str | None) -> str | None:
    """
    Normalize a language code to ISO 639-1 when possible.

    Accepts:
        - 2-letter codes (e.g., 'en')
        - 3-letter codes (e.g., 'eng')
        - IETF tags with region/script (e.g., 'en-US', 'eng-Latn')

    Args:
        code: The language code to normalize.

    Returns:
        The 2-letter ISO 639-1 code if recognized, otherwise None.
    """
    if not code:
        return None

    c = code.lower().strip()
    base = c.split("-")[0]

    if len(base) == 2:
        return base
    if len(base) == 3:
        mapped = ISO639_MAP.get(base)
        return mapped if mapped and len(mapped) == 2 else None

    return None


def filter_allowed_candidates(
    candidates: list[dict],
    allowed_langs: list[str],
) -> list[dict]:
    """
    Return only candidates whose normalized language is in the allowed list.

    Args:
        candidates: A list of dicts, each expected to have a 'lang_norm' key.
        allowed_langs: List of allowed normalized language codes.

    Returns:
        A filtered list of candidates with lang_norm in allowed_langs.
    """
    return [
        c for c in candidates
        if c.get("lang_norm") is not None and c["lang_norm"] in allowed_langs
    ]


def normalize_text(text) -> str:
    """
    Ensure any subtitle entry text is flattened into a single clean string.

    - If `text` is a list (e.g., multiple lines), join with spaces.
    - If it's not a string, convert it.
    - Collapse multiple spaces/tabs/newlines into single spaces.
    """
    if isinstance(text, list):
        text = " ".join(map(str, text))
    else:
        text = str(text)

    # Replace newlines with spaces, then collapse multiple spaces
    return " ".join(text.split())