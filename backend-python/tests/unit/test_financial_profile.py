"""Tests B4: sky.domain.financial_profile — get, upsert, emotion, rolling std."""
from __future__ import annotations

import json
import statistics
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sky.domain.financial_profile import (
    _EDITABLE_DIMENSIONS,
    _MAX_EMOTION_HISTORY,
    apply_emotion_inference,
    get_profile,
    upsert_profile_dimension,
)

_USER = "user-fp-1"


def _make_engine(
    select_row: dict | None = None, select_rows: list[dict] | None = None
) -> MagicMock:
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = select_row

    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)

    mock_begin_ctx = MagicMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_connect_ctx = MagicMock()
    mock_connect_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_connect_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = mock_connect_ctx
    engine.begin.return_value = mock_begin_ctx
    return engine


# ── get_profile ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("sky.domain.financial_profile.get_engine")
async def test_get_profile_returns_none_when_no_row(mock_engine: MagicMock) -> None:
    mock_engine.return_value = _make_engine(select_row=None)
    result = await get_profile(_USER)
    assert result is None


@pytest.mark.asyncio
@patch("sky.domain.financial_profile.get_engine")
async def test_get_profile_returns_financial_profile(mock_engine: MagicMock) -> None:
    row = {
        "savings_mindset": "saver", "savings_mindset_conf": 0.8,
        "risk_tolerance": 4, "risk_tolerance_conf": 0.7,
        "financial_volatility": None, "financial_volatility_conf": None,
        "goal_orientation": "long_term", "goal_orientation_conf": 0.9,
        "stress_baseline": 5, "stress_current": 6, "emotional_volatility": 2,
        "last_emotion": "ansiedad", "last_emotion_at": None,
        "motivation_primary": "security", "motivation_primary_conf": 0.75,
        "recurring_blockers": [], "protective_behaviors": [], "updates_count": 3,
    }
    mock_engine.return_value = _make_engine(select_row=row)
    result = await get_profile(_USER)

    assert result is not None
    assert result.savings_mindset == "saver"
    assert result.goal_orientation == "long_term"
    assert result.stress_baseline == 5
    assert result.updates_count == 3


# ── upsert_profile_dimension ──────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("sky.domain.financial_profile.get_engine")
async def test_upsert_valid_dimension_executes_sql(mock_engine: MagicMock) -> None:
    mock_engine.return_value = _make_engine()
    await upsert_profile_dimension(_USER, "savings_mindset", "saver", confidence=0.8)
    conn = mock_engine.return_value.begin.return_value.__aenter__.return_value
    conn.execute.assert_awaited_once()
    sql = str(conn.execute.call_args[0][0])
    assert "savings_mindset" in sql
    assert "user_financial_profile" in sql


@pytest.mark.asyncio
async def test_upsert_invalid_dimension_raises_value_error() -> None:
    with pytest.raises(ValueError, match="fuera del allow-list"):
        await upsert_profile_dimension(_USER, "hacked_column", "bad", confidence=1.0)


@pytest.mark.asyncio
async def test_upsert_dimension_allow_list_is_complete() -> None:
    """Verificar que todas las dimensiones del allow-list están documentadas."""
    assert "savings_mindset" in _EDITABLE_DIMENSIONS
    assert "risk_tolerance" in _EDITABLE_DIMENSIONS
    assert "goal_orientation" in _EDITABLE_DIMENSIONS
    assert "motivation_primary" in _EDITABLE_DIMENSIONS
    assert "stress_baseline" in _EDITABLE_DIMENSIONS
    assert "recurring_blockers" in _EDITABLE_DIMENSIONS
    assert "protective_behaviors" in _EDITABLE_DIMENSIONS
    # Columnas que NO deben ser editables via tool
    assert "last_emotion" not in _EDITABLE_DIMENSIONS
    assert "emotional_volatility" not in _EDITABLE_DIMENSIONS
    assert "user_id" not in _EDITABLE_DIMENSIONS


# ── apply_emotion_inference ───────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("sky.domain.financial_profile.get_engine")
async def test_apply_emotion_first_observation_no_volatility(mock_engine: MagicMock) -> None:
    """Primera observación: no hay history previo → volatility es None."""
    # apply_emotion_inference usa connect() para leer y begin() para escribir
    row_with_empty_history = {"emotion_history": []}

    mock_mappings = MagicMock()
    mock_mappings.first.return_value = row_with_empty_history
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings

    mock_conn_read = AsyncMock()
    mock_conn_read.execute = AsyncMock(return_value=mock_rs)
    mock_connect_ctx = MagicMock()
    mock_connect_ctx.__aenter__ = AsyncMock(return_value=mock_conn_read)
    mock_connect_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_conn_write = AsyncMock()
    mock_conn_write.execute = AsyncMock()
    mock_begin_ctx = MagicMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn_write)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = mock_connect_ctx
    engine.begin.return_value = mock_begin_ctx
    mock_engine.return_value = engine

    await apply_emotion_inference(_USER, "ansiedad", intensity=7, signal_kind="venting")

    mock_conn_write.execute.assert_awaited_once()
    sql = str(mock_conn_write.execute.call_args[0][0])
    assert "last_emotion" in sql


@pytest.mark.asyncio
@patch("sky.domain.financial_profile.get_engine")
async def test_apply_emotion_calculates_rolling_std(mock_engine: MagicMock) -> None:
    """Con history de 2+ observaciones, emotional_volatility = stdev redondeado."""
    existing_history = [3, 8, 3, 8]  # std = ~2.9
    row_with_history = {"emotion_history": existing_history}

    # Necesitamos dos executes: SELECT (connect) y INSERT (begin)
    mock_mappings_connect = MagicMock()
    mock_mappings_connect.first.return_value = row_with_history

    mock_rs_connect = MagicMock()
    mock_rs_connect.mappings.return_value = mock_mappings_connect

    mock_conn_connect = AsyncMock()
    mock_conn_connect.execute = AsyncMock(return_value=mock_rs_connect)
    mock_connect_ctx = MagicMock()
    mock_connect_ctx.__aenter__ = AsyncMock(return_value=mock_conn_connect)
    mock_connect_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_conn_begin = AsyncMock()
    mock_conn_begin.execute = AsyncMock()
    mock_begin_ctx = MagicMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn_begin)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = mock_connect_ctx
    engine.begin.return_value = mock_begin_ctx
    mock_engine.return_value = engine

    new_intensity = 7
    await apply_emotion_inference(_USER, "orgullo", intensity=new_intensity, signal_kind="progress")

    # Verificar que se ejecutó el INSERT
    mock_conn_begin.execute.assert_awaited_once()

    # Calcular el volatility esperado
    full_history = [*existing_history, new_intensity]
    expected_vol = min(10, round(statistics.stdev(full_history)))
    call_params = mock_conn_begin.execute.call_args[0][1]
    assert call_params["volatility"] == expected_vol


@pytest.mark.asyncio
@patch("sky.domain.financial_profile.get_engine")
async def test_apply_emotion_caps_history_at_max(mock_engine: MagicMock) -> None:
    """El history se trunca a _MAX_EMOTION_HISTORY entradas."""
    # Crear history más largo que el máximo
    long_history = list(range(_MAX_EMOTION_HISTORY + 5))

    mock_mappings = MagicMock()
    mock_mappings.first.return_value = {"emotion_history": long_history}
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings

    mock_conn_connect = AsyncMock()
    mock_conn_connect.execute = AsyncMock(return_value=mock_rs)
    mock_connect_ctx = MagicMock()
    mock_connect_ctx.__aenter__ = AsyncMock(return_value=mock_conn_connect)
    mock_connect_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_conn_begin = AsyncMock()
    mock_conn_begin.execute = AsyncMock()
    mock_begin_ctx = MagicMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_conn_begin)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = mock_connect_ctx
    engine.begin.return_value = mock_begin_ctx
    mock_engine.return_value = engine

    await apply_emotion_inference(_USER, "neutro", intensity=5, signal_kind="inquiry")

    call_params = mock_conn_begin.execute.call_args[0][1]
    stored_history = json.loads(call_params["history"])
    assert len(stored_history) <= _MAX_EMOTION_HISTORY


@pytest.mark.asyncio
@patch("sky.domain.financial_profile.get_engine")
async def test_apply_emotion_intensity_clamped_to_10(mock_engine: MagicMock) -> None:
    """Intensity > 10 se clampea a 10."""
    mock_engine.return_value = _make_engine(select_row={"emotion_history": []})
    await apply_emotion_inference(_USER, "ansiedad", intensity=15, signal_kind="venting")

    conn = mock_engine.return_value.begin.return_value.__aenter__.return_value
    call_params = conn.execute.call_args[0][1]
    assert call_params["stress"] == 10


@pytest.mark.asyncio
@patch("sky.domain.financial_profile.get_engine")
async def test_apply_emotion_intensity_clamped_to_0(mock_engine: MagicMock) -> None:
    """Intensity < 0 se clampea a 0."""
    mock_engine.return_value = _make_engine(select_row={"emotion_history": []})
    await apply_emotion_inference(_USER, "alivio", intensity=-5, signal_kind="inquiry")

    conn = mock_engine.return_value.begin.return_value.__aenter__.return_value
    call_params = conn.execute.call_args[0][1]
    assert call_params["stress"] == 0


@pytest.mark.asyncio
@patch("sky.domain.financial_profile.get_engine")
async def test_get_profile_exception_returns_none(mock_engine: MagicMock) -> None:
    """Exception en get_profile → None (fail-safe, no propaga)."""
    mock_engine.return_value.connect.side_effect = Exception("DB down")
    result = await get_profile(_USER)
    assert result is None
