# V821_RUNOUT_TRANSITION_REPORT_INTEGRATION

Status: **DESIGNED, NOT WIRED.** The descriptive object and its production renderer (`transition_note_text`)
are complete and validated; the live wire into the hand-detail street commentary is specified below but was
**not** landed this pass, because doing it safely requires changes across multiple delicate call sites plus a
full-report re-validation (6-width browser + 30 manual reviews + the v8.20 QA suite) that could not be
completed and proven green this session. Landing a partially-validated change to the shipped report would
violate the trust mandate, so the wire is left as the single named remaining blocker.

## Seam

`gem_report_draft/_hand_grid.py :: _split_argument_into_notes(...)` builds per-street commentary as
`by_street[{preflop,flop,turn,river}]` lists of sentences, then (per-street loop ≈ line 429) joins each into a
note and attaches it to the Hero action on that street; the note is rendered by the canonical pipeline
(`gem_report_draft._html._md_inline`). This is the existing report component and register-styled note path —
no new HTML component is introduced.

## The wire (exact)

1. **Thread the hand object** `h` into `_split_argument_into_notes` (currently it does not receive it). Update
   the signature and all **four** call sites in `gem_report_draft/sections_xiv.py` (≈ lines 3123, 3143, 4267,
   4288) to pass `h`.
2. **Inject after the single-narrative override block** (after ≈ line 415, before the per-street loop), so the
   override cannot wipe the injected note:

   ```python
   import gem_runout_transition as _rt
   for street in ('turn', 'river'):
       if not hero_actions_by_street.get(street):
           continue
       rec = next((r for r in _rt.transitions_for_hand(h)
                   if r.get('street') == street and not r.get('unresolved')), None)
       if rec:
           note = _rt.transition_note_text(rec)      # '' for unresolved -> nothing injected
           if note:
               by_street[street].append(note)        # flows through attach + _md_inline unchanged
   ```
   Compute `transitions_for_hand(h)` once per hand and reuse for both streets.

## Required behaviour (from the brief)

- At most **one** block per street; only on a **resolved** eligible turn/river decision; **no** empty
  placeholder for unresolved (guaranteed: `transition_note_text` returns `''`).
- Distinguish **Factual** (the descriptive facts) from **Insufficient evidence** (the relative-strength /
  action line) — the note text already carries both, with the strategic line explicitly marked. (A literal
  register chip can be added by reusing the existing register styling rather than inline styles.)
- **No Coaching register** in this MVP.
- Preserve Board + Hero context, the Action column, and existing commentary; preserve sticky headers and
  navigation; **do not touch** `sec-SL` or Results state.

## Risks to clear before landing (why it is gated)

- `_split_argument_into_notes` is heavily revised (B83/B95/B108/B142/B143/B145): the single-narrative override,
  the `(N)` note-pill numbering, `action_to_tone`, and the "leave non-key-street actions unmarked" behaviour
  must all still hold once a turn/river note is injected. The injected note becoming a numbered `(N)` pill on a
  street the analyst left unmarked is the main interaction to verify.
- Four call sites must thread `h` consistently.
- Full re-validation required: `_test_scratch.py` (2024), `verify_release.py`, anchor checks, seven-fixture
  Results, mobile-360 overflow, a real full report render with the block visible, one analyst `--quick`, an
  analyst-packet comparison (must show **0** added decisions), and browser checks at 1280/1440/1920/360/390/430
  with zero page-level overflow and no sticky overlap, plus ≥30 manually-reviewed real rendered transitions.

## Current validation of the piece that is done

`transition_note_text` is rendered through the **real** renderer `_md_inline` in `test_runout_transition.py`
(safe-escaping checks pass) and in `RENDERED_EXAMPLES.md`. Adding the new module did **not** regress the
baseline: `_test_scratch.py` 2024/2024, `verify_release.py` exit 0, import smoke OK — the report path is
untouched on this branch.
