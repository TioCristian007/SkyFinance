"""Tests unitarios de sync_bank_account con mocks."""
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sky.ingestion.contracts import (
    AccountBalance,
    AllSourcesFailedError,
    CanonicalMovement,
    IngestionResult,
    MovementSource,
    SourceKind,
)
from sky.ingestion.contracts import AuthenticationError as BankAuthError
from sky.worker.banking_sync import (
    _mark_error,
    _persist_movements,
    _sanitize_error,
    sync_bank_account,
)


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
@patch("sky.worker.banking_sync._mark_error", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"plain_{x}")
async def test_sync_auth_error_propagates(
    _decrypt: MagicMock,
    mock_get_engine: MagicMock,
    mock_mark_error: AsyncMock,
    mock_lock: MagicMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """AuthenticationError se propaga al caller y marca error en DB."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=True)
    mock_row = {
        "id": "acc-uuid", "user_id": "user-uuid", "bank_id": "bchile",
        "encrypted_rut": "enc_rut", "encrypted_pass": "enc_pass",
        "sync_count": 0, "consecutive_errors": 0,
    }
    mock_get_engine.return_value = _make_engine_with_row(mock_row)
    fake_router.ingest = AsyncMock(side_effect=BankAuthError("bad creds"))

    with pytest.raises(BankAuthError):
        await sync_bank_account(
            router=fake_router,
            bank_account_id="acc-uuid",
            user_id="user-uuid",
            arq_pool=fake_arq_pool,
        )

    mock_mark_error.assert_awaited_once()


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync._mark_error", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x, _k: f"plain_{x}")
async def test_sync_all_sources_failed_propagates(
    _decrypt: MagicMock,
    mock_get_engine: MagicMock,
    mock_mark_error: AsyncMock,
    mock_lock: MagicMock,
    fake_router: MagicMock,
    fake_arq_pool: MagicMock,
) -> None:
    """AllSourcesFailedError se propaga y marca error."""
    mock_lock.return_value = _make_advisory_lock_cm(acquired=True)
    mock_row = {
        "id": "acc-uuid", "user_id": "user-uuid", "bank_id": "bchile",
        "encrypted_rut": "enc_rut", "encrypted_pass": "enc_pass",
        "sync_count": 0, "consecutive_errors": 0,
    }
    mock_get_engine.return_value = _make_engine_with_row(mock_row)
    fake_router.ingest = AsyncMock(
        side_effect=AllSourcesFailedError("bchile", [("scraper.bchile", Exception("fail"))])
    )

    with pytest.raises(AllSourcesFailedError):
        await sync_bank_account(
            router=fake_router,
            bank_account_id="acc-uuid",
            user_id="user-uuid",
            arq_pool=fake_arq_pool,
        )

    mock_mark_error.assert_awaited_once()


# ── Tests de helpers puros ────────────────────────────────────────────────────

class TestSanitizeError:
    def test_empty_returns_generic(self) -> None:
        assert _sanitize_error("") == "Error de sincronización"

    def test_password_in_msg_sanitized(self) -> None:
        assert _sanitize_error("wrong password for user") == "Error de autenticación bancaria"

    def test_rut_in_msg_sanitized(self) -> None:
        assert _sanitize_error("invalid rut: 12345678-9") == "Error de autenticación bancaria"

    def test_timeout_message(self) -> None:
        result = _sanitize_error("ETIMEDOUT connecting to bank")
        assert result == "El banco no respondió. Intenta más tarde."

    def test_generic_error_truncated(self) -> None:
        long_msg = "A" * 300
        result = _sanitize_error(long_msg)
        assert len(result) == 200


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
