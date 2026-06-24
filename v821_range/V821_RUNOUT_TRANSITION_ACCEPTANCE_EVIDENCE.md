# V821_RUNOUT_TRANSITION_ACCEPTANCE_EVIDENCE

Honest acceptance ledger. Branch `feature/v8.21-range-reasoning-foundation`. Outcome: **NOT READY** — the
semantics are corrected and validated, but the live report surface is not yet wired and the full acceptance
(browser + manual) is therefore not green.

## PASSED (this session)

| Gate | Result |
|---|---|
| Corrected Runout Transition tests (`test_runout_transition.py`) | **48 / 48**, nonzero exit on failure |
| Neutral-semantics correctness (shared vs Hero contribution, board-only categories, wheel) | covered by tests |
| Fail-closed (made/draw/texture/invalid-cards/incomplete-snapshot) | each owner forced to fail → exact reason |
| Render through the REAL note renderer `_md_inline` + escaping | passes |
| Measured pilot audit (`_v821_runout_pilot.py`, product path) | 3,609 hands → 529 transitions, 482 resolved (91%); **MEASURED audit all zero** |
| Baseline suite `_test_scratch.py` | **2024 / 2024** |
| `verify_release.py` | exit 0 (stale-feature warnings only, allowed) |
| Import / compile smoke | OK (module + report modules import) |
| Analyst-packet workload | **0** added (module feeds nothing into the packet; not yet wired) |
| Runtime / record size | ~0.5 s / 529 transitions; ~2.0 KB per record |

## NOT YET RUN — requires the live wire first (Blocker 6)

These are part of the full acceptance but are meaningful only once the block is rendered into the report, which
is not done (see `V821_RUNOUT_TRANSITION_REPORT_INTEGRATION.md`):

- Real full report generation **with the block visible**.
- One analyst `--quick` + analyst-packet comparison proving **0** added decisions on the wired path.
- Anchor checks / seven-fixture Results regression **with the wire in place**.
- Browser checks at **1280 / 1440 / 1920 / 360 / 390 / 430**, zero page-level overflow, no sticky overlap,
  readable blocks desktop + mobile.
- Desktop + mobile **screenshots**.
- **≥30 manually-reviewed** real rendered transitions (shared-board changes, Hero private improvements, paired
  boards, flush cards, four-flush boards, straight cards, wheels, blanks, draw misses, multiway, 3-bet pots,
  unresolved/suppressed).
- Before/after report-size and runtime deltas on the wired report.

## Why NOT READY (not a partial green)

The brief is explicit: *"It is ready only when the semantics are safe AND the actual report surface is green …
Do not call the workstream ready merely because the standalone module and fixtures pass."* The wire touches a
delicate, heavily-revised note builder across four call sites and requires a full multi-width browser + manual
acceptance to prove green. That could not be completed and proven this session, so the report surface is not
green and the honest verdict is **NOT READY** with the wire named as the single remaining blocker. **`main`,
`v8.20.0`, the Sizing & Lines branch, and all safety tags are unchanged.**

## What a follow-up needs to do

Land the wire exactly as specified in `V821_RUNOUT_TRANSITION_REPORT_INTEGRATION.md`, then run every gate in
the "NOT YET RUN" list to green, capture the screenshots and the 30-hand manual review, and only then flip the
verdict to READY FOR MERGE.
