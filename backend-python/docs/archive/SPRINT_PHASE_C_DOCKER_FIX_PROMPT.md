# Sprint Phase C — Fix de docker/api.Dockerfile (Prompt Sonnet)

> Pegar este texto entero en una sesión nueva de Claude Code Sonnet 4.6 high effort,
> working dir = `C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL`.
>
> **Contexto:** Sonnet ya ejecutó Fase A (diagnóstico) y Fase B (audit) en otra
> sesión. La causa raíz del 502 en `api-v2.skyfinanzas.com` está identificada y
> verificada. Este sprint es **solo Fase C: aplicar 1 fix quirúrgico al
> Dockerfile del API y crear el commit**.
>
> **IMPORTANTE — corrección al plan original:** Fase B propuso modificar
> `backend-python/railway.json` con `build.dockerfilePath: "Dockerfile"`. Eso
> se descartó porque `railway.json` es compartido entre `sky-api-python` y
> `sky-worker-python` (confirmado por el usuario en el incidente del
> healthcheckPath, commits 01d4788 y a1af010). Tocarlo aplicaría a ambos
> services y romperia al worker (el Dockerfile raíz lanza uvicorn, no arq, y
> sin Chromium). El fix correcto es **arreglar `docker/api.Dockerfile`
> directamente** — ese es el que el dashboard de Railway del service
> `sky-api-python` ya está usando.
>
> Modelo recomendado: `claude-sonnet-4-6` (high effort). Tarea pequeña pero
> crítica en producción.

---

## INSTRUCCIÓN PRIMARIA

Aplicá UN fix quirúrgico al archivo `backend-python/docker/api.Dockerfile` para
resolver el 502 Bad Gateway en `api-v2.skyfinanzas.com`. Trabajá directo en
`main`. Commit local. **NO pushees** — el usuario hace `git push origin main`
después de revisar el commit.

Antes de tocar una sola línea, **leé en orden**:

1. `CLAUDE.md` (raíz) — doctrina, mapa del repo, reglas operativas.
2. `backend-python/docker/api.Dockerfile` — el archivo que vamos a tocar.
3. `backend-python/docker/worker.Dockerfile` — solo para confirmar que NO se
   toca y entender por qué es diferente.
4. `backend-python/Dockerfile` — solo para entender que ese archivo existe pero
   NO se usa en prod actualmente (legado del commit 29b4623). NO se toca en
   este sprint.
5. `backend-python/railway.json` — solo para confirmar que está limpio (sin
   healthcheckPath, sin dockerfilePath). NO se toca.
6. `backend-python/pyproject.toml` — para confirmar que `pip install .` instala
   correctamente el package y sus dependencias.

Si algo en este prompt contradice esos archivos, **gana el archivo**. Si la
contradicción es importante, parás y avisás al usuario antes de tocar nada.

---

## DOCTRINA APLICABLE (de CLAUDE.md, no negociable)

1. **Trabajamos directo en `main`.** Sin worktrees, sin PRs en flujo normal.
2. **El usuario hace `git push`.** Vos solo commit local.
3. **Nunca `--force` push a main.**
4. **No tocar `backend/` (Node).**
5. **Mensajes de commit en español**, sin emojis, con `Co-Authored-By`.
6. **PowerShell por defecto** — Windows + miniconda.
7. **Ante ambigüedad: parar y preguntar.**

---

## DIAGNÓSTICO PREVIO (Fase A + Fase B, ya cerradas)

**Confirmado:**

1. **Container del API inicia exitosamente** — log "Application startup complete,
   port 8080" a las 07:52 UTC en un deploy reciente.
2. **Pero cero respuestas 200 en 8+ horas.** Health checks devuelven 502 desde el
   primer minuto.
3. **Railway está usando `backend-python/docker/api.Dockerfile`** para el service
   `sky-api-python` (configurado en su dashboard).
4. **Root cause documentado en `api.Dockerfile`:**
   - Línea 10-11: `RUN pip install $(python -c "...print(' '.join(deps))")` con
     command substitution. El output contiene strings como `asyncpg>=0.30`. Shell
     interpreta `>=` como redirección de I/O (`>` archivo `=0.30`) → instala
     paquetes sin version constraints, algunos fallan o quedan en versiones rotas.
   - Línea 17: `CMD ["sh", "-c", "uvicorn ..."]` — uvicorn es child de `sh`, no
     es PID 1, no recibe SIGTERM del orquestador, muere silenciosamente tras el
     startup.

**Variables de entorno en Railway:** todas correctas (`REDIS_URL`, `CORS_ORIGINS`,
`SENTRY_DSN`, `PROMETHEUS_SECRET`, `DATABASE_URL`, `BANK_ENCRYPTION_KEY`,
`NODE_ENV=production`). NO se tocan.

**CORS errors en browser = consecuencia.** Sin container vivo no hay response
para que `CORSMiddleware` aplique headers. Una vez el container sirve, CORS
funciona (verificado en `sky.api.main`).

**El worker es problema separado** — su healthcheck `/api/health` está
configurado en el dashboard del service `sky-worker-python` (NO en
`railway.json`). El usuario lo resuelve manualmente en Railway UI. NO es parte
de este sprint.

---

## PLAN DE FIX (Fase C — 1 cambio quirúrgico)

### Único cambio: `backend-python/docker/api.Dockerfile`

**Acción A — eliminar el bug del `pip install $(...)`** y usar la forma estándar
`pip install .` (idéntica a la del `worker.Dockerfile`, que sí funciona en prod).

**Acción B — agregar `exec` al CMD** para que uvicorn ocupe PID 1.

**Estado actual (verificá con `Read` antes de editar):**
```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --no-build-isolation \
    $(python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(' '.join(d['project']['dependencies']))")

COPY src/ ./src/

ENV PYTHONPATH=/app/src

CMD ["sh", "-c", "uvicorn sky.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

**Estado objetivo:**
```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app/src

CMD ["sh", "-c", "exec uvicorn sky.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

**Diferencias exactas (3 ediciones puntuales):**

1. **Borrar** las dos líneas viejas del pip install con command substitution:
   ```
   RUN pip install --no-cache-dir --no-build-isolation \
       $(python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(' '.join(d['project']['dependencies']))")
   ```

2. **Mover `COPY src/ ./src/`** arriba (antes del nuevo `pip install`) y
   **agregar** la línea limpia:
   ```
   RUN pip install --no-cache-dir .
   ```
   `pip install .` lee `pyproject.toml` directamente, sin pasar por shell
   expansion. Sin `>=` interpretado mal. Necesita `src/` ya copiado porque el
   package se llama `sky` y vive ahí.

3. **CMD:** agregar `exec ` antes de `uvicorn` (un solo cambio, mismo patrón
   que cualquier shell-form CMD donde necesitás variable expansion).

**Por qué `pip install .` y no `pip install -e .`:** en producción no hay
recarga en caliente, no hay tests, no hay dev tooling. `-e` agrega overhead y
deja site-packages en estado "editable". Para image de prod, `pip install .`
es lo estándar (es lo que ya usa `worker.Dockerfile`).

**Por qué NO copiamos `pyproject.toml` y `src/` por separado para mejor cache:**
sí lo hacemos. La secuencia es:
```
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
```
Esto invalida la cache solo cuando cambia `pyproject.toml` o el código. Para
optimización agresiva de cache podrías separar deps install vs code install,
pero **no es parte de este sprint** — es scope creep.

---

## PASOS EXACTOS

1. `Read` `backend-python/docker/api.Dockerfile` para confirmar estado actual
   coincide con "estado actual" arriba. Si NO coincide, **parás y reportás el
   desvío** — alguien más tocó el archivo.
2. `Read` `backend-python/docker/worker.Dockerfile` solo para confirmar que NO
   tiene el bug del command substitution (referencia de cómo se ve `pip
   install .` bien hecho). No se toca.
3. `Read` `backend-python/railway.json` solo para confirmar que está limpio
   (sin `healthcheckPath`, sin `dockerfilePath`). Si tiene cualquiera de esos
   campos, **parás y avisás** — significa que alguien re-introdujo el bug que
   `a1af010` arregló.
4. `Edit` `backend-python/docker/api.Dockerfile`:
   - Aplicar las 3 ediciones puntuales descritas arriba.
   - Usar 1 sola llamada `Write` (no múltiples `Edit`) — el archivo es chico
     (17 líneas) y los cambios afectan varias regiones; `Write` con el
     contenido completo del "estado objetivo" es más limpio y verificable.
5. **Validar Dockerfile sintácticamente** (sin docker daemon, solo grep básico):
   ```powershell
   Get-Content backend-python\docker\api.Dockerfile | Select-String "^(FROM|RUN|COPY|CMD|ENV|WORKDIR)"
   ```
   Esperado: 7 líneas (FROM, WORKDIR, RUN apt, COPY pyproject, COPY src, RUN pip,
   ENV, CMD). Si hay menos o más, revisar.
6. **Mostrar diff** al usuario para revisión visual:
   ```powershell
   git diff backend-python/docker/api.Dockerfile
   ```
7. **Stage solo ese archivo** (no `git add .`):
   ```powershell
   git add backend-python/docker/api.Dockerfile
   ```
8. **Crear commit** con este mensaje exacto (heredoc single-quoted, `'@` en
   columna 0):
   ```powershell
   git commit -m @'
   fix(docker): api.Dockerfile sin command-substitution y exec en CMD

   Fase C — fix del 502 Bad Gateway en api-v2.skyfinanzas.com.

   Root cause:
   - api.Dockerfile usaba pip install con command substitution
     ($(python -c ... print deps)). El output contenia strings como
     "asyncpg>=0.30"; shell interpreta ">=" como redireccion de I/O
     (> archivo "=0.30") en vez de version constraint. Resultado: deps
     instaladas sin version pin, algunas en versiones rotas, container
     crashea o queda inutil tras startup.
   - El CMD lanzaba uvicorn como child de sh; uvicorn no era PID 1, no
     recibia senales del orquestador, moria silenciosamente tras el
     "Application startup complete" sin servir requests.

   Fix:
   - Reemplazar el RUN pip install $(...) por "RUN pip install ." (misma
     forma que worker.Dockerfile, que funciona en prod). Mover COPY src/
     antes del install para que el package "sky" este disponible.
   - Agregar "exec" al CMD para que uvicorn ocupe PID 1.

   NO se toca railway.json (compartido entre api y worker, lo confirmado en
   commits 01d4788 / a1af010). NO se toca backend-python/Dockerfile raiz
   (legado de 29b4623, no usado por Railway). NO se tocan env vars.

   Resultado esperado tras push + redeploy (~3 min):
   - /api/health responde 200 con {"status":"ok","app":"sky-backend-python"}
   - CORS aplica Access-Control-Allow-Origin: https://app.skyfinanzas.com
   - Browser de https://app.skyfinanzas.com carga sin errores

   El healthcheck fallando en sky-worker-python es problema separado del
   dashboard de Railway (path /api/health configurado a un service que no
   expone HTTP); lo resuelve el usuario en Railway UI, no requiere commit.

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   '@
   ```
9. **NO pushear.** Devolvé al usuario:
   - Commit hash (`git log --oneline -1`)
   - Diff resumen (lineas añadidas/eliminadas)
   - Recordatorio: "vos hacés `git push origin main`".
   - Recordatorio: "en paralelo remové healthcheckPath del dashboard del
     service `sky-worker-python` en Railway UI — eso es independiente del
     push".

---

## GATES DE VERIFICACIÓN (pre-commit, OBLIGATORIOS)

Todos deben pasar antes del commit:

✅ **G1 — Sintaxis del Dockerfile:** la salida del `Select-String` del paso 5
   coincide con lo esperado (7 instrucciones).
✅ **G2 — Diff esperado:** `git diff --stat` muestra exactamente 1 archivo
   modificado (`backend-python/docker/api.Dockerfile`). Si hay más, parar — algo
   extra se modificó.
✅ **G3 — Sin scope creep:** `git status --short` solo muestra
   `M backend-python/docker/api.Dockerfile`. Nada más staged ni modificado.
✅ **G4 — railway.json intacto:** `git diff backend-python/railway.json` debe
   ser vacío. Confirmá que NO se introdujeron `healthcheckPath`,
   `dockerfilePath` ni nada nuevo ahí.
✅ **G5 — Dockerfile raíz intacto:** `git diff backend-python/Dockerfile` debe
   ser vacío. Ese archivo es legado del commit 29b4623 y no se toca acá.
✅ **G6 — Mensaje commit en español, sin emojis, con Co-Authored-By.**
✅ **G7 — Branch correcta:** `git branch --show-current` debe devolver `main`.

Si **cualquier gate falla:** NO hacés commit. Reportás al usuario qué falló y
parás. NO "arreglás" con cambios adicionales.

---

## DEFINITION OF DONE (post-push, lo verifica el usuario)

Después de que el usuario haga `git push origin main` y Railway redeploye
(~3 min):

1. **API responde 200:**
   ```powershell
   curl.exe https://api-v2.skyfinanzas.com/api/health
   # Esperado: {"status":"ok","app":"sky-backend-python"}
   ```
2. **Health profundo 200:**
   ```powershell
   curl.exe https://api-v2.skyfinanzas.com/api/health/deep
   # Esperado: {"status":"ok","db":"ok","redis":"ok","anthropic":"ok"}
   ```
3. **CORS preflight con header correcto:**
   ```powershell
   curl.exe -X OPTIONS https://api-v2.skyfinanzas.com/api/summary `
     -H "Origin: https://app.skyfinanzas.com" `
     -H "Access-Control-Request-Method: GET" `
     -i 2>&1 | Select-String "Access-Control-Allow"
   # Esperado: Access-Control-Allow-Origin: https://app.skyfinanzas.com
   ```
4. **Browser test:** https://app.skyfinanzas.com → Ctrl+F5 → login Supabase →
   ver bancos, summary, transactions cargando. Sin errores CORS en DevTools.
5. **Railway dashboard:**
   - `sky-api-python`: status verde en Deployments tab.
   - `sky-worker-python`: status verde DESPUÉS de que el usuario remueva el
     healthcheckPath del dashboard (acción manual, no relacionada con este
     commit).

Si algún criterio del API falla post-push: el usuario te avisa y abrimos
sprint nuevo de diagnóstico. NO improvisás más fixes a ciegas.

---

## QUÉ NO HACER (límites duros del sprint)

- ❌ **NO toques `backend-python/railway.json`.** Es compartido entre api y
  worker. Cualquier cambio impacta a ambos. Lección de los commits 01d4788 y
  a1af010.
- ❌ **NO toques `backend-python/Dockerfile`** (raíz). Es legado del commit
  29b4623, no usado por Railway. Otro sprint decidirá si se borra o se
  promueve a Dockerfile canónico.
- ❌ **NO toques `backend-python/docker/worker.Dockerfile`.** El worker está
  bien (logs lo confirman: Redis OK, Sentry OK, 8 funciones registradas).
- ❌ **NO toques `src/sky/api/main.py`** (CORS, lifespan, fail-fast). Está
  verificado y correcto.
- ❌ **NO toques env vars en Railway.** Ya están bien según Fase A.
- ❌ **NO toques `pyproject.toml`.** Las dependencias están bien — el problema
  era cómo el Dockerfile las instalaba, no cuáles son.
- ❌ **NO pushees.** El usuario hace `git push`.
- ❌ **NO crees archivos nuevos** (no docs, no scripts, no helpers).
- ❌ **NO refactorices** el Dockerfile aunque veas oportunidades (multi-stage,
  usuario non-root, etc.). Otro sprint.

---

## OUTPUT ESPERADO

Cuando termines, devolvé al usuario exactamente:

```
✅ Fase C cerrada — commit local listo

Commit: <hash> fix(docker): api.Dockerfile sin command-substitution y exec en CMD
Branch: main
Diff: 1 file changed, ~6 insertions(+), ~4 deletions(-)

Gates G1-G7: PASS

Próximos pasos:
1. Vos: git push origin main
2. Vos en paralelo: Railway UI → sky-worker-python → Settings → Deploy →
   Healthcheck Path: dejar vacío, Save. (Esto es manual, no requiere commit.)
3. Esperás ~3 min, corrés los 5 checks del DOD.
4. Si algún check del API falla: abrimos sprint nuevo, no improvisamos.
```

Sin más texto. Sin disculpas. Sin "espero que esto resuelva". Reporte ejecutivo.

---

**Ejecutor:** Sonnet 4.6 (high effort)
**Sprint:** Fase C — Docker fix (corregido: arreglar api.Dockerfile en vez de
railway.json)
**Doctrina:** CLAUDE.md (raíz del repo)
**Urgencia:** bloqueador prod, 502 en API hace 8+ horas
