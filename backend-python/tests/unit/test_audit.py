"""Tests del helper core/audit.py (Fase 11 — R18)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_engine() -> MagicMock:
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_ctx
    return mock_engine, mock_conn


async def _call_log_event(**kwargs: Any) -> None:
    from sky.core.audit import log_event
    await log_event(**kwargs)


async def test_log_sync_start() -> None:
    """log_event sync.start ejecuta INSERT."""
    engine, conn = _mock_engine()
    with patch("sky.core.audit.get_engine", return_value=engine):
        await _call_log_event(
            action="sync.start",
            user_id="user-uuid",
            resource_type="bank_account",
            resource_id="account-uuid",
            metadata={"bank_id": "bchile"},
        )
    conn.execute.assert_called_once()
    sql = str(conn.execute.call_args[0][0])
    assert "audit_log" in sql
    params = conn.execute.call_args[0][1]
    assert params["action"] == "sync.start"
    # Verificar que metadata no contiene PII
    import json
    meta = json.loads(params["metadata"])
    pii_keys = {"rut", "password", "encrypted_rut", "encrypted_pass", "clave"}
    assert not pii_keys.intersection(meta.keys()), f"PII encontrado en metadata: {meta}"


async def test_log_sync_success() -> None:
    """log_event sync.success ejecuta INSERT con new_transactions y elapsed_ms."""
    engine, conn = _mock_engine()
    with patch("sky.core.audit.get_engine", return_value=engine):
        await _call_log_event(
            action="sync.success",
            user_id="user-uuid",
            resource_type="bank_account",
            resource_id="account-uuid",
            metadata={"bank_id": "bchile", "new_transactions": 5, "elapsed_ms": 1200},
        )
    conn.execute.assert_called_once()
    params = conn.execute.call_args[0][1]
    assert params["action"] == "sync.success"
    import json
    meta = json.loads(params["metadata"])
    assert meta["new_transactions"] == 5
    pii_keys = {"rut", "password", "encrypted_rut", "encrypted_pass"}
    assert not pii_keys.intersection(meta.keys())


async def test_log_sync_error() -> None:
    """log_event sync.error ejecuta INSERT con error_type (no mensaje completo)."""
    engine, conn = _mock_engine()
    with patch("sky.core.audit.get_engine", return_value=engine):
        await _call_log_event(
            action="sync.error",
            user_id="user-uuid",
            resource_type="bank_account",
            resource_id="account-uuid",
            metadata={"bank_id": "bchile", "error_type": "AuthenticationError"},
        )
    params = conn.execute.call_args[0][1]
    assert params["action"] == "sync.error"
    import json
    meta = json.loads(params["metadata"])
    assert meta["error_type"] == "AuthenticationError"


async def test_log_account_connected() -> None:
    """log_event account.connected ejecuta INSERT con bank_id."""
    engine, conn = _mock_engine()
    with patch("sky.core.audit.get_engine", return_value=engine):
        await _call_log_event(
            action="account.connected",
            user_id="user-uuid",
            resource_type="bank_account",
            resource_id="new-account-uuid",
            metadata={"bank_id": "bchile"},
            ip_address="192.168.1.1",
        )
    params = conn.execute.call_args[0][1]
    assert params["action"] == "account.connected"
    assert params["ip_address"] == "192.168.1.1"


async def test_log_db_failure_no_raise() -> None:
    """Si DB lanza excepción → log_event swallows + structlog.error (no re-raise)."""
    bad_engine = MagicMock()
    bad_ctx = MagicMock()
    bad_ctx.__aenter__ = AsyncMock(side_effect=Exception("DB connection refused"))
    bad_ctx.__aexit__ = AsyncMock(return_value=False)
    bad_engine.begin.return_value = bad_ctx

    with (
        patch("sky.core.audit.get_engine", return_value=bad_engine),
        patch("sky.core.audit.sentry_sdk") as mock_sentry,
    ):
        # No debe levantar excepción
        await _call_log_event(
            action="sync.start",
            user_id="user-uuid",
            resource_type="bank_account",
            resource_id="account-uuid",
        )
        # Sentry notificado
        mock_sentry.capture_message.assert_called_once()
        assert "audit_log_failed" in str(mock_sentry.capture_message.call_args)
