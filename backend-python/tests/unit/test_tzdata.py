"""Guarda de regresión: tzdata debe estar instalado (pyproject.toml dependencies).

python:3.12-slim no incluye datos de zona horaria del sistema. Sin el paquete
`tzdata`, ZoneInfo('America/Santiago') lanza ZoneInfoNotFoundError y /summary
responde 500. Este test falla inmediatamente si alguien elimina tzdata del
manifiesto de dependencias.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo


def test_tzdata_disponible_para_zona_horaria_chile() -> None:
    tz = ZoneInfo("America/Santiago")
    assert tz.key == "America/Santiago"


def test_tzdata_disponible_para_utc() -> None:
    tz = ZoneInfo("UTC")
    assert tz.key == "UTC"
