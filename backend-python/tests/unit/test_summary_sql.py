"""Tests de la query SQL de summary — verifica filtros críticos."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock


async def test_summary_query_excludes_deleted_at() -> None:
    """La query de transacciones del summary debe incluir 'deleted_at IS NULL'."""
    from sky.api.routers.summary import _fetch_all

    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_mappings.first.return_value = None
    empty_rs = MagicMock()
    empty_rs.mappings.return_value = mock_mappings

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=empty_rs)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx

    await _fetch_all(mock_engine, "user-uuid", date(2026, 5, 1))

    tx_call_sql = str(mock_conn.execute.call_args_list[0][0][0])
    assert "deleted_at IS NULL" in tx_call_sql, (
        "La query de transacciones del summary no filtra deleted_at — "
        "movimientos borrados suman en ingresos/gastos"
    )
