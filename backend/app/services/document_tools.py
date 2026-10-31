"""Tools the chat model can call to read the uploaded document.

The model never sees the whole document at once: it asks for chunks through
typed tools, and every chunk a tool returns is recorded as evidence. The final
answer may only cite chunks from that evidence (see grounding.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.documents import Document
from langchain_core.tools import BaseTool, tool

from app.services.chunk_metadata import CLAUSE_KEYWORDS
from app.services.document_store import StoredDocument

ClauseCategory = Literal[tuple(CLAUSE_KEYWORDS)]  # type: ignore[valid-type]
MAX_RESULTS = 5


@dataclass
class Evidence:
    """Chunks returned by tools during one question, keyed by chunk_id."""

    chunks: dict[str, Document] = field(default_factory=dict)

    def add(self, docs: list[Document]) -> str:
        for d in docs:
            self.chunks[d.metadata["chunk_id"]] = d
        return json.dumps([_chunk_view(d) for d in docs], ensure_ascii=False)


def _chunk_view(doc: Document) -> dict:
    m = doc.metadata
    return {
        "chunk_id": m["chunk_id"],
        "page": m["page"],
        "section": m["section_heading"],
        "clause_category": m["clause_category"],
        "text": doc.page_content,
    }


def make_tools(doc: StoredDocument, evidence: Evidence) -> list[BaseTool]:
    @tool
    def search_document(
        query: str,
        clause_category: ClauseCategory | None = None,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> str:
        """Search the document and return the most relevant chunks.

        Use for almost every question. `query` should hold the key terms of the
        question. Fill `clause_category` or the page range ONLY if the user asked
        for that clause type or those pages; otherwise leave them empty.
        """
        def where(d: Document) -> bool:
            m = d.metadata
            return ((clause_category is None or m["clause_category"] == clause_category)
                    and (page_from is None or m["page"] >= page_from)
                    and (page_to is None or m["page"] <= page_to))

        return evidence.add(doc.index.search(query, k=MAX_RESULTS, where=where))

    @tool
    def find_clauses(category: ClauseCategory) -> str:
        """Return every chunk tagged with a clause category, e.g. all termination clauses."""
        hits = [c for c in doc.chunks if c.metadata["clause_category"] == category]
        if not hits:
            return f"No chunks are tagged '{category}'. Try search_document instead."
        return evidence.add(hits[:MAX_RESULTS * 2])

    @tool
    def get_page(page_number: int) -> str:
        """Return all chunks of one page (1-based). Use when the user names a page."""
        if not 1 <= page_number <= doc.page_count:
            return f"Page {page_number} does not exist; the document has {doc.page_count} pages."
        hits = [c for c in doc.chunks if c.metadata["page"] == page_number]
        if not hits:
            return f"Page {page_number} has no extractable text."
        return evidence.add(hits)

    @tool
    def get_document_info() -> str:
        """Return document-level facts: type, title, parties, key dates, governing law,
        case numbers, outline and page count. Use for overview questions, then cite a
        chunk found with search_document or get_page."""
        info = doc.metadata.model_dump(exclude={"llm_enriched"})
        info.update(filename=doc.filename, page_count=doc.page_count)
        return json.dumps(info, ensure_ascii=False)

    return [search_document, find_clauses, get_page, get_document_info]
