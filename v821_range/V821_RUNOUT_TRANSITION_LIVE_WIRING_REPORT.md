# V821_RUNOUT_TRANSITION_LIVE_WIRING_REPORT

The descriptive Runout Transition note is now **live in the real hand-detail report surface**, through the
existing per-street note system. No standalone inline-style HTML component was added.

## What was wired

**Seam:** `gem_report_draft/_hand_grid.py :: _split_argument_into_notes(...)` builds the per-street note
collection that the appendix hand-grid renders (`_render_hand_grid_table`) and the canonical `_md_inline`
renderer formats.

1. **Hand threaded through** — added a `hand=None` parameter to `_split_argument_into_notes`, passed at **all
   four** call sites in `gem_report_draft/sections_xiv.py` (the two `_emit_section_xiv_appendix` render loops:
   the analyst/aggression path ≈3123/3143 via the per-hand closure, and the `for hid in _hids_render` path
   ≈4267/4288 via `h = hands_by_id.get(hid)`).
2. **Computed once per hand** — `transitions_for_hand(hand)` is called once; resolved turn/river records are
   indexed by street (`_tx_by_street`).
3. **Additive finalizer** — `_attach_runout_transition(notes, a2n, a2t, snn)` wraps **every** return path
   (structured TL;DR fast-path, the no-argument early return, and the normal path), so the note survives the
   structured-argument path and the single-narrative override. For each of turn/river it appends **at most one**
   note bound to the **first hero action** on that street, **merging** into an existing note there (mirrors the
   existing general-note merge) rather than creating a duplicate pill.
4. **Unresolved → nothing** — `transition_note_text` returns `''` for unresolved/all-in records, so no empty
   placeholder is produced.
5. **Through the canonical renderer** — the note is plain Markdown (`**bold**`, no `_italic_` artifacts) and is
   rendered by the report's `_md_inline` like any other note.

## Invariants preserved (tested)

- Existing analyst notes, **note-pill numbering** (contiguous, no dupes), and **tone** are unchanged — the
  finalizer only appends/merges. (`test_runout_wiring.py` §5/§6)
- A **structured TL;DR** note is never corrupted: on a collision the transition binds to a later hero action or
  is omitted for that street, never appended into the TL;DR block. (verified live + §4)
- Board + Hero column, Action column, sticky headers, navigation, Results, `sec-SL`, the analyst-packet schema,
  and analyst selection are untouched.

## Verified live in the real report

Generated a full report on a real session (1,220 hands, `_session_20260527`):
- **109 transition notes** present in the production HTML — embedded in `PB_PAYLOADS.lazyHands` (the report's
  `deflate-raw+base64` lazy payload); decompressed and confirmed (`Runout —`, `became more connected`,
  `hole cards now make`, `Strategic read`, `at least one pair`). The same 109 appear in the secondary `.md`.
- **68 hands** had a resolved turn/river transition; the debug trace confirmed the wiring fired with the hand
  object on those hands. All-in nodes were suppressed (no note).
- Browser-rendered correctly at desktop and mobile (see `V821_RUNOUT_TRANSITION_UI_EVIDENCE.md`).

## Freeze pins re-pinned (intentional, reviewed change)

- `_test_scratch.py` `T-V25-15` `_hand_grid.py` SHA256 → `d325263f…` (was `9a6f64f9…`).
- `verify_release.py` MANIFEST hashes+sizes for `_hand_grid.py` (`d325263f…`, 98750 B) and `sections_xiv.py`
  (`4242653f…`, 285272 B). Both files matched the manifest before the edit; re-pinned to the reviewed state.
  `verify_release.py` exits 0.
