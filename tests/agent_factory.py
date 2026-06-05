"""Shared DailyDigestAgent construction for integration tests."""

from __future__ import annotations

from app.agents.ainews_radar_map_reduce_agent import AINewsRadarMapReduceAgent
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
from app.llm.client import LLMClient
from app.storage.repository import StateRepository
from app.storage.run_lock import RunLock
from tests.fakes import FakeGmailService


def build_daily_digest_agent(
    repo: StateRepository,
    lock: RunLock,
    svc: FakeGmailService,
    llm: LLMClient,
    *,
    gate: DigestQualityGateAgent | None = None,
    map_reduce_senders: tuple[str, ...] = ("swyx+ainews@substack.com",),
    chunk_target_chars: int = 14000,
    max_map_calls: int = 6,
) -> DailyDigestAgent:
    client = GmailClient(service_factory=lambda: svc)
    fetcher = GmailFetcher(client, senders=["newsletter@fixture.test"], max_results=20)
    return DailyDigestAgent(
        repo=repo,
        run_lock=lock,
        fetcher=fetcher,
        router_agent=RouterAgent(llm, model="m"),
        technology_agent=TechnologyProcessorAgent(llm, model="m"),
        radar_agent=RadarProcessorAgent(llm, model="m"),
        leadership_agent=LeadershipProcessorAgent(llm, model="m"),
        courses_agent=CoursesProcessorAgent(llm, model="m"),
        map_reduce_radar_agent=AINewsRadarMapReduceAgent(
            llm,
            model="m",
            chunk_target_chars=chunk_target_chars,
            max_map_calls=max_map_calls,
        ),
        map_reduce_radar_senders=map_reduce_senders,
        composer=DigestComposer(title="Test digest"),
        quality_gate=gate or DigestQualityGateAgent(),
        labeler=GmailLabeler(client),
        sender=GmailSender(client, sender="me@test"),
        digest_to="reader@test",
    )
