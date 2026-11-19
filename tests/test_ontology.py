import pytest
from pydantic import ValidationError

from tarot.ontology import BENCHMARK, CLAUSE_ADAPTER, ClauseType, expand, match_patterns
from tarot.ontology.clauses import AntiDilution, BoardComposition, LiquidationPreference


def ids(clauses):
    return {p.id for p in match_patterns(clauses)}


def test_cap_requires_participating():
    with pytest.raises(ValidationError):
        LiquidationPreference(multiple=1, participating=False, cap=3)
    assert LiquidationPreference(multiple=1, participating=True, cap=3).cap == 3


@pytest.mark.parametrize("seats", [(-1, 2, 1), (0, 0, 0)])
def test_bad_boards_rejected(seats):
    with pytest.raises(ValidationError):
        BoardComposition(investor_seats=seats[0], common_seats=seats[1], independent_seats=seats[2])


def test_discriminator_round_trip():
    raw = {"clause_type": "drag_along", "trigger_holders": ["board"], "founder_carve_outs": True}
    clause = CLAUSE_ADAPTER.validate_python(raw)
    assert clause.clause_type == ClauseType.drag_along
    assert CLAUSE_ADAPTER.validate_json(CLAUSE_ADAPTER.dump_json(clause)) == clause


def test_benchmark_complete_and_valid():
    assert set(BENCHMARK) == set(ClauseType)
    for clause in BENCHMARK.values():
        assert CLAUSE_ADAPTER.validate_python(clause.model_dump()) == clause


def test_full_ratchet_pattern():
    ratchet = AntiDilution(method="full_ratchet", pay_to_play=False)
    assert "full_ratchet_no_pay_to_play" in ids([ratchet])
    assert "full_ratchet_no_pay_to_play" not in ids(
        [ratchet.model_copy(update={"pay_to_play": True})]
    )


def test_benchmark_matches_nothing():
    assert match_patterns(BENCHMARK.values()) == []


def test_multi_clause_pattern_needs_all_clauses():
    ratchet = AntiDilution(method="full_ratchet", pay_to_play=True)
    liq = LiquidationPreference(multiple=1, participating=True)
    assert ids([ratchet]) == set()
    assert ids([ratchet, liq]) == {"participating_uncapped", "ratchet_with_participation"}


def test_expand():
    assert ClauseType.board_composition in expand(ClauseType.drag_along)
    assert ClauseType.drag_along in expand(ClauseType.board_composition)


def test_any_series_can_trigger_a_pattern():
    series_a = LiquidationPreference(multiple=1, participating=False)
    series_b = LiquidationPreference(multiple=2, participating=False)
    assert "high_multiple" in ids([series_b, series_a])
    assert "high_multiple" in ids([series_a, series_b])
