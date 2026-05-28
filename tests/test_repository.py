from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.models.email import EmailInput
from app.models.outputs import (
    RouterDecision,
    RouteCategory,
    TechnologyOutput,
    TechnologySectionOutput,
)
from app.models.section import EmailSection
from app.storage.repository import AgentOutputRecord, StateRepository


@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "test.db"
    r = StateRepository(db, max_email_retries=3)
    yield r
    r.close()


def test_upsert_and_unprocessed(repo: StateRepository) -> None:
    eid = repo.upsert_email(
        EmailInput(message_id="x-1", subject="S", body_preview="body"),
    )
    assert eid >= 1
    pending = repo.fetch_unprocessed_emails()
    assert len(pending) == 1
    assert pending[0].message_id == "x-1"
    assert pending[0].status == "pending"


def test_upsert_stores_sender(repo: StateRepository) -> None:
    eid = repo.upsert_email(
        EmailInput(
            message_id="with-from",
            subject="S",
            sender="Newsletter <news@example.org>",
        ),
    )
    assert repo.get_email_sender_by_id(eid) == "Newsletter <news@example.org>"
    repo.upsert_email(EmailInput(message_id="with-from", subject="S", sender=None))
    assert repo.get_email_sender_by_id(eid) is None


def test_save_agent_output_roundtrip_json(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="m-out"))
    oid = repo.save_agent_output(
        eid,
        "router_decision",
        RouterDecision(category=RouteCategory.TECHNOLOGY, confidence=0.8),
    )
    assert oid >= 1
    row = repo.connection.execute(
        "SELECT payload FROM agent_outputs WHERE id = ?",
        (oid,),
    ).fetchone()
    assert row is not None
    restored = RouterDecision.model_validate_json(row["payload"])
    assert restored.category == RouteCategory.TECHNOLOGY


def test_digest_attach_and_status(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="d1"))
    did = repo.create_digest(status="draft", title="T")
    repo.attach_email_to_digest(did, eid)
    repo.update_digest_status(did, "sent")
    row = repo.connection.execute(
        "SELECT status FROM digests WHERE id = ?",
        (did,),
    ).fetchone()
    assert row["status"] == "sent"


def test_email_status_and_retryable(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="fail1"))
    repo.update_email_status(eid, "failed", error_message="e", increment_retry=True)
    assert len(repo.fetch_retryable_errors()) == 1
    assert repo.fetch_retryable_errors()[0].retry_count == 1

    repo.update_email_status(eid, "failed", error_message="e2", increment_retry=True)
    assert repo.fetch_retryable_errors()[0].retry_count == 2

    repo.update_email_status(eid, "failed", error_message="e3", increment_retry=True)
    assert len(repo.fetch_retryable_errors()) == 0


def test_upsert_updates_existing(repo: StateRepository) -> None:
    id1 = repo.upsert_email(EmailInput(message_id="same", subject="A"))
    id2 = repo.upsert_email(EmailInput(message_id="same", subject="B"))
    assert id1 == id2
    row = repo.connection.execute(
        "SELECT subject FROM emails WHERE id = ?",
        (id1,),
    ).fetchone()
    assert row["subject"] == "B"


def test_upsert_from_fetch_resets_archived_and_failed_to_pending(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="requeue", subject="S"))
    repo.update_email_status(eid, "archived")
    repo.upsert_email(EmailInput(message_id="requeue", subject="S"))
    row = repo.connection.execute(
        "SELECT status, error_message, retry_count FROM emails WHERE id = ?",
        (eid,),
    ).fetchone()
    assert row["status"] == "pending"
    assert row["error_message"] is None
    assert row["retry_count"] == 0

    repo.update_email_status(
        eid,
        "failed",
        error_message="old",
        increment_retry=True,
    )
    repo.upsert_email(EmailInput(message_id="requeue", subject="S2"))
    row2 = repo.connection.execute(
        "SELECT status, error_message, retry_count FROM emails WHERE id = ?",
        (eid,),
    ).fetchone()
    assert row2["status"] == "pending"
    assert row2["error_message"] is None
    assert row2["retry_count"] == 0


def test_technology_output_saved(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="tech"))
    repo.save_agent_output(
        eid,
        "technology",
        TechnologyOutput(core_pain_point="sum"),
    )


def test_try_reuse_complete_outputs(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="r1"))
    assert repo.try_reuse_complete_outputs(eid) is None

    secs = repo.replace_email_sections(
        eid,
        [
            EmailSection(
                section_id="s0",
                order_index=0,
                text="x" * 400 + " body " * 20,
                links=["https://ex.example/article"],
                image_urls=[],
            ),
        ],
    )
    sid = secs[0].id

    repo.save_agent_output(
        eid,
        "router",
        RouterDecision(category=RouteCategory.TECHNOLOGY, confidence=0.8),
        email_section_id=sid,
    )
    assert repo.try_reuse_complete_outputs(eid) is None

    repo.save_agent_output(
        eid,
        "technology",
        TechnologySectionOutput(
            title="T",
            core_pain_point="x",
            original_url="https://ex.example/article",
            diagrams=[],
        ),
        email_section_id=sid,
        category=RouteCategory.TECHNOLOGY.value,
    )
    assert repo.try_reuse_complete_outputs(eid) == frozenset({RouteCategory.TECHNOLOGY})


def test_get_outputs_by_email_ids_latest_per_kind(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="multi"))
    repo.save_agent_output(
        eid,
        "router",
        RouterDecision(category=RouteCategory.COURSES, confidence=0.5),
    )
    repo.save_agent_output(
        eid,
        "router",
        RouterDecision(category=RouteCategory.TECHNOLOGY, confidence=0.9),
    )
    rows = repo.get_outputs_by_email_ids([eid])
    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r, AgentOutputRecord)
    d = RouterDecision.model_validate_json(r.payload)
    assert d.category == RouteCategory.TECHNOLOGY


def test_update_digest_body(repo: StateRepository) -> None:
    did = repo.create_digest(status="draft", title="T", body_html=None)
    repo.update_digest_body(did, body_html="<p>x</p>")
    row = repo.connection.execute(
        "SELECT body_html FROM digests WHERE id = ?",
        (did,),
    ).fetchone()
    assert row["body_html"] == "<p>x</p>"


def test_fetch_latest_digest_for_utc_calendar_day_latest_row(repo: StateRepository) -> None:
    day = date(2026, 5, 10)
    t1 = datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc).isoformat()
    t2 = datetime(2026, 5, 10, 20, 0, 0, tzinfo=timezone.utc).isoformat()
    conn = repo.connection
    conn.execute(
        """
        INSERT INTO digests (status, title, body_html, created_at, updated_at)
        VALUES ('draft', NULL, ?, ?, ?)
        """,
        ("<p>early</p>", t1, t1),
    )
    conn.execute(
        """
        INSERT INTO digests (status, title, body_html, created_at, updated_at)
        VALUES ('draft', NULL, ?, ?, ?)
        """,
        ("<p>late</p>", t2, t2),
    )
    conn.commit()

    got = repo.fetch_latest_digest_for_utc_calendar_day(day)
    assert got is not None
    assert got.body_html == "<p>late</p>"


def test_fetch_latest_digest_for_utc_calendar_day_other_day_excluded(repo: StateRepository) -> None:
    d_may10 = date(2026, 5, 10)
    t_may11 = datetime(2026, 5, 11, 8, 0, 0, tzinfo=timezone.utc).isoformat()
    conn = repo.connection
    conn.execute(
        """
        INSERT INTO digests (status, title, body_html, created_at, updated_at)
        VALUES ('draft', NULL, '<p>x</p>', ?, ?)
        """,
        (t_may11, t_may11),
    )
    conn.commit()
    assert repo.fetch_latest_digest_for_utc_calendar_day(d_may10) is None
