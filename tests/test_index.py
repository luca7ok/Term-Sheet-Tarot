import hashlib
import subprocess
import sys

import pytest
from qdrant_client import QdrantClient, models

from tarot.ingest.chunk import chunk
from tarot.ingest.index import index_chunks
from tarot.ingest.parse import parse_file
from tarot.schemas import ChunkingVariant, ComponentVersion, DocumentSource

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


def test_reembeds_same_id_on_header_or_model_revision_change(tmp_path):
    client, embed = QdrantClient(":memory:"), FakeEmbedder()
    original = chunks_for(tmp_path, "a", ChunkingVariant.C2)[0]
    updated = original.model_copy(update={"header": "Voting Agreement."})
    assert index_chunks(client, [original], embed, {}) == 1
    assert index_chunks(client, [updated], embed, {}) == 1
    assert embed.texts[-1] == f"Voting Agreement.\n\n{original.text}"
    model = ComponentVersion(name="test", version="revision-2")
    assert index_chunks(client, [updated], embed, {}, embedding_model=model) == 1
    assert index_chunks(client, [updated], embed, {}, embedding_model=model) == 0
    assert client.count("chunks_c2").count == 1


def test_failed_replacement_keeps_old_points_until_retry(tmp_path, monkeypatch):
    client, embed = QdrantClient(":memory:"), FakeEmbedder()
    variant = ChunkingVariant.C1
    a = chunks_for(tmp_path, "a", variant)
    b = chunks_for(tmp_path, "b", variant)
    index_chunks(client, a + b, embed, {})
    (tmp_path / "a.txt").write_text("ARTICLE II\nSection 2.1 New. Brand new terms.")
    updated = chunk(
        parse_file(tmp_path / "a.txt", "a", DocumentSource.UPLOAD),
        variant,
        lambda s: len(s.split()),
    )
    assert len(updated) == 2
    monkeypatch.setattr("tarot.ingest.index.SLICE", 1)

    def ids():
        points, _ = client.scroll("chunks_c1", limit=100)
        return {str(p.id) for p in points}

    def chunk_ids(chunks):
        return {str(c.chunk_id) for c in chunks}

    upsert = client.upsert

    def fail_second_write(name, points, **kwargs):
        if str(points[0].id) == str(updated[1].chunk_id):
            return models.UpdateResult(status=models.UpdateStatus.ACKNOWLEDGED)
        return upsert(name, points, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(client, "upsert", fail_second_write)
        with pytest.raises(RuntimeError, match="replacement upsert did not complete"):
            index_chunks(client, updated, embed, {})
    assert ids() == chunk_ids(a + b + updated[:1])
    assert index_chunks(client, updated, embed, {}) == 1
    assert ids() == chunk_ids(updated + b)
    assert index_chunks(client, [], embed, {}, variant=variant, document_ids=["a"]) == 0
    assert ids() == chunk_ids(b)


def test_reindex_holds_process_lock_during_snapshot_and_mutations(tmp_path, monkeypatch):
    lock_dir = tmp_path / "locks"
    monkeypatch.setenv("TAROT_INDEX_LOCK_DIR", str(lock_dir))
    client, embed = QdrantClient(":memory:"), FakeEmbedder()
    variant = ChunkingVariant.C1
    index_chunks(client, chunks_for(tmp_path, "a", variant), embed, {})
    lock_path = lock_dir / "chunks_c1.lock"
    probe = """
import fcntl
import sys
with open(sys.argv[1], "a") as file:
    try:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(1)
"""
    observed = []

    def check_lock(operation):
        def wrap(*args, **kwargs):
            assert (
                subprocess.run(
                    [sys.executable, "-c", probe, str(lock_path)], check=False
                ).returncode
                == 1
            )
            observed.append(operation.__name__)
            return operation(*args, **kwargs)

        return wrap

    for method in ("scroll", "upsert", "delete"):
        monkeypatch.setattr(client, method, check_lock(getattr(client, method)))

    path = tmp_path / "changed.txt"
    path.write_text("New terms")
    updated = chunk(parse_file(path, "a", DocumentSource.UPLOAD), variant, lambda s: len(s.split()))
    assert index_chunks(client, updated, embed, {}) == 1
    assert observed == ["scroll", "upsert", "delete"]
    assert (
        subprocess.run([sys.executable, "-c", probe, str(lock_path)], check=False).returncode == 0
    )
