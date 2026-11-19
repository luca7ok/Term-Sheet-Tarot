import hashlib

import anyio
from mcp.client.client import Client
from qdrant_client import QdrantClient

from tarot.ingest.parse import Store
from tarot.mcp_server.server import Deps, build_server
from tarot.schemas import ChunkingVariant

TEXT = (
    "ARTICLE IV\nSection 4.1 Liquidation. The holders receive the preference.\n\n"
    "Section 4.2 Voting. Each share has one vote on every matter.\n"
)
RATCHET = {
    "clause_type": "anti_dilution",
    "method": "full_ratchet",
    "pay_to_play": False,
}


def embed(texts):
    return [list(hashlib.sha256(t.encode()).digest()[:8]) for t in texts]


def session(tmp_path, body):
    deps = Deps(
        Store(tmp_path / "t.db"),
        QdrantClient(":memory:"),
        embed,
        lambda s: len(s.split()),
        ChunkingVariant.C2,
        tmp_path,
    )

    async def run():
        async with Client(build_server(lambda: deps)) as client:
            return await body(client)

    return anyio.run(run)


def test_tools_listed(tmp_path):
    async def body(client):
        assert {t.name for t in (await client.list_tools()).tools} == {
            "ingest_document",
            "search_document",
            "query_graph",
        }

    session(tmp_path, body)


def test_ingest_then_search_is_isolated_and_idempotent(tmp_path):
    async def body(client):
        for name in ("a", "b"):
            (tmp_path / f"{name}.txt").write_text(TEXT.replace("one vote", f"one vote in {name}"))
        first = await client.call_tool("ingest_document", {"path": str(tmp_path / "a.txt")})
        assert first.structured_content["embedded"] == first.structured_content["chunks"] > 0
        again = await client.call_tool("ingest_document", {"path": str(tmp_path / "a.txt")})
        assert again.structured_content["embedded"] == 0
        assert again.structured_content["skipped"] == first.structured_content["chunks"]
        await client.call_tool(
            "ingest_document", {"path": str(tmp_path / "b.txt"), "document_id": "b"}
        )
        doc_id = first.structured_content["document_id"]
        assert doc_id.startswith("upload-")
        res = await client.call_tool("search_document", {"document_id": doc_id, "query": "voting"})
        assert res.structured_content["hits"]
        assert {h["text"] for h in res.structured_content["hits"]} >= {
            "Section 4.2 Voting. Each share has one vote in a on every matter."
        }
        assert not any("in b" in h["text"] for h in res.structured_content["hits"])

    session(tmp_path, body)


def test_ingest_rejects_bad_path(tmp_path):
    async def body(client):
        (tmp_path / "x.pdf").write_text("x")
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("Section 1.1 Dividends. secret")
        for p in (
            tmp_path / "missing.txt",
            tmp_path / "x.pdf",
            outside,
            tmp_path / "../outside.txt",
        ):
            res = await client.call_tool("ingest_document", {"path": str(p)})
            assert res.is_error

    session(tmp_path, body)


def test_query_graph_matches_full_ratchet(tmp_path):
    async def body(client):
        res = await client.call_tool("query_graph", {"clauses": [RATCHET]})
        assert [p["id"] for p in res.structured_content["patterns"]] == [
            "full_ratchet_no_pay_to_play"
        ]
        assert "anti_dilution" in res.structured_content["expansions"]

    session(tmp_path, body)


def test_query_graph_rejects_invalid_clause(tmp_path):
    async def body(client):
        res = await client.call_tool("query_graph", {"clauses": [{"clause_type": "nope"}]})
        assert res.is_error

    session(tmp_path, body)
