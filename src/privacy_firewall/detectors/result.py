"""Detector-run result types -- per-detector timing and the aggregated result."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document


@dataclass
class DetectorRun:
    """Summary of a single detector execution.

    Attributes:
        detector_name: Name of the detector that was run.
        detection_count: Number of detections the scan produced.
        duration_ms: Wall-clock duration of the scan in milliseconds.
    """

    detector_name: str
    detection_count: int
    duration_ms: float


@dataclass
class DetectionResult:
    """Aggregated result of one or more detector scans.

    Attributes:
        detections: All Detection instances produced during the scan(s).
        runs: Metadata for each individual detector execution.
    """

    detections: list[Detection] = field(default_factory=list)
    runs: list[DetectorRun] = field(default_factory=list)

    @property
    def total_detections(self) -> int:
        """Total number of detections across all runs."""
        return len(self.detections)

    @property
    def detectors_run(self) -> list[str]:
        """Names of every detector that contributed to this result."""
        return [r.detector_name for r in self.runs]

    def merge(self, other: DetectionResult) -> None:
        """Incorporate another DetectionResult into this one.

        Args:
            other: The result to merge from.
        """
        self.detections.extend(other.detections)
        self.runs.extend(other.runs)

    @staticmethod
    def from_detections(
        detector_name: str,
        detections: list[Detection],
        duration_ms: float,
    ) -> DetectionResult:
        """Build a result from a single detector run.

        Args:
            detector_name: Name of the detector that produced the detections.
            detections: The list of detections found.
            duration_ms: How long the scan took, in milliseconds.

        Returns:
            A new DetectionResult encapsulating the run.
        """
        return DetectionResult(
            detections=detections,
            runs=[
                DetectorRun(
                    detector_name=detector_name,
                    detection_count=len(detections),
                    duration_ms=duration_ms,
                )
            ],
        )


def timed_scan(
    detector: BaseDetector,
    document: Document,
    *,
    values_only: bool = False,
) -> DetectionResult:
    """Run a detector's scan and time its execution.

    Args:
        detector: The detector to run.
        document: The document to scan.
        values_only: Forwarded to ``detector.scan()`` — if ``True``,
            per-span bounding boxes are computed for each match.

    Returns:
        A DetectionResult that includes both the findings and timing metadata.
    """
    start = time.perf_counter()
    detections = detector.scan(document, values_only=values_only)
    elapsed = (time.perf_counter() - start) * 1000
    return DetectionResult.from_detections(
        detector_name=detector.name,
        detections=detections,
        duration_ms=elapsed,
    )
