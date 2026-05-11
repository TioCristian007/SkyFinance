# Security Policy — Sky Finance Backend Python

> Para reportar vulnerabilidades: fintyinc@gmail.com (no usar issues públicos).

---

## 1. Cifrado de credenciales bancarias

- **Algoritmo**: AES-256-GCM con IV único por cifrado (128 bits).
- **Clave**: `BANK_ENCRYPTION_KEY` (hex 64 chars = 32 bytes). Solo en backend.
- **Derivación**: SHA-256 del raw key (compatibilidad binaria con Node.js).
- **Formato en DB**: `iv:authTag:ciphertext` (base64, compatible con Node.js) o `v2:...` post-rotación.
- **Segunda capa**: Supabase cifra el disco en reposo (AES-256). Ciphertexts inútiles sin la clave.
- **Rotación**: ver `docs/RUNBOOK_KEY_ROTATION.md`.

## 2. TLS / HSTS

- TLS terminado en Railway (Let's Encrypt).
- `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` en toda response.
- Sin HTTP plain en producción.

## 3. Autenticación y autorización

- JWT de Supabase verificado criptográficamente en `JWTContextMiddleware` (middleware layer).
- RLS habilitado en todas las tablas `public.*`. Schema `aria.*` solo accesible con service_role.
- `SUPABASE_SERVICE_KEY` nunca expuesto al frontend ni logeado.

## 4. Audit log

- Tabla `public.audit_log` inmutable (solo INSERT desde código).
- Eventos críticos: `sync.start/success/error`, `account.connected/disconnected`.
- Sin PII en `metadata`. RLS: usuarios leen solo sus propios eventos.
- Retención: 90 días (TODO trigger Fase 12).

## 5. Acceso a credenciales en runtime

- Credenciales bancarias descifradas solo en memoria del proceso worker.
- `del rut, password, creds` inmediatamente tras el sync.
- Nunca logeadas. `sentry_utils.before_send` elimina PII de eventos Sentry.

## 6. Rate limiting

- slowapi Redis-backed por `user_id` verificado (no IP, resistente a spoofing).
- Default 60 req/min, configurable via `API_RATE_LIMIT_PER_MINUTE`.
- Seguro para multi-instancia (Redis compartido).

## 7. Métricas `/metrics`

- Protegidas por `x-prometheus-secret` header en producción.
- Fail-fast: `RuntimeError` si `PROMETHEUS_SECRET` vacío en `NODE_ENV=production`.

## 8. Sentry

- `before_send` filtra PII (tokens `sk-ant-*`, RUTs chilenos, claves en keys sensibles).
- Fail-fast: `RuntimeError` si `SENTRY_DSN` vacío en producción.

## 9. Dependencias de terceros

| Vendor | Certifications | Risk |
|--------|---------------|------|
| Supabase | SOC2 Type II | DB en US-East-1 |
| Railway | SOC2 | Infra en US |
| Anthropic | Política privacidad comercial | API calls, no data persistence |

## 10. Data retention

- **audit_log**: retención configurable via `AUDIT_LOG_RETENTION_DAYS` (default 90 días).
  Purge ejecutado por el worker ARQ diariamente a las 03:00 UTC (`audit_purge_job`).
  Función SQL: `SELECT public.purge_audit_log_old(:days)` (batchea en grupos de 10 000).
  Si un banco contractualmente exige retención mayor, ajustar `AUDIT_LOG_RETENTION_DAYS` sin redeploy.
- **data_export_requests**: signed URL en `download_url` expira en 7 días (alineado con `expires_at`).
  Después de 7 días, el usuario debe solicitar un nuevo export.

## 11. RLS verification procedure

Correr antes de cada deploy de migración SQL:

```bash
cd backend-python
python scripts/audit_rls_policies.py
```

Expected output: todas las tablas con `RLS: SI` y evaluación `OK` o `WARN`.
Exit code 1 = hay tablas sin RLS o con policies que exponen `aria.*` a clientes → **bloquear deploy**.

El script es read-only (solo SELECT). Nunca modifica policies.

## 12. Customer data export (Ley 19.628 art 11)

Flujo completo para que un usuario solicite sus datos:

1. `POST /api/account/export-request` — crea registro `status='pending'`, encola worker job.
2. Worker genera ZIP con: `transactions`, `goals`, `challenge_states`, `earned_badges`, `audit_log` propio.
3. ZIP sube al bucket privado `"data-exports"` en Supabase Storage.
4. `UPDATE data_export_requests SET status='completed', download_url=<signed URL 7d>`.
5. Usuario pollea `GET /api/account/export-request/{id}` hasta `status='completed'`.

**Datos explícitamente excluidos**: `bank_accounts` (contiene `encrypted_rut`/`encrypted_pass`).
**Formato**: JSON o CSV (`?format=csv`).
**Error**: si el job falla, `status='failed'`, `delivered_at=NULL`, error sanitizado (solo tipo de excepción).
**Rate limit**: 5 req/min en POST (anti-abuse).
**Pre-requisito de deploy**: bucket `"data-exports"` creado manualmente en Supabase Dashboard (privado).

---

*Última revisión: 2026-05-11. Actualizar tras cada cambio de arquitectura de seguridad.*
