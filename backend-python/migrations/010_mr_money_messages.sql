-- 010_mr_money_messages.sql
-- Tabla de historial de conversación con Mr. Money.
-- RLS owner-only: cada usuario solo ve sus propios mensajes.
-- FK a public.profiles(id) ON DELETE CASCADE (convención Sky, verificada 2026-05-29).

CREATE TABLE IF NOT EXISTS public.mr_money_messages (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    role        text        NOT NULL CHECK (role IN ('user', 'assistant')),
    content     text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mr_money_messages_user_time
    ON public.mr_money_messages (user_id, created_at DESC);

ALTER TABLE public.mr_money_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY mr_money_messages_owner
    ON public.mr_money_messages
    FOR ALL
    USING  (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- ─── Verificación post-apply ────────────────────────────────────────────────
-- Ejecutar en Supabase SQL Editor después de aplicar la migración:
--
-- 1) Política RLS activa:
-- SELECT schemaname, tablename, policyname, cmd, qual
--   FROM pg_policies
--  WHERE tablename = 'mr_money_messages';
--
-- 2) Índice creado:
-- SELECT indexname, indexdef
--   FROM pg_indexes
--  WHERE tablename = 'mr_money_messages';
--
-- 3) RLS habilitado:
-- SELECT relname, relrowsecurity
--   FROM pg_class
--  WHERE relname = 'mr_money_messages';
