from __future__ import annotations

import re

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.models.geometry import Span

UPI_PATTERN = re.compile(r"[a-zA-Z0-9._-]+@[a-zA-Z][a-zA-Z0-9._-]*")
"""Regex matching UPI ID format (local@handle)."""

KNOWN_UPI_HANDLES: frozenset[str] = frozenset(
    {
        "ybl",
        "paytm",
        "sbi",
        "okicici",
        "okhdfcbank",
        "okaxis",
        "axl",
        "apl",
        "ibibo",
        "freecharge",
        "phonepe",
        "upi",
        "cred",
        "mobikwik",
        "pnb",
        "yesbank",
        "icici",
        "hdfcbank",
        "idfc",
        "kotak",
        "indus",
        "unionbankofindia",
        "canarabank",
        "boi",
        "barodaupi",
        "rbl",
        "federal",
    }
)
"""Known UPI payment-service provider handles used for confidence scoring."""


class UpiDetector(BaseDetector):
    """Detector that identifies UPI payment IDs in document text."""

    @property
    def name(self) -> str:
        """Human-readable detector name."""
        return "upi"

    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]:
        """Scan a document for UPI IDs.

        Iterates over all text blocks, matches against UPI_PATTERN, validates
        each candidate, deduplicates, and yields a Detection.

        Args:
            document: The document to scan.
            values_only: If ``True``, use per-span bounding boxes for
                precise value-only redaction.

        Returns:
            A list of Detection objects for each valid UPI ID found.
        """
        detections: list[Detection] = []

        for page in document.pages:
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue

                for match in UPI_PATTERN.finditer(block.text):
                    upi_id = match.group()
                    if not self._validate_format(upi_id):
                        continue
                    # Each match is a distinct on-page occurrence (one
                    # non-overlapping pattern), so all are kept: a repeated UPI
                    # ID must be redacted everywhere it appears.

                    match_bbox = (
                        block.bbox_for_span(match.start(), match.end())
                        if values_only
                        else block.bbox
                    )

                    detections.append(
                        Detection(
                            detector_name=self.name,
                            detection_type="UPI",
                            text=upi_id,
                            span=Span(start=match.start(), end=match.end()),
                            bbox=match_bbox,
                            page_number=page.page_number,
                            confidence=self._resolve_confidence(upi_id),
                            reasons=self._resolve_reasons(upi_id),
                        )
                    )

        return detections

    @staticmethod
    def _validate_format(upi_id: str) -> bool:
        """Validate a UPI ID for length and structural rules.

        Args:
            upi_id: The UPI ID string to validate.

        Returns:
            True if the UPI ID is structurally valid, False otherwise.
        """
        if len(upi_id) > 50:
            return False
        if ".." in upi_id or "@@" in upi_id:
            return False
        parts = upi_id.split("@")
        if len(parts) != 2:
            return False
        local, handle = parts
        if not local or not handle:
            return False
        if "." in handle:
            return False
        return True

    @staticmethod
    def _resolve_confidence(upi_id: str) -> float:
        """Return a confidence score based on whether the handle is known.

        Args:
            upi_id: The UPI ID string.

        Returns:
            A confidence float between 0.0 and 1.0.
        """
        handle = upi_id.split("@", 1)[1] if "@" in upi_id else ""
        if handle in KNOWN_UPI_HANDLES:
            return 0.95
        return 0.7

    @staticmethod
    def _resolve_reasons(upi_id: str) -> tuple[str, ...]:
        """Return human-readable evidence for a UPI match.

        Args:
            upi_id: The UPI ID string.

        Returns:
            Evidence strings describing why this match was accepted.
        """
        handle = upi_id.split("@", 1)[1] if "@" in upi_id else ""
        if handle in KNOWN_UPI_HANDLES:
            return ("matches UPI ID format", f"known payment-provider handle '{handle}'")
        return ("matches UPI ID format", f"unrecognised handle '{handle}'")


