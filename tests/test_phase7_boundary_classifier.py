"""Phase 7 boundary classifier tests.

Covers: ambiguity detection, boundary classifier trigger/skip, validation,
fallback paths, budget caps, canonical ContentUnit construction, and persistence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from app.agents.boundary_classifier_agent import BoundaryClassifierAgent
from app.agents.content_unit_classifier_agent import ContentUnitClassifierAgent
from app.agents.courses_agent import CoursesProcessorAgent
from app.agents.daily_digest_agent import DailyDigestAgent, _BOUNDARY_MAX_SECTIONS
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
from app.models.content_units import (
    BoundaryBudgetStatus,
    BoundaryLLMOutput,
    BoundaryLLMUnit,
    BoundaryOutlineSection,
    BoundaryUnitType,
    ContentUnit,
    GroupingAmbiguityReason,
)
from app.models.email import EmailInput
from app.models.outputs import TechnologySectionOutput
from app.models.section import EmailSection
from app.parsing.boundary_validation import (
    compute_composite_outline_hash,
    compute_outline_hash,
    validate_boundary_llm_output,
)
from app.agents.ainews_radar_map_reduce_agent import AINewsRadarMapReduceAgent
from app.parsing.content_unit_grouping import (
    assemble_final_groups,
    build_canonical_units,
    build_content_units_from_section_groups,
    conservative_groups_for_run,
    conservative_non_promo_groups,
    deterministic_units_for_run,
    group_content_units,
    is_promo_section,
    split_non_promo_runs,
    validate_groups_respect_hard_boundaries,
    validate_run_groups_coverage,
)
from app.storage.repository import StateRepository
from app.storage.run_lock import RunLock
from tests.fakes import FakeGmailService
from tests.fakes.llm import ScriptedLLMClient
from tests.test_step5_section_digest_integration import _message_full_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sec(sid: str, heading: str | None, text: str, *, links: list[str] | None = None) -> EmailSection:
    return EmailSection(
        section_id=sid,
        order_index=int(sid[1:]) if sid[1:].isdigit() else 0,
        heading=heading,
        text=text,
        links=links or [],
    )


def _long(n: int = 250) -> str:
    return ("word " * n).strip()


def _boundary_agent(*, responses: list[str]) -> BoundaryClassifierAgent:
    llm = ScriptedLLMClient(responses)
    return BoundaryClassifierAgent(llm, model="m")


def _phase7_agent(
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
        fetcher=GmailFetcher(client, senders=["newsletter@fixture.test"], max_results=20),
        router_agent=Mock(spec=RouterAgent),
        technology_agent=technology,
        radar_agent=Mock(spec=RadarProcessorAgent),
        leadership_agent=Mock(spec=LeadershipProcessorAgent),
        courses_agent=Mock(spec=CoursesProcessorAgent),
        map_reduce_radar_senders=(),
        content_unit_classifier_agent=ContentUnitClassifierAgent(llm, model="m"),
        boundary_classifier_agent=boundary,
        enable_content_unit_routing=True,
        composer=DigestComposer(title="Phase 7 test"),
        quality_gate=DigestQualityGateAgent(),
        labeler=GmailLabeler(client),
        sender=GmailSender(client, sender="me@test"),
        digest_to="reader@test",
    )


# ---------------------------------------------------------------------------
# 1. group_content_units returns GroupingResult with ambiguous flag
# ---------------------------------------------------------------------------


def test_ambiguous_every_like_email_sets_ambiguous_true() -> None:
    """4 mixed-heading non-promo sections, total < 1800 chars → ambiguous=True.

    Keeping total chars below the long-form threshold (1800) ensures
    _looks_like_single_long_form() returns False and the ambiguity check fires.
    """
    # _long(60) = 300 chars each → total 1200 < 1800 threshold
    sections = [
        _sec("s0", "Welcome", _long(60)),
        _sec("s1", "The AI Stack in 2026", _long(60)),
        _sec("s2", "Leadership Notes", _long(60)),
        _sec("s3", "Quick Hits", _long(60)),
    ]
    result = group_content_units(sections)
    assert result.ambiguous is True
    assert result.non_promo_section_count == 4
    assert GroupingAmbiguityReason.SECTION_COUNT_GRAY_ZONE in result.ambiguity_reasons


def test_clear_numbered_article_does_not_set_ambiguous() -> None:
    """Numbered-chapter headings (≥ 2) → unambiguous merge."""
    sections = [
        _sec("s0", "1. Introduction", _long(200)),
        _sec("s1", "2. The Problem", _long(250)),
        _sec("s2", "3. Solution", _long(300)),
        _sec("s3", "4. Conclusion", _long(150)),
    ]
    result = group_content_units(sections)
    assert result.ambiguous is False


def test_single_section_is_never_ambiguous() -> None:
    sections = [_sec("s0", "The Essay", _long(400))]
    result = group_content_units(sections)
    assert result.ambiguous is False


def test_high_confidence_long_form_is_not_ambiguous() -> None:
    """≤ 8 sections, ≥ 1800 chars, ≤ 1 primary URL → long-form confidence, not ambiguous."""
    sections = [
        _sec("s0", "Part One", _long(400), links=["https://essay.example/deep-dive"]),
        _sec("s1", "Part Two", _long(400), links=["https://essay.example/deep-dive"]),
        _sec("s2", "Part Three", _long(400), links=["https://essay.example/deep-dive"]),
    ]
    result = group_content_units(sections)
    assert result.ambiguous is False


def test_clear_multi_url_aggregator_is_not_ambiguous() -> None:
    """≥ 3 distinct primary URLs → deterministic split, not ambiguous."""
    sections = [
        _sec("s0", "Story 1", _long(80), links=["https://source1.com/a"]),
        _sec("s1", "Story 2", _long(80), links=["https://source2.com/b"]),
        _sec("s2", "Story 3", _long(80), links=["https://source3.com/c"]),
        _sec("s3", "Story 4", _long(80), links=["https://source4.com/d"]),
    ]
    result = group_content_units(sections)
    assert result.ambiguous is False


# ---------------------------------------------------------------------------
# 2. conservative_units = max split
# ---------------------------------------------------------------------------


def test_conservative_units_max_split() -> None:
    sections = [
        _sec("s0", "Intro", _long(150)),
        _sec("s1", "Deep Dive", _long(200)),
        _sec("s2", "Workshop", "Register RSVP for the webinar cohort bootcamp."),
        _sec("s3", "Outro", _long(120)),
    ]
    result = group_content_units(sections)
    # conservative_units: every section its own unit
    assert len(result.conservative_units) == 4
    assert result.conservative_units[0].section_keys == ["s0"]
    assert result.conservative_units[1].section_keys == ["s1"]
    assert result.conservative_units[2].section_keys == ["s2"]
    assert result.conservative_units[3].section_keys == ["s3"]
    # u0/u1/u2/u3 keys assigned in order
    assert [u.content_unit_key for u in result.conservative_units] == ["u0", "u1", "u2", "u3"]


# ---------------------------------------------------------------------------
# 3. validate_boundary_llm_output
# ---------------------------------------------------------------------------


def _make_llm_output(units_data: list[tuple[str, list[str]]], confidence: float = 0.9) -> BoundaryLLMOutput:
    units = [
        BoundaryLLMUnit(
            unit_title=title,
            section_keys=keys,
            unit_type=BoundaryUnitType.STANDALONE,
            reason="test",
        )
        for title, keys in units_data
    ]
    return BoundaryLLMOutput(units=units, confidence=confidence)


def _validate_run(
    llm: BoundaryLLMOutput,
    run_keys: list[str],
    all_sections: list[EmailSection],
) -> list[str]:
    return validate_boundary_llm_output(
        llm,
        run_section_keys=run_keys,
        all_sections=all_sections,
    )


def test_validate_valid_output_returns_no_errors() -> None:
    sections = [_sec("s0", "A", "a"), _sec("s1", "B", "b"), _sec("s2", "C", "c")]
    llm = _make_llm_output([("Unit A", ["s0", "s1"]), ("Unit B", ["s2"])])
    assert _validate_run(llm, ["s0", "s1", "s2"], sections) == []


def test_validate_invented_section_key_returns_error() -> None:
    sections = [_sec("s0", "A", "a"), _sec("s1", "B", "b"), _sec("s2", "C", "c")]
    llm = _make_llm_output([("Unit A", ["s0", "s_invented"]), ("Unit B", ["s2"])])
    errors = _validate_run(llm, ["s0", "s1", "s2"], sections)
    assert any("invented_section_key" in e for e in errors)


def test_validate_missing_section_key_returns_error() -> None:
    sections = [_sec("s0", "A", "a"), _sec("s1", "B", "b"), _sec("s2", "C", "c")]
    llm = _make_llm_output([("Unit A", ["s0"]), ("Unit B", ["s2"])])
    errors = _validate_run(llm, ["s0", "s1", "s2"], sections)
    assert any("missing_section_key" in e and "s1" in e for e in errors)


def test_validate_duplicate_section_key_returns_error() -> None:
    sections = [_sec("s0", "A", "a"), _sec("s1", "B", "b"), _sec("s2", "C", "c")]
    llm = _make_llm_output([("Unit A", ["s0", "s1"]), ("Unit B", ["s1", "s2"])])
    errors = _validate_run(llm, ["s0", "s1", "s2"], sections)
    assert any("duplicate_section_key" in e for e in errors)


def test_validate_non_contiguous_section_keys_returns_error() -> None:
    sections = [_sec("s0", "A", "a"), _sec("s1", "B", "b"), _sec("s2", "C", "c")]
    llm = _make_llm_output([("Unit A", ["s0", "s2"]), ("Unit B", ["s1"])])
    errors = _validate_run(llm, ["s0", "s1", "s2"], sections)
    assert any("non_contiguous" in e for e in errors)


def test_validate_overlapping_units_returns_error() -> None:
    sections = [_sec("s0", "A", "a"), _sec("s1", "B", "b"), _sec("s2", "C", "c")]
    llm = _make_llm_output([("Unit A", ["s0", "s1"]), ("Unit B", ["s1", "s2"])])
    errors = _validate_run(llm, ["s0", "s1", "s2"], sections)
    assert errors


def test_validate_rejects_merge_across_promo_hard_boundary() -> None:
    """P0: s0 essay, s1 promo, s2 other — LLM [s0,s2] must be rejected."""
    promo_text = "Register RSVP webinar cohort bootcamp sponsor"
    sections = [
        _sec("s0", "Essay", _long(60)),
        _sec("s1", "Sponsor", promo_text),
        _sec("s2", "Other", _long(60)),
    ]
    llm = _make_llm_output([("Bad merge", ["s0", "s2"])])
    errors = _validate_run(llm, ["s0", "s2"], sections)
    assert any("spans_hard_boundary" in e or "non_contiguous" in e for e in errors)


def test_split_non_promo_runs_separates_promo() -> None:
    promo_text = "Register RSVP webinar cohort bootcamp sponsor"
    sections = [
        _sec("s0", "Essay", "a"),
        _sec("s1", "Sponsor", promo_text),
        _sec("s2", "Other", "b"),
        _sec("s3", "More", "c"),
    ]
    runs = split_non_promo_runs(sections)
    assert [[s.section_id for s in r] for r in runs] == [["s0"], ["s2", "s3"]]


def test_validate_groups_respect_hard_boundaries_rejects_cross_promo_group() -> None:
    promo_text = "Register RSVP webinar cohort bootcamp sponsor"
    s0 = _sec("s0", "Essay", "a")
    s1 = _sec("s1", "Sponsor", promo_text)
    s2 = _sec("s2", "Other", "b")
    errors = validate_groups_respect_hard_boundaries([[s0, s2]], [s0, s1, s2])
    assert any("spans_hard_boundary" in e or "non_contiguous_group" in e for e in errors)


def test_assemble_final_groups_rejects_cross_promo_groups() -> None:
    promo_text = "Register RSVP webinar cohort bootcamp sponsor"
    s0 = _sec("s0", "Essay", "a")
    s1 = _sec("s1", "Sponsor", promo_text)
    s2 = _sec("s2", "Other", "b")
    with pytest.raises(ValueError, match="assemble_final_groups"):
        assemble_final_groups([s0, s1, s2], [[s0, s2]])


# ---------------------------------------------------------------------------
# 4. build_content_units_from_section_groups — shared builder
# ---------------------------------------------------------------------------


def test_shared_builder_assigns_u0_u1_keys() -> None:
    s0 = _sec("s0", "Intro", "intro text")
    s1 = _sec("s1", "Deep Dive", "deep text")
    s2 = _sec("s2", "Outro", "outro text")
    groups = [[s0, s1], [s2]]
    units = build_content_units_from_section_groups(groups)
    assert [u.content_unit_key for u in units] == ["u0", "u1"]
    assert units[0].section_keys == ["s0", "s1"]
    assert units[0].unit_text == "intro text\n\ndeep text"
    assert units[1].section_keys == ["s2"]


def test_shared_builder_deduplicates_links() -> None:
    s0 = _sec("s0", "A", "text", links=["https://x.com/a", "https://x.com/b"])
    s1 = _sec("s1", "B", "text2", links=["https://x.com/b", "https://x.com/c"])
    units = build_content_units_from_section_groups([[s0, s1]])
    assert units[0].links == ["https://x.com/a", "https://x.com/b", "https://x.com/c"]


# ---------------------------------------------------------------------------
# 5. assemble_final_groups — promo interleaving
# ---------------------------------------------------------------------------


def test_assemble_final_groups_interleaves_promo() -> None:
    s0 = _sec("s0", "Intro", _long(150))
    s1 = _sec("s1", "Deep Dive", _long(200))
    promo = _sec("s2", "Workshop", "Register RSVP for the webinar cohort bootcamp.")
    s3 = _sec("s3", "Outro", _long(120))

    # Boundary classifier says s0+s1 are one unit, s3 is its own
    non_promo_groups = [[s0, s1], [s3]]
    all_groups = assemble_final_groups([s0, s1, promo, s3], non_promo_groups)
    assert len(all_groups) == 3
    assert all_groups[0] == [s0, s1]
    assert all_groups[1] == [promo]
    assert all_groups[2] == [s3]


# ---------------------------------------------------------------------------
# 6. _run_boundary_classifier via full integration (mocked boundary agent)
# ---------------------------------------------------------------------------


def test_boundary_classifier_triggered_for_ambiguous_email(tmp_path) -> None:
    """Ambiguous email → boundary agent called; result persisted as boundary_classifier kind."""
    # _long(60) = 300 chars each → 4 sections, total 1200 < 1800 → ambiguous=True
    html = (
        "<html><body>"
        "<h2>The AI Stack in 2026</h2><p>" + (_long(60)) + "</p>"
        "<h2>Leadership Notes</h2><p>" + (_long(60)) + "</p>"
        "<h2>Quick Hits</h2><p>" + (_long(60)) + "</p>"
        "<h2>Research Roundup</h2><p>" + (_long(60)) + "</p>"
        "</body></html>"
    )
    msg_id = "p7-ambiguous"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Mixed Issue", sender="newsletter@fixture.test"))

    # Category classifier LLM: one call per unit (4 sections → ambiguous, boundary agent
    # merges s0+s1, keeps s2 and s3 → 3 units)
    category_responses = [
        '{"category":"TECHNOLOGY","confidence":0.9,"rationale":"r","primary_value":"v","evidence":[]}',
        '{"category":"LEADERSHIP","confidence":0.85,"rationale":"r","primary_value":"v","evidence":[]}',
        '{"category":"RADAR","confidence":0.85,"rationale":"r","primary_value":"v","evidence":[]}',
    ]
    llm = ScriptedLLMClient(category_responses)

    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="T", core_pain_point="p", original_url=None, diagrams=[]
    )

    boundary_mock = Mock(spec=BoundaryClassifierAgent)
    boundary_mock.classify_boundaries.return_value = BoundaryLLMOutput(
        units=[
            BoundaryLLMUnit(unit_title="AI Stack + Leadership", section_keys=["s0", "s1"],
                            unit_type=BoundaryUnitType.LONG_FORM, reason="cohesive"),
            BoundaryLLMUnit(unit_title="Quick Hits", section_keys=["s2"],
                            unit_type=BoundaryUnitType.STANDALONE, reason="independent"),
            BoundaryLLMUnit(unit_title="Research Roundup", section_keys=["s3"],
                            unit_type=BoundaryUnitType.LINK_ROUNDUP, reason="roundup"),
        ],
        confidence=0.88,
        warnings=[],
    )

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=boundary_mock,
    )
    agent.run_daily()

    boundary_mock.classify_boundaries.assert_called_once()

    row = repo.connection.execute(
        "SELECT kind, payload FROM agent_outputs WHERE kind = 'boundary_classifier'"
    ).fetchone()
    assert row is not None
    import json
    payload = json.loads(row["payload"])
    assert payload["fallback_used"] is False
    assert payload["confidence"] == pytest.approx(0.88)


def test_non_ambiguous_email_does_not_trigger_boundary_classifier(tmp_path) -> None:
    """Numbered-chapter article → boundary agent NOT called."""
    html = (
        "<html><body>"
        "<h2>1. Introduction</h2><p>" + (_long(250)) + "</p>"
        "<h2>2. The Problem</h2><p>" + (_long(300)) + "</p>"
        "<h2>3. Solution</h2><p>" + (_long(280)) + "</p>"
        "</body></html>"
    )
    msg_id = "p7-chapter"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7c.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Chapter Article", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient([
        '{"category":"TECHNOLOGY","confidence":0.9,"rationale":"r","primary_value":"v","evidence":[]}'
    ])
    boundary_mock = Mock(spec=BoundaryClassifierAgent)

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7c.sqlite"),
        svc=svc,
        llm=llm,
        technology=Mock(spec=TechnologyProcessorAgent),
        boundary=boundary_mock,
    )
    agent.run_daily()

    boundary_mock.classify_boundaries.assert_not_called()


# ---------------------------------------------------------------------------
# 7. LLM invented / missing / duplicate / non-contiguous → fallback
# ---------------------------------------------------------------------------


def _run_boundary_classifier_direct(
    tmp_path,
    *,
    html: str,
    boundary_response: BoundaryLLMOutput,
    category_responses: list[str],
) -> dict:
    """Helper: run an ambiguous email through the pipeline and return agent_outputs rows."""
    msg_id = "p7-direct"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7d.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Mixed", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient(category_responses)
    boundary_mock = Mock(spec=BoundaryClassifierAgent)
    boundary_mock.classify_boundaries.return_value = boundary_response

    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="T", core_pain_point="p", original_url=None, diagrams=[]
    )

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7d.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=boundary_mock,
    )
    agent.run_daily()

    import json
    rows = repo.connection.execute(
        "SELECT kind, payload FROM agent_outputs"
    ).fetchall()
    return {r["kind"]: json.loads(r["payload"]) for r in rows if r["kind"] == "boundary_classifier"}


def _ambiguous_html() -> str:
    # _long(60) = 300 chars each → total ~1200 chars < 1800 long-form threshold
    # 4 non-promo sections in gray zone (3–8) → ambiguous=True
    return (
        "<html><body>"
        "<h2>Topic A</h2><p>" + _long(60) + "</p>"
        "<h2>Topic B</h2><p>" + _long(60) + "</p>"
        "<h2>Topic C</h2><p>" + _long(60) + "</p>"
        "<h2>Topic D</h2><p>" + _long(60) + "</p>"
        "</body></html>"
    )


def _cat_responses(n: int) -> list[str]:
    return [
        '{"category":"TECHNOLOGY","confidence":0.9,"rationale":"r","primary_value":"v","evidence":[]}'
        for _ in range(n)
    ]


def test_llm_invented_section_key_triggers_fallback(tmp_path) -> None:
    bad_response = BoundaryLLMOutput(
        units=[
            BoundaryLLMUnit(unit_title="A", section_keys=["s0", "s_invented"],
                            unit_type=BoundaryUnitType.STANDALONE, reason="r"),
            BoundaryLLMUnit(unit_title="B", section_keys=["s2", "s3"],
                            unit_type=BoundaryUnitType.STANDALONE, reason="r"),
        ],
        confidence=0.85,
    )
    rows = _run_boundary_classifier_direct(
        tmp_path,
        html=_ambiguous_html(),
        boundary_response=bad_response,
        category_responses=_cat_responses(4),  # conservative = 4 units
    )
    bc = rows.get("boundary_classifier", {})
    assert bc.get("fallback_used") is True
    assert bc.get("fallback_reason") == "validation_failed"
    assert any("invented_section_key" in e for e in bc.get("validation_errors", []))


def test_llm_missing_section_triggers_fallback(tmp_path) -> None:
    # Only covers s0, s2, s3 — missing s1
    bad_response = BoundaryLLMOutput(
        units=[
            BoundaryLLMUnit(unit_title="A", section_keys=["s0"],
                            unit_type=BoundaryUnitType.STANDALONE, reason="r"),
            BoundaryLLMUnit(unit_title="B", section_keys=["s2", "s3"],
                            unit_type=BoundaryUnitType.STANDALONE, reason="r"),
        ],
        confidence=0.85,
    )
    rows = _run_boundary_classifier_direct(
        tmp_path,
        html=_ambiguous_html(),
        boundary_response=bad_response,
        category_responses=_cat_responses(4),
    )
    bc = rows.get("boundary_classifier", {})
    assert bc.get("fallback_used") is True
    assert any("missing_section_key" in e for e in bc.get("validation_errors", []))


def test_llm_duplicate_section_triggers_fallback(tmp_path) -> None:
    bad_response = BoundaryLLMOutput(
        units=[
            BoundaryLLMUnit(unit_title="A", section_keys=["s0", "s1"],
                            unit_type=BoundaryUnitType.STANDALONE, reason="r"),
            BoundaryLLMUnit(unit_title="B", section_keys=["s1", "s2", "s3"],
                            unit_type=BoundaryUnitType.STANDALONE, reason="r"),
        ],
        confidence=0.85,
    )
    rows = _run_boundary_classifier_direct(
        tmp_path,
        html=_ambiguous_html(),
        boundary_response=bad_response,
        category_responses=_cat_responses(4),
    )
    bc = rows.get("boundary_classifier", {})
    assert bc.get("fallback_used") is True


def test_llm_non_contiguous_section_keys_triggers_fallback(tmp_path) -> None:
    # s0 and s2 skip s1
    bad_response = BoundaryLLMOutput(
        units=[
            BoundaryLLMUnit(unit_title="A", section_keys=["s0", "s2"],
                            unit_type=BoundaryUnitType.STANDALONE, reason="r"),
            BoundaryLLMUnit(unit_title="B", section_keys=["s1", "s3"],
                            unit_type=BoundaryUnitType.STANDALONE, reason="r"),
        ],
        confidence=0.85,
    )
    rows = _run_boundary_classifier_direct(
        tmp_path,
        html=_ambiguous_html(),
        boundary_response=bad_response,
        category_responses=_cat_responses(4),
    )
    bc = rows.get("boundary_classifier", {})
    assert bc.get("fallback_used") is True
    assert any("non_contiguous" in e for e in bc.get("validation_errors", []))


# ---------------------------------------------------------------------------
# 8. LLM call exception → fallback
# ---------------------------------------------------------------------------


def test_llm_exception_triggers_fallback_and_email_continues(tmp_path) -> None:
    msg_id = "p7-exc"
    html = _ambiguous_html()
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7e.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Mixed", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient(_cat_responses(4))
    boundary_mock = Mock(spec=BoundaryClassifierAgent)
    boundary_mock.classify_boundaries.side_effect = RuntimeError("network timeout")

    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="T", core_pain_point="p", original_url=None, diagrams=[]
    )

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7e.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=boundary_mock,
    )
    result = agent.run_daily()
    assert result is True  # email must not fail due to boundary classifier error

    import json
    row = repo.connection.execute(
        "SELECT payload FROM agent_outputs WHERE kind = 'boundary_classifier'"
    ).fetchone()
    assert row is not None
    payload = json.loads(row["payload"])
    assert payload["fallback_used"] is True
    assert payload["fallback_reason"] == "llm_error"
    assert any("network timeout" in e for e in payload["validation_errors"])


# ---------------------------------------------------------------------------
# 9. Budget cap — section count exceeded → LLM not called
# ---------------------------------------------------------------------------


def test_budget_cap_section_count_skips_llm(tmp_path, monkeypatch) -> None:
    """When non-promo section count exceeds cap, LLM is not called and conservative split is used.

    We patch ``_BOUNDARY_MAX_SECTIONS`` to 2 so a 4-section ambiguous email exceeds the cap.
    The default cap (12) can never be exceeded under current ambiguity rules (max 8 sections),
    but the cap serves as a future-proofing backstop; monkeypatching lets us unit-test the path.
    """
    import app.agents.daily_digest_agent as dda_module
    monkeypatch.setattr(dda_module, "_BOUNDARY_MAX_SECTIONS", 2)

    html = _ambiguous_html()  # 4 non-promo sections → exceeds cap of 2
    msg_id = "p7-budget"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7b.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Large Issue", sender="newsletter@fixture.test"))

    # conservative split = 4 units → 4 category classifier calls
    llm = ScriptedLLMClient(_cat_responses(4))
    boundary_mock = Mock(spec=BoundaryClassifierAgent)
    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="T", core_pain_point="p", original_url=None, diagrams=[]
    )

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7b.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=boundary_mock,
    )
    agent.run_daily()

    boundary_mock.classify_boundaries.assert_not_called()

    import json
    row = repo.connection.execute(
        "SELECT payload FROM agent_outputs WHERE kind = 'boundary_classifier'"
    ).fetchone()
    assert row is not None
    payload = json.loads(row["payload"])
    assert payload["budget_status"] == BoundaryBudgetStatus.SECTION_COUNT_EXCEEDED


# ---------------------------------------------------------------------------
# 10. Low confidence → fallback
# ---------------------------------------------------------------------------


def test_low_confidence_boundary_output_triggers_fallback(tmp_path) -> None:
    msg_id = "p7-lowconf"
    html = _ambiguous_html()
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7lc.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Mixed", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient(_cat_responses(4))  # conservative = 4 units
    boundary_mock = Mock(spec=BoundaryClassifierAgent)
    boundary_mock.classify_boundaries.return_value = BoundaryLLMOutput(
        units=[
            BoundaryLLMUnit(unit_title="All", section_keys=["s0", "s1", "s2", "s3"],
                            unit_type=BoundaryUnitType.MIXED, reason="unclear"),
        ],
        confidence=0.6,  # below 0.75 threshold
    )

    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="T", core_pain_point="p", original_url=None, diagrams=[]
    )

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7lc.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=boundary_mock,
    )
    agent.run_daily()

    import json
    row = repo.connection.execute(
        "SELECT payload FROM agent_outputs WHERE kind = 'boundary_classifier'"
    ).fetchone()
    assert row is not None
    payload = json.loads(row["payload"])
    assert payload["fallback_used"] is True
    assert payload["fallback_reason"] == "low_confidence"


# ---------------------------------------------------------------------------
# 11. Accepted LLM result → canonical u0/u1 ContentUnit keys via shared builder
# ---------------------------------------------------------------------------


def test_accepted_result_uses_shared_builder_for_canonical_keys() -> None:
    s0 = _sec("s0", "Intro", "intro " * 100)
    s1 = _sec("s1", "Deep Dive", "deep " * 120)
    s2 = _sec("s2", "Promo", "Register RSVP for the webinar cohort bootcamp.")
    s3 = _sec("s3", "Outro", "outro " * 80)

    # Simulate boundary classifier grouping s0+s1 as one unit
    non_promo_groups = [[s0, s1], [s3]]
    all_groups = assemble_final_groups([s0, s1, s2, s3], non_promo_groups)
    units = build_content_units_from_section_groups(all_groups)

    assert [u.content_unit_key for u in units] == ["u0", "u1", "u2"]
    assert units[0].section_keys == ["s0", "s1"]
    assert units[1].section_keys == ["s2"]  # promo interleaved
    assert units[2].section_keys == ["s3"]
    assert "intro" in units[0].unit_text
    assert "deep" in units[0].unit_text


def test_conservative_fallback_uses_same_builder_as_accepted_path() -> None:
    """Both paths produce u0/u1/… keys via build_content_units_from_section_groups."""
    sections = [
        _sec("s0", "A", _long(100)),
        _sec("s1", "B", _long(120)),
        _sec("s2", "C", _long(90)),
    ]
    grouping = group_content_units(sections)

    # Conservative: each section its own group
    conservative_groups = [[s] for s in sections]
    conservative_units = build_content_units_from_section_groups(conservative_groups)

    assert conservative_units == grouping.conservative_units
    assert [u.content_unit_key for u in conservative_units] == ["u0", "u1", "u2"]


# ---------------------------------------------------------------------------
# 12. P0 hard-boundary: per-run scope, promo separate, cross-promo reject
# ---------------------------------------------------------------------------


def test_boundary_classifier_called_per_multi_section_run_not_across_promo(tmp_path) -> None:
    """Runs [s0], [s2,s3,s4] — LLM called once for the multi-section run only."""
    html = (
        "<html><body>"
        "<h2>Essay Intro</h2><p>" + _long(55) + "</p>"
        "<h2>Sponsor</h2><p>Register RSVP for the webinar cohort bootcamp early bird.</p>"
        "<h2>Section A</h2><p>" + _long(55) + "</p>"
        "<h2>Section B</h2><p>" + _long(55) + "</p>"
        "<h2>Section C</h2><p>" + _long(55) + "</p>"
        "</body></html>"
    )
    msg_id = "p7-per-run"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7pr.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Mixed", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient(_cat_responses(5))
    boundary_mock = Mock(spec=BoundaryClassifierAgent)
    boundary_mock.classify_boundaries.return_value = BoundaryLLMOutput(
        units=[
            BoundaryLLMUnit(unit_title="Tail", section_keys=["s2", "s3", "s4"],
                            unit_type=BoundaryUnitType.LONG_FORM, reason="r"),
        ],
        confidence=0.9,
    )

    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="T", core_pain_point="p", original_url=None, diagrams=[]
    )

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7pr.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=boundary_mock,
    )
    agent.run_daily()

    assert boundary_mock.classify_boundaries.call_count == 1
    sent_keys = [s.section_key for s in boundary_mock.classify_boundaries.call_args.kwargs["sections"]]
    assert sent_keys == ["s2", "s3", "s4"]
    assert "s0" not in sent_keys
    assert "s1" not in sent_keys


def test_cross_promo_llm_merge_falls_back_per_run(tmp_path) -> None:
    """LLM tries [s0,s2] for run [s2,s3] path — rejected; promo stays separate."""
    html = (
        "<html><body>"
        "<h2>Essay</h2><p>" + _long(55) + "</p>"
        "<h2>Sponsor</h2><p>Register RSVP for the webinar cohort bootcamp early bird.</p>"
        "<h2>Topic A</h2><p>" + _long(55) + "</p>"
        "<h2>Topic B</h2><p>" + _long(55) + "</p>"
        "<h2>Topic C</h2><p>" + _long(55) + "</p>"
        "</body></html>"
    )
    msg_id = "p7-cross-promo"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7cp.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Mixed", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient(_cat_responses(5))
    boundary_mock = Mock(spec=BoundaryClassifierAgent)
    # Invalid: tries to pull s0 into run [s2,s3,s4]
    boundary_mock.classify_boundaries.return_value = BoundaryLLMOutput(
        units=[
            BoundaryLLMUnit(unit_title="Bad", section_keys=["s0", "s2", "s3", "s4"],
                            unit_type=BoundaryUnitType.MIXED, reason="bad"),
        ],
        confidence=0.9,
    )

    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="T", core_pain_point="p", original_url=None, diagrams=[]
    )

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7cp.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=boundary_mock,
    )
    agent.run_daily()

    import json
    row = repo.connection.execute(
        "SELECT payload FROM agent_outputs WHERE kind = 'boundary_classifier'",
    ).fetchone()
    assert row is not None
    payload = json.loads(row["payload"])
    assert payload["fallback_used"] is True
    assert payload["fallback_reason"] == "validation_failed"

    # Promo s1 remains its own unit; s0 singleton; s2,s3,s4 split conservatively
    accepted = payload["accepted_units"]
    section_sets = [tuple(u["section_keys"]) for u in accepted]
    assert ("s1",) in section_sets
    assert ("s0",) in section_sets
    assert not any("s0" in keys and "s2" in keys for keys in section_sets)


def test_promo_section_remains_separate_unit_after_boundary_accept(tmp_path) -> None:
    html = (
        "<html><body>"
        "<h2>Essay Intro</h2><p>" + _long(55) + "</p>"
        "<h2>Sponsor</h2><p>Register RSVP for the webinar cohort bootcamp early bird.</p>"
        "<h2>Section A</h2><p>" + _long(55) + "</p>"
        "<h2>Section B</h2><p>" + _long(55) + "</p>"
        "<h2>Section C</h2><p>" + _long(55) + "</p>"
        "</body></html>"
    )
    msg_id = "p7-promo-sep"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7ps.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Mixed", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient(_cat_responses(5))
    boundary_mock = Mock(spec=BoundaryClassifierAgent)
    boundary_mock.classify_boundaries.return_value = BoundaryLLMOutput(
        units=[
            BoundaryLLMUnit(unit_title="Tail", section_keys=["s2", "s3", "s4"],
                            unit_type=BoundaryUnitType.LONG_FORM, reason="ok"),
        ],
        confidence=0.9,
    )
    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="T", core_pain_point="p", original_url=None, diagrams=[]
    )

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7ps.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=boundary_mock,
    )
    agent.run_daily()

    import json
    row = repo.connection.execute(
        "SELECT payload FROM agent_outputs WHERE kind = 'boundary_classifier'",
    ).fetchone()
    payload = json.loads(row["payload"])
    promo_units = [u for u in payload["accepted_units"] if u["section_keys"] == ["s1"]]
    assert len(promo_units) == 1


def test_ainews_sender_does_not_call_boundary_classifier(tmp_path) -> None:
    from app.models.outputs import AINewsRadarCardRole, AINewsRadarDigestCard, AINewsRadarDigestOutput

    html = "<html><body><h2>Topic</h2><p>" + _long(60) + "</p></body></html>"
    msg_id = "p7-ainews"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7ai.sqlite")
    repo.upsert_email(
        EmailInput(
            message_id=msg_id,
            subject="AINews",
            sender="swyx+ainews@substack.com",
        ),
    )

    llm = ScriptedLLMClient([])
    boundary_mock = Mock(spec=BoundaryClassifierAgent)
    map_reduce_mock = Mock(spec=AINewsRadarMapReduceAgent)
    map_reduce_mock.run.return_value = AINewsRadarDigestOutput(
        cards=[
            AINewsRadarDigestCard(
                role=AINewsRadarCardRole.RECAP,
                title="Recap",
                tldr="Summary.",
                key_points=["Point"],
            ),
        ],
    )
    client = GmailClient(service_factory=lambda: svc)
    agent = DailyDigestAgent(
        repo=repo,
        run_lock=RunLock(tmp_path / "p7ai.sqlite"),
        fetcher=GmailFetcher(client, senders=["swyx+ainews@substack.com"], max_results=20),
        router_agent=Mock(spec=RouterAgent),
        technology_agent=Mock(spec=TechnologyProcessorAgent),
        radar_agent=Mock(spec=RadarProcessorAgent),
        leadership_agent=Mock(spec=LeadershipProcessorAgent),
        courses_agent=Mock(spec=CoursesProcessorAgent),
        map_reduce_radar_agent=map_reduce_mock,
        map_reduce_radar_senders=("swyx+ainews@substack.com",),
        content_unit_classifier_agent=ContentUnitClassifierAgent(llm, model="m"),
        boundary_classifier_agent=boundary_mock,
        enable_content_unit_routing=True,
        composer=DigestComposer(title="AINews test"),
        quality_gate=DigestQualityGateAgent(),
        labeler=GmailLabeler(client),
        sender=GmailSender(client, sender="me@test"),
        digest_to="reader@test",
    )
    agent.run_daily()

    boundary_mock.classify_boundaries.assert_not_called()
    row = repo.connection.execute(
        "SELECT kind FROM agent_outputs WHERE kind = 'boundary_classifier'",
    ).fetchone()
    assert row is None


# ---------------------------------------------------------------------------
# 13. compute_outline_hash is stable and structural-only
# ---------------------------------------------------------------------------


def test_compute_outline_hash_reflects_snippet_truncation() -> None:
    sections = [
        BoundaryOutlineSection(section_key="s0", heading="Intro", snippet="a" * 280, char_count=500),
        BoundaryOutlineSection(section_key="s1", heading="Body", snippet="b" * 280, char_count=1200),
    ]
    h_full = compute_outline_hash(sections)
    sections[0] = sections[0].model_copy(update={"snippet": "a" * 140})
    h_trunc = compute_outline_hash(sections)
    assert h_full != h_trunc


def test_compute_outline_hash_changes_when_structure_changes() -> None:
    sections = [
        BoundaryOutlineSection(section_key="s0", heading="Intro", char_count=500),
    ]
    h1 = compute_outline_hash(sections)
    sections[0] = sections[0].model_copy(update={"char_count": 501})
    h2 = compute_outline_hash(sections)
    assert h1 != h2


def test_compute_composite_outline_hash_single_and_multi() -> None:
    h1 = "abc123"
    h2 = "def456"
    assert compute_composite_outline_hash([h1]) == h1
    assert compute_composite_outline_hash([h1, h2]) != h1
    assert compute_composite_outline_hash([h1, h2]) != h2


def test_deterministic_units_for_run_scopes_and_dedupes() -> None:
    merged = ContentUnit(
        content_unit_key="u0",
        unit_text="x",
        section_keys=["s0", "s1"],
    )
    promo_unit = ContentUnit(content_unit_key="u2", unit_text="p", section_keys=["s9"])
    units = deterministic_units_for_run([merged, promo_unit], ["s0", "s1"])
    assert len(units) == 1
    assert units[0].content_unit_key == "u0"


def test_validate_run_groups_coverage_missing_and_duplicate() -> None:
    s0 = _sec("s0", "A", "a")
    s1 = _sec("s1", "B", "b")
    assert any("missing" in e for e in validate_run_groups_coverage([[s0]], ["s0", "s1"]))
    assert any("duplicate" in e for e in validate_run_groups_coverage([[s0], [s0]], ["s0"]))


def test_build_canonical_units_matches_conservative_units() -> None:
    sections = [
        _sec("s0", "A", _long(60)),
        _sec("s1", "B", _long(60)),
        _sec("s2", "C", _long(60)),
    ]
    grouping = group_content_units(sections)
    built = build_canonical_units(sections, conservative_non_promo_groups(sections))
    assert [u.section_keys for u in built] == [u.section_keys for u in grouping.conservative_units]


def test_ambiguous_without_boundary_agent_persists_llm_skipped_disabled(tmp_path) -> None:
    # Same mixed-heading fixture as test_boundary_classifier_triggered_for_ambiguous_email.
    html = (
        "<html><body>"
        "<h2>The AI Stack in 2026</h2><p>" + (_long(60)) + "</p>"
        "<h2>Leadership Notes</h2><p>" + (_long(60)) + "</p>"
        "<h2>Quick Hits</h2><p>" + (_long(60)) + "</p>"
        "<h2>Research Roundup</h2><p>" + (_long(60)) + "</p>"
        "</body></html>"
    )
    msg_id = "p7-disabled"
    svc = FakeGmailService(messages={msg_id: _message_full_html(msg_id, html)})
    repo = StateRepository(tmp_path / "p7dis.sqlite")
    repo.upsert_email(EmailInput(message_id=msg_id, subject="Ambiguous", sender="newsletter@fixture.test"))

    llm = ScriptedLLMClient(
        [
            '{"category":"TECHNOLOGY","confidence":0.9,"rationale":"r","primary_value":"v","evidence":[]}',
        ]
        * 4,
    )
    technology = Mock(spec=TechnologyProcessorAgent)
    technology.run_section.return_value = TechnologySectionOutput(
        title="T", core_pain_point="p", original_url=None, diagrams=[]
    )

    agent = _phase7_agent(
        repo=repo,
        lock=RunLock(tmp_path / "p7dis.sqlite"),
        svc=svc,
        llm=llm,
        technology=technology,
        boundary=None,
    )
    agent.run_daily()

    import json
    row = repo.connection.execute(
        "SELECT payload FROM agent_outputs WHERE kind = 'boundary_classifier'",
    ).fetchone()
    assert row is not None
    payload = json.loads(row["payload"])
    assert payload["fallback_used"] is True
    assert payload["fallback_reason"] == "llm_skipped_disabled"
    assert payload["budget_status"] == BoundaryBudgetStatus.LLM_SKIPPED_DISABLED
    assert len(payload["accepted_units"]) == 4
