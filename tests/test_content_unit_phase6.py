from __future__ import annotations

from unittest.mock import Mock

from app.agents.ainews_radar_map_reduce_agent import AINewsRadarMapReduceAgent
from app.agents.content_unit_classifier_agent import ContentUnitClassifierAgent
from app.agents.courses_agent import CoursesProcessorAgent
from app.agents.daily_digest_agent import DailyDigestAgent
from app.agents.leadership_agent import LeadershipProcessorAgent
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
from app.models.outputs import TechnologySectionOutput
from app.models.section import EmailSection
from app.parsing.content_unit_grouping import group_content_units
from app.storage.repository import StateRepository
from app.storage.run_lock import RunLock
from tests.fakes import FakeGmailService
from tests.fakes.llm import ScriptedLLMClient
from tests.test_step5_section_digest_integration import _message_full_html


def _phase6_agent(
    *,
    repo: StateRepository,
    lock: RunLock,
    svc: FakeGmailService,
    llm: ScriptedLLMClient,
    technology: TechnologyProcessorAgent,
) -> DailyDigestAgent:
    client = GmailClient(service_factory=lambda: svc)
    return DailyDigestAgent(
        repo=repo,
        run_lock=lock,
        fetcher=GmailFetcher(client, senders=["newsletter@fixture.test"], max_results=20),
        router_agent=Mock(spec=RouterAgent),
        technology_agent=technology,
        radar_agent=Mock(spec=RadarProcessorAgent),
        leadership_agent=Mock(spec=LeadershipProcessorAgent),
        courses_agent=Mock(spec=CoursesProcessorAgent),
        map_reduce_radar_agent=AINewsRadarMapReduceAgent(llm, model="m"),
        map_reduce_radar_senders=(),
        content_unit_classifier_agent=ContentUnitClassifierAgent(llm, model="m"),
        enable_content_unit_routing=True,
        composer=DigestComposer(title="Phase 6 test"),
        quality_gate=DigestQualityGateAgent(),
        labeler=GmailLabeler(client),
        sender=GmailSender(client, sender="me@test"),
        digest_to="reader@test",
    )


def test_group_content_units_splits_promo_from_long_form() -> None:
    sections = [
        EmailSection(section_id="s0", order_index=0, heading="Architecture", text="deep " * 300),
        EmailSection(section_id="s1", order_index=1, heading="Tradeoffs", text="tradeoff " * 300),
        EmailSection(
            section_id="s2",
            order_index=2,
            heading="Workshop",
            text="Register for the webinar and RSVP for the workshop.",
            links=["https://events.example/register"],
        ),
    ]

    grouping = group_content_units(sections)

    assert [u.content_unit_key for u in grouping.units] == ["u0", "u1"]
    assert grouping.units[0].section_keys == ["s0", "s1"]
    assert grouping.units[1].section_keys == ["s2"]


def test_phase6_content_unit_classifier_dispatches_processor_and_persists_pair(tmp_path) -> None:
    html = "<html><body><h2>Agent reliability</h2><p>" + ("system design " * 220) + "</p></body></html>"
    msg_id = "phase6-ok"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "phase6.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Reliability", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient(
        [
            (
                '{"category":"TECHNOLOGY","confidence":0.9,'
                '"rationale":"Durable architecture discussion.",'
                '"primary_value":"Remember an agent reliability pattern.",'
                '"evidence":["system design"]}'
            ),
        ],
    )
    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="Agent reliability",
        core_pain_point="Keeping agent workflows reliable under tool and context failures.",
        original_url=None,
        diagrams=[],
    )

    agent = _phase6_agent(repo=repo, lock=RunLock(tmp_path / "phase6.sqlite"), svc=svc, llm=llm, technology=technology)
    assert agent.run_daily() is True

    rows = repo.connection.execute(
        "SELECT kind, category, content_unit_key FROM agent_outputs ORDER BY id",
    ).fetchall()
    assert [(r["kind"], r["category"], r["content_unit_key"]) for r in rows] == [
        ("classifier", "TECHNOLOGY", "u0"),
        ("technology", "TECHNOLOGY", "u0"),
    ]
    assert repo.connection.execute("SELECT status FROM emails").fetchone()["status"] == "archived"


def test_phase6_low_confidence_classifier_fails_email_without_processor(tmp_path) -> None:
    html = "<html><body><h2>Ambiguous</h2><p>" + ("mixed signal " * 180) + "</p></body></html>"
    msg_id = "phase6-low"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "phase6_low.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Ambiguous", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient(
        [
            (
                '{"category":"RADAR","confidence":0.4,'
                '"rationale":"Insufficient evidence.",'
                '"primary_value":"Unclear.",'
                '"evidence":["mixed signal"]}'
            ),
        ],
    )
    technology = Mock(spec=TechnologyProcessorAgent)

    agent = _phase6_agent(
        repo=repo,
        lock=RunLock(tmp_path / "phase6_low.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
    )
    assert agent.run_daily() is True

    assert technology.run_section.call_count == 0
    email = repo.connection.execute("SELECT status, retry_count, error_message FROM emails").fetchone()
    assert email["status"] == "failed"
    assert email["retry_count"] == 1
    assert "classification_failed" in email["error_message"]
    assert repo.connection.execute("SELECT kind FROM agent_outputs").fetchone()["kind"] == "classifier"
