"""Tests unitarios de sync_bank_account con mocks."""
import asyncio
from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sky.core.errors import RateLimitError
from sky.ingestion.contracts import (
    PROGRESS_2FA_WAIT_PREFIX,
    PROGRESS_LOGIN_OK,
    AccountBalance,
    AllSourcesFailedError,
    CanonicalMovement,
    CircuitOpenError,
    IngestionResult,
    MovementSource,
    RecoverableIngestionError,
    SourceKind,
    TwoFactorTimeoutError,
)
from sky.ingestion.contracts import AuthenticationError as BankAuthError
from sky.worker.banking_sync import (
    RECONNECT_USER_MSG,
    _mark_error,
    _mark_needs_reconnection,
    _mark_syncing,
    _mark_waiting_2fa,
    _persist_movements,
    _user_message_for_failure,
    sync_bank_account,
)


@pytest.fixture(autouse=True)
def _disable_aria_fireforget(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-4: estos tests no verifican ARIA. Sin esto, el success-path dispara
    `asyncio.create_task(_track_aria_events(...))` y, al cerrarse el event loop
    del test, queda una corutina AsyncMock sin await (RuntimeWarning)."""
    from sky.worker import banking_sync
    monkeypatch.setattr(banking_sync.settings, "sync_aria_enabled", False)


@pytest.fixture
def fake_router() -> MagicMock:
    r = MagicMock()
    r.ingest = AsyncMock(return_value=IngestionResult(
        balance=AccountBalance(balance_clp=1_000_000, as_of=datetime(2026, 4, 15)),
        movements=[
            CanonicalMovement(
                external_id="bchile_abc123",
                amount_clp=-5000,
                raw_description="STARBUCKS",
                occurred_at=date(2026, 4, 15),
                movement_source=MovementSource.ACCOUNT,
                source_kind=SourceKind.SCRAPER,
            )
        ],
        source_kind=SourceKind.SCRAPER,
        source_identifier="scraper.bchile",
        elapsed_ms=12_345,
    ))
    return r


@pytest.fixture
def fake_arq_pool() -> MagicMock:
    p = MagicMock()
    p.enqueue_job = AsyncMock()
    return p


def _make_advisory_lock_cm(acquired: bool) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=acquired)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _make_engine_with_row(row: dict) -> MagicMock:
    """Mock engine que devuelve `row` en el SELECT y un dummy en el UPDATE."""
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = row
    mock_select_result = MagicMock()
    mock_select_result.mappings.return_value = mock_mappings

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=[mock_select_result, MagicMock()])

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_ctx
    return mock_engine


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync._persist_movements", new_callable=AsyncMock)
@patch("sky.worker.banking_sync._update_account_after_sync", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"decrypted_{x}")
async def test_sync_returns_skipped_when_lock_held(
    _decrypt: MagicMock,
    _engine: MagicMock,
    _update: AsyncMock,
    _persist: AsyncMock,
    mock_lock: MagicMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """Cuando el advisory lock está tomado, sync retorna {skipped: True}."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=False)

    out = await sync_bank_account(
        router=fake_router,
        bank_account_id=str(uuid4()),
        user_id=str(uuid4()),
        arq_pool=fake_arq_pool,
    )
    assert out["skipped"] is True
    _persist.assert_not_called()


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync._persist_movements", new_callable=AsyncMock)
@patch("sky.worker.banking_sync._update_account_after_sync", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"plain_{x}")
async def test_sync_success_path(
    _decrypt: MagicMock,
    mock_get_engine: MagicMock,
    _update: AsyncMock,
    mock_persist: AsyncMock,
    mock_lock: MagicMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """Lock adquirido, ingest OK, movimientos insertados, categorize encolado."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=True)
    mock_row = {
        "id": "acc-uuid", "user_id": "user-uuid", "bank_id": "bchile",
        "encrypted_rut": "enc_rut", "encrypted_pass": "enc_pass",
        "sync_count": 2, "consecutive_errors": 0,
    }
    mock_get_engine.return_value = _make_engine_with_row(mock_row)
    mock_persist.return_value = 3

    out = await sync_bank_account(
        router=fake_router,
        bank_account_id="acc-uuid",
        user_id="user-uuid",
        arq_pool=fake_arq_pool,
    )

    assert out["success"] is True
    assert out["new_transactions"] == 3
    assert out["bank_id"] == "bchile"
    fake_arq_pool.enqueue_job.assert_awaited_once_with("categorize_pending_job")


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync._mark_needs_reconnection", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"plain_{x}")
async def test_sync_auth_error_marks_needs_reconnection(
    _decrypt: MagicMock,
    mock_get_engine: MagicMock,
    mock_mark_reconnect: AsyncMock,
    mock_lock: MagicMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """B1: AuthenticationError → needs_reconnection (no 'error' genérico),
    retorna dict de fallo sin re-lanzar."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=True)
    mock_row = {
        "id": "acc-uuid", "user_id": "user-uuid", "bank_id": "bchile",
        "encrypted_rut": "enc_rut", "encrypted_pass": "enc_pass",
        "sync_count": 0, "consecutive_errors": 0,
    }
    mock_get_engine.return_value = _make_engine_with_row(mock_row)
    fake_router.ingest = AsyncMock(side_effect=BankAuthError("bad creds"))

    out = await sync_bank_account(
        router=fake_router,
        bank_account_id="acc-uuid",
        user_id="user-uuid",
        arq_pool=fake_arq_pool,
    )

    assert out["success"] is False
    assert out["error_type"] == "AuthenticationError"
    assert out["needs_reconnection"] is True
    mock_mark_reconnect.assert_awaited_once_with("acc-uuid")


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"plain_{x}")
async def test_sync_skipped_when_status_needs_reconnection(
    _decrypt: MagicMock,
    mock_get_engine: MagicMock,
    mock_lock: MagicMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """B2 hard-stop: cuenta en needs_reconnection NUNCA llega al banco,
    aunque el job ya esté encolado (backstop de todos los caminos)."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=True)
    mock_row = {
        "id": "acc-uuid", "user_id": "user-uuid", "bank_id": "bchile",
        "encrypted_rut": "enc_rut", "encrypted_pass": "enc_pass",
        "sync_count": 0, "consecutive_errors": 2,
        "status": "needs_reconnection",
    }
    mock_get_engine.return_value = _make_engine_with_row(mock_row)

    out = await sync_bank_account(
        router=fake_router,
        bank_account_id="acc-uuid",
        user_id="user-uuid",
        arq_pool=fake_arq_pool,
    )

    assert out["skipped"] is True
    assert out["reason"] == "needs_reconnection"
    fake_router.ingest.assert_not_called()


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync._mark_error", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"plain_{x}")
async def test_sync_all_sources_failed_returns_failure_dict(
    _decrypt: MagicMock,
    mock_get_engine: MagicMock,
    mock_mark_error: AsyncMock,
    mock_lock: MagicMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """AllSourcesFailedError retorna dict de fallo (sin re-lanzar) y marca error en DB."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=True)
    mock_row = {
        "id": "acc-uuid", "user_id": "user-uuid", "bank_id": "bchile",
        "encrypted_rut": "enc_rut", "encrypted_pass": "enc_pass",
        "sync_count": 0, "consecutive_errors": 0,
    }
    mock_get_engine.return_value = _make_engine_with_row(mock_row)
    fake_router.ingest = AsyncMock(
        side_effect=AllSourcesFailedError("bchile", [("scraper.bchile", RecoverableIngestionError("fail"))])
    )

    out = await sync_bank_account(
        router=fake_router,
        bank_account_id="acc-uuid",
        user_id="user-uuid",
        arq_pool=fake_arq_pool,
    )

    assert out["success"] is False
    assert out["error_type"] == "AllSourcesFailedError"
    mock_mark_error.assert_awaited_once()


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync._persist_movements", new_callable=AsyncMock)
@patch("sky.worker.banking_sync._update_account_after_sync", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"plain_{x}")
async def test_sync_sets_status_syncing_at_start(
    _decrypt: MagicMock,
    mock_get_engine: MagicMock,
    _update: AsyncMock,
    mock_persist: AsyncMock,
    mock_lock: MagicMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """Al arrancar sync se setea status='syncing', no 'active' (P3)."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=True)
    mock_row = {
        "id": "acc-uuid", "user_id": "user-uuid", "bank_id": "bchile",
        "encrypted_rut": "enc_rut", "encrypted_pass": "enc_pass",
        "sync_count": 0, "consecutive_errors": 0,
    }
    mock_get_engine.return_value = _make_engine_with_row(mock_row)
    mock_persist.return_value = 0

    await sync_bank_account(
        router=fake_router,
        bank_account_id="acc-uuid",
        user_id="user-uuid",
        arq_pool=fake_arq_pool,
    )

    # La segunda llamada a conn.execute (índice 1) es el UPDATE de status
    conn = mock_get_engine.return_value.begin.return_value.__aenter__.return_value
    update_sql = str(conn.execute.call_args_list[1][0][0])
    assert "syncing" in update_sql
    assert "active" not in update_sql.split("SET")[1].split("WHERE")[0]


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync._mark_error", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"plain_{x}")
async def test_sync_unexpected_exception_marks_error_and_reraises(
    _decrypt: MagicMock,
    mock_get_engine: MagicMock,
    mock_mark_error: AsyncMock,
    mock_lock: MagicMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """Excepción inesperada → _mark_error llamado, status nunca queda en 'syncing' (P3)."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=True)
    mock_row = {
        "id": "acc-uuid", "user_id": "user-uuid", "bank_id": "bchile",
        "encrypted_rut": "enc_rut", "encrypted_pass": "enc_pass",
        "sync_count": 0, "consecutive_errors": 0,
    }
    mock_get_engine.return_value = _make_engine_with_row(mock_row)
    fake_router.ingest = AsyncMock(side_effect=RuntimeError("fallo inesperado"))

    with pytest.raises(RuntimeError, match="fallo inesperado"):
        await sync_bank_account(
            router=fake_router,
            bank_account_id="acc-uuid",
            user_id="user-uuid",
            arq_pool=fake_arq_pool,
        )

    mock_mark_error.assert_awaited_once_with("acc-uuid", "Error inesperado de sincronización")


# ── Tests de helpers puros ────────────────────────────────────────────────────

class TestUserMessageForFailure:
    def _exc(self, causes: list[tuple[str, Exception]]) -> AllSourcesFailedError:
        return AllSourcesFailedError("bchile", causes)

    def test_2fa_timeout(self) -> None:
        exc = self._exc([("scraper.bchile", TwoFactorTimeoutError("timeout 2fa"))])
        msg = _user_message_for_failure(exc)
        assert "aprobación" in msg.lower()
        assert "app del banco" in msg.lower()

    def test_antibot_campo_rut(self) -> None:
        exc = self._exc([("scraper.bchile", RecoverableIngestionError("No se encontró el campo de RUT"))])
        msg = _user_message_for_failure(exc)
        assert "automáticamente" in msg.lower()
        assert "reintenta más tarde" in msg.lower()

    def test_antibot_incapsula(self) -> None:
        exc = self._exc([("scraper.bchile", RecoverableIngestionError("incapsula block detected"))])
        msg = _user_message_for_failure(exc)
        assert "automáticamente" in msg.lower()

    def test_circuit_open(self) -> None:
        exc = self._exc([("scraper.bchile", CircuitOpenError("circuito abierto para scraper.bchile"))])
        msg = _user_message_for_failure(exc)
        assert "saturado" in msg.lower() or "minutos" in msg.lower()

    def test_rate_limit(self) -> None:
        exc = self._exc([("scraper.bchile", RateLimitError("rate limit exceeded"))])
        msg = _user_message_for_failure(exc)
        assert "intentos" in msg.lower()

    def test_credentials_clave_incorrecta(self) -> None:
        exc = self._exc([("scraper.bchile", RecoverableIngestionError("clave incorrecta para el usuario"))])
        msg = _user_message_for_failure(exc)
        assert "clave" in msg.lower() or "rut" in msg.lower()

    def test_timeout(self) -> None:
        exc = self._exc([("scraper.bchile", RecoverableIngestionError("ETIMEDOUT after 30s"))])
        msg = _user_message_for_failure(exc)
        assert "respondió" in msg.lower() or "tarde" in msg.lower()

    def test_default(self) -> None:
        exc = self._exc([("scraper.bchile", RecoverableIngestionError("some unexpected internal error xyz"))])
        msg = _user_message_for_failure(exc)
        assert "sincronización" in msg.lower() or "reintenta" in msg.lower()

    def test_2fa_wins_over_generic(self) -> None:
        """2FA timeout tiene mayor prioridad que un error genérico."""
        exc = self._exc([
            ("scraper.bchile", RecoverableIngestionError("generic error")),
            ("scraper.bci", TwoFactorTimeoutError("2fa timeout")),
        ])
        msg = _user_message_for_failure(exc)
        assert "aprobación" in msg.lower()


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.get_engine")
async def test_mark_error_updates_db(mock_get_engine: MagicMock) -> None:
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    await _mark_error("some-account-id", "Error de test")
    mock_conn.execute.assert_awaited_once()


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.get_engine")
async def test_mark_needs_reconnection_updates_db(mock_get_engine: MagicMock) -> None:
    """B1: _mark_needs_reconnection escribe el status terminal + mensaje accionable."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    await _mark_needs_reconnection("some-account-id")

    mock_conn.execute.assert_awaited_once()
    sql = str(mock_conn.execute.call_args[0][0])
    params = mock_conn.execute.call_args[0][1]
    assert "needs_reconnection" in sql
    assert params["msg"] == RECONNECT_USER_MSG


# ── waiting_2fa visible (sprint testers 2026-06-12) ───────────────────────────

@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync._mark_syncing", new_callable=AsyncMock)
@patch("sky.worker.banking_sync._mark_waiting_2fa", new_callable=AsyncMock)
@patch("sky.worker.banking_sync._persist_movements", new_callable=AsyncMock)
@patch("sky.worker.banking_sync._update_account_after_sync", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"plain_{x}")
async def test_progress_2fa_marca_waiting_y_vuelve_a_syncing(
    _decrypt: MagicMock,
    mock_get_engine: MagicMock,
    _update: AsyncMock,
    mock_persist: AsyncMock,
    mock_waiting: AsyncMock,
    mock_syncing: AsyncMock,
    mock_lock: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """El prefijo de progreso 2FA marca waiting_2fa en DB; PROGRESS_LOGIN_OK
    devuelve la cuenta a syncing. Es la señal que el frontend convierte en el
    banner "aprueba en tu app" — sin esto el tester ve un spinner genérico."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=True)
    mock_row = {
        "id": "acc-uuid", "user_id": "user-uuid", "bank_id": "bchile",
        "encrypted_rut": "enc_rut", "encrypted_pass": "enc_pass",
        "sync_count": 0, "consecutive_errors": 0,
    }
    mock_get_engine.return_value = _make_engine_with_row(mock_row)
    mock_persist.return_value = 0

    result_obj = IngestionResult(
        balance=None, movements=[], source_kind=SourceKind.SCRAPER,
        source_identifier="scraper.bchile", elapsed_ms=10,
    )

    async def fake_ingest(**kwargs: Any) -> IngestionResult:
        on_progress = kwargs.get("on_progress")
        assert on_progress is not None, "sync_bank_account debe pasar on_progress al router"
        on_progress(f"{PROGRESS_2FA_WAIT_PREFIX} en tu app Banco de Chile...")
        await asyncio.sleep(0)  # deja correr el task del UPDATE
        on_progress(f"{PROGRESS_2FA_WAIT_PREFIX} (90s restantes)...")  # repetido: no re-marca
        on_progress(PROGRESS_LOGIN_OK)
        await asyncio.sleep(0)
        return result_obj

    router = MagicMock()
    router.ingest = fake_ingest

    out = await sync_bank_account(
        router=router,
        bank_account_id="acc-uuid",
        user_id="user-uuid",
        arq_pool=fake_arq_pool,
    )

    assert out["success"] is True
    mock_waiting.assert_awaited_once()
    args = mock_waiting.await_args[0]
    assert args[0] == "acc-uuid"
    assert args[1].startswith(PROGRESS_2FA_WAIT_PREFIX)
    mock_syncing.assert_awaited_once_with("acc-uuid")


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.get_engine")
async def test_mark_waiting_2fa_updates_db(mock_get_engine: MagicMock) -> None:
    """waiting_2fa se escribe con el mensaje visible y SIN tocar consecutive_errors
    (esperar la aprobación del usuario no es un error)."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    await _mark_waiting_2fa("acc-1", f"{PROGRESS_2FA_WAIT_PREFIX} en tu app...")

    sql = str(mock_conn.execute.call_args[0][0])
    params = mock_conn.execute.call_args[0][1]
    assert "waiting_2fa" in sql
    assert "consecutive_errors" not in sql
    assert params["msg"].startswith(PROGRESS_2FA_WAIT_PREFIX)


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.get_engine")
async def test_mark_syncing_vuelve_de_2fa_y_limpia_error(mock_get_engine: MagicMock) -> None:
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    await _mark_syncing("acc-1")

    sql = str(mock_conn.execute.call_args[0][0])
    assert "'syncing'" in sql
    assert "last_sync_error = NULL" in sql


@pytest.mark.asyncio
@patch("sky.worker.jobs.sync.get_engine")
async def test_sync_all_excluye_needs_reconnection(mock_get_engine: MagicMock) -> None:
    """B2: el SELECT de sync-all excluye cuentas en needs_reconnection."""
    from sky.worker.jobs.sync import sync_all_user_accounts_job

    mock_rs = MagicMock()
    mock_rs.fetchall.return_value = []
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.connect.return_value = mock_ctx

    arq_pool = MagicMock()
    arq_pool.enqueue_job = AsyncMock()
    await sync_all_user_accounts_job({"arq_pool": arq_pool}, "user-uuid")

    sql = str(mock_conn.execute.call_args[0][0])
    assert "needs_reconnection" in sql


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.get_engine")
async def test_persist_movements_empty(mock_get_engine: MagicMock) -> None:
    result = await _persist_movements(user_id="u", bank_account_id="a", movements=[])
    assert result == 0
    mock_get_engine.assert_not_called()


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.get_engine")
async def test_persist_movements_inserts_and_counts(mock_get_engine: MagicMock) -> None:
    mock_exec_result = MagicMock()
    mock_exec_result.rowcount = 1
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_exec_result)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    movements = [
        CanonicalMovement(
            external_id="bchile_abc",
            amount_clp=-5000,
            raw_description="STARBUCKS",
            occurred_at=date(2026, 4, 15),
            movement_source=MovementSource.ACCOUNT,
            source_kind=SourceKind.SCRAPER,
        )
    ]
    result = await _persist_movements(
        user_id="user-1", bank_account_id="acc-1", movements=movements
    )
    assert result == 1


# ── Tests de los job wrappers ─────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("sky.worker.jobs.sync.sync_bank_account", new_callable=AsyncMock)
async def test_sync_bank_account_job_delegates(
    mock_sync: AsyncMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    from sky.worker.jobs.sync import sync_bank_account_job

    mock_sync.return_value = {"success": True, "new_transactions": 1}
    ctx: dict = {"router": fake_router, "arq_pool": fake_arq_pool}

    result = await sync_bank_account_job(ctx, "acc-id", "user-id")
    assert result["success"] is True
    mock_sync.assert_awaited_once()


@pytest.mark.asyncio
@patch("sky.worker.jobs.sync.get_engine")
async def test_sync_all_user_accounts_job_enqueues(
    mock_get_engine: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    from sky.worker.jobs.sync import sync_all_user_accounts_job

    acc1, acc2 = str(uuid4()), str(uuid4())
    mock_rs = MagicMock()
    mock_rs.fetchall.return_value = [(acc1,), (acc2,)]
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.connect.return_value = mock_ctx

    ctx: dict = {"arq_pool": fake_arq_pool}
    result = await sync_all_user_accounts_job(ctx, "user-uuid")

    assert result["enqueued"] == 2
    assert fake_arq_pool.enqueue_job.await_count == 2
