import pytest

from tarot.golden.kappa import kappa
from tarot.golden.labelstudio import from_export, to_tasks
from tarot.golden.select import main as select_main
from tarot.ingest.parse import parse_file
from tarot.ontology.clauses import ClauseType, LiquidationPreference
from tarot.schemas import DocumentSource


def task(doc, text, *regions):
    result = []
    for i, (start, end, label, attrs) in enumerate(regions):
        rid = f"r{i}"
        result.append(
            {
                "id": rid,
                "type": "labels",
                "from_name": "label",
                "value": {"start": start, "end": end, "text": text[start:end], "labels": [label]},
            }
        )
        for name, v in attrs.items():
            kind = "number" if isinstance(v, int | float) and not isinstance(v, bool) else "choices"
            value = {"number": v} if kind == "number" else {"choices": [str(v).lower()]}
            result.append({"id": rid, "type": kind, "from_name": name, "value": value})
    return {"data": {"document_id": doc, "text": text}, "annotations": [{"result": result}]}


LP = ClauseType.liquidation_preference.value
TEXT = "x" * 10


def test_kappa_hand_computed():
    a = [task("d", TEXT, (0, 5, LP, {}))]
    b = [task("d", TEXT, (0, 4, LP, {}))]
    # pairs: 4 (lp,lp), 1 (lp,none), 5 (none,none). po=0.9, pe=0.5*0.4+0.5*0.6=0.5, kappa=0.8
    res = kappa(a, b)
    assert res["overall"] == pytest.approx(0.8)
    assert res["per_type"][LP] == pytest.approx(0.8)
    assert res["per_type"]["drag_along"] is None
    assert res["regions"] == {"a": 1, "b": 1}


def test_kappa_perfect_agreement():
    a = [task("d", TEXT, (2, 8, LP, {}))]
    assert kappa(a, a)["overall"] == 1.0


def test_from_export_valid_and_invalid():
    ok = task(
        "d",
        TEXT,
        (0, 5, LP, {"multiple": 1, "participating": True, "cap": 3, "seniority": "senior"}),
    )
    gold = from_export([ok])["d"]
    assert gold[0].clause == LiquidationPreference(
        multiple=1, participating=True, cap=3, seniority="senior"
    )
    assert (gold[0].span.start, gold[0].span.end) == (0, 5)
    bad = task("d", TEXT, (0, 5, LP, {"multiple": 1, "participating": False, "cap": 3}))
    with pytest.raises(ValueError, match="region r0.*cap"):
        from_export([bad])


def test_select_deterministic_and_pilot(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    heads = [
        "Liquidation Preference.",
        "Anti-Dilution.",
        "Board of Directors.",
        "Drag-Along.",
        "Protective Provisions.",
    ]
    for i in range(8):
        body = "\n".join(f"{n}. {heads[(i + n) % 5]}\ntext" for n in range(1, 3))
        (raw / f"doc{i}.txt").write_text(body)

    def run(out):
        monkeypatch.setattr(
            "sys.argv", ["select", str(raw), "--n", "7", "--pilot", "5", "--out", str(out)]
        )
        select_main()
        return [(out / f).read_text() for f in ("pilot.txt", "main.txt")]

    first, second = run(tmp_path / "a"), run(tmp_path / "b")
    assert first == second
    assert len(first[0].split()) == 5 and len(first[1].split()) == 2


def test_to_tasks(tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("hello")
    assert to_tasks([parse_file(f, "d", DocumentSource.UPLOAD)]) == [
        {"data": {"document_id": "d", "text": "hello"}}
    ]
