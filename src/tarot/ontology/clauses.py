from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from tarot.schemas import TarotModel


class ClauseType(StrEnum):
    liquidation_preference = "liquidation_preference"
    anti_dilution = "anti_dilution"
    board_composition = "board_composition"
    drag_along = "drag_along"
    protective_provisions = "protective_provisions"


class Seniority(StrEnum):
    senior = "senior"
    pari_passu = "pari_passu"
    junior = "junior"


class AntiDilutionMethod(StrEnum):
    broad_based_weighted_average = "broad_based_weighted_average"
    narrow_based_weighted_average = "narrow_based_weighted_average"
    full_ratchet = "full_ratchet"
    none = "none"


class DragHolder(StrEnum):
    board = "board"
    preferred_majority = "preferred_majority"
    common_majority = "common_majority"


class VetoMatter(StrEnum):
    amend_charter = "amend_charter"
    new_senior_security = "new_senior_security"
    change_board_size = "change_board_size"
    dividends = "dividends"
    liquidation_or_sale = "liquidation_or_sale"
    debt_above_threshold = "debt_above_threshold"
    redemption = "redemption"


class VotingThreshold(StrEnum):
    majority = "majority"
    supermajority = "supermajority"


class LiquidationPreference(TarotModel):
    clause_type: Literal[ClauseType.liquidation_preference] = ClauseType.liquidation_preference
    multiple: float = Field(gt=0)
    participating: bool
    cap: float | None = Field(default=None, gt=0)
    seniority: Seniority = Seniority.pari_passu

    @model_validator(mode="after")
    def _cap_needs_participation(self):
        if self.cap is not None and not self.participating:
            raise ValueError("cap is only allowed when participating")
        return self


class AntiDilution(TarotModel):
    clause_type: Literal[ClauseType.anti_dilution] = ClauseType.anti_dilution
    method: AntiDilutionMethod
    pay_to_play: bool


class BoardComposition(TarotModel):
    clause_type: Literal[ClauseType.board_composition] = ClauseType.board_composition
    investor_seats: int = Field(ge=0)
    common_seats: int = Field(ge=0)
    independent_seats: int = Field(ge=0)

    @model_validator(mode="after")
    def _non_empty(self):
        if self.investor_seats + self.common_seats + self.independent_seats < 1:
            raise ValueError("board needs at least one seat")
        return self


class DragAlong(TarotModel):
    clause_type: Literal[ClauseType.drag_along] = ClauseType.drag_along
    trigger_holders: frozenset[DragHolder] = Field(min_length=1)
    founder_carve_outs: bool


class ProtectiveProvisions(TarotModel):
    clause_type: Literal[ClauseType.protective_provisions] = ClauseType.protective_provisions
    veto_matters: frozenset[VetoMatter]
    voting_threshold: VotingThreshold


Clause = Annotated[
    LiquidationPreference | AntiDilution | BoardComposition | DragAlong | ProtectiveProvisions,
    Field(discriminator="clause_type"),
]
CLAUSE_ADAPTER: TypeAdapter[Clause] = TypeAdapter(Clause)

BENCHMARK: dict[ClauseType, Clause] = {
    ClauseType.liquidation_preference: LiquidationPreference(multiple=1, participating=False),
    ClauseType.anti_dilution: AntiDilution(
        method=AntiDilutionMethod.broad_based_weighted_average, pay_to_play=False
    ),
    ClauseType.board_composition: BoardComposition(
        investor_seats=2, common_seats=2, independent_seats=1
    ),
    ClauseType.drag_along: DragAlong(
        trigger_holders=frozenset(DragHolder), founder_carve_outs=False
    ),
    ClauseType.protective_provisions: ProtectiveProvisions(
        veto_matters=frozenset(VetoMatter), voting_threshold=VotingThreshold.majority
    ),
}

HEADINGS: dict[ClauseType, tuple[str, ...]] = {
    ClauseType.liquidation_preference: (
        "liquidation",
        "liquidation preference",
        "liquidation, dissolution or winding up",
        "deemed liquidation event",
    ),
    ClauseType.anti_dilution: (
        "anti-dilution",
        "adjustments to conversion price",
        "adjustment for diluting issues",
    ),
    ClauseType.board_composition: ("election of directors", "board of directors"),
    ClauseType.drag_along: ("drag-along", "drag along right", "sale of the company"),
    ClauseType.protective_provisions: ("protective provisions", "series a protective provisions"),
}
