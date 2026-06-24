# V821_RUNOUT_TRANSITION_CANONICAL_CONTRACT

One deterministic, result-independent **transition record** per eligible turn or river Hero decision. Every
operand is CONSUMED from a canonical Pokerbot owner; nothing is recomputed by an analyst or renderer. Produced
by `gem_runout_transition.build_transition(hand, action_index)`.

## Eligibility / fail-closed

Build a record only for a Hero decision on **turn** (board 4) or **river** (board 5) where the canonical
decision snapshot resolves. Fail closed (return an explicit `unresolved` record, never a fabricated one) when:
- `gem_decision_snapshot.build_decision_snapshot` reports `no_hero_decision` or omits a core operand
  (`pot_before_action_bb` / `hero_stack_before_action_bb` / `canonical_effective_decision_depth_bb`);
- fewer than 4 board cards at the decision (not a turn/river node);
- Hero hole cards are not exactly 2;
- the decision is all-in or has **no future decision** (a runout-transition lesson about the next street is
  moot) → suppressed.

## A. Identity & decision state (canonical owners)

| Field | Owner |
|---|---|
| `hand_id` | `hand['id']` |
| `street` | `snapshot.street` (`turn`/`river`) |
| `decision_id` | `'%s:%s:%s' % (hand_id, street, action_index)` |
| `prev_board` | `board_at_decision[:-1]` (flop on turn, turn on river) |
| `new_card` | `board_at_decision[-1]` |
| `resulting_board` | `board_at_decision` (street-exact) |
| `position` | `snapshot.hero_position` |
| `ip` | `hand['hero_ip']` (bool) |
| `pot_type` | `hand['pot_type']` |
| `n_players` | `len(snapshot.players_active_before_action) + 1` |
| `multiway` | `n_players >= 3` |
| `initiative` | derived from `hand['pfr']` + prior barrel/probe flags (descriptive, not a verdict) |
| `eff_stack_bb` | `snapshot.canonical_effective_decision_depth_bb` |
| `spr` | postflop `round(eff_depth / contestable_pot_before_action_bb, 2)` when available, else `None` |

No `net_bb` / showdown / villain cards / later action / later board. The action line is never read past
`action_index`.

## B. Texture transition (deterministic tags)

`prev_texture` = `_board_texture(prev_board)`, `new_texture` = `_board_texture(resulting_board)` (canonical
`gem_analyst_packet._board_texture`). Plus `transition_tags` — a sorted list from a deterministic classifier
over the raw cards (`board pairs`, the rank of `new_card` vs prev ranks, suits):

`board_paired` · `top_card_pair` · `low_card_pair` · `double_paired` · `overcard` · `undercard_or_brick` ·
`flush_card` · `four_flush` · `monotone_complete` · `straight_completing` · `connectivity_increase` ·
`connectivity_decrease` · `counterfeit` (board now out-runs a Hero two-pair-from-board) · `blank_vs_hero_draws`
(new card neither completes nor extends Hero's principal draw). Each tag is produced **only** when
deterministically true from the board cards (and, for `*_vs_hero_draws`/`counterfeit`, Hero's canonical
evaluator state) — never free-form LLM classification.

## C. Hero state transition (canonical evaluators only)

Computed on `prev_board` vs `resulting_board`:

| Field | Owner |
|---|---|
| `made_before` / `made_after` | `gem_parser.hand_strength_name(cards, board)` |
| `made_detail_before` / `_after` | `gem_made_hands.draw_profile(...)['made_hand']` (fine class) |
| `draw_before` / `draw_after` | `draw_profile` (`straight_draw`, `flush_draw`, `straight_outs`, `flush_outs`, `clean_outs`, `overcards`) |
| `improved` / `weakened` / `unchanged` | deterministic comparison of made-hand rank + draw state |
| `outs_delta` | `clean_outs_after − clean_outs_before` (when both canonically defined) |
| `draw_completed` | a draw present before is now a made hand / `None` after |
| `draw_busted` | a draw present before is absent after without completing |
| `has_showdown_value` | coarse, result-independent: made-hand class is `pair`+ (no equity) |
| `overcards_after` | `draw_profile_after['overcards']` |

Blockers and any opponent-range-relative state are **omitted** (no canonical owner). No invented ranges/equity.

## D. Planning evidence (facts vs coaching, separated)

| Field | Meaning |
|---|---|
| `changed[]` | objective facts the card changed (made-hand jump, draw completed/busted, flush/straight available, board paired …) — each a `{fact, source, tier}` |
| `remained[]` | prior facts the card did **not** invalidate (e.g. "you still hold an over-pair", "the board is still single-suited to your suit") |
| `reassess[]` | deterministic descriptive prompts triggered by tags (e.g. "a flush is now possible — reassess thin value bets and continued bluffs") — descriptive, **not** an action verdict |
| `planning_implication` | one of `continue` / `resize` / `slow_down` / `pivot` / `abandon` / **`insufficient_evidence`**. Renders a concrete action **only** when a documented canonical owner + a result-independent rule supports it; otherwise `insufficient_evidence` with the standard message. (MVP: always `insufficient_evidence` — strategic layer is blocked; see the debt register.) |
| `evidence_source` | canonical owner(s) cited |
| `evidence_tier` | `canonical_made_hand_class` · `canonical_draw_profile` · `canonical_board_texture` (descriptive tiers); strategic tiers reserved |
| `confidence` | `high` for deterministic descriptive facts; strategic confidence absent while blocked |
| `unresolved_fields[]` | anything a canonical owner could not supply |
| `register` | `Factual` for `changed`/`remained`; `Coaching` only for rule-backed implications; `Insufficient evidence` otherwise |

The contract **distinguishes facts (Factual register) from coaching (Coaching register)** and never lets an
unresolved case become analyst-generated advice.

## Provenance / no-calc invariants (enforced in the trust model)

No analyst-created pot/equity/EV/range/stack/sizing numbers; renderer performs no strategic calculation; no
later action/board/showdown leaks into the record; effective stack is decision-time; multiway never uses
heads-up rules; unsupported range language suppressed; unresolved stays unresolved.
