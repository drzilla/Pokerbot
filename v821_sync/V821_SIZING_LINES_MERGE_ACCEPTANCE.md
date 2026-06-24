# V821_SIZING_LINES_MERGE_ACCEPTANCE

## Outcome

**SIZING & LINES MERGE: PASS — aggregate flop-sizing detection is integrated into main.**

## Commits

| Item | Value |
|---|---|
| Feature branch tip (frozen) | `6dc79a5` (`feature/v8.21-sizing-line-pilot`) |
| Main commit before merge | `d72ed955a868` (= `v8.20.0`) |
| **Merge commit** | `5f1fbfe8487562e8d17a3412ef10e061cace3ffe` (auditable `--no-ff`; parents `d72ed95` + `6dc79a5`) |
| Final pushed main commit | recorded in `V821_SIZING_LINES_MAIN_INTEGRATION_REPORT.md` |
| Pre-sync safety tag | `v8.21-presync-safety` → `78780bb` (retained) |
| `v8.20.0` tag | `d72ed955a868` (unchanged) |
| External audit archive | `V821_SIZING_LINES_EVIDENCE_ARCHIVE.zip` · SHA-256 `f2d18af1f4b53b6406925524805933176bdaffc1dddd5c5c536da5ee42d901f6` (ZIP integrity OK, 12 entries) |

## Surviving product capability (integrated)

Automatic detection of a **repeated flop c-bet sizing habit** — when the player keeps sizing eligible flop
c-bets **too large or too small** on a board class — with a plain-language adjustment, explicitly an
**aggregate** signal and **not** a per-hand mistake verdict. Eligible = **heads-up, single-raised-pot,
non-all-in** flop c-bets, compared to the canonical reference bands. **No extra analyst-LLM workload.**

## Deferred scope (unchanged by this merge)

Per-hand sizing verdicts (rejected: 0 confirmed / 3,609 real hands); turn, river, multiway, 3-bet-pot and
4-bet-pot sizing (blocked — no canonical context-specific reference bands; `gto_texture_archetypes.json` is
flop-c-bet only); preflop all-in/commitment sizing; multi-street line coaching; any range/equity/EV path.

## Suite & verifier — before (feature `6dc79a5`) and after (main `5f1fbfe`)

| Gate | Before (feature) | After (main) |
|---|---|---|
| `test_sizing_line_pilot.py` | 25 / 25 | **25 / 25** |
| `_test_scratch.py` | 2024 / 2024 | **2024 / 2024** |
| `test_metrics` / `test_textures` / `test_lint` / `test_gtow` | 533/0 · 135/0 · 48/0 · OK | **533/0 · 135/0 · 48/0 · OK** |
| `verify_release.py` | 66/69 OK, 3 stale, 0 missing, 0 canary, 0 regression | **66/69 OK, 3 stale, 0 missing, 0 canary, 0 regression** |
| Compile / import smoke | OK | **OK** |
| Real report render | exit 0 | **exit 0** |
| Anchor validation | 278 / 278 resolve | **278 / 278 resolve** |
| Analyst full | sealed, zero_calc, semantic 0, leaks 0 | **sealed `GEM-v8.20.0-5f1fbfe…`, required=20/optional=8, zero_calc** |
| Analyst `--quick` (one run) | PASSED, ANALYST_COMPLETE | **PASSED, ANALYST_COMPLETE** |
| Seven-fixture Results | 7×8 ALL_PASS | **7×8 ALL_PASS** |
| Responsive 360/390/430 + page-overflow + table-scroll | pass | **pass** |
| No sizing decision in packet | 0 | **0** |
| Analyst workload | required=20/optional=8 | **required=20/optional=8 (no increase)** |

The 3 stale files (`gem_analyzer.py`, `gem_sizing_detector.py`, `gem_report_draft/draft.py`) are the intended
v8.21 feature deltas vs the **frozen** v8.20 manifest — the manifest was **not** re-pinned, by policy.

## Known pre-existing failures — independently proven unchanged against current main

| Suite | Result | Proof |
|---|---|---|
| `test_detectors.py` | 88 / 5 | Ran with **main's exact code** (checked out main's 3 changed files in a scratch step) → identical 88/5. Detector modules + the test are byte-identical to main; the 5 are fixture-dependent, not introduced. |
| `test_report_draft.py` | 67 / 3 | Ran with **main's exact code** → identical 67/3 (`test_f1_*` pot-amount: "flop 7.5 != 6.5"). The pot-amount path is byte-identical to main; the 3 are independent of the sizing wording (also confirmed by stashing only the wording files). |

## Trust boundary (held post-merge)

No analyst-packet schema change; **0** per-hand sizing candidates in the packet; no renderer-created strategic
calculation (over/under **direction** is computed in `gem_sizing_detector`, the renderer only displays it); no
range/equity/EV path; no obsolete archived evidence returned to the repository.
