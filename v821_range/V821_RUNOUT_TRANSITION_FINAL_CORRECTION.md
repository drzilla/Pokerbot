# V821_RUNOUT_TRANSITION_FINAL_CORRECTION

Closes Blocker 1 — the false turn "plays the board" wording.

## The defect

The turn shared-board note read *"The paired board (X) gives every remaining player at least one pair (your
best five plays the board)."* This is **false on the turn**: only four community cards exist, so a five-card
hand must still use a hole card. The river note also over-claimed *"your best five is X, supplied by the
board"* for **any** board-only river, including ones where a hole-card kicker plays.

## The fix (`gem_runout_transition.py`)

A category change that Hero does not privately improve now states the shared **minimum** with an explicit
hole-card caveat, and **never** claims board-play on the flop/turn:

- turn single pair → *"The paired board (X) gives every remaining player at least one pair; kickers and
  stronger hands still depend on the hole cards."*
- turn double-paired → *"…every remaining player has at least two pair, with kickers and stronger hands still
  depending on the hole cards."*
- turn trips → *"…trips are on the board, shared by every remaining player, with kickers and full houses still
  depending on the hole cards."*

The strong claim *"all five community cards now form your complete best five (X), shared by every remaining
player"* is emitted **only** when a new helper **proves** it:

```python
def _plays_pure_board(cards, board):
    if len(board) < 5: return False                       # a 4-card turn board can never supply a complete five
    return evaluate_best_hand(cards, board) == evaluate_best_hand(board[:2], board[2:])
```

`evaluate_best_hand` returns a comparable `(rank, name, kickers)` tuple, so the equality means Hero's hole
cards add **nothing** — not even a kicker. On the river where a hole-card kicker (or a higher hand of the same
category) plays, the floor wording is used instead.

## Verification

- **Negative tests** (`test_runout_transition.py` §10–§11): no flop/turn fact contains `plays the board`,
  `supplied by the board`, `complete best five`, or `best five is supplied`; turn shared notes defer kickers to
  the hole cards; `_plays_pure_board` is False on every 4-card board. A **corpus-wide** scan over all three real
  sessions asserts **zero** flop/turn board-play phrases.
- **Positive tests**: a proven pure-board river (`3d2c` on `Ks-Qd-7c-9h-9s`) carries *"all five community cards
  now form your complete best five (pair)…"*; a river where a hole-card kicker plays (`AcTd` …) does **not**.
- **Wiring tests** (`test_runout_wiring.py` §12): wired turn notes never claim board-play; a proven pure-board
  river note does.
- Module suite **78/78**, wiring suite **34/34**.
- **Real corpus**: `_v821_runout_pilot.py` MEASURED audit all zero; regenerated examples/samples carry the
  corrected wording.
- **Generated reports**: the decompressed lazy payloads of the AUTO_ONLY (V7) and analyst-integrated (V2)
  reports contain **0** `plays the board` / `supplied by the board` occurrences.
- **Manual review RE-EVALUATED** (`_v821_review_check.py`): 46/46 PASS against the corrected rules — and one
  river case (`TM6039960337`) correctly **dropped** the over-claim (a hole-card kicker plays, so it now uses
  the floor). See `V821_RUNOUT_TRANSITION_MANUAL_REVIEW_LEDGER.md`.

Docs updated in place: `..._SEMANTIC_CONTRACT.md`, `V821_RANGE_REASONING_CURRENT_STATE.md`,
`..._TRUST_MODEL.md`.
