"""Checks the model's final answer against the chunks the tools actually returned.

The model chooses the answer; code decides what is shown as its source:
- the cited chunk must be one a tool returned during this question,
- the page number always comes from that chunk's metadata,
- the quote must appear in the chunk word for word (at least three words; case,
  spacing and punctuation aside), otherwise the closest sentence of the chunk is
  shown instead,
- a date or number the answer states must be in the quote when the chunk has it.

An answer with several points cites each one; every citation passes the same checks.
"""
from __future__ import annotations

import logging
import re

from langchain_core.documents import Document
from rapidfuzz import fuzz

from app.schemas import ChatAnswer, FinalAnswer, Source, SourceClaim
from app.services.text_normalize import normalize_whitespace, to_ascii

log = logging.getLogger(__name__)

MIN_QUOTE_WORDS = 3  # one or two words of a chunk say nothing about where an answer comes from
MAX_SOURCES = 10
MAX_QUOTE_CHARS = 600  # legal sentences are long; the highlight should cover the whole one
UNVERIFIED_ANSWER = (
    "I could not find a passage in the document that supports an answer to this question."
)
# No colon: "Discharge date: 31.08.2024" must keep the value that follows its label.
# Nor before a digit: "TTK m. 378" stays in one piece.
_SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+(?![\s\d])|\n+")
_FACT = re.compile(r"\d[\d.,/-]*\d")  # two digits or more: skips list markers like "(1)"
# Numbers that name a clause or a law say where a rule is, not what it states.
_LEGAL_REFERENCE = re.compile(
    r"\b(?:m|md|madde\w*|article|art|section|sec|clause)\.?\s*\d[\d./]*"
    r"|\b\d[\d./]*\s*(?:madde\w*|sayılı)\b",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return normalize_whitespace(to_ascii(text))


def _words(text: str) -> str:
    """Lower-cased words without punctuation, so spacing and quote marks do not matter."""
    return " ".join(re.findall(r"\w+", to_ascii(text)))


def _in_chunk(quote: str, chunk_text: str) -> bool:
    """The quote's words appear in the chunk in the same order, none changed or added."""
    words = _words(quote)
    return len(words.split()) >= MIN_QUOTE_WORDS and f" {words} " in f" {_words(chunk_text)} "


def _sentences(text: str) -> list[str]:
    # A line starting in lower case continues the sentence the page layout wrapped.
    unwrapped = re.sub(r"\n+(\w)", lambda m: f" {m[1]}" if m[1].islower() else m[0], text)
    return [s.strip() for s in _SENTENCE_SPLIT.split(unwrapped) if s.strip()]


def _closest_sentence(chunk_text: str, target: str) -> str:
    sentences = [s for s in _sentences(chunk_text) if len(s.split()) >= 4]
    if not sentences:
        return chunk_text[:MAX_QUOTE_CHARS]
    target_norm = _norm(target)
    return max(sentences, key=lambda s: fuzz.partial_ratio(_norm(s), target_norm))


def _facts(text: str) -> set[str]:
    """Dates and numbers, so that 31/08/2024 and 31.08.2024 compare as the same value."""
    values = _FACT.findall(_LEGAL_REFERENCE.sub(" ", text))
    return {".".join(str(int(n)) for n in re.findall(r"\d+", m)) for m in values}


def _sentence_stating(chunk_text: str, facts: set[str], answer: str) -> str:
    answer_norm = _norm(answer)
    return max(_sentences(chunk_text), key=lambda s: (len(facts & _facts(s)),
                                                      fuzz.partial_ratio(_norm(s), answer_norm)))


def _trim(text: str) -> str:
    text = normalize_whitespace(text)
    return text if len(text) <= MAX_QUOTE_CHARS else text[:MAX_QUOTE_CHARS].rsplit(" ", 1)[0] + "…"


def _checked_quote(chunk: Document, quote: str | None, claim: str) -> str:
    chunk_id = chunk.metadata["chunk_id"]
    quote = quote or ""
    if not _in_chunk(quote, chunk.page_content):
        log.info("quote replaced reason=not_in_chunk chunk=%s", chunk_id)
        quote = _closest_sentence(chunk.page_content, quote or claim)

    facts = _facts(claim)
    if len(facts & _facts(chunk.page_content)) > len(facts & _facts(quote)):
        log.info("quote replaced reason=missing_value chunk=%s", chunk_id)
        quote = _sentence_stating(chunk.page_content, facts, claim)
    return _trim(quote)


def _checked_sources(claims: list[SourceClaim], answer: str,
                     evidence: dict[str, Document]) -> list[Source]:
    """The claims a returned chunk backs; the same passage is listed once."""
    sources: dict[tuple[int, str], Source] = {}
    for claim in claims[:MAX_SOURCES]:
        chunk = evidence.get(claim.chunk_id)
        if chunk is None:
            log.info("source dropped reason=chunk_not_returned chunk=%s", claim.chunk_id)
            continue
        quote = _checked_quote(chunk, claim.reference_text, claim.point or answer)
        sources.setdefault((chunk.metadata["page"], quote), Source(
            point=claim.point, page_number=chunk.metadata["page"], reference_text=quote,
        ))
    return list(sources.values())


def verify(final: FinalAnswer, evidence: dict[str, Document]) -> ChatAnswer:
    """The answer with every citation backed by evidence, or found=False."""
    if not final.found:
        return ChatAnswer(answer=final.answer, page_number=None, reference_text=None, found=False)

    main = SourceClaim(chunk_id=final.chunk_id or "", reference_text=final.reference_text)
    sources = (_checked_sources(final.sources, final.answer, evidence)
               or _checked_sources([main], final.answer, evidence))
    if not sources:
        # A claim about the document with no chunk behind it: don't show it.
        log.warning("answer rejected reason=no_supporting_chunk chunks_returned=%d", len(evidence))
        return ChatAnswer(answer=UNVERIFIED_ANSWER, page_number=None, reference_text=None,
                          found=False)

    return ChatAnswer(
        answer=final.answer,
        page_number=sources[0].page_number,
        reference_text=sources[0].reference_text,
        found=True,
        sources=sources,
    )
