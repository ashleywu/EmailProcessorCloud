from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import load_settings


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    for key in (
        "NEWSLETTER_SENDERS",
        "DIGEST_RECIPIENT_EMAIL",
        "GMAIL_CREDENTIALS_PATH",
        "GMAIL_TOKEN_PATH",
        "GMAIL_LOOKBACK_DAYS",
        "DAILY_DIGEST_DB_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def test_load_settings_defaults_for_gmail() -> None:
    settings = load_settings()
    assert settings.newsletter_senders == ()
    assert settings.digest_recipient_email is None
    assert settings.gmail_lookback_days == 2
    assert settings.gmail_credentials_path.name == "credentials.json"
    assert settings.gmail_token_path.name == "token.json"


def test_load_settings_parses_csv_senders(monkeypatch) -> None:
    monkeypatch.setenv("NEWSLETTER_SENDERS", " a@x.com , b@y.com ,, c@z.com ")
    settings = load_settings()
    assert settings.newsletter_senders == ("a@x.com", "b@y.com", "c@z.com")


def test_load_settings_reads_recipient_and_lookback(monkeypatch) -> None:
    monkeypatch.setenv("DIGEST_RECIPIENT_EMAIL", "you@example.com")
    monkeypatch.setenv("GMAIL_LOOKBACK_DAYS", "5")
    settings = load_settings()
    assert settings.digest_recipient_email == "you@example.com"
    assert settings.gmail_lookback_days == 5


def test_load_settings_uses_explicit_paths(monkeypatch, tmp_path) -> None:
    creds = tmp_path / "c.json"
    token = tmp_path / "t.json"
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(creds))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token))
    settings = load_settings()
    assert settings.gmail_credentials_path == creds
    assert settings.gmail_token_path == token
