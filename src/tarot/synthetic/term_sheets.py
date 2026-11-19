"""Synthetic term sheets with exact-span labels. Fine-tuning data (D4) only, never test data."""

import json
import os
import random
from pathlib import Path

from tarot.ontology.clauses import (
    BENCHMARK,
    CLAUSE_ADAPTER,
    AntiDilution,
    AntiDilutionMethod,
    BoardComposition,
    Clause,
    ClauseType,
    DragAlong,
    DragHolder,
    LiquidationPreference,
    ProtectiveProvisions,
    VetoMatter,
    VotingThreshold,
)

HEADINGS = {
    ClauseType.liquidation_preference: "Liquidation Preference",
    ClauseType.anti_dilution: "Anti-dilution Provisions",
    ClauseType.board_composition: "Board of Directors",
    ClauseType.drag_along: "Drag-Along",
    ClauseType.protective_provisions: "Protective Provisions",
}
MULTIPLE = {
    1: ("1x the original purchase price", "one times the amount originally invested"),
    1.5: ("1.5x the original purchase price", "one and a half times the amount invested"),
    2: ("2x the original purchase price", "two times the amount originally invested"),
    3: ("3x the original purchase price", "three times the amount invested"),
}
METHOD = {
    AntiDilutionMethod.broad_based_weighted_average: (
        "Conversion price adjusts on a broad-based weighted average basis.",
        "Down-round protection is broad-based weighted average.",
    ),
    AntiDilutionMethod.narrow_based_weighted_average: (
        "Conversion price adjusts on a narrow-based weighted average basis.",
        "Down-round protection is narrow-based weighted average.",
    ),
    AntiDilutionMethod.full_ratchet: (
        "Conversion price resets to the new lower price under a full ratchet.",
        "Down-round protection is a full ratchet to the dilutive issue price.",
    ),
    AntiDilutionMethod.none: (
        "There is no anti-dilution adjustment to the conversion price.",
        "The Series A receives no anti-dilution protection.",
    ),
}
HOLDER = {
    DragHolder.board: "the Board",
    DragHolder.preferred_majority: "holders of a majority of the Preferred",
    DragHolder.common_majority: "holders of a majority of the Common",
}
VETO = {
    VetoMatter.amend_charter: ("any amendment of the charter", "an amendment to the charter"),
    VetoMatter.new_senior_security: ("issuing a senior security", "creating a senior class"),
    VetoMatter.change_board_size: ("changing the size of the board", "any change to board size"),
    VetoMatter.dividends: ("paying any dividend", "declaring a dividend"),
    VetoMatter.liquidation_or_sale: (
        "a liquidation of the company",
        "any liquidation or sale of the company",
    ),
    VetoMatter.debt_above_threshold: ("incurring debt above the agreed limit", "taking on debt"),
    VetoMatter.redemption: ("any redemption of shares", "a redemption of capital stock"),
}
THRESHOLD = {
    VotingThreshold.majority: ("a simple majority", "at least a simple majority"),
    VotingThreshold.supermajority: (
        "at least two-thirds",
        "no less than two-thirds",
    ),
}
FILLERS = {
    "Dividends": (
        "Non-cumulative dividends of {n}% accrue when and if declared by the board.",
        "Holders receive {n}% non-cumulative dividends, payable only if declared.",
    ),
    "Information Rights": (
        "Major investors receive annual budgets and quarterly financials within {n} days.",
        "Investors holding the minimum stake get quarterly accounts within {n} days.",
    ),
    "Expenses": (
        "The company pays investor counsel fees up to ${n},000 at closing.",
        "Legal fees of the lead investor are reimbursed, capped at ${n},000.",
    ),
    "Exclusivity": (
        "The company will not solicit competing offers for {n} days after signing.",
        "A {n}-day no-shop applies from the date of this term sheet.",
    ),
}
COMPANY = (
    ("Nova", "Brightwave", "Quillon", "Harbor", "Pixel"),
    ("Labs", "Systems", "Robotics", "Bio"),
)


def _lst(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def sample(rng: random.Random, t: ClauseType) -> Clause:
    if rng.random() < 0.4:
        return BENCHMARK[t]
    match t:
        case ClauseType.liquidation_preference:
            part = rng.random() < 0.5
            cap = rng.choice((None, 2, 3)) if part else None
            return LiquidationPreference(
                multiple=rng.choice(list(MULTIPLE)), participating=part, cap=cap
            )
        case ClauseType.anti_dilution:
            return AntiDilution(
                method=rng.choice(list(AntiDilutionMethod)), pay_to_play=rng.random() < 0.5
            )
        case ClauseType.board_composition:
            return BoardComposition(
                investor_seats=rng.randint(1, 3),
                common_seats=rng.randint(1, 3),
                independent_seats=rng.randint(0, 2),
            )
        case ClauseType.drag_along:
            holders = rng.sample(list(DragHolder), rng.randint(1, len(DragHolder)))
            return DragAlong(
                trigger_holders=frozenset(holders), founder_carve_outs=rng.random() < 0.5
            )
        case ClauseType.protective_provisions:
            matters = rng.sample(list(VetoMatter), rng.randint(1, len(VetoMatter)))
            return ProtectiveProvisions(
                veto_matters=frozenset(matters), voting_threshold=rng.choice(list(VotingThreshold))
            )


def render(rng: random.Random, c: Clause) -> str:
    ch = rng.choice
    match c:
        case LiquidationPreference():
            s = f"On a liquidation, holders first receive {ch(MULTIPLE[c.multiple])}"
            if not c.participating:
                s += ", or convert to common if that pays more, with no further share of proceeds."
            elif c.cap is None:
                s += ", then share pro rata with the common on an as-converted basis."
            else:
                s += f", then participate with the common until total proceeds reach {c.cap:g}x."
            return s + ch(
                (" The Series A ranks pari passu.", " Ranking is pari passu with other preferred.")
            )
        case AntiDilution():
            tail = (
                "Holders must buy their pro rata share of new rounds to keep this right.",
                "Pay-to-play applies: non-participating holders lose the protection.",
            )
            return ch(METHOD[c.method]) + (" " + ch(tail) if c.pay_to_play else "")
        case BoardComposition():
            i, k, d = c.investor_seats, c.common_seats, c.independent_seats
            di, dk = (f"director{'s' * (n > 1)}" for n in (i, k))
            s = ch(
                (
                    f"The board has {i} investor {di} and {k} common {dk}",
                    f"{i} {di} named by the investors and {k} by the common holders",
                )
            )
            return s + (
                f", plus {d} independent director{'s' * (d > 1)}."
                if d
                else ", with no independent directors."
            )
        case DragAlong():
            who = _lst([HOLDER[h] for h in sorted(c.trigger_holders)])
            s = ch(
                (
                    f"A sale of the company may be forced by {who}.",
                    f"Drag-along is triggered by {who}.",
                )
            )
            return s + (
                " Founder carve-outs apply."
                if c.founder_carve_outs
                else " There are no carve-outs."
            )
        case ProtectiveProvisions():
            what = _lst([ch(VETO[m]) for m in sorted(c.veto_matters)])
            vote = ch(THRESHOLD[c.voting_threshold])
            return f"Consent of {vote} of the Preferred is required for {what}."


def make_doc(seed: int, index: int) -> tuple[str, str, list[dict]]:
    rng = random.Random(f"{seed}-{index}")
    doc_id = f"syn-{seed}-{index:05d}"
    rnd = rng.choice(("Seed", "Series A"))
    name = f"{rng.choice(COMPANY[0])} {rng.choice(COMPANY[1])}"
    title = f"TERM SHEET\n{name} Inc.\n{rnd} Preferred Stock Financing"
    secs = [(HEADINGS[t], render(rng, c := sample(rng, t)), c) for t in ClauseType]
    secs += [
        (h, rng.choice(FILLERS[h]).format(n=rng.randint(2, 9) * 5), None)
        for h in rng.sample(sorted(FILLERS), rng.randint(2, 3))
    ]
    rng.shuffle(secs)
    text, labels = title, []
    for head, body, clause in secs:
        text += f"\n\n{head}:\n"
        if clause:
            c = CLAUSE_ADAPTER.dump_python(clause, mode="json")
            for k in ("trigger_holders", "veto_matters"):
                if k in c:
                    c[k].sort()  # frozenset order is hash-dependent
            labels.append({"clause": c, "span": {"start": len(text), "end": len(text) + len(body)}})
        text += body
    return doc_id, text + "\n", labels


def _atomic(path: Path, data: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data.encode())
    os.replace(tmp, path)


def write_corpus(n: int, seed: int, out: str | Path) -> int:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        doc_id, text, labels = make_doc(seed, i)
        _atomic(out / f"{doc_id}.txt", text)
        _atomic(out / f"{doc_id}.labels.json", json.dumps(labels, indent=2) + "\n")
    return n
