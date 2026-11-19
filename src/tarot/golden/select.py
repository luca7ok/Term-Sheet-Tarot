import argparse
import csv
import random
from pathlib import Path

from tarot.ingest.parse import parse_file
from tarot.ontology.clauses import HEADINGS, ClauseType
from tarot.schemas import DocumentSource

TARGET = 30  # instances per clause type
CAP = 3  # per document and type, so one filing with many series cannot dominate


def counts(parsed) -> dict[ClauseType, int]:
    low = parsed.text.lower()
    out = {}
    for t, terms in HEADINGS.items():
        heads = sum(any(x in h.title.lower() for x in terms) for h in parsed.headings)
        out[t] = min(heads or any(x in low for x in terms), CAP)
    return out


def pick(cands: dict[str, dict], n: int, pilot: int, seed: int) -> list[str]:
    """Greedy. Pilot rounds maximise newly covered types. Every round favours rare types."""
    ids = sorted(cands)
    random.Random(seed).shuffle(ids)
    cur = dict.fromkeys(ClauseType, 0)
    kinds: set[str] = set()
    chosen: list[str] = []

    def score(i: str):
        c = cands[i]["counts"]
        new = sum(1 for t in ClauseType if c[t] and not cur[t]) if len(chosen) < pilot else 0
        gain = sum(min(c[t], max(0, TARGET - cur[t])) / (1 + cur[t]) for t in ClauseType)
        return new, cands[i]["kind"] not in kinds, gain

    while len(chosen) < min(n, len(ids)):
        best = max((i for i in ids if i not in chosen), key=score)  # ties: first in shuffled order
        chosen.append(best)
        kinds.add(cands[best]["kind"])
        for t in ClauseType:
            cur[t] += cands[best]["counts"][t]
    return chosen


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m tarot.golden.select")
    p.add_argument("raw_dir")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--pilot", type=int, default=5)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="data/golden/g1_extraction")
    a = p.parse_args()
    raw = Path(a.raw_dir)
    index = raw / "index.csv"
    kind = (
        {r["document_id"]: r.get("kind") or "" for r in csv.DictReader(index.open())}
        if index.exists()
        else {}
    )
    cands = {}
    for f in sorted(raw.iterdir()):
        if f.suffix in (".htm", ".html", ".txt"):
            cands[f.stem] = {
                "counts": counts(parse_file(f, f.stem, DocumentSource.UPLOAD)),
                "kind": kind.get(f.stem, ""),
            }
    chosen = pick(cands, a.n, a.pilot, a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pilot.txt").write_text("".join(f"{i}\n" for i in chosen[: a.pilot]))
    (out / "main.txt").write_text("".join(f"{i}\n" for i in chosen[a.pilot :]))
    for label, ids in (("pilot", chosen[: a.pilot]), ("all", chosen)):
        print(f"{label}: {len(ids)} documents")
        for t in ClauseType:
            print(f"  {t.value}: {sum(cands[i]['counts'][t] for i in ids)}")


if __name__ == "__main__":
    main()
