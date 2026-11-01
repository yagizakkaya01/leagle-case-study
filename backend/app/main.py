"""FastAPI application entry point."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, conversations, documents
from app.config import settings
from app.dependencies import get_document_store
from app.logging_config import RequestLogMiddleware, setup_logging

setup_logging()
log = logging.getLogger(__name__)

PURGE_INTERVAL_SECONDS = 15 * 60


def _purge_loop(stop: threading.Event) -> None:
    """Deletes documents (and their chats) older than RETENTION_HOURS, every 15 min."""
    while not stop.is_set():
        try:
            cutoff = datetime.now(UTC) - timedelta(hours=settings.RETENTION_HOURS)
            get_document_store().purge_older_than(cutoff)
        except Exception:  # never let a failed run stop future runs
            log.warning("Retention purge failed", exc_info=True)
        stop.wait(PURGE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = threading.Event()
    if settings.RETENTION_HOURS > 0:
        threading.Thread(target=_purge_loop, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Legal Document Chat API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLogMiddleware)  # added last: outermost, so it times everything


@app.exception_handler(HTTPException)
async def log_rejection(request: Request, exc: HTTPException):
    log.info("rejected status=%d detail=%r", exc.status_code, exc.detail)
    return await http_exception_handler(request, exc)


app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(conversations.router)


@app.get("/api/settings", tags=["settings"])
def public_settings() -> dict:
    """What the UI needs to know about this deployment (demo banner and retention)."""
    return {
        "demo_notice": settings.DEMO_NOTICE or None,
        "retention_hours": settings.RETENTION_HOURS or None,
    }


@app.get("/healthz", tags=["health"])
def healthz() -> dict[str, bool]:
    return {"ok": True}
