import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import ValidationError
from qdrant_client import QdrantClient, models

from tarot.ingest.chunk import chunk, qwen_token_counter
from tarot.ingest.index import Embedder, index_chunks, qwen_embedder
from tarot.ingest.parse import Store, parse_and_store
from tarot.ontology import CLAUSE_ADAPTER, ClauseType, expand, match_patterns
from tarot.schemas import ChunkingVariant, DocumentSource, TarotModel, sha256_hex

QUERY_PREFIX = (
    "Instruct: Given a question about a legal contract, retrieve the clause that answers it\n"
    "Query: "
)
SUFFIXES = {".htm", ".html", ".txt"}


@dataclass
class Deps:
    store: Store
    qdrant: QdrantClient
    embed: Embedder
    count_tokens: Callable[[str], int]
    variant: ChunkingVariant
    upload_dir: Path


def default_deps() -> Deps:
    return Deps(
        Store(Path(os.environ.get("TAROT_DB", "data/tarot.db"))),
        QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333")),
        qwen_embedder(),
        qwen_token_counter(),
        ChunkingVariant(os.environ.get("TAROT_VARIANT", "c2")),
        Path(os.environ.get("TAROT_UPLOAD_DIR", "data/uploads")),
    )


class IngestResult(TarotModel):
    document_id: str
    chunks: int
    embedded: int
    skipped: int


class Hit(TarotModel):
    chunk_id: str
    score: float
    section_path: list[str]
    span_start: int
    span_end: int
    text: str


class SearchResult(TarotModel):
    document_id: str
    hits: list[Hit]


class PatternHit(TarotModel):
    id: str
    description: str
    reads: list[ClauseType]


class GraphResult(TarotModel):
    patterns: list[PatternHit]
    expansions: dict[ClauseType, list[ClauseType]]


def build_server(deps_factory: Callable[[], Deps] = default_deps) -> MCPServer:
    deps = cache(deps_factory)  # lazy: query_graph never loads torch
    # shortcut: async tools keep sqlite on one thread but block the loop while embedding
    mcp = MCPServer("term-sheet-tarot")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def ingest_document(path: str, document_id: str | None = None) -> IngestResult:
        """Parse, chunk, embed and index one .htm/.html/.txt file."""
        d = deps()
        p = Path(path).resolve()
        # the server must not read arbitrary files on its host, only what was uploaded
        if not p.is_relative_to(d.upload_dir.resolve()):
            raise ValueError(f"{path}: outside the upload directory {d.upload_dir}")
        if not p.is_file() or p.suffix.lower() not in SUFFIXES:
            raise ValueError(f"{path}: not an existing .htm/.html/.txt file")
        document_id = document_id or f"upload-{sha256_hex(p.read_bytes())[:12]}"
        parsed, _ = parse_and_store(d.store, p, document_id, DocumentSource.UPLOAD)
        chunks = chunk(parsed, d.variant, d.count_tokens)
        embedded = index_chunks(d.qdrant, chunks, d.embed, {})
        return IngestResult(
            document_id=document_id,
            chunks=len(chunks),
            embedded=embedded,
            skipped=len(chunks) - embedded,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def search_document(document_id: str, query: str, k: int = 5) -> SearchResult:
        """Dense search within one document."""
        d = deps()
        found = d.qdrant.query_points(
            f"chunks_{d.variant}",
            query=d.embed([QUERY_PREFIX + query])[0],
            using="dense",
            query_filter=models.Filter(
                must=models.FieldCondition(
                    key="document_id", match=models.MatchValue(value=document_id)
                )
            ),
            limit=k,
        )
        return SearchResult(
            document_id=document_id,
            hits=[
                Hit(
                    chunk_id=str(h.id),
                    score=h.score,
                    **{f: h.payload[f] for f in Hit.model_fields.keys() - {"chunk_id", "score"}},
                )
                for h in found.points
            ],
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def query_graph(clauses: list[dict]) -> GraphResult:
        """Match risk patterns and expansion edges for extracted clauses."""
        try:
            parsed = [CLAUSE_ADAPTER.validate_python(c) for c in clauses]
        except ValidationError as e:
            raise ValueError(f"invalid clause: {e}") from e
        return GraphResult(
            patterns=[
                PatternHit(id=p.id, description=p.description, reads=list(p.reads))
                for p in match_patterns(parsed)
            ],
            expansions={t: sorted(expand(t)) for t in sorted({c.clause_type for c in parsed})},
        )

    return mcp
