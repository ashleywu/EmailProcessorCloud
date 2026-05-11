"""Paragraph-oriented chunk splits for eventual LLM calls."""

from __future__ import annotations


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split prose into contiguous chunks respecting ``\\n\\n`` paragraph seams first.

    Important: callers that feed plain text into model APIs with bounded context windows must
    run this helper whenever ``len(parsed.plain_text)`` exceeds those limits rather than slicing
    the string manually.
    """

    if max_chars <= 0:
        return []

    normalized = text.strip()
    if not normalized:
        return []

    paragraphs: list[str] = []
    blocks = normalized.split("\n\n")
    for blk in blocks:
        piece = blk.strip()
        if piece:
            paragraphs.append(piece)
    if not paragraphs:
        paragraphs = [line for line in normalized.split("\n") if line.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []

    buffer = ""
    for para in paragraphs:
        if buffer:
            tentative = buffer + "\n\n" + para
        else:
            tentative = para

        if len(tentative) <= max_chars:
            buffer = tentative
            continue

        if buffer:
            chunks.append(buffer.strip())

        # Oversized paragraphs get word-wrapped progressively.
        if len(para) <= max_chars:
            buffer = para
        else:
            for slab in _split_oversized_block(para, max_chars=max_chars):
                chunks.append(slab)
            buffer = ""

    if buffer:
        chunks.append(buffer.strip())

    return [chunk for chunk in chunks if chunk]


def _split_oversized_block(para: str, *, max_chars: int) -> list[str]:
    parts: list[str] = []
    cursor = para.strip()
    while cursor:
        if len(cursor) <= max_chars:
            parts.append(cursor)
            break
        window = cursor[:max_chars]
        boundary = window.rfind(" ")
        slice_end = boundary if boundary > max_chars * 6 // 10 else max_chars
        fragment = cursor[:slice_end].rstrip()
        if not fragment:
            fragment = cursor[:max_chars]
            slice_end = max_chars
        parts.append(fragment.strip())
        cursor = cursor[len(fragment) :].strip()
    return parts
