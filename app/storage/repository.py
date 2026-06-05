from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.models.digest import ProcessedEmail
from app.models.email import EmailInput
from app.models.outputs import (
    MAP_REDUCE_RADAR_DIGEST_KIND,
    PROCESSOR_OUTPUT_KIND,
    RouterDecision,
    RouteCategory,
)
from app.models.section import EmailSection
from app.parsing.section_caps import compute_section_content_hash
from app.storage.db import init_schema, open_initialized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class AgentOutputRecord:
    """Latest row per (email_id, email_section_id, kind)—see ``get_latest_outputs_by_email_ids``."""

    id: int
    email_id: int
    kind: str
    payload: str
    created_at: str
    email_section_id: int | None = None
    section_key: str | None = None
    category: str | None = None
    section_order_index: int | None = None
    section_heading: str | None = None


@dataclass(frozen=True, slots=True)
class EmailSectionRecord:
    """Persisted ``email_sections`` row returned from ``replace_email_sections`` / ``list_email_sections``."""

    id: int
    email_id: int
    section_key: str
    order_index: int
    heading: str | None
    text: str
    links_json: str
    image_urls_json: str
    content_hash: str
    created_at: str


@dataclass(frozen=True, slots=True)
class DigestPreviewRecord:
    """One digest row selected for HTML preview (UTC calendar-day semantics)."""

    digest_id: int
    status: str
    body_html: str | None


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
        """Insert or update a row from Gmail fetch.

        On conflict, reset ``status`` to ``pending`` and clear error fields so a
        message can be re-queued when it shows up in ``fetch_recent`` again
        (e.g. user removed ``AI_DIGEST_PROCESSED`` and returned the mail to the inbox).
        """

        now = _utc_now_iso()
        received = email.received_at.isoformat() if email.received_at else None
        self._conn.execute(
            """
            INSERT INTO emails (message_id, subject, sender, body_preview, status, received_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
              subject = excluded.subject,
              sender = excluded.sender,
              body_preview = excluded.body_preview,
              received_at = COALESCE(excluded.received_at, emails.received_at),
              status = 'pending',
              error_message = NULL,
              retry_count = 0,
              updated_at = excluded.updated_at
            """,
            (email.message_id, email.subject, email.sender, email.body_preview, received, now, now),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM emails WHERE message_id = ?",
            (email.message_id,),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def save_agent_output(
        self,
        email_id: int,
        kind: str,
        output: BaseModel,
        *,
        email_section_id: int | None = None,
        category: str | None = None,
    ) -> int:
        """Persist one agent JSON row.

        ``email_section_id`` NULL keeps legacy whole-email granularity. When ``kind`` is ``router``,
        ``category`` (if passed) must match ``RouterDecision.category`` in ``output``.
        """

        payload = output.model_dump_json()
        canonical_category = category

        if kind == "router":
            decision = RouterDecision.model_validate(output)
            expected = decision.category.value
            if canonical_category is not None and canonical_category != expected:
                msg = f"category {canonical_category!r} mismatches RouterDecision.category {expected!r}"
                raise ValueError(msg)
            canonical_category = expected
        elif canonical_category is not None:
            # Denormalized field for processors: allowed but payload has no canonical category anchor.
            pass

        if email_section_id is not None:
            row = self._conn.execute(
                "SELECT id FROM email_sections WHERE id = ? AND email_id = ?",
                (email_section_id, email_id),
            ).fetchone()
            if row is None:
                raise ValueError(
                    "email_section_id does not belong to this email_id (or missing row)",
                )

        now = _utc_now_iso()
        cur = self._conn.execute(
            """
            INSERT INTO agent_outputs (
              email_id, email_section_id, kind, category, payload, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (email_id, email_section_id, kind, canonical_category, payload, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def replace_email_sections(
        self,
        email_id: int,
        sections: Sequence[EmailSection],
    ) -> list[EmailSectionRecord]:
        """Swap slices while preserving IDs when `(section_key, content_hash)` is unchanged."""

        cur = self._conn.cursor()
        now = _utc_now_iso()
        inserted: list[EmailSectionRecord] = []
        tracked_ids: list[int] = []
        try:
            pairs = [(s, compute_section_content_hash(s)) for s in sections]

            for sec, chash in pairs:
                links_payload = json.dumps(sec.links)
                imgs_payload = json.dumps(sec.image_urls)
                heading = sec.heading
                section_key = sec.section_id.strip()

                match = cur.execute(
                    """
                    SELECT id FROM email_sections
                    WHERE email_id = ? AND section_key = ? AND content_hash = ?
                    """,
                    (email_id, section_key, chash),
                ).fetchone()

                if match:
                    pk = int(match["id"])
                    cur.execute(
                        """
                        UPDATE email_sections
                           SET order_index = ?,
                               heading = ?,
                               text = ?,
                               links_json = ?,
                               image_urls_json = ?,
                               content_hash = ?
                         WHERE id = ? AND email_id = ?
                        """,
                        (
                            sec.order_index,
                            heading,
                            sec.text or "",
                            links_payload,
                            imgs_payload,
                            chash,
                            pk,
                            email_id,
                        ),
                    )
                    tracked_ids.append(pk)
                else:
                    cur.execute(
                        "DELETE FROM email_sections WHERE email_id = ? AND section_key = ?",
                        (email_id, section_key),
                    )
                    cur.execute(
                        """
                        INSERT INTO email_sections (
                          email_id, section_key, order_index, heading, text,
                          links_json, image_urls_json, content_hash, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            email_id,
                            section_key,
                            sec.order_index,
                            heading,
                            sec.text or "",
                            links_payload,
                            imgs_payload,
                            chash,
                            now,
                        ),
                    )
                    tracked_ids.append(int(cur.lastrowid))

            placeholders = ",".join("?" for _ in tracked_ids)
            cur.execute(
                f"""
                DELETE FROM email_sections
                 WHERE email_id = ?
                   AND id NOT IN ({placeholders})
                """,
                (email_id, *tracked_ids),
            )

            rows = cur.execute(
                f"""
                SELECT id, email_id, section_key, order_index, heading, text,
                       links_json, image_urls_json, content_hash, created_at
                  FROM email_sections
                 WHERE email_id = ?
                   AND id IN ({placeholders})
                 ORDER BY order_index, id
                """,
                (email_id, *tracked_ids),
            ).fetchall()
            inserted = [_row_to_section_record(r) for r in rows]

            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return inserted

    def list_email_sections(self, email_id: int) -> list[EmailSectionRecord]:
        rows = self._conn.execute(
            """
            SELECT id, email_id, section_key, order_index, heading, text,
                   links_json, image_urls_json, content_hash, created_at
            FROM email_sections
            WHERE email_id = ?
            ORDER BY order_index, id
            """,
            (email_id,),
        ).fetchall()
        return [_row_to_section_record(r) for r in rows]

    def get_latest_agent_output_for_section_kind(
        self,
        email_id: int,
        *,
        section_id: int,
        kind: str,
    ) -> AgentOutputRecord | None:
        """Return newest ``agent_outputs`` slice for `(email_id, section_id, kind)`."""

        row = self._conn.execute(
            """
            SELECT ao.id, ao.email_id, ao.email_section_id, ao.kind, ao.category, ao.payload,
                   ao.created_at, es.section_key, es.order_index AS section_order_index,
                   es.heading AS section_heading
            FROM agent_outputs ao
            LEFT JOIN email_sections es ON es.id = ao.email_section_id
            WHERE ao.email_id = ?
              AND ao.email_section_id = ?
              AND ao.kind = ?
            ORDER BY ao.id DESC
            LIMIT 1
            """,
            (email_id, section_id, kind),
        ).fetchone()
        return _row_to_agent_output(row) if row is not None else None

    def clear_section_scoped_agent_outputs(self, email_id: int) -> None:
        """Remove per-section router/processor rows (map-reduce reprocess)."""

        self._conn.execute(
            "DELETE FROM agent_outputs WHERE email_id = ? AND email_section_id IS NOT NULL",
            (email_id,),
        )
        self._conn.commit()

    def map_reduce_radar_digest_cached(self, email_id: int) -> bool:
        row = self._conn.execute(
            """
            SELECT id FROM agent_outputs
            WHERE email_id = ? AND kind = ? AND email_section_id IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (email_id, MAP_REDUCE_RADAR_DIGEST_KIND),
        ).fetchone()
        return row is not None

    def section_pipeline_outputs_cached(self, email_id: int) -> bool:
        """``True`` when every stored section row has a fresh router decision + processor JSON."""

        secs = self.list_email_sections(email_id)
        if not secs:
            return False
        for srec in secs:
            r_row = self.get_latest_agent_output_for_section_kind(email_id, section_id=srec.id, kind="router")
            if r_row is None:
                return False
            try:
                decision = RouterDecision.model_validate_json(r_row.payload)
            except Exception:
                return False
            proc_kind = PROCESSOR_OUTPUT_KIND[decision.category]
            proc_row = self.get_latest_agent_output_for_section_kind(email_id, section_id=srec.id, kind=proc_kind)
            if proc_row is None and decision.category == RouteCategory.COURSES:
                proc_row = self.get_latest_agent_output_for_section_kind(
                    email_id,
                    section_id=srec.id,
                    kind="noise",
                )
            if proc_row is None:
                return False
        return True

    def router_categories_cached_for_sections(self, email_id: int) -> frozenset[RouteCategory] | None:
        """Return merged router categories stored per section.

        ``None`` when any section misses router output — caller should rerun the pipeline instead of reusing.
        """

        secs = self.list_email_sections(email_id)
        if not secs:
            return None
        cats: set[RouteCategory] = set()
        for srec in secs:
            r_row = self.get_latest_agent_output_for_section_kind(email_id, section_id=srec.id, kind="router")
            if r_row is None:
                return None
            try:
                decision = RouterDecision.model_validate_json(r_row.payload)
            except Exception:
                return None
            cats.add(decision.category)
        return frozenset(cats)

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

    def get_latest_outputs_by_email_ids(self, email_ids: Sequence[int]) -> list[AgentOutputRecord]:
        """Latest row per (email_id, email_section_id, kind) by greatest ``id``."""

        ids = list(dict.fromkeys(int(i) for i in email_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        sql = f"""
            SELECT ao.id, ao.email_id, ao.email_section_id, ao.kind, ao.category, ao.payload, ao.created_at,
                   es.section_key, es.order_index AS section_order_index,
                   es.heading AS section_heading
            FROM agent_outputs ao
            LEFT JOIN email_sections es ON es.id = ao.email_section_id
            INNER JOIN (
              SELECT email_id, email_section_id, kind, MAX(id) AS max_id
              FROM agent_outputs
              WHERE email_id IN ({placeholders})
              GROUP BY email_id, email_section_id, kind
            ) t
              ON ao.email_id = t.email_id
             AND ao.kind = t.kind
             AND ao.id = t.max_id
             AND (
                   (ao.email_section_id IS NULL AND t.email_section_id IS NULL)
                OR (ao.email_section_id = t.email_section_id)
             )
            ORDER BY ao.email_id,
                     (es.order_index IS NULL) ASC,
                     COALESCE(es.order_index, 2147483647),
                     ao.kind
        """
        rows = self._conn.execute(sql, ids).fetchall()
        return [_row_to_agent_output(r) for r in rows]

    def list_outputs_for_digest(self, email_ids: Sequence[int]) -> list[AgentOutputRecord]:
        """Alias of ``get_latest_outputs_by_email_ids`` with readable name for callers."""

        return self.get_latest_outputs_by_email_ids(email_ids)

    def get_outputs_by_email_ids(self, email_ids: Sequence[int]) -> list[AgentOutputRecord]:
        """Backward-compatible name for digest composition / tests."""

        return self.get_latest_outputs_by_email_ids(email_ids)

    def try_reuse_complete_outputs(self, email_id: int) -> frozenset[RouteCategory] | None:
        """Reuse persisted outputs when complete for the active pipeline shape."""

        if self.map_reduce_radar_digest_cached(email_id):
            return frozenset({RouteCategory.RADAR})
        if not self.section_pipeline_outputs_cached(email_id):
            return None
        return self.router_categories_cached_for_sections(email_id)

    def get_email_subject_by_id(self, email_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT subject FROM emails WHERE id = ?",
            (email_id,),
        ).fetchone()
        if row is None:
            return None
        return row["subject"]

    def get_email_sender_by_id(self, email_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT sender FROM emails WHERE id = ?",
            (email_id,),
        ).fetchone()
        if row is None:
            return None
        v = row["sender"]
        if v is None:
            return None
        s = str(v).strip()
        return s or None

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

    def fetch_latest_digest_for_utc_calendar_day(self, day: date) -> DigestPreviewRecord | None:
        """Return the digest with the latest ``created_at`` whose instant falls on ``day`` in UTC.

        Rows are matched by half-open interval ``[day 00:00 UTC, next day 00:00 UTC)`` using
        ISO8601 ``created_at`` strings stored in SQLite.
        """

        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        row = self._conn.execute(
            """
            SELECT id, status, body_html FROM digests
            WHERE created_at >= ? AND created_at < ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        if row is None:
            return None
        return DigestPreviewRecord(
            digest_id=int(row["id"]),
            status=str(row["status"]),
            body_html=row["body_html"],
        )


def _row_to_agent_output(r: sqlite3.Row) -> AgentOutputRecord:
    soi = r["section_order_index"]
    sec_key = r["section_key"]
    sh_raw = None
    if "section_heading" in r.keys():
        sh_raw = r["section_heading"]
    return AgentOutputRecord(
        id=int(r["id"]),
        email_id=int(r["email_id"]),
        kind=str(r["kind"]),
        payload=str(r["payload"]),
        created_at=str(r["created_at"]),
        email_section_id=(int(r["email_section_id"]) if r["email_section_id"] is not None else None),
        section_key=str(sec_key) if sec_key is not None else None,
        category=str(r["category"]) if r["category"] is not None else None,
        section_order_index=int(soi) if soi is not None else None,
        section_heading=str(sh_raw) if sh_raw is not None else None,
    )


def _row_to_section_record(r: sqlite3.Row) -> EmailSectionRecord:
    ch_raw = ""
    if "content_hash" in r.keys() and r["content_hash"] is not None:
        ch_raw = str(r["content_hash"])
    return EmailSectionRecord(
        id=int(r["id"]),
        email_id=int(r["email_id"]),
        section_key=str(r["section_key"]),
        order_index=int(r["order_index"]),
        heading=r["heading"],
        text=str(r["text"]),
        links_json=str(r["links_json"]),
        image_urls_json=str(r["image_urls_json"]),
        content_hash=ch_raw,
        created_at=str(r["created_at"]),
    )
