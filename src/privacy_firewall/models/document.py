"""``Document`` and ``Page``: the parsed structure every pipeline stage exchanges."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from privacy_firewall.models.blocks import Block


class Page(BaseModel):
    """A single page within a processed document.

    Stores the page dimensions, number, and the list of content blocks
    identified on that page.
    """

    model_config = ConfigDict(frozen=True)

    page_number: int
    width: float
    height: float
    blocks: list[Block] = []

    @field_validator("page_number")
    @classmethod
    def page_number_must_be_positive(cls, v: int) -> int:
        """Validate that page_number is >= 1."""
        if v < 1:
            msg = "page_number must be >= 1"
            raise ValueError(msg)
        return v

    @field_validator("width")
    @classmethod
    def width_must_be_positive(cls, v: float) -> float:
        """Validate that width is strictly positive."""
        if v <= 0:
            msg = "width must be positive"
            raise ValueError(msg)
        return v

    @field_validator("height")
    @classmethod
    def height_must_be_positive(cls, v: float) -> float:
        """Validate that height is strictly positive."""
        if v <= 0:
            msg = "height must be positive"
            raise ValueError(msg)
        return v


class Document(BaseModel):
    """A processed document consisting of an ordered list of pages."""

    model_config = ConfigDict(frozen=True)

    pages: list[Page] = []
