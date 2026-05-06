"""sky.api.routers.webhooks — Webhooks de integraciones externas."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from sky.core.logging import get_logger

logger = get_logger("api.webhooks")
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/fintoc")
async def fintoc_webhook(request: Request) -> dict[str, str]:
    """
    Webhook de Fintoc. Valida x-fintoc-signature.

    TODO (Fase futura): implementar verificación real de firma HMAC-SHA256
    usando fintoc_secret_key. Por ahora se requiere que el header exista.
    """
    signature = request.headers.get("x-fintoc-signature", "")
    if not signature:
        logger.warning("fintoc_webhook_missing_signature")
        raise HTTPException(status_code=401, detail="Firma de webhook requerida")

    # TODO: validate HMAC-SHA256(signature, body, settings.fintoc_secret_key)
    logger.info("fintoc_webhook_received", signature_present=True)
    return {"status": "received"}
