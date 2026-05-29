-- 011 — Perfil cualitativo privado por usuario (ARIA-quali v1)
-- Tabla interna, solo service_role. RLS bloquea acceso cliente.
-- Registra dimensiones psico-financieras aprendidas por Mr. Money.

CREATE TABLE IF NOT EXISTS public.user_financial_profile (
  user_id                   uuid PRIMARY KEY
                            REFERENCES public.profiles(id) ON DELETE CASCADE,
  savings_mindset           text,
  savings_mindset_conf      numeric(3,2),
  risk_tolerance            int,
  risk_tolerance_conf       numeric(3,2),
  financial_volatility      int,
  financial_volatility_conf numeric(3,2),
  goal_orientation          text,
  goal_orientation_conf     numeric(3,2),
  stress_baseline           int,
  stress_current            int,
  emotional_volatility      int,
  last_emotion              text,
  last_emotion_at           timestamptz,
  motivation_primary        text,
  motivation_primary_conf   numeric(3,2),
  recurring_blockers        jsonb DEFAULT '[]'::jsonb,
  protective_behaviors      jsonb DEFAULT '[]'::jsonb,
  emotion_history           jsonb DEFAULT '[]'::jsonb,
  updates_count             int DEFAULT 0,
  first_observed_at         timestamptz DEFAULT NOW(),
  last_updated_at           timestamptz DEFAULT NOW(),
  CHECK (savings_mindset IS NULL OR
         savings_mindset IN ('saver','spender','avoider','balanced')),
  CHECK (goal_orientation IS NULL OR
         goal_orientation IN ('short_term','long_term','mixed')),
  CHECK (motivation_primary IS NULL OR
         motivation_primary IN ('security','family','experience','freedom','status')),
  CHECK (risk_tolerance IS NULL OR risk_tolerance BETWEEN 0 AND 10),
  CHECK (financial_volatility IS NULL OR financial_volatility BETWEEN 0 AND 10),
  CHECK (stress_baseline IS NULL OR stress_baseline BETWEEN 0 AND 10),
  CHECK (stress_current IS NULL OR stress_current BETWEEN 0 AND 10),
  CHECK (emotional_volatility IS NULL OR emotional_volatility BETWEEN 0 AND 10)
);

CREATE INDEX IF NOT EXISTS idx_ufp_last_updated
  ON public.user_financial_profile (last_updated_at DESC);

ALTER TABLE public.user_financial_profile ENABLE ROW LEVEL SECURITY;

-- Solo service_role puede leer/escribir. Ningún cliente JWT accede.
CREATE POLICY ufp_service_only ON public.user_financial_profile
  FOR ALL USING (false) WITH CHECK (false);
