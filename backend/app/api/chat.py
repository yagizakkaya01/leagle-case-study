"""Chat endpoint: one question about an uploaded document."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_chat_service, get_document_store, get_repository
from app.schemas import ChatAnswer, ChatRequest
from app.services.chat import ChatService
from app.services.document_store import DocumentStore
from app.services.persistence import Repository

router = APIRouter(prefix="/api/chat", tags=["chat"])

TITLE_CHARS = 80


@router.post("", response_model=ChatAnswer)
def ask(
    body: ChatRequest,
    store: Annotated[DocumentStore, Depends(get_document_store)],
    repo: Annotated[Repository, Depends(get_repository)],
    chat: Annotated[ChatService | None, Depends(get_chat_service)],
) -> ChatAnswer:
    if chat is None:
        raise HTTPException(503, "No language model is configured (set NVIDIA_API_KEY).")
    doc = store.get(body.document_id)
    if doc is None:
        raise HTTPException(404, "Document not found. Please upload it again.")

    conversation_id = str(body.session_id)
    existing = repo.get_conversation(conversation_id)
    if existing and (existing.client_id != body.client_id
                     or existing.document_id != body.document_id):
        raise HTTPException(403, "This conversation belongs to another document or user.")

    question = body.question.strip()
    try:
        answer = chat.ask(doc, conversation_id, question)
    except Exception as exc:
        raise HTTPException(502, "The language model did not respond. Please try again.") from exc
    repo.touch_conversation(conversation_id, body.client_id, doc.document_id,
                            title=question[:TITLE_CHARS])
    return answer
