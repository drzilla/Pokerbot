# V821_RUNOUT_TRANSITION_TRUST_MODEL

Provenance and no-calculation invariants for the Runout Transition module. Enforced in
`gem_runout_transition.py`, asserted by `test_runout_transition.py` (49 checks) and the wiring by
`test_runout_wiring.py` (29 checks). Production rendering path:
**`transition_note_text(rec)` → the existing per-street note collection in
`gem_report_draft/_hand_grid.py::_split_argument_into_notes` → the canonical `_md_inline` renderer.** There is
no standalone HTML renderer (`render_html` does not exist).

## Semantic safety (relative strength is never claimed)

The module emits objective facts only. It does **not** use `hero_status`, `improved`, `weakened`,
`counterfeit`, or `has_showdown_value`. Hero "improvement" is credited **only when proven**: Hero's best-five
must beat the **board-only** best-five (`hand_strength_name(board[:2], board[2:])` on the river; board
rank-counts on the turn). A shared/board-driven category change is labelled by its exact property — on the
river *"shared by every remaining player"*; on the turn the precise board fact (*"every remaining player has at
least one pair"* / *"trips are present on the board"* / *"double-paired"*), never a complete board-only
best-five. Relative strength / the correct action is always rendered **Insufficient evidence** (compact bold
label), pending a canonical opponent-range owner.

## Invariants

| Invariant | How enforced | Test |
|---|---|---|
| No later action leaks into an earlier decision | only `build_decision_snapshot(hand, action_index)` is consumed; the ledger is never read past the node | "no future-card leak" / "one record per street" |
| No later board card leaks | street-exact `board_at_decision`; `new_card = board[-1]`, `prev_board = board[:-1]` | "turn record board has exactly 4 cards"; pilot later-card audit = 0 |
| No villain showdown / result fields | the module never reads villain cards / net / showdown; no result keys in the record | pilot result-field audit = 0 |
| Hero improvement is proven, not assumed | `hero_hole_cards_contribute_after` = Hero best-five beats the board-only best-five | "pocket pair on paired board contributes" / "board-only two pair: no contribution" |
| No shared-board false improvement | when contribution is false, no fact claims Hero's hole cards make/improve a hand | pilot shared-board-false-improvement audit = 0 |
| Effective stack is decision-time correct | `snapshot.canonical_effective_decision_depth_bb`; SPR from decision-time contestable pot | record `eff_stack_bb` / `spr` |
| Multiway never uses heads-up rules | `multiway = (active players + Hero) >= 3`; no heads-up-only logic | "multiway hand has >=3 players" |
| Unsupported range language suppressed | no opponent-range owner exists → no range/equity/EV/nut-advantage language in the facts | pilot range-term audit = 0 |
| No raw enum names or markdown artifacts in the report | `_label()` maps enums to player-facing text; the note uses `**bold**` (no `_italic_`, which `_md_inline` would leak) | "no raw enum names" / "no literal markdown underscores" |
| Fail closed | any required canonical owner failure / invalid cards / incomplete snapshot → `unresolved` record, no factual claims, `confidence='none'`, **empty** rendered note | "made/draw/texture/invalid/snapshot failure → unresolved"; "unresolved renders nothing" |
| Each fact has provenance + tier | every `changed`/`remained` fact carries `{fact, source, tier}` (`canonical_made_hand_class` / `canonical_draw_profile` / `canonical_board_texture`) | record `changed[].tier` |
| Renderer performs no strategic calculation | `transition_note_text` only formats `teaching_block` fields; the contribution direction is computed in the module; output goes through the canonical `_md_inline` | wiring escaping test |
| Nothing enters the analyst packet / no LLM | `gem_runout_transition` is not imported by `gem_analyst_packet`; the contract is fully programmatic; the wiring threads only the parsed hand, adds no analyst decision | "analyst packet does not reference gem_runout_transition"; packet before/after diff |
| Wiring is additive | one note max per turn/river street, bound to the first hero action (merged if a note exists), after the single-narrative override; existing notes / numbering / tone unchanged; structured TL;DR notes never corrupted | `test_runout_wiring.py` |

## Canonical owners consumed (no parallel calculator)

| Operand | Owner |
|---|---|
| identity / decision state / eff-stack / SPR / all-in suppression | `gem_decision_snapshot.build_decision_snapshot` |
| best-five made hand (Hero and board-only) | `gem_parser.hand_strength_name` |
| draws / outs / completed / missed | `gem_made_hands.draw_profile` |
| board texture | `gem_analyst_packet._board_texture` |
| transition tags (pair/flush/straight/connectivity/blank, ace-low aware) | deterministic board-card arithmetic over the above (no new evaluator) |
| pot type / position / players / initiative | `gem_parser` hand fields |

## Registers

Descriptive facts → **Factual** register, tiers `canonical_made_hand_class` / `canonical_draw_profile` /
`canonical_board_texture`, confidence `high`. The strategic line → **Insufficient evidence**. The `Coaching`
register is reserved for a future rule-backed layer with a documented owner + acceptance rule, and is **not**
emitted in this MVP.

## Missing infrastructure → debt, not replacement

The strategic recommendation layer and any range/nut-advantage statement require a canonical **opponent-range
/ fold-equity owner** that does not exist. Per the trust mandate this is recorded as engineering debt
(`V821_RANGE_REASONING_DEBT_REGISTER.md`) and rendered as *Insufficient evidence* — never replaced by an
ad-hoc calculator or analyst intuition.
