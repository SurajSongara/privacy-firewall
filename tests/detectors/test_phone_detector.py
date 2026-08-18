from privacy_firewall.detectors.phone_detector import PhoneDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.document import Document, Page
from privacy_firewall.models.geometry import BoundingBox


def _page(text: str) -> Page:
    bbox = BoundingBox(x0=0.0, y0=0.0, x1=400.0, y1=50.0)
    block = TextBlock(
        block_id="b1", bbox=bbox, page_number=1, confidence=1.0, text=text
    )
    return Page(
        page_number=1, width=612.0, height=792.0, blocks=[block]
    )


class TestPhoneDetector:
    def setup_method(self) -> None:
        self.detector = PhoneDetector()

    def test_name(self) -> None:
        assert self.detector.name == "phone"

    def test_detect_plain_10_digit(self) -> None:
        doc = Document(pages=[_page("Phone: 9876543210")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "9876543210"
        assert result[0].detection_type == "PHONE"
        assert result[0].confidence == 0.85

    def test_detect_with_country_code_plus(self) -> None:
        doc = Document(pages=[_page("Phone: +919876543210")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_detect_with_country_code_plus_dash(self) -> None:
        doc = Document(pages=[_page("Phone: +91-9876543210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_detect_with_country_code_plus_space(self) -> None:
        doc = Document(pages=[_page("Phone: +91 9876543210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_detect_with_leading_zero(self) -> None:
        doc = Document(pages=[_page("Phone: 09876543210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_detect_5_5_format(self) -> None:
        doc = Document(pages=[_page("Phone: 98765 43210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_detect_5_5_format_hyphen(self) -> None:
        doc = Document(pages=[_page("Phone: 98765-43210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_detect_3_3_4_format_space(self) -> None:
        doc = Document(pages=[_page("Phone: 987 654 3210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_detect_3_3_4_format_hyphen(self) -> None:
        doc = Document(pages=[_page("Phone: 987-654-3210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_detect_4_3_3_format_space(self) -> None:
        doc = Document(pages=[_page("Phone: 9876 543 210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_detect_4_3_3_format_hyphen(self) -> None:
        doc = Document(pages=[_page("Phone: 9876-543-210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_multiple_phones(self) -> None:
        doc = Document(pages=[_page("Phone1: 9876543210, Phone2: 8765432109")])
        result = self.detector.scan(doc)
        assert len(result) == 2

    def test_no_false_positive_short_digits(self) -> None:
        doc = Document(pages=[_page("Code: 123456")])
        result = self.detector.scan(doc)
        assert len(result) == 0

    def test_no_false_positive_starts_with_5(self) -> None:
        doc = Document(pages=[_page("Number: 5123456789")])
        result = self.detector.scan(doc)
        assert len(result) == 0

    def test_no_match_when_no_phone(self) -> None:
        doc = Document(pages=[_page("This text has no phone number.")])
        result = self.detector.scan(doc)
        assert result == []

    def test_same_occurrence_matched_by_two_formats_counted_once(self) -> None:
        # One "+91-9876543210" is matched by both the +prefixed and the bare
        # 10-digit pattern; the overlapping re-match must not double-count it.
        doc = Document(pages=[_page("Call +91-9876543210 today")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_keeps_both_occurrences_of_same_number(self) -> None:
        # The same number in two places (differently formatted) is two things
        # to redact; collapsing them leaves the second in the output.
        doc = Document(pages=[_page("Number: 9876543210 and 98765 43210 refer to same")])
        result = self.detector.scan(doc)
        assert len(result) == 2

    def test_phone_at_start(self) -> None:
        doc = Document(pages=[_page("9876543210 is my number")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_phone_at_end(self) -> None:
        doc = Document(pages=[_page("My number is 9876543210")])
        result = self.detector.scan(doc)
        assert len(result) == 1

    def test_bbox_populated(self) -> None:
        bbox = BoundingBox(x0=10.0, y0=20.0, x1=400.0, y1=50.0)
        block = TextBlock(
            block_id="b1", bbox=bbox, page_number=1, confidence=1.0, text="9876543210"
        )
        page = Page(page_number=1, width=612.0, height=792.0, blocks=[block])
        doc = Document(pages=[page])
        result = self.detector.scan(doc)
        assert result[0].bbox == bbox

    def test_reject_bank_ref_between_slashes(self) -> None:
        # 10-digit merchant/payee id inside "/BANK/NNNNNNNNNN/" is a
        # transaction reference token, not a phone number.
        doc = Document(pages=[_page("/CNRB/9179083184/Paym")])
        result = self.detector.scan(doc)
        assert result == []

    def test_accept_phone_with_colon_prefix(self) -> None:
        # OCR block ": 8989796847" (Branch Phone label sits in previous block)
        # still detects because there is no slash next to the digits.
        doc = Document(pages=[_page(": 8989796847")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "8989796847"
