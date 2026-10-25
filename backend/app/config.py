"""Runtime configuration. Every secret comes from the environment; nothing is committed."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
CONTENT_DIR = REPO_DIR / "content"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    # --- core
    database_url: str = f"sqlite:///{BACKEND_DIR / 'kaksha_dev.db'}"
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 720
    cors_origins: str = "*"
    upload_dir: Path = BACKEND_DIR / "uploads"
    seed_on_startup: bool = True
    content_dir: Path = CONTENT_DIR

    # --- models (single source of truth; prompts never hard-code an id)
    model_extract: str = "claude-haiku-4-5-20251001"
    model_plan: str = "claude-sonnet-4-5-20250929"
    model_tutor: str = "claude-sonnet-4-5-20250929"
    anthropic_api_key: str = ""

    # --- speech
    sarvam_api_key: str = ""
    sarvam_base: str = "https://api.sarvam.ai"

    # --- budgets / limits
    daily_budget_inr_per_school: float = 250.0
    max_photo_bytes: int = 6 * 1024 * 1024
    max_audio_bytes: int = 4 * 1024 * 1024
    photo_ttl_days: int = 7
    audio_ttl_hours: int = 24
    # When true, AI proposals are auto-accepted ONLY if high-confidence + arithmetic-verified (numeracy).
    auto_accept_high_confidence: bool = False

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s
