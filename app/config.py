"""Configuration loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models import Urgency


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Claude
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5"
    classifier_timeout_seconds: float = 20.0

    # Zendesk
    zendesk_subdomain: str | None = None
    zendesk_email: str | None = None
    zendesk_api_token: str | None = None
    zendesk_webhook_secret: str | None = None
    signature_tolerance_seconds: int = 300

    # Slack
    slack_webhook_url: str | None = None
    slack_alert_min_urgency: Urgency = Urgency.HIGH

    # App
    demo_mode: bool = True
    log_level: str = "INFO"

    @property
    def zendesk_enabled(self) -> bool:
        return bool(self.zendesk_subdomain and self.zendesk_email and self.zendesk_api_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()
