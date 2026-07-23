"""PDF rendering: applies redaction instructions from a plan onto a PDF copy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from privacy_firewall.engine.redaction import RedactionPlan, RedactionType
from privacy_firewall.parsers.pdf_open import open_pdf
from privacy_firewall.parsers.pdfium_compat import PdfiumDocument, Rect, open_document
from privacy_firewall.renderer.pdfium_draw import PageWriter, base14_name


class PDFRenderer:
    """Applies a RedactionPlan to a PDF file, producing a redacted copy.

    Redacted text objects are *deleted from the page* and the content stream
    regenerated, so the glyphs leave the file rather than being covered up.
    Surviving characters from the same text runs are re-inserted at their
    original positions.

    The original PDF is never modified.
    """

    BLACK_BAR_COLOR: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """RGB colour used for ``BLACK_BAR`` redactions."""

    REPLACE_FILL: tuple[float, float, float] = (1.0, 1.0, 1.0)
    """Fallback background colour behind ``REPLACE`` text."""

    REPLACE_TEXT_COLOR: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """Fallback colour of the ``REPLACE`` replacement text."""

    DEFAULT_REPLACEMENT = "*****"
    """Replacement drawn when a ``REPLACE`` redaction carries no text."""

    DEFAULT_FONT_SIZE = 11.0
    """Fallback font size when the original style cannot be sampled."""

    HIGHLIGHT_COLOR: tuple[float, float, float] = (1.0, 1.0, 0.0)
    """RGB colour used for ``HIGHLIGHT`` redactions."""

    HIGHLIGHT_OPACITY: float = 0.3
    """Opacity (0-1) applied to highlight overlays."""

    def render(
        self,
        input_path: str | Path,
        output_path: str | Path,
        plan: RedactionPlan,
        *,
        password: str | None = None,
    ) -> Path:
        """Generate a redacted PDF copy.

        Redactions are applied to an in-memory copy of the source PDF, then
        saved to *output_path*. The original file is never touched. An
        encrypted source is written out **unencrypted** — the redacted copy is
        meant to be shared, so it must open without a password.

        Args:
            input_path: Path to the original PDF (never modified).
            output_path: Where to write the redacted copy.
            plan: The redaction plan to apply.
            password: Password for an encrypted source PDF, if required.

        Returns:
            The absolute path to the output file.

        Raises:
            EncryptedPDFError: If the source is password-protected and no
                correct password was supplied.
        """
        doc = open_pdf(input_path, password=password)
        try:
            self._apply_plan(doc, plan)
            doc.save(str(output_path))
        finally:
            doc.close()

        return Path(output_path).resolve()

    @staticmethod
    def render_bytes(data: bytes, plan: RedactionPlan) -> bytes:
        """Generate a redacted PDF from raw bytes.

        Args:
            data: Raw bytes of the original PDF.
            plan: The redaction plan to apply.

        Returns:
            Raw bytes of the redacted PDF.
        """
        doc = open_document(stream=data)
        try:
            PDFRenderer._apply_plan(doc, plan)
            return doc.tobytes()
        finally:
            doc.close()

    @staticmethod
    def _apply_plan(doc: PdfiumDocument, plan: RedactionPlan) -> None:
        """Apply every redaction in the plan to the open document.

        Each redaction's bbox is refined by searching for its text inside its
        own region (falling back to the detection bbox if not found), and
        identical rects from overlapping detections are deduplicated so no
        region is redacted twice.

        Args:
            doc: An open document.
            plan: The redaction plan to apply.
        """
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_redactions = plan.by_page(page_num + 1)
            if not page_redactions:
                continue

            jobs: list[tuple[Rect, RedactionType, str]] = []
            highlights: list[Rect] = []
            seen: set[tuple[float, float, float, float]] = set()
            for redaction in page_redactions:
                bbox_rect = Rect(
                    redaction.bbox.x0,
                    redaction.bbox.y0,
                    redaction.bbox.x1,
                    redaction.bbox.y1,
                )
                # Refine the bbox via search, but only inside this redaction's
                # own region: the plan carries one redaction per instance, so a
                # page-wide search of repeated text would return every twin and
                # the duplicate jobs would repaint their background fill over
                # the already-drawn styled stars.
                clip = Rect(
                    bbox_rect.x0 - 2, bbox_rect.y0 - 2, bbox_rect.x1 + 2, bbox_rect.y1 + 2
                )
                rects = page.search_for(redaction.detection.text, clip=clip)
                if not rects:
                    # Imprecise bbox (e.g. OCR geometry offset from the native
                    # text layer): search the whole page but keep only the match
                    # nearest this detection's bbox.
                    matches = page.search_for(redaction.detection.text)
                    if matches:
                        cx = (bbox_rect.x0 + bbox_rect.x1) / 2
                        cy = (bbox_rect.y0 + bbox_rect.y1) / 2
                        rects = [
                            min(
                                matches,
                                key=lambda r: (
                                    ((r.x0 + r.x1) / 2 - cx) ** 2 + ((r.y0 + r.y1) / 2 - cy) ** 2
                                ),
                            )
                        ]
                    else:
                        rects = [bbox_rect]
                for rect in rects:
                    key = (
                        round(rect.x0, 1),
                        round(rect.y0, 1),
                        round(rect.x1, 1),
                        round(rect.y1, 1),
                    )
                    if key in seen:
                        continue  # two detections of the same instance
                    seen.add(key)
                    if redaction.redaction_type == RedactionType.HIGHLIGHT:
                        highlights.append(rect)
                    else:
                        replacement = redaction.replacement_text or PDFRenderer.DEFAULT_REPLACEMENT
                        jobs.append((rect, redaction.redaction_type, replacement))

            writer = PageWriter(doc.raw, page.raw_page, page.media_height)
            if highlights:
                for rect in highlights:
                    writer.draw_rect(
                        rect,
                        fill=PDFRenderer.HIGHLIGHT_COLOR,
                        opacity=PDFRenderer.HIGHLIGHT_OPACITY,
                    )
            if jobs:
                jobs = PDFRenderer._merge_overlapping_jobs(jobs)
                PDFRenderer._redact(page, writer, jobs)
            writer.finalize()
            page.invalidate()

    @staticmethod
    def _merge_overlapping_jobs(
        jobs: list[tuple[Rect, RedactionType, str]],
    ) -> list[tuple[Rect, RedactionType, str]]:
        """Merge same-type jobs whose rects overlap into their union.

        Two detections can cover the same text with *different* rects (e.g. a
        detector's full-width email plus a manual mark of the same email) —
        drawing both would paint stars over stars. The union keeps one clean
        patch; the wider rect's replacement wins (it mirrors more of the
        original text's length).
        """
        merged: list[tuple[Rect, RedactionType, str]] = []
        for rect, rtype, replacement in jobs:
            while True:
                hit = next(
                    (
                        i
                        for i, (mrect, mtype, _mrepl) in enumerate(merged)
                        if mtype == rtype and rect.intersects(mrect)
                    ),
                    None,
                )
                if hit is None:
                    break
                mrect, _mtype, mrepl = merged.pop(hit)
                if mrect.width > rect.width:
                    replacement = mrepl
                rect = rect | mrect
            merged.append((rect, rtype, replacement))
        return merged

    @staticmethod
    def _redact(
        page: Any, writer: PageWriter, jobs: list[tuple[Rect, RedactionType, str]]
    ) -> None:
        """Redact *jobs* without disturbing the rest of each text line.

        A PDF text run cannot be split without re-laying it out, so any run a
        redaction touches is removed **whole** and its surviving characters are
        re-drawn at their exact original positions:

        1. Snapshot every affected line's characters (text, position, font,
           size, colour) before touching the page.
        2. Sample the local background colour behind each redaction, while the
           page still renders as the user saw it.
        3. Delete the text objects covering those lines, and zero image pixels
           inside the redaction rectangles (scans carry their PII in the image).
        4. Re-insert the surviving characters and draw the styled replacement
           stars / black bars.
        """
        rects = [job[0] for job in jobs]
        try:
            lines = PDFRenderer._snapshot_lines(page)
        except ValueError:
            lines = []  # rotated text: fall back to plain cover-and-strip

        # Lines hit by a redaction — chain-expanded so that any line clipped by
        # another affected line's removal band is also captured and re-inserted
        # rather than silently damaged.
        affected: list[dict[str, Any]] = []
        affected_ids: set[int] = set()
        pending = [ln for ln in lines if any(ln["rect"].intersects(r) for r in rects)]
        while pending:
            for line in pending:
                affected.append(line)
                affected_ids.add(id(line))
            bands = [ln["rect"] for ln in affected]
            pending = [
                ln
                for ln in lines
                if id(ln) not in affected_ids and any(ln["rect"].intersects(b) for b in bands)
            ]

        survivors: list[dict[str, Any]] = []
        anchors: dict[int, dict[str, Any]] = {}
        for line in affected:
            for span in line["spans"]:
                fontname = base14_name(span["font"])
                run: list[dict[str, Any]] = []
                run_width = 0.0

                def flush(run: list[dict[str, Any]], span: dict[str, Any] = {}) -> None:
                    if run:
                        survivors.append(PDFRenderer._make_run(span, run))
                        run.clear()

                for char in span["chars"]:
                    hit = PDFRenderer._char_hit(char, rects)
                    if hit is not None:
                        flush(run, span)
                        # First redacted character anchors the replacement.
                        anchors.setdefault(
                            hit,
                            {
                                "origin": char["origin"],
                                "size": span["size"],
                                "color": span["color"],
                                "font": span["font"],
                            },
                        )
                        continue
                    if run:
                        # Split the run wherever the original glyph position
                        # deviates from the natural advance (kerning, or metrics
                        # differing from the base-14 replacement font) — every
                        # glyph must land exactly where it was.
                        expected_x = run[0]["origin"][0] + run_width
                        if abs(float(char["origin"][0]) - expected_x) > 0.3:
                            flush(run, span)
                    if not run:
                        run_width = 0.0
                    run.append(char)
                    run_width += writer.text_width(char["c"], fontname, span["size"])
                flush(run, span)

        # Sample backgrounds before anything is stripped or cleared.
        fills = [
            PDFRenderer._sample_background(page, rect)
            if rtype == RedactionType.REPLACE
            else PDFRenderer.BLACK_BAR_COLOR
            for rect, rtype, _ in jobs
        ]

        # Strip the affected text runs whole, then wipe image pixels.
        writer.remove_text_in([ln["rect"] for ln in affected] or rects)
        writer.clear_image_pixels(rects)

        # Draw fills, then the styled stars, then the surviving text.
        for (rect, rtype, replacement), fill in zip(jobs, fills):
            writer.draw_rect(rect, fill=fill)
            if rtype != RedactionType.REPLACE:
                continue
            anchor = anchors.get(id(rect))
            if anchor is not None:
                fontsize = float(anchor["size"])
                color = PDFRenderer._int_rgb(int(anchor["color"]))
                fontname = base14_name(str(anchor["font"]))
                origin = (rect.x0, float(anchor["origin"][1]))
            else:  # no text under the rect (scanned image region)
                fontsize = max(4.0, min(PDFRenderer.DEFAULT_FONT_SIZE, rect.height * 0.75))
                color = PDFRenderer.REPLACE_TEXT_COLOR
                fontname = "helv"
                origin = (rect.x0, rect.y1 - rect.height * 0.25)
            stars = PDFRenderer._fit_stars(writer, replacement, rect, fontsize)
            writer.insert_text(
                origin, stars, fontsize=fontsize, fontname=fontname, color=color
            )

        for survivor in survivors:
            writer.insert_text(
                survivor["origin"],
                survivor["text"],
                fontsize=survivor["size"],
                fontname=base14_name(survivor["font"]),
                color=PDFRenderer._int_rgb(survivor["color"]),
            )

    @staticmethod
    def _snapshot_lines(page: Any) -> list[dict[str, Any]]:
        """Capture every horizontal text line with per-character geometry.

        Raises:
            ValueError: If the page contains rotated (non-horizontal) text —
                the caller falls back to plain cover-and-strip redaction.
        """
        lines: list[dict[str, Any]] = []
        for block in page.get_text("rawdict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = []
                rect = Rect()
                for span in line.get("spans", []):
                    chars = [
                        {"c": ch["c"], "bbox": ch["bbox"], "origin": ch["origin"]}
                        for ch in span.get("chars", [])
                    ]
                    if not chars:
                        continue
                    for ch in chars:
                        rect |= Rect(*ch["bbox"])
                    spans.append(
                        {
                            "font": span.get("font", ""),
                            "size": float(span.get("size", PDFRenderer.DEFAULT_FONT_SIZE)),
                            "color": int(span.get("color", 0)),
                            "chars": chars,
                        }
                    )
                if not spans:
                    continue
                if abs(line.get("dir", (1, 0))[1]) > 0.01:
                    msg = "page has non-horizontal text"
                    raise ValueError(msg)
                lines.append({"rect": rect, "spans": spans})
        return lines

    @staticmethod
    def _char_hit(char: dict[str, Any], rects: list[Rect]) -> int | None:
        """Id of the first rect containing the character's centre, else None."""
        x0, y0, x1, y1 = char["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for rect in rects:
            if rect.contains_point(cx, cy):
                return id(rect)
        return None

    @staticmethod
    def _make_run(span: dict[str, Any], chars: list[dict[str, Any]]) -> dict[str, Any]:
        """Bundle consecutive surviving characters into one insertable run."""
        return {
            "text": "".join(ch["c"] for ch in chars),
            "origin": (float(chars[0]["origin"][0]), float(chars[0]["origin"][1])),
            "font": span["font"],
            "size": span["size"],
            "color": span["color"],
        }

    @staticmethod
    def _base14_for(font: str) -> str:
        """Nearest base-14 family for an embedded font name."""
        return base14_name(font)

    @staticmethod
    def _int_rgb(color: int) -> tuple[float, float, float]:
        """sRGB integer (as reported by ``get_text``) to a float triple."""
        return (
            ((color >> 16) & 255) / 255.0,
            ((color >> 8) & 255) / 255.0,
            (color & 255) / 255.0,
        )

    @staticmethod
    def _sample_background(page: Any, rect: Rect) -> tuple[float, float, float]:
        """Most common pixel colour on the border just outside *rect*.

        Approximates the local background (white page, coloured table row, dark
        header band) so the redaction patch doesn't punch a white hole into
        coloured areas.
        """
        try:
            pad = 2.0
            clip = Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
            clip = clip & page.rect
            if clip.is_empty:
                return PDFRenderer.REPLACE_FILL
            pix = page.get_pixmap(clip=clip)
            width, height = pix.width, pix.height
            if width < 3 or height < 3:
                return PDFRenderer.REPLACE_FILL
            counts: dict[tuple[int, ...], int] = {}
            border = [(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
            border += [(0, y) for y in range(height)] + [(width - 1, y) for y in range(height)]
            for x, y in border:
                value = tuple(pix.pixel(x, y)[:3])
                counts[value] = counts.get(value, 0) + 1
            most_common = max(counts, key=lambda k: counts[k])
            return (most_common[0] / 255.0, most_common[1] / 255.0, most_common[2] / 255.0)
        except Exception:  # noqa: BLE001 - style matching must never block redaction
            return PDFRenderer.REPLACE_FILL

    @staticmethod
    def _fit_stars(writer: PageWriter, replacement: str, rect: Rect, fontsize: float) -> str:
        """Trim a star-only replacement so it cannot overflow the rect.

        Non-star replacements are returned unchanged.
        """
        if not replacement or set(replacement) != {"*"}:
            return replacement
        char_width = writer.text_width("*", "helv", fontsize)
        if char_width <= 0:
            return replacement
        max_chars = max(1, int(rect.width / char_width))
        return replacement[:max_chars]
