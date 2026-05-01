# CLAUDE.md — Sky Finance

> Contexto persistente para sesiones de Claude Code. Léelo antes de tocar nada.
> Mantén este archivo conciso. La fuente de verdad detallada vive en otro lado.

---

## 📜 Fuente de verdad doctrinal

**`C:\Users\crist\OneDrive\Documentos\SkyFinance\Estados del Arte\SkyFinanzas_EstadoDelArte_v5_Documentado.pdf`**

Ese documento está **registrado ante INAPI** (propiedad intelectual, Chile) y es la única fuente autoritativa del producto, arquitectura, deuda y visión. Está dividido deliberadamente en:

- **Parte I** — Estado actual verificado (lo implementado en producción Node.js)
- **Parte II** — Arquitectura objetivo (migración Python — Fases 0-13)
- **Parte III** — Plan de remediación de deuda (P0/P1/P2 + BUG-1 a BUG-4)
- **Parte IV** — Visión, gobierno, doctrina permanente
- **Anexo A** — Estructura de repositorios actual y objetivo

**Regla principal**: si algo en este `CLAUDE.md` contradice al v5, gana el v5. Lee el v5 cuando necesites profundidad. Este archivo solo carga lo esencial para que cada sesión arranque eficiente.

**Cofundadores y titularidad** — SkyFinanzas SpA (RUT 78.395.382-K):
- Cristian Cristóbal Amaru Vásquez Guevara · 22.141.522-1
- Juan José Latorre Pérez · 22.003.365-1

---

## 🎯 Qué es Sky (no perder esto de vista)

Sky NO es una app de gastos con IA. Es un **sistema operativo financiero personal**: capa cognitiva entre la persona y su vida financiera, que absorbe complejidad y devuelve **claridad**.

- **Promesa central**: alivio emocional. La landing dice "Respira. Tus finanzas están en las mejores manos". La promesa es respiratoria antes que cognitiva.
- **Tesis**: la gente no falla por falta de conocimiento, sino por ansiedad/evasión/fricción. La tecnología debe absorber complejidad, no exigir expertise.
- **Tres pilares**: automatización bancaria · interpretación inteligente (Mr. Money) · diseño conductual (metas, desafíos, simulaciones).
- **Mr. Money guía; no decide.** Toda propuesta estructurada (`propose_challenge`, etc.) requiere confirmación explícita del usuario antes de ejecutarse. NO da asesoría de inversión específica, NO recomienda activos puntuales, NO actúa como asesor licenciado, NO garantiza resultados.
- **Marca**: Sky / Sky Finanzas. Personaje IA = Mr. Money. Paleta verde `#00C853`, navy `#0D1B2A`, blanco `#FFFFFF`. Tipografías Instrument Serif + Geist + Geist Mono.

---

## ⚖️ Doctrina inviolable (del Capítulo 26 + Capítulos 4, 8, 13, 14)

Estas reglas sobrescriben conveniencia de corto plazo. No se negocian durante construcción.

1. **El producto debe sentirse ligero.** La ligereza es feature, no limitación.
2. **Mr. Money guía; no decide.** Propuestas estructuradas requieren confirmación explícita.
3. **La confianza vale más que cualquier monetización rápida.**
4. **El frontend NO es la fuente de verdad.** Toda lógica crítica vive en backend.
5. **La arquitectura desacopla** proveedor bancario, lógica de negocio y analytics.
6. **Los datos del usuario existen primero para servir al usuario.**
7. **ARIA solo se activa con `aria_consent = true`.** Sin UUID en `aria.*`. Service_role exclusivo.
8. **La ambición debe merecerse con ejecución disciplinada.**
9. **La deuda técnica se documenta, no se oculta.** Honestidad narrativa.
10. **La arquitectura tolera pivotes estratégicos.** Ningún proveedor/banco/integración es inamovible.

### Reglas técnicas inviolables (Parte II §13.2 + §14.4 + §15.4)

11. **API Python NUNCA importa Playwright.** El worker es el único con browser pool arrancado. API y worker son procesos deployables independientes.
12. **`sky.domain` jamás pregunta de qué `source` vino un movimiento.** Si una capa superior necesita distinguir origen, el modelo canónico está incompleto — se enriquece, no se rompe la abstracción.
13. **Modelo canónico único**: todo proveedor devuelve `CanonicalMovement`. Categorización, Mr. Money, ARIA, summary, reporting consumen el mismo shape.
14. **Scraper como fallback permanente.** Incluso tras integrar APIs directas, el scraper queda como última línea. Solo se elimina si un contrato bancario lo exige.
15. **`AuthenticationError` NO dispara failover** del IngestionRouter. La credencial es el problema y todos los proveedores la rechazarían igual.
16. **Rate limit = `skip`, no `fail`.** El siguiente provider de la cadena se intenta.
17. **Configuración como palanca operativa**: cambios de estrategia (activar BCI directo al 5%, mover Fintoc a primera línea) son `UPDATE` a `ingestion_routing_rules`, no deploys.

### Seguridad inviolable (Parte I §11.1 + Parte III §20)

18. **`SUPABASE_SERVICE_KEY` y `BANK_ENCRYPTION_KEY` solo en backend.** Nunca en frontend, repo, ni logs.
19. **Credenciales bancarias = AES-256-GCM con IV único** (formato `iv:authTag:ciphertext` base64, compatible binario Node ↔ Python).
20. **Mr. Money llama a Anthropic solo desde el backend.** Nunca desde el browser.
21. **RLS habilitado en TODAS las tablas de `public`.** Schema `aria` bloqueado a clientes (solo service_role escribe).
22. **Frontend NUNCA llama a Supabase con `service_role` ni a Anthropic directo.**
23. **Errores de scraper sanitizados** antes de mostrarse al usuario (eliminar password, rut, stack, timeouts).

---

## 🏗️ Stack y arquitectura

Monorepo. Tres patas:

| Carpeta | Rol | Estado |
|---|---|---|
| `backend/` | Node.js + Express, vivo en producción | ✅ Sirve usuarios reales |
| `backend-python/` | Python 3.12 + FastAPI + ARQ + Playwright. Migración. | 🟡 Fases 0-5 cerradas. **NO toca prod hasta Fase 13** |
| `frontend/` | React 18.3 + Vite 5.4. Solo consume el backend. | ✅ Estable |

**DB compartida**: Supabase Postgres. Esquemas `public` (RLS) y `aria` (analytics, sin UUID, service_role only).

**Despliegue actual**: Railway · `app.skyfinanzas.com` (frontend) + `api.skyfinanzas.com` (backend Node) · DNS Squarespace.

### Regla de oro
```
Frontend  → solo muestra, captura y llama al backend
Backend   → calcula, decide, guarda, llama a la IA
IA        → solo desde el backend, nunca desde el browser
ARIA      → solo escribe analytics anónimos
Cifrado   → solo el backend conoce BANK_ENCRYPTION_KEY
```

### Regla doctrinal Parte I vs Parte II
Cada decisión técnica se etiqueta mentalmente:
- **Parte I** = qué hay vivo HOY (Node.js, prod). Tocar con cuidado quirúrgico.
- **Parte II** = qué se está construyendo (Python, migración). Aquí trabajamos.
- **Parte III** = deuda registrada. Cada P/BUG tiene fase asignada de cierre.

Cuando algo sea ambiguo: leer el v5 PDF, sección correspondiente.

---

## 🗺️ Mapa del repo

```
sky_OFFICIAL/
├── backend/                     ← Node.js prod (Parte I del v5)
│   ├── server.js, middleware/, routes/, services/, scripts/
│   └── Dockerfile (node:22-slim + Chromium vía apt)
├── backend-python/              ← Python migración (Parte II del v5) ← FOCO ACTIVO
│   ├── src/sky/
│   │   ├── core/                ← config, db, encryption, locks, logging, errors, metrics
│   │   ├── ingestion/           ← Fase 4-5 ✅ (router + scrapers + rate limit + CB + rules DB)
│   │   │   ├── routing/         ← router.py, rules.py
│   │   │   ├── sources/         ← bchile_scraper, falabella_scraper (skel), bci_direct (parcial)
│   │   │   └── parsers/         ← bchile_parser
│   │   ├── api/                 ← FastAPI; main + jwt_auth ✅; routers/* schemas/* STUBS hasta Fase 7
│   │   ├── worker/              ← ARQ; main ✅; jobs/* y banking_sync STUBS hasta Fase 6
│   │   └── domain/              ← Mr. Money, ARIA, finance, categorizer — STUBS hasta Fase 8
│   ├── tests/                   ← unit (verde) + integration (vacío) + parity (vacío)
│   ├── scripts/                 ← smoke_router, test_bchile_scraper, test_bci_scraper, verify_encryption_compat
│   ├── migrations/              ← 000_immediate_fixes.sql, 001_routing_rules.sql
│   ├── docs/
│   │   ├── MIGRATION_13_PHASES.md     ← plan maestro técnico
│   │   ├── REMEDIATION_P0_P3.md       ← deuda P0-P3 → fase de cierre
│   │   └── FASE5_CLOSURE_PLAN.md      ← template del proceso de cierre por fase
│   ├── pyproject.toml · ruff.toml · mypy.ini · .env.example
│   └── README.md                 ← estado real Python
├── frontend/                    ← React app (Parte I)
└── CLAUDE.md                    ← este archivo
```

**Fuera del monorepo**:
- `SkyFinancWebSite/` (repo separado) — landing pública en GitHub Pages, CNAME `skyfinanzas.com`
- `SupabaseSQLQuerys/` (repo separado) — migraciones SQL versionadas

---

## 📐 Contrato `DataSource` (Parte II §14)

La pieza más protegida del rediseño. Modificarlo requiere RFC interno.

### `kind` (5 tipos)
| Kind | Significado |
|---|---|
| `SCRAPER` | Browser automation (BChile, Falabella) |
| `AGGREGATOR` | Fintoc, Belvo |
| `BANK_API_DIRECT` | API propia del banco con acuerdo bilateral |
| `SFA` | Open Banking regulado chileno (CMF) |
| `MANUAL_UPLOAD` | Archivo subido por el usuario, fallback humano |

### `auth_mode` (4 modos)
| Modo | Para |
|---|---|
| `PASSWORD` | RUT + clave (scraping) |
| `OAUTH` | Tokens access/refresh (Fintoc, bancos) |
| `API_KEY` | Clave institucional |
| `CONSENT_TOKEN` | Token de consentimiento explícito (SFA) |

### Source identifiers
| Identifier | Capa | Estado |
|---|---|---|
| `scraper.bchile` | SCRAPER · PASSWORD | ✅ Validado contra cuenta real |
| `scraper.falabella` | SCRAPER · PASSWORD | 🟡 Skeleton |
| `scraper.bci` | SCRAPER · PASSWORD | 🟡 Parcial |
| `mercadopago.api` | AGGREGATOR · OAUTH | 🔴 Futuro |
| `fintoc` | AGGREGATOR · OAUTH | 🔴 Futuro |
| `bci.direct`, `santander.direct` | BANK_API_DIRECT · OAUTH | 🔴 Futuro |
| `sfa.<bank>` | SFA · CONSENT_TOKEN | 🔴 Horizonte |
| `manual` | MANUAL_UPLOAD · — | 🔴 Futuro |

### `CanonicalMovement` (campos)
`external_id` (SHA-256 determinístico) · `amount_clp` (int CLP) · `raw_description` · `occurred_at` (date) · `movement_source` (CUENTA / TARJETA / LÍNEA) · `source_kind` · `source_metadata` (libre, debug — el dominio NO lo lee).

### Determinismo del `external_id`
```python
external_id = f"{bank_id}_{sha256(f'{date}|{amount}|{desc.lower()}').hexdigest()[:16]}"
```
Mismo movimiento real → mismo id → idempotencia natural en `INSERT ... ON CONFLICT`.

---

## 🔁 IngestionRouter — failover, circuit breaker, rate limit (Parte II §15)

- **Cadena de proveedores por banco**: lista ordenada en `public.ingestion_routing_rules`. Editable sin redeploy.
- **Rollout %**: hash determinístico de `user_id + bank_id` para canary releases (5% → 50% → 100%).
- **Circuit breaker en Redis** (`cb:<source_id>`): abre tras **5 fallos en 60s**, mantiene abierto **120s**, cierra tras **3 éxitos consecutivos** en half-open.
- **Rate limit en Redis** (`rl:<source_id>`): sliding window log atómico (Lua), namespaces separados de CB.
- **Política de failover**: salta si circuit OPEN → registra `RecoverableIngestionError` y prueba siguiente → `AuthenticationError` propaga sin failover → toda la cadena falla = `AllSourcesFailedError`.

---

## 🧠 Mr. Money — arquitectura de respuesta (Parte I §4)

1. **Detección local primero** — patrones (saludos, consultas de desafíos) responden sin tokens.
2. Si no hay match local → construye contexto financiero (balance, ingresos/gastos por categoría, tasa ahorro, metas, desafíos, cuentas) → eleva a `claude-sonnet`.
3. Tipos de respuesta: texto simple · `propose_challenge` (estructurada, render interactivo, **requiere confirmación**) · navegación (deep-link a vistas).
4. Tools (tool use de Anthropic) para proyecciones financieras y evaluar realismo de metas.

---

## 🧮 Categorización 3 capas (Parte I §3.3)

Orden estricto, cada capa solo invoca la siguiente si falla:
1. **Reglas deterministas** — ~25 regex. Sin tokens.
2. **Caché de comercios** — tabla `merchant_categories`, lookup por prefijo progresivo (`"jumbo las condes" → "jumbo las" → "jumbo"`). Compartida entre todos los usuarios.
3. **Claude API** — solo si las dos capas anteriores fallan. Resultado se guarda en caché.

---

## 🛡️ ARIA — pipeline de anonimización (Parte I §8)

Solo activo si `profiles.aria_consent = true` (P0-2 fortalece este guard).

5 pasos:
1. **Extracción** — evento real → señal estructurada
2. **Categorización** — valor exacto → rango (monto → bucket, fecha → trimestre)
3. **Eliminación de identidad** — UUID descartado antes de escribir en `aria.*`
4. **Randomización intra-bucket** — valor guardado = random dentro del rango, no el real
5. **Ruptura de correlaciones** — jitter temporal ±36h, batch_id propio por registro

Threshold de vistas analíticas: **mínimo 10 registros** (k-anonymity informal).

Tablas `aria.*`: `spending_patterns`, `goal_signals`, `behavioral_signals`, `session_insights`. Vistas: `v_motivation_by_cohort`, `v_spending_by_segment`.

---

## 📋 Inventario de deuda activa (Parte III §19)

| ID | Item | Estado | Cierra en |
|---|---|---|---|
| **P0-1** | JWT auth en backend (Node lee header sin verificar) | Abierto en Node | Python Fase 7 (`api/middleware/jwt_auth.py` ya existe) |
| **P0-2** | Consent ARIA inconsistente en flujo bancario | Abierto | Fix Node (30 min) + reforzado en Python Fase 8 |
| ~~P0-3~~ | ~~Refresh en vivo post-sync~~ | ✅ Resuelto Abr-2026 | — |
| **P1-1** | `Sky.jsx` god-component (1 678 LOC) | Abierto | Refactor frontend (paralelo) |
| **P1-2** | CORS permisivo por fallback | Abierto | Python: rechazar deploy sin allowlist |
| **P2-1..4** | Tests / CI / rate limiting / monitoring | Abiertos | Python Fase 10 |
| **P2-5** | Paralelismo Puppeteer sin límite | Mitigado (secuencial) | Python: browser pool default 4 |
| **P2-6** | Rotación `BANK_ENCRYPTION_KEY` sin procedimiento | Abierto | Python: key versioning |
| **BUG-1** | `external_id` inconsistente (2 implementaciones Node) | Abierto | Python: única `build_external_id` |
| **BUG-2** | Upsert apunta a UNIQUE INDEX inexistente | Abierto | Python migration `002_indexes_and_constraints.sql` |
| **BUG-3** | Lock en memoria del proceso | Abierto | Python: `pg_try_advisory_lock` |
| **BUG-4** | Sync secuencial entre bancos (5 min) | Abierto | Python: browser pool paralelo (~90s) |

**Regla**: cuando trabajemos en una fase, verificar qué P/BUG cierra y asegurar que se cumple antes del commit de cierre.

---

## 🐍 Convenciones Python (backend-python/)

- `from __future__ import annotations` siempre.
- `StrEnum` (3.11+) en vez de `(str, Enum)`. `from enum import StrEnum`.
- Async-first: SQLAlchemy 2.0 async, `redis.asyncio`, FastAPI native async, ARQ, `httpx` async.
- `structlog` con context binding. Nunca `print`.
- Excepciones tipadas en `sky.core.errors`. NO crear duplicados.
- `pydantic-settings` (`Settings` clase) para config; fail-fast si falta env var crítica.
- `dataclass(frozen=True, slots=True)` para value objects inmutables.
- Sin `# type: ignore` salvo cuando mypy genuinamente no puede inferir; ruff `UP037` los detecta sobrantes.

### Tests
- `pytest` con `asyncio_mode=auto`. Sin `@pytest.mark.asyncio` en cada test.
- `fakeredis[lua]>=2.26` para Redis en tests. Fixture `fake_redis` ya en `conftest.py`.
- `@pytest.fixture(autouse=True)` para resetear estado global.
- Nunca `time.sleep` en tests async — usa `await asyncio.sleep`.
- Timing tests del circuit breaker: `await asyncio.sleep ≥ 1.0s`. Nunca `< 1.0s`.
- Variables dummy de Supabase en `conftest.py` con `os.environ.setdefault(...)` ANTES de cualquier import de `sky.*`.

### Naming Redis
- `rl:<source_id>` rate limit · `cb:<source_id>` circuit breaker · namespaces separados.

### Mensajes de commit
- Cierre de fase: español, formato del plan correspondiente. Ej:
  `Fase 5 cerrada: IngestionRouter con rate limit, circuit breaker, rules en DB`
- Otros commits: convencional pero en español.
- Siempre `Co-Authored-By: Claude ...`

---

## ⚙️ Comandos comunes

### Setup (una vez)
```powershell
cd backend-python
python -m venv .venv
.venv\Scripts\activate            # Windows; Linux/Mac: source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

### Loop dev
```powershell
.venv\Scripts\activate
pytest tests/unit/ -v --cov=src/sky/ingestion --cov-report=term-missing
ruff check src/sky/ingestion/ tests/
mypy src/sky/ingestion/
```

### Smoke contra Redis real
```powershell
docker run -d --rm -p 6379:6379 --name sky-redis-smoke redis:7-alpine
$env:REDIS_URL = "redis://localhost:6379"
python scripts/smoke_router.py
docker stop sky-redis-smoke
```

### Levantar stack
```powershell
$env:REDIS_URL = "redis://localhost:6379"
uvicorn sky.api.main:app --reload --port 8000
arq sky.worker.main.WorkerSettings   # cuando Fase 6 esté implementada
```

### PowerShell vs bash
- PowerShell: `$env:VAR = "valor"` (NO `VAR=valor cmd` estilo bash).
- PowerShell: `;` o `if ($?) { ... }` (NO `&&`).
- Heredoc multilínea: `@'...'@` (single-quoted, literal). Cierre `'@` debe ir en columna 0.

---

## 🚦 Cierre de fase — proceso estándar

Cada fase nueva sigue este patrón (template = `backend-python/docs/FASE5_CLOSURE_PLAN.md`):

1. **Plan**: crear `docs/FASE<N>_CLOSURE_PLAN.md` antes de tocar código. Sin plan no se escribe código.
2. **Implementación**: por archivo según el plan.
3. **Gates §3** — todos exit code 0:
   - `ruff check src/sky/ingestion/ tests/`
   - `mypy src/sky/ingestion/`
   - `pytest tests/ -v --cov=... --cov-report=term-missing`
   - Smoke contra Redis local (si aplica)
   - `uvicorn` arranca + `/api/health` responde 200
4. **Migraciones SQL** (si aplica): aplicar en staging primero, prod después. Verificar con query.
5. **Verificar P/BUG cerrados**: cruzar con tabla §19 del v5.
6. **Commit**: mensaje exacto del plan, en español. `Co-Authored-By: Claude`.
7. **Update**: `docs/MIGRATION_13_PHASES.md` con `### Estado: ✅ Cerrada (YYYY-MM-DD)` + archivos + gates marcados.

---

## 🤝 Reglas de operación con Claude

- **Trabajamos directo en `main`** (decisión 2026-04-30). Sin worktrees, sin PRs en flujo normal. `.claude/` está en `.gitignore`.
- **El usuario hace `git push`**. Yo solo commit local.
- **Nunca `--force` push a main.** Si parece necesario, algo está mal — diagnosticar antes.
- **Ante ambigüedad o conflicto**: parar y preguntar antes de tocar archivos. No tomar acciones destructivas (`reset --hard`, merge, force) sin OK explícito.
- **Plan-first para fases**: nunca empezar a escribir código de una fase sin primero el `FASE<N>_CLOSURE_PLAN.md`.
- **Si encuentro deuda fuera de scope**: documentar como TODO referenciando la fase correcta del v5, no arreglarlo en el momento.
- **No tocar `backend/` (Node) salvo solicitud explícita.** Ese código está en producción sirviendo usuarios.
- **PowerShell por defecto** — el usuario está en Windows con miniconda. Adaptar comandos.

---

## 🎯 Visión estratégica (Parte IV §24)

Las 5 fases de negocio (no confundir con las 13 fases técnicas):

| Fase de negocio | Objetivo |
|---|---|
| **F1 — Demostrar alivio** | Que un usuario sienta más claridad en una semana. Cierre de P0 + migración Python. |
| **F2 — Consolidar hábito** | Recomendación entre pares. Más bancos. Fintoc + APIs directas. Entrada universitaria. |
| **F3 — Capa institucional** | ARIA genera valor B2B (bancos, gobierno, aseguradoras). |
| **F4 — Infraestructura** | Sky como plataforma. Contrato `DataSource` como API pública. |
| **F5 — Categoría regional** | Expansión Perú, México, Colombia. |

**Riesgos estratégicos vivos** (Parte IV §25): onboarding · complejidad acumulada · traición de datos · dependencia de proveedor · regulación (SFA) · sobrehype · talento · deuda · ejecución de migración.

---

## 🔖 Atajos de contexto frecuentes

| Pregunta | Archivo / sección |
|---|---|
| "Qué es Sky exactamente" | v5 PDF · §1, §2 (identidad y tesis) |
| "Qué hay implementado HOY" | v5 PDF · Parte I (§1-§11) o `backend-python/README.md` |
| "Cómo es la arquitectura objetivo" | v5 PDF · Parte II (§12-§18) |
| "Estado de fases técnicas" | `backend-python/docs/MIGRATION_13_PHASES.md` |
| "Deuda técnica P0/P1/P2/BUG" | v5 PDF · Parte III (§19-§22) o `backend-python/docs/REMEDIATION_P0_P3.md` |
| "Decisiones doctrinales completas" | v5 PDF · §26 |
| "Cómo cierro una fase" | `backend-python/docs/FASE5_CLOSURE_PLAN.md` (template) |
| "Estructura objetivo del repo Python" | v5 PDF · Anexo A.2 |
| "Mapeo Node → Python (qué archivo va a qué)" | v5 PDF · Anexo A · "Mapeo conceptual" |
| "Bancos soportados + estado" | `backend-python/src/sky/ingestion/sources/__init__.py` (`SUPPORTED_BANKS`) |
| "Reglas de routing iniciales" | `backend-python/migrations/001_routing_rules.sql` |
| "Cómo corre el smoke" | `backend-python/scripts/smoke_router.py` |

---

## 📅 Última actualización

`2026-04-30` · Tras lectura del v5 PDF (registro INAPI) y cierre de Fase 5.

Cuando algo de fondo cambie en el producto/arquitectura/doctrina, actualizar el v5 PDF primero (registro legal), después este archivo. Este `CLAUDE.md` siempre debe ser un derivado fiel del v5.
