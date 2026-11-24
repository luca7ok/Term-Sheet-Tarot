import argparse
import json
import logging
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from tarot.golden.labelstudio import GoldClause, from_export
from tarot.ontology.clauses import BENCHMARK, ClauseType

log = logging.getLogger(__name__)

yn = lambda b: "Yes" if b else "No"  # noqa: E731
names = lambda vs: ", ".join(sorted(str(v).replace("_", " ") for v in vs))  # noqa: E731

FACTOID: dict[ClauseType, tuple[tuple[str, Callable], ...]] = {
    ClauseType.liquidation_preference: (
        (
            "What is the liquidation preference multiple of the preferred stock?",
            lambda c: f"{c.multiple:g}x the original price.",
        ),
        (
            "Is the liquidation preference participating?",
            lambda c: (
                "No, non-participating."
                if not c.participating
                else f"Yes, participating with a {c.cap:g}x cap."
                if c.cap
                else "Yes, participating with no cap."
            ),
        ),
    ),
    ClauseType.anti_dilution: (
        (
            "Which anti-dilution method applies to the preferred stock?",
            lambda c: names([c.method]) + ".",
        ),
        (
            "Does the anti-dilution protection include pay-to-play?",
            lambda c: yn(c.pay_to_play) + ".",
        ),
    ),
    ClauseType.board_composition: (
        (
            "How many board seats do the preferred holders elect?",
            lambda c: f"{c.investor_seats} investor seats.",
        ),
        (
            "How is the board composed?",
            lambda c: (
                f"{c.investor_seats} investor, {c.common_seats} common and "
                f"{c.independent_seats} independent seats."
            ),
        ),
    ),
    ClauseType.drag_along: (
        ("Whose approval triggers the drag-along?", lambda c: names(c.trigger_holders) + "."),
        ("Does the drag-along have founder carve-outs?", lambda c: yn(c.founder_carve_outs) + "."),
    ),
    ClauseType.protective_provisions: (
        (
            "Which matters need the preferred holders' consent?",
            lambda c: names(c.veto_matters) + ".",
        ),
        (
            "What voting threshold do the protective provisions require?",
            lambda c: f"{c.voting_threshold.value}.".capitalize(),
        ),
    ),
}


def _benchmark(g: GoldClause) -> tuple[str, str]:
    t = g.clause.clause_type
    label = t.value.replace("_", " ")
    got = g.clause.model_dump(mode="json", exclude={"clause_type"})
    base = BENCHMARK[t].model_dump(mode="json", exclude={"clause_type"})
    show = lambda v: names(v) if isinstance(v, list) else str(v).replace("_", " ")  # noqa: E731
    diffs = [
        f"{k.replace('_', ' ')} {show(v)} (default {show(base[k])})"
        for k, v in got.items()
        if v != base[k]
    ]
    answer = (
        "Differs from the NVCA default: " + "; ".join(diffs) + "."
        if diffs
        else ("Matches the NVCA default.")
    )
    return f"How does the {label} clause compare with the NVCA default?", answer


def generate(
    gold: dict[str, list[GoldClause]], dataset_version: str, corpus_snapshot: str
) -> list[dict]:
    rows = []
    for doc in sorted(gold):
        ordered = sorted(gold[doc], key=lambda x: (x.span.start, x.span.end))
        candidates = [
            [("factoid", q, f(g.clause)) for q, f in FACTOID[g.clause.clause_type]]
            + [("benchmark", *_benchmark(g))]
            for g in ordered
        ]
        answers: dict[str, set[str]] = defaultdict(set)
        for questions in candidates:
            for _, question, answer in questions:
                answers[question].add(answer)
        # G1 records attributes and offsets but has no structured series scope.
        for question, choices in answers.items():
            if len(choices) > 1:
                log.warning("%s: conflicting answers for %r; review manually", doc, question)
        emitted: dict[str, dict] = {}
        for g, questions in zip(ordered, candidates, strict=True):
            for kind, q, answer in questions:
                if len(answers[q]) > 1:
                    continue
                span = {"chunk_id": None, "start": g.span.start, "end": g.span.end}
                if q in emitted:  # several series agree: one row citing every span
                    emitted[q]["supporting_spans"].append(span)
                    continue
                emitted[q] = {
                    "id": f"g2-gen-{len(rows) + 1:04d}",
                    "question": q,
                    "question_type": kind,
                    "document_id": doc,
                    "expected_answer": answer,
                    "supporting_spans": [span],
                    "answerable": True,
                    "dataset_version": dataset_version,
                    "corpus_snapshot": corpus_snapshot,
                }
                rows.append(emitted[q])
    return rows


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m tarot.golden.g2")
    p.add_argument("export")
    p.add_argument("--out", default="data/golden/g2_qa/generated.jsonl")
    p.add_argument("--dataset-version", required=True)
    p.add_argument("--corpus-snapshot", required=True)
    a = p.parse_args(argv)
    rows = generate(
        from_export(json.loads(Path(a.export).read_text(encoding="utf-8"))),
        a.dataset_version,
        a.corpus_snapshot,
    )
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"{len(rows)} rows -> {a.out}")


if __name__ == "__main__":
    main()
