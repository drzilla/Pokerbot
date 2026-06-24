# SECOND_FAMILY_SAFETY_ASSESSMENT — turn continuation / double-barrel

Per the brief, the prioritized second family is a rule-backed turn double-barrel detector. Evaluated against
the hard constraint: a CONFIRMABLE family must nominate result-independently from **existing canonical
operands + an explicit owner rule**, with no invented ranges, fresh equity/EV, generic range interaction,
new evaluator, analyst-side calc, or "solver usually" hand-waving.

## Candidate hypotheses vs canonical support

| Hypothesis | Canonical support? | Verdict |
|---|---|---|
| Bluff when the turn pairs a middle/low card | "wrong" needs villain's continue range / fold-equity | needs invented range → **UNSAFE** |
| Barrel connected middling boards (J-9-8…) without adequate equity | "adequate equity" = a fresh equity calc vs a range | needs equity → **UNSAFE** |
| Double-barrel A-high in a 4BP without equity/draw support | draw is canonical (`draw_profile`), but "mistake" needs fold-equity vs the 4BP range | needs equity/range → **UNSAFE** |
| Continue after the turn invalidates the flop plan | "invalidates" / "−EV" needs range + equity | needs range/equity → **UNSAFE** |
| Bet medium SDV with weak/no draw when an owner rule prefers checking | needs an explicit, result-independent owner rule | see below |

## What the references actually contain

Every turn-barrel rule in the repo references is **equity-, fold-equity-, or result-dependent**:

- `GEM_Quick_Reference.txt`: "Fold to Turn Barrel 45–55% HU" (a frequency stat); "Turn barrel sizing 50–75%";
  M6 "3BP double-FD turn barrel with **medium equity** (MARGINAL)" — equity-gated and marked marginal.
- `Knockman_Leaks_Index.md` L1: triggers on `x/r flop AND barrel turn ≥65% AND **went_to_sd=lost**` with an
  **EV-loss ≥ 25 BB** threshold — i.e. it depends on the **result** (`went_to_sd=lost`) and an EV figure.
  Using it would **leak future/result information** into nomination — forbidden.
- "K-series binary: JAM if **FE > required**, else CHECK-FOLD" — explicit fold-equity math.

There is **no** result-independent, canonical-operand-only owner rule for turn barrels.

## The result-independent slice is already covered

The only canonical, result-independent turn-barrel nomination — *Hero continues aggression (bet flop +
bet/raise turn) with a weak made hand and no strong draw* — is **already emitted** by the existing
`gem_discovery_context.family_turn_overbarrel` as **READ_DEPENDENT** (it stays read-dependent precisely
because confirming needs a range that is not canonical). A new family would duplicate it.

## Decision — DO NOT IMPLEMENT a second family

A confirmable turn double-barrel family cannot be built without invented equity/ranges or result leakage,
and the safe result-independent slice already exists. This is reinforced by the sizing result: even a
precise, complete **flop sizing chart** yields **0** confirmed per-hand mistakes on 3609 real hands; a turn
barrel family — with **no** turn chart and heavier range-dependence — would be strictly worse. **Second
family: NOT IMPLEMENTED (rejected as unsafe / duplicative).**
