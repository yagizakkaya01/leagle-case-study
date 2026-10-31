"""Saved conversations: list, reopen (document + messages) and delete."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.documents import to_document_info
from app.dependencies import get_document_store, get_repository
from app.schemas import ConversationDetail, ConversationSummary, StoredMessage
from app.services.document_store import DocumentStore
from app.services.persistence import ConversationRecord, Repository

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

ClientId = Annotated[str, Query(min_length=1, max_length=100)]


def _owned(repo: Repository, conversation_id: str, client_id: str) -> ConversationRecord:
    conv = repo.get_conversation(conversation_id)
    if conv is None or conv.client_id != client_id:
        raise HTTPException(404, "Conversation not found.")
    return conv


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    client_id: ClientId, repo: Annotated[Repository, Depends(get_repository)]
) -> list[ConversationSummary]:
    return [
        ConversationSummary(session_id=c.id, document_id=c.document_id, filename=c.filename,
                            title=c.title, updated_at=c.updated_at)
        for c in repo.list_conversations(client_id)
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    client_id: ClientId,
    repo: Annotated[Repository, Depends(get_repository)],
    store: Annotated[DocumentStore, Depends(get_document_store)],
) -> ConversationDetail:
    conv = _owned(repo, conversation_id, client_id)
    doc = store.get(conv.document_id)
    if doc is None:
        raise HTTPException(410, "The document of this conversation is no longer available.")

    messages = []
    for m in repo.history(conversation_id).messages:
        if m.type == "human":
            messages.append(StoredMessage(role="user", content=m.content))
        elif m.type == "ai":
            messages.append(StoredMessage(role="assistant", content=m.content,
                                          **m.additional_kwargs))
    return ConversationDetail(session_id=conversation_id, document=to_document_info(doc),
                              messages=messages)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    client_id: ClientId,
    repo: Annotated[Repository, Depends(get_repository)],
) -> None:
    _owned(repo, conversation_id, client_id)
    repo.delete_conversation(conversation_id)
