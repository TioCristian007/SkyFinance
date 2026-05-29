# 08 — Estado Real y Deuda Viva

[← Volver al índice](../ESTADO_DEL_ARTE.md)

> La sección más importante para operar honestamente. Doctrina §22: "la deuda se documenta, no se oculta".
> Referencia de deuda formal: `backend-python/docs/REMEDIATION_P0_P3.md`.

**Última actualización**: 2026-05-29

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

**Causa raíz confirmada**: Incapsula detecta Playwright headless sin stealth (navigator.webdriver expuesto, User-Agent con "HeadlessChrome", fingerprint de Chromium bundled). Sirve challenge JS que bloquea el formulario → `_fill_rut` no encuentra el campo → `RecoverableIngestionError`.

**Palancas agregadas (2026-05-25)**:
- `browser_headless=True/False` (setting, no redeploy) — permite correr visible para diagnóstico local.
- Stealth básico en `browser_pool.py`: `--disable-blink-features=AutomationControlled`, User-Agent realista de Chrome/Windows, `navigator.webdriver=undefined` via init_script, intentar `channel="chrome"` (Chrome de sistema, mejor huella).
- `scraper_debug_capture=True` (setting) + `scraper_debug_dir` — guarda screenshot + HTML en el punto de fallo (sin PII) para diagnosticar qué sirve Incapsula.

**Implicación**: el scraping en producción sigue siendo frágil. Stealth básico puede ayudar pero no es garantía (Incapsula es sofisticado). Para el demo, el camino confiable es local-first (laptop). Fix real arquitectónico: proxy residencial o migración a SFA. **Refuerza la tesis SFA.**

### B-2 · Scraper BCI roto — dominio cambiado
`portalpersonas.bci.cl` ya no resuelve (NXDOMAIN desde toda red probada; antes funcionaba). BCI cambió el dominio de su portal. Requiere rework: nuevo dominio + probablemente nuevos selectores y endpoints de API interna. BCI está en `pending`. Sprint propio pendiente.

### ✅ B-3 · Auditoría — bug de runtime corregido (2026-05-25)

**Bug encontrado**: el INSERT en `sky/core/audit.py` usaba `:detail::jsonb`. Con SQLAlchemy `text()` + asyncpg, el cast `::jsonb` rompe el parseo del bind param nombrado `:detail` → asyncpg lanza `PostgresSyntaxError` en runtime. **Ningún evento de auditoría se escribía en Postgres real** desde el inicio del sistema.

**Fix aplicado**: `CAST(:detail AS jsonb)` en lugar de `:detail::jsonb`. Un line change quirúrgico. Test de regresión agregado en `tests/unit/test_audit.py` (`test_sql_uses_cast_not_postgres_cast_syntax`) que verifica que el SQL compilado no contiene `::jsonb`.

**Estado**: ✅ corregido y cubierto por test. Verificación de runtime con Postgres de staging sigue siendo recomendable para confirmar que `resource_id uuid` acepta `str` Python vía asyncpg, pero el bug de sintaxis está resuelto.

### B-4 · Balance visible tras desconectar cuenta
`handleDisconnect` en `BankConnect.jsx` llamaba `loadAccounts()` (refresca estado interno del componente) pero no llamaba `onSyncComplete?.()`, que es el callback que refresca `bankBalances` en `Sky.jsx`. **Corregido** (2026-05-23): se agregó `onSyncComplete?.()` tras `loadAccounts()`. Verificación visual de QA manual pendiente.

### B-5 · Lentitud general
La app se siente lenta. Sin profiling aún. Sospechas: cold-start de Railway, queries de `/summary`/`/transactions`, re-renders del god-component `Sky.jsx`, polling de `BankConnect` cada 5s. **Medir antes de optimizar.**

## ✅ Corregido recientemente (mayo 2026)

| Fix | Detalle |
|---|---|
| **A1 — categoría real en sync bancario** | `banking_sync._track_aria_events` tenía hardcoded `"category": "other"`. Cambiado a `getattr(m, "category", None) or "other"` — future-proof cuando `CanonicalMovement` reciba el campo. |
| **A2 — track_goal_event cableado** | `goals.py`: `_fire_goal_aria` (fire-and-forget) nunca se disparaba. Ahora se dispara en `create_goal` (status=active), `update_goal` (active/completed según pct), `delete_goal` (abandoned). |
| **A3 / A3b — aria_consent endpoint + toggle frontend** | `ProfilePatch` expone `aria_consent: bool \| None`. Endpoint `PATCH /api/profile` persiste el valor en `profiles.aria_consent`. Frontend `Sky.jsx`: sección "Privacidad y datos" con toggle "Compartir patrones anónimos para mejorar Sky". |
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
| **audit INSERT roto en runtime (B-3)** | (2026-05-25) `:detail::jsonb` rompía asyncpg con named params → 0 filas escritas. Corregido con `CAST(:detail AS jsonb)`. Test de regresión agregado. |
| **Mr. Money: logging silencioso en errores Anthropic** | (2026-05-25) `except` usaba `logger.warning` sin traceback. Cambiado a `logger.error(exc_info=True)` con detección explícita de `AuthenticationError`/`APIStatusError`. |
| **Stealth anti-bot básico en browser_pool** | (2026-05-25) `--disable-blink-features=AutomationControlled`, User-Agent realista, `navigator.webdriver=undefined`. Palancas `browser_headless` + `scraper_debug_capture`. |
| **Validators fail-fast en Settings** | (2026-05-25) `field_validator` en pydantic v2 para secrets críticos: vacío/espacios → error al arrancar. `anthropic_api_key` valida además prefijo `sk-ant`. |
| **KPI Ingresos perdía positivos no-income/no-transfer** | (2026-05-28) `compute_summary` usaba whitelist `category IN ('income','transfer')` para income — positivos con `category='other'`, `'food'`, etc. caían en ninguna rama y se perdían del summary (~$50K invisibles: sidebar vs donut). Tercera aparición del patrón "filtro por categoría en vez de signo" (anteriores: toggle Tipo frontend, B-3 vocabulario audit). Fix: predicado por signo (`amount > 0 AND (category != 'transfer' OR count_transfers_as_income)`). Tests de regresión en `TestIncomeBySign` · `test_finance.py`. |

## 🆕 ARIA-quali v1 (2026-05-29)

Nueva capa de inteligencia cualitativa incorporada en producción. No es deuda — es feature nueva.

### Perfil cualitativo privado (`public.user_financial_profile`)
- Tabla con dimensiones psicológicas/financieras: `savings_mindset`, `risk_tolerance`, `financial_volatility`, `goal_orientation`, `stress_baseline/current`, `emotional_volatility`, `motivation_primary`, `recurring_blockers`, `protective_behaviors`, `emotion_history` (jsonb).
- **RLS `ufp_service_only`**: `USING (false) WITH CHECK (false)` — ningún JWT puede leer ni escribir. Solo `service_role`. El perfil es invisible al usuario.
- **Migración**: `migrations/011_user_financial_profile.sql` (aplicar manualmente).

### Mr. Money: contexto enriquecido + tools
- `_build_financial_context` inyecta sección "PERFIL APRENDIDO" para dimensiones con `confidence >= 0.5`.
- Tool `read_profile`: Mr. Money puede leer el perfil propio para enriquecer respuesta.
- Tool `update_profile_dimension`: actualiza una dimensión del allow-list (`_EDITABLE_DIMENSIONS`). El allow-list bloquea columnas como `user_id` o `emotional_volatility` (estas solo las calcula el sistema).
- Tool `infer_emotional_state` (**premium-gated**): llama a `apply_emotion_inference` que registra `last_emotion`, actualiza `stress_current`, y calcula `emotional_volatility` como desviación estándar móvil de las últimas 20 observaciones.

### Snapshot semanal k-anon (`aria.user_profile_snapshots`)
- Job ARQ `snapshot_profiles_job`: corre lunes 06:00 UTC. Agrupa perfiles por `(age_range, region, income_range, occupation)`. Buckets con menos de `profile_snapshot_k_anon_min` (default 5) se descartan. Los que superan el umbral se insertan como snapshots anónimos con jitter ±`profile_snapshot_jitter_days` días.
- Tabla `aria.user_profile_snapshots`: sin `user_id`, sin UUID. Solo datos agregados. `service_role` only.
- **Migración**: `migrations/012_aria_user_profile_snapshots.sql` (aplicar manualmente).

### Data export (Ley 19.628)
- `_collect_user_data` agrega dataset `perfil_cualitativo` al ZIP. El usuario puede descargar sus propias dimensiones aprendidas.

### Deuda nueva introducida por ARIA-quali v1

| ID | Item | Nota |
|---|---|---|
| **Q-1** | `profiles.tier` no existe | `_is_premium_user()` siempre retorna `False` → `infer_emotional_state` deshabilitado para todos. Retomar cuando se agregue la columna `tier` a `public.profiles`. |
| **Q-2** | `k_anon_min=5` es bajo para ARIA | Para privacidad ARIA robusta el umbral debería ser ≥10. Aceptable para lanzamiento con base de usuarios pequeña; subir a 10 cuando haya ≥100 usuarios activos. Configurable sin redeploy (`profile_snapshot_k_anon_min` en settings). |
| **Q-3** | Snapshot no tiene test de integración contra Postgres real | Los tests de `test_snapshot_profiles.py` mockean el insert a `aria.*`. El job funciona lógicamente pero el insert a Supabase no está verificado en staging. Confirmar en el primer run real. |
| **Q-4** | Perfil cualitativo sin ponderación temporal | `upsert_profile_dimension` (`financial_profile.py:96`) sobreescribe cada dimensión con la última inferencia de Claude. Sin EWMA para numéricas, sin histograma ponderado para categóricas, sin decay temporal. Único componente con memoria: `emotion_history` (jsonb capped 20) + `emotional_volatility` (rolling std). Consecuencia: el perfil puede saltar entre estados ante un mensaje impulsivo y los snapshots a `aria.*` quedan ruidosos. Sprint propio planeado con parámetros aprobados (suave: α=0.25 numéricas, threshold conf 0.8 categóricas, confianza acumulativa). **Hacer antes de cualquier demo del perfil cualitativo** — el primer cliente que vea el perfil "saltando" pierde confianza. |

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
2. **B-3** ✅ cerrado — correr `log_event(...)` contra Postgres staging para confirmar que `resource_id uuid` acepta `str` (asyncpg cast). Low-effort, 10 min.
3. **B-4** ~~balance post-disconnect~~ — código corregido; pendiente QA visual.
4. **B-2** rework scraper BCI (sprint propio).
5. **B-1** resiliencia anti-bot datacenter — stealth básico agregado; evaluar si es suficiente o se necesita proxy residencial.
6. **B-5** performance (profiling primero).
7. Decomisionar Node legacy + limpiar `api-v2`.
