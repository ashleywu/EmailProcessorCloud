"""Parse newsletter From headers and match map-reduce radar senders."""

from __future__ import annotations

import re
from collections.abc import Sequence
from email.utils import parseaddr

_ANGLE_ADDR_RE = re.compile(r"<([^>]+)>")


def normalize_sender_email(from_header: str | None) -> str | None:
    """Extract and normalize the mailbox from a From header."""

    if from_header is None:
        return None
    raw = str(from_header).strip()
    if not raw:
        return None

    _display, addr = parseaddr(raw)
    candidate = (addr or "").strip()
    if not candidate:
        m = _ANGLE_ADDR_RE.search(raw)
        if m:
            candidate = m.group(1).strip()
        elif "@" in raw and " " not in raw.split("@", 1)[0][-20:]:
            candidate = raw

    if not candidate or "@" not in candidate:
        return None
    return candidate.lower()


def normalize_sender_allowlist(senders: Sequence[str]) -> frozenset[str]:
    out: set[str] = set()
    for spec in senders:
        norm = normalize_sender_email(spec) or str(spec).strip().lower()
        if norm and "@" in norm:
            out.add(norm)
    return frozenset(out)


def sender_matches_map_reduce(
    from_header: str | None,
    allowed: Sequence[str],
) -> bool:
    """Return True when the From header mailbox is in the normalized allowlist."""

    email = normalize_sender_email(from_header)
    if email is None:
        return False
    return email in normalize_sender_allowlist(allowed)
