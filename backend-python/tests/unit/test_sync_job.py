"""Tests unitarios de sync_bank_account con mocks."""
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sky.ingestion.contracts import (
    AccountBalance,
    CanonicalMovement,
    IngestionResult,
    MovementSource,
    SourceKind,
)
from sky.worker.banking_sync import sync_bank_account


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
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=False)
    cm.__aexit__ = AsyncMock(return_value=None)
    mock_lock.return_value = cm

    out = await sync_bank_account(
        router=fake_router,
        bank_account_id=str(uuid4()),
        user_id=str(uuid4()),
        arq_pool=fake_arq_pool,
    )
    assert out["skipped"] is True
    _persist.assert_not_called()
