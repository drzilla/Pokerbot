# V821_RUNOUT_TRANSITION_PILOT_RESULTS (corrected)

Real-session pilot of the **corrected** `gem_runout_transition` over the approved corpus (3 sessions under
`GEM 20260527`), run through the **product path** `transitions_for_hand`. Raw: `RUNOUT_PILOT_METRICS.json`
(authoritative), `RUNOUT_PILOT_SAMPLES.json`.

## Coverage

| Metric | Value |
|---|---|
| Unique real hands | 3,609 |
| Eligible street transitions (one per Hero turn/river street) | 529 |
| **Resolved (complete canonical evidence)** | **482 (91%)** |
| Unresolved / suppressed | 47 — `not_a_turn_or_river_node` 29, `all_in_or_no_future_decision` 18 |
| Rendered blocks | 482 |
| Rule-backed strategic coaching | **0** (strategic layer blocked — by design) |

## Objective distributions

- **Hero hole-card contribution (after the card):** contributes **281** · board-only/shared **201**. This is
  the safety-critical split the old model got wrong: 201 transitions where Hero's category is fully available
  from the board are now labelled *shared by the field*, not "Hero improved".
- **Best-five category:** changed **136** · unchanged **346**.
- **Top transition tags:** connectivity_increase 179 · undercard_or_brick 102 · overcard 95 · board_paired 85
  · low_card_pair 54 · flush_card 53 · blank 49 · four_to_a_straight 41.

## MEASURED trust audit — all zero (computed, not assumed)

| Audited risk | Measured |
|---|---|
| Result-field leakage | **0** |
| Later-card leakage (token-bounded) | **0** |
| Unsupported range terms (in factual claims) | **0** |
| Unsupported strategic directives | **0** |
| Banned strength words (improved/weakened/counterfeit/showdown-value) | **0** |
| Shared-board false-improvement claims | **0** |
| Static-texture duplication (every fact describes a change) | **0** |
| Duplicate records per street | **0** |
| Accidentally-rendered unresolved records | **0** |

> A substring false-positive (the later card `Th` matching inside the word "**Th**e") was found during the
> audit and fixed with token-bounded matching — so the zero is genuinely measured, per the requirement not to
> report zero false positives unless the audit actually measured them.

## Cost

Avg record ~2.0 KB; runtime ~0.5 s for 529 transitions over 3,609 hands (deterministic single pass). No
analyst-packet additions → 0 token/workload impact.

## Representative samples (from `RUNOUT_PILOT_SAMPLES.json`)

- **Shared board change (no false improvement):** `TM6039961024` `8c-8h-5d-5c` — *"Your best-five category
  changed from pair to two_pair because the board changed; this category is now available from the board and
  is shared by every remaining player. The board paired (5c)."* (`contributes = False`).
- **Hero private improvement:** `TM6039960546` `Qs-2c-Kd-8d` — *"Your hole cards now make two_pair (was
  pair)."* (`contributes = True`).
- **Suppressed (correct):** all-in turn decisions → unresolved `all_in_or_no_future_decision`; non-turn/river
  nodes → `not_a_turn_or_river_node`.

## Assessment

The corrected descriptive Runout Transition is **safe and useful** on real hands: 91% of eligible turn/river
street transitions get an objective "what changed / what remained / reassess" explanation, improvement is
attributed to Hero **only** when his hole cards provably contribute (281 vs 201 shared), and the measured trust
audit is clean. The strategic layer remains blocked (0 recommendations) pending a canonical opponent-range
owner.
