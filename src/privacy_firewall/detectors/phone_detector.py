from __future__ import annotations

import re

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.detectors.utils import is_in_slash_token, overlaps_taken
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.models.geometry import Span

PHONE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\+\d{1,3}[-.\s]?\d{4,14}"),
    re.compile(r"\b0\d{10}\b"),
    re.compile(r"\d{3}[-.\s]\d{3}[-.\s]\d{4}"),
    re.compile(r"\d{4}[-.\s]\d{3}[-.\s]\d{3}"),
    re.compile(r"\d{5}[-.\s]\d{5}"),
    re.compile(r"\b\d{10}\b"),
]
"""List of regex patterns covering common phone number formats."""


class PhoneDetector(BaseDetector):
    """Detector that identifies phone numbers in document text."""

    @property
    def name(self) -> str:
        """Human-readable detector name."""
        return "phone"

    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]:
        """Scan a document for phone numbers.

        Iterates over all text blocks and all PHONE_PATTERNS, validates each
        match, deduplicates by normalized digits, and yields a Detection.

        Args:
            document: The document to scan.
            values_only: If ``True``, use per-span bounding boxes for
                precise value-only redaction.

        Returns:
            A list of Detection objects for each valid phone number found.
        """
        detections: list[Detection] = []

        for page in document.pages:
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue

                # Spans already emitted in this block. The formats overlap (a
                # ``+91-`` number is also a bare 10-digit run), so this drops the
                # redundant re-match of one occurrence while keeping a genuine
                # repeat of the same number elsewhere on the page.
                taken: list[tuple[int, int]] = []
                for pattern in PHONE_PATTERNS:
                    for match in pattern.finditer(block.text):
                        raw = match.group()
                        if not self._validate_phone(raw):
                            continue
                        if is_in_slash_token(block.text, match.start(), match.end()):
                            continue
                        if overlaps_taken(taken, match.start(), match.end()):
                            continue

                        match_bbox = (
                            block.bbox_for_span(match.start(), match.end())
                            if values_only
                            else block.bbox
                        )

                        detections.append(
                            Detection(
                                detector_name=self.name,
                                detection_type="PHONE",
                                text=raw,
                                span=Span(start=match.start(), end=match.end()),
                                bbox=match_bbox,
                                page_number=page.page_number,
                                confidence=self._resolve_confidence(raw),
                                reasons=self._resolve_reasons(raw),
                            )
                        )
                        taken.append((match.start(), match.end()))

        return detections

    @staticmethod
    def _validate_phone(raw: str) -> bool:
        """Validate a phone number by digit count and leading digit rules.

        Args:
            raw: The raw phone number string.

        Returns:
            True if the number has 10-15 digits and meets country-code rules.
        """
        digits_only = re.sub(r"[^\d]", "", raw)
        if len(digits_only) < 10 or len(digits_only) > 15:
            return False
        if len(digits_only) == 10 and digits_only[0] not in "6789":
            return False
        return True

    @staticmethod
    def _resolve_confidence(raw: str) -> float:
        """Return a confidence score based on phone number format.

        Args:
            raw: The raw phone number string.

        Returns:
            A confidence float between 0.0 and 1.0.
        """
        digits_only = re.sub(r"[^\d]", "", raw)
        if len(digits_only) == 10:
            return 0.85
        if raw.startswith("+") or raw.startswith("0"):
            return 0.9
        return 0.7

    @staticmethod
    def _resolve_reasons(raw: str) -> tuple[str, ...]:
        """Return human-readable evidence for a phone match.

        Args:
            raw: The raw phone number string.

        Returns:
            Evidence strings describing why this match was accepted.
        """
        digits_only = re.sub(r"[^\d]", "", raw)
        if len(digits_only) == 10:
            return ("10-digit mobile number starting with 6-9",)
        if raw.startswith("+"):
            return ("matches phone format", "has international dialling prefix")
        if raw.startswith("0"):
            return ("matches phone format", "has trunk prefix '0'")
        return ("matches phone format",)


