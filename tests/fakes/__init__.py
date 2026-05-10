"""Shared test doubles for the Gmail integration layer.

Kept under ``tests/`` (not under ``app/``) so they ship only with the
test suite and never leak into runtime imports.
"""

from tests.fakes.gmail import (
    FakeGmailService,
    FakeHttpError,
    FakeResponse,
    make_message,
)

__all__ = ["FakeGmailService", "FakeHttpError", "FakeResponse", "make_message"]
