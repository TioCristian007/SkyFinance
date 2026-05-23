# POST-CUTOVER AUDIT — Sky Finance
**Fecha**: 2026-05-17  
**Auditor**: Claude Sonnet 4.6 (session sprint post-cutover)  
**Scope**: Monorepo sky_OFFICIAL — estado real tras cutover Python

---

## 1. Estado del repo

### Git log (20 commits recientes)
```
b85c3a4 debug: add traceback to bchile fetch error
be3d5ef fix: align ARQ queue name to sky:default
b313f92 fix: upsert on bank connect instead of INSERT (handles reconnect)
a3cef8d fix: send bank_id snake_case to Python backend
4f6be12 fix: update connectBank endpoint to /banking/accounts
e8823dc fix: filter banks by status field instead of available
73fba20 fix: remove duplicate /banks endpoint
7f26691 fix: add GET /api/banking/banks endpoint
e7e83f4 fix: replace setUserId with setAccessToken in Sky.jsx
c5dd702 chore: force bundle rebuild
503d469 chore: force frontend rebuild
4f629fe fix: move CORSMiddleware to outermost position (fix preflight 400)
b978465 feat: add setAccessToken call in handleSession (App.jsx)
51a9640 feat: migrate auth from x-user-id to Bearer token (closes P0-1)
31fbab2 fix(challenges): remove ChallengeOut import
087c28e fix(docker): use PYTHONPATH instead of pip install
dc2ba62 fix(docker): add CACHEBUST arg
6036f3c fix(auth): ES256 JWT verification via JWKS
f6b0182 fix(goals): map domain fields to real DB column names (title, saved_amount, deadline)
a418899 fix(summary): remove deleted_at filter
```

### Untracked files (sin commitear)
- `backend-python/body.json` — debug output (ver §6)
- `backend-python/docs/SPRINT_POST_CUTOVER_PROMPT.md` — prompt de este sprint

### Branches
- `main` (único branch activo)
- Repo up to date con `origin/main` según `git status`

### Estado de fases técnicas (verificado en MIGRATION_13_PHASES.md)
- Fases 0–12: **✅ Cerradas**
- Fase 13 (parity + cutover gradual): **🔄 En ejecución** — cutover forzado pre-fase-13, sin parity tests formales

### Discrepancia crítica de documentación
`backend-python/README.md` dice "Fases 0-5 cerradas. NO toca producción hasta Fase 13." — **DESACTUALIZADO**. La fuente de verdad es `MIGRATION_13_PHASES.md`.

---

## 2. Estado de Railway services

> **No tengo acceso Railway en tiempo real en esta sesión.** Lo siguiente se infiere del código, Dockerfiles, railway.json y logs de deploy documentados en MIGRATION_13_PHASES.md §11.

### Frontend — `SkyFinance`
- URL: `app.skyfinanzas.com`
- Dockerfile: no existe en el repo (probablemente build estático Vite)
- **ENV VAR CRÍTICA**: `VITE_API_URL` — valor actual en Railway **no verificado directamente**
  - `.env.example` frontend dice: `VITE_API_URL=https://sky-api-python-production.up.railway.app/api`
  - Podría estar apuntando al Python backend. Necesita confirmación.

### Backend Node — `appealing-benevolence-production`
- URL: `api.skyfinanzas.com`
- Estado: **en standby para rollback** (sigue deployado, no recibe tráfico si VITE_API_URL apunta a Python)
- Sin cambios post-cutover en este sprint

### Backend Python — `sky-api-python`
- URL pública: `api-v2.skyfinanzas.com` (custom domain) + `sky-api-python-production.up.railway.app`
- Dockerfile: `docker/api.Dockerfile` → `CMD uvicorn ... --port 8000`
- **ISSUE**: Puerto hardcodeado a 8000. Railway asigna `$PORT` dinámicamente (típicamente 8080). Si Railway routea al `$PORT` y el servicio escucha en 8000, el healthcheck falla.
  - Deploy verificado (2026-05-11) funcionó, pero el Dockerfile no usa `$PORT`. Posible que Railway esté configurado para usar puerto 8000 manualmente.
- ENV vars en Railway (según MIGRATION_13_PHASES.md Fase 11):
  - `DATABASE_URL`, `REDIS_URL` (internal), `BANK_ENCRYPTION_KEY`, `SUPABASE_*`, `ANTHROPIC_API_KEY`, `SENTRY_DSN`, `PROMETHEUS_SECRET`, `CORS_ORIGINS=https://app.skyfinanzas.com`
- Último deploy verificado: `GET /api/health` → 200, `GET /api/health/deep` → `{"status":"ok","db":"ok","redis":"ok","anthropic":"ok"}`

### Worker Python — `sky-worker-python`
- Dockerfile: `docker/worker.Dockerfile` (con Playwright + Chromium)
- Estado (per logs Fase 11): Active, browser pool 4, 5 functions + cron registrados
- `routing_rules_loaded count=8` (leyendo desde DB Supabase, no fallback)
- ARQ queue name: `sky:default` (fijado en commit `be3d5ef`)

### Redis — Railway plugin
- URL interna: `redis.railway.internal:6379`
- Usado por: ARQ queue, slowapi, idempotency, circuit breaker, rate limiter

### sky-cron-sync (legacy)
- Servicio Railway que llamaba al cron de Node
- Estado: **DEBE DECOMMISSIONARSE** — ya no es necesario con ARQ cron nativo
- Riesgo: si sigue activo, puede disparar syncs conflictivos

---

## 3. Estado de Supabase

### Migraciones SQL verificadas (según MIGRATION_13_PHASES.md)
| Migración | Estado | Verificación |
|---|---|---|
| `000_immediate_fixes.sql` | ✅ Aplicada (pre-Fase 5) | — |
| `001_routing_rules.sql` | ✅ Aplicada | `SELECT count(*) FROM ingestion_routing_rules` → 8 |
| `002_indexes_and_constraints.sql` | ⚠️ Gate manual pendiente en HANDOVER_FASE_9.md §3.1 | `uniq_tx_external` + índices |
| `003_auto_sync_enabled.sql` | ✅ Aplicada (requerida por worker ARQ cron) | `profiles.auto_sync_enabled` column |
| `004_audit_log.sql` | ✅ Aplicada (per Fase 11 closure) | SHA-256 user_hash + JSONB metadata |
| `005_audit_log_purge.sql` | ⚠️ Gate manual pendiente (Fase 12) | `purge_audit_log_old()` function |

### Bucket Storage
- `data-exports`: debe existir como bucket privado (per Fase 12). Estado real **no verificado** en esta sesión.

### Scripts RLS
- `scripts/audit_rls_policies.py` disponible pero **no ejecutado** en esta sesión (requiere DB real).

---

## 4. Estado del frontend

### VITE_API_URL y llamadas al backend

`frontend/src/services/api.js` usa `VITE_API_URL` (build-time env var):
- Si `VITE_API_URL=https://sky-api-python-production.up.railway.app/api` → llama Python
- Si no está seteada → cae a `/api` relativo → 404 en prod (frontend sirve estático)

**Todos los endpoints que llama el frontend** (via `api.js`):

| Función | Método | Path | Estado Python |
|---|---|---|---|
| `getSummary()` | GET | `/summary` | ⚠️ SHAPE MISMATCH (ver §5) |
| `getTransactions()` | GET | `/transactions` | ✅ Compatible |
| `sendChat()` | POST | `/chat` | ✅ Compatible |
| `getChallenges()` | GET | `/challenges` | ✅ Compatible (estructura) |
| `activateChallenge()` | POST | `/challenges/:id/activate` | ❌ Python tiene `/accept` |
| `completeChallenge()` | POST | `/challenges/:id/complete` | ❌ Python tiene `/decline` |
| `getGoals()` | GET | `/goals` | ⚠️ SHAPE MISMATCH (ver §5) |
| `addGoal()` | POST | `/goals` | ⚠️ SHAPE MISMATCH (ver §5) |
| `updateGoalSaved()` | PATCH | `/goals/:id` | ⚠️ Parcial |
| `deleteGoal()` | DELETE | `/goals/:id` | ✅ Compatible |
| `getSupportedBanks()` | GET | `/banking/banks` | ⚠️ No requiere JWT (ok), pero los datos de SUPPORTED_BANKS incluyen `falabella` status=active |
| `getBankAccounts()` | GET | `/banking/accounts` | ⚠️ SHAPE MISMATCH (ver §5) |
| `connectBank()` | POST | `/banking/accounts` | ✅ Endpoint correcto (fix 4f6be12) |
| `syncBankAccount()` | POST | `/banking/sync/:id` | ✅ Compatible |
| `syncAllBanks()` | POST | `/banking/sync-all` | ✅ Compatible |
| `disconnectBank()` | DELETE | `/banking/accounts/:id` | ✅ Compatible |
| `runSimulation()` | POST | `/simulate` | ✅ Compatible |

### Renderizado de bancos disponibles
- `BankConnect.jsx` filtra por `b.status === "active"`
- `SUPPORTED_BANKS` en Python: `bchile=active`, **`falabella=active`** (skeleton!), `bci=pending`, resto pending
- **Problema**: Falabella aparece como "Disponible" en la UI aunque su scraper es skeleton — devuelve `RecoverableIngestionError`
- BCI no aparece como disponible (status=pending) aunque tiene scraper parcial

---

## 5. MISMATCHES DETECTADOS

### MISMATCH-1 — Summary endpoint (🔴 CRÍTICO — BLOCKER)

**Causa**: Python devuelve respuesta plana, Node devuelve objeto anidado.

**Node** `GET /api/summary` devuelve:
```json
{
  "summary": {
    "balance": 500000,
    "income": 1200000,
    "expenses": 700000,
    "savingsRate": 41,
    "spendingRate": 58,
    "bankAccounts": [...],
    "totalBankBalance": 3800000,
    "hasBankAccounts": true,
    "incomeIsReal": true,
    "topCategory": {...},
    "categoryTotals": {...}
  },
  "profile": { "user": { "name": "Cristian", ... } },
  "badges": { "allBadges": [...], "newBadges": [...] }
}
```

**Python** `GET /api/summary` devuelve:
```json
{
  "balance": 500000,
  "income": 1200000,
  "expenses": 700000,
  "savings_rate": 0.4166,
  "net_flow": 500000,
  "period_days": 30
}
```

**Sky.jsx líneas 371–400**:
```javascript
setSummary(summaryRes.summary);          // ← undefined (no hay clave "summary")
setProfile(summaryRes.profile);          // ← undefined
setAllBadges(summaryRes.badges.allBadges); // ← CRASH: Cannot read allBadges of undefined
```
→ El bloque `init()` lanza excepción silenciosa, `setLoading(false)` ejecuta, pero todo el estado queda en null.
→ **La app muestra pantalla vacía o defaults.**

**Missing en Python que Sky.jsx necesita**:
- `summaryRes.summary.bankAccounts` → fallback para banco
- `summaryRes.summary.totalBankBalance` → balance display
- `summaryRes.summary.hasBankAccounts`, `summaryRes.summary.incomeIsReal`
- `summaryRes.profile.user.name` → saludo de Mr. Money
- `summaryRes.badges.allBadges` → sección de badges

---

### MISMATCH-2 — Bank accounts camelCase (🔴 CRÍTICO)

**Node** `GET /api/banking/accounts` devuelve:
```json
{
  "accounts": [{
    "id": "uuid",
    "bankId": "bchile",
    "bankName": "Banco de Chile",
    "bankIcon": "🏦",
    "balance": 1500000,
    "lastSyncAt": "2026-05-17T10:00:00Z",
    "lastSyncError": null,
    "status": "active",
    "syncCount": 5,
    "minutesAgo": 30,
    "accountType": "Cta. Corriente",
    "last4": null
  }],
  "totalBalance": 1500000
}
```

**Python** `GET /api/banking/accounts` devuelve:
```json
{
  "accounts": [{
    "id": "uuid",
    "bank_id": "bchile",
    "bank_name": "Banco de Chile",
    "bank_icon": "🏦",
    "last_balance": 1500000,
    "last_sync_at": "2026-05-17T10:00:00Z",
    "last_sync_error": null,
    "status": "active",
    "sync_count": 5,
    "minutes_ago": 30,
    "account_type": "Cuenta"
  }],
  "total_balance": 1500000
}
```

**Impacto en frontend**:
- `BankConnect.jsx` lee `accRes.totalBalance` → `undefined` (Python devuelve `total_balance`)
- `BankConnect.jsx` lee `acc.bankName`, `acc.bankId`, `acc.balance`, `acc.lastSyncAt`, `acc.lastSyncError` → todos `undefined`
- `Sky.jsx` lee `bankBalances.totalBalance` → `undefined` → mostrado como $0
- `Sky.jsx` lee `acc.bankName` en múltiples lugares → `undefined` → "Banco" como fallback

**Raíz**: Sin `model_config = ConfigDict(alias_generator=to_camel)` en los schemas Pydantic.

---

### MISMATCH-3 — Goals response wrapper + field names (🔴 CRÍTICO)

**Node** `GET /api/goals` devuelve:
```json
{
  "goals": [{
    "id": "uuid",
    "title": "Fondo de emergencia",
    "targetAmount": 600000,
    "savedAmount": 150000,
    "deadline": "2026-12-31",
    "projection": { "pct": 25, "remaining": 450000, "monthsToGoal": 9 }
  }]
}
```

**Python** `GET /api/goals` devuelve:
```json
[{
  "id": "uuid",
  "name": "Fondo de emergencia",
  "target_amount": 600000,
  "current_amount": 150000,
  "target_date": "2026-12-31",
  "progress_pct": 25.0,
  "created_at": "2026-01-01T..."
}]
```
*(array directo, sin wrapper `{goals: [...]}`, sin `projection` object)*

**Sky.jsx línea 376**:
```javascript
setGoals(goalsRes.goals); // ← undefined (Python devuelve array, no {goals:[...]})
```
→ goals = undefined → sección metas no muestra nada.

**Otros accesos rotos** (Sky.jsx):
- `goal.title` → undefined (Python: `name`)
- `goal.saved_amount` → undefined (Python: `current_amount`)
- `goal.projection.pct` → crash (Python: no tiene `projection` object)
- `const { goal } = await api.addGoal(...)` → goal=undefined (Python devuelve GoalOut directo)

---

### MISMATCH-4 — Challenge endpoints path (🟡 ALTO)

**api.js llama**:
- `POST /api/challenges/:id/activate`
- `POST /api/challenges/:id/complete`

**Python tiene**:
- `POST /api/challenges/:id/accept`
- `POST /api/challenges/:id/decline`

→ Activar/completar desafíos devuelve 404. Los desafíos se listan correctamente pero no se pueden operar.

---

### MISMATCH-5 — Falabella en SUPPORTED_BANKS como active (🟡 ALTO)

`SUPPORTED_BANKS` en `sources/__init__.py`:
- `falabella: status="active"` — **pero el scraper es skeleton**
- `BankConnect.jsx` filtra `b.status === "active"` → Falabella aparece como disponible en UI
- Si usuario intenta conectar Falabella → sync falla con `RecoverableIngestionError`

**Corrección**: cambiar `falabella.status` a `"pending"` hasta que el scraper esté implementado.

---

### MISMATCH-6 — Puerto Docker hardcodeado (🟡 ALTO)

`docker/api.Dockerfile`:
```dockerfile
CMD ["uvicorn", "sky.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Railway asigna `$PORT` dinámicamente. El Dockerfile no usa `$PORT`. Si Railway routea al `$PORT` (ej: 8080) y el servicio escucha en 8000, los healthchecks fallan.

La nota de lecciones aprendidas en Fase 11 dice: "`$PORT` requires wrapper `sh -c "..."` for shell expansion."

Corrección:
```dockerfile
CMD ["sh", "-c", "uvicorn sky.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

*(Si el deploy actual funciona con custom domain, posiblemente Railway está configurado para exponer puerto 8000 manualmente — verificar en dashboard.)*

---

### MISMATCH-7 — body.json sin commitear (🟢 BAJO)

`backend-python/body.json` contiene:
```json
{"monthly_savings":50000,"months":12,"annual_rate":0.05,"target_amount":1000000}
```
**Sin PII**. Son parámetros de simulación del endpoint `/api/simulate` usados en debugging. Debe borrarse del disco y agregarse a `.gitignore`.

---

### MISMATCH-8 — VITE_API_URL en Railway no verificado (🟡 ALTO)

No puedo acceder a Railway directamente en esta sesión. Si `VITE_API_URL` del servicio frontend sigue apuntando a Node (`appealing-benevolence-production.up.railway.app/api`), el frontend habla con Node y los mismatches de Python son irrelevantes **pero el cutover no ocurrió**.

El `.env.example` del frontend apunta al Python backend, pero ese archivo es solo ejemplo — lo que importa es el env var en el servicio Railway del frontend.

---

## 6. Funcionalidades testadas vs no-testadas

| Feature | Estado | Verificación |
|---|---|---|
| `GET /api/health` | ✅ Funcionando | Deploy Fase 11 verificó 200 |
| `GET /api/health/deep` | ✅ Funcionando | `{"db":"ok","redis":"ok","anthropic":"ok"}` |
| JWT auth (P0-1) | ✅ Cerrado | ES256 JWKS + Bearer token activo |
| `POST /api/chat` sin JWT | ✅ 401 | Verificado Fase 7 |
| `POST /api/chat` "hola" | ✅ Responde local | Verificado Fase 7 |
| `GET /api/summary` | ❌ Shape incorrecto | MISMATCH-1 |
| `GET /api/banking/accounts` | ❌ Shape incorrecto | MISMATCH-2 |
| `GET /api/goals` | ❌ Shape incorrecto | MISMATCH-3 |
| `POST /api/challenges/:id/activate` | ❌ 404 | MISMATCH-4 |
| `GET /api/challenges` | ✅ Compatible | ChallengesResponse shape ok |
| `GET /api/banking/banks` | ⚠️ Falabella as active | MISMATCH-5 |
| `POST /api/banking/accounts` | ✅ Endpoint ok | Fix 4f6be12 |
| `POST /api/banking/sync/:id` | ✅ Compatible | ARQ enqueue |
| `GET /metrics` | ✅ Con secret | Verificado Fase 10 |
| `GET /api/audit/me` | 🔵 No testado en prod | Fase 12 |
| `POST /api/account/export-request` | 🔵 No testado en prod | Fase 12 |
| Sync bancario real (BChile) | 🔵 No testado post-deploy | Requiere cuenta real |
| ARIA pipeline | 🔵 No testado en prod | Requiere aria_consent=true |
| Audit log populado | 🔵 No testado | Acción requerida para verificar |

---

## 7. Riesgos para demo a banqueros

### 🔴 Bloqueantes (deben resolverse antes)
1. **App muestra pantalla vacía / datos incorrectos** — MISMATCH-1 (summary shape) rompe la carga inicial de Sky.jsx. El usuario ve el loader indefinidamente o la app con defaults vacíos.
2. **Sección bancaria no funciona** — MISMATCH-2. Balances en $0, bancos sin nombre.
3. **Metas no cargan** — MISMATCH-3. `goals` = undefined.
4. **Falabella como disponible** — usuario puede intentar conectar y fallar silenciosamente.

### 🟡 Problemas visibles a banquero/auditor
5. **Puerto Docker** — si Railway no está configurado para puerto 8000, servicio puede caerse entre deploys.
6. **sky-cron-sync legacy** — cron en Railway apuntando a Node sigue activo. Si Node está apagado, el cron falla silenciosamente.
7. **Migration 002 y 005** pendientes de aplicación manual — si nunca se aplicaron, `uniq_tx_external` no existe → duplicación de transacciones posible, función purge no existe.
8. **README desactualizado** — un auditor que lea README.md pensará que el sistema está en Fase 5, no deployado.

### 🔵 Lo que un banco/auditor podría pedir
- Políticas RLS → `scripts/audit_rls_policies.py` disponible pero no ejecutado recientemente
- Audit log del usuario → endpoint `/api/audit/me` implementado pero no testado en prod
- Data export → `/api/account/export-request` implementado pero no testado en prod
- SECURITY.md → `docs/SECURITY.md` existe y tiene 9 secciones completas ✅
- DR Runbook → `docs/DR_RUNBOOK.md` existe ✅
- Key rotation → `docs/RUNBOOK_KEY_ROTATION.md` existe ✅

---

## 8. Resumen ejecutivo

### Estado general: 🔴 ROJO — NO listo para testers

El backend Python está deployado y sus endpoints individuales funcionan, pero **el contrato de respuesta no es compatible con el frontend en los endpoints críticos**. El frontend fue parcialmente migrado (auth, URL del endpoint de conexión bancaria) pero la forma de las respuestas (shapes) no se actualizó. El resultado es que la app carga pero muestra datos vacíos o incompletos en dashboard, metas y cuentas bancarias.

### Top 5 a fixear (en orden)

1. **Summary endpoint**: agregar wrapper `{summary: ..., profile: ..., badges: ...}` al Python `GET /api/summary` para que Sky.jsx pueda cargar el dashboard.

2. **Bank accounts camelCase**: agregar `model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)` a `BankAccountOut` + `BankAccountListResponse` o bien hacer el mapeo explícito en el router.

3. **Goals wrapper + fields**: envolver respuesta de `GET /api/goals` en `{goals: [...]}` y mapear `goal.title`/`goal.saved_amount`/`goal.projection` en los campos que Sky.jsx espera.

4. **Challenge paths**: agregar alias routes `/activate` y `/complete` al router de challenges (o renombrar `/accept`→`/activate`, `/decline`→`/complete`).

5. **Falabella status**: cambiar `falabella.status` a `"pending"` en `SUPPORTED_BANKS` hasta que el scraper esté completo.

### Estimación de esfuerzo

| Fix | Archivos | Tiempo estimado |
|---|---|---|
| #1 Summary shape | `api/routers/summary.py`, `api/schemas/summary.py`, `domain/finance.py` | 2–3h |
| #2 Banking camelCase | `api/schemas/banking.py`, `api/routers/banking.py` | 1h |
| #3 Goals shape | `api/routers/goals.py`, `api/schemas/goals.py` | 1h |
| #4 Challenge paths | `api/routers/challenges.py` | 30min |
| #5 Falabella pending | `ingestion/sources/__init__.py` | 5min |
| Bonus: body.json + .gitignore | 1 archivo | 5min |
| **Total** | | **~5–6h** |

**No se requiere tocar Sky.jsx** (God Component P1-1). Los fixes están 100% en el backend Python.

---

*Audit generado: 2026-05-17 · Claude Sonnet 4.6 · backend-python/docs/POST_CUTOVER_AUDIT.md*
