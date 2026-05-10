from __future__ import annotations

import base64
from email import message_from_bytes

import pytest

from app.gmail.client import GmailClient
from app.gmail.sender import GmailSender, build_html_message
from tests.fakes import FakeGmailService, FakeHttpError


def _decode_raw(payload: dict[str, str]):
    return message_from_bytes(base64.urlsafe_b64decode(payload["raw"].encode("ascii")))


def test_build_html_message_produces_multipart_with_html_part() -> None:
    payload = build_html_message(
        sender="me@example.com",
        to="you@example.com",
        subject="Daily Digest",
        html="<p>hi</p>",
    )
    assert "raw" in payload

    msg = _decode_raw(payload)
    assert msg["From"] == "me@example.com"
    assert msg["To"] == "you@example.com"
    assert msg["Subject"] == "Daily Digest"
    assert msg.is_multipart()
    types = [p.get_content_type() for p in msg.walk() if not p.is_multipart()]
    assert "text/html" in types


def test_build_html_message_includes_plain_alternative_when_provided() -> None:
    payload = build_html_message(
        sender="me@example.com",
        to="you@example.com",
        subject="Subj",
        html="<p>html body</p>",
        plain="plain body",
    )
    msg = _decode_raw(payload)
    types = [p.get_content_type() for p in msg.walk() if not p.is_multipart()]
    assert "text/plain" in types
    assert "text/html" in types


def test_build_html_message_uses_urlsafe_base64() -> None:
    payload = build_html_message(
        sender="me@example.com",
        to="you@example.com",
        subject="S",
        html="<p>x</p>",
    )
    raw = payload["raw"]
    assert "+" not in raw
    assert "/" not in raw
    base64.urlsafe_b64decode(raw.encode("ascii"))


def test_build_html_message_validates_required_fields() -> None:
    base = dict(sender="a@b", to="c@d", subject="s", html="<p>x</p>")
    for field in ("sender", "to", "subject", "html"):
        kwargs = dict(base)
        kwargs[field] = ""
        with pytest.raises(ValueError):
            build_html_message(**kwargs)


def test_send_html_returns_message_id_and_uses_send_endpoint() -> None:
    service = FakeGmailService()
    client = GmailClient(service_factory=lambda: service)
    sender = GmailSender(client, sender="me@example.com")

    sent_id = sender.send_html(
        to="you@example.com",
        subject="Today's digest",
        html="<h1>news</h1>",
    )

    assert sent_id == "sent-1"
    send_calls = service.call_kwargs("messages.send")
    assert len(send_calls) == 1
    assert send_calls[0]["userId"] == "me"
    assert "raw" in send_calls[0]["body"]

    decoded = _decode_raw(send_calls[0]["body"])
    assert decoded["To"] == "you@example.com"
    assert decoded["Subject"] == "Today's digest"


def test_send_html_retries_after_401_via_client() -> None:
    services = [FakeGmailService(), FakeGmailService()]

    def factory():
        return services.pop(0)

    client = GmailClient(service_factory=factory)
    first_service = client.service
    first_service.queue_failure("messages.send", FakeHttpError(401))

    sender = GmailSender(client, sender="me@example.com")
    sent_id = sender.send_html(
        to="you@example.com", subject="S", html="<p>x</p>"
    )

    assert sent_id == "sent-1"
    assert client.service is not first_service
