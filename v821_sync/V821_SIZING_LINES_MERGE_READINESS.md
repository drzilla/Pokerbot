# V821_SIZING_LINES_MERGE_READINESS

## Verdict: **MERGE-READY** (as a future decision; not merged here)

The branch `feature/v8.21-sizing-line-pilot` is technically ready to be merged into `main`. Per the git
boundaries, this closeout does **not** merge it — the branch is committed and pushed; the merge decision is
the owner's.

## Readiness criteria

| Criterion | Status |
|---|---|
| Scope locked | ✅ `V821_SIZING_LINES_FINAL_SCOPE.md` — aggregate flop c-bet sizing only; no per-hand/turn/river/line/range/EV |
| Synchronized onto released v8.20.0 | ✅ merge `6b331c2`; clean auto-merge; all 13 sync gates green |
| Feature complete + player-facing | ✅ wording covers all 7 points; renders in a real report; 3 example states proven |
| Tests green | ✅ sizing 25/25, `_test_scratch` 2024/2024; core suites green |
| No regression introduced | ✅ `verify_release` 0 canary / 0 regression; pre-existing failures proven unchanged |
| Fixed defects not reintroduced | ✅ no per-hand family, no `summarize_offband_sizing`, no hardcoded ids, no renderer calc |
| Trust boundary intact | ✅ no analyst schema change; 0 packet candidates; direction computed in detector, not renderer |
| Evidence reconciled & archived | ✅ obsolete JSON externally archived w/ SHA; docs reconciled; superseded banners |
| Documentation authority single & consistent | ✅ FINAL_SCOPE supersedes per-hand docs; `+235`→`+92/−19` corrected |

## Known, expected, non-blocking deltas

1. **`verify_release` shows 3 stale files** (`gem_analyzer.py`, `gem_sizing_detector.py`,
   `gem_report_draft/draft.py`) vs the **frozen v8.20.0 manifest** — these are the intentional v8.21 feature
   changes. **0 missing, 0 canary failures, 0 regressions.** The manifest is **not** re-pinned by policy ("do
   not re-pin/rebuild the v8.20 release merely to remove expected feature-branch deltas"). A real v8.21
   release would re-pin the manifest at release time (out of scope now).
2. **Pre-existing test failures inherited from the baseline**, proven unchanged, not introduced here:
   `test_detectors` 88/5 (fixture-dependent detector controls); `test_report_draft` 67/3 (`test_f1_*`
   pot-amount fixtures). Neither touches Sizing & Lines.

## Footprint (minimal, reviewable)

3 production files, **+92 / −19**. Plus tests (`test_sizing_line_pilot.py`), deliverables (`v821_sync/`),
superseded-banner/doc reconciliations (`v03_pilot/`), and the removal of 10 archived evidence JSON.

## Boundaries honored (will be re-confirmed at closeout)

Do **not**: merge into `main`; tag or release v8.21; modify the v8.20 release worktree/branch or the
`v8.20.0` tag; update the production Claude Chat project; begin Range Reasoning or Runout Transition. The
safety reference `v8.21-presync-safety` → `78780bb` is retained.

## If/when the owner approves a merge

Standard PR of `feature/v8.21-sizing-line-pilot` → `main`; on merge into a release train, re-pin the
`verify_release` manifest for the 3 changed files as part of the release build (not before).
