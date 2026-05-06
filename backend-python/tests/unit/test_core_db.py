"""Tests de sky.core.db — get_aria_client()."""
from unittest.mock import MagicMock, patch

import sky.core.db as db_module
from sky.core.config import settings


def _reset_aria_client() -> None:
    db_module._aria_client = None


def test_get_aria_client_uses_service_key() -> None:
    """Verifica que se usa supabase_url + supabase_service_key (no anon key)."""
    _reset_aria_client()
    mock_client = MagicMock()

    with patch("sky.core.db.create_client", return_value=mock_client) as mock_create:
        result = db_module.get_aria_client()

    mock_create.assert_called_once()
    call_args = mock_create.call_args.args
    assert call_args[0] == settings.supabase_url
    assert call_args[1] == settings.supabase_service_key
    assert call_args[1] != settings.supabase_anon_key
    assert result is mock_client
    _reset_aria_client()


def test_get_aria_client_is_cached() -> None:
    """Segunda llamada devuelve la misma instancia sin crear otro cliente."""
    _reset_aria_client()
    mock_client = MagicMock()

    with patch("sky.core.db.create_client", return_value=mock_client) as mock_create:
        c1 = db_module.get_aria_client()
        c2 = db_module.get_aria_client()

    assert c1 is c2
    mock_create.assert_called_once()
    _reset_aria_client()


def test_get_aria_client_exposes_schema_method() -> None:
    """El cliente retornado tiene el método schema() requerido por ARIA."""
    _reset_aria_client()
    mock_client = MagicMock()

    with patch("sky.core.db.create_client", return_value=mock_client):
        client = db_module.get_aria_client()

    aria_ref = client.schema("aria")
    mock_client.schema.assert_called_once_with("aria")
    assert aria_ref is not None
    _reset_aria_client()
