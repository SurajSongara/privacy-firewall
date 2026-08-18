"""Tesseract OCR adapter — wraps tesserocr into the OCRProvider interface."""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image as PILImage

from privacy_firewall.models.blocks import TextBlock, TextSpan
from privacy_firewall.models.document import Document, Page
from privacy_firewall.models.geometry import BoundingBox
from privacy_firewall.ocr.provider import OCRProvider
from privacy_firewall.parsers.pdfium_compat import PdfiumDocument, open_document

if TYPE_CHECKING:
    import tesserocr


class TesseractOCRAdapter(OCRProvider):
    """Adapter that runs Tesseract OCR on each PDF page and returns a Document.

    Each page is rendered to an image via PDFium before being fed to
    Tesseract.  The OCR results (text + bounding boxes) are converted
    to ``TextBlock`` and ``TextSpan`` items with confidence scores.

    Requires the ``tesserocr`` package and a tessdata directory with
    the appropriate language data files.
    """

    name = "tesseract"

    @classmethod
    def is_available(cls) -> bool:
        """Whether the ``tesserocr`` backend is importable."""
        from importlib.util import find_spec

        return find_spec("tesserocr") is not None

    def __init__(
        self,
        dpi: int = 200,
        lang: str = "eng",
        tessdata_path: str | None = None,
    ) -> None:
        """Initialise the adapter with Tesseract configuration.

        Args:
            dpi: Resolution used when rendering PDF pages to images.
            lang: Tesseract language code (e.g. ``"eng"``, ``"eng+hin"``).
            tessdata_path: Path to the tessdata directory.  If ``None``,
                the ``TESSDATA_PREFIX`` environment variable is used.
        """
        self._dpi = dpi
        self._lang = lang
        self._tessdata_path = tessdata_path
        self._api: tesserocr.PyTessBaseAPI | None = None

    def _get_engine(self) -> tesserocr.PyTessBaseAPI:
        """Lazy-initialise and return the Tesseract API instance.

        Returns:
            A ``tesserocr.PyTessBaseAPI`` instance.

        Raises:
            ImportError: If the ``tesserocr`` package is not installed.
            RuntimeError: If Tesseract initialisation fails.
        """
        if self._api is not None:
            return self._api
        try:
            import tesserocr
        except ImportError as exc:
            msg = (
                "tesserocr is not installed. Install it with:\n"
                "  pip install tesserocr\n"
            )
            raise ImportError(msg) from exc

        kwargs: dict[str, object] = {"lang": self._lang}
        if self._tessdata_path is not None:
            kwargs["path"] = self._tessdata_path

        api = tesserocr.PyTessBaseAPI(**kwargs)
        self._api = api
        return self._api

    def process(self, path: str | Path) -> Document:
        """Run Tesseract OCR on a PDF file on disk.

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
        """Run Tesseract OCR on PDF content from raw bytes.

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
        import tesserocr as _tesserocr

        engine = self._get_engine()
        pages: list[Page] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            rect = page.rect

            pix = page.get_pixmap(dpi=self._dpi)
            scale = self._dpi / 72.0

            img = PILImage.open(io.BytesIO(pix.tobytes("png")))

            engine.SetImage(img)
            engine.Recognize()

            ri = engine.GetIterator()
            if not ri:
                pages.append(
                    Page(
                        page_number=page_num + 1,
                        width=rect.width,
                        height=rect.height,
                        blocks=[],
                    ),
                )
                continue

            ri.Begin()
            blocks: list[TextBlock] = []

            while True:
                text = ri.GetUTF8Text(_tesserocr.RIL.TEXTLINE)
                confidence = ri.Confidence(_tesserocr.RIL.TEXTLINE)
                bbox_pixels = ri.BoundingBox(_tesserocr.RIL.TEXTLINE)

                # Skip empty or whitespace-only lines
                if text and text.strip():
                    # Convert from image pixel coords to PDF page coords
                    # tesserocr BoundingBox returns (x1, y1, x2, y2) tuple
                    x0 = bbox_pixels[0] / scale
                    y0 = bbox_pixels[1] / scale
                    x1 = bbox_pixels[2] / scale
                    y1 = bbox_pixels[3] / scale

                    # Clamp to page boundaries
                    x0 = max(x0, rect.x0)
                    y0 = max(y0, rect.y0)
                    x1 = min(x1, rect.x1)
                    y1 = min(y1, rect.y1)

                    # Normalize confidence from 0-100 to 0-1
                    conf_normalized = max(0.0, min(1.0, confidence / 100.0))

                    bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
                    cleaned = text.strip()
                    span = TextSpan(text=cleaned, bbox=bbox)

                    blocks.append(
                        TextBlock(
                            block_id=str(uuid.uuid4()),
                            bbox=bbox,
                            page_number=page_num + 1,
                            confidence=conf_normalized,
                            text=cleaned,
                            spans=[span],
                        ),
                    )

                if not ri.Next(_tesserocr.RIL.TEXTLINE):
                    break

            pages.append(
                Page(
                    page_number=page_num + 1,
                    width=rect.width,
                    height=rect.height,
                    blocks=blocks,
                ),
            )

        return Document(pages=pages)
