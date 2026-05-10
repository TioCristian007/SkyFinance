"""
scripts/rekey_bank_accounts.py — Re-cifrado de credenciales con nueva clave.

Uso (dry-run, NO escribe en DB):
    python scripts/rekey_bank_accounts.py

Uso (aplicar cambios reales):
    python scripts/rekey_bank_accounts.py --apply

Requiere (en .env o variables de entorno):
    BANK_ENCRYPTION_KEY    = clave actual (ciphertexts sin prefijo en DB)
    BANK_ENCRYPTION_KEY_V2 = clave nueva (ciphertexts re-cifrados tendrán prefijo 'v2:')
    DATABASE_URL           = postgresql://... (Supabase)

Proceso:
    1. Lee todos los bank_accounts donde encrypted_rut NOT LIKE 'v2:%'.
    2. Para cada registro: decrypt con BANK_ENCRYPTION_KEY (v1).
    3. Re-cifra con BANK_ENCRYPTION_KEY_V2, agrega prefijo 'v2:'.
    4. Si --apply: UPDATE bank_accounts SET encrypted_rut=..., encrypted_pass=...
    5. Imprime resumen: N procesados, M ya en v2 (skipped), K errores.

Ver docs/RUNBOOK_KEY_ROTATION.md para el procedimiento completo.
"""
from __future__ import annotations

import asyncio
import os
import sys

# ── Setup de env antes de importar sky ────────────────────────────────────────
for var in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY",
            "ANTHROPIC_API_KEY", "BANK_ENCRYPTION_KEY"):
    if not os.environ.get(var):
        print(f"ERROR: {var} no está configurado", file=sys.stderr)
        sys.exit(1)

from sqlalchemy import text  # noqa: E402

from sky.core.config import settings  # noqa: E402
from sky.core.db import get_engine  # noqa: E402
from sky.core.encryption import decrypt, encrypt  # noqa: E402


async def run(apply: bool) -> None:
    v2_key = settings.bank_encryption_key_v2
    if not v2_key:
        print("ERROR: BANK_ENCRYPTION_KEY_V2 no configurado. Aborting.", file=sys.stderr)
        sys.exit(1)

    engine = get_engine()
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n=== rekey_bank_accounts.py [{mode}] ===\n")

    processed = 0
    skipped_v2 = 0
    errors = 0

    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id, encrypted_rut, encrypted_pass
                  FROM public.bank_accounts
                 WHERE status != 'disconnected'
                 ORDER BY created_at ASC
            """),
        )
        rows = rs.fetchall()

    print(f"Total filas a procesar: {len(rows)}")

    updates = []
    for row in rows:
        account_id = str(row[0])
        enc_rut = str(row[1])
        enc_pass = str(row[2])

        if enc_rut.startswith("v2:"):
            skipped_v2 += 1
            continue

        try:
            rut = decrypt(enc_rut, settings.bank_encryption_key)
            password = decrypt(enc_pass, settings.bank_encryption_key)

            new_enc_rut = "v2:" + encrypt(rut, v2_key)
            new_enc_pass = "v2:" + encrypt(password, v2_key)

            updates.append((account_id, new_enc_rut, new_enc_pass))
            processed += 1

        except Exception as exc:
            print(f"  ERROR account {account_id}: {exc}", file=sys.stderr)
            errors += 1
        finally:
            rut = ""  # type: ignore[assignment]
            password = ""  # type: ignore[assignment]

    print("\nResultados:")
    print(f"  A re-cifrar: {processed}")
    print(f"  Ya en v2 (skip): {skipped_v2}")
    print(f"  Errores: {errors}")

    if not apply:
        print("\n[DRY-RUN] No se escribió nada. Ejecutar con --apply para aplicar.")
        return

    if errors > 0:
        print(f"\nABORTED: hay {errors} error(es). Resolver antes de aplicar.", file=sys.stderr)
        sys.exit(1)

    print(f"\nAplicando {len(updates)} UPDATE(s)...")
    async with engine.begin() as conn:
        for account_id, new_enc_rut, new_enc_pass in updates:
            await conn.execute(
                text("""
                    UPDATE public.bank_accounts
                       SET encrypted_rut = :enc_rut,
                           encrypted_pass = :enc_pass,
                           updated_at = NOW()
                     WHERE id = :id
                """),
                {"id": account_id, "enc_rut": new_enc_rut, "enc_pass": new_enc_pass},
            )
    print(f"OK — {len(updates)} cuenta(s) re-cifradas con v2.")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    asyncio.run(run(apply=apply))
