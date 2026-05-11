-- ─────────────────────────────────────────────────────────────────────────────
-- Fase 12: función de purge del audit_log (retención configurable, default 90d)
-- ─────────────────────────────────────────────────────────────────────────────
-- pg_cron NO está instalado en este Supabase → esta función la invoca el worker
-- ARQ (audit_purge_job) diariamente a las 03:00 UTC.
--
-- La función acepta :days como parámetro para que el worker pase
-- settings.audit_log_retention_days — ajustable sin redeploy.
--
-- Puede invocarse manualmente también:
--   SELECT public.purge_audit_log_old(90);
--
-- IDEMPOTENT: si no hay nada que purgar, retorna 0.
-- Batchea en grupos de 10 000 para evitar lock prolongado.
--
-- Ejecutar como: Dashboard Supabase > SQL Editor > New Query > pegar > Run.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.purge_audit_log_old(days integer DEFAULT 90)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  deleted_total   integer := 0;
  deleted_batch   integer;
  max_iterations  integer := 50;
  iteration       integer := 0;
BEGIN
  LOOP
    EXIT WHEN iteration >= max_iterations;
    iteration := iteration + 1;

    DELETE FROM public.audit_log
     WHERE id IN (
       SELECT id FROM public.audit_log
        WHERE occurred_at < NOW() - (days * INTERVAL '1 day')
        LIMIT 10000
     );

    GET DIAGNOSTICS deleted_batch = ROW_COUNT;
    deleted_total := deleted_total + deleted_batch;

    EXIT WHEN deleted_batch = 0;
  END LOOP;

  RETURN deleted_total;
END;
$$;

COMMENT ON FUNCTION public.purge_audit_log_old(integer) IS
  'Elimina registros de audit_log con occurred_at < NOW() - days dias. '
  'Invocado por el worker ARQ (audit_purge_job) diariamente a las 03:00 UTC. '
  'Batchea en grupos de 10 000 (max 50 iteraciones). IDEMPOTENT.';

-- ── Verificación ─────────────────────────────────────────────────────────────
-- SELECT proname FROM pg_proc WHERE proname = 'purge_audit_log_old';
-- Esperado: purge_audit_log_old
