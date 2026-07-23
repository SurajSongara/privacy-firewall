"""RapidOCR adapter — uses PaddleOCR models via ONNX runtime (no PaddlePaddle needed)."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from privacy_firewall.models.blocks import TextBlock, TextSpan
from privacy_firewall.models.document import Document, Page
from privacy_firewall.models.geometry import BoundingBox
from privacy_firewall.ocr.provider import OCRProvider
from privacy_firewall.parsers.pdfium_compat import PdfiumDocument, Rect, open_document


class RapidOCRAdapter(OCRProvider):
    """Adapter that runs RapidOCR (ONNX-based PaddleOCR) on each PDF page.

    Uses the ``rapidocr-onnxruntime`` package which runs PaddleOCR models
    via ONNX Runtime — no PaddlePaddle dependency required.
    """

    name = "rapidocr"

    @classmethod
    def is_available(cls) -> bool:
        """Whether the ``rapidocr-onnxruntime`` backend is importable."""
        from importlib.util import find_spec

        return find_spec("rapidocr_onnxruntime") is not None

    def __init__(self, dpi: int = 200, lang: str = "en") -> None:
        """Initialise the adapter.

        Args:
            dpi: Resolution for rendering PDF pages to images.
            lang: Language code (used for model selection).
        """
        self._dpi = dpi
        self._lang = lang
        self._engine: Any = None

    def _get_engine(self) -> Any:
        """Lazy-initialise and return the RapidOCR engine."""
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            msg = (
                "rapidocr-onnxruntime is not installed. Install it with:\n"
                "  pip install rapidocr-onnxruntime\n"
            )
            raise ImportError(msg) from exc
        self._engine = RapidOCR()
        return self._engine

    def process(self, path: str | Path) -> Document:
        """Run OCR on a PDF file on disk."""
        doc = open_document(path)
        try:
            return self._process_doc(doc)
        finally:
            doc.close()

    def process_bytes(self, data: bytes) -> Document:
        """Run OCR on PDF content from raw bytes."""
        doc = open_document(stream=data)
        try:
            return self._process_doc(doc)
        finally:
            doc.close()

    def _process_doc(self, doc: PdfiumDocument) -> Document:
        """Core logic: render each page, run OCR, build Document."""
        engine = self._get_engine()
        pages: list[Page] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            rect = page.rect

            pix = page.get_pixmap(dpi=self._dpi)
            scale = self._dpi / 72.0

            img_bytes = pix.tobytes("png")

            result, _ = engine(img_bytes)
            blocks = self._ocr_result_to_blocks(result, page_num + 1, scale, rect)

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
        """Convert RapidOCR result into TextBlock items."""
        blocks: list[TextBlock] = []
        if not ocr_result:
            return blocks

        for entry in ocr_result:
            bbox_points, text, confidence = entry

            # RapidOCR returns [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            xs = [p[0] for p in bbox_points]
            ys = [p[1] for p in bbox_points]
            x0 = min(xs) / scale
            y0 = min(ys) / scale
            x1 = max(xs) / scale
            y1 = max(ys) / scale

            # Clamp to page boundaries
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
                    confidence=float(confidence),
                    text=text,
                    spans=[span],
                ),
            )

        return blocks
