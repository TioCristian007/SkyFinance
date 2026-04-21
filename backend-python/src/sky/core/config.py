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
