"""Runtime configuration. Every secret comes from the environment; nothing is committed."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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
    model_photo: str = "claude-sonnet-5-5"  # evidence photo reading (vision; handwriting and tick marks)
    model_plan: str = "claude-sonnet-5"
    model_tutor: str = "claude-sonnet-5"
    model_book: str = "claude-sonnet-5"  # textbook/chapter mapping (vision + book knowledge)
    book_web_search: bool = True  # let book mapping look the book up on the web (server-side search)
    book_research_timeout_s: float = 45.0  # wall-clock cap on that lookup; mapping goes on without it
    anthropic_api_key: str = ""

    # --- speech
    sarvam_api_key: str = ""
    sarvam_base: str = "https://api.sarvam.ai"
    sarvam_stt_model: str = "saaras:v3"  # mode=transcribe; saarika:v2.5 is deprecated
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_speaker: str = "shubh"  # bulbul:v3 default; speaks all 11 TTS languages
    gnani_api_key: str = ""  # Gnani stays off unless this is set
    gnani_base: str = "https://api.vachana.ai"
    gnani_stt_model: str = "prisma-v3.0"
    gnani_tts_model: str = "timbre-v3.0"
    gnani_tts_voice: str = "Shivani"  # timbre-v3.0 voice; covers all 10 Gnani languages
    stt_timeout_s: float = 25.0  # per provider; the router then falls back to the next one
    tts_timeout_s: float = 20.0
    stt_max_seconds: float = 30.0  # REST limit of both providers; longer WAVs are clipped (and said so)

    # --- budgets / limits
    daily_budget_inr_per_school: float = 250.0
    max_photo_bytes: int = 6 * 1024 * 1024
    max_audio_bytes: int = 10 * 1024 * 1024  # uncompressed WAV: ~5 min at 16 kHz
    photo_ttl_days: int = 7
    audio_ttl_hours: int = 24
    # When true, AI proposals are auto-accepted ONLY if high-confidence + arithmetic-verified (numeracy).
    auto_accept_high_confidence: bool = False

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Hosted Postgres (Neon, Render) hands out postgres:// or postgresql:// URLs, which
        # SQLAlchemy maps to psycopg2. We ship psycopg 3, so name that driver explicitly.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s
