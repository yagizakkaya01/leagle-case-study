"""Keeps uploaded PDFs, their processed chunks and metadata.

PDF files go to a FileStorage (local folder or Azure Blob); processed documents
are cached in memory. After a restart a document is rebuilt from its stored file
and saved metadata, so old conversations can be reopened without calling the
LLM again.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import Runnable

from app.logging_config import short_id
from app.schemas import DocumentMetadata
from app.services.document_metadata import extract_metadata
from app.services.file_storage import FileStorage
from app.services.pdf_processing import process_pdf
from app.services.persistence import DocumentRecord, Repository
from app.services.search_index import SearchIndex

log = logging.getLogger(__name__)


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
        files: FileStorage,
        *,
        chunk_size: int,
        overlap: int,
        max_pages: int,
        metadata_extractor: Runnable | None = None,
        embeddings: Embeddings | None = None,
        repository: Repository | None = None,
    ):
        self._files = files
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._max_pages = max_pages
        self._extractor = metadata_extractor
        self._embeddings = embeddings
        self._repository = repository
        self._documents: dict[str, StoredDocument] = {}
        self._lock = threading.Lock()

    def add(self, data: bytes, filename: str) -> StoredDocument:
        # Content hash as id: re-uploading the same PDF reuses the existing entry.
        document_id = hashlib.sha256(data).hexdigest()
        with self._lock:
            existing = self._documents.get(document_id)
        if existing:
            return existing

        # Known from an earlier run: reuse its metadata instead of a new LLM call.
        record = self._repository.get_document(document_id) if self._repository else None
        known = DocumentMetadata.model_validate(record.metadata) if record else None
        started = time.perf_counter()
        doc = self._build(data, document_id, filename, known)
        log.info("document processed doc=%s pages=%d chunks=%d empty_pages=%d bytes=%d "
                 "metadata_reused=%s ms=%d", short_id(document_id), doc.page_count,
                 len(doc.chunks), len(doc.empty_pages), len(data), known is not None,
                 (time.perf_counter() - started) * 1000)
        if not doc.chunks:  # the API rejects it; keeping it would escape the retention purge
            return doc
        self._files.save(document_id, data)
        if self._repository is not None:
            self._repository.save_document(DocumentRecord(
                document_id, filename,
                {**doc.metadata.model_dump(), "page_count": doc.page_count},
            ))
        with self._lock:
            self._documents[document_id] = doc
        return doc

    def get(self, document_id: str) -> StoredDocument | None:
        with self._lock:
            cached = self._documents.get(document_id)
        if cached or self._repository is None:
            return cached
        record = self._repository.get_document(document_id)
        data = self._files.load(document_id) if record else None
        if record is None or data is None:
            return None
        meta = DocumentMetadata.model_validate(record.metadata)
        doc = self._build(data, document_id, record.filename, meta)
        log.info("document restored doc=%s chunks=%d", short_id(document_id), len(doc.chunks))
        with self._lock:
            self._documents[document_id] = doc
        return doc

    def load_file(self, document_id: str) -> bytes | None:
        """The original PDF, for showing a citation on its page."""
        return self._files.load(document_id)

    def purge_older_than(self, cutoff: datetime) -> int:
        """Deletes documents uploaded before `cutoff` with their files and chats."""
        if self._repository is None:
            return 0
        expired = self._repository.documents_older_than(cutoff)
        for document_id in expired:
            self._repository.delete_document(document_id)
            self._files.delete(document_id)
            with self._lock:
                self._documents.pop(document_id, None)
        if expired:
            log.info("Retention: deleted %d expired document(s)", len(expired))
        return len(expired)

    def _build(self, data: bytes, document_id: str, filename: str,
               metadata: DocumentMetadata | None = None) -> StoredDocument:
        processed = process_pdf(
            data,
            document_id=document_id,
            filename=filename,
            chunk_size=self._chunk_size,
            overlap=self._overlap,
            max_pages=self._max_pages,
        )
        if metadata is None and processed.chunks:
            metadata = extract_metadata(processed, self._extractor)
        return StoredDocument(
            document_id=document_id,
            filename=filename,
            pages=processed.pages,
            chunks=processed.chunks,
            empty_pages=processed.empty_pages,
            metadata=metadata or DocumentMetadata(),
            index=SearchIndex(processed.chunks, self._embeddings),
        )
