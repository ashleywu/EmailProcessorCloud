from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from dotenv import load_dotenv

# Always load `.env` from the project root so `python -m app.main ...` works even when cwd is elsewhere.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def redact_secret(value: str | None) -> str:
    """Mask API keys and similar secrets for safe terminal output (e.g. ``show-config``)."""

    if value is None or not str(value).strip():
        return "(not set)"
    s = str(value).strip()
    if len(s) <= 7:
        return "***"
    sl = s.lower()
    if sl.startswith("sk-proj-"):
        return "sk-proj-******"
    if s.startswith("sk-"):
        return "sk-******"
    return s[:4] + "******"


class Settings(BaseSettings):
    """Runtime configuration from environment (see `.env.example`).

    Loaded once via :func:`load_settings`. Use explicit fields — do not read secrets with
    ``os.getenv`` elsewhere.
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    db_path: Path = Field(
        default_factory=lambda: Path.cwd() / "data" / "daily_digest.db",
        validation_alias="DAILY_DIGEST_DB_PATH",
    )
    lock_name: str = Field(default="daily_digest_agent", validation_alias="DAILY_DIGEST_LOCK_NAME")
    lock_ttl_minutes: int = Field(default=60, validation_alias="DAILY_DIGEST_LOCK_TTL_MINUTES")
    max_email_retries: int = Field(default=3, validation_alias="DAILY_DIGEST_MAX_EMAIL_RETRIES")
    #: Maximum number of compose → quality-gate rounds (includes the first draft).
    max_quality_gate_attempts: int = Field(
        default=3,
        ge=1,
        validation_alias="DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS",
    )

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    router_model: str = Field(default="gpt-4o-mini", validation_alias="ROUTER_MODEL")
    processor_model: str = Field(default="gpt-4o-mini", validation_alias="PROCESSOR_MODEL")

    digest_recipient_email: str | None = Field(default=None, validation_alias="DIGEST_RECIPIENT_EMAIL")
    newsletter_senders_csv: str = Field(default="", validation_alias="NEWSLETTER_SENDERS")

    @field_validator("openai_api_key", "digest_recipient_email", mode="before")
    @classmethod
    def _empty_str_none(cls, v: Any) -> Any:
        if v == "":
            return None
        return v

    gmail_credentials_path: Path = Field(
        default_factory=lambda: Path.cwd() / "secrets" / "credentials.json",
        validation_alias="GMAIL_CREDENTIALS_PATH",
    )
    gmail_token_path: Path = Field(
        default_factory=lambda: Path.cwd() / "secrets" / "token.json",
        validation_alias="GMAIL_TOKEN_PATH",
    )
    gmail_lookback_days: int = Field(default=2, validation_alias="GMAIL_LOOKBACK_DAYS")

    @computed_field
    @property
    def newsletter_senders(self) -> tuple[str, ...]:
        raw = self.newsletter_senders_csv
        if raw is None or not str(raw).strip():
            return ()
        parts = [p.strip() for p in str(raw).split(",")]
        return tuple(p for p in parts if p)

    @field_validator("newsletter_senders_csv", mode="before")
    @classmethod
    def _coerce_senders_csv(cls, v: Any) -> Any:
        if v is None:
            return ""
        return v

    @field_validator("db_path", "gmail_credentials_path", "gmail_token_path", mode="before")
    @classmethod
    def _expand_path(cls, v: Any) -> Any:
        if v is None:
            return v
        return Path(v).expanduser() if not isinstance(v, Path) else v.expanduser()


def load_settings() -> Settings:
    """Load settings from environment variables and optional ``.env`` (via python-dotenv)."""

    load_dotenv(_ENV_FILE)
    return Settings()


def build_gmail_client(settings: Settings):
    """Create a Gmail API client using paths from settings.

    Call this from application code instead of constructing ``GmailClient``
    manually so OAuth paths and defaults stay centralized.
    """
    from app.gmail.client import GmailClient

    return GmailClient(
        credentials_path=settings.gmail_credentials_path,
        token_path=settings.gmail_token_path,
    )


def format_gmail_config_summary(settings: Settings) -> str:
    """Return a multi-line configuration summary safe for terminals.

    Credential / token JSON files are never read — no secrets from disk are emitted.
    ``OPENAI_API_KEY`` is redacted.
    """
    from app.gmail.client import DEFAULT_SCOPES
    from app.gmail.labeler import ERROR_LABEL, PROCESSED_LABEL

    lines: list[str] = []

    lines.append(f"OPENAI_API_KEY={redact_secret(settings.openai_api_key)}")
    lines.append(f"ROUTER_MODEL={settings.router_model}")
    lines.append(f"PROCESSOR_MODEL={settings.processor_model}")
    lines.append(f"DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS={settings.max_quality_gate_attempts}")
    lines.append("")

    n_senders = len(settings.newsletter_senders)
    lines.append(f"NEWSLETTER_SENDERS_COUNT={n_senders}")
    senders_display = ",".join(settings.newsletter_senders) if settings.newsletter_senders else "(none)"
    lines.append(f"NEWSLETTER_SENDERS={senders_display}")

    recv = settings.digest_recipient_email or "(not set)"
    lines.append(f"DIGEST_RECIPIENT_EMAIL={recv}")

    lines.append(f"GMAIL_CREDENTIALS_PATH={settings.gmail_credentials_path}")
    lines.append(f"GMAIL_TOKEN_PATH={settings.gmail_token_path}")
    lines.append(f"GMAIL_LOOKBACK_DAYS={settings.gmail_lookback_days}")

    lines.append("gmail_pipeline_labels:")
    lines.append(f"  {PROCESSED_LABEL}")
    lines.append(f"  {ERROR_LABEL}")
    lines.append(
        "(Category labels AI_DIGEST/TECHNOLOGY etc. are not applied; "
        "use only PROCESSED + archive.)",
    )

    lines.append("oauth_scopes:")
    for scope in DEFAULT_SCOPES:
        lines.append(f"  {scope}")

    return "\n".join(lines) + "\n"


def build_run_lock(settings: Settings):
    """Construct a `RunLock` using database path and lock parameters from settings."""
    from app.storage.run_lock import RunLock

    return RunLock(
        settings.db_path,
        lock_name=settings.lock_name,
        ttl_minutes=settings.lock_ttl_minutes,
    )
