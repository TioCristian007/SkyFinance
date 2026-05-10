# RUNBOOK: Rotación de BANK_ENCRYPTION_KEY

> Proceso para rotar la clave maestra AES-256-GCM sin downtime.
> Ejecutar fuera del horario pico. Estimación: 30 min.

---

## Cuándo ejecutar

- Sospecha de compromiso de clave
- Política de rotación periódica (recomendado: anual)
- Auditoría ISO27001 lo exige

## Paso 1: Generar nueva clave

```python
import secrets
print(secrets.token_hex(32))  # 64 chars hex = 32 bytes
```

Guardar en gestor de secretos (Railway ENV o AWS SM). No commitear nunca.

## Paso 2: Dry-run del script

```bash
# En backend-python/:
$env:BANK_ENCRYPTION_KEY    = "clave_actual"
$env:BANK_ENCRYPTION_KEY_V2 = "clave_nueva"
$env:DATABASE_URL            = "postgresql+asyncpg://..."
python scripts/rekey_bank_accounts.py
```

Revisar output: `A re-cifrar: N, Errores: 0`. Si hay errores, investigar antes de continuar.

## Paso 3: Deploy del código dual-decrypt

Antes de re-cifrar, el API debe poder descifrar tanto v1 (sin prefijo) como v2 (`v2:...`).
`encryption.strip_version_prefix()` ya maneja esto. Pero `decrypt()` usa `settings.bank_encryption_key`.
Durante la rotación, añadir lógica dual en el código que descifra credenciales en `banking_sync.py`:

```python
# temporal durante rotación — revertir en Paso 5
def decrypt_with_fallback(ciphertext: str, key_v1: str, key_v2: str) -> str:
    if ciphertext.startswith("v2:"):
        return decrypt(ciphertext, key_v2)
    return decrypt(ciphertext, key_v1)
```

Deploy de este cambio ANTES de ejecutar el re-cifrado.

## Paso 4: Aplicar re-cifrado

```bash
python scripts/rekey_bank_accounts.py --apply
```

Verificar en DB:
```sql
SELECT COUNT(*) FROM public.bank_accounts WHERE encrypted_rut NOT LIKE 'v2:%';
-- Debe ser 0
```

## Paso 5: Retirar clave v1

1. En Railway: renombrar `BANK_ENCRYPTION_KEY_V2` → `BANK_ENCRYPTION_KEY`
2. Eliminar `BANK_ENCRYPTION_KEY_V2`
3. Revertir lógica dual-decrypt del Paso 3
4. Redeploy

## Rollback

Si algo falla en Paso 4: el código sigue usando v1. Los ciphertexts sin prefijo
se descifran con la clave original. No hay pérdida de datos.

---

*Ver también: `docs/SECURITY.md` §Cifrado, `src/sky/core/encryption.py`*
