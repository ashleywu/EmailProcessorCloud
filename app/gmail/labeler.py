from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.models.outputs import RouteCategory

PROCESSED_LABEL = "AI_DIGEST_PROCESSED"
ERROR_LABEL = "AI_DIGEST_ERROR"
INBOX_LABEL = "INBOX"

CATEGORY_LABEL_PREFIX = "AI_DIGEST/"


def category_label_name(category: RouteCategory | str) -> str:
    """Return the Gmail label name used for a router category."""

    value = category.value if isinstance(category, RouteCategory) else str(category)
    return f"{CATEGORY_LABEL_PREFIX}{value}"


class GmailLabeler:
    """Manage Gmail labels for the digest pipeline.

    The labeler is intentionally orthogonal to fetching/sending and never
    archives a message implicitly: ``mark_processed`` and ``mark_error``
    only set labels. Callers must call ``archive`` explicitly when they
    want the message removed from the inbox. This makes the labeler safe
    to use in dry-run or test contexts.
    """

    def __init__(
        self,
        client,
        *,
        user_id: str = "me",
    ) -> None:
        self._client = client
        self._user_id = user_id
        self._label_id_cache: dict[str, str] = {}

    def list_labels(self) -> list[dict]:
        response = self._client.execute(
            lambda svc: svc.users().labels().list(userId=self._user_id)
        )
        return list(response.get("labels", []) or [])

    def ensure_labels(self, names: Sequence[str]) -> dict[str, str]:
        """Ensure every label in ``names`` exists, creating missing ones.

        Returns a mapping of ``label_name -> label_id`` for the requested
        labels. Existing label ids are cached to avoid repeated lookups.
        """

        wanted = list(dict.fromkeys(names))
        if not wanted:
            return {}

        missing = [n for n in wanted if n not in self._label_id_cache]
        if missing:
            existing = {lbl["name"]: lbl["id"] for lbl in self.list_labels() if "id" in lbl}
            for name in wanted:
                if name in existing:
                    self._label_id_cache[name] = existing[name]

            for name in wanted:
                if name in self._label_id_cache:
                    continue
                created = self._client.execute(
                    lambda svc, n=name: svc.users()
                    .labels()
                    .create(
                        userId=self._user_id,
                        body={
                            "name": n,
                            "labelListVisibility": "labelShow",
                            "messageListVisibility": "show",
                        },
                    )
                )
                self._label_id_cache[name] = str(created["id"])

        return {name: self._label_id_cache[name] for name in wanted}

    def add_labels(
        self,
        message_id: str,
        names: Iterable[str],
        *,
        remove: Iterable[str] = (),
    ) -> None:
        add_names = [n for n in dict.fromkeys(names)]
        remove_names = [n for n in dict.fromkeys(remove)]

        ids = self.ensure_labels(add_names)
        body: dict[str, list[str]] = {}
        if add_names:
            body["addLabelIds"] = [ids[n] for n in add_names]
        if remove_names:
            body["removeLabelIds"] = list(remove_names)

        if not body:
            return

        self._client.execute(
            lambda svc: svc.users()
            .messages()
            .modify(userId=self._user_id, id=message_id, body=body)
        )

    def add_category(self, message_id: str, category: RouteCategory | str) -> None:
        self.add_labels(message_id, [category_label_name(category)])

    def mark_processed(self, message_id: str) -> None:
        """Mark a message processed without touching INBOX (no archive)."""
        self.add_labels(message_id, [PROCESSED_LABEL])

    def mark_error(self, message_id: str) -> None:
        """Mark a message as errored without touching INBOX (no archive)."""
        self.add_labels(message_id, [ERROR_LABEL])

    def archive(self, message_id: str) -> None:
        """Remove the INBOX label so the message disappears from the inbox."""
        self._client.execute(
            lambda svc: svc.users()
            .messages()
            .modify(
                userId=self._user_id,
                id=message_id,
                body={"removeLabelIds": [INBOX_LABEL]},
            )
        )
