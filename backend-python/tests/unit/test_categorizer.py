"""Tests del categorizador 3 capas."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sky.domain.categorizer import (
    _apply_layer1,
    _categorize_with_ai,
    _key_variants,
    _lookup_cache,
    _save_to_cache,
    categorize_movements,
    normalize_merchant,
)


class TestNormalizeMerchant:
    def test_strips_pago_prefix(self) -> None:
        assert normalize_merchant("PAGO: STARBUCKS MALL") == "starbucks mall"

    def test_strips_compra_comercio(self) -> None:
        assert normalize_merchant("COMPRA COMERCIO JUMBO LAS CONDES") == "jumbo las condes"

    def test_collapses_dashes(self) -> None:
        assert normalize_merchant("UBER--EATS--CL") == "uber eats cl"

    def test_caps_at_60_chars(self) -> None:
        long = "x" * 100
        assert len(normalize_merchant(long)) == 60


class TestLayer1Rules:
    @pytest.mark.parametrize("desc,amount,expected", [
        ("Traspaso de: Juan Perez", 50000, "income"),
        ("ABONO REMUNERACION SUELDO", 800000, "income"),
        ("Traspaso a: Ahorro", -10000, "transfer"),
        ("Khipu", -5000, "transfer"),
        ("Comision mantencion cta", -1500, "banking_fee"),
        ("BIP! Recarga", -3000, "transport"),
        ("COPEC PEAJE", -25000, "transport"),
        ("Netflix Suscripcion", -8500, "subscriptions"),
        ("Pago: Entel Movil", -25000, "utilities"),
        ("Salcobrand Vitacura", -12000, "health"),
        ("Pago TC Bchile", -200000, "debt_payment"),
        ("Aporte AFP", -50000, "savings"),
        ("Jumbo Las Condes", -45000, "food"),
        ("Starbucks Costanera", -5500, "food"),
        ("Rappi Restaurant", -12000, "food"),
        ("Uber Trip", -8500, "transport"),
        ("Falabella Online", -75000, "shopping"),
        ("Isapre Banmedica", -180000, "health"),
        ("Aguas Andinas", -25000, "utilities"),
    ])
    def test_rule_matches(self, desc: str, amount: int, expected: str) -> None:
        assert _apply_layer1(desc, amount) == expected

    def test_unknown_returns_none(self) -> None:
        assert _apply_layer1("FOO BAR XYZ", -1000) is None


@pytest.mark.asyncio
@patch("sky.domain.categorizer._lookup_cache", new_callable=AsyncMock)
@patch("sky.domain.categorizer._categorize_with_ai", new_callable=AsyncMock)
async def test_three_layers_priority(mock_ai: AsyncMock, mock_cache: AsyncMock) -> None:
    """Layer 1 gana sobre cache y AI. Cache gana sobre AI."""
    # _lookup_cache retorna key normalizada → categoría
    mock_cache.return_value = {"misterio compras": "shopping"}
    mock_ai.return_value = {"raro nuevo": "entertainment"}

    movements = [
        {"description": "Jumbo Las Condes", "amount": -10000},   # Layer 1 → food
        {"description": "Misterio Compras", "amount": -5000},    # Layer 2 → shopping
        {"description": "Raro Nuevo", "amount": -3000},          # Layer 3 → entertainment
    ]
    items = await categorize_movements(movements)
    assert items[0].category == "food"          and items[0].source == "rule"
    assert items[1].category == "shopping"      and items[1].source == "cache"
    assert items[2].category == "entertainment" and items[2].source == "ai"


@pytest.mark.asyncio
@patch("sky.domain.categorizer._lookup_cache", new_callable=AsyncMock)
@patch("sky.domain.categorizer._categorize_with_ai", new_callable=AsyncMock)
async def test_ai_failure_falls_back_to_other(mock_ai: AsyncMock, mock_cache: AsyncMock) -> None:
    mock_cache.return_value = {}
    mock_ai.return_value = {}  # AI no devolvió nada

    items = await categorize_movements(
        [{"description": "completamente desconocido", "amount": -5000}]
    )
    assert items[0].category == "other"
    assert items[0].source == "fallback"


@pytest.mark.asyncio
async def test_zero_amount_returns_other_fallback() -> None:
    items = await categorize_movements([{"description": "Anything", "amount": 0}])
    assert items[0].category == "other"


# ── Tests de _key_variants ────────────────────────────────────────────────────

class TestKeyVariants:
    def test_single_word(self) -> None:
        assert _key_variants("jumbo") == ["jumbo"]

    def test_multi_word(self) -> None:
        assert _key_variants("jumbo las condes") == ["jumbo las condes", "jumbo las", "jumbo"]

    def test_empty_returns_empty(self) -> None:
        assert _key_variants("") == []

    def test_extra_spaces_ignored(self) -> None:
        result = _key_variants("netflix  premium")
        assert "netflix" in result


# ── Tests de _lookup_cache ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lookup_cache_empty_input() -> None:
    result = await _lookup_cache([])
    assert result == {}


@pytest.mark.asyncio
@patch("sky.domain.categorizer.get_engine")
async def test_lookup_cache_hit_by_prefix(mock_get_engine: MagicMock) -> None:
    """Cache hit usando variant de prefijo ('jumbo' matchea 'jumbo las condes')."""
    mock_row = MagicMock()
    mock_row.merchant_key = "jumbo"
    mock_row.category = "food"
    mock_rs = MagicMock()
    mock_rs.fetchall.return_value = [mock_row]
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.connect.return_value = mock_ctx

    result = await _lookup_cache(["jumbo las condes"])
    assert result == {"jumbo las condes": "food"}


@pytest.mark.asyncio
@patch("sky.domain.categorizer.get_engine")
async def test_lookup_cache_miss_returns_empty(mock_get_engine: MagicMock) -> None:
    mock_rs = MagicMock()
    mock_rs.fetchall.return_value = []
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_rs)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.connect.return_value = mock_ctx

    result = await _lookup_cache(["sitio desconocido"])
    assert result == {}


# ── Tests de _save_to_cache ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_to_cache_empty_entries() -> None:
    await _save_to_cache([])  # no debe lanzar ni llamar engine


@pytest.mark.asyncio
@patch("sky.domain.categorizer.get_engine")
async def test_save_to_cache_calls_upsert(mock_get_engine: MagicMock) -> None:
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    entries = [
        {"merchant_key": "starbucks", "category": "food", "source": "ai", "confidence": 0.92}
    ]
    await _save_to_cache(entries)
    mock_conn.execute.assert_awaited_once()


@pytest.mark.asyncio
@patch("sky.domain.categorizer.get_engine")
async def test_save_to_cache_tolerates_execute_error(mock_get_engine: MagicMock) -> None:
    """Una excepción en execute no debe propagar — solo loguear warning."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_engine.return_value.begin.return_value = mock_ctx

    entries = [{"merchant_key": "oxxo", "category": "food", "source": "ai", "confidence": 0.85}]
    await _save_to_cache(entries)  # no debe lanzar


# ── Tests de _categorize_with_ai ─────────────────────────────────────────────

class _FakeTextBlock:
    """Simulacro de anthropic.types.TextBlock para evitar instanciación real."""
    type = "text"
    def __init__(self, text: str) -> None:
        self.text = text


@pytest.mark.asyncio
@patch("sky.domain.categorizer._save_to_cache", new_callable=AsyncMock)
@patch("sky.domain.categorizer.anthropic.AsyncAnthropic")
@patch("sky.domain.categorizer.TextBlock", _FakeTextBlock)
async def test_categorize_with_ai_success(
    mock_anthropic_cls: MagicMock,
    mock_save_cache: AsyncMock,
) -> None:
    items_json = json.dumps([{"key": "netflix", "category": "subscriptions", "confidence": 0.95}])
    mock_resp = MagicMock()
    mock_resp.content = [_FakeTextBlock(items_json)]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_resp)
    mock_anthropic_cls.return_value = mock_client

    result = await _categorize_with_ai(["netflix"])
    assert result == {"netflix": "subscriptions"}
    mock_save_cache.assert_awaited_once()


@pytest.mark.asyncio
@patch("sky.domain.categorizer._save_to_cache", new_callable=AsyncMock)
@patch("sky.domain.categorizer.anthropic.AsyncAnthropic")
@patch("sky.domain.categorizer.TextBlock", _FakeTextBlock)
async def test_categorize_with_ai_low_confidence_becomes_other(
    mock_anthropic_cls: MagicMock,
    mock_save_cache: AsyncMock,
) -> None:
    items_json = json.dumps([{"key": "misterio", "category": "food", "confidence": 0.3}])
    mock_resp = MagicMock()
    mock_resp.content = [_FakeTextBlock(items_json)]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_resp)
    mock_anthropic_cls.return_value = mock_client

    result = await _categorize_with_ai(["misterio"])
    assert result == {"misterio": "other"}


@pytest.mark.asyncio
async def test_categorize_with_ai_empty_input() -> None:
    result = await _categorize_with_ai([])
    assert result == {}


@pytest.mark.asyncio
@patch("sky.domain.categorizer.anthropic.AsyncAnthropic")
@patch("sky.domain.categorizer.TextBlock", _FakeTextBlock)
async def test_categorize_with_ai_exception_returns_empty(
    mock_anthropic_cls: MagicMock,
) -> None:
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("Network error"))
    mock_anthropic_cls.return_value = mock_client

    result = await _categorize_with_ai(["cualquier cosa"])
    assert result == {}
