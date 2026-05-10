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

---

*Última revisión: 2026-05-10. Actualizar tras cada cambio de arquitectura de seguridad.*
