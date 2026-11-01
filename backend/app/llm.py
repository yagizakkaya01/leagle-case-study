"""Chat model factory (NVIDIA NIM, see docs/MODEL_SELECTION.md).

Returns None when no API key is configured, so the app still runs (rule-based
metadata only) and tests never hit the network.
"""
from __future__ import annotations

from langchain_core.documents import BaseDocumentCompressor
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from langchain_core.runnables import Runnable
from langchain_nvidia_ai_endpoints import ChatNVIDIA, NVIDIAEmbeddings, NVIDIARerank
from pydantic import BaseModel

from app.config import settings

RERANK_RESULTS = 20  # at least as many as search asks for; its default of 5 would cut results


def get_chat_model() -> BaseChatModel | None:
    if not settings.NVIDIA_API_KEY:
        return None
    effort = settings.LLM_REASONING_EFFORT
    return ChatNVIDIA(
        model=settings.NVIDIA_MODEL,
        api_key=settings.NVIDIA_API_KEY,
        temperature=settings.LLM_TEMPERATURE,
        # Reasoning tokens count against this limit; too low a value cuts the answer off.
        max_completion_tokens=settings.LLM_MAX_TOKENS,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        usage_telemetry_enabled=False,
        model_kwargs={"reasoning_effort": effort} if effort else {},
    )


def get_embeddings() -> Embeddings | None:
    if not settings.NVIDIA_API_KEY:
        return None
    return NVIDIAEmbeddings(
        model=settings.NVIDIA_EMBED_MODEL,
        api_key=settings.NVIDIA_API_KEY,
        truncate="END",  # chunks are short; never fail on an over-long one
    )


def get_reranker() -> BaseDocumentCompressor | None:
    if not settings.NVIDIA_API_KEY or not settings.NVIDIA_RERANK_MODEL:
        return None
    return NVIDIARerank(
        model=settings.NVIDIA_RERANK_MODEL,
        api_key=settings.NVIDIA_API_KEY,
        top_n=RERANK_RESULTS,
        truncate="END",
    )


def structured_output(llm: BaseChatModel, schema: type[BaseModel]) -> Runnable:
    """Forces a single tool call whose arguments are `schema`, parsed into the model.

    ChatNVIDIA's `with_structured_output` sends an NVIDIA-specific `guided_json`
    field that the hosted endpoint rejects (HTTP 400); tool calling is supported
    by every model we use, so the same schema goes through as a forced tool call.
    """
    return llm.bind_tools([schema], tool_choice=schema.__name__) | PydanticToolsParser(
        tools=[schema], first_tool_only=True
    )
