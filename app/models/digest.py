from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DigestRecord(BaseModel):
    """Persisted digest row shape."""

    id: int
    status: str
    title: str | None = None
    body_html: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProcessedEmail(BaseModel):
    """Email after pipeline steps; ties DB id to business ids and optional digest."""

    id: int = Field(..., ge=1)
    message_id: str
    status: str
    digest_id: int | None = None
    retry_count: int = 0
    error_message: str | None = None
    updated_at: datetime | None = None
