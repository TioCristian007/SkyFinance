"""
sky.domain.merchant_feedback — Feedback loop de categorización.

Es el "§4 votos crowdsourced" diferido desde Fase 6: cuando un usuario
recategoriza una transacción, el sistema aprende.

1. El voto se registra en `merchant_category_votes` y aplica DE INMEDIATO a
   las futuras transacciones de ese usuario (capa 0 del categorizador).
2. Si el comercio es elegible para crowdsourcing y la categoría mayoritaria
   junta >= `merchant_vote_promotion_threshold` usuarios distintos, se
   promueve al caché global (`merchant_categories` con source='user').
   La guarda de prioridad de `upsert_merchant_category` (migración 014)
   garantiza que la IA nunca pise esa fila.

Frontera de privacidad (doctrina §5/§21 — lo más sensible del sprint):
transferencias y contrapartes personales NUNCA entran al caché global.
La elegibilidad se decide acá, al momento del voto — la única instancia
con la `raw_description` a mano — y se persiste en `crowdsource_eligible`.
El voto inelegible sigue valiendo como override privado del usuario.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.domain.categorizer import TRANSFER_PREFIX_RE, normalize_merchant

logger = get_logger("merchant_feedback")


def is_crowdsource_eligible(raw_description: str, category: str) -> bool:
    """Solo comercios reales se crowdsourcean.

    Quedan fuera del caché global:
    - descripciones de transferencia/traspaso (la contraparte es una persona)
    - votos cuya categoría final es 'transfer' (señal de contraparte personal,
      aunque la glosa no tenga prefijo de transferencia)
    """
    if category == "transfer":
        return False
    s = (raw_description or "").strip()
    if not s:
        return False
    return TRANSFER_PREFIX_RE.match(s) is None


def _key_is_promotable(merchant_key: str) -> bool:
    """Defensa en profundidad: re-chequeo sobre la key antes del upsert global.

    `crowdsource_eligible` ya filtra en la consulta de quórum; esto protege
    además contra cualquier camino futuro que llame a la promoción con una
    key de transferencia.
    """
    return bool(merchant_key) and TRANSFER_PREFIX_RE.match(merchant_key) is None


async def _maybe_promote(conn: AsyncConnection, merchant_key: str) -> None:
    """Promueve la categoría mayoritaria al caché global si hay quórum.

    Mayoría = categoría con más usuarios DISTINTOS entre los votos elegibles
    de la key (no necesariamente la del voto recién emitido). Sin quórum no
    se escribe nada: un solo usuario jamás contamina el caché global.
    """
    if not _key_is_promotable(merchant_key):
        return

    rs = await conn.execute(
        text("""
            SELECT category, COUNT(DISTINCT user_id) AS voters
              FROM public.merchant_category_votes
             WHERE merchant_key = :mkey AND crowdsource_eligible
             GROUP BY category
             ORDER BY voters DESC, MAX(updated_at) DESC
             LIMIT 1
        """),
        {"mkey": merchant_key},
    )
    row = rs.first()
    if row is None:
        return

    voters = int(row.voters)
    if voters < settings.merchant_vote_promotion_threshold:
        return

    await conn.execute(
        text("""
            SELECT public.upsert_merchant_category(
                :p_merchant_key, :p_category, 'user', 1.0
            )
        """),
        {"p_merchant_key": merchant_key, "p_category": row.category},
    )
    logger.info(
        "merchant_category_promoted",
        merchant=merchant_key,
        category=str(row.category),
        voters=voters,
    )


async def record_user_categorization(
    user_id: str,
    raw_description: str,
    category: str,
) -> None:
    """Registra el voto del usuario y promueve al caché global si hay quórum.

    Voto y promoción van en UNA transacción (el conteo de quórum ve el voto
    recién emitido). Lanza excepción si la escritura falla — el caller decide
    si es fatal (el endpoint de recategorización lo trata como best-effort).
    """
    merchant_key = normalize_merchant(raw_description or "")
    if not merchant_key:
        return

    eligible = is_crowdsource_eligible(raw_description, category)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO public.merchant_category_votes
                       (user_id, merchant_key, category, crowdsource_eligible)
                VALUES (:uid, :mkey, :cat, :elig)
                ON CONFLICT (user_id, merchant_key) DO UPDATE SET
                    category             = EXCLUDED.category,
                    crowdsource_eligible = EXCLUDED.crowdsource_eligible,
                    updated_at           = NOW()
            """),
            {"uid": user_id, "mkey": merchant_key, "cat": category, "elig": eligible},
        )
        if eligible:
            await _maybe_promote(conn, merchant_key)

    # Las keys inelegibles pueden contener nombres propios → no van a logs.
    logger.info(
        "merchant_vote_recorded",
        merchant=merchant_key if eligible else "<contraparte personal>",
        category=category,
        eligible=eligible,
    )
