-- 008 — Agrega count_transfers_as_expense a profiles (DEFAULT true)
-- Espejo simétrico de count_transfers_as_income para transferencias salientes.
-- DEFAULT true: las transferencias enviadas cuentan como gasto (comportamiento actual implícito).
-- El usuario puede apagarlo desde "Ajustes de cálculo" en el dashboard.

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS count_transfers_as_expense boolean NOT NULL DEFAULT true;
