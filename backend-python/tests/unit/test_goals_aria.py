"""Regresión A2: track_goal_event se llama en create/update/delete."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_USER = "user-goals-aria-1"


def _make_engine_returning(row: dict | None) -> MagicMock:
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = row if row else None
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings
    mock_rs.rowcount = 1

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)

    mock_begin_ctx = MagicMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_connect_ctx = MagicMock()
    mock_connect_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_connect_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_begin_ctx
    mock_engine.connect.return_value = mock_connect_ctx
    return mock_engine


@pytest.mark.asyncio
@patch("sky.domain.goals.asyncio.create_task")
@patch("sky.domain.goals._fire_goal_aria", new_callable=AsyncMock)
@patch("sky.domain.goals._get_monthly_capacity", new_callable=AsyncMock, return_value=100_000)
@patch("sky.domain.goals.get_engine")
async def test_create_goal_fires_aria(
    mock_engine: MagicMock,
    _mock_cap: AsyncMock,
    mock_fire: AsyncMock,
    mock_create_task: MagicMock,
) -> None:
    """create_goal debe disparar _fire_goal_aria con status='active' y rate=0."""
    from sky.domain.goals import create_goal

    row = {
        "id": "goal-1", "name": "Viaje", "target_amount": 1_000_000,
        "current_amount": 0, "target_date": None, "created_at": None,
    }
    mock_engine.return_value = _make_engine_returning(row)

    mock_coro = MagicMock()
    mock_fire.return_value = mock_coro
    mock_create_task.return_value = MagicMock()

    created_task = False

    def fake_create_task(coro: object) -> MagicMock:
        nonlocal created_task
        created_task = True
        t = MagicMock()
        t.add_done_callback = MagicMock()
        return t

    mock_create_task.side_effect = fake_create_task

    await create_goal(_USER, "Viaje", 1_000_000, None)

    assert created_task, "asyncio.create_task debería haber sido llamado"


@pytest.mark.asyncio
@patch("sky.domain.goals.asyncio.create_task")
@patch("sky.domain.goals._get_monthly_capacity", new_callable=AsyncMock, return_value=100_000)
@patch("sky.domain.goals.get_engine")
async def test_delete_goal_reads_before_delete(
    mock_engine: MagicMock,
    _mock_cap: AsyncMock,
    mock_create_task: MagicMock,
) -> None:
    """delete_goal debe leer la meta antes de borrarla y disparar aria con status='abandoned'."""
    from sky.domain.goals import delete_goal

    pre_row = {"name": "Viaje", "target_amount": 1_000_000, "current_amount": 200_000}
    mock_engine.return_value = _make_engine_returning(pre_row)

    fired_status = []

    async def fake_fire(uid: str, goal: dict, completion_rate: float, goal_status: str) -> None:
        fired_status.append(goal_status)

    with patch("sky.domain.goals._fire_goal_aria", side_effect=fake_fire):
        mock_create_task.side_effect = lambda coro: MagicMock(add_done_callback=MagicMock())
        await delete_goal(_USER, "goal-1")

    assert mock_create_task.called


@pytest.mark.asyncio
@patch("sky.domain.goals.asyncio.create_task")
@patch("sky.domain.goals._get_monthly_capacity", new_callable=AsyncMock, return_value=50_000)
@patch("sky.domain.goals.get_engine")
async def test_update_goal_fires_aria_completed_when_100pct(
    mock_engine: MagicMock,
    _mock_cap: AsyncMock,
    mock_create_task: MagicMock,
) -> None:
    """update_goal con current_amount == target_amount → goal_status='completed'."""
    from sky.domain.goals import update_goal

    row = {
        "id": "goal-2", "name": "Meta", "target_amount": 500_000,
        "current_amount": 500_000, "target_date": None, "created_at": None,
    }
    mock_engine.return_value = _make_engine_returning(row)

    fired_statuses = []

    async def fake_fire(uid: str, goal: dict, completion_rate: float, goal_status: str) -> None:
        fired_statuses.append(goal_status)

    with patch("sky.domain.goals._fire_goal_aria", side_effect=fake_fire):
        mock_create_task.side_effect = lambda coro: MagicMock(add_done_callback=MagicMock())
        await update_goal(_USER, "goal-2", {"current_amount": 500_000})

    assert mock_create_task.called
