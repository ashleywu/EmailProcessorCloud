from __future__ import annotations

from app.models.content_units import (
    ConfidenceBandAction,
    ConfidenceBandResult,
    ContentUnitClassificationResult,
)

CLASSIFIER_CONFIDENCE_PROCESS = 0.75
CLASSIFIER_CONFIDENCE_MIN = 0.55
CONFIDENCE_HARD_OVERRIDE = 1.0
CONFIDENCE_SENDER_PRIOR = 0.9
CONFIDENCE_HEURISTIC_STRONG = 0.85
CONFIDENCE_HEURISTIC_WEAK = 0.65

WARNING_CLASSIFICATION_LOW_CONFIDENCE = "classification_low_confidence"


def apply_confidence_band(result: ContentUnitClassificationResult) -> ConfidenceBandResult:
    warnings = list(result.warnings)
    action = ConfidenceBandAction.PROCESS

    if result.confidence < CLASSIFIER_CONFIDENCE_MIN:
        action = ConfidenceBandAction.FAIL
    elif result.confidence < CLASSIFIER_CONFIDENCE_PROCESS:
        action = ConfidenceBandAction.WARN
        if WARNING_CLASSIFICATION_LOW_CONFIDENCE not in warnings:
            warnings.append(WARNING_CLASSIFICATION_LOW_CONFIDENCE)

    updated = result.model_copy(update={"warnings": warnings})
    return ConfidenceBandResult(action=action, result=updated)


__all__ = [
    "CLASSIFIER_CONFIDENCE_MIN",
    "CLASSIFIER_CONFIDENCE_PROCESS",
    "CONFIDENCE_HARD_OVERRIDE",
    "CONFIDENCE_HEURISTIC_STRONG",
    "CONFIDENCE_HEURISTIC_WEAK",
    "CONFIDENCE_SENDER_PRIOR",
    "WARNING_CLASSIFICATION_LOW_CONFIDENCE",
    "apply_confidence_band",
]
