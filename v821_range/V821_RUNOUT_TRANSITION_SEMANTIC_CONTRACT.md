# V821_RUNOUT_TRANSITION_SEMANTIC_CONTRACT

The corrected, neutral, factual record produced by `gem_runout_transition.build_transition(hand, action_index)`.
Replaces the unsafe improved/weakened/counterfeit/showdown-value model.

## Why the old model was unsafe

The prior contract labelled Hero `improved`/`weakened` from the change in the **best-five hand category**, and
treated any pair-or-better as `has_showdown_value`. On a **shared board change** this is wrong: when the board
pairs, every remaining player's formal category rises (e.g. one-pair → two-pair) without Hero's private cards
improving, and Hero's *relative* strength can actually fall. The category is a fact; "Hero improved" is a
relative-strength claim that needs an opponent-range owner we do not have.

## Corrected fields (objective only)

| Field | Meaning | Canonical source |
|---|---|---|
| `best_five_category_before` / `_after` | Hero's best-five class before/after the card | `gem_parser.hand_strength_name` |
| `category_changed` | the class changed | derived |
| `board_category_before` / `_after` | best-five available from the **board alone** (river: `hand_strength_name(board[:2], board[2:])`; turn: board rank-counts — a board straight/flush needs 5 cards) | `gem_parser.hand_strength_name` |
| `hero_hole_cards_contribute_before` / `_after` | Hero's best-five **beats the board-only best-five** ⇒ his hole cards add something (proven, not assumed) | derived comparison |
| `board_only_or_shared_category` | `not hero_hole_cards_contribute_after` — the category is fully available from the board and shared by the field | derived |
| `draw_completed` | a **real** draw (not a backdoor) became a straight/flush via Hero's hole cards | `gem_made_hands.draw_profile` |
| `real_draw_missed` | a real draw was present before, is gone, and did not complete | `gem_made_hands.draw_profile` |
| `transition_tags` | objective board tags (below) | board arithmetic over canonical inputs |

**Removed:** `hero_status` (improved/weakened/unchanged), `counterfeit` tag, `has_showdown_value`,
`draw_busted`, and the strategic `planning_implication` label.

## Wording rules (enforced + tested)

- Hero contribution is stated **only** when `hero_hole_cards_contribute_after` is True: *"Your hole cards now
  make two pair (was pair)."* / *"Your flush draw completed: your hole cards now make a flush."*
- A shared/board-driven category change states the shared **minimum** and **never** claims board-play on the
  flop/turn (only four community cards exist, so a five-card hand must still use a hole card):
  - turn single pair: *"The paired board (X) gives every remaining player at least one pair; kickers and
    stronger hands still depend on the hole cards."*
  - turn double-paired: *"…every remaining player has at least two pair, with kickers and stronger hands still
    depending on the hole cards."*; turn trips: *"…trips are on the board, shared by every remaining player,
    with kickers and full houses still depending on the hole cards."*
  - **"the board now forms your complete best five"** is emitted **only** on a river board that is *proven* to
    be Hero's exact best five — `_plays_pure_board(cards, board)` (`evaluate_best_hand(cards, board) ==
    evaluate_best_hand(board[:2], board[2:])`, i.e. the hole cards add nothing, kicker included). When a
    hole-card kicker (or a higher hand of the same category) plays, the river uses the floor wording instead.
- A missed real draw with no made hand: *"Your draw did not complete and your hole cards do not make a hand on
  this board."*
- **Never** emitted: `improved`, `weakened`, `counterfeit`, `showdown value` (batch-scanned in tests + pilot).
- Relative strength / correct action is always rendered **Insufficient evidence**: *"Relative hand strength and
  the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist."*

## Transition tags (objective board facts)

`board_paired` (+`top_card_pair`/`low_card_pair`), `double_paired`, `trips_on_board`, `overcard`,
`undercard_or_brick`, `flush_card` (3 suited) / `four_flush` (4) / `monotone_complete` (5),
`connectivity_increase` (3 board cards in a 5-rank window, **ace plays high and low**), `four_to_a_straight`
(4 in a window), `straight_on_board` (5 in a window), `blank` (emitted **only** when all evidence resolves and
nothing structural or Hero-state changed). `counterfeit` and `connectivity_decrease` are **not** tags (no
canonical private-card rule; a card cannot reduce board coordination).

## Fail-closed (any required canonical owner failure ⇒ unresolved)

`build_transition` returns `{'unresolved': True, 'unresolved_reason': ...}` with **no** factual claims,
confidence `none`, and an **empty** rendered note for: `missing_made_hand_evidence`, `missing_draw_evidence`,
`missing_texture_evidence`, `invalid_cards`, `incomplete_decision_snapshot`, plus eligibility suppressions
`not_a_turn_or_river_node` and `all_in_or_no_future_decision`. Each owner-failure path has a dedicated test.

## Eligibility & uniqueness

One record per **street** (the first Hero turn/river decision on that street), via `transitions_for_hand` —
the product path. No later action / later board card / showdown leakage (street-exact `board_at_decision`;
`new_card = board[-1]`; `prev_board = board[:-1]`).
