"""Tests del helper core/audit.py (Fase 11 — R18, ISO27001 A.12.4).

API pública de log_event() preserva legibilidad (action, user_id, metadata),
mapea internamente al schema real con hashing:
    action="sync.success" → event_type="bank_sync", outcome="success"
    user_id="uuid"        → user_hash=sha256(uuid+salt)
    metadata={...}        → detail=jsonb(...)
    ip_address="ip"       → ip_hash=sha256(ip+salt)

Acciones desconocidas → warning + skip INSERT (nunca insertar valores inválidos).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_engine() -> tuple[MagicMock, AsyncMock]:
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


# ── Mapping action → (event_type, outcome) ───────────────────────────────────

async def test_log_sync_success_maps_to_bank_sync_success() -> None:
    engine, conn = _mock_engine()
    with patch("sky.core.audit.get_engine", return_value=engine):
        await _call_log_event(
            action="sync.success",
            user_id="user-uuid",
            resource_type="bank_account",
            resource_id="account-uuid",
            metadata={"bank_id": "bchile"},
        )
    conn.execute.assert_called_once()
    sql = str(conn.execute.call_args[0][0])
    assert "audit_log" in sql
    params = conn.execute.call_args[0][1]
    assert params["event_type"] == "bank_sync"
    assert params["outcome"] == "success"
    # Sin user_id raw — debe ser hash
    assert "user_id" not in params
    detail = json.loads(params["detail"])
    pii_keys = {"rut", "password", "encrypted_rut", "encrypted_pass", "clave"}
    assert not pii_keys.intersection(detail.keys()), f"PII en detail: {detail}"


async def test_unknown_action_no_insert_logs_warning() -> None:
    """Acción no mapeada → no INSERT + warning (nunca insertar valores inválidos en DB)."""
    engine, conn = _mock_engine()
    with (
        patch("sky.core.audit.get_engine", return_value=engine),
        patch("sky.core.audit.logger") as mock_logger,
    ):
        await _call_log_event(action="sync.start", user_id="user-uuid")
    conn.execute.assert_not_called()
    mock_logger.warning.assert_called_once()
    assert "audit_unknown_action_skipped" in str(mock_logger.warning.call_args)


async def test_log_sync_success_outcome_success() -> None:
    engine, conn = _mock_engine()
    with patch("sky.core.audit.get_engine", return_value=engine):
        await _call_log_event(
            action="sync.success",
            user_id="user-uuid",
            resource_type="bank_account",
            resource_id="account-uuid",
            metadata={"bank_id": "bchile", "new_transactions": 5, "elapsed_ms": 1200},
        )
    params = conn.execute.call_args[0][1]
    assert params["event_type"] == "bank_sync"
    assert params["outcome"] == "success"
    detail = json.loads(params["detail"])
    assert detail["new_transactions"] == 5


async def test_log_sync_error_outcome_failure() -> None:
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
    assert params["event_type"] == "bank_sync"
    assert params["outcome"] == "failure"
    detail = json.loads(params["detail"])
    assert detail["error_type"] == "AuthenticationError"


async def test_log_account_connected() -> None:
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
    assert params["event_type"] == "bank_connected"
    assert params["outcome"] == "success"
    # IP nunca debe persistirse raw
    assert "ip_address" not in params
    assert "ip_hash" in params


# ── Hashing user_hash / ip_hash ──────────────────────────────────────────────

async def test_user_hash_is_sha256_of_id_plus_salt() -> None:
    """Con salt configurada, user_hash = sha256(user_id + salt)."""
    engine, conn = _mock_engine()
    test_salt = "test_salt_for_unit_tests_abc123"
    expected_hash = hashlib.sha256(f"user-uuid{test_salt}".encode()).hexdigest()

    with (
        patch("sky.core.audit.get_engine", return_value=engine),
        patch("sky.core.audit.settings") as mock_settings,
    ):
        mock_settings.audit_log_salt = test_salt
        await _call_log_event(
            action="sync.success",
            user_id="user-uuid",
            resource_type="bank_account",
            resource_id="account-uuid",
        )
    params = conn.execute.call_args[0][1]
    assert params["user_hash"] == expected_hash


async def test_user_hash_changes_with_salt() -> None:
    """Salts diferentes → hashes diferentes para el mismo user_id."""
    engine, conn1 = _mock_engine()

    with (
        patch("sky.core.audit.get_engine", return_value=engine),
        patch("sky.core.audit.settings") as mock_settings,
    ):
        mock_settings.audit_log_salt = "salt-A"
        await _call_log_event(action="sync.success", user_id="same-user")
    hash_a = conn1.execute.call_args[0][1]["user_hash"]

    engine, conn2 = _mock_engine()
    with (
        patch("sky.core.audit.get_engine", return_value=engine),
        patch("sky.core.audit.settings") as mock_settings,
    ):
        mock_settings.audit_log_salt = "salt-B"
        await _call_log_event(action="sync.success", user_id="same-user")
    hash_b = conn2.execute.call_args[0][1]["user_hash"]

    assert hash_a != hash_b
    assert hash_a != "same-user"  # nunca persiste raw


async def test_ip_hash_is_sha256_of_ip_plus_salt() -> None:
    engine, conn = _mock_engine()
    test_salt = "test_salt_abc"
    expected = hashlib.sha256(f"192.168.1.1{test_salt}".encode()).hexdigest()

    with (
        patch("sky.core.audit.get_engine", return_value=engine),
        patch("sky.core.audit.settings") as mock_settings,
    ):
        mock_settings.audit_log_salt = test_salt
        await _call_log_event(
            action="account.connected",
            user_id="user-uuid",
            ip_address="192.168.1.1",
        )
    assert conn.execute.call_args[0][1]["ip_hash"] == expected


async def test_no_pii_persisted() -> None:
    """Verifica que user_id raw NUNCA aparece en params del INSERT."""
    engine, conn = _mock_engine()
    with (
        patch("sky.core.audit.get_engine", return_value=engine),
        patch("sky.core.audit.settings") as mock_settings,
    ):
        mock_settings.audit_log_salt = "any-salt"
        await _call_log_event(
            action="sync.success",
            user_id="12345678-9",  # parece RUT chileno
            ip_address="201.220.10.5",
            metadata={"bank_id": "bchile"},
        )
    params = conn.execute.call_args[0][1]
    # Ningún field debe contener el user_id raw
    for k, v in params.items():
        assert v != "12345678-9", f"user_id raw leakeó en field '{k}'"
        assert v != "201.220.10.5", f"ip raw leakeó en field '{k}'"


# ── SQL syntax — no ::jsonb con asyncpg ──────────────────────────────────────

async def test_sql_uses_cast_not_postgres_cast_syntax() -> None:
    """El SQL debe usar CAST(:detail AS jsonb), no :detail::jsonb.

    asyncpg con named params interpreta '::' como el inicio de un bind param y
    lanza PostgresSyntaxError. Este test blinda la regresión del bug B-3.
    """
    engine, conn = _mock_engine()
    with patch("sky.core.audit.get_engine", return_value=engine):
        await _call_log_event(action="sync.success", user_id="user-uuid")
    sql = str(conn.execute.call_args[0][0])
    assert "::jsonb" not in sql, "SQL usa ::jsonb — rompe asyncpg con named params (bug B-3)"
    assert "CAST" in sql and "AS jsonb" in sql, "SQL debe usar CAST(:detail AS jsonb)"


# ── Fail-safe ────────────────────────────────────────────────────────────────

async def test_log_db_failure_no_raise_and_sentry_notified() -> None:
    """Si DB lanza excepción → log_event swallows + Sentry capture (no re-raise)."""
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
            action="sync.success",
            user_id="user-uuid",
            resource_type="bank_account",
            resource_id="account-uuid",
        )
        mock_sentry.capture_message.assert_called_once()
        assert "audit_log_failed" in str(mock_sentry.capture_message.call_args)


# ── Invariante: _ACTION_MAP solo produce valores permitidos por la DB ─────────

def test_action_map_only_valid_db_values() -> None:
    """Todos los (event_type, outcome) en _ACTION_MAP existen en los CHECK constraints."""
    from sky.core.audit import _ACTION_MAP

    valid_event_types = {
        "user_created", "user_deleted", "profile_updated",
        "bank_connected", "bank_disconnected", "bank_sync",
        "credentials_rotated", "data_export_requested", "data_export_delivered",
        "deletion_requested", "deletion_executed",
        "consent_granted", "consent_revoked", "admin_access",
    }
    valid_outcomes = {"success", "failure", "partial"}

    for action, (event_type, outcome) in _ACTION_MAP.items():
        assert event_type in valid_event_types, (
            f"action='{action}' → event_type='{event_type}' NO existe en el CHECK constraint"
        )
        assert outcome in valid_outcomes, (
            f"action='{action}' → outcome='{outcome}' NO existe en el CHECK constraint"
        )
