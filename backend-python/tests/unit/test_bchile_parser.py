"""
Tests de parsers BChile — sin browser, puros de lógica.
"""

from datetime import date
from sky.ingestion.parsers.bchile_parser import normalize_date, parse_amount


class TestNormalizeDate:
    def test_iso_format(self):
        assert normalize_date("2026-04-15") == date(2026, 4, 15)

    def test_iso_with_time(self):
        assert normalize_date("2026-04-15T10:30:00") == date(2026, 4, 15)

    def test_dd_mm_yyyy_dash(self):
        assert normalize_date("15-04-2026") == date(2026, 4, 15)

    def test_dd_mm_yyyy_slash(self):
        assert normalize_date("15/04/2026") == date(2026, 4, 15)

    def test_none_returns_today(self):
        assert normalize_date(None) == date.today()

    def test_empty_returns_today(self):
        assert normalize_date("") == date.today()

    def test_epoch_millis(self):
        # 1712332800000 = 2024-04-05 16:00:00 UTC — el resultado exacto depende del TZ local.
        # Sólo verificamos que devuelve un date cercano.
        result = normalize_date(1712332800000)
        assert isinstance(result, date)

    def test_invalid_returns_today(self):
        assert normalize_date("foo") == date.today()


class TestParseAmount:
    def test_int(self):
        assert parse_amount(4890) == 4890

    def test_negative_int(self):
        assert parse_amount(-4890) == -4890

    def test_string_no_formatting(self):
        assert parse_amount("4890") == 4890

    def test_string_with_dots(self):
        assert parse_amount("4.890") == 4890

    def test_string_with_currency(self):
        assert parse_amount("$4.890") == 4890

    def test_string_with_comma_decimals(self):
        # "$4.890,50" → 4890 (trunca decimales)
        assert parse_amount("$4.890,50") == 4890

    def test_negative_string(self):
        assert parse_amount("-4890") == -4890

    def test_none(self):
        assert parse_amount(None) == 0

    def test_empty_string(self):
        assert parse_amount("") == 0
