"""Tests de routing/rules.py (carga DB + cache TTL)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import sky.ingestion.routing.rules as rules_mod
from sky.ingestion.routing.rules import (
    DEFAULT_RULES,
    invalidate_cache,
    load_rules_from_db,
)


@pytest.fixture(autouse=True)
def reset_cache() -> None:
    """Limpia el cache antes de cada test para evitar interferencia."""
    invalidate_cache()
    yield
    invalidate_cache()


def _make_mock_engine(rows: list[Any]) -> MagicMock:
    """Devuelve un AsyncEngine mock que retorna rows al ejecutar SELECT."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_result)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_cm
    return mock_engine


def _make_row(
    bank_id: str,
    source_chain: list[str],
    rollout_pct: int = 100,
    user_cohort: str = "all",
) -> MagicMock:
    row = MagicMock()
    row.bank_id = bank_id
    row.source_chain = source_chain
    row.rollout_pct = rollout_pct
    row.user_cohort = user_cohort
    return row


@pytest.mark.asyncio
async def test_default_rules_when_db_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise() -> None:
        raise RuntimeError("DB down")

    monkeypatch.setattr(rules_mod, "get_engine", _raise)
    monkeypatch.setattr(rules_mod.settings, "routing_rules_db_required", False)

    result = await load_rules_from_db()
    assert result == DEFAULT_RULES


@pytest.mark.asyncio
async def test_db_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise() -> None:
        raise RuntimeError("DB down")

    monkeypatch.setattr(rules_mod, "get_engine", _raise)
    monkeypatch.setattr(rules_mod.settings, "routing_rules_db_required", True)

    with pytest.raises(RuntimeError, match="DB down"):
        await load_rules_from_db()


@pytest.mark.asyncio
async def test_db_results_mapped_to_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        _make_row("bchile", ["scraper.bchile"], rollout_pct=100),
        _make_row("bci", ["scraper.bci", "fintoc"], rollout_pct=50, user_cohort="beta"),
    ]
    mock_engine = _make_mock_engine(rows)
    monkeypatch.setattr(rules_mod, "get_engine", lambda: mock_engine)

    result = await load_rules_from_db()
    assert len(result) == 2

    bchile_rule = next(r for r in result if r.bank_id == "bchile")
    assert bchile_rule.source_chain == ["scraper.bchile"]
    assert bchile_rule.rollout_percentage == 100

    bci_rule = next(r for r in result if r.bank_id == "bci")
    assert bci_rule.source_chain == ["scraper.bci", "fintoc"]
    assert bci_rule.rollout_percentage == 50
    assert bci_rule.user_cohort == "beta"


@pytest.mark.asyncio
async def test_empty_db_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_engine = _make_mock_engine([])  # 0 filas
    monkeypatch.setattr(rules_mod, "get_engine", lambda: mock_engine)

    result = await load_rules_from_db()
    assert result == DEFAULT_RULES


@pytest.mark.asyncio
async def test_cache_respects_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_make_row("bchile", ["scraper.bchile"])]
    mock_engine = _make_mock_engine(rows)
    call_count = 0

    def counting_engine() -> MagicMock:
        nonlocal call_count
        call_count += 1
        return mock_engine

    monkeypatch.setattr(rules_mod, "get_engine", counting_engine)
    monkeypatch.setattr(rules_mod.settings, "routing_rules_cache_ttl_sec", 60)

    await load_rules_from_db()
    await load_rules_from_db()

    # La segunda llamada debe usar el cache — get_engine solo se llama 1 vez
    assert call_count == 1


@pytest.mark.asyncio
async def test_force_bypass_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_make_row("bchile", ["scraper.bchile"])]
    mock_engine = _make_mock_engine(rows)
    call_count = 0

    def counting_engine() -> MagicMock:
        nonlocal call_count
        call_count += 1
        return mock_engine

    monkeypatch.setattr(rules_mod, "get_engine", counting_engine)

    await load_rules_from_db()
    await load_rules_from_db(force=True)

    # force=True ignora el cache → 2 hits a DB
    assert call_count == 2


@pytest.mark.asyncio
async def test_invalidate_clears_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_make_row("bchile", ["scraper.bchile"])]
    mock_engine = _make_mock_engine(rows)
    call_count = 0

    def counting_engine() -> MagicMock:
        nonlocal call_count
        call_count += 1
        return mock_engine

    monkeypatch.setattr(rules_mod, "get_engine", counting_engine)

    await load_rules_from_db()
    invalidate_cache()
    await load_rules_from_db()

    # Después de invalidate, la segunda llamada va a DB
    assert call_count == 2
