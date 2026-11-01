"""Chat endpoints: one question about an uploaded document, plain or streamed."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.dependencies import (
    enforce_chat_limit,
    get_chat_service,
    get_document_store,
    get_repository,
)
from app.schemas import ChatAnswer, ChatRequest
from app.services.chat import ChatService
from app.services.document_store import DocumentStore, StoredDocument
from app.services.persistence import Repository

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

TITLE_CHARS = 80
ANSWER_FAILED = "The answer could not be produced. Please try again."
LLM_RATE_LIMITED = "The free language model is rate limited. Please try again in a few minutes."

Store = Annotated[DocumentStore, Depends(get_document_store)]
Repo = Annotated[Repository, Depends(get_repository)]
Chat = Annotated[ChatService | None, Depends(get_chat_service)]


def _prepare(body: ChatRequest, store: DocumentStore, repo: Repository,
             chat: ChatService | None) -> tuple[ChatService, StoredDocument]:
    if chat is None:
        raise HTTPException(503, "No language model is configured (set NVIDIA_API_KEY).")
    doc = store.get(body.document_id)
    if doc is None:
        raise HTTPException(404, "Document not found. Please upload it again.")
    existing = repo.get_conversation(str(body.session_id))
    if existing and (existing.client_id != body.client_id
                     or existing.document_id != body.document_id):
        raise HTTPException(403, "This conversation belongs to another document or user.")
    return chat, doc


def _failure_detail(exc: Exception) -> str:
    """What the user is told; the cause goes to the log.

    Only a 429 is known to come from the model; anything else (the model, the database, a
    bug) gets the same neutral message.
    """
    if "[429]" in str(exc):  # how the NVIDIA client reports the status code
        log.warning("model rate limited")
        return LLM_RATE_LIMITED
    log.error("answer failed error=%s", type(exc).__name__, exc_info=exc)
    return ANSWER_FAILED


def _remember(repo: Repository, body: ChatRequest) -> None:
    repo.touch_conversation(str(body.session_id), body.client_id, body.document_id,
                            title=body.question.strip()[:TITLE_CHARS])


@router.post("", response_model=ChatAnswer, dependencies=[Depends(enforce_chat_limit)])
def ask(body: ChatRequest, store: Store, repo: Repo, chat: Chat) -> ChatAnswer:
    service, doc = _prepare(body, store, repo, chat)
    try:
        answer = service.ask(doc, str(body.session_id), body.question.strip())
    except Exception as exc:
        detail = _failure_detail(exc)
        raise HTTPException(503 if detail == LLM_RATE_LIMITED else 502, detail) from exc
    _remember(repo, body)
    return answer


@router.post("/stream", dependencies=[Depends(enforce_chat_limit)])
def ask_stream(body: ChatRequest, store: Store, repo: Repo, chat: Chat) -> StreamingResponse:
    """Server-Sent Events: `tool` and `delta` events while working, then `final`
    (the verified ChatAnswer) or `error`."""
    service, doc = _prepare(body, store, repo, chat)

    def events() -> Iterator[str]:
        try:
            for event in service.ask_stream(doc, str(body.session_id), body.question.strip()):
                kind = event.pop("type")
                if kind == "final":
                    _remember(repo, body)
                    event = event["answer"].model_dump()
                yield _sse(kind, event)
        except Exception as exc:
            yield _sse("error", {"detail": _failure_detail(exc)})

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # tells nginx not to buffer the stream
    })


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
