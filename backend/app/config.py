"""Application settings, loaded from environment variables / `.env`."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Server ---
    CORS_ORIGINS: str = "http://localhost:5173"

    # --- Uploads ---
    STORAGE_DIR: Path = Path("storage")
    MAX_UPLOAD_MB: int = 10
    MAX_PAGES: int = 50

    # --- Chunking (word based) ---
    CHUNK_SIZE: int = 200
    CHUNK_OVERLAP: int = 40

    # --- LLM (NVIDIA NIM via LangChain, see docs/MODEL_SELECTION.md) ---
    NVIDIA_API_KEY: str = ""
    NVIDIA_MODEL: str = "google/gemma-4-31b-it"
    LLM_TEMPERATURE: float = 0.0
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
