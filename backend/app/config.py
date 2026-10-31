"""Application settings, loaded from environment variables / `.env`."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Resolved from the backend folder, so it works whatever the working directory is.
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # --- Server ---
    CORS_ORIGINS: str = "http://localhost:5173"

    # --- Uploads ---
    STORAGE_DIR: Path = BACKEND_DIR / "storage"
    MAX_UPLOAD_MB: int = 10
    MAX_PAGES: int = 50

    # --- Chunking (word based) ---
    CHUNK_SIZE: int = 200
    CHUNK_OVERLAP: int = 40

    # --- Persistence: empty = in memory; postgresql://user:pass@host:5432/db = persistent ---
    DATABASE_URL: str = ""

    # --- LLM (NVIDIA NIM via LangChain, see docs/MODEL_SELECTION.md) ---
    NVIDIA_API_KEY: str = ""
    NVIDIA_MODEL: str = "mistralai/mistral-large-4-1t-a52b"
    NVIDIA_EMBED_MODEL: str = "nvidia/nemotron-3-embed-1b"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 4096
    LLM_REASONING_EFFORT: str = "low"  # "low" | "medium" | "high"; empty = model default
    LLM_TIMEOUT_SECONDS: float = 60.0

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


settings = Settings()
