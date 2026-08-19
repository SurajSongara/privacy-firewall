"""PDFium-backed PDF reading — the engine's replacement for PyMuPDF's read API.

The engine used a small, well-defined slice of PyMuPDF: page geometry, four
flavours of ``page.get_text()``, image listings, rasterisation and text search.
This module reimplements exactly that slice on top of :mod:`pypdfium2` so the
consumers (parser, diagnostics, OCR adapters, page images, review session) keep
their existing call shapes.

Two coordinate facts drive the whole module:

* **PDFium is bottom-left/y-up; the engine is top-left/y-down.** Every box
  crossing this boundary is flipped here, once, so ``BoundingBox`` keeps its
  original meaning everywhere else.
* **Text lives in unrotated page space while page size is rotation-adjusted.**
  That is also how PyMuPDF behaves, so the flip uses the *mediabox* height while
  :attr:`Page.rect` reports the rotated size.

Text is grouped back into MuPDF's block/line/span shape. PDFium emits explicit
``\\r\\n`` separators between lines, so line breaks are exact; blocks follow the
page's own text objects, which is the same content-stream structure PyMuPDF
reports blocks from.
"""

from __future__ import annotations

import ctypes
import functools
import io
import math
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as raw

__all__ = [
    "PDFIUM_LOCK",
    "Annotation",
    "PdfiumDocument",
    "PdfiumPage",
    "Rect",
    "open_document",
]

PDFIUM_LOCK = threading.RLock()
"""Process-wide lock serialising every entry into the PDFium C library.

PDFium's core is not thread-safe: two threads running its C functions at once
corrupt shared state and segfault (``OSError: access violation``). The Studio
server renders pages and parses documents concurrently in a threadpool, so all
primitive read/render calls here — and the renderer's write sequence — hold
this single lock. It is re-entrant so a guarded high-level operation (rendering
redactions) may call other guarded primitives on the same thread.
"""

def synchronized[F: Callable[..., Any]](fn: F) -> F:
    """Serialise *fn* against all other PDFium access via :data:`PDFIUM_LOCK`."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with PDFIUM_LOCK:
            return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


#: Document Info-dictionary keys that can carry PII (name, account, email in an
#: export tool's stamp). Producer/Creator/dates are excluded as non-PII noise.
_META_KEYS: tuple[str, ...] = ("Title", "Author", "Subject", "Keywords")

_BLOCK_GAP_RATIO = 1.3
"""A vertical gap wider than this multiple of the line height starts a block."""

_DEFAULT_FONT_SIZE = 11.0


@dataclass
class Rect:
    """An axis-aligned rectangle in top-left page coordinates.

    Mirrors the slice of ``fitz.Rect`` the renderer relied on: union (``|``),
    intersection (``&``), containment tests and ``width``/``height``.
    """

    x0: float = math.inf
    y0: float = math.inf
    x1: float = -math.inf
    y1: float = -math.inf

    def __post_init__(self) -> None:
        """Normalise an inverted rect to the empty sentinel.

        A bare ``Rect()`` is the ``fitz.Rect()`` idiom: an empty rectangle that
        any union absorbs into. ``Rect(0, 0, 0, 0)`` stays a real zero-area rect,
        which is what a non-overlapping intersection returns.
        """
        if self.x1 < self.x0 or self.y1 < self.y0:
            self.x0, self.y0 = math.inf, math.inf
            self.x1, self.y1 = -math.inf, -math.inf

    @property
    def width(self) -> float:
        """Rectangle width (never negative)."""
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        """Rectangle height (never negative)."""
        return max(0.0, self.y1 - self.y0)

    @property
    def is_empty(self) -> bool:
        """Whether the rectangle has no area."""
        return not (self.x1 > self.x0 and self.y1 > self.y0)

    def __iter__(self) -> Any:
        """Iterate as ``(x0, y0, x1, y1)`` so ``tuple(rect)`` works."""
        return iter((self.x0, self.y0, self.x1, self.y1))

    def __or__(self, other: Rect) -> Rect:
        """Smallest rectangle containing both operands."""
        return Rect(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def __ior__(self, other: Rect) -> Rect:
        """In-place union (``rect |= other``)."""
        return self | other

    def __and__(self, other: Rect) -> Rect:
        """Overlapping region, or an empty rect when they do not overlap."""
        x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
        x1, y1 = min(self.x1, other.x1), min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return Rect(0.0, 0.0, 0.0, 0.0)
        return Rect(x0, y0, x1, y1)

    def intersects(self, other: Rect) -> bool:
        """Whether the two rectangles share any area."""
        return not (
            self.x1 <= other.x0 or other.x1 <= self.x0 or self.y1 <= other.y0 or other.y1 <= self.y0
        )

    def contains_point(self, x: float, y: float) -> bool:
        """Whether ``(x, y)`` lies inside (inclusive) the rectangle."""
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


class Pixmap:
    """A rasterised page, exposing the ``fitz.Pixmap`` members the engine used."""

    def __init__(self, bitmap: Any) -> None:
        """Wrap a rendered :class:`pypdfium2.PdfBitmap`."""
        self._image = bitmap.to_pil().convert("RGB")
        self.width, self.height = self._image.size

    def pixel(self, x: int, y: int) -> tuple[int, ...]:
        """RGB tuple of one pixel (used for background colour sampling)."""
        value = self._image.getpixel((x, y))
        return tuple(int(v) for v in value[:3])

    def tobytes(self, output: str = "png") -> bytes:
        """Encode the page as image bytes (PNG unless *output* says otherwise)."""
        buf = io.BytesIO()
        self._image.save(buf, output.upper())
        return buf.getvalue()


def _is_word_separator(char: str) -> bool:
    """Whether *char* ends a word.

    Whitespace plus control characters: PDFium reports unmapped glyphs as NUL
    and PyMuPDF breaks words on them, so a damaged run does not swallow the
    readable text that follows it into one giant "word".
    """
    return char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F


def _flip(rect_ltrb: tuple[float, float, float, float], media_height: float) -> Rect:
    """PDFium ``(left, bottom, right, top)`` to a top-left :class:`Rect`."""
    left, bottom, right, top = rect_ltrb
    return Rect(left, media_height - top, right, media_height - bottom)


#: PDFium annotation subtype codes (``FPDF_ANNOT_*``) to readable names, for the
#: kinds that can carry text a redaction must account for.
_ANNOT_SUBTYPES: dict[int, str] = {
    1: "text",
    3: "freetext",
    9: "highlight",
    13: "stamp",
    16: "popup",
    17: "fileattachment",
    20: "widget",
}


def _annot_string(annot: Any, key: str) -> str:
    """Read a string entry (e.g. ``Contents``, ``V``, ``T``) from an annotation.

    ``FPDFAnnot_GetStringValue`` takes an ASCII *key* and fills a UTF-16LE
    buffer; the returned length counts the trailing NUL. Returns ``""`` when the
    entry is absent.
    """
    key_bytes = key.encode("ascii") + b"\x00"
    length = raw.FPDFAnnot_GetStringValue(annot, key_bytes, None, 0)
    if length <= 2:  # only the NUL terminator: nothing to read
        return ""
    buffer = ctypes.create_string_buffer(length)
    raw.FPDFAnnot_GetStringValue(
        annot, key_bytes, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)), length
    )
    return buffer.raw[: length - 2].decode("utf-16-le", errors="ignore")


@dataclass(frozen=True)
class Annotation:
    """Text-bearing content that lives *outside* the page content stream.

    Comments, free-text notes, stamps and form-field (widget) values are stored
    in the page's annotation list, not its drawing commands, so plain text
    extraction never sees them. Each carries a :attr:`rect` on the page (already
    flipped to top-left space) so it can also be redacted visually.
    """

    subtype: str
    text: str
    field_name: str
    rect: Rect


class PdfiumPage:
    """One page, exposing the PyMuPDF page API the engine actually used."""

    def __init__(self, doc: PdfiumDocument, index: int) -> None:
        """Bind to page *index* of *doc* (0-based)."""
        self._doc = doc
        self._index = index
        self._page = doc._pdf[index]
        self._textpage: Any = None
        self._cache: dict[str, Any] = {}

    # ---- geometry -------------------------------------------------------

    @property
    def rect(self) -> Rect:
        """Page rectangle in points, rotation-adjusted (matches PyMuPDF)."""
        width, height = self._page.get_size()
        return Rect(0.0, 0.0, float(width), float(height))

    @property
    def rotation(self) -> int:
        """Page rotation in degrees (0/90/180/270)."""
        return int(self._page.get_rotation())

    @property
    def media_height(self) -> float:
        """Unrotated mediabox height — the reference for every y-flip."""
        _left, bottom, _right, top = self._page.get_mediabox()
        return float(top - bottom)

    @property
    def _media_height(self) -> float:
        """Alias kept for internal readability."""
        return self.media_height

    @property
    def raw_page(self) -> Any:
        """The underlying :class:`pypdfium2.PdfPage`, for write-side access."""
        return self._page

    @synchronized
    def invalidate(self) -> None:
        """Drop cached text/geometry after the page has been edited."""
        if self._textpage is not None:
            self._textpage.close()
            self._textpage = None
        self._cache.clear()

    @synchronized
    def annotations(self) -> list[Annotation]:
        """Text-bearing annotations on this page (comments, notes, form fields).

        These live outside the content stream, so :meth:`get_text` never
        reports them — an account holder's name in a form field or a phone
        number in a sticky note would otherwise slip past detection *and*
        redaction. Annotations with no readable text (pure links, empty popups)
        are skipped.
        """
        page = self._page.raw
        count = raw.FPDFPage_GetAnnotCount(page)
        results: list[Annotation] = []
        for index in range(count):
            annot = raw.FPDFPage_GetAnnot(page, index)
            if not annot:
                continue
            try:
                subtype = _ANNOT_SUBTYPES.get(raw.FPDFAnnot_GetSubtype(annot), "other")
                # Contents holds markup-annotation text; V holds a form field's
                # value. Either (or both) may be present.
                parts = [_annot_string(annot, "Contents"), _annot_string(annot, "V")]
                text = " ".join(p for p in parts if p).strip()
                field_name = _annot_string(annot, "T")
                if not text:
                    continue
                rect = self._annot_rect(annot)
                results.append(
                    Annotation(subtype=subtype, text=text, field_name=field_name, rect=rect)
                )
            finally:
                raw.FPDFPage_CloseAnnot(annot)
        return results

    def _annot_rect(self, annot: Any) -> Rect:
        """Flipped page rectangle of an annotation, or empty if unavailable."""
        rectf = raw.FS_RECTF()
        if not raw.FPDFAnnot_GetRect(annot, ctypes.byref(rectf)):
            return Rect()
        return _flip((rectf.left, rectf.bottom, rectf.right, rectf.top), self.media_height)

    # ---- text -----------------------------------------------------------

    def _tp(self) -> Any:
        """Lazily open (and keep) this page's text page."""
        if self._textpage is None:
            self._textpage = self._page.get_textpage()
        return self._textpage

    @synchronized
    def _chars(self) -> list[dict[str, Any]]:
        """Every character with geometry and style, in content-stream order.

        Line separators PDFium injects (``\\r``/``\\n``) are kept, marked with
        ``newline``, because they are the exact line breaks of the source.
        """
        cached: list[dict[str, Any]] | None = self._cache.get("chars")
        if cached is not None:
            return cached

        tp = self._tp()
        height = self._media_height
        loose = raw.FS_RECTF()
        char_matrix = raw.FS_MATRIX()
        name_buf = ctypes.create_string_buffer(128)
        flags = ctypes.c_int()
        ox, oy = ctypes.c_double(), ctypes.c_double()
        red, green, blue, alpha = (ctypes.c_uint() for _ in range(4))

        # Index by character, never by position in ``get_text_range()``: PDFium
        # counts unmapped glyphs (NUL) in ``count_chars`` but omits them from
        # the returned string, so the two indexes drift apart on damaged PDFs
        # and every bounding box after the first NUL would be wrong.
        chars: list[dict[str, Any]] = []
        for i in range(tp.count_chars()):
            ch = chr(raw.FPDFText_GetUnicode(tp, i))
            if ch in "\r\n":
                chars.append({"c": ch, "newline": True})
                continue
            raw.FPDFText_GetLooseCharBox(tp, i, ctypes.byref(loose))
            bbox = _flip((loose.left, loose.bottom, loose.right, loose.top), height)
            raw.FPDFText_GetCharOrigin(tp, i, ctypes.byref(ox), ctypes.byref(oy))
            colour = 0
            if raw.FPDFText_GetFillColor(tp, i, red, green, blue, alpha):
                colour = (red.value << 16) | (green.value << 8) | blue.value
            length = raw.FPDFText_GetFontInfo(tp, i, name_buf, 128, flags)
            font = name_buf.raw[: max(0, length)].rstrip(b"\x00").decode("utf-8", "replace")
            # ``FPDFText_GetFontSize`` is the nominal em size from the ``Tf``
            # operator; the glyph's rendered size also depends on the text
            # matrix (a doc may set size 220 and scale the matrix by 0.05 to
            # draw at 11pt). Fold in the matrix's vertical scale so ``size`` is
            # the effective rendered size — what re-inserting redaction survivor
            # text needs, and what PyMuPDF's ``get_text`` reported before the
            # PDFium migration.
            nominal = float(raw.FPDFText_GetFontSize(tp, i))
            yscale = 1.0
            if raw.FPDFText_GetMatrix(tp, i, char_matrix):
                yscale = math.hypot(char_matrix.c, char_matrix.d)
            size = (nominal * yscale) or _DEFAULT_FONT_SIZE
            owner = ctypes.cast(raw.FPDFText_GetTextObject(tp, i), ctypes.c_void_p).value
            chars.append(
                {
                    "c": ch,
                    "newline": False,
                    "obj": owner,
                    "bbox": (bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                    "origin": (float(ox.value), height - float(oy.value)),
                    "font": font,
                    "size": size,
                    "color": colour,
                    "angle": float(raw.FPDFText_GetCharAngle(tp, i)),
                }
            )

        self._cache["chars"] = chars
        return chars

    def _lines(self) -> list[dict[str, Any]]:
        """Characters regrouped into lines of same-style spans."""
        cached: list[dict[str, Any]] | None = self._cache.get("lines")
        if cached is not None:
            return cached

        lines: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = []

        def close_line() -> None:
            if not current:
                return
            spans: list[dict[str, Any]] = []
            for char in current:
                key = (char["font"], round(char["size"], 3), char["color"])
                if spans and spans[-1]["_key"] == key:
                    spans[-1]["chars"].append(char)
                else:
                    spans.append({"_key": key, "chars": [char]})
            rect = Rect()
            built: list[dict[str, Any]] = []
            for span in spans:
                span_rect = Rect()
                for char in span["chars"]:
                    span_rect |= Rect(*char["bbox"])
                rect |= span_rect
                first = span["chars"][0]
                built.append(
                    {
                        "font": first["font"],
                        "size": first["size"],
                        "color": first["color"],
                        "bbox": tuple(span_rect),
                        "text": "".join(c["c"] for c in span["chars"]),
                        "chars": [
                            {"c": c["c"], "bbox": c["bbox"], "origin": c["origin"]}
                            for c in span["chars"]
                        ],
                    }
                )
            angle = current[0]["angle"]
            lines.append(
                {
                    "bbox": tuple(rect),
                    "rect": rect,
                    "dir": (math.cos(angle), -math.sin(angle)),
                    "spans": built,
                    "obj": current[0]["obj"],
                }
            )
            current.clear()

        for char in self._chars():
            if char["newline"]:
                close_line()
            else:
                current.append(char)
        close_line()

        self._cache["lines"] = lines
        return lines

    def _text_blocks(self) -> list[dict[str, Any]]:
        """Lines grouped into blocks, following the PDF's own text objects.

        A block boundary is a change of owning text object. That is the same
        structure PyMuPDF reports, because both derive from the content stream
        rather than from geometry — and it matters: detectors read a block's
        text as one string, so merging two logically separate blocks would let
        one block's label vouch for the other's value (a ``UTR:`` reference
        number reading as a phone number, for example).

        Consecutive lines from one object stay together; a vertical gap wider
        than :data:`_BLOCK_GAP_RATIO` line heights still splits, which catches
        generators that emit a whole page as a single object.

        This splits where PyMuPDF would sometimes merge closely-spaced lines
        into one paragraph. That is the safe direction: a smaller block means
        less unrelated text in the string a detector scans.
        """
        lines = self._lines()
        blocks: list[dict[str, Any]] = []
        group: list[dict[str, Any]] = []

        def close_group() -> None:
            if not group:
                return
            rect = Rect()
            for line in group:
                rect |= line["rect"]
            blocks.append({"type": 0, "bbox": tuple(rect), "lines": list(group)})
            group.clear()

        for line in lines:
            if group:
                previous = group[-1]
                gap = line["rect"].y0 - previous["rect"].y1
                height = max(previous["rect"].height, line["rect"].height, 1.0)
                if (
                    line["obj"] != previous["obj"]
                    or gap > height * _BLOCK_GAP_RATIO
                    or gap < -height
                ):
                    close_group()
            group.append(line)
        close_group()
        return blocks

    def _image_blocks(self) -> list[dict[str, Any]]:
        """Image objects on the page, in PyMuPDF's ``type: 1`` block shape."""
        cached: list[dict[str, Any]] | None = self._cache.get("images")
        if cached is not None:
            return cached

        height = self._media_height
        blocks: list[dict[str, Any]] = []
        for obj in self._page.get_objects():
            if not isinstance(obj, pdfium.PdfImage):
                continue
            bbox = _flip(tuple(obj.get_bounds()), height)
            try:
                data = obj.get_data(decode_simple=True)
            except Exception:  # noqa: BLE001 - image bytes are best-effort
                data = b""
            blocks.append(
                {
                    "type": 1,
                    "bbox": tuple(bbox),
                    "image": bytes(data),
                    "ext": "png",
                }
            )
        self._cache["images"] = blocks
        return blocks

    @synchronized
    def get_images(self, full: bool = False) -> list[tuple[Any, ...]]:
        """Image listing — only its length was ever used (image count)."""
        del full
        return [(i,) for i, _ in enumerate(self._image_blocks())]

    def get_text(self, kind: str = "text", *, clip: Rect | None = None) -> Any:
        """Extract page text in one of PyMuPDF's shapes.

        Args:
            kind: ``"text"``, ``"words"``, ``"dict"`` or ``"rawdict"``.
            clip: Optional region; blocks outside it are dropped.

        Returns:
            A string for ``"text"``, a list of word tuples for ``"words"``,
            otherwise a ``{"blocks": [...]}`` mapping.

        Raises:
            ValueError: If *kind* is not a supported extraction shape.
        """
        if kind == "text":
            return "\n".join(
                "".join(span["text"] for span in line["spans"]) for line in self._lines()
            ) + ("\n" if self._lines() else "")

        if kind == "words":
            return self._words()

        if kind not in ("dict", "rawdict"):
            msg = f"unsupported get_text kind: {kind!r}"
            raise ValueError(msg)

        blocks = self._text_blocks() + self._image_blocks()
        if clip is not None:
            blocks = [b for b in blocks if Rect(*b["bbox"]).intersects(clip)]
        if kind == "dict":
            blocks = [
                {
                    **b,
                    "lines": [
                        {**ln, "spans": [self._strip_chars(s) for s in ln["spans"]]}
                        for ln in b["lines"]
                    ],
                }
                if b["type"] == 0
                else b
                for b in blocks
            ]
        return {"blocks": [self._clean(b) for b in blocks]}

    @staticmethod
    def _strip_chars(span: dict[str, Any]) -> dict[str, Any]:
        """Drop per-character detail (``dict`` keeps only span-level data)."""
        return {k: v for k, v in span.items() if k != "chars"}

    @staticmethod
    def _clean(block: dict[str, Any]) -> dict[str, Any]:
        """Remove the internal ``rect`` helper from a line/block tree."""
        if block["type"] != 0:
            return block
        return {
            **block,
            "lines": [{k: v for k, v in ln.items() if k != "rect"} for ln in block["lines"]],
        }

    def _words(self) -> list[tuple[float, float, float, float, str, int, int, int]]:
        """Whitespace-delimited words with bboxes, in PyMuPDF's tuple shape.

        Each word takes its *line's* vertical extent rather than its own glyph
        box, which is what PyMuPDF reports. It matters for redaction: a bar
        sized to the glyph ink would leave ascenders and descenders showing.
        """
        words: list[tuple[float, float, float, float, str, int, int, int]] = []
        for block_no, block in enumerate(self._text_blocks()):
            for line_no, line in enumerate(block["lines"]):
                word_no = 0
                pending: list[dict[str, Any]] = []
                top, bottom = line["rect"].y0, line["rect"].y1

                def flush(
                    pending: list[dict[str, Any]],
                    word_no: int,
                    top: float = 0.0,
                    bottom: float = 0.0,
                ) -> int:
                    if not pending:
                        return word_no
                    rect = Rect()
                    for char in pending:
                        rect |= Rect(*char["bbox"])
                    words.append(
                        (
                            rect.x0,
                            top,
                            rect.x1,
                            bottom,
                            "".join(c["c"] for c in pending),
                            block_no,
                            line_no,
                            word_no,
                        )
                    )
                    return word_no + 1

                for span in line["spans"]:
                    for char in span["chars"]:
                        if _is_word_separator(char["c"]):
                            word_no = flush(pending, word_no, top, bottom)
                            pending = []
                        else:
                            pending.append(char)
                word_no = flush(pending, word_no, top, bottom)
        return words

    @synchronized
    def search_for(self, needle: str, *, clip: Rect | None = None) -> list[Rect]:
        """Rectangles of every occurrence of *needle* on the page."""
        if not needle:
            return []
        chars = [c for c in self._chars() if not c["newline"]]
        haystack = "".join(c["c"] for c in chars)
        hits: list[Rect] = []
        start = haystack.find(needle)
        while start != -1:
            rect = Rect()
            for char in chars[start : start + len(needle)]:
                rect |= Rect(*char["bbox"])
            if not rect.is_empty and (clip is None or rect.intersects(clip)):
                hits.append(rect)
            start = haystack.find(needle, start + 1)
        return hits

    # ---- raster ---------------------------------------------------------

    @synchronized
    def get_pixmap(
        self,
        *,
        dpi: int | None = None,
        scale: float | None = None,
        clip: Rect | None = None,
    ) -> Pixmap:
        """Rasterise the page.

        Args:
            dpi: Target resolution; mutually exclusive with *scale*.
            scale: Direct multiplier over the 72 dpi page space.
            clip: Optional region to render instead of the whole page.

        Returns:
            The rendered :class:`Pixmap`.
        """
        factor = scale if scale is not None else (dpi or 72) / 72.0
        crop = (0.0, 0.0, 0.0, 0.0)
        if clip is not None:
            page_rect = self.rect
            crop = (
                max(0.0, clip.x0),
                max(0.0, page_rect.y1 - clip.y1),
                max(0.0, page_rect.x1 - clip.x1),
                max(0.0, clip.y0),
            )
        return Pixmap(self._page.render(scale=factor, crop=crop))

    @synchronized
    def close(self) -> None:
        """Release the text page held for this page."""
        if self._textpage is not None:
            self._textpage.close()
            self._textpage = None


class PdfiumDocument:
    """An open PDF, exposing the PyMuPDF document API the engine used."""

    def __init__(self, pdf: Any, *, needs_pass: bool, was_encrypted: bool) -> None:
        """Wrap an open :class:`pypdfium2.PdfDocument`."""
        self._pdf = pdf
        self._needs_pass = needs_pass
        self._encrypted = was_encrypted
        self._pages: dict[int, PdfiumPage] = {}
        self._closed = False

    # ---- document-level state ------------------------------------------

    @property
    def needs_pass(self) -> bool:
        """Whether the document is still locked."""
        return self._needs_pass

    @property
    def is_encrypted(self) -> bool:
        """Whether the source document carried encryption."""
        return self._encrypted

    @property
    def page_count(self) -> int:
        """Number of pages."""
        return len(self._pdf)

    @synchronized
    def metadata(self) -> dict[str, str]:
        """PII-bearing Info-dictionary entries (Title/Author/Subject/Keywords).

        Export tools routinely stamp the account holder's name or number into
        these fields, where they are invisible on the page but trivially
        readable. Producer/Creator/date noise is excluded. Empty values are
        dropped, so an empty dict means nothing sensitive was found here.
        """
        result: dict[str, str] = {}
        for key in _META_KEYS:
            value = self._pdf.get_metadata_value(key).strip()
            if value:
                result[key] = value
        return result

    def __len__(self) -> int:
        """Number of pages."""
        return 0 if self._needs_pass else len(self._pdf)

    @synchronized
    def __getitem__(self, index: int) -> PdfiumPage:
        """Return (and cache) the page at *index*."""
        if index not in self._pages:
            self._pages[index] = PdfiumPage(self, index)
        return self._pages[index]

    def __iter__(self) -> Iterator[PdfiumPage]:
        """Iterate over pages, so ``for page in doc`` works as it did."""
        return (self[i] for i in range(len(self)))

    def __enter__(self) -> PdfiumDocument:
        """Support ``with open_pdf(...) as doc:``."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the document on context exit."""
        self.close()

    @synchronized
    def close(self) -> None:
        """Release every page and the underlying document."""
        if self._closed:
            return
        self._closed = True
        for page in self._pages.values():
            page.close()
        self._pages.clear()
        self._pdf.close()

    @synchronized
    def sanitize(self) -> None:
        """Strip every annotation from every page (comments, notes, form fields).

        Annotations live outside the content stream, so a redaction that only
        edits the drawing commands leaves them untouched — a phone number in a
        sticky note or a name in a form field would survive. A redacted document
        is meant to be shared clean, so they are removed wholesale, matching what
        "sanitise document" does in desktop PDF tools. Document metadata is
        dropped separately by :meth:`save` (the fresh output document has none).
        """
        for i in range(len(self._pdf)):
            page = self._pdf[i]
            # Remove from the tail so surviving indices never shift.
            for index in range(raw.FPDFPage_GetAnnotCount(page.raw) - 1, -1, -1):
                raw.FPDFPage_RemoveAnnot(page.raw, index)

    # ---- output ---------------------------------------------------------

    @synchronized
    def tobytes(self, *, sanitize: bool = False) -> bytes:
        """Serialise the document, always unencrypted.

        Args:
            sanitize: Also strip annotations and metadata (for redacted output).
        """
        buf = io.BytesIO()
        self.save(buf, sanitize=sanitize)
        return buf.getvalue()

    @synchronized
    def save(self, dest: Any, *, sanitize: bool = False) -> None:
        """Write the document to a path or file object, always unencrypted.

        PDFium has no encryption *writer*, but ``FPDF_SaveAsCopy`` preserves the
        source's encryption dictionary. Copying the pages into a fresh document
        is what actually drops it, so a redacted copy always opens without a
        password. The fresh document also carries no Info dictionary, so the
        source's metadata never reaches the output.

        Args:
            dest: A path or writable binary file object.
            sanitize: Strip annotations before writing (for redacted output).
                Metadata is always dropped by the fresh-document copy.
        """
        if sanitize:
            self.sanitize()
        out = pdfium.PdfDocument.new()
        try:
            out.import_pages(self._pdf)
            if isinstance(dest, str | Path):
                with Path(dest).open("wb") as handle:
                    out.save(handle)
            else:
                out.save(dest)
        finally:
            out.close()

    @property
    def raw(self) -> Any:
        """The underlying :class:`pypdfium2.PdfDocument` (write-side access)."""
        return self._pdf


def is_password_error(exc: Exception) -> bool:
    """Whether a PDFium load failure was caused by a missing/wrong password.

    PDFium reports a corrupt file and a locked file through the same exception
    type, so the message is the only discriminator available.
    """
    return "password" in str(exc).lower()


@synchronized
def open_document(
    path: str | Path | None = None,
    *,
    stream: bytes | None = None,
    password: str | None = None,
) -> PdfiumDocument:
    """Open a PDF from a path or bytes, authenticating when required.

    Args:
        path: Path to the PDF (mutually exclusive with *stream*).
        stream: Raw PDF bytes (mutually exclusive with *path*).
        password: Password for an encrypted document.

    Returns:
        The opened document. When the file is locked and no usable password was
        given, the returned document reports ``needs_pass``.

    Raises:
        PdfiumError: If the file is unreadable for any reason other than being
            password-protected.
    """
    source: Any = stream if stream is not None else str(path)
    try:
        pdf = pdfium.PdfDocument(source, password=password)
    except pdfium.PdfiumError as exc:
        if not is_password_error(exc):
            raise
        # Either no password was supplied or it was wrong; the caller decides
        # whether a locked document is fatal.
        return PdfiumDocument(_EmptyPdf(), needs_pass=True, was_encrypted=True)
    # -1 means "no security handler", i.e. the document was never encrypted.
    encrypted = int(raw.FPDF_GetSecurityHandlerRevision(pdf)) != -1
    return PdfiumDocument(pdf, needs_pass=False, was_encrypted=encrypted)


class _EmptyPdf:
    """Stand-in for a document that could not be unlocked."""

    def __len__(self) -> int:
        """A locked document exposes no pages."""
        return 0

    @synchronized
    def __getitem__(self, index: int) -> Any:
        """Always fails — a locked document has no readable pages.

        Raises:
            IndexError: Always.
        """
        msg = "document is locked"
        raise IndexError(msg)

    @synchronized
    def close(self) -> None:
        """No resources to release."""
