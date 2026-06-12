"""
tests/unit/test_failure_taxonomy.py — Taxonomía C1 de fallos de sync (sprint 2026-06-12).

La clasificación canónica vive en contracts: cada kind tiene mensaje de
usuario y acción propios, y el audit_log lleva failure_kind para que la
causa real sea visible sin cavar en la DB.
"""

from __future__ import annotations

from sky.ingestion.contracts import (
    FAILURE_ACTIONS,
    FAILURE_USER_MESSAGES,
    AuthenticationError,
    CircuitOpenError,
    FieldFillError,
    RecoverableIngestionError,
    SyncFailureKind,
    TwoFactorTimeoutError,
    classify_failure_chain,
    classify_sync_failure,
)
from sky.worker.banking_sync import RECONNECT_USER_MSG

# ── Clasificación de una excepción ───────────────────────────────────────────


def test_clasifica_2fa_timeout():
    kind = classify_sync_failure(TwoFactorTimeoutError("timeout 2fa"))
    assert kind is SyncFailureKind.NEEDS_2FA


def test_clasifica_field_fill():
    kind = classify_sync_failure(FieldFillError("password", expected_len=8, got_len=7))
    assert kind is SyncFailureKind.FIELD_FILL_FAILED


def test_clasifica_auth_error_tipado():
    kind = classify_sync_failure(AuthenticationError("Error de login: no son correctos"))
    assert kind is SyncFailureKind.WRONG_CREDENTIALS


def test_clasifica_circuit_open():
    kind = classify_sync_failure(CircuitOpenError("circuito abierto para scraper.bchile"))
    assert kind is SyncFailureKind.BANK_TEMPORARY


def test_clasifica_antibot_antes_que_credenciales():
    """'No se encontró el campo de clave' es anti-bot/form roto, NO clave mala."""
    kind = classify_sync_failure(
        RecoverableIngestionError("No se encontró el campo de clave")
    )
    assert kind is SyncFailureKind.ANTIBOT


def test_clasifica_credenciales_por_texto():
    kind = classify_sync_failure(RecoverableIngestionError("clave incorrecta para usuario"))
    assert kind is SyncFailureKind.WRONG_CREDENTIALS


def test_clasifica_timeout_como_temporal():
    kind = classify_sync_failure(RecoverableIngestionError("ETIMEDOUT after 30s"))
    assert kind is SyncFailureKind.BANK_TEMPORARY


def test_clasifica_desconocido():
    kind = classify_sync_failure(RecoverableIngestionError("algo raro interno xyz"))
    assert kind is SyncFailureKind.UNKNOWN


# ── Clasificación de cadenas ─────────────────────────────────────────────────


def test_chain_2fa_gana_sobre_generico():
    kind = classify_failure_chain([
        RecoverableIngestionError("generic error"),
        TwoFactorTimeoutError("2fa timeout"),
    ])
    assert kind is SyncFailureKind.NEEDS_2FA


def test_chain_field_fill_gana_sobre_temporal():
    kind = classify_failure_chain([
        RecoverableIngestionError("ETIMEDOUT"),
        FieldFillError("password", expected_len=8, got_len=7),
    ])
    assert kind is SyncFailureKind.FIELD_FILL_FAILED


def test_chain_vacia_es_unknown():
    assert classify_failure_chain([]) is SyncFailureKind.UNKNOWN


# ── Mensajes y acciones ──────────────────────────────────────────────────────


def test_todos_los_kinds_tienen_mensaje_y_accion():
    for kind in SyncFailureKind:
        assert kind in FAILURE_USER_MESSAGES, f"falta mensaje para {kind}"
        assert kind in FAILURE_ACTIONS, f"falta acción para {kind}"


def test_reconnect_msg_viene_de_la_taxonomia():
    """Un solo lugar para el mensaje de reconexión: la taxonomía C1."""
    assert FAILURE_USER_MESSAGES[SyncFailureKind.WRONG_CREDENTIALS] == RECONNECT_USER_MSG
    assert FAILURE_ACTIONS[SyncFailureKind.WRONG_CREDENTIALS] == "reconnect"


def test_field_fill_no_culpa_al_usuario():
    msg = FAILURE_USER_MESSAGES[SyncFailureKind.FIELD_FILL_FAILED]
    assert "no es un problema de tu clave" in msg
