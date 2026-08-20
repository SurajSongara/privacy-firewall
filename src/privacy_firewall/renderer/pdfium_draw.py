"""PDFium write primitives: the drawing and stripping operations redaction needs.

PyMuPDF offered ``insert_text``/``draw_rect``/``apply_redactions`` directly.
PDFium works one page *object* at a time, so this module wraps the raw calls
into the same handful of operations, keeping every caller in the engine's
top-left coordinate space.

Removal here is genuinely destructive: a text object is deleted from the page
and the content stream regenerated, so the glyphs are gone from the file rather
than covered up.
"""

from __future__ import annotations

import ctypes
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from privacy_firewall.parsers.pdfium_compat import Rect

__all__ = ["PageWriter", "base14_name"]

_FILL_MODE_WINDING = 1

STANDARD_FONTS: dict[str, bytes] = {
    "helv": b"Helvetica",
    "hebo": b"Helvetica-Bold",
    "heit": b"Helvetica-Oblique",
    "cour": b"Courier",
    "cobo": b"Courier-Bold",
    "tiro": b"Times-Roman",
    "tibo": b"Times-Bold",
}
"""PyMuPDF base-14 aliases mapped to PDFium's standard font names."""


def base14_name(font: str) -> str:
    """Nearest base-14 alias for an embedded font name.

    Replacement text can only use standard fonts, so exact matching is
    impossible — but keeping the family (mono / serif / sans) preserves the
    look of the surrounding content.
    """
    name = font.lower()
    if "courier" in name or "mono" in name:
        return "cour"
    if "times" in name or "georgia" in name or "garamond" in name or "book" in name:
        return "tiro"
    return "helv"


def _widestring(text: str) -> Any:
    """Encode *text* as the NUL-terminated UTF-16LE PDFium expects."""
    return ctypes.cast(
        ctypes.c_char_p((text + "\0").encode("utf-16-le")), raw.FPDF_WIDESTRING
    )


class PageWriter:
    """Draw, measure and strip content on one page, in top-left coordinates."""

    def __init__(self, pdf: Any, page: Any, media_height: float) -> None:
        """Bind to an open PDFium document/page pair.

        Args:
            pdf: The owning :class:`pypdfium2.PdfDocument`.
            page: The :class:`pypdfium2.PdfPage` being edited.
            media_height: Unrotated mediabox height, for the y-flip.
        """
        self._pdf = pdf
        self._page = page
        self._height = media_height
        self._fonts: dict[str, Any] = {}
        self._dirty = False

    # ---- fonts and metrics ---------------------------------------------

    def _font(self, alias: str) -> Any:
        """Load (and cache) a standard font by PyMuPDF alias."""
        if alias not in self._fonts:
            name = STANDARD_FONTS.get(alias, b"Helvetica")
            self._fonts[alias] = raw.FPDFText_LoadStandardFont(self._pdf, name)
        return self._fonts[alias]

    def text_width(self, text: str, fontname: str = "helv", fontsize: float = 11.0) -> float:
        """Advance width of *text*, matching ``fitz.get_text_length``.

        Sums per-glyph advances (not ink bounds), which is what layout needs.
        """
        font = self._font(fontname)
        total = 0.0
        width = ctypes.c_float()
        for char in text:
            if raw.FPDFFont_GetGlyphWidth(font, ord(char), fontsize, ctypes.byref(width)):
                total += float(width.value)
        return total

    # ---- drawing --------------------------------------------------------

    def insert_text(
        self,
        origin: tuple[float, float],
        text: str,
        *,
        fontsize: float,
        fontname: str = "helv",
        color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> bool:
        """Draw *text* with its baseline starting at *origin* (top-left space).

        Returns:
            ``True`` when the text was placed; ``False`` when the standard font
            could not encode it (non-Latin replacement text, for example).
        """
        if not text:
            return True
        obj = raw.FPDFPageObj_CreateTextObj(self._pdf, self._font(fontname), fontsize)
        if not obj:
            return False
        if not raw.FPDFText_SetText(obj, _widestring(text)):
            raw.FPDFPageObj_Destroy(obj)
            return False
        red, green, blue = (int(max(0.0, min(1.0, c)) * 255) for c in color)
        raw.FPDFPageObj_SetFillColor(obj, red, green, blue, 255)
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, origin[0], self._height - origin[1])
        raw.FPDFPage_InsertObject(self._page, obj)
        self._dirty = True
        return True

    def draw_rect(
        self,
        rect: Rect,
        *,
        fill: tuple[float, float, float],
        opacity: float = 1.0,
    ) -> None:
        """Fill *rect* with a solid colour (top-left space)."""
        if rect.is_empty:
            return
        bottom = self._height - rect.y1
        obj = raw.FPDFPageObj_CreateNewRect(rect.x0, bottom, rect.width, rect.height)
        if not obj:
            return
        red, green, blue = (int(max(0.0, min(1.0, c)) * 255) for c in fill)
        raw.FPDFPageObj_SetFillColor(obj, red, green, blue, int(max(0.0, min(1.0, opacity)) * 255))
        raw.FPDFPath_SetDrawMode(obj, _FILL_MODE_WINDING, False)
        raw.FPDFPage_InsertObject(self._page, obj)
        self._dirty = True

    # ---- destructive removal -------------------------------------------

    def remove_text_in(self, rects: list[Rect]) -> None:
        """Delete every text object whose bounds meet any rect in *rects*.

        Whole objects go, not partial ranges: PDF text runs cannot be split
        without re-laying them out, so the caller re-inserts the surviving
        characters at their original positions afterwards.
        """
        if not rects:
            return
        for obj in list(self._page.get_objects()):
            if raw.FPDFPageObj_GetType(obj) != raw.FPDF_PAGEOBJ_TEXT:
                continue
            bounds = self._bounds(obj)
            if bounds is not None and any(bounds.intersects(r) for r in rects):
                raw.FPDFPage_RemoveObject(self._page, obj)
                raw.FPDFPageObj_Destroy(obj.raw)
                self._dirty = True

    def clear_image_pixels(self, rects: list[Rect]) -> None:
        """Zero the pixels of any image lying under *rects* (scanned pages).

        A scan carries its PII in the raster, so covering it with a rectangle
        would leave the data recoverable underneath.
        """
        if not rects:
            return
        for obj in list(self._page.get_objects()):
            if not isinstance(obj, pdfium.PdfImage):
                continue
            bounds = self._bounds(obj)
            if bounds is None or bounds.is_empty:
                continue
            hits = [r & bounds for r in rects]
            hits = [r for r in hits if not r.is_empty]
            if not hits:
                continue
            try:
                self._blank_regions(obj, bounds, hits)
            except Exception:  # noqa: BLE001 - a stubborn image must not abort redaction
                continue

    def _blank_regions(self, image: Any, bounds: Rect, hits: list[Rect]) -> None:
        """Paint *hits* black inside *image*, whose page extent is *bounds*."""
        from PIL import ImageDraw

        # ``render=True`` composites the image's soft mask into an alpha channel;
        # reading the raw base (``render=False``) and writing it back as RGB
        # strips that mask, so a faint watermark's normally-transparent base
        # pixels (often solid black at the edges) render as opaque black bars
        # across the page. Keep the frame RGBA so transparency survives the
        # round-trip while opaque scans (all alpha 255) are blanked as before.
        frame = image.get_bitmap(render=True).to_pil()
        if frame.mode != "RGBA":
            frame = frame.convert("RGBA")
        cols, rows = frame.size
        draw = ImageDraw.Draw(frame)
        painted = False
        for hit in hits:
            # Page space -> image pixel space. The bitmap's y axis runs top-down
            # and ``bounds`` is already top-left, so no flip is needed here.
            x0 = int((hit.x0 - bounds.x0) / bounds.width * cols)
            x1 = int((hit.x1 - bounds.x0) / bounds.width * cols)
            y0 = int((hit.y0 - bounds.y0) / bounds.height * rows)
            y1 = int((hit.y1 - bounds.y0) / bounds.height * rows)
            x0, x1 = max(0, min(x0, cols)), max(0, min(x1, cols))
            y0, y1 = max(0, min(y0, rows)), max(0, min(y1, rows))
            if x1 > x0 and y1 > y0:
                draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(0, 0, 0, 255))
                painted = True
        if not painted:
            return
        image.set_bitmap(pdfium.PdfBitmap.from_pil(frame))
        self._dirty = True

    def _bounds(self, obj: Any) -> Rect | None:
        """Page-space bounds of a page object, flipped to top-left."""
        left, bottom, right, top = (ctypes.c_float() for _ in range(4))
        handle = getattr(obj, "raw", obj)
        if not raw.FPDFPageObj_GetBounds(handle, left, bottom, right, top):
            return None
        return Rect(
            float(left.value),
            self._height - float(top.value),
            float(right.value),
            self._height - float(bottom.value),
        )

    def finalize(self) -> None:
        """Regenerate the page content stream if anything changed."""
        if self._dirty:
            raw.FPDFPage_GenerateContent(self._page)
            self._dirty = False
