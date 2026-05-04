"""
sky.core.logging — structlog JSON con filtro de PII.

Nunca logea: passwords, rut, claves, tokens de acceso.
Siempre logea: bank_id, user_id (para debug), duración, errores sanitizados.
"""
from __future__ import annotations

import re
from typing import Any

import structlog

_PII_PATTERNS = re.compile(
    r"(password|clave|rut|secret|token|api_key|authorization)",
    re.IGNORECASE,
)


def _filter_pii(_: object, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Reemplaza valores sensibles en los logs."""
    for key in list(event_dict.keys()):
        if _PII_PATTERNS.search(key):
            event_dict[key] = "***REDACTED***"
    return event_dict


def setup_logging(json_output: bool = True) -> None:
    """Configurar structlog. Llamar una vez al inicio del proceso."""
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _filter_pii,
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "") -> structlog.BoundLogger:
    """Obtener un logger con nombre."""
    return structlog.get_logger(component=name)  # type: ignore[no-any-return]
