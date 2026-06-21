# Wave 1 + Wave 2 — Combined Criteria Freeze (v8.18.0 train)

One bounded, implementation-oriented criteria freeze for the combined product train, per the
accelerated same-day plan. The governing execution model is the accelerated plan; where an older
roadmap conflicts, the accelerated plan wins. This freeze is practical, not a formal-proof exercise.

## 0. Frozen baseline

```
stable release : main @ 378846b  (merge of v8.17.0 + the accepted REV17 7b6827e)
release tag    : v8.17.1  (annotated, on 378846b; HELD locally — Ron pushes)
train baseline : 378846b   (Wave-1/2 branches start here)
```

The accepted REV17 baseline proves (regression-frozen — must not regress):
full-history canonical action sizing; exact per-row hand/player/action identity; zero raw-sizing
fallback; the tracked single-owner action-sizing ownership contract; ordinary ante/SB/BB replay
(the 9 raw-source goldens); 3,177 reconciled real-report sized actions.

## 1. Regression baseline (frozen — re-run unchanged)

| Check | Frozen expectation |
|---|---|
| Unit suite | `_test_scratch.py` ALL PASS (REV17: 1763) |
| `verify_release` | 56/56 files + 612 canaries + 12 anti-canaries, clean |
| Clean-extract | bundle re-extracts → clean-room verify + suite PASS; `acceptance/production_calculation_ownership.json` ships |
| Parity gates | A–R all PASS (P row-bound 3177/0, Q fallback 0, R dead-blind 0; A–O unchanged) |
| Holdout | 179 / 0 |
| Raw-source goldens | 9/9 match (ante/SB/BB sizing unchanged) |
| Frozen Stage-F seeds | `acceptance/_stage_f_selfcheck.py` 45/45 (gates read-only) |
| June-16 preservation | 844 hands / 12 tournaments / 16 bullets, hydration 844/844, Range Lens 359/359, 77/763/4 |
| Target hands (visible) | 83975040 18.1/18.1 · 84295325 12.2 ×3 · 84601619 Call 40.6 / JAM all-in to 73.6 |
| No-recalc rule | no report feature independently recalculates action sizing, final status, tournament truth, or structured hand markup |

## 2. This-execution scope (confirmed with Ron)

The full 6-feature train is a multi-session delivery. This execution delivers, on top of the frozen
REV17 release: **this criteria freeze + recon + shared-file ownership matrix**, then the foundational
**W1-A Canonical Final Decision Status** complete + validated. The remaining lanes (W2-A Commentary
Capsule, W2-B Villain Teaching, H4 PokerHandDisplay, W1-B Tournament Results, R2 DataTable, runtime
package) are staged for subsequent executions against this freeze.

## 3. W1-A — Canonical Final Decision Status (this execution's product outcome)

### 3.1 The typed owner

One canonical owner (`gem_final_status.py`) computes, per hand, exactly one:

```
FinalDecisionStatus = MISTAKE | CONDITIONAL | CLEARED | UNASSESSED | UNGRADED
```

> **v8.18.0 W1-A correction §1.1:** the model gained **UNASSESSED ("Not reviewed")**. A gradeable hand
> with no positive or negative adjudication (a neutral canonical `Review`, a neutral queue inclusion, or
> simply not individually reviewed) is **UNASSESSED**, NOT `CLEARED` — "nothing confirmed wrong" is not
> "explicitly judged correct," and a secondary reason never manufactures a positive grade. `CLEARED` now
> requires an EXPLICIT positive adjudication (cleared/justified/standard/correct, or a cooler/flip/suckout
> with a correct-action verdict). Precedence: MISTAKE > CONDITIONAL > CLEARED > UNASSESSED > UNGRADED.

with secondary reasons kept SEPARATE (a status is never a reason):

```
SecondaryReason = SUCKOUT | FLIP | COOLER | JUSTIFIED | READ_DEPENDENT   (zero or more)
```

### 3.2 Frozen status contract

| Status | Meaning | Derivation rule |
|---|---|---|
| `MISTAKE` | Hero made a graded action error | the canonical reviewed decision is a genuine action mistake (a wrong action at a price-applicable / gradeable decision) — NEVER from the result alone |
| `CLEARED` | Hero's graded action was fine | a gradeable decision whose canonical verdict is correct/standard (a suckout/flip/cooler loss is CLEARED with a secondary reason) |
| `CONDITIONAL` | correct only under a read / borderline | a gradeable decision whose canonical verdict is read-dependent / borderline / mixed |
| `UNGRADED` | no gradeable action decision | no_hero_decision (walk), forced short all-in below the blind, or a result-only hand where Hero never made a gradeable decision |

### 3.2a Hand-level status precedence (frozen)

A hand may contain several Hero decisions. Derive exactly ONE final status by precedence; secondary
reasons NEVER override it (`gem_final_status.combine_statuses`):

```
1. any genuine graded action mistake        -> MISTAKE
2. else any read-dependent / borderline / mixed graded decision -> CONDITIONAL
3. else at least one graded-correct decision -> CLEARED
4. else no gradeable Hero decision           -> UNGRADED
```

```
correct action + later cooler   -> CLEARED + COOLER
borderline decision + suckout   -> CONDITIONAL + SUCKOUT
one correct + one genuine mistake -> MISTAKE
walk / forced sub-blind all-in / result-only -> UNGRADED
```

The verdict taxonomy is carried coded ('III.2 Mistake') AND humanized ('Mistake'); the coded form is
authoritative (`gem_final_status._classify_verdict`): III.1/III.2 -> MISTAKE; III.4/III.8/III.9 ->
CONDITIONAL; I.7/III.0/III.3/III.5 -> CLEARED. (The bare-word marker alone is unreliable for coded
verdicts -- the demo report exposed this and the classifier fixes it.)

### 3.2b Full current-surface inventory (from recon)

| Surface | Current source | New canonical source | Migration action | State |
|---|---|---|---|---|
| Hand-detail card root `<article>` | `data-canonical-verdict` (cv.verdict) | `+ data-final-status` (cv.final_status) | stamp added, BOTH card paths (sections_xiv 2454 + 4120) | migrated |
| Hand-detail title pill (primary) | `short_verdict_pill` (BLANK for unflagged) | `.final-status-pill` (gem_final_status) | added as primary; never blank | migrated |
| Lazy hand body | = the article HTML (PB_PAYLOADS) | the SAME article -> same status | structural (one HTML, no separate path) | migrated |
| Static shell card | = the article HTML | same | structural | migrated |
| Sticky top bar | clones `.verdict-pill` | clones `.final-status-pill` (verdict-pill fallback) | JS repointed (_html.py topbar) | migrated |
| Verdict-nuance pill | `short_verdict_pill` | retained as nuance; dropped when it merely repeats status/reason | de-duplicated (verdict_pill_redundant) | preserved (consistent) |
| Summary counters (Mistakes/100, Punts/100) | `canonical_mistakes_count` (same cv) | consistent with MISTAKE status (one cv) | verified by gate | preserved |
| Hand-list popup row | reads `.verdict-pill` for nuance | unchanged (nuance), not a status contradiction | preserved | preserved |
| Review queue `.status-pill` | analyst REVIEW state (agree/bug/debate/drill) | unchanged -- review state is a SEPARATE concept | preserved (separate) | preserved |
| Reviewed-hand list | review state | unchanged | preserved | preserved |
| Analyst chips (Agree/Debate/Report bug) | review controls | unchanged -- never redefine system status | preserved (separate) | preserved |
| Export / Markdown mirror | render output | carries the pill text (Cleared/Mistake/...) | follows the renderer | migrated |
| Navigation labels / anchors | section registry | unchanged | preserved | preserved |

Review state stays a distinct concept everywhere (the spec's requirement #5): the canonical SYSTEM
status (`.final-status-pill` / `data-final-status`) never reads analyst Agree/Debate/Bug, and the
review surfaces (`.status-pill`, the chips) never set the system status.

### 3.3 Required outcomes (frozen acceptance)

1. one canonical status drives every touched surface;
2. **no hand says MISTAKE when no action mistake exists** (a lost suckout/cooler is CLEARED, not MISTAKE);
3. cleared hands retain a visible top-level status (CLEARED is shown, not blank);
4. **result-only hands do not become strategically graded** (they are UNGRADED);
5. review state (analyst Agree/Debate/etc.) does not independently redefine the SYSTEM status;
6. lazy and non-lazy representations agree;
7. summary / table / list / header / commentary labels do not contradict each other for the same hand.

### 3.4 Status-contradiction gate (frozen)

A gate parses the regenerated report and, for every hand, extracts every visible status/grade label
across the touched surfaces and asserts they are mutually consistent with the one canonical
`FinalDecisionStatus`:
- a `CLEARED`/`UNGRADED` hand is labelled "Mistake" on **no** surface;
- a `MISTAKE` hand is consistently a mistake wherever it is labelled;
- an `UNGRADED`/result-only hand carries no strategic grade;
- the lazy body status and the static-shell status agree.
0 contradictions required on June-16.

## 4. Preservation constraints (frozen, all lanes)

Preserve the REV17 action-sizing + ownership truth, the 9 goldens, zero raw fallback, full hand +
player identity, existing navigation + review controls, Range Lens data + Hero emphasis (100% where
Range Lens renders), existing commentary unless explicitly transformed through a zero-drop ledger,
villain chronology + identity, ONE static portable HTML report, desktop + mobile access to the same
hand data. No feature independently recalculates sizing / status / tournament truth / hand markup.

## 5. Lane + shared-file ownership

(Shared-file matrix filled from recon — see `SHARED_FILE_OWNERSHIP_MATRIX.md`.) For this execution
W1-A owns the new `gem_final_status.py` + the status-label surfaces it touches; it consumes the
canonical decision model read-only and does not change action sizing, the REV17 binding, or the
ownership contract.

## 6. Evidence + measurement requirements (frozen)

The integrated evidence package carries: implementation diff; acceptance manifest; test/gate outputs
(suite, verify_release, parity A–R, holdout, frozen seeds); product inventories (status distribution
+ the status-contradiction inventory); real regenerated report; before/after runtime + source-bundle
+ generated-HTML size; clean-extract proof; known non-blocking debt. Self-verify the shipped ZIP
bytes from a fresh extraction.

## 7. Bounded technical-quality budget

While touching the status surfaces: one canonical owner of the final-status fact; delete replaced
ad-hoc status/verdict label paths where safe; no adapter that merely preserves duplication; record
before/after sizes. No repository-wide refactor. The four accepted debts (holdout frozen-gate
counters; the 0.12BB short-all-in 0.1BB attribute; `_qa_report_deep.py` regex; REV17 +4.8% HTML) are
fixed only if their area is naturally touched; none blocks.
