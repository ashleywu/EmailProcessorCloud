"""SP3 Latent Space (swyx@) profile fast-path tests."""

from __future__ import annotations

import json
from unittest.mock import Mock

from app.agents.ainews_radar_map_reduce_agent import AINewsRadarMapReduceAgent
from app.agents.boundary_classifier_agent import BoundaryClassifierAgent
from app.agents.content_unit_classifier_agent import ContentUnitClassifierAgent
from app.agents.courses_agent import CoursesProcessorAgent
from app.agents.daily_digest_agent import DailyDigestAgent
from app.agents.leadership_agent import LeadershipProcessorAgent
from app.agents.leadership_essay_agent import LeadershipEssayProcessorAgent
from app.agents.radar_agent import RadarProcessorAgent
from app.agents.router_agent import RouterAgent
from app.agents.technical_longform_agent import TechnicalLongformProcessorAgent
from app.agents.technology_agent import TechnologyProcessorAgent
from app.digest.composer import DigestComposer
from app.digest.quality_gate import DigestQualityGateAgent
from app.gmail.client import GmailClient
from app.gmail.fetcher import GmailFetcher
from app.gmail.labeler import GmailLabeler
from app.gmail.sender import GmailSender
from app.models.email import EmailInput
from app.models.outputs import (
    MAP_REDUCE_RADAR_DIGEST_KIND,
    TECHNICAL_LONGFORM_OUTPUT_KIND,
    TechnicalLongformOutput,
)
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


def railway_interview_sections() -> list[EmailSection]:
    """Railway/Andon-style interview — multiple topic H2s stay in one unit."""

    return [
        EmailSection(section_id="s0", order_index=0, heading=None, text=_long(350)),
        EmailSection(
            section_id="s1",
            order_index=1,
            heading="How Railway Thinks About Platform Reliability",
            text=_long(220),
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
            heading="On incident response culture",
            text="Interviewer: How do you run Andon? " + _long(180),
        ),
        EmailSection(
            section_id="s4",
            order_index=4,
            heading="On deployment velocity",
            text="Guest: We ship weekly with guardrails. " + _long(160),
        ),
    ]


def tech_essay_sections() -> list[EmailSection]:
    return [
        EmailSection(section_id="s0", order_index=0, heading=None, text=_long(320)),
        EmailSection(
            section_id="s1",
            order_index=1,
            heading="Why Small Models Win at the Edge",
            text=_long(260),
        ),
        EmailSection(
            section_id="s2",
            order_index=2,
            heading="Footer links",
            text="Unsubscribe | Latent Space",
        ),
    ]


def multi_topic_transcript_sections() -> list[EmailSection]:
    return [
        EmailSection(section_id="s0", order_index=0, heading="Intro", text=_long(200)),
        EmailSection(section_id="s1", order_index=1, heading="Topic A", text=_long(150)),
        EmailSection(section_id="s2", order_index=2, heading="Topic B", text=_long(150)),
        EmailSection(section_id="s3", order_index=3, heading="Topic C", text=_long(150)),
        EmailSection(section_id="s4", order_index=4, heading="Topic D", text=_long(150)),
    ]


def test_latent_space_profile_merges_interview_and_hides_sponsor() -> None:
    sections = railway_interview_sections()
    roles = detect_interrupt_roles(sections)
    assert roles[2] is InterruptRole.PROMO

    profile = SENDER_PROFILES["swyx@substack.com"]
    plan = group_profile_units(profile, sections, roles=roles)

    assert plan.hidden_section_keys == ("s2",)
    assert plan.article_unit.section_keys == ["s0", "s1", "s3", "s4"]
    assert "Andon" in plan.article_unit.unit_text


def test_latent_space_profile_merges_multi_topic_transcript_into_one_unit() -> None:
    sections = multi_topic_transcript_sections()
    profile = SENDER_PROFILES["swyx@substack.com"]
    plan = group_profile_units(profile, sections)
    assert plan.article_unit.section_keys == ["s0", "s1", "s2", "s3", "s4"]


def test_swyx_plus_ainews_not_in_sp3_registry() -> None:
    assert "swyx+ainews@substack.com" not in SENDER_PROFILES
    assert SENDER_PROFILES["swyx@substack.com"].strategy.value == "single_tech_longform"


def test_technical_longform_composer_renders_one_technical_index_card(tmp_path) -> None:
    repo = StateRepository(tmp_path / "compose.sqlite")
    try:
        longform = TechnicalLongformOutput(
            title="Railway reliability",
            format="interview",
            central_topic="Platform reliability practices at Railway.",
            key_technical_insights=["Andon culture reduces MTTR."],
            architecture_or_workflow_insights=["Deploy guardrails enable weekly shipping."],
            tradeoffs_or_disagreements=["Speed vs safety tension in small teams."],
            practical_takeaways=["Run blameless postmortems."],
            original_url="https://www.latent.space/p/railway",
        )
        row = AgentOutputRecord(
            id=1,
            email_id=9,
            kind=TECHNICAL_LONGFORM_OUTPUT_KIND,
            payload=longform.model_dump_json(),
            created_at="2026-06-12T00:00:00+00:00",
            content_unit_key="u0",
            category="TECHNOLOGY",
        )
        classifier = AgentOutputRecord(
            id=0,
            email_id=9,
            kind="classifier",
            payload='{"category":"TECHNOLOGY","confidence":1.0,"rationale":"r","primary_value":"v","evidence":[],"routing_source":"sender_profile","warnings":[]}',
            created_at="2026-06-12T00:00:00+00:00",
            content_unit_key="u0",
            category="TECHNOLOGY",
        )
        html = DigestComposer().compose([classifier, row], {9: "Railway interview"}).html
        assert html.count("Technical Index") == 1
        assert "Andon culture reduces MTTR" in html
        assert "Deploy guardrails" in html
        assert "Format: interview" in html
        assert html.count('<div class="item">') >= 1
    finally:
        repo.close()


def _latent_space_agent(
    *,
    repo: StateRepository,
    lock: RunLock,
    svc: FakeGmailService,
    llm: ScriptedLLMClient,
    technical_longform: TechnicalLongformProcessorAgent,
    boundary: BoundaryClassifierAgent | None = None,
    map_reduce: AINewsRadarMapReduceAgent | None = None,
    fetch_senders: tuple[str, ...] = ("swyx@substack.com",),
) -> DailyDigestAgent:
    client = GmailClient(service_factory=lambda: svc)
    return DailyDigestAgent(
        repo=repo,
        run_lock=lock,
        fetcher=GmailFetcher(client, senders=list(fetch_senders), max_results=20),
        router_agent=Mock(spec=RouterAgent),
        technology_agent=Mock(spec=TechnologyProcessorAgent),
        radar_agent=Mock(spec=RadarProcessorAgent),
        leadership_agent=Mock(spec=LeadershipProcessorAgent),
        courses_agent=Mock(spec=CoursesProcessorAgent),
        leadership_essay_agent=Mock(spec=LeadershipEssayProcessorAgent),
        technical_longform_agent=technical_longform,
        map_reduce_radar_agent=map_reduce,
        map_reduce_radar_senders=("swyx+ainews@substack.com",),
        content_unit_classifier_agent=ContentUnitClassifierAgent(llm, model="m"),
        boundary_classifier_agent=boundary or Mock(spec=BoundaryClassifierAgent),
        enable_content_unit_routing=True,
        composer=DigestComposer(title="Latent Space SP3"),
        quality_gate=DigestQualityGateAgent(),
        labeler=GmailLabeler(client),
        sender=GmailSender(client, sender="me@test"),
        digest_to="reader@test",
    )


def _run_profile_integration(
    tmp_path,
    *,
    msg_id: str,
    sender: str,
    sections: list[EmailSection],
    longform_output: TechnicalLongformOutput,
) -> tuple[StateRepository, Mock, Mock]:
    html = "<html><body>" + "".join(
        f"<h2>{section.heading}</h2><p>{section.text}</p>" if section.heading else f"<p>{section.text}</p>"
        for section in sections
    ) + "</body></html>"

    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    db_path = tmp_path / f"{msg_id}.sqlite"
    repo = StateRepository(db_path)
    repo.upsert_email(
        EmailInput(
            message_id=msg_id,
            subject=longform_output.title,
            sender=sender,
        ),
    )

    llm = ScriptedLLMClient([])
    longform_mock = Mock(spec=TechnicalLongformProcessorAgent)
    longform_mock.run_unit.return_value = longform_output
    boundary = Mock(spec=BoundaryClassifierAgent)

    agent = _latent_space_agent(
        repo=repo,
        lock=RunLock(db_path),
        svc=svc,
        llm=llm,
        technical_longform=longform_mock,
        boundary=boundary,
    )
    assert agent.run_daily() is True
    return repo, boundary, longform_mock


def test_interview_integration_one_technology_card_no_bc_or_classifier(tmp_path) -> None:
    output = TechnicalLongformOutput(
        title="How Railway Thinks About Platform Reliability",
        format="interview",
        central_topic="Reliability culture at Railway.",
        key_technical_insights=["Andon reduces MTTR."],
        architecture_or_workflow_insights=["Weekly deploy guardrails."],
        tradeoffs_or_disagreements=[],
        practical_takeaways=["Run blameless postmortems."],
        original_url=None,
    )
    repo, boundary, longform_mock = _run_profile_integration(
        tmp_path,
        msg_id="ls-interview",
        sender="swyx@substack.com",
        sections=railway_interview_sections(),
        longform_output=output,
    )
    try:
        boundary.classify_boundaries.assert_not_called()
        longform_mock.run_unit.assert_called_once()

        rows = repo.connection.execute(
            "SELECT kind, category, content_unit_key FROM agent_outputs ORDER BY id",
        ).fetchall()
        assert [(row["kind"], row["category"], row["content_unit_key"]) for row in rows] == [
            ("classifier", "TECHNOLOGY", "u0"),
            (TECHNICAL_LONGFORM_OUTPUT_KIND, "TECHNOLOGY", "u0"),
        ]
        assert repo.connection.execute(
            "SELECT 1 FROM agent_outputs WHERE kind = 'boundary_classifier'",
        ).fetchone() is None

        classifier_payload = json.loads(
            repo.connection.execute(
                "SELECT payload FROM agent_outputs WHERE kind = 'classifier'",
            ).fetchone()["payload"],
        )
        assert classifier_payload["routing_source"] == "sender_profile"
        assert repo.connection.execute("SELECT status FROM emails").fetchone()["status"] == "archived"
    finally:
        repo.close()


def test_essay_integration_one_technology_card(tmp_path) -> None:
    output = TechnicalLongformOutput(
        title="Why Small Models Win at the Edge",
        format="essay",
        central_topic="Edge inference favors small models.",
        key_technical_insights=["Quantization closes the accuracy gap."],
        architecture_or_workflow_insights=[],
        tradeoffs_or_disagreements=[],
        practical_takeaways=["Profile latency before picking model size."],
        original_url=None,
    )
    repo, _, longform_mock = _run_profile_integration(
        tmp_path,
        msg_id="ls-essay",
        sender="swyx@substack.com",
        sections=tech_essay_sections(),
        longform_output=output,
    )
    try:
        longform_mock.run_unit.assert_called_once()
        kinds = [
            row["kind"]
            for row in repo.connection.execute(
                "SELECT kind FROM agent_outputs ORDER BY id",
            ).fetchall()
        ]
        assert kinds == ["classifier", TECHNICAL_LONGFORM_OUTPUT_KIND]
    finally:
        repo.close()


def test_transcript_integration_still_one_processor_call(tmp_path) -> None:
    output = TechnicalLongformOutput(
        title="Multi-topic transcript",
        format="transcript",
        central_topic="Several AI infra topics in one conversation.",
        key_technical_insights=["Topic A insight.", "Topic B insight."],
        architecture_or_workflow_insights=["Shared pipeline patterns."],
        tradeoffs_or_disagreements=["Disagreement on eval harness design."],
        practical_takeaways=["Unify observability early."],
        original_url=None,
    )
    repo, _, longform_mock = _run_profile_integration(
        tmp_path,
        msg_id="ls-transcript",
        sender="swyx@substack.com",
        sections=multi_topic_transcript_sections(),
        longform_output=output,
    )
    try:
        assert longform_mock.run_unit.call_count == 1
        assert repo.connection.execute("SELECT COUNT(*) AS n FROM agent_outputs").fetchone()["n"] == 2
    finally:
        repo.close()


def test_ainews_sender_uses_map_reduce_not_sp3(tmp_path) -> None:
    sections = [
        EmailSection(section_id="s0", order_index=0, heading="Hero", text=_long(400)),
        EmailSection(section_id="s1", order_index=1, heading="Recap", text=_long(300)),
    ]
    html = "<html><body>" + "".join(
        f"<h2>{section.heading}</h2><p>{section.text}</p>" for section in sections
    ) + "</body></html>"

    msg_id = "ls-ainews-not-sp3"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    db_path = tmp_path / "ainews.sqlite"
    repo = StateRepository(db_path)
    repo.upsert_email(
        EmailInput(
            message_id=msg_id,
            subject="AINews issue",
            sender="swyx+ainews@substack.com",
        ),
    )

    llm = ScriptedLLMClient([])
    longform_mock = Mock(spec=TechnicalLongformProcessorAgent)
    map_reduce_mock = Mock(spec=AINewsRadarMapReduceAgent)
    from app.models.outputs import AINewsRadarDigestCard, AINewsRadarDigestOutput

    map_reduce_mock.run.return_value = AINewsRadarDigestOutput(
        cards=[
            AINewsRadarDigestCard(title="Hero story", tldr="Summary", key_points=["Point"]),
        ],
    )
    boundary = Mock(spec=BoundaryClassifierAgent)

    agent = _latent_space_agent(
        repo=repo,
        lock=RunLock(db_path),
        svc=svc,
        llm=llm,
        technical_longform=longform_mock,
        boundary=boundary,
        map_reduce=map_reduce_mock,
        fetch_senders=("swyx+ainews@substack.com",),
    )
    assert agent.run_daily() is True

    try:
        longform_mock.run_unit.assert_not_called()
        map_reduce_mock.run.assert_called_once()
        boundary.classify_boundaries.assert_not_called()

        row = repo.connection.execute(
            "SELECT kind FROM agent_outputs ORDER BY id",
        ).fetchone()
        assert row["kind"] == MAP_REDUCE_RADAR_DIGEST_KIND
    finally:
        repo.close()
