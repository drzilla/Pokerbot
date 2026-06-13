# Phase 4.5 — Documented Test Gaps

Tracked gaps from the Phase 4.5 visual-layer implementation.
Each gap has a risk level and a mitigation note.

---

## Gap 1 — GTOW `partial` render branch

**Status:** CLOSED (v7.99.32). TM10000003 preflop-only hand added to enriched
fixture; `test_enriched_gtow_ready_and_disabled` now exercises all three
GTOW render branches (ready / approximate / disabled) end-to-end.

---

## Gap 2 — Modal JS (manual browser test)

**Risk:** Medium
**What:** No automated test clicks a pill and verifies the modal opens with
exactly one hand. The scaffold HTML + JS are structurally verified (present
in output, `handSiblingNodes` confirmed absent, `querySelector` +
`cloneNode(true)` confirmed), but DOM interaction is untestable in Python.

**Manual checklist — run before trusting popups:**

1. Open a generated HTML report on `file://` protocol.
2. Click 3 pills in different body sections (e.g. S2 punt, S13 cleared,
   S3 strategic leak). Each must open a modal showing **exactly one hand**
   (no sibling contamination).
3. Click the X button — modal closes.
4. Press Escape — modal closes.
5. Click the dark backdrop — modal closes.
6. Click a "Relevant hands" button on any section — list appears with
   hand IDs. Click one — single-hand modal opens for that hand.
7. In the modal, set a review status and type a note — verify "Auto-saved"
   appears. Close and reopen the same hand — review state persists.
8. Resize browser to mobile width (~375px). Repeat steps 2-6 — modal
   should scroll vertically, not overflow.

---

## Gap 3 — Relevant-hands list drill-through JS

**Risk:** Low
**What:** Tests verify the list renders correct hand IDs, but don't verify
clicking a list entry calls `openHand()`. Same JS limitation as Gap 2.
**Mitigation:** Covered by Gap 2 manual checklist step 6.

---

## Gap 4 — localStorage review notes

**Risk:** Low
**What:** `saveReview()` / `loadReview()` in the modal JS are untested.
They use `try/catch` for graceful degradation when storage is blocked.
**Mitigation:** Covered by Gap 2 manual checklist step 7. Non-critical
UX feature with built-in error handling.

---

## Gap 5 — XIV.B cite-group rendering details

**Risk:** Low-medium
**What:** The category emoji logic on XIV.B cite-group headers
(wide-open / missed-open / mistake / MDA / pick / tail-fold) is exercised
only when matching anchor patterns appear in the fixture. The enriched
fixture produces XIV.B groups but does not trigger all emoji categories.
Also: `_xivb_flag_note` (detector-flagged but un-analyst-reviewed hands)
and `_why_here_text` default path are not specifically tested.
**Mitigation:** Cosmetic rendering — wrong emoji or missing "Why here"
text would be noticeable in visual review but not a data-integrity issue.

---

## Gap 6 — Bounty (PKO) stack-context branch

**Risk:** Low
**What:** The stack-context `<details>` has a bounty coverage path
(`is_bounty: True` showing "Hero covers" / "covers Hero"). The enriched
fixture uses `is_bounty: False`, so the bounty branch is untested in
integration. PKO URL derivation is unit-tested in `test_gtow.py`.
**Mitigation:** Add a PKO hand to the enriched fixture if PKO sessions
become common in the production pipeline.

---

## Gap 7 — Contrast CSS in rendered output

**Risk:** Very low
**What:** B3 lint tests verify the rule fires on synthetic blocks, but
no test checks that the inline CSS fixes (`tr.highlight td { color: #1e293b }`
etc.) actually appear in rendered HTML.
**Mitigation:** CSS is hardcoded in `_html_wrap()` — if it compiles,
it ships. Visual spot-check in any rendered report confirms contrast.

---

## Gap 8 — `render_md` GTOW flag path

**Risk:** Very low
**What:** The `render_md()` path has `gtow_links` param and calls
`_resolve_gtow_flag()`, but no test calls it. Code is structurally
identical to `render_html()`.
**Mitigation:** Markdown output is secondary (HTML is the primary
deliverable). The shared `_resolve_gtow_flag()` function is tested
via the HTML path.
