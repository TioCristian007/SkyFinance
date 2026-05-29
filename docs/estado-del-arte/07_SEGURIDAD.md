# 07 — Seguridad

[← Volver al índice](../ESTADO_DEL_ARTE.md)

> Referencia detallada: `backend-python/docs/SECURITY.md`, `docs/SECURITY_INFRASTRUCTURE.md`, `DR_RUNBOOK.md`, `RUNBOOK_KEY_ROTATION.md`.

---

## Modelo de amenaza — qué protege Sky

| Activo | Sensibilidad | Dónde vive |
|---|---|---|
| Credenciales bancarias (RUT + clave) | **Crítica** | `bank_accounts.encrypted_rut/pass` (cifradas) |
| Movimientos financieros | Alta | `transactions` (Postgres, RLS) |
| Saldos | Alta | `bank_accounts.last_balance` |
| Perfil cualitativo (dimensiones psicológicas) | Alta (privado) | `public.user_financial_profile` (RLS service_only) |
| Patrones de gasto | Media (anonimizada) | schema `aria.*` |
| Identidad (UUID) | Media | `auth.users` / `profiles.id` |

`profiles` **no** guarda nombre, email ni RUT — solo UUID y preferencias. La PII la administra Supabase Auth.

## 1. Cifrado de credenciales

- **AES-256-GCM** con IV único (128 bits) por cifrado.
- Clave `BANK_ENCRYPTION_KEY` (hex 64 = 32 bytes), derivada por SHA-256 (compat binaria Node↔Python).
- Formato en DB: `iv:authTag:ciphertext` base64, o `v2:...` post-rotación.
- Segunda capa: Supabase cifra disco en reposo.
- Credenciales descifradas **solo en memoria del worker**; `del rut, password, creds` inmediato.

## 2. Transporte

- TLS 1.2+ end-to-end (Railway / Let's Encrypt). Sin HTTP plain en prod.
- HSTS: `max-age=63072000; includeSubDomains; preload`.

## 3. Autenticación y autorización

- JWT de Supabase verificado criptográficamente en `JWTContextMiddleware` (HS256, audience `authenticated`, firma + expiración).
- **RLS habilitado en todas las tablas `public.*`**. Schema `aria.*` solo `service_role`.
- `SUPABASE_SERVICE_KEY` nunca al frontend ni a logs.
- Endpoints internos (`/api/internal/*`) protegidos por `x-cron-secret`; sin `CRON_SECRET` → 503 fail-safe.

## 4. ARIA — anonimización en 5 pasos

Solo activo con `profiles.aria_consent = true`:

1. **Extracción** — evento real → señal estructurada.
2. **Categorización** — valor exacto → rango (monto → bucket, fecha → trimestre).
3. **Eliminación de identidad** — UUID descartado antes de escribir.
4. **Randomización intra-bucket** — valor guardado = random dentro del rango.
5. **Ruptura de correlaciones** — jitter temporal ±36h, batch_id propio.

Vistas analíticas con **k-anonymity ≥ 10** (mínimo 10 registros por agregado). Tablas: `aria.spending_patterns`, `goal_signals`, `behavioral_signals`, `session_insights`.

## 5. Audit log

- `public.audit_log` inmutable (solo INSERT). Eventos: `sync.start/success/error`, `account.connected/disconnected`, export, delete.
- `user_hash = SHA-256(user_id + AUDIT_LOG_SALT)` — correlación sin PII. Sin PII en metadata.
- Retención `AUDIT_LOG_RETENTION_DAYS` (90), purgado por `audit_purge_job` diario 03:00 UTC.
- ✅ Bug de sintaxis corregido (2026-05-25): `:detail::jsonb` → `CAST(:detail AS jsonb)`. Ver [08](08_ESTADO_Y_DEUDA.md).

## 6. Rate limiting

- slowapi Redis-backed por `user_id` verificado (no IP). Default 60/min. Multi-instancia seguro.

## 7. Observabilidad protegida

- `/metrics` requiere `x-prometheus-secret` en prod (fail-fast si vacío).
- Sentry `before_send` filtra PII (tokens `sk-ant-*`, RUTs, claves). Fail-fast si `SENTRY_DSN` vacío en prod.

## 8. Privacidad y cumplimiento

- **Ley 19.628** (datos personales, Chile).
- **Data export (art. 11)**: `POST /api/account/export-request` → worker genera ZIP (transactions, goals, challenges, badges, audit propio, perfil_cualitativo) → signed URL 7d. Excluye `bank_accounts` (credenciales cifradas). Rate limit 5/min.
- Diseño compatible con **CMF SFA** (consent tokens, scopes).

## 9. Idempotencia

- Header `Idempotency-Key` (UUID v4) en POST con side-effects (`/banking/sync`, `/sync-all`, `/accounts`). Replay devuelve respuesta cacheada (TTL 24h). Ver `API_CONTRACT.md`.

## 10. Dependencias de terceros

| Vendor | Certificación | Riesgo |
|---|---|---|
| Supabase | SOC2 Type II | DB en US-East-1 |
| Railway | SOC2 | Infra US |
| Anthropic | Privacidad comercial | API calls, sin persistencia |

## 11. Runbooks de seguridad

- **Rotación de `BANK_ENCRYPTION_KEY`** (`RUNBOOK_KEY_ROTATION.md`): dual-decrypt → `rekey_bank_accounts.py --apply` → verificar prefijo `v2:` → retirar v1. Sin downtime, rollback seguro.
- **DR** (`DR_RUNBOOK.md`): 3 escenarios (Supabase down, Railway down, brecha de clave).
- **RLS verification**: `scripts/audit_rls_policies.py` antes de cada migración (exit 1 bloquea deploy).

## 12. Perfil cualitativo privado (ARIA-quali v1, 2026-05-29)

Nueva capa de datos introducida por ARIA-quali v1. Dos tablas con regímenes de acceso distintos:

### `public.user_financial_profile` — perfil privado por usuario

- Contiene dimensiones psicológicas y financieras aprendidas por Mr. Money (savings_mindset, risk_tolerance, etc.).
- **RLS `ufp_service_only`**: política única `FOR ALL USING (false) WITH CHECK (false)`. **Ningún JWT puede leer ni escribir.** Solo `service_role` (el backend).
- El perfil es **invisible para el usuario** — no hay endpoint que lo exponga. Solo se devuelve indirectamente en el ZIP de data export (`perfil_cualitativo`).
- Mr. Money lo lee vía `domain/financial_profile.get_profile()` e inyecta dimensiones con `confidence >= 0.5` en su contexto de sistema.
- Actualización solo via tool `update_profile_dimension` que valida contra un allow-list explícito (`_EDITABLE_DIMENSIONS`). Columnas como `emotional_volatility`, `last_emotion` y `user_id` **no** están en el allow-list.
- `apply_emotion_inference` (tool `infer_emotional_state`, premium-gated) actualiza `last_emotion`, `stress_current`, y calcula `emotional_volatility` como desviación estándar móvil de las últimas 20 intensidades (`emotion_history jsonb`). El tool solo está disponible cuando `_is_premium_user() == True` (actualmente siempre False hasta que se agregue `profiles.tier`).

### `aria.user_profile_snapshots` — snapshots k-anon

- Sin `user_id`. Sin UUID. Solo datos agregados y bucketizados.
- Schema `aria.*` — acceso exclusivo `service_role`, igual que `spending_patterns` y demás tablas `aria.*`.
- Job semanal `snapshot_profiles_job` (lunes 06:00 UTC): agrupa perfiles por demografía `(age_range, region, income_range, occupation)`. Buckets con menos de `profile_snapshot_k_anon_min` (default 5) se descartan silenciosamente. Jitter temporal ±`profile_snapshot_jitter_days` (default 3) para romper correlación con el momento real.
- El umbral de k-anonimidad configurable (ver deuda Q-2 en [08](08_ESTADO_Y_DEUDA.md)).

## Deuda de seguridad reconocida

- P0-1 (JWT en Node) — cerrado por el cutover a Python (verificación criptográfica nativa).
- Gestión de secretos en Railway ENV (no Secrets Manager) — aceptable para MVP, escala documentada.
- Rotación de `BANK_ENCRYPTION_KEY` sin automatizar (procedimiento manual documentado).
