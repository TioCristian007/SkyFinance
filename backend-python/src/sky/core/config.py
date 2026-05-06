"""
sky.core.config — Settings centralizados con pydantic-settings.

Toda variable de entorno se declara aquí. Si falta una requerida,
el servidor no arranca (fail-fast, no silent defaults peligrosos).

Uso:
    from sky.core.config import settings
    print(settings.supabase_url)
"""

from functools import lru_cache

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
    mr_money_model: str = "claude-sonnet-4-7-20250930"
    mr_money_max_tokens: int = 4096
    mr_money_temperature: float = 0.7
    mr_money_cache_ttl: str = "5m"

    # ── Scheduler / cron interno (Fase 7) ─────────────────────────────────
    scheduler_due_threshold_hours: float = 1.0
    scheduler_max_consecutive_errors: int = 5

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
