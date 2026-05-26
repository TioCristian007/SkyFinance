-- migrations/006_bank_accounts_status_check.sql
-- Versiona el constraint de status en bank_accounts.
-- Ya aplicado en Supabase el 2026-05-26; este archivo registra el esquema en el repo.
ALTER TABLE public.bank_accounts DROP CONSTRAINT IF EXISTS bank_accounts_status_check;
ALTER TABLE public.bank_accounts ADD CONSTRAINT bank_accounts_status_check
  CHECK (status IN ('active', 'error', 'disconnected', 'syncing', 'waiting_2fa'));
