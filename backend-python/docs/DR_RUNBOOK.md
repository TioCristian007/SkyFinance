# Disaster Recovery Runbook — Sky Finance

> Tres escenarios críticos. Estimaciones de RTO/RPO son aproximadas.
> Contacto de emergencia: fintyinc@gmail.com

---

## Escenario 1: Supabase down

**RTO estimado**: 15-30 min (depende de Supabase SLA).

**Síntomas**: API retorna 500 en endpoints que tocan DB. `/api/health/deep` muestra `"db": "down"`.

**Acciones**:
1. Verificar status en status.supabase.com.
2. Si outage confirmado: activar maintenance mode en frontend (ENV `MAINTENANCE_MODE=true`).
3. Worker sigue corriendo pero los jobs fallarán con error (ARQ reintentos).
4. Esperar restauración de Supabase.
5. Tras restauración: verificar `/api/health/deep` → `"db": "ok"`.
6. Desactivar maintenance mode.

**PITR**: Supabase Pro ofrece Point-in-Time Recovery de 7 días. En caso de corrupción:
Dashboard Supabase > Database > Backups > Restore.

---

## Escenario 2: Railway down (infra total)

**RTO estimado**: 30-60 min (migración a backup).

**Acciones**:
1. Verificar status.railway.app.
2. Si downtime extendido (>30 min): deploy de emergencia en Render o Fly.io.
   ```bash
   # Render: fly launch --image python:3.12-slim (adaptar dockerfile)
   # Las ENV vars están documentadas en FASE11_DEPLOY_CHECKLIST.md
   ```
3. Actualizar DNS (CNAME `api.skyfinanzas.com`) al nuevo host. TTL: 5 min (pre-configurar).
4. Verificar `/api/health` en nuevo host antes de actualizar DNS.

---

## Escenario 3: Brecha de credenciales (BANK_ENCRYPTION_KEY comprometida)

**RTO estimado**: 2-4 horas (rotación + comunicación).

**Acciones inmediatas** (primeros 15 min):
1. Revocar acceso al servidor comprometido (Railway dashboard > Service > Delete / Suspend).
2. Revocar `BANK_ENCRYPTION_KEY` y `SUPABASE_SERVICE_KEY` en Railway ENV.
3. Notificar a los cofundadores.

**Rotación** (siguientes 2-3 horas):
1. Seguir `docs/RUNBOOK_KEY_ROTATION.md` completo.
2. Deploy con nueva clave.
3. Verificar que ciphertexts en DB tienen prefijo `v2:`.

**Comunicación** (mismo día):
1. Notificar usuarios afectados (email desde `fintyinc@gmail.com`).
2. Documentar incidente internamente.
3. Si aplica: notificación regulatoria (CMF/SBIF si hay clientes en producción).

---

*Actualizar este runbook cuando cambie la arquitectura de infra.*
