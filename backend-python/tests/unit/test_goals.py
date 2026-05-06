"""Tests de sky.domain.goals — calc_goal_projection (pure) + DB helpers."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sky.domain.goals import calc_goal_projection


class TestCalcGoalProjection:
    def test_normal_case(self) -> None:
        r = calc_goal_projection(200_000, 1_000_000, 100_000)
        assert r["remaining"] == 800_000
        assert r["months_to_goal"] == 8
        assert r["monthly_savings"] == 100_000
        assert r["projected_date"] is not None

    def test_goal_already_reached(self) -> None:
        r = calc_goal_projection(1_000_000, 1_000_000, 50_000)
        assert r["remaining"] == 0
        assert r["months_to_goal"] is None  # no need to project
        assert r["pct"] == 100

    def test_zero_monthly_capacity(self) -> None:
        r = calc_goal_projection(0, 500_000, 0)
        assert r["months_to_goal"] is None
        assert r["projected_date"] is None

    def test_pct_capped_at_100(self) -> None:
        r = calc_goal_projection(2_000_000, 1_000_000, 100_000)
        assert r["pct"] == 100

    def test_pct_partial(self) -> None:
        r = calc_goal_projection(250_000, 1_000_000, 50_000)
        assert r["pct"] == 25

    def test_months_to_goal_ceiling(self) -> None:
        r = calc_goal_projection(0, 100_001, 100_000)
        assert r["months_to_goal"] == 2  # ceil(100_001 / 100_000)

    def test_zero_target_amount_doesnt_divide_by_zero(self) -> None:
        r = calc_goal_projection(0, 0, 50_000)
        assert r["pct"] >= 0  # no ZeroDivisionError


def _make_engine_with_rows(rows: list[dict]) -> MagicMock:
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


@pytest.mark.asyncio
@patch("sky.domain.goals._get_monthly_capacity", new_callable=AsyncMock)
@patch("sky.domain.goals.get_engine")
async def test_get_goals_returns_list(
    mock_get_engine: MagicMock,
    mock_capacity: AsyncMock,
) -> None:
    mock_capacity.return_value = 200_000
    mock_get_engine.return_value = _make_engine_with_rows([
        {
            "id": "goal-1", "name": "Viaje Europa", "target_amount": 2_000_000,
            "current_amount": 500_000, "target_date": None,
            "created_at": "2026-01-01T00:00:00",
        }
    ])

    from sky.domain.goals import get_goals
    goals = await get_goals("user-1")

    assert len(goals) == 1
    assert goals[0]["name"] == "Viaje Europa"
    assert "progress_pct" in goals[0]
    assert "projection" in goals[0]


@pytest.mark.asyncio
@patch("sky.domain.goals._get_monthly_capacity", new_callable=AsyncMock)
@patch("sky.domain.goals.get_engine")
async def test_get_goals_empty(
    mock_get_engine: MagicMock,
    mock_capacity: AsyncMock,
) -> None:
    mock_capacity.return_value = 0
    mock_get_engine.return_value = _make_engine_with_rows([])

    from sky.domain.goals import get_goals
    assert await get_goals("user-1") == []


@pytest.mark.asyncio
@patch("sky.domain.goals._get_monthly_capacity", new_callable=AsyncMock)
@patch("sky.domain.goals.get_engine")
async def test_create_goal_returns_row(
    mock_get_engine: MagicMock,
    mock_capacity: AsyncMock,
) -> None:
    mock_capacity.return_value = 100_000
    mock_row = {
        "id": "g-1", "name": "Fondo emergencia", "target_amount": 500_000,
        "current_amount": 0, "target_date": None, "created_at": "2026-01-01",
    }
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = mock_row
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    from sky.domain.goals import create_goal
    result = await create_goal("user-1", "Fondo emergencia", 500_000, None)

    assert result["id"] == "g-1"
    assert result["name"] == "Fondo emergencia"
    assert "progress_pct" in result


@pytest.mark.asyncio
@patch("sky.domain.goals.get_engine")
async def test_delete_goal_returns_true_on_success(mock_get_engine: MagicMock) -> None:
    mock_rs = MagicMock()
    mock_rs.rowcount = 1
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    from sky.domain.goals import delete_goal
    assert await delete_goal("user-1", "goal-1") is True


@pytest.mark.asyncio
@patch("sky.domain.goals.get_engine")
async def test_delete_goal_returns_false_when_not_found(mock_get_engine: MagicMock) -> None:
    mock_rs = MagicMock()
    mock_rs.rowcount = 0
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    from sky.domain.goals import delete_goal
    assert await delete_goal("user-1", "nonexistent") is False
