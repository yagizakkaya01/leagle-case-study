"""Standard Python logging setup (console only)."""
from __future__ import annotations

import logging

from app.config import settings

_NOISY = ("httpx", "httpx2", "httpcore", "pdfminer", "urllib3")


def setup_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    for lib in _NOISY:
        logging.getLogger(lib).setLevel(logging.WARNING)
