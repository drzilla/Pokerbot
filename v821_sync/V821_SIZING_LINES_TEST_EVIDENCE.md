# V821_SIZING_LINES_TEST_EVIDENCE

Final test + verifier evidence for the v8.21 Sizing & Lines closeout (wording finalization + evidence
archival), run on the synchronized branch (`feature/v8.21-sizing-line-pilot`, merge base v8.20.0
`d72ed955a868`). `PYTHONUTF8=1`.

| Gate | Result | Notes |
|---|---|---|
| `test_metrics.py` | **533 / 0** | green |
| `test_textures.py` | **135 / 0** | green |
| `test_lint.py` | **48 / 0** | green |
| `test_gtow.py` | **OK** (58) | green |
| `test_sizing_line_pilot.py` | **25 / 25** | the feature gate (truth-table, freq-vs-sizing split, aggregate-only, no per-hand candidate, wiring) |
| `_test_scratch.py` | **2024 / 2024** | v8.20 release omnibus incl. T-W1A-SD-01..09 (sizing detector), analyst, Results, identity |
| `test_detectors.py` | 88 / 5 | the **5 are pre-existing** on the merge base, unchanged by this work (fixture/session-dependent) |
| `test_report_draft.py` | 67 / 3 | the **3 are pre-existing** (`test_f1_*` pot-amount: "flop 7.5 != 6.5") — **proven** by stashing the wording edits: identical 67/3 at the pre-wording state |
| `verify_release.py` | **66/69 OK, 3 stale, 0 missing, 0 canary failures, 0 regressions** | 3 stale = the v8.21 feature files (`gem_analyzer.py`, `gem_sizing_detector.py`, `gem_report_draft/draft.py`) vs the frozen v8.20 manifest — intentional deltas; **no re-pin** by policy |
| Compile / import smoke | **OK** | `gem_sizing_detector`, `gem_report_draft/draft`, `gem_analyzer` |
| Real report render | **exit 0** | `Pokerbot_Knockman_20260604-05_AUTO_ONLY_V2.{md,html}`; new player-facing wording renders (under-sizing leak shown) |
| Anchor validation | **✅ all 278 anchor links resolve** | `sec-SL` valid |
| Analyst full run | **clean** | sealed `GEM-v8.20.0-122a5ae…` required=20 optional=8 semantic_failing=0 future_leaks=0 zero_calc=True |
| Analyst `--quick` (one run) | **exit 0** | validate-before-render PASSED; `ANALYST_COMPLETE` reviewed=20; zero forbidden work; bindings all True |
| Seven-fixture Results regression | **ALL_PASS** (7×8) | `_qa_seven_fixture_results.py` |
| Responsive 360 / 390 / 430 | **all_pass=True** | `_qa_mobile_360_overflow.py` |
| Responsive 1280 | **desktop render OK** | 3.07 MB HTML |
| Page-level horizontal overflow | **pass** | `scrollWidth_eq_clientWidth: True` |
| Internal table-scroll | **pass** | `results_tables_horizontally_scrollable: True` |
| Clean worktree (post-commit) | **yes** | only `_v03_pack/` untracked scratch remains |

## Pre-existing-failure proof

- `test_detectors` 88/5: the detector code and `test_detectors.py` are unchanged by the v8.21 branch and by
  the v8.20 release relative to the merge base; the 5 are inherited fixture failures, not a regression.
- `test_report_draft` 67/3: `git stash` of only the two wording files (`gem_sizing_detector.py`,
  `gem_report_draft/draft.py`) reproduced the **identical 3 `test_f1_*` pot-amount failures** — they are
  independent of the sizing wording (a pot-calculation fixture issue), not introduced here.

## User-facing behavior chain (verified)

`parsed betting actions → eligible flop c-bet → gate (cbet_chart_applies) → aggregate_compliance →
build_sizing_leak_signals → report commentary` — intact. Eligible SRP/HU/non-all-in c-bets counted; excluded
contexts (multiway/3BP/4BP/all-in) not sizing-judged; c-bet **frequency** and **sizing** use **separate**
denominators (gate returns `None` sizing → counted in `n_cbet`, excluded from `sizing_judged_n`); **0**
per-hand candidates in the analyst packet; **no** analyst schema change; **no** renderer calculation (the
over/under direction is computed in the detector). Rendered examples for over-sizing, under-sizing, and
no-signal in `RENDERED_EXAMPLES.md`.
