import uuid
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from tarot.schemas.base import TarotModel, sha256_hex
from tarot.schemas.span import Span

CHUNK_NAMESPACE = uuid.UUID("5f0c1d2e-8a4b-4c6d-9e7f-0a1b2c3d4e5f")


class ChunkingVariant(StrEnum):
    C0 = "c0"
    C1 = "c1"
    C2 = "c2"
    C3 = "c3"
    C4 = "c4"


class Chunk(TarotModel):
    chunk_id: uuid.UUID
    document_id: str
    variant: ChunkingVariant
    span: Span
    section_path: tuple[str, ...] = ()
    text: str
    header: str = ""
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        document_id: str,
        variant: ChunkingVariant,
        span: Span,
        text: str,
        section_path: tuple[str, ...] = (),
        header: str = "",
    ) -> Self:
        content_hash = sha256_hex(text)
        key = f"{document_id}:{variant}:{span.start}:{span.end}:{content_hash}"
        return cls(
            chunk_id=uuid.uuid5(CHUNK_NAMESPACE, key),
            document_id=document_id,
            variant=variant,
            span=span,
            section_path=section_path,
            text=text,
            header=header,
            content_hash=content_hash,
        )

    @model_validator(mode="after")
    def _text_matches_span_and_hash(self) -> Self:
        if len(self.text) != len(self.span):
            raise ValueError(
                f"text length ({len(self.text)}) does not match span length ({len(self.span)})"
            )
        if sha256_hex(self.text) != self.content_hash:
            raise ValueError("content_hash does not match text")
        return self
