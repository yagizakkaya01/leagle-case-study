"""Keeps uploaded PDFs, their processed chunks and metadata.

Files go to a local folder for now; the registry lives in process memory.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import Runnable

from app.schemas import DocumentMetadata
from app.services.document_metadata import extract_metadata
from app.services.pdf_processing import process_pdf
from app.services.search_index import SearchIndex


@dataclass
class StoredDocument:
    document_id: str
    filename: str
    pages: list[str]
    chunks: list[Document]
    empty_pages: list[int]
    metadata: DocumentMetadata
    index: SearchIndex

    @property
    def page_count(self) -> int:
        return len(self.pages)


class DocumentStore:
    def __init__(
        self,
        storage_dir: Path,
        *,
        chunk_size: int,
        overlap: int,
        max_pages: int,
        metadata_extractor: Runnable | None = None,
        embeddings: Embeddings | None = None,
    ):
        self._dir = storage_dir
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._max_pages = max_pages
        self._extractor = metadata_extractor
        self._embeddings = embeddings
        self._documents: dict[str, StoredDocument] = {}
        self._lock = threading.Lock()

    def add(self, data: bytes, filename: str) -> StoredDocument:
        # Content hash as id: re-uploading the same PDF reuses the existing entry.
        document_id = hashlib.sha256(data).hexdigest()
        with self._lock:
            existing = self._documents.get(document_id)
        if existing:
            return existing

        processed = process_pdf(
            data,
            document_id=document_id,
            filename=filename,
            chunk_size=self._chunk_size,
            overlap=self._overlap,
            max_pages=self._max_pages,
        )
        metadata = extract_metadata(processed, self._extractor) if processed.chunks else None

        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / f"{document_id}.pdf").write_bytes(data)

        doc = StoredDocument(
            document_id=document_id,
            filename=filename,
            pages=processed.pages,
            chunks=processed.chunks,
            empty_pages=processed.empty_pages,
            metadata=metadata or DocumentMetadata(),
            index=SearchIndex(processed.chunks, self._embeddings),
        )
        with self._lock:
            self._documents[document_id] = doc
        return doc

    def get(self, document_id: str) -> StoredDocument | None:
        with self._lock:
            return self._documents.get(document_id)
