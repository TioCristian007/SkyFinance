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

-- ── Verificación ─────────────────────────────────────────────────────────────
-- SELECT indexname FROM pg_indexes
--  WHERE tablename IN ('transactions', 'merchant_categories')
--    AND (indexname LIKE 'uniq_%' OR indexname LIKE 'idx_tx_%' OR indexname LIKE 'idx_transactions_%')
--  ORDER BY indexname;
-- Esperado: idx_transactions_pending, idx_tx_bank_account, idx_tx_user_date,
--           uniq_merchant_key, uniq_tx_external
