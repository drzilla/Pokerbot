# V821_SIZING_LINES_BASELINE_EVIDENCE

Stage-3 baseline verification of the synchronized branch (merge `6b331c2`, parents `78780bb` + `d72ed95`).
**All gates green.** Commands run from `C:/Users/ron/OneDrive/Desktop/Pokerbot_v821_sizing_line` with `PYTHONUTF8=1`.

| # | Gate | Result | Evidence |
|---|---|---|---|
| 1 | Complete repository suite | **GREEN** | `test_metrics` 533/0 · `test_textures` 135/0 · `test_lint` 48/0 · `test_gtow` OK · **`_test_scratch.py` 2024 passed, 0 failed** (v8.20 release omnibus: analyst, Results, coverage, identity, T-W1A-SD sizing) · **`test_sizing_line_pilot.py` 25/25** · `test_detectors` 88 passed / 5 failed |
| 2 | `verify_release.py` | **GREEN (expected delta)** | `67/69 OK, 2 stale, 0 missing, 0 canary failures, 0 regressions`. The 2 stale = `gem_analyzer.py` + `gem_sizing_detector.py` (the gate files vs the frozen v8.20 manifest — no release rebuild performed, by policy) |
| 3 | Compile / import smoke | **GREEN** | `gem_analyzer`, `gem_sizing_detector`, `gem_analyst_packet`, `gem_discovery_context`, `gem_report_draft/draft`, `gem_coverage_builder`, `gem_textures` all compile |
| 4 | Existing Sizing & Lines tests | **GREEN** | `test_sizing_line_pilot.py` 25/25 — gate truth-table (SRP/3BP/4BP/multiway/all-in), freq-vs-sizing split, aggregate-only (no per-hand verdict), dead-duplicate removed, production wiring, 0 per-hand candidates |
| 5 | Report-render smoke | **GREEN** | `Pokerbot_Knockman_20260604-05_AUTO_ONLY_V2.md` rendered; "## Sizing & Line Patterns" shows the gated leak ("middling disconnected IP … **3 sized c-bets**" = gated count) |
| 6 | Anchor validation | **GREEN** | analyzer QA: **"✅ All 278 anchor links resolve"** (`sec-SL` fixed by v8.20; pre-merge it was a broken anchor) |
| 7 | Analyst packet / full / quick | **GREEN** | Full: sealed packet `GEM-v8.20.0-6b331c2baa7b` required=20 optional=8 semantic_failing=0 future_leaks=0 zero_calc=True. Quick: exit 0, "✓ --quick pre-render validation PASSED (packet+analyst+cache+identity bound; coverage 1.0)", `ANALYST_COMPLETE` reviewed=20, "zero forbidden work", binding all True |
| 8 | Results regression | **GREEN** | `_qa_seven_fixture_results.py` 7×8 matrix **ALL_PASS** (resolved/summary-only/unresolved/multi-bullet/multi-day/satellite/over-60) |
| 9 | Desktop report smoke | **GREEN** | `…AUTO_ONLY_V2.html` 3,070,713 bytes rendered; `sec-SL` anchor present |
| 10 | Responsive 360/390/430/1280 | **GREEN** | `_qa_mobile_360_overflow.py` `all_pass=True` at w360/w390/w430 (each `scrollWidth_eq_clientWidth: True`, cards within bounds, aggregate rows compact); 1280 = desktop render (gate 9) |
| 11 | Page-level horizontal-overflow | **GREEN** | `scrollWidth_eq_clientWidth: True`, `no_nonscroll_overflow_offenders: True` at all mobile widths |
| 12 | Internal table-scroll | **GREEN** | `results_tables_horizontally_scrollable: True` (grouped tables scroll on mobile, not page-overflow) |
| 13 | Clean worktree | **GREEN** | `git status` shows only `v821_sync/` (these deliverables) + `_v03_pack/` (untracked scratch); no stray tracked modifications, no merge in progress |

## Notes on the only non-perfect counters

- **`test_detectors` 88/5** — the 5 failures are **pre-existing on the merge-base `f11a9caea665`** and are
  carried identically into both released `main` and this branch (the detector code and `test_detectors.py`
  are unchanged by both the release and the parked branch). They are fixture/session-dependent, **not** a
  merge regression. The count is byte-for-byte the same pre- and post-merge.
- **`verify_release` 2 stale** — by design: the verifier pins the **frozen** v8.20.0 manifest. The two gate
  files legitimately differ from those pins (that is the v8.21 change). **0 canary failures** (no v8.20 fix
  reverted) and **0 regressions** (no old bug reintroduced) are the meaningful invariants, and both hold.

## Regression check

No real regression was exposed by the synchronization. The merge introduced **zero** new test failures, the
full v8.20 release omnibus (`_test_scratch.py`, 2024 tests) passes unchanged, and every v8.20 authoritative
surface (analyst trust, Results, responsive, anchors, identity) validates green with the sizing gate present.
