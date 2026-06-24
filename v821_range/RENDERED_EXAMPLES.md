# V821 Runout Transition - rendered player-facing examples

Rendered by `gem_runout_transition.render_html`. Deterministic, canonical facts only; the improve/weaken direction is computed in the module, not the renderer. Mobile-safe (no fixed pixel widths).


## Improved to flush (turn)

- Qh-7h-2c -> **Qh-7h-2c-Th** | status `improved` | tags `['flush_card']` | register `Factual` | mobile-safe: True

**Player-facing:**

> Runout — the Th Factual What changed: Your hand improved from high_card to flush. Your draw completed. Still valid: You still hold flush (showdown value). Insufficient evidence for a reliable action recommendation -- reassess the changed board features.

**Desktop HTML:**

```html
<div style='margin:6px 0;padding:8px 12px;border:1px solid #e5e7eb;border-radius:10px;background:#fff'><div style='font-weight:700;color:#111827'>Runout — the Th<span style='margin-left:6px;padding:2px 8px;border-radius:10px;background:#eef2ff;color:#3730a3;font-size:.78em;font-weight:700'>Factual</span></div><div style='color:#374151'><strong>What changed:</strong> Your hand improved from high_card to flush. Your draw completed.</div><div style='color:#374151'><strong>Still valid:</strong> You still hold flush (showdown value).</div><div style='margin-top:2px;color:#6b7280;font-size:.92em'>Insufficient evidence for a reliable action recommendation -- reassess the changed board features.</div></div>
```


## Flush now possible, Hero not made (turn)

- 7h-6h-2c -> **7h-6h-2c-Th** | status `unchanged` | tags `['connectivity_increase', 'flush_card', 'overcard']` | register `Factual` | mobile-safe: True

**Player-facing:**

> Runout — the Th Factual What changed: A hearts flush is now possible. An overcard (Th) arrived above the previous board. Reassess: A flush is now possible -- reassess thin value bets and continued bluffs. Insufficient evidence for a reliable action recommendation -- reassess the changed board features.

**Desktop HTML:**

```html
<div style='margin:6px 0;padding:8px 12px;border:1px solid #e5e7eb;border-radius:10px;background:#fff'><div style='font-weight:700;color:#111827'>Runout — the Th<span style='margin-left:6px;padding:2px 8px;border-radius:10px;background:#eef2ff;color:#3730a3;font-size:.78em;font-weight:700'>Factual</span></div><div style='color:#374151'><strong>What changed:</strong> A hearts flush is now possible. An overcard (Th) arrived above the previous board.</div><div style='color:#374151'><strong>Reassess:</strong> A flush is now possible -- reassess thin value bets and continued bluffs.</div><div style='margin-top:2px;color:#6b7280;font-size:.92em'>Insufficient evidence for a reliable action recommendation -- reassess the changed board features.</div></div>
```


## Board paired on the river, overpair holds (river)

- Qh-8d-2c-5s -> **Qh-8d-2c-5s-8c** | status `improved` | tags `['board_paired', 'low_card_pair']` | register `Factual` | mobile-safe: True

**Player-facing:**

> Runout — the 8c Factual What changed: Your hand improved from pair to two_pair. The board paired (8c). Still valid: You still hold two_pair (showdown value). Reassess: A pair on board makes trips/full houses possible -- reassess one-pair and overpair hands. Insufficient evidence for a reliable action recommendation -- reassess the changed board features.

**Desktop HTML:**

```html
<div style='margin:6px 0;padding:8px 12px;border:1px solid #e5e7eb;border-radius:10px;background:#fff'><div style='font-weight:700;color:#111827'>Runout — the 8c<span style='margin-left:6px;padding:2px 8px;border-radius:10px;background:#eef2ff;color:#3730a3;font-size:.78em;font-weight:700'>Factual</span></div><div style='color:#374151'><strong>What changed:</strong> Your hand improved from pair to two_pair. The board paired (8c).</div><div style='color:#374151'><strong>Still valid:</strong> You still hold two_pair (showdown value).</div><div style='color:#374151'><strong>Reassess:</strong> A pair on board makes trips/full houses possible -- reassess one-pair and overpair hands.</div><div style='margin-top:2px;color:#6b7280;font-size:.92em'>Insufficient evidence for a reliable action recommendation -- reassess the changed board features.</div></div>
```


## Blank turn, nothing changed

- Ah-7d-2c -> **Ah-7d-2c-3s** | status `unchanged` | tags `['blank_vs_hero_draws']` | register `Factual` | mobile-safe: True

**Player-facing:**

> Runout — the 3s Factual What changed: The 3s is a blank -- it did not change your hand or the board structure. Insufficient evidence for a reliable action recommendation -- reassess the changed board features.

**Desktop HTML:**

```html
<div style='margin:6px 0;padding:8px 12px;border:1px solid #e5e7eb;border-radius:10px;background:#fff'><div style='font-weight:700;color:#111827'>Runout — the 3s<span style='margin-left:6px;padding:2px 8px;border-radius:10px;background:#eef2ff;color:#3730a3;font-size:.78em;font-weight:700'>Factual</span></div><div style='color:#374151'><strong>What changed:</strong> The 3s is a blank -- it did not change your hand or the board structure.</div><div style='margin-top:2px;color:#6b7280;font-size:.92em'>Insufficient evidence for a reliable action recommendation -- reassess the changed board features.</div></div>
```


## Straight threat on the board (turn)

- 9h-8d-7c -> **9h-8d-7c-6s** | status `unchanged` | tags `['connectivity_increase', 'straight_completing', 'undercard_or_brick']` | register `Factual` | mobile-safe: True

**Player-facing:**

> Runout — the 6s Factual What changed: The board is now straight-coordinated. Reassess: A straight is now possible -- reassess one-pair hands. Insufficient evidence for a reliable action recommendation -- reassess the changed board features.

**Desktop HTML:**

```html
<div style='margin:6px 0;padding:8px 12px;border:1px solid #e5e7eb;border-radius:10px;background:#fff'><div style='font-weight:700;color:#111827'>Runout — the 6s<span style='margin-left:6px;padding:2px 8px;border-radius:10px;background:#eef2ff;color:#3730a3;font-size:.78em;font-weight:700'>Factual</span></div><div style='color:#374151'><strong>What changed:</strong> The board is now straight-coordinated.</div><div style='color:#374151'><strong>Reassess:</strong> A straight is now possible -- reassess one-pair hands.</div><div style='margin-top:2px;color:#6b7280;font-size:.92em'>Insufficient evidence for a reliable action recommendation -- reassess the changed board features.</div></div>
```
