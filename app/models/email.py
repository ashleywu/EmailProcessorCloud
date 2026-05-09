from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EmailInput(BaseModel):
    """Inbound newsletter row used for upsert into SQLite."""

    message_id: str = Field(..., min_length=1, description="Provider-unique message id")
    subject: str | None = None
    body_preview: str | None = None
    received_at: datetime | None = None
