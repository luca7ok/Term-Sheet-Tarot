from typing import Self

from pydantic import NonNegativeInt, model_validator

from tarot.schemas.base import TarotModel


class Span(TarotModel):
    start: NonNegativeInt
    end: NonNegativeInt

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError(f"span end ({self.end}) must be greater than start ({self.start})")
        return self

    def __len__(self) -> int:
        return self.end - self.start
