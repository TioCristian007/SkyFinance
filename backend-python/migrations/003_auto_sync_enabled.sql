-- Migration 003: columna auto_sync_enabled en profiles
-- Pre-requisito de scheduled_sync_job (Fase 9 — Scheduler ARQ).
--
-- La columna controla si el cron de auto-sync incluye la cuenta del usuario.
-- Default: true — usuarios existentes quedan con auto-sync habilitado (opt-out).
--
-- Aplicar ANTES de hacer deploy del worker con cron ARQ activo.
-- Sin esta columna el cron job falla en runtime (SQL error en el JOIN).
--
-- Verificar después:
--   SELECT column_name, data_type, column_default
--     FROM information_schema.columns
--    WHERE table_schema = 'public'
--      AND table_name = 'profiles'
--      AND column_name = 'auto_sync_enabled';
--   -- Debe devolver 1 fila con data_type='boolean', column_default='true'.

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS auto_sync_enabled boolean NOT NULL DEFAULT true;
