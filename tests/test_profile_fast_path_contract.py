"""Profile fast-path persistence, cache reuse, retry, and invalidation (SP1–SP3)."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

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
from app.models.content_units import ClassificationRoutingSource, ContentUnitClassificationResult
from app.models.email import EmailInput
from app.models.outputs import (
    LEADERSHIP_ESSAY_OUTPUT_KIND,
    TECHNICAL_LONGFORM_OUTPUT_KIND,
    LeadershipEssayOutput,
    TechnicalLongformOutput,
    TechnologySectionOutput,
)
from app.models.section import EmailSection
from app.parsing.interrupt_detection import detect_interrupt_roles
from app.parsing.section_caps import compute_section_content_hash
from app.processing.profile_executor import (
    compute_profile_merged_content_hash,
    group_profile_units,
    profile_processor_output_kind,
)
from app.processing.sender_profiles import SENDER_PROFILES, SenderProfile
from app.storage.repository import StateRepository
from app.storage.run_lock import RunLock
from tests.fakes import FakeGmailService
from tests.fakes.llm import ScriptedLLMClient
from tests.test_ale_sp2 import ale_essay_sections
from tests.test_bytebytego_sp1 import salesforce_163_sections
from tests.test_latent_space_sp3 import railway_interview_sections
from tests.test_step5_section_digest_integration import _message_full_html


def _long(n: int = 80) -> str:
    return ("word " * n).strip()


PROFILE_CASES: list[tuple[str, str, list[EmailSection], str, Any]] = [
    (
        "sp1_bytebytego",
        "bytebytego@substack.com",
        salesforce_163_sections(),
        "technology",
        TechnologySectionOutput(
            title="Salesforce systems",
            core_pain_point="Design lessons from long-lived platform architecture.",
            original_url=None,
            diagrams=[],
        ),
    ),
    (
        "sp2_ale",
        "alifeengineered@substack.com",
        ale_essay_sections(),
        LEADERSHIP_ESSAY_OUTPUT_KIND,
        LeadershipEssayOutput(
            title="The Leadership Gap",
            core_thesis="Managers must institutionalize feedback loops.",
            leadership_signals=["Weekly cadence matters."],
            author_action_items=["Schedule a weekly one-on-one."],
            senior_engineer_actions=["Reserve Friday office hours."],
            notable_examples=["Turnaround anecdote."],
            original_url=None,
        ),
    ),
    (
        "sp3_latent_space",
        "swyx@substack.com",
        railway_interview_sections(),
        TECHNICAL_LONGFORM_OUTPUT_KIND,
        TechnicalLongformOutput(
            title="Railway reliability",
            format="interview",
            central_topic="Platform reliability at Railway.",
            key_technical_insights=["Andon reduces MTTR."],
            architecture_or_workflow_insights=["Weekly deploy guardrails."],
            tradeoffs_or_disagreements=[],
            practical_takeaways=["Run blameless postmortems."],
            original_url=None,
        ),
    ),
]


def _sections_html(sections: list[EmailSection]) -> str:
    return "<html><body>" + "".join(
        f"<h2>{section.heading}</h2><p>{section.text}</p>" if section.heading else f"<p>{section.text}</p>"
        for section in sections
    ) + "</body></html>"


def _profile_agent(
    *,
    repo: StateRepository,
    lock: RunLock,
    svc: FakeGmailService,
    sender: str,
    technology: TechnologyProcessorAgent | Mock | None = None,
    leadership_essay: LeadershipEssayProcessorAgent | Mock | None = None,
    technical_longform: TechnicalLongformProcessorAgent | Mock | None = None,
) -> DailyDigestAgent:
    llm = ScriptedLLMClient([])
    client = GmailClient(service_factory=lambda: svc)
    return DailyDigestAgent(
        repo=repo,
        run_lock=lock,
        fetcher=GmailFetcher(client, senders=[sender], max_results=20),
        router_agent=Mock(spec=RouterAgent),
        technology_agent=technology or Mock(spec=TechnologyProcessorAgent),
        radar_agent=Mock(spec=RadarProcessorAgent),
        leadership_agent=Mock(spec=LeadershipProcessorAgent),
        courses_agent=Mock(spec=CoursesProcessorAgent),
        leadership_essay_agent=leadership_essay or Mock(spec=LeadershipEssayProcessorAgent),
        technical_longform_agent=technical_longform or Mock(spec=TechnicalLongformProcessorAgent),
        map_reduce_radar_senders=("swyx+ainews@substack.com",),
        content_unit_classifier_agent=ContentUnitClassifierAgent(llm, model="m"),
        boundary_classifier_agent=Mock(spec=BoundaryClassifierAgent),
        enable_content_unit_routing=True,
        composer=DigestComposer(title="Profile contract"),
        quality_gate=DigestQualityGateAgent(),
        labeler=GmailLabeler(client),
        sender=GmailSender(client, sender="me@test"),
        digest_to="reader@test",
    )


def _wire_processor_mock(
    profile: SenderProfile,
    output: Any,
) -> tuple[Mock | None, Mock | None, Mock | None]:
    technology = leadership_essay = technical_longform = None
    if profile.processor == "technology":
        technology = Mock(spec=TechnologyProcessorAgent)
        technology.run_section.return_value = output
    elif profile.processor == "leadership_essay":
        leadership_essay = Mock(spec=LeadershipEssayProcessorAgent)
        leadership_essay.run_unit.return_value = output
    elif profile.processor == "technical_longform":
        technical_longform = Mock(spec=TechnicalLongformProcessorAgent)
        technical_longform.run_unit.return_value = output
    else:
        raise AssertionError(f"unexpected processor: {profile.processor}")
    return technology, leadership_essay, technical_longform


def _run_profile_email(
    tmp_path,
    *,
    case_id: str,
    sender: str,
    sections: list[EmailSection],
    processor_output: Any,
) -> tuple[StateRepository, Mock | None, Mock | None, Mock | None, int]:
    msg_id = f"profile-{case_id}"
    html = _sections_html(sections)
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    db_path = tmp_path / f"{case_id}.sqlite"
    repo = StateRepository(db_path)
    email_id = repo.upsert_email(
        EmailInput(message_id=msg_id, subject=f"Subject {case_id}", sender=sender),
    )
    profile = SENDER_PROFILES[sender]
    technology, leadership_essay, technical_longform = _wire_processor_mock(profile, processor_output)
    agent = _profile_agent(
        repo=repo,
        lock=RunLock(db_path),
        svc=svc,
        sender=sender,
        technology=technology,
        leadership_essay=leadership_essay,
        technical_longform=technical_longform,
    )
    assert agent.run_daily() is True
    return repo, technology, leadership_essay, technical_longform, email_id


def _active_processor_mock(
    profile: SenderProfile,
    technology: Mock | None,
    leadership_essay: Mock | None,
    technical_longform: Mock | None,
) -> Mock:
    if profile.processor == "technology":
        assert technology is not None
        return technology
    if profile.processor == "leadership_essay":
        assert leadership_essay is not None
        return leadership_essay
    assert technical_longform is not None
    return technical_longform


def _classifier_payload(repo: StateRepository, email_id: int) -> ContentUnitClassificationResult:
    row = repo.connection.execute(
        "SELECT payload FROM agent_outputs WHERE email_id = ? AND kind = 'classifier'",
        (email_id,),
    ).fetchone()
    return ContentUnitClassificationResult.model_validate_json(row["payload"])


@pytest.mark.parametrize(
    ("case_id", "sender", "sections", "processor_kind", "processor_output"),
    PROFILE_CASES,
    ids=[case[0] for case in PROFILE_CASES],
)
def test_profile_persistence_contract(
    tmp_path,
    case_id: str,
    sender: str,
    sections: list[EmailSection],
    processor_kind: str,
    processor_output: Any,
) -> None:
    repo, _, _, _, email_id = _run_profile_email(
        tmp_path,
        case_id=case_id,
        sender=sender,
        sections=sections,
        processor_output=processor_output,
    )
    try:
        profile = SENDER_PROFILES[sender]
        classification = _classifier_payload(repo, email_id)

        assert classification.routing_source == ClassificationRoutingSource.SENDER_PROFILE
        assert classification.sender_profile == sender
        assert classification.grouping_strategy == profile.strategy.value
        assert classification.processor_kind == processor_kind
        assert classification.content_hash
        assert len(classification.content_hash) == 64

        rows = repo.connection.execute(
            """
            SELECT kind, category, content_unit_key FROM agent_outputs ORDER BY id
            """,
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["kind"] == "classifier"
        assert rows[0]["content_unit_key"] == "u0"
        assert rows[1]["kind"] == processor_kind
        assert rows[1]["content_unit_key"] == "u0"
        assert repo.connection.execute(
            "SELECT 1 FROM agent_outputs WHERE kind = 'boundary_classifier'",
        ).fetchone() is None
    finally:
        repo.close()


@pytest.mark.parametrize(
    ("case_id", "sender", "sections", "processor_kind", "processor_output"),
    PROFILE_CASES,
    ids=[f"cache_{case[0]}" for case in PROFILE_CASES],
)
def test_profile_cache_reuse_same_content_hash(
    tmp_path,
    case_id: str,
    sender: str,
    sections: list[EmailSection],
    processor_kind: str,
    processor_output: Any,
) -> None:
    repo, technology, leadership_essay, technical_longform, email_id = _run_profile_email(
        tmp_path,
        case_id=f"{case_id}-cache",
        sender=sender,
        sections=sections,
        processor_output=processor_output,
    )
    profile = SENDER_PROFILES[sender]
    proc_mock = _active_processor_mock(profile, technology, leadership_essay, technical_longform)
    try:
        first_count = (
            proc_mock.run_section.call_count
            if profile.processor == "technology"
            else proc_mock.run_unit.call_count
        )
        assert first_count == 1
        output_count_after_first = repo.connection.execute(
            "SELECT COUNT(*) AS n FROM agent_outputs WHERE email_id = ?",
            (email_id,),
        ).fetchone()["n"]
        assert output_count_after_first == 2

        repo.update_email_status(email_id, "pending")
        msg_id = repo.connection.execute(
            "SELECT message_id FROM emails WHERE id = ?",
            (email_id,),
        ).fetchone()["message_id"]
        svc = FakeGmailService(
            messages={msg_id: _message_full_html(msg_id, _sections_html(sections))},
        )
        agent = _profile_agent(
            repo=repo,
            lock=RunLock(tmp_path / f"{case_id}-cache.sqlite"),
            svc=svc,
            sender=sender,
            technology=technology,
            leadership_essay=leadership_essay,
            technical_longform=technical_longform,
        )
        assert agent.run_daily() is True

        second_count = (
            proc_mock.run_section.call_count
            if profile.processor == "technology"
            else proc_mock.run_unit.call_count
        )
        assert second_count == 1
        output_count_after_second = repo.connection.execute(
            "SELECT COUNT(*) AS n FROM agent_outputs WHERE email_id = ?",
            (email_id,),
        ).fetchone()["n"]
        assert output_count_after_second == 2
    finally:
        repo.close()


@pytest.mark.parametrize(
    ("case_id", "sender", "sections", "processor_kind", "processor_output"),
    PROFILE_CASES,
    ids=[f"invalidate_{case[0]}" for case in PROFILE_CASES],
)
def test_profile_article_change_invalidates_cache(
    tmp_path,
    case_id: str,
    sender: str,
    sections: list[EmailSection],
    processor_kind: str,
    processor_output: Any,
) -> None:
    repo, technology, leadership_essay, technical_longform, email_id = _run_profile_email(
        tmp_path,
        case_id=f"{case_id}-inv",
        sender=sender,
        sections=sections,
        processor_output=processor_output,
    )
    profile = SENDER_PROFILES[sender]
    proc_mock = _active_processor_mock(profile, technology, leadership_essay, technical_longform)
    try:
        old_hash = _classifier_payload(repo, email_id).content_hash

        changed = [EmailSection(**section.model_dump()) for section in sections]
        target_idx = 1 if len(changed) > 1 else 0
        changed[target_idx] = changed[target_idx].model_copy(
            update={"text": (changed[target_idx].text or "") + " REVISED ARTICLE BODY."},
        )

        repo.update_email_status(email_id, "pending")
        msg_id = repo.connection.execute(
            "SELECT message_id FROM emails WHERE id = ?",
            (email_id,),
        ).fetchone()["message_id"]
        svc = FakeGmailService(
            messages={msg_id: _message_full_html(msg_id, _sections_html(changed))},
        )
        agent = _profile_agent(
            repo=repo,
            lock=RunLock(tmp_path / f"{case_id}-inv.sqlite"),
            svc=svc,
            sender=sender,
            technology=technology,
            leadership_essay=leadership_essay,
            technical_longform=technical_longform,
        )
        assert agent.run_daily() is True

        second_count = (
            proc_mock.run_section.call_count
            if profile.processor == "technology"
            else proc_mock.run_unit.call_count
        )
        assert second_count == 2
        new_hash = _classifier_payload(repo, email_id).content_hash
        assert new_hash != old_hash
        assert repo.connection.execute(
            "SELECT COUNT(*) AS n FROM agent_outputs WHERE email_id = ? AND kind = ?",
            (email_id, processor_kind),
        ).fetchone()["n"] == 1
    finally:
        repo.close()


def test_strippable_interrupt_change_does_not_invalidate_article_hash() -> None:
    sections = ale_essay_sections()
    profile = SENDER_PROFILES["alifeengineered@substack.com"]
    roles = detect_interrupt_roles(sections)
    plan = group_profile_units(profile, sections, roles=roles)

    base_hashes = {
        section.section_id.strip(): f"hash-{section.section_id}"
        for section in sections
        if section.section_id.strip() in plan.article_unit.section_keys
    }
    base_hash = compute_profile_merged_content_hash(plan, section_hashes=base_hashes)

    changed_sponsor = [EmailSection(**section.model_dump()) for section in sections]
    changed_sponsor[2] = changed_sponsor[2].model_copy(update={"text": "Different sponsor copy entirely."})
    changed_roles = detect_interrupt_roles(changed_sponsor)
    changed_plan = group_profile_units(profile, changed_sponsor, roles=changed_roles)
    changed_hash = compute_profile_merged_content_hash(changed_plan, section_hashes=base_hashes)

    assert changed_plan.article_unit.section_keys == plan.article_unit.section_keys
    assert changed_hash == base_hash


@pytest.mark.parametrize(
    ("case_id", "sender", "sections", "processor_kind", "processor_output"),
    PROFILE_CASES,
    ids=[f"retry_{case[0]}" for case in PROFILE_CASES],
)
def test_profile_processor_failure_retries_same_path(
    tmp_path,
    case_id: str,
    sender: str,
    sections: list[EmailSection],
    processor_kind: str,
    processor_output: Any,
) -> None:
    msg_id = f"retry-{case_id}"
    html = _sections_html(sections)
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    db_path = tmp_path / f"retry-{case_id}.sqlite"
    repo = StateRepository(db_path)
    email_id = repo.upsert_email(
        EmailInput(message_id=msg_id, subject=f"Retry {case_id}", sender=sender),
    )
    profile = SENDER_PROFILES[sender]
    technology, leadership_essay, technical_longform = _wire_processor_mock(profile, processor_output)
    proc_mock = _active_processor_mock(profile, technology, leadership_essay, technical_longform)

    if profile.processor == "technology":
        proc_mock.run_section.side_effect = [RuntimeError("schema blowup"), processor_output]
    else:
        proc_mock.run_unit.side_effect = [RuntimeError("schema blowup"), processor_output]

    agent = _profile_agent(
        repo=repo,
        lock=RunLock(db_path),
        svc=svc,
        sender=sender,
        technology=technology,
        leadership_essay=leadership_essay,
        technical_longform=technical_longform,
    )
    try:
        assert agent.run_daily() is True
        assert repo.connection.execute("SELECT status FROM emails").fetchone()["status"] == "failed"
        assert repo.connection.execute(
            "SELECT COUNT(*) AS n FROM digest_emails WHERE email_id = ?",
            (email_id,),
        ).fetchone()["n"] == 0

        repo.update_email_status(email_id, "pending", error_message=None)
        assert agent.run_daily() is True
        assert repo.connection.execute("SELECT status FROM emails").fetchone()["status"] == "archived"

        second_count = (
            proc_mock.run_section.call_count
            if profile.processor == "technology"
            else proc_mock.run_unit.call_count
        )
        assert second_count == 2
        assert repo.connection.execute(
            "SELECT COUNT(*) AS n FROM agent_outputs WHERE email_id = ? AND kind = ?",
            (email_id, processor_kind),
        ).fetchone()["n"] == 1
        assert _classifier_payload(repo, email_id).routing_source == ClassificationRoutingSource.SENDER_PROFILE
        assert repo.connection.execute(
            "SELECT 1 FROM agent_outputs WHERE kind = 'boundary_classifier'",
        ).fetchone() is None
    finally:
        repo.close()


@pytest.mark.parametrize(
    ("case_id", "sender", "sections", "processor_kind", "processor_output"),
    PROFILE_CASES,
    ids=[f"archived_{case[0]}" for case in PROFILE_CASES],
)
def test_archived_email_not_reprocessed(
    tmp_path,
    case_id: str,
    sender: str,
    sections: list[EmailSection],
    processor_kind: str,
    processor_output: Any,
) -> None:
    repo, technology, leadership_essay, technical_longform, email_id = _run_profile_email(
        tmp_path,
        case_id=f"{case_id}-arch",
        sender=sender,
        sections=sections,
        processor_output=processor_output,
    )
    profile = SENDER_PROFILES[sender]
    proc_mock = _active_processor_mock(profile, technology, leadership_essay, technical_longform)
    try:
        assert repo.connection.execute("SELECT status FROM emails").fetchone()["status"] == "archived"
        pending = repo.fetch_unprocessed_emails()
        assert email_id not in {row.id for row in pending}

        first_count = (
            proc_mock.run_section.call_count
            if profile.processor == "technology"
            else proc_mock.run_unit.call_count
        )
        msg_id = repo.connection.execute(
            "SELECT message_id FROM emails WHERE id = ?",
            (email_id,),
        ).fetchone()["message_id"]
        svc = FakeGmailService(
            messages={msg_id: _message_full_html(msg_id, _sections_html(sections))},
        )
        agent = _profile_agent(
            repo=repo,
            lock=RunLock(tmp_path / f"{case_id}-arch.sqlite"),
            svc=svc,
            sender=sender,
            technology=technology,
            leadership_essay=leadership_essay,
            technical_longform=technical_longform,
        )
        assert agent.run_daily() is True
        second_count = (
            proc_mock.run_section.call_count
            if profile.processor == "technology"
            else proc_mock.run_unit.call_count
        )
        assert second_count == first_count
    finally:
        repo.close()


def test_swyx_plus_ainews_never_matches_swyx_profile() -> None:
    assert "swyx+ainews@substack.com" not in SENDER_PROFILES
    assert SENDER_PROFILES["swyx@substack.com"].processor == "technical_longform"


def test_unknown_interrupt_retained_in_merged_article() -> None:
    sections = [
        EmailSection(section_id="s0", order_index=0, heading="Topic", text=_long(300)),
        EmailSection(
            section_id="s1",
            order_index=1,
            heading="Side note",
            text="Mention register once in passing. " + _long(120),
        ),
    ]
    profile = SENDER_PROFILES["bytebytego@substack.com"]
    plan = group_profile_units(profile, sections, roles=detect_interrupt_roles(sections))
    assert plan.article_unit.section_keys == ["s0", "s1"]
    assert "register once" in plan.article_unit.unit_text


def test_try_reuse_profile_complete_outputs_repository(tmp_path) -> None:
    sender = "bytebytego@substack.com"
    sections = salesforce_163_sections()
    profile = SENDER_PROFILES[sender]
    repo = StateRepository(tmp_path / "reuse.sqlite")
    try:
        email_id = repo.upsert_email(EmailInput(message_id="reuse-bbg", sender=sender))
        repo.replace_email_sections(email_id, sections)
        roles = detect_interrupt_roles(sections)
        plan = group_profile_units(profile, sections, roles=roles)
        section_records = repo.list_email_sections(email_id)
        section_hashes = {rec.section_key: rec.content_hash for rec in section_records}
        merged_hash = compute_profile_merged_content_hash(plan, section_hashes=section_hashes)
        processor_kind = profile_processor_output_kind(profile)

        assert repo.try_reuse_profile_complete_outputs(email_id) is None

        classification = ContentUnitClassificationResult(
            category=profile.default_category,
            confidence=1.0,
            rationale="r",
            primary_value="v",
            routing_source=ClassificationRoutingSource.SENDER_PROFILE,
            sender_profile=sender,
            grouping_strategy=profile.strategy.value,
            content_hash=merged_hash,
            processor_kind=processor_kind,
        )
        repo.save_agent_output(
            email_id,
            "classifier",
            classification,
            content_unit_key="u0",
            category=profile.default_category.value,
        )
        assert repo.try_reuse_profile_complete_outputs(email_id) is None

        repo.save_agent_output(
            email_id,
            processor_kind,
            TechnologySectionOutput(
                title="T",
                core_pain_point="x",
                original_url=None,
                diagrams=[],
            ),
            content_unit_key="u0",
            category=profile.default_category.value,
        )
        assert repo.try_reuse_profile_complete_outputs(email_id) == frozenset({profile.default_category})
    finally:
        repo.close()


def _article_pair_without_and_with_sponsor() -> tuple[list[EmailSection], list[EmailSection]]:
    """Version A: two article sections. Version B: sponsor inserted, keys shifted."""

    intro = _long(350)
    intro_heading = "Opening"
    body_heading = "How Salesforce Thinks About Platform Reliability"
    body_text = _long(280)
    intro_links = ["https://bytebytego.com/articles/intro"]
    body_links = ["https://bytebytego.com/articles/main"]

    version_a = [
        EmailSection(
            section_id="s0",
            order_index=0,
            heading=intro_heading,
            text=intro,
            links=intro_links,
        ),
        EmailSection(
            section_id="s1",
            order_index=1,
            heading=body_heading,
            text=body_text,
            links=body_links,
        ),
    ]
    version_b = [
        EmailSection(
            section_id="s0",
            order_index=0,
            heading="WorkOS launches auth.md (Sponsored)",
            text=_long(90),
        ),
        EmailSection(
            section_id="s1",
            order_index=1,
            heading=intro_heading,
            text=intro,
            links=intro_links,
        ),
        EmailSection(
            section_id="s2",
            order_index=2,
            heading=body_heading,
            text=body_text,
            links=body_links,
        ),
    ]
    return version_a, version_b


def _section_hashes(sections: list[EmailSection]) -> dict[str, str]:
    return {section.section_id.strip(): compute_section_content_hash(section) for section in sections}


def test_merged_hash_stable_when_sponsor_insertion_shifts_section_keys() -> None:
    from app.parsing.interrupt_detection import is_strippable_interrupt

    version_a, version_b = _article_pair_without_and_with_sponsor()
    profile = SENDER_PROFILES["bytebytego@substack.com"]

    roles_a = detect_interrupt_roles(version_a)
    plan_a = group_profile_units(profile, version_a, roles=roles_a)
    roles_b = detect_interrupt_roles(version_b)
    plan_b = group_profile_units(profile, version_b, roles=roles_b)

    assert plan_a.article_unit.section_keys == ["s0", "s1"]
    assert plan_b.article_unit.section_keys == ["s1", "s2"]
    assert plan_b.hidden_section_keys == ("s0",)
    assert roles_b[0] is not None and is_strippable_interrupt(roles_b[0])

    assert plan_a.article_unit.unit_text == plan_b.article_unit.unit_text
    assert plan_a.article_unit.headings == plan_b.article_unit.headings
    assert plan_a.article_unit.links == plan_b.article_unit.links

    hash_a = compute_profile_merged_content_hash(plan_a, section_hashes=_section_hashes(version_a))
    hash_b = compute_profile_merged_content_hash(plan_b, section_hashes=_section_hashes(version_b))
    assert hash_a == hash_b


def test_merged_hash_changes_when_retained_article_sections_reordered() -> None:
    version_a, _ = _article_pair_without_and_with_sponsor()
    reordered = [
        version_a[1].model_copy(update={"section_id": "s0", "order_index": 0}),
        version_a[0].model_copy(update={"section_id": "s1", "order_index": 1}),
    ]
    profile = SENDER_PROFILES["bytebytego@substack.com"]
    plan_a = group_profile_units(profile, version_a, roles=detect_interrupt_roles(version_a))
    plan_reordered = group_profile_units(profile, reordered, roles=detect_interrupt_roles(reordered))

    hash_a = compute_profile_merged_content_hash(plan_a, section_hashes=_section_hashes(version_a))
    hash_reordered = compute_profile_merged_content_hash(
        plan_reordered,
        section_hashes=_section_hashes(reordered),
    )
    assert hash_a != hash_reordered


def _run_profile_with_sections(
    tmp_path,
    *,
    case_id: str,
    sections: list[EmailSection],
) -> tuple[StateRepository, Mock, int, str]:
    sender = "bytebytego@substack.com"
    processor_output = TechnologySectionOutput(
        title="Platform reliability",
        core_pain_point="Reliability patterns for long-lived systems.",
        original_url=None,
        diagrams=[],
    )
    msg_id = f"sponsor-shift-{case_id}"
    html = _sections_html(sections)
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    db_path = tmp_path / f"sponsor-shift-{case_id}.sqlite"
    repo = StateRepository(db_path)
    email_id = repo.upsert_email(
        EmailInput(message_id=msg_id, subject="Sponsor shift regression", sender=sender),
    )
    profile = SENDER_PROFILES[sender]
    technology, _, _ = _wire_processor_mock(profile, processor_output)
    proc_mock = _active_processor_mock(profile, technology, None, None)
    agent = _profile_agent(
        repo=repo,
        lock=RunLock(db_path),
        svc=svc,
        sender=sender,
        technology=technology,
    )
    assert agent.run_daily() is True
    return repo, proc_mock, email_id, msg_id


def test_profile_cache_reuse_when_sponsor_insertion_shifts_section_keys(tmp_path) -> None:
    version_a, version_b = _article_pair_without_and_with_sponsor()
    repo, proc_mock, email_id, msg_id = _run_profile_with_sections(
        tmp_path,
        case_id="a-then-b",
        sections=version_a,
    )
    try:
        assert proc_mock.run_section.call_count == 1
        first_hash = _classifier_payload(repo, email_id).content_hash

        repo.update_email_status(email_id, "pending")
        svc = FakeGmailService(
            messages={msg_id: _message_full_html(msg_id, _sections_html(version_b))},
        )
        agent = _profile_agent(
            repo=repo,
            lock=RunLock(tmp_path / "sponsor-shift-a-then-b.sqlite"),
            svc=svc,
            sender="bytebytego@substack.com",
            technology=proc_mock,
        )
        assert agent.run_daily() is True

        assert proc_mock.run_section.call_count == 1
        assert _classifier_payload(repo, email_id).content_hash == first_hash
        assert repo.connection.execute(
            "SELECT COUNT(*) AS n FROM agent_outputs WHERE email_id = ?",
            (email_id,),
        ).fetchone()["n"] == 2
    finally:
        repo.close()


def test_profile_cache_reuse_when_sponsor_removed_and_section_keys_shift(tmp_path) -> None:
    version_a, version_b = _article_pair_without_and_with_sponsor()
    repo, proc_mock, email_id, msg_id = _run_profile_with_sections(
        tmp_path,
        case_id="b-then-a",
        sections=version_b,
    )
    try:
        assert proc_mock.run_section.call_count == 1

        repo.update_email_status(email_id, "pending")
        svc = FakeGmailService(
            messages={msg_id: _message_full_html(msg_id, _sections_html(version_a))},
        )
        agent = _profile_agent(
            repo=repo,
            lock=RunLock(tmp_path / "sponsor-shift-b-then-a.sqlite"),
            svc=svc,
            sender="bytebytego@substack.com",
            technology=proc_mock,
        )
        assert agent.run_daily() is True

        assert proc_mock.run_section.call_count == 1
        assert repo.connection.execute(
            "SELECT COUNT(*) AS n FROM agent_outputs WHERE email_id = ? AND kind = 'technology'",
            (email_id,),
        ).fetchone()["n"] == 1
    finally:
        repo.close()
