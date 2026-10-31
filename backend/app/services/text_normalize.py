"""Turkish-aware text normalisation for rule-based matching.

Python's `str.lower()` maps "I" to "i", which is wrong for Turkish ("I" -> "ı",
"İ" -> "i"); keyword rules would silently miss "MADDE"/"İHTAR" without this.
"""
from __future__ import annotations

import re

_TR_LOWER = str.maketrans({
    "İ": "i", "I": "ı", "Ğ": "ğ", "Ü": "ü", "Ş": "ş", "Ö": "ö", "Ç": "ç",
})

_TO_ASCII = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
})


def turkish_lower(text: str) -> str:
    return text.translate(_TR_LOWER).lower()


def to_ascii(text: str) -> str:
    """Lower-cases with Turkish rules, then folds Turkish letters to ASCII."""
    return turkish_lower(text).translate(_TO_ASCII)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
