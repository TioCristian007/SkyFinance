# Sprint Post-Cutover — Prompt para sesión nueva de Claude Code

> Pegar este texto entero en una sesión nueva de Claude Code, working dir =
> `C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL`.
> Modelo recomendado: **Sonnet 4.6 con effort alto** (max effort si está disponible).
> Esta sesión tendrá acceso a `backend-python/.env` con credenciales para
> Supabase, Railway, Anthropic y GitHub.

---

## PROMPT (pegar entero)

```
═══════════════════════════════════════════════════════════════════════════════
SPRINT POST-CUTOVER — Auditoría + Fixes + Frontend full conectado a Python
═══════════════════════════════════════════════════════════════════════════════

CONTEXTO ESTRATÉGICO

Sos un agente trabajando en Sky Finanzas, un sistema operativo financiero
personal con app móvil/web para usuarios chilenos. Fundadores: Cristian
Vásquez (22.141.522-1) + Juan José Latorre (22.003.365-1). SpA constituida
(SkyFinanzas SpA, RUT 78.395.382-K). Propiedad intelectual registrada en
INAPI (Chile) via "Estado del Arte v5 documentado".

La empresa NEGOCIA esta semana pilotos con dueños/presidentes de bancos
chilenos para integración con APIs oficiales. Este sprint es CLAVE: el
sistema tiene que estar 100% operativo, profesional, sin mismatches, listo
para que entren testers y para mostrar a banqueros. No es teoría — es la
base de una empresa de inteligencia y datos B2B que cierra tratos con
bancos.

ESTADO TÉCNICO HOY

El proyecto tiene un monorepo con 3 patas:

  sky_OFFICIAL/
  ├── backend/             ← Node.js Express (PROD original, sirviendo desde 2026)
  ├── backend-python/      ← Python 3.12 + FastAPI + ARQ + Playwright (MIGRACIÓN)
  ├── frontend/            ← React 18 + Vite (sirve usuarios reales)
  ├── docs/                ← Docs business cross-cutting (SECURITY_INFRASTRUCTURE)
  └── scripts/             ← Helpers (md_to_pdf, etc.)

Migración Node → Python: completada al 100% (Fases 0-13 del plan v5).
Cutover ejecutado pero con mucho hotfix (ver últimos commits, especialmente
los 10+ "fix:" recientes). Frontend fue tocado durante cutover y quedaron
mismatches.

INFRAESTRUCTURA EN PRODUCCIÓN

Dominios y servicios actuales (verificar todo con Railway/Squarespace):

  app.skyfinanzas.com           → Frontend React (Railway service "SkyFinance")
  api.skyfinanzas.com           → Backend Node (Railway "appealing-benevolence-production")
  api-v2.skyfinanzas.com        → Backend Python (Railway "sky-api-python")
                                  custom domain, SSL Let's Encrypt
  sky-api-python-production
    .up.railway.app             → mismo backend Python, dominio Railway interno

Worker Python:
  Railway service "sky-worker-python"  ← procesa syncs bancarios async con
                                         Chromium + browser pool 4

Cron externo:
  Railway service "sky-cron-sync"  ← LEGACY, llama al cron-due del Node
                                     debe decommissionarse cuando Python tome 100%

Storage:
  Supabase Storage bucket "data-exports" (privado, ZIP only)

Database:
  Supabase Postgres (project ID: trsvimjdudtfmdyufjbq)
  Región: aws-1-sa-east-1
  Conexión: Transaction Pooler puerto 6543 (NO Direct 5432 — IPv6 only)
  asyncpg requiere connect_args={"statement_cache_size": 0} para pgbouncer compat

Redis:
  Railway plugin Redis, internal URL: redis.railway.internal:6379
  Usado por: ARQ queue, slowapi rate limiter, idempotency middleware,
  circuit breaker, rate limiter de scrapers

═══════════════════════════════════════════════════════════════════════════════
PROBLEMAS CONOCIDOS POST-CUTOVER (lo que el founder reportó hoy)

1. FRONTEND MUESTRA BANCOS DESACTUALIZADOS
   El frontend muestra "Falabella" y "BChile" como bancos conectables (eran
   los del backend Node). El backend Python soporta BCI + BChile en scrapers
   (Falabella es skeleton todavía). Hay inconsistencia entre lo visible
   y lo realmente operativo.

2. PORT MISMATCH 8000 vs 8080
   Custom domain api-v2.skyfinanzas.com está routeando a puerto 8000.
   Dominio interno sky-api-python-production.up.railway.app routea a 8080.
   No está claro cuál es el correcto. Hay que decidir y unificar.

3. SKY.JSX GOD COMPONENT (1678 LOC, P1-1)
   El componente principal del frontend es enorme y tiene mucha lógica de
   negocio. Durante el cutover se hicieron varios fixes inline (commits
   recientes: e7e83f4 setAccessToken, e8823dc filter banks, a3cef8d snake_case).
   Hay que VERIFICAR (no refactorear masivamente — eso es otro sprint) que:
   - Las llamadas al backend usen VITE_API_URL correctamente
   - El shape esperado de los endpoints coincide con lo que el backend Python
     efectivamente devuelve
   - Los botones de bancos muestran los que el backend Python soporta

4. VARIABLES Y CONFIG DESINCRONIZADOS
   El frontend's Railway env var VITE_API_URL podría seguir apuntando a Node
   (`appealing-benevolence-production.up.railway.app/api`) o ya estar en Python
   (`api-v2.skyfinanzas.com/api`). Hay que verificar y decidir cuál debe ser.

5. CARPETAS DOCS/SCRIPTS A NIVEL RAÍZ DEL REPO
   El usuario creó recientemente:
     /docs/SECURITY_INFRASTRUCTURE.md (.pdf)
     /scripts/md_to_pdf.py
   Son materiales business legítimos para entregar a banqueros / auditores
   ISO27001 / consultores de seguridad. Deben quedar versionados. Verificá
   que estén commiteados.

6. BODY.JSON EN backend-python/
   Probable debug output. Verificar si contiene PII real. Si sí, eliminar
   del disco Y asegurar que no esté commiteado.

═══════════════════════════════════════════════════════════════════════════════
LECTURA OBLIGATORIA (en este orden, antes de hacer NADA)

1. CLAUDE.md (raíz del repo)
   — doctrina del proyecto, reglas inviolables, stack, fases técnicas

2. backend-python/README.md
   — estado real del backend Python (cuáles fases cerradas, qué está vivo)

3. backend-python/docs/MIGRATION_13_PHASES.md
   — plan maestro técnico, fases 0-13 cerradas con detalles

4. backend-python/docs/SECURITY.md
   — política de seguridad real implementada

5. backend-python/docs/HANDOVER_FASE_9.md sección §3.3 (TODOs activos)
   — deuda menor documentada, varias cosas son scope-creep prohibido

6. backend-python/src/sky/ingestion/sources/__init__.py
   — SUPPORTED_BANKS list (esto define qué bancos visibles en frontend
     deberían ser)

7. backend-python/src/sky/api/routers/banking.py
   — endpoints de banking, especialmente GET /api/banking/banks
     (qué shape devuelve, qué filter aplica)

8. backend-python/src/sky/api/main.py
   — todos los routers montados, middlewares order

9. frontend/src/services/api.js
   — cómo el frontend llama al backend (VITE_API_URL usage)

10. frontend/src/Sky.jsx
    — god component, especialmente la sección donde renderiza bancos
      y la sección donde llama a /api/banking

11. frontend/src/components/BankConnect.jsx
    — flow de conectar nueva cuenta bancaria

12. backend/services/* (Node — comparar shapes/endpoints para paridad)
    — referencia: lo que el frontend actual espera

13. backend-python/docs/FASE11_CLOSURE_PLAN.md, FASE12_CLOSURE_PLAN.md
    — entender qué se implementó recientemente y los gates verificados

═══════════════════════════════════════════════════════════════════════════════
RECURSOS Y ACCESOS DISPONIBLES

backend-python/.env contiene credenciales reales para:
  SUPABASE_URL=https://trsvimjdudtfmdyufjbq.supabase.co
  SUPABASE_ANON_KEY=<eyJ... — lectura read-only RLS>
  SUPABASE_SERVICE_KEY=<eyJ... — service_role bypassa RLS>
  RAILWAY_TOKEN=<token — para Railway CLI o API HTTP>
  BANK_ENCRYPTION_KEY=<hex 64 — NO USAR salvo verificación crítica>
  ANTHROPIC_API_KEY=<sk-ant-... — NO USAR para tests reales sin necesidad>
  GITHUB_PAT=<token GitHub — solo lectura del repo si necesitás>
  AUDIT_LOG_SALT=<hex 64 — para verificar hashing audit log>
  DATABASE_URL=<postgresql+asyncpg://... pooler aws-1-sa-east-1:6543>

Tools disponibles para explorar infra:

  Railway CLI:
    - Instalar si no está: npm install -g @railway/cli
    - railway login --browserless (con RAILWAY_TOKEN env var)
    - railway environment, railway status, railway variables, railway logs
    - O usar API HTTP directa: https://backboard.railway.app/graphql/v2

  Supabase:
    - supabase-py (ya en pyproject.toml, ya instalado en venv)
    - O psql via DATABASE_URL para queries directas
    - O REST API: https://trsvimjdudtfmdyufjbq.supabase.co/rest/v1/

  GitHub:
    - gh CLI con GITHUB_PAT
    - O git directo del repo local

  Frontend en producción:
    - Inspeccionar https://app.skyfinanzas.com en navegador (manual user)
    - O analizar el HTML/JS bundle desde la URL

═══════════════════════════════════════════════════════════════════════════════
TAREA — 3 fases obligatorias

FASE A — AUDITORÍA COMPLETA (1-2 horas)
═════════════════════════════════════════

Producir: backend-python/docs/POST_CUTOVER_AUDIT.md

Estructura del documento:

1. Estado actual del repo (git log últimos 20 commits, branches, untracked)
2. Estado de Railway services (cada uno: status, env vars críticas, domain,
   port config, último deploy success/failure):
     - SkyFinance (frontend)
     - appealing-benevolence-production (backend Node)
     - sky-api-python (backend Python)
     - sky-worker-python (worker Python)
     - Redis (plugin)
     - sky-cron-sync (legacy)

3. Estado de Supabase:
     - Lista de tablas en schema public y aria
     - RLS enabled por cada tabla
     - Run scripts/audit_rls_policies.py y pegar output
     - Lista de policies por tabla (resumido)
     - Verificación que migrations 001-005 están aplicadas
     - Bucket "data-exports" verificado

4. Estado del frontend (sin modificar nada):
     - Identificar TODOS los lugares en frontend/src donde se llama al backend
     - Listar endpoints usados con sus shapes esperados
     - Identificar dónde se renderizan los bancos disponibles
     - Identificar VITE_API_URL usage y dependencias

5. Mismatches detectados (la sección clave del audit):
     - Endpoints que el frontend llama pero el backend Python NO tiene
       o tiene con shape distinto
     - Bancos visibles en frontend vs SUPPORTED_BANKS del Python
     - Variables de entorno desincronizadas (frontend Railway vs backend Python
       Railway vs .env local)
     - Port mismatch 8000 vs 8080: cuál es el real, qué hay que cambiar
     - Cron externo sky-cron-sync apuntando a Node (cuándo decommissionar)

6. Funcionalidades testadas vs no-testadas en producción Python:
     - Health checks: estado
     - Auth (JWT): testar con curl + JWT real
     - Sync bancario: testar con cuenta de prueba si hay
     - Categorización: estado
     - Mr. Money: testar /api/chat con mensaje simple "hola"
     - Audit log: verificar que se popula (correr una acción auditable, queryear DB)
     - Data export: testar /api/account/export-request con curl + JWT
     - /api/audit/me: testar con curl + JWT

7. Riesgos identificados para el demo a banqueros (mañana o esta semana):
     - Lo que podría romper visible al usuario
     - Lo que un banco/auditor podría pedir y no tenemos

8. Resumen ejecutivo (TOP):
     - 1 línea con el estado general (verde/amarillo/rojo)
     - 5 puntos clave a fixear
     - Estimación de esfuerzo total

NO ESCRIBIR CÓDIGO en Fase A. Solo análisis y documentación.
Reportá cuando POST_CUTOVER_AUDIT.md esté listo, antes de pasar a Fase B.

═════════════════════════════════════════
FASE B — PLAN DE FIXES PRIORIZADO (30 min)
═════════════════════════════════════════

Producir: backend-python/docs/POST_CUTOVER_PLAN.md

Estructura:

1. Definition of Done (criterio claro de "listo para testers"):
   - app.skyfinanzas.com cargá y muestra Sky.jsx sin errores en console
   - El frontend pega exclusivamente al backend Python (api-v2.skyfinanzas.com)
   - Los bancos mostrados en la UI = bancos efectivamente soportados por Python
   - Un usuario test puede conectar UNA cuenta bancaria real (BChile o BCI),
     ver sus transacciones, hablar con Mr. Money, ver desafíos
   - Sin warnings ni errors en Sentry durante 24h de testing interno
   - Métricas en /metrics muestran tráfico real (sync_total > 0,
     api_request_duration > 0)

2. Lista de fixes priorizada (orden de ejecución):

   PRIORIDAD ALTA — bloqueantes para testers
     Fix #1: Frontend VITE_API_URL Railway env var → api-v2.skyfinanzas.com/api
     Fix #2: Port consistency 8000 vs 8080 (decidir + unificar)
     Fix #3: Bancos visibles en Sky.jsx = SUPPORTED_BANKS del Python
             (filtrar por status="active" probablemente)
     Fix #4: Verificar todos los endpoints que Sky.jsx llama existen en Python
             con shape compatible. Si hay shape mismatch, ajustar Python
             para devolver lo que el frontend espera (NO al revés —
             el frontend Node ya funciona, mantener compat)

   PRIORIDAD MEDIA — DX y observabilidad
     Fix #5: body.json en backend-python — verificar PII, borrar, agregar gitignore
     Fix #6: backend-python/.env REAL bien populado (no solo .gitignore)
     Fix #7: Verificar que ARQ queue name "sky:default" coincide entre encoder
             (banking_sync) y decoder (worker)
     Fix #8: TODO #8 del HANDOVER (slowapi memory en tests integration —
             solo si Sonnet anterior no lo cerró)

   PRIORIDAD BAJA — pulido para banqueros
     Fix #9: docs/SECURITY_INFRASTRUCTURE.md sincronizado con estado real Python
     Fix #10: Logs de Railway sin PII (verificar muestreo de logs últimas 24h)
     Fix #11: Cron sky-cron-sync — plan de decommission después de cutover estable

3. Procedimiento de ejecución por fix:
   Cada fix lista:
     - Archivos a tocar
     - Pasos concretos
     - Verificación post-fix (curl, query, etc.)
     - Rollback si algo se rompe

4. Estimación total y orden recomendado de ejecución

Pasar el plan al usuario para APROBACIÓN antes de Fase C.

═════════════════════════════════════════
FASE C — EJECUCIÓN DE FIXES (post-aprobación, 2-4 horas)
═════════════════════════════════════════

Solo después de "aprobado" del usuario.

1. Ejecutar fixes en orden de prioridad
2. Por cada fix:
   - Implementar
   - Tests si aplica (no romper los 359+ existentes)
   - Verificar con curl/query
   - Documentar el cambio si toca config Railway/Supabase
3. Commit por fix (o por grupo coherente — no commits gigantes mezclando todo)
4. Push permitido para fixes pequeños documentados; NO push si fix es estructural
   sin OK del usuario

5. Verificación end-to-end final (la prueba real):
   - Abrir https://app.skyfinanzas.com en navegador (pedile al usuario que
     pruebe en su browser y pegue lo que ve; vos no podés navegar HTTP)
   - Login con cuenta test
   - Ver dashboard
   - Botón "conectar banco" → ver lista de bancos = SUPPORTED_BANKS Python
   - Conectar una cuenta (BChile o BCI) con credenciales test
   - Ver transacciones cargadas
   - Mr. Money: "hola" + una pregunta financiera real
   - Verificar audit log se populó

6. Generar backend-python/docs/POST_CUTOVER_CLOSURE.md con:
   - Lista de fixes ejecutados
   - Outputs de verificación
   - Estado final: VERDE para testers
   - TODOs documentados que quedan abiertos

═══════════════════════════════════════════════════════════════════════════════
DOCTRINAS INVIOLABLES

1. PLAN-FIRST: nada se codea sin plan aprobado por el usuario.
2. Sin romper backend Node — sigue en standby para rollback rápido.
3. Sin REFACTOR MASIVO de Sky.jsx — eso es sprint dedicado posterior (P1-1).
   Fixes mínimos quirúrgicos solo donde sea necesario para la conectividad.
4. NUNCA importar Playwright en API Python — solo el worker.
5. JWT criptográficamente verificado en TODOS los endpoints protegidos.
6. ARIA solo si aria_consent=true. Schema aria.* bloqueado a clientes.
7. Sin print, structlog.get_logger() siempre.
8. Sin PII en métricas, logs, audit log (más allá de hashes), Sentry breadcrumbs.
9. Trabajamos directo en main. Sin PRs. El usuario pushea (vos commit local).
10. PowerShell por defecto. $env:VAR para set, if ($?) { } no &&.
11. Si encontrás deuda fuera de scope, documentar como TODO referenciando v5,
    NO arreglar inline.

═══════════════════════════════════════════════════════════════════════════════
PROCESO COMUNICATIVO

Reportar al usuario en estos hitos (sí o sí):
  - Cuando POST_CUTOVER_AUDIT.md esté listo (fin Fase A)
  - Cuando POST_CUTOVER_PLAN.md esté listo (fin Fase B) — pedir aprobación
  - Cuando ejecutaste cada fix de alta prioridad
  - Cuando POST_CUTOVER_CLOSURE.md esté listo (fin Fase C)
  - SI encontrás algo crítico (data leak, security hole, prod broken)

Reportes finos, no épicos. Sin "perfecto, completado exitosamente". Datos:
archivos tocados, qué cambió, verificación curl/query con output real.

═══════════════════════════════════════════════════════════════════════════════
OUTPUT ESPERADO AL FINAL

Estado del repo:
  - Commits locales con fixes aplicados (push tuya pendiente)
  - 3 docs nuevos: POST_CUTOVER_AUDIT.md, POST_CUTOVER_PLAN.md, POST_CUTOVER_CLOSURE.md
  - 0 mismatches conocidos
  - app.skyfinanzas.com vivo conectado a backend Python
  - Listo para invitar 5-10 testers internos

Mensaje final al usuario:
  - Lista de fixes ejecutados (1 línea cada uno con commit hash)
  - Outputs clave de verificación
  - TODOs abiertos restantes (con prioridad y estimación)
  - Recomendación de próximo paso

═══════════════════════════════════════════════════════════════════════════════
ARRANQUE

1. cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL
2. git status, git log --oneline -10  (entender estado actual)
3. Leer los 13 docs de la "LECTURA OBLIGATORIA" en orden
4. Verificar que backend-python/.env existe y tiene credenciales reales
   (NO pegarlas en ningún lado, solo confirmar que están)
5. Arrancar Fase A — Auditoría completa

Andá.
```

---

## Cómo arrancar la sesión nueva

### Paso 1 — Verificar que `.env` está completo

```powershell
cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL\backend-python
Select-String -Path .env -Pattern "^(SUPABASE_URL|SUPABASE_ANON_KEY|SUPABASE_SERVICE_KEY|RAILWAY_TOKEN|BANK_ENCRYPTION_KEY|ANTHROPIC_API_KEY|GITHUB_PAT|AUDIT_LOG_SALT|DATABASE_URL)="
```

Tenés que ver las 9 líneas con valores (no vacíos). Si falta alguna, agregala desde Bitwarden antes de arrancar la sesión.

### Paso 2 — Abrir Claude Code nuevo

```powershell
# Sesión PowerShell nueva (limpia, sin contexto):
cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL
claude
# Una vez dentro:
/model
# Elegir Sonnet 4.6 + high effort (si la opción aparece)
```

### Paso 3 — Pegar el prompt

Copiá el bloque entre los ` ``` ` del archivo `backend-python/docs/SPRINT_POST_CUTOVER_PROMPT.md` (lo que está entre `═══ SPRINT POST-CUTOVER ═══` y `Andá.`).

Pegalo como primer mensaje en la sesión nueva.

### Paso 4 — Esperar Fase A

Claude Code va a leer todos los docs (15-30 min), explorar Railway via CLI/API, queryar Supabase, analizar frontend. Después te entrega `POST_CUTOVER_AUDIT.md`.

Pegalo acá conmigo cuando vuelva, y revisamos juntos antes de aprobar Fase B + C.
