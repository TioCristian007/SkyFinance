-- scripts/cleanup_bchile_accounts.sql
-- D2 (sprint ingesta 2026-06-12): limpieza de estado de las cuentas bchile en prod.
--
-- Correr en el SQL editor de Supabase (service_role). SIEMPRE inspeccionar
-- con el paso 1 antes de descomentar cualquier mutación.

-- ── 1. Inspección: las 3 cuentas bchile (1 fundador activa + 2 disconnected) ──
SELECT id, user_id, bank_id, status, consecutive_errors, sync_count,
       last_sync_at, last_sync_error, created_at, updated_at
  FROM public.bank_accounts
 WHERE bank_id = 'bchile'
 ORDER BY created_at;

-- ── 2. Cuenta del fundador (activa) ──────────────────────────────────────────
-- El sync exitoso post-Fase A ya resetea consecutive_errors y last_sync_error.
-- Solo si quedó un error stale de la era del falso positivo (B-7), limpiar:
--
-- UPDATE public.bank_accounts
--    SET last_sync_error = NULL,
--        consecutive_errors = 0,
--        updated_at = NOW()
--  WHERE id = '<ID_FUNDADOR>' AND bank_id = 'bchile' AND status = 'active';

-- ── 3. Cuentas disconnected viejas ───────────────────────────────────────────
-- Opción A (default, conservadora): DEJARLAS. El soft-disconnect preserva el
-- histórico de transactions y no interfiere — todos los caminos de sync y
-- listado filtran status='disconnected'.
--
-- Opción B (borrado definitivo): IRREVERSIBLE. Borra primero las transacciones
-- asociadas y después la cuenta. Solo si se decide no conservar el histórico:
--
-- DELETE FROM public.transactions
--  WHERE bank_account_id = '<ID_CUENTA_VIEJA>';
-- DELETE FROM public.bank_accounts
--  WHERE id = '<ID_CUENTA_VIEJA>' AND status = 'disconnected';

-- ── 4. Verificación post-limpieza ────────────────────────────────────────────
-- Repetir el SELECT del paso 1: la cuenta activa debe quedar con
-- consecutive_errors=0 y last_sync_error NULL.
