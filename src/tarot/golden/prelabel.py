import argparse
import json
import re
from pathlib import Path

from tarot.golden.labelstudio import to_tasks
from tarot.ingest.parse import ParsedDocument, parse_file
from tarot.ontology.clauses import HEADINGS, ClauseType
from tarot.schemas import DocumentSource

MODEL_VERSION = "headings-v1"
_NUM = re.compile(r"^(?:(?:section|article)\s+(?:[ivxlc]+|\d+(?:\.\d+)*)\b|\d+(?:\.\d+)*)[.:]?\s*")


def _hit(ctype: ClauseType, title: str, body: str) -> bool:
    for p in HEADINGS[ctype]:
        if p == "liquidation" and title != p:  # bare word: only a heading that is just that
            continue
        if p in title and (p != "board of directors" or "elect" in body[:400].lower()):
            return True
    return False


def prelabel(parsed: ParsedDocument) -> list[tuple[int, int, ClauseType]]:
    hs = parsed.headings
    out = []
    for i, h in enumerate(hs):
        stop = next((n.span.start for n in hs[i + 1 :] if n.level <= h.level), len(parsed.text))
        body = parsed.text[h.span.end : stop]
        start = h.span.end + len(body) - len(body.lstrip())
        end = h.span.end + len(body.rstrip())
        if end <= start:
            continue
        title = _NUM.sub("", h.title.lower()).strip(" .:")
        out += [(start, end, t) for t in ClauseType if _hit(t, title, body.lstrip())]
    return sorted(out)


def tasks(docs: list[ParsedDocument]) -> list[dict]:
    out = to_tasks(docs)
    for task, p in zip(out, docs, strict=True):
        result = [
            {
                "id": f"pre{i}",
                "from_name": "label",
                "to_name": "text",
                "type": "labels",
                "value": {"start": s, "end": e, "text": p.text[s:e], "labels": [t.value]},
            }
            for i, (s, e, t) in enumerate(prelabel(p))
        ]
        task["predictions"] = [{"model_version": MODEL_VERSION, "result": result}]
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m tarot.golden.prelabel")
    p.add_argument("raw_dir")
    p.add_argument("ids_file", help="main.txt; refused if any id is in pilot.txt beside it")
    p.add_argument("--out", default="tasks.json")
    a = p.parse_args(argv)
    ids = Path(a.ids_file).read_text().split()
    pilot = Path(a.ids_file).with_name("pilot.txt")
    clash = sorted(set(ids) & set(pilot.read_text().split())) if pilot.exists() else []
    if clash:
        raise SystemExit(f"refusing: pilot filings must be labelled without pre-labels: {clash}")
    files = {f.stem: f for f in Path(a.raw_dir).iterdir() if f.suffix in (".htm", ".html", ".txt")}
    docs = [parse_file(files[i], i, DocumentSource.UPLOAD) for i in ids]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(tasks(docs)))
    print(f"{len(docs)} tasks, {sum(len(prelabel(d)) for d in docs)} pre-labels -> {a.out}")


if __name__ == "__main__":
    main()
