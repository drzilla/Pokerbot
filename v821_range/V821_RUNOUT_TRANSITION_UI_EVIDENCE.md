# V821_RUNOUT_TRANSITION_UI_EVIDENCE

Browser acceptance of the live transition notes in the real report
(`Pokerbot_Knockman_20260527-28_AUTO_ONLY_V4.html`, served over localhost; appendix hand cards expanded). The
notes render through the report's per-street note system (numbered pill + `🧠` tag, street label, `_md_inline`).

## Rendered example (verbatim from the live DOM)

> **TURN** · ① 🧠 **Runout — the Th.** The board became more connected. An overcard (Th) arrived above the
> previous board. Still true: Your hole cards still make pair. Reassess: An overcard arrived — a prior top pair
> or overpair may no longer be top of the board. **Strategic read: insufficient evidence** — relative strength
> and the correct action are not determinable from objective facts alone.
>
> **RIVER** · ② 🧠 **Runout — the 3h.** Your draw did not complete, though your hole cards still make pair.
> Still true: Your hole cards still make pair. **Strategic read: insufficient evidence** — …

Bold renders as `<strong>` (no literal `**`/underscore artifacts); the turn note is pill ①, the river note is
pill ② (numbering preserved); both bound to the correct street.

## Six-width acceptance (measured in-browser)

| Width | Page horizontal overflow | Transition note width | Note clipped | Screenshot |
|---|---|---|---|---|
| 360 | **0 px** | 272 px | no | captured (mobile) |
| 390 | **0 px** | 302 px | no | captured (mobile — both notes visible) |
| 430 | **0 px** | 342 px | no | captured |
| 1280 | **0 px** | ~911 px | no | captured (desktop) |
| 1440 | **0 px** | 1002 px | no | captured |
| 1920 | **0 px** | 1002 px (content max-width) | no | captured; sticky bar bottom 194 px — no overlap with the note |

Verified at every width: **no page-level horizontal overflow** (`documentElement.scrollWidth ==
clientWidth`), the transition note **reflows** from 272 px (360) to 1002 px (≥1440) and is **never clipped**
(`right <= viewport`), no sticky-header overlap, Board+Hero and Action columns and existing Commentary remain
intact, and the note is **readable** (wraps cleanly) on desktop and mobile.

## Notes

- Screenshots captured at 360 / 390 / 1280; layout health at 430 / 1440 / 1920 verified via DOM geometry
  (`getBoundingClientRect` + `scrollWidth/clientWidth`), the same method used for the v8.18 mobile-overflow
  evidence. The programmatic `_qa_mobile_360_overflow.py` gate also passes at 360/390/430.
- The production HTML uses lazy hand cards (`PBLazy`, `deflate-raw+base64` `PB_PAYLOADS.lazyHands`); the notes
  are embedded there and inflate on expand. The screenshots use the non-lazy full render so the notes are
  directly visible; the lazy payload was independently decompressed and confirmed to contain the same 109 notes.
