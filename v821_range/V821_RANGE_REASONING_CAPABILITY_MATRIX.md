# V821_RANGE_REASONING_CAPABILITY_MATRIX

Stage-1 audit for the v8.21 **Range Reasoning** foundation, first module **Runout Transition**. Branch
`feature/v8.21-range-reasoning-foundation` @ `93637eb` (released v8.20.0 + merged v8.21 aggregate sizing).

> Note on method: the planned multi-agent audit was unavailable (subagents hit a monthly spend limit). This
> matrix was produced with direct inspection + a keystone feasibility probe, drawing on the canonical owners
> already mapped in prior v8.21 work.

## Keystone feasibility (proven)

A deterministic before→after street transition is computable from existing canonical evaluators, no new
evaluator and no range/equity. Probe — AKh on `Qs Jh 5d`:

| Board | `hand_strength_name` | `draw_profile` (straight/flush/outs) |
|---|---|---|
| flop `Qs Jh 5d` | high_card | gutshot · 4 straight outs · backdoor_fd · 10 clean outs |
| turn `+Th` | **straight** | straight **completed** (sd None) · new flush_draw (9) · 15 clean outs |
| river `+2c` | straight | flush **busted** (fd None) |

So made-hand-before/after, draw-before/after, outs gained/lost, and completed/busted draws are all
deterministic and result-independent.

## Capability matrix

| Component | Class | Canonical owner / note |
|---|---|---|
| Decision identity (hand id, street, decision id) | **ALREADY_EXISTS** | `gem_decision_snapshot.build_decision_snapshot(hand, action_index)`; decision_id `hand:street:idx` |
| Previous board / new card / resulting board | **GENUINELY_NEW** (trivial) | slices of `hand['board']` (`before=board[:n-1]`, `new=board[n-1]`, `after=board[:n]`); deterministic |
| Hero position · IP/OOP | **ALREADY_EXISTS** | `snapshot.hero_position`, `hand['hero_ip']` |
| Pot type | **ALREADY_EXISTS** | `hand['pot_type']` (SRP/3BP/4BP) |
| Number of players / multiway | **ALREADY_EXISTS** | `snapshot.players_active_before_action` (+Hero); `hand['players_at_flop']`/`n_players` |
| Initiative / prior-action context | **PARTIALLY_EXISTS** | `hand['pfr']`, barrel/probe flags (`double_barreled`, `delayed_cbet_turn`, `probe_turn`), `hero_street_actions`, action ledger |
| Effective stack at decision | **ALREADY_EXISTS** | `snapshot.canonical_effective_decision_depth_bb` |
| SPR at decision | **ALREADY_EXISTS** | postflop `eff_depth / contestable_pot_before_action_bb` (the `atomic_snapshot` formula) |
| Deterministic transition tags (board pair, top/low pair, overcard, undercard/brick, flush card, four-flush, straight-completing, connectivity +/−, double-paired, counterfeit, blank-vs-draw) | **GENUINELY_NEW** (deterministic) | new classifier consuming raw board cards + `gem_analyst_packet._board_texture` / `gem_textures` — board-card arithmetic, **not** a new evaluator |
| Made-hand class before/after | **ALREADY_EXISTS** | `gem_parser.hand_strength_name(cards, board)` (9-class) |
| Draw class before/after; straight/flush draw; outs | **ALREADY_EXISTS** | `gem_made_hands.draw_profile(cards, board)` |
| Outs gained / lost; draw completed / busted | **GENUINELY_NEW** (derived) | diff of `draw_profile` before vs after (deterministic) |
| Overcards | **ALREADY_EXISTS** | `draw_profile['overcards']` / `overcard_ranks` |
| Blockers (nut blockers) | **BLOCKED_BY_CANONICAL_INFRASTRUCTURE** | no canonical nut-blocker owner; overcard info only. Omit from MVP. |
| Showdown-value change (result-independent) | **PARTIALLY_EXISTS** | derivable as "has/keeps/loses showdown value" from made-hand class only (no equity); coarse |
| "What changed" facts | **GENUINELY_NEW** (composed) | composed from the deterministic before/after above |
| "What remained valid" facts | **GENUINELY_NEW** (composed) | the prior facts the new card did not invalidate |
| "Reassess" prompts | **GENUINELY_NEW** (deterministic triggers) | e.g. "flush completed — reassess thin value / bluffs" (descriptive, not a verdict) |
| Range / nut-advantage language | **BLOCKED_BY_CANONICAL_INFRASTRUCTURE** | no opponent-range owner; **suppress** |
| continue / resize / slow / pivot / abandon recommendation | **BLOCKED_BY_CANONICAL_INFRASTRUCTURE** | needs opponent range + fold-equity (absent) → **Insufficient evidence** + debt |
| Insufficient-evidence suppression | **ALREADY_EXISTS** (reuse) | the Factual/Coaching/Insufficient register pattern (`gem_report_draft/sections_xiv.py`, registers) |
| Read-Sensitive Reconstruction | **PLANNED_ELSEWHERE** | later, inside Review/Drill (`gem_drill_export.py`, `gem_review_trust.py`) — not this run |
| Counterfactual Threshold / adaptive coaching / solver sim | **INFEASIBLE_OR_UNSAFE** | explicitly out of scope |

## Duplication-risk analysis

| Existing | Risk | Resolution |
|---|---|---|
| Static texture analysis (`gem_textures.classify_archetype`, `_board_texture`) | renaming static labels as "Range Reasoning" | **REUSE** for the texture of each street; the NEW value is the **transition** (before→after + consequence), never a static label. Do not rename. |
| Sizing & Lines (`sec-SL`, `build_sizing_leak_signals`) | overlapping report section | Separate concern (flop c-bet **sizing** %); Runout Transition is the **street change**. No overlap; do not touch `sec-SL`. |
| Range Lens (`rng-class-match`, `per_opponent_range_lines`) | range "dump" temptation | Mirror its **match-not-dump** discipline; Runout Transition emits **no** range combos. |
| Villain teaching (`gem_villain_teaching`, `gem_analyst_villain`) | hindsight / invented intel | Mirror the **constrained-projection, invents-nothing, no-hindsight** contract. |
| Review/Drill (`gem_drill_export`, `gem_review_trust`) | premature coupling | Record as **future hook** only. |
| Future counterfactual work | scope creep | Out of scope; debt-record only. |

## Contract-feasibility verdict

- **DESCRIPTIVE Runout Transition MVP is feasible and safe** — every descriptive field has a canonical owner
  or is a deterministic derivation of one; no new evaluator, no analyst math, no range/equity, no future leak.
- **STRATEGIC recommendation layer is BLOCKED** — no canonical opponent-range / fold-equity owner exists, so
  continue/resize/slow/pivot/abandon cannot be result-independently justified. It renders **"Insufficient
  evidence …"** and is recorded as engineering debt (the named canonical dependency: an opponent-range owner).

## Integration seam

`gem_report_draft/_hand_grid.py` (≈line 417: "Build notes per street and attach to hero action on that
street") — the per-street note system on the turn/river Hero action is the attach point for a compact
transition block. Layout constraints to preserve: sticky street headers, Board+Hero context, Action column,
desktop/mobile nav, the `sec-SL` sizing section, and Results behavior.

## Recommended smallest safe MVP

Deterministic transition classification + a compact player-facing **"what changed / what remained / reassess"**
explanation on turn/river, with **range/nut language suppressed** and **strategic recommendations rendered as
Insufficient evidence** (blocked layer documented as debt). No range construction in the first slice.
