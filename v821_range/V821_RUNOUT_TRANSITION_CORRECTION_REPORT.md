# V821_RUNOUT_TRANSITION_CORRECTION_REPORT

Correction of the Runout Transition prototype against the six named blockers. Branch
`feature/v8.21-range-reasoning-foundation`.

## Blocker 1 — Hero-state semantics (FIXED)

Removed `hero_status` improved/weakened, the `counterfeit` tag, and `has_showdown_value`. Added the neutral
factual contract (`best_five_category_before/after`, `category_changed`, `hero_hole_cards_contribute_before/
after`, `board_only_or_shared_category`, `draw_completed`, `real_draw_missed`). Hero contribution is **proven**
by comparing his best-five against the **board-only** best-five (canonical evaluator on the river; board
rank-counts on the turn), never inferred from a shared category rise. Shared-board changes now read *"…shared
by every remaining player."* See `V821_RUNOUT_TRANSITION_SEMANTIC_CONTRACT.md`. Pilot: 201 board/shared vs 281
genuine hole-card contributions, **0** shared-board false-improvement claims measured.

## Blocker 2 — fail closed (FIXED)

`_made_or_fail` / `_draw_or_fail` / `_texture_or_fail` + card/board validation now raise `_EvidenceError`;
`build_transition` returns an unresolved record with an exact reason (`missing_made_hand_evidence`,
`missing_draw_evidence`, `missing_texture_evidence`, `invalid_cards`, `incomplete_decision_snapshot`), **no**
factual claims, confidence `none`, and an empty rendered note. Tests force each owner to raise and assert the
exact reason.

## Blocker 3 — classification (FIXED)

Ace-low straight windows added (`_max_straight_window` evaluates the wheel: A-2-3-4(-5)). `connectivity_decrease`
and `counterfeit` removed. Distinguished `connectivity_increase` (3-in-window) / `four_to_a_straight` (4) /
`straight_on_board` (5) / Hero completing a straight with hole cards (`draw_completed`). `blank` is emitted
only when all evidence resolves and nothing structural or Hero-state changed.

## Blocker 4 — tests (FIXED)

Removed the tautological assertion. `test_runout_transition.py` is now **48 checks, all passing**, exiting
nonzero on any failure: shared-category, pocket-pair-on-paired-board, board-only pair/two-pair, Hero private
improvement vs shared change, wheel connectivity + completion, each canonical owner forced to fail, invalid
cards, incomplete snapshot, one-record-per-street, no-future-card leak, no banned wording, and rendering
through the **real** report note renderer (`gem_report_draft._html._md_inline`) with escaping checks.

## Blocker 5 — measured pilot (FIXED)

`_v821_runout_pilot.py` runs the **product path** (`transitions_for_hand`) and **computes** every trust
metric. On 3,609 real hands → 529 street transitions, 482 resolved (91%): the MEASURED audit is **all zero** —
result-field leakage 0, later-card leakage 0, unsupported range terms 0, unsupported strategic directives 0,
banned strength words 0, shared-board false-improvement 0, static-texture duplication 0, duplicate-per-street
0, accidentally-rendered-unresolved 0. (A substring false-positive — the later card `Th` matching inside
"**Th**e" — was found and fixed with token-bounded matching; the zero is now real.) Avg record ~2 KB, runtime
~0.5 s. `RUNOUT_PILOT_METRICS.json` is authoritative.

## Blocker 6 — live report wiring

See `V821_RUNOUT_TRANSITION_REPORT_INTEGRATION.md` and `V821_RUNOUT_TRANSITION_ACCEPTANCE_EVIDENCE.md` for the
integration design, the wiring, and the acceptance run.

## Net

The descriptive Runout Transition is now **safe**: it states only objective, canonically-sourced facts about
what the card changed, attributes improvement to Hero **only when his hole cards provably contribute**, fails
closed on missing evidence, and explicitly withholds any relative-strength / action call as Insufficient
evidence pending a canonical opponent-range owner.
