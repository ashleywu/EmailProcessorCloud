from __future__ import annotations


class QualityGateFailedException(Exception):
    """Raised when digest HTML still fails the quality gate after all rewrite attempts."""

    def __init__(self, problems: list[str], *, last_html: str) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems
        self.last_html = last_html
