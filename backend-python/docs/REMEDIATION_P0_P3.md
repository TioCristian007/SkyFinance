# PLAN DE REMEDIACIÓN P0–P3 + MAPA DE MIGRACIÓN

## Visión general

Este documento mapea cada ítem de deuda técnica (P0 a P3) a su solución concreta,
indicando si se resuelve en el backend Node actual (pre-migración), durante la
migración a Python, o como consecuencia natural del rewrite.

Convención:
- ✅ RESUELTO — ya aplicado en producción
- 🔧 FIX INMEDIATO — aplicar en Node hoy, no esperar migración
- 🐍 MIGRACIÓN — se resuelve al implementar la fase Python indicada
- 📋 DOCUMENTADO — reconocido, planificado, no urgente

---

## P0 — BLOQUEANTES (resolver antes de escala pública)

### P0-1 · Auth JWT en el backend
| Campo | Valor |
|---|---|
| Estado | 🔧 FIX INMEDIATO en Node + 🐍 integrado en Python Fase 7 |
| Síntoma | middleware/auth.js confía en header x-user-id sin verificar JWT |
| Riesgo | Cualquiera con un UUID puede acceder a datos ajenos, incluyendo disparar syncs que descifran credenciales bancarias |
| Fix Node (aplicar YA) | Ver archivo `01_node_p0_auth_fix/` en esta entrega |
| Fix Python | `src/sky/api/middleware/jwt_auth.py` ya incluido en scaffold — verificación criptográfica desde día 1 |
| Estimación | 4-6 horas en Node, 0 horas adicionales en Python (ya incluido) |
| Verificación | Sin JWT válido → 401 en todas las rutas. Con JWT de usuario A → no puede leer datos de usuario B |

#### Fix Node para P0-1 (aplicar ahora):

**1. Frontend — `services/api.js`:**
Agregar token de Supabase Auth a cada request:

```javascript
// En api.js, modificar la función request():
import { supabase } from "./supabase.js";

async function request(path, options = {}) {
  // Obtener session activa
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const headers = {
    "Content-Type": "application/json",
    ...(token ? { "Authorization": `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
  // ... resto igual, pero SIN el header x-user-id
}
```

**2. Backend — `middleware/auth.js`:**
Verificar JWT en lugar de confiar en header:

```javascript
import { getAnonClient } from "../services/supabaseClient.js";

export async function extractUserId(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader?.startsWith("Bearer ")) {
    req.userId = null;
    return next();
  }

  const token = authHeader.slice(7);
  try {
    const { data: { user }, error } = await getAnonClient().auth.getUser(token);
    if (error || !user) {
      req.userId = null;
    } else {
      req.userId = user.id;
    }
  } catch {
    req.userId = null;
  }
  next();
}
```

**3. Endpoints internal:** mantener auth por `x-cron-secret` (no cambia).

---

### P0-2 · Consentimiento ARIA inconsistente
| Campo | Valor |
|---|---|
| Estado | ✅ RESUELTO en Entrega 2 |
| Síntoma | trackSpendingEvent se llamaba sin userId → ARIA escribía sin consent |
| Fix aplicado | Guard estricto: `if (!userId \|\| !(await hasAriaConsent(userId))) return` |
| Fix Python | `src/sky/domain/aria.py` tendrá el mismo guard estricto |

---

### P0-3 · Refresh en vivo post-sync
| Campo | Valor |
|---|---|
| Estado | ✅ RESUELTO en patch useLiveData |
| Síntoma | Transacciones no aparecían en UI después de sync |
| Fix aplicado | Hook `useLiveData` + `refreshAll` en `onSyncComplete` |

---

## P1 — FRAGILIDAD ESTRUCTURAL

### P1-1 · Sky.jsx god-component (1678 líneas)
| Campo | Valor |
|---|---|
| Estado | 📋 DOCUMENTADO — resolver en paralelo a migración backend |
| Plan | Extraer hooks (useTransactions, useSummary, useBankAccounts). Migrar a TanStack Query. Romper en 5-7 componentes |
| Cuándo | Sprint dedicado de frontend, no bloquea migración Python |
| Estimación | 2-3 semanas |

### P1-2 · CORS permisivo por fallback
| Campo | Valor |
|---|---|
| Estado | 🐍 MIGRACIÓN — Fase 7 |
| Fix Python | `src/sky/api/main.py` ya falla ruidosamente si `CORS_ORIGINS` está vacío en producción |
| Fix Node temporal | Agregar check en server.js: si `NODE_ENV=production` y `CORS_ORIGINS` vacío → throw |

---

## P2 — HIGIENE OPERACIONAL

### P2-1 · Sin tests automatizados
| Campo | Valor |
|---|---|
| Estado | 🐍 MIGRACIÓN — Fases 1-8 |
| Plan | El scaffold Python incluye pytest + estructura de tests desde día 1. Cada fase agrega tests de su módulo. Parity tests en Fase 13 |
| Tests incluidos en scaffold | `test_encryption_compat.py`, `test_contracts.py` |

### P2-2 · Sin CI/CD
| Campo | Valor |
|---|---|
| Estado | 🐍 MIGRACIÓN — scaffold |
| Plan | `.github/workflows/ci.yml` incluido en scaffold. Lint + mypy + tests en cada PR |

### P2-3 · Sin rate limiting
| Campo | Valor |
|---|---|
| Estado | 🐍 MIGRACIÓN — Fase 7 |
| Plan | Rate limit middleware en FastAPI: Redis-backed token bucket por endpoint y por usuario |

### P2-4 · Sin monitoring
| Campo | Valor |
|---|---|
| Estado | 🐍 MIGRACIÓN — Fase 10 |
| Plan | Prometheus metrics + structlog JSON + Sentry para errores |

### P2-5 · Paralelismo Puppeteer sin límite
| Campo | Valor |
|---|---|
| Estado | ✅ MITIGADO (sync secuencial en Node) / 🐍 RESUELTO en Fase 4 |
| Fix Python | Browser pool con semáforo fijo (default 4). Incluido en scaffold: `browser_pool.py` |

### P2-6 · Rotación BANK_ENCRYPTION_KEY sin procedimiento
| Campo | Valor |
|---|---|
| Estado | 📋 DOCUMENTADO |
| Plan | Key versioning: cada token guarda qué key-version lo encriptó. Script de re-encryption batch. Implementar en Fase 3 de Python |

---

## P3 — BUGS ESTRUCTURALES

### BUG-1 · external_id inconsistente (dos implementaciones)
| Campo | Valor |
|---|---|
| Estado | 🐍 MIGRACIÓN — Fase 1 |
| Síntoma | bankingAdapter.js y bankSyncService.js tienen funciones buildExternalId distintas |
| Fix Python | Una ÚNICA función `build_external_id` en `contracts.py`. SHA-256 determinístico. Ya incluido en scaffold |
| Fix Node temporal | SQL fix entregado: `CREATE UNIQUE INDEX uniq_tx_external` previene duplicados aunque el id varíe |

### BUG-2 · UNIQUE INDEX inexistente para upsert
| Campo | Valor |
|---|---|
| Estado | 🔧 FIX INMEDIATO — SQL entregado |
| Síntoma | `there is no unique or exclusion constraint matching the ON CONFLICT specification` |
| Fix | Correr `01_immediate_sql_fixes/run_now.sql` en Supabase |

### BUG-3 · Lock en memoria del proceso
| Campo | Valor |
|---|---|
| Estado | 🐍 MIGRACIÓN — Fase 6 |
| Síntoma | `_syncingAccounts` (Set) no escala con múltiples workers |
| Fix Python | `pg_try_advisory_lock` vía `src/sky/core/locks.py`. Ya incluido en scaffold |

### BUG-4 · Sync secuencial entre bancos
| Campo | Valor |
|---|---|
| Estado | 🐍 MIGRACIÓN — Fase 4 |
| Síntoma | 6 bancos × 50s = 5 minutos |
| Fix Python | Browser pool con paralelismo controlado: 6 bancos en ~90s |

---

## MAPA: FASE DE MIGRACIÓN → ÍTEMS QUE RESUELVE

| Fase | Entregable | P0-P3 que cierra |
|---|---|---|
| Fase 0 | Scaffolding repo Python | — (infraestructura) |
| Fase 1 | Contrato DataSource + CanonicalMovement | BUG-1 |
| Fase 2 | Core: config, DB, logging, errors | P2-1 (parcial) |
| Fase 3 | Encryption compatible binario | P2-6 (diseño) |
| Fase 4 | BChile scraper Playwright + browser pool | BUG-4, P2-5 |
| Fase 5 | IngestionRouter + circuit breaker | — (nuevo) |
| Fase 6 | Queue ARQ + advisory locks | BUG-3 |
| Fase 7 | FastAPI paridad 1:1 endpoints | P0-1, P1-2, P2-3 |
| Fase 8 | Dominio: Mr. Money, ARIA, finance | P0-2 (reforzado) |
| Fase 9 | Scheduler ARQ cron | — (reemplazo) |
| Fase 10 | Observabilidad | P2-4 |
| Fase 11 | Docker + deploy | — (infra) |
| Fase 12 | Migraciones SQL + índices | BUG-2 (definitivo) |
| Fase 13 | Parity tests + cutover | P2-1, P2-2 |

---

## PRIORIDAD DE EJECUCIÓN INMEDIATA (antes de migración)

1. **AHORA** — Correr `run_now.sql` en Supabase (BUG-2, 2 minutos)
2. **ESTA SEMANA** — Aplicar fix P0-1 auth JWT en Node (4-6 horas)
3. **EN PARALELO** — Entregar scaffold Python al equipo para Fase 0-1
4. **CONTINUO** — Node sigue en producción sirviendo a testers mientras Python avanza

---

## CRITERIO DE CUTOVER (cuándo apagar Node)

NO apagar Node hasta que:
- [ ] Fase 7 completa: todos los endpoints de FastAPI responden igual que Node
- [ ] Fase 13: parity tests pasan al 100%
- [ ] 48h de tráfico real a Python sin incidentes
- [ ] Rollback instantáneo verificado (cambiar DNS de api.skyfinanzas.com de vuelta a Node en <5 min)
