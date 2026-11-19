import csv

import httpx

from tarot.ingest import crawler


def make_hit(filename="d1ex31.htm", file_type="EX-3.1", adsh="0001193125-15-237610"):
    return {
        "_id": f"{adsh}:{filename}",
        "_source": {
            "ciks": ["0001124105"],
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
        return self.hits if start == 0 and query == crawler.QUERIES[0] else []

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
    assert crawler.parse_hit(make_hit(file_type="EX-4.2")) is not None


def test_crawl_skips_duplicates_and_reruns(tmp_path):
    hits = [
        make_hit("a.htm"),
        make_hit("b.htm", adsh="0001193125-15-000001"),
        make_hit("c.htm", file_type="EX-10.1"),
    ]
    client = FakeClient(hits, {"a.htm": b"charter", "b.htm": b"charter"})

    assert crawler.crawl(client, tmp_path, limit=10) == 1
    assert crawler.crawl(client, tmp_path, limit=10) == 0

    with (tmp_path / "index.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [row["path"] for row in rows] == ["edgar-0001193125-15-237610-a.htm"]
    assert (tmp_path / rows[0]["path"]).read_bytes() == b"charter"


def test_crawl_skips_failed_downloads(tmp_path):
    class FlakyClient(FakeClient):
        def download(self, meta, filename):
            if filename == "bad.htm":
                raise httpx.HTTPStatusError("504", request=None, response=None)
            return super().download(meta, filename)

    hits = [make_hit("bad.htm"), make_hit("good.htm")]
    client = FlakyClient(hits, {"good.htm": b"charter"})
    assert crawler.crawl(client, tmp_path, limit=10) == 1


def test_crawl_respects_limit(tmp_path):
    hits = [make_hit(f"{i}.htm") for i in range(5)]
    contents = {f"{i}.htm": f"doc {i}".encode() for i in range(5)}
    assert crawler.crawl(FakeClient(hits, contents), tmp_path, limit=2) == 2
