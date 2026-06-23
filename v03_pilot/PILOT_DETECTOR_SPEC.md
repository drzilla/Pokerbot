# PILOT_DETECTOR_SPEC (as built)

Family **`flop_cbet_sizing`** — per-hand flop c-bet sizing mismatch vs the canonical board-archetype band.

## Changed files (3 production files, +189 / −3)

| File | Change |
|---|---|
| `gem_sizing_detector.py` | **+** `assess_flop_cbet_sizing(hand)` + `_flop_cbet_sizing_pct(hand)` + thresholds. The per-DECISION complement to the existing aggregate `build_sizing_leak_signals` (untouched). |
| `gem_discovery_context.py` | **+** `import gem_sizing_detector`; **+** `family_flop_cbet_sizing(hands, prior_records)`; **+** a `review_value` branch (gross→CONFIRMED, moderate→READ_DEPENDENT); **+** the family appended to the `run_value` raw tuple. |
| `gem_analyst_packet.py` | **+** `EVIDENCE['chart.flop_cbet_sizing_band']`; **+** `flop_cbet_sizing → chart.flop_cbet_sizing_band` in the `_norm_decision` evidence map; **+** thread detector-supplied `packet_facts` (the `sizing_assessment`) into the sealed atomic record. |

New: `test_sizing_line_pilot.py` (36 assertions), `_v03_pilot_run.py` (measurement harness), `v03_pilot/` (deliverables).

## `gem_sizing_detector.assess_flop_cbet_sizing(hand, *, tolerance_pp=10, gross_pp=25) -> dict|None`

Returns an assessment dict only when Hero's flop c-bet deviates from an applicable **complete** band; else
`None` (fail closed). Consumes canonical fields only; invents no sizing math.

Thresholds: `TOLERANCE_PP = 10` (canonical `sizing_within_target` default), `GROSS_PP = 25`,
`GROSS_OVER_MULT = 2.0`, `GROSS_UNDER_MULT = 0.5`.

Algorithm:
1. require `hand['pfr']`; read `actual` = flop-cbet % from `hand['hero_bets']`; require ≥3 board cards.
2. archetype = `hand['board_archetype']` or `gem_textures.classify_archetype(board[:3])`; require not `unknown`.
3. require `archetype_meta(arch)['confidence'] == 'complete'`.
4. `side` = `ip|oop` from `hand['hero_ip']`; `depth` = `eff_stack_bb|stack_bb|100`.
5. `tgt = get_gto_target(arch, side, depth)`; require non-empty `sizings_pct`.
6. `within = sizing_within_target(actual, targets, tolerance_pp)`; if `None`/`True` → `None` (no candidate).
7. else compute `nearest`, `deviation_pp`, `direction`; `severity = gross` iff `deviation_pp ≥ gross_pp` and
   not dual-strategy and (`actual ≥ 2×max(targets)` or `actual ≤ 0.5×min(targets)`), else `moderate`.

Returned facts (cited by the analyst): `board_archetype, cbet_side, depth_band, eff_stack_bb_flop,
actual_sizing_pct, target_sizings_pct, nearest_target_pct, deviation_pp, direction, tolerance_pp,
dual_strategy, chart_confidence, chart_freq_pct, chart_notes, chart_source, severity, proposed_sizing_pct`.

## `gem_discovery_context.family_flop_cbet_sizing(hands, prior_records)`

Per hand: require 2 hole cards; require a **clean single flop c-bet** (`len(hero flop actions)==1 and ==
'bets'`) so the `_record` decision_id action index resolves to the c-bet; call `assess_flop_cbet_sizing`;
require a made-hand class (postflop packet completeness). Emits `_rule_record(..., CHART_BACKED, <band
citation>, <proposed sizing>)` with a `context` carrying `made_hand_class`, `board`, `hero_cards`,
`eff_stack_bb`, `pot_before_bb`, the `sizing_assessment`, and `packet_facts={'sizing_assessment': ...}`.

## Integration seam

`run_value` raw tuple → `+ family_flop_cbet_sizing(...)`. Dedup key `(hand_id, street, family)`. `review_value`
maps gross→CONFIRMED / moderate→READ_DEPENDENT. `build_packet`: a CONFIRMED decision id lands in
`confirmed_ids` → **required**; moderate → **optional** (cap 8). `_norm_decision` cites
`chart.flop_cbet_sizing_band` and merges `packet_facts` into the atomic record.

## No-leakage / no-calc guarantees

- Record sealed by `atomic_snapshot`; action line truncated at Hero's c-bet; street-exact board; no
  `net_bb`/`showdown`/`won`/`prior_verdict` (verified by `test_sizing_line_pilot.py` and `semantic_audit`).
- `semantic_audit` over the sizing records: `failing=0`, `future_information_leaks=0`,
  `zero_analyst_calculations_required=True`.
- Every cited number is a key of the decision record (`sizing_assessment`, `chosen_incremental_bb`,
  `pot_before_bb`, …) or the chart excerpt — `validate_analyst_output` enforces this.

## Worked outputs (fixture corpus)

| Hand | Board / archetype / side | Actual | Band | Deviation | Severity | Verdict |
|---|---|---|---|---|---|---|
| `TM91000015` | Js7h8h · middling_disconnected · OOP | **217%** | `[85]` (single, complete) | 132 pp over, all-in | **gross** | **CONFIRMED_MISTAKE** |
| `TM90000006` | 2h7d4c · low_ragged · IP | 36.9% | `[50,100]` (dual) | 13.1 pp under | moderate | READ_DEPENDENT |
| `TM91000003` | Qs9h4c · broadway_disconnected · IP | 36.4% | `[33,85,100]` | within 10pp of 33 | — | **correctly not flagged** |
