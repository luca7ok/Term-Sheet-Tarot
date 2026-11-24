import pytest

from tarot.ingest.chunk import chunk
from tarot.ingest.parse import ParsedDocument, find_headings
from tarot.schemas import ChunkingVariant, Document, DocumentSource, FileType, sha256_hex


def words(text: str) -> int:
    return len(text.split())


def make(text: str) -> ParsedDocument:
    doc = Document(
        document_id="d1",
        source=DocumentSource.SYNTHETIC,
        file_type=FileType.TXT,
        content_hash=sha256_hex(text),
    )
    return ParsedDocument(document=doc, text=text, headings=find_headings(text))


def test_long_section_splits_into_contiguous_chunks():
    text = "ARTICLE IV\nSection 4.1 Liquidation. " + " ".join(f"w{i}" for i in range(1497))
    chunks = chunk(make(text), ChunkingVariant.C1, words)
    body = [c for c in chunks if c.section_path == ("ARTICLE IV", "Section 4.1 Liquidation.")]
    assert len(body) == 3
    assert all(
        not text[a.span.end : b.span.start].strip() for a, b in zip(body, body[1:], strict=False)
    )
    assert all(words(c.text) <= 512 for c in chunks)


def test_c2_header_lists_defined_terms():
    text = (
        'ARTICLE IV\nSection 4.1 Liquidation. The price (the "Original Issue Price") and '
        '"Deemed Liquidation Event" means a sale. The Original Issue Price applies.'
    )
    c = chunk(make(text), ChunkingVariant.C2, words)[-1]
    assert c.header == (
        "Document › ARTICLE IV › Section 4.1 Liquidation"
        ". Uses: Deemed Liquidation Event, Original Issue Price."
    )


def test_c0_covers_text_without_overlap():
    text = "\n\n".join(" ".join(f"w{p}_{i}" for i in range(300)) for p in range(5))
    chunks = chunk(make(text), ChunkingVariant.C0, words)
    assert len(chunks) > 1
    assert all(a.span.end <= b.span.start for a, b in zip(chunks, chunks[1:], strict=False))
    assert " ".join(c.text for c in chunks).split() == text.split()


def test_c3_rejected():
    with pytest.raises(ValueError, match="E1"):
        chunk(make("x"), ChunkingVariant.C3, words)


def test_c1_without_headings_is_one_section():
    assert len(chunk(make("plain text"), ChunkingVariant.C1, words)) == 1


def test_oversized_text_without_separators_preserves_offsets():
    text = "0123456789" * 9
    chunks = chunk(make(text), ChunkingVariant.C0, len, max_tokens=12)
    assert "".join(c.text for c in chunks) == text
    assert all(c.text == text[c.span.start : c.span.end] and len(c.text) <= 12 for c in chunks)


def test_c2_uses_document_kind(tmp_path):
    from tarot.ingest.parse import Store, parse_and_store

    path = tmp_path / "agreement.txt"
    path.write_text("Some terms")
    store = Store(tmp_path / "store.db")
    parse_and_store(store, path, "d", DocumentSource.UPLOAD)
    parsed, skipped = parse_and_store(
        store, path, "d", DocumentSource.UPLOAD, kind="voting_agreement"
    )
    assert not skipped
    assert chunk(parsed, ChunkingVariant.C2, words)[0].header == "Voting Agreement."
    assert store.get("d").document.kind == "voting_agreement"
