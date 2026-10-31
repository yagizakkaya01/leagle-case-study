"""Document-level metadata: rule-based fields plus one structured LLM call.

The LLM only fills descriptive fields (type, parties, dates, ...). Case
numbers, the outline and clause counts come from rules, so they cannot be
invented.
"""
from __future__ import annotations

import logging
from collections import Counter

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from app.llm import structured_output
from app.schemas import DocumentMetadata, LlmDocumentFields, OutlineItem
from app.services.chunk_metadata import OTHER, case_numbers
from app.services.pdf_processing import ProcessedPdf

log = logging.getLogger(__name__)

_MAX_PROMPT_CHARS = 12_000
_MAX_OUTLINE_ITEMS = 60

_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You extract metadata from a legal document. Use ONLY information that is "
     "explicitly written in the text. If a field is not stated, leave it null or "
     "empty; never guess. Dates: ISO yyyy-mm-dd when the day is known. Keep the "
     "summary neutral and in the document's language."),
    ("human",
     "Section headings found by the parser:\n{outline}\n\n"
     "Document text (pages are marked):\n{text}"),
])


def build_extractor(llm: BaseChatModel | None) -> Runnable | None:
    if llm is None:
        return None
    return _PROMPT | structured_output(llm, LlmDocumentFields)


def _prompt_text(pages: list[str]) -> str:
    parts, used = [], 0
    for number, text in enumerate(pages, start=1):
        block = f"--- Page {number} ---\n{text}\n"
        if used + len(block) > _MAX_PROMPT_CHARS:
            parts.append(block[: _MAX_PROMPT_CHARS - used])
            break
        parts.append(block)
        used += len(block)
    return "".join(parts)


def extract_metadata(processed: ProcessedPdf, extractor: Runnable | None) -> DocumentMetadata:
    outline = [OutlineItem(heading=h, page=p) for h, p in processed.outline][:_MAX_OUTLINE_ITEMS]
    categories = Counter(
        c.metadata["clause_category"] for c in processed.chunks
        if c.metadata["clause_category"] != OTHER
    )
    metadata = DocumentMetadata(
        case_numbers=case_numbers("\n".join(processed.pages)),
        outline=outline,
        clause_categories=dict(categories.most_common()),
    )
    if extractor is None:
        return metadata

    try:
        fields: LlmDocumentFields | None = extractor.invoke({
            "outline": "\n".join(f"- {o.heading} (p. {o.page})" for o in outline) or "(none)",
            "text": _prompt_text(processed.pages),
        })
    except Exception:  # metadata is a nice-to-have; never fail the upload over it
        log.warning("LLM metadata extraction failed", exc_info=True)
        return metadata
    if fields is None:  # the model answered without calling the schema tool
        log.warning("LLM returned no metadata tool call")
        return metadata

    return DocumentMetadata(**{**metadata.model_dump(), **fields.model_dump(),
                               "llm_enriched": True})
