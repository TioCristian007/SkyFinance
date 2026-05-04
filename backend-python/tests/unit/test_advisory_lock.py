"""Tests de pg_try_advisory_lock wrapper."""
from sky.core.locks import _key_from_string


def test_key_is_deterministic() -> None:
    assert _key_from_string("foo") == _key_from_string("foo")


def test_key_changes_with_input() -> None:
    assert _key_from_string("foo") != _key_from_string("bar")


def test_key_fits_int64() -> None:
    k = _key_from_string("sync:bank_account:abc-def-1234")
    assert -(2**63) <= k <= (2**63 - 1)


# Test de adquisición real requiere DB → vive en tests/integration
