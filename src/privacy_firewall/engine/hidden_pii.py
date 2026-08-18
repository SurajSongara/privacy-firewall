"""Detect PII hiding *outside* a PDF's visible text.

Plain text extraction only sees the page content stream. A PDF also carries
text in two other places that a naive redactor never touches:

* **Document metadata** — the Info dictionary (Title/Author/Subject/Keywords).
  Bank and tax export tools stamp the account holder's name or number here,
  where it is invisible on the page but readable in one click of File →
  Properties.
* **Annotations** — comments, sticky notes, free-text callouts and form-field
  (widget) values. Fillable Form 16 / ITR PDFs keep the taxpayer's PII as form
  values, which are annotations, not page text.

This module runs the *same* detector registry the visible pipeline uses over
those surfaces, so a PAN in an annotation is validated exactly like a PAN on
the page. The findings feed both reporting (``detect``/``scan``) and
verification (proving the redacted output is clean).
"""

from __future__ import annotations

from dataclasses import dataclass

from privacy_firewall.detectors import build_registry
from privacy_firewall.detectors.registry import DetectorRegistry
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.document import Document, Page
from privacy_firewall.models.geometry import BoundingBox
from privacy_firewall.parsers.pdfium_compat import PdfiumDocument


@dataclass(frozen=True)
class HiddenFinding:
    """One PII value found on a non-content surface of a PDF.

    Attributes:
        surface: The kind of surface — ``"metadata"``, ``"annotation"`` or
            ``"form-field"``.
        location: A human-readable pointer, e.g. ``"metadata:Author"``,
            ``"annotation on page 1"`` or ``"form field 'pan_field'"``.
        page: 1-based page number for annotations, ``None`` for document-level
            metadata.
        detection_type: The detector type that fired (PAN, PHONE, …).
        value: The matched PII value.
        confidence: The detector's confidence.
    """

    surface: str
    location: str
    page: int | None
    detection_type: str
    value: str
    confidence: float


def _scan_text(text: str, registry: DetectorRegistry) -> list[tuple[str, str, float]]:
    """Run the detectors over a bare string, off a synthetic one-block document.

    Returns ``(detection_type, value, confidence)`` triples. Reusing the real
    registry means metadata and annotations get the same checksum and context
    validation as visible text — no second, weaker code path.
    """
    if not text.strip():
        return []
    block = TextBlock(
        block_id="hidden-0",
        bbox=BoundingBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0),
        page_number=1,
        confidence=1.0,
        text=text,
        spans=[],
    )
    doc = Document(pages=[Page(page_number=1, width=1.0, height=1.0, blocks=[block])])
    result = registry.run_all(doc)
    return [(d.detection_type, d.text, d.confidence) for d in result.detections]


def scan_hidden_pii(
    doc: PdfiumDocument, *, registry: DetectorRegistry | None = None
) -> list[HiddenFinding]:
    """Scan *doc*'s metadata and annotations for PII.

    Args:
        doc: An open document.
        registry: Detector registry to use (defaults to all detectors).

    Returns:
        Every PII value found outside the page content stream, de-duplicated on
        ``(surface, location, detection_type, value)``.
    """
    registry = registry or build_registry()
    findings: list[HiddenFinding] = []

    # Document metadata (Info dictionary).
    for key, value in doc.metadata().items():
        for det_type, matched, conf in _scan_text(value, registry):
            findings.append(
                HiddenFinding(
                    surface="metadata",
                    location=f"metadata:{key}",
                    page=None,
                    detection_type=det_type,
                    value=matched,
                    confidence=conf,
                )
            )

    # Annotations, per page.
    for page_index in range(len(doc)):
        page_no = page_index + 1
        for annot in doc[page_index].annotations():
            is_field = annot.subtype == "widget"
            surface = "form-field" if is_field else "annotation"
            if is_field and annot.field_name:
                location = f"form field '{annot.field_name}' on page {page_no}"
            else:
                location = f"{annot.subtype} annotation on page {page_no}"
            for det_type, matched, conf in _scan_text(annot.text, registry):
                findings.append(
                    HiddenFinding(
                        surface=surface,
                        location=location,
                        page=page_no,
                        detection_type=det_type,
                        value=matched,
                        confidence=conf,
                    )
                )

    # De-duplicate: the same value can match via Contents and V on one annot.
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[HiddenFinding] = []
    for finding in findings:
        dedup_key = (finding.surface, finding.location, finding.detection_type, finding.value)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        unique.append(finding)
    return unique
