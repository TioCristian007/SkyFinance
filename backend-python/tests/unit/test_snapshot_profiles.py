"""Tests D4: snapshot_profiles_job — k-anon, bucketización, jitter, batch_id."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sky.worker.jobs.snapshot_profiles import _int_bucket, snapshot_profiles_job

# ── Tests de helper _int_bucket ──────────────────────────────────────────────

def test_int_bucket_low() -> None:
    assert _int_bucket(0) == "low"
    assert _int_bucket(3) == "low"


def test_int_bucket_mid() -> None:
    assert _int_bucket(4) == "mid"
    assert _int_bucket(6) == "mid"


def test_int_bucket_high() -> None:
    assert _int_bucket(7) == "high"
    assert _int_bucket(10) == "high"


def test_int_bucket_none_returns_none() -> None:
    assert _int_bucket(None) is None


# ── Tests del job principal ───────────────────────────────────────────────────

def _make_snapshot_engine(rows: list[dict]) -> MagicMock:
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = rows
    mock_rs = MagicMock()
    mock_rs.mappings.return_value = mock_mappings

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)

    mock_connect_ctx = MagicMock()
    mock_connect_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_connect_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = mock_connect_ctx
    return engine


def _make_profile_row(
    age_range: str = "26-35",
    region: str = "RM",
    income_range: str = "1M-2M",
    occupation: str = "empleado",
    savings_mindset: str | None = "saver",
    risk_tolerance: int | None = 5,
) -> dict:
    return {
        "age_range": age_range,
        "region": region,
        "income_range": income_range,
        "occupation": occupation,
        "savings_mindset": savings_mindset,
        "risk_tolerance": risk_tolerance,
        "financial_volatility": None,
        "goal_orientation": "long_term",
        "stress_baseline": 4,
        "motivation_primary": "security",
        "emotional_volatility": 2,
    }


@pytest.mark.asyncio
@patch("sky.worker.jobs.snapshot_profiles.get_aria_client")
@patch("sky.worker.jobs.snapshot_profiles.get_engine")
@patch("sky.worker.jobs.snapshot_profiles.settings")
async def test_snapshot_inserts_bucket_above_k_min(
    mock_settings: MagicMock,
    mock_engine: MagicMock,
    mock_aria: MagicMock,
) -> None:
    """Bucket con 6 perfiles y k_anon_min=5 → 6 snapshots insertados."""
    mock_settings.profile_snapshot_k_anon_min = 5
    mock_settings.profile_snapshot_jitter_days = 3

    rows = [_make_profile_row() for _ in range(6)]
    mock_engine.return_value = _make_snapshot_engine(rows)

    inserted_data: list = []
    mock_aria_client = MagicMock()
    mock_aria_client.schema.return_value.from_.return_value.insert.return_value.execute = MagicMock(
        side_effect=lambda: inserted_data.extend(
            mock_aria_client.schema.return_value.from_.return_value.insert.call_args[0][0]
        )
    )
    mock_aria.return_value = mock_aria_client

    result = await snapshot_profiles_job({})

    assert result["inserted"] == 6
    assert result["skipped_buckets"] == 0
    assert result["total"] == 6


@pytest.mark.asyncio
@patch("sky.worker.jobs.snapshot_profiles.get_aria_client")
@patch("sky.worker.jobs.snapshot_profiles.get_engine")
@patch("sky.worker.jobs.snapshot_profiles.settings")
async def test_snapshot_skips_bucket_below_k_min(
    mock_settings: MagicMock,
    mock_engine: MagicMock,
    mock_aria: MagicMock,
) -> None:
    """Bucket con 4 perfiles y k_anon_min=5 → ningún snapshot insertado."""
    mock_settings.profile_snapshot_k_anon_min = 5
    mock_settings.profile_snapshot_jitter_days = 3

    rows = [_make_profile_row() for _ in range(4)]
    mock_engine.return_value = _make_snapshot_engine(rows)

    mock_aria.return_value = MagicMock()

    result = await snapshot_profiles_job({})

    assert result["inserted"] == 0
    assert result["skipped_buckets"] == 1
    mock_aria.return_value.schema.assert_not_called()


@pytest.mark.asyncio
@patch("sky.worker.jobs.snapshot_profiles.get_aria_client")
@patch("sky.worker.jobs.snapshot_profiles.get_engine")
@patch("sky.worker.jobs.snapshot_profiles.settings")
async def test_snapshot_two_buckets_one_above_one_below(
    mock_settings: MagicMock,
    mock_engine: MagicMock,
    mock_aria: MagicMock,
) -> None:
    """Dos buckets: uno con 6 (inserta) y otro con 4 (skipa)."""
    mock_settings.profile_snapshot_k_anon_min = 5
    mock_settings.profile_snapshot_jitter_days = 3

    rows_big = [_make_profile_row(age_range="26-35") for _ in range(6)]
    rows_small = [_make_profile_row(age_range="46-55") for _ in range(4)]
    mock_engine.return_value = _make_snapshot_engine(rows_big + rows_small)

    inserted_snapshots: list = []

    mock_aria_client = MagicMock()
    mock_aria_client.schema.return_value.from_.return_value.insert = MagicMock(
        side_effect=lambda data: type("R", (), {
            "execute": lambda self: inserted_snapshots.extend(data)
        })()
    )
    mock_aria.return_value = mock_aria_client

    result = await snapshot_profiles_job({})

    assert result["inserted"] == 6
    assert result["skipped_buckets"] == 1
    assert result["total"] == 10


@pytest.mark.asyncio
@patch("sky.worker.jobs.snapshot_profiles.get_engine")
@patch("sky.worker.jobs.snapshot_profiles.settings")
async def test_snapshot_empty_returns_zero(
    mock_settings: MagicMock,
    mock_engine: MagicMock,
) -> None:
    """Sin perfiles en DB → retorna 0 sin llamar a aria_client."""
    mock_settings.profile_snapshot_k_anon_min = 5
    mock_settings.profile_snapshot_jitter_days = 3
    mock_engine.return_value = _make_snapshot_engine([])

    result = await snapshot_profiles_job({})

    assert result["total"] == 0
    assert result["inserted"] == 0


@pytest.mark.asyncio
@patch("sky.worker.jobs.snapshot_profiles.get_aria_client")
@patch("sky.worker.jobs.snapshot_profiles.get_engine")
@patch("sky.worker.jobs.snapshot_profiles.settings")
async def test_snapshot_jitter_within_bounds(
    mock_settings: MagicMock,
    mock_engine: MagicMock,
    mock_aria: MagicMock,
) -> None:
    """jitter_offset_days debe estar dentro de [-jitter_days, +jitter_days]."""
    mock_settings.profile_snapshot_k_anon_min = 5
    mock_settings.profile_snapshot_jitter_days = 3

    rows = [_make_profile_row() for _ in range(6)]
    mock_engine.return_value = _make_snapshot_engine(rows)

    captured_data: list[dict] = []
    mock_aria_client = MagicMock()

    def capture_insert(data: list) -> MagicMock:
        captured_data.extend(data)
        r = MagicMock()
        r.execute = MagicMock()
        return r

    mock_aria_client.schema.return_value.from_.return_value.insert.side_effect = capture_insert
    mock_aria.return_value = mock_aria_client

    await snapshot_profiles_job({})

    for snap in captured_data:
        assert -3 <= snap["jitter_offset_days"] <= 3


@pytest.mark.asyncio
@patch("sky.worker.jobs.snapshot_profiles.get_aria_client")
@patch("sky.worker.jobs.snapshot_profiles.get_engine")
@patch("sky.worker.jobs.snapshot_profiles.settings")
async def test_snapshot_batch_id_unique_per_run(
    mock_settings: MagicMock,
    mock_engine: MagicMock,
    mock_aria: MagicMock,
) -> None:
    """Todos los snapshots del mismo run comparten el mismo batch_id."""
    mock_settings.profile_snapshot_k_anon_min = 5
    mock_settings.profile_snapshot_jitter_days = 3

    rows = [_make_profile_row() for _ in range(6)]
    mock_engine.return_value = _make_snapshot_engine(rows)

    captured_data: list[dict] = []

    def capture_insert(data: list) -> MagicMock:
        captured_data.extend(data)
        r = MagicMock()
        r.execute = MagicMock()
        return r

    mock_aria_client = MagicMock()
    mock_aria_client.schema.return_value.from_.return_value.insert.side_effect = capture_insert
    mock_aria.return_value = mock_aria_client

    result = await snapshot_profiles_job({})

    batch_ids = {snap["batch_id"] for snap in captured_data}
    assert len(batch_ids) == 1
    assert result["batch_id"] in batch_ids


# ── Tests de mr_money premium gate (C4) ──────────────────────────────────────

@pytest.mark.asyncio
@patch("sky.domain.mr_money.settings")
async def test_is_premium_user_default_false(mock_settings: MagicMock) -> None:
    """Con emotion_inference_premium_only=True, todos son free → retorna False."""
    from sky.domain.mr_money import _is_premium_user
    mock_settings.emotion_inference_premium_only = True
    result = await _is_premium_user("any-user")
    assert result is False


@pytest.mark.asyncio
@patch("sky.domain.mr_money.settings")
async def test_is_premium_user_setting_disabled_returns_true(mock_settings: MagicMock) -> None:
    """Con emotion_inference_premium_only=False → todos son 'premium' (dev mode)."""
    from sky.domain.mr_money import _is_premium_user
    mock_settings.emotion_inference_premium_only = False
    result = await _is_premium_user("any-user")
    assert result is True


def test_build_tools_for_user_free_excludes_emotion_tool() -> None:
    from sky.domain.mr_money import MR_MONEY_TOOLS, _build_tools_for_user
    tools = _build_tools_for_user(is_premium=False)
    assert tools == MR_MONEY_TOOLS
    tool_names = [t["name"] for t in tools]
    assert "infer_emotional_state" not in tool_names


def test_build_tools_for_user_premium_includes_emotion_tool() -> None:
    from sky.domain.mr_money import MR_MONEY_TOOLS, _build_tools_for_user
    tools = _build_tools_for_user(is_premium=True)
    tool_names = [t["name"] for t in tools]
    assert "infer_emotional_state" in tool_names
    assert len(tools) == len(MR_MONEY_TOOLS) + 1


def test_build_system_prompt_premium_mentions_emotion() -> None:
    from sky.domain.mr_money import _build_system_prompt
    prompt = _build_system_prompt("ctx", is_premium=True)
    assert "infer_emotional_state" in prompt or "EMOCIÓN" in prompt


def test_build_system_prompt_free_no_emotion_instructions() -> None:
    from sky.domain.mr_money import _build_system_prompt
    prompt = _build_system_prompt("ctx", is_premium=False)
    assert "infer_emotional_state" not in prompt
