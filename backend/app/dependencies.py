"""Shared singletons, exposed as FastAPI dependencies so tests can override them."""
from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.llm import get_chat_model, get_embeddings
from app.services.chat import ChatService
from app.services.document_metadata import build_extractor
from app.services.document_store import DocumentStore
from app.services.persistence import Repository, build_repository


@lru_cache
def get_repository() -> Repository:
    return build_repository(settings.DATABASE_URL)


@lru_cache
def get_document_store() -> DocumentStore:
    return DocumentStore(
        settings.STORAGE_DIR,
        chunk_size=settings.CHUNK_SIZE,
        overlap=settings.CHUNK_OVERLAP,
        max_pages=settings.MAX_PAGES,
        metadata_extractor=build_extractor(get_chat_model()),
        embeddings=get_embeddings(),
        repository=get_repository(),
    )


@lru_cache
def get_chat_service() -> ChatService | None:
    llm = get_chat_model()
    return ChatService(llm, get_repository().history) if llm is not None else None
