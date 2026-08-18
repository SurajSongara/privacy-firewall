"""Tests for the ``redact-batch`` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
from typer.testing import CliRunner

from privacy_firewall.__main__ import app

runner = CliRunner()


def _make_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for line in lines:
        page.insert_text((50, y), line, fontsize=12)
        y += 30
    doc.save(str(path))
    doc.close()


def _make_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "docs"
    folder.mkdir()
    _make_pdf(folder / "statement.pdf", ["PAN: ABCPE1234F", "Phone: 9876543210"])
    _make_pdf(folder / "invoice.pdf", ["Email: jane@example.com"])
    (folder / "notes.txt").write_text("Account: 50100123456789\n", encoding="utf-8")
    return folder


class TestRedactBatch:
    def test_redacts_all_and_writes_summary(self, tmp_path: Path) -> None:
        folder = _make_folder(tmp_path)
        result = runner.invoke(app, ["redact-batch", str(folder)])
        assert result.exit_code == 0, result.output

        # A redacted copy for every input (incl. the converted txt).
        assert (folder / "statement.redacted.pdf").exists()
        assert (folder / "invoice.redacted.pdf").exists()
        assert (folder / "notes.redacted.pdf").exists()
        # Originals untouched.
        assert (folder / "statement.pdf").exists()

        summary = json.loads((folder / "redaction-summary.json").read_text(encoding="utf-8"))
        by_file = {r["file"]: r for r in summary}
        assert by_file["statement.pdf"]["status"] == "ok"
        assert by_file["statement.pdf"]["redactions"] >= 2
        assert (folder / "redaction-summary.csv").exists()

    def test_out_dir_keeps_originals_folder_clean(self, tmp_path: Path) -> None:
        folder = _make_folder(tmp_path)
        out = tmp_path / "redacted"
        result = runner.invoke(app, ["redact-batch", str(folder), "--out", str(out)])
        assert result.exit_code == 0, result.output
        assert (out / "statement.redacted.pdf").exists()
        assert not (folder / "statement.redacted.pdf").exists()

    def test_certificate_flag_verifies_each_file(self, tmp_path: Path) -> None:
        folder = _make_folder(tmp_path)
        result = runner.invoke(app, ["redact-batch", str(folder), "--certificate"])
        assert result.exit_code == 0, result.output
        assert (folder / "statement.redacted.certificate.json").exists()
        summary = json.loads((folder / "redaction-summary.json").read_text(encoding="utf-8"))
        assert all(r["verified"] == "pass" for r in summary if r["status"] == "ok")

    def test_corrupt_file_reported_not_aborting(self, tmp_path: Path) -> None:
        folder = _make_folder(tmp_path)
        # A file with a PDF suffix but invalid content.
        (folder / "broken.pdf").write_bytes(b"not a pdf")
        result = runner.invoke(app, ["redact-batch", str(folder)])

        # One file errored → non-zero exit, but the good files still processed.
        assert result.exit_code == 1
        assert (folder / "statement.redacted.pdf").exists()
        summary = json.loads((folder / "redaction-summary.json").read_text(encoding="utf-8"))
        by_file = {r["file"]: r for r in summary}
        assert by_file["broken.pdf"]["status"] == "error"
        assert by_file["statement.pdf"]["status"] == "ok"

    def test_empty_folder_is_a_clean_noop(self, tmp_path: Path) -> None:
        folder = tmp_path / "empty"
        folder.mkdir()
        result = runner.invoke(app, ["redact-batch", str(folder)])
        assert result.exit_code == 0
        assert "No supported documents" in result.output

    def test_reredacting_does_not_pick_up_outputs(self, tmp_path: Path) -> None:
        folder = _make_folder(tmp_path)
        runner.invoke(app, ["redact-batch", str(folder)])
        # Second run must not treat *.redacted.pdf as new inputs.
        result = runner.invoke(app, ["redact-batch", str(folder)])
        assert result.exit_code == 0, result.output
        summary = json.loads((folder / "redaction-summary.json").read_text(encoding="utf-8"))
        assert not any(r["file"].endswith(".redacted.pdf") for r in summary)
