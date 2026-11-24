import argparse
import csv
import html
import os
import re
import time
from collections.abc import Iterator
from itertools import takewhile
from pathlib import Path

import httpx

from tarot.schemas import EdgarMetadata, sha256_hex

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/{filename}"
QUERIES = [
    '"liquidation preference" "Series A Preferred"',
    '"investors\' rights agreement" "Series A Preferred"',
]
VOTING_QUERIES = ['"voting agreement" "drag-along"', '"voting agreement" "Series A Preferred"']
KINDS = {
    "charter": (QUERIES, re.compile(r"^EX-3(\.|$)")),
    "voting_agreement": (VOTING_QUERIES, re.compile(r"^EX-(4|10)(\.|$)")),
}
FORMS = "S-1,S-1/A"
FILE_SUFFIXES = {".htm", ".html", ".txt"}
PAGE_SIZE = 100
MAX_RESULTS = 10_000
REQUEST_INTERVAL = 0.15
RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
OUT_DIR = Path("data/raw/edgar")
INDEX_FIELDS = ["document_id", "path", "content_hash", "kind", *EdgarMetadata.model_fields]
TITLE_CHARS = 300
CHARTER_REQUIRED = [
    re.compile(p, re.I)
    for p in (
        r"amended\s+and\s+restated\s+certificate\s+of\s+incorporation",
        r"series\s+[A-Z]\s+preferred",
        r"liquidation",
    )
]
CHARTER_REJECT_TITLE = re.compile(r"form\s+of|certificate\s+of\s+(designations?|amendment)", re.I)
VOTING_REQUIRED = re.compile(r"voting\s+agreement", re.I)
VOTING_SALE = re.compile(r"drag[- ]along|sale\s+of\s+the\s+company", re.I)


class SecClient:
    def __init__(self, user_agent: str):
        self._http = httpx.Client(
            headers={"User-Agent": user_agent}, timeout=30, follow_redirects=True
        )
        self._last_request = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._http.close()

    def _get(self, url: str, **params) -> httpx.Response:
        for attempt in range(RETRIES):
            wait = self._last_request + REQUEST_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                response = self._http.get(url, params=params)
                response.raise_for_status()
                return response
            except (httpx.HTTPStatusError, httpx.TransportError) as error:
                if isinstance(error, httpx.HTTPStatusError) and (
                    error.response.status_code not in RETRY_STATUSES
                ):
                    raise
                if attempt == RETRIES - 1:
                    raise
                time.sleep(2**attempt)
        raise AssertionError("unreachable")

    def search_page(self, query: str, start: int) -> list[dict]:
        params = {"q": query, "forms": FORMS, "from": start}
        return self._get(SEARCH_URL, **params).json()["hits"]["hits"]

    def download(self, meta: EdgarMetadata, filename: str) -> bytes:
        url = ARCHIVE_URL.format(
            cik=int(meta.cik), adsh=meta.accession_number.replace("-", ""), filename=filename
        )
        return self._get(url).content


def parse_hit(hit: dict, kind: str = "charter") -> tuple[EdgarMetadata, str] | None:
    source = hit["_source"]
    adsh, filename = hit["_id"].split(":", 1)
    file_type = source.get("file_type", "")
    if not KINDS[kind][1].match(file_type) or Path(filename).suffix.lower() not in FILE_SUFFIXES:
        return None
    company = re.sub(r"\(CIK \d+\)\s*$", "", source["display_names"][0])
    meta = EdgarMetadata(
        cik=source["ciks"][0],
        accession_number=adsh,
        company_name=" ".join(company.split()),
        form_type=source["form"],
        filing_date=source["file_date"],
        exhibit=file_type.removeprefix("EX-"),
    )
    return meta, filename


def document_id(meta: EdgarMetadata, filename: str) -> str:
    return f"edgar-{meta.accession_number}-{Path(filename).stem}"


def passes_gate(kind: str, content: bytes) -> bool:
    text = " ".join(
        html.unescape(re.sub(r"<[^>]*>", " ", content.decode("utf-8", "ignore"))).split()
    )
    if kind == "voting_agreement":
        return bool(VOTING_REQUIRED.search(text) and VOTING_SALE.search(text))
    return all(p.search(text) for p in CHARTER_REQUIRED) and not CHARTER_REJECT_TITLE.search(
        text[:TITLE_CHARS]
    )


def search(client: SecClient, kind: str) -> Iterator[dict]:
    for query in KINDS[kind][0]:
        for start in range(0, MAX_RESULTS, PAGE_SIZE):
            hits = client.search_page(query, start)
            if not hits:
                break
            yield from hits


def crawl(client: SecClient, out_dir: Path, limit: int, kinds=tuple(KINDS)) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.csv"
    rows = []
    if index_path.exists():
        with index_path.open(newline="") as f:
            reader = csv.DictReader(f)
            if "kind" not in (reader.fieldnames or []):
                raise ValueError(
                    f"{index_path} has no 'kind' column; crawl into a fresh --out directory"
                )
            rows = list(reader)
    seen_ids = {row["document_id"] for row in rows}
    seen_hashes = {row["content_hash"] for row in rows}
    seen_keys = {(row["cik"], row["kind"]) for row in rows}

    added = dict.fromkeys(kinds, 0)
    rejected = 0
    with index_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        if index_path.stat().st_size == 0:
            writer.writeheader()
        # takewhile stops paging a kind's search as soon as that kind is full
        hits = (
            (k, h)
            for k in kinds
            for h in takewhile(lambda _, k=k: added[k] < limit, search(client, k))
        )
        for kind, hit in hits:
            parsed = parse_hit(hit, kind)
            if parsed is None:
                continue
            meta, filename = parsed
            doc_id = document_id(meta, filename)
            if doc_id in seen_ids or (meta.cik, kind) in seen_keys:
                continue
            seen_ids.add(doc_id)

            try:
                content = client.download(meta, filename)
            except httpx.HTTPError as error:
                print(f"skipped {doc_id}: {error}")
                continue
            if not passes_gate(kind, content):
                rejected += 1
                continue
            content_hash = sha256_hex(content)
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            seen_keys.add((meta.cik, kind))

            path = f"{doc_id}{Path(filename).suffix.lower()}"
            (out_dir / path).write_bytes(content)
            writer.writerow(
                {"document_id": doc_id, "path": path, "content_hash": content_hash, "kind": kind}
                | meta.model_dump(mode="json")
            )
            f.flush()
            added[kind] += 1
    print(f"rejected {rejected} downloads that failed the content gate")
    return sum(added.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download S-1 charter and voting agreement exhibits."
    )
    parser.add_argument("--limit", type=int, default=100, help="accepted documents per kind")
    parser.add_argument("--kind", choices=[*KINDS, "all"], default="all")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        parser.error('set SEC_USER_AGENT in .env, e.g. "Your Name you@university.edu"')
    with SecClient(user_agent) as client:
        added = crawl(
            client, args.out, args.limit, tuple(KINDS) if args.kind == "all" else (args.kind,)
        )
    print(f"added {added} exhibits to {args.out}")


if __name__ == "__main__":
    main()
