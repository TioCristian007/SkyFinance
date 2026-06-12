"""
sky.core.config — Settings centralizados con pydantic-settings.

Toda variable de entorno se declara aquí. Si falta una requerida,
el servidor no arranca (fail-fast, no silent defaults peligrosos).

Uso:
    from sky.core.config import settings
    print(settings.supabase_url)
"""

from functools import lru_cache

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Supabase ──────────────────────────────────────────────────────────
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str

    # ── Anthropic ─────────────────────────────────────────────────────────
    anthropic_api_key: str

    # ── Encryption ────────────────────────────────────────────────────────
    bank_encryption_key: str  # hex string, 64 chars = 32 bytes

    # ── Redis (para ARQ + circuit breaker) ────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── Server ────────────────────────────────────────────────────────────
    port: int = 8000
    node_env: str = "development"
    cors_origins: str = ""  # comma-separated
    cron_secret: str = ""

    # ── Scraping ──────────────────────────────────────────────────────────
    chrome_path: str = "/usr/bin/chromium"
    browser_pool_size: int = 4
    bchile_2fa_timeout_sec: int = 120
    browser_headless: bool = True
    # "chrome" = Chrome real con fallback a bundled · "bundled" = fuerza Chromium
    # bundled (repro del bug '$' del sprint 2026-06-12). Palanca operativa (§14).
    browser_channel: str = "chrome"
    scraper_debug_capture: bool = False
    scraper_debug_dir: str = ""   # vacío = usa carpeta temp del sistema
    # C3 (sprint 2026-06-12): bucket privado de Supabase Storage para capturas
    # debug durables (el /tmp del contenedor es efímero). Vacío = solo local.
    scraper_debug_bucket: str = ""

    # ── Scheduler ─────────────────────────────────────────────────────────
    scheduler_base_interval_hours: float = 1.0

    # ── Fintoc (futuro — deshabilitado por default) ───────────────────────
    fintoc_secret_key: str = ""

    # ── Rate limiting (Fase 5) ────────────────────────────────────────────
    rate_limit_default_max: int = 10
    rate_limit_default_window_sec: int = 60
    # Override por source: "scraper.bchile=2/60,fintoc=30/60"
    rate_limit_overrides: str = ""

    # ── Routing rules (Fase 5) ────────────────────────────────────────────
    routing_rules_cache_ttl_sec: int = 60   # cache en memoria del router
    routing_rules_db_required: bool = False  # si True, falla al arrancar si DB no responde

    # ── Categorización (Fase 6) ───────────────────────────────────────────
    categorize_batch_size: int = 50
    categorize_max_keys_per_ai_call: int = 20
    categorize_anthropic_model: str = "claude-haiku-4-5-20251001"
    categorize_confidence_threshold: float = 0.75

    # ── Sync banking job (Fase 6) ─────────────────────────────────────────
    sync_advisory_lock_timeout_sec: int = 600   # 10 min — máximo razonable
    sync_max_concurrent_per_user: int = 4       # alineado con browser_pool_size
    sync_aria_enabled: bool = True              # respeta aria_consent del user

    # ── Mr. Money — AI chat (Fase 7) ──────────────────────────────────────
    mr_money_model: str = "claude-sonnet-4-6"   # alias sin fecha; pin al snapshot en Fase 13
    mr_money_max_tokens: int = 4096
    mr_money_temperature: float = 0.7
    mr_money_cache_ttl: str = "5m"

    # ── Scheduler / cron interno (Fase 7) ─────────────────────────────────
    scheduler_due_threshold_hours: float = 1.0
    scheduler_max_consecutive_errors: int = 5

    # ── Scheduler / cron ARQ (Fase 9) ──────────────────────────────────────
    scheduler_backoff_factor: int = 2          # Node: BACKOFF_FACTOR = 2
    scheduler_max_backoff_hours: float = 24.0  # Node: MAX_BACKOFF_HOURS = 24
    scheduler_max_per_tick: int = 20           # Node: MAX_ACCOUNTS_PER_TICK = 20

    # ── Database (TODO #7 — Fase 10) ──────────────────────────────────────────
    database_url: str  # fail-fast si falta; db.py hace el replace a +asyncpg

    # ── Observabilidad (Fase 10) ──────────────────────────────────────────────
    sentry_dsn: str = ""  # vacío = Sentry deshabilitado (dev silencioso)

    # ── Audit log salt (Fase 11) ──────────────────────────────────────────────
    # SHA-256(user_id + salt) → user_hash para audit_log. NUNCA rotar este salt
    # en producción — invalida correlación histórica. Mismo nivel de criticidad
    # que BANK_ENCRYPTION_KEY. Vacío = hashing deshabilitado (dev only).
    audit_log_salt: str = ""

    # ── Rate limiting HTTP (Fase 11 — P2-3) ──────────────────────────────────
    api_rate_limit_per_minute: int = 60

    # ── Observabilidad prod (Fase 11) ────────────────────────────────────────
    # Fail-fast si is_production=True y está vacío (verificado en main.py).
    prometheus_secret: str = ""   # vacío = acceso libre en dev

    # ── Idempotency (Fase 11) ────────────────────────────────────────────────
    idempotency_ttl_seconds: int = 86400    # 24h

    # ── Rotación de clave bancaria (Fase 11 — P2-6) ──────────────────────────
    bank_encryption_key_v2: str = ""        # vacío = sin rotación activa

    # ── Audit log retención (Fase 12) ────────────────────────────────────────
    # Ajustable sin redeploy si un banco contractualmente exige retención mayor.
    audit_log_retention_days: int = 90

    # ── ARIA-quali v1 — perfil cualitativo + snapshot ────────────────────────
    # emotion_inference_premium_only: si True, la tool infer_emotional_state solo
    # se registra para usuarios premium. Como profiles.tier no existe aún (deuda),
    # todos los usuarios son tratados como free → tool deshabilitada en prod hasta
    # que se cablee tier.
    emotion_inference_premium_only: bool = True
    profile_snapshot_k_anon_min:    int  = 5   # subir a 10 al cruzar 500 usuarios
    profile_snapshot_jitter_days:   int  = 3

    @field_validator(
        "anthropic_api_key", "supabase_service_key", "bank_encryption_key", "database_url",
        mode="before",
    )
    @classmethod
    def _validate_critical_secret_not_empty(cls, v: object, info: ValidationInfo) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError(
                f"El secreto crítico '{info.field_name}' es vacío o solo espacios — "
                "el servidor no puede arrancar sin él"
            )
        if info.field_name == "anthropic_api_key" and not v.startswith("sk-ant"):
            raise ValueError(
                "anthropic_api_key debe comenzar con el prefijo 'sk-ant' — "
                "verificar ANTHROPIC_API_KEY en el entorno"
            )
        return v

    @property
    def rate_limit_overrides_map(self) -> dict[str, tuple[int, int]]:
        """Parsea 'scraper.bchile=2/60,fintoc=30/60' → {'scraper.bchile': (2, 60), ...}"""
        out: dict[str, tuple[int, int]] = {}
        if not self.rate_limit_overrides:
            return out
        for entry in self.rate_limit_overrides.split(","):
            entry = entry.strip()
            if not entry or "=" not in entry:
                continue
            key, val = entry.split("=", 1)
            if "/" not in val:
                continue
            max_s, win_s = val.split("/", 1)
            try:
                out[key.strip()] = (int(max_s), int(win_s))
            except ValueError:
                continue
        return out

    @property
    def is_production(self) -> bool:
        return self.node_env == "production"

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.cors_origins:
            return []
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def encryption_key_bytes(self) -> bytes:
        return bytes.fromhex(self.bank_encryption_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


# Shortcut — importar directamente
settings = get_settings()
