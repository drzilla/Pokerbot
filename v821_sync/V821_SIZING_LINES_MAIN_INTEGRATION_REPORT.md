# V821_SIZING_LINES_MAIN_INTEGRATION_REPORT

Final main-branch integration of the v8.21 **Sizing & Lines** feature.

## Integration topology

| Item | Value |
|---|---|
| Repository | `drzilla/Pokerbot` (`origin`) |
| Feature branch (frozen) | `feature/v8.21-sizing-line-pilot` @ **`6dc79a5`** |
| Main before merge | **`d72ed955a868`** (= tag `v8.20.0`; `origin/main` had advanced **0** commits — no reconciliation needed) |
| Merge method | auditable **non-fast-forward** (`git merge --no-ff`), in the isolated `main` worktree (`Pokerbot_v8131_coverage`) |
| **Merge commit** | **`5f1fbfe8487562e8d17a3412ef10e061cace3ffe`** (parents `d72ed95` + `6dc79a5`) |
| Final pushed main commit | (this state-record commit on top of the merge — see closing) |
| History preserved | yes — `5f1fbfe → 6dc79a5 → 122a5ae → 6b331c2(merge v8.20) → 78780bb → 16507ae → c813797 → 63b00e7`. No squash; parked pilot history + archive-removal trail intact. |

## Exact product capability now in main

Pokerbot automatically detects a **repeated flop c-bet sizing habit** and tells the player to bet bigger or
smaller. Scope (locked): heads-up, single-raised-pot, non-all-in flop c-bets; canonical reference-band
comparison; aggregate too-big / too-small pattern per board class; plain-language adjustment; **not** a
per-hand verdict; fully programmatic, **no extra analyst-LLM workload**.

Production chain (verified intact on main):
```
gem_parser actions → gem_analyzer._gto_sizing_pct [GATE gem_sizing_detector.cbet_chart_applies]
  → gem_textures.aggregate_compliance → gem_sizing_detector.build_sizing_leak_signals
  → report_data['sizing_leak_signals'] → gem_report_draft "## Sizing & Line Patterns" (anchor sec-SL)
```
Excluded from sizing judgment (verified): multiway, 3-bet pots, 4-bet pots, all-in flop bets.

Footprint vs v8.20.0: **+92 / −19** across `gem_analyzer.py` (+8), `gem_sizing_detector.py` (+67/−10),
`gem_report_draft/draft.py` (+17/−9). `gem_discovery_context.py` / `gem_analyst_packet.py` unchanged (no
schema change).

## Exact deferred scope

per-hand sizing verdicts (rejected); turn / river / multiway / 3-bet-pot / 4-bet-pot sizing (need canonical
context-specific reference bands); preflop all-in eligibility; multi-street line coaching; range / equity / EV.
Future expansion of Sizing & Lines requires **canonical context-specific reference bands** first.

## Archive

`V821_SIZING_LINES_EVIDENCE_ARCHIVE.zip` (outside the repo) · SHA-256
`f2d18af1f4b53b6406925524805933176bdaffc1dddd5c5c536da5ee42d901f6` · 10 obsolete per-hand JSON +
README + per-file manifest. Repository docs reference it by filename + SHA; not runtime authority. None of
the archived files returned to the repo on merge.

## Suite & verifier (post-merge on main)

sizing 25/25 · `_test_scratch` 2024/2024 · metrics 533 / textures 135 / lint 48 / gtow OK · `verify_release`
66/69 OK, 3 stale (the 3 feature files), **0 missing, 0 canary failures, 0 regressions** · compile OK · report
render exit 0 · **278/278 anchors** · analyst full sealed (`5f1fbfe`, zero_calc) · one `--quick` ANALYST_COMPLETE
· Results 7×8 ALL_PASS · responsive 360/390/430/1280 pass. Pre-existing `test_detectors` 88/5 and
`test_report_draft` 67/3 proven identical on main's exact code.

## Remote Git confirmation

- `feature/v8.21-sizing-line-pilot` remains at `6dc79a5` (local = `origin`); remote branch retained.
- `main` pushed to `origin/main` (final tip in the closing of this report / the closeout response).
- `v8.20.0` tag unchanged at `d72ed955a868`; **no `v8.21.0` tag created**; safety tag `v8.21-presync-safety`
  retained at `78780bb`.

## Project state

Aggregate flop c-bet sizing is **complete and merged into main**. Business value: repeated too-big / too-small
flop-sizing habits are now detected automatically, with a clear adjustment and no extra analyst time. Per-hand
sizing verdicts remain rejected; preflop / turn / river / multiway / 3BP / 4BP sizing remain deferred behind
canonical reference bands.

## Is main clean and ready for the next workstream?

**Yes.** Both worktrees clean (except `_v03_pack/` untracked scratch); gates green; no open sizing scope.
Recommended next workstream: commission the canonical turn/river/3BP/4BP/multiway sizing **reference-band
owner** (the sole blocker to extending this feature). Do not start Range Reasoning or Runout Transition here.
