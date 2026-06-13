-- migrations/015_merchant_aliases.sql
-- Sprint categorización que aprende (2026-06-12), Fase 2: renombre +
-- nombre canónico de comercio (display).
--
-- Dos piezas:
--   A. Nueva tabla merchant_aliases: el renombre de un comercio por un
--      usuario ("60092 providencia" → "Copec"). Es su override de display
--      inmediato y la base del crowdsourcing de nombres.
--   B. Nueva tabla merchant_display_names: el nombre global resuelto por
--      consenso (>= umbral de usuarios distintos con el mismo nombre).
--      SOLO la escribe la promoción con quórum — no hay escritor IA, así
--      que no necesita guarda de prioridad (a diferencia de la 014).
--
-- Frontera de identidad/privacidad (sprint doc §1.2 y §1.7): transferencias,
-- contrapartes personales y etiquetas de pasarela (mercadopago*, …) quedan
-- crowdsource_eligible=false → jamás se promueven al global. El alias
-- inelegible sigue valiendo como renombre privado del usuario.
--
-- ⚠️ ORDEN DE DEPLOY: aplicar esta migración ANTES de deployar el código
-- que escribe aliases (api + worker). El código viejo no lee estas tablas
-- (compatible); el nuevo las necesita. Staging antes que prod. Después:
--   python scripts/audit_rls_policies.py            (exit 0)
--
-- Preflight (la Supabase compartida tiene artefactos era-Node): ambas deben
-- devolver NULL antes de aplicar; si alguna existe, PARAR e inspeccionar:
--   SELECT to_regclass('public.merchant_aliases'),
--          to_regclass('public.merchant_display_names');


-- ─────────────────────────────────────────────────────────────────────────────
-- A. Tabla de aliases por usuario
--    crowdsource_eligible se decide al renombrar (única instancia con la
--    raw_description a mano), con la MISMA elegibilidad de los votos de
--    categoría (merchant_feedback.is_crowdsource_eligible).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.merchant_aliases (
  user_id              uuid        NOT NULL
                       REFERENCES public.profiles(id) ON DELETE CASCADE,
  merchant_key         text        NOT NULL,
  display_name         text        NOT NULL,
  crowdsource_eligible boolean     NOT NULL DEFAULT false,
  created_at           timestamptz NOT NULL DEFAULT NOW(),
  updated_at           timestamptz NOT NULL DEFAULT NOW(),

  PRIMARY KEY (user_id, merchant_key),

  CONSTRAINT merchant_aliases_display_name_check
    CHECK (char_length(btrim(display_name)) BETWEEN 1 AND 60)
);

COMMENT ON TABLE public.merchant_aliases IS
  'Renombre de comercio por (usuario, comercio). Override de display inmediato para las tx propias + base del crowdsourcing de nombres. Puede contener contrapartes personales en merchant_key/display_name → per-user, RLS, jamás se lee cross-user. ARIA no lee esta tabla.';
COMMENT ON COLUMN public.merchant_aliases.merchant_key IS
  'Key normalizada (normalize_merchant): lowercase, sin prefijos banco, máx 60 chars.';
COMMENT ON COLUMN public.merchant_aliases.display_name IS
  'Nombre elegido por el usuario, tal cual lo escribió (trim, 1-60 chars).';
COMMENT ON COLUMN public.merchant_aliases.crowdsource_eligible IS
  'false para transferencias/contrapartes personales/etiquetas de pasarela: el alias vale solo como renombre privado y NUNCA se promueve al nombre global.';

-- Conteo de quórum: COUNT(DISTINCT user_id) por (merchant_key, display_name)
-- solo sobre aliases elegibles.
CREATE INDEX IF NOT EXISTS idx_ma_promotion
  ON public.merchant_aliases (merchant_key, display_name)
  WHERE crowdsource_eligible;

DROP TRIGGER IF EXISTS trg_merchant_aliases_updated_at
  ON public.merchant_aliases;

CREATE TRIGGER trg_merchant_aliases_updated_at
  BEFORE UPDATE ON public.merchant_aliases
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- RLS por usuario (doctrina §18): cada usuario lee/escribe SOLO sus aliases.
-- El backend (service_role) bypasea RLS como en el resto de public.*.
ALTER TABLE public.merchant_aliases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ma_user_own ON public.merchant_aliases;

CREATE POLICY ma_user_own ON public.merchant_aliases
  FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- B. Tabla de nombres globales (consenso)
--    Espejo de merchant_categories en acceso: RLS habilitado, service_role
--    only. Las keys acá son SIEMPRE de comercios reales (la promoción exige
--    crowdsource_eligible + _key_is_promotable); jamás contendrá
--    transferencias, contrapartes ni etiquetas de pasarela.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.merchant_display_names (
  merchant_key text        PRIMARY KEY,
  display_name text        NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT NOW(),
  updated_at   timestamptz NOT NULL DEFAULT NOW(),

  CONSTRAINT merchant_display_names_display_name_check
    CHECK (char_length(btrim(display_name)) BETWEEN 1 AND 60)
);

COMMENT ON TABLE public.merchant_display_names IS
  'Nombre canónico global por comercio, resuelto por consenso (>= umbral de usuarios distintos con el mismo display_name). Solo escribe la promoción con quórum (no hay escritor IA). Solo keys de comercios reales — la elegibilidad filtra transferencias/pasarelas antes de promover.';

DROP TRIGGER IF EXISTS trg_merchant_display_names_updated_at
  ON public.merchant_display_names;

CREATE TRIGGER trg_merchant_display_names_updated_at
  BEFORE UPDATE ON public.merchant_display_names
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- RLS habilitado, acceso solo backend (service_role bypasea; sin policies
-- para anon/authenticated — mismo patrón que merchant_categories).
ALTER TABLE public.merchant_display_names ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS mdn_service_role_full_access ON public.merchant_display_names;

CREATE POLICY mdn_service_role_full_access ON public.merchant_display_names
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);


-- ─────────────────────────────────────────────────────────────────────────────
-- Verificación post-aplicación (manual)
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. RLS activo en ambas tablas:
-- SELECT relname, relrowsecurity FROM pg_class
--  WHERE oid IN ('public.merchant_aliases'::regclass,
--                'public.merchant_display_names'::regclass);

-- 2. Policies: ma_user_own (por usuario) y mdn_service_role_full_access:
-- SELECT tablename, policyname, roles FROM pg_policies
--  WHERE tablename IN ('merchant_aliases', 'merchant_display_names');

-- 3. El CHECK de largo del nombre:
-- SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--  WHERE conrelid = 'public.merchant_aliases'::regclass AND contype = 'c';
