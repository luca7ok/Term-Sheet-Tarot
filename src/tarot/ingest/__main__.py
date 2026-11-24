import argparse
import csv
import os
import time
from pathlib import Path

from qdrant_client import QdrantClient, models

from tarot.ingest.chunk import chunk, qwen_token_counter
from tarot.ingest.index import EMBEDDING_MODEL, index_chunks, qwen_embedder
from tarot.ingest.parse import DB_PATH, PARSER_VERSION, Store, parse_and_store
from tarot.schemas import ChunkingVariant, ComponentVersion, DocumentSource, EdgarMetadata, Manifest

MANIFEST_DIR = Path("data/manifests")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m tarot.ingest")
    p.add_argument("raw_dir", type=Path)
    p.add_argument("--variants", nargs="+", default=["c0", "c1", "c2"])
    where = p.add_mutually_exclusive_group()
    where.add_argument("--qdrant-url", default="http://localhost:6333")
    where.add_argument("--qdrant-path")
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--limit", type=int)
    p.add_argument("--allow-cpu", action="store_true")
    args = p.parse_args()

    with (args.raw_dir / "index.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))[: args.limit]
    edgar = {
        r["document_id"]: EdgarMetadata(**{k: r[k] for k in EdgarMetadata.model_fields})
        for r in rows
    }
    store = Store(args.db)
    docs = [
        parse_and_store(
            store,
            args.raw_dir / r["path"],
            r["document_id"],
            DocumentSource.EDGAR,
            edgar[r["document_id"]],
            kind=r.get("kind") or None,
        )[0]
        for r in rows
    ]
    client = (
        QdrantClient(path=args.qdrant_path) if args.qdrant_path else QdrantClient(args.qdrant_url)
    )
    count_tokens, embed = qwen_token_counter(), qwen_embedder(allow_cpu=args.allow_cpu)
    for v in args.variants:
        start = time.monotonic()
        variant = ChunkingVariant(v)
        chunks = [c for d in docs for c in chunk(d, variant, count_tokens)]
        new = index_chunks(client, chunks, embed, edgar, variant=variant, document_ids=edgar)
        in_index = client.count(
            f"chunks_{variant}",
            models.Filter(
                must=models.FieldCondition(
                    key="document_id", match=models.MatchAny(any=list(edgar))
                )
            ),
            exact=True,
        ).count
        manifest = Manifest.create(
            parser=ComponentVersion(name="stdlib-regex", version=PARSER_VERSION),
            embedding_model=EMBEDDING_MODEL,
            chunking_variant=variant,
            document_ids=list(edgar),
            chunk_count=in_index,
        )
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        path = MANIFEST_DIR / f"{manifest.snapshot_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(manifest.model_dump_json(indent=2))
        os.replace(tmp, path)
        print(
            f"{variant}: new_embeddings={new} total_chunks={in_index} manifest={path}"
            f" elapsed={time.monotonic() - start:.1f}s"
        )


if __name__ == "__main__":
    main()
