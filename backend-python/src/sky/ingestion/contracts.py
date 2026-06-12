"""
sky.ingestion.contracts — Contrato DataSource y modelo canónico.

ESTA ES LA PIEZA MÁS IMPORTANTE DEL REDISEÑO.

Toda fuente de datos bancarios — scraper, Fintoc, API directa, SFA,
upload manual — implementa DataSource. El dominio (categorización,
Mr. Money, ARIA, summary) consume CanonicalMovement y NUNCA pregunta
de qué fuente vino.

REGLA DOCTRINAL:
    Nada en sky.domain puede preguntar de qué source vino un movimiento.
    Si necesita distinguir origen, el modelo canónico está incompleto
    y hay que enriquecerlo — no romper la abstracción.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

# ── Enums ─────────────────────────────────────────────────────────────────────

class SourceKind(StrEnum):
    """Tipo de fuente de datos."""
    SCRAPER = "scraper"
    AGGREGATOR = "aggregator"       # Fintoc, Belvo
    BANK_API_DIRECT = "bank_api"    # API propia del banco
    SFA = "sfa"                     # Open Banking regulado (CMF)
    MANUAL_UPLOAD = "manual"        # CSV subido por usuario


class AuthMode(StrEnum):
    """Método de autenticación requerido."""
    PASSWORD = "password"           # RUT + clave (scraping)
    OAUTH = "oauth"                 # Tokens access/refresh (Fintoc, bancos)
    API_KEY = "api_key"             # Clave institucional
    CONSENT_TOKEN = "consent"       # Token SFA


class MovementSource(StrEnum):
    """De qué producto bancario viene el movimiento."""
    ACCOUNT = "account"             # Cuenta corriente / vista / RUT
    CREDIT_CARD = "credit_card"     # Tarjeta de crédito
    CREDIT_LINE = "credit_line"     # Línea de crédito


# ── Modelo canónico ──────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CanonicalMovement:
    """
    Movimiento bancario normalizado. Toda fuente produce esto.
    El dominio consume esto. Nunca pregunta de dónde vino.

    external_id es SHA-256 determinístico — la misma transacción
    siempre produce el mismo id, independiente de la fuente.
    """
    external_id: str                 # SHA-256 hash, primeros 16 hex chars
    amount_clp: int                  # Entero en pesos chilenos (negativo = gasto)
    raw_description: str             # Texto bancario original
    occurred_at: date                # Fecha del movimiento
    movement_source: MovementSource  # cuenta, TC, línea de crédito
    source_kind: SourceKind          # trazabilidad: de qué tipo de fuente vino
    source_metadata: dict[str, Any] = field(default_factory=dict)  # libre, debug only


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Saldo de una cuenta bancaria."""
    balance_clp: int
    as_of: datetime                  # cuándo el banco reportó este saldo


# ── Resultado de ingesta ──────────────────────────────────────────────────────

@dataclass(slots=True)
class IngestionResult:
    """Lo que una fuente devuelve al terminar una ingesta."""
    balance: AccountBalance | None
    movements: list[CanonicalMovement]
    source_kind: SourceKind
    source_identifier: str           # ej: "scraper.bchile", "fintoc", "bci.direct"
    elapsed_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Capacidades declaradas ────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class IngestionCapabilities:
    """
    Cada fuente declara qué puede hacer.
    El IngestionRouter las lee para enrutar inteligentemente.
    """
    supports_webhooks: bool = False
    supports_backfill: bool = False
    backfill_days: int = 90
    provides_balance: bool = True
    provides_movements: bool = True
    provides_credit_card: bool = False
    typical_latency_ms: int = 5000
    estimated_failure_rate: float = 0.05  # 5%
    cost_per_invocation_usd: float = 0.0


# ── Credenciales ──────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class BankCredentials:
    """Credenciales descifradas en memoria. Nunca se logean, nunca se persisten."""
    rut: str
    password: str


@dataclass(frozen=True, slots=True)
class OAuthTokens:
    """Tokens OAuth para agregadores y APIs directas."""
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None


# ── Contrato DataSource ──────────────────────────────────────────────────────

# Callback para reportar progreso (2FA, login, etc.)
ProgressCallback = Callable[[str], None]


class DataSource(ABC):
    """
    Contrato que toda fuente de datos bancarios debe implementar.

    Implementaciones concretas:
        - BChileScraperSource   (scraper Playwright)
        - FalabellaScraperSource (scraper Playwright)
        - FintocSource          (API Fintoc)
        - BCIDirectSource       (API directa BCI)
        - SFASource             (Open Banking regulado)
        - ManualUploadSource    (CSV)

    Invariantes:
        - fetch() SIEMPRE devuelve IngestionResult con CanonicalMovement.
        - fetch() NUNCA logea credenciales.
        - fetch() reporta progreso vía on_progress callback.
        - Si falla con error recuperable, lanza RecoverableIngestionError.
        - Si falla con auth, lanza AuthenticationError.
    """

    @property
    @abstractmethod
    def source_identifier(self) -> str:
        """Identificador único, ej: 'scraper.bchile', 'fintoc', 'bci.direct'."""
        ...

    @property
    @abstractmethod
    def source_kind(self) -> SourceKind:
        """Tipo de fuente."""
        ...

    @property
    @abstractmethod
    def supported_banks(self) -> list[str]:
        """Lista de bank_ids que esta fuente puede manejar."""
        ...

    @abstractmethod
    def capabilities(self) -> IngestionCapabilities:
        """Capacidades declaradas de esta fuente."""
        ...

    @abstractmethod
    async def fetch(
        self,
        bank_id: str,
        credentials: BankCredentials | OAuthTokens,
        *,
        on_progress: ProgressCallback | None = None,
        since: date | None = None,
    ) -> IngestionResult:
        """
        Ejecuta la ingesta y devuelve movimientos normalizados.

        Args:
            bank_id: identificador del banco (ej: 'bchile', 'falabella')
            credentials: credenciales descifradas
            on_progress: callback para reportar estado (2FA, login, etc.)
            since: fecha mínima para sync incremental (None = backfill completo)

        Returns:
            IngestionResult con balance y movimientos canónicos.

        Raises:
            AuthenticationError: credenciales rechazadas por el banco.
            RecoverableIngestionError: error transitorio (timeout, red, etc.)
        """
        ...


# ── Excepciones de ingesta ────────────────────────────────────────────────────

class IngestionError(Exception):
    """Base para errores de ingesta."""
    pass


class AuthenticationError(IngestionError):
    """Credenciales rechazadas. No hacer failover — todos los providers fallarían igual."""
    pass


class RecoverableIngestionError(IngestionError):
    """Error transitorio. El router puede intentar el siguiente provider en la cadena."""
    pass


class TwoFactorTimeoutError(RecoverableIngestionError):
    """2FA no fue aprobado dentro del timeout."""
    pass


class FieldFillError(RecoverableIngestionError):
    """Un campo del form de login no quedó con el valor esperado tras llenarlo.

    Detectado por la verificación post-fill (leer input.value antes del submit).
    NO es un error de credenciales: el valor correcto nunca llegó al banco —
    por eso no hereda de AuthenticationError y el router puede hacer failover.

    PII: el mensaje y los atributos solo llevan longitudes — jamás el valor
    del RUT o la clave (doctrina §20).
    """

    def __init__(self, field: str, expected_len: int, got_len: int) -> None:
        self.field = field
        self.expected_len = expected_len
        self.got_len = got_len
        super().__init__(
            f"El campo '{field}' no quedó con el valor esperado tras llenarlo "
            f"(esperado {expected_len} caracteres, quedó {got_len})."
        )


class CircuitOpenError(RecoverableIngestionError):
    """El circuit breaker de la fuente está abierto; no se intentó."""


class AllSourcesFailedError(IngestionError):
    """Toda la cadena de providers falló."""

    def __init__(self, bank_id: str, errors: list[tuple[str, Exception]]):
        self.bank_id = bank_id
        self.errors = errors
        if errors:
            detail = "; ".join(f"{src}: {type(e).__name__}: {e}" for src, e in errors)
        else:
            detail = "sin proveedores disponibles"
        super().__init__(f"Todos los proveedores fallaron para {bank_id}: {detail}")

    @property
    def primary_cause(self) -> Exception | None:
        """Última excepción de la cadena (el proveedor más lejos intentado), o None."""
        return self.errors[-1][1] if self.errors else None


# ── build_external_id — ÚNICO en todo el sistema ─────────────────────────────

def build_external_id(
    bank_id: str,
    occurred_at: date,
    amount_clp: int,
    raw_description: str,
    movement_source: MovementSource = MovementSource.ACCOUNT,
    *,
    native_id: str | None = None,
    balance: int | None = None,
) -> str:
    """
    Genera un external_id determinístico para deduplicación.

    INVARIANTE: la misma transacción real SIEMPRE produce el mismo id,
    sin importar qué source la trajo, cuántas veces se procese, ni
    en qué orden.

    Si el banco provee un identificador nativo (native_id), es la base
    preferida — inmune a cambios de descripción o monto.
    Sin native_id, el fallback incluye balance para máxima unicidad.
    """
    if native_id:
        basis = f"{bank_id}:native:{native_id}"
    else:
        desc_norm = raw_description.lower().strip()[:60]
        date_str = occurred_at.isoformat()
        basis = f"{bank_id}:{movement_source.value}:{date_str}:{amount_clp}:{desc_norm}:{balance}"
    h = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    return f"{bank_id}_{h[:16]}"
