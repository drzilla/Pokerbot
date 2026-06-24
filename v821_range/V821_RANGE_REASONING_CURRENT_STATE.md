# V821_RANGE_REASONING_CURRENT_STATE

v8.21 **Range Reasoning** — first module **Runout Transition**. Branch
`feature/v8.21-range-reasoning-foundation` off `main` (`93637eb`); safety tag `v8.21-range-reasoning-base`.

**Status: NOT READY FOR MERGE.** The semantics are corrected and validated; the live report surface is not yet
wired, so the full acceptance is not green.

## What works (corrected + validated)

- **Safe, neutral descriptive module** `gem_runout_transition.py`. Per eligible turn/river Hero decision it
  emits objective facts only: best-five category before/after, **proven** hole-card contribution (Hero's
  best-five vs the board-only best-five), `category_changed`, `board_only_or_shared_category`,
  `draw_completed`, `real_draw_missed`, and objective board tags (paired / flush / four-to-a-straight / wheel
  connectivity / blank). It never says improved/weakened/counterfeit/showdown-value; a shared board change
  reads *"shared by every remaining player"*; improvement is attributed to Hero only when his hole cards
  provably contribute. See `V821_RUNOUT_TRANSITION_SEMANTIC_CONTRACT.md` + `..._CORRECTION_REPORT.md`.
- **Fail-closed**: any required canonical owner failure / invalid cards / incomplete snapshot → unresolved with
  an exact reason, no factual claims, empty rendered note.
- **Tests** `test_runout_transition.py` — **48/48** (shared vs private, board-only categories, wheel, each
  owner forced to fail, one-record-per-street, no future-card leak, no banned wording, render through the real
  `_md_inline` with escaping).
- **Measured pilot** `_v821_runout_pilot.py` (product path) — 3,609 hands → 529 street transitions, 482
  resolved (91%); **MEASURED trust audit all zero** (computed, not assumed). 281 hole-card-contribute vs 201
  board/shared. `RUNOUT_PILOT_METRICS.json` authoritative.
- **No baseline regression**: `_test_scratch.py` 2024/2024, `verify_release.py` exit 0, import smoke OK — the
  report path is untouched on this branch.

## What is NOT done (the remaining blocker)

- **Live report wiring + full acceptance.** Designed precisely (`V821_RUNOUT_TRANSITION_REPORT_INTEGRATION.md`):
  thread `h` into `_split_argument_into_notes` (4 call sites) and inject `transition_note_text` into
  `by_street[turn/river]` after the single-narrative override; it flows through the existing note + `_md_inline`
  pipeline. **Not landed** because it touches a delicate, heavily-revised note builder and requires a full
  re-validation (6-width browser + 30 manual reviews + screenshots + seven-fixture Results + analyst `--quick`
  + packet comparison) that could not be completed and proven green this session. Acceptance ledger:
  `V821_RUNOUT_TRANSITION_ACCEPTANCE_EVIDENCE.md`.

## What is blocked by missing canonical infrastructure (debt)

- **Strategic recommendations** (continue/resize/slow/pivot/abandon) and any range/nut-advantage language —
  blocked by the absent canonical **opponent-range / fold-equity owner** (debt **D1**); always rendered
  *Insufficient evidence*. See `V821_RANGE_REASONING_DEBT_REGISTER.md`.

## Owner decisions

1. Approve landing the report wire (designed) + commission the full browser/manual acceptance to flip to READY.
2. Commission the canonical opponent-range/fold-equity owner (D1) to unblock the strategic layer.

## Analyst-LLM time

Zero. The module is fully programmatic and feeds nothing into the analyst packet; once wired it adds **0**
analyst decisions (to be re-proven by packet comparison on the wired path).
