"""Pin del contenido de migrations/015_merchant_aliases.sql.

Mismo espíritu que test_migration_014.py: los invariantes del ARCHIVO quedan
pineados para que nadie los "simplifique" antes de aplicarlo en staging/prod.
La verificación de RLS contra DB real la hace scripts/audit_rls_policies.py.
"""
from __future__ import annotations

import re
from pathlib import Path

_SQL = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "015_merchant_aliases.sql"
).read_text(encoding="utf-8")


class TestTablaAliases:
    def test_fk_profiles_on_delete_cascade(self) -> None:
        """Convención Sky: FK a public.profiles, NO a auth.users."""
        assert "REFERENCES public.profiles(id) ON DELETE CASCADE" in _SQL
        assert "auth.users" not in _SQL

    def test_pk_compuesta_usuario_comercio(self) -> None:
        assert "PRIMARY KEY (user_id, merchant_key)" in _SQL

    def test_rls_habilitado_con_policy_por_usuario(self) -> None:
        """Doctrina §18: RLS en toda tabla nueva de public."""
        assert (
            "ALTER TABLE public.merchant_aliases ENABLE ROW LEVEL SECURITY"
            in _SQL
        )
        assert "USING (auth.uid() = user_id)" in _SQL
        assert "WITH CHECK (auth.uid() = user_id)" in _SQL

    def test_crowdsource_eligible_default_false(self) -> None:
        """Frontera de privacidad: por defecto un alias NO es crowdsourceable."""
        assert re.search(
            r"crowdsource_eligible\s+boolean\s+NOT NULL DEFAULT false", _SQL
        )

    def test_display_name_con_check_de_largo(self) -> None:
        """1-60 chars tras trim: guarda DB-level además de la del endpoint."""
        assert re.search(
            r"CHECK \(char_length\(btrim\(display_name\)\) BETWEEN 1 AND 60\)",
            _SQL,
        )

    def test_indice_parcial_solo_aliases_elegibles(self) -> None:
        assert re.search(
            r"ON public\.merchant_aliases \(merchant_key, display_name\)\s+"
            r"WHERE crowdsource_eligible",
            _SQL,
        )


class TestTablaNombresGlobales:
    def test_pk_por_merchant_key(self) -> None:
        assert re.search(r"merchant_key text\s+PRIMARY KEY", _SQL)

    def test_rls_habilitado_service_role_only(self) -> None:
        """Espejo de merchant_categories: la escribe/lee solo el backend."""
        assert (
            "ALTER TABLE public.merchant_display_names ENABLE ROW LEVEL SECURITY"
            in _SQL
        )
        assert "mdn_service_role_full_access" in _SQL
        assert "FOR ALL TO service_role" in _SQL

    def test_sin_guarda_de_prioridad_porque_no_hay_escritor_ia(self) -> None:
        """A diferencia de la 014: nadie más que el consenso escribe acá.
        Si algún día aparece otro escritor, este test obliga a repensarlo."""
        assert "upsert_merchant_display" not in _SQL
        assert "CREATE OR REPLACE FUNCTION" not in _SQL


class TestOrdenDeDeploy:
    def test_advertencia_de_orden_presente(self) -> None:
        """Como la 013/014: migración ANTES que el código que escribe."""
        assert "ORDEN DE DEPLOY" in _SQL

    def test_preflight_era_node_presente(self) -> None:
        """La Supabase compartida tiene artefactos era-Node: verificar que
        las tablas NO existan antes de aplicar (CREATE IF NOT EXISTS callaría
        un esquema viejo divergente)."""
        assert "to_regclass('public.merchant_aliases')" in _SQL
        assert "to_regclass('public.merchant_display_names')" in _SQL
