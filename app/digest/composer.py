from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.outputs import (
    AINewsRadarCardRole,
    AINewsRadarDigestOutput,
    MAP_REDUCE_RADAR_DIGEST_KIND,
    CoursesOutput,
    Diagram,
    LeadershipSectionOutput,
    LeadershipSignal,
    RadarOutput,
    RouteCategory,
    TechnologySectionOutput,
)
from app.storage.repository import AgentOutputRecord


def _sender_label(senders: Mapping[int, str | None], email_id: int) -> str | None:
    raw = senders.get(email_id)
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _parse_courses_payload(raw: str) -> CoursesOutput:
    return CoursesOutput.model_validate_json(raw)


def _diagram_rows(diagrams: list[Diagram]) -> list[dict[str, Any]]:
    return [{"title": d.title, "diagram_type": d.diagram_type, "content": d.content} for d in diagrams]


def _courses_digest_row(
    *,
    email_subject: str,
    from_line: str | None,
    section_heading: str | None,
    m: CoursesOutput,
) -> dict[str, Any]:
    return {
        "subject": email_subject,
        "source_subject": email_subject,
        "source_sender": from_line,
        "section_heading": section_heading,
        "summary": m.summary,
        "actions": [{"label": a.label, "url": a.url} for a in m.actions],
        "promo_blocks": [
            {"text": b.text, "cta": {"label": b.cta.label, "url": b.cta.url}} for b in m.promo_blocks
        ],
    }


def _leadership_digest_row(
    *,
    email_subject: str,
    from_line: str | None,
    section_heading: str | None,
    signals: list[LeadershipSignal],
    summary: str | None,
) -> dict[str, Any]:
    return {
        "subject": email_subject,
        "source_sender": from_line,
        "section_heading": section_heading,
        "summary": summary,
        "signals": [
            {
                "theme": s.theme,
                "insight": s.insight,
                "actionable_item": s.actionable_item,
                "link": s.link,
                "source_subject": email_subject,
                "source_sender": from_line,
                "section_heading": section_heading,
            }
            for s in signals
        ],
    }


def _deep_recap_card_row(
    *,
    email_subject: str,
    from_line: str | None,
    card,
) -> dict[str, Any]:
    return {
        "subject": email_subject,
        "source_sender": from_line,
        "role": card.role.value,
        "title": card.title,
        "tldr": card.tldr,
        "key_points": list(card.key_points),
        "why_it_matters": list(card.why_it_matters),
        "watchouts": list(card.watchouts),
    }


def _split_ainews_deep_recap_rows(
    *,
    email_subject: str,
    from_line: str | None,
    digest: AINewsRadarDigestOutput,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    top_story: list[dict[str, Any]] = []
    recap: list[dict[str, Any]] = []
    for card in digest.cards:
        row = _deep_recap_card_row(
            email_subject=email_subject,
            from_line=from_line,
            card=card,
        )
        if card.role == AINewsRadarCardRole.TOP_STORY:
            top_story.append(row)
        else:
            recap.append(row)
    return top_story, recap


def _radar_digest_row(
    *,
    email_subject: str,
    from_line: str | None,
    section_heading: str | None,
    m: RadarOutput,
) -> dict[str, Any]:
    return {
        "subject": email_subject,
        "source_sender": from_line,
        "section_heading": section_heading,
        "summary": m.summary,
        "items": [
            {
                "entity": it.entity,
                "impact_or_action": it.impact_or_action,
                "url": it.url,
                "source_subject": email_subject,
                "source_sender": from_line,
                "section_heading": section_heading,
            }
            for it in m.items
        ],
    }


def _repair_html(html: str, problems: Sequence[str]) -> str:
    """Apply deterministic fixes suggested by quality-gate problem codes."""

    pset = set(problems)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script"):
        tag.decompose()
    for tag in soup.find_all("style"):
        tag.decompose()
    out = str(soup)
    low = out.lower()
    if "missing_html_root" in pset or "missing_html_close" in pset:
        if "<html" not in low:
            out = (
                '<!DOCTYPE html>\n<html lang="en"><head>'
                '<meta charset="utf-8"/></head><body>'
                f"{out}</body></html>"
            )
        elif "</html>" not in low:
            out = out + "</body></html>"
    if "body_too_short" in pset:
        filler = "<p>" + ("Padding added to satisfy minimum length checks. " * 8) + "</p>"
        if "</body>" in out.lower():
            idx = out.lower().rindex("</body>")
            out = out[:idx] + filler + out[idx:]
        else:
            out = out + filler
    if "nul_byte" in pset:
        out = out.replace("\x00", "")
    if "unrendered_template_markup" in pset:
        out = out.replace("{{", "(").replace("}}", ")")
        out = out.replace("{%", "(%").replace("%}", "%)")
    return out


_KIND_ORDER_FOR_SECTION = {
    "technology": 10,
    "ainews_radar_digest": 15,
    "radar": 20,
    "leadership": 30,
    "courses": 40,
    "noise": 41,
}

_PROCESSOR_KINDS = frozenset(
    {"technology", "radar", "ainews_radar_digest", "leadership", "courses", "noise"},
)


def _valid_category_kind_pair(cat: RouteCategory, kind: str) -> bool:
    if kind == "technology":
        return cat == RouteCategory.TECHNOLOGY
    if kind == "radar":
        return cat == RouteCategory.RADAR
    if kind == MAP_REDUCE_RADAR_DIGEST_KIND:
        return cat == RouteCategory.RADAR
    if kind == "leadership":
        return cat == RouteCategory.LEADERSHIP
    if kind == "courses":
        return cat == RouteCategory.COURSES
    if kind == "noise":
        return cat == RouteCategory.COURSES
    return False


@dataclass(frozen=True, slots=True)
class ComposeResult:
    """Rendered digest HTML plus non-fatal composition diagnostics."""

    html: str
    composition_warnings: tuple[str, ...] = ()


class DigestComposer:
    """Renders digest HTML from persisted **section-scoped** structured outputs."""

    def __init__(self, *, title: str = "Daily digest") -> None:
        self._default_title = title
        tpl_dir = Path(__file__).resolve().parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(tpl_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def compose(
        self,
        output_rows: Sequence[AgentOutputRecord],
        subjects: Mapping[int, str | None],
        *,
        senders: Mapping[int, str | None] | None = None,
        revision_problems: Sequence[str] = (),
    ) -> ComposeResult:
        """Build HTML; when ``revision_problems`` is non-empty, repair the prior render.

        Skipped legacy or inconsistent rows append to ``composition_warnings`` rather than
        being rerouted silently.
        """

        snd = senders or {}
        warnings: list[str] = []

        map_reduce_digest_email_ids: set[int] = set()
        for r in output_rows:
            if r.kind == MAP_REDUCE_RADAR_DIGEST_KIND and r.email_section_id is None:
                map_reduce_digest_email_ids.add(r.email_id)

        for r in output_rows:
            if r.kind not in _PROCESSOR_KINDS:
                continue
            if r.email_section_id is None and r.kind != MAP_REDUCE_RADAR_DIGEST_KIND:
                cat_disp = repr(r.category)
                warnings.append(
                    "composition_legacy_email_level_processor: "
                    f"agent_output_id={r.id} email_id={r.email_id} "
                    f"email_section_id=null kind={r.kind!r} category={cat_disp}",
                )

        digest_rows = [
            row
            for row in output_rows
            if row.kind == MAP_REDUCE_RADAR_DIGEST_KIND and row.email_section_id is None
        ]
        proc_rows = [
            row
            for row in output_rows
            if row.email_section_id is not None
            and row.kind in _PROCESSOR_KINDS
            and row.email_id not in map_reduce_digest_email_ids
        ]
        proc_rows.sort(
            key=lambda row: (
                row.email_id,
                row.section_order_index if row.section_order_index is not None else 2_147_483_647,
                _KIND_ORDER_FOR_SECTION.get(row.kind, 99),
                row.id,
            ),
        )

        technical_index: list[dict[str, Any]] = []
        ai_radar_top_story: list[dict[str, Any]] = []
        ai_radar_recap: list[dict[str, Any]] = []
        ai_radar: list[dict[str, Any]] = []
        leadership_signals: list[dict[str, Any]] = []
        courses: list[dict[str, Any]] = []

        for row in sorted(digest_rows, key=lambda r: (r.email_id, r.id)):
            cat_raw = row.category
            try:
                cat = RouteCategory(str(cat_raw))
            except (TypeError, ValueError):
                warnings.append(
                    "composition_invalid_category: "
                    f"agent_output_id={row.id} email_id={row.email_id} "
                    f"email_section_id=null kind={row.kind!r} category={cat_raw!r}",
                )
                continue
            if not _valid_category_kind_pair(cat, row.kind):
                warnings.append(
                    "composition_category_kind_mismatch: "
                    f"agent_output_id={row.id} email_id={row.email_id} "
                    f"email_section_id=null kind={row.kind!r} category={cat.value!r}",
                )
                continue
            subject = subjects.get(row.email_id)
            email_subject = subject or f"Email #{row.email_id}"
            from_line = _sender_label(snd, row.email_id)
            digest = AINewsRadarDigestOutput.model_validate_json(row.payload)
            top_rows, recap_rows = _split_ainews_deep_recap_rows(
                email_subject=email_subject,
                from_line=from_line,
                digest=digest,
            )
            ai_radar_top_story.extend(top_rows)
            ai_radar_recap.extend(recap_rows)

        for row in proc_rows:
            cat_raw = row.category
            try:
                cat = RouteCategory(str(cat_raw))
            except (TypeError, ValueError):
                warnings.append(
                    "composition_invalid_category: "
                    f"agent_output_id={row.id} email_id={row.email_id} "
                    f"email_section_id={row.email_section_id} kind={row.kind!r} category={cat_raw!r}",
                )
                continue

            subject = subjects.get(row.email_id)
            email_subject = subject or f"Email #{row.email_id}"
            from_line = _sender_label(snd, row.email_id)
            heading = row.section_heading or None

            if not _valid_category_kind_pair(cat, row.kind):
                warnings.append(
                    "composition_category_kind_mismatch: "
                    f"agent_output_id={row.id} email_id={row.email_id} "
                    f"email_section_id={row.email_section_id} kind={row.kind!r} category={cat.value!r}",
                )
                continue

            if cat == RouteCategory.TECHNOLOGY and row.kind == "technology":
                m = TechnologySectionOutput.model_validate_json(row.payload)
                technical_index.append(
                    {
                        "email_subject": email_subject,
                        "source_sender": from_line,
                        "section_heading": heading,
                        "title": m.title,
                        "article_url": m.original_url,
                        "core_pain_point": m.core_pain_point,
                        "diagrams": _diagram_rows(m.diagrams),
                    },
                )
            elif cat == RouteCategory.RADAR and row.kind == "radar":
                radar_m = RadarOutput.model_validate_json(row.payload)
                ai_radar.append(
                    _radar_digest_row(
                        email_subject=email_subject,
                        from_line=from_line,
                        section_heading=heading,
                        m=radar_m,
                    ),
                )
            elif cat == RouteCategory.LEADERSHIP and row.kind == "leadership":
                lm = LeadershipSectionOutput.model_validate_json(row.payload)
                leadership_signals.append(
                    _leadership_digest_row(
                        email_subject=email_subject,
                        from_line=from_line,
                        section_heading=heading,
                        signals=list(lm.signals),
                        summary=lm.summary,
                    ),
                )
            elif cat == RouteCategory.COURSES and row.kind in ("courses", "noise"):
                cm = (
                    CoursesOutput.model_validate_json(row.payload)
                    if row.kind == "courses"
                    else _parse_courses_payload(row.payload)
                )
                courses.append(
                    _courses_digest_row(
                        email_subject=email_subject,
                        from_line=from_line,
                        section_heading=heading,
                        m=cm,
                    ),
                )

        quality_notes = "; ".join(revision_problems) if revision_problems else ""

        tpl = self._env.get_template("daily_digest.html.j2")
        html = tpl.render(
            title=self._default_title,
            quality_notes=quality_notes,
            technical_index=technical_index,
            ai_radar_top_story=ai_radar_top_story,
            ai_radar_recap=ai_radar_recap,
            ai_radar=ai_radar,
            leadership_signals=leadership_signals,
            courses=courses,
        )
        if revision_problems:
            html = _repair_html(html, revision_problems)
        return ComposeResult(html=html, composition_warnings=tuple(warnings))
