"""sky.core.sentry_utils — Init de Sentry y filtrado de PII."""
from __future__ import annotations

import json
import re
from typing import Any

import sentry_sdk

from sky.core.config import settings
from sky.core.logging import get_logger

logger = get_logger("sentry")

# ── Credenciales a eliminar por nombre de clave (case-insensitive) ─────────────
_SCRUB_KEYS = frozenset({
    # Credenciales bancarias
    "encrypted_rut",    # credencial AES-256-GCM — nunca debe aparecer en errores
    "encrypted_pass",   # ídem
    "password",         # contraseña en texto plano
    "rut",              # identificador nacional chileno (PII alta sensibilidad)
    "clave",            # sinónimo de contraseña en contexto bancario chileno
    "credential",       # genérico
    "credentials",      # ídem plural
    # HTTP headers sensibles (HTTP headers son case-insensitive → comparar con k.lower())
    "authorization",    # Bearer token / Basic auth
    "cookie",           # Session cookies
    "x-cron-secret",    # Secreto del cron interno de Sky
})

# ── Patrones en string values a eliminar ──────────────────────────────────────
_TOKEN_RE = re.compile(
    r"\bsk-(?:ant-)?[A-Za-z0-9\-_]{10,}\b"
    # Cubre: sk-ant-api03-... (Anthropic), sk-proj-... (otros)
    # Umbral mínimo 10 chars para evitar falsos positivos en hashes cortos
)
_RUT_CL_RE = re.compile(
    r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dkK]\b"
    # Cubre: 12.345.678-9 · 12345678-9 · 12345678K · 9.876.543-k
)


def _scrub(obj: Any, depth: int = 0) -> Any:
    """
    Recursivamente elimina PII de un objeto arbitrario.
    Depth cap en 10 para evitar recursión infinita en estructuras circulares.
    Comparación de claves es case-insensitive (HTTP headers son case-insensitive).
    """
    if depth > 10:
        return "[TRUNCATED]"
    if isinstance(obj, str):
        if _TOKEN_RE.search(obj) or _RUT_CL_RE.search(obj):
            return "[REDACTED]"
        return obj
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if k.lower() in _SCRUB_KEYS else _scrub(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub(item, depth + 1) for item in obj]
    return obj


def _event_contains_sensitive(event: Any) -> bool:
    """
    Post-scrub check: serializa el evento a JSON y busca patrones sensibles.
    Captura PII que sobrevivió _scrub (ej: token como clave de dict,
    datos truncados por depth cap, tipos no-string con repr sensible).
    Si no se puede serializar, asume sensible y descarta.
    """
    try:
        text = json.dumps(event, default=str)
        return bool(_TOKEN_RE.search(text) or _RUT_CL_RE.search(text))
    except Exception:
        return True  # No se pudo verificar → asumir sensible → descartar


def before_send(
    event: dict[str, Any], hint: dict[str, Any]
) -> dict[str, Any] | None:
    """
    Sentry before_send: pipeline de dos pasos para eliminar PII antes de enviar.

    Paso 1 — _scrub (walk recursivo):
      • Claves en _SCRUB_KEYS (case-insensitive) → [REDACTED] en cualquier parte
        del evento: exception.stacktrace.frames[].vars, breadcrumbs[].data,
        request.data, request.headers, y cualquier estructura arbitraria.
      • String values con token (sk-ant-..) o RUT chileno → [REDACTED].
      • Depth > 10 → [TRUNCATED].

    Paso 2 — _event_contains_sensitive (post-scrub check):
      • Serializa el evento scrubbed a JSON y aplica los regexes.
      • Si detecta pattern → return None (drop). Captura PII que sobrevivió
        el paso 1 (ej: token Anthropic como clave de dict, no como valor).

    Fail-safe: cualquier excepción en cualquier paso → return None.
    Es preferible perder el evento que enviar datos de usuario sin sanitizar.
    """
    try:
        scrubbed = _scrub(event)
        if _event_contains_sensitive(scrubbed):
            logger.warning("sentry_post_scrub_sensitive_dropping_event")
            return None
        return scrubbed  # type: ignore[no-any-return]
    except Exception:
        logger.warning("sentry_scrub_failed_dropping_event")
        return None


def init_sentry() -> None:
    """
    Inicializa Sentry SDK. No-op si SENTRY_DSN está vacío (dev mode).
    Llamar desde lifespan de API y startup del worker.
    """
    if not settings.sentry_dsn:
        logger.info("sentry_disabled", reason="SENTRY_DSN not configured")
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1 if settings.is_production else 1.0,
        before_send=before_send,
        environment="production" if settings.is_production else "development",
    )
    logger.info("sentry_initialized", env=settings.node_env)
