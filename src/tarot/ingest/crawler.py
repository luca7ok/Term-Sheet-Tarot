import argparse
import csv
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path

import httpx

from tarot.schemas import EdgarMetadata, sha256_hex

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/{filename}"
QUERIES = [
    '"liquidation preference" "Series A Preferred"',
    '"investors\' rights agreement" "Series A Preferred"',
]
FORMS = "S-1,S-1/A"
EXHIBIT_PATTERN = re.compile(r"^EX-[34](\.|$)")
FILE_SUFFIXES = {".htm", ".html", ".txt"}
PAGE_SIZE = 100
MAX_RESULTS = 10_000
REQUEST_INTERVAL = 0.15
RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
OUT_DIR = Path("data/raw/edgar")
INDEX_FIELDS = ["document_id", "path", "content_hash", *EdgarMetadata.model_fields]


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


def parse_hit(hit: dict) -> tuple[EdgarMetadata, str] | None:
    source = hit["_source"]
    adsh, filename = hit["_id"].split(":", 1)
    file_type = source.get("file_type", "")
    if not EXHIBIT_PATTERN.match(file_type) or Path(filename).suffix.lower() not in FILE_SUFFIXES:
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


def search(client: SecClient) -> Iterator[dict]:
    for query in QUERIES:
        for start in range(0, MAX_RESULTS, PAGE_SIZE):
            hits = client.search_page(query, start)
            if not hits:
                break
            yield from hits


def crawl(client: SecClient, out_dir: Path, limit: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.csv"
    rows = []
    if index_path.exists():
        with index_path.open(newline="") as f:
            rows = list(csv.DictReader(f))
    seen_ids = {row["document_id"] for row in rows}
    seen_hashes = {row["content_hash"] for row in rows}

    added = 0
    with index_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        if not rows:
            writer.writeheader()
        for hit in search(client):
            if added >= limit:
                break
            parsed = parse_hit(hit)
            if parsed is None:
                continue
            meta, filename = parsed
            doc_id = document_id(meta, filename)
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)

            try:
                content = client.download(meta, filename)
            except httpx.HTTPError as error:
                print(f"skipped {doc_id}: {error}")
                continue
            content_hash = sha256_hex(content)
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)

            path = f"{doc_id}{Path(filename).suffix.lower()}"
            (out_dir / path).write_bytes(content)
            writer.writerow(
                {"document_id": doc_id, "path": path, "content_hash": content_hash}
                | meta.model_dump(mode="json")
            )
            f.flush()
            added += 1
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="Download S-1 charter and rights exhibits.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        parser.error('set SEC_USER_AGENT in .env, e.g. "Your Name you@university.edu"')
    with SecClient(user_agent) as client:
        added = crawl(client, args.out, args.limit)
    print(f"added {added} exhibits to {args.out}")


if __name__ == "__main__":
    main()
