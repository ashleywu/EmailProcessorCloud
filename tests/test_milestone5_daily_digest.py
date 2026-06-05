from __future__ import annotations

import base64
import sqlite3

import pytest

from app.agents.daily_digest_agent import (
    DIGEST_STATUS_EMPTY,
    DIGEST_STATUS_ERROR,
    DIGEST_STATUS_SEND_FAILED,
    DIGEST_STATUS_SENT,
    DailyDigestAgent,
)
from app.agents.leadership_agent import LeadershipProcessorAgent
from app.agents.courses_agent import CoursesProcessorAgent
from app.agents.radar_agent import RadarProcessorAgent
from app.agents.router_agent import RouterAgent
from app.agents.technology_agent import TechnologyProcessorAgent
from app.digest.quality_gate import DigestQualityGateAgent, QualityGateResult
from app.gmail.labeler import INBOX_LABEL
from app.models.email import EmailInput
from app.storage.repository import StateRepository
from app.storage.run_lock import RunLock
from tests.agent_factory import build_daily_digest_agent
from tests.fakes import FakeGmailService, FakeHttpError, make_message
from tests.fakes.llm import ScriptedLLMClient


def _b64url(data: str) -> str:
    return base64.urlsafe_b64encode(data.encode("utf-8")).decode("ascii").rstrip("=")


def _message_full_html(msg_id: str, html: str) -> dict:
    m = make_message(msg_id=msg_id, label_ids=["INBOX"])
    headers = m["payload"]["headers"]
    m["payload"] = {
        "mimeType": "text/html",
        "headers": headers,
        "body": {"data": _b64url(html)},
    }
    return m


def _agent(
    repo: StateRepository,
    lock: RunLock,
    svc: FakeGmailService,
    llm: ScriptedLLMClient,
    *,
    gate=None,
    queue_send_fail: bool = False,
) -> DailyDigestAgent:
    if queue_send_fail:
        svc.queue_failure("messages.send", FakeHttpError(400, "send boom"))
    return build_daily_digest_agent(
        repo,
        lock,
        svc,
        llm,
        gate=gate,
        map_reduce_senders=(),
    )


def test_digest_sent_archives_and_links_emails(tmp_path) -> None:
    html_body = (
        '<html><body><p>News digest body text here padded for section minimums.</p>'
        '<a href="https://example.com/post">Read</a></body></html>'
    )
    svc = FakeGmailService(messages={"gm1": _message_full_html("gm1", html_body)})
    db = tmp_path / "db1.sqlite"
    repo = StateRepository(db)
    repo.upsert_email(EmailInput(message_id="gm1", subject="S1"))
    llm = ScriptedLLMClient(
        [
            '{"category": "TECHNOLOGY", "confidence": 0.9, "rationale": null}',
            '{"title": "T", '
            '"core_pain_point": "Pain summary text here with enough detail for the digest.", '
            '"original_url": "https://example.com/post", "diagrams": []}',
        ],
    )
    _agent(repo, RunLock(db), svc, llm).run_daily()

    row = repo.connection.execute("SELECT status FROM digests").fetchone()
    assert row["status"] == DIGEST_STATUS_SENT

    em = repo.connection.execute(
        "SELECT status FROM emails WHERE message_id = ?",
        ("gm1",),
    ).fetchone()
    assert em["status"] == "archived"

    linked = repo.connection.execute("SELECT COUNT(*) FROM digest_emails").fetchone()[0]
    assert linked == 1

    send_i = next(i for i, c in enumerate(svc.calls) if c.method == "messages.send")
    modify_indices = [i for i, c in enumerate(svc.calls) if c.method == "messages.modify"]
    assert modify_indices
    assert all(i > send_i for i in modify_indices)


def test_single_email_failure_does_not_block_others(tmp_path) -> None:
    svc = FakeGmailService(
        messages={
            "ok": _message_full_html(
                "ok",
                '<html><body><p>'
                + ("Ok newsletter body padded for minimum section length tokens. " * 25)
                + '</p>'
                '<a href="https://example.com/p">More</a></body></html>',
            ),
        },
    )
    db = tmp_path / "db2.sqlite"
    repo = StateRepository(db)
    repo.upsert_email(EmailInput(message_id="ok", subject="A"))
    repo.upsert_email(EmailInput(message_id="missing", subject="B"))
    llm = ScriptedLLMClient(
        [
            '{"category": "TECHNOLOGY", "confidence": 0.9, "rationale": null}',
            '{"title": "P", '
            '"core_pain_point": "Summary overview with enough unicode weight for QA.", '
            '"original_url": "https://example.com/p", "diagrams": []}',
        ],
    )
    _agent(repo, RunLock(db), svc, llm).run_daily()

    bad = repo.connection.execute(
        "SELECT status, retry_count FROM emails WHERE message_id = ?",
        ("missing",),
    ).fetchone()
    assert bad["status"] == "failed"
    assert bad["retry_count"] == 1

    good = repo.connection.execute(
        "SELECT status FROM emails WHERE message_id = ?",
        ("ok",),
    ).fetchone()
    assert good["status"] == "archived"
    assert repo.connection.execute("SELECT COUNT(*) FROM digest_emails").fetchone()[0] == 1


def test_send_failure_does_not_archive(tmp_path) -> None:
    svc = FakeGmailService(
        messages={
            "g1": _message_full_html(
                "g1",
                '<html><body><p>'
                + ("Promotional teaser text with enough prose for ingest. " * 30)
                + '</p>'
                '<a href="https://courses.example/rsvp">RSVP</a></body></html>',
            ),
        },
    )
    db = tmp_path / "db3.sqlite"
    repo = StateRepository(db)
    repo.upsert_email(EmailInput(message_id="g1", subject="S"))
    llm = ScriptedLLMClient(
        [
            '{"category": "COURSES", "confidence": 0.5, "rationale": null}',
            '{"summary": "Ad only teaser.", '
            '"actions": [{"label": "RSVP","url":"https://courses.example/rsvp"}], '
            '"promo_blocks": []}',
        ],
    )
    _agent(repo, RunLock(db), svc, llm, queue_send_fail=True).run_daily()

    row = repo.connection.execute("SELECT status FROM digests").fetchone()
    assert row["status"] == DIGEST_STATUS_SEND_FAILED
    em = repo.connection.execute("SELECT status FROM emails").fetchone()
    assert em["status"] == "pending"
    archive_calls = [
        c
        for c in svc.calls
        if c.method == "messages.modify"
        and c.kwargs.get("body", {}).get("removeLabelIds") == [INBOX_LABEL]
    ]
    assert archive_calls == []


def test_quality_gate_failure_persists_error(tmp_path) -> None:
    svc = FakeGmailService(
        messages={
            "g1": _message_full_html(
                "g1",
                '<html><body><p>'
                + ("Quality gate fixture padding for section routing minimums. " * 30)
                + '</p>'
                '<a href="https://learn.example/join">Join</a></body></html>',
            ),
        },
    )
    db = tmp_path / "db4.sqlite"
    repo = StateRepository(db)
    repo.upsert_email(EmailInput(message_id="g1", subject="S"))
    llm = ScriptedLLMClient(
        [
            '{"category": "COURSES", "confidence": 0.5, "rationale": null}',
            '{"summary": "Low value RSVP note.", '
            '"actions":[{"label":"Join","url":"https://learn.example/join"}],'
            '"promo_blocks":[]}',
        ],
    )

    class AlwaysFail:
        def check(self, html: str) -> QualityGateResult:
            return QualityGateResult(ok=False, problems=["forced_fail"])

    _agent(repo, RunLock(db), svc, llm, gate=AlwaysFail()).run_daily()

    row = repo.connection.execute(
        "SELECT status, error_message, body_html FROM digests",
    ).fetchone()
    assert row["status"] == DIGEST_STATUS_ERROR
    assert row["error_message"] is not None
    assert "quality_gate" in row["error_message"]
    assert row["body_html"]
    em = repo.connection.execute("SELECT status FROM emails").fetchone()
    assert em["status"] == "pending"


def test_retry_after_quality_fail_reuses_outputs_without_llm_or_fetch(tmp_path) -> None:
    svc = FakeGmailService(
        messages={
            "g1": _message_full_html(
                "g1",
                '<html><body><p>'
                + ("Retry fixture padding narrative for ingest minimums enforced. " * 30)
                + '</p>'
                '<a href="https://learn.example/class">Register</a></body></html>',
            ),
        },
    )
    db = tmp_path / "db_retry.sqlite"
    repo = StateRepository(db)
    repo.upsert_email(EmailInput(message_id="g1", subject="S"))
    llm = ScriptedLLMClient(
        [
            '{"category": "COURSES", "confidence": 0.5, "rationale": null}',
            '{"summary": "Low value teaser.", '
            '"actions":[{"label":"Register","url":"https://learn.example/class"}],'
            '"promo_blocks":[]}',
        ],
    )

    class AlwaysFail:
        def check(self, html: str) -> QualityGateResult:
            return QualityGateResult(ok=False, problems=["forced_fail"])

    _agent(repo, RunLock(db), svc, llm, gate=AlwaysFail()).run_daily()
    assert len(llm.completion_calls) == 2
    n_fetch = sum(1 for c in svc.calls if c.method == "messages.get")

    _agent(repo, RunLock(db), svc, llm, gate=DigestQualityGateAgent()).run_daily()

    assert len(llm.completion_calls) == 2
    assert sum(1 for c in svc.calls if c.method == "messages.get") == n_fetch
    assert repo.connection.execute("SELECT status FROM digests ORDER BY id").fetchall()[-1][
        "status"
    ] == DIGEST_STATUS_SENT
    assert (
        repo.connection.execute("SELECT status FROM emails").fetchone()["status"] == "archived"
    )


def test_run_lock_second_instance_does_not_steal_release(tmp_path) -> None:
    db = tmp_path / "db5.sqlite"
    first = RunLock(db)
    assert first.acquire(owner="p1")
    second = RunLock(db)
    assert second.acquire(owner="p2") is False
    second.release()
    row = sqlite3.connect(db).execute("SELECT owner FROM run_locks").fetchone()
    assert row is not None
    assert row[0] == "p1"
    first.release()


def test_all_candidates_fail_marks_digest_empty(tmp_path) -> None:
    svc = FakeGmailService(messages={})
    db = tmp_path / "db6.sqlite"
    repo = StateRepository(db)
    repo.upsert_email(EmailInput(message_id="only_bad", subject="Z"))
    llm = ScriptedLLMClient([])
    _agent(repo, RunLock(db), svc, llm).run_daily()

    row = repo.connection.execute("SELECT status FROM digests").fetchone()
    assert row["status"] == DIGEST_STATUS_EMPTY
    em = repo.connection.execute("SELECT status FROM emails").fetchone()
    assert em["status"] == "failed"
