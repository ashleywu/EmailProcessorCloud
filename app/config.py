from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _path_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return Path(raw).expanduser()


def _csv_env(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    parts = [item.strip() for item in raw.split(",")]
    return tuple(p for p in parts if p)


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration from environment (see `.env.example`)."""

    db_path: Path
    lock_name: str
    lock_ttl_minutes: int
    max_email_retries: int

    newsletter_senders: tuple[str, ...] = field(default_factory=tuple)
    digest_recipient_email: str | None = None
    gmail_credentials_path: Path = field(default_factory=lambda: Path("secrets/credentials.json"))
    gmail_token_path: Path = field(default_factory=lambda: Path("secrets/token.json"))
    gmail_lookback_days: int = 2


def load_settings() -> Settings:
    db_default = Path.cwd() / "data" / "daily_digest.db"
    raw_path = os.environ.get("DAILY_DIGEST_DB_PATH")
    db_path = Path(raw_path).expanduser() if raw_path else db_default

    return Settings(
        db_path=db_path,
        lock_name=os.environ.get("DAILY_DIGEST_LOCK_NAME", "daily_digest_agent"),
        lock_ttl_minutes=_int_env("DAILY_DIGEST_LOCK_TTL_MINUTES", 60),
        max_email_retries=_int_env("DAILY_DIGEST_MAX_EMAIL_RETRIES", 3),
        newsletter_senders=_csv_env("NEWSLETTER_SENDERS"),
        digest_recipient_email=os.environ.get("DIGEST_RECIPIENT_EMAIL") or None,
        gmail_credentials_path=_path_env(
            "GMAIL_CREDENTIALS_PATH",
            Path.cwd() / "secrets" / "credentials.json",
        ),
        gmail_token_path=_path_env(
            "GMAIL_TOKEN_PATH",
            Path.cwd() / "secrets" / "token.json",
        ),
        gmail_lookback_days=_int_env("GMAIL_LOOKBACK_DAYS", 2),
    )


def build_run_lock(settings: Settings):
    """Construct a `RunLock` using database path and lock parameters from settings."""
    from app.storage.run_lock import RunLock

    return RunLock(
        settings.db_path,
        lock_name=settings.lock_name,
        ttl_minutes=settings.lock_ttl_minutes,
    )
