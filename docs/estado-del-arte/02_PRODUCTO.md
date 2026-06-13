# 02 — Producto

[← Volver al índice](../ESTADO_DEL_ARTE.md)

---

## Qué es Sky (y qué NO es)

Sky **no** es una app de gastos con IA pegada encima. Es un **sistema operativo financiero personal**: una capa cognitiva que absorbe la complejidad financiera del usuario y devuelve claridad.

La regla de oro del producto: **el producto debe sentirse ligero**. La ligereza es feature, no limitación.

## Flujo del usuario (alto nivel)

1. **Onboarding** — el usuario conecta su banco (RUT + clave, cifradas). Hoy vía scraping.
2. **Consolidación** — Sky sincroniza saldos y movimientos, los normaliza a `CanonicalMovement`.
3. **Categorización** — cada movimiento recibe una categoría (3 capas, ver abajo).
4. **Interpretación** — Mr. Money construye contexto financiero y conversa.
5. **Acción conductual** — metas, desafíos y simulaciones para cambiar hábitos.

## Mr. Money — arquitectura de respuesta

El asistente conversacional de Sky, sobre **Claude (Anthropic)**. Principios:

1. **Detección local primero** — patrones simples (saludos, consultas de desafíos) se responden **sin gastar tokens**. ~60-70% de las consultas se resuelven localmente.
2. Si no hay match local → construye **contexto financiero** (balance, ingresos/gastos por categoría, tasa de ahorro, metas, desafíos, cuentas) → eleva a `claude-sonnet`.
3. **Tipos de respuesta**:
   - Texto simple.
   - `propose_challenge` — propuesta estructurada, render interactivo, **requiere confirmación explícita del usuario**.
   - Navegación — deep-link a vistas de la app.
4. **Tool use** de Anthropic para proyecciones financieras y evaluar realismo de metas.

**Doctrina de Mr. Money**: *guía, no decide*. NO da asesoría de inversión específica, NO recomienda activos puntuales, NO actúa como asesor licenciado, NO garantiza resultados. Toda propuesta estructurada requiere que el usuario confirme antes de ejecutarse.

Configuración (`sky.core.config`): modelo `claude-sonnet-4-6` (alias), `mr_money_max_tokens=4096`, `temperature=0.7`, prompt caching 5m.

## Categorización en 5 niveles (aprende del usuario)

Orden estricto; cada nivel solo invoca el siguiente si no resolvió (sprint "categorización que aprende", 2026-06-12/13):

0. **Votos propios** — tabla `merchant_category_votes`, prefix matching per-user. El usuario recategorizó ese comercio: override privado inmediato. Nunca lo pisa nada.
1. **Caché global `source='user'`** — consenso crowdsourced (≥ N usuarios distintos, `merchant_vote_promotion_threshold`, default 3). Corrige una regla equivocada PARA TODOS; la IA no puede pisar estas filas.
2. **Reglas deterministas** — ~25 regex. Sin tokens. (`categorizer.py`)
3. **Caché de comercios** `source 'rule'/'ai'` — tabla `merchant_categories`, lookup por prefijo progresivo (`"jumbo las condes" → "jumbo las" → "jumbo"`). Compartida entre todos los usuarios. Va BAJO las reglas (solo el tier `'user'` las supera).
4. **Claude API** — solo si todo lo anterior falla. Modelo `claude-haiku-4-5`. El resultado se guarda en caché.

**Aprende del usuario**: recategorizar (PATCH) registra un voto; renombrar un comercio (`PATCH …/{id}/merchant`, Fase 2) registra un alias de display. Ambos aplican YA al usuario y, con quórum de N usuarios distintos, se promueven al global. **Frontera de identidad/privacidad**: transferencias, contrapartes personales y etiquetas de pasarela (`mercadopago*`, …) jamás se comparten — solo se crowdsourcea una key que identifica confiablemente UN comercio. Detalle en `backend-python/docs/SPRINT_CATEGORIZACION_APRENDE.md`.

**Categoría especial `income`**: se asigna por reglas (monto positivo + glosa que matchea `abono|remuner|sueldo|salario|honorario|liquidaci|traspaso de:|...`). Ver nota crítica en [08](08_ESTADO_Y_DEUDA.md) — el display de ingreso/gasto en el frontend ahora usa el **signo del monto**, no la categoría, para robustez.

**Estado de categorización (post-fix)**: las transacciones se insertan con `categorization_status='pending'` y descripción `'Procesando...'`, y un job ARQ (`categorize_pending_job`) las procesa async, reemplazando descripción y categoría. (Ver [04](04_ARQUITECTURA.md) y [08](08_ESTADO_Y_DEUDA.md) — bug de cola ARQ ya corregido.)

## Metas, desafíos y simulaciones (diseño conductual)

- **Metas** (`goals`): el usuario define objetivos de ahorro. Sky calcula *capacity* = `max(0, ingreso − gastos)` de los últimos 30 días y evalúa realismo.
- **Desafíos** (`challenges`): retos de comportamiento (ej. "Ahorra $60K este mes", "Registra 5 gastos"). Estados: propuesto → aceptado/activo → completado.
- **Simulaciones**: proyecciones financieras ("¿qué pasa si reduzco X gasto?").

## Resumen financiero

`finance.py` calcula el resumen del usuario:
- `income` = suma de montos positivos.
- `expenses` = suma de `abs(monto)` donde `category != "income"` y monto negativo.
- `balance`, `savings_rate = max(0, (income − expenses)/income)`, `net_flow`.

## Marca y diseño

- **Paleta**: verde `#00C853`, navy `#0D1B2A`, blanco `#FFFFFF`.
- **Tipografías**: Instrument Serif (display) + Geist (texto) + Geist Mono (datos).
- **Tono**: cálido, calmo, sin jerga financiera. Empático antes que técnico.
