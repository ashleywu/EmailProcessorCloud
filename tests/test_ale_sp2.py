"""SP2 A Life Engineered profile fast-path tests."""

from __future__ import annotations

import json
from unittest.mock import Mock

from app.agents.boundary_classifier_agent import BoundaryClassifierAgent
from app.agents.content_unit_classifier_agent import ContentUnitClassifierAgent
from app.agents.courses_agent import CoursesProcessorAgent
from app.agents.daily_digest_agent import DailyDigestAgent
from app.agents.leadership_agent import LeadershipProcessorAgent
from app.agents.leadership_essay_agent import LeadershipEssayProcessorAgent
from app.agents.radar_agent import RadarProcessorAgent
from app.agents.router_agent import RouterAgent
from app.agents.technology_agent import TechnologyProcessorAgent
from app.digest.composer import DigestComposer
from app.digest.quality_gate import DigestQualityGateAgent
from app.gmail.client import GmailClient
from app.gmail.fetcher import GmailFetcher
from app.gmail.labeler import GmailLabeler
from app.gmail.sender import GmailSender
from app.models.email import EmailInput
from app.models.outputs import LEADERSHIP_ESSAY_OUTPUT_KIND, LeadershipEssayOutput
from app.models.section import EmailSection
from app.parsing.interrupt_detection import InterruptRole, detect_interrupt_roles
from app.processing.profile_executor import group_profile_units
from app.processing.sender_profiles import SENDER_PROFILES
from app.storage.repository import AgentOutputRecord, StateRepository
from app.storage.run_lock import RunLock
from tests.fakes import FakeGmailService
from tests.fakes.llm import ScriptedLLMClient
from tests.test_step5_section_digest_integration import _message_full_html


def _long(n: int = 80) -> str:
    return ("word " * n).strip()


def ale_essay_sections() -> list[EmailSection]:
    return [
        EmailSection(section_id="s0", order_index=0, heading=None, text=_long(350)),
        EmailSection(
            section_id="s1",
            order_index=1,
            heading="The Leadership Gap Nobody Talks About",
            text=_long(280),
        ),
        EmailSection(
            section_id="s2",
            order_index=2,
            heading="Partner cohort (Sponsored)",
            text=_long(90),
        ),
        EmailSection(
            section_id="s3",
            order_index=3,
            heading="What to do next",
            text=(
                "The author recommends scheduling a weekly one-on-one with every direct report. "
                + _long(180)
            ),
        ),
    ]


def test_ale_profile_merges_body_and_hides_sponsored_block() -> None:
    sections = ale_essay_sections()
    roles = detect_interrupt_roles(sections)
    assert roles[2] is InterruptRole.PROMO

    profile = SENDER_PROFILES["alifeengineered@substack.com"]
    plan = group_profile_units(profile, sections, roles=roles)

    assert plan.hidden_section_keys == ("s2",)
    assert plan.article_unit.section_keys == ["s0", "s1", "s3"]
    assert "weekly one-on-one" in plan.article_unit.unit_text


def test_leadership_essay_composer_renders_author_and_senior_actions_separately(tmp_path) -> None:
    repo = StateRepository(tmp_path / "compose.sqlite")
    try:
        essay = LeadershipEssayOutput(
            title="Leadership Gap",
            core_thesis="Great managers close the feedback loop early.",
            leadership_signals=["Feedback cadence predicts retention."],
            author_action_items=["Schedule a weekly one-on-one with every direct report."],
            senior_engineer_actions=["Block 30 minutes Friday to review team feedback themes."],
            notable_examples=["Example from a turnaround team."],
            original_url=None,
        )
        row = AgentOutputRecord(
            id=1,
            email_id=7,
            kind=LEADERSHIP_ESSAY_OUTPUT_KIND,
            payload=essay.model_dump_json(),
            created_at="2026-06-12T00:00:00+00:00",
            content_unit_key="u0",
            category="LEADERSHIP",
        )
        classifier = AgentOutputRecord(
            id=0,
            email_id=7,
            kind="classifier",
            payload='{"category":"LEADERSHIP","confidence":1.0,"rationale":"r","primary_value":"v","evidence":[],"routing_source":"sender_profile","warnings":[]}',
            created_at="2026-06-12T00:00:00+00:00",
            content_unit_key="u0",
            category="LEADERSHIP",
        )
        html = DigestComposer().compose([classifier, row], {7: "ALE issue"}).html
        assert "Author action items" in html
        assert "Senior engineer actions" in html
        assert "weekly one-on-one" in html
        assert "review team feedback themes" in html
        assert html.index("Author action items") < html.index("Senior engineer actions")
    finally:
        repo.close()


def _ale_agent(
    *,
    repo: StateRepository,
    lock: RunLock,
    svc: FakeGmailService,
    llm: ScriptedLLMClient,
    leadership_essay: LeadershipEssayProcessorAgent,
    boundary: BoundaryClassifierAgent | None = None,
) -> DailyDigestAgent:
    client = GmailClient(service_factory=lambda: svc)
    return DailyDigestAgent(
        repo=repo,
        run_lock=lock,
        fetcher=GmailFetcher(client, senders=["alifeengineered@substack.com"], max_results=20),
        router_agent=Mock(spec=RouterAgent),
        technology_agent=Mock(spec=TechnologyProcessorAgent),
        radar_agent=Mock(spec=RadarProcessorAgent),
        leadership_agent=Mock(spec=LeadershipProcessorAgent),
        courses_agent=Mock(spec=CoursesProcessorAgent),
        leadership_essay_agent=leadership_essay,
        map_reduce_radar_senders=(),
        content_unit_classifier_agent=ContentUnitClassifierAgent(llm, model="m"),
        boundary_classifier_agent=boundary or Mock(spec=BoundaryClassifierAgent),
        enable_content_unit_routing=True,
        composer=DigestComposer(title="ALE SP2"),
        quality_gate=DigestQualityGateAgent(),
        labeler=GmailLabeler(client),
        sender=GmailSender(client, sender="me@test"),
        digest_to="reader@test",
    )


def test_ale_integration_profile_path_skips_boundary_and_classifier_llm(tmp_path) -> None:
    sections = ale_essay_sections()
    html = "<html><body>" + "".join(
        f"<h2>{section.heading}</h2><p>{section.text}</p>" if section.heading else f"<p>{section.text}</p>"
        for section in sections
    ) + "</body></html>"

    msg_id = "ale-sp2"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "ale.sqlite")
    repo.upsert_email(
        EmailInput(
            message_id=msg_id,
            subject="The Leadership Gap",
            sender="alifeengineered@substack.com",
        ),
    )

    llm = ScriptedLLMClient([])
    essay_mock = Mock(spec=LeadershipEssayProcessorAgent)
    essay_mock.run_unit.return_value = LeadershipEssayOutput(
        title="The Leadership Gap Nobody Talks About",
        core_thesis="Managers must institutionalize feedback loops.",
        leadership_signals=["Weekly cadence matters."],
        author_action_items=["Schedule a weekly one-on-one with every direct report."],
        senior_engineer_actions=["Reserve Friday office hours for upward feedback."],
        notable_examples=["Turnaround team anecdote."],
        original_url=None,
    )
    boundary = Mock(spec=BoundaryClassifierAgent)

    agent = _ale_agent(
        repo=repo,
        lock=RunLock(tmp_path / "ale.sqlite"),
        svc=svc,
        llm=llm,
        leadership_essay=essay_mock,
        boundary=boundary,
    )

    assert agent.run_daily() is True

    boundary.classify_boundaries.assert_not_called()
    essay_mock.run_unit.assert_called_once()

    rows = repo.connection.execute(
        "SELECT kind, category, content_unit_key FROM agent_outputs ORDER BY id",
    ).fetchall()
    assert [(row["kind"], row["category"], row["content_unit_key"]) for row in rows] == [
        ("classifier", "LEADERSHIP", "u0"),
        (LEADERSHIP_ESSAY_OUTPUT_KIND, "LEADERSHIP", "u0"),
    ]

    payload = json.loads(
        repo.connection.execute(
            "SELECT payload FROM agent_outputs WHERE kind = ?",
            (LEADERSHIP_ESSAY_OUTPUT_KIND,),
        ).fetchone()["payload"],
    )
    assert payload["author_action_items"] == ["Schedule a weekly one-on-one with every direct report."]
    assert payload["senior_engineer_actions"] == ["Reserve Friday office hours for upward feedback."]

    classifier_payload = json.loads(
        repo.connection.execute(
            "SELECT payload FROM agent_outputs WHERE kind = 'classifier'",
        ).fetchone()["payload"],
    )
    assert classifier_payload["routing_source"] == "sender_profile"

    assert repo.connection.execute("SELECT status FROM emails").fetchone()["status"] == "archived"
