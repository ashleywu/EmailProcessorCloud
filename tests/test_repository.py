from __future__ import annotations

import pytest

from app.models.email import EmailInput
from app.models.outputs import RouterDecision, RouteCategory, TechnologyOutput
from app.storage.repository import StateRepository


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


def test_technology_output_saved(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="tech"))
    repo.save_agent_output(
        eid,
        "technology",
        TechnologyOutput(core_pain_point="sum"),
    )
