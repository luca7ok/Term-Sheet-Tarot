from datetime import UTC, datetime
from typing import Self

from pydantic import AwareDatetime, NonNegativeInt, field_validator

from tarot.schemas.base import TarotModel, sha256_hex
from tarot.schemas.chunk import ChunkingVariant


class ComponentVersion(TarotModel):
    name: str
    version: str


class Manifest(TarotModel):
    snapshot_id: str
    created_at: AwareDatetime
    parser: ComponentVersion
    embedding_model: ComponentVersion
    chunking_variant: ChunkingVariant
    document_ids: tuple[str, ...]
    chunk_count: NonNegativeInt

    @field_validator("document_ids")
    @classmethod
    def _sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @classmethod
    def create(
        cls,
        *,
        parser: ComponentVersion,
        embedding_model: ComponentVersion,
        chunking_variant: ChunkingVariant,
        document_ids: tuple[str, ...] | list[str],
        chunk_count: int,
        created_at: datetime | None = None,
    ) -> Self:
        created_at = created_at or datetime.now(UTC)
        ids = sorted(set(document_ids))
        fingerprint = "|".join(
            [
                f"{parser.name}={parser.version}",
                f"{embedding_model.name}={embedding_model.version}",
                str(chunking_variant),
                str(chunk_count),
                *ids,
            ]
        )
        return cls(
            snapshot_id=f"snap-{created_at:%Y-%m-%d}-{sha256_hex(fingerprint)[:8]}",
            created_at=created_at,
            parser=parser,
            embedding_model=embedding_model,
            chunking_variant=chunking_variant,
            document_ids=tuple(ids),
            chunk_count=chunk_count,
        )
