from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.gmail.client import GmailClient
from app.gmail.fetcher import (
    DEFAULT_EXCLUDED_LABELS,
    ERROR_LABEL,
    PROCESSED_LABEL,
    GmailFetcher,
    build_query,
    parse_gmail_message,
)
from tests.fakes import FakeGmailService, make_message


FIXED_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)


def test_build_query_includes_each_sender_with_or() -> None:
    q = build_query(
        ["a@x.com", "b@y.com"],
        lookback_days=2,
        now=FIXED_NOW,
    )
    assert "(from:a@x.com OR from:b@y.com)" in q


def test_build_query_excludes_processed_and_error_labels() -> None:
    q = build_query(["a@x.com"], lookback_days=2, now=FIXED_NOW)
    assert f"-label:{PROCESSED_LABEL}" in q
    assert f"-label:{ERROR_LABEL}" in q
    assert DEFAULT_EXCLUDED_LABELS == (PROCESSED_LABEL, ERROR_LABEL)


def test_build_query_uses_after_epoch_for_lookback() -> None:
    q = build_query(["a@x.com"], lookback_days=2, now=FIXED_NOW)
    expected_after = int((FIXED_NOW - timedelta(days=2)).timestamp())
    assert f"after:{expected_after}" in q


def test_build_query_does_not_filter_unread() -> None:
    q = build_query(["a@x.com"], lookback_days=2, now=FIXED_NOW)
    assert "is:unread" not in q
    assert "label:UNREAD" not in q


def test_build_query_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError):
        build_query([], lookback_days=2)
    with pytest.raises(ValueError):
        build_query(["a@x.com"], lookback_days=0)


def test_parse_gmail_message_extracts_headers_and_date() -> None:
    payload = make_message(
        msg_id="m1",
        sender="news@example.com",
        subject="Weekly Update",
        snippet="hello world",
        date="Wed, 06 May 2026 10:00:00 +0000",
        label_ids=["INBOX", "CATEGORY_UPDATES"],
    )
    msg = parse_gmail_message(payload)
    assert msg.message_id == "m1"
    assert msg.sender == "news@example.com"
    assert msg.subject == "Weekly Update"
    assert msg.snippet == "hello world"
    assert msg.received_at == datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc)
    assert msg.label_ids == ("INBOX", "CATEGORY_UPDATES")


def test_parse_gmail_message_handles_missing_optional_fields() -> None:
    msg = parse_gmail_message({"id": "m2", "threadId": "t2"})
    assert msg.message_id == "m2"
    assert msg.subject is None
    assert msg.received_at is None
    assert msg.label_ids == ()


def test_to_email_input_roundtrip() -> None:
    payload = make_message(
        msg_id="m3",
        sender="news@example.com",
        subject="Hi",
        snippet="preview",
        date="Wed, 06 May 2026 10:00:00 +0000",
    )
    ei = parse_gmail_message(payload).to_email_input()
    assert ei.message_id == "m3"
    assert ei.subject == "Hi"
    assert ei.body_preview == "preview"
    assert ei.received_at is not None


def test_fetch_recent_returns_parsed_messages() -> None:
    service = FakeGmailService(
        messages={
            "m1": make_message(msg_id="m1", subject="One"),
            "m2": make_message(msg_id="m2", subject="Two"),
        },
        list_results=[{"messages": [{"id": "m1"}, {"id": "m2"}]}],
    )
    client = GmailClient(service_factory=lambda: service)
    fetcher = GmailFetcher(
        client,
        senders=["newsletter@example.com"],
        lookback_days=2,
    )

    messages = fetcher.fetch_recent(now=FIXED_NOW)

    assert [m.message_id for m in messages] == ["m1", "m2"]
    assert [m.subject for m in messages] == ["One", "Two"]


def test_fetch_recent_query_includes_sender_and_excludes_processed_error() -> None:
    service = FakeGmailService(list_results=[{"messages": []}])
    client = GmailClient(service_factory=lambda: service)
    fetcher = GmailFetcher(
        client,
        senders=["foo@x.com", "bar@y.com"],
        lookback_days=2,
    )

    fetcher.fetch_recent(now=FIXED_NOW)

    list_calls = service.call_kwargs("messages.list")
    assert len(list_calls) == 1
    q = list_calls[0]["q"]
    assert "from:foo@x.com" in q
    assert "from:bar@y.com" in q
    assert f"-label:{PROCESSED_LABEL}" in q
    assert f"-label:{ERROR_LABEL}" in q
    assert list_calls[0]["userId"] == "me"
    assert list_calls[0]["includeSpamTrash"] is False


def test_fetch_recent_paginates_until_no_token() -> None:
    service = FakeGmailService(
        messages={
            "m1": make_message(msg_id="m1"),
            "m2": make_message(msg_id="m2"),
            "m3": make_message(msg_id="m3"),
        },
        list_results=[
            {"messages": [{"id": "m1"}], "nextPageToken": "t1"},
            {"messages": [{"id": "m2"}, {"id": "m3"}]},
        ],
    )
    client = GmailClient(service_factory=lambda: service)
    fetcher = GmailFetcher(client, senders=["a@x.com"], lookback_days=2)

    messages = fetcher.fetch_recent(now=FIXED_NOW)
    assert [m.message_id for m in messages] == ["m1", "m2", "m3"]

    list_calls = service.call_kwargs("messages.list")
    assert len(list_calls) == 2
    assert "pageToken" not in list_calls[0]
    assert list_calls[1]["pageToken"] == "t1"


def test_fetch_recent_returns_empty_for_no_senders() -> None:
    service = FakeGmailService()
    client = GmailClient(service_factory=lambda: service)
    fetcher = GmailFetcher(client, senders=[], lookback_days=2)

    assert fetcher.fetch_recent(now=FIXED_NOW) == []
    assert service.call_kwargs("messages.list") == []
