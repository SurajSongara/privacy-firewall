"""Regression tests for redacting repeated occurrences of the same value.

A PII value often appears more than once on a page — most notably an Aadhaar
number written both plainly (``862583142918``) and in its canonical spaced form
(``8625 8314 2918``). Every occurrence must be physically removed; leaving the
second one on the page defeats the redaction. These tests lock in that guarantee
end to end (detection through rendering), since the failure mode split across the
detector's de-duplication and the renderer's bbox refinement.

PyMuPDF (``fitz``) builds the fixtures; the engine reads and redacts through its
own PDFium shim. All values are fabricated and checksum-valid.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from privacy_firewall.engine.redact import redact_document
from privacy_firewall.parsers.pdfium_compat import open_document

# 862583142918 is a valid Aadhaar (Verhoeff checksum, first digit 2-9).
_PLAIN = "862583142918"
_SPACED = "8625 8314 2918"


def _redact(tmp_path: Path, lines: list[str]) -> str:
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420, height=300)
    for i, line in enumerate(lines):
        page.insert_text((50, 60 + i * 40), line, fontsize=12)
    doc.save(str(src))
    doc.close()

    redact_document(src, out)
    with open_document(str(out)) as opened:
        return opened[0].get_text("text")


def test_both_plain_and_spaced_occurrences_are_removed(tmp_path: Path) -> None:
    text = _redact(tmp_path, [f"A: {_PLAIN}", f"B: {_SPACED}"])
    assert _PLAIN not in text
    assert _SPACED not in text


def test_spaced_form_removed_even_when_listed_before_plain(tmp_path: Path) -> None:
    # Order must not matter: the spaced form appearing first once caused the
    # whole-page fallback to redact the plain twin and skip the spaced one.
    text = _redact(tmp_path, [f"B: {_SPACED}", f"A: {_PLAIN}"])
    assert _PLAIN not in text
    assert _SPACED not in text


def test_repeated_plain_value_removed_from_every_line(tmp_path: Path) -> None:
    text = _redact(tmp_path, [f"Line {i}: {_PLAIN}" for i in range(3)])
    assert _PLAIN not in text


def test_repeated_values_removed_across_detectors(tmp_path: Path) -> None:
    # The same leak class affected phone, account, IFSC and UPI: a value found
    # in two places was detected once and only redacted once, leaving the second
    # occurrence in the output. Every type must be removed at both places.
    cases = {
        "9876543210": ["Mobile: 9876543210", "Contact: 9876543210"],
        "30512345678": ["Account No: 30512345678", "A/c No: 30512345678"],
        "HDFC0001234": ["IFSC: HDFC0001234", "Branch IFSC: HDFC0001234"],
        "rajesh@okhdfcbank": ["UPI: rajesh@okhdfcbank", "Pay to: rajesh@okhdfcbank"],
    }
    lines = [line for pair in cases.values() for line in pair]
    text = _redact(tmp_path, lines)
    for value in cases:
        assert value not in text, f"{value} still present after redaction"
