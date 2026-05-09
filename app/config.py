from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration from environment (see `.env.example`)."""

    db_path: Path
    lock_name: str
    lock_ttl_minutes: int
    max_email_retries: int


def load_settings() -> Settings:
    db_default = Path.cwd() / "data" / "daily_digest.db"
    raw_path = os.environ.get("DAILY_DIGEST_DB_PATH")
    db_path = Path(raw_path).expanduser() if raw_path else db_default

    return Settings(
        db_path=db_path,
        lock_name=os.environ.get("DAILY_DIGEST_LOCK_NAME", "daily_digest_agent"),
        lock_ttl_minutes=_int_env("DAILY_DIGEST_LOCK_TTL_MINUTES", 60),
        max_email_retries=_int_env("DAILY_DIGEST_MAX_EMAIL_RETRIES", 3),
    )


def build_run_lock(settings: Settings):
    """Construct a `RunLock` using database path and lock parameters from settings."""
    from app.storage.run_lock import RunLock

    return RunLock(
        settings.db_path,
        lock_name=settings.lock_name,
        ttl_minutes=settings.lock_ttl_minutes,
    )
