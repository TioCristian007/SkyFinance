-- 012 — Snapshots agregados y anonimizados de perfiles cualitativos (ARIA-quali v1)
-- Tabla en schema aria. Sin user_id (doctrina §21).
-- Poblada por snapshot_profiles_job (ARQ cron lunes 03:00 America/Santiago).
-- k-anonymity mínimo = profile_snapshot_k_anon_min (default 5, subir a 10 a 500 usuarios).

CREATE TABLE IF NOT EXISTS aria.user_profile_snapshots (
  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  age_range                   text NOT NULL,
  region                      text NOT NULL,
  income_range                text NOT NULL,
  occupation                  text NOT NULL,
  savings_mindset             text,
  risk_tolerance_bucket       text,           -- low (0-3) | mid (4-6) | high (7-10)
  financial_volatility_bucket text,
  goal_orientation            text,
  stress_baseline_bucket      text,
  motivation_primary          text,
  emotional_volatility_bucket text,
  observed_period             text NOT NULL,  -- YYYY-Qn (ej: 2026-Q2)
  jitter_offset_days          int  NOT NULL,
  batch_id                    uuid NOT NULL,
  inserted_at                 timestamptz NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ups_period_region
  ON aria.user_profile_snapshots (observed_period, region);

-- aria.* es service_role only. No se agrega RLS pública (schema aria excluido de RLS por diseño).
