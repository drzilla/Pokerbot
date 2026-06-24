# V821_SIZING_LINES_SYNC_REPORT

Synchronization of the parked Pokerbot v8.21 **Sizing & Lines** branch onto the released **v8.20.0** baseline.

## Identities (verified)

| Item | Value |
|---|---|
| Repository | `https://github.com/drzilla/Pokerbot.git` (remote `origin`) |
| Original parked tip | `78780bb98fde879842ac09109800d43825b1615c` |
| **Safety reference (pre-sync)** | tag **`v8.21-presync-safety`** → `78780bb` (created before any history change; not deleted) |
| Released `main` | `d72ed955a868457f84ea917924aa55db17efecad` |
| `origin/main` | `d72ed955a868…` (matches; fetch attempted — local refs already authoritative) |
| Annotated tag `v8.20.0` | `v8.20.0^{commit}` = `d72ed955a868…` (resolves to the release commit) ✓ |
| Merge-base(branch, main) | `f11a9caea6652132aacf92bad77ab0458b82d41d` (the RC; an ancestor of `main`) |
| **Synchronization method** | **non-fast-forward merge of `main` into the branch** (`git merge --no-ff main`) — parked commits preserved, **no rebase, no force-push** |
| **Synchronized branch tip (merge)** | `6b331c2baa7b4b5f13538b29f11a4cd23621e3bc` (merge commit; parents `78780bb` + `d72ed95`) |
| Branch | `feature/v8.21-sizing-line-pilot` |
| Release-worktree isolation | `main` is checked out in a **separate** worktree (`Pokerbot_v8131_coverage`); never touched ✓ |

## Unique parked commits RETAINED (4)

```
78780bb v8.21 production-path fix: gate the canonical aggregate sizing detector; drop dead duplicate
16507ae v8.21 aggregate-only closeout: remove per-hand sizing family, keep aggregate leak
c813797 v8.21 deep validation: correct sizing detector + retract product-value claim
63b00e7 v8.21 pilot: per-hand flop c-bet sizing detector (Family A)
```
All preserved in history under the merge. Net surviving production footprint of the parked work:
`gem_sizing_detector.cbet_chart_applies` gate (+`_flop_cbet_is_all_in`) and the `gem_analyzer._gto_sizing_pct`
fold-in — **+41 lines across 2 files**.

## Release scope absorbed (14 commits, 20 files, +29072/−25015)

v8.20.0 brought: vendored `phevaluator` self-contained lean runtime + dropped `-rc` build identity; 3-population
sealed analyst packet (`required`/`optional`/**`unresolved`**) + one-pass→report verdict mapping +
`analyst_commentary_from_output` + `--quick` fail-closed hardening + ungraded-debt routing; one canonical
Results state owner + shared filters/grouping + restored Cost/Cash/Net chart + 7-fixture Results harness;
**`sec-SL` anchor fix**; mobile 360px overflow proof; 6 detector false-positive fixes; refreshed `verify_release`
manifest pins.

## Conflicts encountered & resolution (see `V821_SIZING_LINES_CONFLICT_RESOLUTION.md`)

| File both sides changed | Outcome | Why |
|---|---|---|
| `gem_analyzer.py` | **Clean auto-merge, 0 conflicts** | v8.20 edits are all in the `__main__` block (analyst/coverage/identity); the parked gate is in the GTO texture block (`_gto_sizing_pct`, ~L2622). Disjoint hunks. Verified: both present post-merge. |

No other file changed on both sides. `gem_sizing_detector.py` (parked gate) carried verbatim (v8.20 didn't touch it);
`gem_discovery_context.py` / `gem_analyst_packet.py` taken from v8.20 (parked had reverted to byte-identical baseline);
`gem_report_draft/draft.py` taken from v8.20 (incl. `sec-SL` fix).

## Generated files removed / excluded

- `_v03_pack/` (extracted reference pack) — left untracked, **not committed**.
- The dead `_v03_*.py` harnesses + `AGGREGATE_*.json` were already removed in `78780bb`; **not reintroduced**.

## Baseline verification (all green — full evidence in `V821_SIZING_LINES_BASELINE_EVIDENCE.md`)

| Gate | Result |
|---|---|
| Repository suite | `test_metrics` 533/0 · `test_textures` 135/0 · `test_lint` 48/0 · `test_gtow` OK · **`_test_scratch` 2024/0** · **`test_sizing_line_pilot` 25/25** · `test_detectors` 88/5 (5 **pre-existing**, unchanged by merge) |
| `verify_release.py` | **67/69 OK, 2 stale, 0 missing, 0 canary failures, 0 regressions** (the 2 stale = `gem_analyzer.py` + `gem_sizing_detector.py`, i.e. the gate files vs the frozen v8.20 manifest — expected, no release rebuild) |
| Compile/import smoke | 7 core modules compile OK |
| Report render + desktop | `Pokerbot_Knockman_20260604-05_AUTO_ONLY_V2.{md,html}` (3.07 MB HTML); gated "## Sizing & Line Patterns" renders |
| Anchor validation | **✅ All 278 anchor links resolve** (`sec-SL` fixed by v8.20) |
| Analyst full | Sealed packet `GEM-v8.20.0-6b331c2baa7b` required=20 optional=8 semantic_failing=0 future_leaks=0 zero_calc=True |
| Analyst `--quick` | exit 0; validate-before-render PASSED; `ANALYST_COMPLETE` reviewed=20; zero forbidden work; binding all True |
| Results regression | `_qa_seven_fixture_results.py` 7×8 **ALL_PASS** |
| Responsive 360/390/430 | `_qa_mobile_360_overflow.py` **all_pass=True** |
| Page horizontal-overflow | `scrollWidth_eq_clientWidth: True` |
| Internal table-scroll | `results_tables_horizontally_scrollable: True` |
| Clean worktree | only `v821_sync/` (deliverables) + `_v03_pack/` (untracked scratch) |

**Synchronized baseline: GREEN.**

## Remote branch status

Local synchronized branch ready to push to `origin/feature/v8.21-sizing-line-pilot` after the deliverables
commit (push performed per the git boundaries — branch only; **no merge to `main`, no tag change, no release**).
Final pushed tip recorded in the closing response.
