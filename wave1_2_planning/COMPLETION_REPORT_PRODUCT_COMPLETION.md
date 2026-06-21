# v8.18.0 Product-Completion Release Candidate — Completion Report

Branch `feature/v8180-wave1-wave2-integration` (continues `3a967b2`, off released `main @ 378846b`,
tag `v8.17.1`). The remaining product scope from the prior RC is now **complete and verified in the
regenerated report** — not marked "staged". NOT merged / tagged / pushed.

## 1. Commentary Capsule — **Complete**

- Registers **FACTUAL / COACHING / INSUFFICIENT_EVIDENCE** (`gem_commentary_capsule.canonical_register`,
  applied at build time; INSUFFICIENT_EVIDENCE is explicit, never a silent "Unclear"). Compact capsule
  preserved (coaching takeaway → factual evidence → deeper on demand) with street locality, Range Lens,
  Hero-combo emphasis, bounty/ICM/villain/analyst evidence.
- **Live zero-drop proof** from the REAL report payload (`gem_commentary_migration.run_migration_audit`):
  **2721 source items inventoried, BALANCES = True, 0 unaccounted (0 silent drops + 0 without
  destination), 0 lint failures**. Artifact: `commentary_zero_drop_ledger.json`.

## 2. Villain Teaching — **Complete**

- Explicit data contract (`gem_villain_teaching.teaching_contract`): stable_villain_key
  (`tournament_id|player_hash`), hand decision id (sequence position), **observation separated from
  inference**, confidence, current/future exploit, guardrail, supporting evidence ids; alias is
  presentation only.
- Real-report coverage (`villain_teaching_coverage`): **9 eligible / 9 complete seven-part / 0
  incomplete / 0 chronology violations / 0 identity collisions / 0 result-oriented violations**.
  No-hindsight chronology preserved; result-as-cue rejected. Artifact: `villain_teaching_coverage.json`.

## 3. Tournament Results — **Complete (redesign)**

One canonical typed Results table (`gem_report_draft._datatable`), browser-verified:
- exactly one Results section; **Details / Drivers / SRC columns removed**; the one-line cross-check
  removed; the redundant Drivers rollup retired.
- **exit hand is the FINAL column, rendered via PokerHandDisplay** (12 exit-hand components, accessible
  labels) + a standard clickable hand link (id kept separate from cards).
- **Top% one decimal**; **−100% ROI muted but retained** (computed colour rgb(102,112,133) @ 0.6);
  signed Net/ROI; **totals row + average Top% (11.6%)**; HH-only return shows *unresolved*; satellite
  return shows a **ticket marker**.
- **sticky compact filters** (entry time / speed / bounty / freezeout / multi-bullet / multi-day /
  satellite / phase) with counts — only the dimensions the data can distinguish.
- Source-to-row reconciliation: 12 source tournament events → 12 rendered rows; **0 source events
  missing, 0 unexpected duplicate rows** (the per-event payload is 1:1 with the rows).

## 4. DataTable foundation — **Complete**

`gem_report_draft/_datatable.py` owns: typed `Column` definitions (kind drives format + sort + align),
the display formatter, the sort accessor (**signed-numeric aware, stable null-last**), filters,
totals/aggregates, sticky header + sticky filter controls, responsive behaviour, accessible labels
(aria-sort / role), and canonical link/hand cells. The shared `initDataTable` JS engine drives
click-to-sort, filter chips, and totals recompute over visible rows. **Tournament Results consumes
it; the legacy `_ttSort` is retired for that table** (it binds to no table now — one engine).
Browser-verified: sort (Net −216/−108/−108 + aria-sort), filter (bounty 12→10), totals recompute.

## 5. PokerHandDisplay — **Complete on the required surfaces**

The typed owner (`_cards.py`) drives all card markup. Migrated surfaces: (1) prominent hand-detail
header (render_poker_hand PROMINENT); (2) hand-list popup row — the JS renderer `fmtCardSpans` now
emits the SAME `poker-hand` component (class + glyph + accessible label + unknown `card-x`) from the
canonical serialized hand string (window.handIndex); (3) Tournament Results exit-hand cell
(`_datatable.hand_cell` → render_poker_hand); the review-queue scrapes the canonical article cards.
**No consumer builds suit spans independently** (T-PHD-06/07 guard); the hand id stays separate from
the card display; desktop + mobile use the same component.

## 6. Lean Claude Chat runtime package — **Complete**

`gem_lean_runtime.py` (built by `_build_lean_runtime.py`): the report-generation closure only —
runtime `gem_*.py` + `gem_report_draft/` (incl. the v8.18.0 owners + `_datatable` + `_cards`) + parser
config + a compact STEP0 + concise release notes. EXCLUDES the Stage-F/Stage-P `acceptance/`
apparatus, the `_qa_*` harnesses, the full unit suite, design specs, the full changelog, and the
quick reference.

| Package | Files | Bytes |
|---|---|---|
| full release bundle `gem_src_bundle.py` | 152 | 2,419,264 |
| **lean `gem_lean_runtime.py`** | **82** | **1,683,901** (−735,363, **−30.4%**) |

**Projected Claude Chat capacity** (current = 97%, complete inventory incl. retained 593 KB session
CSVs): required-upload set → **66.5%**; conservative (keep all optional prose) → **71.8%** — both below
the 75–80% target. Changelog (135 KB) → release notes (~3 KB); quick reference (102 KB) reclassified
optional. Delete: `gem_src_bundle.py`, `GEM_Changelog.txt`. Upload: `gem_lean_runtime.py`,
`GEM_Release_Notes_v8.18.0.txt`. Retain: STEP0 + parser config/reference + session CSVs; optional:
quick reference + guides. Artifact: `chat_capacity_inventory.json`.

## 7. Validation (all green)

| Check | Result |
|---|---|
| Unit suite | **1792 / 1792** (+UNASSESSED, +DataTable T-DT, +PHD-07, +CAP18-02, +VT18) |
| `verify_release` | **60/60 files, 618 canaries, 12 anti** (+`_datatable.py`; canaries updated to the redesign) |
| Clean-extract | **152-file bundle** → clean-room verify 60/60 + suite PASS |
| Parity A–R (REV17 frozen) | **PASS** (action sizing untouched) |
| Holdout / Stage-F seeds | **0 / 45-45** |
| Status-contradiction gate | **0** over 844 hands (AUTO_ONLY + analyst demo); popup consumes canonical |
| Commentary live zero-drop | **0 unaccounted** (2721 items) |
| Villain coverage | 9/9 complete; 0 chronology/identity/result-oriented violations |
| Results source→row | 12 events → 12 rows; 0 missing, 0 dup |
| DataTable (browser) | sort + filter + totals recompute verified |
| PokerHandDisplay | popup + exit-hand canonical components (aria-label) |
| Desktop + mobile (DOM) | 0 document overflow; filters wrap; pills + cards readable |

Screenshots: the preview screenshot tool is unresponsive in this environment (times out even on a
170 KB cropped page) — so the visual evidence is the **deterministic DOM artifacts** above (computed
colours/labels/geometry) **plus the self-contained cropped artifact** `_crop_results.html` (renders
the 5 status pills + the Results DataTable). Not a report defect.

## 8. Distribution

AUTO_ONLY: UNASSESSED 813 · CLEARED 26 · UNGRADED 5. Demo: UNASSESSED 808 · CLEARED 28 · MISTAKE 2 ·
CONDITIONAL 1 · UNGRADED 5. 854 / 849 PokerHandDisplay components.

## 9. Known non-blocking debt

III.3 "Cleared · Correct" nuance redundancy; a status legend block; the lean quick-reference dedup (it
is reclassified optional rather than shrunk in place). None contradicts a canonical truth.

No Wave 3. Awaits one integrated GPT technical acceptance + one Ron product review.
