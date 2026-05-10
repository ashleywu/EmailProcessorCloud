"""In-memory fake of the subset of the Gmail API surface we use.

Mirrors the chained call style ``service.users().messages().list(...).execute()``
without importing googleapiclient. Records calls for assertions and
supports injecting failures (e.g. simulated 401s).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


class FakeResponse:
    """Mimic ``googleapiclient.errors.HttpError.resp`` enough for status checks."""

    def __init__(self, status: int) -> None:
        self.status = status


class FakeHttpError(Exception):
    """Raised by the fake service to simulate transport failures (e.g. 401)."""

    def __init__(self, status: int, message: str = "fake http error") -> None:
        super().__init__(f"{status}: {message}")
        self.resp = FakeResponse(status)


def make_message(
    *,
    msg_id: str,
    sender: str = "newsletter@example.com",
    subject: str = "Hello",
    snippet: str = "snippet",
    date: str | None = None,
    label_ids: Iterable[str] | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    headers = [
        {"name": "From", "value": sender},
        {"name": "Subject", "value": subject},
    ]
    if date is not None:
        headers.append({"name": "Date", "value": date})
    return {
        "id": msg_id,
        "threadId": thread_id or f"t-{msg_id}",
        "snippet": snippet,
        "labelIds": list(label_ids or []),
        "payload": {"headers": headers},
    }


class _Request:
    """Lazy request that runs ``func`` only when ``execute()`` is called."""

    def __init__(self, func: Callable[[], Any], *, fail_with: Exception | None = None):
        self._func = func
        self._fail_with = fail_with

    def execute(self) -> Any:
        if self._fail_with is not None:
            raise self._fail_with
        return self._func()


@dataclass
class _Call:
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class _Messages:
    def __init__(self, parent: "_Users", svc: "FakeGmailService") -> None:
        self._parent = parent
        self._svc = svc

    def list(self, **kwargs: Any) -> _Request:
        self._svc.calls.append(_Call("messages.list", dict(kwargs)))
        fail = self._svc._consume_failure("messages.list")
        return _Request(lambda: self._svc._messages_list_response(kwargs), fail_with=fail)

    def get(self, **kwargs: Any) -> _Request:
        self._svc.calls.append(_Call("messages.get", dict(kwargs)))
        fail = self._svc._consume_failure("messages.get")
        return _Request(lambda: self._svc._messages_get_response(kwargs), fail_with=fail)

    def modify(self, **kwargs: Any) -> _Request:
        self._svc.calls.append(_Call("messages.modify", dict(kwargs)))
        fail = self._svc._consume_failure("messages.modify")

        def _do() -> dict[str, Any]:
            mid = kwargs["id"]
            body = kwargs.get("body", {})
            current = self._svc.message_labels.setdefault(mid, set())
            for lid in body.get("removeLabelIds", []) or []:
                current.discard(lid)
            for lid in body.get("addLabelIds", []) or []:
                current.add(lid)
            return {"id": mid, "labelIds": sorted(current)}

        return _Request(_do, fail_with=fail)

    def send(self, **kwargs: Any) -> _Request:
        self._svc.calls.append(_Call("messages.send", dict(kwargs)))
        fail = self._svc._consume_failure("messages.send")

        def _do() -> dict[str, Any]:
            self._svc.sent.append(kwargs)
            sent_id = self._svc._next_sent_id()
            return {"id": sent_id, "threadId": f"thr-{sent_id}"}

        return _Request(_do, fail_with=fail)


class _Labels:
    def __init__(self, parent: "_Users", svc: "FakeGmailService") -> None:
        self._parent = parent
        self._svc = svc

    def list(self, **kwargs: Any) -> _Request:
        self._svc.calls.append(_Call("labels.list", dict(kwargs)))
        fail = self._svc._consume_failure("labels.list")
        return _Request(
            lambda: {"labels": [{"id": lid, "name": n} for n, lid in self._svc.labels.items()]},
            fail_with=fail,
        )

    def create(self, **kwargs: Any) -> _Request:
        self._svc.calls.append(_Call("labels.create", dict(kwargs)))
        fail = self._svc._consume_failure("labels.create")

        def _do() -> dict[str, Any]:
            name = kwargs["body"]["name"]
            if name in self._svc.labels:
                return {"id": self._svc.labels[name], "name": name}
            new_id = self._svc._next_label_id()
            self._svc.labels[name] = new_id
            return {"id": new_id, "name": name}

        return _Request(_do, fail_with=fail)


class _Users:
    def __init__(self, svc: "FakeGmailService") -> None:
        self._svc = svc

    def messages(self) -> _Messages:
        return _Messages(self, self._svc)

    def labels(self) -> _Labels:
        return _Labels(self, self._svc)


class FakeGmailService:
    """In-memory Gmail service.

    Pre-populate ``messages`` (id -> message payload) for ``messages.get``
    and ``list_results`` (list of pages, each a dict with ``messages`` and
    optional ``nextPageToken``) for ``messages.list``.
    """

    def __init__(
        self,
        *,
        messages: dict[str, dict[str, Any]] | None = None,
        list_results: list[dict[str, Any]] | None = None,
        labels: dict[str, str] | None = None,
    ) -> None:
        self.messages: dict[str, dict[str, Any]] = dict(messages or {})
        self.list_results: list[dict[str, Any]] = list(list_results or [])
        self.labels: dict[str, str] = dict(labels or {})
        self.message_labels: dict[str, set[str]] = {
            mid: set(payload.get("labelIds") or [])
            for mid, payload in self.messages.items()
        }
        self.calls: list[_Call] = []
        self.sent: list[dict[str, Any]] = []
        self._failures: dict[str, list[Exception]] = {}
        self._label_seq = 0
        self._sent_seq = 0
        self._list_index = 0

    def queue_failure(self, method: str, exc: Exception) -> None:
        """Inject a failure for the next call to ``method`` (e.g. ``"messages.list"``)."""
        self._failures.setdefault(method, []).append(exc)

    def _consume_failure(self, method: str) -> Exception | None:
        bucket = self._failures.get(method)
        if not bucket:
            return None
        return bucket.pop(0)

    def users(self) -> _Users:
        return _Users(self)

    def call_kwargs(self, method: str) -> list[dict[str, Any]]:
        return [c.kwargs for c in self.calls if c.method == method]

    def _next_label_id(self) -> str:
        self._label_seq += 1
        return f"Label_{self._label_seq}"

    def _next_sent_id(self) -> str:
        self._sent_seq += 1
        return f"sent-{self._sent_seq}"

    def _messages_list_response(self, _kwargs: dict[str, Any]) -> dict[str, Any]:
        if not self.list_results:
            return {"messages": []}
        if self._list_index >= len(self.list_results):
            return {"messages": []}
        page = self.list_results[self._list_index]
        self._list_index += 1
        return page

    def _messages_get_response(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        mid = kwargs["id"]
        if mid not in self.messages:
            raise KeyError(f"FakeGmailService: unknown message id {mid!r}")
        payload = dict(self.messages[mid])
        payload["labelIds"] = sorted(self.message_labels.get(mid, set(payload.get("labelIds") or [])))
        return payload
