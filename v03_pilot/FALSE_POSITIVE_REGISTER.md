> ⚠️ **SUPERSEDED (per-hand pilot era).** False-positive analysis of the rejected per-hand sizing detector.
> The accepted feature is the **aggregate** flop c-bet sizing-leak detector (no per-hand verdicts). Current
> authority: `v821_sync/V821_SIZING_LINES_FINAL_SCOPE.md`. Kept for audit.

# FALSE_POSITIVE_REGISTER

A false positive (FP) for this detector means a `flop_cbet_sizing` candidate that is a **detector error** —
the nomination should not have fired given canonical inputs (a `DETECTOR_BUG`), as distinct from a
chart-true off-band size the analyst clears as `JUSTIFIED`/`READ_DEPENDENT` (those are **correct** nominations
with a non-mistake verdict).

## Observed on the measurement corpus

| Class | Count | Detail |
|---|---|---|
| Detector-bug FPs | **0** | No nominated candidate was a detector error. |
| Chart-true, analyst-cleared (`READ_DEPENDENT`) | 1 | `TM90000006` (dual-strategy moderate under-size) — a correct nomination, analyst-judged, not a mistake. Not an FP. |
| Correctly **suppressed** near-miss (true negative) | 1 | `TM91000003` (broadway_disconnected IP, 36.4% within ±10pp of the 33% band) — **not** nominated. The detector correctly stayed silent. |

**Reviewed FP sample:** the within-tolerance hand `TM91000003` was inspected as the representative
near-miss; the detector's `sizing_within_target` gate correctly excluded it (36.4% is 3.4 pp from a
sanctioned size). No spurious nomination.

## FP-prevention guards (design-level, with the failing-test that pins each)

| Guard | Prevents | Pinned by |
|---|---|---|
| `sizing_within_target` ±10pp tolerance | flagging a near-on-size c-bet | `within tolerance -> None` |
| dual-strategy band never graded `gross` | confirming a size the chart sanctions among several | `dual-strategy never gross (300% vs [33,85,100])` |
| `confidence == 'complete'` required | judging against an incomplete/TODO chart | `incomplete chart -> None` |
| applicable band required (`get_gto_target` non-empty) | judging a depth/side with no reference | `no sanctioned band -> None` |
| archetype must classify (not `unknown`) | judging an unclassifiable board | `unknown archetype -> None` |
| PFR + clean single flop c-bet required | grading a non-c-bet or a contaminated node | `not PFR -> None`, `no flop c-bet -> None` |
| gross = ≥25pp **and** ≥2×/≤0.5× the band | auto-confirming a mixing-range deviation | `moderate (40% vs [25])` stays READ_DEPENDENT |
| `atomic_snapshot` fail-closed on missing operand | emitting a half-resolved record | `semantic audit: 0 failing` |

## Known FP signatures to watch when scaling (not yet observed)

1. **All-in c-bets graded as "sizing".** A gross over-size that is also all-in (e.g. `TM91000015`) is
   simultaneously a stack-off; the size finding is valid but the analyst should note the over-commitment
   framing. Watch for spots where a near-all-in pot-committed c-bet is technically "off-band" but forced.
2. **Tiny-pot percentage inflation.** A small absolute bet into a tiny flop pot can read as a high % (the
   217% here is partly this). Decision-time `pot_before_bb` is in the record so the analyst can sanity-check
   the absolute size; consider a future `min_pot_before_bb` floor if scaling shows noise.
3. **3-bet/4-bet-pot c-bets vs single-raised-pot charts.** The archetype band is calibrated for SRP range
   c-bets; a 3BP c-bet may legitimately differ. `pot_type` is available on the hand — a future refinement
   could scope the family to SRP only or add a 3BP band.

These are logged for the expansion decision; none is an FP on the current corpus.
