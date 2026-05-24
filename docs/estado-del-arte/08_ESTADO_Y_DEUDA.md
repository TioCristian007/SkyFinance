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

### B-3 · Auditoría — código corregido, pendiente verificación en runtime
El bug original (mezcla `:detail::jsonb` named con `$1..$7` posicional) fue corregido en el commit `adff285` (2026-05-10). El INSERT en `sky/core/audit.py` usa parámetros nombrados consistentes (`:event_type`, `:user_hash`, etc.) — confirmado leyendo el código y con grep: **no existen bindings `$1..$7` en ningún archivo de `src/`**.

Lo que queda pendiente es verificar en runtime con Postgres real:
- Confirmar que el driver asyncpg efectivamente escribe filas con `statement_cache_size=0` (configuración de asyncpg usada en el engine).
- Confirmar que `resource_id` (columna `uuid` en Postgres) acepta el `str` Python que le pasa el código (asyncpg debería hacer el cast, pero no está verificado con filas reales).

**Estado**: código corregido (no es bloqueador de código); **verificación de runtime pendiente** — correr `log_event(...)` contra Postgres de staging y confirmar fila insertada.

### B-4 · Balance visible tras desconectar cuenta
`handleDisconnect` en `BankConnect.jsx` llamaba `loadAccounts()` (refresca estado interno del componente) pero no llamaba `onSyncComplete?.()`, que es el callback que refresca `bankBalances` en `Sky.jsx`. **Corregido** (2026-05-23): se agregó `onSyncComplete?.()` tras `loadAccounts()`. Verificación visual de QA manual pendiente.

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
| **PII en logs scraper** | (2026-05-23) Eliminados dos `logger.info` de debug que registraban RUT, nombre y nº de cuenta a nivel INFO en `bchile_scraper.py`. Doctrina §16. |
| **Transparencia de errores de sync** | (2026-05-23) `AllSourcesFailedError` conserva la causa; mensaje al usuario por tipo de error; no se reintentan fallos terminales (ARQ). |
| **propose_challenge roto** | (2026-05-23) La tool generaba desafíos freeform sin `challenge_id`; el frontend esperaba `{type, input:{challenge_id, reasoning}}` y crasheaba. Restaurada la paridad con el catálogo `MOCK_CHALLENGES`. |
| **Tests de chat rotos** | (2026-05-23) 4 tests de `test_api_chat.py` asertaban el contrato viejo (`type/text/route`) ya reemplazado por `ChatUnifiedResponse`. Actualizados → recuperada la red de cobertura de Mr. Money. |
| **ruff verde** | (2026-05-23) Limpiadas las 17 violaciones preexistentes (imports muertos, EOF, líneas largas). El gate `ruff check exit 0` ahora se cumple. |

## 🧹 Rastrilleo de deuda menor (2026-05-23)

Hallazgos del barrido de calidad. No bloquean, pero se documentan para no acumularse (doctrina §22):

| ID | Item | Nota |
|---|---|---|
| ✅ **R-1** | ~~Lista de bancos duplicada en 4+ lugares~~ | **Cerrado 2026-05-23.** `SUPPORTED_BANKS` (incl. `account_type`) es la fuente única. `_DEFAULT_ACCOUNT_TYPE` eliminado de `banking.py` y `summary.py`. `DEFAULT_RULES` alineado a bchile+bci. |
| **R-2** | Naming engañoso de BCI | `BCIDirectSource` (archivo `bci_direct.py`) tiene `source_identifier == "scraper.bci"` y BCI es un scraper (no API directa). Renombrar a `BCIScraperSource`/`bci_scraper.py` cuando se haga el rework B-2. |
| ✅ **R-3** | ~~`FalabellaScraperSource` muerto~~ | **Cerrado 2026-05-23.** Dejó de registrarse en `build_all_sources`; el archivo se conserva como skeleton de referencia. |
| ✅ **R-4** | ~~`RuntimeWarning: coroutine never awaited`~~ | **Cerrado 2026-05-24.** Fixture autouse en `test_sync_job` deshabilita la tarea fire-and-forget de ARIA (no la verifican). Suite sin warnings (`pytest -W error::RuntimeWarning` verde). |
| **R-5** | Webhooks sin verificación de firma | `webhooks.py`: TODO de validar HMAC-SHA256 nunca implementado. Confirmar que la ruta no haga nada sensible mientras Fintoc no esté cableado. Cerrar cuando se cablee Fintoc (agregar HMAC primero). |
| ✅ **R-6** | ~~Sin gate automático~~ | **Cerrado 2026-05-23.** `.githooks/pre-push` corre ruff+mypy+pytest antes de cada push. Activar con `git config core.hooksPath .githooks`. Script manual: `backend-python/scripts/check_gates.ps1`. |
| ✅ **R-7** | ~~BOM en 3 mensajes de commit~~ | **Cerrado 2026-05-24.** Removido el BOM UTF-8 de los 3 subjects vía `git filter-branch --msg-filter` (commits aún sin pushear; contenido idéntico verificado con diff vacío). |

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
2. **B-3** verificación de runtime (log_event contra Postgres staging).
3. **B-4** ~~balance post-disconnect~~ — código corregido; pendiente QA visual.
4. **B-2** rework scraper BCI (sprint propio).
5. **B-1** resiliencia anti-bot datacenter (arquitectónico, mediano plazo).
6. **B-5** performance (profiling primero).
7. Decomisionar Node legacy + limpiar `api-v2`.
