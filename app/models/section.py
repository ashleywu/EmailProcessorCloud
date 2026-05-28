"""Email sections produced by DOM-based sectionization prior to routing."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmailSection(BaseModel):
    """One contiguous slice of newsletter content (typically under a heading).

    **Authoritative section-scoped assets:** use ``links`` and ``image_urls`` for URL allowlists;
    ``text`` is human-readable prose only and does not embed full ``href`` or binary media.
    See ``docs/section-extraction.md``.
    """

    section_id: str = Field(
        ...,
        description='Stable handle within one email (e.g. ``"s0"``); pair with parent message id in logs.',
    )
    order_index: int = Field(..., ge=0, description="Zero-based reading order; aligns with ``section_id`` sequence.")
    heading: str | None = Field(
        default=None,
        description="Visible heading text when this slice started at an ``h1``–``h6`` node.",
    )
    text: str = Field(
        default="",
        description="LLM-readable plaintext for the slice; URL assets live in links/image_urls.",
    )
    links: list[str] = Field(
        default_factory=list,
        description="Authoritative section-scoped https links (from ``a[href]``), deduped in order.",
    )
    image_urls: list[str] = Field(
        default_factory=list,
        description="Authoritative section-scoped image URLs after absolutize + chrome filtering.",
    )
    email_id: str | None = Field(
        default=None,
        description="Filled when persisted; optional during parse-only sectionization.",
    )


__all__ = ["EmailSection"]
