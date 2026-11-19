import json
import re
import sqlite3
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Self

from pydantic import model_validator

from tarot.schemas import (
    Document,
    DocumentSource,
    EdgarMetadata,
    FileType,
    Span,
    TarotModel,
    sha256_hex,
)

DB_PATH = Path("data/tarot.db")
PARSER_VERSION = "stdlib-regex-1"  # bump when parsing output changes, forces a re-parse
BLOCK_TAGS = {"p", "div", "br", "tr", "li", "table", "center", "h1", "h2", "h3", "h4", "h5", "h6"}
# Article lines carry only a number (title may follow on the next line); sections need a
# capitalised title and a full stop so "pursuant to Section 4.2 hereof" does not match.
HEADING_RE = re.compile(
    r"^[ \t]*(?:(?P<art>(?:ARTICLE|Article)[ \t]+(?:[IVXLC]+|\d+)\b[.:]?"
    r"(?:[ \t]+[A-Z][^\n]{0,80})?)[ \t]*$"
    r"|(?P<sec>(?:(?:SECTION|Section)[ \t]+)?(?P<num>\d+(?:\.\d+)*)\.?[ \t]+[A-Z][^.\n]{0,80}\.))",
    re.M,
)


class Heading(TarotModel):
    level: int
    title: str
    span: Span


class ParsedDocument(TarotModel):
    document: Document
    text: str
    headings: tuple[Heading, ...] = ()

    @model_validator(mode="after")
    def _headings_inside_text(self) -> Self:
        for h in self.headings:
            if h.span.end > len(self.text) or h.title not in self.text[h.span.start : h.span.end]:
                raise ValueError(f"heading {h.title!r} not found at its span")
        return self


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _normalize(text: str) -> str:
    lines = (re.sub(r"[ \t\xa0\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def find_headings(text: str) -> tuple[Heading, ...]:
    out = []
    for m in HEADING_RE.finditer(text):
        title = m.group(0).strip()
        level = 1 if m["art"] else 2 if m["num"].count(".") < 2 else 3
        start = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
        out.append(Heading(level=level, title=title, span=Span(start=start, end=m.end())))
    return tuple(out)


def parse_file(
    path: Path, document_id: str, source: DocumentSource, edgar: EdgarMetadata | None = None
) -> ParsedDocument:
    raw = Path(path).read_bytes()
    html = Path(path).suffix.lower() in (".htm", ".html")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:  # pre-2010 EDGAR filings are often Windows-1252
        text = raw.decode("cp1252", errors="replace")
    if html:
        stripper = _Stripper()
        stripper.feed(text)
        text = unescape("".join(stripper.parts))
    text = _normalize(text)
    doc = Document(
        document_id=document_id,
        source=source,
        file_type=FileType.HTML if html else FileType.TXT,
        content_hash=sha256_hex(raw),
        edgar=edgar,
    )
    return ParsedDocument(document=doc, text=text, headings=find_headings(text))


class Store:
    def __init__(self, path: Path = DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS documents (document_id TEXT PRIMARY KEY, content_hash TEXT,"
            " parser_version TEXT, document_json TEXT, text TEXT, headings_json TEXT)"
        )

    def get(self, document_id: str) -> ParsedDocument | None:
        row = self.db.execute(
            "SELECT document_json, text, headings_json FROM documents"
            " WHERE document_id = ? AND parser_version = ?",
            (document_id, PARSER_VERSION),
        ).fetchone()
        if row is None:
            return None
        return ParsedDocument(
            document=Document.model_validate_json(row[0]),
            text=row[1],
            headings=tuple(Heading.model_validate(h) for h in json.loads(row[2])),
        )

    def put(self, parsed: ParsedDocument) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?, ?)",
                (
                    parsed.document.document_id,
                    parsed.document.content_hash,
                    PARSER_VERSION,
                    parsed.document.model_dump_json(),
                    parsed.text,
                    json.dumps([h.model_dump() for h in parsed.headings]),
                ),
            )


def parse_and_store(
    store: Store,
    path: Path,
    document_id: str,
    source: DocumentSource,
    edgar: EdgarMetadata | None = None,
) -> tuple[ParsedDocument, bool]:
    """Returns (parsed, skipped)."""
    cached = store.get(document_id)
    if cached and cached.document.content_hash == sha256_hex(Path(path).read_bytes()):
        return cached, True
    parsed = parse_file(path, document_id, source, edgar)
    store.put(parsed)
    return parsed, False
