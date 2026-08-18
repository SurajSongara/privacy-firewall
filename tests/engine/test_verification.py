"""Tests for post-redaction verification and the certificate."""

from __future__ import annotations

from pathlib import Path

import fitz

from privacy_firewall.detectors import build_registry
from privacy_firewall.engine.context import ContextScorer
from privacy_firewall.engine.fusion import FusionEngine
from privacy_firewall.engine.ocr_pipeline import get_merged_document
from privacy_firewall.engine.redaction import RedactionPlanner, RedactionType
from privacy_firewall.engine.verification import (
    build_certificate,
    certify,
    verify_redaction,
)
from privacy_firewall.models.detection import Detection
from privacy_firewall.renderer.pdf_renderer import PDFRenderer

# Synthetic PII only — fabricated values.
_PII_LINES = [
    "PAN: ABCPE1234F",
    "Email: john@example.com",
    "Phone: 9876543210",
]


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for line in _PII_LINES:
        page.insert_text((50, y), line, fontsize=12)
        y += 30
    doc.save(str(path))
    doc.close()


def _detect(pdf: Path) -> list[Detection]:
    document, _ = get_merged_document(pdf)
    result = build_registry().run_all(document, values_only=True)
    scored = ContextScorer().apply(document, result.detections)
    return FusionEngine().fuse(scored).detections


def _redact(pdf: Path, out: Path) -> list[Detection]:
    document, _ = get_merged_document(pdf)
    detections = _detect(pdf)
    plan = RedactionPlanner().plan(document, detections, default_type=RedactionType.REPLACE)
    PDFRenderer().render(pdf, out, plan)
    return detections


class TestVerifyRedaction:
    def test_clean_redaction_passes(self, tmp_path: Path) -> None:
        src = tmp_path / "in.pdf"
        out = tmp_path / "out.pdf"
        _make_pdf(src)
        detections = _redact(src, out)
        assert detections  # sanity: the pipeline found PII

        result = verify_redaction(out, detections)
        assert result.passed
        assert result.literal_leaks == 0
        assert result.residual_detections == 0
        assert result.leaked_types == ()
        assert result.checked_values > 0

    def test_leaky_output_fails(self, tmp_path: Path) -> None:
        # Verifying the ORIGINAL (unredacted) file against the detections
        # must fail — every value is still extractable.
        src = tmp_path / "in.pdf"
        out = tmp_path / "out.pdf"
        _make_pdf(src)
        detections = _redact(src, out)

        result = verify_redaction(src, detections)
        assert not result.passed
        assert result.literal_leaks > 0
        assert result.leaked_types  # types are reported, values are not


class TestCertificate:
    def test_certificate_hashes_and_counts(self, tmp_path: Path) -> None:
        src = tmp_path / "in.pdf"
        out = tmp_path / "out.pdf"
        _make_pdf(src)
        detections = _redact(src, out)
        result = verify_redaction(out, detections)

        cert = build_certificate(src, out, detections, result)
        assert cert.verification_passed
        assert cert.total_redactions == len(detections)
        assert sum(cert.redactions_by_type.values()) == len(detections)
        # 64-hex SHA-256 for both files.
        assert len(cert.input_sha256) == 64
        assert len(cert.output_sha256) == 64
        assert cert.input_sha256 != cert.output_sha256

    def test_certificate_contains_no_raw_pii(self, tmp_path: Path) -> None:
        src = tmp_path / "in.pdf"
        out = tmp_path / "out.pdf"
        _make_pdf(src)
        detections = _redact(src, out)
        result = verify_redaction(out, detections)
        cert = build_certificate(src, out, detections, result)

        blob = cert.model_dump_json()
        assert "ABCPE1234F" not in blob
        assert "john@example.com" not in blob
        assert "9876543210" not in blob

    def test_certify_writes_json_and_pdf(self, tmp_path: Path) -> None:
        src = tmp_path / "in.pdf"
        out = tmp_path / "out.pdf"
        _make_pdf(src)
        detections = _redact(src, out)

        json_path = tmp_path / "cert.json"
        pdf_path = tmp_path / "cert.pdf"
        cert = certify(src, out, detections, json_path=json_path, pdf_path=pdf_path)

        assert json_path.exists()
        assert pdf_path.exists()
        assert cert.verification_passed
        # The rendered certificate is a valid, single-page PDF.
        doc = fitz.open(str(pdf_path))
        assert doc.page_count == 1
        doc.close()
