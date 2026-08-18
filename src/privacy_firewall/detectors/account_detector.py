"""Detector for Indian bank account numbers."""

from __future__ import annotations

import re

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.detectors.utils import is_in_slash_token, overlaps_taken
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.models.geometry import Span

# Bank account numbers are typically 9-18 digits
# Common lengths: 11 (SBI), 12 (ICICI), 14 (HDFC), 15 (Axis)
# They often appear near IFSC codes or after keywords like "A/c", "Account"
# Order matters: longer alternatives first to avoid partial matches
ACCOUNT_KEYWORDS = re.compile(
    r"(?:Account|Acct|A/C|Acc|A/?c)\s*(?:No\.?|Number|#)?\s*[:.]?\s*",
    re.IGNORECASE,
)
ACCOUNT_PATTERN = re.compile(
    r"(?:A/?c|Account|Acct|A/C|Acc)\s*(?:No\.?|Number|#)?\s*[:.]?\s*(\d{9,18})",
    re.IGNORECASE,
)

# Also match standalone account numbers that are 11-15 digits
# (most common Indian bank account lengths)
STANDALONE_ACCOUNT_PATTERN = re.compile(r"\b(\d{11,15})\b")

# IFSC pattern to exclude (IFSCs are 11 chars but contain letters)
IFSC_EXCLUDE = re.compile(r"[A-Za-z]")

# SBI statement ledger rows end with "<digits> AT <5-digit branch code>"
# (e.g. "0097737162096 AT 30524" / "0099509044300AT30524"). The leading
# digits are transaction line-item markers, not account numbers.
LEDGER_LINE_SUFFIX = re.compile(r"\s*AT\s*\d{5}\b", re.IGNORECASE)

# OCR often splits "Account Number : 40798662399" across two blocks
# (label block ends with the keyword; the value block starts with ":").
# Recognising the label on the previous block upgrades a standalone hit
# to keyword-anchored confidence.
LABEL_BLOCK_SUFFIX = re.compile(
    r"(?:Account|A/?c|CIF|CKYCR|Customer\s*ID)"
    r"(?:\s*(?:No\.?|Number|ID|#))?\s*[:.]?\s*$",
    re.IGNORECASE,
)


class AccountDetector(BaseDetector):
    """Detector for Indian bank account numbers.

    Matches account numbers that appear:
    1. After keywords like "A/c", "Account No", etc.
    2. As standalone 11-15 digit numbers (common Indian lengths)

    Validation:
    - Must be 9-18 digits
    - Should not be an IFSC code (contains letters)
    - Should not be a PAN (10 chars with letters)
    - Should not be an Aadhaar (12 digits, handled by Aadhaar detector)
    """

    @property
    def name(self) -> str:
        """Human-readable detector name."""
        return "account"

    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]:
        """Scan every text block for bank account numbers.

        Args:
            document: The document to scan.
            values_only: If ``True``, use per-span bounding boxes for
                precise value-only redaction.

        Returns:
            A list of Detection instances for every unique valid account found.
        """
        detections: list[Detection] = []

        for page in document.pages:
            prev_text_block: TextBlock | None = None
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue

                # Cross-block label pairing: if the previous block ends with an
                # account label (e.g. "Account Number", "CIF Number", "CKYCR"),
                # any standalone hit in this block is treated as keyword-anchored.
                label_from_prev = (
                    prev_text_block is not None
                    and LABEL_BLOCK_SUFFIX.search(prev_text_block.text) is not None
                )

                # Spans already emitted in this block. The keyword and standalone
                # passes both match a labelled number, so this drops the second
                # pass's re-match of the same occurrence while keeping a genuine
                # repeat of the account elsewhere (header vs. footer), which must
                # also be redacted.
                taken: list[tuple[int, int]] = []

                # First, find accounts with explicit keywords
                for match in ACCOUNT_KEYWORDS.finditer(block.text):
                    # Get the number after the keyword
                    remaining = block.text[match.end():]
                    num_match = re.match(r"(\d{9,18})", remaining)
                    if num_match:
                        account = num_match.group(1)
                        if not self._validate_account(account):
                            continue

                        # Calculate span for the account number only
                        account_start = match.end() + num_match.start()
                        account_end = match.end() + num_match.end()

                        if overlaps_taken(taken, account_start, account_end):
                            continue
                        if self._is_ledger_line_marker(block.text, account_end):
                            continue
                        if is_in_slash_token(block.text, account_start, account_end):
                            continue

                        match_bbox = (
                            block.bbox_for_span(account_start, account_end)
                            if values_only
                            else block.bbox
                        )

                        detections.append(
                            Detection(
                                detector_name=self.name,
                                detection_type="ACCOUNT",
                                text=account,
                                span=Span(start=account_start, end=account_end),
                                bbox=match_bbox,
                                page_number=page.page_number,
                                confidence=0.85,
                                reasons=(
                                    "9-18 digit number",
                                    "follows an account label (e.g. 'A/c No')",
                                ),
                            )
                        )
                        taken.append((account_start, account_end))

                # Then, find standalone account numbers (11-15 digits).
                # The overlap check skips ones already emitted by the keyword
                # pass above; a repeat elsewhere in the block is still kept.
                for match in STANDALONE_ACCOUNT_PATTERN.finditer(block.text):
                    account = match.group(1)
                    if not self._validate_account(account):
                        continue
                    if overlaps_taken(taken, match.start(1), match.end(1)):
                        continue

                    # Skip if this number appears right after an IFSC
                    # (it's likely a branch code, not an account)
                    prefix = block.text[max(0, match.start() - 15):match.start()]
                    if re.search(r"[A-Za-z]{4}0", prefix):
                        continue

                    if self._is_ledger_line_marker(block.text, match.end(1)):
                        continue
                    if is_in_slash_token(block.text, match.start(1), match.end(1)):
                        continue

                    match_bbox = (
                        block.bbox_for_span(match.start(1), match.end(1))
                        if values_only
                        else block.bbox
                    )

                    detections.append(
                        Detection(
                            detector_name=self.name,
                            detection_type="ACCOUNT",
                            text=account,
                            span=Span(start=match.start(1), end=match.end(1)),
                            bbox=match_bbox,
                            page_number=page.page_number,
                            confidence=0.85 if label_from_prev else 0.70,
                            reasons=(
                                ("standalone number of common account length (11-15 digits)",)
                                + (
                                    ("previous block ends with an account label",)
                                    if label_from_prev
                                    else ()
                                )
                            ),
                        )
                    )
                    taken.append((match.start(1), match.end(1)))

                prev_text_block = block

        return detections

    @staticmethod
    def _is_ledger_line_marker(text: str, end: int) -> bool:
        """Return ``True`` when the digit run is followed by ``AT <branch-code>``.

        SBI statement rows end with ``<txn-line-marker> AT <branch>`` (e.g.
        ``0097737162096 AT 30524``); those leading digits are ledger
        artifacts, not real account numbers.
        """
        return LEDGER_LINE_SUFFIX.match(text, end) is not None

    @staticmethod
    def _validate_account(account: str) -> bool:
        """Validate an account number.

        Args:
            account: The account number string to validate.

        Returns:
            ``True`` if the account number is valid.
        """
        if len(account) < 9 or len(account) > 18:
            return False

        # Must be all digits
        if not account.isdigit():
            return False

        # Exclude common false positives
        # All same digits (e.g., 00000000000)
        if len(set(account)) == 1:
            return False

        # Looks like a date (DDMMYYYY or similar)
        if len(account) == 8:
            day = int(account[:2])
            month = int(account[2:4])
            year = int(account[4:8])
            if 1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100:
                return False

        # Looks like a phone number (10 digits starting with 6-9)
        if len(account) == 10 and account[0] in "6789":
            return False

        # Looks like an Aadhaar (12 digits, will be caught by Aadhaar detector)
        if len(account) == 12:
            return False  # Let Aadhaar detector handle it

        # Exclude UPI transaction IDs (12-13 digits starting with 0 or specific patterns)
        # UPI IDs often start with 0 and are 12 digits
        if len(account) == 12 and account.startswith("0"):
            return False

        # Exclude amounts (numbers with commas or decimal points nearby)
        # This is handled by context, but we can exclude very round numbers
        if len(account) >= 10:
            # Check if it's mostly zeros (like 1000000000)
            zero_count = account.count("0")
            if zero_count > len(account) * 0.7:
                return False

        return True
