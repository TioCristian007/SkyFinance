"""Tests del categorizador 3 capas."""
from unittest.mock import AsyncMock, patch

import pytest

from sky.domain.categorizer import (
    _apply_layer1,
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
