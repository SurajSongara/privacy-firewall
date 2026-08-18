from privacy_firewall.detectors.upi_detector import UpiDetector
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


class TestUpiDetector:
    def setup_method(self) -> None:
        self.detector = UpiDetector()

    def test_name(self) -> None:
        assert self.detector.name == "upi"

    def test_detect_upi_ybl(self) -> None:
        doc = Document(pages=[_page("UPI: user@ybl")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "user@ybl"
        assert result[0].detection_type == "UPI"
        assert result[0].confidence == 0.95

    def test_detect_upi_paytm(self) -> None:
        doc = Document(pages=[_page("UPI: user@paytm")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].confidence == 0.95

    def test_detect_upi_phonepe(self) -> None:
        doc = Document(pages=[_page("UPI: user@phonepe")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].confidence == 0.95

    def test_detect_upi_with_dots(self) -> None:
        doc = Document(pages=[_page("UPI: user.name@ybl")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "user.name@ybl"

    def test_detect_upi_with_underscores(self) -> None:
        doc = Document(pages=[_page("UPI: user_name@ybl")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_detect_upi_with_hyphens(self) -> None:
        doc = Document(pages=[_page("UPI: user-name@ybl")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_unknown_handle_lower_confidence(self) -> None:
        doc = Document(pages=[_page("UPI: user@unknownhandle")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].confidence == 0.7

    def test_multiple_upi_ids(self) -> None:
        doc = Document(pages=[_page("Send to user1@ybl or user2@paytm")])
        result = self.detector.scan(doc)
        assert len(result) == 2

    def test_no_false_positive_bare_email(self) -> None:
        doc = Document(pages=[_page("Email: user@example.com")])
        result = self.detector.scan(doc)
        assert len(result) == 0

    def test_no_false_positive_without_at(self) -> None:
        doc = Document(pages=[_page("Just text without an ID.")])
        result = self.detector.scan(doc)
        assert result == []

    def test_keeps_both_occurrences_of_same_upi_id(self) -> None:
        # Both occurrences are on the page and must each be redacted.
        doc = Document(pages=[_page("Send to user@ybl or user@ybl")])
        result = self.detector.scan(doc)
        assert len(result) == 2
        assert all(r.text == "user@ybl" for r in result)

    def test_rejects_double_at(self) -> None:
        doc = Document(pages=[_page("UPI: user@@ybl")])
        result = self.detector.scan(doc)
        assert len(result) == 0

    def test_rejects_double_dot_in_handle(self) -> None:
        doc = Document(pages=[_page("UPI: user@ybl..com")])
        result = self.detector.scan(doc)
        assert len(result) == 0

    def test_upi_at_start(self) -> None:
        doc = Document(pages=[_page("user@ybl is my UPI")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_upi_at_end(self) -> None:
        doc = Document(pages=[_page("My UPI is user@ybl")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_handle_with_numbers(self) -> None:
        doc = Document(pages=[_page("UPI: user@ybl2")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_bbox_populated(self) -> None:
        bbox = BoundingBox(x0=10.0, y0=20.0, x1=300.0, y1=50.0)
        block = TextBlock(
            block_id="b1", bbox=bbox, page_number=1, confidence=1.0, text="user@ybl"
        )
        page = Page(page_number=1, width=612.0, height=792.0, blocks=[block])
        doc = Document(pages=[page])
        result = self.detector.scan(doc)
        assert result[0].bbox == bbox
