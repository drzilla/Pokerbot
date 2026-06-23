# REAL_SESSION_FINDINGS

Real corpus: **3 approved raw sessions, 3,609 hands** (`_session_live_test` 943h / 2026-06-04,
`hh_today` 1446h / 2026-06-09, `_session_20260527` 1220h / 2026-05-27). Parsed with the canonical v8.21
`gem_parser`; provenance + per-file SHA-256 in `REAL_CORPUS_PROVENANCE.json`. **Fixtures excluded.**

## Opportunity funnel (`REAL_OPPORTUNITY_BASELINE.json`)

```
3609 hands → 686 reached flop → 135 Hero-PFR flop c-bets → 120 clean single c-bets
  excluded (fail closed): 27 non-SRP · 21 multiway · 0 all-in · 7 no applicable band
  → 65 judgeable vs a complete SRP/HU band
     → 36 compliant (within sanctioned spread/tolerance)
     → 29 off-band nominations (15 gross, 14 moderate)
```

## Bounded one-pass review (`REAL_REVIEWED_QUEUE.json`)

Every genuinely-new nomination reviewed once, from record facts only.

| Terminal verdict | Count |
|---|---|
| **CONFIRMED_MISTAKE** | **0** |
| JUSTIFIED | 5 |
| READ_DEPENDENT | 24 |
| INSUFFICIENT_EVIDENCE | 0 |
| DETECTOR_BUG | 0 |

- **Resolved precision (confirmed / resolved): 0.0**
- **Incremental confirmed mistakes / 100 real hands: 0.0**
- Overlap with another discovery family: 1 / 29. Overlap with the material-loss screen: 1 / 29.
- Analyst workload: ~58 min (29 × 2 min) for **0** confirmed mistakes.

## Why zero confirmed mistakes (the core product finding)

The archetype sizing band is a **range-level** c-bet strategy, not a per-hand prescription. A single hand
inside a mixed/polarized range legitimately uses a non-modal size. So an off-band size is a real *deviation*
but not, on its own, a *result-independent mistake*. Two dominant, defensible patterns account for all 29:

- **Strong hands sizing off the modal size → JUSTIFIED (5).** e.g. `TM6060027674` trips on K-K-K (OOP)
  betting 33% vs an `[66]` band — thin value on a board-trips texture, correct, not a mistake;
  `TM6059850926` / `TM6008014133` two-pair small-bets; `TM6007886506` a set small-betting (trap);
  `TM6060026814` a straight overbetting 100% on K-T-Q (value/protection).
- **Medium/weak hands under-betting dynamic boards → READ_DEPENDENT (24).** The recurring signature is Hero
  c-betting ~33% on middling/dynamic flops (J-9-x, etc.) where the solver band is 75–150%. This is a **real
  recurring tendency**, but each individual hand could be a deliberate pot-control small bet or a genuine
  under-bet leak — confirming needs the range/equity read the packet deliberately does not carry.

**This recurring under-sizing is an AGGREGATE leak, not 29 per-hand mistakes** — and the aggregate is already
owned by the existing `gem_sizing_detector.build_sizing_leak_signals` (fires on ≥8-sample repeated patterns),
which is the correct altitude for it.

## True-positive evidence cards

**None.** There is no confirmed result-independent mistake to card. (This is the honest output; a fabricated
card would violate the no-overclaim rule.)

## False-positive / detector-bug register

| Class | Count | Notes |
|---|---|---|
| DETECTOR_BUG (post-correction) | **0 / 29** | No nomination fired where the chart did not apply. |
| Over-nomination (pre-correction, FIXED) | 4 | In-between-spread sizes on multi-size bands (Defect 3). Removed by the within-spread fix. |
| Chart-misapplication (pre-correction, FIXED) | all fixtures + would-be 3BP/multiway/all-in | Removed by `_chart_applies` (Defect 2). |
| JUSTIFIED (correct nomination, non-mistake) | 5 | Strong-hand deviations — correct to surface, correct to clear. |
| READ_DEPENDENT (correct nomination, undecidable) | 24 | Real deviations needing range/equity. |

Net: after the three corrections, the detector produces **no false confirmed mistakes** — but it also
produces **no confirmed mistakes at all**, at a cost of 29 review items / 3609 hands.
