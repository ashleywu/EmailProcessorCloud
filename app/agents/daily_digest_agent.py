from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.agents.boundary_classifier_agent import BoundaryClassifierAgent
from app.agents.content_unit_classifier_agent import ContentUnitClassifierAgent
from app.agents.courses_agent import CoursesProcessorAgent
from app.agents.ainews_radar_map_reduce_agent import AINewsRadarMapReduceAgent
from app.agents.leadership_agent import LeadershipProcessorAgent
from app.agents.leadership_essay_agent import LeadershipEssayProcessorAgent
from app.agents.technical_longform_agent import TechnicalLongformProcessorAgent
from app.agents.processor_dispatcher import ProcessorDispatcher, ProcessorDispatchResult
from app.agents.radar_agent import RadarProcessorAgent
from app.agents.router_agent import RouterAgent
from app.agents.technology_agent import TechnologyProcessorAgent
from app.digest.composer import DigestComposer
from app.digest.exceptions import QualityGateFailedException
from app.digest.quality_gate import DigestQualityGateAgent
from app.gmail.fetcher import GmailFetcher
from app.gmail.labeler import INBOX_LABEL, PROCESSED_LABEL, GmailLabeler
from app.gmail.sender import GmailSender
from app.models.content_units import (
    BoundaryBudgetStatus,
    BoundaryClassificationResult,
    BoundaryOutlineSection,
    ClassificationRoutingSource,
    ContentUnit,
    ContentUnitClassificationResult,
    GroupingResult,
)
from app.models.outputs import (
    LEADERSHIP_ESSAY_OUTPUT_KIND,
    MAP_REDUCE_RADAR_DIGEST_KIND,
    PROCESSOR_OUTPUT_KIND,
    TECHNICAL_LONGFORM_OUTPUT_KIND,
    RouterDecision,
    RouteCategory,
)
from app.models.section import EmailSection
from app.parsing.boundary_validation import (
    compute_composite_outline_hash,
    compute_outline_hash,
    validate_boundary_llm_output,
)
from app.parsing.content_unit_grouping import (
    assemble_final_groups,
    build_content_units_from_section_groups,
    conservative_groups_for_run,
    deterministic_units_for_run,
    group_content_units,
    is_hard_boundary_section,
    split_non_promo_runs,
)
from app.parsing.parser import ParsedHtmlResult, parse_newsletter_html
from app.parsing.section_caps import normalize_sections_for_routing
from app.parsing.sender_match import sender_matches_map_reduce
from app.processing.confidence_band import (
    CONFIDENCE_HARD_OVERRIDE,
    ConfidenceBandAction,
    apply_confidence_band,
)
from app.processing.profile_executor import (
    ProfileRunPlan,
    compute_profile_merged_content_hash,
    profile_processor_output_kind,
    resolve_profile_plan,
)
from app.processing.sender_profiles import lookup_sender_profile
from app.processing.unit_classification import classify_content_unit
from app.storage.repository import EmailSectionRecord, StateRepository
from app.storage.run_lock import RunLock

DIGEST_STATUS_DRAFT = "draft"
DIGEST_STATUS_SENT = "sent"
DIGEST_STATUS_EMPTY = "empty"
DIGEST_STATUS_ERROR = "error"
DIGEST_STATUS_SEND_FAILED = "send_failed"

_BOUNDARY_MAX_SECTIONS = 12
_BOUNDARY_MIN_CONFIDENCE = 0.75
_BOUNDARY_SNIPPET_MAX_CHARS = 280

_LOGGER = logging.getLogger(__name__)

ProcessLink = tuple[int, str, frozenset[RouteCategory]]


@dataclass(frozen=True, slots=True)
class SkippedEmailLink:
    """Shape-profile teaser/paywall — labeled in Gmail but not attached to digest."""

    email_id: int
    message_id: str


class DailyDigestAgent:
    """Orchestrates fetch → parse → section caps → route → processors → compose → gate → send → label/archive."""

    def __init__(
        self,
        *,
        repo: StateRepository,
        run_lock: RunLock,
        fetcher: GmailFetcher,
        router_agent: RouterAgent,
        technology_agent: TechnologyProcessorAgent,
        radar_agent: RadarProcessorAgent,
        leadership_agent: LeadershipProcessorAgent,
        courses_agent: CoursesProcessorAgent,
        leadership_essay_agent: LeadershipEssayProcessorAgent | None = None,
        technical_longform_agent: TechnicalLongformProcessorAgent | None = None,
        composer: DigestComposer,
        quality_gate: DigestQualityGateAgent,
        labeler: GmailLabeler,
        sender: GmailSender,
        digest_to: str,
        map_reduce_radar_agent: AINewsRadarMapReduceAgent | None = None,
        map_reduce_radar_senders: tuple[str, ...] = (),
        content_unit_classifier_agent: ContentUnitClassifierAgent | None = None,
        boundary_classifier_agent: BoundaryClassifierAgent | None = None,
        enable_content_unit_routing: bool = False,
        digest_subject_prefix: str = "Daily digest",
        lock_owner: str | None = None,
        max_quality_gate_attempts: int = 3,
    ) -> None:
        self._repo = repo
        self._run_lock = run_lock
        self._fetcher = fetcher
        self._router = router_agent
        self._technology = technology_agent
        self._radar = radar_agent
        self._leadership = leadership_agent
        self._leadership_essay = leadership_essay_agent
        self._technical_longform = technical_longform_agent
        self._courses = courses_agent
        self._map_reduce = map_reduce_radar_agent
        self._map_reduce_senders = tuple(map_reduce_radar_senders)
        self._content_unit_classifier = content_unit_classifier_agent
        self._boundary_classifier = boundary_classifier_agent
        self._enable_content_unit_routing = enable_content_unit_routing
        self._processor_dispatcher = ProcessorDispatcher(
            technology_agent=technology_agent,
            radar_agent=radar_agent,
            leadership_agent=leadership_agent,
            courses_agent=courses_agent,
        )
        self._composer = composer
        self._quality_gate = quality_gate
        self._labeler = labeler
        self._sender = sender
        self._digest_to = digest_to
        self._subject_prefix = digest_subject_prefix
        self._lock_owner = lock_owner
        self._max_quality_gate_attempts = max_quality_gate_attempts

    def run_daily(self) -> bool:
        """Run the daily pipeline.

        Returns ``False`` if the run lock could not be acquired; ``True`` when the lock was held
        for the attempt (including early exits such as no candidates or send failure).
        """

        acquired = self._run_lock.acquire(owner=self._lock_owner)
        if not acquired:
            return False
        digest_id: int | None = None
        success_links: list[ProcessLink] = []
        skipped_links: list[SkippedEmailLink] = []
        try:
            candidates = self._merge_candidates()
            if not candidates:
                return True

            digest_id = self._repo.create_digest(
                status=DIGEST_STATUS_DRAFT,
                title=self._digest_title(),
            )
            for pe in candidates:
                outcome = self._process_one_email(pe.id, pe.message_id, digest_id)
                if isinstance(outcome, SkippedEmailLink):
                    skipped_links.append(outcome)
                elif outcome is not None:
                    success_links.append(outcome)

            if not success_links and not skipped_links:
                self._repo.update_digest_status(digest_id, DIGEST_STATUS_EMPTY)
                return True

            if not success_links:
                self._repo.update_digest_status(digest_id, DIGEST_STATUS_EMPTY)
                for skipped in skipped_links:
                    self._labeler.add_labels(
                        skipped.message_id,
                        [PROCESSED_LABEL],
                        remove=[INBOX_LABEL],
                    )
                    self._repo.update_email_status(skipped.email_id, "skipped")
                return True

            email_ids = [lid[0] for lid in success_links]
            rows = self._repo.get_outputs_by_email_ids(email_ids)
            subjects = {eid: self._repo.get_email_subject_by_id(eid) for eid in email_ids}
            senders = {eid: self._repo.get_email_sender_by_id(eid) for eid in email_ids}

            try:
                html = self._compose_with_quality_gate(rows, subjects, senders)
            except QualityGateFailedException as exc:
                self._repo.update_digest_body(digest_id, body_html=exc.last_html)
                self._repo.update_digest_status(
                    digest_id,
                    DIGEST_STATUS_ERROR,
                    error_message="quality_gate: " + "; ".join(exc.problems),
                )
                return True

            self._repo.update_digest_body(digest_id, body_html=html)

            try:
                self._sender.send_html(
                    to=self._digest_to,
                    subject=self._digest_title(),
                    html=html,
                )
            except Exception as exc:
                self._repo.update_digest_status(
                    digest_id,
                    DIGEST_STATUS_SEND_FAILED,
                    error_message=f"send_failed: {exc}",
                )
                return True

            self._repo.update_digest_status(digest_id, DIGEST_STATUS_SENT)
            for email_id, message_id, _categories in success_links:
                self._labeler.add_labels(
                    message_id,
                    [PROCESSED_LABEL],
                    remove=[INBOX_LABEL],
                )
                self._repo.update_email_status(email_id, "archived")
            for skipped in skipped_links:
                self._labeler.add_labels(
                    skipped.message_id,
                    [PROCESSED_LABEL],
                    remove=[INBOX_LABEL],
                )
                self._repo.update_email_status(skipped.email_id, "skipped")

            return True

        finally:
            self._run_lock.release()

    def _digest_title(self) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{self._subject_prefix} — {day}"

    def _merge_candidates(self):
        seen: set[int] = set()
        out = []
        for pe in self._repo.fetch_unprocessed_emails():
            if pe.id not in seen:
                seen.add(pe.id)
                out.append(pe)
        for pe in self._repo.fetch_retryable_errors():
            if pe.id not in seen:
                seen.add(pe.id)
                out.append(pe)
        return out

    def _process_one_email(
        self,
        email_id: int,
        message_id: str,
        digest_id: int,
    ) -> ProcessLink | SkippedEmailLink | None:
        if self._uses_map_reduce_radar(email_id, message_id):
            return self._process_map_reduce_radar_email(email_id, message_id, digest_id)

        if self._enable_content_unit_routing and self._content_unit_classifier is not None:
            return self._process_content_unit_email(email_id, message_id, digest_id)

        reuse = self._repo.try_reuse_complete_outputs(email_id)
        if reuse is not None:
            self._repo.attach_email_to_digest(digest_id, email_id)
            return (email_id, message_id, reuse)
        try:
            html = self._fetcher.fetch_message_html(message_id)
            parsed = parse_newsletter_html(html)
            subject = self._repo.get_email_subject_by_id(email_id)

            merged_sections = normalize_sections_for_routing(parsed)
            section_records = self._repo.replace_email_sections(email_id, merged_sections)
            by_key: dict[str, EmailSection] = {s.section_id.strip(): s for s in merged_sections}

            categories: set[RouteCategory] = set()

            for sr in sorted(section_records, key=lambda r: (r.order_index, r.id)):
                sec = by_key.get(sr.section_key)
                if sec is None:
                    raise RuntimeError(f"section_key {sr.section_key!r} missing from merged sections")

                if self._reuse_section_processor_if_cached(email_id, sr):
                    cats = self._load_cached_router_category(email_id, sr.id)
                    if cats is None:
                        raise RuntimeError("cached processors without router slice")
                    categories.add(cats)
                    continue

                decision = self._router.run(subject=subject, plain_text=sec.text, section_heading=sec.heading)
                self._repo.save_agent_output(
                    email_id,
                    "router",
                    decision,
                    email_section_id=sr.id,
                    category=decision.category.value,
                )

                proc_kind = PROCESSOR_OUTPUT_KIND[decision.category]
                if decision.category == RouteCategory.TECHNOLOGY:
                    proc_out = self._technology.run_section(
                        sec,
                        subject=subject,
                        parsed_fallback=parsed,
                    )
                elif decision.category == RouteCategory.RADAR:
                    proc_out = self._radar.run_section(sec, subject=subject)
                elif decision.category == RouteCategory.LEADERSHIP:
                    proc_out = self._leadership.run_section(
                        sec,
                        subject=subject,
                        parsed_fallback=parsed,
                    )
                elif decision.category == RouteCategory.COURSES:
                    proc_out = self._courses.run_section(
                        sec,
                        subject=subject,
                        parsed_fallback=parsed,
                    )
                else:
                    raise AssertionError(f"unexpected router category: {decision.category!r}")

                self._repo.save_agent_output(
                    email_id,
                    proc_kind,
                    proc_out,
                    email_section_id=sr.id,
                    category=decision.category.value,
                )
                categories.add(decision.category)

            self._repo.attach_email_to_digest(digest_id, email_id)
            return (email_id, message_id, frozenset(categories))
        except Exception as exc:
            self._repo.update_email_status(
                email_id,
                "failed",
                error_message=str(exc),
                increment_retry=True,
            )
            return None

    def _uses_map_reduce_radar(self, email_id: int, message_id: str) -> bool:
        if self._map_reduce is None or not self._map_reduce_senders:
            return False
        sender = self._repo.get_email_sender_by_id(email_id)
        if not sender:
            sender = self._fetcher.fetch_message_sender(message_id)
        return sender_matches_map_reduce(sender, self._map_reduce_senders)

    def _process_map_reduce_radar_email(
        self,
        email_id: int,
        message_id: str,
        digest_id: int,
    ) -> ProcessLink | None:
        if self._repo.map_reduce_radar_digest_cached(email_id):
            self._repo.attach_email_to_digest(digest_id, email_id)
            return (email_id, message_id, frozenset({RouteCategory.RADAR}))

        assert self._map_reduce is not None
        try:
            html = self._fetcher.fetch_message_html(message_id)
            parsed = parse_newsletter_html(html)
            subject = self._repo.get_email_subject_by_id(email_id)

            self._repo.replace_email_sections(email_id, parsed.sections)
            self._repo.clear_section_scoped_agent_outputs(email_id)

            digest_out = self._map_reduce.run(parsed, subject=subject)
            self._repo.save_agent_output(
                email_id,
                MAP_REDUCE_RADAR_DIGEST_KIND,
                digest_out,
                email_section_id=None,
                category=RouteCategory.RADAR.value,
            )
            self._repo.attach_email_to_digest(digest_id, email_id)
            return (email_id, message_id, frozenset({RouteCategory.RADAR}))
        except Exception as exc:
            self._repo.update_email_status(
                email_id,
                "failed",
                error_message=str(exc),
                increment_retry=True,
            )
            return None

    def _resolve_profile_plan(
        self,
        *,
        parsed: ParsedHtmlResult,
        sender: str | None,
    ) -> ProfileRunPlan | None:
        profile = lookup_sender_profile(sender)
        if profile is None:
            return None
        return resolve_profile_plan(profile, parsed)

    def _persist_shape_decision(self, email_id: int, grouping: GroupingResult) -> None:
        if grouping.shape_profile_id is None or grouping.digest_shape is None:
            return
        self._repo.save_newsletter_shape_decision(
            email_id,
            profile_id=grouping.shape_profile_id,
            digest_shape=grouping.digest_shape,
            digest_excluded_section_keys=grouping.digest_excluded_section_keys,
            distinct_canonical_story_urls=grouping.distinct_canonical_story_urls,
            substantive_article_chars=grouping.substantive_article_chars,
            merged_section_keys=grouping.merged_section_keys,
        )

    def _process_content_unit_email(
        self,
        email_id: int,
        message_id: str,
        digest_id: int,
    ) -> ProcessLink | SkippedEmailLink | None:
        assert self._content_unit_classifier is not None

        reuse = self._repo.try_reuse_complete_outputs(email_id)
        if reuse is not None:
            self._repo.attach_email_to_digest(digest_id, email_id)
            return (email_id, message_id, reuse)

        try:
            html = self._fetcher.fetch_message_html(message_id)
            parsed = parse_newsletter_html(html)
            subject = self._repo.get_email_subject_by_id(email_id)
            sender = self._repo.get_email_sender_by_id(email_id)

            self._repo.replace_email_sections(email_id, parsed.sections)
            self._repo.clear_section_scoped_agent_outputs(email_id)

            profile_plan = self._resolve_profile_plan(parsed=parsed, sender=sender)
            if profile_plan is not None:
                section_records = self._repo.list_email_sections(email_id)
                section_hashes = {rec.section_key: rec.content_hash for rec in section_records}
                merged_hash = compute_profile_merged_content_hash(
                    profile_plan,
                    section_hashes=section_hashes,
                )
                processor_kind = profile_processor_output_kind(profile_plan.profile)
                unit_key = profile_plan.article_unit.content_unit_key

                if self._repo.profile_unit_outputs_cached(
                    email_id,
                    content_unit_key=unit_key,
                    processor_kind=processor_kind,
                    merged_content_hash=merged_hash,
                ):
                    self._repo.clear_orphan_content_unit_outputs(
                        email_id,
                        keep_content_unit_key=unit_key,
                    )
                    self._repo.attach_email_to_digest(digest_id, email_id)
                    return (email_id, message_id, frozenset({profile_plan.profile.default_category}))

                stale_classifier = self._repo.get_latest_agent_output_for_unit_kind(
                    email_id,
                    content_unit_key=unit_key,
                    kind="classifier",
                )
                if stale_classifier is not None:
                    self._repo.clear_profile_unit_outputs(
                        email_id,
                        content_unit_key=unit_key,
                        processor_kind=processor_kind,
                    )
                self._repo.clear_orphan_content_unit_outputs(
                    email_id,
                    keep_content_unit_key=unit_key,
                )

                category = self._process_profile_article_unit(
                    email_id,
                    profile_plan,
                    parsed=parsed,
                    subject=subject,
                    merged_content_hash=merged_hash,
                    processor_kind=processor_kind,
                )
                self._repo.attach_email_to_digest(digest_id, email_id)
                return (email_id, message_id, frozenset({category}))

            grouping = group_content_units(
                parsed.sections,
                original_url=parsed.original_url,
                sender=sender,
            )

            if grouping.digest_shape == "teaser_paywall" and not grouping.units:
                self._persist_shape_decision(email_id, grouping)
                self._repo.update_email_status(email_id, "skipped")
                return SkippedEmailLink(email_id, message_id)

            if grouping.shape_profile_id is not None:
                self._persist_shape_decision(email_id, grouping)

            units = self._resolve_content_units(
                email_id=email_id,
                parsed=parsed,
                subject=subject,
                sender=sender,
                grouping=grouping,
            )

            categories: set[RouteCategory] = set()
            for unit in units:
                category = self._process_one_content_unit(
                    email_id,
                    unit,
                    parsed=parsed,
                    subject=subject,
                    grouping=grouping,
                )
                categories.add(category)

            self._repo.attach_email_to_digest(digest_id, email_id)
            return (email_id, message_id, frozenset(categories))
        except Exception as exc:
            self._repo.update_email_status(
                email_id,
                "failed",
                error_message=str(exc),
                increment_retry=True,
            )
            return None

    def _process_one_content_unit(
        self,
        email_id: int,
        unit: ContentUnit,
        *,
        parsed: ParsedHtmlResult,
        subject: str | None,
        grouping: GroupingResult | None,
    ) -> RouteCategory:
        classification = classify_content_unit(
            unit,
            outline=grouping,
            prior=None,
            sanity=None,
            classifier_agent=self._content_unit_classifier,
            parsed=parsed,
        )
        band = apply_confidence_band(classification)
        self._repo.save_agent_output(
            email_id,
            "classifier",
            band.result,
            content_unit_key=unit.content_unit_key,
            category=band.result.category.value,
        )
        if band.action == ConfidenceBandAction.FAIL:
            raise RuntimeError(
                f"classification_failed: confidence {band.result.confidence:.2f} "
                f"for unit {unit.content_unit_key!r}",
            )

        dispatch = self._processor_dispatcher.dispatch_unit(
            category=band.result.category,
            unit=unit,
            subject=subject,
            parsed_fallback=parsed,
        )
        self._repo.save_agent_output(
            email_id,
            dispatch.kind,
            dispatch.output,
            content_unit_key=unit.content_unit_key,
            category=band.result.category.value,
        )
        return band.result.category

    def _process_profile_article_unit(
        self,
        email_id: int,
        plan: ProfileRunPlan,
        *,
        parsed: ParsedHtmlResult,
        subject: str | None,
        merged_content_hash: str,
        processor_kind: str,
    ) -> RouteCategory:
        profile = plan.profile
        unit = plan.article_unit
        category = profile.default_category

        cap_key = category.value.lower()
        card_cap = profile.maximum_digest_cards.get(cap_key)
        if card_cap is not None and card_cap < 1:
            raise RuntimeError(
                f"profile_invariant_violation: maximum_digest_cards for {category.value!r} is {card_cap}",
            )

        classification = ContentUnitClassificationResult(
            category=category,
            confidence=CONFIDENCE_HARD_OVERRIDE,
            rationale=f"Sender profile {profile.sender_email!r} forces {category.value}.",
            primary_value=f"Profile fast path ({profile.strategy.value}).",
            evidence=[f"section_keys={unit.section_keys}"],
            routing_source=ClassificationRoutingSource.SENDER_PROFILE,
            sender_profile=profile.sender_email,
            grouping_strategy=profile.strategy.value,
            content_hash=merged_content_hash,
            processor_kind=processor_kind,
        )
        self._repo.save_agent_output(
            email_id,
            "classifier",
            classification,
            content_unit_key=unit.content_unit_key,
            category=category.value,
        )

        dispatch = self._dispatch_profile_processor(
            profile,
            unit,
            subject=subject,
            parsed=parsed,
        )
        if dispatch.kind != processor_kind:
            raise RuntimeError(
                f"profile_invariant_violation: expected processor kind {processor_kind!r}, "
                f"got {dispatch.kind!r}",
            )
        self._repo.save_agent_output(
            email_id,
            dispatch.kind,
            dispatch.output,
            content_unit_key=unit.content_unit_key,
            category=category.value,
        )

        if card_cap is not None:
            proc_rows = self._repo.connection.execute(
                """
                SELECT COUNT(*) AS n FROM agent_outputs
                WHERE email_id = ? AND content_unit_key = ? AND kind = ? AND category = ?
                """,
                (email_id, unit.content_unit_key, processor_kind, category.value),
            ).fetchone()["n"]
            if int(proc_rows) > card_cap:
                raise RuntimeError(
                    f"profile_invariant_violation: {int(proc_rows)} {category.value} cards exceed "
                    f"maximum_digest_cards[{cap_key!r}]={card_cap}",
                )

        return category

    def _dispatch_profile_processor(
        self,
        profile,
        unit: ContentUnit,
        *,
        subject: str | None,
        parsed: ParsedHtmlResult,
    ) -> ProcessorDispatchResult:
        if profile.processor == "technology":
            return self._processor_dispatcher.dispatch_unit(
                category=RouteCategory.TECHNOLOGY,
                unit=unit,
                subject=subject,
                parsed_fallback=parsed,
            )
        if profile.processor == "leadership_essay":
            if self._leadership_essay is None:
                raise RuntimeError("leadership_essay_agent is required for leadership_essay profiles")
            output = self._leadership_essay.run_unit(
                unit,
                subject=subject,
                parsed_fallback=parsed,
            )
            return ProcessorDispatchResult(kind=LEADERSHIP_ESSAY_OUTPUT_KIND, output=output)
        if profile.processor == "technical_longform":
            if self._technical_longform is None:
                raise RuntimeError("technical_longform_agent is required for technical_longform profiles")
            output = self._technical_longform.run_unit(
                unit,
                subject=subject,
                parsed_fallback=parsed,
            )
            return ProcessorDispatchResult(kind=TECHNICAL_LONGFORM_OUTPUT_KIND, output=output)
        raise RuntimeError(f"unsupported profile processor: {profile.processor!r}")

    def _resolve_content_units(
        self,
        *,
        email_id: int,
        parsed: ParsedHtmlResult,
        subject: str | None,
        sender: str | None,
        grouping: GroupingResult,
    ) -> list[ContentUnit]:
        sections = parsed.sections
        if not grouping.ambiguous:
            return grouping.units

        conservative_groups = conservative_groups_for_run(
            sections,
            [section.section_id.strip() for section in sections if not is_hard_boundary_section(section)],
        )
        conservative_units = build_content_units_from_section_groups(
            assemble_final_groups(sections, conservative_groups),
        )
        hard_boundary_keys = [
            section.section_id.strip()
            for section in sections
            if is_hard_boundary_section(section)
        ]

        if self._boundary_classifier is None:
            self._persist_boundary_classification(
                email_id=email_id,
                grouping=grouping,
                deterministic_units=grouping.units,
                accepted_units=conservative_units,
                fallback_used=True,
                fallback_reason="llm_skipped_disabled",
                validation_errors=[],
                confidence=None,
                budget_status=BoundaryBudgetStatus.LLM_SKIPPED_DISABLED,
                outline_hashes=[],
                llm_units=None,
            )
            return conservative_units

        if grouping.non_promo_section_count > _BOUNDARY_MAX_SECTIONS:
            self._persist_boundary_classification(
                email_id=email_id,
                grouping=grouping,
                deterministic_units=grouping.units,
                accepted_units=conservative_units,
                fallback_used=True,
                fallback_reason="section_count_exceeded",
                validation_errors=[],
                confidence=None,
                budget_status=BoundaryBudgetStatus.SECTION_COUNT_EXCEEDED,
                outline_hashes=[],
                llm_units=None,
            )
            return conservative_units

        accepted_non_promo_groups: list[list[EmailSection]] = []
        outline_hashes: list[str] = []
        collected_llm_units = []
        fallback_used = False
        fallback_reason: str | None = None
        validation_errors: list[str] = []
        last_confidence: float | None = None
        budget_status = BoundaryBudgetStatus.OK

        section_by_key = {section.section_id.strip(): section for section in sections}

        for run in split_non_promo_runs(sections):
            run_keys = [section.section_id.strip() for section in run]
            if len(run) <= 1:
                for section in run:
                    accepted_non_promo_groups.append([section])
                continue

            outline = self._build_boundary_outline(run)
            outline_hashes.append(compute_outline_hash(outline))
            det_units = deterministic_units_for_run(grouping.units, run_keys)

            try:
                llm_output = self._boundary_classifier.classify_boundaries(
                    sender=sender,
                    subject=subject,
                    original_url=parsed.original_url,
                    sections=outline,
                    deterministic_units=det_units,
                    ambiguity_reasons=grouping.ambiguity_reasons,
                    hard_boundary_section_keys=hard_boundary_keys,
                )
            except Exception as exc:
                fallback_used = True
                fallback_reason = "llm_error"
                validation_errors.append(str(exc))
                accepted_non_promo_groups.extend([[section] for section in run])
                continue

            last_confidence = llm_output.confidence
            errors = validate_boundary_llm_output(
                llm_output,
                run_section_keys=run_keys,
                all_sections=sections,
            )
            if errors:
                fallback_used = True
                fallback_reason = "validation_failed"
                validation_errors.extend(errors)
                accepted_non_promo_groups.extend([[section] for section in run])
                continue

            if llm_output.confidence < _BOUNDARY_MIN_CONFIDENCE:
                fallback_used = True
                fallback_reason = "low_confidence"
                validation_errors.append(
                    f"low_confidence: {llm_output.confidence:.2f} < {_BOUNDARY_MIN_CONFIDENCE}",
                )
                accepted_non_promo_groups.extend([[section] for section in run])
                continue

            collected_llm_units.extend(llm_output.units)
            for llm_unit in llm_output.units:
                group = [section_by_key[key] for key in llm_unit.section_keys if key in section_by_key]
                if group:
                    accepted_non_promo_groups.append(group)

        final_groups = assemble_final_groups(sections, accepted_non_promo_groups)
        accepted_units = build_content_units_from_section_groups(final_groups)

        self._persist_boundary_classification(
            email_id=email_id,
            grouping=grouping,
            deterministic_units=grouping.units,
            accepted_units=accepted_units,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            validation_errors=validation_errors,
            confidence=last_confidence,
            budget_status=budget_status,
            outline_hashes=outline_hashes,
            llm_units=collected_llm_units or None,
        )
        return accepted_units

    def _build_boundary_outline(
        self,
        run: list[EmailSection],
    ) -> list[BoundaryOutlineSection]:
        outline: list[BoundaryOutlineSection] = []
        for section in run:
            snippet = (section.text or "")[:_BOUNDARY_SNIPPET_MAX_CHARS]
            primary_links = [
                str(link).strip()
                for link in section.links
                if str(link).strip().startswith("https://")
            ][:3]
            outline.append(
                BoundaryOutlineSection(
                    section_key=section.section_id.strip(),
                    heading=section.heading,
                    snippet=snippet,
                    char_count=len(section.text or ""),
                    link_count=len(section.links),
                    primary_links=primary_links,
                ),
            )
        return outline

    def _persist_boundary_classification(
        self,
        *,
        email_id: int,
        grouping: GroupingResult,
        deterministic_units: list[ContentUnit],
        accepted_units: list[ContentUnit],
        fallback_used: bool,
        fallback_reason: str | None,
        validation_errors: list[str],
        confidence: float | None,
        budget_status: BoundaryBudgetStatus,
        outline_hashes: list[str],
        llm_units,
    ) -> None:
        result = BoundaryClassificationResult(
            outline_hash=compute_composite_outline_hash(outline_hashes),
            deterministic_units=deterministic_units,
            llm_units=llm_units,
            accepted_units=accepted_units,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            validation_errors=validation_errors,
            confidence=confidence,
            ambiguity_reasons=grouping.ambiguity_reasons,
            budget_status=budget_status,
        )
        self._repo.save_agent_output(
            email_id,
            "boundary_classifier",
            result,
            email_section_id=None,
        )

    def _reuse_section_processor_if_cached(self, email_id: int, sr: EmailSectionRecord) -> bool:
        """Skip LLM when router + processor rows already exist for this DB section id."""

        router_row = self._repo.get_latest_agent_output_for_section_kind(
            email_id,
            section_id=sr.id,
            kind="router",
        )
        if router_row is None:
            return False
        try:
            decision = RouterDecision.model_validate_json(router_row.payload)
        except Exception:
            return False
        proc_kind = PROCESSOR_OUTPUT_KIND[decision.category]
        proc_row = self._repo.get_latest_agent_output_for_section_kind(
            email_id,
            section_id=sr.id,
            kind=proc_kind,
        )
        if proc_row is None and decision.category == RouteCategory.COURSES:
            proc_row = self._repo.get_latest_agent_output_for_section_kind(
                email_id,
                section_id=sr.id,
                kind="noise",
            )
        return proc_row is not None

    def _load_cached_router_category(self, email_id: int, section_id: int) -> RouteCategory | None:
        row = self._repo.get_latest_agent_output_for_section_kind(
            email_id,
            section_id=section_id,
            kind="router",
        )
        if row is None:
            return None
        try:
            return RouterDecision.model_validate_json(row.payload).category
        except Exception:
            return None

    def _compose_with_quality_gate(self, rows, subjects, senders):
        logged_comp_warnings: set[str] = set()

        def render(revision_problems):
            compose_out = self._composer.compose(
                rows,
                subjects,
                senders=senders,
                revision_problems=revision_problems,
            )
            for msg in compose_out.composition_warnings:
                if msg not in logged_comp_warnings:
                    logged_comp_warnings.add(msg)
                    _LOGGER.warning("%s", msg)
            return compose_out.html

        html = render(())
        max_attempts = self._max_quality_gate_attempts
        for attempt in range(max_attempts):
            result = self._quality_gate.check(html)
            if result.ok:
                return html
            problems = list(result.problems)
            if attempt >= max_attempts - 1:
                raise QualityGateFailedException(problems, last_html=html)
            html = render(problems)
        return html
