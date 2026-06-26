"""Structured logging via structlog.

The in-product agent is *Daedalus*; its logs/spans carry a ``[daedalus]``
component tag so they're greppable and recognisable in a trace. Product-level
logs stay under the default component.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(component: str = "ariadne") -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger().bind(component=component)


def daedalus_logger() -> structlog.stdlib.BoundLogger:
    """Logger for the in-product agent (tagged ``[daedalus]``)."""
    return get_logger("daedalus")
