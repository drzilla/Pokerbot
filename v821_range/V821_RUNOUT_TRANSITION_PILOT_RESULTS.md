# V821_RUNOUT_TRANSITION_PILOT_RESULTS

Real-session pilot of `gem_runout_transition` over the approved corpus (3 sessions under `GEM 20260527`).
Raw: `RUNOUT_PILOT_METRICS.json`, `RUNOUT_PILOT_SAMPLES.json`.

## Corpus & coverage

| Metric | Value |
|---|---|
| Real hands | 3,609 |
| Eligible turn/river Hero decisions | 654 |
| **Resolved (complete canonical evidence)** | **589 (90%)** |
| Unresolved / suppressed | 65 — `not_a_turn_or_river_node` 35, `all_in_or_no_future_decision` 30 |
| Descriptive output produced | 589 |
| **Rule-backed strategic coaching** | **0** (strategic layer blocked — by design) |
| Strategic recs rendered *Insufficient evidence* | 589 |
| Result leaks | **0** |
| Unsupported range claims | **0** |
| Duplicate static-texture commentary | **0** (emits transition before→after, not static labels) |
| Analyst-LLM workload added | **0** |

## Distributions

- **Hero status:** unchanged 418 · improved 158 · weakened 13 (result-independent; "weakened" = made-hand
  counterfeited or a **real** draw — not a backdoor — missed leaving no made hand). `RUNOUT_PILOT_METRICS.json`
  is authoritative.
- **Top transition tags:** connectivity_increase 211 · overcard 124 · undercard_or_brick 123 · board_paired 95
  · flush_card 68 · blank_vs_hero_draws 61 · low_card_pair 60 · straight_completing 46. (`straight_completing`
  is the tightened 4-in-window board-straight threat; general coordination is `connectivity_increase`.)

## Cost

Avg record ~1.6 KB; **0.39 s for 654 decisions** over 3,609 hands (deterministic, single pass; negligible
runtime). No analyst-packet additions, so no token/workload impact.

## Manual sample inspection

- **Useful (improved):** `TM6039961024` `8c-8h-5d-5c` — *"Your hand improved from pair to two_pair. The board
  paired (5c)."* (Hero 88 turns trips/two-pair when the board pairs Hero's set context.)
- **Useful (flush threat):** `TM6040063154` `7s-6d-5s-Qs` — tags `flush_card, overcard`, reassess *"A flush is
  now possible — reassess thin value bets and continued bluffs."*
- **Useful (improved to flush):** AKh on `Qh-7h-2c` + `Th` — *"improved from high_card to flush; draw
  completed; you still hold flush (showdown value)."*
- **Suppressed (correct):** all-in turn decisions → *Insufficient evidence* (`all_in_or_no_future_decision`);
  preflop/flop nodes excluded (`not_a_turn_or_river_node`).
- **Weak / watch:** `connectivity_increase` fires on ~32% of transitions — accurate but verbose; it drives no
  coaching claim (only a descriptive tag), so it adds no risk, but the surface should de-emphasise it visually.

## Assessment

The **descriptive** Runout Transition foundation is genuinely useful on real hands: 90% of eligible turn/river
decisions get a result-independent "what changed / what remained / reassess" explanation, with honest
suppression elsewhere and **zero** leaks, range claims, or analyst workload. Product value is **not** claimed
from fixtures alone — it is demonstrated on 589 real decisions. The **strategic** layer (continue/resize/pivot/
abandon) produced **0** recommendations because no canonical opponent-range owner exists; it is correctly
withheld as *Insufficient evidence* and recorded as debt.
