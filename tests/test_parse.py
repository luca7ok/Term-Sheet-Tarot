from tarot.ingest.parse import Store, find_headings, parse_and_store, parse_file
from tarot.schemas import DocumentSource

HTML = (
    "<html><style>p{}</style><body><p>Smith &amp; Co &#8220;Inc&#8221;</p>"
    "<p>Section 1.5   Liquidation. The holders</p><p>pursuant to</p>"
    "<p>Section 4.2 hereof the board.</p></body></html>"
)


def test_html_unescape_and_headings(tmp_path):
    f = tmp_path / "a.htm"
    f.write_text(HTML)
    parsed = parse_file(f, "d1", DocumentSource.SYNTHETIC)
    assert "Smith & Co “Inc”" in parsed.text
    assert "p{}" not in parsed.text
    assert [h.title for h in parsed.headings] == ["Section 1.5 Liquidation."]
    assert parsed.headings[0].level == 2


def test_heading_levels_and_cross_reference_rejected():
    text = "ARTICLE IV\n4.2.1 Voting Rights. x\nSection 4.2 hereof applies\n1. Dividends. y"
    assert [(h.level, h.title) for h in find_headings(text)] == [
        (1, "ARTICLE IV"),
        (3, "4.2.1 Voting Rights."),
        (2, "1. Dividends."),
    ]


def test_store_skips_unchanged_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("Section 1.1 Dividends. text")
    store = Store(tmp_path / "t.db")
    first, skipped = parse_and_store(store, f, "d1", DocumentSource.SYNTHETIC)
    again, skipped_again = parse_and_store(store, f, "d1", DocumentSource.SYNTHETIC)
    assert (skipped, skipped_again) == (False, True)
    assert again == first
    f.write_text("Section 1.1 Dividends. changed")
    assert parse_and_store(store, f, "d1", DocumentSource.SYNTHETIC)[1] is False


def test_store_reparses_after_parser_change(tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("Section 1.1 Dividends. text")
    store = Store(tmp_path / "t.db")
    parse_and_store(store, f, "d1", DocumentSource.SYNTHETIC)
    monkeypatch.setattr("tarot.ingest.parse.PARSER_VERSION", "next")
    assert parse_and_store(store, f, "d1", DocumentSource.SYNTHETIC)[1] is False


def test_cp1252_bytes_decode(tmp_path):
    f = tmp_path / "old.txt"
    f.write_bytes("Section 1.1 Dividends. the “Holder”".encode("cp1252"))
    assert "“Holder”" in parse_file(f, "d1", DocumentSource.SYNTHETIC).text


def test_adjacent_html_cells_are_separated(tmp_path):
    path = tmp_path / "table.html"
    path.write_text(
        "<table><tr><th>Series</th><th>Amount</th></tr><tr><td>A</td><td>1x</td></tr></table>"
    )
    parsed = parse_file(path, "d", DocumentSource.UPLOAD)
    assert parsed.text.split() == ["Series", "Amount", "A", "1x"]
