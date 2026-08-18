"""Block models -- ``TextBlock`` / ``ImageBlock`` / ``TableBlock`` within a page."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from privacy_firewall.models.geometry import BoundingBox


class BlockType(StrEnum):
    """Supported content block types within a document page."""

    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"


class Block(BaseModel):
    """A content block extracted from a document page.

    Stores the block identifier, type, bounding geometry, page number,
    and detection confidence.
    """

    model_config = ConfigDict(frozen=True)

    block_id: str
    block_type: BlockType
    bbox: BoundingBox
    page_number: int
    confidence: float

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: float) -> float:
        """Validate that confidence is between 0.0 and 1.0 (inclusive)."""
        if not 0.0 <= v <= 1.0:
            msg = "confidence must be between 0 and 1"
            raise ValueError(msg)
        return v

    @field_validator("page_number")
    @classmethod
    def page_number_must_be_positive(cls, v: int) -> int:
        """Validate that page_number is >= 1."""
        if v < 1:
            msg = "page_number must be >= 1"
            raise ValueError(msg)
        return v


class TextSpan(BaseModel):
    """A single text span with its precise bounding box within a block.

    Represents a contiguous piece of text from a PDF content stream
    that shares the same formatting properties.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    bbox: BoundingBox


class TextBlock(Block):
    """A block containing extracted text content with per-span geometry."""

    model_config = ConfigDict(frozen=True)

    block_type: Literal[BlockType.TEXT] = BlockType.TEXT
    text: str
    spans: list[TextSpan] = Field(default_factory=list)

    def bbox_for_span(self, start: int, end: int) -> BoundingBox:
        """Compute the bounding box covering a character range of ``text``.

        Character offsets are aligned to ``text`` by *locating* each
        span's word in it (robust to whatever separator joined the
        words — a blind cumulative walk drifts by one character per
        separator). Words only partially covered by ``[start, end)``
        are clipped horizontally in proportion to the covered
        characters, so a sub-word range gets a sub-word box.

        Args:
            start: Character offset (0-based) of the start of the range.
            end: Character offset (0-based) of the end of the range
                (exclusive).

        Returns:
            The union ``BoundingBox`` of the covered (parts of) words,
            or the block-level ``self.bbox`` if no spans overlap.
        """
        if not self.spans:
            return self.bbox

        pos = 0
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        found = False

        for span in self.spans:
            if not span.text:
                continue
            offset = self.text.find(span.text, pos)
            if offset < 0:
                offset = pos
            pos = offset + len(span.text)
            overlap_start = max(start, offset)
            overlap_end = min(end, offset + len(span.text))
            if overlap_start >= overlap_end:
                continue
            found = True
            width = span.bbox.x1 - span.bbox.x0
            frac_start = (overlap_start - offset) / len(span.text)
            frac_end = (overlap_end - offset) / len(span.text)
            x0 = min(x0, span.bbox.x0 + frac_start * width)
            x1 = max(x1, span.bbox.x0 + frac_end * width)
            y0 = min(y0, span.bbox.y0)
            y1 = max(y1, span.bbox.y1)

        if not found:
            return self.bbox
        return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


class ImageBlock(Block):
    """A block containing image data with an optional MIME type."""

    model_config = ConfigDict(frozen=True)

    block_type: Literal[BlockType.IMAGE] = BlockType.IMAGE
    image_data: bytes | None = None
    mime_type: str | None = None


class TableBlock(Block):
    """A block representing tabular content as a list of string rows."""

    model_config = ConfigDict(frozen=True)

    block_type: Literal[BlockType.TABLE] = BlockType.TABLE
    rows: list[list[str]] = []
