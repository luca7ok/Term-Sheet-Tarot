from collections.abc import Callable

from qdrant_client import QdrantClient, models

from tarot.schemas import Chunk, ComponentVersion, EdgarMetadata

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


def index_chunks(
    client: QdrantClient,
    chunks: list[Chunk],
    embed: Embedder,
    edgar: dict[str, EdgarMetadata],
) -> int:
    if not chunks:
        return 0
    name = f"chunks_{chunks[0].variant}"
    ids = [str(c.chunk_id) for c in chunks]
    have = (
        {str(p.id) for p in client.retrieve(name, ids, with_payload=False)}
        if (client.collection_exists(name))
        else set()
    )
    new = [c for c in chunks if str(c.chunk_id) not in have]
    for i in range(0, len(new), SLICE):
        batch = new[i : i + SLICE]
        vectors = embed([f"{c.header}\n\n{c.text}" if c.header else c.text for c in batch])
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
        client.upsert(
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
                        **(
                            edgar[c.document_id].model_dump(mode="json")
                            if c.document_id in edgar
                            else {}
                        ),
                    },
                )
                for c, v in zip(batch, vectors, strict=True)
            ],
        )
    return len(new)
