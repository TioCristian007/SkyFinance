# Post-Cutover Debug Audit — 2026-05-19

## Hallazgo principal: 502 en TODOS los endpoints

```
GET https://api-v2.skyfinanzas.com/api/health       → 502 "Application failed to respond"
GET https://api-v2.skyfinanzas.com/api/banking/banks → 502 "Application failed to respond"
```

El 502 es de Railway reverse proxy y significa: **el container arranca pero uvicorn no responde**.
Esto prueba que la app crashea DURANTE el lifespan startup, antes de que cualquier handler se registre.

---

## Bug 1: Python API no responde (502 en todo)

### Endpoint
`https://api-v2.skyfinanzas.com/api/*` — todos

### Status code
502 (Railway: "Application failed to respond")

### Causa raíz identificada: H7 parcial + nueva

El lifespan en `api/main.py:65` llama `build_router(include_browser_sources=False)`.
`build_router` en `ingestion/bootstrap.py:35` ejecuta:

```python
redis = Redis.from_url(settings.redis_url, decode_responses=False)
await redis.ping()   # ← CRASH AQUÍ
```

`settings.redis_url` tiene default `"redis://localhost:6379"`. En un container de Railway,
localhost:6379 no tiene nada → la conexión falla → excepción no capturada → lifespan nunca
hace `yield` → uvicorn sale → Railway devuelve 502.

Como el lifespan crashea antes de yieldar, **NINGÚN** endpoint responde, ni siquiera
`/api/health` (que no usa Redis). Esto explica ambos bugs visibles.

### Evidencia adicional
- `Procfile` ausente en `backend-python/` → Railway usa Nixpacks y puede que el start command
  sea incorrecto (detecta uvicorn pero no sabe que el módulo es `sky.api.main:app`).
- `docker/api.Dockerfile` está en ruta no estándar y no está referenciado en `railway.json`.
  Si Railway usa Nixpacks en vez del Dockerfile, el container podría no arrancar correctamente.

### Fix propuesto (Fix A)
Archivo: `backend-python/src/sky/api/main.py` — lifespan

Envolver `build_router()` y `create_pool()` en try/except. Si Redis no está disponible,
la API arranca en modo degradado: `app.state.redis = None`, `app.state.arq_pool = None`.
Endpoints básicos (health, banks, chat, summary) funcionan. Sync endpoints retornan 503 claro.

### Fix propuesto (Fix B)  
Archivo nuevo: `backend-python/Procfile`

```
web: uvicorn sky.api.main:app --host 0.0.0.0 --port $PORT
```

Garantiza que Nixpacks use el start command correcto independientemente de la configuración
de Railway (Dockerfile vs Nixpacks).

### Verificación post-fix
```powershell
curl.exe https://api-v2.skyfinanzas.com/api/health
# Debe retornar: {"status":"ok","app":"sky-backend-python"}
curl.exe https://api-v2.skyfinanzas.com/api/banking/banks
# Debe retornar: {"banks":[...8 bancos...]}
```

### Acción requerida del usuario (FUERA DEL CÓDIGO)
En Railway dashboard → servicio `sky-api-python` → Variables:
- Verificar que `REDIS_URL` esté seteada y apunte al plugin Redis de Railway
  (algo como `redis://default:password@monorail.proxy.rlwy.net:PORT`)
- Si NO está seteada: conectar el plugin Redis de Railway al servicio

**Nota**: El Fix A (modo degradado) permite que la API funcione aunque Redis no esté.
El sync bancario seguirá degradado hasta que REDIS_URL esté correcta. Para pilotos
iniciales (solo visualizar bancos y chatear con Mr. Money) alcanza con Fix A + Fix B.

---

## Bug 2: Mr. Money — shape mismatch de respuesta

### Contexto
Este bug se manifiesta DESPUÉS de que Fix A resuelva el 502. Con el 502, el catch en
`send()` de Sky.jsx se activa → setApiErr(true) → "⚠ Sin conexión". Una vez que el
API responda, el 502 ya no activa el catch, pero habría una respuesta silenciosa vacía.

### Endpoint llamado por frontend
`POST /api/chat` con `{message, history}`

### Shape recibido (Python)
```json
{"type": "text", "text": "Hola 👋 Soy Mr. Money..."}
```

### Shape esperado por Sky.jsx (basado en Node aiService.js)
```json
{
  "reply": "texto del mensaje",
  "proposals": [],
  "navigations": []
}
```

### Diff exacto
| Campo | Node (esperado) | Python actual |
|-------|-----------------|---------------|
| Texto de respuesta | `result.reply` | `result.text` (no leído) |
| Propuestas | `result.proposals[]` | tipo `ProposeChallenge` separado |
| Navegación | `result.navigations[0].simulation_type` | tipo `NavigationResponse` separado |

Sky.jsx línea 445: `addBotMsg(result.reply)` → `result.reply` es `undefined` → mensaje bot vacío.
No activa el catch (addBotMsg(undefined) no lanza). El banner "⚠ Sin conexión" viene del 502,
no de este mismatch.

### Causa raíz identificada: H6
Python devuelve discriminated union `{type, text}` en lugar de `{reply, proposals, navigations}`.

### Fix propuesto (Fix C)
Archivo: `backend-python/src/sky/api/chat.py`
Archivo: `backend-python/src/sky/api/schemas/chat.py`

Agregar `ChatUnifiedResponse(BaseModel)`:
```python
class ChatUnifiedResponse(BaseModel):
    reply: str = ""
    proposals: list[dict[str, Any]] = []
    navigations: list[dict[str, Any]] = []
```

Modificar `chat_endpoint` para convertir la respuesta interna al formato unificado antes de
retornar. Para `ChatTextResponse` → `reply = response.text`. Para `ProposeChallenge` →
`reply = "Tengo una propuesta para ti:" + proposals[...]`. Para `NavigationResponse` →
`reply = response.label`.

### Verificación post-fix
```powershell
curl.exe -X POST https://api-v2.skyfinanzas.com/api/chat `
  -H "Authorization: Bearer $env:TEST_JWT" `
  -H "Content-Type: application/json" `
  -d '{"message":"hola"}'
# Debe retornar: {"reply":"Hola 👋 Soy Mr. Money...","proposals":[],"navigations":[]}
```

---

## Bug 3: health.py — NullPointerError en modo degradado

### Contexto
Con Fix A (modo degradado), `request.app.state.redis = None`. El endpoint
`/api/health/deep` llama `await check_redis(request.app.state.redis)` con `None` → crash.

### Fix propuesto (Fix D)
Archivo: `backend-python/src/sky/api/routers/health.py`

En `health_deep`: `redis_client = getattr(request.app.state, "redis", None)`.
Si `redis_client is None`: reportar `redis = "down"` sin llamar a `check_redis()`.

---

## Bug 4: banking.py — AttributeError en sync cuando arq_pool=None

### Contexto
Con Fix A (modo degradado), `request.app.state.arq_pool = None`. Los endpoints
`POST /banking/sync/*` y `POST /banking/accounts` intentan `arq_pool.enqueue_job(...)` → crash.

### Fix propuesto (Fix E)
Archivo: `backend-python/src/sky/api/routers/banking.py`

En `sync_bank_account_endpoint`, `sync_all_endpoint`, y `connect_account`:
```python
arq_pool = request.app.state.arq_pool
if arq_pool is None:
    raise HTTPException(status_code=503, detail="Servicio de sync no disponible. Verifica configuración de Redis.")
```

---

## Resumen de fixes

| Fix | Archivo | Prioridad | Tiempo |
|-----|---------|-----------|--------|
| A — lifespan Redis tolerante | `api/main.py` | CRÍTICO | 10 min |
| B — Procfile para Nixpacks | `Procfile` (nuevo) | CRÍTICO | 1 min |
| C — chat unified response | `api/chat.py`, `schemas/chat.py` | CRÍTICO | 15 min |
| D — health degraded mode | `api/routers/health.py` | IMPORTANTE | 5 min |
| E — banking null arq_pool | `api/routers/banking.py` | IMPORTANTE | 5 min |

**Total estimado**: 36 min implementación + 20 min testing + deploy Railway ~5 min

## Acción manual del usuario (prereq)

**ANTES** de pushear el fix, verificar en Railway dashboard:
1. Servicio `sky-api-python` → Variables → confirmar `REDIS_URL` existe y tiene valor
   (algo como `redis://default:password@...railway.internal:PORT`)
2. Si no existe: conectar plugin Redis al servicio desde Railway dashboard
3. Si existe pero apunta a localhost: actualizar al URL real del plugin

**DESPUÉS** de pushear:
1. Ctrl+F5 en `app.skyfinanzas.com`
2. "Conectar banco" → debe ver Banco de Chile (verde/disponible) + BCI, Falabella, etc. (próximamente)
3. Mr. Money → escribir "hola" → debe ver respuesta sin banner "⚠ Sin conexión"

## Definition of Done

- [ ] `curl https://api-v2.skyfinanzas.com/api/health` → `{"status":"ok",...}`
- [ ] `curl https://api-v2.skyfinanzas.com/api/banking/banks` → JSON con 8 bancos
- [ ] `curl -X POST /api/chat -H "Auth..." {"message":"hola"}` → `{"reply":"Hola 👋...",...}`
- [ ] Tests pytest: todos pasan (sin regresiones)
- [ ] App: BChile aparece como conectar, Mr. Money responde
