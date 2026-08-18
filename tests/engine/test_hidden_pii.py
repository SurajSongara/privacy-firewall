"""Tests for hidden-surface PII: metadata, annotations and form fields.

These cover the leak class that page-text extraction cannot see — PII stamped
into the document Info dictionary or stored in annotations/form fields — end to
end: extraction, scanning with the real detectors, sanitisation on the redacted
output, and the verifier refusing to pass a document that still leaks there.

PyMuPDF (``fitz``) is used only to *build* fixtures with hidden PII; the engine
reads and redacts them through its own PDFium shim.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from privacy_firewall.engine.hidden_pii import scan_hidden_pii
from privacy_firewall.engine.redact import redact_document
from privacy_firewall.engine.verification import verify_redaction
from privacy_firewall.parsers.pdfium_compat import open_document

# All fabricated, checksum-valid where the detector needs it.
_META = {
    "author": "Ravi Kumar Sharma",
    "title": "Account 30512345678",
    "subject": "ravi@example.com",
    "keywords": "9876543210",
}
_ANNOT_TEXT = "call me 9876543210"
_FIELD_VALUE = "ABCPE1234F"


def _pdf_with_hidden_pii(path: Path) -> None:
    """Build a one-page PDF with PII in metadata, an annotation and a field."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 50), "Visible PAN: ABCPE1234F", fontsize=12)
    doc.set_metadata(_META)
    page.add_text_annot((200, 50), _ANNOT_TEXT)
    widget = fitz.Widget()
    widget.field_name = "pan_field"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_value = _FIELD_VALUE
    widget.rect = fitz.Rect(50, 120, 200, 140)
    page.add_widget(widget)
    doc.save(str(path))
    doc.close()


def _clean_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "PAN: ABCPE1234F", fontsize=12)
    doc.save(str(path))
    doc.close()


class TestExtraction:
    def test_metadata_reads_pii_keys_only(self, tmp_path: Path) -> None:
        pdf = tmp_path / "h.pdf"
        _pdf_with_hidden_pii(pdf)
        with open_document(str(pdf)) as doc:
            meta = doc.metadata()
        assert meta["Author"] == "Ravi Kumar Sharma"
        assert meta["Title"] == "Account 30512345678"
        # Producer/Creator noise is excluded.
        assert "Producer" not in meta and "Creator" not in meta

    def test_annotations_expose_note_and_field(self, tmp_path: Path) -> None:
        pdf = tmp_path / "h.pdf"
        _pdf_with_hidden_pii(pdf)
        with open_document(str(pdf)) as doc:
            annots = doc[0].annotations()
        texts = {a.text for a in annots}
        assert _ANNOT_TEXT in texts
        assert _FIELD_VALUE in texts
        field = next(a for a in annots if a.subtype == "widget")
        assert field.field_name == "pan_field"
        assert not field.rect.is_empty


class TestScan:
    def test_scan_finds_pii_across_all_surfaces(self, tmp_path: Path) -> None:
        pdf = tmp_path / "h.pdf"
        _pdf_with_hidden_pii(pdf)
        with open_document(str(pdf)) as doc:
            findings = scan_hidden_pii(doc)

        by_surface = {(f.surface, f.detection_type, f.value) for f in findings}
        assert ("metadata", "ACCOUNT", "30512345678") in by_surface
        assert ("metadata", "EMAIL", "ravi@example.com") in by_surface
        assert ("annotation", "PHONE", "9876543210") in by_surface
        assert ("form-field", "PAN", "ABCPE1234F") in by_surface

    def test_clean_document_has_no_hidden_pii(self, tmp_path: Path) -> None:
        pdf = tmp_path / "c.pdf"
        _clean_pdf(pdf)
        with open_document(str(pdf)) as doc:
            assert scan_hidden_pii(doc) == []


class TestSanitizeOnRedaction:
    def test_redaction_strips_metadata_and_annotations(self, tmp_path: Path) -> None:
        src = tmp_path / "in.pdf"
        out = tmp_path / "out.pdf"
        _pdf_with_hidden_pii(src)

        redact_document(src, out)

        with open_document(str(out)) as doc:
            assert doc.metadata() == {}
            assert doc[0].annotations() == []
            assert scan_hidden_pii(doc) == []

    def test_annotation_text_is_gone_from_raw_bytes(self, tmp_path: Path) -> None:
        src = tmp_path / "in.pdf"
        out = tmp_path / "out.pdf"
        _pdf_with_hidden_pii(src)
        redact_document(src, out)

        # Independent engine + raw bytes: the sticky-note phone must be gone.
        ref = fitz.open(str(out))
        raw = ref.tobytes(garbage=0, deflate=False)
        ref.close()
        assert b"9876543210" not in raw
        assert b"Ravi Kumar Sharma" not in raw


class TestVerificationSeesHiddenSurfaces:
    def test_verify_fails_when_hidden_pii_survives(self, tmp_path: Path) -> None:
        # An unsanitised document with hidden PII, checked as if it were output.
        leaky = tmp_path / "leaky.pdf"
        _pdf_with_hidden_pii(leaky)
        result = verify_redaction(leaky, [])
        assert not result.passed
        assert result.hidden_leaks > 0

    def test_verify_passes_on_sanitised_output(self, tmp_path: Path) -> None:
        src = tmp_path / "in.pdf"
        out = tmp_path / "out.pdf"
        _pdf_with_hidden_pii(src)
        _, detections, _ = redact_document(src, out)
        result = verify_redaction(out, detections)
        assert result.passed
        assert result.hidden_leaks == 0

    def test_hidden_leak_reported_even_without_redaction_claim(
        self, tmp_path: Path
    ) -> None:
        # Empty redaction list: the hidden-surface check must still fire so the
        # certificate cannot claim "clean" while metadata leaks.
        leaky = tmp_path / "leaky.pdf"
        _pdf_with_hidden_pii(leaky)
        result = verify_redaction(leaky, [])
        assert result.hidden_leaks >= 4
