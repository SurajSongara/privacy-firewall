"""PaddleOCR adapter — wraps the PaddleOCR engine into the OCRProvider interface."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from privacy_firewall.models.blocks import TextBlock, TextSpan
from privacy_firewall.models.document import Document, Page
from privacy_firewall.models.geometry import BoundingBox
from privacy_firewall.ocr.provider import OCRProvider
from privacy_firewall.parsers.pdfium_compat import PdfiumDocument, Rect, open_document


class PaddleOCRAdapter(OCRProvider):
    """Adapter that runs PaddleOCR on each PDF page and returns a Document.

    Each page is rendered to an image via PDFium before being fed to
    PaddleOCR.  The OCR results (text + bounding quadrilaterals) are
    converted to ``TextBlock`` and ``TextSpan`` items with appropriate
    confidence scores.

    Requires the ``paddleocr`` package (and its ``paddlepaddle`` backend)
    to be installed separately.
    """

    name = "paddleocr"

    @classmethod
    def is_available(cls) -> bool:
        """Whether both ``paddleocr`` and its ``paddle`` backend are importable."""
        from importlib.util import find_spec

        return find_spec("paddleocr") is not None and find_spec("paddle") is not None

    def __init__(self, dpi: int = 200, lang: str = "en", use_angle_cls: bool = True) -> None:
        """Initialise the adapter with PaddleOCR configuration.

        Args:
            dpi: Resolution used when rendering PDF pages to images.
            lang: Language code passed to PaddleOCR (e.g. ``"en"``, ``"ch"``).
            use_angle_cls: Whether to enable the text-angle classification
                module in PaddleOCR.
        """
        self._dpi = dpi
        self._lang = lang
        self._use_angle_cls = use_angle_cls
        self._ocr: Any = None

    def _get_engine(self) -> Any:
        """Lazy-initialise and return the PaddleOCR engine instance.

        Returns:
            The PaddleOCR engine instance.

        Raises:
            ImportError: If the ``paddleocr`` package is not installed.
        """
        if self._ocr is not None:
            return self._ocr
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            msg = (
                "paddleocr is not installed. Install it with:\n"
                "  pip install paddleocr\n"
                "(Note: paddleocr requires paddlepaddle which may not be "
                "available on all Python versions.)"
            )
            raise ImportError(msg) from exc
        try:
            self._ocr = PaddleOCR(use_angle_cls=self._use_angle_cls, lang=self._lang)
        except Exception as exc:
            msg = (
                "paddleocr is not installed or its paddlepaddle backend is "
                "unavailable. Install with:\n"
                "  pip install paddleocr\n"
                f"Underlying error: {exc}"
            )
            raise ImportError(msg) from exc
        return self._ocr

    def process(self, path: str | Path) -> Document:
        """Run PaddleOCR on a PDF file on disk.

        Args:
            path: Path to the PDF file.

        Returns:
            A ``Document`` with OCR-extracted ``TextBlock`` items.
        """
        doc = open_document(path)
        try:
            return self._process_doc(doc)
        finally:
            doc.close()

    def process_bytes(self, data: bytes) -> Document:
        """Run PaddleOCR on PDF content from raw bytes.

        Args:
            data: Raw PDF bytes.

        Returns:
            A ``Document`` with OCR-extracted ``TextBlock`` items.
        """
        doc = open_document(stream=data)
        try:
            return self._process_doc(doc)
        finally:
            doc.close()

    def _process_doc(self, doc: PdfiumDocument) -> Document:
        """Core logic: render each page, run OCR, build Document.

        Args:
            doc: An open document.

        Returns:
            A ``Document`` with OCR'd text.
        """
        engine = self._get_engine()
        pages: list[Page] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            rect = page.rect

            pix = page.get_pixmap(dpi=self._dpi)
            scale = self._dpi / 72.0

            img_bytes = pix.tobytes("png")

            raw = engine.ocr(img_bytes)
            page_results = raw[0] if raw else []

            blocks = self._ocr_result_to_blocks(page_results, page_num + 1, scale, rect)

            pages.append(
                Page(
                    page_number=page_num + 1,
                    width=rect.width,
                    height=rect.height,
                    blocks=blocks,
                ),
            )

        return Document(pages=pages)

    @staticmethod
    def _ocr_result_to_blocks(
        ocr_result: Any,
        page_number: int,
        scale: float,
        rect: Rect,
    ) -> list[TextBlock]:
        """Convert a PaddleOCR page result into ``TextBlock`` items.

        Each detected text line becomes a ``TextBlock`` containing a
        single ``TextSpan``.

        Args:
            ocr_result: The raw result from ``PaddleOCR.ocr()`` for one
                page (a list of ``[bbox_quad, (text, confidence)]`` entries,
                or ``None``).
            page_number: 1-based page number.
            scale: The DPI scale factor (dpi / 72).
            rect: The page's rectangle for coordinate normalisation.

        Returns:
            A list of ``TextBlock`` objects.
        """
        blocks: list[TextBlock] = []
        if not ocr_result:
            return blocks

        for entry in ocr_result:
            bbox_quad, (text, confidence) = entry

            xs = [p[0] for p in bbox_quad]
            ys = [p[1] for p in bbox_quad]
            x0 = min(xs) / scale
            y0 = min(ys) / scale
            x1 = max(xs) / scale
            y1 = max(ys) / scale

            x0 = max(x0, rect.x0)
            y0 = max(y0, rect.y0)
            x1 = min(x1, rect.x1)
            y1 = min(y1, rect.y1)

            bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
            span = TextSpan(text=text, bbox=bbox)

            blocks.append(
                TextBlock(
                    block_id=str(uuid.uuid4()),
                    bbox=bbox,
                    page_number=page_number,
                    confidence=confidence,
                    text=text,
                    spans=[span],
                ),
            )

        return blocks
