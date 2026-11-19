from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import product

import networkx as nx

from tarot.ontology.clauses import Clause, ClauseType, DragHolder

T = ClauseType
Clauses = dict[ClauseType, Clause]


@dataclass(frozen=True)
class Pattern:
    id: str
    description: str
    reads: tuple[ClauseType, ...]
    test: Callable[[Clauses], bool]


PATTERNS = (
    Pattern(
        "full_ratchet_no_pay_to_play",
        "Full-ratchet anti-dilution with no pay-to-play",
        (T.anti_dilution,),
        lambda c: (
            c[T.anti_dilution].method == "full_ratchet" and not c[T.anti_dilution].pay_to_play
        ),
    ),
    Pattern(
        "participating_uncapped",
        "Participating liquidation preference with no cap",
        (T.liquidation_preference,),
        lambda c: (
            c[T.liquidation_preference].participating and c[T.liquidation_preference].cap is None
        ),
    ),
    Pattern(
        "high_multiple",
        "Liquidation preference multiple above 1x",
        (T.liquidation_preference,),
        lambda c: c[T.liquidation_preference].multiple > 1,
    ),
    Pattern(
        "investor_board_control",
        "Investor seats outnumber all other seats",
        (T.board_composition,),
        lambda c: (
            c[T.board_composition].investor_seats
            > c[T.board_composition].common_seats + c[T.board_composition].independent_seats
        ),
    ),
    Pattern(
        "drag_without_common",
        "Drag-along does not require a common majority",
        (T.drag_along,),
        lambda c: DragHolder.common_majority not in c[T.drag_along].trigger_holders,
    ),
    Pattern(
        "ratchet_with_participation",
        "Full ratchet combined with participating preference",
        (T.anti_dilution, T.liquidation_preference),
        lambda c: (
            c[T.anti_dilution].method == "full_ratchet"
            and c[T.liquidation_preference].participating
        ),
    ),
)

EXPANSIONS = (
    (T.drag_along, T.board_composition),
    (T.anti_dilution, T.liquidation_preference),
    (T.protective_provisions, T.board_composition),
)

_G = nx.DiGraph()
_G.add_nodes_from(ClauseType)
for _p in PATTERNS:
    _G.add_node(_p.id, pattern=_p)
    _G.add_edges_from((_p.id, t, {"kind": "reads"}) for t in _p.reads)
for _a, _b in EXPANSIONS:
    _G.add_edge(_a, _b, kind="expands")
    _G.add_edge(_b, _a, kind="expands")


def match_patterns(clauses: Iterable[Clause]) -> list[Pattern]:
    by_type: dict[ClauseType, list[Clause]] = {}
    for c in clauses:
        by_type.setdefault(c.clause_type, []).append(c)
    # a charter often has one clause per series (A, B, C); any combination may trigger
    return [
        p
        for _, p in _G.nodes(data="pattern")
        if p
        and any(
            p.test(dict(zip(p.reads, combo, strict=True)))
            for combo in product(*(by_type.get(t, []) for t in p.reads))
        )
    ]


def expand(clause_type: ClauseType) -> set[ClauseType]:
    return {t for _, t, k in _G.out_edges(clause_type, data="kind") if k == "expands"}
