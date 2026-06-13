# SPRINT — Categorización que aprende (feedback loop + comercios canónicos)

> **Estado**: Fase 1 VERIFICADA EN PROD (migración 014 aplicada). Bloque 0 (endurecimiento de elegibilidad) + Fase 2 (renombre + nombre canónico) CONSTRUIDOS (2026-06-13) — pendiente aplicar migración 015 + deploy + verificación en prod (ver §5). Fase 3 solo diseño.
> **Objetivo**: que cada categorización/renombre de un usuario mejore el sistema — para esa persona y, con respaldo de varios, para todos. Es el "§4 votos crowdsourced" que `categorizer.py:14` dejó diferido desde Fase 6.
> **Doble valor**: producto (el diferencial "aprende de la comunidad") + dato más limpio para ARIA (tesis B2B). Avanza y solidifica a la vez.

---

## 0. Estado actual (verificado en código + prod)

**Categorización 3 capas** (`backend-python/src/sky/domain/categorizer.py`):
1. Reglas regex (`_RULES`, `_apply_layer1:95`) — sin tokens.
2. Caché `merchant_categories` con prefix matching (`_lookup_cache:148`, `_key_variants:138`). La IA guarda resultados acá (`_save_to_cache:176` → función SQL `upsert_merchant_category`).
3. Claude Haiku (`_categorize_with_ai:233`).

**`merchant_categories` (prod)**: PK `merchant_key` (global, una fila por comercio), columnas `category, source ('ai' default), hits (contador), confidence, created_at, updated_at`. **RLS habilitado, policy `service_role_full_access` only** (lo escribe/lee solo el backend). Sources hoy: `rule` (164), `ai` (40). **No existe `user`.**

**Gaps confirmados:**
- **Recategorización no enseña**: `transactions.py:recategorize:92` solo hace `UPDATE transactions SET category` — no toca el caché. El mismo comercio se re-clasifica de cero la próxima vez.
- **`upsert_merchant_category` sobrescribe ciego**: `ON CONFLICT (merchant_key) DO UPDATE SET category=EXCLUDED.category, source=EXCLUDED.source, ...` → una categorización IA pisaría un voto de usuario. **Falta guarda de prioridad.**
- **Sin identidad de comercio canónico**: `normalize_merchant:105` limpia básico ("Pago:", "mercadopago*", separadores) pero no colapsa variantes (`oxxo`/`OXXO`/`60092 providencia` → `Copec`) ni hay renombre de usuario. `merchant_display:125` solo hace Title Case.

---

## 1. Invariantes NO NEGOCIABLES (las trampas de este sprint)

1. **Prioridad de fuentes**: `user > ai`. Un voto de usuario JAMÁS puede ser pisado por la IA. La guarda va en `upsert_merchant_category` (cláusula `WHERE` en el `ON CONFLICT DO UPDATE`: no actualizar si la fila existente es `source='user'` y la nueva no lo es). Migración que reemplaza la función.
2. **Frontera de privacidad (doctrina §5, §21)**: SOLO comercios reales se crowdsourcean. Transferencias y contrapartes personales (nombres propios: "Transferencia a Juan", "Traspaso de: …") **NUNCA** entran al caché global ni a aliases compartidos. Filtrar con `_TRANSFER_PREFIX_RE` + categoría `transfer` + heurística. Esto es lo más sensible del sprint — un nombre propio filtrado entre usuarios es una brecha.
3. **Anti-envenenamiento del caché global**: el voto de UN usuario aplica de inmediato a SUS propias transacciones, pero la promoción al caché global (`source='user'`, visible para todos) requiere **umbral de N usuarios distintos** de acuerdo (configurable, ej. 3). Un solo usuario no contamina el global. Usar el contador `hits` / tabla de votos para esto.
4. **Orden de deploy (como la 013)**: migración (tablas nuevas + reemplazo de función) ANTES de deployar el código que escribe. Inspeccionar constraints existentes con `pg_get_constraintdef` antes (la Supabase compartida tiene artefactos de la era Node — ver [[project_supabase_node_era_artifacts]]).
5. **RLS en TODA tabla nueva de `public` (doctrina §18)**: votos/aliases con `user_id` → RLS por usuario (lee/escribe lo propio). El caché global resuelto sigue `service_role` only. FK: `user_id → public.profiles(id) ON DELETE CASCADE` (convención Sky, NO auth.users — ver [[project_fk_convention]]).
6. **No romper el flujo 3 capas existente**: la categorización para las transacciones de un usuario consulta PRIMERO sus votos propios, luego el caché global, luego reglas/IA. El job `categorize_pending_job` y el endpoint recategorize comparten esta resolución.
7. **Invariante de identidad (Bloque 0, 2026-06-12)**: `merchant_key` NO es una identidad de comercio — es una **etiqueta de pago**. Las etiquetas de pasarela/terminal (`mercadopago <token>`, `paypal …`, `sumup …`, `khipu …`, `webpay …`, `transbank …`) pueden ser comercios distintos para gente distinta → crowdsourcearlas al global es incorrecto (y en wallets P2P, una fuga de contraparte). **Solo se promueve al global una key que identifica confiablemente UN negocio.** La decisión vive en `merchant_feedback.is_crowdsource_eligible` (única función, reusada por votos de categoría Y aliases de Fase 2) con match por primera palabra de la key normalizada (`GATEWAY_LABEL_FIRST_WORDS` — lista corta deliberada: mejor sub-excluir, el quórum es el backstop) + re-chequeo en `_key_is_promotable` al promover (cubre votos viejos persistidos como elegibles). El override per-user sigue funcionando para las etiquetas excluidas — solo no se comparten. El fix profundo — resolver "¿una key = un comercio o varios?" — es la **FASE 3 (identidad canónica)**, motivada exactamente por este caso.

---

## 2. Fases

### FASE 1 — Feedback loop: recategorizar enseña (núcleo, alto valor)
- **Migración**: reemplazar `upsert_merchant_category` con guarda de prioridad (`user` no se pisa por `ai`). Nueva tabla `public.merchant_category_votes` (`user_id`, `merchant_key`, `category`, `created_at`, `updated_at`, UNIQUE(user_id, merchant_key)) con RLS por usuario.
- **Backend**: `recategorize` (transactions.py) → además del UPDATE de la tx, registra el voto (`merchant_category_votes`) y, si corresponde, promueve al caché global (`upsert_merchant_category(..., source='user')`) cuando ≥ umbral de usuarios distintos coinciden. Filtrar comercios solamente (invariante 2).
- **Categorización**: la resolución para las tx de un usuario consulta sus votos propios primero (override per-user inmediato), antes del caché global.
- **Aceptación**: recategorizo "aramco universida" como food → la próxima tx de ese comercio (mía) entra como food sin IA; con ≥N usuarios coincidiendo, entra para todos; un voto IA posterior NO pisa el voto usuario; una transferencia a una persona NUNCA entra al global.

### FASE 2 — Renombre + nombre canónico de comercio (display)
- **Migración**: tabla `public.merchant_aliases` (`user_id`, `merchant_key`, `display_name`, timestamps, UNIQUE(user_id, merchant_key), RLS por usuario). Promoción a alias global con el mismo umbral anti-envenenamiento.
- **Backend**: endpoint para renombrar un comercio (glosa → nombre amable, ej. "60092 providencia" → "Copec"). `merchant_display:125` consulta aliases (propio del usuario primero, luego global) antes del Title Case.
- **Frontend**: UI de renombre en la transacción/comercio (junto a la recategorización que ya existe, commit `bbe05c7`). Mensaje claro de que el nombre se comparte si varios coinciden.
- **Aceptación**: renombro "60092 providencia" a "Copec" → mis tx de ese comercio muestran "Copec"; con ≥N coincidencias, todos lo ven; transferencias a personas no son renombrables/crowdsourceables.

### FASE 3 — Matching de comercio canónico por variantes (ambicioso — evaluar diferir)
- Colapsar variantes de glosa (`oxxo`, `OXXO`, `el oxxo de la esquina`, códigos tipo `60092`) a UNA entidad de comercio canónica que conduzca categoría Y display. Requiere resolución de identidad (fuzzy/normalización avanzada).
- **Recomendación**: proponer el diseño pero **NO** construir en este sprint salvo que las Fases 1-2 salgan rápido. Es candidato a sprint propio (riesgo de fuzzy matching). Documentar el diseño como plan para retomar.

---

## 3. Esquema sugerido (Fable finaliza en su plan)

```sql
-- Voto de categoría por usuario (per-user override + base del crowdsourcing)
CREATE TABLE public.merchant_category_votes (
  user_id      uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  merchant_key text NOT NULL,
  category     text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, merchant_key)
);
-- RLS: el usuario lee/escribe solo sus votos. (+ política service_role full.)

-- Guarda de prioridad en la función (user no se pisa por ai):
-- ON CONFLICT (merchant_key) DO UPDATE SET ... 
--   WHERE merchant_categories.source <> 'user' OR EXCLUDED.source = 'user';
```
(Tabla `merchant_aliases` análoga para Fase 2.)

---

## 4. Disciplina / gates

- Trabajo directo en `main`, sin branches. Gates por commit: `ruff` + `mypy` + `pytest` verde.
- Tests de regresión obligatorios: guarda de prioridad (ai no pisa user), frontera de privacidad (transferencia no entra al global), umbral anti-envenenamiento, override per-user.
- Migración SQL: `audit_rls_policies.py` verde + aplicar en orden (migración antes que código). Avisar el orden de deploy explícitamente.
- Commits en español + `Co-Authored-By`. El usuario pushea.
- Frontend: ojo con `Sky.jsx` (god-component P1-1) — si el UI de renombre lo infla mucho, evaluar una rebanada de extracción.

---

## 5. Estado de ejecución (2026-06-12)

### Fase 1 — ✅ CONSTRUIDA (pendiente: aplicar migración + deploy + verificación en prod)

Commits: `fc3de31` (migración 014 + `verify_merchant_priority_guard.py` + pin del
archivo) · `74e9650` (dominio `merchant_feedback` + umbral config) · `67c0a22`
(resolución 5 niveles + job con `user_id`) · `179bf18` (PATCH enseña + canon de
categorías) · `1085d76` (picker travel→insurance). Tests: 555 → 598.

**Decisiones tomadas sobre el diseño sugerido (§3):**
- `merchant_category_votes` ganó la columna `crowdsource_eligible boolean NOT NULL
  DEFAULT false`, **decidida al votar** — es la única instancia con la
  `raw_description` a mano; al promover ya solo existe la key normalizada. Índice
  parcial `(merchant_key, category) WHERE crowdsource_eligible` para el quórum.
- **Resolución**: votos propios → caché `source='user'` → reglas → caché
  `'rule'/'ai'` → IA. Desviación deliberada del texto literal del §1.6 ("votos →
  caché → reglas/IA"): solo el tier `'user'` del caché sube sobre las reglas.
  Subir TODO el caché habría dejado que las 164 semillas y las filas IA viejas
  sombreen por prefijo las reglas sign-dependent (transfer/income) — regresión
  ajena al sprint. El objetivo del doc (el consenso corrige una regla equivocada
  PARA TODOS) se cumple igual: test `test_consenso_crowdsourced_corrige_la_regla_para_todos`.
- La promoción converge a la **mayoría** (`COUNT(DISTINCT user_id)` por categoría
  entre votos elegibles), no al último voto emitido. `user` sí puede pisar a
  `user` (consenso nuevo); no hay retracción automática si la mayoría se diluye.
- El CHECK era-Node de `source` se dropea **por inspección** de `pg_constraint`
  (el nombre autogenerado puede variar entre entornos), no por nombre fijo.
- Bug latente cerrado de pasada: `_VALID_CATEGORIES` aceptaba `'travel'` (no
  existe en `transactions_category_check` → 500 al elegir "Viajes" en el picker)
  y rechazaba `'insurance'` (DB-válida). Canon único `set(CATEGORIES)` + picker.

**Checklist de deploy (en este orden, como la 013):**
1. Aplicar `migrations/014_merchant_category_votes.sql` en **staging**.
2. `python scripts/audit_rls_policies.py` (exit 0) y
   `python scripts/verify_merchant_priority_guard.py` (exit 0 — ejercita la
   guarda de verdad, con ROLLBACK).
3. Aplicar la 014 en **prod** + repetir ambas verificaciones.
4. Deploy Railway api + worker (el código viejo es compatible con el esquema
   nuevo; el nuevo NO corre sin la tabla).
5. Smoke en prod: recategorizar una tx → fila en `merchant_category_votes` con
   `crowdsource_eligible=true`; recategorizar una "Transferencia a: …" → fila
   con `crowdsource_eligible=false` y NADA nuevo en `merchant_categories`.

### Bloque 0 — ✅ CONSTRUIDO (2026-06-13). Endurecer la elegibilidad para el global

Commit `7a77821`. Hallazgo de diseño que motivó el bloque: `merchant_key` NO
es una identidad de comercio, es una **etiqueta de pago**. Las etiquetas de
pasarela/terminal (`mercadopago <token>`, …) pueden ser comercios distintos
para gente distinta — promoverlas al global mezcla negocios ajenos y, en
wallets P2P, filtra contrapartes. Detalle en el invariante §1.7.

- `is_crowdsource_eligible` (función ÚNICA, reusada por votos de categoría y
  por aliases de Fase 2) ahora devuelve `False` también para etiquetas de
  pasarela. Match por **primera palabra** de la key normalizada
  (`GATEWAY_LABEL_FIRST_WORDS`) — sin substring, para no excluir comercios
  reales que contengan el token al medio (`feria mercadopago` sigue elegible).
- Lista deliberadamente corta (`mercadopago`, `paypal`, `sumup`, `khipu`,
  `webpay`, `transbank`). Principio: **mejor sub-excluir** — el umbral de N
  usuarios es el backstop para lo no listado; marcar por error a `jumbo`/
  `starbucks` sería peor. `mercadopago*` es el piso confirmado del kickoff.
- `_key_is_promotable` también se endureció: re-chequea la etiqueta al
  promover, así un voto viejo persistido como `eligible=true` (de antes de
  este cambio) jamás llega al global — sin backfill de datos.
- El override per-user sigue funcionando para las etiquetas excluidas (el
  usuario las categoriza/renombra para sí; solo no se comparten).
- Tests: `"mercadopago decop" → eligible=false`, `"jumbo las condes" →
  eligible=true`, first-word matching, defensa en profundidad en
  `_maybe_promote`/`_maybe_promote_alias`.

### Fase 2 — ✅ CONSTRUIDA (2026-06-13). Renombre + nombre canónico (display)

Commits: `8fe7a2c` (migración 015 + pin) · `484974b` (dominio: aliases +
nombre global) · `a63e3d7` (endpoint + UI). Tests: 598 → 650.

**Decisiones sobre el esquema sugerido (§2 Fase 2):**
- Dos tablas, no una: `merchant_aliases` (per-user, RLS por usuario, espejo
  estructural de `merchant_category_votes`) + `merchant_display_names`
  (global, resuelto por consenso, RLS `service_role` only como
  `merchant_categories`). El nombre global vive separado de los aliases
  per-user igual que el caché global vive separado de los votos.
- `merchant_display_names` **no** lleva guarda de prioridad ni función
  plpgsql: a diferencia de `merchant_categories`, no tiene escritor IA — solo
  la promoción con quórum escribe ahí. El upsert es inline. (Test del pin
  obliga a repensarlo si algún día aparece otro escritor.)
- Resolución de display por página (`merchant_display_batch`): alias propio
  (prefix matching, como los votos) → alias global → Title Case. El override
  propio gana SIEMPRE al global. **Guarda de lectura**: keys con prefijo de
  transferencia jamás consultan el global (la contraparte es una persona, esa
  tabla no debe contenerlas); el alias propio sí aplica (renombre privado de
  la contraparte). Fail-open: el display es un realce, no puede botar la lista.
- El renombre es endpoint propio (`PATCH …/{id}/merchant`), no parte del
  PATCH de recategorización: el cliente nunca manda la `merchant_key`, se
  deriva de la tx del usuario. A diferencia del voto de categoría
  (best-effort tras el UPDATE), acá el alias ES la acción: si falla, falla.
- Promoción de nombre por **mayoría exacta** del `display_name` tras trim
  (`COUNT(DISTINCT user_id)`), conservador: el quórum es más difícil que
  colapsar variantes — eso es Fase 3.

**Checklist de deploy (en este orden, como la 013/014):**
1. Preflight: `SELECT to_regclass('public.merchant_aliases'),
   to_regclass('public.merchant_display_names');` → ambas NULL. Si alguna
   existe (artefacto era-Node), PARAR e inspeccionar.
2. Aplicar `migrations/015_merchant_aliases.sql` en **staging**.
3. `python scripts/audit_rls_policies.py` (exit 0).
4. Aplicar la 015 en **prod** + repetir audit.
5. Deploy Railway api + worker (el código viejo no lee las tablas nuevas;
   el nuevo las necesita).
6. Smoke en prod: renombrar el comercio de una tx (lápiz en Movimientos) →
   fila en `merchant_aliases` con `crowdsource_eligible=true` y el nombre
   aparece en TODAS las tx del comercio; renombrar una "Transferencia a: …"
   → fila con `crowdsource_eligible=false`, nombre visible solo para el
   usuario y NADA en `merchant_display_names`; renombrar `mercadopago*…` →
   también `crowdsource_eligible=false`.

### Fase 3 — Propuesta de diseño (NO construir en este sprint)

**Motivación reforzada (Bloque 0, 2026-06-13)**: el endurecimiento de
elegibilidad es un parche al síntoma — excluimos las etiquetas de pasarela
del global porque no podemos distinguir, hoy, si `mercadopago <token>` es UN
comercio o varios. El fix profundo es exactamente la pregunta de Fase 3:
**¿una `merchant_key` = un comercio o varios?** Cuando exista identidad
canónica, una etiqueta de pasarela podrá resolverse al comercio real
subyacente (vía el token) en vez de quedar per-user only.

Identidad canónica de comercio por variantes (`oxxo`/`OXXO`/`60092 providencia`
→ "Copec"), que conduce categoría Y display:

- **Esquema**: `merchant_entities` (id, canonical_name, category_hint) +
  `merchant_entity_aliases` (entity_id, merchant_key UNIQUE). El alias mapea
  keys normalizadas a UNA entidad; categoría/display cuelgan de la entidad. Las
  tablas de votos/aliases per-user de Fases 1-2 quedan intactas debajo (el
  override privado sigue ganando).
- **Resolución en cascada, barato primero**: (1) lookup exacto de la key en
  aliases; (2) prefix variants (reuso de `_key_variants`); (3) fuzzy SOLO
  offline — job ARQ nocturno que batea keys nuevas contra entidades con
  `pg_trgm` (similarity ≥ 0.85 + cap de longitud). **Nunca fuzzy en el hot path
  del sync.**
- **Curaduría con el mismo umbral**: el fuzzy PROPONE (tabla
  `merchant_alias_candidates`); la promoción a alias global exige el quórum de
  N usuarios (un renombre de Fase 2 cuenta como voto de alias) o confirmación
  del operador vía panel. Nada se colapsa automáticamente sin respaldo humano.
- **Privacidad**: misma frontera de Fase 1 — keys con prefijo de transferencia
  jamás entran a entidades/aliases; la elegibilidad ya viene persistida en los
  votos.
- **Por qué es sprint propio**: riesgo de falsos merges (`jumbo` vs `jumbo
  express`), extensión `pg_trgm` en Supabase, backfill de ~200 keys existentes,
  UI de curaduría. No es una tarde.
