"""Chat endpoint: one question about an uploaded document."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_chat_service, get_document_store
from app.schemas import ChatAnswer, ChatRequest
from app.services.chat import ChatService
from app.services.document_store import DocumentStore

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatAnswer)
def ask(
    body: ChatRequest,
    store: Annotated[DocumentStore, Depends(get_document_store)],
    chat: Annotated[ChatService | None, Depends(get_chat_service)],
) -> ChatAnswer:
    if chat is None:
        raise HTTPException(503, "No language model is configured (set NVIDIA_API_KEY).")
    doc = store.get(body.document_id)
    if doc is None:
        raise HTTPException(404, "Document not found. Please upload it again.")
    try:
        return chat.ask(doc, body.session_id, body.question.strip())
    except Exception as exc:
        raise HTTPException(502, "The language model did not respond. Please try again.") from exc
