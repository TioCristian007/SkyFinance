-- migrations/013_bank_accounts_needs_reconnection.sql
-- Sprint ingesta 2026-06-12, Fase B1: nuevo status 'needs_reconnection'.
--
-- Cuando el banco rechaza la clave de verdad (no un mismatch de fill, eso es
-- FieldFillError), la cuenta entra en 'needs_reconnection': ni el cron ni el
-- botón "Actualizar" la reintentan hasta que el usuario reconecte con su clave
-- vigente. Protege contra el bloqueo del banco al 3er intento fallido.
--
-- ⚠️ ORDEN DE DEPLOY: aplicar esta migración ANTES de deployar el worker que
-- escribe 'needs_reconnection' (si no, el UPDATE viola el CHECK y el job
-- reintenta — exactamente lo que queremos evitar). Staging antes que prod.

ALTER TABLE public.bank_accounts DROP CONSTRAINT IF EXISTS bank_accounts_status_check;
ALTER TABLE public.bank_accounts ADD CONSTRAINT bank_accounts_status_check
  CHECK (status IN ('active', 'error', 'disconnected', 'syncing', 'waiting_2fa',
                    'needs_reconnection'));
