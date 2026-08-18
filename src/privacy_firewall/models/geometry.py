"""Geometry primitives -- ``BoundingBox`` and ``Span`` in top-left coordinate space."""

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


class BoundingBox(BaseModel):
    """An axis-aligned bounding box defined by two corner coordinates.

    The box spans from (x0, y0) to (x1, y1), where x1 > x0 and y1 > y0.
    """

    model_config = ConfigDict(frozen=True)

    x0: float
    y0: float
    x1: float
    y1: float

    @field_validator("x1")
    @classmethod
    def x1_must_exceed_x0(cls, v: float, info: ValidationInfo) -> float:
        """Validate that x1 is strictly greater than x0."""
        if "x0" in info.data and v <= info.data["x0"]:
            msg = "x1 must be greater than x0"
            raise ValueError(msg)
        return v

    @field_validator("y1")
    @classmethod
    def y1_must_exceed_y0(cls, v: float, info: ValidationInfo) -> float:
        """Validate that y1 is strictly greater than y0."""
        if "y0" in info.data and v <= info.data["y0"]:
            msg = "y1 must be greater than y0"
            raise ValueError(msg)
        return v


class Span(BaseModel):
    """A character-offset span within a source string.

    The span covers the half-open interval [start, end), where
    end > start and start >= 0.
    """

    model_config = ConfigDict(frozen=True)

    start: int
    end: int

    @field_validator("end")
    @classmethod
    def end_must_exceed_start(cls, v: int, info: ValidationInfo) -> int:
        """Validate that end is strictly greater than start."""
        if "start" in info.data and v <= info.data["start"]:
            msg = "end must be greater than start"
            raise ValueError(msg)
        return v

    @field_validator("start")
    @classmethod
    def start_must_be_non_negative(cls, v: int) -> int:
        """Validate that start is not negative."""
        if v < 0:
            msg = "start must be non-negative"
            raise ValueError(msg)
        return v
