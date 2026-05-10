from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from app.config import Settings, build_gmail_client, format_gmail_config_summary
from app.main import main


@pytest.fixture
def minimal_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "db.sqlite",
        lock_name="daily_digest_agent",
        lock_ttl_minutes=60,
        max_email_retries=3,
        newsletter_senders=("a@news.example", "b@digest.example"),
        digest_recipient_email="reader@example.com",
        gmail_credentials_path=tmp_path / "credentials.json",
        gmail_token_path=tmp_path / "token.json",
        gmail_lookback_days=2,
    )


def test_format_gmail_config_summary_includes_allowed_fields(
    minimal_settings: Settings,
) -> None:
    out = format_gmail_config_summary(minimal_settings)

    assert "NEWSLETTER_SENDERS_COUNT=2" in out
    assert "NEWSLETTER_SENDERS=a@news.example,b@digest.example" in out
    assert "DIGEST_RECIPIENT_EMAIL=reader@example.com" in out
    assert str(minimal_settings.gmail_credentials_path) in out
    assert str(minimal_settings.gmail_token_path) in out
    assert "GMAIL_LOOKBACK_DAYS=2" in out
    assert "AI_DIGEST_PROCESSED" in out
    assert "AI_DIGEST_ERROR" in out
    assert "AI_DIGEST/TECHNOLOGY" in out
    assert "AI_DIGEST/RADAR" in out
    assert "https://www.googleapis.com/auth/gmail.modify" in out
    assert "https://www.googleapis.com/auth/gmail.send" in out


def test_format_gmail_config_summary_does_not_read_credential_or_token_files(
    tmp_path: Path,
) -> None:
    client_secret = "LEAK_TEST_CLIENT_SECRET_88421"
    access = "LEAK_TEST_ACCESS_TOKEN_99211"
    refresh = "LEAK_TEST_REFRESH_TOKEN_77330"

    cred_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"

    cred_path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "cid",
                    "client_secret": client_secret,
                }
            },
        ),
        encoding="utf-8",
    )
    token_path.write_text(
        json.dumps(
            {
                "token": access,
                "refresh_token": refresh,
                "scope": "https://www.googleapis.com/auth/gmail.modify",
            },
        ),
        encoding="utf-8",
    )

    settings = Settings(
        db_path=tmp_path / "db.sqlite",
        lock_name="daily_digest_agent",
        lock_ttl_minutes=60,
        max_email_retries=3,
        newsletter_senders=("x@y.com",),
        digest_recipient_email=None,
        gmail_credentials_path=cred_path,
        gmail_token_path=token_path,
        gmail_lookback_days=2,
    )

    # Open files and never read them in the formatter (regression guard).
    reader = mock.Mock(side_effect=AssertionError("credential/token files must not be read"))
    with mock.patch.object(Path, "read_text", reader):
        out = format_gmail_config_summary(settings)

    assert client_secret not in out
    assert access not in out
    assert refresh not in out
    assert "LEAK_TEST_" not in out
    assert str(cred_path) in out
    assert str(token_path) in out
    reader.assert_not_called()


def test_main_show_config_stdout_no_secrets_with_env_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cred = tmp_path / "c.json"
    tok = tmp_path / "t.json"
    secret_marker = "SHOW_CONFIG_SECRET_MARKER_7711"
    tok_marker = "SHOW_CONFIG_TOKEN_MARKER_6622"
    cred.write_text(json.dumps({"installed": {"client_secret": secret_marker}}), encoding="utf-8")
    tok.write_text(
        json.dumps({"token": tok_marker, "refresh_token": "SHOW_CONFIG_RT_5511"}),
        encoding="utf-8",
    )

    monkeypatch.setenv("NEWSLETTER_SENDERS", "n1@e.com")
    monkeypatch.setenv("DIGEST_RECIPIENT_EMAIL", "recv@e.com")
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(cred))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tok))
    monkeypatch.setenv("GMAIL_LOOKBACK_DAYS", "4")
    monkeypatch.delenv("DAILY_DIGEST_DB_PATH", raising=False)

    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        code = main(["show-config"])
    assert code == 0

    out = buf.getvalue()
    assert secret_marker not in out
    assert tok_marker not in out
    assert "SHOW_CONFIG_RT_5511" not in out
    assert "NEWSLETTER_SENDERS_COUNT=1" in out
    assert "NEWSLETTER_SENDERS=n1@e.com" in out
    assert "DIGEST_RECIPIENT_EMAIL=recv@e.com" in out
    assert str(cred) in out
    assert str(tok) in out
    assert "GMAIL_LOOKBACK_DAYS=4" in out


def test_main_show_config_subprocess_no_secrets(
    tmp_path: Path,
) -> None:
    secret = "SUBPROC_CLIENT_SECRET_991199"
    token = "SUBPROC_ACCESS_882288"
    rt = "SUBPROC_REFRESH_773377"
    cred = tmp_path / "subc.json"
    tok = tmp_path / "subt.json"
    cred.write_text(json.dumps({"web": {"client_secret": secret}}), encoding="utf-8")
    tok.write_text(json.dumps({"token": token, "refresh_token": rt}), encoding="utf-8")

    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["GMAIL_CREDENTIALS_PATH"] = str(cred)
    env["GMAIL_TOKEN_PATH"] = str(tok)
    env["NEWSLETTER_SENDERS"] = "ping@example.com"
    env.pop("DIGEST_RECIPIENT_EMAIL", None)

    proc = subprocess.run(
        [sys.executable, "-m", "app.main", "show-config"],
        cwd=str(project_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    out = proc.stdout + proc.stderr
    assert secret not in out
    assert token not in out
    assert rt not in out
    assert "NEWSLETTER_SENDERS_COUNT=1" in out
    assert "NEWSLETTER_SENDERS=ping@example.com" in out


def test_format_gmail_config_summary_sender_count_when_empty(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "db.sqlite",
        lock_name="daily_digest_agent",
        lock_ttl_minutes=60,
        max_email_retries=3,
        newsletter_senders=(),
    )
    out = format_gmail_config_summary(settings)
    assert "NEWSLETTER_SENDERS_COUNT=0" in out
    assert "NEWSLETTER_SENDERS=(none)" in out


def test_build_gmail_client_forwards_paths_from_settings(tmp_path: Path) -> None:
    s = Settings(
        db_path=tmp_path / "d.db",
        lock_name="daily_digest_agent",
        lock_ttl_minutes=60,
        max_email_retries=3,
        gmail_credentials_path=tmp_path / "g1.json",
        gmail_token_path=tmp_path / "g2.json",
    )
    with mock.patch("app.gmail.client.GmailClient") as ctor:
        client = build_gmail_client(s)

    ctor.assert_called_once_with(
        credentials_path=s.gmail_credentials_path,
        token_path=s.gmail_token_path,
    )
    assert client is ctor.return_value

