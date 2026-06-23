> ➡️ **Followed by the aggregate-only closeout.** This package recommended `RECALIBRATE`; that recalibration
> is now executed — the per-hand family is removed and the sizing signal kept in aggregate form only. Final
> disposition: `AGGREGATE_CLOSEOUT_PACKAGE.md` (verdict `KEEP_AGGREGATE_ONLY`). The real-population evidence
> below remains valid and is what drove the closeout.

# V03 Deep Validation, Real-Population Proof & Safe-Expansion Package

Pokerbot v8.21 · branch `feature/v8.21-sizing-line-pilot` · continued from `63b00e7`.
**Not merged, pushed, tagged, released, or sent to Claude Chat.**

## Headline

The first pilot's product-value claim does **not** survive real-data validation. On **3,609 real hands**
across 3 approved sessions, the corrected per-hand sizing detector produces **0 confirmed mistakes**. The
prior "1 confirmed mistake" (`TM91000015`) was a **fixture, 3-bet-pot, all-in** chart-misapplication and is
**retracted**. Three implementation defects were found and corrected. No second family qualifies.

## Deliverable index

| # | Deliverable | File |
|---|---|---|
| 1 | Deep audit of `63b00e7` | `V03_DEEP_AUDIT_OF_63B00E7.md` |
| 2 | Corrected first-run claim matrix | `CORRECTED_CLAIM_MATRIX.md` |
| 3 | Real-corpus provenance manifest | `REAL_CORPUS_PROVENANCE.json` |
| 4 | Real-session opportunity baseline | `REAL_OPPORTUNITY_BASELINE.json` |
| 5 | Real-session candidate queue | `REAL_CANDIDATE_QUEUE.json` |
| 6 | Reviewed queue | `REAL_REVIEWED_QUEUE.json` |
| 7 | True-positive evidence cards | `REAL_SESSION_FINDINGS.md` (none — 0 confirmed) |
| 8 | False-positive / detector-bug register | `REAL_SESSION_FINDINGS.md` |
| 9 | Second-family safety assessment | `SECOND_FAMILY_SAFETY_ASSESSMENT.md` |
| 10 | Second-family spec + implementation | **NOT IMPLEMENTED** (see #9) |
| 11 | Semantic-audit + mutation evidence | `test_sizing_line_pilot.py` (40/40) + below |
| 12 | Runtime / packet / workload comparison | below + `REAL_PRODUCT_VALUE_METRICS.json` |
| 13 | Full test / verifier results | below |
| 14 | Patch / diffstat / commit list | below |
| 15 | Final verdicts + recommendation | below |

## Corrections applied this run (3 files)

1. **Verdict ownership** — detector no longer assigns `CONFIRMED_MISTAKE`; it NOMINATES (gross=high-confidence
   → required review; moderate → optional). Analyst owns the terminal verdict. `run_value` confirms 0 sizing.
2. **Chart applicability** — `_chart_applies`: fail closed unless heads-up single-raised-pot, non-all-in.
3. **Multi-size band spread** — a size within `[min,max]` of a multi-size band is compliant (no over-nomination).

## Real-population measurement

| Metric | Value |
|---|---|
| Real hands | 3,609 (3 approved sessions; fixtures excluded) |
| Judgeable c-bet opportunities | 65 |
| Off-band nominations | 29 (15 gross, 14 moderate) |
| **CONFIRMED_MISTAKE** | **0** |
| JUSTIFIED / READ_DEPENDENT / INSUFFICIENT / DETECTOR_BUG | 5 / 24 / 0 / 0 |
| Resolved precision (confirmed/resolved) | **0.0** |
| Confirmed mistakes / 100 real hands | **0.0** |
| Overlap (other discovery family / material-loss screen) | 1 / 1 |
| Analyst workload | ~58 min for 0 confirmed mistakes |
| Incremental discovery runtime | +9.8 ms (+10.9%) over 3,609 hands; ~5.3 KB/record |

## Tests / verifier

| Check | Result |
|---|---|
| `test_sizing_line_pilot.py` (40 adversarial assertions) | **40 passed, 0 failed** |
| `test_metrics` / `test_textures` / `test_lint` / `test_gtow` | 533 / 135 / 48 / 58 — all pass (unchanged) |
| `test_detectors` | 88 passed, **5 failed — pre-existing, unchanged** (no new failures) |
| `semantic_audit` over real records | `failing=0`, `future_information_leaks=0`, `zero_analyst_calculations_required=true` |
| `verify_release` | `66/69 OK, 3 stale, **0 canary failures, 0 regressions**` (the 3 stale = the 3 edited files vs the frozen v8.20-rc manifest; not re-frozen — no release) |

## Diffstat (this run, vs `63b00e7`)

```
 gem_analyst_packet.py    |  14 +-   (force-required gross nomination, not confirmed)
 gem_discovery_context.py |  29 +-   (review_value: nominate not auto-confirm)
 gem_sizing_detector.py   |  43 +-   (SRP/HU/non-all-in gate + within-spread precision fix)
 test_sizing_line_pilot.py| 246 +-   (40 adversarial assertions, corrected expectations)
 v03_pilot/*              (deep-validation deliverables; run-1 fixture outputs refreshed to 0)
```
Whole pilot vs `f11a9ca` (v8.20-rc): 3 prod files, +240 / −4.

## Final verdicts

| Gate | Verdict |
|---|---|
| `63b00e7` implementation trustworthy | **FAIL (as committed)** — sound seam, but it auto-confirmed a fixture 3BP all-in hand and misapplied the SRP chart. Corrected this run; the **corrected** seam is trustworthy. |
| Prior "genuine mistake found" valid on real data | **FAIL** — `TM91000015` is a fixture chart-misapplication; 0 confirmed on 3,609 real hands. |
| Sizing detector production-value proven | **FAIL** — 0 confirmed mistakes / 3,609 real hands; resolved precision 0.0. |
| Second family safe and useful | **NOT IMPLEMENTED** — no confirmable turn family exists without invented equity/range or result leakage; the safe slice is already covered. |
| One-pass / no-calculation preserved | **PASS** — semantic audit clean, zero analyst calc, validator binding intact, no leakage. |

## Recommendation — **RECALIBRATE**

The corrected detector is **safe** (fails closed correctly, no leakage, analyst owns the verdict) and surfaces
**real off-band sizes**, but per-hand sizing deviations are **not confirmable individual mistakes** (the
archetype band is a range-level strategy). It found **0** confirmed mistakes on real data while adding ~29
review items per 3,600 hands.

Recalibrate its role rather than expand or fully reject:

1. **Do not treat the per-hand detector as a confirmed-mistake engine.** It is, at best, an optional
   low-confidence READ_DEPENDENT review aid; keep it off the required/confirmed path (already done — it no
   longer auto-confirms).
2. **Route its signal to the existing AGGREGATE detector**, which is the correct altitude for sizing leaks
   (the real value here is the *recurring* under-sizing of dynamic middling boards, not 29 per-hand mistakes).
3. **Do not add a second family** (turn double-barrel rejected as unsafe/duplicative).
4. Before any production reliance, gate harder (it currently emits ~0.8 nominations / 100 hands, all
   read-dependent) or disable per-hand emission and rely on the aggregate.

This run **corrects** the earlier overclaim: the sizing/line capability, as a *confirmed-mistake* source, is
**not** justified on real data. The companion conclusion to RECALIBRATE is **KEEP_SIZING_ONLY** in the narrow
sense of "add no second family."
