"""Tests for the ReviewSession (engine side of the review UI)."""

from pathlib import Path

import fitz
import pytest

from privacy_firewall.policy import BUILTIN_POLICIES
from privacy_firewall.ui.session import ReviewSession


@pytest.fixture
def pii_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "PAN: AAAAA1111A", fontsize=12)
    page.insert_text((50, 140), "UPI: someone@unknownhandle", fontsize=12)
    page.insert_text((50, 180), "Customer: Ramesh Kumar", fontsize=12)
    page.insert_text((50, 220), "Dear RAMESH KUMAR, your account is active", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def session(pii_pdf: Path) -> ReviewSession:
    return ReviewSession(pii_pdf, BUILTIN_POLICIES["share-with-ai"])


class TestReviewSession:
    def test_summary_shape(self, session: ReviewSession) -> None:
        summary = session.summary()
        assert summary["policy"] == "share-with-ai"
        assert summary["pages"][0]["page_number"] == 1
        assert summary["counts"]["redact"] >= 1
        types = {e["type"] for e in summary["entries"]}
        assert "PAN" in types
        assert "UPI" in types
        for entry in summary["entries"]:
            assert entry["detection_id"]
            assert entry["reasons"]
            assert entry["effective_action"] in ("redact", "keep", "ask")

    def test_set_decision(self, session: ReviewSession) -> None:
        entry_id = session.summary()["entries"][0]["detection_id"]
        assert session.set_decision(entry_id, "keep")
        updated = next(e for e in session.summary()["entries"] if e["detection_id"] == entry_id)
        assert updated["decision"] == "keep"
        assert updated["effective_action"] == "keep"
        assert session.set_decision(entry_id, None)
        assert not session.set_decision("bogus-id", "keep")

    def test_page_png_cached(self, session: ReviewSession) -> None:
        png1 = session.page_png(1)
        assert png1[:8] == b"\x89PNG\r\n\x1a\n"
        assert session.page_png(1) is png1

    def test_page_png_cache_is_bounded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "many.pdf"
        doc = fitz.open()
        for i in range(4):
            page = doc.new_page()
            page.insert_text((50, 100), f"page {i + 1}", fontsize=12)
        doc.save(str(path))
        doc.close()

        monkeypatch.setattr(ReviewSession, "PAGE_CACHE_PAGES", 2)
        session = ReviewSession(path, BUILTIN_POLICIES["share-with-ai"])
        for n in range(1, 5):
            session.page_png(n)
        assert len(session._page_cache) == 2
        assert set(session._page_cache) == {3, 4}  # LRU keeps the newest

    def test_apply_writes_redacted_pdf_and_plan(self, session: ReviewSession) -> None:
        out_path, count = session.apply()
        assert out_path.exists()
        assert out_path.name == "doc.redacted.pdf"
        assert count >= 1
        assert session.plan_file_path.exists()
        # The redacted PDF must no longer contain the PAN — the value is
        # replaced with stars, not blacked out.
        with fitz.open(out_path) as doc:
            text = doc[0].get_text()
        assert "AAAAA1111A" not in text
        assert "*****" in text

    def test_lazy_session_runs_on_demand(self, pii_pdf: Path) -> None:
        session = ReviewSession(pii_pdf, BUILTIN_POLICIES["share-with-ai"], lazy=True)
        assert session.status == "starting"
        assert not session.is_ready
        with pytest.raises(RuntimeError, match="not finished"):
            _ = session.plan
        with pytest.raises(RuntimeError, match="not finished"):
            _ = session.document
        session.run()
        assert session.is_ready
        assert session.status_payload() == {
            "status": "ready",
            "detail": "",
            "needs_password": False,
        }
        assert session.plan.entries

    def test_lazy_session_records_error(self, tmp_path: Path) -> None:
        bogus = tmp_path / "not-a-pdf.pdf"
        bogus.write_bytes(b"not a pdf at all")
        session = ReviewSession(bogus, BUILTIN_POLICIES["share-with-ai"], lazy=True)
        with pytest.raises(Exception):  # noqa: B017 - any parse failure counts
            session.run()
        assert session.status == "error"
        assert session.error

    def test_resume_restores_decisions_and_manual_marks(self, pii_pdf: Path) -> None:
        first = ReviewSession(pii_pdf, BUILTIN_POLICIES["share-with-ai"])
        entry_id = first.plan.entries[0].detection_id
        assert first.set_decision(entry_id, "keep")
        marked = first.mark_text("Ramesh Kumar", "NAME", case_sensitive=True).added
        assert marked
        first.save_plan()

        second = ReviewSession(pii_pdf, BUILTIN_POLICIES["share-with-ai"])
        assert second.restored_decisions == 1
        assert second.restored_manual == len(marked)
        restored = second.plan.entry_by_id(entry_id)
        assert restored is not None and restored.decision is not None
        assert restored.decision.value == "keep"
        assert second.plan.entry_by_id(marked[0].detection_id) is not None
        assert second.summary()["restored"] == {
            "decisions": 1,
            "manual": len(marked),
        }

    def test_resume_ignores_stale_plan_file(self, pii_pdf: Path) -> None:
        first = ReviewSession(pii_pdf, BUILTIN_POLICIES["share-with-ai"])
        first.set_decision(first.plan.entries[0].detection_id, "keep")
        first.save_plan()
        # Change the document — the recorded hash no longer matches.
        with fitz.open(pii_pdf) as doc:
            doc[0].insert_text((50, 300), "extra line", fontsize=12)
            doc.saveIncr()
        second = ReviewSession(pii_pdf, BUILTIN_POLICIES["share-with-ai"])
        assert second.restored_decisions == 0
        assert second.restored_manual == 0

    def test_resume_survives_corrupt_plan_file(self, pii_pdf: Path) -> None:
        pii_pdf.with_suffix(".review.json").write_text("{ nope", encoding="utf-8")
        session = ReviewSession(pii_pdf, BUILTIN_POLICIES["share-with-ai"])
        assert session.is_ready
        assert session.restored_decisions == 0

    def test_rerun_discards_decisions(self, session: ReviewSession) -> None:
        entry_id = session.plan.entries[0].detection_id
        session.set_decision(entry_id, "keep")
        session.rerun(force_ocr=False)
        assert session.is_ready
        entry = session.plan.entry_by_id(entry_id)
        assert entry is not None
        assert entry.decision is None

    def test_preview_page_png(self, session: ReviewSession) -> None:
        png = session.preview_page_png(1)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        with pytest.raises(ValueError, match="out of range"):
            session.preview_page_png(99)

    def test_preview_reflects_current_decisions(self, session: ReviewSession) -> None:
        before = session.preview_page_png(1)
        for entry in session.plan.entries:
            session.set_decision(entry.detection_id, "keep")
        after = session.preview_page_png(1)
        assert before != after  # keeping everything removes the redactions

    def test_page_words_have_text_and_geometry(self, session: ReviewSession) -> None:
        words = session.page_words(1)
        assert any(w["text"] == "Ramesh" for w in words)
        for w in words:
            assert w["x1"] > w["x0"]
            assert w["y1"] > w["y0"]

    def test_page_words_unknown_page_raises(self, session: ReviewSession) -> None:
        with pytest.raises(ValueError, match="page 99"):
            session.page_words(99)

    def test_mark_text_marks_all_instances(self, session: ReviewSession) -> None:
        entries = session.mark_text("Ramesh Kumar", "name").added
        assert len(entries) == 2  # "Ramesh Kumar" + "RAMESH KUMAR" (case-insensitive)
        for entry in entries:
            assert entry.detection.detector_name == "manual"
            assert entry.detection.detection_type == "NAME"
            assert entry.detection.confidence == 1.0
            assert entry.decision is not None
            assert entry.effective_action.value == "redact"
        assert all(e["type"] != "" for e in session.summary()["entries"])

    def test_mark_text_same_offset_in_two_blocks(self, tmp_path: Path) -> None:
        # Identical text at the same block-relative offset in two separate
        # blocks must produce two entries (distinct detection ids).
        path = tmp_path / "twice.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 100), "Ramesh Kumar", fontsize=12)
        page.insert_text((50, 500), "Ramesh Kumar", fontsize=12)
        doc.save(str(path))
        doc.close()
        session = ReviewSession(path, BUILTIN_POLICIES["share-with-ai"])
        entries = session.mark_text("Ramesh Kumar", "NAME").added
        assert len(entries) == 2
        assert entries[0].detection_id != entries[1].detection_id
        boxes = {(round(e.detection.bbox.y0), round(e.detection.bbox.y1)) for e in entries}
        assert len(boxes) == 2

    def test_mark_substring_bbox_is_glyph_exact_on_proportional_font(self, tmp_path: Path) -> None:
        # helv is proportional: uniform interpolation would misplace the
        # box; real glyph boundaries from rawdict must match search_for.
        path = tmp_path / "prop.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 100), "File WilliamMcIlvanney_GenAI_v2b.pdf end", fontsize=12)
        expected = page.search_for("GenAI")[0]
        doc.save(str(path))
        doc.close()

        session = ReviewSession(path, BUILTIN_POLICIES["share-with-ai"])
        [entry] = session.mark_text("GenAI", "KEYWORD").added
        bbox = entry.detection.bbox
        assert abs(bbox.x0 - expected.x0) < 0.5
        assert abs(bbox.x1 - expected.x1) < 0.5

    def test_page_words_carry_char_boundaries(self, session: ReviewSession) -> None:
        words = session.page_words(1)
        with_cx = [w for w in words if "cx" in w]
        assert with_cx, "native document words should expose char boundaries"
        for w in with_cx:
            assert len(w["cx"]) == len(w["text"]) + 1
            assert w["cx"] == sorted(w["cx"])
            assert abs(w["cx"][0] - w["x0"]) < 1.0
            assert abs(w["cx"][-1] - w["x1"]) < 1.0

    def test_mark_text_case_sensitive(self, session: ReviewSession) -> None:
        entries = session.mark_text("Ramesh Kumar", "NAME", case_sensitive=True).added
        assert len(entries) == 1
        assert entries[0].detection.text == "Ramesh Kumar"

    def test_page_words_dedupe_native_ocr_twins(self) -> None:
        # Hybrid documents carry the same word twice at nearly identical
        # coordinates (native + OCR reading); the text layer must not.
        from privacy_firewall.ui.session import _dedupe_twin_words

        words = [
            {"text": "PAN", "x0": 41.3, "y0": 111.0, "x1": 54.8, "y1": 119.3},
            {"text": "PAN", "x0": 40.0, "y0": 110.5, "x1": 56.5, "y1": 119.5},  # OCR twin
            {"text": "PAN", "x0": 300.0, "y0": 500.0, "x1": 313.5, "y1": 508.3},  # elsewhere
            {"text": "Name", "x0": 41.3, "y0": 111.0, "x1": 60.0, "y1": 119.3},  # diff text
        ]
        kept = _dedupe_twin_words(words)
        assert len(kept) == 3
        assert kept[0] == words[0]  # native (first) wins
        assert words[1] not in kept

    def test_mark_text_skips_native_ocr_twin_blocks(self, tmp_path: Path) -> None:
        # Two blocks containing the same word at (nearly) the same spot —
        # the hybrid-merge shape — must yield one entry, not two.
        from privacy_firewall.engine.decision import ReviewPlan
        from privacy_firewall.models.blocks import TextBlock
        from privacy_firewall.models.document import Document, Page
        from privacy_firewall.models.geometry import BoundingBox

        path = tmp_path / "twin.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(str(path))
        doc.close()

        session = ReviewSession(path, BUILTIN_POLICIES["share-with-ai"], lazy=True)
        blocks = [
            TextBlock(
                block_id=f"b{i}",
                bbox=BoundingBox(x0=x0, y0=y0, x1=x0 + 40.0, y1=y0 + 10.0),
                page_number=1,
                confidence=1.0,
                text="PAN ABCDE1234F",
                spans=[],
            )
            for i, (x0, y0) in enumerate([(41.3, 111.0), (40.0, 110.5)])
        ]
        session._document = Document(
            pages=[Page(page_number=1, width=612.0, height=792.0, blocks=blocks)]
        )
        session._plan = ReviewPlan(
            source_path=str(path), source_sha256="test", policy_name="share-with-ai"
        )
        result = session.mark_text("ABCDE1234F", "PAN")
        assert len(result.added) == 1
        assert result.skipped == 1  # the OCR twin

    def test_mark_text_is_idempotent(self, session: ReviewSession) -> None:
        first = session.mark_text("Ramesh", "NAME")
        assert first.added
        assert first.skipped == 0
        again = session.mark_text("Ramesh", "NAME")
        assert again.added == []
        assert again.skipped == len(first.added)

    def test_mark_text_no_match(self, session: ReviewSession) -> None:
        result = session.mark_text("not in the document", "X")
        assert result.added == []
        assert result.skipped == 0

    def test_mark_text_blank_raises(self, session: ReviewSession) -> None:
        with pytest.raises(ValueError, match="blank"):
            session.mark_text("   ", "NAME")
        with pytest.raises(ValueError, match="blank"):
            session.mark_text("Ramesh", "   ")

    def test_mark_text_normalises_label(self, session: ReviewSession) -> None:
        entries = session.mark_text("Ramesh", "customer name").added
        assert entries[0].detection.detection_type == "CUSTOMER_NAME"

    def test_remove_manual_entry(self, session: ReviewSession) -> None:
        entry = session.mark_text("Ramesh Kumar", "NAME", case_sensitive=True).added[0]
        assert session.remove_manual_entry(entry.detection_id)
        assert session.plan.entry_by_id(entry.detection_id) is None
        # detector-produced entries cannot be removed
        auto = next(e for e in session.plan.entries if e.detection.detector_name != "manual")
        assert not session.remove_manual_entry(auto.detection_id)
        assert not session.remove_manual_entry("bogus-id")

    def test_apply_redacts_manual_marks(self, session: ReviewSession) -> None:
        assert session.mark_text("Ramesh Kumar", "NAME").added
        out_path, _count = session.apply()
        with fitz.open(out_path) as doc:
            text = doc[0].get_text()
        assert "Ramesh" not in text
        assert "RAMESH" not in text

    def test_apply_respects_keep_decisions(self, pii_pdf: Path) -> None:
        session = ReviewSession(pii_pdf, BUILTIN_POLICIES["share-with-ai"])
        for entry in session.summary()["entries"]:
            session.set_decision(entry["detection_id"], "keep")
        out_path, count = session.apply()
        assert count == 0
        with fitz.open(out_path) as doc:
            assert "AAAAA1111A" in doc[0].get_text()
