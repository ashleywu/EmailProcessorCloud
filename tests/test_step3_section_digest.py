"""Step 3 tests: capped section merges, content-hash invalidation."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.email import EmailInput
from app.models.outputs import RadarOutput, RouterDecision, RouteCategory
from app.models.section import EmailSection
from app.parsing.parser import ParsedHtmlResult
from app.parsing.section_caps import MAX_SECTIONS_PER_EMAIL, normalize_sections_for_routing
from app.storage.repository import StateRepository


@pytest.fixture
def repo(tmp_path: Path) -> StateRepository:
    db = tmp_path / "step3.sqlite"
    r = StateRepository(db)
    yield r
    r.close()


def test_normalize_sections_respects_max_sections_and_preserves_concatenated_text() -> None:
    raw = []
    filler = "x" * 400 + "\n"
    for idx in range(12):
        raw.append(
            EmailSection(
                section_id=f"m{idx}",
                order_index=idx,
                text=f"{filler}{idx}",
                links=[f"https://lnk.example/{idx}"],
                image_urls=[],
            ),
        )
    plain_blob = "\n".join(s.text for s in raw)
    parsed = ParsedHtmlResult(
        plain_text=plain_blob,
        plain_text_chars=len(plain_blob),
        links=[],
        image_urls=[],
        original_url=None,
        sections=raw,
    )
    merged = normalize_sections_for_routing(parsed)
    assert len(merged) <= MAX_SECTIONS_PER_EMAIL
    joined = "\n".join(s.text for s in merged)
    for idx in range(12):
        assert str(idx) in joined


def test_content_hash_change_clears_matching_outputs_via_replace(repo: StateRepository) -> None:
    eid = repo.upsert_email(EmailInput(message_id="hx"))
    recs = repo.replace_email_sections(
        eid,
        [
            EmailSection(
                section_id="s0",
                order_index=0,
                text="alpha " * 100,
                links=["https://a.example/doc"],
                image_urls=[],
            ),
        ],
    )
    sid = recs[0].id

    repo.save_agent_output(
        eid,
        "router",
        RouterDecision(category=RouteCategory.RADAR, confidence=0.6),
        email_section_id=sid,
    )
    oid = repo.save_agent_output(eid, "radar", RadarOutput(summary="pulse"), email_section_id=sid)

    repo.replace_email_sections(
        eid,
        [
            EmailSection(
                section_id="s0",
                order_index=0,
                text="beta " * 100,
                links=["https://a.example/doc"],
                image_urls=[],
            ),
        ],
    )
    leftovers = repo.connection.execute(
        "SELECT COUNT(*) AS c FROM agent_outputs WHERE id = ?",
        (oid,),
    ).fetchone()["c"]
    assert int(leftovers) == 0

