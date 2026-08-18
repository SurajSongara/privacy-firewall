"""``DetectorRegistry``: runs detectors over a Document and collects timed results."""

from __future__ import annotations

from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.detectors.result import DetectionResult, timed_scan
from privacy_firewall.models.document import Document


class DetectorRegistry:
    """Registry that manages detectors and runs them against documents."""

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._detectors: dict[str, BaseDetector] = {}

    def register(self, detector: BaseDetector) -> None:
        """Register a detector by its ``.name``.

        If a detector with the same name already exists it is overwritten.

        Args:
            detector: The detector instance to register.
        """
        self._detectors[detector.name] = detector

    def unregister(self, name: str) -> None:
        """Remove a detector from the registry.

        Args:
            name: The name of the detector to remove.
        """
        self._detectors.pop(name, None)

    def get(self, name: str) -> BaseDetector | None:
        """Retrieve a registered detector by name.

        Args:
            name: The detector name to look up.

        Returns:
            The detector instance, or ``None`` if not found.
        """
        return self._detectors.get(name)

    @property
    def detectors(self) -> dict[str, BaseDetector]:
        """Copy of the internal name-to-detector mapping."""
        return dict(self._detectors)

    @property
    def detector_names(self) -> list[str]:
        """List of all registered detector names."""
        return list(self._detectors)

    def run_all(self, document: Document, *, values_only: bool = False) -> DetectionResult:
        """Run every registered detector against the document.

        Args:
            document: The document to scan.
            values_only: If ``True``, each detector uses per-span bounding
                boxes so only the matched value is redacted.

        Returns:
            An aggregated DetectionResult containing all findings.
        """
        result = DetectionResult()
        for detector in self._detectors.values():
            dr = timed_scan(detector, document, values_only=values_only)
            result.merge(dr)
        return result

    def run(self, document: Document, name: str) -> DetectionResult | None:
        """Run a single named detector against the document.

        Args:
            document: The document to scan.
            name: Name of the detector to run.

        Returns:
            A DetectionResult for that detector, or ``None`` if the name is
            not registered.
        """
        detector = self._detectors.get(name)
        if detector is None:
            return None
        return timed_scan(detector, document)
