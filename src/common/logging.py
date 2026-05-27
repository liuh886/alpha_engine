"""Centralized structured logging configuration.

Uses structlog when available, falls back to stdlib logging otherwise.
"""

from __future__ import annotations

import logging
import sys

try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:
    _HAS_STRUCTLOG = False

_configured = False


def setup_logging(*, development: bool = False) -> None:
    """Configure logging for the entire application.

    Call once at startup (e.g. in api_server.py). Safe to call multiple times;
    only the first call takes effect.
    """
    global _configured
    if _configured:
        return
    _configured = True

    log_level = logging.DEBUG if development else logging.INFO

    if _HAS_STRUCTLOG:
        shared_processors: list = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]

        # Configure stdlib logging first so structlog can route through it
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stderr,
            level=log_level,
        )

        if development:
            structlog.configure(
                processors=[*shared_processors, structlog.dev.ConsoleRenderer()],
                wrapper_class=structlog.stdlib.BoundLogger,
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                cache_logger_on_first_use=True,
            )
        else:
            structlog.configure(
                processors=[*shared_processors, structlog.processors.JSONRenderer()],
                wrapper_class=structlog.stdlib.BoundLogger,
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                cache_logger_on_first_use=True,
            )
    else:
        logging.basicConfig(
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            stream=sys.stderr,
            level=log_level,
        )


def get_logger(name: str):
    """Return a named logger (structlog if available, stdlib otherwise).

    Usage::

        from src.common.logging import get_logger
        log = get_logger(__name__)
        log.info("thing_happened", key="value")
    """
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return logging.getLogger(name)
