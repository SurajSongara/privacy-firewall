"""Detector for email addresses, gated by a TLD allowlist to suppress false positives."""

from __future__ import annotations

import re

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.models.geometry import Span

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
"""Regex matching standard email addresses per RFC 5322 simplified."""

KNOWN_TLDS: frozenset[str] = frozenset(
    {
        # Generic
        "com", "net", "org", "edu", "gov", "mil", "int", "info", "biz",
        "name", "pro", "mobi", "email", "cloud", "online", "site", "store",
        "tech", "app", "dev", "io", "ai", "me", "co", "xyz", "bank",
        # Country codes common in Indian documents
        "in", "us", "uk", "au", "ca", "de", "fr", "jp", "cn", "ru", "br",
        "it", "nl", "es", "se", "ch", "sg", "hk", "ae", "nz", "za",
    }
)
"""TLD allowlist — rejects OCR artifacts like ``30524@sbi.coin``."""


class EmailDetector(BaseDetector):
    """Detector that identifies email addresses in document text."""

    @property
    def name(self) -> str:
        """Human-readable detector name."""
        return "email"

    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]:
        """Scan a document for email addresses.

        Iterates over all text blocks, matches against EMAIL_PATTERN, and
        validates each candidate before yielding a Detection.

        Args:
            document: The document to scan.
            values_only: If ``True``, use per-span bounding boxes for
                precise value-only redaction.

        Returns:
            A list of Detection objects for each valid email address found.
        """
        detections: list[Detection] = []

        for page in document.pages:
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue

                for match in EMAIL_PATTERN.finditer(block.text):
                    email = self._trim_glued_suffix(match.group())
                    if not self._validate_format(email):
                        continue

                    end = match.start() + len(email)
                    match_bbox = (
                        block.bbox_for_span(match.start(), end)
                        if values_only
                        else block.bbox
                    )

                    detections.append(
                        Detection(
                            detector_name=self.name,
                            detection_type="EMAIL",
                            text=email,
                            span=Span(start=match.start(), end=end),
                            bbox=match_bbox,
                            page_number=page.page_number,
                            confidence=0.9,
                            reasons=(
                                "matches email address format",
                                "local part and domain are structurally valid",
                            ),
                        )
                    )

        return detections

    @staticmethod
    def _trim_glued_suffix(email: str) -> str:
        """Trim a following token glued onto the TLD by PDF text extraction.

        Fragmented extraction can concatenate the next label directly onto
        an email (``user@hotmail.comPhone``). If the over-matched TLD starts
        with a known TLD and the residue begins with an uppercase letter
        (a new token), trim to the known TLD. Lowercase residues are left
        alone so genuine artifacts like ``sbi.coin`` stay rejected.

        Args:
            email: The regex-matched candidate email.

        Returns:
            The email trimmed to a known TLD boundary, or unchanged.
        """
        _, _, domain = email.partition("@")
        tld = domain.split(".")[-1]
        if tld.lower() in KNOWN_TLDS:
            return email
        for known in sorted(KNOWN_TLDS, key=len, reverse=True):
            if tld.lower().startswith(known) and tld[len(known) :][:1].isupper():
                return email[: len(email) - (len(tld) - len(known))]
        return email

    @staticmethod
    def _validate_format(email: str) -> bool:
        """Validate an email address against length and structural rules.

        Args:
            email: The email address string to validate.

        Returns:
            True if the email is structurally valid, False otherwise.
        """
        if len(email) > 254:
            return False
        local, _, domain = email.partition("@")
        if not local or len(local) > 64:
            return False
        if not domain or ".." in domain:
            return False
        # Domain must end with a recognised TLD (rejects OCR artifacts
        # like "sbi.coin" or "internal.ledger")
        tld = domain.split(".")[-1].lower()
        if tld not in KNOWN_TLDS:
            return False
        # Domain should not contain invalid characters
        if not all(c.isalnum() or c in "-." for c in domain):
            return False
        return True
