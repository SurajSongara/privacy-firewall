"""Detector for the Indian GSTIN (GST Identification Number)."""

from __future__ import annotations

import re

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.models.geometry import Span

# 15 chars: 2-digit state code, 10-char PAN, 1 entity char, 'Z', 1 checksum.
# Alphanumeric lookarounds prevent matching a GSTIN embedded in a longer token.
GSTIN_PATTERN = re.compile(
    r"(?<![A-Z0-9])[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z](?![A-Z0-9])"
)

# Base-36 alphabet used by the GSTIN check-digit algorithm.
_CODE = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Valid GST state codes are 01–38, plus 97 (other territory) and 99 (centre).
_SPECIAL_STATE_CODES = frozenset({97, 99})


class GSTINDetector(BaseDetector):
    """Detector for the 15-character GSTIN, validated by its check digit.

    GSTINs embed the entity's PAN and carry a base-36 checksum in the final
    position, so a format match plus a valid checksum is high-confidence.
    """

    @property
    def name(self) -> str:
        """Human-readable detector name."""
        return "gstin"

    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]:
        """Scan every text block for valid GSTINs.

        Args:
            document: The document to scan.
            values_only: If ``True``, use per-span bounding boxes for
                precise value-only redaction.

        Returns:
            A list of Detection instances for every valid GSTIN found.
        """
        detections: list[Detection] = []

        for page in document.pages:
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue

                for match in GSTIN_PATTERN.finditer(block.text):
                    gstin = match.group()
                    if not self._is_valid(gstin):
                        continue

                    match_bbox = (
                        block.bbox_for_span(match.start(), match.end())
                        if values_only
                        else block.bbox
                    )

                    detections.append(
                        Detection(
                            detector_name=self.name,
                            detection_type="GSTIN",
                            text=gstin,
                            span=Span(start=match.start(), end=match.end()),
                            bbox=match_bbox,
                            page_number=page.page_number,
                            confidence=0.95,
                            reasons=(
                                "matches GSTIN format",
                                "base-36 checksum valid",
                                f"state code '{gstin[:2]}'",
                            ),
                        )
                    )

        return detections

    @classmethod
    def _is_valid(cls, gstin: str) -> bool:
        """Whether *gstin* has a valid state code and check digit."""
        if len(gstin) != 15:
            return False
        state = int(gstin[:2])
        if not (1 <= state <= 38 or state in _SPECIAL_STATE_CODES):
            return False
        return cls._checksum(gstin[:14]) == gstin[14]

    @staticmethod
    def _checksum(first14: str) -> str:
        """Compute the GSTIN check character for the first 14 characters.

        The official algorithm walks the characters right-to-left with an
        alternating factor of 2, 1, 2, 1, …, sums each product's base-36
        digits, and derives the check character from the running total.
        """
        base = len(_CODE)
        factor = 2
        total = 0
        for char in reversed(first14):
            product = factor * _CODE.index(char)
            factor = 1 if factor == 2 else 2
            total += product // base + product % base
        return _CODE[(base - (total % base)) % base]
