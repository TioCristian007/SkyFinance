# SPRINT — Scrapers conectados de verdad (P0)

> **Audiencia**: Claude (Sonnet, max effort) en sesión nueva, sin contexto previo.
> **Modo**: trabajar directo en `main`, sin worktrees, sin PRs.
> **Push**: lo hace el usuario.
> **Deploy**: Railway. Worker (`sky-worker`) y API (`sky-api-python`) son servicios separados — un fix en el worker requiere redeploy del worker, no de la API.
> **Idioma de commits**: español, `Co-Authored-By: Claude`.
> **Cuenta Railway operativa**: `cristovasq464@gmail.com` (el repo y el proyecto están bajo esa cuenta).

---

## 0. Contexto

Sky migró de Node.js a Python (FastAPI + ARQ + Playwright), cutover completado mayo 2026. Producción viva en `app.skyfinanzas.com` / `api.skyfinanzas.com`. Hay una reunión con BCI (Gerente de Innovación + Product Owner Open Banking) la semana del 26-28 mayo 2026. **La app tiene que funcionar impecable para esa reunión** — este sprint es lo que lo asegura.

Síntomas reportados por el usuario tras conectar su cuenta de Banco de Chile en producción:

1. Las transacciones recién sincronizadas se quedan con descripción **"Procesando..."** indefinidamente.
2. Solo se ven **salidas (gastos en rojo)** — ninguna entrada en verde, pese a que el usuario sí tiene ingresos.
3. En el selector de bancos se ven **Falabella** (scraper es skeleton, no real) y otros en "Próximamente"; **BCI no aparece** como conectable pese a que su scraper funcionaba.
4. La app va **muy lenta**.

---

## 0.5 Pre-flight

```powershell
cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL
git status                    # On branch main, limpio
git log --oneline -5

# Backend prod responde
Invoke-RestMethod -Uri "https://api.skyfinanzas.com/api/health"
# Esperado: { status: "ok", app: "sky-backend-python" }

# Frontend apunta al backend correcto (NO api-v2)
# Abrir app.skyfinanzas.com, F12 Network, confirmar requests a api.skyfinanzas.com
```

Si algo falla, parar y avisar.

---

## 1. Diagnóstico ya hecho (validar, no re-investigar desde cero)

### 1.1 — "Procesando..." eterno + "solo salidas" = MISMO bug (cola ARQ mal nombrada)

**Causa raíz**: el pool de ARQ del worker se crea sin `default_queue_name`, así que encola jobs en `arq:queue`, pero el worker consume de `sky:default`. El `categorize_pending_job` cae en una cola que nadie escucha y nunca se ejecuta.

Evidencia:

- API encola con cola correcta — `backend-python/src/sky/api/main.py:70`:
  ```python
  app.state.arq_pool = await create_pool(..., default_queue_name="sky:default")
  ```
- Worker encola SIN cola — `backend-python/src/sky/worker/main.py:47`:
  ```python
  ctx["arq_pool"] = await create_pool(RedisSettings.from_dsn(settings.redis_url))
  ```
- Worker consume de `sky:default` — `backend-python/src/sky/worker/main.py:88`:
  ```python
  queue_name = "sky:default"
  ```
- `categorize_pending_job` se encola desde el worker — `backend-python/src/sky/worker/banking_sync.py:165`:
  ```python
  if inserted > 0:
      await arq_pool.enqueue_job("categorize_pending_job")
  ```

**Cadena del fallo**:
1. Sync inserta transacciones con `description='Procesando...'`, `category='other'`, `categorization_status='pending'` (`banking_sync.py:217`).
2. Encola `categorize_pending_job` → cae en `arq:queue` (cola equivocada).
3. Worker escucha `sky:default` → nunca lo corre.
4. Transacciones quedan `pending` para siempre → "Procesando..." eterno.
5. `category` queda `'other'`. Frontend pinta verde solo si `category === "income"` (`frontend/src/Sky.jsx:283`) → todo se ve rojo → "solo salidas".

**También rompe sync-all** (`jobs/sync.py:62` encola por la misma vía).

### 1.2 — Income display frágil (segundo orden, pero real)

Aun con la categorización corriendo, el display de ingreso/gasto depende de `category === "income"`, y la categorización solo asigna `"income"` con un regex estrecho de descripción (`categorizer.py:70-72`: `abono|remuner|sueldo|salario|honorario|liquidaci`...). Un ingreso con glosa que no matchee (ej. "TRANSFERENCIA DE JUAN") queda en otra categoría → se ve rojo aunque el monto sea positivo.

El resumen financiero (`finance.py:57`) sí usa el signo (`if amount > 0: income += amount`). Hay **dos definiciones de "ingreso" que se contradicen** entre el resumen (signo) y el display de transacciones (categoría).

### 1.3 — Falabella visible, BCI ausente

`SUPPORTED_BANKS` (`backend-python/src/sky/ingestion/sources/__init__.py`):
- `bchile`: `active`
- `falabella`: `pending` (skeleton, no real)
- `bci`: `pending`
- resto: `pending`

El usuario aprobó: **dejar solo BChile y BCI visibles**. Falabella debe salir del listado. BCI debe pasar a `active` SI su scraper funciona en producción.

### 1.4 — BCI scraper `ERR_NAME_NOT_RESOLVED`

Corriendo `scripts/test_bci_scraper.py` localmente, falla con `net::ERR_NAME_NOT_RESOLVED` en `portalpersonas.bci.cl`. El usuario afirma que el scraper **funcionaba** (scrapeaba balance y movimientos). Sospecha principal: **DNS local de la máquina Windows del usuario**, no el código. Hay que validar en producción (worker de Railway), no localmente.

---

## 2. Plan de fix

Orden estricto. Cada paso con gate. Confirmar con el usuario antes de cada commit.

### Paso 1 — Fix cola ARQ (EL fix crítico, una línea)

**Archivo**: `backend-python/src/sky/worker/main.py:47`

```diff
-    ctx["arq_pool"] = await create_pool(RedisSettings.from_dsn(settings.redis_url))
+    ctx["arq_pool"] = await create_pool(
+        RedisSettings.from_dsn(settings.redis_url),
+        default_queue_name="sky:default",
+    )
```

**Gate**:
- `ruff check src/sky/worker/main.py` → 0 errores.
- `mypy src/sky/worker/main.py` → 0 errores.
- `pytest tests/ -q` → verde.

**Verificación post-deploy** (requiere redeploy del worker en Railway):
1. Usuario hace push → Railway redeploya `sky-worker`.
2. Usuario dispara un sync de Banco de Chile desde la app (o reconecta).
3. Esperar ~2-3 min.
4. En la app, las transacciones deben dejar de decir "Procesando..." y mostrar descripción real + categoría.
5. Logs del worker deben mostrar `categorize_batch_done processed=N`.

**Verificación en logs**:
```powershell
railway logs --service "sky-worker" | Select-String "categorize_batch_done"
```

**Commit**:
```
fix(worker): arq_pool del worker usa default_queue_name=sky:default — categorize_pending_job nunca corría
```

**IMPORTANTE**: Las transacciones ya insertadas con `categorization_status='pending'` necesitan re-encolar. Después del deploy, el `categorize_pending_job` toma cualquier `pending`, así que basta con dispararlo una vez. Si no se dispara solo, el usuario puede hacer un sync nuevo o se puede encolar manualmente. Documentar cómo en el reporte.

### Paso 2 — Income display robusto (frontend usa signo, no categoría)

**Solo después de validar Paso 1.** Primero confirmar con datos reales que el scraper guarda los signos correctos:

```sql
-- Query de diagnóstico (correr en Supabase SQL editor o psql)
SELECT amount, category, description, categorization_status
  FROM public.transactions
 WHERE user_id = '<uuid del usuario>'
 ORDER BY date DESC LIMIT 20;
```

- Si los gastos tienen `amount < 0` y los ingresos `amount > 0` → signos correctos → fix es frontend.
- Si todos tienen el mismo signo → bug en el scraper (`bchile_scraper.py:600`, el check `tipo == "cargo"`). Investigar el payload real de `getCartola` (hay logs temporales en `bchile_scraper.py:482,499`).

**Fix frontend** (asumiendo signos correctos) — `frontend/src/Sky.jsx`:

Buscar TODOS los lugares con `tx.category === "income"` (al menos línea 283, posiblemente más con grep) y cambiar la lógica de display de ingreso/gasto para que use el signo del monto:

```diff
-  const isIncome = tx.category === "income";
+  const isIncome = tx.amount > 0;
```

Esto alinea el display con el cálculo del resumen (`finance.py:57`). La categoría `"income"` sigue existiendo para Mr. Money y analytics; solo el indicador visual verde/rojo pasa a depender del signo.

**Gate**: `npm run build` exit 0. Verificar en la app que ingresos (monto positivo) se ven verdes.

**Commit**:
```
fix(frontend): display ingreso/gasto usa signo del monto, no categoría — ingresos sin glosa estándar ya no se ven como gasto
```

### Paso 3 — Limpiar listado de bancos (solo BChile + BCI)

**Archivo**: `backend-python/src/sky/ingestion/sources/__init__.py`

Remover del listado `SUPPORTED_BANKS` los bancos que no se quieren mostrar (Falabella, Santander, Banco Estado, Itaú, Scotiabank, Mercado Pago), o cambiarlos para que el frontend no los liste. El usuario aprobó dejar **solo BChile y BCI**.

Decisión de implementación: lo más limpio es dejar solo bchile y bci en `SUPPORTED_BANKS`. Pero verificar que ningún otro módulo dependa de las entradas removidas (grep `SUPPORTED_BANKS`, `_BANK_META`). Si hay dependencias, en vez de remover, agregar un campo `visible: bool` y filtrar en el endpoint `/api/banking/banks`.

**Gate**: `pytest tests/ -q` verde. `/api/banking/banks` devuelve solo bchile + bci.

**Commit**:
```
fix(banking): SUPPORTED_BANKS solo expone BChile y BCI — quitar bancos no operativos del onboarding
```

### Paso 4 — BCI: validar en producción y activar

**NO marcar BCI como `active` sin validar que el scraper funciona en producción.**

1. Triage del `ERR_NAME_NOT_RESOLVED` (probablemente DNS local del usuario, no prod). Pedir al usuario que corra:
   ```powershell
   nslookup portalpersonas.bci.cl
   nslookup apilocal.bci.cl
   ```
   Si no resuelven en su máquina pero el dominio existe → es DNS local. El worker de Railway probablemente sí resuelve.

2. **Validar en producción**: pedir al usuario que conecte su cuenta BCI en la app (con BCI en `active` temporalmente, o vía un sync de prueba) y observar logs del worker:
   ```powershell
   railway logs --service "sky-worker" | Select-String "bci"
   ```
   - Si el sync de BCI completa y trae balance + movimientos → marcar `bci` como `active` en `SUPPORTED_BANKS`.
   - Si falla en prod también → dejar `pending` y documentar por qué.

3. Si se activa: verificar end-to-end (conectar, sync, ver transacciones categorizadas).

**Gate**: decisión documentada (activado / no activado) con evidencia de logs.

**Commit (si se activa)**:
```
feat(banking): activar BCI en SUPPORTED_BANKS — scraper validado en producción
```

### Paso 5 — Performance (profiling, no optimización ciega)

La app va lenta. Antes de optimizar, medir dónde:

1. **Cold start de Railway**: ¿el servicio se duerme? Revisar plan de Railway (si es Hobby, puede dormir). Medir tiempo de primera respuesta tras inactividad.
2. **Queries lentas**: revisar `/api/summary`, `/api/transactions`, `/api/banking/accounts` con timing:
   ```powershell
   Measure-Command { Invoke-RestMethod -Uri "https://api.skyfinanzas.com/api/health" }
   ```
   (con JWT para los endpoints privados)
3. **Frontend re-renders**: `Sky.jsx` es un god-component (1600+ LOC, deuda P1-1). Puede estar re-renderizando de más. Revisar con React DevTools Profiler.
4. **Sync bloqueante**: el polling de `BankConnect` cada 5s puede recargar todo. Revisar.

Reportar hallazgos. NO optimizar sin medir primero. Si la lentitud es cold-start de Railway, la solución es el plan/healthcheck, no el código.

**Gate**: reporte de profiling con el cuello de botella identificado. Fixes de performance van como sprint separado salvo que sean triviales.

### Paso 6 — Reporte final

```
SPRINT SCRAPERS P0 — REPORTE

Paso 1 (cola ARQ): ✅/❌ · commit <sha> · categorize corre = sí/no
Paso 2 (income display): ✅/❌ · signos en DB = correctos/incorrectos · commit <sha>
Paso 3 (listado bancos): ✅/❌ · commit <sha>
Paso 4 (BCI): activado = sí/no · razón
Paso 5 (performance): cuello de botella = <hallazgo>

Pendiente / sprint siguiente:
- <ítem>
```

---

## 3. Lo que NO se toca

- **`backend/` (Node.js)** — referencia post-cutover, no editar.
- **`core/config.py`** — no flexibilizar parsing del `.env`.
- **Schema Supabase / migraciones** — no aplicar migraciones nuevas sin avisar.
- **`bchile_scraper.py`** — solo tocar si Paso 2 revela bug de signos. No "mejorar" gratis.
- **Refactor de `Sky.jsx`** (P1-1) — no abordar el refactor masivo en este sprint; solo el cambio puntual del display.
- **Logs temporales** en `bchile_scraper.py:482,499` — dejarlos hasta confirmar que el scraper funciona; removerlos al final si todo OK.

---

## 4. Reglas operativas

- **PowerShell** (Windows). `$env:VAR="..."`, `;` no `&&`.
- **Confirmar antes de cada commit.**
- **Plan-first** dentro de cada paso: leer el archivo antes de editar.
- **Worker y API son deploys separados** — un fix de worker necesita redeploy de `sky-worker`.
- **Nunca `--force` push.** Trabajar en `main`. El usuario pushea.
- Deuda fuera de scope → documentar en `docs/REMEDIATION_P0_P3.md`, no arreglar inline.

---

_Redactado 2026-05-21 · sprint P0 para dejar los scrapers conectados end-to-end antes de la reunión BCI._
