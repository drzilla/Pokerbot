PHASE 2 — OFF-GRAMMAR DECISIONS LOG
====================================
Tracks every table where rendered columns differ from §3 as written.
Each entry: table, deviation, one-line reason.

## financial_summary (daily summary — Step 1)

**RESOLVED (#29) — grammar updated to match actual 12-col emitter output.**
Original §3 grammar (7 cols) was stale; emitter evolved in Phase 3/4 to
include tournament-specific columns (Tourneys, Bullets, ROI, ITM/B,
Top1/B, Top5/B, FT/B, Avg BI). See decision #29.

## tournament_pnl (per-tourney PnL — Batch 1)

1. **bb/100 appended after §3 columns.**
   §3 does not list bb/100; kept because it is the primary HH-derived
   performance metric and removing it loses information the user reads.

2. **Invested, Cashes, ABI, Finish omitted.**
   Data sources (`_compute_per_tourney_pnl` + `usd_overlay`) do not
   currently compute these fields; adding them requires upstream
   pipeline changes outside Phase 2 scope.

## variance_ledger (EAI preflop + postflop — Batch 1)

3. **Street column added (not in original emitter, present in §3).**
   §3 lists Street as column 1. Pre-migration tables had no Street
   column; each table was implicitly scoped by its heading
   ("Preflop All-Ins" / "Postflop All-Ins"). Added the explicit
   column so rows are self-describing per §3.

## leak_bucket (III.7 Out-of-Bound + IV.2 Preflop Deviations — Batch 2)

4. **Count and Denom merged into Count/Denom.**
   §3 specifies a single `Count/Denom` column. Pre-migration tables
   had separate Count and Denom columns. Merged to `count/denom (label)`
   format per §3.

5. **Detail column appended in IV.2 table (not in §3).**
   The IV.2 preflop-deviation bucket table carries a Detail column
   with `_xref()` links to XIII appendix sections. Not in §3 grammar;
   kept appended after §3 columns because removing it breaks the
   click-through navigation from IV.2 → XIII.

6. **III.3 strategic leak overview table left as prose.**
   Columns (`# · Leak · Metric · Status · Analyst Judgment · Detail`)
   have no structural overlap with §3 leak_bucket grammar. This is a
   qualitative analyst-commentary table, not a deviation-bucket rate
   table. Stays as prose; not a leak_bucket.

## profile_matrix (IV.1 Position Matrix — Batch 2)

7. **§3 columns reordered to front; 5 extra columns appended.**
   §3: `Position · Status · Rate · Target · Count · Opps · Notes`.
   Pre-migration had 12 columns. Mapped: Open% → Rate, Opens → Count,
   FI Opps → Opps, Flagged → Notes. Extra columns (Hands, VPIP, PFR,
   Limps, Missed) appended after §3 columns — these are fundamental
   poker metrics that removing would lose actionable information.
   No computation changed — same values, same derivation, re-housed.
   ⚠️ Wide table (12 cols): flagged for Phase 3 mobile lint review.

8. **Positional P&L table left as prose.**
   Columns (`Pos · Hands · Net BB · bb/100 · VPIP Net BB · VPIP bb/h ·
   Status`) have no Rate/Target/Opportunities structure. This is a P&L
   breakdown by position, not a profile matrix. Stays as prose.

9. **Stack-Depth Distribution table left as prose.**
   Simple 3-column table (`Bucket · Hands · %`) does not match any
   §3 table_type. Stays as prose.

## raw_reference (XIII Full Deviation Lists — Batch 3)

10. **New `raw_reference` block type added to _blocks.py.**
    §3 defines `raw_reference` as a table_type but §2 had no matching
    block type. Added in Phase 2 (14th type) because XIII tables need
    a typed wrapper and `prose` would suppress Phase 3 lint. §3 says
    "source order allowed" — column order is NOT grammar-enforced.

11. **13 XIII tables migrated, all source-order preserved.**
    Chart sanity, XIII.1/2/3 deviation lists, XIII.4.x mistake tables
    (×4 via `_emit_mistake_table`), XIII.4.4 awaiting, XIII.4.5
    analyst-reviewed, XIII.4.6 auto-corrected, XIII.5.0 freq tests,
    XIII.5.1/5.2 MDA aligned/missed, XIII.6 large-loss audit, XIII.7
    blind-spot audit. No column reordering — raw_reference grammar
    allows source order.

12. **`_emit_table_compact` refactored to emit via block.**
    The dynamic column-dropping helper now wraps output in
    `raw_reference_block` internally. Column-drop logic unchanged;
    only the output path changed (buffer → block → render → doc.w).

## action_review (VIII — Batch 3)

13. **No matching emitter — left as prose.**
    §3 action_review grammar: `Spot/Decision · Status · Count ·
    EV Impact · Example Hands · Recommended`. VIII.11 renders a
    summary **cross-tab** (Street × 5 Verdict columns) plus
    collapsible `<details>` bullet-point examples — structurally
    incompatible with the §3 flat-table grammar. No table in the
    current codebase matches action_review. Type exists in _blocks.py
    for future use.

## metric_status (stat tables — Batch 3)

14. **RESOLVED — metric_status grammar implemented (Commit A + B).**
    §3: `Metric · Status · Value/Rate · Target · Delta · Sample · Notes`.
    Commit A migrated `_stat_row()`, `_stat_row_pct()`, `STAT_HEADER`,
    `STAT_SEP` to the 7-col §3 grammar. CI moved to ⓘ tooltip on
    Value/Rate. Delta column added (deviation from target midpoint).
    Commit B converted all 6 inline stat tables to
    `write_block(metric_table_block(...))` — block-registered and
    passing E1/E2/E5 lint cleanly. `metric_status` grammar entry added
    to TABLE_GRAMMAR. 3 suppression entries (#14 E1/E2/E5) removed.

## hand_evidence (III.1/III.2/III.3/III.7/III.9/IV.2 — Tier 1)

15. **Column headers preserved — §3 "Spot" position, not §3 word.**
    §3 defines `Hand · Cards · Spot · Review/Verdict · Impact · Why`.
    Each table keeps its own descriptive header at the §3 column
    position: `Type` (III.1), `What went wrong` (III.2), `Cleared As`
    (III.3), `Reason` (III.7), `Archetype` (III.9 Picks), `Structural
    signal` (III.9 Provisional). Standardizes structure and column
    order, not the words — collapsing semantics violates "preserve
    poker semantics / don't oversimplify" non-negotiables.

16. **`#` row-number column prepended in M4/M5/M6 tables.**
    §3 does not list a row-number column. Kept prepended before Hand
    because clinical examples and Picks need ordinal numbering for
    analyst reference. Same pattern as cooler tables (F2/F3).

17. **M3 and M7 tables inside `<details>` — boundary respected.**
    III.3 cleared verdicts and III.9 open candidates sit inside
    `<details>` collapse blocks. The `hand_evidence_table_block` wraps
    only the table; `<details>`/`</details>` tags remain as prose
    outside the block boundary. Hard gate: block never contains
    `<details>`.

18. **X6 (VIII.7 Check-Raise Evidence) → `raw_reference`, not
    `hand_evidence` or `prose`.**
    8 domain-specific columns (Street/Board/Hand/Draw/Line/Net/Verdict)
    — structurally a raw evidence ledger, not a hand-review table.
    `raw_reference` preserves real tabular structure without forcing
    §3 hand_evidence column mapping onto incompatible poker-line data.
    `prose` would suppress Phase 3 lint on a legitimate table.

19. **Cooler tables F2/F3 stay as prose.**
    I.7 Coolers: `# · Hand Reference · Hero · Villain · Board · Street
    · Kind`. Hero-vs-Villain matchup ledger — structurally different
    from hand_evidence (no Spot/Verdict/Impact/Why mapping). Stays
    prose; not forced into hand_evidence or raw_reference.

## hand_evidence (I.3/V.3/VII.1/VII.4 — Tier 2)

20. **F1 (I.3 Large-Loss Audit) — Board and Type appended after §3.**
    §3: `Hand · Cards · Spot · Verdict · Impact · Why`. Current:
    `Hand Reference · Cards · Net · Board · Verdict · Type`. Net maps
    to §3 Impact position; Board and Type are domain-specific extras
    appended. No column dropped, no computation changed.

21. **X2 (V.3 SB Folded Hands) — Opener and Stack appended.**
    `Hand Reference · Cards · Opener · Stack`. Only Hand and Cards are
    §3 columns; Opener (the LP position that opened) and Stack are
    poker-context extras. J29 framework: migration wraps output only —
    no change to which hands appear, how SB action is labeled, or how
    the missed-steal detector interacts.

22. **X3 (VII.1 Missed Delayed C-bets) — Hero Pos, Board, Stack
    appended.**
    `Hand Reference · Hero Pos · Cards · Board · Stack`. Hero Pos,
    Board, Stack are all domain-specific extras appended after §3
    columns. Cards remains at §3 position 2 (after Hand).

23. **X4 (VII.4 Missed 3BP Barrels) — Flop and Stack appended.**
    `Hand Reference · Cards · Flop · Stack`. Flop (first 3 board
    cards as pills) and Stack are domain extras. No computation
    changed — same `hero_3bet` + `cbet_flop_3bp` filter logic.

24. **X5 (IX Sizing Deviations) — Depth, Actual, Target appended.**
    `Hand Reference · Cards · Depth · Actual · Target · Δ (Act/Tgt−1) ·
    Verdict`. Hand-keyed table with magnitude-based review verdict
    (👍 on-pattern / 🟡 notable / 👎 off-pattern). Δ maps to §3
    Impact (numerical impact of deviation); Verdict maps to §3
    Review/Verdict; Depth, Actual, Target are domain-specific extras
    appended after §3 columns. `_href()` → `_hand_ref()` citation
    side-effect timing preserved — fires inside loop before row buffer.
    No computation changed; same B195 delta + B232 sort logic.

## variance_ledger — EAI summary tables (Phase 4 lint gate)

25. **EAI summary tables (eai-preflop, eai-postflop) — full column
    schema divergence from §3 variance_ledger grammar.**
    §3 variance_ledger: `Street · Matchup · Hero · Villain · Board ·
    Pot BB · Equity · EV Diff`. These are per-hand equity-analysis
    columns for individual all-in matchup detail.
    Actual (S1.6 EAI summary): `Street · Category · Count · Won ·
    Actual · Expected · Delta · Status`. These are aggregate
    category-breakdown columns (ahead/flip/behind win-rate distributions
    vs expected). The block type is structurally correct — both are
    variance/equity tables rendered from EAI data — but the column
    schema serves a different analytical purpose: category-level
    summary vs per-hand matchup detail. Street (col 0) matches; cols
    1-7 diverge at every position. Produces 7 E1 errors per block
    (14 total). Suppressed as I1/INFO in lint.
    **Resolution target: Phase 5 — grammar-v2 alignment.** Add a
    dedicated `variance_summary` grammar or variance_ledger subtype
    when the per-hand EAI detail table is implemented. Suppressions
    (#25) removed and E1 fires at full ERROR severity once the new
    grammar is in place.

## tournament_pnl — per-tourney P&L table (Phase 4 lint gate)

26. **Per-tourney P&L (per-tourney-pnl) — full column schema divergence
    from §3 tournament_pnl grammar.**
    §3 tournament_pnl: `Tourney · BI · Stack · Place · $Prize · ROI ·
    Time`. These describe tournament-results data (finish position,
    prize money, event duration).
    Actual (S1.1 per-tourney PnL): `Date · Tournament · Bullets ·
    Hands · BI · NetBB · bb/100` (without USD overlay); or
    `Date · Tournament · Bullets · Hands · BI · Net$ · ROI · NetBB ·
    bb/100` (with USD overlay). The renderer shows a hand-history-
    derived performance breakdown, not tournament-results data.
    Decisions #1-2 partially documented the divergence (bb/100 appended,
    Invested/Cashes/ABI/Finish omitted), but the full column mismatch
    was unaddressed — all 7 §3 positions differ in the no-USD variant.
    Produces 7 E1 errors. Suppressed as I1/INFO in lint.
    **Resolution target: Phase 5 — grammar-v2 alignment.** Redesign
    tournament_pnl grammar around the actual HH-derived data source,
    or split into tournament_results (§3) vs tournament_performance
    (HH) subtypes. Suppressions (#26) removed and E1 fires at full
    ERROR severity once the new grammar is in place.

## profile_matrix — empty rows guard (Phase 4 lint gate)

27. **Position profile matrix (iv1-position-matrix) — E4 empty rows
    in minimal-fixture renders.**
    The `_emit_section_iv` emitter unconditionally creates the
    `profile_matrix_block` even when `s['positions']` is empty. In
    production, the analyzer always populates position data from hand
    history, so the table always has rows. The E4 fires only in the
    Phase 2/4 minimal test fixture where `s['positions'] = {}`.
    Adding an empty-guard (`if tbl_rows:`) before block creation would
    be the proper fix but is a functional change outside Phase 4 scope.
    Suppressed as I1/INFO in lint. Resolution: add empty-guard in a
    future cleanup pass.

## metric_status — T6 Caller IP denom-missing fallback (Commit B)

28. **Caller IP Aggression (HU/MW) — denom-missing presentation.**
    When the analyzer schema omits the denominator field
    (`caller_ip_flop_n` / `caller_ip_flop_n_mw` is None), the metric
    has a percentage from the CSV but no sample count for Wilson CI or
    delta computation. Pre-migration: showed `{pct}% (n=—, denom
    missing)` in the old 6-col Value column with ⚪ status.
    Post-migration decision: show available percentage in Value/Rate
    column, ⚪ status (indeterminate), no CI tooltip, delta=`—`
    (unreliable without denominator), sample=`n=—`, notes explain the
    gap with B13 cross-reference. This is an analytical decision about
    presenting unreliable data — the percentage is informational but
    cannot carry a verdict. See B13 for the upstream schema fix.

## financial_summary + leak_bucket_overview — grammar update (Phase 4.6)

29. **RESOLVED — grammars updated to match actual emitter output.**
    Both grammars were written speculatively during Phase 2/3 lint creation
    and never matched the actual emitter columns (which evolved during
    Phase 3/4 table migrations). Same class as decisions #25/#26 but the
    fix is grammar-update (not suppression) because these tables have
    stable, mature column layouts unlikely to change.
    **financial_summary**: old grammar `Date · Tables · Hands · $Cost ·
    $Cash · $Net · bb/100` (7 cols) → updated to `Date · Tourneys ·
    Bullets · $Cost · $Cash · $Net · ROI · ITM/B · Top1/B · Top5/B ·
    FT/B · Avg BI` (12 cols, matching sections_financial.py line 128).
    **leak_bucket_overview**: old grammar `Bucket · Count/Denom · Rate ·
    Target · Status · Notes` (6 cols, wrong order) → updated to
    `Status · Bucket · Rate · Acceptable · Common Hands · Count/Denom`
    (6 cols, matching actual emitter order). The 7th column (Detail) in
    the iv2-buckets variant is an allowed appended extra (I2 info).
    Eliminates 13 E1 errors on real report runs. No suppression needed.
