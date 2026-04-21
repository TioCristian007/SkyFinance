"""Pytest fixtures compartidas."""
import pytest


@pytest.fixture
def test_encryption_key() -> str:
    return "test_key_for_unit_tests_only_32chars!"
