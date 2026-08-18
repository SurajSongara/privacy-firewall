"""Detector for Indian PAN (Permanent Account Number) identifiers."""

from __future__ import annotations

import re

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.models.geometry import Span

PAN_PATTERN = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")

PAN_STATUS_CODES = frozenset({"P", "C", "H", "F", "A", "T", "B", "L", "J", "G"})


class PANDetector(BaseDetector):
    """Detector for Indian Permanent Account Number (PAN) identifiers.

    Matches the standard PAN format ``ABCDE1234F`` and validates the
    4th character against known status codes.
    """

    @property
    def name(self) -> str:
        """Human-readable detector name."""
        return "pan"

    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]:
        """Scan every text block for PAN patterns.

        Args:
            document: The document to scan.
            values_only: If ``True``, use per-span bounding boxes for
                precise value-only redaction.

        Returns:
            A list of Detection instances for every valid PAN found.
        """
        detections: list[Detection] = []

        for page in document.pages:
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue

                for match in PAN_PATTERN.finditer(block.text):
                    pan = match.group()
                    if not self._validate_format(pan):
                        continue

                    match_bbox = (
                        block.bbox_for_span(match.start(), match.end())
                        if values_only
                        else block.bbox
                    )

                    detections.append(
                        Detection(
                            detector_name=self.name,
                            detection_type="PAN",
                            text=pan,
                            span=Span(start=match.start(), end=match.end()),
                            bbox=match_bbox,
                            page_number=page.page_number,
                            confidence=0.95,
                            reasons=(
                                "matches PAN format",
                                f"holder-type code '{pan[3]}' is valid",
                            ),
                        )
                    )

        return detections

    @staticmethod
    def _validate_format(pan: str) -> bool:
        """Verify the PAN's structure (length and status-code character).

        Args:
            pan: The 10-character PAN string to validate.

        Returns:
            ``True`` if the PAN has valid length and a recognised status code.
        """
        if len(pan) != 10:
            return False
        status = pan[3]
        return status in PAN_STATUS_CODES
