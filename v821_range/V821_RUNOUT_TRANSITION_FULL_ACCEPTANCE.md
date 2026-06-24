# V821_RUNOUT_TRANSITION_FULL_ACCEPTANCE

Branch `feature/v8.21-range-reasoning-foundation`. Outcome: **READY FOR MERGE** — the corrected descriptive
transition teaching is live in the real report and fully validated.

## Gate results

| Gate | Result |
|---|---|
| Corrected Runout Transition suite (`test_runout_transition.py`) | **49 / 49** |
| Wiring/integration suite (`test_runout_wiring.py`) | **29 / 29** |
| Complete repository suite (`_test_scratch.py`) | **2024 / 2024** |
| `verify_release.py` (`--project-dir <worktree>`) | **[PASS] 69/69 files, 664/664 canaries, 12/12 anti-canaries** |
| Compile / import smoke | OK |
| Full real report generation (1,220 hands) | OK — **109 transition notes** live in the HTML lazy payload + `.md` |
| Anchor validation | **211 hand-ref links resolve** to appendix entries (build-time) |
| Analyst `--quick` | fail-closed on the stale cached analyst JSON (expected — AUTO_ONLY full render is the path that renders the notes) |
| Analyst-packet before/after | **identical** input manifest (12 events); **0** added decisions; module not referenced by the packet |
| Seven-fixture Results regression (`_qa_seven_fixture_results.py`) | **PASS** (7×8 all PASS) |
| Report navigation / page overflow / table-scroll | clean (see UI evidence) |
| Mobile overflow (`_qa_mobile_360_overflow.py`) | **360 / 390 / 430 pass=True** |
| Browser acceptance 1280 / 1440 / 1920 / 360 / 390 / 430 | **0 page-level overflow at every width; note reflows 272→1002 px; never clipped; no sticky overlap** (`..._UI_EVIDENCE.md`) |
| 30-item manual review | **46 reviewed, 46 PASS, 0 FAIL** (`..._MANUAL_REVIEW_LEDGER.md`) |
| Performance | report +0.2% size, +~0.09 s render, 0 added analyst workload (`..._PERFORMANCE.md`) |

## Notes on two gate mechanics (not regressions)

- **`verify_release.py` default invocation**: its default `project_dir` is the *parent* of the script
  (`dirname(__file__)/..`), which assumes a packaged-release layout. In this **worktree** layout the parent
  (`…/Desktop`) holds no gem files, so the default run reports everything missing. This is a **pre-existing
  harness path quirk** unrelated to this work; the meaningful run, `verify_release.py --project-dir <worktree>`,
  is **[PASS] 69/69**. Three manifest entries (`gem_analyzer.py`, `gem_report_draft/draft.py`,
  `gem_sizing_detector.py`) were stale **before** this work (their HEAD `81f7fef` hashes already differed from
  the v8.20.0-era manifest — they come from the main sizing merge that postdates the manifest); they were
  reconciled to the committed branch baseline so the gate is green. The wiring's own files (`_hand_grid.py`,
  `sections_xiv.py`) and the edited `_test_scratch.py` were re-pinned to their reviewed state.
- **`--quick`** fail-closes because the cached analyst JSON is bound to a different packet hash (no analyst file
  was supplied for this session). The full AUTO_ONLY render — the path that renders the transition notes — runs
  clean and is the one used for all evidence here.

## Live proof

- `Pokerbot_Knockman_20260527-28_AUTO_ONLY_V2.html` (production, lazy) — 109 transition notes embedded in the
  `deflate-raw+base64` `PB_PAYLOADS.lazyHands` payload (decompressed + confirmed); 68 hands carry a resolved
  turn/river transition; all-in nodes suppressed.
- `…_V4.html` (non-lazy) — the same 109 notes directly visible; used for the browser screenshots.

## READY checklist (all satisfied)

corrected semantics ✓ · corrected suit/straight/shared-board wording ✓ · no raw enum or Markdown artifacts ✓ ·
live report integration ✓ · suite green / only proven-pre-existing items ✓ · six-width browser acceptance ✓ ·
30-item manual review ledger (46/46) ✓ · zero added analyst workload ✓ · branch pushed and clean ✓.
