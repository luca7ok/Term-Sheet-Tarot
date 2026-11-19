from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from tarot.schemas import (
    Chunk,
    ChunkingVariant,
    ComponentVersion,
    Document,
    DocumentSource,
    EdgarMetadata,
    FileType,
    Manifest,
    Span,
    sha256_hex,
)

EDGAR = EdgarMetadata(
    cik="0001234567",
    accession_number="0001234567-19-000123",
    company_name="Example Inc.",
    form_type="S-1",
    filing_date=date(2019, 3, 1),
    exhibit="3.1",
)

PARSER = ComponentVersion(name="docling", version="2.0.0")
EMBEDDER = ComponentVersion(name="Qwen3-Embedding-0.6B", version="1")


def make_chunk(text="1x non-participating", start=100, variant=ChunkingVariant.C2):
    return Chunk.create(
        document_id="edgar-0001234567-exh3-1",
        variant=variant,
        span=Span(start=start, end=start + len(text)),
        text=text,
        section_path=("Article IV", "B.2 Liquidation Preference"),
        header="Certificate of Incorporation > Article IV > B.2 Liquidation Preference",
    )


class TestSpan:
    def test_length(self):
        assert len(Span(start=10, end=25)) == 15

    @pytest.mark.parametrize(("start", "end"), [(5, 5), (10, 3), (-1, 4)])
    def test_rejects_invalid(self, start, end):
        with pytest.raises(ValidationError):
            Span(start=start, end=end)


class TestDocument:
    def test_edgar_document(self):
        doc = Document(
            document_id="edgar-0001234567-exh3-1",
            source=DocumentSource.EDGAR,
            file_type=FileType.HTML,
            content_hash=sha256_hex(b"<html></html>"),
            edgar=EDGAR,
        )
        assert doc.edgar.exhibit == "3.1"

    def test_edgar_source_requires_metadata(self):
        with pytest.raises(ValidationError, match="edgar metadata"):
            Document(
                document_id="edgar-x",
                source=DocumentSource.EDGAR,
                file_type=FileType.HTML,
                content_hash=sha256_hex(b"x"),
            )

    def test_metadata_only_for_edgar(self):
        with pytest.raises(ValidationError, match="edgar metadata"):
            Document(
                document_id="upload-x",
                source=DocumentSource.UPLOAD,
                file_type=FileType.PDF,
                content_hash=sha256_hex(b"x"),
                edgar=EDGAR,
            )

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            Document(
                document_id="upload-x",
                source=DocumentSource.UPLOAD,
                file_type=FileType.PDF,
                content_hash=sha256_hex(b"x"),
                pages=3,
            )


class TestChunk:
    def test_id_is_deterministic(self):
        assert make_chunk().chunk_id == make_chunk().chunk_id

    def test_id_differs_by_variant_and_position(self):
        base = make_chunk()
        assert base.chunk_id != make_chunk(variant=ChunkingVariant.C0).chunk_id
        assert base.chunk_id != make_chunk(start=200).chunk_id
        assert base.chunk_id != make_chunk(text="2x participating   ").chunk_id

    def test_text_must_match_span_length(self):
        with pytest.raises(ValidationError, match="span length"):
            Chunk.create(
                document_id="d",
                variant=ChunkingVariant.C0,
                span=Span(start=0, end=3),
                text="four",
            )

    def test_hash_must_match_text(self):
        chunk = make_chunk()
        data = chunk.model_dump() | {"content_hash": sha256_hex("other")}
        with pytest.raises(ValidationError, match="content_hash"):
            Chunk.model_validate(data)

    def test_json_round_trip(self):
        chunk = make_chunk()
        assert Chunk.model_validate_json(chunk.model_dump_json()) == chunk

    def test_is_immutable(self):
        with pytest.raises(ValidationError):
            make_chunk().text = "changed"


class TestManifest:
    def create(self, document_ids, created_at=datetime(2026, 11, 20, tzinfo=UTC), **overrides):
        args = dict(
            parser=PARSER,
            embedding_model=EMBEDDER,
            chunking_variant=ChunkingVariant.C2,
            document_ids=document_ids,
            chunk_count=42,
            created_at=created_at,
        )
        return Manifest.create(**(args | overrides))

    def test_snapshot_id_format(self):
        assert self.create(["a", "b"]).snapshot_id.startswith("snap-2026-11-20-")

    def test_snapshot_id_ignores_document_order_and_duplicates(self):
        assert self.create(["b", "a"]).snapshot_id == self.create(["a", "b", "a"]).snapshot_id

    def test_snapshot_id_changes_with_embedding_model(self):
        other = ComponentVersion(name="BGE-M3", version="1")
        assert (
            self.create(["a"]).snapshot_id != self.create(["a"], embedding_model=other).snapshot_id
        )

    def test_requires_timezone(self):
        with pytest.raises(ValidationError):
            self.create(["a"], created_at=datetime(2026, 11, 20))

    def test_json_round_trip(self):
        manifest = self.create(["a", "b"])
        assert Manifest.model_validate_json(manifest.model_dump_json()) == manifest
