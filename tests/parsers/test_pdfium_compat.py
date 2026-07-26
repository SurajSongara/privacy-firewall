"""Tests for the PDFium read shim.

These cover the invariants that are easy to get silently wrong in the port and
that the end-to-end tests would only catch as a vague geometry drift: the
coordinate flip, character indexing on damaged PDFs, block boundaries, and the
``Rect`` algebra the renderer depends on.

PyMuPDF is used here purely as an *independent* reference implementation — it is
a test-only dependency and is never shipped.
"""

from __future__ import annotations

import fitz
import pytest

from privacy_firewall.parsers.pdfium_compat import Rect, open_document


def _pdf(lines: list[tuple[float, float, str]], *, rotation: int = 0) -> bytes:
    """Build a single-page PDF with *lines* of ``(x, y, text)``."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=12)
    if rotation:
        page.set_rotation(rotation)
    data: bytes = doc.tobytes()
    doc.close()
    return data


class TestRect:
    def test_bare_rect_is_empty_and_absorbed_by_union(self) -> None:
        rect = Rect()
        assert rect.is_empty
        assert (rect | Rect(10, 20, 30, 40)) == Rect(10, 20, 30, 40)

    def test_explicit_zero_rect_is_not_the_empty_sentinel(self) -> None:
        # A non-overlapping intersection returns this; it must not swallow a
        # subsequent union the way the empty sentinel does.
        zero = Rect(0.0, 0.0, 0.0, 0.0)
        assert zero.is_empty
        assert (zero | Rect(10, 10, 20, 20)) == Rect(0, 0, 20, 20)

    def test_intersection_of_disjoint_rects_has_no_area(self) -> None:
        assert (Rect(0, 0, 5, 5) & Rect(10, 10, 20, 20)).is_empty

    def test_intersects_excludes_touching_edges(self) -> None:
        assert not Rect(0, 0, 10, 10).intersects(Rect(10, 0, 20, 10))
        assert Rect(0, 0, 10, 10).intersects(Rect(9, 0, 20, 10))

    def test_width_and_height_never_negative(self) -> None:
        assert Rect().width == 0.0
        assert Rect().height == 0.0


class TestCoordinateFlip:
    def test_word_boxes_match_pymupdf(self) -> None:
        data = _pdf([(60, 130, "PAN: ABCPE1234F")])
        reference = fitz.open(stream=data, filetype="pdf")
        expected = reference[0].get_text("words")
        reference.close()

        with open_document(stream=data) as doc:
            actual = doc[0].get_text("words")

        assert [w[4] for w in actual] == [w[4] for w in expected]
        for got, want in zip(actual, expected):
            # Horizontal extents agree exactly; vertical ones differ by a couple
            # of points because the two engines derive the line box from
            # slightly different font metrics.
            assert got[0] == pytest.approx(want[0], abs=0.5)
            assert got[2] == pytest.approx(want[2], abs=0.5)
            assert got[1] == pytest.approx(want[1], abs=3.0)
            assert got[3] == pytest.approx(want[3], abs=3.0)

    @pytest.mark.parametrize("rotation", [0, 90, 180, 270])
    def test_text_geometry_is_rotation_independent(self, rotation: int) -> None:
        # Text lives in unrotated page space in both engines; only the reported
        # page size changes. Flipping with the rotated height would break this.
        data = _pdf([(60, 130, "PAN: ABCPE1234F")], rotation=rotation)
        with open_document(stream=data) as doc:
            word = doc[0].get_text("words")[0]
        assert word[0] == pytest.approx(60.0, abs=2.0)
        assert word[1] == pytest.approx(117.0, abs=4.0)

    def test_page_rect_follows_rotation(self) -> None:
        with open_document(stream=_pdf([(60, 130, "x")], rotation=90)) as doc:
            rect = doc[0].rect
        assert (rect.width, rect.height) == (842.0, 595.0)


class TestCharacterIndexing:
    def test_unmapped_glyphs_do_not_shift_boxes(self) -> None:
        """PDFium counts NUL glyphs but omits them from ``get_text_range()``.

        Indexing boxes by string position would misalign every word after the
        first unmapped glyph, so the shim indexes by character instead.
        """
        data = _pdf([(50, 100, "\x00" * 20 + "SECRET"), (50, 140, "PAN: ABCPE1234F")])
        with open_document(stream=data) as doc:
            words = {w[4]: w for w in doc[0].get_text("words")}

        assert "ABCPE1234F" in words
        # Without the fix this lands far from its true position on the page.
        assert words["ABCPE1234F"][1] == pytest.approx(128.0, abs=5.0)

    def test_control_characters_break_words(self) -> None:
        data = _pdf([(50, 100, "\x00" * 20 + "SECRET")])
        with open_document(stream=data) as doc:
            texts = [w[4] for w in doc[0].get_text("words")]
        assert "SECRET" in texts


class TestBlocks:
    def test_blocks_follow_text_objects_not_geometry(self) -> None:
        """Each ``insert_text`` is its own text object, so each is its own block.

        Detectors read a block's text as one string; merging separate blocks
        would let one block's label vouch for another block's value.
        """
        data = _pdf(
            [(50, 100, "UTR: 7987465071"), (50, 116, "Ref ID: 8223027920")]
        )
        with open_document(stream=data) as doc:
            blocks = [b for b in doc[0].get_text("dict")["blocks"] if b["type"] == 0]

        assert len(blocks) == 2
        texts = ["".join(s["text"] for ln in b["lines"] for s in ln["spans"]) for b in blocks]
        assert texts == ["UTR: 7987465071", "Ref ID: 8223027920"]

    def test_splits_where_pymupdf_would_merge_a_paragraph(self) -> None:
        """A deliberate, documented difference from PyMuPDF.

        PyMuPDF merges closely-spaced lines into one paragraph block; the shim
        keeps one block per text object. Splitting is the safe direction for
        detection — a detector sees less unrelated text in one string, so a
        label on one line cannot vouch for a value on another.
        """
        data = _pdf([(50, 100 + 16 * i, f"Field {i}: value{i}") for i in range(6)])
        reference = fitz.open(stream=data, filetype="pdf")
        merged = len([b for b in reference[0].get_text("dict")["blocks"] if b["type"] == 0])
        reference.close()

        with open_document(stream=data) as doc:
            actual = len([b for b in doc[0].get_text("dict")["blocks"] if b["type"] == 0])

        assert merged == 1
        assert actual == 6


class TestExtractionShapes:
    def test_text_matches_pymupdf(self) -> None:
        data = _pdf([(50, 100, "State Bank of India"), (50, 130, "PAN: ABCPE1234F")])
        reference = fitz.open(stream=data, filetype="pdf")
        expected = " ".join(reference[0].get_text("text").split())
        reference.close()

        with open_document(stream=data) as doc:
            actual = " ".join(doc[0].get_text("text").split())
        assert actual == expected

    def test_rawdict_exposes_per_character_geometry(self) -> None:
        with open_document(stream=_pdf([(50, 100, "AB")])) as doc:
            blocks = doc[0].get_text("rawdict")["blocks"]
        chars = [c for b in blocks for ln in b["lines"] for s in ln["spans"] for c in s["chars"]]
        assert [c["c"] for c in chars] == ["A", "B"]
        assert all(len(c["bbox"]) == 4 and len(c["origin"]) == 2 for c in chars)

    def test_dict_omits_per_character_detail(self) -> None:
        with open_document(stream=_pdf([(50, 100, "AB")])) as doc:
            blocks = doc[0].get_text("dict")["blocks"]
        spans = [s for b in blocks for ln in b["lines"] for s in ln["spans"]]
        assert spans and all("chars" not in s for s in spans)

    def test_unknown_kind_is_rejected(self) -> None:
        with open_document(stream=_pdf([(50, 100, "AB")])) as doc, pytest.raises(ValueError):
            doc[0].get_text("html")

    def test_search_finds_every_occurrence(self) -> None:
        data = _pdf([(50, 100, "ABCPE1234F"), (50, 130, "ABCPE1234F")])
        with open_document(stream=data) as doc:
            hits = doc[0].search_for("ABCPE1234F")
        assert len(hits) == 2
        assert all(not h.is_empty for h in hits)

    def test_search_respects_clip(self) -> None:
        data = _pdf([(50, 100, "ABCPE1234F"), (50, 130, "ABCPE1234F")])
        with open_document(stream=data) as doc:
            page = doc[0]
            hits = page.search_for("ABCPE1234F", clip=Rect(0, 85, 595, 110))
        assert len(hits) == 1


class TestDocumentState:
    def test_locked_document_reports_needs_pass(self) -> None:
        doc = fitz.open()
        doc.new_page().insert_text((60, 100), "secret")
        data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="pw")
        doc.close()

        with open_document(stream=data) as opened:
            assert opened.needs_pass is True
            assert len(opened) == 0

    def test_correct_password_unlocks_and_reports_encrypted(self) -> None:
        doc = fitz.open()
        doc.new_page().insert_text((60, 100), "secret")
        data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="pw")
        doc.close()

        with open_document(stream=data, password="pw") as opened:
            assert opened.needs_pass is False
            assert opened.is_encrypted is True
            assert "secret" in opened[0].get_text("text")

    def test_plain_document_is_not_reported_as_encrypted(self) -> None:
        with open_document(stream=_pdf([(50, 100, "hello")])) as doc:
            assert doc.is_encrypted is False

    def test_save_drops_encryption(self) -> None:
        doc = fitz.open()
        doc.new_page().insert_text((60, 100), "secret")
        data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="pw")
        doc.close()

        with open_document(stream=data, password="pw") as opened:
            saved = opened.tobytes()

        # PDFium's SaveAsCopy keeps the source crypt dict; the shim copies pages
        # into a fresh document so a redacted copy opens without a password.
        check = fitz.open(stream=saved, filetype="pdf")
        assert check.needs_pass == 0
        check.close()

    def test_iterates_pages(self) -> None:
        doc = fitz.open()
        for _ in range(3):
            doc.new_page()
        data = doc.tobytes()
        doc.close()

        with open_document(stream=data) as opened:
            assert len(list(opened)) == 3


class TestHiddenSurfaces:
    """Metadata and annotations — text outside the page content stream."""

    def _pdf_with_hidden(self) -> bytes:
        doc = fitz.open()
        page = doc.new_page(width=400, height=300)
        page.insert_text((50, 50), "on page", fontsize=12)
        doc.set_metadata({"author": "Ravi Sharma", "keywords": "9876543210"})
        page.add_text_annot((200, 50), "note 9876543210")
        data: bytes = doc.tobytes()
        doc.close()
        return data

    def test_metadata_excludes_producer_noise(self) -> None:
        with open_document(stream=self._pdf_with_hidden()) as doc:
            meta = doc.metadata()
        assert meta.get("Author") == "Ravi Sharma"
        assert meta.get("Keywords") == "9876543210"
        assert "Producer" not in meta

    def test_annotation_text_and_rect_are_exposed(self) -> None:
        with open_document(stream=self._pdf_with_hidden()) as doc:
            annots = doc[0].annotations()
        assert any("9876543210" in a.text for a in annots)
        assert all(not a.rect.is_empty for a in annots)

    def test_sanitise_drops_metadata_and_annotations(self) -> None:
        with open_document(stream=self._pdf_with_hidden()) as doc:
            cleaned = doc.tobytes(sanitize=True)
        with open_document(stream=cleaned) as out:
            assert out.metadata() == {}
            assert out[0].annotations() == []

    def test_default_save_is_not_sanitised(self) -> None:
        # Annotations survive a plain round-trip; only redaction sanitises.
        with open_document(stream=self._pdf_with_hidden()) as doc:
            plain = doc.tobytes()
        with open_document(stream=plain) as out:
            assert out[0].annotations()
