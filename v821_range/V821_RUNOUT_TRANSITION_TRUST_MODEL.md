# V821_RUNOUT_TRANSITION_TRUST_MODEL

> **v8.21 correction (supersedes the relative-strength rows below).** The module no longer emits
> `improved`/`weakened`/`counterfeit`/`has_showdown_value`. Hero "improvement" is now a **proven** fact —
> Hero's best-five must beat the **board-only** best-five for his hole cards to be credited — and a shared
> board change is labelled *"shared by every remaining player."* Relative strength / the correct action is
> always rendered **Insufficient evidence** pending a canonical opponent-range owner. Tests are now **48/48**
> (forced canonical-owner failures included). See `V821_RUNOUT_TRANSITION_SEMANTIC_CONTRACT.md` and
> `V821_RUNOUT_TRANSITION_CORRECTION_REPORT.md`. The provenance/no-calculation invariants below still hold.

Provenance and no-calculation invariants for the Runout Transition module. Each is enforced in
`gem_runout_transition.py` and asserted by `test_runout_transition.py`.

| Invariant | How enforced | Test |
|---|---|---|
| No later action leaks into an earlier decision | the action ledger is never read past `action_index`; only `build_decision_snapshot(hand, action_index)` is consumed | "no later-card mention in turn changed facts" |
| No later board card leaks into an earlier transition | the record uses the **street-exact** `board_at_decision`; `new_card = board[-1]`, `prev_board = board[:-1]`; nothing reads a later street | "no future-card leak: turn record board has exactly 4 cards" |
| No Villain showdown cards influence the output | the module never reads villain hole cards / showdown; `_LEAK_KEYS`-style fields (net/showdown/won) are absent | record has no result fields |
| Effective stack is decision-time correct | `snapshot.canonical_effective_decision_depth_bb`; SPR from decision-time contestable pot | record `eff_stack_bb` / `spr` |
| Multiway never uses heads-up rules | `multiway = (active players + Hero) >= 3` is carried; no heads-up-only logic in the descriptive layer | "multiway" / "IP SRP HU" |
| Unsupported range language suppressed | no opponent-range owner exists → the module emits **no** range/combo/nut-advantage language | "no invented numbers / no range language in facts" |
| Analyst provides no new numbers | nothing flows into the analyst packet; no analyst-LLM step; the contract is fully programmatic | analyst workload added = 0 (pilot) |
| Renderer performs no strategic calculation | `render_html` only formats `teaching_block` fields; the over/under/improve **direction** is computed in the module | render test |
| Every coaching statement has provenance + tier | each `changed`/`remained` fact carries `{fact, source, tier}` (`canonical_made_hand_class` / `canonical_draw_profile` / `canonical_board_texture`) | record `changed[].tier` |
| Unresolved stays unresolved (no analyst-generated advice) | fail-closed `unresolved` record + `planning_implication='insufficient_evidence'`; never fabricates | "incomplete evidence -> unresolved", "all-in -> suppressed" |
| No ad-hoc equity/EV scripts | the module imports only canonical owners (`gem_decision_snapshot`, `gem_parser`, `gem_made_hands`, `gem_analyst_packet._board_texture`); no new evaluator | code review + import check |

## Canonical owners consumed (no parallel calculator)

| Operand | Owner |
|---|---|
| identity / decision state / eff-stack / SPR | `gem_decision_snapshot.build_decision_snapshot` |
| made hand (before/after) | `gem_parser.hand_strength_name` |
| draws / outs / completed / busted | `gem_made_hands.draw_profile` |
| board texture | `gem_analyst_packet._board_texture` |
| transition tags | deterministic board-card arithmetic over the above (no new evaluator) |
| pot type / position / players / initiative | `gem_parser` hand fields |

## Evidence tiers / registers

Descriptive facts → `Factual` register, tiers `canonical_made_hand_class` / `canonical_draw_profile` /
`canonical_board_texture`, confidence `high`. Strategic implications → `Insufficient evidence` register while
the opponent-range owner is absent (the `Coaching` register is reserved for a future rule-backed layer with a
documented owner + acceptance rule). This mirrors the existing villain-teaching discipline (constrained
projection, invents nothing, no hindsight).

## Missing infrastructure → debt, not replacement

The strategic recommendation layer and any range/nut-advantage statement require a canonical **opponent-range
/ fold-equity owner** that does not exist. Per the trust mandate this is recorded as engineering debt
(`V821_RANGE_REASONING_DEBT_REGISTER.md`) and rendered as *Insufficient evidence* — it is **never** replaced
by an ad-hoc calculator or analyst intuition.
