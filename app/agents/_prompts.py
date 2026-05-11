from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def format_newsletter_text(*, subject: str | None, plain_text: str) -> str:
    blocks: list[str] = []
    if subject:
        blocks.append(f"Subject: {subject}")
    blocks.append("Plain text:\n" + plain_text)
    return "\n\n".join(blocks)
