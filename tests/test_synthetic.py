import json
from collections import Counter

from tarot.ontology.clauses import CLAUSE_ADAPTER, AntiDilutionMethod, ClauseType
from tarot.synthetic.term_sheets import make_doc, write_corpus

STEMS = {
    "full_ratchet": "full ratchet",
    "none": "no anti-dilution",
    "broad_based_weighted_average": "broad-based",
    "narrow_based_weighted_average": "narrow-based",
    "board": "the Board",
    "preferred_majority": "Preferred",
    "common_majority": "Common",
    "amend_charter": "charter",
    "new_senior_security": "senior",
    "change_board_size": "board size|size of the board",
    "dividends": "dividend",
    "liquidation_or_sale": "liquidation",
    "debt_above_threshold": "debt",
    "redemption": "redemption",
    "majority": "simple majority",
    "supermajority": "two-thirds",
}
MULTIPLES = {1: "1x|one times", 1.5: "1.5x|one and a half", 2: "2x|two times", 3: "3x|three times"}


def has(span, stems):
    return any(s in span for s in stems.split("|"))


def test_deterministic(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    write_corpus(5, 0, a)
    write_corpus(5, 0, b)
    write_corpus(5, 0, b)
    write_corpus(5, 1, c)
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir())
    assert all((a / n).read_bytes() == (b / n).read_bytes() for n in names)
    assert any(
        (a / n).read_bytes() != (c / n.replace("syn-0", "syn-1")).read_bytes() for n in names
    )


def test_labels_validate_and_match_text():
    for i in range(60):
        _, text, labels = make_doc(0, i)
        assert Counter(lab["clause"]["clause_type"] for lab in labels) == Counter(ClauseType)
        for lab in labels:
            c = CLAUSE_ADAPTER.validate_python(lab["clause"])
            span = text[lab["span"]["start"] : lab["span"]["end"]]
            assert text[lab["span"]["start"] - 1] == "\n" and "\n" not in span
            match c.clause_type:
                case ClauseType.liquidation_preference:
                    assert has(span, MULTIPLES[c.multiple])
                    assert ("participate" in span or "pro rata" in span) == c.participating
                    assert c.cap is None or f"{c.cap:g}x." in span
                    assert c.cap is None or c.cap >= c.multiple
                case ClauseType.anti_dilution:
                    assert has(span, STEMS[c.method])
                case ClauseType.board_composition:
                    assert all(str(n) in span for n in (c.investor_seats, c.common_seats))
                case ClauseType.drag_along:
                    assert all(has(span, STEMS[h]) for h in c.trigger_holders)
                    assert ("no carve-outs" in span) != c.founder_carve_outs
                case ClauseType.protective_provisions:
                    assert all(has(span, STEMS[m]) for m in c.veto_matters)
                    assert has(span, STEMS[c.voting_threshold])


def test_coverage():
    docs = [make_doc(0, i)[2] for i in range(200)]
    clauses = [CLAUSE_ADAPTER.validate_python(lab["clause"]) for d in docs for lab in d]
    assert {c.method for c in clauses if c.clause_type == "anti_dilution"} == set(
        AntiDilutionMethod
    )
    assert {c.participating for c in clauses if c.clause_type == "liquidation_preference"} == {
        True,
        False,
    }
    json.dumps(docs)
