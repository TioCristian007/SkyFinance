"""
Test del contrato DataSource y build_external_id.

build_external_id es CRÍTICO: debe ser determinístico.
La misma transacción real SIEMPRE debe producir el mismo id.
"""

from datetime import date
from sky.ingestion.contracts import (
    build_external_id,
    CanonicalMovement,
    MovementSource,
    SourceKind,
)


class TestBuildExternalId:
    def test_deterministic(self):
        """Mismo input → mismo output, siempre."""
        a = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS MALL")
        b = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS MALL")
        assert a == b

    def test_case_insensitive_description(self):
        """Descripciones con distinto case producen mismo id."""
        a = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS MALL")
        b = build_external_id("bchile", date(2026, 4, 15), -4890, "starbucks mall")
        assert a == b

    def test_different_amount_different_id(self):
        a = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS")
        b = build_external_id("bchile", date(2026, 4, 15), -5000, "STARBUCKS")
        assert a != b

    def test_different_bank_different_id(self):
        a = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS")
        b = build_external_id("falabella", date(2026, 4, 15), -4890, "STARBUCKS")
        assert a != b

    def test_starts_with_bank_id(self):
        eid = build_external_id("bchile", date(2026, 4, 15), -4890, "TEST")
        assert eid.startswith("bchile_")

    def test_length_consistent(self):
        eid = build_external_id("bchile", date(2026, 4, 15), -4890, "TEST")
        # bank_id + "_" + 16 hex chars
        assert len(eid) == len("bchile_") + 16


class TestCanonicalMovement:
    def test_frozen(self):
        """CanonicalMovement es inmutable."""
        m = CanonicalMovement(
            external_id="bchile_abc123",
            amount_clp=-4890,
            raw_description="STARBUCKS",
            occurred_at=date(2026, 4, 15),
            movement_source=MovementSource.ACCOUNT,
            source_kind=SourceKind.SCRAPER,
        )
        assert m.amount_clp == -4890
        try:
            m.amount_clp = 0  # type: ignore
            assert False, "Should be frozen"
        except AttributeError:
            pass
