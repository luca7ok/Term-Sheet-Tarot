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
        "Certificate of Incorporation › ARTICLE IV › Section 4.1 Liquidation"
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
