import csv

import httpx
import pytest

from tarot.ingest import crawler

CHARTER = (
    b"<p>EXHIBIT 3.1</p><h1>Amended and Restated Certificate of Incorporation</h1>"
    b"<p>Series A Preferred Stock ... Liquidation Preference ...</p>"
)
VOTING = b"<h1>Voting Agreement</h1><p>Drag-Along. Sale of the Company.</p>"


def make_hit(
    filename="d1ex31.htm", file_type="EX-3.1", adsh="0001193125-15-237610", cik="0001124105"
):
    return {
        "_id": f"{adsh}:{filename}",
        "_source": {
            "ciks": [cik],
            "display_names": ["TARGACEPT INC  (GYRE)  (CIK 0001124105)"],
            "form": "S-1",
            "file_date": "2006-01-17",
            "file_type": file_type,
        },
    }


class FakeClient:
    def __init__(self, hits, contents):
        self.hits = hits
        self.contents = contents

    def search_page(self, query, start):
        first = query in (crawler.QUERIES[0], crawler.VOTING_QUERIES[0])
        return self.hits if start == 0 and first else []

    def download(self, meta, filename):
        return self.contents[filename]


def test_parse_hit():
    meta, filename = crawler.parse_hit(make_hit())
    assert filename == "d1ex31.htm"
    assert meta.company_name == "TARGACEPT INC (GYRE)"
    assert meta.exhibit == "3.1"
    assert crawler.document_id(meta, filename) == "edgar-0001193125-15-237610-d1ex31"


def test_parse_hit_skips_other_exhibits_and_formats():
    assert crawler.parse_hit(make_hit(file_type="EX-10.1")) is None
    assert crawler.parse_hit(make_hit(file_type="EX-31")) is None
    assert crawler.parse_hit(make_hit(filename="d1ex31.pdf")) is None
    assert crawler.parse_hit(make_hit(file_type="EX-4.2")) is None
    assert crawler.parse_hit(make_hit(file_type="EX-4.2"), "voting_agreement") is not None
    assert crawler.parse_hit(make_hit(file_type="EX-10.1"), "voting_agreement") is not None
    assert crawler.parse_hit(make_hit(file_type="EX-3.1"), "voting_agreement") is None


def test_crawl_skips_duplicates_and_reruns(tmp_path):
    hits = [
        make_hit("a.htm"),
        make_hit("b.htm", adsh="0001193125-15-000001"),
        make_hit("c.htm", file_type="EX-10.1"),
    ]
    client = FakeClient(hits, {"a.htm": CHARTER, "b.htm": CHARTER, "c.htm": b"junk"})

    assert crawler.crawl(client, tmp_path, limit=10) == 1
    assert crawler.crawl(client, tmp_path, limit=10) == 0

    with (tmp_path / "index.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [row["path"] for row in rows] == ["edgar-0001193125-15-237610-a.htm"]
    assert (tmp_path / rows[0]["path"]).read_bytes() == CHARTER


def test_crawl_skips_failed_downloads(tmp_path):
    class FlakyClient(FakeClient):
        def download(self, meta, filename):
            if filename == "bad.htm":
                raise httpx.HTTPStatusError("504", request=None, response=None)
            return super().download(meta, filename)

    hits = [make_hit("bad.htm"), make_hit("good.htm")]
    client = FlakyClient(hits, {"good.htm": CHARTER})
    assert crawler.crawl(client, tmp_path, limit=10) == 1


def test_crawl_respects_limit(tmp_path):
    hits = [make_hit(f"{i}.htm", cik=f"{i:010d}") for i in range(5)]
    contents = {f"{i}.htm": CHARTER + str(i).encode() for i in range(5)}
    assert crawler.crawl(FakeClient(hits, contents), tmp_path, limit=2) == 2


def test_charter_gate():
    assert crawler.passes_gate("charter", CHARTER)
    designations = b"<h1>Certificate of Designations</h1>" + CHARTER
    assert not crawler.passes_gate("charter", designations)
    assert not crawler.passes_gate("charter", b"FORM OF " + CHARTER)
    assert not crawler.passes_gate("charter", b"<p>Certificate of Amendment</p>" + CHARTER)
    assert not crawler.passes_gate("charter", b"Amended and Restated Certificate of Incorporation")


def test_voting_agreement_gate():
    assert crawler.passes_gate("voting_agreement", VOTING)
    assert crawler.passes_gate("voting_agreement", b"Voting Agreement ... drag along ...")
    assert not crawler.passes_gate("voting_agreement", b"Voting Agreement, nothing else")
    assert not crawler.passes_gate("voting_agreement", b"Drag-Along only")


def test_crawl_keeps_one_document_per_company_and_kind(tmp_path, capsys):
    hits = [
        make_hit("a.htm"),
        make_hit("a2.htm", adsh="0001193125-15-000001"),
        make_hit("rejected.htm", cik="0000000002"),
        make_hit("v.htm", file_type="EX-10.2"),
    ]
    contents = {
        "a.htm": CHARTER,
        "a2.htm": CHARTER + b" refiled",
        "rejected.htm": b"junk",
        "v.htm": VOTING,
    }
    client = FakeClient(hits, contents)
    assert crawler.crawl(client, tmp_path, limit=10) == 2
    assert "rejected 1" in capsys.readouterr().out
    assert crawler.crawl(client, tmp_path, limit=10) == 0
    with (tmp_path / "index.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["kind"] for r in rows] == ["charter", "voting_agreement"]
    assert not (tmp_path / "edgar-0001193125-15-000001-a2.htm").exists()


def test_crawl_kind_filter(tmp_path):
    client = FakeClient([make_hit("v.htm", file_type="EX-10.2")], {"v.htm": VOTING})
    assert crawler.crawl(client, tmp_path, limit=10, kinds=("charter",)) == 0
    assert crawler.crawl(client, tmp_path, limit=10, kinds=("voting_agreement",)) == 1


def test_crawl_rejects_old_format_index(tmp_path):
    (tmp_path / "index.csv").write_text("document_id,path,content_hash,cik\nx,x.htm,h,0001124105\n")
    with pytest.raises(ValueError, match="fresh --out"):
        crawler.crawl(FakeClient([], {}), tmp_path, limit=1)


def test_limit_applies_per_kind(tmp_path):
    charters = [make_hit(f"c{i}.htm", "EX-3.1", cik=f"000000000{i}") for i in range(3)]
    votings = [make_hit(f"v{i}.htm", "EX-10.2", cik=f"000000000{i}") for i in range(3)]
    contents = {f"c{i}.htm": CHARTER for i in range(3)} | {f"v{i}.htm": VOTING for i in range(3)}
    index = tmp_path / "index.csv"
    assert crawler.crawl(FakeClient(charters + votings, contents), tmp_path, limit=1) == 2
    with index.open(newline="") as f:
        assert sorted(row["kind"] for row in csv.DictReader(f)) == ["charter", "voting_agreement"]
