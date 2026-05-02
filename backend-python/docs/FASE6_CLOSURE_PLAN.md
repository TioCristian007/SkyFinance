# FASE 6 — Plan de Cierre Definitivo

> Plan ejecutable para cerrar Fase 6 del plan de 13 fases (v5 Parte II §16).
> Diseñado para que un agente Sonnet pueda construirlo sin ambigüedad.
> Doctrinas inviolables vienen de `CLAUDE.md` y v5 PDF; aquí solo se referencian.

## 0. Contexto — qué hay y qué falta

| Componente | Estado actual | Acción |
|---|---|---|
| `worker/main.py` | ✅ ARQ WorkerSettings con browser pool lifecycle, bootstrap del router | Registrar `functions = [...]` (hoy `[]`) |
| `worker/jobs/sync.py` | 🔴 Stub 4 LOC | NUEVO — `sync_bank_account_job`, `sync_all_user_accounts_job` |
| `worker/jobs/categorize.py` | 🔴 Stub 4 LOC | NUEVO — `categorize_pending_job` |
| `worker/banking_sync.py` | 🔴 Stub 10 LOC | NUEVO — orquestador con `pg_try_advisory_lock` |
| `domain/categorizer.py` | 🔴 Stub 6 LOC | NUEVO — 3 capas portadas de Node (regex → cache → Claude) |
| `api/main.py` | ✅ lifespan con router | Agregar `arq_pool` a `app.state` |
| `api/routers/banking.py` | 🔴 Stub 8 LOC | NUEVO — endpoint `POST /api/banking/sync/:id` que solo encola |
| `api/schemas/banking.py` | 🔴 Stub 4 LOC | NUEVO — request/response Pydantic |
| `core/locks.py` | ✅ wrapper de advisory lock | Verificar interfaz async + tests |
| Migración `002_indexes_and_constraints.sql` | 🔴 No existe | NUEVO — cierra BUG-2 + índice para queue depth |
| Tests Fase 6 | 🔴 Ninguno | Crear 4 archivos |
| `MIGRATION_13_PHASES.md` | Marca Fase 6 pendiente | Marcar `### Estado: ✅ Cerrada (YYYY-MM-DD)` |

**Doctrina inviolable** (no negociar durante construcción — vienen de CLAUDE.md):
- API NUNCA importa Playwright. El job que sincroniza vive en `worker/`.
- `sync.py` invoca `IngestionRouter` ya construido en `ctx["router"]`. No redescubre fuentes.
- `AuthenticationError` propaga al frontend como error de credenciales — no failover, no retry.
- `RecoverableIngestionError` → router intenta siguiente fuente. Si toda la cadena falla → `AllSourcesFailedError` → status `error` en `bank_accounts`.
- Advisory lock por `bank_account_id` (hash SHA-256) usando `pg_try_advisory_lock`. Cierra **BUG-3**.
- Persistencia con `INSERT ... ON CONFLICT (user_id, bank_account_id, external_id) DO NOTHING` aprovechando el unique índice ya creado en `000_immediate_fixes.sql`. Cierra **BUG-1, BUG-2**.
- Categorización es **fire-and-forget desde sync**: insertar con `categorization_status='pending'`, encolar `categorize_pending_job` al final.
- ARIA solo se dispara si `aria_consent=true` y siempre con `user_id` explícito (cierra **P0-2**).
- Browser pool paralelo del worker permite múltiples bancos del mismo user en paralelo (cierra **BUG-4**).

---

## 1. Definition of Done (Gate de Fase 6)

La fase se da por cerrada cuando **los 8 puntos** se cumplen. No hay parcial.

1. `pytest tests/unit/ -v` → todos los tests pasan, incluidos los 3 nuevos.
2. `pytest tests/integration/test_sync_job.py -v` → test end-to-end pasa con worker + Redis local + DB de staging.
3. `mypy src/sky/` → 0 errores (ahora alcanza también `worker/`, `api/routers/banking.py`, `domain/categorizer.py`).
4. `ruff check src/sky/ tests/` → 0 errores.
5. Migración `002_indexes_and_constraints.sql` aplicada en staging y producción. Verificación: 4 índices reportados.
6. Smoke manual: `arq sky.worker.main.WorkerSettings` arranca limpio + encolar `sync_bank_account_job` con cuenta BChile real → movimientos persisten en `transactions` con `categorization_status='pending'`. Segunda ejecución del mismo job no inserta duplicados.
7. `categorize_pending_job` ejecutado tras el sync deja todas las filas con `categorization_status IN ('done','failed')`. Categorías reales (no solo `other`).
8. `docs/MIGRATION_13_PHASES.md` actualizado: la sección Fase 6 marcada `✅ Cerrada (YYYY-MM-DD)` con archivos y gates `[x]`.

---

## 2. Cambios por archivo

### 2.1 `pyproject.toml` — sin cambios

No requiere deps nuevas. `arq>=0.26.1`, `redis>=5.2.0`, `anthropic>=0.40.0`, `sqlalchemy[asyncio]>=2.0.36`, `httpx`, `cryptography`, todo ya está.

### 2.2 `src/sky/core/config.py` — settings de categorización y advisory lock

Agregar al final del bloque de settings, antes de las `@property`:

```python
    # ── Categorización (Fase 6) ───────────────────────────────────────────
    categorize_batch_size: int = 50
    categorize_max_keys_per_ai_call: int = 20
    categorize_anthropic_model: str = "claude-haiku-4-5-20251001"
    categorize_confidence_threshold: float = 0.75

    # ── Sync banking job (Fase 6) ─────────────────────────────────────────
    sync_advisory_lock_timeout_sec: int = 600   # 10 min — máximo razonable
    sync_max_concurrent_per_user: int = 4       # alineado con browser_pool_size
    sync_aria_enabled: bool = True              # respeta aria_consent del user
```

### 2.3 `src/sky/core/locks.py` — verificar/crear `try_advisory_lock`

Si no existe el helper async, crearlo. Interfaz objetivo:

```python
"""sky.core.locks — Postgres advisory locks distribuidos."""
from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("locks")


def _key_from_string(s: str) -> int:
    """SHA-256 → int64 estable. Postgres pg_try_advisory_lock acepta bigint."""
    h = hashlib.sha256(s.encode("utf-8")).digest()
    # Tomar 8 bytes como int signed 64-bit
    return int.from_bytes(h[:8], "big", signed=True)


@asynccontextmanager
async def try_advisory_lock(key_str: str) -> AsyncIterator[bool]:
    """
    Adquiere un advisory lock no-bloqueante. Si lo obtiene, lo libera al salir.
    
    Yields True si se adquirió, False si ya estaba tomado por otro worker.
    El caller decide qué hacer cuando es False (skip, retry, etc.).
    
    Uso:
        async with try_advisory_lock(f"sync:bank_account:{account_id}") as got:
            if not got:
                logger.info("sync_skipped_locked")
                return
            ...  # trabajo seguro
    """
    key = _key_from_string(key_str)
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
        )
        got = bool(result.scalar())
        try:
            yield got
        finally:
            if got:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": key}
                )
                await conn.commit()
```

### 2.4 `src/sky/domain/categorizer.py` — 3 capas portadas de Node

**Reemplazar el archivo completo.** Paridad funcional con `backend/services/categorizerService.js`. Misma jerarquía de 16 categorías, mismas reglas regex Layer 1, mismo prefix matching Layer 2, mismo system prompt Layer 3. La 4ta capa de crowdsourcing con votos NO se incluye aquí — está en TODO Fase 8 (§4).

```python
"""
sky.domain.categorizer — Categorización 3 capas (paridad con Node v3).

Jerarquía:
    1. Reglas regex deterministas — sin tokens, instantáneo.
    2. Cache en `merchant_categories` con prefix matching progresivo.
    3. Claude Haiku batch 20 keys/call. Resultado se guarda en cache.

Si Claude no logra confidence ≥ 0.75 → "other". Si la 3ra capa falla
(rate limit, error de red), todas las filas restantes se marcan "failed"
para no quedar en loop infinito; la entrega futura de re-categorización
las recupera.

Categoría "other" + status="failed" significa: el sistema no pudo
clasificar y el usuario tendrá la oportunidad de declarar manualmente
(ver §4 — sistema de votos crowdsourced, fuera de scope Fase 6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import anthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("categorizer")


CATEGORIES = (
    "food", "transport", "subscriptions", "entertainment",
    "health", "education", "housing", "insurance", "utilities",
    "shopping", "debt_payment", "savings", "transfer",
    "banking_fee", "income", "other",
)

CATEGORY_LABELS = {
    "food":          "Alimentación",
    "transport":     "Transporte",
    "subscriptions": "Suscripción",
    "entertainment": "Entretención",
    "health":        "Salud",
    "education":     "Educación",
    "housing":       "Vivienda",
    "insurance":     "Seguro",
    "utilities":     "Servicios básicos",
    "shopping":      "Compras",
    "debt_payment":  "Cuota crédito",
    "savings":       "Ahorro",
    "transfer":      "Transferencia",
    "banking_fee":   "Comisión bancaria",
    "income":        "Ingreso",
    "other":         "Gasto",
}


# ── CAPA 1: Reglas deterministas ──────────────────────────────────────────────
# Paridad estricta con LAYER1_RULES de Node. Orden importa: la primera regla
# que matchea gana. Mantener orden idéntico al de categorizerService.js v3.

_RULES: list[tuple[Any, str]] = [
    # Tuplas (predicate, category). Predicate recibe (desc_lower, amount).
    (lambda d, a: a > 0 and re.search(r"^traspaso\s+de:", d, re.I) is not None,                        "income"),
    (lambda d, a: a > 0 and re.search(r"abono|remuner|sueldo|salario|honorario|liquidaci", d, re.I) is not None, "income"),
    (lambda d, a: a > 0 and re.search(r"devoluci[oó]n\s*(imp|sii)|reintegro", d, re.I) is not None,    "income"),
    (lambda d, a: a < 0 and re.search(r"^traspaso\s+a:", d, re.I) is not None,                         "transfer"),
    (lambda d, a: a < 0 and re.search(r"khipu|transferencia\s+a:", d, re.I) is not None,               "transfer"),
    (lambda d, a: re.search(r"^comisi[oó]n|iva\s+comisi[oó]n|mantenci[oó]n\s+cta|cargo\s+mantenci", d, re.I) is not None, "banking_fee"),
    (lambda d, a: re.search(r"bip[!\s]|red\s+movilidad|transantiago", d, re.I) is not None,            "transport"),
    (lambda d, a: re.search(r"pago:metro\s|metro\s+(de\s+santiago|baquedano|universidad|plaza|santa\s+ana)", d, re.I) is not None, "transport"),
    (lambda d, a: re.search(r"\bcopec\b|\bshell\b|\bpetrobras\b|\benex\b|\besso\b", d, re.I) is not None, "transport"),
    (lambda d, a: re.search(r"\bnetflix\b|\bspotify\b|\bdisney\+|\bhbo\s*max\b|\byoutube\s*premium\b|\bamazon\s*prime\b|\bcrunchyroll\b|\bstar\+", d, re.I) is not None, "subscriptions"),
    (lambda d, a: re.search(r"pago:(entel|movistar|claro|wom|vtr|gtd)\b", d, re.I) is not None,        "utilities"),
    (lambda d, a: re.search(r"salcobrand|cruz\s*verde|ahumada|dr\.?\s*simi", d, re.I) is not None,     "health"),
    (lambda d, a: re.search(r"pago\s+tar(jeta)?\s+cr[eé]d|pago\s+tc\b", d, re.I) is not None,          "debt_payment"),
    (lambda d, a: re.search(r"dep[oó]sito\s+plazo|dap\b|fondo\s+mutuo|\bapv\b|aporte\s+afp", d, re.I) is not None, "savings"),
    (lambda d, a: re.search(r"\bjumbo\b|\blider\b|\btottus\b|\bsanta\s+isabel\b|\bunimarc\b|\bacuenta\b|\bekono\b|\bmayor[i1]sta\s*10\b", d, re.I) is not None, "food"),
    (lambda d, a: re.search(r"\bstarbucks\b|\bmcdonald|\bburger\s*king\b|\bsubway\b|\bdominos\b|\bpizza\s*hut\b|\btelepi[zs]za\b|\bkfc\b", d, re.I) is not None, "food"),
    (lambda d, a: re.search(r"\brappi\b|\bpedidos\s*ya\b|\buber\s*eats\b|\bcornershop\b", d, re.I) is not None, "food"),
    (lambda d, a: re.search(r"\boxxo\b|\baramco\b|\btake\s*[&y]?\s*go\b|\bpronto\s*copec\b", d, re.I) is not None, "food"),
    (lambda d, a: re.search(r"\buber\b(?!\s*eats)|\bcabify\b|\bindriver\b|\bdidi\b|\beasy\s*taxi\b", d, re.I) is not None, "transport"),
    (lambda d, a: re.search(r"\bfalabella\b|\bripley\b|\bhites\b|\bsodimac\b|\bhomecenter\b", d, re.I) is not None, "shopping"),
    (lambda d, a: re.search(r"\bisapre\b|\bfonasa\b|\bbanmedica\b|\bconsalud\b|\bcolmena\b|\bvidaintegra\b|\bintegram[eé]dica\b", d, re.I) is not None, "health"),
    (lambda d, a: re.search(r"\bchilectra\b|\benel\b(?!\s*x)|\baguas\s+andinas\b|\bmetrogas\b|\bessbio\b|\besval\b", d, re.I) is not None, "utilities"),
]


def _apply_layer1(description: str, amount: int) -> str | None:
    desc_l = description.lower() if description else ""
    for predicate, cat in _RULES:
        if predicate(desc_l, amount):
            return cat
    return None


# ── Normalización ─────────────────────────────────────────────────────────────

def normalize_merchant(description: str) -> str:
    """Limpia descripciones bancarias para usar como key de cache."""
    s = description.lower()
    s = re.sub(r"^pago\s*:\s*", "", s)
    s = re.sub(r"^cargo\s*:\s*", "", s)
    s = re.sub(r"^compra\s+comercio\s*", "", s)
    s = re.sub(r"^compra\s+internet\s*", "", s)
    s = re.sub(r"^pago\s+internet\s*", "", s)
    s = re.sub(r"mercadopago\*", "mercadopago ", s)
    s = re.sub(r"[*_\-.]{2,}", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()[:60]


def _key_variants(merchant_key: str) -> list[str]:
    """`'jumbo las condes' → ['jumbo las condes', 'jumbo las', 'jumbo']`."""
    if not merchant_key:
        return []
    words = [w for w in merchant_key.split(" ") if w]
    return [" ".join(words[:i]) for i in range(len(words), 0, -1)]


# ── CAPA 2: Cache con prefix matching ────────────────────────────────────────

async def _lookup_cache(merchant_keys: list[str]) -> dict[str, str]:
    if not merchant_keys:
        return {}
    all_variants = sorted({v for k in merchant_keys for v in _key_variants(k)})
    if not all_variants:
        return {}

    engine: AsyncEngine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("SELECT merchant_key, category FROM public.merchant_categories WHERE merchant_key = ANY(:keys)"),
            {"keys": all_variants},
        )
        rows = rs.fetchall()

    variant_map = {r.merchant_key: r.category for r in rows}
    out: dict[str, str] = {}
    for key in merchant_keys:
        for v in _key_variants(key):
            if v in variant_map:
                out[key] = variant_map[v]
                break
    return out


async def _save_to_cache(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    engine: AsyncEngine = get_engine()
    async with engine.begin() as conn:
        for e in entries:
            try:
                await conn.execute(
                    text("""
                        SELECT public.upsert_merchant_category(
                            :p_merchant_key, :p_category, :p_source, :p_confidence
                        )
                    """),
                    {
                        "p_merchant_key": e["merchant_key"],
                        "p_category":     e["category"],
                        "p_source":       e.get("source", "ai"),
                        "p_confidence":   e.get("confidence"),
                    },
                )
            except Exception as exc:
                logger.warning("cache_write_failed", merchant=e["merchant_key"], error=str(exc))


# ── CAPA 3: Claude Haiku ──────────────────────────────────────────────────────

_CATEGORIZER_SYSTEM = """Eres un clasificador de transacciones bancarias chilenas.
Recibirás nombres de comercios ya normalizados (sin "Pago:", en minúsculas).
Responde SOLO con un array JSON. Sin texto extra, sin markdown.

Categorías:
food         → supermercados, restoranes, cafeterías, delivery, kioscos, conveniencia, almacenes
transport    → metro, uber, cabify, taxi, bencina, peajes, estacionamiento, buses, vuelos
subscriptions → streaming (netflix,spotify,disney+), software SaaS, membresías digitales
entertainment → cines, juegos, eventos, bares, discotecas, libros
health       → farmacias, médicos, clínicas, ópticas, isapre, laboratorios
education    → universidades, colegios, cursos, academias, preuniversitarios
housing      → arriendo, dividendo, condominio, gastos comunes, mudanza
insurance    → seguros vida/auto/hogar
utilities    → luz, agua, gas, teléfono, internet, cable
shopping     → ropa, tecnología, muebles, mascotas, retail general
debt_payment → cuotas crédito, pago tarjeta, cuota préstamo
savings      → DAP, fondos mutuos, APV, cuenta ahorro
transfer     → traspasos entre personas
banking_fee  → comisiones, mantención, IVA bancario
other        → solo si realmente no se puede clasificar

Reglas Chile:
- "aramco", "oxxo", "take go", "pronto copec" → food
- "jumbo las condes", "lider pudahuel" (ciudad al final) → food por el supermercado
- "mimar", "petco", "puppis" → shopping
- "mercadopago" + nombre → categoriza por el negocio que sigue
- confidence < 0.75 → usar "other"

Formato EXACTO (solo esto):
[{"key":"nombre","category":"food","confidence":0.95},...]"""


async def _categorize_with_ai(merchant_keys: list[str]) -> dict[str, str]:
    if not merchant_keys:
        return {}
    client = anthropic.AsyncAnthropic()
    try:
        resp = await client.messages.create(
            model=settings.categorize_anthropic_model,
            max_tokens=1024,
            system=_CATEGORIZER_SYSTEM,
            messages=[{"role": "user", "content": f"Clasifica:\n{json.dumps(merchant_keys)}"}],
        )
        raw = resp.content[0].text.strip() if resp.content else "[]"
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.I).strip()
        items = json.loads(cleaned)

        result: dict[str, str] = {}
        to_cache: list[dict[str, Any]] = []
        thr = settings.categorize_confidence_threshold
        for item in items:
            cat = item.get("category", "other")
            conf = item.get("confidence", 0.0) or 0.0
            if conf < thr or cat not in CATEGORIES:
                cat = "other"
            key = item.get("key")
            if key:
                result[key] = cat
                to_cache.append({"merchant_key": key, "category": cat, "source": "ai", "confidence": conf})

        if to_cache:
            await _save_to_cache(to_cache)
        return result
    except Exception as exc:
        logger.error("ai_categorize_failed", error=str(exc))
        return {}


# ── Función principal ────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CategorizedItem:
    idx: int                    # índice original en la lista de entrada
    raw_description: str
    merchant_key: str
    amount: int
    category: str               # categoría final
    label: str                  # etiqueta es-CL para UI
    source: str                 # "rule" | "cache" | "ai" | "fallback"


async def categorize_movements(
    movements: list[dict[str, Any]],
) -> list[CategorizedItem]:
    """
    Categoriza una lista de movimientos en 3 capas. Devuelve un item por
    movimiento de entrada, en el mismo orden.
    
    Cada `movement` debe tener al menos `amount` (int) y `description` (str).
    """
    out: list[CategorizedItem | None] = [None] * len(movements)
    needs_cache: list[tuple[int, str, int, str]] = []  # (idx, mkey, amount, raw)

    # Capa 1
    for i, m in enumerate(movements):
        amount = int(m.get("amount", 0) or 0)
        raw = (m.get("description") or "").strip()
        if amount == 0:
            continue
        cat = _apply_layer1(raw, amount)
        if cat:
            out[i] = CategorizedItem(
                idx=i, raw_description=raw, merchant_key=normalize_merchant(raw),
                amount=amount, category=cat, label=CATEGORY_LABELS[cat], source="rule",
            )
        else:
            needs_cache.append((i, normalize_merchant(raw), amount, raw))

    # Capa 2
    cache_keys = sorted({mkey for _, mkey, _, _ in needs_cache if mkey})
    cache_hits = await _lookup_cache(cache_keys)
    needs_ai: list[tuple[int, str, int, str]] = []
    for i, mkey, amount, raw in needs_cache:
        if mkey in cache_hits:
            cat = cache_hits[mkey]
            out[i] = CategorizedItem(
                idx=i, raw_description=raw, merchant_key=mkey,
                amount=amount, category=cat, label=CATEGORY_LABELS.get(cat, "Gasto"), source="cache",
            )
        else:
            needs_ai.append((i, mkey, amount, raw))

    # Capa 3 (en batches)
    if needs_ai:
        ai_keys = sorted({mkey for _, mkey, _, _ in needs_ai if mkey})
        ai_results: dict[str, str] = {}
        bs = settings.categorize_max_keys_per_ai_call
        for j in range(0, len(ai_keys), bs):
            batch = ai_keys[j:j + bs]
            ai_results.update(await _categorize_with_ai(batch))

        for i, mkey, amount, raw in needs_ai:
            cat = ai_results.get(mkey, "other")
            source = "ai" if mkey in ai_results else "fallback"
            out[i] = CategorizedItem(
                idx=i, raw_description=raw, merchant_key=mkey,
                amount=amount, category=cat, label=CATEGORY_LABELS.get(cat, "Gasto"), source=source,
            )

    # Rellenar huecos (movimientos con amount=0 saltados arriba)
    for i, m in enumerate(movements):
        if out[i] is None:
            raw = (m.get("description") or "").strip()
            out[i] = CategorizedItem(
                idx=i, raw_description=raw, merchant_key=normalize_merchant(raw),
                amount=int(m.get("amount", 0) or 0),
                category="other", label=CATEGORY_LABELS["other"], source="fallback",
            )

    logger.info(
        "categorize_done",
        total=len(movements),
        rule=sum(1 for x in out if x and x.source == "rule"),
        cache=sum(1 for x in out if x and x.source == "cache"),
        ai=sum(1 for x in out if x and x.source == "ai"),
        fallback=sum(1 for x in out if x and x.source == "fallback"),
    )
    return [x for x in out if x is not None]
```

> El sistema de votos crowdsourced que mencionaste (los usuarios marcan manualmente comercios y la confianza sube con N votos) está fuera de scope de Fase 6. Está documentado en §4 como TODO de Fase 8.

### 2.5 `src/sky/worker/banking_sync.py` — orquestador con advisory lock

**NUEVO archivo.** Reemplaza la función inline del Node `bankSyncService.syncBankAccount`. Vive en `worker/` porque solo el worker tiene browser pool.

```python
"""
sky.worker.banking_sync — Orquestador de sync por cuenta bancaria.

Llamado por el job `sync_bank_account_job`. Toma:
    - bank_account_id (uuid)
    - user_id (uuid)
Usa:
    - `IngestionRouter` (ya construido en `ctx["router"]`)
    - `pg_try_advisory_lock` para evitar syncs duplicados (cierra BUG-3)
    - `INSERT ... ON CONFLICT (user_id, bank_account_id, external_id) DO NOTHING`
      para idempotencia (cierra BUG-1, BUG-2)

Devuelve dict con:
    - success: bool
    - new_transactions: int
    - balance: int (CLP) | None
    - bank_id: str
    - elapsed_ms: int
    - skipped: bool (True si advisory lock estaba tomado)

NUNCA logea credenciales ni descrifa fuera del scope necesario.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.encryption import decrypt
from sky.core.errors import (
    AllSourcesFailedError,
    AuthenticationError,
    DataSourceNotFoundError,
)
from sky.core.locks import try_advisory_lock
from sky.core.logging import get_logger
from sky.ingestion.contracts import BankCredentials
from sky.ingestion.routing.router import IngestionRouter

logger = get_logger("banking_sync")


async def sync_bank_account(
    *,
    router: IngestionRouter,
    bank_account_id: str,
    user_id: str,
    arq_pool: Any,  # ArqRedis para encolar categorize_pending_job al final
) -> dict[str, Any]:
    """Sincroniza UNA cuenta bancaria. Idempotente. Lock por bank_account_id."""
    started_at = datetime.utcnow()

    async with try_advisory_lock(f"sync:bank_account:{bank_account_id}") as got:
        if not got:
            logger.info("sync_skipped_locked", bank_account_id=bank_account_id)
            return {"skipped": True, "reason": "lock_held"}

        engine = get_engine()
        async with engine.begin() as conn:
            row = (await conn.execute(
                text("""
                    SELECT id, user_id, bank_id, encrypted_rut, encrypted_pass,
                           sync_count, consecutive_errors
                      FROM public.bank_accounts
                     WHERE id = :id AND user_id = :uid AND status != 'disconnected'
                """),
                {"id": bank_account_id, "uid": user_id},
            )).mappings().first()
            if row is None:
                raise DataSourceNotFoundError(f"bank_account not found: {bank_account_id}")

            await conn.execute(
                text("""
                    UPDATE public.bank_accounts
                       SET status = 'active',
                           last_sync_error = NULL,
                           last_scheduled_at = NOW(),
                           updated_at = NOW()
                     WHERE id = :id
                """),
                {"id": bank_account_id},
            )

        # Descifrar credenciales SOLO en memoria.
        rut = decrypt(row["encrypted_rut"])
        password = decrypt(row["encrypted_pass"])
        creds = BankCredentials(rut=rut, password=password)
        bank_id = row["bank_id"]

        try:
            result = await router.ingest(bank_id=bank_id, user_id=user_id, credentials=creds)
        except AuthenticationError as exc:
            await _mark_error(bank_account_id, "Credenciales rechazadas por el banco")
            raise
        except AllSourcesFailedError as exc:
            await _mark_error(bank_account_id, _sanitize_error(str(exc)))
            raise
        finally:
            # No persistir credenciales en variables locales más tiempo del necesario.
            del rut, password, creds

        inserted = await _persist_movements(
            user_id=user_id,
            bank_account_id=bank_account_id,
            movements=result.movements,
        )

        await _update_account_after_sync(
            bank_account_id=bank_account_id,
            balance=result.balance.balance_clp if result.balance else None,
            sync_count=row["sync_count"] or 0,
        )

        # Encolar categorización si insertamos algo nuevo.
        if inserted > 0:
            await arq_pool.enqueue_job("categorize_pending_job")

        elapsed_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
        logger.info(
            "sync_completed",
            bank_account_id=bank_account_id, bank_id=bank_id,
            new_transactions=inserted, elapsed_ms=elapsed_ms,
        )

        return {
            "success": True,
            "new_transactions": inserted,
            "balance": result.balance.balance_clp if result.balance else None,
            "bank_id": bank_id,
            "elapsed_ms": elapsed_ms,
        }


async def _persist_movements(
    *, user_id: str, bank_account_id: str, movements: list[Any],
) -> int:
    """
    Inserta movimientos con `categorization_status='pending'`. Idempotente vía
    UNIQUE INDEX (user_id, bank_account_id, external_id). Devuelve el conteo
    real de filas insertadas.
    """
    if not movements:
        return 0
    engine = get_engine()
    inserted = 0
    async with engine.begin() as conn:
        for m in movements:
            res = await conn.execute(
                text("""
                    INSERT INTO public.transactions
                        (user_id, bank_account_id, amount, category, description,
                         raw_description, date, external_id, movement_source,
                         categorization_status)
                    VALUES
                        (:user_id, :bank_account_id, :amount, 'other', 'Procesando...',
                         :raw_description, :date, :external_id, :movement_source,
                         'pending')
                    ON CONFLICT (user_id, bank_account_id, external_id)
                    WHERE external_id IS NOT NULL
                    DO NOTHING
                """),
                {
                    "user_id":         user_id,
                    "bank_account_id": bank_account_id,
                    "amount":          m.amount_clp,
                    "raw_description": m.raw_description,
                    "date":            m.occurred_at,
                    "external_id":     m.external_id,
                    "movement_source": m.movement_source.value,
                },
            )
            if res.rowcount and res.rowcount > 0:
                inserted += 1
    return inserted


async def _update_account_after_sync(
    *, bank_account_id: str, balance: int | None, sync_count: int,
) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE public.bank_accounts
                   SET last_sync_at = NOW(),
                       last_sync_error = NULL,
                       last_balance = COALESCE(:balance, last_balance),
                       status = 'active',
                       sync_count = :sync_count,
                       consecutive_errors = 0,
                       updated_at = NOW()
                 WHERE id = :id
            """),
            {"id": bank_account_id, "balance": balance, "sync_count": sync_count + 1},
        )


async def _mark_error(bank_account_id: str, msg: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE public.bank_accounts
                   SET status = 'error',
                       last_sync_error = :msg,
                       consecutive_errors = COALESCE(consecutive_errors, 0) + 1,
                       updated_at = NOW()
                 WHERE id = :id
            """),
            {"id": bank_account_id, "msg": msg[:500]},
        )


def _sanitize_error(msg: str) -> str:
    """Eliminar PII y stack traces antes de mostrar al usuario."""
    if not msg:
        return "Error de sincronización"
    import re as _re
    if _re.search(r"password|rut|clave|credential", msg, _re.I):
        return "Error de autenticación bancaria"
    if _re.search(r"ETIMEDOUT|ECONNREFUSED|timeout", msg, _re.I):
        return "El banco no respondió. Intenta más tarde."
    return msg[:200]
```

### 2.6 `src/sky/worker/jobs/sync.py` — jobs ARQ

**NUEVO archivo.**

```python
"""
sky.worker.jobs.sync — ARQ jobs de sincronización bancaria.

Funciones registradas:
    - sync_bank_account_job(account_id, user_id): sync de UNA cuenta.
    - sync_all_user_accounts_job(user_id): encola N jobs (uno por cuenta activa).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.worker.banking_sync import sync_bank_account

logger = get_logger("jobs.sync")


async def sync_bank_account_job(
    ctx: dict[str, Any],
    bank_account_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Job ARQ: sincroniza UNA cuenta bancaria."""
    router = ctx["router"]
    arq_pool = ctx["arq_pool"]
    return await sync_bank_account(
        router=router,
        bank_account_id=bank_account_id,
        user_id=user_id,
        arq_pool=arq_pool,
    )


async def sync_all_user_accounts_job(
    ctx: dict[str, Any],
    user_id: str,
) -> dict[str, Any]:
    """
    Job ARQ: encola un job de sync por cada cuenta activa del user.
    NO sincroniza secuencialmente — cada cuenta corre como job propio,
    permitiendo paralelismo limitado por el browser pool del worker.
    Cierra BUG-4 (sync secuencial entre bancos del mismo user).
    """
    arq_pool = ctx["arq_pool"]
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id FROM public.bank_accounts
                 WHERE user_id = :uid AND status != 'disconnected'
            """),
            {"uid": user_id},
        )
        ids = [row[0] for row in rs.fetchall()]

    enqueued = 0
    for account_id in ids:
        await arq_pool.enqueue_job("sync_bank_account_job", str(account_id), user_id)
        enqueued += 1

    logger.info("sync_all_enqueued", user_id=user_id, count=enqueued)
    return {"enqueued": enqueued}
```

### 2.7 `src/sky/worker/jobs/categorize.py` — categorize_pending_job

**NUEVO archivo.**

```python
"""
sky.worker.jobs.categorize — Procesamiento de cola de categorización.

Toma hasta CATEGORIZE_BATCH_SIZE filas con categorization_status='pending',
las pasa por las 3 capas, y aplica el resultado.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.domain.categorizer import CATEGORY_LABELS, categorize_movements

logger = get_logger("jobs.categorize")


async def categorize_pending_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """Job ARQ: categoriza hasta BATCH_SIZE filas pendientes."""
    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT id, raw_description, amount
                  FROM public.transactions
                 WHERE categorization_status = 'pending'
                 ORDER BY created_at ASC
                 LIMIT :batch
            """),
            {"batch": settings.categorize_batch_size},
        )
        rows = rs.mappings().all()

    if not rows:
        return {"processed": 0, "skipped": True}

    movements = [
        {"description": r["raw_description"] or "", "amount": int(r["amount"] or 0)}
        for r in rows
    ]
    items = await categorize_movements(movements)

    # items viene en el mismo orden que movements; filas viene en el mismo orden
    # que rows. Las posiciones coinciden.
    succeeded = failed = 0
    async with engine.begin() as conn:
        for row, item in zip(rows, items, strict=True):
            new_status = "failed" if item.category == "other" and item.source == "fallback" else "done"
            try:
                await conn.execute(
                    text("""
                        UPDATE public.transactions
                           SET category = :cat,
                               description = :label,
                               categorization_status = :status
                         WHERE id = :id
                    """),
                    {
                        "id":     row["id"],
                        "cat":    item.category,
                        "label":  item.label,
                        "status": new_status,
                    },
                )
                succeeded += 1
            except Exception as exc:
                logger.error("update_failed", id=str(row["id"]), error=str(exc))
                failed += 1

    logger.info("categorize_batch_done", processed=succeeded, failed=failed)
    return {"processed": succeeded, "failed": failed}
```

### 2.8 `src/sky/worker/main.py` — registrar jobs y exponer arq_pool en ctx

Modificación quirúrgica. Agregar a `WorkerSettings.functions` y al startup `ctx["arq_pool"]`:

```python
# Imports nuevos
from arq import create_pool
from arq.connections import RedisSettings

from sky.worker.jobs.sync import sync_bank_account_job, sync_all_user_accounts_job
from sky.worker.jobs.categorize import categorize_pending_job


async def startup(ctx: dict[str, Any]) -> None:
    # ... (lo que ya hay) ...
    router, redis = await build_router(include_browser_sources=True)
    ctx["router"] = router
    ctx["redis"] = redis
    # NUEVO: pool de ARQ para encolar jobs desde dentro de otros jobs
    ctx["arq_pool"] = await create_pool(
        RedisSettings.from_dsn(settings.redis_url)
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    # ... (lo que ya hay) ...
    arq_pool = ctx.get("arq_pool")
    if arq_pool:
        await arq_pool.aclose()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    functions = [
        sync_bank_account_job,
        sync_all_user_accounts_job,
        categorize_pending_job,
    ]
    queue_name = "sky:default"  # cola única por ahora; separación viene en Fase 9
    max_jobs = settings.browser_pool_size * 2
```

### 2.9 `src/sky/api/main.py` — exponer arq_pool en lifespan

Cambio mínimo:

```python
from arq import create_pool
from arq.connections import RedisSettings

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging(json_output=settings.is_production)
    logger.info("api_starting", port=settings.port)

    router, redis = await build_router(include_browser_sources=False)
    app.state.router = router
    app.state.redis = redis
    # NUEVO: pool de ARQ para encolar desde routers
    app.state.arq_pool = await create_pool(
        RedisSettings.from_dsn(settings.redis_url)
    )

    yield

    await app.state.arq_pool.aclose()
    await redis.aclose()
    await close_engine()
    logger.info("api_stopped")
```

### 2.10 `src/sky/api/schemas/banking.py` — Pydantic v2

**Reemplazar el archivo completo.**

```python
"""sky.api.schemas.banking — Schemas Pydantic para endpoints bancarios."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SyncBankAccountResponse(BaseModel):
    started: bool = True
    job_id: str = Field(..., description="ARQ job_id para poll opcional")


class SyncAllResponse(BaseModel):
    started: bool = True
    job_id: str
```

### 2.11 `src/sky/api/routers/banking.py` — endpoint que solo encola

**Reemplazar el archivo completo.** Solo expone el sync por ahora; los endpoints de listado/conexión/desconexión son Fase 7.

```python
"""sky.api.routers.banking — Endpoints bancarios (Fase 6 = solo sync)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from sky.api.deps import require_user_id
from sky.api.schemas.banking import SyncAllResponse, SyncBankAccountResponse
from sky.core.logging import get_logger

logger = get_logger("api.banking")
router = APIRouter(prefix="/api/banking", tags=["banking"])


@router.post("/sync/{account_id}", response_model=SyncBankAccountResponse)
async def sync_bank_account_endpoint(
    account_id: str,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> SyncBankAccountResponse:
    """
    Encola un sync de la cuenta indicada. Responde inmediato `{started: true}`.
    El frontend hace polling sobre `/api/banking/accounts` (Fase 7) para ver
    el progreso real.
    """
    arq_pool = request.app.state.arq_pool
    job = await arq_pool.enqueue_job(
        "sync_bank_account_job",
        account_id,
        user_id,
    )
    if job is None:
        raise HTTPException(503, "No se pudo encolar el sync. Reintenta.")
    return SyncBankAccountResponse(started=True, job_id=job.job_id)


@router.post("/sync-all", response_model=SyncAllResponse)
async def sync_all_endpoint(
    request: Request,
    user_id: str = Depends(require_user_id),
) -> SyncAllResponse:
    """Encola un sync de TODAS las cuentas activas del user."""
    arq_pool = request.app.state.arq_pool
    job = await arq_pool.enqueue_job("sync_all_user_accounts_job", user_id)
    if job is None:
        raise HTTPException(503, "No se pudo encolar el sync. Reintenta.")
    return SyncAllResponse(started=True, job_id=job.job_id)
```

Y montar el router en `api/main.py`:
```python
from sky.api.routers import banking
app.include_router(banking.router)
```

### 2.12 `migrations/002_indexes_and_constraints.sql` — NUEVO

```sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Migración 002 — Índices para Fase 6 (Queue ARQ)
-- Ejecutar después de 001_routing_rules.sql
-- ─────────────────────────────────────────────────────────────────────────────

-- BUG-2 cierre definitivo: el unique index ya está en 000_immediate_fixes.sql
-- (uniq_tx_external). Validamos que existe; si no, este script lo agrega.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_tx_external
  ON public.transactions (user_id, bank_account_id, external_id)
  WHERE external_id IS NOT NULL;

-- Índice parcial para que categorize_pending_job sea barato a volumen alto.
-- Sin esto, la query "SELECT ... WHERE categorization_status='pending'"
-- escanea toda la tabla cuando hay millones de filas.
CREATE INDEX IF NOT EXISTS idx_transactions_pending
  ON public.transactions (created_at)
  WHERE categorization_status = 'pending';

-- Reforzar idx_tx_user_date e idx_tx_bank_account si no existen.
CREATE INDEX IF NOT EXISTS idx_tx_user_date
  ON public.transactions (user_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_tx_bank_account
  ON public.transactions (bank_account_id, external_id)
  WHERE external_id IS NOT NULL;

-- Validar que merchant_categories tiene unique key (ya en 000)
CREATE UNIQUE INDEX IF NOT EXISTS uniq_merchant_key
  ON public.merchant_categories (merchant_key);

-- ── Verificación ─────────────────────────────────────────────────────────
-- SELECT indexname FROM pg_indexes
--  WHERE tablename = 'transactions'
--    AND (indexname LIKE 'uniq_%' OR indexname LIKE 'idx_tx_%' OR indexname LIKE 'idx_transactions_%')
--  ORDER BY indexname;
-- Esperado: idx_transactions_pending, idx_tx_bank_account, idx_tx_user_date, uniq_tx_external
```

### 2.13 Tests nuevos

#### `tests/unit/test_categorizer.py`

Golden cases por categoría. Mock de `_lookup_cache` y `_categorize_with_ai`.

```python
"""Tests del categorizador 3 capas."""
from unittest.mock import AsyncMock, patch

import pytest

from sky.domain.categorizer import (
    CATEGORY_LABELS, _apply_layer1, categorize_movements, normalize_merchant,
)


class TestNormalizeMerchant:
    def test_strips_pago_prefix(self) -> None:
        assert normalize_merchant("PAGO: STARBUCKS MALL") == "starbucks mall"

    def test_strips_compra_comercio(self) -> None:
        assert normalize_merchant("COMPRA COMERCIO JUMBO LAS CONDES") == "jumbo las condes"

    def test_collapses_dashes(self) -> None:
        assert normalize_merchant("UBER--EATS--CL") == "uber eats cl"

    def test_caps_at_60_chars(self) -> None:
        long = "x" * 100
        assert len(normalize_merchant(long)) == 60


class TestLayer1Rules:
    @pytest.mark.parametrize("desc,amount,expected", [
        ("Traspaso de: Juan Perez", 50000, "income"),
        ("ABONO REMUNERACION SUELDO", 800000, "income"),
        ("Traspaso a: Ahorro", -10000, "transfer"),
        ("Khipu", -5000, "transfer"),
        ("Comision mantencion cta", -1500, "banking_fee"),
        ("BIP! Recarga", -3000, "transport"),
        ("COPEC PEAJE", -25000, "transport"),
        ("Netflix Suscripcion", -8500, "subscriptions"),
        ("Pago: Entel Movil", -25000, "utilities"),
        ("Salcobrand Vitacura", -12000, "health"),
        ("Pago TC Bchile", -200000, "debt_payment"),
        ("Aporte AFP", -50000, "savings"),
        ("Jumbo Las Condes", -45000, "food"),
        ("Starbucks Costanera", -5500, "food"),
        ("Rappi Restaurant", -12000, "food"),
        ("Uber Trip", -8500, "transport"),
        ("Falabella Online", -75000, "shopping"),
        ("Isapre Banmedica", -180000, "health"),
        ("Aguas Andinas", -25000, "utilities"),
    ])
    def test_rule_matches(self, desc: str, amount: int, expected: str) -> None:
        assert _apply_layer1(desc, amount) == expected

    def test_unknown_returns_none(self) -> None:
        assert _apply_layer1("FOO BAR XYZ", -1000) is None


@pytest.mark.asyncio
@patch("sky.domain.categorizer._lookup_cache", new_callable=AsyncMock)
@patch("sky.domain.categorizer._categorize_with_ai", new_callable=AsyncMock)
async def test_three_layers_priority(mock_ai: AsyncMock, mock_cache: AsyncMock) -> None:
    """Layer 1 gana sobre cache y AI. Cache gana sobre AI."""
    mock_cache.return_value = {"misterio": "shopping"}
    mock_ai.return_value = {"raro nuevo": "entertainment"}

    movements = [
        {"description": "Jumbo Las Condes", "amount": -10000},   # Layer 1 → food
        {"description": "Misterio Compras", "amount": -5000},    # Layer 2 → shopping
        {"description": "Raro Nuevo", "amount": -3000},          # Layer 3 → entertainment
    ]
    items = await categorize_movements(movements)
    assert items[0].category == "food"     and items[0].source == "rule"
    assert items[1].category == "shopping" and items[1].source == "cache"
    assert items[2].category == "entertainment" and items[2].source == "ai"


@pytest.mark.asyncio
@patch("sky.domain.categorizer._lookup_cache", new_callable=AsyncMock)
@patch("sky.domain.categorizer._categorize_with_ai", new_callable=AsyncMock)
async def test_ai_failure_falls_back_to_other(mock_ai: AsyncMock, mock_cache: AsyncMock) -> None:
    mock_cache.return_value = {}
    mock_ai.return_value = {}  # AI no devolvió nada

    items = await categorize_movements([{"description": "completamente desconocido", "amount": -5000}])
    assert items[0].category == "other"
    assert items[0].source == "fallback"


@pytest.mark.asyncio
async def test_zero_amount_returns_other_fallback() -> None:
    items = await categorize_movements([{"description": "Anything", "amount": 0}])
    assert items[0].category == "other"
```

#### `tests/unit/test_advisory_lock.py`

```python
"""Tests de pg_try_advisory_lock wrapper."""
import pytest

from sky.core.locks import _key_from_string


def test_key_is_deterministic() -> None:
    assert _key_from_string("foo") == _key_from_string("foo")


def test_key_changes_with_input() -> None:
    assert _key_from_string("foo") != _key_from_string("bar")


def test_key_fits_int64() -> None:
    k = _key_from_string("sync:bank_account:abc-def")
    assert -(2**63) <= k <= (2**63 - 1)


# Test de adquisición real requiere DB → vive en tests/integration
```

#### `tests/unit/test_sync_job.py`

```python
"""Tests unitarios de sync_bank_account_job con mocks."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sky.ingestion.contracts import (
    AccountBalance, CanonicalMovement, IngestionResult,
    MovementSource, SourceKind,
)
from sky.worker.banking_sync import sync_bank_account


@pytest.fixture
def fake_router() -> MagicMock:
    r = MagicMock()
    r.ingest = AsyncMock(return_value=IngestionResult(
        balance=AccountBalance(balance_clp=1_000_000, as_of=None),
        movements=[
            CanonicalMovement(
                external_id="bchile_abc123",
                amount_clp=-5000,
                raw_description="STARBUCKS",
                occurred_at=date(2026, 4, 15),
                movement_source=MovementSource.ACCOUNT,
                source_kind=SourceKind.SCRAPER,
            )
        ],
        source_kind=SourceKind.SCRAPER,
        source_identifier="scraper.bchile",
        elapsed_ms=12_345,
    ))
    return r


@pytest.fixture
def fake_arq_pool() -> MagicMock:
    p = MagicMock()
    p.enqueue_job = AsyncMock()
    return p


@pytest.mark.asyncio
@patch("sky.worker.banking_sync.try_advisory_lock")
@patch("sky.worker.banking_sync._persist_movements", new_callable=AsyncMock)
@patch("sky.worker.banking_sync._update_account_after_sync", new_callable=AsyncMock)
@patch("sky.worker.banking_sync.get_engine")
@patch("sky.worker.banking_sync.decrypt", side_effect=lambda x: f"decrypted_{x}")
async def test_sync_returns_skipped_when_lock_held(
    _decrypt, _engine, _update, _persist, mock_lock,
    fake_router, fake_arq_pool,
):
    # advisory lock devuelve False (otro worker tiene el lock)
    cm = AsyncMock()
    cm.__aenter__.return_value = False
    cm.__aexit__.return_value = None
    mock_lock.return_value = cm

    out = await sync_bank_account(
        router=fake_router,
        bank_account_id=str(uuid4()),
        user_id=str(uuid4()),
        arq_pool=fake_arq_pool,
    )
    assert out["skipped"] is True


# Tests más profundos de persistencia + advisory lock real → tests/integration
```

#### `tests/integration/test_sync_job.py`

```python
"""
Integration test del job sync_bank_account_job.

Requiere:
    - DB de staging con tabla `bank_accounts` y `transactions`
    - Redis local (o fakeredis con ARQ)
    - Una cuenta de test con credenciales válidas (skip si no está configurada)
"""
import os

import pytest


@pytest.mark.skipif(
    not os.getenv("INTEGRATION_TEST_BANK_ACCOUNT_ID"),
    reason="No INTEGRATION_TEST_BANK_ACCOUNT_ID env var; salteando integration test",
)
@pytest.mark.asyncio
async def test_sync_persists_movements_and_enqueues_categorize() -> None:
    # TODO(equipo): cuando tengamos cuenta de test con creds válidas,
    # poblar este test:
    #   1. Crear bank_account con creds reales
    #   2. Llamar sync_bank_account_job
    #   3. Verificar transactions inserted con categorization_status='pending'
    #   4. Llamar categorize_pending_job
    #   5. Verificar que pasaron a 'done' o 'failed'
    pytest.skip("Pendiente — requiere cuenta de test con creds válidas")
```

### 2.14 `docs/MIGRATION_13_PHASES.md` — marcar Fase 6 cerrada

Reemplazar el bloque "Estimación: 1 semana" de Fase 6 por:

```
### Estado: ✅ Cerrada (YYYY-MM-DD)

Archivos finales:
- src/sky/domain/categorizer.py             (3 capas: regex + cache + Claude Haiku)
- src/sky/worker/banking_sync.py            (orquestador con advisory lock)
- src/sky/worker/jobs/sync.py               (sync_bank_account_job, sync_all_user_accounts_job)
- src/sky/worker/jobs/categorize.py         (categorize_pending_job)
- src/sky/worker/main.py                    (registra functions + arq_pool en ctx)
- src/sky/api/main.py                       (arq_pool en app.state)
- src/sky/api/routers/banking.py            (POST /api/banking/sync/:id, /sync-all)
- src/sky/api/schemas/banking.py
- src/sky/core/locks.py                     (try_advisory_lock async)
- migrations/002_indexes_and_constraints.sql
- tests/unit/test_categorizer.py            (golden cases)
- tests/unit/test_advisory_lock.py
- tests/unit/test_sync_job.py
- tests/integration/test_sync_job.py        (gate manual con cuenta real)

Bugs cerrados: BUG-1 (external_id determinístico), BUG-2 (UNIQUE INDEX),
BUG-3 (advisory lock), BUG-4 (browser pool paralelo).

Gates verificados:
- [x] pytest tests/unit/ -v               → todos pasan
- [x] coverage ≥ 85% en domain/categorizer + worker/banking_sync
- [x] mypy src/sky/                       → 0 errores
- [x] ruff check src/sky/ tests/          → 0 errores
- [x] migración 002 aplicada en staging y prod
- [x] arq sky.worker.main.WorkerSettings  → arranca limpio
- [x] sync end-to-end con cuenta real     → movimientos persisten
- [x] segundo sync no inserta duplicados  → idempotencia OK
```

---

## 3. Verificación final (gate humano antes de cerrar)

Ejecutar exactamente, en orden:

```powershell
cd backend-python
.venv\Scripts\activate

# 1. Calidad estática
ruff check src/sky/ tests/
mypy src/sky/

# 2. Tests unitarios
pytest tests/unit/ -v --cov=src/sky --cov-report=term-missing

# 3. Smoke local — Redis + DB + worker
docker run -d --rm -p 6379:6379 --name sky-redis-fase6 redis:7-alpine
$env:REDIS_URL = "redis://localhost:6379"

# 3a. Worker arranca
arq sky.worker.main.WorkerSettings
# Esperado: log "router_built sources=N rules=M with_browser=True" + "worker_ready"
# Ctrl+C para detener.

# 4. API arranca y encola
uvicorn sky.api.main:app --port 8000 &
Start-Sleep 2
# Suponiendo que tienes un JWT válido y un bank_account_id real:
curl -X POST http://localhost:8000/api/banking/sync/$ACCOUNT_ID `
     -H "Authorization: Bearer $JWT"
# Esperado: {"started":true,"job_id":"..."}

# 5. Verificar en Supabase: SELECT count(*) FROM transactions WHERE bank_account_id=$ACCOUNT_ID;
#    Antes y después del sync — diferencia = movimientos nuevos.

docker stop sky-redis-fase6
```

Cada comando debe terminar con exit code 0. Si alguno falla, **no marcar Fase 6 como cerrada**.

---

## 4. Out of scope (no tocar en este PR — TODOs explícitos)

Estos ítems están reconocidos y no se postergan al olvido — quedan registrados con su fase de cierre.

### 4.1 Crowdsourcing de categorías (Fase 8)
Sistema de votos donde el usuario marca manualmente comercios no categorizados, y la confianza sube con N votos de usuarios distintos. Implementación:
- Tabla `merchant_category_votes(user_id, merchant_key, category, voted_at, weight)` — RLS por usuario
- Función `compute_merchant_category(merchant_key)` que agrega votos y devuelve la categoría con mayor consenso si pasa threshold (ej: 3 votos coincidentes).
- Layer 4 del categorizer: si `_categorize_with_ai` devuelve `other`, consultar votos crowdsourced.
- Endpoint `POST /api/transactions/:id/declare-category` para que el usuario declare manualmente.
- UI no-intrusiva: en el listado de transacciones, las que están en `failed` muestran "❓ ¿De qué se trata?" con un menú rápido.

**Por qué no en Fase 6**: Fase 6 es Queue ARQ. Agregar la 4ta capa requiere schema nuevo + endpoint + UI — eso se construye limpio en Fase 7 (endpoint) + Fase 8 (lógica del dominio).

### 4.2 Endpoints bancarios completos (Fase 7)
Hoy solo se expone `POST /api/banking/sync/:id` y `/sync-all`. Falta:
- `GET /api/banking/accounts` (listado con balance, status, lastSyncError, minutesAgo)
- `POST /api/banking/accounts` (conectar nueva cuenta — cifra credenciales)
- `DELETE /api/banking/accounts/:id` (desconectar)
- `GET /api/banking/banks` (listado de bancos soportados desde `SUPPORTED_BANKS`)

### 4.3 Falabella scraper completo (paralelo)
`falabella_scraper.py` sigue como skeleton — lanza `RecoverableIngestionError`. Cuando un user con falabella sincronice, el router intentará la fuente, fallará con recoverable, no hay siguiente en la cadena (`["scraper.falabella"]`), y propaga `AllSourcesFailedError`. El user verá `last_sync_error="…no respondió…"`. **Esto NO bloquea Fase 6** — el sistema es robusto a fuentes incompletas. Falabella se completa en paralelo por el equipo.

### 4.4 BCI scraper end-to-end con cuenta real (gate residual Fase 4)
`bci_direct.py` está parcial. Cuando se tenga una cuenta BCI de pruebas, correr `scripts/test_bci_scraper.py` y validar gates de Fase 4. No bloquea Fase 6.

### 4.5 Separación de colas por tipo de job (Fase 9)
Hoy todos los jobs van a `sky:default`. v5 §16.1 define 5 colas (`api:sync`, `scraper:sync`, `categorization`, `scheduled`, `webhook`). La separación hace falta solo a volumen alto y se hace cuando llegue ese volumen, no antes. Documentado en Fase 9.

### 4.6 Métricas Prometheus por source (Fase 10)
Hoy hay logs estructurados pero no contadores Prometheus. Es trabajo de Fase 10.

### 4.7 Webhook handler (Fase 7+ para Fintoc)
`worker/jobs/webhook.py` es stub. Cuando Fintoc esté integrado, recibirá webhooks de movimientos en push. No es Fase 6.

### 4.8 Re-categorización masiva
Si en el futuro se mejora el categorizer, las filas viejas con `categorization_status='failed'` o categoría errada deben poder re-categorizarse. Endpoint admin futuro: `POST /api/admin/recategorize` que marca filas como pending y deja que `categorize_pending_job` las procese.

---

## 5. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| `pg_try_advisory_lock` no funciona como esperado en Supabase pooler | Verificar en staging primero. Si falla, usar `LOCK TABLE` row-level con `FOR UPDATE SKIP LOCKED` como fallback. |
| `arq.create_pool` requiere config sutilmente distinta a `redis.from_url` | Probar en smoke (paso §3) antes de declarar gate cerrado. |
| Insert masivo uno-a-uno es lento a volumen alto | Para BChile típico (~200 movimientos / sync) está OK. Si llegamos a 10k+ por sync, batch insert con `executemany` o `COPY`. Documentar como TODO cuando se observe. |
| `categorize_pending_job` queda en loop si Anthropic está caído | El path de fallback marca como `failed` cuando el AI falla. No re-encola hasta que un evento futuro las resucite. |
| ARIA escribe sin consent porque `bankSyncService` Node lo hace | Esto es Fase 6 Python — pasamos `user_id` siempre y el guard estricto vive en `domain/aria.py` (Fase 8). En Fase 6 NO disparamos ARIA aún (es Fase 8). Si quieres ARIA en Fase 6, agregamos el call con guard estricto. **Decisión propuesta: NO disparar ARIA en Fase 6, dejarlo para Fase 8 cuando `domain/aria.py` exista.** |
| Imposible probar Falabella en integration | Aceptable — Falabella seguirá fallando con recoverable, es comportamiento esperado. Test de integración cubre BChile. |
| `app.state.arq_pool` no se cierra limpio en shutdown | Verificar en logs de uvicorn que `await app.state.arq_pool.aclose()` se ejecuta sin warnings. |

---

## 6. Checklist final del PR

Antes de cerrar Fase 6:

- [ ] Todos los archivos de §2 creados/modificados
- [ ] `pytest tests/unit/ -v` verde (≥ 30 casos nuevos del categorizer + locks + sync)
- [ ] `pytest --cov=src/sky` ≥ 85% en `domain/categorizer.py` + `worker/banking_sync.py`
- [ ] `mypy src/sky/` sin errores
- [ ] `ruff check src/sky/ tests/` sin errores
- [ ] Migración `002_indexes_and_constraints.sql` aplicada en staging y prod (4 índices verificados)
- [ ] `arq sky.worker.main.WorkerSettings` arranca y registra los 3 jobs
- [ ] `uvicorn sky.api.main:app` arranca, `/api/health` 200, `arq_pool` en `app.state`
- [ ] Sync real con cuenta BChile: `POST /api/banking/sync/:id` → encola → worker procesa → `transactions` rows inserted con `categorization_status='pending'` → `categorize_pending_job` corrió → status `done`/`failed`
- [ ] Segundo sync inmediato del mismo `account_id`: 0 duplicados (advisory lock + ON CONFLICT)
- [ ] `docs/MIGRATION_13_PHASES.md` actualizado (§2.14)
- [ ] Commit message exacto: `Fase 6 cerrada: Queue ARQ con sync_bank_account_job, advisory lock y categorización 3 capas`

---

## 7. Lo que esto deja listo para Fase 7

Fase 7 (FastAPI paridad endpoints Node) recibe:

- `app.state.arq_pool` ya disponible — los routers solo encolan, nunca ejecutan inline.
- `app.state.router` ya disponible para queries síncronas (ej: `GET /api/banking/banks` lee de `SUPPORTED_BANKS`).
- `categorize_movements` ya disponible en `domain/categorizer.py` para que `POST /api/transactions` (creación manual) pueda categorizar al vuelo.
- JWT auth ya funciona en `api/middleware/jwt_auth.py` desde Fase 0 — `require_user_id` en `deps.py` está listo.
- Schema `transactions` con `categorization_status` poblado por jobs reales — los endpoints de listado ya tienen datos verdaderos.

Cuando Fase 6 cierre limpia, los 17 endpoints de Fase 7 se construyen como capa fina sobre lo que ya existe: cada endpoint pesa < 50 LOC porque toda la lógica está abajo.
