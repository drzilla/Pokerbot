# V821_RUNOUT_TRANSITION_PRODUCT_REQUIREMENTS

Module inside **v8.21 Range Reasoning**. Not a standalone epic; not a rename of static texture analysis.

## What it teaches

For each eligible turn or river: **what the new card changed** about the board and Hero's hand, **what of the
previous plan still holds**, and **what to reassess** — reusable poker reasoning, not a range dump or a
solver-style verdict. The value is the *transition between streets*, not the static texture of one board.

## Eligible population

Hero **turn (board 4)** or **river (board 5)** decision where the canonical decision snapshot resolves and
Hero holds 2 cards. Suppressed (Insufficient evidence) when the decision is **all-in / has no future decision**
or the snapshot is incomplete (fail-closed).

## Output structure (5 parts, deterministic)

1. **Before the card** — prior board state + texture (and Hero's prior made hand).
2. **The card** — what arrived + deterministic transition tags.
3. **What changed** — made-hand/draw changes, board completion (pair/flush/straight), counterfeit — each a
   canonical fact (Factual register).
4. **What remained valid** — prior facts the card did not invalidate (e.g. "you still hold an over-pair").
5. **Planning implication** — `continue`/`resize`/`slow_down`/`pivot`/`abandon` **only** when a documented
   canonical owner + a result-independent rule supports it; otherwise the exact string *"Insufficient evidence
   for a reliable action recommendation — reassess the changed board features."*

## Descriptive vs strategic

- **Descriptive (shipped):** every fact above is the output of a canonical evaluator (`hand_strength_name`,
  `draw_profile`, `_board_texture`) or deterministic board arithmetic. **Factual** register, high confidence.
- **Strategic (blocked):** continue/resize/slow/pivot/abandon needs the opponent's continuing range +
  fold-equity, for which **no canonical owner exists**. The MVP therefore always renders **Insufficient
  evidence** for the action and records the dependency as debt. No label is rendered just because it is in the
  product vision.

## Registers (kept distinct)

`Factual` for `changed`/`remained`; `Coaching` reserved for future rule-backed implications; `Insufficient
evidence` for the strategic layer and any unresolved record. Uncertainty is never converted into confident
coaching prose.

## Hard constraints

No per-hand solver verdict; **no range/equity/EV/pot/stack/sizing numbers invented** by analyst or renderer;
no later action/board/showdown leaks into an earlier-street record; effective stack is decision-time; multiway
never uses heads-up rules; range/nut-advantage language suppressed (no opponent-range owner); the renderer
displays but does not derive (the over/under/improve direction is computed in the module). Out of scope:
turn/river *sizing* judgments, multi-street line coaching, "wrong barrel" logic, Counterfactual Threshold Lab,
adaptive coaching, solver simulation. Read-Sensitive Reconstruction is a later Review/Drill integration point,
not built here.

## Success threshold (MVP, descriptive)

- Deterministic: identical input → identical record (no LLM classification).
- High coverage on real turns/rivers with complete canonical evidence; honest suppression otherwise.
- Zero result leaks, zero unsupported range claims, zero analyst-LLM workload added.
- Player-useful "what changed / what remained / reassess" copy on a real corpus.
