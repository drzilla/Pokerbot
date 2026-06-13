# Implementation Plan — Coaching Cards Phase 1 (v8.10.0)

> **For:** GPT implementation session
> **From:** Claude Code architecture review of handoff package + codebase audit
> **Date:** 2026-06-10
> **Codebase:** GEM v8.9.9 (616 tests, 24 verified files, 149 canaries)

---

## Final patch status

Applied and verified (v8.9.9):
- EAI private evaluator import uses inner `except Exception`.
- EAI private evaluator smoke test compares value against public evaluator.
- MC 20k comment softened to non-borderline classification stability.
- Grid test verifies third column `minmax(0,1fr)`.
- Villain evidence clustering skips clustering when signal key/family/label is missing.
- Villain evidence cluster merge preserves missing `suggests` and `so_what`.
- Villain evidence label dedups alias/V-number and falls back to `"Unknown villain"`.
- B8 commentary collapse implemented, but remains skip-default / optional-risk in future similar plans.

Verification: 616/616 tests pass, 24/24 files verified, 149/149 canaries verified.

---

## What This Is

Add a compact coaching-card layer inside the existing **Hand Details → Commentary** column. Each card answers: What should I do? Why? What range? What changes because of bounty/ICM/villain? What should I learn?

Three-layer architecture: `decision_facts` → `coaching_interpretation` → `display_card`. Renderer consumes only `display_card`. **Renderer performs zero poker calculations.**

Phase 1 is conservative programmatic cards only — no LLM enrichment, no blocker logic, no Hero-range commentary, no full mixed-action engine.

---

## Hard Rules (carry forward from all prior sessions)

- `--analyst-file` must NOT be placed inside HH input directory
- Renderer must not create analytical facts
- No new detectors or threshold changes without explicit approval
- Desktop UX for non-V25 areas must not change
- Non-V25 mobile: `@media(max-width:768px)`, NOT 900px
- Never hide a table unless JS replacement exists (`.has-mobile-cards` gating)
- `data-mobile-mode` must live on `.table-shell`
- Package naming: v8.9.9 is used; next is v8.10.0
- All previously parked items remain parked

---

## File Map — Where Things Live

| What | File | Key Lines / Functions |
|------|------|----------------------|
| Pipeline orchestrator | `gem_analyzer.py` (532 KB) | `__main__` block, calls coverage builder |
| Coverage builder | `gem_coverage_builder.py` (116 KB) | `build_and_write()` — candidates, auto-verdicts, worksheet |
| Decision math / pot odds | `gem_analyzer.py` ~L2164-2187 | `required_equity`, pot sizes, call amounts from action ledger |
| Bounty data | `gem_analyzer.py` ~L1506-1512 | `h['bounty_value_bb']`, format='BOUNTY', hero_covers |
| Tournament phase / ICM | `gem_analyzer.py` ~L138, 1250, 1370 | `tournament_phase` field: bubble_zone, post_bubble, ft_zone, late_reg |
| Villain intel | `gem_villain_intel.py` (109 KB) | `build_villain_intel()` → evidence_atoms, exploit_opportunities, read_states |
| Opponent profiles | `gem_opponent_profiler.py` (25 KB) | Per-villain 4D dimensions + 10 archetypes |
| Hand detail data | `gem_report_data.py` ~L2755-2796 | `appendix_hand_details` dict → actions by street, showdown, eai_equity |
| Hand context builder | `sections_xiv.py` ~L1343-1568 | `_build_hand_opponent_contexts()` → 4-bucket context routing |
| Commentary column | `_html.py` ~L914, 1430-1465 | `<h4>Commentary</h4>` section, `notesByStreet` routing |
| Verdict feedback | `_html.py` ~L697-701, 1918-1975 | Agree/Debate/Report chips, localStorage persistence |
| Report data serialization | `draft.py` ~L300-400 | JSON embedding into HTML template |
| Parser | `gem_parser.py` (100 KB) | `parse_session()` → hands list with ~80 fields |
| Ranges | `Poker_Ranges_Text.txt` (100 KB) | 405 charts: open, 3-bet, squeeze, jam by position+depth |
| EAI equity | `gem_eai_equity.py` (9 KB) | Monte Carlo all-in equity (ahead/flip/behind) |

---

## Implementation Phases

### Phase A: New Module — `gem_coaching_cards.py`

**What:** Pure-Python module that builds `decision_facts`, runs template interpretation, derives quality gates, and emits `display_card` objects. No renderer logic. No JS.

**Location:** New file `gem_coaching_cards.py` at project root (same level as gem_analyzer.py).

**Entry point:**

```python
def build_coaching_cards(hands, stats, report_data, ranges=None):
    """Build coaching display_cards for all eligible hands.
    
    Returns dict mapping hand_id → list[display_card].
    Mutates nothing.
    """
```

#### A1: Decision Facts Builder

Build `decision_facts` for each eligible hand/street decision. The handoff specifies exactly which spots deserve a fact (Section "Which Spots Deserve a Card?"):
- Hero faces all-in
- Hero calls/folds large bet
- Hero jams/rejams
- Bounty all-in/call/jam
- River call/fold/bet
- Turn raise/call/fold vs raise
- Large Hero bet/raise (60%+ pot)
- Analyst-reviewed hands
- Auto-flagged punt/mistake/good exploit
- Issue explorer hands

**Data sources for each decision_facts sub-object:**

| Sub-object | Source in existing pipeline |
|------------|---------------------------|
| `decision_meta` | `h['pf_action']`, `h['hero_bets']`, `h['facing_bets']`, `h['decision_points']`, auto-verdict from `report_data['auto_verdicts']` |
| `game_context` | `h['format']` (BOUNTY/FREEZEOUT/SATELLITE), `h['game_type']`, `h['table_size']`, `h['n_players']`, action ledger per-street player counts |
| `hero` | `h['position']`, `h['cards']`, `h['stack_bb']`, `h['eff_stack_bb']`, `classify_hand_for_betting()` from gem_parser |
| `villains` | Action ledger: who bet/raised/jammed. `h['villains']` dict for stacks. `covered_by_hero` = hero stack > villain stack |
| `board` | `h['board']`, `h['board_texture']`, `classify_board()` from gem_parser, `h.get('draw_profile')` from gem_made_hands |
| `pot_facts` | `h.get('pot_facing')`, `h.get('call_amount_bb')`, reconstructed from action_ledger if needed. `pot_validation` = "passed" if action_ledger pot matches parsed pot within 0.5BB |
| `math_facts` | `h.get('required_eq_pct')` from decision_math enrichment. `hero_equity_low/high` from EAI or range-based estimate. `equity_display_mode` = "suppressed" if no range |
| `range_facts` | Showdown data from `h['villains'][v]['shown_cards']` → "showdown" source. GTOW chart data → "chart" source. Line-inferred from villain archetype → "line_inferred". Fallback → `equity_display_mode = "suppressed"` |
| `bounty_facts` | `h.get('bounty_value_bb')`, `h['format'] == 'BOUNTY'`, hero_covers computed from stacks. `bounty_confidence` = "medium" for mystery bounty, "high" for known PKO |
| `icm_context` | `h.get('tournament_phase')` mapped: bubble_zone → bubble, ft_zone → final_table, etc. `pay_jump_pressure` derived from phase + remaining players |
| `satellite_context` | `h['format'] == 'SATELLITE'` check + `h.get('tournament_phase')` for near-seat-bubble detection |
| `villain_reads` | `stats.get('villain_intel', {})` → per-villain evidence_atoms count, read_states for recency/type. `available_before_decision` = True for all programmatic reads (they're computed from prior hands) |
| `blocker_facts` | `enabled: False` in Phase 1 |
| `hero_range_facts` | `enabled: False` in Phase 1 |
| `candidate_alternatives` | Derived from decision_type + existing auto-verdict + detector output. For call spots: call vs fold vs raise. For bet spots: bet vs check. Include `ranking_confidence` |
| `provenance` | `facts_generated_by: "programmatic"`, `facts_version: "v1"` |

#### A2: Quality Gates Derivation

Pure function that takes `decision_facts` and returns `quality_gates` dict + `display_confidence`. These are NEVER stored — always derived.

```python
def derive_quality_gates(facts):
    """Compute quality gates from raw decision_facts.
    Returns (quality_gates: dict, display_confidence: str, suppress_reason: str|None).
    """
```

Gates (11 booleans):
- `numeric_equity_allowed`: equity_display_mode == "numeric" AND range exists AND pot_validation == "passed"
- `range_required_and_present`: at least one range_fact with confidence != "missing"
- `multiway_equity_safe`: players_in_hand_at_decision <= 2 OR equity_model == "multiway"
- `pot_validation_passed`: pot_facts.pot_validation == "passed"
- `bounty_math_safe`: bounty_confidence != "missing" when bounty card attempted
- `villain_read_safe`: evidence_count >= minimum_required AND recency_status != "stale"
- `icm_allows_confident_verdict`: NOT icm_context.suppress_confident_chip_ev_verdict
- `satellite_allows_chip_ev_verdict`: NOT satellite_context.suppress_chip_ev_allin_verdict
- `blocker_commentary_allowed`: blocker_facts.enabled (False in Phase 1)
- `hero_range_commentary_allowed`: hero_range_facts.enabled (False in Phase 1)
- `action_ranking_supported`: candidate_alternatives has >= 2 entries with ranking_confidence >= "medium"

`display_confidence` = weakest relevant input (NOT the EV margin).

#### A3: Template Interpretation

Map `decision_facts` + `quality_gates` → `coaching_interpretation`.

Phase 1 uses templates only (no LLM). One template per card type:

1. **call_math** — HU call/fold with numeric equity
2. **bounty_ev** — bounty-adjusted threshold
3. **bounty_not_collectible** — Hero doesn't cover
4. **multiway_caution** — multiway equity suppressed
5. **icm_caution** — chip-EV suppressed by ICM
6. **satellite_caution** — chip-EV suppressed by satellite bubble
7. **disciplined_fold** — close chip-EV, good fold in context

Each template produces: `poker_verdict`, `headline`, `why`, `learn`, `plan`, `warnings`.

**Wording rules from handoff:**
- No "Freezeout need" → use "Without bounty"
- No "Low confidence" as verdict → use separate confidence chip
- "Call is profitable by price" (soft) vs "Call. Do not raise." (hard, requires action_ranking_supported)
- Bounty-only call must say "Call only because bounty is worth enough"
- Max 9 words headline, 22 words why, 24 words learn, 18 words plan

#### A4: Semantic Assertions

Pure validation functions that run AFTER interpretation, BEFORE display_card building. These are the correctness tests — they catch wrong verdicts.

13 assertion groups (A through M from handoff):
- **A: Numeric equity** — no equity without range, no HU equity as multiway
- **B: Call/fold threshold** — equity vs required_equity consistency
- **C: Action ranking** — "Call. Do not raise." requires candidate_alternatives
- **D: Bounty** — coverage, bands, bounty-only-call wording
- **E: Mistake** — requires recommended != hero_action + supporting facts
- **F: Close/default** — fallback when no stronger verdict passes
- **G: Disciplined fold** — close chip-EV + context justification
- **H: ICM/satellite** — suppression rules, satellite > ICM priority
- **I: Villain exploit** — timing/sample/recency gates
- **J: Mixed action** — strict trigger rules
- **K: Sizing/texture** — requires hero_range or detector support
- **L: Claim reconciliation** — no silent contradiction with existing flags
- **M: Hand narrative** — per-street cards can't contradict

If assertions fail → suppress card or downgrade to close/read_dependent.

#### A5: Display Card Builder

Assemble the final `display_card` dict consumed by the renderer. Max constraints:
- 1 primary card per street (max 2 if second is warning)
- Max 4 metric boxes
- Max 2 range rows
- Max 1 learn line, 1 plan line
- No paragraph over ~24 words

#### A6: Claim Reconciliation + Hand Narrative

- Check new card verdict against existing `report_data['auto_verdicts']`, punt/mistake flags, issue explorer entries
- If conflict: suppress in Phase 1 (prefer suppression over nuanced rewrite)
- Check per-street cards within same hand don't contradict

---

### Phase B: Pipeline Integration

**Where:** `gem_analyzer.py` `__main__` block, AFTER coverage builder returns and BEFORE render.

```python
# After coverage builder
from gem_coaching_cards import build_coaching_cards
coaching_cards = build_coaching_cards(hands, stats, report_data, ranges=ranges)
report_data['coaching_cards'] = coaching_cards
```

**Serialization:** coaching_cards dict gets JSON-serialized into the HTML template alongside existing `report_data` injection.

**In `draft.py`:** Add `coaching_cards` to the JS data payload:

```python
# In the data embedding section
window.coachingCards = {json.dumps(report_data.get('coaching_cards', {}))};
```

---

### Phase C: Renderer — CSS + JS

All changes in `gem_report_draft/_html.py`.

#### C1: CSS — Learn-First Card Styles

Add to the f-string CSS block (doubled braces). Port the styles from the mockup HTML (`hand_commentary_coaching_mockup_v3_learn_first.html`):

- `.coach-stack` — flex column container
- `.learn-card` — base card with variants `.good`, `.warn`, `.bad`, `.blue`
- `.learn-head` — flex header with title + decision chip
- `.learn-title` — bold headline
- `.decision` chip — verdict pill with color variants
- `.answer` — body text
- `.metric-row` — 3-column grid (4-column with `.four`)
- `.metric` — stat box with variants `.money`, `.bad`
- `.range-row` — 3-column grid for range display
- `.range-v`, `.range-text`, `.range-conf` — range sub-elements with confidence colors
- `.learn-line` — bottom learn/plan text
- `.source-line` + `.source-chip` — provenance

All from the mockup — copy verbatim, convert `{}` → `{{}}` for the f-string block.

Mobile responsive rules already in mockup:
- `@media(max-width:900px)` — single column
- `@media(max-width:560px)` — metric grid to 2-col, range to 1-col

#### C2: JS — Coaching Card Renderer

Add to the `_MODAL_HTML` raw string (single braces). New function:

```javascript
function _renderCoachingCard(card) {
    // Renders a single display_card object into DOM elements
    // NO poker math — just reads card fields and builds HTML
    // Returns a DOM element (div.learn-card)
}
```

**Integration point:** In the street commentary section rendering (~L1430-1465), BEFORE existing analyst notes. Check `window.coachingCards[handId]` for cards matching the current street. If found, render the card. Existing analyst notes render below as secondary content.

**Renderer rules (HARD):**
- No poker math
- No inferred missing values
- Output values unchanged from display_card
- May truncate range text visually but preserve full in tooltip
- Does NOT create analytical facts

#### C3: Feedback Metadata Integration

Extend existing verdict chip localStorage to include `card_feedback` fields:
- `card_id`, `card_type`, `generated_by`, `display_confidence`, `facts_version`

When user clicks thumbs-up/down, store alongside existing verdict data.

---

### Phase D: Tests

Add to `_test_scratch.py`. The handoff specifies 33 tests grouped in three categories:

#### D1: Load-Bearing Correctness Tests (15)

```
T-CC-01: No equity without range (numeric equity card has range_facts)
T-CC-02: No HU equity in multiway (players_at_decision > 2 suppresses numeric)
T-CC-03: Heads-up-at-decision exception (multiway start, HU at decision → allowed)
T-CC-04: Pot validation includes antes/dead money
T-CC-05: MTT rake assumption explicit in pot_facts
T-CC-06: Bounty arithmetic sanity (with/without threshold reconciles)
T-CC-07: Bounty confidence bands (medium → band, not crisp point)
T-CC-08: Bounty-only call wording (headline says "bounty" when bounty is the reason)
T-CC-09: Bounty coverage (non-covered villain bounty excluded)
T-CC-10: ICM suppression (bubble all-in → no confident chip-EV verdict)
T-CC-11: Satellite suppression + satellite > ICM priority
T-CC-12: Action-ranking guard ("Call. Do not raise." requires alternatives)
T-CC-13: Symmetric mistake guard (mistake requires better alternative)
T-CC-14: Disciplined fold guard (close chip-EV + context required)
T-CC-15: Renderer purity (display_card values unchanged in output)
```

#### D2: Safety / Anti-Hallucination Tests (9)

```
T-CC-16: No blocker wording if blocker_facts disabled
T-CC-17: No Hero-range wording if hero_range_facts disabled
T-CC-18: Villain read timing guard (unavailable before decision → excluded)
T-CC-19: Villain read sample/recency gate (stale/under-sampled → no exploit)
T-CC-20: Claim reconciliation (new verdict doesn't contradict existing flags)
T-CC-21: Hand narrative suppression (per-street cards don't contradict)
T-CC-22: Mixed-card noise guard (pair+draw alone → no mixed card)
T-CC-23: Sizing-card guard (no hero_range → no sizing card)
T-CC-24: Dedup (same lesson_type max once per hand)
```

#### D3: UI / Regression Tests (9)

```
T-CC-25: Existing action display still works
T-CC-26: Existing villain badges still work
T-CC-27: Existing thumbs-up/down still work
T-CC-28: Existing GTOW button still works
T-CC-29: Existing copy/reset notes still work
T-CC-30: Existing analyst notes still render
T-CC-31: Mobile range text doesn't break layout (max-width + ellipsis)
T-CC-32: Max card/length limits enforced (1 primary + 1 warning max)
T-CC-33: Feedback metadata stores card_type, generated_by, display_confidence, facts_version
```

**Test approach:** Tests T-CC-01 through T-CC-24 can be pure Python unit tests against `gem_coaching_cards.py` — construct synthetic `decision_facts` dicts and verify assertion/gate/card output. Tests T-CC-25 through T-CC-33 are source-pattern tests (verify CSS classes, JS functions exist in `_html.py`).

---

### Phase E: Version Bump + Verification

- Bump VERSION to v8.10.0 in `draft.py`
- Add `gem_coaching_cards.py` to `verify_release.py` manifest
- Add Phase 1 canaries: `build_coaching_cards` in gem_coaching_cards.py, `coaching_cards` in gem_analyzer.py, `_renderCoachingCard` in _html.py, `.learn-card` in _html.py
- Update changelog, version tests, hashes
- Run full test suite + verify_release

---

## Execution Order

```
1. Phase A1-A2: decision_facts builder + quality gates  → py_compile
2. Phase A3:    template interpretation (7 card types)   → py_compile
3. Phase A4:    semantic assertions (13 groups)           → py_compile + unit tests
4. Phase A5-A6: display_card builder + reconciliation     → py_compile
5. Phase B:     pipeline integration                      → py_compile + smoke test
6. Phase C1:    CSS (port from mockup)                    → py_compile
7. Phase C2:    JS renderer                               → py_compile
8. Phase C3:    feedback metadata                         → py_compile
9. Phase D:     all 33 tests                              → full test run
10. Phase E:    version bump + verify_release             → final verification
```

---

## Existing Data Availability Assessment

| Data needed by coaching cards | Available now? | Source | Quality |
|-------------------------------|----------------|--------|---------|
| Pot size / call amount | YES | action_ledger, decision_math enrichment | High |
| Required equity % | YES | `h.get('required_eq_pct')` | High for HU calls |
| Hero equity | PARTIAL | EAI for all-ins only; no general range-vs-range | EAI only |
| Villain range | PARTIAL | Showdown data for shown hands; GTOW chart for standard spots | Medium |
| Line-inferred range | NO | Not currently produced | Stub with "suppressed" |
| Bounty value | YES | `h['bounty_value_bb']`, format detection | Medium (mystery = banded) |
| Hero covers villain | DERIVABLE | Compare stack sizes | High |
| Tournament phase | YES | `h['tournament_phase']` | Medium |
| Satellite detection | YES | `h['format'] == 'SATELLITE'` | High |
| Villain profile/archetype | YES | `stats['opponent_profiles']` | Medium |
| Villain evidence count | YES | `stats['villain_intel']['evidence_atoms']` | High |
| Read recency | PARTIAL | Evidence is session-scoped, not cross-session | All "fresh" within session |
| Board texture | YES | `h['board_texture']`, `classify_board()` | High |
| Draw profile | YES | `h.get('draw_profile')` from gem_made_hands | High |
| Existing auto-verdicts | YES | `report_data['auto_verdicts']` | High |
| Existing punt/mistake flags | YES | `stats['punts']`, `stats['mistakes']` | High |
| Blocker analysis | NO | Deferred to Phase 2 | N/A |
| Hero perceived range | NO | Deferred to Phase 2 | N/A |

**Key gap:** General range-vs-range equity (not all-in) doesn't exist yet. Phase 1 will show numeric equity only for EAI all-in spots and suppress it everywhere else. This means most postflop call cards will use `equity_display_mode = "qualitative"` or `"suppressed"` rather than numeric. This is conservative by design.

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Confidently wrong bounty math | Bounty confidence bands + bounty-only-call explicit wording |
| HU equity shown in multiway | Assertion A prevents this; `players_at_decision > 2` → suppressed |
| Missing range but equity shown | Assertion A hard invariant: no numeric equity without range |
| ICM pressure ignored | ICM caution card fires on bubble/FT; suppresses chip-EV verdicts |
| Satellite survival ignored | Satellite caution overrides ICM; suppresses all-in chip-EV |
| Stale/thin villain reads | Sample size + recency gate; under-threshold → watch note only |
| Contradicting existing verdicts | Claim reconciliation pass; Phase 1 prefers suppression |
| Too many cards / noise | Max 1 primary per street; importance gating; strict trigger rules |
| Renderer doing poker math | Hard rule tested by T-CC-15; renderer reads display_card only |

---

## Files Created / Modified

| File | Action | Size Estimate |
|------|--------|---------------|
| `gem_coaching_cards.py` | **NEW** | ~800-1200 lines |
| `gem_analyzer.py` | MODIFY | +10 lines (import + call + data injection) |
| `gem_report_draft/draft.py` | MODIFY | +5 lines (serialize coaching_cards to JS) |
| `gem_report_draft/_html.py` | MODIFY | +200 lines CSS, +150 lines JS |
| `_test_scratch.py` | MODIFY | +33 tests (~500 lines) |
| `verify_release.py` | MODIFY | manifest + canaries + version |
| `GEM_Changelog.txt` | MODIFY | v8.10.0 entry |

---

## Success Criteria

A user opening a hand detail should understand in under ~10 seconds:
1. What the recommended action was, if safely known
2. Why
3. What villain range was assumed, if equity is shown
4. Whether bounty/ICM/satellite/villain context changes the decision
5. What reusable rule applies next time

**The system should prefer no card over a confident-looking weak card.**

---

## What NOT to Do

- No LLM enrichment (Phase 2)
- No blocker commentary (Phase 2)
- No Hero-range/cappedness commentary (Phase 2)
- No full mixed-action engine (Phase 2)
- No full sizing/texture engine (Phase 2)
- No advanced ICM solver (Phase 2)
- No multiway equity model (Phase 2)
- No nuanced hand-narrative bridge wording (Phase 2)
- No large modal redesign
- No changes to action rendering, card rendering, GTOW button, copy/reset notes, villain badges, or existing analyst notes EXCEPT where needed to display the new card
