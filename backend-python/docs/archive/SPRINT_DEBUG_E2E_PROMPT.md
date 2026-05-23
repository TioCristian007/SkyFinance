# Sprint Debug End-to-End — Prompt para sesión nueva de Claude Code

> Pegar este texto entero en una sesión NUEVA de Claude Code.
> Working dir: `C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL`
> Modelo recomendado: **Sonnet 4.6 high effort**.
> Tendrá acceso a `backend-python/.env` con credenciales reales para
> Supabase, Railway, Anthropic, GitHub.

---

## ESTADO ACTUAL (lo que el usuario reporta HOY, 2026-05-18)

Tras el sprint POST_CUTOVER (7 fixes commiteados como `da12ac5`, `7ecdf47`,
`051fcd0`, `7afe829`, `a9d8455`, `997c930`, `36f53ea`, `fae85de`) y push
exitoso a `origin/main`, **dos problemas críticos persisten** en producción:

1. **Frontend NO muestra Banco de Chile NI BCI como bancos para conectar.**
   Sky.jsx en `app.skyfinanzas.com` debería mostrarlos como `status="active"`
   (BChile) y `status="pending"` (BCI) pero ninguno aparece en la UI.

2. **Mr. Money cae a fallback offline.**
   El chat muestra: `"Tienes $0 disponibles. ¿En qué te ayudo?"` seguido de
   `"⚠ Sin conexión al servidor — modo básico"`. Esto es el fallback offline
   que el frontend activa cuando el backend no responde correctamente o el
   shape de respuesta no matchea.

Confirmado por el usuario:
- `git log origin/main..HEAD` → vacío (los 8 commits están pusheados)
- VITE_API_URL en Railway service `SkyFinance` apunta a Python (`https://api-v2.skyfinanzas.com/api`)
- Los 3 services Railway (frontend, sky-api-python, sky-worker-python) deberían estar Active

Es decir: los fixes #1-#7 fueron commiteados, pusheados y supuestamente
deployados, pero los issues no se resolvieron. **Hay bug(s) latente(s) que
requieren debug profundo en producción real.**

---

## CONTEXTO MÍNIMO DEL PROYECTO

Sky Finanzas es un sistema operativo financiero personal con app web
(`app.skyfinanzas.com`). SpA chilena, registrada en INAPI vía v5 PDF.
Fundadores: Cristian Vásquez + Juan José Latorre. Esta semana hay
**reuniones de pilotos con dueños/presidentes de bancos chilenos** — el
sistema TIENE que estar 100% funcional para invitar testers internos
(JJ + 3-5 amigos) ANTES de las reuniones.

Stack en producción:

```
app.skyfinanzas.com           → Railway service "SkyFinance" (React + Vite bundle estático)
api-v2.skyfinanzas.com        → Railway service "sky-api-python" (FastAPI + asyncpg)
                                 dominio Railway: sky-api-python-production.up.railway.app
sky-worker-python             → Railway worker (ARQ + Playwright + Chromium)
Redis                         → Railway plugin (cola ARQ, rate limiter, idempotency)
api.skyfinanzas.com           → Railway service "appealing-benevolence-production" (Node legacy)
                                 SIGUE DEPLOYADO pero el frontend ya NO le pega tráfico
                                 (queda en standby para rollback rápido)
appealing-benevolence-production.up.railway.app → mismo Node
sky-cron-sync                 → Railway legacy cron que llama Node (decommissionar post-estable)
```

Database: Supabase Postgres (project ID `trsvimjdudtfmdyufjbq`, región
`aws-1-sa-east-1`). Conexión: Transaction Pooler puerto 6543. Schema
public.* con RLS, schema aria.* bloqueado a clientes.

---

## HIPÓTESIS DE CAUSA RAÍZ (ordenadas por probabilidad)

### Para "bancos no aparecen"

**H1** — `GET /api/banking/banks` devuelve shape distinto al que Sky.jsx
       espera (objeto vs array, key distinta).
       Sky.jsx lo recibe pero filtra a lista vacía.

**H2** — `GET /api/banking/banks` falla (401/500) y Sky.jsx no maneja
       error, queda con lista vacía sin log visible al user.

**H3** — `GET /api/banking/banks` no existe en Python actual. Fue agregado
       en commit `7f26691 fix: add GET /api/banking/banks endpoint` pero
       puede tener bug. Verificar montaje en `api/main.py` router include.

**H4** — Filter en frontend muy estricto (commit `e8823dc fix: filter banks
       by status field instead of available`) — quizás filtra todos por
       no matchear key esperada.

**H5** — CORS bloquea el request (después de cambio de dominio).
       Devtools Network muestra OPTIONS fallando.

### Para "Mr. Money fallback offline"

**H6** — `POST /api/chat` devuelve shape incompatible — el frontend espera
       un campo (`text`, `message`, `content`?) y Python devuelve otro.

**H7** — `POST /api/chat` falla con 500/401/timeout. El frontend tiene
       try/catch que cae al `ChatTextResponse` local pre-armado:
       `"Tienes $0 disponibles. ¿En qué te ayudo?"` + warning offline.

**H8** — JWT no se envía correctamente en el header. El backend rechaza
       con 401, frontend cae a fallback.

**H9** — Rate limit, idempotency, o cualquier middleware bloquea con 4xx
       en el primer mensaje.

**H10** — Anthropic API key inválida o sin saldo. POST /api/chat tira 500
        cuando llama Anthropic, frontend cae a fallback.

**H11** — Bug en `domain/mr_money.py`: detección local de "hola" devuelve
        respuesta pero shape no es JSON parseable por el frontend.

---

## ACCESOS DISPONIBLES (en `backend-python/.env`)

Verificá que existen con:
```powershell
Select-String -Path backend-python/.env -Pattern "^(SUPABASE|RAILWAY|ANTHROPIC|GITHUB|BANK_ENCRYPTION|AUDIT_LOG|DATABASE)_"
```

Variables que tenés que poder usar:
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`
- `RAILWAY_TOKEN` (para CLI o API HTTP)
- `ANTHROPIC_API_KEY` (NO usar salvo verificación crítica de saldo)
- `GITHUB_PAT` (lectura del repo si necesitás)
- `BANK_ENCRYPTION_KEY` (NO usar salvo verificación de encrypt)
- `AUDIT_LOG_SALT` (para verificar audit_log hashing)
- `DATABASE_URL` (asyncpg pooler aws-1-sa-east-1)

Tools sugeridas:

```bash
# Railway CLI (instalar si no está):
npm install -g @railway/cli
export RAILWAY_TOKEN=<del .env>
railway login --browserless
railway link  # link al proyecto
railway variables --service SkyFinance         # ver env vars frontend
railway variables --service sky-api-python     # ver env vars backend
railway logs --service sky-api-python --tail 200
railway logs --service sky-worker-python --tail 200
railway status

# O API HTTP directa Railway GraphQL v2:
# https://backboard.railway.app/graphql/v2 con Bearer $RAILWAY_TOKEN

# Supabase REST API:
curl https://trsvimjdudtfmdyufjbq.supabase.co/rest/v1/<tabla> \
  -H "apikey: $SUPABASE_SERVICE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_KEY"

# Anthropic API status (verificar saldo sin gastar):
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-haiku-4-5","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}'
# Si responde 200 → API key válida y con saldo
# Si responde 401 → key inválida
# Si responde 403 → sin saldo
# 5 tokens de costo (~0.0001 USD)
```

**JWT real del usuario para tests de endpoints autenticados:**

Para probar endpoints protegidos como `/api/chat`, `/api/banking/accounts`,
necesitás un JWT real. Pide al usuario que lo extraiga de su navegador:

```javascript
// En DevTools Console de app.skyfinanzas.com (F12 → Console):
JSON.parse(localStorage.getItem('sb-trsvimjdudtfmdyufjbq-auth-token')).access_token
```

Le copiará un string largo tipo `eyJhbGciOiJIUzI1NiIsInR5cCI6...`. **Guardalo
en una variable temporal en tu shell**, NO lo escribas a un archivo:

```powershell
$env:TEST_JWT = "el-jwt-largo-del-usuario"
```

Después podés hacer requests autenticadas:
```powershell
curl.exe -H "Authorization: Bearer $env:TEST_JWT" https://api-v2.skyfinanzas.com/api/banking/accounts
```

---

## LECTURA OBLIGATORIA (en orden, ANTES de tocar nada)

1. `CLAUDE.md` (raíz) — doctrina, reglas inviolables
2. `backend-python/docs/POST_CUTOVER_AUDIT.md` — los 5 mismatches detectados
3. `backend-python/docs/POST_CUTOVER_PLAN.md` — los 7 fixes que se implementaron
4. `backend-python/docs/POST_CUTOVER_CLOSURE.md` — verificación e2e que dijo Sonnet
5. `backend-python/src/sky/api/routers/banking.py` — endpoints actuales
6. `backend-python/src/sky/api/routers/chat.py` — endpoint Mr. Money
7. `backend-python/src/sky/api/main.py` — qué routers están montados
8. `backend-python/src/sky/ingestion/sources/__init__.py` — SUPPORTED_BANKS actual
9. `backend-python/src/sky/domain/mr_money.py` — lógica del chat
10. `frontend/src/Sky.jsx` — código React (god component, donde se renderiza banks list y se llama chat)
11. `frontend/src/components/BankConnect.jsx` — UI específica de conectar banco
12. `frontend/src/services/api.js` — cliente HTTP, headers, base URL
13. Cualquier `frontend/src/**/*chat*` — lógica del chat frontend (puede estar en components/Chat.jsx o similar)

---

## TAREA — 4 fases obligatorias

### FASE A — VERIFICACIÓN DE ESTADO REAL EN PRODUCCIÓN (15-20 min)

Producir output en consola (no archivo aún).

1. **Railway services status**:
   ```bash
   railway status
   # o vía API HTTP listar projects/services
   ```
   Confirmar que los 3 services (SkyFinance, sky-api-python, sky-worker-python)
   están Active con último deploy `succeeded`.

2. **Verificar VITE_API_URL real en Railway frontend**:
   ```bash
   railway variables --service SkyFinance | grep VITE_API_URL
   ```
   Confirmar que es exactamente `https://api-v2.skyfinanzas.com/api`.

3. **Confirmar último commit deployado**:
   ```bash
   railway logs --service sky-api-python | head -20
   # Buscar "Starting worker" o "Application startup complete"
   ```
   Y comparar con `git log -1 --format='%H %s'`. El SHA debería coincidir
   con `fae85de docs: POST_CUTOVER_CLOSURE...` o más reciente.

4. **Logs de error últimas 24h en API + worker**:
   ```bash
   railway logs --service sky-api-python --tail 500 | grep -i "error\|exception\|traceback"
   railway logs --service sky-worker-python --tail 500 | grep -i "error\|exception\|traceback"
   ```
   Documentar cualquier error recurrente.

5. **Anthropic API key status**:
   Hacer el curl mínimo a Anthropic (5 tokens, ~$0.0001) para confirmar
   que la API key es válida y tiene saldo.

6. **Health checks contra producción real**:
   ```powershell
   curl.exe https://api-v2.skyfinanzas.com/api/health
   curl.exe https://api-v2.skyfinanzas.com/api/health/deep
   curl.exe https://api-v2.skyfinanzas.com/api/banking/banks
   # ↑ este endpoint NO requiere JWT — devuelve lista pública de bancos soportados
   ```

7. **Pedirle al usuario el JWT** (instrucciones arriba). Guardarlo en
   `$env:TEST_JWT`. Después:
   ```powershell
   curl.exe -H "Authorization: Bearer $env:TEST_JWT" https://api-v2.skyfinanzas.com/api/banking/accounts
   curl.exe -H "Authorization: Bearer $env:TEST_JWT" https://api-v2.skyfinanzas.com/api/summary
   curl.exe -H "Authorization: Bearer $env:TEST_JWT" -X POST https://api-v2.skyfinanzas.com/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message":"hola"}'
   ```
   Pegá EXACTAMENTE el JSON que devuelve cada uno.

---

### FASE B — ANÁLISIS DE FRONTEND (15 min)

NO modificar nada todavía. Solo entender.

1. **Buscar dónde Sky.jsx carga bancos**:
   ```bash
   grep -n "banking/banks\|BankConnect\|availableBanks\|supportedBanks" frontend/src/Sky.jsx
   grep -rn "banking/banks" frontend/src/
   ```
   Identificar el fetch, el state, el filter, y el render.

2. **Buscar dónde Sky.jsx llama Mr. Money**:
   ```bash
   grep -n "chat\|sendMessage\|mrMoney" frontend/src/Sky.jsx
   grep -rn "api/chat" frontend/src/
   ```
   Identificar el POST, el shape esperado en response, el error handling
   que activa el fallback offline.

3. **Identificar el mensaje "Sin conexión al servidor — modo básico"**:
   ```bash
   grep -rn "Sin conexión\|modo básico\|offline" frontend/src/
   ```
   Encontrar exactamente cuándo se activa este fallback.

4. **Identificar "Tienes \$0 disponibles"**:
   ```bash
   grep -rn 'Tienes \$0\|0 disponibles' frontend/src/
   ```
   Confirmar si es un fallback hardcoded o viene del backend.

5. **Comparar shapes esperados vs entregados**:
   Para cada endpoint que el frontend llama:
   - Shape esperado (leer Sky.jsx / services/api.js)
   - Shape entregado (de los curls de Fase A)
   - Diferencia exacta

Producir mental note (no archivo aún) con TODOS los mismatches encontrados.

---

### FASE C — DIAGNÓSTICO DOCUMENTADO + PLAN (30 min)

Producir: `backend-python/docs/POST_CUTOVER_DEBUG_AUDIT.md`

Estructura:

```markdown
# Post-Cutover Debug Audit — 2026-05-18

## Bug 1: Bancos BChile/BCI no aparecen
- Endpoint llamado por frontend: <URL exacta>
- Status code recibido: <200/4xx/5xx>
- Shape recibido: <JSON real>
- Shape esperado por Sky.jsx: <de leer el código>
- Diff exacto: <campo X vs campo Y, array vs object, etc.>
- Causa raíz identificada: <H1/H2/.../H5>
- Fix propuesto: <archivo, líneas, cambio concreto>
- Verificación post-fix: <comando>

## Bug 2: Mr. Money fallback offline
- (mismo formato)
- Causa raíz: <H6/H7/.../H11>
- Fix propuesto: <archivo, líneas, cambio>

## Bugs adicionales encontrados (si los hay)
- ...

## Pre-requisitos del usuario (si hay alguno manual)
- ...

## Estimación: <X min de implementación + Y min de testing>
```

Pasame el audit + plan al usuario para APROBACIÓN antes de Fase D.

---

### FASE D — EJECUCIÓN DE FIXES (tras aprobación, 30-60 min)

1. Implementar fixes en orden de criticidad
2. Tests automatizados: que sigan pasando los 359
3. Commit POR FIX con mensaje descriptivo
4. Push tras tu OK final
5. Esperar redeploy Railway (~3-5 min)
6. Verificar con curls:
   ```powershell
   curl.exe https://api-v2.skyfinanzas.com/api/banking/banks
   # Debe devolver array con BChile y BCI
   curl.exe -H "Authorization: Bearer $env:TEST_JWT" -X POST https://api-v2.skyfinanzas.com/api/chat \
     -H "Content-Type: application/json" -d '{"message":"hola"}'
   # Debe devolver respuesta válida del backend Python (no fallback)
   ```
7. Producir `backend-python/docs/POST_CUTOVER_DEBUG_CLOSURE.md` con:
   - Commits ejecutados
   - Outputs de verificación
   - Instrucciones de prueba humana para el usuario:
     - Hard refresh Ctrl+F5 en app.skyfinanzas.com
     - Click "Conectar banco" → DEBE ver BChile y BCI
     - Click Mr. Money → escribir "hola" → DEBE recibir respuesta sin warning offline

---

## DOCTRINAS INVIOLABLES (no negociar)

1. **PLAN-FIRST**: Fase C documentada y aprobada antes de tocar código.
2. **NO refactor masivo de Sky.jsx** (P1-1 en deuda). Solo fixes quirúrgicos
   donde sea estrictamente necesario para conectividad.
3. **SIN romper backend Node**: sigue en standby para rollback. NO tocarlo.
4. **API NUNCA importa Playwright** (worker only).
5. **JWT criptográficamente verificado en endpoints protegidos** — confirmar.
6. **ARIA con consent guard** — no tocar a menos que sea causa raíz.
7. **Sin print, structlog get_logger**.
8. **Sin PII en logs, métricas, audit log, Sentry**.
9. **Commits descriptivos en español**, formato:
   `fix(<ámbito>): <descripción concreta del bug y solución>`
10. **El usuario pushea**. Vos commit local.
11. **PowerShell por defecto** (Windows). `$env:VAR` para set.
12. **NO usar tokens caros (Anthropic) en exploración**. Reservar para
    verificación crítica única.

---

## DEFINITION OF DONE (criterio claro de "listo")

Cuando lo siguiente se cumple, el sprint cierra:

1. `https://api-v2.skyfinanzas.com/api/banking/banks` devuelve JSON con
   al menos BChile y BCI listados (status active/pending visibles)
2. `https://api-v2.skyfinanzas.com/api/chat` con JWT válido y mensaje "hola"
   devuelve respuesta JSON con shape correcto (sin error 4xx/5xx)
3. En `app.skyfinanzas.com` (post hard refresh):
   - Botón "Conectar banco" muestra BChile y BCI en la lista
   - Mr. Money respondió un mensaje sin "⚠ Sin conexión al servidor"
   - No hay errores rojos en DevTools Console
   - Network tab muestra requests a `api-v2.skyfinanzas.com` con status 200/201
4. `POST_CUTOVER_DEBUG_CLOSURE.md` listo y commit pusheado

---

## OUTPUT ESPERADO AL FINAL

Mensaje al usuario en formato:

```
Bugs fixeados:
  Bug 1 — <descripción 1 línea> — commit <SHA>
  Bug 2 — <descripción 1 línea> — commit <SHA>
  (...)

Verificación automatizada:
  curl /api/banking/banks → OK con N bancos
  curl /api/chat con "hola" → OK con respuesta
  Tests pytest: <N passed>

Acción humana requerida:
  1. Ctrl+F5 en app.skyfinanzas.com
  2. Conectar banco → ver BChile + BCI
  3. Mr. Money "hola" → respuesta sin warning offline
  4. Si falla algún paso: pegá pantalla DevTools Console + Network

Estado: 🟢 / 🟡 / 🔴 con justificación corta.
```

---

## ARRANQUE

```powershell
cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL
git status
git log --oneline -10

# Verificar .env existe con credenciales:
Select-String -Path backend-python/.env -Pattern "^(SUPABASE|RAILWAY|ANTHROPIC|GITHUB)_"

# Después: leer los 13 archivos obligatorios y arrancar Fase A.
```

**Andá. Reportar al usuario al final de cada Fase (A, B, C — pedir aprobación, D).**
