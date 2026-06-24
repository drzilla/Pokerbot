# PRODUCTION_PATH_VERIFICATION (FINAL)

Question: is `summarize_offband_sizing()` invoked by the normal canonical report pipeline, and does its
safety-gated aggregate finding appear in an ordinary generated Pokerbot report?

## Answer: it was NOT integrated — now corrected to one canonical, gated production path

### Finding (before this change)

`summarize_offband_sizing()` was called **only** by `test_sizing_line_pilot.py` and the `_v03_aggregate_closeout.py`
harness — **never** by the report pipeline. The actual production aggregate sizing surface is
`build_sizing_leak_signals`, wired:

```
gem_analyzer GTO block → gem_textures.aggregate_compliance → stats['texture_gto_findings']
  → gem_coverage_builder.py:2205  build_sizing_leak_signals(...)  → report_data['sizing_leak_signals']
  → gem_report_draft/draft.py:702  _emit_sizing_lines  →  "## Sizing & Line Patterns"
```

So `summarize_offband_sizing` was a **duplicate / dead** aggregate implementation, and its SRP / heads-up /
non-all-in safety gates were absent from the real report path (the production sizing-leak signal still
judged 3BP / multiway / all-in c-bets — the same chart-misapplication the deep validation flagged).

### Correction (minimal)

1. **Folded the gate into the production path.** `gem_analyzer`'s `_gto_sizing_pct(h)` now returns `None`
   when `gem_sizing_detector.cbet_chart_applies(h)` is false (not SRP, multiway, or all-in). Because
   `aggregate_compliance` only adds a hand to `sizing_hands` when sizing is non-None, this gates the
   **sizing** dimension while leaving the **c-bet frequency** denominator (`n_cbet`) untouched. One canonical
   aggregate path; no new sizing math.
2. **Removed the dead duplicate.** Deleted `summarize_offband_sizing`, `assess_flop_cbet_sizing`,
   `applicable_band`, `_classify_deviation`, `_depth_tier`, and the per-hand thresholds from
   `gem_sizing_detector.py`. The only public sizing surfaces left are `build_sizing_leak_signals` (untouched)
   and the new `cbet_chart_applies` gate. Removed the now-dead `_v03_*` measurement harnesses and the
   `AGGREGATE_*.json` snapshots that the standalone summary produced.

Net production diff vs pre-pilot `f11a9ca`: `gem_sizing_detector.py` (+gate, build_sizing_leak_signals
untouched) and a `_gto_sizing_pct` gate in `gem_analyzer.py`. `gem_discovery_context.py` and
`gem_analyst_packet.py` remain byte-identical to baseline.

### Real report proof

`PYTHONUTF8=1 GEM_ANALYST_MODE=0 python gem_analyzer.py ".../GEM 20260527/_session_live_test" Knockman`
→ `/mnt/user-data/outputs/Pokerbot_Knockman_20260604-05_AUTO_ONLY_V1.{md,html}`. The rendered
**"## Sizing & Line Patterns"** section (see `PRODUCTION_REPORT_EXCERPT.md`):

> Flop c-bets off-size on middling disconnected boards (IP) — aggregate · Hero c-bet 33%, 60% vs the
> 100%/125%/150% band · **Sizing compliance 0.0% on 3 sized c-bets** · "not a per-hand verdict … not graded
> mistakes."

The **3** sized c-bets is the gated (SRP/HU/non-all-in) count, confirming the gate is live in the report.

### Per-session gated leak signals (production path, 3 approved sessions)

| Session | Hands | Gated sizing-leak signals (judged / compliance) |
|---|---|---|
| `_session_live_test` (06-04/05) | 943 | middling_disconnected IP (3 / 0%) |
| `hh_today` (06-09) | 1446 | ace_high_coordinated IP (5 / 40%), middling_disconnected IP (5 / 0%) |
| `_session_20260527` (05-27) | 1220 | ace_high_coordinated IP (7 / 57%), middling_disconnected IP (6 / 17%) |

`middling_disconnected IP` under-sizing is the robust recurring coaching leak — present in **all three**
sessions, and now in the canonical report.

## Requirements compliance

| Requirement | Status |
|---|---|
| Zero per-hand analyst candidates | ✅ `run_value` emits none; `build_packet` has no sizing decisions |
| Zero additional analyst reviews | ✅ aggregate signal only; no required/optional items |
| No individual confirmed-mistake labels | ✅ "aggregate pattern … not a per-hand verdict … not graded mistakes" |
| One canonical aggregate sizing implementation | ✅ `build_sizing_leak_signals` only; duplicate removed |
| No merge / push / release / deploy | ✅ local commit only |

## Tests / verifier

- `test_sizing_line_pilot.py` (production-path): **25 passed, 0 failed** — gate, frequency-preserving sizing
  gating, aggregate-only signal, single implementation, production wiring, zero per-hand candidates.
- No regression: `test_metrics` 533 · `test_textures` 135 · `test_lint` 48 · `test_gtow` 58 ·
  `test_detectors` 88/5 (pre-existing).
- `verify_release`: see commit (stale files = the 2 edited production files vs the frozen v8.20-rc manifest;
  0 canary failures, 0 regressions).
