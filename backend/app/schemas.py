"""Request / response models shared by the API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

DocumentType = Literal[
    "contract", "court_decision", "legislation", "regulation", "pleading",
    "legal_opinion", "policy", "correspondence", "other",
]


class HighlightRequest(BaseModel):
    page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=1000)


class HighlightBox(BaseModel):
    """A rectangle on a page, in percent of the page size."""
    x: float
    top: float
    width: float
    height: float


class Party(BaseModel):
    name: str
    role: str | None = Field(None, description="e.g. Tenant, Landlord, Plaintiff, Defendant")


class KeyDate(BaseModel):
    label: str = Field(description="What the date is, e.g. 'Signing date', 'Decision date'")
    date: str = Field(description="ISO yyyy-mm-dd when possible, otherwise as written")
    page: int | None = Field(None, description="1-based page where the date appears")


class OutlineItem(BaseModel):
    heading: str
    page: int


class LlmDocumentFields(BaseModel):
    """Fields the LLM extracts; every value must be stated in the document."""

    document_type: DocumentType
    title: str | None = Field(None, description="Title as written in the document")
    language: str | None = Field(None, description="ISO 639-1 code, e.g. 'en', 'tr'")
    summary: str | None = Field(None, description="Two or three neutral sentences")
    parties: list[Party] = Field(default_factory=list)
    key_dates: list[KeyDate] = Field(default_factory=list)
    governing_law: str | None = Field(
        None, description="Governing law or jurisdiction, only if explicitly stated"
    )


class DocumentMetadata(LlmDocumentFields):
    document_type: DocumentType = "other"
    # Rule-based fields, never produced by the LLM:
    case_numbers: list[str] = Field(default_factory=list)
    outline: list[OutlineItem] = Field(default_factory=list)
    clause_categories: dict[str, int] = Field(default_factory=dict)
    llm_enriched: bool = False


class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    page_count: int
    chunk_count: int
    empty_pages: list[int]
    metadata: DocumentMetadata


# --- Chat ---------------------------------------------------------------------

class FinalAnswer(BaseModel):
    """Call exactly once to give the final answer to the user."""

    answer: str = Field(description="Concise answer in the user's language")
    # Defaults to True: grounding.verify() still demands a real chunk_id behind it.
    found: bool = Field(True, description="False when the document does not contain the answer")
    chunk_id: str | None = Field(None, description="chunk_id of the chunk that supports it")
    page_number: int | None = Field(None, description="Page of that chunk")
    reference_text: str | None = Field(
        None, description="Short exact quote (max ~40 words) copied from that chunk"
    )


class ChatRequest(BaseModel):
    document_id: str
    session_id: UUID  # conversation id, created by the browser
    client_id: str = Field(min_length=1, max_length=100)  # anonymous browser id
    question: str = Field(min_length=1, max_length=1000)


class ToolCallInfo(BaseModel):
    name: str
    args: dict


class ChatAnswer(BaseModel):
    answer: str
    page_number: int | None
    reference_text: str | None
    found: bool
    tool_calls: list[ToolCallInfo] = Field(default_factory=list)
    elapsed_seconds: float = 0.0


# --- Conversations ---------------------------------------------------------------

class ConversationSummary(BaseModel):
    session_id: str
    document_id: str
    filename: str
    title: str
    updated_at: datetime


class StoredMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    found: bool | None = None
    page_number: int | None = None
    reference_text: str | None = None


class ConversationDetail(BaseModel):
    session_id: str
    document: DocumentInfo
    messages: list[StoredMessage]
