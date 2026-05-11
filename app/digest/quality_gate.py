from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    ok: bool
    problems: list[str]


class DigestQualityGateAgent:
    """Deterministic HTML checks (no LLM) for stable tests."""

    def __init__(self, *, min_chars: int = 120) -> None:
        self._min_chars = min_chars

    def check(self, html: str) -> QualityGateResult:
        problems: list[str] = []
        low = html.lower()
        if "\x00" in html:
            problems.append("nul_byte")
        if "<script" in low:
            problems.append("forbidden_script_tag")
        if "<html" not in low:
            problems.append("missing_html_root")
        if "</html>" not in low:
            problems.append("missing_html_close")
        if len(html.strip()) < self._min_chars:
            problems.append("body_too_short")
        # Suspicious raw template leakage (very coarse)
        if "{{" in html or "{%" in html:
            problems.append("unrendered_template_markup")
        return QualityGateResult(ok=len(problems) == 0, problems=problems)
