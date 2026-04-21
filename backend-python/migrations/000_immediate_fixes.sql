-- ─────────────────────────────────────────────────────────────────────────────
-- FIXES INMEDIATOS — Correr en Supabase Studio AHORA
-- No interfieren con la migración Python. Solo reparan producción actual.
-- ─────────────────────────────────────────────────────────────────────────────

-- BUG-2: UNIQUE INDEX faltante en merchant_categories
-- Sin esto, el upsert de categorización falla con:
--   "there is no unique or exclusion constraint matching the ON CONFLICT"
CREATE UNIQUE INDEX IF NOT EXISTS uniq_merchant_key
  ON public.merchant_categories (merchant_key);

-- BUG-2b: UNIQUE INDEX para deduplicación de transacciones
-- Sin esto, el sync puede insertar duplicados o fallar en ON CONFLICT
CREATE UNIQUE INDEX IF NOT EXISTS uniq_tx_external
  ON public.transactions (user_id, bank_account_id, external_id)
  WHERE external_id IS NOT NULL;

-- Performance: índice para queries frecuentes del dashboard
CREATE INDEX IF NOT EXISTS idx_tx_user_date
  ON public.transactions (user_id, date DESC);

-- Performance: índice para sync incremental
CREATE INDEX IF NOT EXISTS idx_tx_bank_account
  ON public.transactions (bank_account_id, external_id)
  WHERE external_id IS NOT NULL;

-- ── Verificación ──────────────────────────────────────────────────────────
-- Correr después para confirmar:
--
-- SELECT indexname FROM pg_indexes
--  WHERE tablename IN ('merchant_categories', 'transactions')
--    AND indexname LIKE 'uniq_%' OR indexname LIKE 'idx_tx_%';
--
-- Debe devolver: uniq_merchant_key, uniq_tx_external, idx_tx_user_date, idx_tx_bank_account
