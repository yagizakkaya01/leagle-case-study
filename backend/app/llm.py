"""Chat model factory.

Returns None when no API key is configured, so the app still runs (rule-based
metadata only) and tests never hit the network.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


def _gemini(model: str) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=2,  # retries 429/5xx; a bad request fails fast
    )


def get_chat_model() -> BaseChatModel | None:
    if not settings.GOOGLE_API_KEY:
        return None
    return _gemini(settings.GEMINI_MODEL)


def get_fallback_chat_model() -> BaseChatModel | None:
    if not settings.GOOGLE_API_KEY or not settings.GEMINI_FALLBACK_MODEL:
        return None
    return _gemini(settings.GEMINI_FALLBACK_MODEL)
