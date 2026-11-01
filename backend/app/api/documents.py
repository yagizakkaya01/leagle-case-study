"""PDF upload endpoint."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi import Path as PathParam

from app.config import settings
from app.dependencies import enforce_upload_limit, get_document_store
from app.logging_config import short_id
from app.schemas import DocumentInfo, HighlightBox, HighlightRequest
from app.services.document_store import DocumentStore, StoredDocument
from app.services.pdf_processing import PdfProcessingError
from app.services.quote_location import locate_quote

log = logging.getLogger(__name__)
router =APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=DocumentInfo, dependencies=[Depends(enforce_upload_limit)])
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


@router.get("/{document_id}/file")
def download_document(
    document_id: Annotated[str, PathParam(pattern="^[0-9a-f]{64}$")],
    store: Annotated[DocumentStore, Depends(get_document_store)],
) -> Response:
    # The id is the file's sha256: only someone who already has the file or the id can ask.
    data = store.load_file(document_id)
    if data is None:
        raise HTTPException(404, "The original file is no longer available.")
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": "inline",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=3600",
    })


@router.post("/{document_id}/highlights", response_model=list[HighlightBox])
def find_highlights(
    document_id: Annotated[str, PathParam(pattern="^[0-9a-f]{64}$")],
    body: HighlightRequest,
    store: Annotated[DocumentStore, Depends(get_document_store)],
) -> list[HighlightBox]:
    data = store.load_file(document_id)
    if data is None:
        raise HTTPException(404, "The original file is no longer available.")
    boxes = locate_quote(data, body.page, body.quote)
    if not boxes:
        log.info("highlight found nothing doc=%s page=%d quote_chars=%d",
                 short_id(document_id), body.page, len(body.quote))
    return boxes


def to_document_info(doc: StoredDocument) -> DocumentInfo:
    return DocumentInfo(
        document_id=doc.document_id,
        filename=doc.filename,
        page_count=doc.page_count,
        chunk_count=len(doc.chunks),
        empty_pages=doc.empty_pages,
        metadata=doc.metadata,
    )
