from __future__ import annotations

import base64
import json

from app.digest.composer import DigestComposer
from app.models.outputs import RadarOutput, RouterDecision
from app.parsing.map_reduce_chunks import chunk_sections_for_map
from app.parsing.parser import parse_newsletter_html
from app.parsing.section_caps import MAX_SECTIONS_PER_EMAIL, normalize_sections_for_routing
from app.models.email import EmailInput
from app.agents.ainews_radar_map_reduce_agent import AINewsRadarMapReduceAgent
from app.models.outputs import (
    MAP_REDUCE_RADAR_DIGEST_KIND,
    AINewsRadarCardRole,
    AINewsRadarDigestCard,
    AINewsRadarDigestOutput,
    RouteCategory,
)
from app.parsing.ainews_boundaries import split_ainews_sections
from app.storage.repository import StateRepository
from app.storage.run_lock import RunLock
from app.agents._prompts import load_prompt
from tests.agent_factory import build_daily_digest_agent
from tests.fakes import FakeGmailService, make_message
from tests.fakes.llm import ScriptedLLMClient


def _b64url(data: str) -> str:
    return base64.urlsafe_b64encode(data.encode("utf-8")).decode("ascii").rstrip("=")


def _ainews_html(section_count: int = 22) -> str:
    parts = [
        "<html><body>",
        "<p>Intro padding for the AINews style long issue newsletter body.</p>",
    ]
    for i in range(section_count):
        parts.append(f"<h2>Section {i}</h2>")
        parts.append(f"<p>{'fact ' * 120} item {i}</p>")
    parts.append("</body></html>")
    return "".join(parts)


def _message_with_from(msg_id: str, html: str, from_line: str) -> dict:
    m = make_message(msg_id=msg_id, label_ids=["INBOX"])
    headers = [h for h in m["payload"]["headers"] if h.get("name") != "From"]
    headers.append({"name": "From", "value": from_line})
    m["payload"] = {
        "mimeType": "text/html",
        "headers": headers,
        "body": {"data": _b64url(html)},
    }
    return m


def _map_json(entity: str) -> str:
    return json.dumps(
        {
            "facts": [
                {
                    "entity": entity,
                    "fact": "Shipped a model update.",
                    "implication": "Teams should retest integrations.",
                    "source_heading": "Section 0",
                    "importance_score": 5,
                },
            ],
        },
    )


def _hero_json(title: str = "Reve 2 and Ideogram 4") -> str:
    card = AINewsRadarDigestCard(
        role=AINewsRadarCardRole.TOP_STORY,
        title=title,
        tldr="Layout-native imagegen launches.",
        key_points=["Reve 2.0", "Ideogram 4.0 open weights"],
        why_it_matters=["Composition control improved."],
        watchouts=[],
    )
    return json.dumps({"card": card.model_dump()})


def _recap_reduce_json() -> str:
    card = AINewsRadarDigestCard(
        role=AINewsRadarCardRole.RECAP,
        title="AI Twitter recap",
        tldr="Community and infra threads.",
        key_points=["Agents", "Harnesses"],
        why_it_matters=[],
        watchouts=[],
    )
    return json.dumps({"cards": [card.model_dump()]})


def _reduce_json() -> str:
    card = AINewsRadarDigestCard(
        role=AINewsRadarCardRole.RECAP,
        title="Deep recap theme",
        tldr="A neutral summary of the issue.",
        key_points=["Point A", "Point B", "Point C"],
        why_it_matters=["Because platforms shifted."],
        watchouts=["Latency may rise."],
    )
    return AINewsRadarDigestOutput(cards=[card]).model_dump_json()


def _reve_issue_html() -> str:
    return (
        "<html><body>"
        "<h2>Reve 2 and Ideogram 4: Layouts in Imagegen</h2>"
        "<p>" + ("launch detail " * 80) + "</p>"
        "<h2>AI Twitter Recap</h2>"
        "<p>" + ("twitter fact " * 80) + "</p>"
        "<h2>AI Reddit Recap</h2>"
        "<p>" + ("reddit fact " * 80) + "</p>"
        "</body></html>"
    )


def test_map_reduce_email_skips_per_section_radar(tmp_path) -> None:
    html = _ainews_html(22)
    svc = FakeGmailService(
        messages={
            "gm-ainews": _message_with_from(
                "gm-ainews",
                html,
                "AINews <swyx+ainews@substack.com>",
            ),
        },
    )
    db = tmp_path / "ainews.sqlite"
    repo = StateRepository(db)
    eid = repo.upsert_email(
        EmailInput(
            message_id="gm-ainews",
            subject="AI News Today",
            sender="AINews <swyx+ainews@substack.com>",
        ),
    )

    parsed = parse_newsletter_html(html)
    chunk_count = len(
        chunk_sections_for_map(
            parsed.sections,
            target_chars=14000,
            max_chunks=6,
        ),
    )
    llm = ScriptedLLMClient(
        [_map_json(f"E{i}") for i in range(chunk_count)] + [_reduce_json()],
    )
    agent = build_daily_digest_agent(repo, RunLock(db), svc, llm)
    agent.run_daily()

    assert len(llm.completion_calls) == chunk_count + 1
    assert chunk_count <= 6

    router_rows = repo.connection.execute(
        "SELECT kind FROM agent_outputs WHERE kind = 'router'",
    ).fetchall()
    assert len(router_rows) == 0

    radar_rows = repo.connection.execute(
        "SELECT kind FROM agent_outputs WHERE kind = 'radar'",
    ).fetchall()
    assert len(radar_rows) == 0

    stored_sections = repo.list_email_sections(eid)
    assert len(stored_sections) > MAX_SECTIONS_PER_EMAIL

    digest_rows = repo.connection.execute(
        "SELECT kind, email_section_id FROM agent_outputs WHERE kind = ?",
        (MAP_REDUCE_RADAR_DIGEST_KIND,),
    ).fetchall()
    assert len(digest_rows) == 1
    assert digest_rows[0]["email_section_id"] is None


def test_hybrid_boundary_hero_plus_recap_llm_calls() -> None:
    html = _reve_issue_html()
    parsed = parse_newsletter_html(html)
    split = split_ainews_sections(parsed.sections)
    assert split.has_boundary
    assert len(split.hero_sections) >= 1
    assert len(split.recap_sections) >= 1

    recap_chunks = len(
        chunk_sections_for_map(
            split.recap_sections,
            target_chars=14000,
            max_chunks=6,
        ),
    )
    llm = ScriptedLLMClient(
        [_hero_json()] + [_map_json("tw")] * recap_chunks + [_recap_reduce_json()],
    )
    agent = AINewsRadarMapReduceAgent(llm, model="m")
    out = agent.run(parsed, subject="[AINews] Reve 2 and Ideogram 4")
    assert 1 <= len(out.cards) <= 3
    assert out.cards[0].role == AINewsRadarCardRole.TOP_STORY
    assert any(c.role == AINewsRadarCardRole.RECAP for c in out.cards)
    assert len(llm.completion_calls) == 1 + recap_chunks + 1


def test_composer_renders_top_story_and_recap_subsections() -> None:
    digest = AINewsRadarDigestOutput(
        cards=[
            AINewsRadarDigestCard(
                role=AINewsRadarCardRole.TOP_STORY,
                title="TOP_STORY_MARKER",
                tldr="lead",
                key_points=["a"],
            ),
            AINewsRadarDigestCard(
                role=AINewsRadarCardRole.RECAP,
                title="RECAP_MARKER",
                tldr="recap",
                key_points=["b"],
            ),
        ],
    )
    from app.storage.repository import AgentOutputRecord

    row = AgentOutputRecord(
        id=10,
        email_id=1,
        kind=MAP_REDUCE_RADAR_DIGEST_KIND,
        payload=digest.model_dump_json(),
        created_at="t",
        email_section_id=None,
        category=RouteCategory.RADAR.value,
    )
    result = DigestComposer().compose([row], subjects={1: "AI News"})
    assert "TOP_STORY_MARKER" in result.html
    assert "RECAP_MARKER" in result.html
    assert "Top Story" in result.html
    assert "Recap" in result.html


def test_composer_renders_deep_recap_not_section_cards(tmp_path) -> None:
    eid = 1
    digest = AINewsRadarDigestOutput(
        cards=[
            AINewsRadarDigestCard(
                title="ONLY_DEEP_RECAP_TITLE",
                tldr="ONLY_DEEP_RECAP_TLDR",
                key_points=["kp1", "kp2"],
                why_it_matters=["why1"],
                watchouts=[],
            ),
        ],
    )
    from app.storage.repository import AgentOutputRecord

    row = AgentOutputRecord(
        id=10,
        email_id=eid,
        kind=MAP_REDUCE_RADAR_DIGEST_KIND,
        payload=digest.model_dump_json(),
        created_at="t",
        email_section_id=None,
        category=RouteCategory.RADAR.value,
    )
    result = DigestComposer().compose([row], subjects={eid: "AI News"})
    assert "ONLY_DEEP_RECAP_TITLE" in result.html
    assert "ONLY_DEEP_RECAP_TLDR" in result.html
    assert "deep-recap" in result.html


def test_reduce_prompt_requires_thematic_cards_not_section_collapse() -> None:
    text = load_prompt("ainews_radar_reduce")
    assert "radar" in text.lower()
    assert "technical index" in text.lower() or "leadership" in text.lower()
    hero = load_prompt("ainews_radar_hero")
    assert "top_story" in hero.lower()
    assert "do not" in hero.lower() and "technical index" in hero.lower()
    recap = load_prompt("ainews_radar_reduce_recap")
    assert "recap" in recap.lower()


def test_ainews_uses_raw_sections_not_routing_cap() -> None:
    html = _ainews_html(22)
    parsed = parse_newsletter_html(html)
    assert len(parsed.sections) > MAX_SECTIONS_PER_EMAIL
    assert len(normalize_sections_for_routing(parsed)) <= MAX_SECTIONS_PER_EMAIL
    assert len(
        chunk_sections_for_map(parsed.sections, target_chars=14000, max_chunks=6),
    ) <= 6


def test_legacy_per_section_outputs_not_reused_for_ainews(tmp_path) -> None:
    html = _ainews_html(4)
    svc = FakeGmailService(
        messages={
            "gm-old": _message_with_from(
                "gm-old",
                html,
                "swyx+ainews@substack.com",
            ),
        },
    )
    db = tmp_path / "legacy.sqlite"
    repo = StateRepository(db)
    eid = repo.upsert_email(
        EmailInput(message_id="gm-old", sender="swyx+ainews@substack.com"),
    )
    recs = repo.replace_email_sections(
        eid,
        parse_newsletter_html(html).sections[:4],
    )
    for rec in recs:
        repo.save_agent_output(
            eid,
            "router",
            RouterDecision(category=RouteCategory.RADAR, confidence=0.9),
            email_section_id=rec.id,
        )
        repo.save_agent_output(
            eid,
            "radar",
            RadarOutput(summary="OLD_SECTION_RADAR_MARKER", items=[]),
            email_section_id=rec.id,
        )
    assert repo.try_reuse_complete_outputs(eid) == frozenset({RouteCategory.RADAR})
    assert not repo.map_reduce_radar_digest_cached(eid)

    parsed = parse_newsletter_html(html)
    chunk_count = len(
        chunk_sections_for_map(parsed.sections, target_chars=14000, max_chunks=6),
    )
    llm = ScriptedLLMClient(
        [_map_json("legacy")] * chunk_count + [_reduce_json()],
    )
    build_daily_digest_agent(repo, RunLock(db), svc, llm).run_daily()

    assert len(llm.completion_calls) == chunk_count + 1
    assert repo.map_reduce_radar_digest_cached(eid)
    old = repo.connection.execute(
        "SELECT payload FROM agent_outputs WHERE kind = 'radar'",
    ).fetchall()
    assert len(old) == 0


def test_try_reuse_with_digest_only(tmp_path) -> None:
    repo = StateRepository(tmp_path / "reuse.sqlite")
    eid = repo.upsert_email(
        EmailInput(message_id="reuse-ainews", sender="swyx+ainews@substack.com"),
    )
    repo.save_agent_output(
        eid,
        MAP_REDUCE_RADAR_DIGEST_KIND,
        AINewsRadarDigestOutput(
            cards=[
                AINewsRadarDigestCard(
                    title="T",
                    tldr="TLDR",
                    key_points=["a"],
                ),
            ],
        ),
        email_section_id=None,
        category=RouteCategory.RADAR.value,
    )
    assert repo.map_reduce_radar_digest_cached(eid)
    assert repo.try_reuse_complete_outputs(eid) == frozenset({RouteCategory.RADAR})
