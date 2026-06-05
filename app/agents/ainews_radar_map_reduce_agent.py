from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence

from app.agents._prompts import format_newsletter_text, load_prompt
from app.llm.client import LLMClient
from app.models.outputs import (
    AINewsRadarCardRole,
    AINewsRadarDigestCard,
    AINewsRadarDigestOutput,
    AINewsRadarFact,
    AINewsRadarHeroCardOutput,
    AINewsRadarMapResult,
    AINewsRadarRecapCardsOutput,
)
from app.models.section import EmailSection
from app.parsing.ainews_boundaries import (
    format_sections_for_llm,
    split_ainews_sections,
)
from app.parsing.map_reduce_chunks import MapReduceChunk, chunk_sections_for_map
from app.parsing.parser import ParsedHtmlResult

_LOGGER = logging.getLogger(__name__)

_SPONSOR_NOISE_RE = re.compile(
    r"\b(sponsor(?:ed)?|advertisement|subscribe\s+to|unsubscribe|referral\s+link)\b",
    re.IGNORECASE,
)

_MAX_FACTS_FOR_REDUCE = 80
_MAX_RECAP_CARDS = 2
_MAX_TOTAL_CARDS = 3


def _format_map_chunk_input(*, subject: str | None, chunk: MapReduceChunk) -> str:
    blocks: list[str] = []
    if subject is not None and str(subject).strip():
        blocks.append(f"Subject: {str(subject).strip()}")
    blocks.append(f"Chunk plain text:\n{chunk.text}")
    return "\n\n".join(blocks)


def _format_section_block_input(*, subject: str | None, label: str, plain: str) -> str:
    blocks: list[str] = []
    if subject is not None and str(subject).strip():
        blocks.append(f"Subject: {str(subject).strip()}")
    blocks.append(f"{label}:\n{plain}")
    return "\n\n".join(blocks)


def _is_noise_fact(fact: AINewsRadarFact) -> bool:
    if fact.importance_score <= 2:
        return True
    blob = f"{fact.entity} {fact.fact}"
    return _SPONSOR_NOISE_RE.search(blob) is not None


def _facts_for_reduce(facts: list[AINewsRadarFact]) -> list[AINewsRadarFact]:
    kept = [f for f in facts if not _is_noise_fact(f)]
    kept.sort(key=lambda f: (-f.importance_score, f.entity))
    return kept[:_MAX_FACTS_FOR_REDUCE]


def _format_reduce_input(*, subject: str | None, facts: list[AINewsRadarFact]) -> str:
    payload = json.dumps([f.model_dump() for f in facts], ensure_ascii=False)
    blocks: list[str] = []
    if subject is not None and str(subject).strip():
        blocks.append(f"Subject: {str(subject).strip()}")
    blocks.append(f"Facts JSON:\n{payload}")
    return "\n\n".join(blocks)


def _ensure_card_role(card: AINewsRadarDigestCard, role: AINewsRadarCardRole) -> AINewsRadarDigestCard:
    if card.role == role:
        return card
    return card.model_copy(update={"role": role})


class AINewsRadarMapReduceAgent:
    """RADAR-only hybrid synthesizer for AINews: Top Story hero + optional Recap map-reduce."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        model: str,
        chunk_target_chars: int = 14000,
        max_map_calls: int = 6,
    ) -> None:
        self._llm = llm
        self._model = model
        self._chunk_target_chars = chunk_target_chars
        self._max_map_calls = max_map_calls
        self._map_prompt = load_prompt("ainews_radar_map")
        self._hero_prompt = load_prompt("ainews_radar_hero")
        self._reduce_prompt = load_prompt("ainews_radar_reduce")
        self._recap_reduce_prompt = load_prompt("ainews_radar_reduce_recap")

    def run(
        self,
        parsed: ParsedHtmlResult,
        *,
        subject: str | None = None,
    ) -> AINewsRadarDigestOutput:
        sections = list(parsed.sections)
        if not sections:
            return self._run_full_issue_plaintext(parsed, subject=subject)

        split = split_ainews_sections(sections)
        _LOGGER.info(
            "ainews_split has_boundary=%s hero=%s recap=%s boundary_heading=%r",
            split.has_boundary,
            len(split.hero_sections),
            len(split.recap_sections),
            split.boundary_heading,
        )

        if not split.has_boundary:
            return self._run_full_issue_sections(sections, subject=subject)

        cards: list[AINewsRadarDigestCard] = []
        if split.hero_sections:
            cards.append(self._synthesize_top_story(split.hero_sections, subject=subject))
        cards.extend(self._synthesize_recap_cards(split.recap_sections, subject=subject))

        if not cards:
            return self._run_full_issue_sections(sections, subject=subject)

        return AINewsRadarDigestOutput(cards=cards[:_MAX_TOTAL_CARDS])

    def _synthesize_top_story(
        self,
        hero_sections: tuple[EmailSection, ...] | list[EmailSection],
        *,
        subject: str | None,
    ) -> AINewsRadarDigestCard:
        body = _format_section_block_input(
            subject=subject,
            label="Hero sections plain text",
            plain=format_sections_for_llm(hero_sections),
        )
        out = self._llm.structured_output(
            self._hero_prompt,
            body,
            AINewsRadarHeroCardOutput,
            model=self._model,
        )
        return _ensure_card_role(out.card, AINewsRadarCardRole.TOP_STORY)

    def _map_facts_for_sections(
        self,
        sections: Sequence[EmailSection],
        *,
        subject: str | None,
        max_map_calls: int | None = None,
    ) -> list[AINewsRadarFact]:
        cap = max_map_calls if max_map_calls is not None else self._max_map_calls
        if not sections:
            return []
        chunks = chunk_sections_for_map(
            sections,
            target_chars=self._chunk_target_chars,
            max_chunks=cap,
        )
        facts: list[AINewsRadarFact] = []
        for chunk in chunks:
            body = _format_map_chunk_input(subject=subject, chunk=chunk)
            map_result = self._llm.structured_output(
                self._map_prompt,
                body,
                AINewsRadarMapResult,
                model=self._model,
            )
            facts.extend(map_result.facts)
        return facts

    def _synthesize_recap_cards(
        self,
        recap_sections: tuple[EmailSection, ...] | list[EmailSection],
        *,
        subject: str | None,
    ) -> list[AINewsRadarDigestCard]:
        if not recap_sections:
            return []

        facts = self._map_facts_for_sections(
            recap_sections,
            subject=subject,
            max_map_calls=self._max_map_calls,
        )
        reduce_facts = _facts_for_reduce(facts)
        if not reduce_facts:
            return []

        reduce_body = _format_reduce_input(subject=subject, facts=reduce_facts)
        recap_out = self._llm.structured_output(
            self._recap_reduce_prompt,
            reduce_body,
            AINewsRadarRecapCardsOutput,
            model=self._model,
        )
        return [
            _ensure_card_role(c, AINewsRadarCardRole.RECAP)
            for c in recap_out.cards[:_MAX_RECAP_CARDS]
        ]

    def _run_full_issue_sections(
        self,
        sections: list[EmailSection],
        *,
        subject: str | None,
    ) -> AINewsRadarDigestOutput:
        facts = self._map_facts_for_sections(sections, subject=subject)
        reduce_facts = _facts_for_reduce(facts)
        if not reduce_facts:
            reduce_facts = sorted(facts, key=lambda f: -f.importance_score)[:10]

        reduce_body = _format_reduce_input(subject=subject, facts=reduce_facts)
        out = self._llm.structured_output(
            self._reduce_prompt,
            reduce_body,
            AINewsRadarDigestOutput,
            model=self._model,
        )
        return AINewsRadarDigestOutput(cards=out.cards[:_MAX_TOTAL_CARDS])

    def _run_full_issue_plaintext(
        self,
        parsed: ParsedHtmlResult,
        *,
        subject: str | None,
    ) -> AINewsRadarDigestOutput:
        body = format_newsletter_text(subject=subject, plain_text=parsed.plain_text)
        map_result = self._llm.structured_output(
            self._map_prompt,
            body,
            AINewsRadarMapResult,
            model=self._model,
        )
        reduce_facts = _facts_for_reduce(list(map_result.facts))
        if not reduce_facts:
            reduce_facts = list(map_result.facts)[:10]
        reduce_body = _format_reduce_input(subject=subject, facts=reduce_facts)
        out = self._llm.structured_output(
            self._reduce_prompt,
            reduce_body,
            AINewsRadarDigestOutput,
            model=self._model,
        )
        return AINewsRadarDigestOutput(cards=out.cards[:_MAX_TOTAL_CARDS])
