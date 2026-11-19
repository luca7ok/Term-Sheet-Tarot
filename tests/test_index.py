import hashlib

from qdrant_client import QdrantClient, models

from tarot.ingest.chunk import chunk
from tarot.ingest.index import index_chunks
from tarot.ingest.parse import parse_file
from tarot.schemas import ChunkingVariant, DocumentSource

TEXT = (
    "ARTICLE IV\nSection 4.1 Liquidation. The holders receive the preference.\n\n"
    "Section 4.2 Voting. Each share has one vote on every matter.\n"
)


class FakeEmbedder:
    def __init__(self):
        self.texts: list[str] = []

    def __call__(self, texts):
        self.texts += texts
        return [list(hashlib.sha256(t.encode()).digest()[:8]) for t in texts]


def chunks_for(tmp_path, doc_id, variant):
    path = tmp_path / f"{doc_id}.txt"
    path.write_text(TEXT.replace("one vote", f"one vote in {doc_id}"))
    return chunk(parse_file(path, doc_id, DocumentSource.UPLOAD), variant, lambda s: len(s.split()))


def test_rerun_embeds_nothing_and_filter_isolates_document(tmp_path):
    client, embed = QdrantClient(":memory:"), FakeEmbedder()
    chunks = chunks_for(tmp_path, "a", ChunkingVariant.C1) + chunks_for(
        tmp_path, "b", ChunkingVariant.C1
    )
    assert index_chunks(client, chunks, embed, {}) == len(chunks) > 0
    assert index_chunks(client, chunks, embed, {}) == 0
    assert len(embed.texts) == len(chunks)
    assert client.count("chunks_c1").count == len(chunks)
    hits, _ = client.scroll(
        "chunks_c1",
        models.Filter(
            must=models.FieldCondition(key="document_id", match=models.MatchValue(value="a"))
        ),
        limit=100,
    )
    assert {h.payload["document_id"] for h in hits} == {"a"}
    assert len(hits) == len(chunks_for(tmp_path, "a", ChunkingVariant.C1))


def test_c2_embeds_header_with_text(tmp_path):
    embed = FakeEmbedder()
    chunks = chunks_for(tmp_path, "a", ChunkingVariant.C2)
    index_chunks(QdrantClient(":memory:"), chunks, embed, {})
    assert embed.texts == [f"{c.header}\n\n{c.text}" for c in chunks]
    assert all(c.header for c in chunks)
