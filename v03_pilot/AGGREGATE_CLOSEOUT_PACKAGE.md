# V03 Aggregate-Only Recalibration — Closeout Package (FINAL)

Pokerbot v8.21 · branch `feature/v8.21-sizing-line-pilot` · continued from `c813797`.
**Not merged, pushed, tagged, released, deployed, or sent to Claude Chat.**

This is the final V03 closeout. The deep validation proved the per-hand sizing detector finds **0 confirmed
mistakes** on real data; this run **removes it from the analyst queue** and keeps only the **safe aggregate
leak signal**.

## What changed (clean footprint)

The per-hand sizing family is **fully removed** from the analyst pipeline. `gem_discovery_context.py` and
`gem_analyst_packet.py` are now **byte-identical to pre-pilot `f11a9ca`** (the discovery families and packet
are unchanged). The **entire net production change is `+235` lines in `gem_sizing_detector.py`**:

- the safety-corrected per-hand assessment (`applicable_band` + `assess_flop_cbet_sizing`) — SRP-only,
  heads-up-only, non-all-in-only, within-band-spread compliant, analyst-owned verdicts, no result/equity;
- a new **aggregate** rollup `summarize_offband_sizing(hands)` — counts/rates by texture/side/depth/direction,
  emits actionable leak signals, with representative hands as **examples only**.

Safety corrections from `c813797` are **preserved** (and are now the gate for every opportunity):
SRP-only · heads-up only · non-all-in only · within-band sizes compliant · analyst owns terminal verdicts ·
no future/result leakage · no alternate calculations.

| File | vs `f11a9ca` | Note |
|---|---|---|
| `gem_sizing_detector.py` | +235 | assess (safe) + aggregate summary; existing `build_sizing_leak_signals` untouched |
| `gem_discovery_context.py` | **0 (reverted)** | per-hand family removed; baseline family set restored |
| `gem_analyst_packet.py` | **0 (reverted)** | sizing evidence/routing removed; packet restored to baseline |

## Aggregate output (real corpus: 3 approved sessions, 3,609 hands)

`AGGREGATE_SIZING_SUMMARY.json` — opportunities **70**, off-band **31 (44%)**, **27 under / 4 over**.

**Actionable recurring leak found (1):**
> *Hero under-sized **13 of 14** c-bets (**93%**) on **middling-disconnected boards IP** vs the sanctioned
> `[100, 125, 150]` band; move sizing toward the band.* Examples: `TM6039246536`, `TM6040364522`,
> `TM6040282339` (examples, **not** confirmed mistakes).

This teaches a genuine, coachable tendency (systematic under-sizing of dynamic IP boards) — the exact thing
an aggregate is for, and the thing the per-hand detector could not confirm.

## Contract compliance (`summarize_offband_sizing`)

| Requirement | Status |
|---|---|
| Zero additional mandatory analyst reviews | ✅ `creates_mandatory_analyst_reviews = 0` |
| Does not label individual hands confirmed mistakes | ✅ `labels_confirmed_mistakes = false`; examples only |
| No results / showdown / invented ranges / equity / EV | ✅ `uses_results_or_equity = false`; canonical inputs only |
| Fails closed when chart applicability uncertain | ✅ non-SRP / multiway / all-in / unknown / incomplete → not an opportunity |

## Overlap with the existing aggregate sizing detector (`AGGREGATE_OVERLAP.json`)

The existing `build_sizing_leak_signals` (over `texture_gto_findings`) fires **3** signals on this corpus; the
recalibrated summary fires **1**. They **share** the headline `middling_disconnected | ip` leak — but the
existing one judged it over **20 ungated** c-bets (it does not gate SRP/HU/all-in and matches discrete
points), whereas the recalibrated version judged **14 clean** SRP/HU/non-all-in c-bets. The existing
detector's other 2 signals are thin OOP buckets (4–5 judged) that the safe gating correctly drops.

**Conclusion:** the recalibrated summary is a **precision-improved, safety-gated** refinement of the existing
aggregate signal. The headline leak is real and already (over-)reported by the existing aggregate.
**Recommended action: fold the recalibrated gates (SRP/HU/non-all-in/within-spread) into the existing
aggregate detector** rather than maintain a parallel rollup.

## Before / after cost & workload (`AGGREGATE_COST_COMPARISON.json`)

| | v8.20 baseline | 63b00e7 (per-hand, uncorrected) | c813797 (per-hand, corrected) | **Aggregate-only (this)** |
|---|---|---|---|---|
| Mandatory analyst reviews | 0 | auto-CONFIRMED (false) | up to 29 (0 confirmed) | **0** |
| Analyst-packet sizing records | 0 | per-hand | 29 (~5.3 KB each) | **0** |
| Confirmed-mistake claims | 0 | 1 (false) | 0 | **0** |
| Deterministic cost | — | — | +9.8 ms discovery | summary 0.0065 s / 3,609 hands; run_value back to baseline 0.14 s |

## Tests / verifier

- `test_sizing_line_pilot.py` (aggregate-only): **34 passed, 0 failed** (applicability gates, deviation
  classification, aggregate rollup, leak-signal, removal from run_value/build_packet, no-leak/no-review contract).
- `test_metrics` 533 · `test_textures` 135 · `test_lint` 48 · `test_gtow` 58 — all pass.
- `test_detectors` 88/5 — the 5 are pre-existing on the clean tree (unchanged).
- `verify_release`: **68/69 OK, 1 stale, 0 canary failures, 0 regressions** — only `gem_sizing_detector.py`
  differs from the frozen v8.20-rc manifest (discovery + packet are byte-identical to baseline again).

## FINAL VERDICT — `KEEP_AGGREGATE_ONLY`

The per-hand sizing/line detector is **rejected as a confirmed-mistake source** (0/3,609 real hands) and
**removed from required and optional analyst review**. The sizing signal is **kept in aggregate form only**:
it surfaces one genuine, actionable, result-independent coaching leak (under-sizing dynamic IP boards) at
**zero analyst-review cost** and with **no per-hand mistake labels**. No second family is added.

Not `REJECT_ENTIRELY` because the aggregate signal teaches a real recurring leak and the safety gates are a
net improvement to the existing aggregate detector. Recommended next step (out of scope here): merge the
recalibrated gates into the existing aggregate reporting and retire the standalone per-hand path.
