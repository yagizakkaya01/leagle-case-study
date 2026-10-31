"""Shared singletons, exposed as FastAPI dependencies so tests can override them."""
from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.llm import get_chat_model
from app.services.document_metadata import build_extractor
from app.services.document_store import DocumentStore


@lru_cache
def get_document_store() -> DocumentStore:
    return DocumentStore(
        settings.STORAGE_DIR,
        chunk_size=settings.CHUNK_SIZE,
        overlap=settings.CHUNK_OVERLAP,
        max_pages=settings.MAX_PAGES,
        metadata_extractor=build_extractor(get_chat_model()),
    )
