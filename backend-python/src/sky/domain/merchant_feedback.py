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

Invariante de identidad (sprint Fase 2, Bloque 0): merchant_key NO es una
identidad de comercio, es una etiqueta de pago. Las etiquetas de pasarela/
terminal (mercadopago*, paypal*, …) pueden ser comercios distintos para
gente distinta → crowdsourcearlas sería incorrecto (y en wallets P2P, una
fuga de contraparte). Solo se promueve al global una key que identifica
confiablemente UN negocio. El fix profundo (¿una key = un comercio o
varios?) es la Fase 3 (identidad canónica), motivada por este caso.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sky.core.config import settings
from sky.core.db import get_engine
from sky.core.logging import get_logger
from sky.domain.categorizer import TRANSFER_PREFIX_RE, normalize_merchant

logger = get_logger("merchant_feedback")

# Etiquetas de pasarela/terminal de pago: nombran el rail de pago, no el
# comercio. Match por PRIMERA PALABRA de la key normalizada — sin substring,
# para no excluir comercios reales que contengan el token al medio. Lista
# deliberadamente corta (mejor sub-excluir: el umbral de quórum es el
# backstop para lo no listado). NO agregar acá nada que pueda ser el nombre
# real de una tienda.
GATEWAY_LABEL_FIRST_WORDS: frozenset[str] = frozenset({
    "mercadopago",  # caso confirmado: "mercadopago <token>"; además wallet P2P
    "paypal",       # misma estructura GATEWAY *seller; también P2P
    "sumup",        # terminal POS móvil: "sumup *comercio"
    "khipu",        # pasarela de transferencias; jamás identifica al comercio
    "webpay",       # etiqueta de red adquirente
    "transbank",    # etiqueta de red adquirente
})


def _is_gateway_label(merchant_key: str) -> bool:
    """True si la key normalizada es una etiqueta de pasarela/terminal."""
    first_word = merchant_key.split(" ", 1)[0] if merchant_key else ""
    return first_word in GATEWAY_LABEL_FIRST_WORDS


def is_crowdsource_eligible(raw_description: str, category: str) -> bool:
    """Solo keys que identifican confiablemente UN comercio se crowdsourcean.

    Única fuente de la decisión, reusada por votos de categoría (Fase 1) y
    aliases de renombre (Fase 2). Quedan fuera del caché global:
    - descripciones de transferencia/traspaso (la contraparte es una persona)
    - votos cuya categoría final es 'transfer' (señal de contraparte personal,
      aunque la glosa no tenga prefijo de transferencia)
    - etiquetas de pasarela/terminal (mercadopago*, …): la misma etiqueta es
      comercios distintos para gente distinta — per-user only
    """
    if category == "transfer":
        return False
    s = (raw_description or "").strip()
    if not s:
        return False
    if TRANSFER_PREFIX_RE.match(s) is not None:
        return False
    return not _is_gateway_label(normalize_merchant(s))


def _key_is_promotable(merchant_key: str) -> bool:
    """Defensa en profundidad: re-chequeo sobre la key antes del upsert global.

    `crowdsource_eligible` ya filtra en la consulta de quórum; esto protege
    además contra cualquier camino futuro que llame a la promoción con una
    key de transferencia, y contra votos viejos persistidos como elegibles
    antes de que su etiqueta entrara a GATEWAY_LABEL_FIRST_WORDS.
    """
    if not merchant_key:
        return False
    if TRANSFER_PREFIX_RE.match(merchant_key) is not None:
        return False
    return not _is_gateway_label(merchant_key)


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
