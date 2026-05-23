# Sprint CORS + Container Debug — Prompt para sesión nueva de Claude Code

> Pegar entero en sesión nueva de Claude Code.
> Working dir: `C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL`
> Modelo: **Sonnet 4.6 high effort**
> Acceso a `backend-python/.env` con RAILWAY_TOKEN, SUPABASE_*, ANTHROPIC_API_KEY

---

## PROMPT (entre las marcas)

```
═══════════════════════════════════════════════════════════════════════════════
SPRINT DEBUG — CORS preflight blocked + container 502 en producción
═══════════════════════════════════════════════════════════════════════════════

CONTEXTO ESTRATÉGICO

Sky Finanzas tiene reuniones con dueños/presidentes de bancos chilenos
ESTA SEMANA. app.skyfinanzas.com TIENE que funcionar. Hoy NO funciona.

Stack:
  app.skyfinanzas.com           → React frontend (Railway "SkyFinance")
                                   VITE_API_URL=https://api-v2.skyfinanzas.com/api
  api-v2.skyfinanzas.com        → FastAPI backend Python (Railway "sky-api-python")
                                   custom domain con SSL Railway-emitted
  sky-worker-python             → ARQ worker Python (mismo repo, mismo Dockerfile)
  Redis                         → Railway plugin (internal URL)
  api.skyfinanzas.com           → Backend Node legacy (NO TOCAR, está en standby)

═══════════════════════════════════════════════════════════════════════════════
PROBLEMA REPORTADO HOY (2026-05-19)

Frontend en `app.skyfinanzas.com` muestra en DevTools Console:

  Access to fetch at 'https://api-v2.skyfinanzas.com/api/summary' from
  origin 'https://app.skyfinanzas.com' has been blocked by CORS policy:
  Response to preflight request doesn't pass access control check:
  No 'Access-Control-Allow-Origin' header is present on the requested resource.

Lo mismo para /goals, /transactions, /challenges, /banking/accounts,
/banking/banks. Resultado: dashboard vacío, "init error: No hay
conexión con el backend", Mr. Money en modo fallback offline.

Hace 1 turno, curl directo al backend devolvía:
  HTTP/1.1 502 Bad Gateway
  Server: railway-edge
  X-Railway-Fallback: true
  {"status":"error","code":502,"message":"Application failed to respond"}

Esto indica que el CONTAINER del backend Python no está respondiendo —
Railway edge devuelve un fallback. Si el container está muerto, CORS
nunca se aplica (no hay backend para aplicarlo).

═══════════════════════════════════════════════════════════════════════════════
COMMITS RECIENTES (orden cronológico, los últimos)

  a1af010  fix(railway): railway.json compartido — quitar healthcheckPath
  29b4623  fix: dockerfile en raíz backend-python + procfile fallback
  fae85de  docs: POST_CUTOVER_CLOSURE con 7 fixes
  36f53ea  fix(docker): usar PORT env var de Railway
  da12ac5  fix(summary): wrapper {summary, profile, badges}
  051fcd0  fix(goals): wrapper + camelCase
  7ecdf47  fix(banking): camelCase
  7afe829  fix(challenges): /activate /complete
  a9d8455  fix(sources): falabella → pending
  997c930  fix(dev): body.json + gitignore

El usuario confirma que `a1af010` se pusheó. Sin embargo el container
sigue dando 502, lo que sugiere que:
  - El redeploy aún no terminó, O
  - El Dockerfile creado en commit 29b4623 tiene un bug que crashea
    al arrancar, O
  - Hay otro problema (Redis URL, env vars faltantes, etc.)

═══════════════════════════════════════════════════════════════════════════════
HIPÓTESIS ORDENADAS POR PROBABILIDAD (las atacás en orden)

H1 — Container crashea al arrancar por bug en Dockerfile nuevo o env vars
     mal configuradas en Railway. Síntoma: 502 + X-Railway-Fallback.
     Acción: ver logs del deploy.

H2 — Redeploy en progreso o falló sin retry exitoso. Síntoma: 502 pero
     el último deploy en Railway dashboard está rojo/building.
     Acción: ver status de deploy + reintentar.

H3 — Container vivo pero crashea durante lifespan (Redis, DB, Sentry init).
     Síntoma: logs muestran traceback al arrancar, después se queda
     respondiendo 502.
     Acción: ver logs del runtime.

H4 — Container vivo y respondiendo pero CORS_ORIGINS env var mal en
     Railway. Síntoma: curl directo a /api/health devuelve 200, curl
     OPTIONS no devuelve Access-Control-Allow-Origin.
     Acción: leer env vars en Railway, comparar con
     core/config.py::cors_origins_list parsing.

H5 — CORS_ORIGINS correcto pero match falla por trailing slash, casing
     o protocolo. Síntoma: curl OPTIONS responde 200 pero sin header
     ACAO; logs muestran "Origin not allowed".
     Acción: agregar logging temporal en CORSMiddleware o parsearlo
     con `o.strip().rstrip("/")` en cors_origins_list.

H6 — Middleware order incorrecto: CORSMiddleware no es el outermost,
     otro middleware intercepta OPTIONS antes y no setea CORS.
     Acción: leer api/main.py líneas del middleware stack. CORS DEBE
     ser el último `add_middleware()` (LIFO → más externo).

H7 — Custom domain Railway proxy comio el header. Caso raro pero posible.
     Acción: curl al dominio Railway interno
     (sky-api-python-production.up.railway.app) y comparar.

H8 — pydantic-settings no lee CORS_ORIGINS por bug en environment loading.
     Acción: ejecutar `python -c "from sky.core.config import settings;
     print(settings.cors_origins_list)"` adentro del container (vía
     Railway shell o local con env var seteada).

═══════════════════════════════════════════════════════════════════════════════
LECTURA OBLIGATORIA antes de ejecutar nada

1. CLAUDE.md (raíz) — doctrina inviolable
2. backend-python/src/sky/api/main.py — middleware stack, CORS config
3. backend-python/src/sky/core/config.py — cors_origins_list property,
   parsing de la env var
4. backend-python/Dockerfile — el Dockerfile que creó Sonnet en commit
   29b4623 (raíz de backend-python)
5. backend-python/Procfile — fallback que creó Sonnet
6. backend-python/railway.json — config compartida (ya limpia en a1af010)
7. backend-python/docs/POST_CUTOVER_DEBUG_AUDIT.md — diagnóstico de
   sesión anterior (Sonnet ya identificó algunos issues, NO lo invalidás
   pero contrastá hipótesis)
8. backend-python/docs/MIGRATION_13_PHASES.md — qué se hizo
9. backend/services/* (Node) — para paridad si hace falta

═══════════════════════════════════════════════════════════════════════════════
ACCESOS

En backend-python/.env:
  SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY
  RAILWAY_TOKEN  ← para CLI o API HTTP
  ANTHROPIC_API_KEY, GITHUB_PAT
  BANK_ENCRYPTION_KEY, AUDIT_LOG_SALT
  DATABASE_URL (pooler asyncpg)

Tools:

Railway CLI:
  npm install -g @railway/cli   # si no está
  $env:RAILWAY_TOKEN = "<del .env>"
  railway login --browserless
  railway link    # link al project
  railway status
  railway logs --service sky-api-python --tail 200
  railway logs --service sky-api-python --deployment-build-log
  railway variables --service sky-api-python

Railway API HTTP (alternativa si CLI tira problemas en Windows):
  curl.exe -X POST https://backboard.railway.app/graphql/v2 \
    -H "Authorization: Bearer $env:RAILWAY_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query":"..."}'

Supabase (probable que NO haga falta para este bug):
  supabase-py ya en .venv
  psql via DATABASE_URL para queries directas

═══════════════════════════════════════════════════════════════════════════════
PLAN DE TRABAJO — 4 fases obligatorias

═════════════════════════════════════════════
FASE A — VERIFICAR STATUS DEL CONTAINER (15 min)
═════════════════════════════════════════════

Objetivo: confirmar si el container está vivo o muerto. Sin esto, todo
el resto de hipótesis es especulación.

A.1 — Curl directo al dominio Railway interno (NO al custom domain):
      curl.exe -i https://sky-api-python-production.up.railway.app/api/health
      Pegá las primeras 10 líneas de la respuesta.

      Si responde {"status":"ok"} → container vivo, problema es CORS
      o custom domain (Fase B)
      Si responde 502 → container muerto, debug Dockerfile/lifespan (Fase A.2)

A.2 — Si container muerto: logs del último deploy
      railway logs --service sky-api-python --tail 200

      Buscá específicamente:
        - "Application startup complete"  → arrancó, problema es otro
        - Tracebacks Python                → bug en código o env vars
        - "ImportError"                    → dep faltante en Dockerfile
        - "RuntimeError"                   → fail-fast (CORS_ORIGINS,
                                              PROMETHEUS_SECRET, SENTRY_DSN)
        - "Connection refused"             → Redis no llega
        - "asyncpg.exceptions"             → DB no conecta

      Pegá las primeras 50 líneas del log + cualquier traceback.

A.3 — Si los logs muestran lifespan error pero el container reinicia
      por restartPolicy ON_FAILURE: verificar si el último deploy
      terminó "deploying" o "succeeded":
      railway status   # o vía Railway dashboard Deployments tab

A.4 — Verificar build log si los logs runtime son confusos:
      railway logs --service sky-api-python --deployment-build-log

      Buscá:
        - "Successfully built"          → build OK
        - "ERROR: Could not find..."    → dep no instalada
        - "Step X/Y FAILED"             → error en Dockerfile

A.5 — Verificar variables de entorno del service:
      railway variables --service sky-api-python

      Crítico ver:
        CORS_ORIGINS         debe ser https://app.skyfinanzas.com
                             (sin trailing slash, sin comillas)
        REDIS_URL            debe apuntar a redis.railway.internal:6379
                             (NO localhost)
        DATABASE_URL         debe ser pooler aws-1-sa-east-1:6543
        SUPABASE_*           presentes con valores eyJ...
        BANK_ENCRYPTION_KEY  hex 64 chars
        AUDIT_LOG_SALT       hex 64 chars
        ANTHROPIC_API_KEY    sk-ant-...
        PROMETHEUS_SECRET    hex 64 chars
        SENTRY_DSN           https://xxx@sentry.io/yyy (formato DSN)
        NODE_ENV             production
        PORT                 8000 o 8080 (debe matchear custom domain)

      Pegá las var keys (NO los valores), confirmá presencia.
      Si alguna falla → ese es el root cause.

═════════════════════════════════════════════
FASE B — SI CONTAINER ESTÁ VIVO: DEBUG CORS (20 min)
═════════════════════════════════════════════

Solo entrá acá si A.1 dio {"status":"ok"} en el dominio Railway interno.

B.1 — Curl OPTIONS preflight con verbose:
      curl.exe -X OPTIONS https://sky-api-python-production.up.railway.app/api/summary `
        -H "Origin: https://app.skyfinanzas.com" `
        -H "Access-Control-Request-Method: GET" `
        -H "Access-Control-Request-Headers: Authorization,Content-Type" `
        -v 2>&1 | Select-Object -First 60

      Buscá:
        < HTTP/1.1 200 OK                          → CORS OK del Railway internal
        < access-control-allow-origin: https://... → header presente
        < HTTP/1.1 4xx/5xx                         → middleware bug
        ausencia de access-control-*               → CORSMiddleware no aplicó

      Si Railway internal funciona pero custom domain no → bug Railway
      proxy custom domain (raro). Si ninguno funciona → bug Python.

B.2 — Si CORS no aplica, leer cors_origins_list:
      Ejecutar adentro del container o local con env var seteada:
        $env:CORS_ORIGINS = "https://app.skyfinanzas.com"  # mismo valor que Railway
        cd backend-python
        python -c "from sky.core.config import settings; print(repr(settings.cors_origins_list))"

      Esperado: ['https://app.skyfinanzas.com']
      Si lista vacía → env var no lee
      Si lista con trailing slash o espacio → bug parsing

B.3 — Si parsing OK, leer middleware order en api/main.py:
      Confirmar que CORSMiddleware es el ÚLTIMO `app.add_middleware()`
      (es el outermost por LIFO). Líneas ~110-136.

      Si NO es el último → reorden. CORS debe ser primero en interceptar
      OPTIONS antes que cualquier auth/idempotency/etc.

B.4 — Test custom domain vs internal:
      curl.exe -X OPTIONS https://api-v2.skyfinanzas.com/api/summary `
        -H "Origin: https://app.skyfinanzas.com" `
        -H "Access-Control-Request-Method: GET" -i

      Si difiere del internal → Railway custom domain proxy issue.
      Reproducir vía Railway support o reconfigurar custom domain.

═════════════════════════════════════════════
FASE C — DIAGNÓSTICO DOCUMENTADO + PLAN (15 min)
═════════════════════════════════════════════

Producir: backend-python/docs/POST_CUTOVER_CORS_DEBUG.md

Estructura:

1. Status real del container (vivo/muerto, último deploy exitoso/fallido)
2. Si muerto: traceback exacto del crash + causa raíz identificada
3. Si vivo: por qué CORS no aplica (env var, parsing, order, proxy)
4. Fix propuesto (concreto, archivo, líneas)
5. Verificación post-fix (comando, output esperado)
6. Rollback si el fix rompe otra cosa

Pasar el plan al usuario para APROBACIÓN antes de Fase D.

═════════════════════════════════════════════
FASE D — EJECUCIÓN DE FIXES (post-aprobación, 30 min)
═════════════════════════════════════════════

1. Implementar fix (1 commit por fix)
2. Mantener tests verde (≥359 passed)
3. Push si fix es backend code, esperar redeploy (~3 min)
4. Si fix es env var Railway → setear via dashboard o CLI, esperar redeploy
5. Verificar con curls:
   - Domain Railway interno → 200 OK
   - Custom domain → 200 OK  
   - OPTIONS preflight → ACAO header presente
   - GET /api/health/deep → all green
6. Generar POST_CUTOVER_CORS_CLOSURE.md con instrucciones para que el
   usuario verifique en app.skyfinanzas.com (hard refresh + login + test
   visual)

═══════════════════════════════════════════════════════════════════════════════
DOCTRINAS INVIOLABLES

1. PLAN-FIRST: Fase C antes de tocar código.
2. NO bajar a modo degradado si Redis/DB falla — fix root cause.
3. NO romper backend Node (sigue en standby).
4. SIN refactor masivo Sky.jsx. Fixes quirúrgicos en backend Python.
5. JWT criptográfico verificado en endpoints protegidos.
6. ARIA con consent guard intacto.
7. Sin print, structlog get_logger.
8. Sin PII en logs, métricas, audit, Sentry.
9. Commits en español: fix(<ámbito>): <descripción>.
10. Usuario pushea. Vos commit local.
11. PowerShell por defecto.
12. Si encontrás un nuevo problema fuera de scope, documentar como
    TODO y NO arreglar inline.

═══════════════════════════════════════════════════════════════════════════════
DEFINITION OF DONE

1. curl.exe https://api-v2.skyfinanzas.com/api/health → 200 con JSON
2. curl.exe OPTIONS con Origin header → 200 + Access-Control-Allow-Origin
3. Usuario hace Ctrl+F5 en app.skyfinanzas.com → dashboard carga
4. DevTools Network tab → cero requests bloqueadas por CORS
5. Mr. Money "hola" → respuesta del backend (no fallback offline)
6. Botón "conectar banco" → ve BChile, BCI (status acorde a SUPPORTED_BANKS)

═══════════════════════════════════════════════════════════════════════════════
OUTPUT ESPERADO AL FINAL

  Status: 🟢 / 🟡 / 🔴

  Root cause identificado:
    <descripción 1 frase>

  Fix aplicado:
    Commit <SHA> — <descripción>

  Verificación automatizada:
    [output curls]

  Acción humana pendiente (si la hay):
    <pasos manuales en Railway o Squarespace>

  Acción humana de verificación visual:
    <pasos en app.skyfinanzas.com>

═══════════════════════════════════════════════════════════════════════════════
ARRANQUE

  cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL
  git status
  git log --oneline -10
  Select-String -Path backend-python/.env -Pattern "^(SUPABASE|RAILWAY|CORS|REDIS|DATABASE|SENTRY|PROMETHEUS)_"

  # Después: leer los 9 archivos obligatorios y arrancar Fase A.

Andá. Reportá al usuario al final de cada Fase. NO tocar código hasta
Fase C aprobada.
```

---

## Cómo copiarlo limpio

```powershell
$raw = Get-Content backend-python\docs\SPRINT_CORS_DEBUG_PROMPT.md -Raw
$match = [regex]::Match($raw, '(?s)```\r?\n(.*?)\r?\n```')
$match.Groups[1].Value | Set-Clipboard
Write-Host "Prompt copiado al clipboard. Pegá con Ctrl+V en Claude Code nuevo." -ForegroundColor Green
```

Después abrís sesión nueva de Claude Code, Ctrl+V, Enter.
