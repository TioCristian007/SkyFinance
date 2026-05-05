"""Tests de pg_try_advisory_lock wrapper."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sky.core.locks import _key_from_string, try_advisory_lock


def test_key_is_deterministic() -> None:
    assert _key_from_string("foo") == _key_from_string("foo")


def test_key_changes_with_input() -> None:
    assert _key_from_string("foo") != _key_from_string("bar")


def test_key_fits_int64() -> None:
    k = _key_from_string("sync:bank_account:abc-def-1234")
    assert -(2**63) <= k <= (2**63 - 1)


def _make_mock_engine(lock_acquired: bool) -> MagicMock:
    """Helper: mock engine donde pg_try_advisory_lock devuelve lock_acquired."""
    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar.return_value = lock_acquired
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_scalar_result)
    mock_conn.commit = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx
    return mock_engine


@pytest.mark.asyncio
@patch("sky.core.locks.get_engine")
async def test_advisory_lock_acquired(mock_get_engine: MagicMock) -> None:
    """Cuando pg_try_advisory_lock devuelve True, yields True y libera al salir."""
    mock_get_engine.return_value = _make_mock_engine(lock_acquired=True)
    mock_conn = mock_get_engine.return_value.connect.return_value.__aenter__.return_value

    async with try_advisory_lock("test:key:acquired") as got:
        assert got is True

    # Debe haber llamado pg_try_advisory_lock Y pg_advisory_unlock
    assert mock_conn.execute.await_count == 2
    assert mock_conn.commit.await_count == 1


@pytest.mark.asyncio
@patch("sky.core.locks.get_engine")
async def test_advisory_lock_not_acquired(mock_get_engine: MagicMock) -> None:
    """Cuando pg_try_advisory_lock devuelve False, yields False y NO libera."""
    mock_get_engine.return_value = _make_mock_engine(lock_acquired=False)
    mock_conn = mock_get_engine.return_value.connect.return_value.__aenter__.return_value

    async with try_advisory_lock("test:key:busy") as got:
        assert got is False

    # Solo se llamó pg_try_advisory_lock, NO pg_advisory_unlock
    assert mock_conn.execute.await_count == 1
    mock_conn.commit.assert_not_awaited()


@pytest.mark.asyncio
@patch("sky.core.locks.get_engine")
async def test_advisory_lock_released_even_on_exception(mock_get_engine: MagicMock) -> None:
    """El unlock se ejecuta aunque el bloque interior lance excepción."""
    mock_get_engine.return_value = _make_mock_engine(lock_acquired=True)
    mock_conn = mock_get_engine.return_value.connect.return_value.__aenter__.return_value

    with pytest.raises(ValueError, match="test error"):
        async with try_advisory_lock("test:key:exception") as got:
            assert got is True
            raise ValueError("test error")

    # pg_advisory_unlock debe haberse llamado en el finally
    assert mock_conn.execute.await_count == 2
