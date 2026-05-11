from __future__ import annotations

from datetime import datetime, timezone

from app.agents.leadership_agent import LeadershipProcessorAgent
from app.agents.noise_agent import NoiseProcessorAgent
from app.agents.radar_agent import RadarProcessorAgent
from app.agents.router_agent import RouterAgent
from app.agents.technology_agent import TechnologyProcessorAgent
from app.digest.composer import DigestComposer
from app.digest.exceptions import QualityGateFailedException
from app.digest.quality_gate import DigestQualityGateAgent
from app.gmail.fetcher import GmailFetcher
from app.gmail.labeler import GmailLabeler
from app.gmail.sender import GmailSender
from app.models.outputs import PROCESSOR_OUTPUT_KIND, RouteCategory
from app.parsing.parser import parse_newsletter_html
from app.storage.repository import StateRepository
from app.storage.run_lock import RunLock

_MAX_QUALITY_ATTEMPTS = 3

DIGEST_STATUS_DRAFT = "draft"
DIGEST_STATUS_SENT = "sent"
DIGEST_STATUS_EMPTY = "empty"
DIGEST_STATUS_ERROR = "error"
DIGEST_STATUS_SEND_FAILED = "send_failed"


class DailyDigestAgent:
    """Orchestrates fetch → parse → route → processors → compose → quality gate → send → label/archive."""

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
        noise_agent: NoiseProcessorAgent,
        composer: DigestComposer,
        quality_gate: DigestQualityGateAgent,
        labeler: GmailLabeler,
        sender: GmailSender,
        digest_to: str,
        digest_subject_prefix: str = "Daily digest",
        lock_owner: str | None = None,
    ) -> None:
        self._repo = repo
        self._run_lock = run_lock
        self._fetcher = fetcher
        self._router = router_agent
        self._technology = technology_agent
        self._radar = radar_agent
        self._leadership = leadership_agent
        self._noise = noise_agent
        self._composer = composer
        self._quality_gate = quality_gate
        self._labeler = labeler
        self._sender = sender
        self._digest_to = digest_to
        self._subject_prefix = digest_subject_prefix
        self._lock_owner = lock_owner

    def run_daily(self) -> None:
        acquired = self._run_lock.acquire(owner=self._lock_owner)
        if not acquired:
            return
        digest_id: int | None = None
        success_links: list[tuple[int, str, RouteCategory]] = []
        try:
            candidates = self._merge_candidates()
            if not candidates:
                return

            digest_id = self._repo.create_digest(
                status=DIGEST_STATUS_DRAFT,
                title=self._digest_title(),
            )
            for pe in candidates:
                link = self._process_one_email(pe.id, pe.message_id, digest_id)
                if link is not None:
                    success_links.append(link)

            if not success_links:
                self._repo.update_digest_status(digest_id, DIGEST_STATUS_EMPTY)
                return

            email_ids = [lid[0] for lid in success_links]
            rows = self._repo.get_outputs_by_email_ids(email_ids)
            subjects = {eid: self._repo.get_email_subject_by_id(eid) for eid in email_ids}

            try:
                html = self._compose_with_quality_gate(rows, subjects)
            except QualityGateFailedException as exc:
                self._repo.update_digest_body(digest_id, body_html=exc.last_html)
                self._repo.update_digest_status(
                    digest_id,
                    DIGEST_STATUS_ERROR,
                    error_message="quality_gate: " + "; ".join(exc.problems),
                )
                return

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
                return

            self._repo.update_digest_status(digest_id, DIGEST_STATUS_SENT)
            for email_id, message_id, category in success_links:
                self._labeler.add_category(message_id, category)
                self._labeler.mark_processed(message_id)
                self._labeler.archive(message_id)
                self._repo.update_email_status(email_id, "archived")

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
    ) -> tuple[int, str, RouteCategory] | None:
        reuse = self._repo.try_reuse_complete_outputs(email_id)
        if reuse is not None:
            self._repo.attach_email_to_digest(digest_id, email_id)
            return (email_id, message_id, reuse)
        try:
            html = self._fetcher.fetch_message_html(message_id)
            parsed = parse_newsletter_html(html)
            subject = self._repo.get_email_subject_by_id(email_id)
            decision = self._router.run(subject=subject, plain_text=parsed.plain_text)
            self._repo.save_agent_output(email_id, "router", decision)
            proc_kind = PROCESSOR_OUTPUT_KIND[decision.category]
            if decision.category == RouteCategory.TECHNOLOGY:
                proc_out = self._technology.run(parsed, subject=subject)
            elif decision.category == RouteCategory.RADAR:
                proc_out = self._radar.run(subject=subject, plain_text=parsed.plain_text)
            elif decision.category == RouteCategory.LEADERSHIP:
                proc_out = self._leadership.run(subject=subject, plain_text=parsed.plain_text)
            else:
                proc_out = self._noise.run(subject=subject, plain_text=parsed.plain_text)
            self._repo.save_agent_output(email_id, proc_kind, proc_out)
            self._repo.attach_email_to_digest(digest_id, email_id)
            return (email_id, message_id, decision.category)
        except Exception as exc:
            self._repo.update_email_status(
                email_id,
                "failed",
                error_message=str(exc),
                increment_retry=True,
            )
            return None

    def _compose_with_quality_gate(self, rows, subjects):
        problems: list[str] = []
        html = self._composer.compose(rows, subjects, revision_problems=())
        for attempt in range(_MAX_QUALITY_ATTEMPTS):
            result = self._quality_gate.check(html)
            if result.ok:
                return html
            problems = list(result.problems)
            if attempt >= _MAX_QUALITY_ATTEMPTS - 1:
                raise QualityGateFailedException(problems, last_html=html)
            html = self._composer.compose(rows, subjects, revision_problems=problems)
