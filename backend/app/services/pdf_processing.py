"""PDF text extraction and chunking.

Each page is extracted on its own so every chunk keeps the page it came from;
that page number is what the chatbot later cites back to the user.
"""
from __future__ import annotations

import io
import re
import statistics
from dataclasses import dataclass, field

import pdfplumber
from langchain_core.documents import Document

from app.services.chunk_metadata import (
    classify_clause,
    parse_heading,
    referenced_clauses,
)

X_TOLERANCE = 1.5  # tighter than the default, which glues words together in many LaTeX PDFs
_MIN_REAL_WORDS = 8
_HEADING_FONT_RATIO = 1.15  # line font >= 115% of the body font -> heading


class PdfProcessingError(ValueError):
    """Raised when an uploaded file cannot be read as a PDF."""


@dataclass
class ProcessedPdf:
    page_count: int
    chunks: list[Document]
    pages: list[str]  # extracted text per page, index 0 = page 1
    outline: list[tuple[str, int]] = field(default_factory=list)  # (heading, page)
    empty_pages: list[int] = field(default_factory=list)  # 1-based


@dataclass
class _Section:
    heading: str | None
    clause_number: str | None
    page: int
    lines: list[str] = field(default_factory=list)
    starts_with_heading: bool = False


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Word-based sliding window that keeps line breaks inside chunks."""
    words = text.replace("\n", " <newline> ").split()
    if not words:
        return []
    step = max(1, chunk_size - overlap)
    chunks = []
    for start in range(0, len(words), step):
        segment = " ".join(words[start:start + chunk_size])
        chunks.append(segment.replace(" <newline> ", "\n").replace("<newline>", "\n").strip())
        if start + chunk_size >= len(words):
            break
    return chunks


def is_valid_chunk(text: str) -> bool:
    """Reject chunks that are only page numbers, bullets or whitespace."""
    cleaned = re.sub(r"^\s*[-➢•▪▸►]\s*$", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d{1,4}\s*$", "", cleaned, flags=re.MULTILINE)
    return len(cleaned.split()) >= _MIN_REAL_WORDS


def split_into_sections(
    pages: list[str], large_lines: frozenset[tuple[int, str]] = frozenset()
) -> list[_Section]:
    """Splits page texts at heading lines; a heading carries over to the next page.

    `large_lines` holds (page, line) pairs set in a larger font than body text.
    """
    heading: str | None = None
    clause_number: str | None = None
    sections: list[_Section] = []
    for page_number, text in enumerate(pages, start=1):
        current = _Section(heading, clause_number, page_number)
        sections.append(current)
        for line in text.splitlines():
            parsed = parse_heading(line, large_font=(page_number, line) in large_lines)
            if parsed:
                heading, clause_number = parsed
                current = _Section(heading, clause_number, page_number, [line], True)
                sections.append(current)
            else:
                current.lines.append(line)
    return [s for s in sections if any(line.strip() for line in s.lines)]


def _extract_lines(pdf: pdfplumber.PDF) -> tuple[list[str], frozenset[tuple[int, str]]]:
    """Page texts plus the lines whose font is clearly larger than body text."""
    page_lines: list[list[tuple[str, float]]] = []
    sizes: list[float] = []
    for page in pdf.pages:
        lines = page.extract_text_lines(x_tolerance=X_TOLERANCE)
        page_lines.append([(ln["text"], statistics.mean(c["size"] for c in ln["chars"]))
                           for ln in lines if ln["chars"]])
        sizes.extend(c["size"] for ln in lines for c in ln["chars"])

    body_size = statistics.median(sizes) if sizes else 0.0
    pages = ["\n".join(text for text, _ in lines).strip() for lines in page_lines]
    large = frozenset(
        (number, text)
        for number, lines in enumerate(page_lines, start=1)
        for text, size in lines
        if body_size and size >= body_size * _HEADING_FONT_RATIO
    )
    return pages, large


def _chunk_document(
    text: str, section: _Section, *, document_id: str, filename: str, index: int
) -> Document:
    return Document(
        page_content=text,
        metadata={
            "chunk_id": f"{document_id[:12]}-p{section.page}-c{index}",
            "document_id": document_id,
            "filename": filename,
            "page": section.page,
            "section_heading": section.heading,
            "clause_number": section.clause_number,
            "clause_category": classify_clause(section.heading, text),
            "references": referenced_clauses(text, section.clause_number),
        },
    )


def process_pdf(
    data: bytes,
    *,
    document_id: str,
    filename: str,
    chunk_size: int,
    overlap: int,
    max_pages: int,
) -> ProcessedPdf:
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdfminer raises many different error types
        raise PdfProcessingError("The file could not be read as a PDF.") from exc

    with pdf:
        if len(pdf.pages) > max_pages:
            raise PdfProcessingError(
                f"The PDF has {len(pdf.pages)} pages; the limit is {max_pages}."
            )
        pages, large_lines = _extract_lines(pdf)

    sections = split_into_sections(pages, large_lines)
    chunks: list[Document] = []
    pages_with_chunks: set[int] = set()
    page_chunk_counter: dict[int, int] = {}
    for section in sections:
        for text in split_text("\n".join(section.lines), chunk_size, overlap):
            if not is_valid_chunk(text):
                continue
            index = page_chunk_counter.get(section.page, 0)
            page_chunk_counter[section.page] = index + 1
            chunks.append(_chunk_document(
                text, section, document_id=document_id, filename=filename, index=index
            ))
            pages_with_chunks.add(section.page)

    return ProcessedPdf(
        page_count=len(pages),
        chunks=chunks,
        pages=pages,
        outline=[(s.heading, s.page) for s in sections if s.starts_with_heading],
        empty_pages=[n for n in range(1, len(pages) + 1) if n not in pages_with_chunks],
    )
