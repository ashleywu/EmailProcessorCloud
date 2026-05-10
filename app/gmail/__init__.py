"""Gmail integration layer (Milestone 2).

Exposes a thin, mockable wrapper around the Gmail API split into four
collaborators: `GmailClient` for auth/transport, `GmailFetcher` for
inbound newsletter retrieval, `GmailLabeler` for taxonomy/archival,
and `GmailSender` for outbound digest delivery.
"""

from app.gmail.client import GmailClient
from app.gmail.fetcher import GmailFetcher, GmailMessage
from app.gmail.labeler import (
    ERROR_LABEL,
    PROCESSED_LABEL,
    GmailLabeler,
)
from app.gmail.sender import GmailSender, build_html_message

__all__ = [
    "ERROR_LABEL",
    "PROCESSED_LABEL",
    "GmailClient",
    "GmailFetcher",
    "GmailLabeler",
    "GmailMessage",
    "GmailSender",
    "build_html_message",
]
