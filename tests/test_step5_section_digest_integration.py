"""Step 5 integration tests aligned with section-scoped routing and persistence.

Architectural assumptions (must match product):
  - Exactly one RouteCategory per section; multi-category newsletters use multiple sections.
  - Processor payloads are section-native (TechnologySectionOutput, RadarOutput, etc.).
  - Per-email all-or-nothing: any section failure skips digest inclusion / labeling / archive for that mail.
  - Section cache reuse routes on DB ``email_sections.id`` pairs with stored rows; preserving that id
    across ``replace_email_sections`` requires unchanged ``(section_key, content_hash)``.
"""

from __future__ import annotations

from unittest.mock import Mock

from app.agents.courses_agent import CoursesProcessorAgent
from app.agents.daily_digest_agent import (
    DIGEST_STATUS_EMPTY,
    DIGEST_STATUS_SEND_FAILED,
    DIGEST_STATUS_SENT,
    DailyDigestAgent,
)
from app.agents.leadership_agent import LeadershipProcessorAgent
from app.agents.radar_agent import RadarProcessorAgent
from app.agents.router_agent import RouterAgent
from app.agents.technology_agent import TechnologyProcessorAgent
from app.agents.ainews_radar_map_reduce_agent import AINewsRadarMapReduceAgent
from app.digest.composer import DigestComposer
from app.digest.quality_gate import DigestQualityGateAgent
from app.gmail.client import GmailClient
from app.gmail.fetcher import GmailFetcher
from app.gmail.labeler import GmailLabeler, PROCESSED_LABEL
from app.gmail.sender import GmailSender
from app.gmail.sender import GmailSender
from app.models.email import EmailInput
from app.models.section import EmailSection
from app.models.outputs import (
    CourseActionItem,
    CoursesOutput,
    LeadershipSectionOutput,
    LeadershipSignal,
    RadarItem,
    RadarOutput,
    RouterDecision,
    RouteCategory,
    TechnologySectionOutput,
)
from app.storage.repository import StateRepository
from app.storage.run_lock import RunLock
from tests.fakes import FakeGmailService, FakeHttpError, make_message
from tests.fakes.llm import ScriptedLLMClient
from tests.test_milestone5_daily_digest import _b64url, _message_full_html


def _padded_chars(*, minimum: int = 320) -> str:
    frag = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Integer posuere erat a ante venenatis dapibus. "
    )
    blob = ""
    while len(blob) < minimum:
        blob += frag
    return blob


def _four_heading_newsletter_html() -> str:
    """Four DOM sections after sectionize (no preamble); each exceeds ``MIN_SECTION_CHARS``."""
    headings = ("Tech depth", "Market radar", "Leadership memo", "Course promo")
    chunks: list[str] = []
    for i, title in enumerate(headings):
        body = _padded_chars()
        chunks.append(
            f"<h2>{title}</h2><p>{body}</p>"
            f'<a href="https://fixture.example/multi/sec{i}/more">More</a>',
        )
    return f"<html><body>{''.join(chunks)}</body></html>"


def _router_decision_for_section_title(*, section_heading: str | None, **_kwargs: object) -> RouterDecision:
    """Return category from ``section_heading`` (stable across retries).

    Do not use list ``RouterAgent.run`` ``side_effect`` queues for retry tests: failed runs may exit
    before every section is routed, so leftover queue entries mis-route the next attempt. Prefer heading,
    ``section_key``, or ``content_hash`` (or similar) as the mock key instead.
    """

    h = (section_heading or "").strip().lower()
    if "tech" in h:
        return RouterDecision(category=RouteCategory.TECHNOLOGY, confidence=0.9, rationale=None)
    if "radar" in h:
        return RouterDecision(category=RouteCategory.RADAR, confidence=0.85, rationale=None)
    if "leadership" in h:
        return RouterDecision(category=RouteCategory.LEADERSHIP, confidence=0.8, rationale=None)
    if "course" in h:
        return RouterDecision(category=RouteCategory.COURSES, confidence=0.75, rationale=None)
    raise AssertionError(f"unexpected fixture heading for router: {section_heading!r}")


def _agent_with_deps(
    repo: StateRepository,
    lock: RunLock,
    svc: FakeGmailService,
    llm: ScriptedLLMClient,
    *,
    router: RouterAgent,
    technology_agent: TechnologyProcessorAgent,
    radar_agent: RadarProcessorAgent,
    leadership_agent: LeadershipProcessorAgent,
    courses_agent: CoursesProcessorAgent,
    gate: DigestQualityGateAgent | None = None,
    queue_send_fail: bool = False,
) -> DailyDigestAgent:
    if queue_send_fail:
        svc.queue_failure("messages.send", FakeHttpError(400, "send boom"))
    client = GmailClient(service_factory=lambda: svc)
    fetcher = GmailFetcher(client, senders=["newsletter@fixture.test"], max_results=20)
    return DailyDigestAgent(
        repo=repo,
        run_lock=lock,
        fetcher=fetcher,
        router_agent=router,
        technology_agent=technology_agent,
        radar_agent=radar_agent,
        leadership_agent=leadership_agent,
        courses_agent=courses_agent,
        map_reduce_radar_agent=AINewsRadarMapReduceAgent(llm, model="m"),
        map_reduce_radar_senders=(),
        composer=DigestComposer(title="Test digest"),
        quality_gate=gate or DigestQualityGateAgent(),
        labeler=GmailLabeler(client),
        sender=GmailSender(client, sender="me@test"),
        digest_to="reader@test",
    )


def test_four_sections_four_categories_in_final_digest_html(tmp_path) -> None:
    html = _four_heading_newsletter_html()
    msg_id = "step5-multi-cat"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    db = tmp_path / "step5_four_cat.sqlite"
    repo = StateRepository(db)
    lock = RunLock(db)
    repo.upsert_email(
        EmailInput(message_id=msg_id, subject="Mega issue STEP5_SUBJECT", sender="newsletter@fixture.test"),
    )

    router = Mock(spec=RouterAgent)
    router.run.side_effect = lambda **kw: _router_decision_for_section_title(**kw)

    tech = Mock(spec=TechnologyProcessorAgent)
    tech.run_section.return_value = TechnologySectionOutput(
        title="STEP5_TECH_ARTICLE_MARKER",
        core_pain_point="STEP5_TECH_CPP_MARKER padded enough for assertions.",
        original_url="https://fixture.example/multi/sec0/article",
        diagrams=[],
    )

    radar = Mock(spec=RadarProcessorAgent)
    radar.run_section.return_value = RadarOutput(
        summary="STEP5_RADAR_SUMMARY_MARKER",
        items=[RadarItem(entity="ACME", impact_or_action="Shipped tooling.", url=None)],
    )

    lead = Mock(spec=LeadershipProcessorAgent)
    lead.run_section.return_value = LeadershipSectionOutput(
        signals=[
            LeadershipSignal(
                theme="STEP5_LEAD_THEME",
                insight="Clarity beats speed.",
                actionable_item="Document decisions weekly.",
                link=None,
            ),
        ],
        summary=None,
    )

    courses = Mock(spec=CoursesProcessorAgent)
    courses.run_section.return_value = CoursesOutput(
        summary="STEP5_RSVP_SUMMARY_MARKER",
        actions=[CourseActionItem(label="Enroll", url="https://courses.fixture.example/step5-enroll")],
        promo_blocks=[],
    )

    agent = _agent_with_deps(
        repo,
        lock,
        svc,
        ScriptedLLMClient([]),
        router=router,
        technology_agent=tech,
        radar_agent=radar,
        leadership_agent=lead,
        courses_agent=courses,
    )

    agent.run_daily()

    router.run.assert_called()
    assert router.run.call_count == 4
    assert tech.run_section.call_count == 1
    assert radar.run_section.call_count == 1
    assert lead.run_section.call_count == 1
    assert courses.run_section.call_count == 1

    body = repo.connection.execute(
        "SELECT body_html FROM digests WHERE status = ?",
        (DIGEST_STATUS_SENT,),
    ).fetchone()["body_html"]
    assert body is not None
    html_out = body
    assert "STEP5_TECH_ARTICLE_MARKER" in html_out
    assert "STEP5_TECH_CPP_MARKER" in html_out
    assert "STEP5_RADAR_SUMMARY_MARKER" in html_out
    assert "STEP5_LEAD_THEME" in html_out
    assert "Courses" in html_out or "STEP5_RSVP_SUMMARY_MARKER" in html_out
    assert "https://courses.fixture.example/step5-enroll" in html_out


def test_section_processor_failure_entire_mail_excluded_from_digest(tmp_path) -> None:
    html = _four_heading_newsletter_html()
    svc = FakeGmailService(messages={"bad_proc": _message_full_html("bad_proc", html)})
    db = tmp_path / "step5_partial.sqlite"
    repo = StateRepository(db)
    repo.upsert_email(
        EmailInput(message_id="bad_proc", subject="Bad section", sender="newsletter@fixture.test"),
    )

    router = Mock(spec=RouterAgent)
    router.run.side_effect = lambda **kw: _router_decision_for_section_title(**kw)

    tech = Mock(spec=TechnologyProcessorAgent)
    tech.run_section.return_value = TechnologySectionOutput(
        title="ok",
        core_pain_point="x" * 200,
        original_url="https://fixture.example/multi/sec0/x",
        diagrams=[],
    )
    radar = Mock(spec=RadarProcessorAgent)
    radar.run_section.return_value = RadarOutput(summary="pulse", items=[])
    lead = Mock(spec=LeadershipProcessorAgent)
    lead.run_section.return_value = LeadershipSectionOutput(
        signals=[
            LeadershipSignal(theme="thr", insight="x", actionable_item="y", link=None),
        ],
        summary=None,
    )
    courses = Mock(spec=CoursesProcessorAgent)
    courses.run_section.side_effect = RuntimeError("courses processor exploded")

    agent = _agent_with_deps(
        repo,
        RunLock(db),
        svc,
        ScriptedLLMClient([]),
        router=router,
        technology_agent=tech,
        radar_agent=radar,
        leadership_agent=lead,
        courses_agent=courses,
    )
    agent.run_daily()

    d = repo.connection.execute("SELECT status FROM digests ORDER BY id").fetchone()
    assert d["status"] == DIGEST_STATUS_EMPTY

    em = repo.connection.execute(
        "SELECT status FROM emails WHERE message_id = ?",
        ("bad_proc",),
    ).fetchone()
    assert em["status"] == "failed"

    digest_links = int(repo.connection.execute("SELECT COUNT(*) FROM digest_emails").fetchone()[0])
    assert digest_links == 0

    assert sum(1 for c in svc.calls if c.method == "messages.modify") == 0


def test_send_failure_skips_processed_label_and_archive(tmp_path) -> None:
    html_body = (
        '<html><body>'
        '<h2>Ingest block</h2><p>'
        + _padded_chars()
        + '</p>'
        '<a href="https://courses.example/rsvp-step5">RSVP</a></body></html>'
    )
    mid = "g-sendfail-step5"
    svc = FakeGmailService(
        labels={PROCESSED_LABEL: "Label_PROC"},
        messages={mid: _message_full_html(mid, html_body)},
    )
    repo = StateRepository(tmp_path / "sf5.sqlite")
    repo.upsert_email(
        EmailInput(message_id=mid, subject="S", sender="newsletter@fixture.test"),
    )
    router = Mock(spec=RouterAgent)
    router.run.return_value = RouterDecision(category=RouteCategory.COURSES, confidence=0.5, rationale=None)
    tech = Mock(spec=TechnologyProcessorAgent)
    radar = Mock(spec=RadarProcessorAgent)
    lead = Mock(spec=LeadershipProcessorAgent)
    courses = Mock(spec=CoursesProcessorAgent)
    courses.run_section.return_value = CoursesOutput(
        summary="Reminder.",
        actions=[CourseActionItem(label="RSVP", url="https://courses.example/rsvp-step5")],
        promo_blocks=[],
    )
    agent = _agent_with_deps(
        repo,
        RunLock(tmp_path / "sf5.sqlite"),
        svc,
        ScriptedLLMClient([]),
        router=router,
        technology_agent=tech,
        radar_agent=radar,
        leadership_agent=lead,
        courses_agent=courses,
        queue_send_fail=True,
    )
    agent.run_daily()

    assert repo.connection.execute("SELECT status FROM digests").fetchone()["status"] == DIGEST_STATUS_SEND_FAILED
    assert svc.call_kwargs("messages.modify") == []


def test_retry_after_section_processor_error_reuses_llm_through_section_cache(tmp_path) -> None:
    """First run succeeds for sections 0–1; Leadership processor raises on section 2 (section-native).

    Second run parses identical HTML; unchanged ``(section_key, content_hash)`` preserves
    ``email_sections.id``. Completed sections reuse router+processor via cache; Leadership and Courses
    run forward without re-invoking Tech/Radar processors.
    """
    html = _four_heading_newsletter_html()
    mid = "step5-cache-retry"
    raw = dict(make_message(msg_id=mid, label_ids=["INBOX"]))
    hdrs = raw["payload"]["headers"]
    raw["payload"] = {"mimeType": "text/html", "headers": hdrs, "body": {"data": _b64url(html)}}

    svc = FakeGmailService(messages={mid: raw})
    db = tmp_path / "step5_cache.sqlite"
    repo = StateRepository(db)
    lock = RunLock(db)
    repo.upsert_email(
        EmailInput(message_id=mid, subject="Cache probe", sender="newsletter@fixture.test"),
    )

    router = Mock(spec=RouterAgent)
    router.run.side_effect = lambda **kw: _router_decision_for_section_title(**kw)

    ok_tech = TechnologySectionOutput(
        title="reuse-tech-marker",
        core_pain_point="body " + "x" * 200,
        original_url="https://fixture.example/multi/sec0/link",
        diagrams=[],
    )
    tech = Mock(spec=TechnologyProcessorAgent)
    tech.run_section.return_value = ok_tech

    ok_radar = RadarOutput(summary="reuse-radar-marker", items=[])
    radar = Mock(spec=RadarProcessorAgent)
    radar.run_section.return_value = ok_radar

    ok_lead = LeadershipSectionOutput(
        signals=[
            LeadershipSignal(theme="reuse-lead", insight="trust", actionable_item="be clear", link=None),
        ],
        summary=None,
    )

    leadership_calls: list[int] = [0]

    leadership = Mock(spec=LeadershipProcessorAgent)

    def _lead_sections(section: EmailSection, **kwargs: object) -> LeadershipSectionOutput:
        leadership_calls[0] += 1
        if leadership_calls[0] == 1:
            raise RuntimeError("leadership flaky once")
        return ok_lead

    leadership.run_section.side_effect = _lead_sections

    ok_course = CoursesOutput(
        summary="courses cache ok",
        actions=[CourseActionItem(label="Join", url="https://courses.fixture.example/marker")],
        promo_blocks=[],
    )
    courses = Mock(spec=CoursesProcessorAgent)
    courses.run_section.return_value = ok_course

    agent = _agent_with_deps(
        repo,
        lock,
        svc,
        ScriptedLLMClient([]),
        router=router,
        technology_agent=tech,
        radar_agent=radar,
        leadership_agent=leadership,
        courses_agent=courses,
    )
    agent.run_daily()

    assert repo.connection.execute("SELECT status FROM digests ORDER BY id").fetchone()["status"] == DIGEST_STATUS_EMPTY

    eid_row = repo.connection.execute(
        "SELECT id FROM emails WHERE message_id = ?",
        (mid,),
    ).fetchone()
    assert eid_row is not None
    email_id = int(eid_row["id"])

    secs_after_fail = repo.list_email_sections(email_id)
    assert len(secs_after_fail) == 4
    preserved_ids_before = tuple(sorted(s.id for s in secs_after_fail))

    n_get_fail = sum(1 for c in svc.calls if c.method == "messages.get")
    tech_calls_after_fail = tech.run_section.call_count

    agent.run_daily()

    assert (
        repo.connection.execute("SELECT status FROM digests ORDER BY id DESC").fetchone()["status"]
        == DIGEST_STATUS_SENT
    )

    secs_after_ok = repo.list_email_sections(email_id)
    preserved_ids_after = tuple(sorted(s.id for s in secs_after_ok))

    assert preserved_ids_after == preserved_ids_before
    assert len(preserved_ids_after) == 4

    assert tech.run_section.call_count == tech_calls_after_fail
    assert radar.run_section.call_count == tech_calls_after_fail == 1
    assert leadership.run_section.call_count == 2
    assert courses.run_section.call_count == 1
    assert router.run.call_count == 5  # First run stops after 3 headings; rerun routes only s2+s3.

    n_get_second = sum(1 for c in svc.calls if c.method == "messages.get")
    assert n_get_second == n_get_fail + 1

    archived = repo.connection.execute("SELECT status FROM emails").fetchone()["status"]
    assert archived == "archived"


def test_second_run_daily_does_not_refetch_processed_archived_mail(tmp_path) -> None:
    html = (
        "<html><body><h2>Only</h2><p>" + _padded_chars() + "</p>"
        '<a href="https://solo.example/item">More</a></body></html>'
    )
    mid = "step5-twice"
    svc = FakeGmailService(messages={mid: _message_full_html(mid, html)})
    db = tmp_path / "step5_twice.sqlite"
    repo = StateRepository(db)
    repo.upsert_email(
        EmailInput(message_id=mid, subject="Solo", sender="newsletter@fixture.test"),
    )
    router = Mock(spec=RouterAgent)
    router.run.return_value = RouterDecision(category=RouteCategory.TECHNOLOGY, confidence=0.9, rationale=None)
    tech = Mock(spec=TechnologyProcessorAgent)
    tech.run_section.return_value = TechnologySectionOutput(
        title="once",
        core_pain_point="y" * 200,
        original_url="https://solo.example/item",
        diagrams=[],
    )
    radar = Mock(spec=RadarProcessorAgent)
    lead = Mock(spec=LeadershipProcessorAgent)
    courses = Mock(spec=CoursesProcessorAgent)
    agent = _agent_with_deps(
        repo,
        RunLock(db),
        svc,
        ScriptedLLMClient([]),
        router=router,
        technology_agent=tech,
        radar_agent=radar,
        leadership_agent=lead,
        courses_agent=courses,
    )
    agent.run_daily()
    n_get_1 = sum(1 for c in svc.calls if c.method == "messages.get")
    assert n_get_1 == 1
    tech_first = tech.run_section.call_count

    agent.run_daily()

    n_get_2 = sum(1 for c in svc.calls if c.method == "messages.get")
    assert n_get_2 == n_get_1
    assert tech.run_section.call_count == tech_first
    sends = svc.call_kwargs("messages.send")
    assert len(sends) == 1
