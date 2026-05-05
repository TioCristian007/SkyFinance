"""Tests del job categorize_pending_job."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sky.domain.categorizer import CategorizedItem
from sky.worker.jobs.categorize import categorize_pending_job


def _make_mock_engine(rows: list[dict]) -> MagicMock:
    """Helper: engine que devuelve `rows` en SELECT y acepta UPDATE."""
    # SELECT via engine.connect()
    mock_mappings_all = MagicMock()
    mock_mappings_all.all.return_value = rows
    mock_select_result = MagicMock()
    mock_select_result.mappings.return_value = mock_mappings_all

    mock_select_conn = AsyncMock()
    mock_select_conn.execute = AsyncMock(return_value=mock_select_result)
    mock_select_ctx = MagicMock()
    mock_select_ctx.__aenter__ = AsyncMock(return_value=mock_select_conn)
    mock_select_ctx.__aexit__ = AsyncMock(return_value=False)

    # UPDATE via engine.begin()
    mock_update_conn = AsyncMock()
    mock_update_conn.execute = AsyncMock()
    mock_update_ctx = MagicMock()
    mock_update_ctx.__aenter__ = AsyncMock(return_value=mock_update_conn)
    mock_update_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_select_ctx
    mock_engine.begin.return_value = mock_update_ctx
    return mock_engine


@pytest.mark.asyncio
@patch("sky.worker.jobs.categorize.get_engine")
async def test_categorize_pending_job_no_rows(mock_get_engine: MagicMock) -> None:
    """Sin filas pendientes → retorna skipped=True."""
    mock_get_engine.return_value = _make_mock_engine(rows=[])

    result = await categorize_pending_job({})
    assert result == {"processed": 0, "skipped": True}


@pytest.mark.asyncio
@patch("sky.worker.jobs.categorize.categorize_movements", new_callable=AsyncMock)
@patch("sky.worker.jobs.categorize.get_engine")
async def test_categorize_pending_job_processes_rows(
    mock_get_engine: MagicMock,
    mock_categorize: AsyncMock,
) -> None:
    """Con filas pendientes → categoriza y actualiza DB."""
    row_id = str(uuid4())
    rows = [{"id": row_id, "raw_description": "STARBUCKS", "amount": -5000}]
    mock_get_engine.return_value = _make_mock_engine(rows=rows)

    mock_categorize.return_value = [
        CategorizedItem(
            idx=0, raw_description="STARBUCKS", merchant_key="starbucks",
            amount=-5000, category="food", label="Alimentación", source="rule",
        )
    ]

    result = await categorize_pending_job({})
    assert result["processed"] == 1
    assert result["failed"] == 0
    mock_categorize.assert_awaited_once()


@pytest.mark.asyncio
@patch("sky.worker.jobs.categorize.categorize_movements", new_callable=AsyncMock)
@patch("sky.worker.jobs.categorize.get_engine")
async def test_categorize_pending_job_fallback_marks_failed(
    mock_get_engine: MagicMock,
    mock_categorize: AsyncMock,
) -> None:
    """Movimiento con source=fallback y category=other → status='failed'."""
    row_id = str(uuid4())
    rows = [{"id": row_id, "raw_description": "XYZQWERT", "amount": -1000}]
    mock_get_engine.return_value = _make_mock_engine(rows=rows)

    mock_categorize.return_value = [
        CategorizedItem(
            idx=0, raw_description="XYZQWERT", merchant_key="xyzqwert",
            amount=-1000, category="other", label="Gasto", source="fallback",
        )
    ]

    result = await categorize_pending_job({})
    # Fallback → categorized but marked as 'failed' in the UPDATE
    assert result["processed"] == 1

    # Verify UPDATE was called with status='failed'
    update_conn = mock_get_engine.return_value.begin.return_value.__aenter__.return_value
    call_kwargs = update_conn.execute.call_args_list[0][0][1]
    assert call_kwargs["status"] == "failed"


@pytest.mark.asyncio
@patch("sky.worker.jobs.categorize.categorize_movements", new_callable=AsyncMock)
@patch("sky.worker.jobs.categorize.get_engine")
async def test_categorize_pending_job_db_error_counts_failed(
    mock_get_engine: MagicMock,
    mock_categorize: AsyncMock,
) -> None:
    """Si el UPDATE lanza excepción, se cuenta como failed."""
    row_id = str(uuid4())
    rows = [{"id": row_id, "raw_description": "NETFLIX", "amount": -8500}]

    # Engine especial: SELECT OK pero UPDATE lanza
    mock_mappings_all = MagicMock()
    mock_mappings_all.all.return_value = rows
    mock_select_result = MagicMock()
    mock_select_result.mappings.return_value = mock_mappings_all
    mock_select_conn = AsyncMock()
    mock_select_conn.execute = AsyncMock(return_value=mock_select_result)
    mock_select_ctx = MagicMock()
    mock_select_ctx.__aenter__ = AsyncMock(return_value=mock_select_conn)
    mock_select_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_update_conn = AsyncMock()
    mock_update_conn.execute = AsyncMock(side_effect=Exception("DB write error"))
    mock_update_ctx = MagicMock()
    mock_update_ctx.__aenter__ = AsyncMock(return_value=mock_update_conn)
    mock_update_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_select_ctx
    mock_engine.begin.return_value = mock_update_ctx
    mock_get_engine.return_value = mock_engine

    mock_categorize.return_value = [
        CategorizedItem(
            idx=0, raw_description="NETFLIX", merchant_key="netflix",
            amount=-8500, category="subscriptions", label="Suscripción", source="rule",
        )
    ]

    result = await categorize_pending_job({})
    assert result["processed"] == 0
    assert result["failed"] == 1
