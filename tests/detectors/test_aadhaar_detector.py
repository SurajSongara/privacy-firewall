from privacy_firewall.detectors.aadhaar_detector import AadhaarDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.document import Document, Page
from privacy_firewall.models.geometry import BoundingBox


def _page(text: str) -> Page:
    bbox = BoundingBox(x0=0.0, y0=0.0, x1=300.0, y1=50.0)
    block = TextBlock(
        block_id="b1", bbox=bbox, page_number=1, confidence=1.0, text=text
    )
    return Page(
        page_number=1, width=612.0, height=792.0, blocks=[block]
    )


class TestAadhaarDetector:
    def setup_method(self) -> None:
        self.detector = AadhaarDetector()

    def test_name(self) -> None:
        assert self.detector.name == "aadhaar"

    def test_detect_continuous(self) -> None:
        # 226251716424 is a valid Aadhaar (Verhoeff checksum, starts 2-9)
        doc = Document(pages=[_page("Aadhaar: 226251716424")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "226251716424"
        assert result[0].detection_type == "AADHAAR"
        assert result[0].confidence == 0.95

    def test_detect_formatted_spaces(self) -> None:
        doc = Document(pages=[_page("Aadhaar: 2262 5171 6424")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "226251716424"

    def test_detect_formatted_hyphens(self) -> None:
        doc = Document(pages=[_page("Aadhaar: 2262-5171-6424")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "226251716424"

    def test_multiple_aadhaars(self) -> None:
        # Both are valid Aadhaar numbers (Verhoeff checksum)
        doc = Document(pages=[_page("First: 555566667771, Second: 444455556666")])
        result = self.detector.scan(doc)
        assert len(result) == 2

    def test_no_false_positive_short_number(self) -> None:
        doc = Document(pages=[_page("Phone: 1234567890")])
        result = self.detector.scan(doc)
        assert len(result) == 0

    def test_no_false_positive_long_number(self) -> None:
        doc = Document(pages=[_page("Number: 1234567890123")])
        result = self.detector.scan(doc)
        assert len(result) == 0

    def test_no_false_positive_mixed_chars(self) -> None:
        doc = Document(pages=[_page("ABCD1234EFGH5678")])
        result = self.detector.scan(doc)
        assert len(result) == 0

    def test_no_match_when_no_aadhaar(self) -> None:
        doc = Document(pages=[_page("This text has no Aadhaar number.")])
        result = self.detector.scan(doc)
        assert result == []

    def test_aadhaar_at_start(self) -> None:
        doc = Document(pages=[_page("226251716424 is my Aadhaar")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_aadhaar_at_end(self) -> None:
        doc = Document(pages=[_page("My Aadhaar is 226251716424")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_formatted_in_sentence(self) -> None:
        doc = Document(pages=[_page("My Aadhaar is 2262 5171 6424, please note.")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "226251716424"

    def test_same_occurrence_not_double_counted(self) -> None:
        # A single continuous occurrence is matched by both the formatted and
        # continuous patterns; it must be emitted once, not twice.
        doc = Document(pages=[_page("Aadhaar: 226251716424")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_keeps_both_occurrences_of_same_value(self) -> None:
        # The same Aadhaar written plainly and in canonical spaced form are two
        # distinct occurrences on the page — both must be detected so both get
        # redacted. Collapsing them to one leaves the second on the page.
        doc = Document(pages=[_page("Number: 226251716424 and 2262 5171 6424 are same")])
        result = self.detector.scan(doc)
        assert len(result) == 2
        assert all(r.text == "226251716424" for r in result)

    def test_bbox_populated(self) -> None:
        bbox = BoundingBox(x0=10.0, y0=20.0, x1=300.0, y1=50.0)
        block = TextBlock(
            block_id="b1", bbox=bbox, page_number=1, confidence=1.0, text="226251716424"
        )
        page = Page(page_number=1, width=612.0, height=792.0, blocks=[block])
        doc = Document(pages=[page])
        result = self.detector.scan(doc)
        assert result[0].bbox == bbox

    def test_leading_zero_rejected(self) -> None:
        # 000000000003 passes Verhoeff but UIDAI never issues numbers
        # starting with 0 or 1 — the structural rule rejects it.
        doc = Document(pages=[_page("000000000003")])
        result = self.detector.scan(doc)
        assert result == []

    def test_leading_one_rejected(self) -> None:
        # 123456789010 passes Verhoeff but starts with 1.
        doc = Document(pages=[_page("Aadhaar: 123456789010")])
        result = self.detector.scan(doc)
        assert result == []

    def test_reject_txn_ref_between_slashes(self) -> None:
        # 12-digit UPI transaction reference embedded in a slash-delimited
        # descriptor (e.g. "UPI/DR/226251716424/Miss") — checksum passes but
        # the structural context marks it as a transaction ref, not Aadhaar.
        doc = Document(pages=[_page("UPI/DR/226251716424/Miss")])
        result = self.detector.scan(doc)
        assert result == []

    def test_reject_txn_ref_trailing_slash(self) -> None:
        # "<12digits>/SBIN" — number followed by a slash is a transaction ref.
        doc = Document(pages=[_page("100224490779/SBIN")])
        result = self.detector.scan(doc)
        assert result == []

    def test_accept_when_surrounded_by_whitespace(self) -> None:
        # Same 12-digit number in a normal Aadhaar context is still detected.
        doc = Document(pages=[_page("Aadhaar Number: 226251716424")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "226251716424"
