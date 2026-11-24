import json
import sys
from collections import Counter
from pathlib import Path

from tarot.golden.labelstudio import spans
from tarot.ontology.clauses import ClauseType

NONE = "none"


def _chars(text: str, regions: list[tuple[int, int, str]]) -> list[str]:
    labels = [NONE] * len(text)
    for start, end, ctype in sorted(regions, key=lambda r: r[0]):  # overlap: first by start wins
        for i in range(start, min(end, len(text))):
            if labels[i] == NONE:
                labels[i] = ctype
    return labels


def _kappa(pairs: Counter) -> float | None:
    n = sum(pairs.values())
    if n == 0:
        return None
    po = sum(c for (a, b), c in pairs.items() if a == b) / n
    ca, cb = Counter(), Counter()
    for (a, b), c in pairs.items():
        ca[a] += c
        cb[b] += c
    pe = sum(ca[k] * cb[k] for k in ca) / n**2
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def kappa(export_a: list[dict], export_b: list[dict]) -> dict:
    a, b = spans(export_a), spans(export_b)
    if a.keys() != b.keys():
        raise ValueError(f"annotators labelled different documents: {sorted(a.keys() ^ b.keys())}")
    pairs: Counter = Counter()
    for doc, (text, ra) in a.items():
        other_text, rb = b[doc]
        if text != other_text:
            raise ValueError(f"{doc}: annotator exports contain different text")
        pairs.update(zip(_chars(text, ra), _chars(text, rb), strict=True))
    per_type = {}
    for t in ClauseType:
        one_vs_rest = Counter()
        for (x, y), c in pairs.items():
            one_vs_rest[(x == t, y == t)] += c
        per_type[t.value] = _kappa(one_vs_rest) if any(t in p for p in pairs) else None
    return {
        "overall": _kappa(pairs),
        "per_type": per_type,
        "regions": {
            "a": sum(len(r) for _, r in a.values()),
            "b": sum(len(r) for _, r in b.values()),
        },
    }


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: python -m tarot.golden.kappa a.json b.json")
    res = kappa(*(json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[1:]))
    ok = "PASS" if res["overall"] >= 0.7 else "FAIL"
    print(f"overall kappa {res['overall']:.3f} ({ok}, gate 0.7)")
    for t, k in res["per_type"].items():
        print(f"  {t}: {'n/a (type absent)' if k is None else f'{k:.3f}'}")
    print(f"regions a={res['regions']['a']} b={res['regions']['b']}")


if __name__ == "__main__":
    main()
