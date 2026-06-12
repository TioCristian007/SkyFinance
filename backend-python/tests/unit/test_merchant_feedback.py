"""Tests del feedback loop de categorización (sprint categorización que aprende).

Regresiones obligatorias del sprint cubiertas acá:
- Frontera de privacidad: una transferencia/contraparte personal JAMÁS
  dispara la promoción al caché global (vota solo como override privado).
- Umbral anti-envenenamiento: sin quórum de usuarios distintos no se
  escribe nada en el caché global.
- La promoción escribe source='user' (la guarda de la 014 hace el resto).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sky.core.config import settings
from sky.domain.merchant_feedback import (
    _key_is_promotable,
    _maybe_promote,
    is_crowdsource_eligible,
    record_user_categorization,
)


def _engine_with(results: list[Any]) -> tuple[MagicMock, AsyncMock]:
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=results)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.begin.return_value = ctx
    return engine, mock_conn


def _count_row(category: str, voters: int) -> MagicMock:
    rs = MagicMock()
    row = MagicMock()
    row.category = category
    row.voters = voters
    rs.first.return_value = row
    return rs


# ── Frontera de privacidad: elegibilidad ─────────────────────────────────────

class TestElegibilidad:
    @pytest.mark.parametrize("desc,category,expected", [
        ("Transferencia a: Juan Perez", "food", False),
        ("TRASPASO DE: MAMA", "income", False),
        ("Traspaso a: Cuenta Ahorro", "savings", False),
        ("traspaso  de:  alguien", "food", False),
        ("Sushi Local Providencia", "transfer", False),  # categoría transfer nunca
        ("JUMBO LAS CONDES", "food", True),
        ("PAGO: STARBUCKS MALL", "food", True),
        ("aramco universida", "food", True),
        ("", "food", False),
        ("   ", "food", False),
    ])
    def test_solo_comercios_reales(self, desc: str, category: str, expected: bool) -> None:
        assert is_crowdsource_eligible(desc, category) is expected

    def test_key_promotable(self) -> None:
        assert _key_is_promotable("jumbo las condes") is True
        assert _key_is_promotable("transferencia a: juan perez") is False
        assert _key_is_promotable("") is False


# ── record_user_categorization ───────────────────────────────────────────────

async def test_transferencia_vota_pero_jamas_promueve() -> None:
    """Regresión frontera de privacidad: el voto inelegible se guarda como
    override privado (elig=False) y NO ejecuta la consulta de promoción."""
    engine, conn = _engine_with([MagicMock()])
    with patch("sky.domain.merchant_feedback.get_engine", return_value=engine):
        await record_user_categorization("u1", "Transferencia a: Juan Perez", "food")

    assert conn.execute.await_count == 1  # solo el upsert del voto
    params = conn.execute.await_args_list[0].args[1]
    assert params["elig"] is False
    assert params["cat"] == "food"


async def test_bajo_umbral_no_promueve() -> None:
    """Regresión anti-envenenamiento: 2 usuarios < umbral 3 → global intacto."""
    engine, conn = _engine_with([MagicMock(), _count_row("food", 2)])
    with patch("sky.domain.merchant_feedback.get_engine", return_value=engine):
        await record_user_categorization("u1", "JUMBO LAS CONDES", "food")

    assert conn.execute.await_count == 2  # voto + conteo, sin upsert global


async def test_con_quorum_promueve_con_source_user() -> None:
    engine, conn = _engine_with([MagicMock(), _count_row("food", 3), MagicMock()])
    with patch("sky.domain.merchant_feedback.get_engine", return_value=engine):
        await record_user_categorization("u1", "JUMBO LAS CONDES", "food")

    assert conn.execute.await_count == 3
    sql = str(conn.execute.await_args_list[2].args[0])
    assert "upsert_merchant_category" in sql
    assert "'user'" in sql  # la promoción siempre escribe source='user'
    params = conn.execute.await_args_list[2].args[1]
    assert params["p_merchant_key"] == "jumbo las condes"  # key normalizada
    assert params["p_category"] == "food"


async def test_promueve_la_mayoria_no_el_voto_emitido() -> None:
    """El global converge a la categoría con más usuarios distintos, aunque
    el voto recién emitido diga otra cosa."""
    engine, conn = _engine_with([MagicMock(), _count_row("food", 4), MagicMock()])
    with patch("sky.domain.merchant_feedback.get_engine", return_value=engine):
        await record_user_categorization("u9", "JUMBO LAS CONDES", "shopping")

    params = conn.execute.await_args_list[2].args[1]
    assert params["p_category"] == "food"


async def test_umbral_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "merchant_vote_promotion_threshold", 1)
    engine, conn = _engine_with([MagicMock(), _count_row("food", 1), MagicMock()])
    with patch("sky.domain.merchant_feedback.get_engine", return_value=engine):
        await record_user_categorization("u1", "JUMBO LAS CONDES", "food")

    assert conn.execute.await_count == 3


async def test_descripcion_vacia_no_toca_db() -> None:
    with patch("sky.domain.merchant_feedback.get_engine") as mock_ge:
        await record_user_categorization("u1", "", "food")
    mock_ge.assert_not_called()


async def test_voto_actualizable_on_conflict() -> None:
    """El upsert del voto usa ON CONFLICT por (user_id, merchant_key):
    el usuario puede cambiar de opinión sin duplicar filas."""
    engine, conn = _engine_with([MagicMock(), _count_row("food", 1)])
    with patch("sky.domain.merchant_feedback.get_engine", return_value=engine):
        await record_user_categorization("u1", "JUMBO LAS CONDES", "food")

    sql = str(conn.execute.await_args_list[0].args[0])
    assert "ON CONFLICT (user_id, merchant_key) DO UPDATE" in sql


# ── Defensa en profundidad en la promoción ───────────────────────────────────

async def test_defensa_en_profundidad_key_transferencia() -> None:
    """Aunque algún camino futuro llegue con una key de transferencia,
    _maybe_promote se niega antes de tocar la DB."""
    conn = AsyncMock()
    await _maybe_promote(conn, "transferencia a: juan perez")
    conn.execute.assert_not_awaited()


async def test_promote_sin_votos_no_escribe() -> None:
    rs = MagicMock()
    rs.first.return_value = None
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=rs)
    await _maybe_promote(conn, "comercio nuevo")
    assert conn.execute.await_count == 1  # solo el conteo
