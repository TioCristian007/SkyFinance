-- ─────────────────────────────────────────────────────────────────────────────
-- Fase 11: audit log (ISO27001 A.12.4)
-- ─────────────────────────────────────────────────────────────────────────────
-- La tabla public.audit_log YA EXISTE en Supabase con schema enfocado en
-- privacy (user_hash, ip_hash, event_type, outcome, detail, occurred_at).
-- Esta migración solo agrega índices y RLS — NO crea ni modifica la tabla.
--
-- Schema esperado (ya en producción):
--   id (uuid), event_type (text), user_hash (text), resource_type (text),
--   resource_id (uuid), outcome (text), detail (jsonb), ip_hash (text),
--   user_agent (text), occurred_at (timestamptz)
--
-- core/audit.py calcula user_hash = sha256(user_id + AUDIT_LOG_SALT) antes
-- de insertar. Nunca se persiste user_id ni IP raw.
--
-- Ejecutar como: Dashboard Supabase > SQL Editor > New Query > pegar > Run.
-- ─────────────────────────────────────────────────────────────────────────────

-- Índices de performance (queries comunes: por user_hash + tiempo, y por event_type)
CREATE INDEX IF NOT EXISTS idx_audit_log_user_occurred
    ON public.audit_log (user_hash, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_event_occurred
    ON public.audit_log (event_type, occurred_at DESC);

-- RLS: bloquear TODO acceso desde clientes (anon/authenticated).
-- service_role bypassa RLS por diseño de Supabase → el backend Python
-- (con SUPABASE_SERVICE_KEY) sigue pudiendo insertar y leer.
-- El endpoint /api/audit/me (Fase 12) hará el filtrado por user_hash
-- en el backend después de calcular el hash del request.
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

-- Borrar policy vieja si existe (la migration anterior pudo haber dejado restos)
DROP POLICY IF EXISTS audit_log_own_read ON public.audit_log;

CREATE POLICY audit_log_service_role_only ON public.audit_log
    FOR ALL
    USING (false)
    WITH CHECK (false);

-- Comentario inmutabilidad (la garantía real está en core/audit.py — solo INSERT)
COMMENT ON TABLE public.audit_log IS
    'Inmutable. Solo INSERT vía service_role desde core/audit.py. '
    'Hashing user_hash/ip_hash en aplicación (privacy-by-design). '
    'Retención: 90 días (TODO purge trigger en Fase 12).';

-- ── Verificación ─────────────────────────────────────────────────────────────
-- SELECT indexname FROM pg_indexes
--  WHERE tablename = 'audit_log'
--    AND indexname LIKE 'idx_audit_log_%'
--  ORDER BY indexname;
-- Esperado: idx_audit_log_event_occurred, idx_audit_log_user_occurred
--
-- SELECT policyname, cmd FROM pg_policies
--  WHERE schemaname = 'public' AND tablename = 'audit_log';
-- Esperado: audit_log_service_role_only · ALL
