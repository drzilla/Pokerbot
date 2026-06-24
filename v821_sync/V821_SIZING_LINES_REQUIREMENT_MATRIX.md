# V821_SIZING_LINES_REQUIREMENT_MATRIX

Capability matrix for Sizing & Lines against the **synchronized v8.20.0 baseline**. Each row: product
requirement · canonical source owner · current implementation/v8.20 status · test coverage · report surface ·
trust risk · remaining work · classification.

## Trust boundary (preserved)

- **parser/analyzer** owns observed action, pot, stack, and sizing facts (`action_ledger`, `hero_bets`,
  `board_archetype`, `pot_type`, `eff_stack_bb`, `spr`, `players_at_flop`).
- **canonical engines** own deterministic derived values (`gem_textures.get_gto_target`/`sizing_within_target`,
  `gem_decision_snapshot`, `aggregate_compliance`).
- **analyst** may interpret supplied facts; may **not** create missing calculations.
- **renderer** may display but **not** derive strategic operands.
- A sizing difference from a target is **not** automatically a mistake — context (range, stack, street,
  texture, player type) may control. The shipped surface is an **aggregate leak**, never a per-hand verdict.

## Sizing evidence

| Capability | Canonical owner | v8.20 status | Test | Report surface | Trust risk | Remaining v8.21 work | Class |
|---|---|---|---|---|---|---|---|
| Flop c-bet % vs reference band | `_gto_sizing_pct`→`aggregate_compliance`→`build_sizing_leak_signals` | ALREADY | `test_sizing_line_pilot` 25/25; `_test_scratch` T-W1A-SD | "Sizing & Line Patterns" | Low (aggregate, exclude-and-count) | — (shipped) | **STILL_REQUIRED_V821** |
| Chart-applicability gate (SRP/HU/non-all-in) | `gem_sizing_detector.cbet_chart_applies` | ABSENT→**landed** | `test_sizing_line_pilot` (gate truth-table) | (gates the above) | Low — decision-time inputs, no result | — (shipped) | **STILL_REQUIRED_V821** |
| Actual bet/raise size (chips & BB) | `action_ledger` (`amount_bb`/`added_bb`/`to_bb`) | PARTIAL (ledger only) | — | not surfaced | Med — raw chips invites per-hand framing | optional copy enrichment | **DEFER_BEYOND_V821** |
| Pre-bet / post-action pot | `_pot_before`, ledger | ALREADY (computed) | — | not surfaced | Low | optional copy | DEFER |
| Effective-stack context | `eff_stack_bb`, `eff_stack_bb_at_decision` | PARTIAL (depth-key only) | — | not surfaced | Low | optional copy | DEFER |
| SPR where canonical | `hand['spr']` / `gem_decision_snapshot` | PARTIAL (field exists) | — | not surfaced | Low | optional copy | DEFER |
| Action type & street | `action_ledger`, `hero_street_actions` | ALREADY | — | partial | Low | — | RETAIN |
| IP/OOP & pot type | `hero_ip`, `pot_type` | ALREADY | gate test | drives buckets | Low | — | RETAIN |
| Multiway context | `players_at_flop`, `multiway_flop` | PARTIAL (gate excludes MW from sizing) | gate test | excluded | Med — HU/MW mix dilutes | per-dimension judging needs charts | **BLOCKED** |
| All-in / capped handling | `cbet_chart_applies._flop_cbet_is_all_in`, `postflop_opportunity_exclusion` | ALREADY (excluded) | gate test | excluded | Low | — | STILL_REQUIRED |
| Uncalled-bet handling | parser ledger | ALREADY | `_test_scratch` | n/a | Low | — | RETAIN |
| Raise-to vs raise-by correctness | `gem_decision_snapshot.build_action_sizing_contract` | ALREADY | `_test_scratch` | n/a | Low | — | RETAIN |
| Turn/river/3BP/4BP sizing bands | none (`gto_texture_archetypes.json` is **flop-cbet only**) | ABSENT | — | — | High — no chart → unjudgeable | needs chart owner (D2/D8) | **BLOCKED_BY_CANONICAL_INFRASTRUCTURE** |

## Line-pattern evidence

| Capability | Canonical owner | v8.20 status | Trust risk | Remaining | Class |
|---|---|---|---|---|---|
| Street-by-street action sequence | `line_actions` / `hero_street_actions` / `action_ledger` | PARTIAL (encoded, **not** on the sizing surface) | High — surfacing as a "pattern" implies a multi-street verdict | a descriptive (non-verdict) line view is a future slice | **DEFER_BEYOND_V821** |
| Single/double/triple barrel | parser barrel flags + `family_turn_overbarrel` (discovery, READ_DEPENDENT) | PARTIAL | High — confirming needs range | none safe | DEFER |
| Check-call / check-raise / bet-fold branches | `action_ledger` | PARTIAL (encoded) | Med | descriptive only | DEFER |
| Delayed c-bet / probe lines | parser delayed-cbet/probe flags | PARTIAL | Med | descriptive only | DEFER |
| Passive-passive-jam / geo-vs-non-geo / sudden escalation / small-small-jam | none | ABSENT | High — needs a sequence detector + range/equity to judge | none | **BLOCKED_BY_CANONICAL_INFRASTRUCTURE** |
| Sizing consistency across streets | `hero_bets` (flop only computed) | PARTIAL | High — no turn/river bands | blocked on charts | BLOCKED |
| Line abort / pivot after runout change | none (overlaps Runout Transition work) | ABSENT | High — duplication risk + range reasoning | none | **BLOCKED_BY_CANONICAL_INFRASTRUCTURE** |

> The "**Lines**" half of "Sizing & Line **Patterns**" is currently aspirational — the shipped surface is
> flop-c-bet-sizing only. Renaming/expanding it requires charts and a result-independent rule that do not exist.

## Teaching layer

| Capability | Canonical owner | v8.20 status | Trust risk | Remaining | Class |
|---|---|---|---|---|---|
| What was observed | `build_sizing_leak_signals` `what_happened` | ALREADY | Low | — | RETAIN |
| What the sizing communicates / line coherence | none | ABSENT | High — range-signaling, unsafe | none | **BLOCKED** |
| Continue / resize / pivot / abort | `build_sizing_leak_signals` `adjustment` (resize only) | PARTIAL | Low (resize); High (pivot/abort) | resize ships; pivot/abort deferred | STILL_REQUIRED (resize) / DEFER (pivot) |
| Population vs theory distinction | curated `gto_texture_archetypes.json` (theory band) | PARTIAL (theory only) | Med — no field baseline | population baseline deferred | DEFER |
| Confidence & evidence source | `build_sizing_leak_signals` (`confidence`, `evidence`, `signal_type=aggregate_leak`) | ALREADY (strong) | Low | — | RETAIN |
| Over-generalization guardrails | exclude-and-count thresholds (sufficient sample, compliance floor) + "not a per-hand verdict" copy | ALREADY (strong) | Low | — | RETAIN |
| Per-hand sizing **verdict** | analyst one-pass + canonical decision node | ABSENT | Critical — 0/3,609 confirmed; routes to `unresolved`/debt | none — locked | **BLOCKED_BY_CANONICAL_INFRASTRUCTURE** |

## Deferred-debt cross-reference (Stage-5)

| Debt | Status | Owner/route |
|---|---|---|
| Per-hand sizing evidence absent/insufficient | confirmed 0/3,609; per-hand path removed | BLOCKED — needs canonical decision-level evidence |
| Aggregate-only where decision-level needed | accepted (aggregate is the correct altitude) | resolved → KEEP_AGGREGATE_ONLY |
| Preflop all-in eligibility ownership | no canonical owner | route to the existing **v8.20 preflop-owner debt** thread (do not let v8.21 own) |
| Steal/3bet/4bet/squeeze/exploit integration | out of charter; range-dependent | DEFER |
| Interaction with future v8.21 range reasoning | not authorized | hard lock until result-independent owner rule exists |
| Duplication with Runout Transition work | line-abort/pivot overlaps it | DEFER, coordinate ownership before any work |
| Sizing description vs strategic verdict | enforced (aggregate, "not graded mistakes") | resolved |

**Net:** the only STILL_REQUIRED items are already implemented (the gate + its test). Everything else is
BLOCKED_BY_CANONICAL_INFRASTRUCTURE or DEFER_BEYOND_V821 — none is an unambiguous, safe slice for now.
