# v8.18.0 Wave-1 + Wave-2 — Integrated Release-Candidate Completion Report

Branch `feature/v8180-wave1-wave2-integration` off the W1-A checkpoint `2ad4059` (off released `main
@ 378846b`, tag `v8.17.1`, held). One integration branch, sequential implementation (the features
share `sections_xiv.py` / `_html.py` / `sections_tournaments.py`). NOT merged / tagged / pushed.

This report is honest about depth: each lane is marked **Complete**, **Aligned/Verified** (the feature
shipped in v8.17 and was brought to the contract + verified), or **Partial** (foundation delivered,
remainder staged).

## 1. W1-A status corrections — **Complete** (mandatory, gating)

- **§1.1 UNASSESSED state.** The typed model is now MISTAKE | CONDITIONAL | CLEARED | **UNASSESSED** |
  UNGRADED. A gradeable hand with no positive/negative adjudication is UNASSESSED ("Not reviewed"),
  never CLEARED. `CLEARED` now requires an explicit positive adjudication; a secondary reason never
  manufactures a positive grade. Updated: enum, precedence, serialization, CSS (distinct slate-blue
  `.fs-unassessed`), label "Not reviewed", legend rationale, tests, distribution, criteria freeze.
  Real-report effect: the 813 unreviewed hands that the W1-A checkpoint wrongly called CLEARED now read
  **UNASSESSED** (honest): AUTO_ONLY = UNASSESSED 813 / CLEARED 26 / UNGRADED 5.
- **§1.2 popup/list migration.** The hand-list popup now CONSUMES the canonical `data-final-status`
  (kept on the lazy placeholder's opening tag — identical lazy or static), never independently infers
  status; the verdict/EAI nuance is a secondary field; review state stays separate. The contradiction
  gate gained **C7** (popup-consumes-canonical) and now recognises UNASSESSED across C1/C3/C5.
- Validation: 0 status contradictions over 844 hands (AUTO_ONLY + analyst demo); `popup_consumes_canonical: true`.

## 2. Commentary Capsule — **Aligned/Verified**

The capsule (`gem_commentary_capsule.py`), the 3-register classifier, the compact render, street
locality, and the 6-destination **zero-drop ledger** (`gem_commentary_migration.py`) shipped in
v8.17.0. v8.18.0 adds the canonical contract vocabulary **FACTUAL | COACHING | INSUFFICIENT_EVIDENCE**
(`canonical_register`, applied at build time; `no_clear_lesson → INSUFFICIENT_EVIDENCE`, an explicit
"what cannot be concluded", never a silent "Unclear"). Existing lints (L1–L13) + the zero-drop ledger
remain the guard. **Partial:** an explicit compact takeaway-extractor and a regenerated zero-drop ledger
artifact over the live report are staged.

## 3. Villain Teaching — **Aligned/Verified**

The seven-part teaching contract (`gem_villain_teaching.py:lesson_7part`) shipped in v8.17.0 and renders
in the live report (what villain did / why a cue / read / confidence / safe exploit / future exploit /
guardrail), with the chronology + identity corrections from v8.13–8.14. Verified present. **Partial:**
the explicit `stable_villain_key` field, an observation-vs-inference split, and a per-object chronology
stamp are staged enhancements (the guards already operate at the detector level).

## 4. PokerHandDisplay — **Complete**

New canonical typed component `gem_report_draft/_cards.py`: `CardVM` (rank/suit/glyph/colour/unknown/
accessible-label), `HandVM`, `HandDisplaySize` (COMPACT/STANDARD/PROMINENT), `render_poker_hand`, the
`poker-hand` DOM marker, typed `to_dict` serialization. ONE owner of card markup: `_html._card_html` /
`_cards_html` now DELEGATE here (every existing surface migrated at once), the prominent hand-detail
header renders the wrapped PROMINENT component (841 in the live report, with `role="img"` +
`aria-label`), unknown/partial cards render a typed `card-x` pill, desktop + mobile use the SAME
component (responsive CSS, no separate mobile logic). 6 bypass/regression tests (T-PHD-01..06) incl. a
guard that the legacy helpers delegate and no second card-markup path exists. **Partial:** the Tournament
exit-hand and the review-queue JS still link by id; migrating those to the wrapped component is staged.

## 5. Tournament Results — **Partial (targeted refinements)**

The v8.15 Tournament Tables v3 surfaces render. v8.18.0 delivers the **Top% always-one-decimal**
contract (`gem_tournament_model._top_pct_label` → "Top 5.0%" / "Top 61.0%", so a totals row can average
it). **Staged:** the canonical typed event-type model (event/bullet/multi-entry/multi-day/HH-only/
summary/satellite/Day-2), single-nav consolidation, exit-hand-as-final-column with PokerHandDisplay,
Details/Drivers/SRC column removal, the −100% ROI mute, the totals/avg-Top% row, and the sticky filters.

## 6. DataTable foundation — **Partial (verified-existing)**

The Results sort/filter/sticky/totals machinery exists inline (`sections_tournaments.py` + the `_ttSort`
JS). A typed-column `DataTable` foundation that replaces it is **staged** — not extracted in this
execution (it pairs with the Tournament Results event-model work to avoid two live table owners).

## 7. Lean Claude Chat runtime package — **Complete**

`_build_lean_runtime.py` builds `gem_lean_runtime.py`: the production report-generation closure only
(runtime `gem_*.py` + `gem_report_draft/` incl. the v8.18.0 owners + parser config + a compact STEP0 +
concise release notes), EXCLUDING the Stage-F/Stage-P `acceptance/` apparatus, the `_qa_*` harnesses,
the full unit suite (`_test_scratch.py`), and design specs.
- full release bundle `gem_src_bundle.py` : **2,404,930 bytes (151 files)**
- lean runtime `gem_lean_runtime.py` : **1,802,538 bytes (83 files)**
- reduction : **602,582 bytes (25.1%)**
- verified: the lean package extracts + `import gem_report_draft, gem_analyzer, gem_report_draft._cards,
  gem_final_status` succeeds (runtime closure intact); `acceptance/`, `_qa_*`, `_test_scratch` absent.

## 8. Validation (integrated)

| Check | Result |
|---|---|
| Unit suite | **1784 / 1784** (W1-A + UNASSESSED + 6 PHD + commentary + Top%) |
| `verify_release` | **59/59 files, 618 canaries, 12 anti** (+`_cards.py`; 8 hashes re-pinned) |
| Clean-extract | **151-file bundle** → clean-room verify 59/59 + suite PASS |
| Parity A–R (REV17 frozen) | **PASS** (P 3177/0, Q 0, R 0 — action-sizing untouched) |
| Holdout | **0 violations** |
| Frozen Stage-F seeds | **45/45** |
| Status-contradiction gate | **0** over 844 hands (AUTO_ONLY + analyst demo); popup consumes canonical |
| Browser smoke (DOM) | desktop + mobile 375: 0 document overflow; UNASSESSED pill distinct; 836–841 PokerHandDisplay components w/ aria-label; pills + cards readable |

(Screenshots time out on the 2.8 MB / 844-lazy-hand report — a renderer limit, not a report defect;
the DOM measurements above are the deterministic visual evidence.)

## 9. Distribution + sizes

- AUTO_ONLY: UNASSESSED 813 · CLEARED 26 · UNGRADED 5 (secondary JUSTIFIED 26).
- Analyst demo: UNASSESSED 808 · CLEARED 28 · MISTAKE 2 · CONDITIONAL 1 · UNGRADED 5.
- Generated HTML (AUTO_ONLY): ~2.79 MB (W1-A +5.96% over REV17; the UNASSESSED/PHD additions are flat).
- Bundle 151 files; lean 83 files (−25.1%).

## 10. Known non-blocking debt + staged work

Tournament Results event-model / single-nav / exit-hand-PHD / column removal / ROI-mute / totals /
filters; DataTable typed-column extraction; Commentary takeaway-extractor + live zero-drop artifact;
Villain stable-key / observation-inference split; III.3 "Cleared · Correct" minor nuance redundancy;
status legend block. None blocks the canonical truths (status, action sizing, card markup, tournament
result values are each single-owner and non-contradictory).

No Wave 3. Awaits ONE integrated GPT technical review + ONE Ron product review.
