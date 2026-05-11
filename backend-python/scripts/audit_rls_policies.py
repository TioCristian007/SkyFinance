"""
scripts/audit_rls_policies.py — Verifica RLS en todas las tablas public.* y aria.*.

Conecta con service_role. SOLO SELECT — nunca crea, modifica ni borra policies.

Uso:
    cd backend-python
    .venv\\Scripts\\activate
    python scripts/audit_rls_policies.py

Exit 0 = todas las tablas tienen RLS habilitado.
Exit 1 = hay tablas sin RLS o con policies que exponen aria.* a anon/authenticated.

Output: report markdown en stdout. Guardable con:
    python scripts/audit_rls_policies.py > rls_report.md
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from sqlalchemy import text

from sky.core.db import get_engine


async def main() -> int:
    engine = get_engine()
    issues: list[str] = []

    async with engine.connect() as conn:
        tables_result = await conn.execute(
            text("""
                SELECT t.schemaname, t.tablename, c.relrowsecurity
                FROM pg_tables t
                JOIN pg_class c ON c.relname = t.tablename
                JOIN pg_namespace n ON n.oid = c.relnamespace
                                   AND n.nspname = t.schemaname
                WHERE t.schemaname IN ('public', 'aria')
                ORDER BY t.schemaname, t.tablename
            """)
        )
        tables = tables_result.fetchall()

        policies_result = await conn.execute(
            text("""
                SELECT schemaname, tablename, policyname, cmd, roles, qual
                FROM pg_policies
                WHERE schemaname IN ('public', 'aria')
                ORDER BY schemaname, tablename, policyname
            """)
        )
        policies_by_table: dict[tuple[str, str], list[Any]] = {}
        for row in policies_result.fetchall():
            key = (str(row[0]), str(row[1]))
            policies_by_table.setdefault(key, []).append(row)

    print("\n# RLS Audit Report -- Sky Finance")
    print(f"\n## Tablas auditadas: {len(tables)}\n")
    print("| Schema | Tabla | RLS | N policies | Evaluacion |")
    print("|--------|-------|-----|------------|------------|")

    for schema, table, rls_enabled in tables:
        key = (str(schema), str(table))
        table_policies = policies_by_table.get(key, [])
        n_policies = len(table_policies)

        has_restrictive = any(
            str(p[5]).strip() in ("false", "(false)")
            for p in table_policies
        )
        # aria.* no debe tener policies que expongan a anon o authenticated
        aria_exposed = str(schema) == "aria" and any(
            "anon" in str(p[4]) or "authenticated" in str(p[4])
            for p in table_policies
        )

        if not rls_enabled:
            eval_str = "FAIL: RLS disabled"
            issues.append(f"{schema}.{table}: RLS no habilitado")
        elif aria_exposed:
            eval_str = "FAIL: aria.* expuesto a anon/authenticated"
            issues.append(f"{schema}.{table}: expuesto a clientes")
        elif n_policies == 0:
            eval_str = "WARN: RLS enabled, sin policies (deny-all implícito)"
        elif has_restrictive:
            eval_str = "OK: policy USING(false)"
        else:
            eval_str = "REVIEW: policies sin USING(false) -- revisar manualmente"

        rls_str = "SI" if rls_enabled else "NO"
        print(f"| {schema} | {table} | {rls_str} | {n_policies} | {eval_str} |")

    print("\n## Resumen\n")
    if issues:
        print(f"ISSUES ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
        print("\nExit 1 -- hay tablas con problemas de RLS.")
        return 1

    print("Todas las tablas tienen RLS configurado. Exit 0.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
