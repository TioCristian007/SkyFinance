# POST-CUTOVER PLAN — Sky Finance
**Fecha**: 2026-05-17  
**Basado en**: POST_CUTOVER_AUDIT.md  
**Requiere aprobación del usuario antes de ejecutar.**

---

## 1. Definition of Done

Se considera **listo para testers** cuando:

- [ ] `app.skyfinanzas.com` carga Sky.jsx sin errores en console
- [ ] Dashboard muestra balance, ingresos, gastos reales del usuario
- [ ] Los bancos mostrados en "Conectar banco" coinciden con los realmente operativos en Python
- [ ] Un usuario test puede conectar una cuenta BChile, ver sus transacciones, hablar con Mr. Money
- [ ] Las metas cargan y se pueden crear/editar
- [ ] Los desafíos se pueden activar
- [ ] `GET /api/health/deep` → 200 `{"db":"ok","redis":"ok","anthropic":"ok"}`
- [ ] Sin `TypeError` ni crashes silenciosos en el init() de Sky.jsx
- [ ] `pytest tests/ -q` → 359+ passed, 0 failed (no regresiones)
- [ ] `ruff check` + `mypy` → 0 errores

---

## 2. Lista de fixes priorizada

### PRIORIDAD ALTA — Bloqueantes para testers

---

#### Fix #1 — Summary endpoint: shape compatible con Sky.jsx
**Urgencia**: 🔴 CRÍTICO — BLOCKER. Sin esto la app muestra pantalla vacía.

**Archivos**:
- `src/sky/api/routers/summary.py`
- `src/sky/api/schemas/summary.py`
- `src/sky/domain/finance.py` (agregar query de bank_accounts y profile)

**Qué hacer**:

El Python `GET /api/summary` debe devolver la misma estructura que Node:
```json
{
  "summary": {
    "balance": ...,
    "income": ...,
    "expenses": ...,
    "savingsRate": ...,
    "spendingRate": ...,
    "bankAccounts": [...],
    "totalBankBalance": ...,
    "hasBankAccounts": true/false,
    "incomeIsReal": true/false,
    "topCategory": {...} | null,
    "categoryTotals": {...},
    "transactionCount": ...,
    "period": "2026-05",
    "currency": "CLP"
  },
  "profile": {
    "user": {
      "id": "...",
      "name": "...",
      "email": "..."
    }
  },
  "badges": {
    "allBadges": [],
    "newBadges": []
  }
}
```

**Pasos**:
1. En `domain/finance.py`: extraer `compute_summary_full(user_id)` que incluye query a `bank_accounts` y `profiles`.
2. Actualizar `SummaryResponse` en schemas para el nuevo shape anidado.
3. Actualizar router `GET /api/summary` para devolver el shape completo.
4. `badges`: el sistema de badges de Node es complejo (evaluateBadges). Para MVP, devolver `{"allBadges": [], "newBadges": []}` — esto es suficiente para que Sky.jsx no crashee. Los badges pueden quedar vacíos.
5. `profile`: query simple a `profiles` table para `id`, `display_name` (o email como fallback).

**Nota importante**: `bankAccounts` en summary debe tener el shape camelCase (ver Fix #2 abajo). Cuando este fix se haga, los `bankAccounts` dentro del summary también deben usar camelCase.

**Verificación**:
```bash
curl -H "Authorization: Bearer <JWT>" https://sky-api-python-production.up.railway.app/api/summary
# Debe devolver {summary: {balance: ..., bankAccounts: [...], ...}, profile: {...}, badges: {...}}
```

**Rollback**: si falla, revertir el cambio en router. El frontend sigue hablando con Python pero vuelve a pantalla vacía (estado actual).

---

#### Fix #2 — Banking: camelCase en respuestas
**Urgencia**: 🔴 CRÍTICO — BankConnect.jsx muestra $0 en todos los balances.

**Archivos**:
- `src/sky/api/schemas/banking.py`
- `src/sky/api/routers/banking.py` (verificar que `total_balance` → `totalBalance`)

**Qué hacer**:

Opción A (recomendada): mapeo explícito en el router — más legible y sin magia.

En `GET /api/banking/accounts`, cambiar el return para construir un dict con camelCase:
```python
return {
    "accounts": [
        {
            "id": a.id,
            "bankId": a.bank_id,
            "bankName": a.bank_name,
            "bankIcon": a.bank_icon,
            "balance": a.last_balance,
            "lastSyncAt": a.last_sync_at,
            "lastSyncError": a.last_sync_error,
            "status": a.status,
            "syncCount": a.sync_count,
            "minutesAgo": a.minutes_ago,
            "accountType": a.account_type,
            "last4": None,
        }
        for a in result.accounts
    ],
    "totalBalance": result.total_balance,
}
```

Opción B: `model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)` — más elegante pero afecta todos los schemas que hereden.

**Usar Opción A** para cambio quirúrgico sin efectos en otros schemas.

**Verificación**:
```bash
curl -H "Authorization: Bearer <JWT>" https://sky-api-python-production.up.railway.app/api/banking/accounts
# Debe devolver {"accounts": [{"bankId": "bchile", "bankName": "Banco de Chile", "balance": ..., ...}], "totalBalance": ...}
```

---

#### Fix #3 — Goals: wrapper + field names
**Urgencia**: 🔴 CRÍTICO — sección de metas no carga.

**Archivos**:
- `src/sky/api/routers/goals.py`

**Qué hacer**:

1. `GET /api/goals` debe devolver `{"goals": [...]}` con camelCase:
```python
return {"goals": [
    {
        "id": str(r["id"]),
        "title": str(r["name"]),           # Sky.jsx usa goal.title
        "targetAmount": int(r["target_amount"]),  # goal.targetAmount
        "savedAmount": int(r["current_amount"] or 0),  # goal.saved_amount / savedAmount
        "deadline": str(r["target_date"]) if r.get("target_date") else None,
        "projection": {                    # goal.projection.pct
            "pct": int(r.get("progress_pct", 0)),
            "remaining": max(0, int(r["target_amount"]) - int(r["current_amount"] or 0)),
            "monthsToGoal": None,
            "projectedDate": None,
        },
        "created_at": str(r["created_at"]),
    }
    for r in rows
]}
```

2. `POST /api/goals` (create) debe devolver `{"goal": {...camelCase...}}`.

3. `PATCH /api/goals/:id` (update) debe devolver `{"goal": {...camelCase...}}`.

**Nota**: Sky.jsx llama `addGoal({title, targetAmount, deadline})`. El schema actual `GoalCreateRequest` tiene `name`, `target_amount`, `target_date`. Ajustar para aceptar ambos formatos o agregar `title`/`targetAmount`/`deadline` como aliases.

**Verificación**:
```bash
curl -H "Authorization: Bearer <JWT>" https://sky-api-python-production.up.railway.app/api/goals
# Debe devolver {"goals": [{"title": "...", "targetAmount": ..., "savedAmount": ..., "projection": {...}}]}
```

---

#### Fix #4 — Challenge paths: /activate y /complete
**Urgencia**: 🟡 ALTO — desafíos visibles pero no operables.

**Archivos**:
- `src/sky/api/routers/challenges.py`

**Qué hacer**:

Agregar los paths que usa el frontend como aliases de `/accept` y `/decline`:
```python
@router.post("/{challenge_id}/activate", response_model=ChallengeAcceptResponse)
async def activate_challenge(challenge_id: str, user_id: str = Depends(require_user_id)):
    # llamar a la misma lógica que accept_challenge
    return await accept_challenge(challenge_id, user_id)

@router.post("/{challenge_id}/complete", response_model=ChallengeAcceptResponse)
async def complete_challenge(challenge_id: str, user_id: str = Depends(require_user_id)):
    # Mr. Money llama complete cuando el desafío se cumple
    # Por ahora, mapear a la lógica de accept (marcar como completado)
    return await accept_challenge(challenge_id, user_id)
```

*(Mantener `/accept` y `/decline` para compatibilidad interna.)*

**Verificación**:
```bash
curl -X POST -H "Authorization: Bearer <JWT>" \
  https://sky-api-python-production.up.railway.app/api/challenges/<id>/activate
# Debe devolver {"id": "...", "status": "active"} — no 404
```

---

#### Fix #5 — Falabella status: pending
**Urgencia**: 🟡 ALTO — Falabella aparece como disponible en UI.

**Archivos**:
- `src/sky/ingestion/sources/__init__.py`

**Qué hacer**:
```python
{"id": "falabella", "name": "Banco Falabella", "icon": "🏦", "status": "pending", "has_2fa": False},
```

**Verificación**:
```bash
curl https://sky-api-python-production.up.railway.app/api/banking/banks
# falabella.status debe ser "pending"
# BankConnect.jsx filtra status==="active" → Falabella NO aparece como disponible
```

---

### PRIORIDAD MEDIA — DX y limpieza

---

#### Fix #6 — body.json: borrar + gitignore
**Urgencia**: 🟢 BAJO — no bloquea nada pero es deuda.

```
# Borrar:
backend-python/body.json

# Agregar a backend-python/.gitignore:
body.json
```

**Sin PII**: contiene solo parámetros de simulación `{monthly_savings, months, annual_rate, target_amount}`.

---

#### Fix #7 — Docker CMD: usar $PORT
**Urgencia**: 🟡 ALTO — potencial causa de caídas post-redeploy.

**Archivo**: `backend-python/docker/api.Dockerfile`

```dockerfile
# Antes:
CMD ["uvicorn", "sky.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Después:
CMD ["sh", "-c", "uvicorn sky.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

**Nota**: Verificar primero en Railway dashboard si el puerto del servicio `sky-api-python` está configurado como 8000. Si está manual en 8000 y funciona, este fix es preventivo para futuros redeploys.

---

#### Fix #8 — README.md: actualizar estado de fases
**Urgencia**: 🟢 BAJO.

`backend-python/README.md` actualizar para reflejar fases 0-12 cerradas, Python en producción como api-v2.

---

### PRIORIDAD BAJA — Para demo a banqueros

---

#### Fix #9 — Verificar VITE_API_URL en Railway frontend
**Urgencia**: 🟡 ALTO pero manual — solo el usuario puede verificar.

El usuario debe verificar en el dashboard Railway del servicio `SkyFinance`:
- `VITE_API_URL` debe ser `https://sky-api-python-production.up.railway.app/api` o `https://api-v2.skyfinanzas.com/api`
- **NO** `https://appealing-benevolence-production.up.railway.app/api` (eso sería Node)

Después de los fixes de respuesta (1-5), el frontend debe apuntar al Python backend.

---

#### Fix #10 — Aplicar migraciones SQL pendientes
**Manual del usuario** — no puedo hacer esto desde aquí.

```sql
-- migration 002 (si no se aplicó):
-- Ver: backend-python/migrations/002_indexes_and_constraints.sql

-- migration 005 (si no se aplicó):
-- Ver: backend-python/migrations/005_audit_log_purge.sql
```

Verificar:
```sql
SELECT indexname FROM pg_indexes
 WHERE tablename = 'transactions' AND indexname LIKE 'uniq_%';
-- Esperado: uniq_tx_external

SELECT proname FROM pg_proc WHERE proname = 'purge_audit_log_old';
-- Esperado: 1 row
```

---

#### Fix #11 — Decommission sky-cron-sync legacy
**Manual del usuario** — apagar el servicio Railway `sky-cron-sync`.

El ARQ cron nativo del worker Python hace la misma función. El cron legacy apunta al endpoint Node que puede estar apagado.

---

## 3. Procedimiento de ejecución por fix

### Orden recomendado de ejecución
```
Fix #5 (falabella, 5 min)
Fix #6 (body.json, 5 min)
Fix #4 (challenges paths, 30 min)
Fix #2 (banking camelCase, 1h)
Fix #3 (goals shape, 1h)
Fix #1 (summary shape, 2-3h) ← más complejo, dejarlo para el final de alta prioridad
Fix #7 (docker port, 15 min)
Fix #8 (README, 15 min)
```

*(Fixes pequeños primero para ganar momentum y limpiar deuda simple.)*

### Por cada fix
1. Implementar el cambio
2. `pytest tests/ -q` → no regresiones
3. `ruff check src/sky/ tests/` → 0 errores
4. `mypy src/sky/` → 0 errores
5. Commit con mensaje descriptivo en español
6. El usuario decide cuándo hacer `git push` → Railway redeploy

### Commits — formato
```
fix(summary): envolver respuesta en {summary, profile, badges} para paridad Node

fix(banking): camelCase en GET /api/banking/accounts (bankId, totalBalance, etc.)

fix(goals): wrapper {goals:[...]}, camelCase campos, projection object

fix(challenges): agregar rutas /activate y /complete como aliases

fix(sources): falabella status→pending hasta que scraper esté implementado
```

---

## 4. Estimación total

| Fix | Dificultad | Tiempo |
|---|---|---|
| #1 Summary | Alta | 2-3h |
| #2 Banking camelCase | Media | 1h |
| #3 Goals | Media | 1h |
| #4 Challenges paths | Baja | 30min |
| #5 Falabella pending | Trivial | 5min |
| #6 body.json | Trivial | 5min |
| #7 Docker port | Trivial | 15min |
| #8 README | Baja | 15min |
| **TOTAL (código)** | | **~5-6h** |

---

## 5. Qué NO se hace en este sprint

- **Refactor de Sky.jsx (P1-1)** — god component de 1678 LOC. Fuera de scope.
- **Implementar Falabella scraper** — Fase futura.
- **BCI end-to-end** — Gate manual pendiente de Fase 4.
- **Parity tests formales** — Fase 13 del plan original.
- **Migrar `api.skyfinanzas.com` de Node a Python** — solo después de 48h de testing estable con api-v2.
- **Badges completos** — el sistema de badges Node es complejo. MVP: badges vacíos.

---

*Aguardando aprobación para iniciar Fase C.*  
*Sky Finance · backend-python/docs/POST_CUTOVER_PLAN.md · 2026-05-17*
