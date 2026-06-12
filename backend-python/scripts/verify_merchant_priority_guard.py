"""
scripts/verify_merchant_priority_guard.py — Verifica la migración 014 contra DB real.

Ejecuta la guarda de prioridad de upsert_merchant_category de verdad (no mocks)
dentro de una transacción que SIEMPRE hace ROLLBACK — no deja residuos ni en prod.

Verifica:
    1. El CHECK de merchant_categories.source acepta 'user'.
    2. Guarda de prioridad: una escritura 'ai' NO pisa una fila 'user'
       (ni categoría, ni source, ni incrementa hits).
    3. Una escritura 'user' SÍ puede actualizar una fila 'user' (consenso nuevo).
    4. Una escritura 'ai' sigue pisando una fila 'ai' (comportamiento original).
    5. merchant_category_votes existe con RLS habilitado.

Uso (igual que audit_rls_policies.py — correr tras aplicar la 014, staging y prod):
    cd backend-python
    .venv\\Scripts\\activate
    python scripts/verify_merchant_priority_guard.py

Exit 0 = guarda operativa. Exit 1 = la migración no quedó bien aplicada.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sky.core.db import get_engine

_KEY = "__sky_selftest_guard__"


async def _fetch(conn: AsyncConnection) -> tuple[str, str, int]:
    rs = await conn.execute(
        text(
            "SELECT category, source, hits FROM public.merchant_categories"
            " WHERE merchant_key = :k"
        ),
        {"k": _KEY},
    )
    row = rs.first()
    if row is None:
        raise AssertionError(f"fila {_KEY} no existe tras upsert")
    return str(row.category), str(row.source), int(row.hits)


async def _upsert(conn: AsyncConnection, category: str, source: str) -> None:
    await conn.execute(
        text("SELECT public.upsert_merchant_category(:k, :c, :s, 1.0)"),
        {"k": _KEY, "c": category, "s": source},
    )


async def main() -> int:
    engine = get_engine()
    failures: list[str] = []

    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            # Limpieza defensiva del sentinel dentro de la transacción
            await conn.execute(
                text("DELETE FROM public.merchant_categories WHERE merchant_key = :k"),
                {"k": _KEY},
            )

            # 1. CHECK acepta 'user'
            await _upsert(conn, "food", "user")
            cat, src, hits = await _fetch(conn)
            if (cat, src, hits) != ("food", "user", 1):
                failures.append(f"insert user: esperaba (food,user,1), hay ({cat},{src},{hits})")

            # 2. 'ai' NO pisa 'user' (ni incrementa hits)
            await _upsert(conn, "shopping", "ai")
            cat, src, hits = await _fetch(conn)
            if (cat, src, hits) != ("food", "user", 1):
                failures.append(
                    f"GUARDA ROTA: 'ai' piso un voto de usuario — ({cat},{src},{hits})"
                )

            # 3. 'user' SÍ actualiza 'user'
            await _upsert(conn, "transport", "user")
            cat, src, _ = await _fetch(conn)
            if (cat, src) != ("transport", "user"):
                failures.append(f"user no pudo actualizar user: ({cat},{src})")

            # 4. 'ai' sigue pisando 'ai' (no romper el flujo original)
            await conn.execute(
                text("DELETE FROM public.merchant_categories WHERE merchant_key = :k"),
                {"k": _KEY},
            )
            await _upsert(conn, "food", "ai")
            await _upsert(conn, "shopping", "ai")
            cat, src, hits = await _fetch(conn)
            if (cat, src, hits) != ("shopping", "ai", 2):
                failures.append(f"ai->ai cambio de comportamiento: ({cat},{src},{hits})")

            # 5. Tabla de votos con RLS
            rs = await conn.execute(
                text(
                    "SELECT relrowsecurity FROM pg_class"
                    " WHERE oid = 'public.merchant_category_votes'::regclass"
                )
            )
            rls = rs.scalar()
            if not rls:
                failures.append("merchant_category_votes sin RLS habilitado")
        except Exception as exc:
            failures.append(f"excepcion durante verificacion: {exc}")
        finally:
            await trans.rollback()

    print("\n# Verificacion migracion 014 — guarda de prioridad user > ai\n")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        print("\nExit 1 — la migracion 014 no quedo bien aplicada.")
        return 1

    print("  OK: CHECK source acepta 'user'")
    print("  OK: 'ai' no pisa 'user' (categoria, source y hits intactos)")
    print("  OK: 'user' actualiza 'user'")
    print("  OK: 'ai' sigue actualizando 'ai'")
    print("  OK: merchant_category_votes con RLS habilitado")
    print("\nTodo verificado con ROLLBACK (sin residuos). Exit 0.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
