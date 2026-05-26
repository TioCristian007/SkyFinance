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

    # ── native_id path ────────────────────────────────────────────────────────

    def test_native_id_deterministic(self):
        """Mismo native_id → mismo external_id, sin importar fecha/monto/desc."""
        native = "JUV000708124183:20260526 09:42:37:5670:cargo:1"
        a = build_external_id("bchile", date(2026, 5, 26), -1000, "PAGO", native_id=native)
        b = build_external_id("bchile", date(2026, 5, 26), -1000, "PAGO", native_id=native)
        assert a == b

    def test_native_id_wins_over_other_fields(self):
        """Con native_id, cambiar fecha/monto/desc no altera el id."""
        native = "NATIVE-XYZ-123"
        base = build_external_id("bchile", date(2026, 5, 1), -5000, "DESC A", native_id=native)
        diff_date = build_external_id("bchile", date(2020, 1, 1), -9999, "DESC B", native_id=native)
        assert base == diff_date

    def test_native_id_vs_no_native_id_produce_different_ids(self):
        with_native = build_external_id(
            "bchile", date(2026, 4, 15), -4890, "STARBUCKS", native_id="ID123"
        )
        without = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS")
        assert with_native != without

    def test_no_native_id_fallback_with_balance(self):
        """Sin native_id, distintos balances producen distintos ids."""
        a = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS", balance=1_000_000)
        b = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS", balance=999_000)
        assert a != b

    def test_no_native_id_with_same_balance_is_stable(self):
        a = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS", balance=500_000)
        b = build_external_id("bchile", date(2026, 4, 15), -4890, "STARBUCKS", balance=500_000)
        assert a == b


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
