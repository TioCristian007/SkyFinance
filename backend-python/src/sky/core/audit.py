"""sky.core.audit — Registro de eventos auditables (ISO27001 A.12.4)."""
from __future__ import annotations

import json
from typing import Any

import sentry_sdk
from sqlalchemy import text

from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("audit")


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

    Acciones críticas:
        sync.start, sync.success, sync.error,
        account.connected, account.disconnected,
        key.access (trazabilidad en rotación de clave)
    """
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO public.audit_log
                        (user_id, action, resource_type, resource_id,
                         metadata, ip_address, user_agent)
                    VALUES
                        (:user_id, :action, :resource_type, :resource_id,
                         :metadata::jsonb, :ip_address::inet, :user_agent)
                """),
                {
                    "user_id": user_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "metadata": json.dumps(metadata or {}),
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                },
            )
    except Exception as exc:
        logger.error("audit_log_failed", action=action, error=str(exc))
        # capture_message es no-op si Sentry no está inicializado (dev)
        sentry_sdk.capture_message(
            f"audit_log_failed: {action}",
            level="warning",
        )
