from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents.daily_digest_agent import DailyDigestAgent
from app.main import main
from app.storage.repository import StateRepository


def test_preview_digest_no_rows_returns_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "empty.db"
    monkeypatch.setenv("DAILY_DIGEST_DB_PATH", str(db))
    err = io.StringIO()
    with patch("sys.stderr", err):
        code = main(["preview-digest", "--date", "2026-05-10"])
    assert code == 1
    assert "No digest found" in err.getvalue()


def test_preview_digest_empty_body_returns_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "d.db"
    monkeypatch.setenv("DAILY_DIGEST_DB_PATH", str(db))
    repo = StateRepository(db)
    try:
        ts = "2026-05-10T12:00:00+00:00"
        repo.connection.execute(
            """
            INSERT INTO digests (status, title, body_html, created_at, updated_at)
            VALUES ('draft', 't', NULL, ?, ?)
            """,
            (ts, ts),
        )
        repo.connection.commit()
    finally:
        repo.close()

    err = io.StringIO()
    with patch("sys.stderr", err):
        code = main(["preview-digest", "--date", "2026-05-10"])
    assert code == 1
    assert "no preview HTML" in err.getvalue()


def test_preview_digest_writes_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "d.db"
    monkeypatch.setenv("DAILY_DIGEST_DB_PATH", str(db))
    repo = StateRepository(db)
    try:
        ts = "2026-05-10T15:00:00+00:00"
        repo.connection.execute(
            """
            INSERT INTO digests (status, title, body_html, created_at, updated_at)
            VALUES ('sent', 't', '<p>Hi</p>', ?, ?)
            """,
            (ts, ts),
        )
        repo.connection.commit()
    finally:
        repo.close()

    out = io.StringIO()
    with patch("sys.stdout", out):
        code = main(["preview-digest", "--date", "2026-05-10"])
    assert code == 0
    assert "<p>Hi</p>" in out.getvalue()


def test_run_daily_requires_digest_recipient(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_DIGEST_DB_PATH", str(tmp_path / "d.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-testing-only")
    monkeypatch.delenv("DIGEST_RECIPIENT_EMAIL", raising=False)
    err = io.StringIO()
    with patch("sys.stderr", err):
        code = main(["run-daily"])
    assert code == 1
    assert "DIGEST_RECIPIENT_EMAIL" in err.getvalue()


def test_run_daily_requires_openai_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_DIGEST_DB_PATH", str(tmp_path / "d.db"))
    monkeypatch.setenv("DIGEST_RECIPIENT_EMAIL", "reader@test.example")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    err = io.StringIO()
    with patch("sys.stderr", err):
        code = main(["run-daily"])
    assert code == 1
    assert "OPENAI_API_KEY" in err.getvalue()


def test_run_daily_exits_1_when_lock_not_acquired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DAILY_DIGEST_DB_PATH", str(tmp_path / "d.db"))
    monkeypatch.setenv("DIGEST_RECIPIENT_EMAIL", "reader@test.example")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-testing-only")
    monkeypatch.setenv("NEWSLETTER_SENDERS", "news@test.example")

    fetcher_inst = MagicMock()
    fetcher_inst.fetch_recent.return_value = []

    err = io.StringIO()
    with (
        patch("sys.stderr", err),
        patch("app.main.build_gmail_client", return_value=MagicMock()),
        patch("app.main.GmailFetcher", return_value=fetcher_inst),
        patch.object(DailyDigestAgent, "run_daily", return_value=False),
    ):
        code = main(["run-daily"])
    assert code == 1
    assert "lock" in err.getvalue().lower()
