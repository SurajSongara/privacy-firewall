"""Detector package for identifying sensitive information in documents.

Exports all built-in detector classes along with the registry, base class,
and result types that downstream consumers use to run and collect scans.
"""

from privacy_firewall.detectors.aadhaar_detector import AadhaarDetector
from privacy_firewall.detectors.account_detector import AccountDetector
from privacy_firewall.detectors.base import BaseDetector
from privacy_firewall.detectors.email_detector import EmailDetector
from privacy_firewall.detectors.gstin_detector import GSTINDetector
from privacy_firewall.detectors.ifsc_detector import IFSCDetector
from privacy_firewall.detectors.name_detector import NameDetector
from privacy_firewall.detectors.pan_detector import PANDetector
from privacy_firewall.detectors.phone_detector import PhoneDetector
from privacy_firewall.detectors.regex_detector import RegexDetector
from privacy_firewall.detectors.registry import DetectorRegistry
from privacy_firewall.detectors.result import DetectionResult, DetectorRun, timed_scan
from privacy_firewall.detectors.upi_detector import UpiDetector
from privacy_firewall.detectors.utils import is_containment_duplicate, is_exact_duplicate

#: Canonical name → class map of every built-in detector. Single source of
#: truth so the CLI, the verifier, and the pipeline all agree on the set.
ALL_DETECTORS: dict[str, type[BaseDetector]] = {
    "pan": PANDetector,
    "aadhaar": AadhaarDetector,
    "email": EmailDetector,
    "phone": PhoneDetector,
    "upi": UpiDetector,
    "ifsc": IFSCDetector,
    "account": AccountDetector,
    "name": NameDetector,
    "gstin": GSTINDetector,
}


def build_registry(names: list[str] | None = None) -> DetectorRegistry:
    """Build a registry with the requested detectors (all if ``names`` is None).

    Args:
        names: Detector names to include, or ``None`` for every built-in.

    Returns:
        A populated :class:`DetectorRegistry`.

    Raises:
        ValueError: If any name is not a known detector.
    """
    registry = DetectorRegistry()
    for name in names if names else list(ALL_DETECTORS):
        cls = ALL_DETECTORS.get(name)
        if cls is None:
            available = ", ".join(sorted(ALL_DETECTORS))
            msg = f"Unknown detector: {name!r}. Available: {available}"
            raise ValueError(msg)
        registry.register(cls())
    return registry


__all__ = [
    "ALL_DETECTORS",
    "AadhaarDetector",
    "AccountDetector",
    "BaseDetector",
    "DetectionResult",
    "DetectorRegistry",
    "DetectorRun",
    "EmailDetector",
    "GSTINDetector",
    "IFSCDetector",
    "NameDetector",
    "PANDetector",
    "PhoneDetector",
    "RegexDetector",
    "build_registry",
    "is_containment_duplicate",
    "is_exact_duplicate",
    "timed_scan",
    "UpiDetector",
]
