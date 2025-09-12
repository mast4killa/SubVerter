from __future__ import annotations

# Common ISO 639-2 to ISO 639-1 language code mapping
ISO639_MAP: dict[str, str] = {
    "eng": "en", "fra": "fr", "fre": "fr", "deu": "de", "ger": "de", "spa": "es",
    "ita": "it", "nld": "nl", "dut": "nl", "por": "pt", "rus": "ru", "jpn": "ja",
    "zho": "zh", "chi": "zh", "ara": "ar", "tur": "tr", "pol": "pl", "swe": "sv",
    "nor": "no", "fin": "fi", "dan": "da", "ces": "cs", "cze": "cs", "ell": "el",
    "gre": "el", "kor": "ko"
}

def normalize_lang_code(code: str | None) -> str | None:
    """
    Normalize a language code to ISO 639-1 when possible.

    Accepts:
    - 2-letter codes (e.g., 'en')
    - 3-letter codes (e.g., 'eng')
    - IETF tags with region/script (e.g., 'en-US', 'eng-Latn')

    Returns:
        2-letter code if recognized, otherwise None.
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
    allowed_langs: list[str]
) -> list[dict]:
    """
    Return only candidates whose normalized language is in the allowed list.
    Ignores any with lang_norm=None.
    """
    return [
        c for c in candidates
        if c.get("lang_norm") is not None and c["lang_norm"] in allowed_langs
    ]