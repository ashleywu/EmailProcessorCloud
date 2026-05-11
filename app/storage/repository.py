from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.models.digest import ProcessedEmail
from app.models.email import EmailInput
from app.models.outputs import PROCESSOR_OUTPUT_KIND, RouterDecision, RouteCategory
from app.storage.db import init_schema, open_initialized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class AgentOutputRecord:
    """Latest agent output row for one (email_id, kind), see ``get_outputs_by_email_ids``."""

    id: int
    email_id: int
    kind: str
    payload: str
    created_at: str


class StateRepository:
    """SQLite-backed application state for emails, agent outputs, and digests."""

    def __init__(self, db_path: Path, *, max_email_retries: int = 3) -> None:
        self._conn = open_initialized(db_path)
        self._max_retries = max_email_retries

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def init_database(self) -> None:
        """Idempotent: schema is applied in `open_initialized`; exposed for explicit API."""
        init_schema(self._conn)

    def upsert_email(self, email: EmailInput) -> int:
        now = _utc_now_iso()
        received = email.received_at.isoformat() if email.received_at else None
        self._conn.execute(
            """
            INSERT INTO emails (message_id, subject, body_preview, status, received_at, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
              subject = excluded.subject,
              body_preview = excluded.body_preview,
              received_at = COALESCE(excluded.received_at, emails.received_at),
              updated_at = excluded.updated_at
            """,
            (email.message_id, email.subject, email.body_preview, received, now, now),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM emails WHERE message_id = ?",
            (email.message_id,),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def save_agent_output(self, email_id: int, kind: str, output: BaseModel) -> int:
        payload = output.model_dump_json()
        now = _utc_now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO agent_outputs (email_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (email_id, kind, payload, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def create_digest(
        self,
        *,
        status: str = "draft",
        title: str | None = None,
        body_html: str | None = None,
    ) -> int:
        now = _utc_now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO digests (status, title, body_html, error_message, created_at, updated_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (status, title, body_html, now, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def attach_email_to_digest(self, digest_id: int, email_id: int) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO digest_emails (digest_id, email_id)
            VALUES (?, ?)
            """,
            (digest_id, email_id),
        )
        self._conn.commit()

    def update_email_status(
        self,
        email_id: int,
        status: str,
        *,
        error_message: str | None = None,
        increment_retry: bool = False,
    ) -> None:
        now = _utc_now_iso()
        if increment_retry:
            self._conn.execute(
                """
                UPDATE emails
                SET status = ?, error_message = ?, retry_count = retry_count + 1, updated_at = ?
                WHERE id = ?
                """,
                (status, error_message, now, email_id),
            )
        else:
            self._conn.execute(
                """
                UPDATE emails
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error_message, now, email_id),
            )
        self._conn.commit()

    def update_digest_status(
        self,
        digest_id: int,
        status: str,
        *,
        error_message: str | None = None,
    ) -> None:
        now = _utc_now_iso()
        if error_message is not None:
            self._conn.execute(
                """
                UPDATE digests SET status = ?, updated_at = ?, error_message = ?
                WHERE id = ?
                """,
                (status, now, error_message, digest_id),
            )
        else:
            self._conn.execute(
                """
                UPDATE digests SET status = ?, updated_at = ? WHERE id = ?
                """,
                (status, now, digest_id),
            )
        self._conn.commit()

    def update_digest_body(
        self,
        digest_id: int,
        *,
        body_html: str | None,
        title: str | None = None,
    ) -> None:
        now = _utc_now_iso()
        if title is not None:
            self._conn.execute(
                """
                UPDATE digests SET body_html = ?, title = ?, updated_at = ? WHERE id = ?
                """,
                (body_html, title, now, digest_id),
            )
        else:
            self._conn.execute(
                """
                UPDATE digests SET body_html = ?, updated_at = ? WHERE id = ?
                """,
                (body_html, now, digest_id),
            )
        self._conn.commit()

    def get_outputs_by_email_ids(self, email_ids: Sequence[int]) -> list[AgentOutputRecord]:
        """Return the latest row per (email_id, kind) by highest ``id``.

        When multiple outputs share the same (email_id, kind), only the row
        with the greatest ``id`` is returned (proxy for latest ``created_at``).
        """
        ids = list(dict.fromkeys(int(i) for i in email_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        sql = f"""
            SELECT ao.id, ao.email_id, ao.kind, ao.payload, ao.created_at
            FROM agent_outputs ao
            INNER JOIN (
              SELECT email_id, kind, MAX(id) AS max_id
              FROM agent_outputs
              WHERE email_id IN ({placeholders})
              GROUP BY email_id, kind
            ) t
              ON ao.email_id = t.email_id
             AND ao.kind = t.kind
             AND ao.id = t.max_id
            ORDER BY ao.email_id, ao.kind
        """
        rows = self._conn.execute(sql, ids).fetchall()
        return [
            AgentOutputRecord(
                id=int(r["id"]),
                email_id=int(r["email_id"]),
                kind=str(r["kind"]),
                payload=str(r["payload"]),
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]

    def try_reuse_complete_outputs(self, email_id: int) -> RouteCategory | None:
        """Return router category when latest ``router`` + matching processor rows exist.

        Enables a later ``run_daily`` after quality-gate or send failure to compose a new
        digest from persisted structured outputs only (no Gmail full fetch, no LLM).
        """

        rows = self.get_outputs_by_email_ids([email_id])
        by_kind = {r.kind: r.payload for r in rows}
        if "router" not in by_kind:
            return None
        try:
            decision = RouterDecision.model_validate_json(by_kind["router"])
        except Exception:
            return None
        proc_kind = PROCESSOR_OUTPUT_KIND[decision.category]
        if proc_kind not in by_kind:
            return None
        return decision.category

    def get_email_subject_by_id(self, email_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT subject FROM emails WHERE id = ?",
            (email_id,),
        ).fetchone()
        if row is None:
            return None
        return row["subject"]

    def fetch_unprocessed_emails(self) -> list[ProcessedEmail]:
        rows = self._conn.execute(
            """
            SELECT e.id, e.message_id, e.status, e.retry_count, e.error_message, e.updated_at,
                   (SELECT de.digest_id FROM digest_emails de WHERE de.email_id = e.id LIMIT 1) AS digest_id
            FROM emails e
            WHERE e.status = 'pending'
            ORDER BY e.id
            """
        ).fetchall()
        return [self._row_to_processed(r) for r in rows]

    def fetch_retryable_errors(self) -> list[ProcessedEmail]:
        rows = self._conn.execute(
            """
            SELECT e.id, e.message_id, e.status, e.retry_count, e.error_message, e.updated_at,
                   (SELECT de.digest_id FROM digest_emails de WHERE de.email_id = e.id LIMIT 1) AS digest_id
            FROM emails e
            WHERE e.status = 'failed' AND e.retry_count < ?
            ORDER BY e.id
            """,
            (self._max_retries,),
        ).fetchall()
        return [self._row_to_processed(r) for r in rows]

    def _row_to_processed(self, row: sqlite3.Row) -> ProcessedEmail:
        data: dict[str, Any] = {k: row[k] for k in row.keys()}
        return ProcessedEmail(
            id=int(data["id"]),
            message_id=str(data["message_id"]),
            status=str(data["status"]),
            digest_id=int(data["digest_id"]) if data.get("digest_id") is not None else None,
            retry_count=int(data.get("retry_count") or 0),
            error_message=data.get("error_message"),
            updated_at=_parse_dt(data.get("updated_at")),
        )
