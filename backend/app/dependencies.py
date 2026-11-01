"""Shared singletons, exposed as FastAPI dependencies so tests can override them."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from app.config import settings
from app.llm import get_chat_model, get_embeddings, get_reranker
from app.services.chat import ChatService
from app.services.document_metadata import build_extractor
from app.services.document_store import DocumentStore
from app.services.file_storage import build_file_storage
from app.services.persistence import Repository, build_repository
from app.services.rate_limit import RateLimiter, client_ip


@lru_cache
def get_repository() -> Repository:
    return build_repository(settings.DATABASE_URL)


@lru_cache
def get_document_store() -> DocumentStore:
    return DocumentStore(
        build_file_storage(settings.AZURE_STORAGE_CONNECTION_STRING,
                           settings.AZURE_STORAGE_CONTAINER, settings.STORAGE_DIR),
        chunk_size=settings.CHUNK_SIZE,
        overlap=settings.CHUNK_OVERLAP,
        max_pages=settings.MAX_PAGES,
        metadata_extractor=build_extractor(get_chat_model()),
        embeddings=get_embeddings(),
        reranker=get_reranker(),
        repository=get_repository(),
    )


@lru_cache
def get_chat_service() -> ChatService | None:
    llm = get_chat_model()
    return ChatService(llm, get_repository().history) if llm is not None else None


@lru_cache
def get_chat_limiter() -> RateLimiter:
    return RateLimiter(settings.CHAT_LIMIT_PER_HOUR, "questions")


@lru_cache
def get_upload_limiter() -> RateLimiter:
    return RateLimiter(settings.UPLOAD_LIMIT_PER_HOUR, "uploads")


def enforce_chat_limit(
    request: Request, limiter: Annotated[RateLimiter, Depends(get_chat_limiter)]
) -> None:
    limiter.check(client_ip(request, settings.TRUSTED_PROXY_HOPS))


def enforce_upload_limit(
    request: Request, limiter: Annotated[RateLimiter, Depends(get_upload_limiter)]
) -> None:
    limiter.check(client_ip(request, settings.TRUSTED_PROXY_HOPS))
