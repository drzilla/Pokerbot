# V821_SIZING_LINES_CURRENT_STATE

Parked-state inventory recorded **before** synchronization (Stage 1 gate). Branch
`feature/v8.21-sizing-line-pilot` @ `78780bb`, merge-base with released `main` (v8.20.0 `d72ed955a868`) =
`f11a9caea665`. Net parked production footprint: `gem_analyzer.py` (+8) and `gem_sizing_detector.py` (+33)
— `gem_discovery_context.py` / `gem_analyst_packet.py` were reverted byte-identical to baseline.

## What ALREADY WORKS (and survives v8.20)

- **Chart-applicability gate** `gem_sizing_detector.cbet_chart_applies(hand)` (+ `_flop_cbet_is_all_in`) —
  SRP / heads-up / non-all-in. Decision-time inputs only; no result/equity. `gem_sizing_detector.py` is
  **not** in the v8.20 release diff, so it carries through verbatim. → **STILL_REQUIRED_V821**.
- **Production fold-in** `gem_analyzer._gto_sizing_pct` returns `None` unless `cbet_chart_applies(h)` — gates
  the sizing dimension while leaving the c-bet *frequency* denominator intact. v8.20 left the GTO texture
  block byte-identical (its edits are all in `__main__`), so the gate carries through. → **STILL_REQUIRED_V821**.
- **Aggregate surface** `build_sizing_leak_signals` → `gem_coverage_builder.py:2205` →
  `report_data['sizing_leak_signals']` → `draft._emit_sizing_lines` → "## Sizing & Line Patterns". Unchanged
  by both sides; v8.20 additionally **fixed the `sec-SL` anchor** (`draft.py:716`). → **RETAIN_UNCHANGED**.
- **Tests** `test_sizing_line_pilot.py` (25/25): gate truth-table, freq-vs-sizing split, aggregate-only (no
  per-hand verdict), dead-duplicate removal, production wiring, 0 per-hand candidates/reviews. →
  **STILL_REQUIRED_V821**.

## What is PARTIAL (evidence exists, not surfaced/judged)

- Actual bet/raise size in chips & BB (`action_ledger` amounts) — tracked, never surfaced. → DEFER.
- Turn/river/raise/probe sizing % (`hero_bets` computes flop-cbet only; coarse `s['sizing']` avg) — no chart
  band to judge. → BLOCKED (charts).
- pot_type (SRP/3BP/4BP) and multiway as sizing dimensions — tracked, folded into one bucket; the gate now
  *excludes* non-SRP/multiway from sizing judgment, but per-dimension judging needs charts that don't exist. → BLOCKED.
- SPR / effective-stack copy (`hand['spr']`, `eff_stack_bb_at_decision`) — fields exist, not surfaced. → DEFER.
- Line-pattern sequence (`line_actions` / `hero_street_actions` / `action_ledger`) — encoded, **not** on the
  sizing surface. "Sizing & Line **Patterns**" is currently flop-cbet-sizing only; the "Lines" half is
  aspirational. → DEFER.

## What v8.20 SUPERSEDED / absorbed

- Per-hand sizing family (`assess_flop_cbet_sizing`, `applicable_band`, `_classify_deviation`) — 0 confirmed
  mistakes on 3,609 real hands; already deleted in `78780bb`. **Must not reintroduce.** v8.20 further added a
  third packet population `unresolved`: a no-canonical-node candidate now routes to `unresolved`/debt, not
  `required` — reinforcing the removal. → **SUPERSEDED_BY_V820**.
- `summarize_offband_sizing` standalone aggregate — dead path never called by the report; already removed. →
  **SUPERSEDED_BY_V820**.
- Fixture-era deliverables/JSON (`PILOT_*.json`, `OPPORTUNITY_BASELINE.json`, `CAPABILITY_AND_DUPLICATION_MATRIX.md`,
  `FALSE_POSITIVE_REGISTER.md`, `TRUE_POSITIVE_EVIDENCE_CARDS.md`, `V03_PILOT_PACKAGE.md`, `V03_RAMP_UP_BASELINE.md`,
  `REAL_SESSION_FINDINGS.md`, `V03_DEEP_VALIDATION_PACKAGE.md`) — retained as provenance with superseded banners. → **SUPERSEDED_BY_V820** (kept for audit).
- `AGGREGATE_CLOSEOUT_PACKAGE.md` "+235L" / `BET_SIZING_LINE_PATTERN_PRODUCT_REQUIREMENTS.md` / `PILOT_DETECTOR_SPEC.md`
  per-hand framing — **ADAPT_TO_V820** (reconcile footprint to true net +41L; re-scope to the aggregate gate).

## What remains GENUINELY NEW for v8.21

Only the gate (already implemented). No other slice is unambiguous + safe. Everything else is BLOCKED or DEFER.

## What is BLOCKED_BY_CANONICAL_INFRASTRUCTURE

- Per-hand sizing **verdict** — needs a canonical decision node + analyst one-pass verdict; no decision-level
  per-hand evidence (0/3,609); now routes to `unresolved`/debt.
- Turn/river/3BP/4BP sizing bands — no chart owner (`gto_texture_archetypes.json` is flop-cbet only).
- Second family (turn double-barrel / "wrong barrel") — needs villain continue-range / fold-equity → would
  invent range/equity or leak result.
- Preflop all-in / commitment eligibility ownership — no canonical owner; overlaps the existing v8.20
  preflop-owner debt thread.

## What requires OWNER INPUT (carried to the next-implementation plan)

1. Per-hand sizing evidence vs aggregate-only (recommend **aggregate-only**).
2. Preflop all-in / commitment eligibility ownership (recommend **keep deferred** to the v8.20 preflop-owner thread).
3. Range-reasoning boundary / second family (recommend **affirm the hard lock — none**).
4. Large `REAL_*.json` evidence in-tree (~9k lines) — keep committed vs archive externally (recommend
   **flag, do not prune unilaterally** in the sync).
5. Do a Stage-6 slice now vs stop at green baseline (recommend **stop at green baseline**).

## Generated / untracked — must NOT commit

`_v03_pack/` (extracted reference pack), any `_census_tmp/` scratch. The dead `_v03_*.py` harnesses and
`AGGREGATE_*.json` were already removed in `78780bb` — must not be reintroduced.
