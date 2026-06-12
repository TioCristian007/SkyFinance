"""Pin del contenido de migrations/014_merchant_category_votes.sql.

La guarda de prioridad vive en plpgsql y no se puede ejecutar en unit tests
(la verificación funcional la hace scripts/verify_merchant_priority_guard.py
contra DB real). Estos tests pinean los invariantes del ARCHIVO para que nadie
los "simplifique" antes de aplicarlo — mismo espíritu que el pin de
CAST(:detail AS jsonb) en test_audit.py.
"""
from __future__ import annotations

import re
from pathlib import Path

_SQL = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "014_merchant_category_votes.sql"
).read_text(encoding="utf-8")


class TestGuardaDePrioridad:
    def test_on_conflict_tiene_where_guard(self) -> None:
        """Invariante 1 del sprint: un voto 'user' jamás lo pisa la IA."""
        assert "WHERE merchant_categories.source <> 'user'" in _SQL
        assert "OR EXCLUDED.source = 'user'" in _SQL

    def test_guard_es_clausula_del_on_conflict(self) -> None:
        """El WHERE debe pertenecer al DO UPDATE, después del SET."""
        m = re.search(
            r"ON CONFLICT \(merchant_key\) DO UPDATE SET.*?"
            r"WHERE merchant_categories\.source <> 'user'",
            _SQL,
            re.DOTALL,
        )
        assert m is not None

    def test_firma_de_funcion_compatible(self) -> None:
        """Misma firma era-Node: el código viejo en prod sigue funcionando."""
        assert "p_merchant_key TEXT" in _SQL
        assert "p_category     TEXT" in _SQL
        assert "p_source       TEXT DEFAULT 'ai'" in _SQL
        assert "p_confidence   NUMERIC DEFAULT NULL" in _SQL


class TestCheckSource:
    def test_check_acepta_user(self) -> None:
        assert "CHECK (source IN ('ai', 'manual', 'rule', 'user'))" in _SQL

    def test_drop_por_inspeccion_no_por_nombre_fijo(self) -> None:
        """Artefacto era-Node: el nombre del CHECK puede variar entre entornos."""
        assert "pg_get_constraintdef(oid) ILIKE '%source%'" in _SQL


class TestTablaVotos:
    def test_fk_profiles_on_delete_cascade(self) -> None:
        """Convención Sky: FK a public.profiles, NO a auth.users."""
        assert "REFERENCES public.profiles(id) ON DELETE CASCADE" in _SQL
        assert "auth.users" not in _SQL

    def test_pk_compuesta_usuario_comercio(self) -> None:
        assert "PRIMARY KEY (user_id, merchant_key)" in _SQL

    def test_rls_habilitado_con_policy_por_usuario(self) -> None:
        """Doctrina §18: RLS en toda tabla nueva de public."""
        assert (
            "ALTER TABLE public.merchant_category_votes ENABLE ROW LEVEL SECURITY"
            in _SQL
        )
        assert "USING (auth.uid() = user_id)" in _SQL
        assert "WITH CHECK (auth.uid() = user_id)" in _SQL

    def test_crowdsource_eligible_default_false(self) -> None:
        """Frontera de privacidad: por defecto un voto NO es crowdsourceable."""
        assert re.search(
            r"crowdsource_eligible\s+boolean\s+NOT NULL DEFAULT false", _SQL
        )

    def test_indice_parcial_solo_votos_elegibles(self) -> None:
        assert re.search(
            r"ON public\.merchant_category_votes \(merchant_key, category\)\s+"
            r"WHERE crowdsource_eligible",
            _SQL,
        )

    def test_check_categorias_canonicas(self) -> None:
        """Las 16 categorías canónicas de CATEGORIES (categorizer.py)."""
        from sky.domain.categorizer import CATEGORIES

        m = re.search(
            r"merchant_category_votes_category_check\s+CHECK \(category IN \((.*?)\)\)",
            _SQL,
            re.DOTALL,
        )
        assert m is not None
        in_sql = {c.strip().strip("'") for c in m.group(1).split(",")}
        assert in_sql == set(CATEGORIES)


class TestOrdenDeDeploy:
    def test_advertencia_de_orden_presente(self) -> None:
        """Como la 013: migración ANTES que el código que escribe."""
        assert "ORDEN DE DEPLOY" in _SQL
