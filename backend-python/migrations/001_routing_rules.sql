-- ─────────────────────────────────────────────────────────────────────────────
-- Migración: tabla ingestion_routing_rules
-- Define qué provider usa cada banco, en qué orden, con qué rollout.
-- Editable sin redeploy — la palanca operativa central del sistema.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.ingestion_routing_rules (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    bank_id         text NOT NULL,
    source_chain    text[] NOT NULL,  -- ej: ARRAY['scraper.bchile']
    rollout_pct     int NOT NULL DEFAULT 100 CHECK (rollout_pct BETWEEN 0 AND 100),
    user_cohort     text NOT NULL DEFAULT 'all',
    enabled         boolean NOT NULL DEFAULT true,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE(bank_id, user_cohort)
);

-- Reglas iniciales: todos los bancos actuales apuntan a scraper
INSERT INTO public.ingestion_routing_rules (bank_id, source_chain, notes) VALUES
    ('bchile',     ARRAY['scraper.bchile'],     'Solo scraper hoy'),
    ('falabella',  ARRAY['scraper.falabella'],   'Solo scraper hoy'),
    ('bci',        ARRAY['scraper.bci'],         'Pendiente — scraper en desarrollo'),
    ('santander',  ARRAY['scraper.santander'],   'Pendiente — scraper en desarrollo'),
    ('bancoestado',ARRAY['scraper.bancoestado'], 'Pendiente — scraper en desarrollo'),
    ('itau',       ARRAY['scraper.itau'],        'Pendiente — scraper en desarrollo'),
    ('scotiabank', ARRAY['scraper.scotiabank'],  'Pendiente — scraper en desarrollo'),
    ('mercadopago',ARRAY['mercadopago.api'],     'API oficial OAuth')
ON CONFLICT (bank_id, user_cohort) DO NOTHING;

-- Cuando se active Fintoc, el cambio es un UPDATE:
-- UPDATE ingestion_routing_rules
--    SET source_chain = ARRAY['fintoc', 'scraper.bchile'],
--        rollout_pct = 10,
--        notes = 'Canary: 10% a Fintoc, resto scraper'
--  WHERE bank_id = 'bchile' AND user_cohort = 'all';
