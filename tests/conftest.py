"""Shared pytest hooks."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _noop_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent tests from loading the developer's local ``.env`` via :func:`load_dotenv`."""

    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **k: None)
