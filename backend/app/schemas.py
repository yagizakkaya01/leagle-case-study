"""Request / response models shared by the API."""
from __future__ import annotations

from pydantic import BaseModel


class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    page_count: int
    chunk_count: int
    empty_pages: list[int]
