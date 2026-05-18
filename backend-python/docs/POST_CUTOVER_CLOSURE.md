# POST_CUTOVER_CLOSURE — Sprint de Corrección Post-Migración

**Fecha**: 2026-05-18
**Branch**: main
**Estado**: ✅ Sprint completado — 7 fixes aplicados, tests verdes

---

## 1. Fixes ejecutados (por orden de prioridad)

| # | Fix | Commit | Archivos |
|---|-----|--------|---------|
| 1 | **summary shape**: envolver en `{summary, profile, badges}` para paridad Node | `da12ac5` | `routers/summary.py`, `tests/unit/test_challenges.py` |
| 2 | **banking camelCase**: `GET /api/banking/accounts` devuelve `bankId`, `balance`, `totalBalance`, etc. | `7ecdf47` | `routers/banking.py`, `schemas/banking.py` |
| 3 | **goals wrapper**: `{goals:[...]}` y campos camelCase con projection | `051fcd0` | `routers/goals.py`, `schemas/goals.py` |
| 4 | **challenges aliases**: `/activate` y `/complete` como aliases de `/accept` y `/decline` | `7afe829` | `routers/challenges.py` |
| 5 | **falabella pending**: status `pending` — scraper es skeleton, no debe aparecer en UI | `a9d8455` | `ingestion/sources/__init__.py` |
| 6 | **body.json gitignore**: archivo de debug excluido del repo | `997c930` | `.gitignore` |
| 7 | **Docker PORT**: CMD usa `${PORT:-8000}` para Railway env var dinámica | `36f53ea` | `docker/api.Dockerfile` |

---

## 2. Gates de calidad

```
ruff check src/sky/api/routers/summary.py   → 0 errores
mypy src/sky/api/routers/summary.py          → 0 errores
pytest tests/ -q                             → 359 passed, 1 skipped
```

---

## 3. Pendiente manual: verificar VITE_API_URL en Railway

El token disponible (`RAILWAY_TOKEN`) es project-level y no permite queries GraphQL a la API de Railway.
Debes verificar manualmente:

1. Ir a Railway dashboard → Proyecto SkyFinance → Service **SkyFinance** (frontend)
2. Ir a **Variables** → buscar `VITE_API_URL`
3. Si el valor es `https://appealing-benevolence-production.up.railway.app/api` (Node) → cambiarlo a:
   ```
   https://api-v2.skyfinanzas.com/api
   ```
4. Guardar → Railway redeployará automáticamente el frontend

Si ya apunta a `https://api-v2.skyfinanzas.com/api` → no hacer nada.

---

## 4. Instrucciones de verificación end-to-end

Después de confirmar `VITE_API_URL` y hacer `git push`:

### Paso 0 — Hard refresh
```
Ctrl+F5 en https://app.skyfinanzas.com
```
Esperado: no quedan archivos cacheados del build anterior.

### Paso 1 — Login
- Ir a `https://app.skyfinanzas.com`
- Login con tu cuenta de prueba
- Esperado: **pantalla de dashboard carga sin blank screen**, sin errores en consola JS

> Si hay blank screen: abrir DevTools (F12) → Console → buscar el error.
> El crash típico pre-fix era `TypeError: Cannot read properties of undefined (reading 'allBadges')` → si ya no aparece, el Fix #1 funcionó.

### Paso 2 — Dashboard principal
- Verificar que aparecen cifras de balance, ingresos, gastos
- Esperado: números reales en CLP (no $0, no NaN)
- `savingsRate` y `spendingRate` son enteros 0-100 (pueden aparecer como porcentaje)

### Paso 3 — Cuentas bancarias
- Ir a la sección de cuentas / Banking
- Esperado: cada cuenta muestra nombre del banco, balance, `lastSyncAt` (no null/undefined)
- `totalBalance` aparece como suma de todas las cuentas

### Paso 4 — Conectar cuenta (si no hay cuentas conectadas)
- Click "Conectar banco"
- Esperado: solo BChile aparece como opción disponible (Falabella debe estar oculto o en estado pendiente)
- Ingresar RUT + clave → click conectar
- Esperado: respuesta inmediata con mensaje "Sync iniciado"

### Paso 5 — Metas
- Ir a la sección Metas / Goals
- Si hay metas: verificar que se listan con `title`, `targetAmount`, `savedAmount`, `deadline`
- Crear meta nueva (ej: "Vacaciones", $500.000, fecha futura)
- Esperado: meta aparece en la lista con progress 0%

### Paso 6 — Mr. Money
- Abrir chat con Mr. Money
- Escribir: `hola`
- Esperado: respuesta de saludo en español, sin errores de API

### Paso 7 — Desafíos
- Ir a la sección Desafíos / Challenges
- Esperado: lista de desafíos disponibles (de MOCK_CHALLENGES: Sin Uber 7 días, Comida bajo $80K, etc.)
- Activar un desafío → click "Aceptar" o "Activar"
- Esperado: desafío pasa a sección "Activos"

---

## 5. Qué NO se abordó en este sprint (TODOs)

| Item | Descripción | Fase |
|------|-------------|------|
| `VITE_API_URL` | Verificación requiere acción manual en Railway dashboard | Inmediato |
| `P0-1` JWT en Node | Backend Node aún lee header sin verificar firma | Fix Node (30 min) |
| `P1-1` Sky.jsx god-component | 1,678 LOC — refactor pendiente | Paralelo frontend |
| `P1-2` CORS permisivo | Python: rechazar deploy sin allowlist | Fase 10 |
| `BUG-4` Sync secuencial | 5 min entre bancos → browser pool paralelo (~90s) | Fase 9 |
| Migration 002 | Aplicada ✅ (`uniq_tx_external`, `idx_transactions_pending` presentes) | — |
| Migration 005 | Aplicada ✅ (confirmado por usuario) | — |
| Fase 6 worker jobs | `banking_sync`, `categorize`, `mr_money` aún stubs | Fase 6 |
| Fase 8 Mr. Money Python | Mr. Money corre en Node por ahora | Fase 8 |

---

## 6. Comando de push

```powershell
git push origin main
```

El usuario debe ejecutar este comando — Claude solo hace commits locales por doctrina del CLAUDE.md.

---

## 7. Resumen ejecutivo

El sprint corrigió las 7 incompatibilidades de shape entre el backend Python y el frontend React que causaban:
- **Pantalla en blanco** al cargar (crash por `summaryRes.badges.allBadges` undefined) → Fix #1
- **Balance $0** en cuentas bancarias (snake_case vs camelCase) → Fix #2
- **Metas no cargaban** (array directo sin wrapper `{goals:[...]}`) → Fix #3
- **Desafíos no activables** (endpoints `/activate`/`/complete` faltantes) → Fix #4
- **Falabella visible** pese a scraper incompleto → Fix #5
- **body.json en repo** → Fix #6
- **Docker hardcodea puerto 8000** en vez de leer `$PORT` de Railway → Fix #7

El único paso crítico pendiente antes de validar en producción es confirmar `VITE_API_URL` en Railway.
