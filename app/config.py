"""
VSM Backend – Application Configuration (Supabase + Prisma)
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

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "VSM Backend"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:8080,http://127.0.0.1:8080"

    # ── Supabase / Prisma ─────────────────────────────────────────────────────
    # DATABASE_URL  → Supabase pooled connection (used by the app)
    # DIRECT_URL    → Supabase direct connection (used by `prisma db push`)
    database_url: str | None = None
    direct_url: str | None = None

    # ── Redis (Celery broker + result backend) ────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Event Aggregation ─────────────────────────────────────────────────────
    aggregation_window_seconds: int = 5
    aggregation_max_events: int = 100

    # ── AI Agent Layer ────────────────────────────────────────────────────────
    ai_agent_url: str = "http://localhost:8001"
    ai_agent_timeout: int = 30

    # ── Webhook Security ──────────────────────────────────────────────────────
    github_webhook_secret: str | None = None
    webhook_hmac_enabled: bool = True

    # ── GitHub App Integration ────────────────────────────────────────────────
    github_app_id: str | None = None
    github_private_key: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None

    # ── Backend URL (for workers calling API) ─────────────────────────────────
    backend_url: str = "http://localhost:8000"

    # ── AI Service Account Identity ───────────────────────────────────────────
    # The AI must authenticate as a normal user (service account) and pass RBAC.
    ai_service_user_id: int = 0

    # ── Celery Task Settings ──────────────────────────────────────────────────
    celery_task_max_retries: int = 3
    celery_task_retry_backoff: int = 5

    # ── Email Settings (Gmail SMTP) ───────────────────────────────────────────
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "onboarding@vsm.dev"
    
    # ── Frontend Settings ─────────────────────────────────────────────────────
    frontend_url: str = "http://localhost:8080"

    # ── NLP Confidence Thresholds ─────────────────────────────────────────────
    nlp_auto_execute_threshold: float = 0.85
    nlp_ask_user_threshold: float = 0.60

    # ── Unlinked Activity AI ──────────────────────────────────────────────────
    unlinked_auto_link_threshold: float = 0.85
    unlinked_ask_user_threshold: float = 0.60


@lru_cache
def get_settings() -> Settings:
    return Settings()
