"""``BaseDetector``: the ``(Document) -> list[Detection]`` contract every detector implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document


class BaseDetector(ABC):
    """Abstract base class for all privacy-leak detectors.

    Subclasses must implement *name* and *scan*.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable detector name (e.g. ``"pan"``, ``"aadhaar"``)."""

    @abstractmethod
    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]:
        """Scan a document and return all detections found.

        Args:
            document: The document to scan.
            values_only: If ``True``, compute precise bounding boxes for
                each match rather than using the full block bounding box.

        Returns:
            A list of Detection instances found in the document.
        """
