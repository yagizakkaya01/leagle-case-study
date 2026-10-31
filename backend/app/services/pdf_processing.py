"""PDF text extraction and chunking.

Each page is extracted on its own so every chunk keeps the page it came from;
that page number is what the chatbot later cites back to the user.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pdfplumber
from langchain_core.documents import Document

_MIN_REAL_WORDS = 8


class PdfProcessingError(ValueError):
    """Raised when an uploaded file cannot be read as a PDF."""


@dataclass
class ProcessedPdf:
    page_count: int
    chunks: list[Document]
    empty_pages: list[int] = field(default_factory=list)  # 1-based


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

        chunks: list[Document] = []
        empty_pages: list[int] = []
        for page_number, page in enumerate(pdf.pages, start=1):
            # Tighter x_tolerance: the default glues words together in many LaTeX PDFs.
            text = (page.extract_text(x_tolerance=1.5) or "").strip()
            page_chunks = [
                c for c in split_text(text, chunk_size, overlap) if is_valid_chunk(c)
            ]
            if not page_chunks:
                empty_pages.append(page_number)
                continue
            chunks.extend(
                Document(
                    page_content=c,
                    metadata={
                        "document_id": document_id,
                        "filename": filename,
                        "page": page_number,
                    },
                )
                for c in page_chunks
            )

        return ProcessedPdf(page_count=len(pdf.pages), chunks=chunks, empty_pages=empty_pages)
