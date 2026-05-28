"""email_sections + section-scoped agent_outputs."""

from __future__ import annotations

import json

import pytest

from app.models.email import EmailInput
from app.models.outputs import (
    RouterDecision,
    RouteCategory,
    TechnologyOutput,
    TechnologySectionOutput,
)
from app.models.section import EmailSection
from app.storage.repository import EmailSectionRecord, StateRepository


@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "sections.db"
    r = StateRepository(db, max_email_retries=3)
    yield r
    r.close()


def test_replace_email_sections_persists_fields(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="sec-persist"))
    sections = [
        EmailSection(
            section_id="s0",
            order_index=0,
            heading="H1",
            text="Body text",
            links=["https://a.example/x"],
            image_urls=["https://cdn.example/i.png"],
        ),
    ]
    out = repo.replace_email_sections(eid, sections)
    assert len(out) == 1
    rec = out[0]
    assert isinstance(rec, EmailSectionRecord)
    assert rec.id >= 1
    assert rec.email_id == eid
    assert rec.section_key == "s0"
    assert rec.order_index == 0
    assert rec.heading == "H1"
    assert rec.text == "Body text"
    assert json.loads(rec.links_json) == ["https://a.example/x"]
    assert json.loads(rec.image_urls_json) == ["https://cdn.example/i.png"]
    assert len(rec.content_hash) == 64

    listed = repo.list_email_sections(eid)
    assert len(listed) == 1
    assert listed[0].section_key == "s0"


def test_replace_sections_cascade_deletes_section_level_outputs(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="cascade-z"))
    recs = repo.replace_email_sections(
        eid,
        [
            EmailSection(section_id="s0", order_index=0, text="a", links=["https://a.example/x"], image_urls=[]),
        ],
    )
    sid0 = recs[0].id
    oid = repo.save_agent_output(
        eid,
        "technology",
        TechnologySectionOutput(
            title="z",
            core_pain_point="z",
            original_url="https://a.example/x",
            diagrams=[],
        ),
        email_section_id=sid0,
        category="TECHNOLOGY",
    )
    assert oid >= 1

    repo.replace_email_sections(
        eid,
        [
            EmailSection(
                section_id="s0",
                order_index=0,
                text="replaced",
                links=["https://a.example/x"],
                image_urls=[],
            ),
        ],
    )
    n = repo.connection.execute(
        "SELECT COUNT(*) AS c FROM agent_outputs WHERE id = ?",
        (oid,),
    ).fetchone()["c"]
    assert int(n) == 0


def test_latest_processor_row_per_section_kind_wins_duplicate_saves(repo: StateRepository) -> None:
    """Compose queries use greatest ``id`` per ``(email_id, email_section_id, kind)``."""

    eid = repo.upsert_email(EmailInput(message_id="dup-latest"))
    recs = repo.replace_email_sections(
        eid,
        [
            EmailSection(
                section_id="s0",
                order_index=0,
                text="solo " * 100,
                links=["https://dup.example/p"],
                image_urls=[],
            ),
        ],
    )
    sid = recs[0].id
    repo.save_agent_output(
        eid,
        "technology",
        TechnologySectionOutput(title="first", core_pain_point="a", original_url="https://dup.example/p", diagrams=[]),
        email_section_id=sid,
        category="TECHNOLOGY",
    )
    repo.save_agent_output(
        eid,
        "technology",
        TechnologySectionOutput(title="second", core_pain_point="b", original_url="https://dup.example/p", diagrams=[]),
        email_section_id=sid,
        category="TECHNOLOGY",
    )
    rows = repo.get_latest_outputs_by_email_ids([eid])
    tech = next(r for r in rows if r.kind == "technology")
    parsed = TechnologySectionOutput.model_validate_json(tech.payload)
    assert parsed.title == "second"


def test_replace_email_sections_preserves_row_id_when_key_and_content_hash_stable(
    repo: StateRepository,
) -> None:
    """Parser ``section_id`` maps to DB ``section_key``; stable content keeps the same PK (no cascade)."""

    eid = repo.upsert_email(EmailInput(message_id="pk-stable"))

    sections = [
        EmailSection(
            section_id="s0",
            order_index=0,
            text="hold " * 120,
            links=["https://pk.example/doc"],
            image_urls=[],
        ),
        EmailSection(
            section_id="s1",
            order_index=1,
            text="stay " * 120,
            links=["https://pk.example/other"],
            image_urls=[],
        ),
    ]
    first = repo.replace_email_sections(eid, sections)
    ids_round1 = tuple(r.id for r in first)

    second = repo.replace_email_sections(eid, sections)
    ids_round2 = tuple(r.id for r in second)
    assert ids_round1 == ids_round2


def test_two_sections_same_processor_kind_both_latest(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="dual-tech"))
    recs = repo.replace_email_sections(
        eid,
        [
            EmailSection(
                section_id="s0",
                order_index=0,
                text="a" * 200,
                links=["https://one.example/p"],
                image_urls=[],
            ),
            EmailSection(
                section_id="s1",
                order_index=1,
                text="b" * 200,
                links=["https://two.example/p"],
                image_urls=[],
            ),
        ],
    )
    repo.save_agent_output(
        eid,
        "technology",
        TechnologySectionOutput(
            title="O1",
            core_pain_point="one",
            original_url="https://one.example/p",
            diagrams=[],
        ),
        email_section_id=recs[0].id,
        category="TECHNOLOGY",
    )
    repo.save_agent_output(
        eid,
        "technology",
        TechnologySectionOutput(
            title="O2",
            core_pain_point="two",
            original_url="https://two.example/p",
            diagrams=[],
        ),
        email_section_id=recs[1].id,
        category="TECHNOLOGY",
    )
    rows = repo.get_latest_outputs_by_email_ids([eid])
    tech_rows = [r for r in rows if r.kind == "technology"]
    assert len(tech_rows) == 2
    payloads = {json.loads(r.payload).get("core_pain_point") for r in tech_rows}
    assert payloads == {"one", "two"}


def test_router_category_column_stored_and_matches_payload(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="cat-col"))
    repo.save_agent_output(
        eid,
        "router",
        RouterDecision(category=RouteCategory.RADAR, confidence=0.5),
    )
    row = repo.connection.execute(
        "SELECT category FROM agent_outputs WHERE email_id = ? AND kind = 'router'",
        (eid,),
    ).fetchone()
    assert row["category"] == "RADAR"


def test_save_router_rejects_category_mismatch(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="bad-cat"))
    with pytest.raises(ValueError, match="mismatches"):
        repo.save_agent_output(
            eid,
            "router",
            RouterDecision(category=RouteCategory.RADAR, confidence=0.5),
            category="TECHNOLOGY",
        )


def test_legacy_null_section_outputs_try_reuse_requires_sections(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="legacy-null"))
    repo.save_agent_output(
        eid,
        "router",
        RouterDecision(category=RouteCategory.TECHNOLOGY, confidence=0.9),
    )
    repo.save_agent_output(
        eid,
        "technology",
        TechnologyOutput(core_pain_point="legacy"),
    )
    rows = repo.get_latest_outputs_by_email_ids([eid])
    assert all(r.email_section_id is None for r in rows)
    assert repo.try_reuse_complete_outputs(eid) is None


def test_list_outputs_for_digest_matches_get_latest(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="list-digest"))
    repo.save_agent_output(
        eid,
        "router",
        RouterDecision(category=RouteCategory.COURSES, confidence=0.4),
    )
    a = repo.list_outputs_for_digest([eid])
    b = repo.get_latest_outputs_by_email_ids([eid])
    assert len(a) == len(b)
    assert {r.id for r in a} == {r.id for r in b}
