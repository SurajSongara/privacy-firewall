"""Post-redaction verification and audit-grade certificate.

A redaction is only trustworthy if you can *prove* it worked. This module
re-parses the redacted output, re-runs the detectors, and asserts that

1. none of the redacted literal values are still extractable from the
   output's text layer, and
2. no detector re-fires on a value that was supposed to be gone.

It then emits a **certificate** (a JSON manifest plus a one-page PDF) that
records the input/output hashes, redaction counts by type, and the
verification result. The certificate never contains the raw PII values —
only counts, types, and pass/fail — so it is itself safe to share.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from privacy_firewall.detectors import build_registry
from privacy_firewall.detectors.registry import DetectorRegistry
from privacy_firewall.engine.decision import file_sha256
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.parsers.pdf_parser import PDFParser

CERTIFICATE_SCHEMA_VERSION = 1

#: Values shorter than this are not flagged by the whitespace-flattened
#: comparison, to avoid trivial substring collisions (e.g. a 2-digit value).
_MIN_FLAT_LEN = 4


def _tool_version() -> str:
    """Best-effort installed package version for the certificate."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("privacy_firewall")
    except PackageNotFoundError:  # pragma: no cover - only when not installed
        return "0.0.0+unknown"


def _document_text(document: Document) -> str:
    """Concatenate every text block's text across all pages."""
    parts: list[str] = []
    for page in document.pages:
        for block in page.blocks:
            if isinstance(block, TextBlock):
                parts.append(block.text)
    return "\n".join(parts)


def _is_extractable(value: str, haystack_raw: str, haystack_flat: str) -> bool:
    """Whether *value* still appears in the output text (case-insensitive).

    Checks both a raw substring match and a whitespace-flattened match, so a
    value the detector normalised (e.g. ``226251716424``) is still caught if
    the output retained it spaced (``2262 5171 6424``).
    """
    v_raw = value.casefold()
    if v_raw and v_raw in haystack_raw:
        return True
    v_flat = "".join(value.split()).casefold()
    return len(v_flat) >= _MIN_FLAT_LEN and v_flat in haystack_flat


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of re-scanning a redacted output for leaks.

    Attributes:
        passed: True when nothing that was redacted is still present.
        checked_values: Number of distinct redacted values verified.
        leaked_types: Detection types (not values) that were found to leak.
        literal_leaks: Redacted values still extractable from the text layer.
        residual_detections: Detector hits on the output matching a
            redacted value.
    """

    passed: bool
    checked_values: int
    leaked_types: tuple[str, ...]
    literal_leaks: int
    residual_detections: int


def verify_redaction(
    output_pdf: Path,
    redacted: list[Detection],
    *,
    registry: DetectorRegistry | None = None,
) -> VerificationResult:
    """Verify that *output_pdf* leaks none of the *redacted* detections.

    Args:
        output_pdf: The redacted PDF to inspect.
        redacted: The detections that were supposed to be removed.
        registry: Detector registry to re-scan with (defaults to all).

    Returns:
        A :class:`VerificationResult`.
    """
    registry = registry or build_registry()
    document = PDFParser(output_pdf).parse()
    text = _document_text(document)
    haystack_raw = text.casefold()
    haystack_flat = "".join(text.split()).casefold()

    # Map each distinct redacted value to the types it was redacted under.
    value_types: dict[str, set[str]] = {}
    for det in redacted:
        if det.text:
            value_types.setdefault(det.text, set()).add(det.detection_type)

    leaked_types: set[str] = set()

    # Check 1 — literal extractability from the output text layer.
    literal_leaks = 0
    for value, types in value_types.items():
        if _is_extractable(value, haystack_raw, haystack_flat):
            literal_leaks += 1
            leaked_types.update(types)

    # Check 2 — a detector re-fires on a value we meant to remove.
    residual = 0
    redacted_values = {v.casefold() for v in value_types}
    residual_result = registry.run_all(document)
    for det in residual_result.detections:
        if det.text.casefold() in redacted_values:
            residual += 1
            leaked_types.add(det.detection_type)

    return VerificationResult(
        passed=literal_leaks == 0 and residual == 0,
        checked_values=len(value_types),
        leaked_types=tuple(sorted(leaked_types)),
        literal_leaks=literal_leaks,
        residual_detections=residual,
    )


class Certificate(BaseModel):
    """Audit-grade record of one redaction. Contains no raw PII values."""

    schema_version: int = CERTIFICATE_SCHEMA_VERSION
    tool: str = "privacy-firewall"
    tool_version: str
    generated_at: str
    input_path: str
    input_sha256: str
    output_path: str
    output_sha256: str
    redactions_by_type: dict[str, int]
    total_redactions: int
    verification_passed: bool
    verification_detail: str
    leaked_types: list[str]


def build_certificate(
    input_pdf: Path,
    output_pdf: Path,
    redacted: list[Detection],
    result: VerificationResult,
) -> Certificate:
    """Assemble a :class:`Certificate` from a redaction and its verification."""
    by_type: dict[str, int] = {}
    for det in redacted:
        by_type[det.detection_type] = by_type.get(det.detection_type, 0) + 1

    if result.passed:
        detail = (
            f"All {result.checked_values} redacted value(s) verified absent "
            "from the output text layer."
        )
    else:
        detail = (
            f"LEAK: {result.literal_leaks} value(s) still extractable, "
            f"{result.residual_detections} detector re-hit(s) across "
            f"type(s): {', '.join(result.leaked_types)}."
        )

    return Certificate(
        tool_version=_tool_version(),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        input_path=str(input_pdf),
        input_sha256=file_sha256(input_pdf),
        output_path=str(output_pdf),
        output_sha256=file_sha256(output_pdf),
        redactions_by_type=dict(sorted(by_type.items())),
        total_redactions=len(redacted),
        verification_passed=result.passed,
        verification_detail=detail,
        leaked_types=list(result.leaked_types),
    )


def render_certificate_pdf(cert: Certificate, dest: Path) -> Path:
    """Render *cert* as a one-page PDF at *dest*."""
    import pypdfium2 as pdfium

    from privacy_firewall.parsers.pdfium_compat import Rect
    from privacy_firewall.renderer.pdfium_draw import PageWriter

    navy = (0.13, 0.29, 0.53)
    green = (0.14, 0.55, 0.24)
    red = (0.78, 0.11, 0.11)
    grey = (0.42, 0.42, 0.42)
    height = 842.0

    doc = pdfium.PdfDocument.new()
    try:
        raw_page = doc.new_page(595.0, height)
        page = PageWriter(doc, raw_page, height)

        def insert_text(
            origin: tuple[float, float],
            text: str,
            *,
            fontsize: float,
            color: tuple[float, float, float] = (0.0, 0.0, 0.0),
            fontname: str = "helv",
        ) -> None:
            page.insert_text(origin, text, fontsize=fontsize, fontname=fontname, color=color)

        page.draw_rect(Rect(0, 0, 595, 92), fill=navy)
        insert_text(
            (50, 50), "Redaction Certificate", fontsize=22, color=(1, 1, 1), fontname="hebo"
        )
        insert_text(
            (50, 74), "privacy-firewall - offline PII redaction", fontsize=10, color=(1, 1, 1)
        )

        ok = cert.verification_passed
        page.draw_rect(Rect(50, 116, 545, 158), fill=green if ok else red)
        insert_text(
            (64, 143),
            "VERIFICATION PASSED" if ok else "VERIFICATION FAILED",
            fontsize=16,
            color=(1, 1, 1),
            fontname="hebo",
        )

        rows: list[tuple[str, str]] = [
            ("Generated (UTC)", cert.generated_at),
            ("Tool version", f"{cert.tool} {cert.tool_version}"),
            ("Input file", Path(cert.input_path).name),
            ("Input SHA-256", cert.input_sha256),
            ("Output file", Path(cert.output_path).name),
            ("Output SHA-256", cert.output_sha256),
            ("Total redactions", str(cert.total_redactions)),
        ]
        y = 195
        for label, value in rows:
            insert_text((50, y), label, fontsize=10, color=grey)
            insert_text((220, y), value, fontsize=9, fontname="cour")
            y += 22

        y += 8
        insert_text((50, y), "Redactions by type", fontsize=11, color=navy, fontname="hebo")
        y += 20
        if cert.redactions_by_type:
            for dtype, count in cert.redactions_by_type.items():
                insert_text((60, y), dtype, fontsize=10, color=grey)
                insert_text((220, y), str(count), fontsize=10, fontname="cour")
                y += 18
        else:
            insert_text((60, y), "(none)", fontsize=10, color=grey)
            y += 18

        y += 12
        for line in _wrap(cert.verification_detail, 92):
            insert_text((50, y), line, fontsize=9, color=grey)
            y += 14

        page.finalize()
        with Path(dest).open("wb") as handle:
            doc.save(handle)
    finally:
        doc.close()
    return dest


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word-wrap for the certificate's detail line."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def certify(
    input_pdf: Path,
    output_pdf: Path,
    redacted: list[Detection],
    *,
    json_path: Path,
    pdf_path: Path | None = None,
    registry: DetectorRegistry | None = None,
) -> Certificate:
    """Verify *output_pdf*, build a certificate, and write it to disk.

    Args:
        input_pdf: The original document.
        output_pdf: The redacted document to verify.
        redacted: The detections that were redacted.
        json_path: Where to write the JSON manifest.
        pdf_path: Optional path for the one-page PDF certificate.
        registry: Detector registry for the re-scan (defaults to all).

    Returns:
        The written :class:`Certificate`.
    """
    result = verify_redaction(output_pdf, redacted, registry=registry)
    cert = build_certificate(input_pdf, output_pdf, redacted, result)
    json_path.write_text(cert.model_dump_json(indent=2), encoding="utf-8")
    if pdf_path is not None:
        render_certificate_pdf(cert, pdf_path)
    return cert
