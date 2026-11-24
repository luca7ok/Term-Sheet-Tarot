import json
import os
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from fcntl import LOCK_EX, flock
from pathlib import Path

from qdrant_client import QdrantClient, models

from tarot.schemas import Chunk, ChunkingVariant, ComponentVersion, EdgarMetadata, sha256_hex

Embedder = Callable[[list[str]], list[list[float]]]
MODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_MODEL = ComponentVersion(name=MODEL, version="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3")
SLICE = 64  # upsert every 64 chunks so a crash keeps finished work


def qwen_embedder(batch_size: int = 16, allow_cpu: bool = False) -> Embedder:
    import torch
    from sentence_transformers import SentenceTransformer

    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    elif allow_cpu:
        device = "cpu"
    else:
        raise RuntimeError("no MPS or CUDA device, CPU is ~30x slower, pass allow_cpu=True")
    model = SentenceTransformer(MODEL, device=device, revision=EMBEDDING_MODEL.version)
    return lambda texts: model.encode(
        texts, batch_size=batch_size, normalize_embeddings=True
    ).tolist()


def _existing(client: QdrantClient, name: str, documents: set[str]) -> dict[str, str | None]:
    if not client.collection_exists(name):
        return {}
    scope = models.Filter(
        must=[
            models.FieldCondition(key="document_id", match=models.MatchAny(any=sorted(documents)))
        ]
    )
    have = {}
    offset = None
    while True:
        points, offset = client.scroll(
            name, scope, offset=offset, limit=256, with_payload=["embedding_fingerprint"]
        )
        have.update({str(p.id): (p.payload or {}).get("embedding_fingerprint") for p in points})
        if offset is None:
            return have


@contextmanager
def _collection_write_lock(name: str) -> Iterator[None]:
    lock_dir = Path(
        os.environ.get("TAROT_INDEX_LOCK_DIR", Path.home() / ".cache/tarot/index-locks")
    )
    lock_dir.mkdir(parents=True, exist_ok=True)
    # Keep the file in place so a waiter and a new writer always lock the same inode.
    with (lock_dir / f"{name}.lock").open("a") as lock_file:
        flock(lock_file, LOCK_EX)
        yield


def index_chunks(
    client: QdrantClient,
    chunks: list[Chunk],
    embed: Embedder,
    edgar: dict[str, EdgarMetadata],
    *,
    variant: ChunkingVariant | None = None,
    document_ids: Iterable[str] = (),
    embedding_model: ComponentVersion | None = None,
) -> int:
    """Index a complete chunk set for each supplied document, in one variant.

    Pass document_ids and variant to also reconcile documents that produced no chunks.
    All processes writing to the collection must share the same TAROT_INDEX_LOCK_DIR.
    """
    if chunks and variant is None:
        variant = chunks[0].variant
    documents = set(document_ids) | {c.document_id for c in chunks}
    if not documents:
        return 0
    if variant is None or any(c.variant != variant for c in chunks):
        raise ValueError("index_chunks requires one chunking variant")
    name = f"chunks_{variant}"
    model = EMBEDDING_MODEL if embedding_model is None else embedding_model
    with _collection_write_lock(name):
        return _index_locked(client, name, documents, chunks, embed, edgar, model)


def _index_locked(
    client: QdrantClient,
    name: str,
    documents: set[str],
    chunks: list[Chunk],
    embed: Embedder,
    edgar: dict[str, EdgarMetadata],
    model: ComponentVersion,
) -> int:
    have = _existing(client, name, documents)
    new = []
    current_ids = set()
    for c in chunks:
        point_id = str(c.chunk_id)
        current_ids.add(point_id)
        body = f"{c.header}\n\n{c.text}" if c.header else c.text
        fingerprint = sha256_hex(json.dumps([model.name, model.version, body]))
        if have.get(point_id) != fingerprint:
            new.append((c, body, fingerprint))
    for i in range(0, len(new), SLICE):
        batch = new[i : i + SLICE]
        vectors = embed([body for _, body, _ in batch])
        if not client.collection_exists(name):
            client.create_collection(
                name,
                vectors_config={
                    "dense": models.VectorParams(
                        size=len(vectors[0]), distance=models.Distance.COSINE
                    )
                },
            )
            client.create_payload_index(name, "document_id", models.PayloadSchemaType.KEYWORD)
        result = client.upsert(
            name,
            [
                models.PointStruct(
                    id=str(c.chunk_id),
                    vector={"dense": v},
                    payload={
                        "document_id": c.document_id,
                        "variant": str(c.variant),
                        "section_path": list(c.section_path),
                        "span_start": c.span.start,
                        "span_end": c.span.end,
                        "content_hash": c.content_hash,
                        "text": c.text,
                        "header": c.header,
                        "embedding_fingerprint": fingerprint,
                        **(
                            edgar[c.document_id].model_dump(mode="json")
                            if c.document_id in edgar
                            else {}
                        ),
                    },
                )
                for (c, _, fingerprint), v in zip(batch, vectors, strict=True)
            ],
            wait=True,
        )
        if result.status != models.UpdateStatus.COMPLETED:
            raise RuntimeError(f"{name}: replacement upsert did not complete ({result.status})")

    # Keep old points until every replacement batch has been written successfully.
    obsolete = sorted(have.keys() - current_ids)
    for i in range(0, len(obsolete), SLICE):
        result = client.delete(name, models.PointIdsList(points=obsolete[i : i + SLICE]), wait=True)
        if result.status != models.UpdateStatus.COMPLETED:
            raise RuntimeError(
                f"{name}: obsolete point deletion did not complete ({result.status})"
            )
    return len(new)
