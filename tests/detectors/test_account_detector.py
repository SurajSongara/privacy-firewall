from privacy_firewall.detectors.account_detector import AccountDetector
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.document import Document, Page
from privacy_firewall.models.geometry import BoundingBox


def _page(*texts: str) -> Page:
    blocks = [
        TextBlock(
            block_id=f"b{i}",
            bbox=BoundingBox(x0=0.0, y0=float(i * 20), x1=400.0, y1=float(i * 20 + 15)),
            page_number=1,
            confidence=1.0,
            text=text,
        )
        for i, text in enumerate(texts)
    ]
    return Page(page_number=1, width=612.0, height=792.0, blocks=blocks)


class TestAccountDetector:
    def setup_method(self) -> None:
        self.detector = AccountDetector()

    def test_name(self) -> None:
        assert self.detector.name == "account"

    def test_detect_with_inline_keyword(self) -> None:
        doc = Document(pages=[_page("Account Number: 40798662399")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "40798662399"
        assert result[0].confidence == 0.85

    def test_detect_standalone(self) -> None:
        doc = Document(pages=[_page("Some header", "40798662399 credited")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "40798662399"
        assert result[0].confidence == 0.70

    def test_cross_block_label_pairs_upgrade_confidence(self) -> None:
        # OCR layout: label on one block, ": <number>" on the next block —
        # the standalone hit should be upgraded to keyword-anchored confidence.
        doc = Document(pages=[_page("Account Number", ": 40798662399")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "40798662399"
        assert result[0].confidence == 0.85

    def test_cross_block_cif_label(self) -> None:
        doc = Document(pages=[_page("CIF Number", ": 90915382785")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "90915382785"
        assert result[0].confidence == 0.85

    def test_cross_block_ckycr_label(self) -> None:
        doc = Document(pages=[_page("CKYCR Number", ": 50073645071003")])
        result = self.detector.scan(doc)
        assert len(result) == 1
        assert result[0].text == "50073645071003"
        assert result[0].confidence == 0.85

    def test_reject_sbi_ledger_line_marker_with_space(self) -> None:
        # "0097737162096 AT 30524" — SBI statement row marker, not an account.
        doc = Document(pages=[_page("0097737162096 AT 30524")])
        result = self.detector.scan(doc)
        assert result == []

    def test_reject_sbi_ledger_line_marker_no_space(self) -> None:
        # "0099509044300AT30524" — same marker without whitespace.
        doc = Document(pages=[_page("0099509044300AT30524")])
        result = self.detector.scan(doc)
        assert result == []

    def test_reject_number_between_slashes(self) -> None:
        # 11-digit number inside a slash-delimited transaction token.
        doc = Document(pages=[_page("UPI/DR/40798662399/PAYEE")])
        result = self.detector.scan(doc)
        assert result == []

    def test_reject_after_ifsc_prefix(self) -> None:
        doc = Document(pages=[_page("HDFC05717000027455")])
        result = self.detector.scan(doc)
        assert result == []

    def test_reject_all_same_digit(self) -> None:
        doc = Document(pages=[_page("Account: 00000000000")])
        result = self.detector.scan(doc)
        assert result == []

    def test_keeps_both_occurrences_of_same_account(self) -> None:
        # Two occurrences of the same account on the page are two things to
        # redact; collapsing them leaves the second in the output.
        doc = Document(pages=[_page("Account: 40798662399 and again 40798662399")])
        result = self.detector.scan(doc)
        assert len(result) == 2
        assert all(r.text == "40798662399" for r in result)
