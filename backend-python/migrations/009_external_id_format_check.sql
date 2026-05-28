-- Blindaje: el external_id de transactions debe seguir el formato Python
-- (`bank_id_<16 hex>` producido por sha256[:16] en build_external_id).
-- Cualquier escritor con formato distinto (ej. el legacy Node 'bchile_<6 base36>')
-- recibe CheckViolationError y NO puede insertar.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'external_id_format_check'
       AND conrelid = 'public.transactions'::regclass
  ) THEN
    ALTER TABLE public.transactions
      ADD CONSTRAINT external_id_format_check
      CHECK (external_id IS NULL OR external_id ~ '^[a-z][a-z0-9]*_[0-9a-f]{16}$')
      NOT VALID;
  END IF;
END $$;

-- Validar el constraint (idempotente: en una DB limpia es no-op;
-- en una DB con filas legacy, falla y obliga a limpiarlas antes).
ALTER TABLE public.transactions
  VALIDATE CONSTRAINT external_id_format_check;
