"""Tests de sky.domain.challenges — DB helpers."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_engine_connect(rows: list[dict]) -> MagicMock:
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


def _mock_engine_begin(row: dict | None, rowcount: int = 1) -> MagicMock:
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = row
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings
    mock_rs.rowcount = rowcount
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_ctx
    return mock_engine


@pytest.mark.asyncio
@patch("sky.domain.challenges.get_engine")
async def test_get_challenges_empty(mock_get_engine: MagicMock) -> None:
    mock_get_engine.return_value = _mock_engine_connect([])

    from sky.domain.challenges import MOCK_CHALLENGES, get_challenges
    result = await get_challenges("user-1")
    assert isinstance(result, dict)
    assert result["active"] == []
    assert result["completed"] == []
    assert len(result["available"]) == len(MOCK_CHALLENGES)
    assert result["points"] == 0


@pytest.mark.asyncio
@patch("sky.domain.challenges.get_engine")
async def test_get_challenges_returns_rows(mock_get_engine: MagicMock) -> None:
    # challenge_states has "no_uber" active; transactions empty (same mock returns both)
    states_rows = [{"challenge_id": "no_uber", "status": "active", "points_earned": 0}]
    mock_get_engine.return_value = _mock_engine_connect(states_rows)

    from sky.domain.challenges import get_challenges
    result = await get_challenges("user-1")
    assert isinstance(result, dict)
    assert len(result["active"]) == 1
    assert result["active"][0]["id"] == "no_uber"


@pytest.mark.asyncio
@patch("sky.domain.challenges.get_engine")
async def test_accept_challenge_returns_id(mock_get_engine: MagicMock) -> None:
    # connect() → empty challenge_states (not yet active); begin() → inserted row
    mock_engine = MagicMock()
    mock_engine.connect.return_value = _mock_engine_connect([]).connect.return_value
    mock_engine.begin.return_value = _mock_engine_begin({"id": "no_uber"}).begin.return_value
    mock_get_engine.return_value = mock_engine

    from sky.domain.challenges import accept_challenge
    result = await accept_challenge("user-1", "no_uber")
    assert result is not None
    assert result["id"] == "no_uber"


@pytest.mark.asyncio
@patch("sky.domain.challenges.get_engine")
async def test_accept_challenge_not_found_returns_none(mock_get_engine: MagicMock) -> None:
    mock_get_engine.return_value = _mock_engine_begin(None)

    from sky.domain.challenges import accept_challenge
    result = await accept_challenge("user-1", "nonexistent")
    assert result is None


@pytest.mark.asyncio
@patch("sky.domain.challenges.get_engine")
async def test_decline_challenge_returns_id(mock_get_engine: MagicMock) -> None:
    mock_get_engine.return_value = _mock_engine_begin({"id": "ch-2"})

    from sky.domain.challenges import decline_challenge
    result = await decline_challenge("user-1", "ch-2")
    assert result is not None
    assert result["id"] == "ch-2"


@pytest.mark.asyncio
@patch("sky.domain.challenges.get_engine")
async def test_decline_challenge_already_active_returns_none(
    mock_get_engine: MagicMock,
) -> None:
    mock_get_engine.return_value = _mock_engine_begin(None)

    from sky.domain.challenges import decline_challenge
    result = await decline_challenge("user-1", "ch-active")
    assert result is None
