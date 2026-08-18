"""Engine-level orchestration for detect → redact of a single document.

Framework-free glue that both the ``redact`` CLI command and the batch
runner reuse, so the detection pipeline is defined in exactly one place.
"""

from __future__ import annotations

from pathlib import Path

from privacy_firewall.detectors import build_registry
from privacy_firewall.engine.context import ContextScorer
from privacy_firewall.engine.fusion import FusionEngine
from privacy_firewall.engine.ocr_pipeline import get_merged_document, get_pipeline_summary
from privacy_firewall.engine.redaction import RedactionPlanner, RedactionType
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.renderer.pdf_renderer import PDFRenderer


def detect_document(
    pdf: Path,
    *,
    force_ocr: bool = False,
    auto: bool = False,
    ocr_provider: str | None = None,
    detector_names: list[str] | None = None,
    values_only: bool = True,
    password: str | None = None,
) -> tuple[Document, list[Detection], str]:
    """Parse *pdf*, run detectors, score, and fuse.

    Args:
        pdf: The PDF to scan.
        force_ocr: Force the OCR pipeline.
        auto: Let diagnostics choose the pipeline.
        ocr_provider: Specific OCR engine name.
        detector_names: Detectors to run, or ``None`` for all.
        values_only: Use per-value bounding boxes (redact the value, not the block).
        password: Password for an encrypted PDF, if required.

    Returns:
        The parsed document, the fused detections, and a pipeline summary string.

    Raises:
        ValueError: If a detector name is unknown.
        EncryptedPDFError: If the PDF is password-protected and no correct
            password was supplied.
    """
    document, source = get_merged_document(
        pdf, force_ocr=force_ocr, auto=auto, ocr_provider=ocr_provider, password=password
    )
    registry = build_registry(detector_names)
    result = registry.run_all(document, values_only=values_only)
    scored = ContextScorer().apply(document, result.detections)
    detections = FusionEngine().fuse(scored).detections
    return document, detections, get_pipeline_summary(source)


def redact_document(
    input_pdf: Path,
    output_pdf: Path,
    *,
    redaction_type: RedactionType = RedactionType.REPLACE,
    force_ocr: bool = False,
    auto: bool = False,
    ocr_provider: str | None = None,
    detector_names: list[str] | None = None,
    values_only: bool = True,
    password: str | None = None,
) -> tuple[Path, list[Detection], str]:
    """Detect and redact *input_pdf* into *output_pdf*.

    Returns:
        The output path, the redacted detections, and a pipeline summary.
    """
    document, detections, summary = detect_document(
        input_pdf,
        force_ocr=force_ocr,
        auto=auto,
        ocr_provider=ocr_provider,
        detector_names=detector_names,
        values_only=values_only,
        password=password,
    )
    plan = RedactionPlanner().plan(document, detections, default_type=redaction_type)
    out_path = PDFRenderer().render(input_pdf, output_pdf, plan, password=password)
    return out_path, detections, summary
