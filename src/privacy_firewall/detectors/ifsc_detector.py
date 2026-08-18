"""Detector for Indian IFSC (Indian Financial System Code) identifiers."""

from __future__ import annotations

import re

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.models.geometry import Span

# IFSC format: 4 letters + 0 + 6 alphanumeric (11 chars total)
# First 4 chars identify the bank
# We use a more flexible pattern to handle cases where IFSC is adjacent to other text
IFSC_PATTERN = re.compile(r"([A-Z]{4}0[A-Z0-9]{6})")

# Known bank codes (first 4 characters)
KNOWN_BANK_CODES = frozenset({
    # Public Sector Banks
    "SBIN", "UBIN", "CNRB", "SBHY", "SBTR", "SBTM", "SBPO", "PUNB",
    "BARB", "BARD", "IDIB", "IOBA", "UCBA", "ANDH", "CBIN", "CDRB",
    "Corpy", "KVGB", "KARB", "MAHB", "ORBC", "PSIB", "PYSB",
    "RATN", "SKSB", "TMBL", "TJSB", "UBI", "UCO", "UNBA", "VIJB",
    # Private Sector Banks
    "HDFC", "ICIC", "UTIB", "AXIS", "KKBK", "CITI", "CHAS",
    "DLXB", "FDRL", "HDFC", "IDFB", "INDB", "JAKA", "KBL",
    "KVB", "LAVB", "MCBL", "NKGS", "ORBC", "PMCB", "RATN",
    "SIBL", "SKSB", "TMBL", "TNSL", "UCBA", "UJVN", "VYSA",
    # Foreign Banks
    "ABNA", "ANDB", "BBKM", "BNPA", "BPVI", "BRIT", "CITI",
    "CRES", "DEUT", "DOSM", "HSBC", "ICBC", "INGV", "JPMC",
    "KBEK", "KRESC", "MHBK", "MIDL", "MOSM", "NOWB", "OCBC",
    "PNBC", "PTCB", "RZVL", "SCBL", "SCOE", "SMBC", "SOGE",
    "SONA", "STBK", "TBTM", "UBSW", "WFCB", "WFBI",
    # Payment Banks
    "AIRT", "AIRP", "JIOS", "PAYU", "YESB", "YTLC",
    # Small Finance Banks
    "AUBL", "BAFL", "BDBL", "BJSA", "Capital", "CCBL",
    "ESAF", "GSCB", "HABU", "ICBL", "JAIB", "JAKA",
    "JALX", "KARB", "KBL", "KESR", "KLGX", "KMBL",
    "KNSB", "KVCB", "LDCB", "LVRD", "MCLX", "NAIN",
    "NESF", "NESF", "PMCB", "PNBK", "POSB", "PUCL",
    "RAJA", "RBLX", "S3BK", "SAHE", "SATJ", "SBLD",
    "SIBL", "SKSB", "STCB", "SURY", "SURY", "TBLX",
    "TJSB", "TNPC", "TNSL", "UCBL", "UJVN", "UOVB",
    "VAVB", "VCBL", "VKBL", "YESB",
})


class IFSCDetector(BaseDetector):
    """Detector for Indian IFSC (Indian Financial System Code) identifiers.

    IFSC is an 11-character alphanumeric code used for identifying
    bank branches for electronic fund transfers (NEFT, RTGS, IMPS).

    Format: ``SBIN0001234`` (4 bank code + 0 + 6 branch code)
    """

    @property
    def name(self) -> str:
        """Human-readable detector name."""
        return "ifsc"

    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]:
        """Scan every text block for IFSC patterns.

        Args:
            document: The document to scan.
            values_only: If ``True``, use per-span bounding boxes for
                precise value-only redaction.

        Returns:
            A list of Detection instances for every unique valid IFSC found.
        """
        detections: list[Detection] = []

        for page in document.pages:
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue

                for match in IFSC_PATTERN.finditer(block.text):
                    ifsc = match.group(1)
                    if not self._validate_format(ifsc):
                        continue
                    # Every match is a distinct on-page occurrence (a single
                    # non-overlapping pattern), so all are kept: a repeated IFSC
                    # must be redacted at each place it appears.

                    reasons = ["matches IFSC format (bank code + '0' + branch code)"]
                    if ifsc[:4] in KNOWN_BANK_CODES:
                        reasons.append(f"recognised bank code '{ifsc[:4]}'")

                    match_bbox = (
                        block.bbox_for_span(match.start(1), match.end(1))
                        if values_only
                        else block.bbox
                    )

                    detections.append(
                        Detection(
                            detector_name=self.name,
                            detection_type="IFSC",
                            text=ifsc,
                            span=Span(start=match.start(1), end=match.end(1)),
                            bbox=match_bbox,
                            page_number=page.page_number,
                            confidence=0.95,
                            reasons=tuple(reasons),
                        )
                    )

        return detections

    @staticmethod
    def _validate_format(ifsc: str) -> bool:
        """Verify the IFSC structure.

        Args:
            ifsc: The IFSC code to validate.

        Returns:
            ``True`` if the IFSC has valid length and structure.
        """
        if len(ifsc) != 11:
            return False
        # First 4 chars must be letters (bank code)
        if not ifsc[:4].isalpha():
            return False
        # 5th char must be 0
        if ifsc[4] != "0":
            return False
        # Last 6 chars must be alphanumeric (branch code)
        if not ifsc[5:].isalnum():
            return False
        return True
