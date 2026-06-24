# V821_RUNOUT_TRANSITION_FULL_ACCEPTANCE

Certified feature tip: **`330ff77`** (`feature/v8.21-range-reasoning-foundation`). Outcome: **MERGE-READY →
INTEGRATED into `main`** (non-fast-forward merge `d3aa5078`). The descriptive Runout Transition capability is
live in the existing hand-detail report, in both the AUTO_ONLY full render and the analyst-integrated
(`--quick`) render. This document states the single final truth; superseded counts and report-version
references have been removed.

## Capability (as accepted)

On eligible turn/river decisions the report explains what the new card objectively changed, what remains true,
and what to reassess — inside the existing report-note surface. Deterministic and result-independent; **≤ 1
transition note per turn/river street**; no analyst-LLM workload; **0** analyst-packet decisions; no
opponent-range / equity / EV / fold-equity computation; no continue/resize/pivot/abandon recommendation — the
strategic action remains **Insufficient evidence** (debt **D1**: a canonical opponent-range/fold-equity owner);
unresolved/all-in render nothing.

## Gate results (final)

| Gate | Result |
|---|---|
| Runout Transition suite (`test_runout_transition.py`) | **78 / 78** |
| Wiring/integration suite (`test_runout_wiring.py`) | **34 / 34** |
| Complete repository suite (`_test_scratch.py`) | **2024 / 2024** |
| `verify_release.py --project-dir <worktree>` | **[PASS] 69/69 files, 664/664 canaries, 12/12 anti-canaries** |
| Compile / import smoke | OK |
| Seven-fixture Results regression | **PASS** (7×8) |
| Anchor validation | **1,220 static anchors resolve** (0 payload-only) |
| Mobile overflow 360 / 390 / 430 | **pass** |
| Browser acceptance 1280 / 1440 / 1920 (and mobile 360/390/430) | **0 page-level overflow at every width; the note reflows 272→1002 px; never clipped; no sticky overlap** |
| Analyst `--quick` (matching packet) | **PASSED** — packet+analyst+cache+identity bound, coverage 1.0, ANALYST_COMPLETE, zero forbidden work |
| Analyst packet | **0** Runout Transition decisions; module **not referenced** by `gem_analyst_packet.py`; required 34 / optional 8 unchanged before vs after; schema unchanged |
| Wording | **0** invalid flop/turn `plays the board` / `supplied by the board` in the generated HTML + decompressed lazy payloads |
| Manual review (re-evaluated against the corrected rules) | **46 / 46 PASS** |
| Performance | report +~0.2% size, +~0.09 s render, **0** added analyst workload |

## Live proof

- **AUTO_ONLY** full render and the **analyst-integrated** (`--quick`) render both carry the **same** transition
  notes for the same hands: **104 hands** with a note, **0 per-hand mismatch** across the 1,220 common hands,
  **0** within-hand duplication. Notes are embedded in the `deflate-raw+base64` `PB_PAYLOADS.lazyHands` payload
  (decompressed + confirmed) and also appear in the secondary `.md`; all-in / unresolved nodes render nothing.
- The corrected turn shared-board note reads *"The paired board (X) gives every remaining player at least one
  pair; kickers and stronger hands still depend on the hole cards"* — no "plays the board"; the strong *"all
  five community cards now form your complete best five (X)"* is emitted only on a river that `_plays_pure_board`
  proves. Rendered artifacts: `screenshots/runout_note_desktop_1280.html`, `screenshots/runout_note_mobile_390.html`.

## Notes on two gate mechanics (not regressions)

- **`verify_release.py` default invocation** resolves `project_dir` to the *parent* of the script
  (`dirname(__file__)/..`), a packaged-release assumption; in the worktree layout the parent holds no gem files,
  so only `--project-dir <worktree>` is meaningful — **[PASS] 69/69**. The wiring's files plus three
  pre-existing-stale manifest entries (from the main sizing merge that postdates the v8.20.0 manifest) were
  reconciled to the committed baseline so the gate is green.
- The earlier "`--quick` fail-closed on a stale cached analyst JSON" was correct fail-closed behaviour for a
  *mismatched* artifact; a fresh QA analyst output bound to the **current** packet (`packet_hash dae3ea4f…`)
  makes `--quick` pass. The QA analyst output is an integration-coverage fixture, not real analyst judgment.

## Checklist (all satisfied)

corrected semantics ✓ · corrected suit/straight/shared-board wording (no false turn board-play) ✓ · no raw enum
or Markdown artifacts ✓ · live report integration (AUTO_ONLY + analyst-integrated) ✓ · suite green / only
proven-pre-existing items ✓ · six-width browser acceptance ✓ · manual review 46/46 ✓ · matching-packet `--quick`
✓ · 0 added analyst workload / 0 packet decisions ✓ · merged into `main` (`d3aa5078`), feature retained at
`330ff77` ✓.
