"""Render PDF pages to PNG images with a bbox coordinate transform.

Engine utility for the review UI: pages are rasterised at a given DPI
and detection bounding boxes (in PDF points, 72/inch) are mapped to
pixel coordinates via the returned ``scale`` factor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from privacy_firewall.models.geometry import BoundingBox
from privacy_firewall.parsers.pdf_open import open_pdf
from privacy_firewall.parsers.pdfium_compat import PDFIUM_LOCK, open_document

DEFAULT_DPI = 144


@dataclass(frozen=True)
class PageImage:
    """A rasterised PDF page.

    Attributes:
        page_number: 1-based page number.
        width: Image width in pixels.
        height: Image height in pixels.
        scale: Multiplier from PDF points to pixels (``dpi / 72``).
        png_bytes: The PNG-encoded image.
    """

    page_number: int
    width: int
    height: int
    scale: float
    png_bytes: bytes


def page_count(pdf_path: Path, password: str | None = None) -> int:
    """Return the number of pages in the PDF."""
    doc = open_pdf(pdf_path, password=password)
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def render_page_image(
    pdf_path: Path, page_number: int, dpi: int = DEFAULT_DPI, password: str | None = None
) -> PageImage:
    """Rasterise one page of a PDF to a PNG.

    Args:
        pdf_path: Path to the PDF.
        page_number: 1-based page number.
        dpi: Render resolution (PDF native resolution is 72 dpi).
        password: Password for an encrypted PDF, if required.

    Returns:
        The rendered PageImage.

    Raises:
        ValueError: If *page_number* is out of range.
        EncryptedPDFError: If the PDF is password-protected and no correct
            password was supplied.
    """
    scale = dpi / 72.0
    # PDFium is not thread-safe; the Studio server renders pages from a
    # threadpool. Serialise the whole open/load/render/close sequence.
    with PDFIUM_LOCK:
        doc = open_pdf(pdf_path, password=password)
        try:
            if not 1 <= page_number <= doc.page_count:
                msg = f"page {page_number} out of range (1..{doc.page_count})"
                raise ValueError(msg)
            page = doc[page_number - 1]
            pixmap = page.get_pixmap(scale=scale)
            return PageImage(
                page_number=page_number,
                width=pixmap.width,
                height=pixmap.height,
                scale=scale,
                png_bytes=pixmap.tobytes("png"),
            )
        finally:
            doc.close()


def render_page_image_bytes(data: bytes, page_number: int, dpi: int = DEFAULT_DPI) -> PageImage:
    """Rasterise one page of an in-memory PDF to a PNG.

    Bytes twin of :func:`render_page_image` — used by the review UI to
    preview redacted output without writing a file.

    Args:
        data: Raw PDF bytes.
        page_number: 1-based page number.
        dpi: Render resolution (PDF native resolution is 72 dpi).

    Returns:
        The rendered PageImage.

    Raises:
        ValueError: If *page_number* is out of range.
    """
    scale = dpi / 72.0
    with PDFIUM_LOCK, open_document(stream=data) as doc:
        if not 1 <= page_number <= doc.page_count:
            msg = f"page {page_number} out of range (1..{doc.page_count})"
            raise ValueError(msg)
        page = doc[page_number - 1]
        pixmap = page.get_pixmap(scale=scale)
        return PageImage(
            page_number=page_number,
            width=pixmap.width,
            height=pixmap.height,
            scale=scale,
            png_bytes=pixmap.tobytes("png"),
        )


def bbox_to_pixels(bbox: BoundingBox, scale: float) -> tuple[float, float, float, float]:
    """Map a bbox from PDF points to rendered-image pixels.

    Args:
        bbox: Bounding box in PDF points.
        scale: The ``PageImage.scale`` of the rendered page.

    Returns:
        ``(x0, y0, x1, y1)`` in pixels.
    """
    return (bbox.x0 * scale, bbox.y0 * scale, bbox.x1 * scale, bbox.y1 * scale)
