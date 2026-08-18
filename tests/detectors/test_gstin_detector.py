from privacy_firewall.detectors.gstin_detector import GSTINDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.document import Document, Page
from privacy_firewall.models.geometry import BoundingBox

# Published, checksum-valid sample GSTINs (fabricated entities).
VALID_GSTIN = "27AAPFU0939F1ZV"
VALID_GSTIN_2 = "24AAACC1206D1ZM"


def _page(text: str) -> Page:
    bbox = BoundingBox(x0=0.0, y0=0.0, x1=300.0, y1=50.0)
    block = TextBlock(block_id="b1", bbox=bbox, page_number=1, confidence=1.0, text=text)
    return Page(page_number=1, width=612.0, height=792.0, blocks=[block])


class TestGSTINDetector:
    def setup_method(self) -> None:
        self.detector = GSTINDetector()

    def test_name(self) -> None:
        assert self.detector.name == "gstin"

    def test_detects_valid_gstin(self) -> None:
        doc = Document(pages=[_page(f"GSTIN: {VALID_GSTIN}")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == VALID_GSTIN
        assert result[0].detection_type == "GSTIN"
        assert result[0].confidence == 0.95
        assert result[0].reasons

    def test_detects_second_valid_gstin(self) -> None:
        doc = Document(pages=[_page(f"Supplier {VALID_GSTIN_2} registered")])
        result = self.detector.scan(doc)
        assert [d.text for d in result] == [VALID_GSTIN_2]

    def test_rejects_bad_checksum(self) -> None:
        # Same as VALID_GSTIN but the final check character is wrong.
        bad = VALID_GSTIN[:-1] + ("W" if VALID_GSTIN[-1] != "W" else "X")
        doc = Document(pages=[_page(f"GSTIN: {bad}")])
        assert self.detector.scan(doc) == []

    def test_rejects_invalid_state_code(self) -> None:
        # State code 00 is not a valid GST state.
        doc = Document(pages=[_page("GSTIN: 00AAPFU0939F1ZV")])
        assert self.detector.scan(doc) == []

    def test_ignores_non_gstin_text(self) -> None:
        doc = Document(pages=[_page("Invoice INV-2026-0042 total 15000")])
        assert self.detector.scan(doc) == []

    def test_not_matched_inside_longer_token(self) -> None:
        # Embedded in a longer alphanumeric run — lookarounds must reject it.
        doc = Document(pages=[_page(f"X{VALID_GSTIN}9")])
        assert self.detector.scan(doc) == []

    def test_values_only_still_detects(self) -> None:
        doc = Document(pages=[_page(f"GSTIN {VALID_GSTIN} here")])
        value = self.detector.scan(doc, values_only=True)[0]
        assert value.text == VALID_GSTIN
        # The value bbox stays within the block bounds.
        assert value.bbox.x0 >= 0.0
        assert value.bbox.x1 <= 300.0
