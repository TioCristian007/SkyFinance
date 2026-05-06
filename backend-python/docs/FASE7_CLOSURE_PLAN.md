# FASE 7 — Plan de Cierre Definitivo

> Plan ejecutable para cerrar Fase 7 del plan de 13 fases (v5 Parte II §17).
> Diseñado para que un agente Sonnet pueda construirlo sin ambigüedad.
> Doctrinas inviolables vienen de `CLAUDE.md` y v5 PDF; aquí solo se referencian.

## Changelog del plan

- **2026-05-05** (Opus): 4 ajustes aprobados, NO renegociar:
  1. Modelo Mr. Money: `claude-sonnet-4-6` (alias, pin al snapshot en Fase 13),
     `max_tokens=4096`. Ver §2.8.
  2. `POST /api/banking/accounts` IN scope (no Fase 8). Ver §2.3 banking.py.
  3. Schemas faltantes especificados explícitos: `BankAccount{Out,ListResponse,
     ConnectRequest,ConnectedResponse}` + `Projection{Request,Response}`. Ver §2.2.
  4. ARIA: paridad estricta con `backend/services/ariaService.js` — buckets,
     clasificadores y nombres de campo replicados 1:1. Ver §2.5.
- Pre-requisito: `get_aria_client()` no existe aún en `sky.core.db`. Crear como
  parte de Fase 7 — usa `SUPABASE_SERVICE_KEY` + `schema('aria')`. NO usar el
  cliente admin genérico para escribir en `aria.*`.

## 0. Contexto — qué hay y qué falta

### Qué trae Fase 6 listo para usar

- `app.state.arq_pool` — los routers encolan jobs, nunca ejecutan sync inline.
- `app.state.router` — disponible para queries de metadata (bancos soportados).
- `domain/categorizer.py` — funciona, 99% coverage.
- `api/middleware/jwt_auth.py` + `api/deps.py::require_user_id` — listos desde Fase 0.
- `api/routers/banking.py` — `POST /sync/:id` y `/sync-all` ya existen.

### Estado actual de los stubs

| Archivo | LOC | Acción |
|---|---|---|
| `api/routers/transactions.py` | 4 | NUEVO — GET + PATCH + DELETE |
| `api/routers/summary.py` | 4 | NUEVO — GET + by-category |
| `api/routers/goals.py` | 4 | NUEVO — CRUD |
| `api/routers/challenges.py` | 4 | NUEVO — GET + accept + decline |
| `api/routers/chat.py` | 4 | NUEVO — POST (Mr. Money) |
| `api/routers/simulate.py` | 4 | NUEVO — POST projection |
| `api/routers/webhooks.py` | 4 | NUEVO — POST fintoc (stub) |
| `api/routers/internal.py` | 4 | NUEVO — POST cron/sync-due |
| `api/routers/health.py` | 4 | NUEVO — GET (ya existe, verificar) |
| `api/routers/banking.py` | ~50 | EXTENDER — GET /accounts + POST /accounts + DELETE /accounts/:id |
| `api/schemas/transactions.py` | 0 | NUEVO |
| `api/schemas/summary.py` | 0 | NUEVO |
| `api/schemas/goals.py` | 0 | NUEVO |
| `api/schemas/challenges.py` | 0 | NUEVO |
| `api/schemas/chat.py` | 0 | NUEVO |
| `domain/finance.py` | 0 | NUEVO — cálculos puros |
| `domain/mr_money.py` | 0 | NUEVO — detección local + Claude tool use |
| `domain/aria.py` | 0 | NUEVO — pipeline 5 pasos + consent guard |
| `domain/goals.py` | 0 | NUEVO — CRUD + progreso |
| `domain/challenges.py` | 0 | NUEVO — generación + CRUD |
| `domain/simulations.py` | 0 | NUEVO — proyecciones |

**Doctrina inviolable** (no negociar durante construcción):
- `require_user_id` en CADA endpoint protegido. Sin excepción. Cierra **P0-1**.
- `domain/aria.py` guard: `if not await has_aria_consent(user_id): return early`. Cierra **P0-2**.
- Mr. Money llama a Anthropic solo desde backend — nunca desde frontend.
- Mr. Money guía, no decide. `propose_challenge` requiere confirmación explícita.
- Sin `print` — usar `structlog.get_logger(...)`.
- Ningún archivo en `domain/` importa desde `ingestion/sources/`.
- API nunca importa Playwright.

---

## 1. Definition of Done (Gate de Fase 7)

La fase se da por cerrada cuando **los 6 puntos** se cumplen:

1. `pytest tests/ -v` → todos pasan (incluidos los tests nuevos de Fase 7).
2. `mypy src/sky/` → 0 errores.
3. `ruff check src/sky/ tests/` → 0 errores.
4. `uvicorn sky.api.main:app --port 8000` arranca, `/api/health` responde 200.
5. Coverage ≥ 70% en `api/routers/`, `domain/finance.py`, `domain/mr_money.py`, `domain/aria.py`.
6. `docs/MIGRATION_13_PHASES.md` actualizado con `### Estado: ✅ Cerrada (YYYY-MM-DD)`.

---

## 2. Orden de implementación

### 2.1 `src/sky/domain/finance.py` — cálculos puros (sin DB)

Funciones puras, todas testeables sin DB. Paridad con `backend/services/financeService.js`.

```python
"""sky.domain.finance — Cálculos financieros puros."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FinancialSummary:
    balance: int                       # saldo total CLP
    income: int                        # ingresos del período
    expenses: int                      # gastos del período (positivo)
    savings_rate: float                # (income - expenses) / income si income > 0
    by_category: dict[str, int]        # gastos por categoría
    net_flow: int                      # income - expenses (puede ser negativo)


def compute_summary(transactions: list[dict[str, Any]], *, period_days: int = 30) -> FinancialSummary:
    """
    Calcula summary a partir de lista de transacciones.
    Cada transacción: {"amount": int, "category": str, "date": date}.
    amount > 0 = ingreso; amount < 0 = gasto.
    """
    ...


def compute_savings_rate(income: int, expenses: int) -> float:
    if income <= 0:
        return 0.0
    return max(0.0, (income - expenses) / income)
```

### 2.2 `src/sky/api/schemas/` — Pydantic v2

Un archivo por dominio. Todos `from __future__ import annotations`.

#### `schemas/transactions.py`

```python
class TransactionOut(BaseModel):
    id: str
    amount: int
    category: str
    description: str
    raw_description: str
    date: date
    bank_account_id: str
    movement_source: str
    categorization_status: str

class TransactionListResponse(BaseModel):
    transactions: list[TransactionOut]
    total: int
    page: int
    page_size: int

class RecategorizeRequest(BaseModel):
    category: str

class TransactionPatchResponse(BaseModel):
    id: str
    category: str
    updated: bool = True
```

#### `schemas/summary.py`

```python
class SummaryResponse(BaseModel):
    balance: int
    income: int
    expenses: int
    savings_rate: float
    net_flow: int
    period_days: int = 30

class CategoryBreakdown(BaseModel):
    category: str
    label: str
    amount: int
    percentage: float

class SummaryByCategoryResponse(BaseModel):
    categories: list[CategoryBreakdown]
    total_expenses: int
```

#### `schemas/goals.py`

```python
class GoalOut(BaseModel):
    id: str
    name: str
    target_amount: int
    current_amount: int
    target_date: date | None
    progress_pct: float
    created_at: datetime

class GoalCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    target_amount: int = Field(..., gt=0)
    target_date: date | None = None

class GoalPatchRequest(BaseModel):
    name: str | None = None
    target_amount: int | None = None
    target_date: date | None = None
    current_amount: int | None = None
```

#### `schemas/challenges.py`

```python
class ChallengeOut(BaseModel):
    id: str
    title: str
    description: str
    target_amount: int
    current_amount: int
    start_date: date
    end_date: date
    status: str      # "proposed" | "active" | "completed" | "declined"
    created_at: datetime

class ChallengeAcceptResponse(BaseModel):
    id: str
    status: str = "active"

class ChallengeDeclineResponse(BaseModel):
    id: str
    status: str = "declined"
```

#### `schemas/chat.py`

```python
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    context_hint: str | None = None   # "challenges", "goals", etc. para routing local

class ChatTextResponse(BaseModel):
    type: str = "text"
    text: str

class ProposeChallenge(BaseModel):
    type: str = "propose_challenge"
    title: str
    description: str
    target_amount: int
    duration_days: int
    rationale: str

class NavigationResponse(BaseModel):
    type: str = "navigation"
    route: str
    label: str

ChatResponse = ChatTextResponse | ProposeChallenge | NavigationResponse
```

#### `schemas/banking.py` — extender (los 2 actuales se mantienen)

```python
class BankAccountOut(BaseModel):
    id: str
    bank_id: str                       # "bchile", "santander", "bci", ...
    bank_name: str
    bank_icon: str | None = None
    last_balance: int = 0
    last_sync_at: datetime | None = None
    last_sync_error: str | None = None
    status: str                        # "active" | "syncing" | "error" | "waiting_2fa" | "disconnected"
    sync_count: int = 0
    minutes_ago: int | None = None
    account_type: str = "Cuenta"

class BankAccountListResponse(BaseModel):
    accounts: list[BankAccountOut]
    total_balance: int

class BankAccountConnectRequest(BaseModel):
    bank_id: str = Field(..., min_length=2, max_length=32)   # ej. "bchile"
    rut: str = Field(..., min_length=8, max_length=12)       # 12345678-9
    password: str = Field(..., min_length=4, max_length=128)
    bank_name: str | None = None                              # default desde SUPPORTED_BANKS

class BankAccountConnectedResponse(BaseModel):
    id: str
    bank_id: str
    status: str = "active"
    sync_job_id: str                   # job_id ARQ para poll opcional
```

#### `schemas/simulate.py` — NUEVO archivo

```python
class ProjectionRequest(BaseModel):
    target_amount: int = Field(..., gt=0)
    monthly_savings: int = Field(..., ge=0)
    current_savings: int = Field(0, ge=0)
    annual_return_pct: float = Field(0.0, ge=0.0, le=30.0)   # 0 = sin invertir; 5 = fondo conservador

class ProjectionPoint(BaseModel):
    month: int                         # 0, 1, 2, ...
    accumulated: int                   # CLP

class ProjectionResponse(BaseModel):
    months_to_goal: int | None         # None si nunca llega con esos parámetros
    final_amount: int                  # tras 60 meses si no llega
    points: list[ProjectionPoint]      # max 60 puntos para gráfico
    feasible: bool
    rationale: str                     # texto corto explicando realismo
```

### 2.3 `src/sky/api/routers/` — implementar uno por uno

Cada router sigue el mismo patrón:
1. Import schemas + deps + logging.
2. `user_id: str = Depends(require_user_id)` en cada handler.
3. Lógica de DB directa (sin ORM complejo — raw SQL via `get_engine()`).
4. Sin lógica de negocio en el router — delegar a `domain/`.

#### `routers/transactions.py`

```python
@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    user_id: str = Depends(require_user_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    bank_account_id: str | None = Query(None),
) -> TransactionListResponse:
    ...

@router.patch("/{tx_id}", response_model=TransactionPatchResponse)
async def recategorize(tx_id: str, body: RecategorizeRequest, user_id: str = Depends(require_user_id)):
    ...

@router.delete("/{tx_id}", status_code=204)
async def soft_delete(tx_id: str, user_id: str = Depends(require_user_id)):
    ...
```

#### `routers/summary.py`

```python
@router.get("", response_model=SummaryResponse)
async def get_summary(user_id: str = Depends(require_user_id), days: int = Query(30)) -> SummaryResponse:
    ...

@router.get("/by-category", response_model=SummaryByCategoryResponse)
async def summary_by_category(user_id: str = Depends(require_user_id), days: int = Query(30)):
    ...
```

#### `routers/banking.py` — extender

Agregar 3 endpoints:

```python
@router.get("/accounts", response_model=BankAccountListResponse)
async def list_accounts(user_id: str = Depends(require_user_id)):
    """Lista cuentas activas del user con last_balance, last_sync_at, status, error."""
    ...

@router.post("/accounts", response_model=BankAccountConnectedResponse, status_code=201)
async def connect_account(
    body: BankAccountConnectRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> BankAccountConnectedResponse:
    """
    Onboarding de cuenta bancaria. Pasos:
      1. Validar que bank_id está en SUPPORTED_BANKS.
      2. Cifrar rut + password con encrypt() (AES-256-GCM).
      3. INSERT en bank_accounts con status='active', sync_count=0.
      4. Encolar primer sync vía arq_pool.enqueue_job('sync_bank_account_job', ...).
      5. Devolver {id, bank_id, status, sync_job_id}.
    NUNCA logear rut/password ni errores que los contengan (sanitize_error).
    """
    ...

@router.delete("/accounts/{account_id}", status_code=204)
async def disconnect_account(account_id: str, user_id: str = Depends(require_user_id)):
    """Soft-disconnect: status='disconnected', no borra histórico de transactions."""
    ...
```

**Doctrina aplicable**:
- Cifrado con la `BANK_ENCRYPTION_KEY` actual (Fase 3 ya validada Node↔Python).
- `sync_bank_account_job` ya existe en Fase 6, solo se encola.
- Fallback de scrapers respeta el routing — no asumir que `scraper.<bank>` siempre gana.

#### `routers/goals.py`, `routers/challenges.py`

CRUD estándar usando `domain/goals.py` y `domain/challenges.py`.

#### `routers/chat.py`

```python
@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, user_id: str = Depends(require_user_id)) -> ChatResponse:
    from sky.domain.mr_money import MrMoney
    agent = MrMoney()
    return await agent.respond(user_id=user_id, message=body.message)
```

#### `routers/simulate.py`

```python
@router.post("/projection", response_model=ProjectionResponse)
async def get_projection(body: ProjectionRequest, user_id: str = Depends(require_user_id)):
    from sky.domain.simulations import compute_projection
    return await compute_projection(user_id=user_id, **body.model_dump())
```

#### `routers/internal.py`

```python
@router.post("/cron/sync-due")
async def cron_sync_due(request: Request):
    secret = request.headers.get("x-cron-secret", "")
    if secret != settings.cron_secret:
        raise HTTPException(401)
    # Lanzar sync de todas las cuentas que tengan last_sync_at > N horas
    ...
```

#### `routers/webhooks.py`

Stub que responde 200 — integración real con Fintoc es Fase futura.

### 2.4 `src/sky/domain/mr_money.py` — Mr. Money con tool use

Arquitectura de 3 niveles:

```
1. Detección local (sin tokens):
   - Saludos: "hola", "buenos días" → respuesta pre-definida
   - Consulta de desafío activo: "cómo va mi desafío" → routing a domain/challenges
   - Deep-link intents: "ver mis metas" → NavigationResponse

2. Si no matchea local → construir contexto financiero:
   - balance, income, expenses del último mes
   - breakdown por categoría (top 5)
   - metas activas (nombre, progress, target)
   - desafíos activos
   - tasa de ahorro

3. Claude API (claude-sonnet-4-5):
   - system: prompt idéntico al de Node (SKY_SYSTEM_PROMPT)
   - tools: compute_projection, evaluate_goal_realism
   - prompt caching: system + tools con cache_control={"type": "ephemeral"}
   - respuesta procesada → ChatTextResponse | ProposeChallenge | NavigationResponse
```

**Mr. Money NUNCA**:
- Recomienda activos de inversión específicos.
- Garantiza retornos.
- Actúa como asesor licenciado.
- Llama a Anthropic desde el frontend (siempre backend).

**Regla `propose_challenge`**: cuando Claude devuelve un `propose_challenge`, la respuesta al frontend incluye `type: "propose_challenge"`. El frontend DEBE renderizarlo como propuesta con botones Aceptar/Rechazar. **NO se crea el desafío en DB hasta que el usuario confirme con `POST /api/challenges/:id/accept`**.

### 2.5 `src/sky/domain/aria.py` — ARIA con consent guard

**Paridad estricta con `backend/services/ariaService.js`** — buckets, clasificadores
y nombres de campos deben replicarse 1:1 para que las vistas analíticas `aria.v_*`
sigan funcionando con datos pre/post migración. **NO inventar buckets nuevos.**

#### Guard de consentimiento (inicio de cada función pública)

```python
async def track_spending_event(profile: AnonProfile, tx: dict, user_id: str | None = None) -> None:
    if not user_id:
        return
    if not await _has_aria_consent(user_id):
        return  # retorno silencioso — NO loguear el user_id
    # ... pipeline
```

`_has_aria_consent` consulta `profiles.aria_consent` con admin client. Fail-safe: en
error de DB, retorna `False` (no escribir).

#### Buckets canónicos (paridad Node — copiar tal cual)

```python
# Amount buckets — getAmountBucket(amount)
# input en CLP positivo (Math.abs)
def get_amount_bucket(amount: int) -> str:
    if amount <= 50000:   return "0-50k"
    if amount <= 150000:  return "50k-150k"
    if amount <= 500000:  return "150k-500k"
    if amount <= 1500000: return "500k-1.5M"
    return "1.5M+"

# Random in bucket (para amount_noise — NO el monto real)
_BUCKET_RANGES = {
    "0-50k":     (1000,    50000),
    "50k-150k":  (50001,   150000),
    "150k-500k": (150001,  500000),
    "500k-1.5M": (500001,  1500000),
    "1.5M+":     (1500001, 5000000),
}

# Goal target buckets — getGoalTargetBucket(target_amount)
def get_goal_target_bucket(amount: int) -> str | None:
    if not amount or amount <= 0: return None
    if amount <= 500000:    return "0-500k"
    if amount <= 2000000:   return "500k-2M"
    if amount <= 10000000:  return "2M-10M"
    if amount <= 30000000:  return "10M-30M"
    return "30M+"

# Income buckets (validados desde profile.income_range)
INCOME_BUCKETS = {"0-500k", "500k-1M", "1M-2M", "2M-5M", "5M+", "prefer_not"}

# Age ranges
AGE_RANGES = {"18-25", "26-35", "36-45", "46-55", "55+", "under-18", "prefer_not"}

# Occupations
OCCUPATIONS = {"empleado", "independiente", "emprendedor", "estudiante",
               "jubilado", "desempleado", "prefer_not"}

# Region buckets — get_region_bucket(region) usa contains case-insensitive
# RM-Sur, RM-Norte, RM-Oriente, RM-Central
# Valparaíso, Biobío, La Araucanía, Antofagasta, Coquimbo, Los Lagos, O'Higgins, Maule
# Otra región, unknown

# Period: "YYYY-Q[1-4]" — getPeriod()
```

#### Clasificadores de texto (paridad Node, regex idénticos)

Replicar **exactamente** las regex de `ariaService.js`:
- `classify_motivation(text) -> "security"|"family"|"experience"|"freedom"|"status"|"unknown"`
- `classify_blocker(text) -> "impulse"|"social_pressure"|"income_gap"|"habit"|"knowledge"|"unknown"`
- `classify_mindset(text) -> "saver"|"spender"|"avoider"|"balanced"`
- `classify_stress(text) -> "high"|"low"|"medium"`
- `classify_orientation(text) -> "short_term"|"long_term"|"mixed"`
- `classify_behavior_shift(user_msg, mr_money_reply) -> "positive"|"negative"|"neutral"`
- `classify_goal_type(title) -> "housing"|"vehicle"|"education"|"travel"|"emergency"|"life_event"|"investment"|"other"`
- `has_significant_content(text) -> bool` (≥5 palabras + match keyword financiero)

**El texto NUNCA se persiste** — solo las clasificaciones derivadas.

#### Funciones públicas (4)

| Python | Node | Llamada desde |
|---|---|---|
| `track_spending_event(profile, tx, user_id)` | `trackSpendingEvent` | `worker/banking_sync.py` post-insert |
| `track_goal_event(profile, goal, completion_rate, status, user_id)` | `trackGoalEvent` | `routers/goals.py` create/update/complete |
| `track_behavioral_signal(profile, user_msg, mr_money_reply, user_id)` | `trackBehavioralSignal` | `domain/mr_money.py` post-respuesta |
| `track_session_insight(profile, session_data, user_id)` | `trackSessionInsight` | (Fase 8 — no implementar aún) |

#### Tablas destino (schema `aria`, service_role)

- `aria.spending_patterns` — campos: age_range, region, income_range, occupation,
  category, amount_bucket, amount_noise, source, period, batch_id
- `aria.goal_signals` — campos: age_range, region, income_range, occupation,
  goal_type, goal_tier, target_bucket, completion_rate, months_to_goal,
  goal_status, period, batch_id
- `aria.behavioral_signals` — campos: age_range, region, income_range, occupation,
  motivation_category, blocker_type, financial_mindset, stress_level,
  goal_orientation, behavior_shift, period, batch_id
- `aria.session_insights` — Fase 8

`batch_id` = `uuid4()` por registro (ruptura de correlaciones). `recorded_at` lo
agrega Postgres con default `NOW() + random_interval ±36h` (ya configurado).

**Cliente DB**: usar `get_aria_client()` (service_role, schema `aria`). NO usar el
admin client genérico. `aria.*` está bloqueado a clientes anon.

Pipeline 5 pasos formalizado:
1. **Extracción**: evento → señal estructurada.
2. **Categorización**: monto → bucket; fecha → trimestre (`getPeriod`).
3. **Eliminación de identidad**: `user_id` descartado tras consent check.
4. **Randomización intra-bucket**: `amount_noise = random(bucket_min, bucket_max)`.
5. **Ruptura de correlaciones**: `batch_id` propio + jitter temporal en DB.

### 2.6 `src/sky/worker/banking_sync.py` — invocar ARIA post-insert

Agregar al final de `sync_bank_account`, después de `_persist_movements`:

```python
if settings.sync_aria_enabled and inserted > 0:
    from sky.domain.aria import track_spending_event
    # Fire-and-forget — si ARIA falla, no falla el sync
    try:
        await track_spending_event(
            user_id=user_id,
            movement_count=inserted,
            bank_id=bank_id,
        )
    except Exception as exc:
        logger.warning("aria_track_failed", error=str(exc))
```

### 2.7 `src/sky/api/main.py` — montar todos los routers

```python
from sky.api.routers import (
    banking, challenges, chat, goals, health,
    internal, simulate, summary, transactions, webhooks,
)

app.include_router(health.router)
app.include_router(banking.router)
app.include_router(transactions.router)
app.include_router(summary.router)
app.include_router(goals.router)
app.include_router(challenges.router)
app.include_router(chat.router)
app.include_router(simulate.router)
app.include_router(webhooks.router)
app.include_router(internal.router)
```

### 2.8 `src/sky/core/config.py` — settings nuevos

`cron_secret` y `sync_aria_enabled` ya existen desde Fase 5/6. Solo agregar:

```python
# Fase 7 — Mr. Money
mr_money_model: str = "claude-sonnet-4-6"
mr_money_max_tokens: int = 4096   # tool use con propose_challenge requiere holgura
mr_money_temperature: float = 0.7
mr_money_cache_ttl: str = "5m"    # prompt caching: system + tools
```

---

## 3. Tests nuevos (Fase 7)

### `tests/unit/test_finance.py`
- `compute_summary` con lista de transacciones variadas.
- `compute_savings_rate` en casos: income 0, income = expenses, income > expenses.
- Breakdown por categoría correcto.

### `tests/unit/test_mr_money.py`
- Detección local de saludos (sin token).
- Detección local de "ver mis metas" → NavigationResponse.
- Ruta AI con `anthropic` mockeado → ChatTextResponse.
- `propose_challenge` parseado correctamente desde respuesta Claude.
- Tool use: `compute_projection` invocado cuando Claude lo pide.

### `tests/unit/test_aria.py`
- Guard: `aria_consent=False` → return early, sin writes.
- Guard: `aria_consent=True` → pipeline ejecuta.
- Anonimización: monto real → bucket (no se guarda el real).
- Jitter temporal: fecha guardada ≠ fecha real (±36h).
- Sin UUID en registros de aria.*.

### `tests/integration/test_api_transactions.py`
- `GET /api/transactions` sin JWT → 401.
- `GET /api/transactions` con JWT → 200 + lista paginada.
- `PATCH /api/transactions/:id` con categoría válida → 200.
- `DELETE /api/transactions/:id` → 204.

### `tests/integration/test_api_chat.py`
- `POST /api/chat` sin JWT → 401.
- `POST /api/chat` con "hola" → respuesta local (sin llamar Anthropic).
- `POST /api/chat` con pregunta financiera → Anthropic mockeado responde.

---

## 4. Out of scope en Fase 7

| Ítem | Fase |
|---|---|
| Crowdsourcing de categorías (votos de usuarios) | Fase 8 |
| BCI scraper end-to-end | Paralelo (no bloquea) |
| Métricas Prometheus detalladas | Fase 10 |
| Fintoc webhook real | Tras integración Fintoc (Fase futura) |
| Test de parity Node vs Python | Fase 13 |

---

## 5. Deuda que cierra esta fase

| ID | Item | Cómo cierra |
|---|---|---|
| **P0-1** | JWT auth en backend | `require_user_id` en TODOS los endpoints — verificado con test 401 |
| **P0-2** | Consent ARIA inconsistente | `domain/aria.py` guard estricto, testeado unit |

---

## 6. Checklist final del PR

- [ ] Todos los archivos de §2 creados
- [ ] `pytest tests/ -v` verde
- [ ] Coverage ≥ 70% en `api/routers/`, `domain/finance.py`, `domain/mr_money.py`, `domain/aria.py`
- [ ] `mypy src/sky/` → 0 errores
- [ ] `ruff check src/sky/ tests/` → 0 errores
- [ ] `uvicorn sky.api.main:app --port 8000` arranca, `/api/health` 200
- [ ] `POST /api/chat` con "hola" responde sin llamar Anthropic
- [ ] `GET /api/transactions` sin JWT → 401; con JWT → 200
- [ ] P0-1 y P0-2 confirmados cerrados en test
- [ ] `docs/MIGRATION_13_PHASES.md` actualizado con estado ✅

---

## 7. Estimación

| Componente | Días |
|---|---|
| domain/finance.py + tests | 0.5 |
| Schemas Pydantic | 0.5 |
| routers/transactions + summary | 1.0 |
| routers/banking (GET + DELETE) | 0.5 |
| routers/goals + challenges | 1.0 |
| domain/goals + domain/challenges | 1.0 |
| domain/mr_money (Mr. Money) | 2.0 |
| domain/aria (pipeline) | 1.5 |
| routers/chat + simulate | 1.0 |
| domain/simulations | 0.5 |
| routers/webhooks + internal | 0.5 |
| Tests de integración | 1.0 |
| Gates finales + documentación | 0.5 |
| **Total** | **~11.5 días** |

Con Claude Code esta fase se puede comprimir a ~2 sesiones de trabajo intensivo.
