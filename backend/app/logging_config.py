"""Standard Python logging setup (console only) and one log line per request.

Lines are `key=value`, and every line a request causes carries its id. Documents can be
confidential, so our log lines hold counts and short ids: never the question, the answer,
a quote, a filename or a full document id (that id is enough to download the file).
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar

from app.config import settings

_NOISY = ("httpx", "httpx2", "httpcore", "pdfminer", "urllib3", "azure", "uvicorn.access")
_QUIET_PATHS = {"/healthz"}  # the container health check would fill the log
_DOCUMENT_ID = re.compile(r"[0-9a-f]{64}")

log = logging.getLogger(__name__)
request_id: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


def setup_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(_RequestIdFilter())
    for lib in _NOISY:
        logging.getLogger(lib).setLevel(logging.WARNING)


def short_id(document_id: str) -> str:
    return document_id[:12]


class RequestLogMiddleware:
    """Plain ASGI: streamed answers pass through unbuffered and are timed to their end."""

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in _QUIET_PATHS:
            await self._app(scope, receive, send)
            return

        current = uuid.uuid4().hex[:8]
        token = request_id.set(current)
        started = time.perf_counter()
        status = 500  # stays so if the app crashes before it responds

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []),
                                      (b"x-request-id", current.encode())]
            await send(message)

        try:
            await self._app(scope, receive, send_with_id)
        except Exception:
            log.exception("request crashed")
            raise
        finally:
            path = _DOCUMENT_ID.sub(lambda m: short_id(m[0]), scope["path"])
            log.info("request method=%s path=%s status=%d ms=%d", scope["method"], path, status,
                     (time.perf_counter() - started) * 1000)
            request_id.reset(token)
