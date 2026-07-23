"""PDF parsing utilities for extracting blocks from PDF documents."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from privacy_firewall.models.blocks import Block, ImageBlock, TextBlock, TextSpan
from privacy_firewall.models.document import Document, Page
from privacy_firewall.models.geometry import BoundingBox
from privacy_firewall.parsers.pdf_open import open_pdf

WordTuple = tuple[float, float, float, float, str, int, int, int]
"""Type of each word tuple returned by ``get_text("words")``."""


class PDFParser:
    """Parser that extracts text and image blocks from PDF files."""
    def __init__(self, file_path: str | Path, password: str | None = None) -> None:
        """Initialize the parser with a path to a PDF file.

        Args:
            file_path: Path to the PDF file.
            password: Password for an encrypted PDF, if required.
        """
        self._path = Path(file_path)
        self._password = password

    def parse(self) -> Document:
        """Parse the PDF file and return a structured Document.

        Returns:
            A Document containing all pages with their text and image blocks.

        Raises:
            EncryptedPDFError: If the PDF is password-protected and no
                correct password was supplied.
        """
        doc = open_pdf(self._path, password=self._password)
        pages: list[Page] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            raw: dict[str, Any] = page.get_text("dict")
            words_data: list[WordTuple] = page.get_text("words")
            blocks = self._extract_blocks(raw, words_data, page_num + 1)
            pages.append(
                Page(
                    page_number=page_num + 1,
                    width=page.rect.width,
                    height=page.rect.height,
                    blocks=blocks,
                )
            )

        doc.close()
        return Document(pages=pages)

    @staticmethod
    def parse_bytes(data: bytes, password: str | None = None) -> Document:
        """Parse PDF content from raw bytes and return a structured Document.

        Args:
            data: Raw PDF bytes.
            password: Password for an encrypted PDF, if required.

        Returns:
            A Document containing all pages with their text and image blocks.

        Raises:
            EncryptedPDFError: If the PDF is password-protected and no
                correct password was supplied.
        """
        doc = open_pdf(stream=data, password=password)
        pages: list[Page] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            raw: dict[str, Any] = page.get_text("dict")
            words_data: list[WordTuple] = page.get_text("words")
            blocks = PDFParser._extract_blocks(raw, words_data, page_num + 1)
            pages.append(
                Page(
                    page_number=page_num + 1,
                    width=page.rect.width,
                    height=page.rect.height,
                    blocks=blocks,
                )
            )

        doc.close()
        return Document(pages=pages)

    @staticmethod
    def _extract_blocks(
        raw: dict[str, Any],
        words_data: list[WordTuple],
        page_number: int,
    ) -> list[Block]:
        """Extract text and image blocks from a page's raw dictionary.

        Uses ``get_text("words")`` for per-word bounding boxes so that
        each word becomes a ``TextSpan`` with its precise geometry.
        Image blocks are extracted from ``get_text("dict")`` as before.

        Args:
            raw: Raw page data as returned by ``get_text("dict")``.
            words_data: Word-level data from ``get_text("words")``.
            page_number: The 1-based page number.

        Returns:
            A list of Block objects (TextBlock or ImageBlock).
        """
        blocks: list[Block] = []

        # Group words by block_no
        block_words: dict[int, list[WordTuple]] = {}
        for w in words_data:
            block_no: int = w[5]
            block_words.setdefault(block_no, []).append(w)

        # Map dict block bboxes to words using spatial proximity
        # get_text("words") uses different block numbering than get_text("dict")
        for item in raw.get("blocks", []):
            item_typed: dict[str, Any] = item
            bbox = BoundingBox(
                x0=item_typed["bbox"][0],
                y0=item_typed["bbox"][1],
                x1=item_typed["bbox"][2],
                y1=item_typed["bbox"][3],
            )
            block_id = str(uuid.uuid4())

            if item_typed["type"] == 0:
                # Find words that fall within this block's bbox
                block_x0, block_y0, block_x1, block_y1 = item_typed["bbox"]
                matching_words = []
                for w in words_data:
                    # Word bbox: (x0, y0, x1, y1, text, block_no, line_no, word_no)
                    wx0, wy0, wx1, wy1 = w[0], w[1], w[2], w[3]
                    # Check if word overlaps with block bbox
                    if (wx0 < block_x1 and wx1 > block_x0 and
                        wy0 < block_y1 and wy1 > block_y0):
                        matching_words.append(w)

                # Sort words by position (top-to-bottom, left-to-right)
                matching_words.sort(key=lambda w: (w[1], w[0]))

                text_parts: list[str] = []
                spans: list[TextSpan] = []
                for w in matching_words:
                    word_text: str = w[4]
                    spans.append(
                        TextSpan(
                            text=word_text,
                            bbox=BoundingBox(
                                x0=w[0],
                                y0=w[1],
                                x1=w[2],
                                y1=w[3],
                            ),
                        )
                    )
                    text_parts.append(word_text)
                text = " ".join(text_parts)
                blocks.append(
                    TextBlock(
                        block_id=block_id,
                        bbox=bbox,
                        page_number=page_number,
                        confidence=1.0,
                        text=text,
                        spans=spans,
                    )
                )

            elif item_typed["type"] == 1:
                image_bytes = item_typed.get("image")
                ext = item_typed.get("ext", "png")
                blocks.append(
                    ImageBlock(
                        block_id=block_id,
                        bbox=bbox,
                        page_number=page_number,
                        confidence=1.0,
                        image_data=image_bytes,
                        mime_type=f"image/{ext}",
                    )
                )

        return blocks
