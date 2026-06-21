# v8.18.0 Final Product Correction — Completion Report

Continues `d0928ca` on `feature/v8180-wave1-wave2-integration`. One bounded correction packet covering
the three material product gaps the prior evidence exposed. Accepted work (REV17, the 5-state status,
popup canonical status, PokerHandDisplay core, typed DataTable, the Results event table, lean builder,
chronology/no-hindsight protections) was preserved, not redesigned. NOT merged / tagged / pushed.

## 1. Duplicate Results product surfaces — REMOVED

The report rendered both the new Results DataTable **and** the old Tournament Performance event table
(24 rows = 12 + 12; 12 unexpected duplicates), the latter carrying Drivers / Reviewed / an id-only
exit cell. Fixed:

- the separate `_emit_performance` event table is **removed**; its BB/100 + cEV/100 are now **columns
  of the one canonical Results DataTable** (no data loss);
- the Drivers-in-view rollup was already retired; the intro prose no longer names a second table;
- the colliding `Result` nav (section S1, "variance vs skill") is renamed **Variance** across all three
  nav-label sources (sidebar rail + workflow topbar + section map), so the nav carries exactly one
  Results-family item: **Tournament Results**.

The surviving surface is the typed DataTable: exit hand as the final PokerHandDisplay cell + standard
hand link, Top% one decimal, muted −100% ROI, signed metrics, totals + average Top%, sticky filters,
HH-only unresolved return, satellite ticket marker.

**Source-to-DOM reconciliation (real report):** Results navigation entries **1**; Results event tables
**1**; source events **12**; rendered canonical event rows **12**; missing **0**; unexpected duplicate
rows **0**. (`results_source_to_dom_reconciliation.json`)

## 2. Visible Commentary Capsule migration — COMPLETE

- The visible register badge is now the canonical contract vocabulary — **Fact / Coach / Insufficient
  evidence** (`_REGISTER_BADGE`); the generic **"Unclear" is gone (0 in the real report)**. An
  INSUFFICIENT_EVIDENCE capsule states the actual limitation in its Caveat (e.g. "evidence is thin here
  — check the price and the opponent range before grading").
- **Full-population live zero-drop ledger** (`run_migration_audit` over the regenerated report):
  **2721 source items, BALANCES = true, 0 unaccounted, 0 lint failures**, and the previous blanket
  "left untouched out of scope" bucket is now resolved to **NAMED visible surfaces with reasons** —
  41 → "hand-detail opponent-context section", 2478 → "villain passive-read evidence (villain-context
  surface)", 202 → visible capsule; **0 items without a named surface**. (`commentary_zero_drop_ledger.json`)

## 3. Villain Teaching full-population coverage — COMPLETE

Coverage now runs over **all 222 built teaching objects** (12 exploit + 210 atom). The 133 "incomplete
eligible" the prior artifact reported are correctly **typed INELIGIBLE** (a thin atom read with no
actionable cue is not an incomplete lesson). For an eligible lesson the current exploit may be
**NOT_APPLICABLE with a reason** (the action completed before a safe adjustment) and is still complete;
the future adjustment must be present. Duplicates are deduped by decision id.

Real-report inventory (`villain_teaching_coverage.json`):

```
all teaching objects        : 222
eligible lessons            : 9   (all 9 complete seven-part)
ineligible (typed)          : 213  — insufficient_evidence 76, no_actionable_cue 133,
                                     no_safe_exploit 0, duplicate_of_another_decision 4, result_only 0
incomplete eligible lessons : 0
duplicate decision lessons remaining : 0   (4 deduped)
chronology violations       : 0
identity collisions         : 0
result-oriented violations  : 0
```

The structured contract carries stable_villain_key (`tournament_id|player_hash`), hand decision id,
observation vs inference, confidence, current exploit (or NOT_APPLICABLE+reason), future exploit,
guardrail, and supporting evidence ids.

## 4. Validation (all green)

| Check | Result |
|---|---|
| Unit suite | **1793 / 1793** (+T-CAP18-03, refined T-VT18-02, updated TT tests) |
| `verify_release` | **60/60 files, 618 canaries, 12 anti** (canary repinned to `_RES_COLS[-1]`) |
| Clean-extract | **152-file bundle** → clean-room verify 60/60 + suite PASS |
| Parity A–R / holdout / Stage-F seeds | **PASS / 0 / 45-45** (REV17 untouched) |
| Status-contradiction gate | **0** over 844 hands (AUTO_ONLY + analyst demo) |
| Results source→row | 1 nav, 1 table, 12 = 12, 0 missing, 0 dup |
| Commentary full-population zero-drop | 2721 items, 0 unaccounted, 0 visible Unclear, 0 without named surface |
| Villain full-population | 222 objects; 0 incomplete-eligible / 0 dup / 0 chronology / 0 identity / 0 result-oriented |
| Browser (DOM) | one `#tt-results` (12 rows, BB/100+cEV+exit-last), one Results nav, S1 → "Variance" |
| Lean runtime | 82 files / −30.4% (capacity ~66.5–71.8%) |

Screenshots remain environment-blocked (the preview screenshot tool times out); evidence is the
deterministic DOM measurements + the cropped `visual_artifact_crop_results.html`.

## 5. Known non-blocking debt

III.3 "Cleared · Correct" nuance redundancy; a status legend block; the lean quick-reference is
reclassified optional (not shrunk in place). None contradicts a canonical truth.

No Wave 3. Awaits one final GPT technical acceptance + one Ron product review.
