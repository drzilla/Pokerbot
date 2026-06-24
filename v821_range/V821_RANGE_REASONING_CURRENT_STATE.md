# V821_RANGE_REASONING_CURRENT_STATE

v8.21 **Range Reasoning** — first module **Runout Transition**. Branch
`feature/v8.21-range-reasoning-foundation` off `main` (`93637eb`); safety tag `v8.21-range-reasoning-base`.

## What works (corrected, validated, and LIVE in the report)

- **Safe, neutral descriptive module** `gem_runout_transition.py`. Per eligible turn/river Hero decision it
  emits objective facts only: best-five category before/after, **proven** hole-card contribution (Hero's
  best-five vs the board-only best-five), `category_changed`, `board_only_or_shared_category`,
  `draw_completed`, `real_draw_missed`, and objective board tags. It never says improved/weakened/counterfeit/
  showdown-value; a shared change states the shared **minimum** category with a hole-card kicker caveat on the
  turn (never "plays the board" — only four community cards exist), and claims *"the board now forms your
  complete best five"* **only** on a river that is *proven* to be Hero's exact best five (`_plays_pure_board`);
  improvement is attributed to Hero only when his hole cards provably contribute. Distinct
  three/four/five-suited and connectivity/four-to-a-straight/straight-on-board wording; player-facing labels
  (no raw enums); compact bold *Insufficient evidence* strategic line (no markdown artifacts). See
  `V821_RUNOUT_TRANSITION_SEMANTIC_CONTRACT.md`.
- **Fail-closed**: any required canonical owner failure / invalid cards / incomplete snapshot → unresolved with
  an exact reason, no factual claims, empty rendered note.
- **LIVE in the report**: `transition_note_text(rec)` is injected into the existing per-street note collection
  in `_split_argument_into_notes` (the hand object is threaded through all four call sites in `sections_xiv.py`)
  via the additive `_attach_runout_transition` finalizer — one note per turn/river street, bound to the first
  hero action (merged if a note already exists), **after** the single-narrative override, rendered by the
  canonical `_md_inline`. Unresolved/all-in render nothing; existing notes / pill numbering / tone are
  preserved; structured TL;DR notes are never corrupted. See `V821_RUNOUT_TRANSITION_REPORT_INTEGRATION.md` and
  `..._LIVE_WIRING_REPORT.md`.
- **Tests**: `test_runout_transition.py` **49/49** (semantics, fail-closed, wheel, no banned wording, render
  through the real `_md_inline`); `test_runout_wiring.py` **29/29** (additive injection, override survival,
  numbering/tone preserved, distinct suit wording, no enum/markdown/range artifacts, no packet entry).
- **Measured pilot** `_v821_runout_pilot.py` (product path) — 3,609 hands → 529 street transitions, 482
  resolved (91%); **MEASURED trust audit all zero**. 281 hole-card-contribute vs 201 board/shared.
- **No baseline regression**: `_test_scratch.py` 2024/2024 (the `_hand_grid.py` freeze pin re-pinned for the
  reviewed wiring), `verify_release.py` exit 0, import smoke OK.

## What is blocked by missing canonical infrastructure (debt)

- **Strategic recommendations** (continue/resize/slow/pivot/abandon) and any range/nut-advantage language —
  blocked by the absent canonical **opponent-range / fold-equity owner** (debt **D1**); always rendered
  *Insufficient evidence*. See `V821_RANGE_REASONING_DEBT_REGISTER.md`.

## Out of scope (unchanged this run)

Opponent ranges, fold equity, equity/EV, continue/resize/pivot recommendations, Range Lens expansion,
Read-Sensitive Reconstruction, new sizing logic, analyst-generated transition commentary.

## Analyst-LLM time

Zero. The module is fully programmatic; nothing enters the analyst packet; the wiring threads only the parsed
hand and adds no analyst decision (proven by the packet before/after comparison in
`V821_RUNOUT_TRANSITION_PERFORMANCE.md`).
