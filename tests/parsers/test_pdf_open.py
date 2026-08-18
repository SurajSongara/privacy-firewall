"""Tests for password-aware PDF opening and the engine's encryption handling."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from privacy_firewall.diagnostics import DocumentAnalyzer
from privacy_firewall.engine.redact import redact_document
from privacy_firewall.engine.redaction import RedactionType
from privacy_firewall.parsers.pdf_open import (
    EncryptedPDFError,
    decrypted_bytes,
    is_encrypted,
    open_pdf,
)
from privacy_firewall.parsers.pdf_parser import PDFParser

_PW = "secret"


def _make_locked_pdf(path: Path, text: str = "PAN: ABCPE1234F") -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), text, fontsize=12)
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=_PW, owner_pw=_PW)
    doc.close()


def _make_plain_pdf(path: Path, text: str = "PAN: ABCPE1234F") -> None:
    doc = fitz.open()
    doc.new_page().insert_text((50, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


class TestOpenPdf:
    def test_open_plain_pdf(self, tmp_path: Path) -> None:
        p = tmp_path / "plain.pdf"
        _make_plain_pdf(p)
        doc = open_pdf(p)
        assert doc.page_count == 1
        doc.close()

    def test_locked_without_password_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        with pytest.raises(EncryptedPDFError, match="password-protected"):
            open_pdf(p)

    def test_locked_wrong_password_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        with pytest.raises(EncryptedPDFError, match="Incorrect password"):
            open_pdf(p, password="wrong")

    def test_locked_correct_password_opens(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        doc = open_pdf(p, password=_PW)
        assert "ABCPE1234F" in doc[0].get_text("text")
        doc.close()

    def test_required_false_returns_locked_doc(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        doc = open_pdf(p, required=False)
        assert doc.needs_pass
        doc.close()

    def test_is_encrypted(self, tmp_path: Path) -> None:
        locked = tmp_path / "locked.pdf"
        plain = tmp_path / "plain.pdf"
        _make_locked_pdf(locked)
        _make_plain_pdf(plain)
        assert is_encrypted(locked)
        assert not is_encrypted(plain)

    def test_decrypted_bytes(self, tmp_path: Path) -> None:
        locked = tmp_path / "locked.pdf"
        plain = tmp_path / "plain.pdf"
        _make_locked_pdf(locked)
        _make_plain_pdf(plain)
        # Plain file → None (use the path directly).
        assert decrypted_bytes(plain) is None
        # Locked file → decrypted, openable-without-password bytes.
        data = decrypted_bytes(locked, _PW)
        assert data is not None
        reopened = fitz.open(stream=data, filetype="pdf")
        assert not reopened.needs_pass
        assert "ABCPE1234F" in reopened[0].get_text("text")
        reopened.close()

    def test_decrypted_bytes_wrong_password(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        with pytest.raises(EncryptedPDFError):
            decrypted_bytes(p, "nope")


class TestParserWithPassword:
    def test_parser_reads_locked_pdf(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        doc = PDFParser(p, password=_PW).parse()
        text = " ".join(b.text for page in doc.pages for b in page.blocks if hasattr(b, "text"))
        assert "ABCPE1234F" in text

    def test_parser_without_password_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        with pytest.raises(EncryptedPDFError):
            PDFParser(p).parse()


class TestAnalyzerWithPassword:
    def test_analyzer_reports_encrypted_when_locked(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        report = DocumentAnalyzer(p).analyze()  # no password
        assert report.is_encrypted
        assert not report.has_native_text

    def test_analyzer_reads_content_with_password(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        report = DocumentAnalyzer(p, _PW).analyze()
        assert report.has_native_text  # unlocked → content analysed


class TestRedactLockedPdf:
    def test_redacts_locked_pdf_and_output_is_unencrypted(self, tmp_path: Path) -> None:
        src = tmp_path / "locked.pdf"
        out = tmp_path / "out.pdf"
        _make_locked_pdf(src, "PAN: ABCPE1234F and phone 9876543210")

        out_path, detections, _ = redact_document(
            src, out, redaction_type=RedactionType.REPLACE, password=_PW
        )
        assert detections  # PII was found behind the password
        # The redacted output opens WITHOUT a password and leaks no PII.
        reopened = fitz.open(str(out_path))
        assert not reopened.needs_pass
        text = reopened[0].get_text("text")
        assert "ABCPE1234F" not in text
        reopened.close()

    def test_redact_without_password_raises(self, tmp_path: Path) -> None:
        src = tmp_path / "locked.pdf"
        out = tmp_path / "out.pdf"
        _make_locked_pdf(src)
        with pytest.raises(EncryptedPDFError):
            redact_document(src, out)


class TestCliPassword:
    def test_detect_without_password_errors_clearly(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from privacy_firewall.__main__ import app

        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        result = CliRunner().invoke(app, ["detect", str(p)])
        assert result.exit_code == 1
        assert "password-protected" in result.output

    def test_detect_with_password_finds_pii(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from privacy_firewall.__main__ import app

        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p, "PAN: ABCPE1234F")
        result = CliRunner().invoke(app, ["detect", str(p), "--password", _PW])
        assert result.exit_code == 0, result.output
        assert "ABCPE1234F" in result.output

    def test_redact_with_password_and_certificate(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from privacy_firewall.__main__ import app

        src = tmp_path / "locked.pdf"
        out = tmp_path / "out.pdf"
        _make_locked_pdf(src, "PAN: ABCPE1234F")
        result = CliRunner().invoke(
            app, ["redact", str(src), str(out), "--password", _PW, "--certificate"]
        )
        assert result.exit_code == 0, result.output
        assert "PASSED" in result.output
        assert out.exists()

    def test_doctor_flags_password_protected(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from privacy_firewall.__main__ import app

        p = tmp_path / "locked.pdf"
        _make_locked_pdf(p)
        result = CliRunner().invoke(app, ["doctor", str(p)])
        assert "password-protected" in result.output
        assert "--password" in result.output
