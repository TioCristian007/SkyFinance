"""
scripts/verify_fase12_schema.py — Verificaciones pre-Fase 12.

Verifica 3 cosas antes de codear:
  1. ¿Existe pg_cron extension? (define si purge va en DB o en worker ARQ)
  2. Schema real de data_export_requests (columnas exactas)
  3. Schema real de earned_badges (necesario para data export)

Uso:
    cd backend-python
    .venv\\Scripts\\activate
    python scripts/verify_fase12_schema.py
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from sky.core.db import get_engine


async def main() -> None:
    engine = get_engine()

    async with engine.connect() as conn:
        # ─── 1. pg_cron extension ─────────────────────────────────────────────
        print("\n=== 1. pg_cron extension ===")
        r = await conn.execute(
            text(
                "SELECT name, default_version, installed_version "
                "FROM pg_available_extensions WHERE name = 'pg_cron'"
            )
        )
        rows = r.fetchall()
        if rows:
            row = rows[0]
            print(f"  name={row[0]!r}  default_version={row[1]!r}  installed_version={row[2]!r}")
            if row[2]:
                print("  RESULTADO: pg_cron INSTALADO")
            else:
                print("  RESULTADO: pg_cron disponible pero NO instalado")
        else:
            print("  RESULTADO: pg_cron NO EXISTE en este servidor")

        # ─── 2. Schema real de data_export_requests ───────────────────────────
        print("\n=== 2. Schema de data_export_requests ===")
        r2 = await conn.execute(
            text(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'data_export_requests'
                ORDER BY ordinal_position
                """
            )
        )
        rows2 = r2.fetchall()
        if rows2:
            for row in rows2:
                print(f"  {row[0]!r:30s} {row[1]!r:20s} nullable={row[2]!r}  default={row[3]!r}")
        else:
            print("  → Tabla data_export_requests NO EXISTE")

        # ─── 3. Schema real de earned_badges ─────────────────────────────────
        print("\n=== 3. Schema de earned_badges ===")
        r3 = await conn.execute(
            text(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'earned_badges'
                ORDER BY ordinal_position
                """
            )
        )
        rows3 = r3.fetchall()
        if rows3:
            for row in rows3:
                print(f"  {row[0]!r:30s} {row[1]!r:20s} nullable={row[2]!r}  default={row[3]!r}")
        else:
            print("  → Tabla earned_badges NO EXISTE")

        # ─── Extra: verificar RLS en audit_log ───────────────────────────────
        print("\n=== 4. Estado RLS en audit_log ===")
        r4 = await conn.execute(
            text(
                """
                SELECT policyname, cmd, qual
                FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'audit_log'
                """
            )
        )
        rows4 = r4.fetchall()
        if rows4:
            for row in rows4:
                print(f"  policy={row[0]!r}  cmd={row[1]!r}  qual={row[2]!r}")
        else:
            print("  → No hay policies en audit_log (o RLS no está habilitado)")

        # ─── Extra: verificar Supabase Storage buckets disponibles ───────────
        print("\n=== 5. Buckets en Supabase Storage ===")
        try:
            r5 = await conn.execute(
                text("SELECT id, name, public FROM storage.buckets ORDER BY name")
            )
            rows5 = r5.fetchall()
            if rows5:
                for row in rows5:
                    print(f"  id={row[0]!r}  name={row[1]!r}  public={row[2]!r}")
            else:
                print("  → No hay buckets creados aún")
        except Exception as exc:
            print(f"  → No se pudo acceder a storage.buckets: {exc}")

    await engine.dispose()
    print("\n=== Verificación completa ===\n")


if __name__ == "__main__":
    asyncio.run(main())
