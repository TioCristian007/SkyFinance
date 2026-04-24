"""
sky.ingestion.parsers.bchile_parser — Helpers de normalización BChile.

BChile devuelve fechas en varios formatos según el endpoint:
    - "2026-04-15" (ISO)
    - "15-04-2026" (DD-MM-YYYY)
    - "15/04/2026" (DD/MM/YYYY)
    - "2026-04-15T00:00:00" (ISO con tiempo)
    - epoch millis a veces en campos "timestamp"
"""

from __future__ import annotations

import re
from datetime import date, datetime


def normalize_date(raw: str | int | None) -> date:
    """Normaliza cualquier formato de fecha de BChile a date."""
    if raw is None:
        return date.today()

    if isinstance(raw, int):
        # Epoch millis
        try:
            return datetime.fromtimestamp(raw / 1000).date()
        except Exception:
            return date.today()

    if not isinstance(raw, str):
        return date.today()

    s = raw.strip()
    if not s:
        return date.today()

    # ISO con T
    if "T" in s:
        s = s.split("T")[0]

    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            pass

    # DD-MM-YYYY o DD/MM/YYYY
    m = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})$", s)
    if m:
        d, mo, y = m.groups()
        try:
            return date(int(y), int(mo), int(d))
        except ValueError:
            pass

    # Fallback
    return date.today()


def parse_amount(raw: str | int | float | None) -> int:
    """Normaliza monto a int (pesos chilenos enteros)."""
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    if not isinstance(raw, str):
        return 0

    # Quitar símbolos, espacios, puntos de miles
    cleaned = re.sub(r"[^\d\-,]", "", raw.strip())
    # Si hay coma, asumimos decimales → tomar solo la parte entera
    if "," in cleaned:
        cleaned = cleaned.split(",")[0]

    try:
        return int(cleaned) if cleaned else 0
    except ValueError:
        return 0
