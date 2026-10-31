"""Checks the model's final answer against the chunks the tools actually returned.

The model chooses the answer; code decides what is shown as its source:
- the cited chunk must be one a tool returned during this question,
- the page number always comes from that chunk's metadata,
- the quote must really appear in the chunk, otherwise the closest sentence
  of the chunk is shown instead.
"""
from __future__ import annotations

import re

from langchain_core.documents import Document
from rapidfuzz import fuzz

from app.schemas import FinalAnswer
from app.services.text_normalize import normalize_whitespace, to_ascii

QUOTE_MATCH_THRESHOLD = 85  # rapidfuzz partial_ratio, 0-100
MAX_QUOTE_CHARS = 300
UNVERIFIED_ANSWER = (
    "I could not find a passage in the document that supports an answer to this question."
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.;:!?])\s+|\n+")


def _norm(text: str) -> str:
    return normalize_whitespace(to_ascii(text))


def _closest_sentence(chunk_text: str, target: str) -> str:
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(chunk_text) if len(s.split()) >= 4]
    if not sentences:
        return chunk_text[:MAX_QUOTE_CHARS]
    target_norm = _norm(target)
    return max(sentences, key=lambda s: fuzz.partial_ratio(_norm(s), target_norm))


def _trim(text: str) -> str:
    text = normalize_whitespace(text)
    return text if len(text) <= MAX_QUOTE_CHARS else text[:MAX_QUOTE_CHARS].rsplit(" ", 1)[0] + "…"


def verify(final: FinalAnswer, evidence: dict[str, Document]) -> FinalAnswer:
    """Returns a copy whose page/quote are backed by evidence, or found=False."""
    chunk = evidence.get(final.chunk_id or "")
    if not final.found:
        return FinalAnswer(answer=final.answer, found=False)
    if chunk is None:
        # A claim about the document with no chunk behind it: don't show it.
        return FinalAnswer(answer=UNVERIFIED_ANSWER, found=False)

    quote = final.reference_text or ""
    if not quote or fuzz.partial_ratio(_norm(quote), _norm(chunk.page_content)) < (
        QUOTE_MATCH_THRESHOLD
    ):
        quote = _closest_sentence(chunk.page_content, quote or final.answer)

    return FinalAnswer(
        answer=final.answer,
        found=True,
        chunk_id=chunk.metadata["chunk_id"],
        page_number=chunk.metadata["page"],
        reference_text=_trim(quote),
    )
