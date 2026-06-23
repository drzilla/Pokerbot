# CAPABILITY_AND_DUPLICATION_MATRIX

Each charter family classified against what already exists in the runtime. The goal is to pick a
**genuinely-new, high-precision, fully-canonical** pilot and avoid duplicating shipped detectors.

Legend: **EXISTS** · **PARTIAL** · **PLANNED-ELSEWHERE** · **NEW** · **UNSAFE/INFEASIBLE** (needs a new dependency)

| Charter family | Existing coverage | Canonical inputs available? | Classification | Pilot decision |
|---|---|---|---|---|
| **A — texture/depth/position c-bet SIZING mismatch** | `gem_sizing_detector.build_sizing_leak_signals` emits an **AGGREGATE** leak (repeated off-size pattern per archetype×side), explicitly *"a single off-size c-bet is never auto-graded."* No **per-hand** decision candidate exists. | **Yes, fully.** `hand['hero_bets']` (chosen %), `hand['board_archetype']`, `hero_ip`, `eff_stack_bb`; `gem_textures.get_gto_target` / `sizing_within_target` (16 complete archetypes). | **NEW** (per-hand complement of an aggregate-only detector) | **SELECTED — pilot #1** |
| **B — unnecessary aggression with showdown value** | None directly. | Made-hand class yes; but "medium SDV is a *mistake* to bet" needs opponent **range interaction**, which is not canonical. Charter says it must fail closed when range interaction is unsupported. | **UNSAFE** (range-dependent) | Defer |
| **C — missed / undersized river VALUE** | `family_river_value` already CONFIRMS *"strong made hand took no value on the river (check-through or materially small bet)."* | Made-hand yes. But a **river sizing band** does not exist (the only sizing chart is **flop** c-bet). The "undersized" sub-case has no canonical reference → would require a heuristic threshold (forbidden: *"do not change thresholds to create findings"*). | **PARTIAL / EXISTS** (check-through shipped; undersized-river lacks a canonical band) | Defer (no new safe surface) |
| **D — bad turn continuation / double barrel** | `family_turn_overbarrel` exists (READ_DEPENDENT). | Range-dependent; no **turn** sizing chart (archetypes are flop-only). | **EXISTS / UNSAFE to confirm** | Defer |
| **E — river curiosity call** | `family_river_curiosity` exists (READ_DEPENDENT). | Price yes; confirming needs an opponent bluff range (not canonical). | **EXISTS** | Defer |
| **F — line-structure inconsistency** | None. | Examples (bet/fold-with-commit, sizing-inconsistent-across-streets) need intent/range inference or use **future** actions to grade an earlier node (no-leakage violation). | **UNSAFE/INFEASIBLE** without a range engine | Defer |

## Why only ONE family is in this pilot

The charter permits up to three families and *prefers a smaller high-precision pilot* ("do not select a
family because it generates many candidates"). After the matrix:

- **A is the single genuinely-new, chart-backed, result-independent, fully-canonical family.** It is the
  per-decision complement to the shipped aggregate detector and reuses the exact same canonical primitives,
  so it adds no parallel calculation and no new evaluator.
- A **second chart-backed sizing family is not supported by current canonical inputs**: the only sizing
  chart in the runtime is **flop c-bet** (`gto_texture_archetypes.json`, side = `ip_cbet`/`oop_cbet`). There
  is no turn/river sizing band, so a "river value sizing" or "turn barrel sizing" family would have to invent
  a reference — rejected by the charter.
- The remaining candidate families (B/D/E/F) are either already shipped as READ_DEPENDENT surfaces or are
  range-dependent / future-leaking, i.e. cannot be made high-precision without a range engine — explicitly
  out of scope.

Shipping one airtight family is the disciplined choice and matches the locked baseline's product-value
model (one rule-backed confirmed mistake per the v8.20 KQs precedent).

## Duplication guardrails honoured

- **No re-implementation of sizing math.** Chosen % of pot is consumed from `hand['hero_bets']`; band +
  deviation come from `gem_textures` (the same owners the aggregate detector uses).
- **No overlap with `gem_material_loss`** (net-loss population — orthogonal axis: loss magnitude vs
  chart deviation).
- **No second pipeline.** The family registers in `gem_discovery_context.run_value`; records seal through
  `gem_analyst_packet.atomic_snapshot`/`build_packet` like every other decision.
