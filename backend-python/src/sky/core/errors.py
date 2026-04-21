"""
sky.core.errors — Jerarquía de excepciones de dominio.

Principio: cada capa lanza sus propias excepciones tipadas.
Los handlers de FastAPI las mapean a HTTP status codes.
"""


class SkyError(Exception):
    """Base de todas las excepciones de Sky."""
    pass


class NotFoundError(SkyError):
    """Recurso no encontrado (404)."""
    pass


class ForbiddenError(SkyError):
    """Acceso denegado a recurso de otro usuario (403)."""
    pass


class ValidationError(SkyError):
    """Input inválido (400)."""
    pass


class AuthenticationError(SkyError):
    """JWT inválido o ausente (401)."""
    pass


class RateLimitError(SkyError):
    """Demasiadas requests (429)."""
    pass


class ExternalServiceError(SkyError):
    """Error en servicio externo (Supabase, Anthropic, banco)."""
    def __init__(self, service: str, message: str):
        self.service = service
        super().__init__(f"[{service}] {message}")
