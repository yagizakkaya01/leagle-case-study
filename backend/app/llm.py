"""Chat model factory (NVIDIA NIM, see docs/MODEL_SELECTION.md).

Returns None when no API key is configured, so the app still runs (rule-based
metadata only) and tests never hit the network.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from app.config import settings


def get_chat_model() -> BaseChatModel | None:
    if not settings.NVIDIA_API_KEY:
        return None
    return ChatNVIDIA(
        model=settings.NVIDIA_MODEL,
        api_key=settings.NVIDIA_API_KEY,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        usage_telemetry_enabled=False,
    )
