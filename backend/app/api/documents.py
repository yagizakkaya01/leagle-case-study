"""PDF upload endpoint."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.config import settings
from app.dependencies import get_document_store
from app.schemas import DocumentInfo
from app.services.document_store import DocumentStore, StoredDocument
from app.services.pdf_processing import PdfProcessingError

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=DocumentInfo)
def upload_document(
    file: UploadFile,
    store: Annotated[DocumentStore, Depends(get_document_store)],
) -> DocumentInfo:
    # Plain `def`: pdfplumber is blocking, so FastAPI runs this in a worker thread.
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than {settings.MAX_UPLOAD_MB} MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Only PDF files are accepted.")

    filename = Path(file.filename or "document.pdf").name
    try:
        doc = store.add(data, filename)
    except PdfProcessingError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not doc.chunks:
        raise HTTPException(422, "No extractable text was found in this PDF.")
    return to_document_info(doc)


def to_document_info(doc: StoredDocument) -> DocumentInfo:
    return DocumentInfo(
        document_id=doc.document_id,
        filename=doc.filename,
        page_count=doc.page_count,
        chunk_count=len(doc.chunks),
        empty_pages=doc.empty_pages,
        metadata=doc.metadata,
    )
