"""Request / response models shared by the API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DocumentType = Literal[
    "contract", "court_decision", "legislation", "regulation", "pleading",
    "legal_opinion", "policy", "correspondence", "other",
]


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
