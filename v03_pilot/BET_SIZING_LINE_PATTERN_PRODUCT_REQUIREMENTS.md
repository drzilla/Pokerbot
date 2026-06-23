# BET_SIZING_LINE_PATTERN_PRODUCT_REQUIREMENTS

Product contract for the v8.21 bounded pilot. Written **before** production code (the spec below was the
build target; `PILOT_DETECTOR_SPEC.md` is its as-built mirror).

## Product objective

Increase **new confirmed postflop mistakes per 100 hands** through a bounded, high-precision bet-sizing
detector, **without** breaking the atomic one-pass, no-calculation analyst workflow. Candidate count is not
success — confirmed, result-independent mistakes are.

## Scope (this pilot)

Exactly one family: **Family A — per-hand flop c-bet sizing mismatch vs the canonical board-archetype
band.** All other charter families are deferred per `CAPABILITY_AND_DUPLICATION_MATRIX.md`.

## R1 — Eligible population (result-independent)

A hand is eligible iff **all** hold, from canonical fields only:

1. Hero is the preflop aggressor (`hand['pfr']`).
2. Hero made a **clean single flop c-bet**: Hero's flop action sequence is exactly one `bets` (so the graded
   node — and the decision_id action index — is unambiguously the c-bet; a later flop call/fold facing a
   raise is a different decision and is excluded).
3. A flop c-bet size (% of pot) exists on `hand['hero_bets']`.
4. ≥3 board cards.
5. The board maps to a **completed** archetype (`gem_textures.classify_archetype`, `confidence == 'complete'`)
   **and** an applicable sizing band exists for `(archetype, side, depth)` (`get_gto_target` non-empty).

Anything failing R1 is **not** a candidate (fail closed) and is counted, never silently dropped.

## R2 — Canonical owners consumed (no parallel calculator)

| Operand | Canonical owner |
|---|---|
| chosen c-bet % of pot | `hand['hero_bets']` (same field `aggregate_compliance` reads) |
| board archetype | `hand['board_archetype']` → fallback `gem_textures.classify_archetype` |
| side (IP/OOP) | `hand['hero_ip']` |
| depth band | `hand['eff_stack_bb']` (same source as the aggregate path) |
| sanctioned sizing band | `gem_textures.get_gto_target(...).sizings_pct` |
| deviation test | `gem_textures.sizing_within_target(actual, targets, ±10pp)` |
| all decision-time facts in the sealed record | `gem_decision_snapshot.build_decision_snapshot` + `build_action_sizing_contract` via `atomic_snapshot` |

No pot/price/stack/SPR/hand-class/equity/EV/range calculator is created. No analyst-side calculation.

## R3 — Evidence tier

`CHART_BACKED` (charter evidence tier 1: "canonical chart / exact completed board-archetype contract").
The packet excerpt key is `chart.flop_cbet_sizing_band` (added once to `EVIDENCE`).

## R4 — Result-independent nomination logic

Given an off-band c-bet (`sizing_within_target` is `False`), classify severity:

- **gross** — `deviation_pp ≥ 25` **AND** (`actual ≥ 2×` the largest **or** `≤ 0.5×` the smallest sanctioned
  size) **AND** a **single-target** (non-dual-strategy) complete band. A deviation this large is beyond a
  plausible mixing artifact → a sizing **error**.
- **moderate** — off-band but not gross, or any **dual-strategy** band (the chart sanctions >1 size) →
  analyst-judged.

Nothing in the nomination uses runout, showdown, net, or prior verdict.

## R5 — Terminal-verdict mapping (the automated baseline; the human analyst re-judges)

- gross → **CONFIRMED_MISTAKE** (`CHART_BACKED`) → promoted to **required**.
- moderate → **READ_DEPENDENT** (`CHART_BACKED`) → **optional** (subject to `optional_cap`, default 8).

## R6 — Suppression / deduplication

- Prior-reviewed nodes (`relationship == ALREADY_REVIEWED_SAME_NODE`, from `final_truth.records`) are
  suppressed by the existing `run_value` filter.
- One family fires at most once per `(hand_id, street, family)`; `build_packet`'s `by_hand` keeps **one
  decision per hand** — a hand already required is never re-nominated.

## R7 — Atomic analyst record

Each candidate seals through `atomic_snapshot` (identical schema/leakage rules as every other decision),
plus a `sizing_assessment` fact block (archetype, side, depth band, actual %, target band, nearest target,
deviation pp, direction, severity, chart confidence/source) merged verbatim so the analyst can cite exact
numbers via `fact_refs: ['sizing_assessment']` and the chart via `evidence_refs: ['chart.flop_cbet_sizing_band']`
— **with zero calculation**.

## R8 — Fail-closed conditions

Emit nothing (and let the snapshot fail closed) when: not PFR · no clean single flop c-bet · <3 board cards
· unknown archetype · non-`complete` chart · no applicable band · within ±10pp tolerance · any core snapshot
operand `None`. Unsupported exact claims degrade to `READ_DEPENDENT` / `INSUFFICIENT_EVIDENCE`, never invented.

## R9 — Workflow preservation

Optional cap and one-pass workflow unchanged. New lower-confidence (moderate) candidates stay **optional**;
only a gross chart-violation is mandatory. `validate_analyst_output` continues to reject unknown/duplicate
ids, out-of-enum verdicts, wrong session/packet binding, unpacketed numeric claims, and cited external
evidence. The semantic audit's `zero_analyst_calculations_required` invariant must hold.

## R10 — Success metrics (reported in `PILOT_PRODUCT_VALUE_METRICS.json`)

eligible opportunities · raw candidates · suppressed-already-reviewed · analyst-reviewed · confirmed new
mistakes · justified · read-dependent · insufficient · detector-bugs · precision (confirmed/resolved) ·
confirmed/100 hands · analyst-minutes per confirmed mistake · packet bytes per confirmed mistake ·
false-positive signatures · incremental deterministic runtime & packet size.

## R11 — Tests

A dedicated suite (`test_sizing_line_pilot.py`) must cover severity classification, every fail-closed branch,
the c-bet node identity, run_value integration, the atomic record + clean semantic audit (no leak / zero
calc), build_packet routing (gross→required, moderate→optional), and `validate_analyst_output` accept/reject.
The existing data-independent suites must not regress.
