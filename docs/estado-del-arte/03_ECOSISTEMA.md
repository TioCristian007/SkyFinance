# 03 — Ecosistema (bancos, DataSource, modelo canónico, SFA)

[← Volver al índice](../ESTADO_DEL_ARTE.md)

---

## Contrato `DataSource` (la pieza más protegida del diseño)

Toda fuente de datos bancarios implementa el contrato abstracto `DataSource`. Modificarlo requiere RFC interno. Vive en `backend-python/src/sky/ingestion/contracts.py`.

### `kind` — 5 tipos

| Kind | Significado |
|---|---|
| `SCRAPER` | Browser automation (BChile, Falabella, BCI) |
| `AGGREGATOR` | Fintoc, Belvo |
| `BANK_API_DIRECT` | API propia del banco con acuerdo bilateral |
| `SFA` | Open Banking regulado chileno (CMF) |
| `MANUAL_UPLOAD` | Archivo subido por el usuario, fallback humano |

### `auth_mode` — 4 modos

| Modo | Para |
|---|---|
| `PASSWORD` | RUT + clave (scraping) |
| `OAUTH` | Tokens access/refresh (Fintoc, bancos) |
| `API_KEY` | Clave institucional |
| `CONSENT_TOKEN` | Token de consentimiento explícito (SFA) |

## Modelo canónico — `CanonicalMovement`

Todo proveedor, sin importar su `kind`, devuelve movimientos en este shape único. Categorización, Mr. Money, ARIA, summary y reporting consumen el mismo modelo.

```
external_id      :: SHA-256 determinístico — f"{bank_id}_{sha256(f'{date}|{amount}|{desc.lower()}')[:16]}"
amount_clp       :: int (CLP, sin decimales). Positivo = ingreso, negativo = gasto.
raw_description  :: str
occurred_at      :: date
movement_source  :: enum(ACCOUNT/CUENTA, CREDIT_CARD/TARJETA, LINE/LÍNEA)
source_kind      :: SourceKind
source_metadata  :: dict (debug libre — el dominio NO lo lee)
```

**Determinismo del `external_id`**: el mismo movimiento real produce siempre el mismo id → idempotencia natural en `INSERT ... ON CONFLICT`. Consecuencia clave: al migrar un banco de scraping a SFA, **no se duplica histórico** — el id une los movimientos.

**Regla doctrinal**: `sky.domain` jamás pregunta de qué `source` vino un movimiento. Si una capa superior necesita distinguir origen, el modelo canónico está incompleto — se enriquece, no se rompe la abstracción.

## Bancos soportados (`SUPPORTED_BANKS`)

Definido en `backend-python/src/sky/ingestion/sources/__init__.py`. Estado a junio 2026 (tras limpieza del listado):

| Identifier | Banco | Capa · Auth | Estado | Notas |
|---|---|---|---|---|
| `bchile` | Banco de Chile | SCRAPER · PASSWORD | **active** | ✅ Validado end-to-end **en producción** (2026-06-12): sync real desde Railway, 42 movs, `channel=chrome`. El blocker histórico **no** era anti-bot desde datacenter (B-1 cerrado/obsoleto): era el `$` de la clave mal tecleado por `type()` en Chromium bundled headless (fix: `fill()` + Chrome real en el worker). 2FA app. |
| `bci` | BCI | SCRAPER · PASSWORD | **pending** | `bci_scraper.py` reconstruido para el portal nuevo `www.bci.cl` + endpoints BFF v3.2 + body capture-and-replay, validado en local (tests verdes). Se activó (2026-06-14) y el primer sync real en prod falló (managed challenge de Cloudflare en el login) → repliegue a `pending` (2026-06-24). Causa raíz **en diagnóstico** (sprint propio). 2FA (Digital Pass). |
| `falabella` | Banco Falabella | SCRAPER · PASSWORD | (removido del listado) | Skeleton, no operativo. |
| `mercadopago`, `fintoc`, `santander.direct`, `bci.direct`, `sfa.<bank>`, `manual` | varios | AGGREGATOR/DIRECT/SFA/MANUAL | 🔴 Futuro | No implementados. |

> El frontend solo muestra como conectables los bancos con `status == "active"`. Los `pending` aparecen como "Próximamente". Por decisión del equipo, el listado expone solo BChile y BCI.

## Scrapers — cómo funcionan

- **BChile** (`bchile_scraper.py`): login en el portal → detecta 2FA (app BancoChile) → usa las **APIs REST internas** de BChile vía `page.evaluate()` con el token XSRF de las cookies. Más estable que scrapear HTML. Extrae balance + cartola (cuenta) + movimientos de tarjeta. Soporta sync incremental (`since`).
- **BCI** (`bci_scraper.py`): login en el widget de `www.bci.cl` (`#rut_aux` con `type()` + `#clave` con `fill()`, verificación post-fill incl. los hidden `#rut`/`#dig`) → intercepta el JWT Bearer del tráfico a `apilocal.bci.cl` → API interna BFF v3.2 (`cuentas-busquedas/por-rut`, `por-numero-cuenta`, `cuentas-movimientos/por-numero-cuenta`) con body capture-and-replay. **Construido y validado en local** (B-2); se activó el 2026-06-14 y se replegó a `pending` el 2026-06-24 tras fallar el primer sync real en prod (managed challenge de Cloudflare en el login). Causa raíz en diagnóstico (sprint propio).

## Open Banking — SFA (la dirección estratégica)

La **CMF** despliega el **Sistema Financiero Abierto**. Sky está diseñado para consumirlo: el SFA es simplemente un nuevo `DataSource` de `kind=SFA`, `auth_mode=CONSENT_TOKEN`. La capa de negocio no cambia.

**Tesis comercial**: cuando un banco libere su SFA, Sky migra a sus usuarios desde scraping a SFA sin que lo noten, generando volumen y métricas de adopción que el banco necesita para justificar la inversión ante CMF y directorio. La fragilidad del scraping (anti-bot, cambios de portal — ver [08](08_ESTADO_Y_DEUDA.md)) es el argumento técnico honesto para el SFA.

## Scraper como fallback permanente

Incluso tras integrar APIs directas o SFA, el scraper queda como **última línea**. Solo se elimina si un contrato bancario lo exige. La cadena de proveedores por banco es configurable en runtime (ver [04](04_ARQUITECTURA.md) — IngestionRouter).
