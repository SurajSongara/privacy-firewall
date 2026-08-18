"""``Detection``: one located PII finding -- evidence, span, bbox and confidence."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from privacy_firewall.models.geometry import BoundingBox, Span


class Detection(BaseModel):
    """A single PII or sensitive-content detection result.

    Captures the detector that produced the match, the matched text,
    its character span and bounding box within the page, the
    confidence score, and human-readable evidence for the match.
    """

    model_config = ConfigDict(frozen=True)

    detector_name: str
    detection_type: str
    text: str
    span: Span
    bbox: BoundingBox
    page_number: int
    confidence: float
    reasons: tuple[str, ...] = ()
    """Human-readable evidence for the match (e.g. "Verhoeff checksum passed")."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def detection_id(self) -> str:
        """Deterministic identifier, stable across runs on the same document.

        Derived from the location and content of the match only — not from
        the detector, confidence, or reasons — so re-scanning the same file
        yields the same id even if scoring changes.
        """
        raw = (
            f"{self.page_number}|{self.detection_type}|"
            f"{self.span.start}|{self.span.end}|{self.text}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: float) -> float:
        """Validate that confidence is between 0.0 and 1.0 (inclusive)."""
        if not 0.0 <= v <= 1.0:
            msg = "confidence must be between 0 and 1"
            raise ValueError(msg)
        return v
