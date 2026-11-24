import json

import pytest
from test_golden import task

from tarot.golden import g2, prelabel, prelabel_recall
from tarot.golden.labelstudio import from_export
from tarot.ingest.parse import parse_file
from tarot.ontology.clauses import ClauseType
from tarot.schemas import DocumentSource

CHARTER = """1. Liquidation Preference.
Upon any liquidation, holders of Series A receive one times the original price.
2. Protective Provisions.
The Corporation shall not, without consent of the Series A holders, amend this charter.
3. Board of Directors.
The board of directors may adopt bylaws and appoint officers.
4. Voting.
5. Board of Directors.
The holders of Series A, voting separately, shall elect two directors.
6. Liquidation Notices.
Notice of any liquidation shall be mailed.
"""
LP = ClauseType.liquidation_preference
PP = ClauseType.protective_provisions
BC = ClauseType.board_composition


def test_prelabel_headings(tmp_path):
    (tmp_path / "d.txt").write_text(CHARTER)
    parsed = parse_file(tmp_path / "d.txt", "d", DocumentSource.UPLOAD)
    found = prelabel.prelabel(parsed)
    assert [(t, parsed.text[s:e].splitlines()[0][:12]) for s, e, t in found] == [
        (LP, "Upon any liq"),
        (PP, "The Corporat"),
        (BC, "The holders "),
    ]
    assert parsed.text[found[0][0] : found[0][1]].endswith("original price.")
    out = prelabel.tasks([parsed])[0]["predictions"][0]
    assert out["model_version"] == "headings-v1"
    assert out["result"][0]["value"]["labels"] == ["liquidation_preference"]
    assert out["result"][0]["to_name"] == "text"


def test_prelabel_refuses_pilot(tmp_path):
    (tmp_path / "pilot.txt").write_text("a\nb\n")
    (tmp_path / "main.txt").write_text("b\nc\n")
    with pytest.raises(SystemExit, match=r"refusing.*\['b'\]"):
        prelabel.main([str(tmp_path), str(tmp_path / "main.txt"), "--out", str(tmp_path / "o")])


def test_g2_rows(tmp_path):
    text = "x" * 40
    export = [
        task(
            "d",
            text,
            (5, 20, LP.value, {"multiple": 2, "participating": True, "cap": 3}),
            (25, 35, "anti_dilution", {"method": "full_ratchet", "pay_to_play": False}),
        )
    ]
    path = tmp_path / "e.json"
    path.write_text(json.dumps(export))
    out = tmp_path / "g.jsonl"
    g2.main(
        [str(path), "--out", str(out), "--dataset-version", "g2-v1.0", "--corpus-snapshot", "s"]
    )
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["id"] for r in rows] == [f"g2-gen-000{i}" for i in range(1, 7)]
    assert [r["question_type"] for r in rows] == ["factoid", "factoid", "benchmark"] * 2
    assert rows[0]["expected_answer"] == "2x the original price."
    assert rows[1]["expected_answer"] == "Yes, participating with a 3x cap."
    assert rows[2]["expected_answer"].startswith("Differs from the NVCA default: multiple 2.0")
    assert rows[3]["expected_answer"] == "full ratchet."
    assert rows[5]["expected_answer"] == (
        "Differs from the NVCA default: method full ratchet (default broad based weighted average)."
    )
    assert rows[0]["supporting_spans"] == [{"chunk_id": None, "start": 5, "end": 20}]
    assert rows[4]["answerable"] is True and rows[4]["corpus_snapshot"] == "s"


def test_recall_hand_example():
    gold = [("d", 0, 10, LP), ("d", 20, 30, "anti_dilution")]
    pre = [("d", 0, 6, LP), ("d", 22, 25, "anti_dilution"), ("d", 40, 50, LP)]
    res = prelabel_recall.score(gold, pre)
    # LP gold covered 6/10 -> found. AD covered 3/10 -> missed. Third pre-label matches no gold.
    assert res[LP.value] == (1.0, 0.5)
    assert res["anti_dilution"] == (0.0, 0.0)
    assert res["all"] == (0.5, pytest.approx(1 / 3))


def test_g2_skips_conflicting_factoids_but_preserves_unambiguous_ones(caplog):
    from tarot.golden.labelstudio import from_export

    gold = from_export(
        [
            task(
                "d",
                "x" * 20,
                (0, 10, LP, {"multiple": 1, "participating": False}),
                (10, 20, LP, {"multiple": 2, "participating": False}),
            )
        ]
    )
    rows = g2.generate(gold, "v", "s")
    factoids = [r for r in rows if r["question_type"] == "factoid"]
    assert {r["question"] for r in factoids} == {"Is the liquidation preference participating?"}
    assert {r["expected_answer"] for r in factoids} == {"No, non-participating."}
    assert "review manually" in caplog.text
    assert not any(r["question_type"] == "benchmark" for r in rows)
    assert "compare with the NVCA default?" in caplog.text


def test_g2_series_that_agree_share_one_row():
    a = (0, 10, LP.value, {"multiple": 1, "participating": False})
    b = (12, 20, LP.value, {"multiple": 1, "participating": True})
    rows = g2.generate(from_export([task("d", "x" * 40, a, b)]), "v", "s")
    multiple = [r for r in rows if "multiple" in r["question"]]
    assert len(multiple) == 1
    assert [s["start"] for s in multiple[0]["supporting_spans"]] == [0, 12]
    assert not any("participating" in r["question"] for r in rows)
