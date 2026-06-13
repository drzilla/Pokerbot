# GEM Report — Comprehensive Improvement Spec (CP24+)

Generated 2026-06-03 from: deep HTML audit (lanks662 V1), ChatGPT gap analysis,
infrastructure audit of current codebase, GPT architecture review.
Every item maps to specific files.

---

## Priority 0 — Architectural Fixes (GPT review, 2026-06-03)

These must land BEFORE Phase 3 coaching spine work. They fix schema
contradictions that would cause Claude to implement both old and new
patterns simultaneously.

### 0A. decision_points[] — Multi-Decision Per Hand

**Problem:** Current design assumes one `key_decision_street` per hand. But many
real hands have multiple decision errors: preflop flat mistake + flop continue
mistake + river call mistake. Flattening to one street loses the drill-down.

**New structure (analyzer-owned):**
```python
hand['decision_points'] = [
    {
        'id': 'preflop_hero_call_001',
        'street': 'preflop',
        'hero_action': 'call',
        'facing_villain': 'villain_name',
        'is_key_decision': True,        # the one used for the verdict
        'leak_code': 'ColdCallNB',      # links to watchlist metric
        'correct_action': '3bet_or_fold',
        'correct_size_bb': None,        # or 8.5 for a sizing mistake
        'minimum_continue_hand': 'AJs / 99+',
        'threshold_explanation': 'ATo below call threshold vs 12BB HJ jam',
        'memory_rule': 'SB vs BTN/CO at 20-40BB = 3-bet or fold.',
        'drill_bucket': 'sb_cold_call_violation',
        'ev_action_bb': -2.4,
        'confidence': 'medium',
        'pot_before_villain_bet_bb': 3.5,
        'villain_bet_bb': 8.0,
        'pot_facing_hero_bb': 11.5,
        'hero_call_amount_bb': 8.0,
        'final_pot_if_call_bb': 19.5,
        'required_equity': 0.41,        # hero_call / final_pot
        'hero_equity_vs_range': 0.35,   # estimated
        'ev_call_bb': -1.2,
    },
    {
        'id': 'river_hero_call_002',
        'street': 'river',
        'hero_action': 'call',
        'facing_villain': 'villain_name',
        'is_key_decision': False,
        'note': 'downstream result of preflop flat — committed by flop SPR',
    }
]
hand['key_decision_id'] = 'preflop_hero_call_001'  # points to verdict basis
```

**Ownership:**
- Parser owns: `hand['villains']`, `hand['action_ledger']`, stacks, cards, board
- Analyzer owns: `hand['decision_points']`, `hand['primary_villain']`, `hand['key_decision_id']`
- Renderer reads: both, but never constructs analytical facts

**Why this matters:** Every downstream feature (mistake box, threshold, drill
generation, EV ranking) needs to know WHICH decision to attach to. Without
`decision_points[]`, we'd have to re-derive this in 5 different places.

**Files:**
- `gem_analyzer.py` — build `decision_points[]` during detector pass
- `gem_analyzer.py:_prefill_verdict()` — attach verdict to `key_decision_id`
- `gem_report_data.py` — pass through to appendix_hand_details
- `gem_report_draft/_hand_grid.py` — render per-decision annotations

**Effort:** High. This is the foundational data model change.

---

### 0B. Pot-Odds Field Normalization

**Problem:** Two naming conventions exist in the codebase:
- Old: `pot_before_action_bb`, `action_amount_bb`, `required_equity`
- New: `pot_before_villain_bet_bb`, `hero_call_amount_bb`, `final_pot_if_call_bb`, `ev_call_bb`

**Fix:** Use ONLY these 5 field names everywhere:

```python
# Canonical pot-odds fields (per decision_point)
pot_before_villain_bet_bb   # pot BEFORE villain acts
villain_bet_bb              # what villain put in
pot_facing_hero_bb          # pot_before + villain_bet (what Hero sees)
hero_call_amount_bb         # what Hero must put in to continue
final_pot_if_call_bb        # pot_facing + hero_call (total if Hero calls)
required_equity             # hero_call / final_pot_if_call (the break-even %)
hero_equity_vs_range        # estimated Hero equity (0-1)
ev_call_bb                  # hero_equity * final_pot - hero_call (+ means call is profitable)
```

**Formula:** `required_equity = hero_call_amount_bb / final_pot_if_call_bb`

**Files to normalize:** `gem_analyzer.py:_compute_decision_math()`,
`gem_pot_odds.py`, `_hand_grid.py` display code, golden test fixtures.

**Effort:** Medium. Grep-and-replace + verify all formulas.

---

### 0C. primary_villain Ownership: Analyzer, Not Parser

**Problem:** The parser can populate `hand['villains']` (all opponents with
seat/position/stack/shown_cards). But `primary_villain` (who Hero's key
decision was against) depends on analyzer logic — the river bettor, the
opener, the squeezer, etc.

**Rule:**
```python
# Parser owns:
hand['villains']              # dict of all opponents
hand['seat_stacks_bb_all']    # all stacks

# Analyzer owns:
hand['primary_villain']       # {'name': ..., 'position': ..., etc.}
hand['decision_points']       # which villain at each decision
hand['key_decision_id']       # which decision drives the verdict
```

**Renderer rule:** Never default to `opener` when reading villain data.
Always use `hand['primary_villain']['name']` → `hand['villains'][name]`.
Only use opener when the section is explicitly about opener behavior
(e.g., SB defend matrix vs specific opener positions).

**Files:** `gem_parser.py` (remove primary_villain assignment if present),
`gem_analyzer.py` (build primary_villain from decision analysis),
all renderer files that read `opener_position` as proxy for "villain".

---

### 0D. Candidate Hand Definition

**A hand is a "candidate" if it appears in ANY of:**
- Promoted leaks (S3 strategic leaks)
- All-in audit (bust_audit bucket)
- Large-loss audit (net_bb < -25)
- Deviation lists (preflop/postflop deviations)
- GTO shortlist (bestplay_screening)
- Analyst file (any hand with a verdict)
- Coaching flag hits
- Any hand with Hero VPIP and net loss > 10 BB

**Coverage targets** (per GEM_Next_Improvements_Spec):
- >= 90% of candidate hands have pot_odds populated
- >= 95% of candidate hands have decision_points[]
- 100% of candidate hands have appendix cards

**Why this matters:** Without a clear definition, coverage metrics are
meaningless. "90% of candidates have pot odds" could mean 90% of 50 hands
or 90% of 500 hands.

---

### 0E. Golden-Test vs Render-Only Gate

**Clarification:**
- Golden tests (parser correctness, equity math, field contracts) run
  during **analysis-cache generation** and **CI/checkpoint validation**
- Render-only mode (`--render-only`) loads cached data and renders in ~3-5s.
  It runs **post-render validation** (broken anchors, orphan popups,
  count consistency) but NOT golden equity tests
- Both gates must pass before a report is shipped

---

### 0F. Analysis QA Gate — Sanity Checks After Every Stage (GPT feedback)

**What:** Automated sanity checks that catch impossible data before it propagates.
Currently bugs like "1499% sizing" or "0BB stacks" reach the rendered report.

**Parser QA (after Stage 1):**
- Total pot from action ledger ~ result pot (within 1BB tolerance)
- No impossible stack sizes (negative, >500BB at micro stakes)
- Every all-in hand has `eff_stack_bb_at_decision` populated
- No villain cards unless showdown/show line exists in raw text
- Board card count valid by street (3 flop, 1 turn, 1 river)
- Game type recognized: **NLH only** — quarantine PLO/Short Deck/Omaha hands
  with a `game_type_quarantine` flag so Hold'em detectors don't fire on them

**Analyzer QA (after Stage 2):**
- `required_equity = hero_call_amount / final_pot_if_call` (formula check)
- EV formula matches stored EV: `ev_call = hero_eq * final_pot - hero_call`
- No hand flagged as both "cooler" AND "punt" simultaneously
- All-in equity source is valid (exact or MC, not fallback default)
- No Hold'em range engine applied to quarantined PLO hands

**Report QA (after render):**
- Every `data-hids` ID resolves to an appendix card
- No `(0BB)` in rendered HTML
- Mistake counts match across all 4 surfaces
- No `>1000%` in non-sizing columns

**Implementation:** New `gem_qa_gate.py` module with `run_parser_qa(hands)`,
`run_analyzer_qa(stats, hands)`, `run_render_qa(html)`. Called at each stage
boundary. Failures logged as warnings (non-blocking) or errors (blocking).

**Effort:** Medium. ~200 lines of assertion functions.

---

### 0G. Game-Type Quarantine (GPT feedback)

**Problem:** The pipeline currently processes PLO hands through Hold'em detectors.
Analyst notes already say "Hold'em framework does not apply" — that should be
a pipeline-level quarantine, not a per-hand workaround.

**Fix:** Parser sets `hand['game_type'] = 'NLH' | 'PLO' | 'PLO5' | 'ShortDeck'`
from the HH header. Analyzer skips all Hold'em-specific detectors when
`game_type != 'NLH'`. Renderer shows quarantined hands with a "non-NLH" badge.

**Files:** `gem_parser.py` (detect game type from header), `gem_analyzer.py`
(gate detectors), `gem_report_draft/_hand_grid.py` (badge).

**Effort:** Low-medium. Parser change is trivial; analyzer gating is ~20 lines.

---

### 0H. Universal analysis_confidence with risk_flags (GPT feedback)

**Problem:** The pipeline has detector confidence + tentative verdicts + analyst
overrides, but they use different schemas. A "CLEAR" detector mistake sounds
equally confident as an "exact" all-in equity, but they're fundamentally different.

**Fix:** Every analytical claim carries:
```python
{
    'label': 'III.2 Mistake',
    'confidence': 'HIGH',
    'reason_source': 'detector+pot_odds+range_model',
    'needs_review': False,
    'risk_flags': ['unknown_villain_range', 'multiway', 'bounty_context_missing']
}
```

**Risk flags vocabulary:**
- `unknown_villain_range` — equity is vs estimated range, not shown cards
- `multiway` — more than 2 players, changes equity/ranges
- `bounty_context_missing` — PKO hand without bounty EV adjustment
- `icm_not_computed` — bubble/FT hand without ICM adjustment
- `small_sample` — metric based on <20 opportunities
- `population_heuristic` — exploit recommendation from population stats, not solver

**Files:** All verdict-producing functions in `gem_analyzer.py`,
`gem_report_draft/_hand_grid.py` (render risk flags as subtle badges).

---

### 0I. Detector Calibration from Analyst Overrides (GPT feedback)

**Problem:** Detectors have static confidence levels. A detector that gets
cleared 40% of the time by the analyst should be MEDIUM, not CLEAR.

**What:** Persist analyst overrides across sessions. After each analyst pass,
compute per-detector precision:

```text
Detector: Missed River Value Bet
Flagged: 84 hands (across 5 sessions)
Confirmed: 37  |  Cleared: 31  |  Read-dependent: 16
Precision: 44%
Status: noisy — demote future confidence to MEDIUM
```

**Implementation:**
- `gem_meta_analysis.py` — accumulate `{detector_name: {flagged, confirmed, cleared}}`
  across session_history
- `gem_analyzer.py` — load calibration data; adjust confidence levels dynamically
- Renderer shows calibration note: "This detector is historically noisy for this player"

**Effort:** Medium. Cross-session persistence + feedback loop.

---

### 0J. Stratified Blindspot Sampling (GPT feedback)

**Problem:** Current blindspot sample is random unflagged VPIP hands. Random
sampling finds random things; stratified sampling finds hidden leaks.

**Sample strata (instead of random):**
- Largest won hands (non-flagged)
- Largest lost non-flagged hands
- River folds with strong made hands (possible missed value)
- Checked-back rivers after villain checked twice (possible missed thin value)
- SB flats that were not flagged (passive leak candidates)
- BTN/CO folds first-in (possible missed steals not caught by detector)
- C-bet skipped on high-card dry boards (possible missed c-bet)
- Multiway turn calls (difficult spot category)

**Implementation:** Replace random sample with stratified picker in
`gem_analyzer.py` candidate builder (~line 7700).

**Effort:** Low-medium. ~40 lines replacing the random picker.

---

## Robustness & Coverage Gaps (Claude Code audit, 2026-06-03)

Discovered by auditing the lanks662 report: 6,176 hands, 1,447 appendix cards
(23%), 106 with EAI equity (1.7%). These are real holes, not theoretical.

### R1. 93% of Hands Have Zero Equity Estimation

**The problem:** EAI only computes equity for showdown all-ins (~7% of appendix
cards, ~1.7% of all hands). For the vast majority of decisions — flop c-bet,
turn barrel, river call that doesn't go to showdown — there's no equity
assessment at all. The report says "you should have bet" but can't prove
Hero had enough equity to justify it.

**Fix: Range-based equity estimation for candidate hands.**
For every decision_point in a candidate hand:
1. Estimate villain's range from: position + action sequence + pot type + stack depth
   (use precomputed range tables from `gem_ranges.py`, not solver)
2. Compute Hero's equity vs that estimated range (fast lookup or enumeration)
3. Store as `hero_equity_vs_range` with `confidence: 'estimated'` + risk_flag
   `unknown_villain_range`

**Coverage target:** Every candidate hand (5-8% of volume) gets equity estimation.
Non-candidates stay at 0% coverage (acceptable — they weren't flagged).

**Effort:** High. Needs range estimation heuristics + equity computation for
non-showdown situations.

---

### R2. Won Hands with Suboptimal Play Are Invisible

**The problem:** 534 winning hands in the appendix. But if Hero won +20BB despite
calling too wide (hit two pair), the positive result masks the mistake.
Detectors only flag losses or specific action patterns. A won hand that was
-EV at decision time but ran well is NEVER flagged.

**Fix: "Lucky mistake" detector.** For showdown hands where Hero won:
1. If Hero's equity at decision time was <35% (underdog) AND Hero called/raised
2. Flag as "won but -EV decision" with outcome `got_lucky`
3. Surface in a "Positive variance masking mistakes" section

**Already partially exists:** EAI computes equity + `suckout_direction` for all-in
hands. Extend to non-all-in showdown decisions by estimating villain's range.

**Effort:** Medium. Range estimation needed (same as R1).

---

### R3. Preflop Folds Get Almost Zero Analysis (~75% of volume)

**The problem:** ~75% of hands are preflop folds. The only detector that fires
on folds is "missed steal." No analysis of:
- Correct folds that should be reinforced
- Over-folding by position (folding too much from CO/BTN)
- Under-folding by position (not folding enough from EP)
- Fold patterns vs specific opponent types

**Fix: Positional fold-frequency analysis.**
1. Compute fold% by position vs actual open/defend ranges
2. Flag positions where fold% is >10pp above expected
3. Cross-reference with card quality: "You folded 88 from HJ — this is an open"

**Partially exists:** The position matrix shows VPIP by position, and the
defend matrix shows fold rate vs opener. But there's no drill-down into
WHICH hands were folded that shouldn't have been (beyond "missed steal").

**Effort:** Medium. Needs fold-hand tracking in parser (currently only VPIP hands
get full detail), plus range membership check.

---

### R4. No Tilt / Emotional Cascade Detection

**The problem:** The report has a basic "quartile deterioration" tilt flag.
But it can't detect:
- "This mistake happened 3 hands after losing a 40BB pot" (emotional correlation)
- "Hero played 5 consecutive hands aggressively after being card dead" (frustration)
- "Hero's VPIP jumped from 22% to 40% in the last 30 hands of this tournament"

**Fix: Temporal decision-quality tracking.**
1. Compute rolling 20-hand mistake density (sliding window)
2. Detect spikes: if mistake density doubles after a big loss (>20BB), flag as
   "possible tilt cascade"
3. Cross-reference with timing: consecutive tables, re-buy decisions
4. Surface as "Decision quality timeline" in the report

**Infrastructure:** Hand IDs are chronological in GG — sorting by ID gives time order.
`hand['net_bb']` + `hand['tournament']` + sequential ordering = enough data.

**Effort:** Medium. ~50 lines for rolling window + spike detection.

---

### R5. No Bet-Sizing Tell Detection

**The problem:** Hero might always bet 33% pot with bluffs and 75% with value.
This is a MASSIVE exploitable tell that any observant opponent can detect.
The pipeline computes sizing stats but doesn't cross-reference sizing with
hand strength.

**Fix: Sizing-by-strength correlation detector.**
1. For each postflop bet/raise, record: `(street, sizing_pct, hand_strength)`
2. Compute average sizing by hand-strength bucket:
   - Value (top pair+): mean sizing X% pot
   - Bluff (missed draw, air): mean sizing Y% pot
   - If |X - Y| > 15pp → "sizing tell detected"
3. Surface as: "Your bluffs average 38% pot, your value bets average 72% pot.
   Opponents can exploit this."

**Effort:** Medium. Data exists in action_ledger + hand_strength. Correlation is ~30 lines.

---

### R6. No Disconnection / Timeout Hand Filtering

**The problem:** If Hero disconnects and auto-folds, the hand counts as a
preflop fold. If Hero times out on a river decision and auto-checks, it
counts as a passive check. Neither should influence strategy metrics.

**Fix:** Parser detects "Hero timed out" / "Hero disconnected" lines in raw HH.
Flag hand with `hand['disconnected'] = True`. Exclude from:
- VPIP/PFR calculations (didn't make a real decision)
- Missed steal / missed defend (couldn't act)
- Passivity metrics (forced timeout)

**Effort:** Low. Parser regex for disconnect/timeout lines + exclude flag.

---

### R7. No Duplicate Hand Detection Across Sessions

**The problem:** If the same tournament's hand histories appear in two different
input files (re-download, overlapping date ranges), hands get counted twice.
This inflates volume, distorts rates, and creates duplicate appendix cards.

**Fix:** Parser de-duplicates by hand ID. If `hand['id']` already seen, skip
the duplicate. Log warning: "N duplicate hands removed from input."

**Effort:** Trivial. ~5 lines in parser with a seen-set.

---

### R8. No Hand-Gap Detection

**The problem:** If tournament hand data jumps from hand #100 to hand #105,
we don't detect that 4 hands are missing. Missing hands distort:
- VPIP/PFR rates (denominator is wrong)
- Tournament narrative (key hand might be missing)
- Position analysis (one position under-represented)

**Fix:** After parsing all hands per tournament, check for ID gaps.
Log warning: "Tournament X: possible gap — 4 sequential IDs missing between
hand #100 and #105."

**Effort:** Low. ~15 lines in parser or report_data.

---

### R9. Multiple-Testing Correction for Detectors

**The problem:** 60+ detectors each fire independently. At a 5% false positive
rate per detector, ~3 detectors will trigger incorrectly on a normal session.
No statistical correction for running 60 simultaneous tests.

**Fix:** Apply FDR (false discovery rate) correction to detector outputs.
After all detectors run, rank by p-value/confidence, apply Benjamini-Hochberg
correction. Detectors that survive FDR correction are true HIGH confidence;
others are downgraded to MEDIUM.

**Alternative (simpler):** Use GPT's detector calibration approach (0I) instead —
empirical precision tracking is more practical than theoretical FDR for
poker heuristics.

**Effort:** Low for BH correction (~20 lines). Medium for full calibration.

---

### R10. Small-Sample Visual Weight Problem

**The problem:** A metric based on 3 opportunities gets equal visual prominence
as one based on 300. "BB 3-bet vs SB: 100% (1/1)" looks like a strong signal
when it's noise.

**Current state:** Wilson CI is computed for SOME metrics (40 mentions in report).
But many table cells show raw rates without sample-size context.

**Fix:** Universal rule: every rate cell with n < 20 gets a "thin sample" marker.
Options:
1. Dim the cell (reduced opacity)
2. Add `(n=3)` inline
3. Use `⚪` instead of colored status emoji
4. Wilson CI tooltip on every rate (already exists for some — extend to all)

**Effort:** Low. ~20 lines in renderer stat-row helpers.

---

### R11. No Stack Trajectory Tracking Within Tournament

**The problem:** The report knows Hero's starting stack per hand, but doesn't
track the TRAJECTORY: "Hero peaked at 85BB, lost a flip to 40BB, rebuilt to
60BB, busted at 12BB." This arc tells the story of the tournament.

**Fix:** For each tournament with >20 hands:
1. Compute stack_bb series by hand order
2. Identify: peak, valley, biggest gain, biggest loss
3. Surface as mini-chart or narrative: "Peaked at 85BB hand #47, crashed to 40BB
   after flip hand #52, rebuilt to 60BB by hand #78"
4. Cross-reference peaks/valleys with specific hands → "the story"

**Infrastructure:** `hand['stack_bb']` + chronological ordering by ID.

**Effort:** Medium. Stack series computation is trivial; rendering a mini-chart
or narrative is ~40 lines.

---

### R12. No "What If" Post-Fold Analysis

**The problem:** When Hero folds preflop, we never know if the fold was correct.
The board comes out, other players show — but we don't compute "if Hero had
called with A8o, would they have won?"

**This is intentionally limited** — post-fold equity is results-oriented thinking.
But for SPECIFIC categories it's useful:
- Folds on the bubble of satellites (were they correctly tight?)
- Premium folds in 3-bet pots (was the fold right vs villain's actual hand?)

**Fix (limited scope):** For showdown hands where Hero folded pre-flop AND
the final board is known AND villain hands are shown:
1. Compute Hero's hypothetical equity with their folded cards
2. If Hero would have won with >70% equity → flag as "interesting fold"
3. Don't call it a mistake — call it "what-if context"

**Effort:** Medium. Only meaningful when villain hands shown + Hero folded early.

---

## Auto-Coach Engine (Stage 7.5 — GPT feedback)

**The key architectural insight:** The pipeline is good at DETECTION but weak
on EXPLANATION, CORRECTION, and TRAINING. The fix is a new processing stage
between detector/equity and candidate builder:

```
[Detectors + EAI equity]
         |
         v
[7.5] AUTO-COACH ENGINE ← NEW
  - decision_points[] graph (0A)
  - root mistake attribution
  - pot odds + range equity
  - correct action + sizing
  - minimum hand threshold
  - leak bucket assignment
  - drill bucket assignment
  - counterexample search
  - line-class clustering
  - board-texture matrices
  - confidence + risk_flags
         |
         v
[Candidate builder + pre-fill]
```

### ACE-1. Board-Texture Behavior Matrices (GPT feedback)

**What:** Auto-produce c-bet behavior split by board class:
```text
C-bet by board class:
- A-high dry: 32% (target 65%) → under-cbet → 14 hands
- Paired dry: 28% (target 55%) → under-cbet → 8 hands
- Connected middling: 71% (target 35%) → OVER-cbet → 22 hands
- Monotone: 48% (target 35%) → slightly high → 6 hands
```

**Why it matters:** "C-bet too much/too little" is useless coaching. "You over-cbet
connected middling boards" is actionable. Board texture is already computed
by the parser but dormant in aggregate analysis.

**Implementation:**
- `gem_analyzer.py` — group c-bet decisions by `hand['board_texture']`, compute
  rate per texture class, compare to population targets
- `gem_report_draft/sections_iv_xii.py` — render texture matrix in the c-bet section
  (sec-9-1) with per-texture popup hand lists

**Effort:** Medium. ~60 lines analyzer + ~40 lines renderer.

---

### ACE-2. Line-Class Clustering (GPT feedback)

**What:** Group hands by recurring ACTION SEQUENCES, not individual errors:

```text
Line class: PFR OOP → c-bet flop → barrel bad turn → check river
Frequency: 37 hands
EV: -64 BB total
Main issue: turn barrel on range-disadvantage cards
Examples: 5 hands
Counterexample: 1 hand where barrel was correct
```

**Useful line classes to detect:**
- SB flat → call squeeze (passive preflop leak)
- BTN steal → miss c-bet dry flop (aggression leak)
- BB defend → check-call flop → overfold river (passivity leak)
- PFR IP → c-bet connected board → give up turn (barrel leak)
- OOP 3-bettor → c-bet A-high flop with TT/JJ (sizing/frequency leak)

**Why it matters:** Individual detectors catch single-hand errors. Line-class
clustering catches HABITUAL lines — the kind of leak that burns 50BB over
30 hands instead of 15BB on one hand.

**Implementation:**
- `gem_analyzer.py` — compute `hand['line_actions']` canonical string (already exists!)
  Group by line_actions prefix. Count frequency + total net_bb per cluster.
  Flag clusters with high frequency + negative EV.
- New section or subsection in report showing top 5 recurring -EV line classes

**Effort:** Medium. The data exists (`line_actions`); the clustering + rendering is ~100 lines.

---

### ACE-3. Population-Exploit Module (GPT feedback)

**What:** For every river call/bluff/value decision, add practical population heuristics:

```text
Solver baseline: mixed call (EV ≈ 0)
Population exploit:
- Unknown low-stakes pool underbluffs river jams → FOLD
- Calling stations overcall river bets → bet larger for value
- Nits underbluff big river bets → fold to big sizing
Recommended exploit: fold (population underbluffs)
```

**Not a solver.** Just practical heuristics from known population tendencies
at low-mid stakes:
- Population underbluffs rivers (MDF violation → fold more)
- Population overcalls small bets (size up value bets)
- Population underfolds to 3-bets (3-bet tighter for value)
- Population overdefends vs steals (steal wider)

**Implementation:**
- New `gem_population_exploits.py` — lookup table of population tendencies
  by spot type (river call, river bet, 3-bet, steal)
- `gem_analyzer.py` — attach exploit recommendation to decision_points
- Renderer shows exploit note on hand card alongside GTO baseline

**Effort:** Medium. Authoring the population heuristic table is the work.

---

### ACE-4. ICM/Bounty Red-Flag Approximation (GPT feedback)

**What:** Rough ICM classifier — not perfect math, just practical flags:

```python
hand['icm_context'] = {
    'near_bubble': True,        # within 10% of pay places
    'final_table': False,
    'satellite': False,
    'bounty_covers_villain': True,
    'hero_covered': False,       # Hero shorter than villain
    'stack_utility': 'medium',   # low/medium/high based on stack relative to avg
    'icm_flag': 'ChipEV says call, but ICM risk high → analyst review required'
}
```

**When flag fires:**
- Near bubble + Hero has big stack → flag "ICM says fold wider than chipEV"
- Bounty covers villain → flag "bounty may justify wider call — don't auto-label mistake"
- Satellite + Hero in qualifying position → flag "stop gambling, ICM says fold everything"

**Implementation:**
- `gem_parser.py` — detect tournament phase + player count from HH headers
  (partially exists via `tournament_phase`)
- `gem_analyzer.py` — compute rough ICM flags from phase + stack depth
- Detector gating: don't fire "missed steal" near bubble with short stack

**Effort:** Low-medium. Phase detection partially exists. Rough ICM flags are ~30 lines.

---

### ACE-5. Counterexample Generation (GPT feedback)

**What:** For each promoted leak, show 3 hand types:
1. **Clean example** — obvious mistake
2. **Boundary example** — close/mixed spot
3. **Counterexample** — similar spot where Hero played correctly

**Prevents overcorrection.** If the report says "bet more rivers," it should also
show a river where checking back was correct — so the player doesn't become a
spew monkey.

**Implementation:**
- For each leak bucket, partition hands by EV:
  - Worst EV → clean example
  - Middle EV → boundary
  - Best EV in same action category → counterexample (or same spot but different action)
- `gem_report_draft/sections_mistakes.py` — render as 3 labeled groups per leak

**Effort:** Medium. Needs partition logic + cross-referencing same-spot-different-action hands.

---

## Priority 1 — Coaching Spine (the "diagnostic ladder")

The report already has metric watchlist, promoted leaks, drills, deviation lists,
and hand-level detail. What's missing is a consistent contract:

> **Metric says off -> show exactly where -> show why -> show hands -> show what to do -> drill it.**

### 1A. Metric Drilldown Cards — every red/amber metric gets a breakdown

**What:** When a metric is red/amber in S6.0, the linked section should show a
position/street/role sub-breakdown, not just the aggregate number.

**Example:** VPIP-PFR gap = 12.2 (target <8). Breakdown should show:
- SB flat-call rate: 18% (main contributor)
- Cold-call from CO: 14% (secondary)
- BB defend via flat: normal
- Limps/overlimps: 2 (negligible)

**Infrastructure:** `gem_leak_watchlist.py` has flat items with `label + action`.
Need to add `sub_breakdowns: [{position, value, target, delta, hand_ids}]` per item.

**Files:**
- `gem_leak_watchlist.py` — add breakdown builder per metric key
- `gem_report_draft/sections_financial.py:1359` — render sub-breakdown rows
- `gem_report_draft/tldr.py:824` — dashboard card shows mini-breakdown

**Blocked by:** Nothing. Data already exists in stats; just needs slicing.

---

### 1B. Standard Mistake Box — structured format for every hand note

**What:** Every hand card's analyst-notes yellow block should have a fixed structure.
The fields live on the `decision_point` (from 0A), not as free-form markdown.

**Data model (per decision_point, computed by analyzer + prefill):**
```python
{
    # From 0A decision_points:
    'correct_action': '3bet_or_fold',
    'correct_size_bb': 8.5,             # None if not a sizing issue
    'minimum_continue_hand': 'AJs / 99+',
    'threshold_explanation': 'ATo is below call threshold vs 12BB HJ jam',
    'memory_rule': 'SB vs BTN/CO at 20-40BB = 3-bet or fold.',
    'drill_bucket': 'sb_cold_call_violation',
    # Pot odds from 0B:
    'required_equity': 0.41,
    'hero_equity_vs_range': 0.35,
    'ev_call_bb': -1.2,
}
```

**Rendered on the hand card as:**
```
MISTAKE: Called SB vs BTN open with AJo at 32BB instead of 3-bet/fold.
WHY WRONG: SB flatting creates dominated OOP pots. Need 41% equity, have ~35%.
CORRECT ACTION: 3-bet to 8.5BB or fold depending on villain.
THRESHOLD: Minimum continue hand: AJs / 99+. ATo is below threshold.
MEMORY RULE: SB vs BTN/CO at 20-40BB = 3-bet or fold.
EXCEPTION: Flat only with specific exploit/read, not default.
DRILL: sb_cold_call_violation (auto-generated GTOW scenario)
```

**Implementation:**
- `gem_analyzer.py:_prefill_verdict()` — populate the 0A decision_point fields
  for every auto-resolvable hand. HIGH-confidence hands get all fields;
  MEDIUM hands get partial; analyst fills the rest.
- `gem_report_draft/_hand_grid.py:121` — render from decision_point fields,
  not from free-form markdown. Fall back to markdown for legacy analyst entries.
- `gem_ranges.py` — `range_boundary()` and `hand_in_range()` functions power
  the `minimum_continue_hand` and `threshold_explanation` fields.

**Blocked by:** 0A (decision_points) and 1C (range membership function).

---

### 1C. Minimum Hand / Threshold — "what's the weakest correct hand here?"

**What:** Every range-based mistake (wide open, missed defend, wide cold-call) should say:
"Minimum correct open here is A8s/AJo/KTs/77. Your A7o is below threshold."

**Infrastructure:** `gem_ranges.py` has range expansion but NO membership test.
`sections_iv_xii.py` has `_DEFEND_RANGES` with full ranges per position pair.
The `_defend_range_note()` function (line 367) already builds the note but doesn't
compute the threshold boundary.

**Implementation:**
- `gem_ranges.py` — add `hand_in_range(hand_class, range_str) -> bool` and
  `range_boundary(range_str) -> str` (returns the bottom hands of the range)
- `sections_iv_xii.py:_defend_range_note()` — use membership test, add boundary:
  "BB vs HJ: defend range is 33+, A2s+... Boundary: Q9o/J9s. Your A5o is INSIDE."
- `gem_report_draft/_hand_grid.py` — display threshold on each flagged hand card
- Add `_OPEN_RANGES` table (position -> RFI range + target%) for open decisions

**Blocked by:** `_OPEN_RANGES` table needs to be authored from Poker_Ranges_Text.txt.

---

### 1D. EV-Weighted Leak Ranking — prioritize by BB lost, not count

**What:** Each promoted leak in S3 should show:
> **Caller IP Agg - Priority #1**
> Impact: -42 BB estimated / 37 spots / recurring
> Main pattern: IP caller checks back too many strong/marginal-value hands

**Infrastructure:** `gem_pot_odds.py` computes per-hand EV. Promoted leaks have
per-hand `net_bb` but no rollup. `sections_mistakes.py:757` iterates promoted leaks
by name, not by EV impact.

**Implementation:**
- `gem_analyzer.py` candidate builder — compute `total_ev_lost_bb` per leak bucket
  by summing per-hand EV estimates
- `gem_leak_watchlist.py` — add `ev_impact` field to each leak
- `gem_report_draft/sections_mistakes.py` — sort promoted leaks by EV impact;
  render impact line in the S3 table
- `gem_report_draft/tldr.py` — TL;DR leak summary uses EV ranking

**Blocked by:** EV estimates are approximate (not all hands have solver EV).
Use `net_bb` sum as fallback.

---

## Priority 2 — Hand Card Enrichment

### 2A. Board Texture Label on Every Postflop Card

**What:** Every hand that went to flop+ should show: "Board: A72r (dry A-high rainbow)"

**Infrastructure:** ALREADY COMPUTED. `hand['board_texture']` set by parser
(`gem_parser.py:190-207`). 10+ categories: `dry_ahigh`, `wet_monotone`,
`paired_board`, `connected_mid`, etc. Just not displayed.

**Implementation:**
- `gem_report_draft/_hand_grid.py` — in street header for FLOP, add
  `board_texture` label from `h.get('board_texture', '')`. One-liner.

**Effort:** Trivial. < 10 lines.

---

### 2B. Pot Odds on Every Call Decision (not just river)

**What:** Every call action in the hand grid should show "need X% to call".
Currently only shown on river calls (1.8% coverage).

**Infrastructure:** The code at `_hand_grid.py:602-615` already computes pot odds
but is gated by `if street == 'river' and is_h`. Remove the `river` gate.

**Implementation:**
- `gem_report_draft/_hand_grid.py:602` — change `if street == 'river' and is_h`
  to `if is_h` (show pot odds on ALL hero calls)

**Effort:** Trivial. 1-line change.

---

### 2C. IP/OOP Label on Hand Cards

**What:** Each postflop street header should show "Hero IP" or "Hero OOP".

**Infrastructure:** `hand['hero_ip']` exists (boolean, preflop-derived). Accurate
for HU pots. For multiway, position relative to last aggressor would be better
but `hero_ip` covers the common case.

**Implementation:**
- `gem_report_draft/_hand_grid.py` street header — add
  `"(IP)" if h.get('hero_ip') else "(OOP)"` after the street label

**Effort:** Trivial. ~5 lines.

---

### 2D. Opponent Count per Street

**What:** Show "HU", "3-way", "4-way" on each street header.

**Infrastructure:** `hand['players_at_flop']` exists. For turn/river, can be
derived from the action ledger (count distinct players with non-fold actions).

**Implementation:**
- `gem_report_draft/_hand_grid.py` — compute players per street from action ledger;
  display badge on each street header

**Effort:** Medium. ~20 lines.

---

### 2E. Per-Street Pot Reconstruction in Grid

**What:** Each street header already shows "X BB pot" (line 452 in _hand_grid.py).
Verify it's correct and prominent.

**Infrastructure:** `pot_by_street` dict is passed to the grid renderer.
Already displayed. Just needs visual prominence check.

**Effort:** Already done. Verify only.

---

### 2F. Villain Shown Hand Strength Label

**What:** When villain shows at SD, label their hand: "Villain: K7s (top pair)"
not just "K7s".

**Infrastructure:** `_describe_made_hand()` already exists in `_html.py` and IS
used at line 750 in `_hand_grid.py`. Check if it renders for all SD hands.

**Effort:** Verify coverage. May already work.

---

### 2G. ICM / Tournament Pressure Context

**What:** Near-bubble hands should show bubble factor or ICM pressure.
"Phase: BUBBLE (45/50 paid, avg stack 22BB)"

**Infrastructure:** `hand['tournament_phase']` exists (79.5% coverage).
No bubble factor computation exists.

**Implementation:**
- `gem_parser.py` — enhance tournament_phase with player count / pay structure
  if available from HH headers
- `gem_report_draft/_hand_grid.py` — show phase badge prominently

**Effort:** Medium. Phase badge is trivial; bubble factor needs pay structure data
which GG HH may not provide.

---

## Priority 3 — Section Drill-Down Gaps

### 3A. Wire Hand-List Popups into Zero-Popup Sections

10 stat-table sections have tables but ZERO hand drill-down:

| Section | Content | Hand Source |
|---------|---------|-------------|
| sec-9-2 | CBet 3BP | 3BP c-bet opps from stats |
| sec-9-3 | Check-Raise | CR hands from stats |
| sec-9-4 | BB Lead Profile | donk-bet hands |
| sec-11-2 | Sizing Profile | over/undersize hands |
| sec-11-6 | Bluff Categories | value_ids/semi_ids/pure_ids (ALREADY IN STATS) |
| sec-11-8 | Fold to CBet | fold-to-cbet hands |
| sec-11-10 | AF Breakdown | aggressive action hands |
| sec-9-5 | Facing Donks | donk-response hands |
| sec-12 | Leak Persistence | tracked leak hands |
| sec-4-2 | PKO Bounty Context | bounty-involved hands |

**Implementation:** For each, identify the hand-ID source in `stats` and wire
`_popup_example_ids()` + `data-hids` into the table cells. Same pattern as the
defend/3bet/squeeze popups.

**Effort:** Medium. ~15 lines per section x 10 sections = ~150 lines total.

---

### 3B. Representative / Boundary / Counterexample Hands per Leak

**What:** For each promoted leak, show 3 hand types:
1. **Clean example** — obvious mistake
2. **Boundary example** — close/mixed spot
3. **Counterexample** — similar spot where play was correct

**Implementation:**
- `gem_report_draft/sections_mistakes.py:_candidate_hands_for_leak()` — partition
  candidates by EV or confidence: worst (clean), middle (boundary), best in
  same category (counterexample)
- Render as 3-tab or 3-row groups in the S3 leak detail

**Effort:** Medium-high. Needs candidate ranking by EV + correct-play detection.

---

### 3C. Confirmed vs Candidate vs Noise Tagging (P3c from feedback)

**What:** Three explicit buckets everywhere:
- **Confirmed mistake** — hand reviewed; drill it
- **Pattern candidate** — metric says suspicious; review before drilling
- **Noise / mixed** — don't change behavior yet

**Infrastructure:** Partially exists. Analyst entries have verdicts (III.1/III.2/III.3).
Auto-classified hands have no `review_tier` field.

**Implementation:**
- Add `review_tier` field: `reviewed | auto_equity | auto_preflop | auto_small | out_of_scope`
- Renderer shows honest tag: "auto -- not individually reviewed"
- Coverage stats: "N reviewed / M auto" truthfully

**Effort:** Medium. Data model change + renderer update.

---

## Priority 4 — Coaching Automation

### 4A. "What Should I Study" Summary

**What:** A prioritized 3-item action list at the top:
"Before your next session: (1) review these 5 cold-call hands, (2) practice
this GTOW drill, (3) read this range"

**Implementation:** Already partially exists in the dashboard watch card.
Enhance to show specific hand counts and drill links.

**Effort:** Low. ~20 lines in `tldr.py`.

---

### 4B. Leak Decision Trees

**What:** For each promoted leak, generate a decision tree:
"Before calling preflop outside BB: (1) Am I in BB? -> call okay.
(2) Pocket pair with set-mining odds? -> call if 15x IP. (3) Otherwise fold/3-bet."

**Implementation:** Static decision trees per leak type, stored in a JSON/dict map.
Renderer looks up tree by leak name and renders it.

**Effort:** Medium. Authoring ~10 decision trees is the work, not the code.

---

### 4C. Opponent-Type Exploit Integration on Hand Cards

**What:** Each hand card should show when the correct play changes by villain type:
"Solver baseline: river bluff okay. Population: overcalls, so check.
Villain-specific: if Station, never bluff."

**Infrastructure:** `villain_archetype` is on 100% of cards. Exploit notes exist
in `villain_exploit_note`. Just need to surface them prominently.

**Implementation:**
- `gem_report_draft/_hand_grid.py` — show archetype + exploit in the result footer

**Effort:** Low. ~10 lines.

---

### 4D. "First Mistake Before the All-In" on Bust Hands

**What:** Every large loss should identify:
- Final all-in result: punt / cooler / flip / bad beat
- **First avoidable mistake** (e.g., 3-bet too large preflop)
- **Street where EV was actually lost**

**Infrastructure:** `decision_math` per-street data exists from `_compute_decision_math()`.
The analyst TL;DR sometimes identifies this manually.

**Implementation:**
- `gem_analyzer.py:_prefill_verdict()` — for bust_audit hands, trace back through
  streets to find the first -EV decision point
- Surface as "Root cause: over-committed on flop with TPNK" in the hand card

**Effort:** High. Requires multi-street EV comparison logic.

---

### 4E. Drill Packs from Report

**What:** For each promoted leak, generate a drill pack:
- Leak: SB flats vs CO/BTN
- Goal: 3-bet/fold correctly
- Pass condition: 85% correct
- 25 hands from this report + scenario description
- Hand IDs to replay

**Infrastructure:** `gem_drill_export.py` already generates GTOW drill JSON.
Top Drills section exists.

**Implementation:** Extend drill export to generate per-leak packs with the
report's actual hand IDs as source material.

**Effort:** Medium.

---

### 4F. Session-Over-Session Comparison

**What:** "Your VPIP was 25.6% (last session: 23.1%, trend: up)"

**Infrastructure:** `session_history_path` + CSV exists. `skill_band_cumulative`
reads multi-session data. Trend arrows exist in `skill_movement`.

**Implementation:**
- `gem_report_data.py` — load previous session's watchlist values
- `sections_financial.py:1359` — add "prev" column to watchlist table

**Effort:** Medium. Need to persist watchlist values per session.

---

## Priority 5 — Pipeline / Code Quality

### 5A. Candidate Ordering Before Equity Passes (P1 from feedback)

**What:** `gem_analyzer.py` emits the candidate/template file AFTER the equity MC
pass (~line 7436). If equity times out, candidates are never written, forcing the
analyst to reconstruct by hand from 3 different scattered sources.

**Fix:**
1. Move candidate emission to BEFORE equity (candidates need parsed hands + detector
   flags, not equity)
2. Backfill equity fields into candidate file after equity completes
3. Consolidate ALL candidate sources: mistakes, punts, coolers, clinical_candidates,
   deep-cold-call, calldown, multistreet buckets — into one union
4. Add `--equity-timeout` flag for graceful degradation

**Effort:** High. Requires careful reorder of gem_analyzer.py's 8600-line flow.

---

### 5B. Verdict Routing Decoupled from String Prefixes (P3d from feedback)

**What:** 76 `verdict.startswith()` checks gate routing across the renderer.
A label change (e.g., "Cleared" -> "Auto -- not individually reviewed") risks
silently dropping hands into "pending."

**Fix:** Parse the verdict once into `{class: 'III.3', label: '...', tier: '...'}`
and route on `class`, not on `startswith` of the display string.

**Files:** All renderer files that use `.startswith(('III.0', 'III.3', ...))`.
Grep for `verdict.*startswith` — 76 sites.

**Effort:** Medium-high. Mechanical but must touch 76 sites without regressions.

---

### 5C. Extreme Value Display Capping

**What:** Sizing Profile table shows 1499% in the Max column (a 15x pot overbet).
Mathematically correct but visually alarming.

**Fix:** Cap displayed sizing at ">10x" when value exceeds 1000%. Same for any
percentage column that can exceed reasonable display bounds.

**Files:** `gem_report_draft/sections_iv_xii.py` — sizing profile renderer.

**Effort:** Trivial. ~5 lines.

---

### 5D. Per-Metric Breakdown Dimensions (detail for 1A)

ChatGPT identified specific breakdown axes each metric needs:

| Red Metric | Required Breakdown Dimensions |
|---|---|
| VPIP-PFR gap | by position, stack depth, cold-calls, SB flats, BB defends, limps/overlimps |
| AF (low) | by street x position x role: IP PFR, OOP PFR, caller IP, caller OOP |
| ATS (low) | CO/BTN/SB separately, first-in spots only, stack depth buckets |
| 3-bet OOP (low) | SB vs CO/BTN, BB vs BTN/SB, squeeze opportunities, blockers |
| Cold-call (high) | by position, by opener position, by stack depth |
| C-bet (low/high) | by street, board texture, IP/OOP, SRP vs 3BP |
| BB iso vs SB | stack depth buckets, villain limp frequency context |

These dimensions must be computed in the watchlist builder and rendered as
sub-rows or expandable detail under each flagged metric.

---

## Structural Guarantees (Testing Checklist)

| # | Check | Assert |
|---|-------|--------|
| G1 | Every red/amber metric is clickable | No red/amber in watchlist without `<a>` |
| G2 | Every popup renders >= 1 hand | No `data-hids` produces 0 renderable rows |
| G3 | Every /B metric uses same denominator | ITM/B, Top1/B, Top5/B, FT/B all divide by n_b |
| G4 | Every hand ref has an appendix card | Every `sec-app-hand-X` anchor exists |
| G5 | No stat section has table with 0 drill-down | Every section with `<table>` has hand-list-trigger or sec-app-hand |
| G6 | Defend/open targets are per-opener | No defend matrix row uses aggregate band |
| G7 | Mistake counts match across 4 surfaces | strip = TL;DR = S2 header = S2.2 heading |
| G8 | Pot odds on every hero call | Every call action with amt > 0 shows need X% |
| G9 | Board texture on every postflop card | Every hand with board length >= 3 shows texture label |
| G10 | No "got it in as N% underdog" | Narrative uses Suckout/Flip/Behind classification |
| G11 | Structured mistake box on reviewed hands | Every III.1/III.2 card has mistake_desc + correct_action |
| G12 | Threshold on range-based mistakes | Every wide/missed hand shows boundary + membership |

---

## Implementation Sequence (GPT-reviewed, batch-safe)

### HARD GATE RULE
> **Do not implement Batch 2+ until Batch 1 foundation tests pass and legacy
> fields are either migrated or explicitly shimmed.**

### Pipeline Architecture (corrected dependency order)

The Auto-Coach Engine cannot sit BEFORE the candidate builder (it needs
candidates), but candidates can't wait for Auto-Coach (they need to exist
for equity, prefill, and analyst). Fix: **two-pass candidate structure:**

```
[1] Parser
[2] Detectors (60+ rules)
[3] Initial Candidate Builder ← builds candidate set from detectors/losses/strata
[4] Auto-Coach Engine ← enriches each candidate with decision_points, equity, coaching
[5] Candidate Re-ranker ← EV priority, confidence, rep/boundary/counter selection
[6] Prefill Verdicts ← reads enriched decision_points
[7] Candidate + Template emission ← BEFORE equity MC (not after!)
[8] EAI Equity MC ← backfills equity into existing candidates
[9] Analyst Step
[10] Post-Analyst Refresh + Render
```

### Merged duplicates (GPT review)

| Kept | Merged into it | Reason |
|------|---------------|--------|
| ACE-5 Counterexamples | 3B Rep/boundary/counter | Same feature |
| 1A Metric drilldown | 5D Per-metric dimensions | 5D is the detail spec for 1A |
| 0H Confidence model | 3C Confirmed/candidate/noise | Share one schema |
| 4D First mistake | 0A decision_points root_mistake_street | Special case of multi-decision |
| R9 FDR correction | 0I Detector calibration | Empirical calibration > theoretical FDR |

### Appendix card policy (GPT review)

```
100% of reviewed / promoted / high-impact candidates → full appendix cards
100% of ALL candidates → compact drilldown rows (popup table, not full card)
Only top-priority candidates get full cards by default
```

This prevents appendix explosion when candidate pool widens.

---

### Batch 1 — Foundation (give to Claude FIRST, alone)

**Data model:**
1. `decision_points[]` data model (0A)
2. Pot-odds field normalization (0B — single schema, delete old names)
3. `primary_villain` analyzer ownership (0C)
4. Candidate hand definition (0D)

**Pipeline robustness:**
5. Candidate emission BEFORE equity MC (was 5A — promoted to Batch 1)
6. Duplicate hand detection (R7)
7. Game-type quarantine NLH/PLO (0G)
8. Disconnection/timeout hand filtering (R6)
9. Basic QA gate — parser + analyzer sanity checks (0F)

**9 items. All low-to-medium risk. Establish the clean foundation.**

**Test gate before proceeding:**
- `decision_points[]` populated on >= 95% of candidate hands
- pot-odds schema: zero legacy field names remain (grep returns 0)
- `primary_villain` set by analyzer, not parser
- candidate file written before equity MC starts
- no PLO hands processed by NLH detectors
- no disconnection hands in VPIP/PFR denominators
- QA gate catches: pot mismatch, impossible stacks, missing eff_stack

---

### Batch 2 — Coverage + Confidence

1. Universal `analysis_confidence` + `risk_flags` (0H, absorbs 3C)
2. Stratified blindspot sampling (0J)
3. Hand-gap detection per tournament (R8)
4. Small-sample visual markers (R10 — dim/mark cells with n < 20)
5. Golden-test vs render-only gate clarification (0E)
6. Compact candidate coverage stats in report

**6 items. Makes the report honest about what it knows vs what it's guessing.**

---

### Batch 3 — Auto-Coach MVP

1. Standard mistake box — correct_action, minimum_hand, memory_rule, drill_bucket (1B, absorbs 1C)
2. Root mistake attribution — `root_mistake_street` on decision_points (absorbs 4D)
3. EV-weighted leak ranking (1D)
4. Metric drilldown cards with per-metric breakdown dimensions (1A, absorbs 5D)
5. Counterexamples — clean/boundary/counter per leak (ACE-5, absorbs 3B)
6. Section drill-down wiring — popups into 10 zero-popup sections (3A)

**6 items. This is the coaching spine: "off -> where -> why -> hands -> drill."**

---

### Batch 4 — Pattern Analysis

1. Board-texture behavior matrices (ACE-1)
2. Line-class clustering (ACE-2 — group by line_actions, find habits)
3. Sizing-tell detection (R5 — sizing vs hand-strength correlation)
4. Lucky mistake detector (R2 — won hands with -EV decisions)
5. Range-based equity for non-showdown candidates (R1 — depends on Batch 1 ranges)

**5 items. Deeper analysis that finds leaks no single detector catches.**

---

### Batch 5 — Advanced Context + Coaching Automation

1. Population-exploit module (ACE-3)
2. ICM/bounty red-flag approximation (ACE-4)
3. Tilt/emotional cascade detection (R4)
4. Stack trajectory tracking per tournament (R11)
5. Session-over-session comparison (4F)
6. "What should I study" summary (4A)
7. Leak decision trees (4B)
8. Drill packs from report (4E)
9. Detector calibration from analyst overrides (0I)

**9 items. Advanced features that require a stable foundation.**

---

### Batch 6 — Code Quality + Research

1. Verdict routing decoupled from startswith (5B — 76 sites)
2. Extreme value display capping (5C)
3. Preflop fold analysis (R3)
4. Post-fold what-if (R12 — limited scope)
5. Auto narrative draft

**5 items. Polish and research. Lower priority than coaching value.**

---

## Quick wins DONE in CP23

- 2A Board texture on cards DONE
- 2B Pot odds on all calls DONE
- 2C IP/OOP label on cards DONE
- 4C Villain exploit on cards DONE

---

## Item Count Summary

| Batch | Items | Focus | Status |
|-------|-------|-------|--------|
| CP23 quick wins | 4 | Hand card enrichment | **DONE** |
| Batch 1 — Foundation | 9 | Data model + pipeline robustness | Next |
| Batch 2 — Coverage + Confidence | 6 | Honest reporting | After B1 gate |
| Batch 3 — Auto-Coach MVP | 6 | The coaching spine | After B2 |
| Batch 4 — Pattern Analysis | 5 | Deep leak detection | After B3 |
| Batch 5 — Advanced Context | 9 | Automation + context | After B4 |
| Batch 6 — Code Quality | 5 | Polish + research | Whenever |
| **Total** | **44 items** | | **4 done, 40 spec'd** |
