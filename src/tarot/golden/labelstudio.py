import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from pydantic import ValidationError

from tarot.ingest.parse import ParsedDocument, parse_file
from tarot.ontology.clauses import (
    CLAUSE_ADAPTER,
    AntiDilution,
    BoardComposition,
    Clause,
    ClauseType,
    DragAlong,
    LiquidationPreference,
    ProtectiveProvisions,
)
from tarot.schemas import DocumentSource, Span, TarotModel

_MODELS = {
    ClauseType.liquidation_preference: LiquidationPreference,
    ClauseType.anti_dilution: AntiDilution,
    ClauseType.board_composition: BoardComposition,
    ClauseType.drag_along: DragAlong,
    ClauseType.protective_provisions: ProtectiveProvisions,
}


class GoldClause(TarotModel):
    span: Span
    clause: Clause


def to_tasks(parsed_docs: list[ParsedDocument]) -> list[dict]:
    return [{"data": {"document_id": p.document.document_id, "text": p.text}} for p in parsed_docs]


def _regions(task: dict) -> dict[str, dict]:
    """Group one annotation's results by region id. Raises on a region without a clause label."""
    anns = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
    if not anns:
        raise ValueError(f"{task['data']['document_id']}: no submitted annotation")
    regions: dict[str, dict] = defaultdict(dict)
    for r in anns[0]["result"]:
        if r["type"] == "labels":
            v = r["value"]
            if len(v["labels"]) != 1:
                raise ValueError(f"region {r['id']}: expected exactly one label, got {v['labels']}")
            regions[r["id"]].update(start=v["start"], end=v["end"], label=v["labels"][0])
        elif r["type"] in ("choices", "number"):
            v = r["value"]
            if r["type"] == "number":
                regions[r["id"]][r["from_name"]] = v["number"]
            else:
                multi = r["from_name"] in ("trigger_holders", "veto_matters")
                regions[r["id"]][r["from_name"]] = v["choices"] if multi else v["choices"][0]
    for rid, reg in regions.items():
        if "label" not in reg:
            raise ValueError(f"region {rid}: attributes without a clause label")
    return regions


def spans(export: list[dict]) -> dict[str, tuple[str, list[tuple[int, int, str]]]]:
    """document_id -> (text, [(start, end, clause_type)]). Attributes are not validated."""
    return {
        t["data"]["document_id"]: (
            t["data"]["text"],
            [(r["start"], r["end"], r["label"]) for r in _regions(t).values()],
        )
        for t in export
    }


def from_export(export_json: list[dict]) -> dict[str, list[GoldClause]]:
    out: dict[str, list[GoldClause]] = {}
    for task in export_json:
        gold = []
        for rid, reg in _regions(task).items():
            try:
                ctype = ClauseType(reg["label"])
                # attributes left over from a switched label are ignored
                fields = {k: v for k, v in reg.items() if k in _MODELS[ctype].model_fields}
                clause = CLAUSE_ADAPTER.validate_python({**fields, "clause_type": ctype})
                gold.append(
                    GoldClause(span=Span(start=reg["start"], end=reg["end"]), clause=clause)
                )
            except (ValueError, ValidationError) as e:
                raise ValueError(f"region {rid}: {e}") from e
        out[task["data"]["document_id"]] = gold
    return out


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m tarot.golden.labelstudio")
    p.add_argument("raw_dir")
    p.add_argument("ids_file", help="pilot.txt or main.txt")
    a = p.parse_args()
    files = {f.stem: f for f in Path(a.raw_dir).iterdir() if f.suffix in (".htm", ".html", ".txt")}
    ids = Path(a.ids_file).read_text().split()
    docs = [parse_file(files[i], i, DocumentSource.UPLOAD) for i in ids]
    json.dump(to_tasks(docs), sys.stdout)


if __name__ == "__main__":
    main()
