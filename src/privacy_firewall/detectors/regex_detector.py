"""``RegexDetector``: a reusable detector driven by patterns and a validation hook."""

from __future__ import annotations

import re
from collections.abc import Callable

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.models.geometry import Span

ValidationHook = Callable[[str], float | None]


class RegexDetector(BaseDetector):
    """Detector that scans document text using compiled regex patterns.

    Each match can optionally be passed through a validation hook that may
    adjust the confidence score or reject the match entirely.
    """

    def __init__(
        self,
        name: str,
        detection_type: str,
        patterns: list[re.Pattern[str]],
        *,
        validate: ValidationHook | None = None,
        confidence: float = 1.0,
        priority: int = 0,
    ) -> None:
        """Initialise the regex detector.

        Args:
            name: Unique detector name.
            detection_type: Type label attached to every detection (e.g. ``"PAN"``).
            patterns: Compiled regex patterns to search for.
            validate: Optional hook that receives matched text and returns a
                confidence score, or ``None`` to reject the match.
            confidence: Default confidence when *validate* is not supplied.
            priority: Execution priority (higher runs first).
        """
        self._name = name
        self._detection_type = detection_type
        self._patterns = patterns
        self._validate = validate
        self._confidence = confidence
        self._priority = priority

    @property
    def name(self) -> str:
        """Human-readable detector name."""
        return self._name

    @property
    def priority(self) -> int:
        """Execution priority (higher values run first)."""
        return self._priority

    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]:
        """Scan every text block in the document for all configured patterns.

        Args:
            document: The document to scan.
            values_only: If ``True``, use per-span bounding boxes so only
                the matched text region is redacted rather than the full block.

        Returns:
            A list of Detection instances for every non-rejected match.
        """
        detections: list[Detection] = []

        for page in document.pages:
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue

                for pattern in self._patterns:
                    for match in pattern.finditer(block.text):
                        matched_text = match.group()
                        conf = self._resolve_confidence(matched_text)
                        if conf is None:
                            continue

                        match_bbox = (
                            block.bbox_for_span(match.start(), match.end())
                            if values_only
                            else block.bbox
                        )

                        detections.append(
                            Detection(
                                detector_name=self._name,
                                detection_type=self._detection_type,
                                text=matched_text,
                                span=Span(start=match.start(), end=match.end()),
                                bbox=match_bbox,
                                page_number=page.page_number,
                                confidence=conf,
                                reasons=(f"matches {self._detection_type} pattern",),
                            )
                        )

        return detections

    def _resolve_confidence(self, matched_text: str) -> float | None:
        """Determine the confidence score for a matched piece of text.

        If a validation hook is registered it is called; otherwise the
        detector-level default confidence is returned.

        Args:
            matched_text: The text that matched a regex pattern.

        Returns:
            A confidence score, or ``None`` if the match should be rejected.
        """
        if self._validate is not None:
            result = self._validate(matched_text)
            if result is None:
                return None
            return result
        return self._confidence
