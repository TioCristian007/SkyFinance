"""Tests unitarios de scheduled_sync_job."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from sky.worker.jobs.scheduled import scheduled_sync_job

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_engine(rows: list[dict[str, Any]]) -> MagicMock:
    """Mock engine que devuelve rows en SELECT via .mappings().all()."""
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = rows
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx
    return mock_engine


def _make_ctx(enqueue_return: Any = ...) -> dict[str, Any]:
    """Mock ctx de ARQ con arq_pool. Por defecto enqueue devuelve MagicMock (job ok)."""
    arq_pool = MagicMock()
    arq_pool.enqueue_job = AsyncMock(
        return_value=MagicMock() if enqueue_return is ... else enqueue_return
    )
    return {"arq_pool": arq_pool}


def _row(
    uid: str = "uuid-1",
    user: str = "user-1",
    errors: int = 0,
    last: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": uid,
        "user_id": user,
        "consecutive_errors": errors,
        "last_scheduled_at": last,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_no_candidates_returns_zero() -> None:
    """Query vacía → {"processed": 0} sin encolar nada."""
    ctx = _make_ctx()
    with patch("sky.worker.jobs.scheduled.get_engine", return_value=_make_engine([])):
        result = await scheduled_sync_job(ctx)

    assert result == {"processed": 0}
    ctx["arq_pool"].enqueue_job.assert_not_called()


async def test_all_due_no_last_scheduled() -> None:
    """last_scheduled_at=None → siempre due → encola todas."""
    rows = [_row("uuid-1", "user-1"), _row("uuid-2", "user-2")]
    ctx = _make_ctx()
    with patch("sky.worker.jobs.scheduled.get_engine", return_value=_make_engine(rows)):
        result = await scheduled_sync_job(ctx)

    assert result["ok"] == 2
    assert result["fail"] == 0
    assert ctx["arq_pool"].enqueue_job.call_count == 2


async def test_backoff_filters_recent_account() -> None:
    """1 error → interval=2h. last_scheduled=1h ago → NO due."""
    one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    rows = [_row(errors=1, last=one_hour_ago)]
    ctx = _make_ctx()
    with patch("sky.worker.jobs.scheduled.get_engine", return_value=_make_engine(rows)):
        result = await scheduled_sync_job(ctx)

    assert result == {"processed": 0, "skipped": 1}
    ctx["arq_pool"].enqueue_job.assert_not_called()


async def test_backoff_allows_overdue_account() -> None:
    """1 error → interval=2h. last_scheduled=3h ago → due."""
    three_hours_ago = datetime.now(UTC) - timedelta(hours=3)
    rows = [_row(errors=1, last=three_hours_ago)]
    ctx = _make_ctx()
    with patch("sky.worker.jobs.scheduled.get_engine", return_value=_make_engine(rows)):
        result = await scheduled_sync_job(ctx)

    assert result["ok"] == 1
    assert ctx["arq_pool"].enqueue_job.call_count == 1


async def test_max_per_tick_limits_enqueue() -> None:
    """25 due, max_per_tick=20 (default) → encola solo 20."""
    rows = [_row(uid=f"uuid-{i}", user=f"user-{i}") for i in range(25)]
    ctx = _make_ctx()
    with patch("sky.worker.jobs.scheduled.get_engine", return_value=_make_engine(rows)):
        result = await scheduled_sync_job(ctx)

    assert ctx["arq_pool"].enqueue_job.call_count == 20
    assert result["processed"] == 20


async def test_enqueue_returns_none_counts_fail() -> None:
    """Si arq_pool.enqueue_job devuelve None → fail += 1."""
    rows = [_row()]
    ctx = _make_ctx(enqueue_return=None)
    with patch("sky.worker.jobs.scheduled.get_engine", return_value=_make_engine(rows)):
        result = await scheduled_sync_job(ctx)

    assert result["fail"] == 1
    assert result["ok"] == 0
    assert result["processed"] == 1


async def test_backoff_exponential_3_errors() -> None:
    """3 errors → interval=min(1*2^3, 24)=8h. last=7h ago → NO due."""
    seven_hours_ago = datetime.now(UTC) - timedelta(hours=7)
    rows = [_row(errors=3, last=seven_hours_ago)]
    ctx = _make_ctx()
    with patch("sky.worker.jobs.scheduled.get_engine", return_value=_make_engine(rows)):
        result = await scheduled_sync_job(ctx)

    assert result == {"processed": 0, "skipped": 1}
    ctx["arq_pool"].enqueue_job.assert_not_called()


async def test_backoff_max_cap_respected() -> None:
    """10 errors → min(1*2^10, 24)=24h. last=25h ago → due (cap respetado)."""
    twenty_five_hours_ago = datetime.now(UTC) - timedelta(hours=25)
    rows = [_row(errors=10, last=twenty_five_hours_ago)]
    ctx = _make_ctx()
    with patch("sky.worker.jobs.scheduled.get_engine", return_value=_make_engine(rows)):
        result = await scheduled_sync_job(ctx)

    assert result["ok"] == 1


async def test_naive_datetime_treated_as_utc() -> None:
    """datetime naive en last_scheduled_at se trata como UTC (compatibilidad asyncpg)."""
    # asyncpg puede devolver datetime naive dependiendo de configuración.
    naive_three_hours_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
    rows = [_row(errors=1, last=naive_three_hours_ago)]  # interval=2h → due
    ctx = _make_ctx()
    with patch("sky.worker.jobs.scheduled.get_engine", return_value=_make_engine(rows)):
        result = await scheduled_sync_job(ctx)

    assert result["ok"] == 1
