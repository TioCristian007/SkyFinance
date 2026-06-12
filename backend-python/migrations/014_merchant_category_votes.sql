-- migrations/014_merchant_category_votes.sql
-- Sprint categorización que aprende (2026-06-12), Fase 1: feedback loop.
--
-- Tres piezas:
--   A. merchant_categories.source acepta 'user' (el CHECK era-Node solo
--      permitía 'ai','manual','rule' — ver SupabaseSQLQuerys/
--      Merchant_categories_cache_unified.txt).
--   B. Nueva tabla merchant_category_votes: el voto de categoría de un
--      usuario sobre un comercio. Es su override inmediato (capa 0 del
--      categorizador) y la base del crowdsourcing.
--   C. upsert_merchant_category con guarda de prioridad: una fila
--      source='user' (consenso humano) JAMÁS la pisa una escritura 'ai'.
--
-- ⚠️ ORDEN DE DEPLOY: aplicar esta migración ANTES de deployar el código
-- que escribe votos (api + worker). El código viejo es compatible con el
-- esquema nuevo (la firma de la función no cambia; la tabla nueva no la
-- lee nadie). Staging antes que prod. Después de aplicar:
--   python scripts/audit_rls_policies.py            (exit 0)
--   python scripts/verify_merchant_priority_guard.py (exit 0)
--
-- Preflight sugerido (artefactos era-Node pueden tener nombres distintos):
--   SELECT conname, pg_get_constraintdef(oid)
--     FROM pg_constraint
--    WHERE conrelid = 'public.merchant_categories'::regclass AND contype = 'c';


-- ─────────────────────────────────────────────────────────────────────────────
-- A. CHECK de source acepta 'user'
--    Drop por inspección (no por nombre fijo): el constraint vino inline en la
--    era Node y su nombre autogenerado puede variar entre entornos.
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE c record;
BEGIN
  FOR c IN
    SELECT conname
      FROM pg_constraint
     WHERE conrelid = 'public.merchant_categories'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) ILIKE '%source%'
  LOOP
    EXECUTE format('ALTER TABLE public.merchant_categories DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;

ALTER TABLE public.merchant_categories
  ADD CONSTRAINT merchant_categories_source_check
  CHECK (source IN ('ai', 'manual', 'rule', 'user'));

COMMENT ON COLUMN public.merchant_categories.source IS
  'ai=Claude Haiku | rule=semilla conocida | user=consenso de usuarios (>= umbral de votos distintos; la IA no lo pisa) | manual=legacy Node, sin uso.';


-- ─────────────────────────────────────────────────────────────────────────────
-- B. Tabla de votos por usuario
--    crowdsource_eligible se decide al votar (única instancia con la
--    raw_description a mano): transferencias y contrapartes personales quedan
--    en false y NUNCA participan de la promoción al caché global (doctrina §5,
--    §21). El voto inelegible sigue siendo válido como override privado.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.merchant_category_votes (
  user_id              uuid        NOT NULL
                       REFERENCES public.profiles(id) ON DELETE CASCADE,
  merchant_key         text        NOT NULL,
  category             text        NOT NULL,
  crowdsource_eligible boolean     NOT NULL DEFAULT false,
  created_at           timestamptz NOT NULL DEFAULT NOW(),
  updated_at           timestamptz NOT NULL DEFAULT NOW(),

  PRIMARY KEY (user_id, merchant_key),

  CONSTRAINT merchant_category_votes_category_check
    CHECK (category IN (
      'food', 'transport', 'subscriptions', 'entertainment',
      'health', 'education', 'housing', 'insurance', 'utilities',
      'shopping', 'debt_payment', 'savings', 'transfer',
      'banking_fee', 'income', 'other'
    ))
);

COMMENT ON TABLE public.merchant_category_votes IS
  'Voto de categoría por (usuario, comercio). Override inmediato para las tx propias (capa 0) + base del crowdsourcing. Puede contener contrapartes personales en merchant_key → per-user, RLS, jamás se lee cross-user. ARIA no lee esta tabla.';
COMMENT ON COLUMN public.merchant_category_votes.merchant_key IS
  'Key normalizada (normalize_merchant): lowercase, sin prefijos banco, máx 60 chars.';
COMMENT ON COLUMN public.merchant_category_votes.crowdsource_eligible IS
  'false para transferencias/contrapartes personales o categoría transfer: el voto vale solo como override privado y NUNCA se promueve al caché global.';

-- Conteo de quórum: COUNT(DISTINCT user_id) por (merchant_key, category)
-- solo sobre votos elegibles.
CREATE INDEX IF NOT EXISTS idx_mcv_promotion
  ON public.merchant_category_votes (merchant_key, category)
  WHERE crowdsource_eligible;

DROP TRIGGER IF EXISTS trg_merchant_category_votes_updated_at
  ON public.merchant_category_votes;

CREATE TRIGGER trg_merchant_category_votes_updated_at
  BEFORE UPDATE ON public.merchant_category_votes
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- RLS por usuario (doctrina §18): cada usuario lee/escribe SOLO sus votos.
-- El backend (service_role) bypasea RLS como en el resto de public.*.
ALTER TABLE public.merchant_category_votes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS mcv_user_own ON public.merchant_category_votes;

CREATE POLICY mcv_user_own ON public.merchant_category_votes
  FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- C. upsert_merchant_category con guarda de prioridad user > ai
--    Misma firma que la versión era-Node (compatible con el código en prod).
--    La cláusula WHERE del ON CONFLICT es la guarda: si la fila existente es
--    source='user', solo otra escritura source='user' puede actualizarla.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.upsert_merchant_category(
  p_merchant_key TEXT,
  p_category     TEXT,
  p_source       TEXT DEFAULT 'ai',
  p_confidence   NUMERIC DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO public.merchant_categories (merchant_key, category, source, hits, confidence)
  VALUES (p_merchant_key, p_category, p_source, 1, p_confidence)
  ON CONFLICT (merchant_key) DO UPDATE SET
    category   = EXCLUDED.category,
    source     = EXCLUDED.source,
    confidence = COALESCE(EXCLUDED.confidence, merchant_categories.confidence),
    hits       = merchant_categories.hits + 1,
    updated_at = NOW()
  WHERE merchant_categories.source <> 'user'
     OR EXCLUDED.source = 'user';
END;
$$;

COMMENT ON FUNCTION public.upsert_merchant_category IS
  'Upsert en merchant_categories incrementando hits. Guarda de prioridad: una fila source=user solo la actualiza otra escritura source=user (un voto de usuario jamás lo pisa la IA).';


-- ─────────────────────────────────────────────────────────────────────────────
-- Verificación post-aplicación (manual; la verificación funcional con
-- rollback la hace scripts/verify_merchant_priority_guard.py)
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. El CHECK de source incluye 'user':
-- SELECT pg_get_constraintdef(oid) FROM pg_constraint
--  WHERE conname = 'merchant_categories_source_check';

-- 2. RLS activo en la tabla de votos:
-- SELECT relrowsecurity FROM pg_class
--  WHERE oid = 'public.merchant_category_votes'::regclass;

-- 3. La función quedó con la guarda:
-- SELECT pg_get_functiondef('public.upsert_merchant_category'::regproc);
