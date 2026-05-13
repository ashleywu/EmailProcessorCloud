from __future__ import annotations

import base64
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape as html_escape
from typing import Any

from app.models.email import EmailInput

PROCESSED_LABEL = "AI_DIGEST_PROCESSED"
ERROR_LABEL = "AI_DIGEST_ERROR"
DEFAULT_EXCLUDED_LABELS: tuple[str, ...] = (PROCESSED_LABEL, ERROR_LABEL)


@dataclass(frozen=True, slots=True)
class GmailMessage:
    """Lightweight, pickle-safe view of a Gmail message used by the
    pipeline. Only the fields needed for routing/persistence are kept."""

    message_id: str
    thread_id: str
    sender: str
    subject: str | None = None
    snippet: str | None = None
    received_at: datetime | None = None
    label_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_email_input(self) -> EmailInput:
        raw_from = (self.sender or "").strip()
        return EmailInput(
            message_id=self.message_id,
            subject=self.subject,
            sender=raw_from or None,
            body_preview=self.snippet,
            received_at=self.received_at,
        )


def build_query(
    senders: Sequence[str],
    *,
    lookback_days: int,
    exclude_labels: Sequence[str] = DEFAULT_EXCLUDED_LABELS,
    now: datetime | None = None,
) -> str:
    """Construct a Gmail search query for the configured senders.

    The query intentionally:
    - groups senders with OR so any of them matches,
    - uses ``after:`` with an absolute epoch (deterministic, unlike
      ``newer_than`` which depends on Gmail's clock),
    - excludes the processed/error labels so re-runs are idempotent,
    - does NOT filter on ``is:unread`` so already-read newsletters are
      still picked up on the first scheduled run after the user reads
      them in the inbox.
    """

    if not senders:
        raise ValueError("build_query requires at least one sender.")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive.")

    now = now or datetime.now(timezone.utc)
    after_ts = int((now - timedelta(days=lookback_days)).timestamp())

    sender_clause = " OR ".join(f"from:{s}" for s in senders)
    parts = [f"({sender_clause})", f"after:{after_ts}"]
    parts.extend(f"-label:{label}" for label in exclude_labels)
    return " ".join(parts)


def _header(headers: Iterable[dict[str, str]], name: str) -> str | None:
    target = name.lower()
    for h in headers:
        if str(h.get("name", "")).lower() == target:
            return h.get("value")
    return None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _decode_body_data(data: str | None) -> bytes:
    if not data:
        return b""
    pad = (-len(data)) % 4
    return base64.urlsafe_b64decode(data + ("=" * pad))


def extract_html_from_gmail_payload(payload: Mapping[str, Any]) -> str:
    """Best-effort HTML body from a Gmail ``messages.get`` payload (full format)."""

    def from_part(part: Mapping[str, Any]) -> str | None:
        mime = str(part.get("mimeType") or "")
        if mime == "text/html":
            raw = _decode_body_data((part.get("body") or {}).get("data"))
            return raw.decode("utf-8", errors="replace")
        nested = part.get("parts") or []
        for p in nested:
            got = from_part(p)
            if got:
                return got
        return None

    root = payload.get("payload") or {}
    html = from_part(root)
    if html:
        return html
    mime = str(root.get("mimeType") or "")
    if mime == "text/plain":
        raw = _decode_body_data((root.get("body") or {}).get("data"))
        text = raw.decode("utf-8", errors="replace")
        return f"<html><body><pre>{html_escape(text)}</pre></body></html>"
    return "<html><body></body></html>"


def parse_gmail_message(payload: dict) -> GmailMessage:
    """Convert a Gmail ``users.messages.get`` response into ``GmailMessage``."""

    msg_payload = payload.get("payload") or {}
    headers = msg_payload.get("headers") or []
    return GmailMessage(
        message_id=str(payload["id"]),
        thread_id=str(payload.get("threadId") or ""),
        sender=_header(headers, "From") or "",
        subject=_header(headers, "Subject"),
        snippet=payload.get("snippet"),
        received_at=_parse_date(_header(headers, "Date")),
        label_ids=tuple(payload.get("labelIds") or ()),
    )


class GmailFetcher:
    """Fetch newsletter messages for the configured senders."""

    def __init__(
        self,
        client,
        *,
        senders: Sequence[str],
        lookback_days: int = 2,
        excluded_labels: Sequence[str] = DEFAULT_EXCLUDED_LABELS,
        user_id: str = "me",
        max_results: int | None = None,
    ) -> None:
        self._client = client
        self._senders = tuple(senders)
        self._lookback_days = lookback_days
        self._excluded_labels = tuple(excluded_labels)
        self._user_id = user_id
        self._max_results = max_results

    def build_query(self, *, now: datetime | None = None) -> str:
        return build_query(
            self._senders,
            lookback_days=self._lookback_days,
            exclude_labels=self._excluded_labels,
            now=now,
        )

    def fetch_recent(self, *, now: datetime | None = None) -> list[GmailMessage]:
        """Return the senders' messages within the lookback window,
        skipping anything already labeled processed/error."""

        if not self._senders:
            return []

        query = self.build_query(now=now)
        ids = self._list_message_ids(query)
        return [self._get_message(mid) for mid in ids]

    def _list_message_ids(self, query: str) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        while True:
            kwargs: dict = {
                "userId": self._user_id,
                "q": query,
                "includeSpamTrash": False,
            }
            if self._max_results is not None:
                kwargs["maxResults"] = self._max_results
            if page_token:
                kwargs["pageToken"] = page_token

            response = self._client.execute(
                lambda svc, kw=kwargs: svc.users().messages().list(**kw)
            )

            for entry in response.get("messages", []) or []:
                if "id" in entry:
                    ids.append(str(entry["id"]))

            page_token = response.get("nextPageToken")
            if not page_token:
                return ids
            if self._max_results is not None and len(ids) >= self._max_results:
                return ids[: self._max_results]

    def _get_message(self, message_id: str) -> GmailMessage:
        payload = self._client.execute(
            lambda svc, mid=message_id: (
                svc.users()
                .messages()
                .get(
                    userId=self._user_id,
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
            )
        )
        return parse_gmail_message(payload)

    def fetch_message_html(self, message_id: str) -> str:
        """Download full message and return HTML (or HTML-wrapped plain text)."""

        payload = self._client.execute(
            lambda svc, mid=message_id: svc.users()
            .messages()
            .get(userId=self._user_id, id=mid, format="full"),
        )
        return extract_html_from_gmail_payload(payload)
