-- Fase 11: tabla de audit log (ISO27001 A.12.4)
-- Aplicar ANTES del deploy en Railway (ver docs/FASE11_DEPLOY_CHECKLIST.md).
-- Ejecutar como: Dashboard Supabase > SQL Editor > New Query > pegar > Run.

CREATE TABLE IF NOT EXISTS public.audit_log (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID,
    action        TEXT          NOT NULL,
    resource_type TEXT,
    resource_id   UUID,
    metadata      JSONB         NOT NULL DEFAULT '{}'::jsonb,
    ip_address    INET,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_created
    ON public.audit_log (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_action
    ON public.audit_log (action, created_at DESC);

-- RLS: usuarios autenticados solo pueden leer sus propios eventos.
-- El backend escribe con service_role (bypasses RLS).
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_log_own_read ON public.audit_log
    FOR SELECT USING (user_id = auth.uid());

-- Inmutabilidad: solo INSERT desde código (doctrinal).
-- Con service_role el REVOKE no es efectivo — la garantía está en core/audit.py.
-- TODO Fase 12: trigger de purge para registros > 90 días (retención mínima).

COMMENT ON TABLE public.audit_log IS
    'Inmutable. Solo INSERT desde código. Retención: 90 días (TODO purge trigger Fase 12).';
