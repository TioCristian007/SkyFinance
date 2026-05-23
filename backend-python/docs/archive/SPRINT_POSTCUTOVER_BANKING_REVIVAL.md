# SPRINT — Reanimar conexión bancaria post-cutover Python

> **Audiencia**: Claude (Sonnet, max effort) en sesión nueva, sin contexto previo.
> **Modo**: trabajar directo en `main`, sin worktrees, sin PRs.
> **Push**: lo hace el usuario.
> **Idioma de commits**: español, `Co-Authored-By: Claude`.

---

## 0. Contexto rápido

- Sky migró de `backend/` (Node.js) a `backend-python/` (FastAPI + ARQ + Playwright). Cutover ya ocurrió: `api.skyfinanzas.com` apunta al backend Python.
- Frontend (`frontend/`, React 18) no fue tocado en el cutover y **dejó de mostrar la lista de bancos** cuando el usuario hace click en *"+ Conectar otro banco"*.
- Scripts de prueba de scrapers (`scripts/test_*.py`) explotaban al arrancar con `python-dotenv could not parse statement starting at line 62`. **Ya arreglado por el usuario antes de iniciar este sprint** — verificar en pre-flight.
- El scraper de **BCI** falla con `net::ERR_NAME_NOT_RESOLVED` al navegar a `https://portalpersonas.bci.cl/mibci/login`. BChile sí funciona y extrae datos.

**Producción está parcialmente caída para onboarding bancario**. No hay branches, trabajamos en `main`. Lee `CLAUDE.md` antes de tocar nada.

---

## 0.5 Pre-flight (5 min, antes de cualquier edición)

Corre todo esto. Si algo falla, **para y avisa al usuario antes de avanzar**.

```powershell
# Ubicación correcta
cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL
git status                    # debe ser "On branch main", working tree clean
git log --oneline -5

# .env del backend Python — debe parsear sin error
cd backend-python
.venv\Scripts\activate
python -c "from sky.core.config import settings; print('config_ok', settings.node_env)"
# Esperado: "config_ok development" o "config_ok production". Si tira DotEnvError → PARA.

# Backend prod arriba
Invoke-RestMethod -Uri "https://api.skyfinanzas.com/api/health" -Method Get
# Esperado: { status: "ok", app: "sky-backend-python" }

# Frontend buildea limpio (gate de paso 1 después)
cd ..\frontend
npm run build 2>&1 | Select-Object -Last 5
# Esperado: termina sin errores
```

Si **cualquiera** falla, no avanzar. Reportar al usuario qué pasó.

---

## 1. Síntomas verificables

| Síntoma | Dónde se observa | Severidad |
|---|---|---|
| Al pulsar "+ Conectar otro banco" en `app.skyfinanzas.com` no aparecen logos de bancos | Browser, vista `BankConnect → ConnectForm` | **P0** — bloquea onboarding |
| `scripts/test_bci_scraper.py` falla con `ERR_NAME_NOT_RESOLVED` en `portalpersonas.bci.cl` | Terminal local Windows | **P2** — investigar antes de fixear |
| Docstrings de tests manuales emiten `SyntaxWarning: invalid escape sequence '\S'` | Cualquier ejecución de `scripts/test_*.py` | **P3** — cosmético |

---

## 2. Diagnóstico (ya hecho — valida, no re-investigues)

### 2.1 — Lista de bancos vacía (P0) · causa raíz

`frontend/src/components/BankConnect.jsx:390-404`:

```js
const [accRes, banksRes] = await Promise.all([
  api.getBankAccounts(),       // requiere JWT — puede 401/500/503
  api.getSupportedBanks(),     // público, devuelve SUPPORTED_BANKS
]);
setAccounts(...); setTotalBalance(...); setBanks(banksRes.banks || []);
```

`Promise.all` rechaza entera si cualquiera rechaza. Si `/api/banking/accounts` falla por **cualquier** motivo, el `catch` se traga el error, `setBanks` jamás corre, `banks` queda `[]`, y `ConnectForm` no renderiza botones de banco. El usuario ve solo "Cancelar". Es exactamente lo reportado.

Backend está OK: `GET /api/banking/banks` en `backend-python/src/sky/api/routers/banking.py:30-33` devuelve `{banks: SUPPORTED_BANKS}` sin auth. Confirmable con `curl https://api.skyfinanzas.com/api/banking/banks`.

El fix de §3 Paso 1 (allSettled) **enmascara** el síntoma. La causa secundaria — por qué `/accounts` falla — se ataca en §3 Pasos 2-3.

### 2.2 — BCI `ERR_NAME_NOT_RESOLVED` (P2) · hipótesis

URL en `backend-python/src/sky/ingestion/sources/bci_direct.py:57`:
```python
BCI_BANK_URL = "https://portalpersonas.bci.cl/mibci/login"
```

`ERR_NAME_NOT_RESOLVED` = Chromium no pudo resolver el DNS. Tres hipótesis ordenadas por probabilidad:

1. **DNS local del Windows del usuario**. BChile resuelve, BCI no → discriminado por dominio. Posibles: antivirus/firewall, hosts file, DNS del ISP, VPN.
2. **Chromium de Playwright con resolver roto**. Reinstalar con `playwright install chromium --force`.
3. **BCI cambió el dominio**. Improbable (operación masiva, no haría rename silencioso). Solo válido si (1) y (2) descartados.

Triage concreto en §3 Paso 4. **No modifiques `BCI_BANK_URL` hasta confirmar la causa**.

---

## 3. Plan de fix

Ejecutar en orden. Cada paso tiene gate. No avanzar sin confirmación.

### Paso 1 — Frontend: `Promise.allSettled` en `loadAccounts`

**Archivo**: `frontend/src/components/BankConnect.jsx`

```diff
   const loadAccounts = async () => {
     try {
-      const [accRes, banksRes] = await Promise.all([
+      // allSettled: la lista de bancos NO debe depender de /accounts.
+      // Si /accounts falla (401, 503, DB), igual queremos que el usuario
+      // pueda abrir "Conectar banco" y ver los logos.
+      const [accRes, banksRes] = await Promise.allSettled([
         api.getBankAccounts(),
         api.getSupportedBanks(),
       ]);
-      setAccounts(accRes.accounts || []);
-      setTotalBalance(accRes.totalBalance || 0);
-      setBanks(banksRes.banks || []);
+
+      if (accRes.status === "fulfilled") {
+        setAccounts(accRes.value.accounts || []);
+        setTotalBalance(accRes.value.totalBalance || 0);
+      } else {
+        console.error("[BankConnect] getBankAccounts falló:", accRes.reason?.message);
+        setAccounts([]); setTotalBalance(0);
+      }
+
+      if (banksRes.status === "fulfilled") {
+        setBanks(banksRes.value.banks || []);
+      } else {
+        console.error("[BankConnect] getSupportedBanks falló:", banksRes.reason?.message);
+        setBanks([]);
+      }
     } catch (e) {
       console.error("[BankConnect] loadAccounts:", e.message);
     } finally {
       setLoading(false);
     }
   };
```

**Acceptance**:
- `npm run build` exit 0.
- Tras deploy del frontend: abrir `app.skyfinanzas.com`, ir a vista bancos, pulsar "+ Conectar otro banco". DevTools → Network: dos requests, `/banking/accounts` y `/banking/banks`. Aunque `/accounts` retorne 401/500, la lista de logos aparece.

**Commit**:
```
fix(frontend): BankConnect usa Promise.allSettled — la lista de bancos no se rompe si /accounts falla
```

### Paso 2 — Verificar endpoints reales en prod con JWT

Sin tocar código. **Pídele al usuario un JWT válido de Supabase** (desde `localStorage.getItem('sb-<proj>-auth-token')` en su navegador, o `getSession()` en la consola). No loguearlo en archivos.

```powershell
$jwt  = "<jwt aquí>"
$base = "https://api.skyfinanzas.com/api"

Invoke-RestMethod -Uri "$base/health"          -Method Get
Invoke-RestMethod -Uri "$base/banking/banks"   -Method Get
Invoke-RestMethod -Uri "$base/banking/accounts" -Method Get -Headers @{ Authorization = "Bearer $jwt" }
```

**Acceptance** (los 3 deben pasar):
- `/health` → 200, `{status:"ok"}`.
- `/banking/banks` → 200, `{banks:[...]}` con 8 entradas.
- `/banking/accounts` → 200, `{accounts:[...], totalBalance:N}`.

**Si `/banking/accounts` devuelve:**
- **401** → JWT no se está verificando. Ir a Paso 3.
- **500** → DB. `railway logs --service api` para el stack. Reportar al usuario.
- **503** → Redis/ARQ. Revisar `app.state.arq_pool` y `app.state.redis` en `lifespan`. Reportar.
- **CORS** → revisar `CORS_ORIGINS` en Railway env vars del servicio API.

### Paso 3 — Solo si Paso 2 dio 401: arreglar verificación JWT

Lee primero en este orden:
1. `backend-python/src/sky/api/middleware/jwt_auth.py`
2. `backend-python/src/sky/api/middleware/jwt_context.py`
3. `backend-python/src/sky/core/config.py` — ver qué env var espera para el secret.

Verifica:
- `Settings` tiene un campo para el secret de Supabase (probable `supabase_jwt_secret: str`).
- Está poblado en Railway env vars del servicio API.
- `jwt.decode(token, secret, algorithms=[...], audience="authenticated")` usa la signing key correcta (NO la anon, NO la service).
- Si Supabase está en RS256 + JWKS, adaptar el flujo (descargar JWKS, cachear, validar `kid`).

Cierra **P0-1** del v5. Documentar en `docs/REMEDIATION_P0_P3.md` con fecha y commit.

**Acceptance**: Paso 2 reintentado → `/banking/accounts` → 200.

**Commit**:
```
fix(api): verificación JWT real con signing key de Supabase — cierra P0-1
```

### Paso 4 — Triage BCI DNS

**Antes de tocar `bci_direct.py`**, corre este bloque en PowerShell del usuario y reporta el output:

```powershell
Write-Host "=== 1. DNS del sistema ===" -ForegroundColor Cyan
nslookup portalpersonas.bci.cl
nslookup apilocal.bci.cl

Write-Host "`n=== 2. HTTP HEAD ===" -ForegroundColor Cyan
try {
  $r = Invoke-WebRequest -Uri "https://portalpersonas.bci.cl/mibci/login" `
        -Method Head -UseBasicParsing -MaximumRedirection 0 `
        -ErrorAction SilentlyContinue
  Write-Host "Status: $($r.StatusCode)"
} catch { Write-Host "FAIL: $($_.Exception.Message)" -ForegroundColor Red }

Write-Host "`n=== 3. hosts file ===" -ForegroundColor Cyan
$h = Select-String -Path "$env:windir\System32\drivers\etc\hosts" -Pattern "bci" -ErrorAction SilentlyContinue
if ($h) { $h } else { Write-Host "(sin entradas para bci)" }

Write-Host "`n=== 4. Proxy env ===" -ForegroundColor Cyan
Write-Host "HTTP_PROXY  = $env:HTTP_PROXY"
Write-Host "HTTPS_PROXY = $env:HTTPS_PROXY"

Write-Host "`n=== 5. Chromium de Playwright ===" -ForegroundColor Cyan
cd C:\Users\crist\OneDrive\Documentos\SkyFinance\sky_OFFICIAL\backend-python
.venv\Scripts\python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().__enter__(); print(p.chromium.executable_path)"
```

**Interpretación del output**:

| Resultado | Causa | Fix |
|---|---|---|
| (1) falla + (3) tiene entrada `bci` | Hosts file bloquea | Remover línea de `hosts` (admin) |
| (1) falla + (3) vacío | DNS del sistema | `Set-DnsClientServerAddress -InterfaceIndex N -ServerAddresses 1.1.1.1,8.8.8.8` |
| (1) y (2) OK + scraper falla | Chromium roto | `playwright install chromium --force` |
| (4) tiene proxy seteado | Proxy intercepta | `Remove-Item env:HTTP_PROXY; Remove-Item env:HTTPS_PROXY` y reintentar |
| Todo OK + scraper sigue fallando | Hipótesis 3: dominio cambió | Verificar URL nueva con `Invoke-WebRequest`, actualizar `bci_direct.py:57-60` |

**Acceptance**: `python scripts/test_bci_scraper.py <rut_test> <pwd_test>` arranca Chromium y llega al formulario de login (no necesita completar 2FA). El `ERR_NAME_NOT_RESOLVED` desaparece.

**Commit (solo si tocaste código)**:
```
fix(bci): actualizar URL del portal — el dominio anterior dejó de resolver
```

### Paso 5 — Limpieza `SyntaxWarning \S` (cosmético, junto al primer commit que toques scripts)

`backend-python/scripts/test_bci_scraper.py:1-5` y `scripts/test_bchile_scraper.py:1-22` tienen rutas Windows en docstrings normales:

```diff
-"""
+r"""
 scripts/test_bci_scraper.py — Test manual del scraper de BCI.

 USO:
     1. Activar el venv: .venv\Scripts\activate  (Windows)
```

**Acceptance**: `python -W error::SyntaxWarning scripts/test_bci_scraper.py --help` exit 0.

**Commit** (puede agruparse con otro):
```
fix(scripts): docstrings de tests manuales como raw strings — silencia SyntaxWarning
```

### Paso 6 — Reporte final

Al terminar, postear en el chat con el usuario un reporte así:

```
SPRINT POSTCUTOVER BANKING REVIVAL — REPORTE

Paso 1 (allSettled): ✅/❌  · commit <sha>
Paso 2 (verify endpoints):  /health <code>  /banks <code>  /accounts <code>
Paso 3 (JWT fix): ✅/❌/N/A  · commit <sha>
Paso 4 (BCI triage): causa identificada = <hipótesis 1/2/3>  · fix aplicado = <sí/no/no necesario>
Paso 5 (SyntaxWarning): ✅/❌  · commit <sha>

Deuda nueva detectada:
- <ítem 1>
- <ítem 2>

Pendiente para próximo sprint:
- <ítem 1>
```

---

## 4. Lo que NO se toca en este sprint

- **`backend/` (Node.js)** — no editar. Quedó como referencia post-cutover.
- **`backend-python/src/sky/ingestion/sources/bchile_scraper.py`** — funciona. No "mejorar" sin necesidad.
- **`backend-python/src/sky/core/config.py`** — no hacer permisivo el parsing del `.env`. Fail-fast es por diseño (v5 Parte II §13).
- **`backend-python/.env`** — gitignored. Si el pre-flight falla por dotenv, parar y pedir al usuario.
- **`migrations/*.sql`** — no aplicar migraciones nuevas. Si falta tabla → documentar, NO crear.
- **Tests baseline** (`tests/unit/`, `tests/integration/`) — pueden ejecutarse para verificar regresión, pero no editar excepto si rompiste algo.
- **RLS y políticas Supabase** — no tocar.
- **`Sky.jsx`** — god-component (P1-1). Tocar solo si tu fix lo exige; refactor masivo va aparte.

---

## 5. Reglas operativas

- **PowerShell** por defecto (Windows + miniconda). `$env:VAR = "..."`, `;` o `if ($?) { ... }` — NO `&&`.
- **Plan-first** dentro de cada paso. Leer el archivo antes de editar.
- **Confirmar con usuario** antes de:
  - Cualquier commit.
  - Tocar middleware de auth (Paso 3).
  - Modificar URLs de scrapers (Paso 4 hipótesis 3).
  - Cambios en `core/config.py`.
- **Nunca `--force` push**, nunca `reset --hard` sin OK explícito.
- **Trabajar en `main`**, sin branches. El usuario hace el `git push`.
- Cualquier deuda fuera de scope → registrar en `docs/REMEDIATION_P0_P3.md`, NO arreglar inline.

---

## 6. Referencias

- Plan maestro: `docs/MIGRATION_13_PHASES.md`
- Deuda registrada: `docs/REMEDIATION_P0_P3.md`
- Contrato API: `docs/API_CONTRACT.md`
- Plantilla cierre de fase: `docs/FASE6_CLOSURE_PLAN.md`
- Doctrina: raíz `CLAUDE.md` §⚖️
- Fuente última: `C:\Users\crist\OneDrive\Documentos\SkyFinance\Estados del Arte\SkyFinanzas_EstadoDelArte_v5_Documentado.pdf` (INAPI)

---

_Última actualización: 2026-05-19 · sprint redactado durante incidente "bancos no aparecen post-cutover"._

