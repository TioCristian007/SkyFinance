"""Tests del catálogo único de bancos en sky.ingestion.sources."""
from __future__ import annotations

from sky.ingestion.sources import SUPPORTED_BANKS, account_type_for


def test_supported_banks_required_fields() -> None:
    required = {"id", "name", "icon", "status", "has_2fa", "account_type"}
    for bank in SUPPORTED_BANKS:
        missing = required - bank.keys()
        assert not missing, f"{bank['id']} le faltan campos: {missing}"


def test_supported_banks_account_type_is_string() -> None:
    for bank in SUPPORTED_BANKS:
        assert isinstance(bank["account_type"], str), f"{bank['id']}.account_type debe ser str"
        assert bank["account_type"], f"{bank['id']}.account_type no debe ser vacío"


def test_account_type_for_known_banks() -> None:
    assert account_type_for("bchile") == "Cta. Corriente"
    assert account_type_for("bci") == "Cta. Vista"


def test_account_type_for_unknown_falls_back() -> None:
    assert account_type_for("banco_inexistente") == "Cuenta"
    assert account_type_for("") == "Cuenta"


def test_supported_banks_ids_unique() -> None:
    ids = [str(b["id"]) for b in SUPPORTED_BANKS]
    assert len(ids) == len(set(ids)), "IDs de bancos duplicados en SUPPORTED_BANKS"


def test_default_rules_bank_ids_subset_of_supported_banks() -> None:
    """DEFAULT_RULES solo debe contener bancos con source registrada (hoy bchile + bci)."""
    from sky.ingestion.routing.rules import DEFAULT_RULES

    supported_ids = {str(b["id"]) for b in SUPPORTED_BANKS}
    for rule in DEFAULT_RULES:
        assert rule.bank_id in supported_ids, (
            f"DEFAULT_RULES contiene '{rule.bank_id}' que no está en SUPPORTED_BANKS"
        )
