# V821 Runout Transition — rendered player-facing examples

Each block is the Markdown note from `gem_runout_transition.transition_note_text(rec)` rendered through the **real** report note renderer `gem_report_draft._html._md_inline` (the same pipeline the hand-detail per-street commentary uses — no separate inline-style mini-renderer). Deterministic, canonical facts only; the contribution direction is computed in the module. Inline markdown only (no fixed pixel widths), so it reflows on desktop and mobile.


## Hero completes a flush with hole cards (turn)
- Qh-7h-2c → **Qh-7h-2c-Th** | category `high_card → flush` | hole-cards contribute: `True` | tags `['flush_card']`

**Player-facing (rendered):**

> Runout — the Th. Your flush draw completed: your hole cards now make flush. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the Th.</strong> Your flush draw completed: your hole cards now make flush. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.
```

## Shared board change — board pairs, no Hero improvement (turn)
- Ks-Qd-7c → **Ks-Qd-7c-Kh** | category `high_card → pair` | hole-cards contribute: `False` | tags `['board_paired', 'top_card_pair']`

**Player-facing (rendered):**

> Runout — the Kh. Your best-five category changed from high_card to pair because the board changed; this category is now available from the board and is shared by every remaining player. The board paired (Kh). Reassess: A paired board makes trips and full houses possible for the field -- reassess one-pair and overpair holdings. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the Kh.</strong> Your best-five category changed from high_card to pair because the board changed; this category is now available from the board and is shared by every remaining player. The board paired (Kh). Reassess: A paired board makes trips and full houses possible for the field -- reassess one-pair and overpair holdings. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.
```

## Hero private improvement — pocket pair, board pairs low card (turn)
- Qs-7d-2c → **Qs-7d-2c-7h** | category `pair → two_pair` | hole-cards contribute: `True` | tags `['board_paired', 'low_card_pair']`

**Player-facing (rendered):**

> Runout — the 7h. Your hole cards now make two_pair (was pair). The board paired (7h). Reassess: A paired board makes trips and full houses possible for the field -- reassess one-pair and overpair holdings. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the 7h.</strong> Your hole cards now make two_pair (was pair). The board paired (7h). Reassess: A paired board makes trips and full houses possible for the field -- reassess one-pair and overpair holdings. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.
```

## Flush now possible, Hero not made (turn)
- 7h-6h-2c → **7h-6h-2c-Th** | category `high_card → high_card` | hole-cards contribute: `False` | tags `['connectivity_increase', 'flush_card', 'overcard']`

**Player-facing (rendered):**

> Runout — the Th. A hearts flush is now possible on the board. The board became more connected (straight coordination increased). An overcard (Th) arrived above the previous board. Reassess: A flush is now possible -- reassess thin value bets and continued bluffs. An overcard arrived -- a prior top pair or overpair may no longer be the top of the board. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the Th.</strong> A hearts flush is now possible on the board. The board became more connected (straight coordination increased). An overcard (Th) arrived above the previous board. Reassess: A flush is now possible -- reassess thin value bets and continued bluffs. An overcard arrived -- a prior top pair or overpair may no longer be the top of the board. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.
```

## Blank — nothing meaningful changed (turn)
- Ks-9d-2c → **Ks-9d-2c-5h** | category `pair → pair` | hole-cards contribute: `True` | tags `['blank']`

**Player-facing (rendered):**

> Runout — the 5h. The 5h is a blank: it did not change your best-five category, your draws, or the board structure. Still true: Your hole cards still make pair. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the 5h.</strong> The 5h is a blank: it did not change your best-five category, your draws, or the board structure. Still true: Your hole cards still make pair. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.
```

## Board four-to-a-straight via the wheel (turn)
- As-2d-3c → **As-2d-3c-4h** | category `high_card → high_card` | hole-cards contribute: `False` | tags `['connectivity_increase', 'four_to_a_straight']`

**Player-facing (rendered):**

> Runout — the 4h. The board is now four-to-a-straight. Reassess: A straight is now possible for the field -- reassess one-pair holdings. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the 4h.</strong> The board is now four-to-a-straight. Reassess: A straight is now possible for the field -- reassess one-pair holdings. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.
```

## Board-only two pair on the river (no Hero contribution)
- Ks-Kd-7c-7h → **Ks-Kd-7c-7h-9s** | category `two_pair → two_pair` | hole-cards contribute: `False` | tags `['double_paired']`

**Player-facing (rendered):**

> Runout — the 9s. Still true: Your best-five (two_pair) comes from the board and is unchanged; it is shared by the field. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.

**HTML (via the real renderer `_md_inline`):**

```html
<strong>Runout — the 9s.</strong> Still true: Your best-five (two_pair) comes from the board and is unchanged; it is shared by the field. _Insufficient evidence for a strategic call:_ Relative hand strength and the correct action are unresolved here: that needs a canonical opponent-range owner, which does not exist. Reassess the changed board features rather than assuming a stronger relative position.
```
