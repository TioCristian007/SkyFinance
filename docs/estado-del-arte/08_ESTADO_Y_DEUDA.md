# 08 — Estado Real y Deuda Viva

[← Volver al índice](../ESTADO_DEL_ARTE.md)

> La sección más importante para operar honestamente. Doctrina §22: "la deuda se documenta, no se oculta".
> Referencia de deuda formal: `backend-python/docs/REMEDIATION_P0_P3.md`.

**Última actualización**: 2026-05-23

---

## ✅ Lo que funciona (verificado)

- **Producción viva**: `app.skyfinanzas.com` + `api.skyfinanzas.com` responden 200.
- **Migración Python completa**: 13 fases cerradas, cutover hecho, Node archivado.
- **Categorización**: 3 capas funcionando. ~1.283 transacciones, 0 en `pending`, ~1.231 `done`, ~52 `failed` (fallback "other").
- **Display ingreso/gasto**: por signo del monto — ingresos en verde, gastos en rojo.
- **Cifrado, RLS, audit (parcial), data export, rate limit, idempotencia**: implementados.
- **Scraper BChile**: validado funcionando **desde IP residencial** — login + 2FA + 175 movimientos + balance, signos correctos.
- **Cola ARQ**: corregida (ver abajo).

## ❌ Lo que NO funciona / bloqueadores

### B-1 · Scraping bloqueado desde datacenter (anti-bot) — **crítico arquitectónico**
BChile está detrás de **Imperva Incapsula**. El scraper headless desde la **IP de datacenter de Railway** es detectado como bot y recibe una página-desafío sin formulario de login → falla con "No se encontró el campo de RUT". Desde IP residencial (laptop, browser visible) funciona. 
**Implicación**: el scraping en producción es frágil. Para el demo, el camino confiable es local-first (laptop). Fix real: evasión anti-bot (stealth, proxy residencial) — no trivial. **Refuerza la tesis SFA.**

### B-2 · Scraper BCI roto — dominio cambiado
`portalpersonas.bci.cl` ya no resuelve (NXDOMAIN desde toda red probada; antes funcionaba). BCI cambió el dominio de su portal. Requiere rework: nuevo dominio + probablemente nuevos selectores y endpoints de API interna. BCI está en `pending`. Sprint propio pendiente.

### B-3 · Bug del audit log — no audita
El INSERT en `audit_log` mezcla `:detail::jsonb` (named) con `$1..$7` (posicional) → `PostgresSyntaxError` en cada sync. No tumba el sync (try/except) pero **no se escribe ningún registro de auditoría**. Fix: corregir el binding del parámetro en `sky/core/audit.py`.

### B-4 · Balance visible tras desconectar cuenta
Reportado: al desconectar una cuenta, el saldo seguía visible. El endpoint hace soft-disconnect (`status='disconnected'`) y `/accounts` filtra por status, así que probablemente es caché de estado en el frontend o el total no se recalcula. Requiere reproducción + diagnóstico.

### B-5 · Lentitud general
La app se siente lenta. Sin profiling aún. Sospechas: cold-start de Railway, queries de `/summary`/`/transactions`, re-renders del god-component `Sky.jsx`, polling de `BankConnect` cada 5s. **Medir antes de optimizar.**

## ✅ Corregido recientemente (mayo 2026)

| Fix | Detalle |
|---|---|
| **Cola ARQ** | `worker/main.py` ahora crea el pool con `default_queue_name="sky:default"`. Antes, `categorize_pending_job` caía en `arq:queue` (fantasma) y nunca corría → "Procesando..." eterno + todo rojo. Causa raíz de dos síntomas. |
| **Income display** | `Sky.jsx` usa `tx.amount > 0` (3 lugares) en vez de `category === "income"`. Ingresos sin glosa estándar ya no se ven como gasto. |
| **BankConnect** | `Promise.allSettled` — la lista de bancos no se rompe si `/accounts` falla. |
| **VITE_API_URL** | Reapuntado de `api-v2` (canary muerto) a `api.skyfinanzas.com`. |
| **Listado bancos** | `SUPPORTED_BANKS` solo expone BChile + BCI. |
| **SyntaxWarning `\S`** | Docstrings de scripts como raw strings. |

## Deuda de infraestructura

- **`appealing-benevolence`** (Node legacy) sigue online en Railway — decomisionar.
- **`api-v2.skyfinanzas.com`** — custom domain leftover del canary, devuelve 502. Limpiar.
- **Warm standby** en Fly.io recomendado (DR Railway).

## Inventario de deuda P0-P3 (de `REMEDIATION_P0_P3.md`)

| ID | Item | Estado |
|---|---|---|
| P0-1 | JWT auth verificado | ✅ Cerrado por cutover Python |
| P0-2 | Consent ARIA | ✅ Resuelto |
| P0-3 | Refresh post-sync | ✅ Resuelto |
| P1-1 | `Sky.jsx` god-component (1.600 LOC) | Abierto — refactor frontend |
| P1-2 | CORS permisivo | ✅ Cerrado (fail-fast en prod) |
| P2-1..4 | Tests/CI/rate limit/monitoring | Mayormente cerrados (Fase 10-11) |
| P2-6 | Rotación `BANK_ENCRYPTION_KEY` | Procedimiento manual documentado |
| BUG-1..4 | external_id / upsert / lock / sync secuencial | ✅ Cerrados en Python |

## Prioridades sugeridas (orden)

1. **Prep del pitch BCI** (objetivo de negocio inmediato — ver `Documentacion_Externa_Reuniones_Bancos/`).
2. **B-3** audit log (fix trivial, restaura auditoría).
3. **B-4** balance post-disconnect (se vería mal en demo).
4. **B-2** rework scraper BCI (sprint propio).
5. **B-1** resiliencia anti-bot datacenter (arquitectónico, mediano plazo).
6. **B-5** performance (profiling primero).
7. Decomisionar Node legacy + limpiar `api-v2`.
