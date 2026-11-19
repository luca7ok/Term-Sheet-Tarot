import argparse
import json
from pathlib import Path

from tarot.golden.labelstudio import spans
from tarot.golden.prelabel import prelabel
from tarot.ingest.parse import parse_file
from tarot.schemas import DocumentSource

GATE = 0.8


def _hit(gold: tuple, pre: tuple) -> bool:
    """Same document and type, and the pre-label covers at least half of the gold span."""
    overlap = min(gold[2], pre[2]) - max(gold[1], pre[1])
    return gold[::3] == pre[::3] and overlap >= 0.5 * (gold[2] - gold[1])


def score(gold: list[tuple], pre: list[tuple]) -> dict[str, tuple[float | None, float | None]]:
    """Tuples are (doc, start, end, type). type or "all" -> (recall, precision), None if empty."""
    out = {}
    for key in sorted({str(g[3]) for g in gold} | {str(q[3]) for q in pre}) + ["all"]:
        g = [x for x in gold if key in ("all", str(x[3]))]
        q = [x for x in pre if key in ("all", str(x[3]))]
        found = sum(any(_hit(x, y) for y in q) for x in g)
        right = sum(any(_hit(x, y) for x in g) for y in q)
        out[key] = (found / len(g) if g else None, right / len(q) if q else None)
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m tarot.golden.prelabel_recall")
    p.add_argument("raw_dir")
    p.add_argument("gold_export")
    a = p.parse_args(argv)
    files = {f.stem: f for f in Path(a.raw_dir).iterdir() if f.suffix in (".htm", ".html", ".txt")}
    gold, pre = [], []
    for doc, (text, regions) in spans(json.loads(Path(a.gold_export).read_text())).items():
        parsed = parse_file(files[doc], doc, DocumentSource.UPLOAD)
        if parsed.text != text:
            raise SystemExit(f"{doc}: parsed text differs from the export text, offsets invalid")
        gold += [(doc, s, e, t) for s, e, t in regions]
        pre += [(doc, s, e, t) for s, e, t in prelabel(parsed)]
    res = score(gold, pre)
    fmt = lambda v: "n/a" if v is None else f"{v:.2f}"  # noqa: E731
    for k, (r, pr) in res.items():
        print(f"{k:24} recall {fmt(r)}  precision {fmt(pr)}")
    r = res["all"][0]
    print(f"recall >= {GATE}: {'yes' if r is not None and r >= GATE else 'NO, label from scratch'}")


if __name__ == "__main__":
    main()
