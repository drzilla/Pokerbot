# V821 Runout Transition — rendered player-facing examples

Each block is the Markdown note from `gem_runout_transition.transition_note_text(rec)` rendered through the **real** report note renderer `gem_report_draft._html._md_inline` (the same pipeline the hand-detail per-street commentary uses — no separate inline-style mini-renderer). Deterministic, canonical facts only; the contribution direction is computed in the module. Inline markdown only (no fixed pixel widths), so it reflows on desktop and mobile.


## Hero completes a flush with hole cards (turn)
- Qh-7h-2c → **Qh-7h-2c-Th** | category `high_card → flush` | hole-cards contribute: `True` | tags `['flush_card']`

**Player-facing (rendered):**

> Runout — the Th. Your flush draw completed: your hole cards now make a flush. A third heart arrived; a flush is now possible for holdings containing two hearts. Reassess: A flush is now possible -- reassess thin value bets and continued bluffs. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the Th.</strong> Your flush draw completed: your hole cards now make a flush. A third heart arrived; a flush is now possible for holdings containing two hearts. Reassess: A flush is now possible -- reassess thin value bets and continued bluffs. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```

## Shared board change — board pairs, no Hero improvement (turn)
- Ks-Qd-7c → **Ks-Qd-7c-Kh** | category `high_card → pair` | hole-cards contribute: `False` | tags `['board_paired', 'top_card_pair']`

**Player-facing (rendered):**

> Runout — the Kh. The paired board (Kh) gives every remaining player at least one pair (your best five plays the board). Reassess: A paired board makes trips and full houses possible for some holdings -- reassess one-pair and overpair holdings. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the Kh.</strong> The paired board (Kh) gives every remaining player at least one pair (your best five plays the board). Reassess: A paired board makes trips and full houses possible for some holdings -- reassess one-pair and overpair holdings. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```

## Hero private improvement — pocket pair, board pairs low card (turn)
- Qs-7d-2c → **Qs-7d-2c-7h** | category `pair → two_pair` | hole-cards contribute: `True` | tags `['board_paired', 'low_card_pair']`

**Player-facing (rendered):**

> Runout — the 7h. Your hole cards now make two pair (was pair). The board paired (7h). Reassess: A paired board makes trips and full houses possible for some holdings -- reassess one-pair and overpair holdings. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the 7h.</strong> Your hole cards now make two pair (was pair). The board paired (7h). Reassess: A paired board makes trips and full houses possible for some holdings -- reassess one-pair and overpair holdings. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```

## Three suited — a flush is possible for two-of-suit holdings (turn)
- 7h-6h-2c → **7h-6h-2c-Th** | category `high_card → high_card` | hole-cards contribute: `False` | tags `['connectivity_increase', 'flush_card', 'overcard']`

**Player-facing (rendered):**

> Runout — the Th. A third heart arrived; a flush is now possible for holdings containing two hearts. The board became more connected. An overcard (Th) arrived above the previous board. Reassess: A flush is now possible -- reassess thin value bets and continued bluffs. An overcard arrived -- a prior top pair or overpair may no longer be top of the board. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the Th.</strong> A third heart arrived; a flush is now possible for holdings containing two hearts. The board became more connected. An overcard (Th) arrived above the previous board. Reassess: A flush is now possible -- reassess thin value bets and continued bluffs. An overcard arrived -- a prior top pair or overpair may no longer be top of the board. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```

## Four suited — one-of-suit holdings make a flush (turn)
- 7h-6h-2h → **7h-6h-2h-Th** | category `high_card → high_card` | hole-cards contribute: `False` | tags `['connectivity_increase', 'four_flush', 'overcard']`

**Player-facing (rendered):**

> Runout — the Th. The board is now four-heart; any player holding one heart can make a flush. The board became more connected. An overcard (Th) arrived above the previous board. Reassess: An overcard arrived -- a prior top pair or overpair may no longer be top of the board. Four to a flush is on the board -- reassess thin value bets and continued bluffs. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the Th.</strong> The board is now four-heart; any player holding one heart can make a flush. The board became more connected. An overcard (Th) arrived above the previous board. Reassess: An overcard arrived -- a prior top pair or overpair may no longer be top of the board. Four to a flush is on the board -- reassess thin value bets and continued bluffs. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```

## Five suited — flush on the board, shared (river)
- 7h-6h-2h-Th → **7h-6h-2h-Th-Qh** | category `high_card → flush` | hole-cards contribute: `False` | tags `['monotone_complete', 'overcard']`

**Player-facing (rendered):**

> Runout — the Qh. A heart flush is now present on the board and is shared unless a player can make a higher flush. An overcard (Qh) arrived above the previous board. Reassess: A heart flush is on the board -- reassess unless you hold a higher card of that suit. An overcard arrived -- a prior top pair or overpair may no longer be top of the board. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the Qh.</strong> A heart flush is now present on the board and is shared unless a player can make a higher flush. An overcard (Qh) arrived above the previous board. Reassess: A heart flush is on the board -- reassess unless you hold a higher card of that suit. An overcard arrived -- a prior top pair or overpair may no longer be top of the board. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```

## Straight present on the board, shared (river)
- 9c-8d-7h-6s → **9c-8d-7h-6s-5c** | category `high_card → straight` | hole-cards contribute: `False` | tags `['connectivity_increase', 'four_to_a_straight', 'straight_on_board', 'undercard_or_brick']`

**Player-facing (rendered):**

> Runout — the 5c. A straight is now present on the board and is shared unless a player can make a higher straight. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the 5c.</strong> A straight is now present on the board and is shared unless a player can make a higher straight. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```

## Blank — nothing meaningful changed (turn)
- Ks-9d-2c → **Ks-9d-2c-5h** | category `pair → pair` | hole-cards contribute: `True` | tags `['blank']`

**Player-facing (rendered):**

> Runout — the 5h. The 5h is a blank: it did not change your best five, your draws, or the board structure. Still true: Your hole cards still make pair. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the 5h.</strong> The 5h is a blank: it did not change your best five, your draws, or the board structure. Still true: Your hole cards still make pair. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```

## Board four-to-a-straight via the wheel (turn)
- As-2d-3c → **As-2d-3c-4h** | category `high_card → high_card` | hole-cards contribute: `False` | tags `['connectivity_increase', 'four_to_a_straight']`

**Player-facing (rendered):**

> Runout — the 4h. The board is now four-to-a-straight; some holdings can complete a straight. Reassess: Some holdings can now complete a straight -- reassess one-pair holdings. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the 4h.</strong> The board is now four-to-a-straight; some holdings can complete a straight. Reassess: Some holdings can now complete a straight -- reassess one-pair holdings. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```

## Board-only two pair on the river (no Hero contribution)
- Ks-Kd-7c-7h → **Ks-Kd-7c-7h-9s** | category `two_pair → two_pair` | hole-cards contribute: `False` | tags `['double_paired']`

**Player-facing (rendered):**

> Runout — the 9s. Still true: Your best five (two pair) comes from the board and is unchanged. Strategic read: insufficient evidence -- relative strength and the correct action are not determinable from objective facts alone.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the 9s.</strong> Still true: Your best five (two pair) comes from the board and is unchanged. <strong>Strategic read: insufficient evidence</strong> -- relative strength and the correct action are not determinable from objective facts alone.
```
