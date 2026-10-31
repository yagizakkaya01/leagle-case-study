"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import documents
from app.config import settings
from app.logging_config import setup_logging

setup_logging()

app = FastAPI(title="Legal Document Chat API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(documents.router)


@app.get("/healthz", tags=["health"])
def healthz() -> dict[str, bool]:
    return {"ok": True}
