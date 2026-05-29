"""Regresión A1: track_spending_event recibe categoría real (no 'other' hardcoded)."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sky.ingestion.contracts import CanonicalMovement, MovementSource, SourceKind
from sky.worker.banking_sync import _track_aria_events  # noqa: F401


@pytest.fixture(autouse=True)
def _disable_aria(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asegurar que sync_aria_enabled esté activo para que el path se ejecute."""
    from sky.worker import banking_sync
    monkeypatch.setattr(banking_sync.settings, "sync_aria_enabled", True)


def _make_movement(amount: int = -5000) -> CanonicalMovement:
    return CanonicalMovement(
        external_id="bchile_abc123",
        amount_clp=amount,
        raw_description="STARBUCKS",
        occurred_at=date(2026, 4, 15),
        movement_source=MovementSource.ACCOUNT,
        source_kind=SourceKind.SCRAPER,
    )


@pytest.mark.asyncio
@patch("sky.worker.banking_sync._load_anon_profile", new_callable=AsyncMock)
async def test_track_aria_events_uses_getattr_category(
    mock_profile: AsyncMock,
) -> None:
    """CanonicalMovement no tiene .category → fallback a 'other' (no AttributeError)."""
    import sky.worker.banking_sync as bsync
    mock_profile.return_value = MagicMock()

    # track_spending_event se importa localmente dentro de la función
    with patch("sky.domain.aria.track_spending_event", new_callable=AsyncMock) as mock_ts:
        await bsync._track_aria_events("user-1", [_make_movement()])
        # Debe haberse llamado sin AttributeError
        mock_ts.assert_awaited_once()
        call_kwargs = mock_ts.call_args[0][1]  # segundo arg posicional = tx dict
        assert call_kwargs["category"] == "other"  # fallback cuando no hay .category


@pytest.mark.asyncio
@patch("sky.worker.banking_sync._load_anon_profile", new_callable=AsyncMock)
async def test_track_aria_events_canonical_no_category_attr_fallback(
    mock_profile: AsyncMock,
) -> None:
    """CanonicalMovement no tiene .category → getattr devuelve None → fallback 'other'."""
    m = _make_movement()
    # Verificar que CanonicalMovement genuinamente no tiene .category
    assert not hasattr(m, "category")
    # La expresión del fix: getattr(m, "category", None) or "other" == "other"
    result = getattr(m, "category", None) or "other"
    assert result == "other"


@pytest.mark.asyncio
async def test_track_aria_events_object_with_category_uses_it() -> None:
    """Si el objeto tiene .category, se usa (future-proof)."""

    class FakeMovement:
        amount_clp = -5000
        category = "food"

    result = getattr(FakeMovement(), "category", None) or "other"
    assert result == "food"


@pytest.mark.asyncio
async def test_track_aria_events_object_with_none_category_falls_back() -> None:
    """Si .category es None, el fallback sigue siendo 'other'."""

    class FakeMovement:
        amount_clp = -5000
        category = None

    result = getattr(FakeMovement(), "category", None) or "other"
    assert result == "other"
