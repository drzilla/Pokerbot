> ⚠️ **SUPERSEDED by the deep-validation run.** The product-value claims below (the "1 confirmed mistake"
> `TM91000015`, "EXPAND cautiously") are **retracted** — `TM91000015` was a fixture 3-bet-pot all-in
> chart-misapplication. See `V03_DEEP_VALIDATION_PACKAGE.md`, `V03_DEEP_AUDIT_OF_63B00E7.md`, and
> `CORRECTED_CLAIM_MATRIX.md`. Real-data result: **0 confirmed mistakes / 3,609 hands → RECALIBRATE.**

# V03 Bet-Sizing / Line-Pattern Pilot — Implementation & Measurement Package (run 1, superseded)

Pokerbot **v8.21**, branch `feature/v8.21-sizing-line-pilot`, from RC commit `f11a9caea665`.
**Not merged, tagged, released, deployed, or pushed to Claude Chat.** One family implemented:
`flop_cbet_sizing` (Family A — per-hand flop c-bet sizing mismatch vs the canonical board-archetype band).

## Deliverable index

| # | Deliverable | File |
|---|---|---|
| 1 | Ramp-up baseline | `V03_RAMP_UP_BASELINE.md` |
| 2 | Capability / duplication matrix | `CAPABILITY_AND_DUPLICATION_MATRIX.md` |
| 3 | Product requirements | `BET_SIZING_LINE_PATTERN_PRODUCT_REQUIREMENTS.md` |
| 4 | Pilot detector spec (as built) | `PILOT_DETECTOR_SPEC.md` |
| 5 | Opportunity baseline | `OPPORTUNITY_BASELINE.json` |
| 6 | Implementation + changed-file inventory | below + 3 prod files |
| 7 | Pilot candidate queue (sealed atomic records) | `PILOT_CANDIDATE_QUEUE.json` |
| 8 | Reviewed queue (one-pass analyst verdicts) | `PILOT_REVIEWED_QUEUE.json` |
| 9 | Product-value metrics | `PILOT_PRODUCT_VALUE_METRICS.json` |
| 10 | True-positive evidence cards | `TRUE_POSITIVE_EVIDENCE_CARDS.md` |
| 11 | False-positive register | `FALSE_POSITIVE_REGISTER.md` |
| 12 | Packet / runtime cost comparison | `PILOT_COST_COMPARISON.json` |
| 13 | Tests / suite / verifier output | below |
| 14 | Deferred findings | `DEFERRED_FINDINGS.md` |
| 15 | Explicit verdicts + recommendation | below |

## Changed-file inventory (`git diff --stat HEAD`)

```
 gem_analyst_packet.py    |  15 +-   (EVIDENCE excerpt + evidence map + thread packet_facts)
 gem_discovery_context.py |  75 +-   (family_flop_cbet_sizing + review_value branch + run_value wiring)
 gem_sizing_detector.py   | 102 +    (assess_flop_cbet_sizing per-hand complement)
 3 files changed, 189 insertions(+), 3 deletions(-)
```
New (untracked): `test_sizing_line_pilot.py` (36 assertions), `_v03_pilot_run.py` (measurement harness),
`v03_pilot/` (this package). The existing aggregate detector and all other modules are untouched.

## Measurement (in-worktree real-structure fixture corpus, 58 hands)

> The 844-hand June-16 benchmark raw inputs are absent from disk (see `DEFERRED_FINDINGS.md` D1); the
> headline rate below is a **pipeline proof**, not a production population estimate. `_v03_pilot_run.py
> <RESTORED_SESSION_DIR>` regenerates all metrics for the real population once inputs are restored.

| Metric | Value |
|---|---|
| Eligible opportunities (clean flop c-bets, judgeable vs complete band) | 3 |
| Raw candidates | 2 |
| Suppressed (already reviewed) | 0 |
| Analyst-reviewed | 2 |
| **Confirmed new mistakes** | **1** (`TM91000015`, 217% all-in c-bet vs 85% band) |
| Read-dependent | 1 (`TM90000006`, dual-strategy moderate) |
| Justified / Insufficient / Detector-bugs | 0 / 0 / 0 |
| Compliant c-bet correctly NOT flagged | 1 (`TM91000003`) |
| Precision (confirmed / resolved) | 0.50 |
| Precision (non-detector-bug nominations) | 1.00 |
| Confirmed / 100 hands | 1.72 (corpus-limited) |
| Analyst-minutes / confirmed mistake (≈2 min/record) | 4.0 |
| Packet bytes / candidate | ~5,011 (same magnitude as every other discovery decision) |
| Incremental deterministic runtime | within timing noise (≈0%; 3 cheap canonical calls per c-bet) |
| One-pass / no-calc audit | `failing=0`, `future_information_leaks=0`, `zero_analyst_calculations_required=true` |

## Tests / suite / verifier

| Check | Result |
|---|---|
| `test_sizing_line_pilot.py` (new, targeted) | **36 passed, 0 failed** |
| `test_metrics.py` | 533 passed, 0 failed (unchanged) |
| `test_textures.py` | 135 passed, 0 failed (unchanged) |
| `test_lint.py` | 48 passed, 0 failed (unchanged) |
| `test_gtow.py` | 58 tests, OK (unchanged) |
| `test_detectors.py` | 88 passed, **5 failed — identical to the pre-change baseline (no new failures)** |
| `verify_release.py` | `66/69 files OK, 3 stale, 0 missing, **0 canary failures, 0 regressions**` |

**Verifier note:** the 3 "stale" files are exactly the 3 I edited. The verifier hashes against the **frozen
v8.20-rc manifest**; an unreleased pilot is expected to differ on its edited files. The meaningful release
gates — **664/664 canaries present, 12/12 anti-canaries absent, package structure OK** — all pass, i.e. no
fix was reverted and no old bug reintroduced. Re-freezing the manifest is a release action and was **not**
performed (scope lock).

## Explicit verdicts

| Gate | Verdict |
|---|---|
| Ramp-up baseline reliable | **PASS** (with the documented June-16 raw-input gap) |
| Pilot implementation complete | **PASS** — family implemented, integrated through the canonical packet pipeline, 36/36 targeted tests, no suite regression |
| At least one additional genuine mistake found | **PASS** — `TM91000015`, a result-independent flop c-bet over-size, distinct in kind from the v8.20 KQs preflop mistake (corpus-limited; benchmark confirmation pending D1) |
| Reviewed precision acceptable for continued expansion | **PASS (provisional)** — 0 detector-bug FPs, 1/1 chart-true nominations, restraint on dual-strategy bands; provisional pending a larger benchmark population |
| One-pass / no-calculation contract preserved | **PASS** — `zero_analyst_calculations_required=true`, 0 future-info leaks, `validate_analyst_output` accept/reject proven |

## Recommendation — **EXPAND (cautiously), gated on a real-population measurement**

The family is the disciplined, fully-canonical, result-independent per-hand complement the charter asked
for, it preserves every trust/efficiency invariant, and it found a genuine new postflop mistake at
negligible deterministic cost. **Before broad rollout**, run `_v03_pilot_run.py` on a restored 844-hand
benchmark (D1) to confirm precision and confirmed/100 on a real population, and consider the scaling guards
in the FP register (SRP-only scoping, tiny-pot floor, all-in framing). Do **not** add a turn/river sizing
family until turn/river sizing charts exist (D2). No second family is recommended in this pilot.
