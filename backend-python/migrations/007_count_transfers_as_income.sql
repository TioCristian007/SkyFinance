-- 007_count_transfers_as_income.sql
-- Habilita contar transferencias entrantes como ingreso (flag por usuario).
-- DEFAULT TRUE: todos los usuarios existentes quedan con el flag encendido.
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS count_transfers_as_income boolean NOT NULL DEFAULT true;
