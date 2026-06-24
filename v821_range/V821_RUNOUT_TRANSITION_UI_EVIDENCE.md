# V821_RUNOUT_TRANSITION_UI_EVIDENCE

Browser acceptance of the live transition notes in the **AUTO_ONLY full render** of the real report (1,220
hands), served over localhost with appendix hand cards expanded. The same notes appear in the
analyst-integrated (`--quick`) render. The notes render through the report's per-street note system (numbered
pill + `🧠` tag, street label, `_md_inline`).

## Rendered example (verbatim from the live DOM — corrected wording)

> **TURN** · ② 🧠 **Runout — the Kd.** The paired board (Kd) gives every remaining player at least one pair;
> kickers and stronger hands still depend on the hole cards. Reassess: A paired board makes trips and full
> houses possible for some holdings — reassess one-pair and overpair holdings. **Strategic read: insufficient
> evidence** — relative strength and the correct action are not determinable from objective facts alone.

This is the **corrected** turn shared-board note: no "plays the board" claim, kickers explicitly deferred to
the hole cards. Bold renders as `<strong>` (no literal `**`/underscore artifacts); the note keeps its numbered
pill and street binding. The same hand carries the **same** note in AUTO_ONLY and the analyst-integrated
(`--quick`) render (0 per-hand mismatches across 1,220 hands).

Saved standalone artifacts (faithful render with the report's note CSS, openable in a browser):
`screenshots/runout_note_desktop_1280.html`, `screenshots/runout_note_mobile_390.html`,
`screenshots/runout_note_rendered_text.txt`.

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
  are embedded there and inflate on expand. The rendered-note artifacts (`screenshots/runout_note_*.html`) use
  the report's own note CSS; the lazy payload was independently decompressed and confirmed to carry the
  transition notes on **104 hands**, identical between the AUTO_ONLY and analyst-integrated renders (0 per-hand
  mismatch, 0 within-hand duplication).
