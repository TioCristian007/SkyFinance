"""
Test del contrato DataSource y build_external_id.

build_external_id es CRÍTICO: debe ser determinístico.
La misma transacción real SIEMPRE debe producir el mismo id.
"""

from datetime import date

from sky.ingestion.contracts import (
    AllSourcesFailedError,
    CanonicalMovement,
    CircuitOpenError,
    MovementSource,
    RecoverableIngestionError,
    SourceKind,
    build_external_id,
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


class TestAllSourcesFailedError:
    def test_str_includes_source_type_and_message(self) -> None:
        cause = RecoverableIngestionError("Scraper falló: X")
        exc = AllSourcesFailedError("bchile", [("scraper.bchile", cause)])
        s = str(exc)
        assert "scraper.bchile" in s
        assert "RecoverableIngestionError" in s
        assert "Scraper falló: X" in s

    def test_primary_cause_returns_last_error(self) -> None:
        e1 = RecoverableIngestionError("first")
        e2 = CircuitOpenError("second")
        exc = AllSourcesFailedError("bchile", [("src.a", e1), ("src.b", e2)])
        assert exc.primary_cause is e2

    def test_primary_cause_empty_errors_returns_none(self) -> None:
        exc = AllSourcesFailedError("bchile", [])
        assert exc.primary_cause is None

    def test_empty_errors_detail_message(self) -> None:
        exc = AllSourcesFailedError("bchile", [])
        assert "sin proveedores disponibles" in str(exc)

    def test_multiple_errors_in_str(self) -> None:
        exc = AllSourcesFailedError("bchile", [
            ("src.a", RecoverableIngestionError("a down")),
            ("src.b", CircuitOpenError("circuito abierto")),
        ])
        s = str(exc)
        assert "src.a" in s
        assert "src.b" in s
        assert "CircuitOpenError" in s


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
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass
