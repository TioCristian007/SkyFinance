"""Tests para sky.worker.jobs.audit_purge."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_engine():
    """Engine con conn.execute que retorna un scalar."""
    engine = MagicMock()
    conn = AsyncMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=conn)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine, conn


async def test_audit_purge_returns_deleted_count(mock_engine):
    engine, conn = mock_engine
    result_mock = MagicMock()
    result_mock.scalar.return_value = 42
    conn.execute = AsyncMock(return_value=result_mock)

    with patch("sky.worker.jobs.audit_purge.get_engine", return_value=engine):
        from sky.worker.jobs.audit_purge import audit_purge_job

        out = await audit_purge_job({})

    assert out == {"deleted": 42}
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args
    # Verifica que el SQL llama a la función con el parámetro :days
    sql_text = str(call_args[0][0])
    assert "purge_audit_log_old" in sql_text
    assert ":days" in sql_text


async def test_audit_purge_idempotent_zero(mock_engine):
    """Retorna 0 cuando no hay registros que purgar — sin error."""
    engine, conn = mock_engine
    result_mock = MagicMock()
    result_mock.scalar.return_value = 0
    conn.execute = AsyncMock(return_value=result_mock)

    with patch("sky.worker.jobs.audit_purge.get_engine", return_value=engine):
        from sky.worker.jobs.audit_purge import audit_purge_job

        out = await audit_purge_job({})

    assert out == {"deleted": 0}


async def test_audit_purge_no_log_event_called(mock_engine):
    """El purge NO llama a log_event — no se auto-audita."""
    engine, conn = mock_engine
    result_mock = MagicMock()
    result_mock.scalar.return_value = 5
    conn.execute = AsyncMock(return_value=result_mock)

    with (
        patch("sky.worker.jobs.audit_purge.get_engine", return_value=engine),
        patch("sky.core.audit.log_event", new_callable=AsyncMock) as mock_log,
    ):
        from sky.worker.jobs.audit_purge import audit_purge_job

        await audit_purge_job({})

    mock_log.assert_not_called()


async def test_audit_purge_db_error_propagates(mock_engine):
    """Si la DB lanza excepción, el job la propaga (no swallow)."""
    engine, conn = mock_engine
    conn.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

    with patch("sky.worker.jobs.audit_purge.get_engine", return_value=engine):
        from sky.worker.jobs.audit_purge import audit_purge_job

        with pytest.raises(RuntimeError, match="DB connection lost"):
            await audit_purge_job({})


async def test_audit_purge_max_tries_is_one():
    """max_tries=1 configurado en el job — ARQ no auto-retry."""
    from sky.worker.jobs.audit_purge import audit_purge_job

    assert getattr(audit_purge_job, "max_tries", None) == 1


async def test_audit_purge_uses_retention_days_from_settings(mock_engine):
    """El job pasa settings.audit_log_retention_days al SQL (no hardcoded 90)."""
    engine, conn = mock_engine
    result_mock = MagicMock()
    result_mock.scalar.return_value = 0
    conn.execute = AsyncMock(return_value=result_mock)

    with (
        patch("sky.worker.jobs.audit_purge.get_engine", return_value=engine),
        patch("sky.worker.jobs.audit_purge.settings") as mock_settings,
    ):
        mock_settings.audit_log_retention_days = 180

        from sky.worker.jobs.audit_purge import audit_purge_job

        await audit_purge_job({})

    # Bind param :days debe recibir el valor del setting, no hardcoded 90
    call_kwargs = conn.execute.call_args[0][1]
    assert call_kwargs.get("days") == 180
