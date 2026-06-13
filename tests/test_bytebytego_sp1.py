"""SP1 ByteByteGo profile fast-path tests."""

from __future__ import annotations

from unittest.mock import Mock

from app.agents.boundary_classifier_agent import BoundaryClassifierAgent
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
from app.models.outputs import RouteCategory, TechnologySectionOutput
from app.models.section import EmailSection
from app.parsing.interrupt_detection import InterruptRole, detect_interrupt_roles
from app.parsing.parser import ParsedHtmlResult
from app.processing.profile_executor import group_profile_units, resolve_profile_plan
from app.processing.sender_profiles import SENDER_PROFILES
from app.storage.repository import StateRepository
from app.storage.run_lock import RunLock
from tests.fakes import FakeGmailService
from tests.fakes.llm import ScriptedLLMClient
from tests.test_step5_section_digest_integration import _message_full_html


def _long(n: int = 80) -> str:
    return ("word " * n).strip()


def salesforce_163_sections() -> list[EmailSection]:
    """ByteByteGo Salesforce #163 shape (s0,s1,s3–s20 article; s2 sponsored)."""

    sections: list[EmailSection] = [
        EmailSection(section_id="s0", order_index=0, heading=None, text=_long(400)),
        EmailSection(
            section_id="s1",
            order_index=1,
            heading="What Salesforce Learned After 25 Years of Building Systems",
            text="What Salesforce Learned After 25 Years of Building Systems",
        ),
        EmailSection(
            section_id="s2",
            order_index=2,
            heading="WorkOS launches auth.md (Sponsored)",
            text=_long(120),
        ),
    ]
    for index in range(3, 21):
        sections.append(
            EmailSection(
                section_id=f"s{index}",
                order_index=index,
                heading=f"Section {index}",
                text=_long(100),
                links=[f"https://bytebytego.com/citations/ref-{index}"],
            ),
        )
    return sections


def test_salesforce_163_profile_groups_one_article_unit() -> None:
    sections = salesforce_163_sections()
    roles = detect_interrupt_roles(sections)
    assert roles[2] is InterruptRole.PROMO

    profile = SENDER_PROFILES["bytebytego@substack.com"]
    plan = group_profile_units(profile, sections, roles=roles)

    assert plan.hidden_section_keys == ("s2",)
    assert plan.article_unit.content_unit_key == "u0"
    assert plan.article_unit.section_keys == [f"s{i}" for i in [0, 1, *range(3, 21)]]
    assert "s2" not in plan.article_unit.section_keys


def test_weak_promo_keyword_stays_in_bytebytego_article_unit() -> None:
    sections = [
        EmailSection(section_id="s0", order_index=0, heading="Architecture", text=_long(300)),
        EmailSection(
            section_id="s1",
            order_index=1,
            heading="Side note",
            text="Mention register once in passing. " + _long(120),
        ),
    ]
    roles = detect_interrupt_roles(sections)
    assert roles[1] is InterruptRole.UNKNOWN_INTERRUPT

    profile = SENDER_PROFILES["bytebytego@substack.com"]
    plan = group_profile_units(profile, sections, roles=roles)
    assert plan.article_unit.section_keys == ["s0", "s1"]
    assert plan.hidden_section_keys == ()


def test_resolve_profile_plan_returns_none_on_empty_body() -> None:
    profile = SENDER_PROFILES["bytebytego@substack.com"]
    parsed = ParsedHtmlResult(
        plain_text="",
        plain_text_chars=0,
        links=[],
        image_urls=[],
        sections=[
            EmailSection(section_id="s0", order_index=0, heading="(Sponsored)", text="Ad only."),
        ],
    )
    assert resolve_profile_plan(profile, parsed) is None


def _bytebytego_agent(
    *,
    repo: StateRepository,
    lock: RunLock,
    svc: FakeGmailService,
    llm: ScriptedLLMClient,
    technology: TechnologyProcessorAgent,
    boundary: BoundaryClassifierAgent | None = None,
) -> DailyDigestAgent:
    client = GmailClient(service_factory=lambda: svc)
    return DailyDigestAgent(
        repo=repo,
        run_lock=lock,
        fetcher=GmailFetcher(client, senders=["bytebytego@substack.com"], max_results=20),
        router_agent=Mock(spec=RouterAgent),
        technology_agent=technology,
        radar_agent=Mock(spec=RadarProcessorAgent),
        leadership_agent=Mock(spec=LeadershipProcessorAgent),
        courses_agent=Mock(spec=CoursesProcessorAgent),
        map_reduce_radar_senders=(),
        content_unit_classifier_agent=ContentUnitClassifierAgent(llm, model="m"),
        boundary_classifier_agent=boundary,
        enable_content_unit_routing=True,
        composer=DigestComposer(title="ByteByteGo SP1"),
        quality_gate=DigestQualityGateAgent(),
        labeler=GmailLabeler(client),
        sender=GmailSender(client, sender="me@test"),
        digest_to="reader@test",
    )


def test_salesforce_163_integration_uses_profile_not_boundary_or_classifier_llm(tmp_path) -> None:
    sections = salesforce_163_sections()
    html = "<html><body>" + "".join(
        f"<h2>{section.heading}</h2><p>{section.text}</p>" if section.heading else f"<p>{section.text}</p>"
        for section in sections
    ) + "</body></html>"

    msg_id = "bbg-salesforce-163"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "bbg163.sqlite")
    repo.upsert_email(
        EmailInput(
            message_id=msg_id,
            subject="What Salesforce Learned",
            sender="bytebytego@substack.com",
        ),
    )

    llm = ScriptedLLMClient([])
    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="Salesforce systems",
        core_pain_point="Design lessons from long-lived platform architecture.",
        original_url=None,
        diagrams=[],
    )
    boundary = Mock(spec=BoundaryClassifierAgent)

    agent = _bytebytego_agent(
        repo=repo,
        lock=RunLock(tmp_path / "bbg163.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=boundary,
    )
    assert agent.run_daily() is True

    boundary.classify_boundaries.assert_not_called()
    assert technology.run_section.call_count == 1

    rows = repo.connection.execute(
        "SELECT kind, category, content_unit_key FROM agent_outputs ORDER BY id",
    ).fetchall()
    assert [(row["kind"], row["category"], row["content_unit_key"]) for row in rows] == [
        ("classifier", "TECHNOLOGY", "u0"),
        ("technology", "TECHNOLOGY", "u0"),
    ]

    boundary_row = repo.connection.execute(
        "SELECT 1 FROM agent_outputs WHERE kind = 'boundary_classifier'",
    ).fetchone()
    assert boundary_row is None

    import json

    classifier_payload = json.loads(
        repo.connection.execute(
            "SELECT payload FROM agent_outputs WHERE kind = 'classifier'",
        ).fetchone()["payload"],
    )
    assert classifier_payload["routing_source"] == "sender_profile"

    assert repo.connection.execute("SELECT status FROM emails").fetchone()["status"] == "archived"


def test_composer_ignores_generic_units_when_profile_u0_exists(tmp_path) -> None:
    """Generic u1/u2 leftovers must not produce extra Technical Index cards."""

    from app.models.content_units import ClassificationRoutingSource, ContentUnitClassificationResult
    from app.storage.repository import AgentOutputRecord

    repo = StateRepository(tmp_path / "orphan.sqlite")
    try:
        email_id = repo.upsert_email(
            EmailInput(message_id="bbg-orphan", sender="bytebytego@substack.com"),
        )
        profile_clf = ContentUnitClassificationResult(
            category=RouteCategory.TECHNOLOGY,
            confidence=1.0,
            rationale="profile",
            primary_value="v",
            routing_source=ClassificationRoutingSource.SENDER_PROFILE,
            sender_profile="bytebytego@substack.com",
            grouping_strategy="single_tech_article",
            content_hash="abc",
            processor_kind="technology",
        )
        generic_clf = ContentUnitClassificationResult(
            category=RouteCategory.TECHNOLOGY,
            confidence=0.9,
            rationale="generic",
            primary_value="v",
            routing_source=ClassificationRoutingSource.LLM_CLASSIFIER,
        )
        rows = [
            AgentOutputRecord(
                id=1,
                email_id=email_id,
                kind="classifier",
                payload=generic_clf.model_dump_json(),
                created_at="t",
                content_unit_key="u1",
                category="TECHNOLOGY",
            ),
            AgentOutputRecord(
                id=2,
                email_id=email_id,
                kind="technology",
                payload=TechnologySectionOutput(
                    title="Stale chapter A",
                    core_pain_point="old split",
                    original_url=None,
                    diagrams=[],
                ).model_dump_json(),
                created_at="t",
                content_unit_key="u1",
                category="TECHNOLOGY",
            ),
            AgentOutputRecord(
                id=3,
                email_id=email_id,
                kind="classifier",
                payload=profile_clf.model_dump_json(),
                created_at="t",
                content_unit_key="u0",
                category="TECHNOLOGY",
            ),
            AgentOutputRecord(
                id=4,
                email_id=email_id,
                kind="technology",
                payload=TechnologySectionOutput(
                    title="Merged article",
                    core_pain_point="one card",
                    original_url=None,
                    diagrams=[],
                ).model_dump_json(),
                created_at="t",
                content_unit_key="u0",
                category="TECHNOLOGY",
            ),
        ]
        html = DigestComposer().compose(rows, {email_id: "Token Spend"}).html
        assert html.count("Stale chapter A") == 0
        assert "Merged article" in html
        assert html.count("one card") == 1
    finally:
        repo.close()
