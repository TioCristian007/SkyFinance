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

    from sky.domain.challenges import get_challenges
    result = await get_challenges("user-1")
    assert result == []


@pytest.mark.asyncio
@patch("sky.domain.challenges.get_engine")
async def test_get_challenges_returns_rows(mock_get_engine: MagicMock) -> None:
    rows = [
        {
            "id": "ch-1", "title": "No café este mes", "description": "Evita cafeterías",
            "target_amount": 20_000, "current_amount": 0,
            "start_date": "2026-05-01", "end_date": "2026-05-31",
            "status": "proposed", "created_at": "2026-05-01T00:00:00",
        }
    ]
    mock_get_engine.return_value = _mock_engine_connect(rows)

    from sky.domain.challenges import get_challenges
    result = await get_challenges("user-1")
    assert len(result) == 1
    assert result[0]["title"] == "No café este mes"
    assert result[0]["status"] == "proposed"


@pytest.mark.asyncio
@patch("sky.domain.challenges.get_engine")
async def test_accept_challenge_returns_id(mock_get_engine: MagicMock) -> None:
    mock_get_engine.return_value = _mock_engine_begin({"id": "ch-1"})

    from sky.domain.challenges import accept_challenge
    result = await accept_challenge("user-1", "ch-1")
    assert result is not None
    assert result["id"] == "ch-1"


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
