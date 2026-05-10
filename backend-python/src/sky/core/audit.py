"""sky.core.audit — Registro de eventos auditables (ISO27001 A.12.4).

Schema real en public.audit_log (privacy-by-design):
    id (uuid), event_type (text), user_hash (text), resource_type (text),
    resource_id (uuid), outcome (text), detail (jsonb), ip_hash (text),
    user_agent (text), occurred_at (timestamptz)

NUNCA se persiste user_id raw ni IP raw. user_hash y ip_hash son SHA-256
con salt fijo (settings.audit_log_salt) que NO se rota — mantener correlación
histórica es requisito para auditoría.

API pública: log_event() mantiene parámetros legibles (action, user_id, metadata,
ip_address) y mapea internamente al schema real con hashing.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import sentry_sdk
from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("audit")


# Mapping de "action" (API pública) → (event_type, outcome) en el schema real.
# Convención: <recurso>.<resultado>. event_type captura la acción base,
# outcome captura success/failure/etc separadamente para queries de auditoría.
_ACTION_MAP: dict[str, tuple[str, str]] = {
    "sync.start":            ("sync",    "started"),
    "sync.success":          ("sync",    "success"),
    "sync.error":            ("sync",    "failure"),
    "account.connected":     ("account", "connected"),
    "account.disconnected":  ("account", "disconnected"),
    "key.access":            ("key",     "accessed"),
    "key.rotation":          ("key",     "rotated"),
}


def _hash(value: str | None) -> str | None:
    """SHA-256(value + audit_log_salt). Determinístico — mismo input → mismo hash."""
    if not value:
        return None
    salt = settings.audit_log_salt
    if not salt:
        # Modo dev: sin salt, hashing es no-op preserve-as-is. En prod este
        # camino no debería tomarse (settings.audit_log_salt es required vía
        # fail-fast en main.py cuando is_production=True).
        return value
    return hashlib.sha256(f"{value}{salt}".encode()).hexdigest()


async def log_event(
    *,
    action: str,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """
    Inserta evento en public.audit_log. Fire-and-forget: si falla, loguea error
    y notifica Sentry, pero NO propaga excepción (nunca bloquear hot path).

    NUNCA incluir PII en metadata: sin rut, password, ni tokens bancarios.
    Audit log es inmutable: solo INSERT, sin UPDATE ni DELETE.

    Acciones críticas registradas en _ACTION_MAP:
        sync.start, sync.success, sync.error,
        account.connected, account.disconnected,
        key.access, key.rotation
    """
    try:
        event_type, outcome = _ACTION_MAP.get(action, (action, "info"))
        user_hash = _hash(user_id)
        ip_hash = _hash(ip_address)

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO public.audit_log
                        (event_type, user_hash, resource_type, resource_id,
                         outcome, detail, ip_hash, user_agent)
                    VALUES
                        (:event_type, :user_hash, :resource_type, :resource_id,
                         :outcome, :detail::jsonb, :ip_hash, :user_agent)
                """),
                {
                    "event_type":    event_type,
                    "user_hash":     user_hash,
                    "resource_type": resource_type,
                    "resource_id":   resource_id,
                    "outcome":       outcome,
                    "detail":        json.dumps(metadata or {}),
                    "ip_hash":       ip_hash,
                    "user_agent":    user_agent,
                },
            )
    except Exception as exc:
        logger.error("audit_log_failed", action=action, error=str(exc))
        # capture_message es no-op si Sentry no está inicializado (dev)
        sentry_sdk.capture_message(
            f"audit_log_failed: {action}",
            level="warning",
        )
