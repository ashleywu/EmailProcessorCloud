"""Mixed newsletter shape profiles (Every, Turing Post, …)."""

from app.processing.newsletter_shape.profile import DigestEmailShape, NewsletterShapeDecision
from app.processing.newsletter_shape.registry import lookup_newsletter_shape_profile
from app.processing.newsletter_shape.shape_classifier import classify_newsletter_shape

__all__ = [
    "DigestEmailShape",
    "NewsletterShapeDecision",
    "classify_newsletter_shape",
    "lookup_newsletter_shape_profile",
]
