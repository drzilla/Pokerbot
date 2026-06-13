# GEM Pipeline — Complete Technical Specification v2

Generated 2026-06-03, revised after GPT architecture review.
This is the implementation-ready spec for all 44 items across 6 batches.
Covers data structures, navigation, analyst workflow, and every dimension.

**v2 changes (GPT review):**
1. decision_points[] extracted IMMEDIATELY after parsing (before detectors)
2. Pot-odds schema expanded for non-call actions (bet/raise/jam/check/fold)
3. facing_villain uses name reference + snapshot (not full duplication)
4. IP/OOP expanded for multiway (ip/oop/middle/multiway_unclear)
5. EAI renamed: Fast Exact Equity vs Slow Equity Backfill
6. Test gates behavioral (not grep-based)
7. Candidate coverage categories split (exact vs range equity)
8. Renderer adapter layer added

---

## Part 1: Analytical Dimensions

Every hand exists in multiple analytical dimensions simultaneously. A single
hand might be: a preflop cold-call mistake (action dimension), from the SB
(position dimension), at 25BB effective (stack dimension), on a dry A-high
flop (board dimension), in a bounty tournament near the bubble (tournament
dimension), against a calling station (villain dimension), where Hero had
45% equity but needed 38% (math dimension).

The pipeline must track all these dimensions and cross-reference them.

### 1.1 The Seven Analytical Axes

| Axis | What it answers | Key fields | Level |
|------|----------------|-----------|-------|
| **Position** | Where was Hero relative to the action? | position, hero_ip, eff_pos | Per-hand |
| **Stack depth** | How deep were the effective stacks? | eff_stack_bb_at_decision, spr | Per-decision |
| **Action sequence** | What line did Hero take? | action_ledger, line_actions, hero_street_actions | Per-street |
| **Board** | What community cards and texture? | board, board_texture, board_archetype | Per-street |
| **Opponent** | Who was Hero playing against? | villains, primary_villain, archetype | Per-hand |
| **Tournament** | What was the tournament context? | tournament_phase, format, buyin, level | Per-hand |
| **Math** | Was the play +EV or -EV? | required_equity, hero_equity, ev_call_bb | Per-decision |

Every metric, every leak, every drill-down should be sliceable by these 7 axes.

### 1.2 Dimension Hierarchy

```
SESSION (all hands)
  |
  +-- TOURNAMENT (per tournament)
  |     |
  |     +-- PHASE (early / middle / late / bubble / FT)
  |           |
  |           +-- HAND (single hand)
  |                 |
  |                 +-- STREET (preflop / flop / turn / river)
  |                       |
  |                       +-- DECISION POINT (Hero's action)
  |                             |
  |                             +-- MATH (pot odds, equity, EV)
  |                             +-- OPPONENT (who, archetype, range)
  |                             +-- BOARD STATE (texture, draws, outs)
```

The `decision_point` is the atomic unit. Everything rolls up from there.

---

## Part 2: Data Structures

### 2.1 The Decision Point (central object)

Every Hero action that involves a strategic choice is a decision point.
A single hand may have 1-4 decision points.

```python
decision_point = {
    # ===== IDENTITY (set by Decision Point Extractor, Stage 2) =====
    'id': 'TM5936548038_preflop_call_001',  # hand_id + street + action + seq
    'hand_id': 'TM5936548038',
    'street': 'preflop',                     # preflop / flop / turn / river
    'action_index': 3,                       # index in action_ledger
    'is_key_decision': True,                 # the one used for the hand verdict

    # ===== HERO ACTION (set by Extractor) =====
    'hero_action': 'call',                   # call / raise / bet / check / fold / jam
    'hero_amount_bb': 8.0,
    'hero_action_class': 'cold_call',        # semantic: cold_call / 3bet / cbet / barrel /
                                             #   check_raise / probe / value_bet / bluff /
                                             #   jam / fold_to_bet / check_back / defend

    # ===== POSITION CONTEXT (set by Extractor) =====
    'hero_position': 'SB',
    'position_relative': 'oop',              # ip / oop / middle / multiway_unclear
    'players_left_to_act': 2,                # after Hero at THIS decision
    'hero_is_pfr': False,                    # was Hero the preflop raiser?
    'hero_is_last_aggressor': False,          # was Hero the last to bet/raise?
    'last_aggressor': 'Player_c81d',         # who was?
    'eff_stack_bb': 25.3,                    # effective at THIS decision
    'spr': None,                             # stack-to-pot ratio (postflop only)
    'players_in_hand': 3,                    # at this street

    # ===== OPPONENT CONTEXT (set by Extractor, enriched by Analyzer) =====
    # Reference-based: renderer resolves full data via hand['villains'][name]
    'facing_villain_name': 'Player_c81d',    # key into hand['villains']
    'facing_villain_role': 'opener',         # opener / bettor / raiser / jammer / squeezer / checker
    'facing_villain_snapshot': {             # facts at THIS exact decision moment
        'position': 'BTN',
        'stack_bb': 34.5,
    },

    # ===== BOARD CONTEXT (postflop only, set by Extractor) =====
    'board': ['Ah', '7d', '2c'],
    'board_texture': 'dry_ahigh',
    'board_archetype': 'A-high rainbow',
    'draw_profile': {
        'flush_draw': False,
        'straight_draw': False,
        'gutshot': True,
        'overcards': 1,
        'made_hand': 'high_card',
        'hand_strength_rank': 7,             # 1=nuts, 10=air
        'summary': 'gutshot, 1 overcard',
    },

    # ===== MATH (set by Auto-Coach Engine, Stage 7) =====
    # math_type determines which fields are populated:
    'math_type': 'facing_bet',               # facing_bet / hero_bet / hero_raise /
                                             #   hero_jam / check_or_bet / fold_vs_bet

    # -- FACING BET / CALL MATH (when math_type == 'facing_bet') --
    'pot_before_villain_bet_bb': 3.5,
    'villain_bet_bb': 8.0,
    'pot_facing_hero_bb': 11.5,              # what Hero sees
    'hero_call_amount_bb': 8.0,              # what Hero must put in
    'final_pot_if_call_bb': 19.5,            # total if Hero calls
    'required_equity': 0.41,                 # hero_call / final_pot (break-even %)
    'hero_equity_vs_range': 0.35,            # estimated (0-1)
    'equity_source': 'range_estimate',       # exact_shown / mc / range_estimate / none
    'ev_call_bb': -1.2,                      # hero_eq * final_pot - hero_call

    # -- HERO BET / BLUFF MATH (when math_type == 'hero_bet') --
    'risk_bb': None,                         # what Hero risks (bet size)
    'reward_bb': None,                       # what Hero wins if villain folds (pot)
    'fold_equity_required': None,            # breakeven fold frequency
    'estimated_fold_equity': None,           # estimated villain fold %
    'ev_bet_bb': None,                       # fold_eq * reward - (1-fold_eq) * risk (simplified)

    # -- HERO JAM MATH (when math_type == 'hero_jam') --
    'hero_risk_bb': None,                    # Hero's total risk (stack)
    'pot_before_jam_bb': None,
    'equity_when_called': None,              # Hero's equity if villain calls
    'ev_jam_bb': None,                       # fold_eq * pot + (1-fold_eq)(eq * final_pot - risk)

    # -- CHECK VS BET (when math_type == 'check_or_bet') --
    'ev_check_bb': None,                     # estimated EV of checking
    'ev_bet_bb': None,                       # estimated EV of betting
    'preferred_action': None,                # 'bet' or 'check'

    # ===== COACHING FIELDS (set by Auto-Coach, Stage 7) =====
    'correct_action': '3bet_or_fold',
    'correct_size_bb': 8.5,                  # None if not a sizing issue
    'minimum_continue_hand': 'AJs / 99+',
    'threshold_explanation': 'ATo below call threshold vs 12BB HJ jam',
    'memory_rule': 'SB vs BTN/CO at 20-40BB = 3-bet or fold.',
    'exception': 'Flat only with specific exploit/read, not default.',
    'drill_bucket': 'sb_cold_call_violation',

    # ===== LEAK LINKAGE (set by Detectors, Stage 3) =====
    'leak_code': 'Cold_Call_NB',             # maps to watchlist metric
    'detector_name': 'missed_3bet_sb',
    'detector_confidence': 'CLEAR',

    # ===== CLASSIFICATION (set by Detectors + Prefill) =====
    'is_mistake': True,
    'mistake_type': 'cold_call_oop',
    'ev_lost_bb': 2.4,

    # ===== ROOT MISTAKE TRACKING (set by Auto-Coach) =====
    'is_root_mistake': True,                 # FIRST error in the hand?
    'downstream_of': None,                   # or 'preflop_call_001'

    # ===== CONFIDENCE (set by Detectors, refined by Auto-Coach) =====
    'confidence': 'HIGH',
    'risk_flags': [],                        # ['unknown_villain_range', 'multiway', etc.]
    'needs_review': False,

    # ===== CONTEXT (set by Auto-Coach) =====
    'population_note': None,                 # 'Pool underfolds to 3-bets here'
    'villain_specific_note': None,           # 'This villain is LAG — 3-bet wider'
    'icm_context': {
        'near_bubble': False,
        'final_table': False,
        'satellite': False,
        'bounty_covers_villain': True,
        'hero_covered': False,
        'stack_utility': 'medium',
        'icm_flag': None,
    },
}
```

**math_type routing:** The renderer checks `math_type` and displays only
the relevant fields. A bet decision shows fold_equity_required, not
required_equity (which is for calls). A jam shows equity_when_called.
A check-vs-bet shows both EVs side by side.

### 2.2 Hand-Level Structure (enhanced)

```python
hand = {
    # === PARSER-OWNED (Stage 1) ===
    # Identity
    'id': 'TM5936548038',
    'date': '2026-04-22',
    'tournament': '$5.50 Satellite to 55...',
    'tournament_id': '123456789',
    'format': 'BOUNTY',
    'buyin': 5.50,
    'game_type': 'NLH',                      # NEW: NLH / PLO / PLO5 / ShortDeck
    'disconnected': False,                    # NEW: timeout/disconnect detection

    # Table state
    'table_size': 8,
    'n_players': 7,
    'level': 12,
    'sb_blind': 0.5,
    'bb_blind': 1.0,
    'ante': 0.125,

    # Hero
    'hero': 'lanks662',
    'cards': ['As', 'Td'],
    'position': 'SB',
    'eff_pos': 6,
    'hero_ip': False,
    'stack_bb': 54.3,
    'eff_stack_bb': 34.9,
    'eff_stack_bb_at_decision': 34.9,

    # Villains
    'villains': {
        'Player_c81d': {
            'position': 'BTN',
            'stack_bb': 34.5,
            'shown_cards': ['Kh', 'Kd'],     # only if shown at SD
            'archetype': 'LAG',
            'archetype_label': 'Loose Aggressive',
            'archetype_reason': 'VPIP 38 / PFR 28 / AF 3.2',
            'exploit_note': 'Overbluffs rivers',
        },
    },
    'seat_stacks_bb_all': {'BTN': 34.5, 'SB': 54.3, 'BB': 22.1, ...},

    # Actions (canonical)
    'action_ledger': [
        {'street': 'preflop', 'player': 'Player_c81d', 'position': 'BTN',
         'action': 'raises', 'amount_bb': 2.5, 'is_all_in': False, 'stack_bb': 34.5},
        {'street': 'preflop', 'player': 'lanks662', 'position': 'SB',
         'action': 'calls', 'amount_bb': 2.5, 'is_all_in': False, 'stack_bb': 54.3,
         'is_hero': True},
        ...
    ],
    'pot_ledger': {'main': 8.5, 'side_pots': []},

    # Board
    'board': ['Ah', '7d', '2c', '5h', '9s'],
    'board_texture': 'dry_ahigh',
    'board_archetype': 'A-high rainbow',

    # Classification flags (100+ boolean flags from parser)
    'vpip': True, 'pfr': False, 'cold_called': True,
    'hero_cbet_flop': False, 'went_to_sd': True,
    ...

    # Outcome
    'net_bb': -25.3,
    'won': False,
    'hand_strength': 'high_card',

    # Tournament context
    'tournament_phase': 'middle',

    # === ANALYZER-OWNED (Stage 2+) ===
    'primary_villain': {                      # NEW: who the key decision was against
        'name': 'Player_c81d',
        'position': 'BTN',
        'stack_bb': 34.5,
        'archetype': 'LAG',
    },

    'decision_points': [                      # NEW: multi-decision per hand
        { ... decision_point dict ... },
        { ... decision_point dict ... },
    ],
    'key_decision_id': 'TM5936548038_preflop_call_001',

    # Variance classification (analyzer)
    'variance_outcome': 'top_of_range',       # suckout / lost_flip / top_of_range / semi_bluff

    # EAI equity (Stage 3)
    'eai': {
        'hero_equity': 0.35,
        'is_favorite': False,
        'suckout': None,
        'method': 'exact',
        'n_allin': 2,
    },

    # Coaching flags (Stage 5)
    'coaching_flags': ['MW_SMALL_SIZING'],

    # Analysis confidence (new)
    'analysis_confidence': {
        'label': 'III.2 Mistake',
        'confidence': 'HIGH',
        'reason_source': 'detector+pot_odds',
        'needs_review': False,
        'risk_flags': ['unknown_villain_range'],
        'review_tier': 'auto_preflop',        # reviewed / auto_equity / auto_preflop / auto_small
    },
}
```

### 2.3 Street-Level Structure

Each street within a hand carries:

```python
street_context = {
    'street': 'flop',
    'board_cards': ['Ah', '7d', '2c'],
    'board_texture': 'dry_ahigh',
    'pot_at_start_bb': 5.5,
    'pot_at_end_bb': 18.0,
    'players_at_start': 3,
    'players_at_end': 2,
    'hero_ip': False,

    # Hero's draw profile at this street
    'draw_profile': {
        'flush_draw': False,
        'straight_draw': False,
        'gutshot': True,
        'overcards': 1,
        'made_hand': 'high_card',
        'hand_strength_rank': 7,             # 1=nuts, 10=air
        'summary': 'gutshot, 1 overcard',
    },

    # Actions on this street
    'actions': [
        {'player': 'Hero', 'action': 'check', 'amount_bb': 0},
        {'player': 'Villain', 'action': 'bets', 'amount_bb': 3.5},
        {'player': 'Hero', 'action': 'calls', 'amount_bb': 3.5},
    ],

    # Decision point(s) on this street
    'decision_point_ids': ['TM5936548038_flop_call_001'],
}
```

### 2.4 Action-Level Structure

Each individual action within the action_ledger:

```python
action_entry = {
    'street': 'flop',
    'player': 'lanks662',
    'position': 'SB',
    'action': 'calls',                       # folds/checks/calls/bets/raises/posts
    'amount_bb': 3.5,
    'is_all_in': False,
    'is_hero': True,
    'stack_bb': 51.8,                        # stack BEFORE this action
    'stack_after_bb': 48.3,                  # stack AFTER
    'pot_before_bb': 9.0,                    # pot before this action
    'pot_after_bb': 12.5,                    # pot after
    'sizing_pct': 38.9,                      # as % of pot (for bets/raises)

    # Decision-point linkage (if this is a Hero strategic decision)
    'decision_point_id': 'TM5936548038_flop_call_001',
}
```

---

## Part 3: Pipeline Flow (corrected two-pass architecture)

```
[1] PARSER
    Input:  Raw HH text files
    Output: hand[] with 176+ fields per hand
    Gate:   Parser QA (pot balance, impossible stacks, game-type detect)
    ALL hands processed. Duplicates removed. Disconnections flagged.
    Game type set (NLH/PLO/ShortDeck). PLO quarantined.

[2] DECISION POINT EXTRACTOR (NEW — runs immediately after parser)
    Input:  Parsed hands with action_ledger
    Output: hand['decision_points'] with identity + position + board fields
    EVERY hand gets decision_points[]. This runs BEFORE detectors.
    Sets: id, street, action_index, hero_action, hero_action_class,
          position_relative, players_left_to_act, eff_stack_bb, spr,
          facing_villain_name/role/snapshot, board context, draw_profile.
    Math fields and coaching fields are LEFT EMPTY (filled later).
    Why early: detectors, candidates, equity all attach to dp IDs.

[3] DETECTORS (attach flags to decision_point IDs)
    Input:  All parsed hands WITH decision_points
    Output: stats['mistakes'], stats['punts'], stats['coolers']
    Each detector flag includes the decision_point_id it applies to.
    Gate:   Analyzer QA (formula checks, no cooler+punt overlap)
    NLH-only: PLO/ShortDeck hands skip all NLH detectors.

[4] FAST EXACT EQUITY (was "EAI equity")
    Input:  Showdown all-in hands with shown villain cards
    Output: hero_equity, is_favorite, suckout per hand
    Method: exact enumeration (postflop) or fixed-seed MC (preflop)
    Coverage: ~10-15% of hands. Fast. Always runs.

[5] VARIANCE CLASSIFIER
    Input:  All-in hands with exact equity
    Output: variance_outcome per hand (suckout/flip/top_of_range/semi_bluff)

[6] COACHING RULES
    Input:  All NLH hands
    Output: coaching_flags[] per hand, attached to decision_point IDs
    5 rules. Session-wide pattern checks.

[7] INITIAL CANDIDATE BUILDER
    Input:  Detector output + exact equity + variance + coaching flags
    Output: candidate_set (typed buckets)
    Sources: mistakes, punts, coolers, bust_audit, iii4_screening,
             read_dependent, bestplay, stratified blindspot strata
    Gate:   candidate_definition coverage check
    Candidates already HAVE decision_points (from Stage 2).

[8] AUTO-COACH ENGINE (enriches existing decision_points)
    Input:  Each candidate hand's decision_points[]
    Output: Fills the EMPTY math + coaching fields:
      - Pot-odds math (math_type-appropriate fields)
      - Range-based equity estimation (for non-showdown candidates)
      - correct_action + minimum_continue_hand + memory_rule
      - leak_code linkage + drill_bucket assignment
      - root_mistake attribution (is_root_mistake, downstream_of)
      - population exploit note + ICM/bounty flags
    Gate:   >= 95% of candidates have math fields populated

[9] CANDIDATE RE-RANKER
    Input:  Enriched candidates
    Output: Priority-ranked + rep/boundary/counter selection
    Ranking: ev_lost_bb x recurrence x confidence x future_frequency

[10] PREFILL VERDICTS
    Input:  Ranked candidates with enriched decision_points
    Output: Suggested verdict per hand (HIGH/MEDIUM/empty)
    Reads from decision_points math for all arguments.

[11] CANDIDATE + TEMPLATE EMISSION
    Output: analyst_candidates.json + session_analysis_TEMPLATE.json
    MUST happen BEFORE slow equity (Stage 12).
    All buckets + all sources in one union file.

[12] SLOW EQUITY BACKFILL (optional, may timeout)
    Backfills deeper range equity / MC into existing candidates.
    If timeout → candidates already written. No data lost.
    --equity-timeout flag for graceful degradation.
    Separate from Fast Exact Equity — different scope and urgency.

[13] ANALYST STEP
    Input:  Candidate file + template
    Output: session_analysis_<date>.json with verdicts + arguments
    Analyst confirms/overrides prefill, writes arguments for
    MEDIUM/blank hands, clears false positives, adds new hands.

[14] POST-ANALYST REFRESH
    Merges analyst verdicts → recomputes discipline tier.
    All surfaces read from single canonical source.

[15] REPORT RENDER (via adapter layer)
    Reads: stats + rd + analyst_commentary via adapter helpers
    Renders: 14 sections, appendix cards, popups, drills
    Gate: render QA (orphan links, count consistency, 0BB check)
```

**Key architectural change:** Decision Point Extractor (Stage 2) runs
IMMEDIATELY after parsing. This means detectors (Stage 3) can attach their
flags directly to decision_point IDs. No re-mapping needed later.

**Consequence:** Every hand has `decision_points[]` from the start. The
identity/position/board fields are populated by the extractor. The math
and coaching fields start as `None` and are filled by the Auto-Coach
Engine (Stage 8) only for CANDIDATE hands.

---

## Part 4: Navigation Architecture

### 4.1 User Navigation Paths

The report has 3 navigation entry points:

**Path 1: Top-down (TL;DR → drill into problems)**
```
TL;DR Dashboard
  → Coach Watchlist card (top 4 red metrics)
    → Click metric name → section with breakdown + hand popups
      → Click hand count → popup table with 5-20 hands
        → Click hand → appendix card with full grid + coaching box
```

**Path 2: Metric-driven (Watchlist → why am I off?)**
```
S6.0 Metric Watchlist (all 20 metrics, color-coded)
  → Click red metric → target section (e.g., sec-8-1 Position Analysis)
    → Per-position/per-opener breakdown tables
      → Click count cell → hand-list popup
        → Click hand → appendix card
```

**Path 3: Hand-driven (browse hands → understand each one)**
```
S7.5 Hands to Open First (priority queue)
  → Click hand → appendix card
    → Read coaching box (mistake + correct action + threshold + drill)
    → Click drill bucket → GTOW drill scenario
```

**Path 4: Leak-driven (S3 promoted leaks → examples → drill)**
```
S3 Strategic Leaks
  → Click leak name → popup with candidate hands
    → See 3 groups: Clean mistake / Boundary / Counterexample
      → Click hand → appendix card
  → Decision tree for this leak type
  → EV impact: "-42 BB estimated / 37 spots / recurring"
```

### 4.2 Section Navigation Map

```
DASHBOARD (TL;DR)
  |
  +-- S1 Reality Check (variance vs skill)
  |     +-- S1.0 Skill Index, S1.0b Daily Summary
  |     +-- S1.1 Per-Tournament P&L (with Why narrative)
  |     +-- S1.1a Full Result Attribution
  |     +-- S1.3 Large-Loss Audit
  |     +-- S1.4 All-Ins (quality check, suckout ledger)
  |     +-- S1.5-S1.9 Card quality, phases, arc
  |
  +-- S2 Strategic Evaluation (error taxonomy)
  |     +-- S2.1 Punts (III.1)
  |     +-- S2.2 Confirmed Mistakes (III.2)
  |
  +-- S3 Strategic Leaks (promoted, with EV ranking)
  |
  +-- S5 Action Card
  |     +-- S5.1 Promoted Leaks summary
  |     +-- S5.2 Top Drills (auto-generated GTOW)
  |     +-- S5.3 GTO Wizard Shortlist
  |     +-- S5.6 Solver Confirmation Pass
  |     +-- S5.8 Opponent Archetype Mirror
  |
  +-- S6 Session Verdict & KPIs
  |     +-- S6.0 Metric Watchlist (20 metrics, linked)
  |     +-- S6.1 Heuristic Cheat Sheet
  |     +-- S6.2 Top-Line KPIs
  |
  +-- S7 Coach
  |     +-- S7.1 Mental Game
  |     +-- S7.2 Bluff Profile
  |     +-- S7.3 Jasper-5 Exploits
  |
  +-- S8 Pre-Flop Engine
  |     +-- S8.1 Position Matrix (VPIP/PFR by pos) ← VPIP, PFR, ATS link here
  |     +-- S8.2 Preflop Deviations
  |     +-- S8.3 Blind Combat ← BB iso link here
  |     +-- S8.4 3-Bet Profile ← Cold-call link here
  |     +-- S8.5 Squeeze ← 3-Bet OOP link here
  |     +-- S8.6 4-Bet ← Hero 4-bet link here
  |
  +-- S9 Post-Flop SRP
  |     +-- S9.1 C-Bet (with board-texture matrix) ← CBet links here
  |     +-- S9.2 CBet 3BP ← CBet 3BP link here
  |     +-- S9.3 Check-Raise
  |     +-- S9.4 BB Lead / Donk
  |
  +-- S10 Post-Flop 3BP/4BP
  |
  +-- S11 Macro Post-Flop
  |     +-- S11.2 Sizing Profile
  |     +-- S11.5 Bluff Profile ← Pure/Semi bluff link here
  |     +-- S11.7 Check-Raise Frequency ← CR link here
  |     +-- S11.10 AF Breakdown ← Agg delta link here
  |     +-- S11.11 Bet/Check Decision ← AF link here
  |
  +-- S12 Leak Persistence
  +-- S17 Full Deviation Lists
  +-- S18 Appendix (hand detail cards)
```

### 4.3 Hand Detail Card Layout (the appendix card)

Each card is an `<article class="hand-detail-card">` with:

```
+------------------------------------------------------------------+
| HAND TM5936548038 — As Td (SB 54BB) · -25.3 BB                  |
| $5.50 Satellite · 2026-04-22 · Middle phase                     |
+------------------------------------------------------------------+
| PRE-FLOP (OOP)          | FLOP (OOP)              | TURN        |
| 5.5 BB pot              | Ah 7d 2c                | 5h          |
|                          | Dry A-High              |             |
|                          | 12.5 BB pot             | 18.0 BB pot |
|--------------------------|-------------------------|-------------|
| BTN(35BB) Raise 2.5BB   | Hero Check              | Hero Check  |
| Hero Call 2.5BB          | BTN Bet 3.5BB (38%)     | BTN Bet 8BB |
|   need 33%               |   Hero Call 3.5BB       |   Hero Fold |
| BB Fold                  |     need 28%            |             |
+------------------------------------------------------------------+
| Hero result: -25.3 BB · Lost at showdown                         |
| All-in equity: 35% (underdog) · 🤢 got unlucky                  |
| Villain: BTN LAG — Overbluffs rivers, underfolds to 3-bets      |
| Showdown vs BTN: Kh Kd (overpair)                               |
+------------------------------------------------------------------+
| COACHING BOX                                                     |
| MISTAKE: Called SB vs BTN open with ATo at 25BB — cold call OOP  |
| WHY WRONG: Need 33% equity, have ~28% vs BTN range. -EV by 1.2BB|
| CORRECT ACTION: 3-bet to 7.5BB or fold.                          |
| THRESHOLD: Min continue: AJs / 99+. ATo is below threshold.     |
| MEMORY RULE: SB vs BTN/CO at 20-40BB = 3-bet or fold.           |
| DRILL: sb_cold_call_violation                                    |
+------------------------------------------------------------------+
| ANALYST VERDICT: III.2 Mistake (HIGH confidence)                 |
| "TL;DR: Cold-call leak in SB. Population 3-bets wider here.     |
|  Action committed Hero OOP with dominated range..."              |
+------------------------------------------------------------------+
```

### 4.4 Popup Hand-List Table Layout

When clicking any count or hand-list trigger:

```
+---------------------------------------------------------------+
| Cold calls from CO (14 hands)                                  |
+---------------------------------------------------------------+
| Hand     | Cards  | Position | Net BB | Verdict               |
|----------|--------|----------|--------|-----------------------|
| 59205050 | AhTd   | CO       | -8.3   | III.2 Mistake         |
| 29103480 | KsQd   | CO       | +12.1  | III.3 Cleared         |
| ...      |        |          |        |                       |
| (only 4 this session)                                          |
+---------------------------------------------------------------+
```

If < 5 hands: shows "only N this session" marker.
If 0 renderable: never happens (DEFECT 2 guarantee).

---

## Part 5: What Goes to the Analyst

### 5.1 The Candidate File

```json
{
  "session_date": "2026-04-22",
  "player": "lanks662",
  "total_hands": 6176,
  "candidate_count": 487,
  "coverage": {
    "with_decision_points": 463,
    "with_pot_odds_math": 441,
    "with_exact_equity": 106,             // shown cards, exact or fast MC
    "with_range_equity": 335,             // estimated vs constructed range
    "with_coaching_box": 389,             // correct_action + memory_rule populated
    "with_full_coaching_box": 247         // all fields incl threshold + drill
  },

  "buckets": {
    "bust_audit": [
      {
        "id": "TM5936548038",
        "bucket": "bust_audit",
        "priority": 85,
        "prefill_verdict": "I.7 Cooler",
        "prefill_confidence": "MEDIUM",
        "decision_points": [ ... ],
        "context": { ... 55 fields ... },
        "auto_coach": {
          "correct_action": null,
          "root_mistake_street": "preflop",
          "ev_lost_bb": 25.3,
          "minimum_continue_hand": null,
          "drill_bucket": null,
          "risk_flags": ["top_of_range", "unknown_villain_range"]
        }
      }
    ],
    "mistakes": [ ... ],
    "punts": [ ... ],
    "coolers": [ ... ],
    "iii4_screening": [ ... ],
    "read_dependent_screening": [ ... ],
    "bestplay_screening": [ ... ],
    "blindspot_strata": [ ... ]
  },

  "leak_summary": {
    "Cold_Call_NB": {
      "status": "red",
      "value": 10.4,
      "target": "<=6.5",
      "ev_impact_bb": -42,
      "hand_count": 37,
      "breakdown": {
        "by_position": {"CO": 14, "BTN": 8, "HJ": 6, "MP": 5, "SB": 4},
        "by_stack_depth": {"<20BB": 12, "20-40BB": 18, "40+BB": 7}
      },
      "representative_hands": {
        "clean_mistake": "TM5936548038",
        "boundary": "TM5890289704",
        "counterexample": "TM5970611557"
      }
    }
  }
}
```

### 5.2 What the Analyst Must Provide

**Per hand (required):**
```json
{
  "verdict": "III.2 Mistake",
  "confidence": "HIGH"
}
```

**Per hand (optional but high-value):**
```json
{
  "argument": "TL;DR: Cold-call leak...\n### PRICE -> REQUIRED EQUITY\n...",
  "outcome": "variance",
  "correct_action": "3bet_to_8bb",
  "label": "SB cold-call OOP",
  "spot": "SB vs BTN open, 25BB eff"
}
```

**Session-level (optional):**
```json
{
  "__synthesis__": {
    "headline": "Passive preflop leaks in blind positions",
    "session_read": "Full narrative...",
    "session_interpretation": {
      "attribution_guide": "Surface -108% but implied +1.2%...",
      "key_takeaway": "Cold-calling is the #1 leak by EV"
    }
  }
}
```

### 5.3 What Automation Handles vs What Analyst Decides

| Decision | Automated? | Analyst? | Notes |
|----------|-----------|----------|-------|
| Was this hand a mistake? | Detectors flag it | Confirms or clears | Detectors have ~80% precision |
| What was the correct play? | Auto-coach computes for preflop | Writes for postflop | Preflop ranges are mechanical; postflop needs judgment |
| What's the minimum hand? | Range lookup | Confirms boundary | Preflop only; postflop thresholds need range construction |
| Is this an exploit or a leak? | Population heuristic | Decides per villain | Automation says "pool does X"; analyst says "this villain does Y" |
| What's the memory rule? | Template per leak type | Customizes to player | Generic rules automated; player-specific rules need coach |
| What's the root mistake? | decision_points[0] if preflop | Traces multi-street | Preflop mistakes obvious; "flop SPR committed Hero" needs judgment |
| Is this ICM-correct? | Rough flags | Assesses pay jumps | Automation flags bubble; analyst weighs chip utility |
| What drill should I run? | drill_bucket auto-assigned | Selects from GTOW | Bucket is automated; specific scenario selection is manual |
| Session narrative | Not automated | Writes synthesis | Requires coaching judgment across 50+ data points |

---

## Part 6: Metric Drilldown Dimensions (the "Why am I off?" spec)

Each red/amber watchlist metric needs specific breakdown axes:

### 6.1 VPIP (red at 25.6%, target 18-23%)

**Breakdown dimensions:**
```
VPIP by:
  Position:     UTG 12% | MP 18% | HJ 22% | CO 28% | BTN 35% | SB 30% | BB 42%
  Action type:  Open 15% | Call 8% | 3-bet 2.6%
  Stack depth:  <20BB 28% | 20-40BB 25% | 40+BB 24%
  Pot type:     First-in 18% | Facing raise 7.6% | Facing 3-bet 2.2%
  Table size:   6-max 27.8% | 8-max 24.9%
Main contributor: BB defense too wide (42% vs target 35%) + SB flats (30% vs target 20%)
```

### 6.2 Cold-Call Non-Blind (red at 10.4%, target <=6.5%)

**Breakdown dimensions:**
```
Cold-call by:
  Position:     CO 14% | HJ 8% | MP 6% | BTN 4%
  Vs opener:    vs EP 12% | vs MP 10% | vs LP 8%
  Stack depth:  <20BB 15% | 20-40BB 10% | 40+BB 8%
  Hand class:   Pairs 35% | Suited connectors 25% | Broadway 20% | Other 20%
Main contributor: CO cold-calls (14%, 22 hands) — pairs and suited connectors
```

### 6.3 AF (red at 1.28, target >=1.5)

**Breakdown dimensions:**
```
AF by:
  Street:       Flop 1.8 | Turn 1.1 | River 0.9
  Position:     IP 1.5 | OOP 0.9
  Role:         PFR 1.8 | Caller 0.7
  Pot type:     SRP 1.4 | 3BP 1.1
  Combined:     IP-PFR 2.1 | OOP-PFR 1.3 | IP-Caller 1.0 | OOP-Caller 0.5
Main contributor: OOP-Caller AF 0.5 (too passive when OOP and called preflop)
```

### 6.4 ATS (red at 25.7%, target >=35%)

**Breakdown dimensions:**
```
ATS by:
  Position:     BTN 42% | CO 28% | SB 15%
  Stack depth:  <15BB 35% | 15-25BB 28% | 25-40BB 22% | 40+BB 20%
  First-in:     Yes 30% | No (faced limp) 18%
  Table size:   6-max 32% | 8-max 24%
Main contributor: CO opens too tight (28% vs target 35-40%) at 25-40BB
```

### 6.5 3-Bet OOP (red at 4.6%, target >=7%)

**Breakdown dimensions:**
```
3-Bet OOP by:
  Defender:     SB vs BTN 6% | SB vs CO 4% | BB vs BTN 5% | BB vs SB 8%
  Stack depth:  <20BB 8% | 20-40BB 4% | 40+BB 3%
  Squeeze opps: Squeeze rate 7.6% (vs target 6-12%)
  Hand class:   Premiums 100% | Broadways 12% | Suited connectors 4%
Main contributor: SB vs CO only 4% (target 8-12%) — missing 3-bet bluffs
```

### 6.6 CBet 3BP (red at 7.1%, target >=35%)

**Breakdown dimensions:**
```
CBet 3BP by:
  Board texture:  A-high dry 20% | K-high 10% | Connected 0% | Low paired 0%
  IP/OOP:         IP 12% | OOP 3%
  Pot type:       vs Warrior (LP caller) 38% | vs Gentleman (EP/MP) 27% | BvB 25%
  Stack depth:    <20BB 15% | 20-40BB 5% | 40+BB 0%
Main contributor: Never c-betting in 3BP OOP (3%) and giving up too often IP on non-A boards
```

### 6.7 VPIP-PFR Gap (red at 12.2, target <8)

**Breakdown dimensions:**
```
Gap contributors:
  SB flat-call rate:    18% (SB VPIP 30% - SB PFR 12% = 18% gap)
  Cold-call from CO:    14% (CO VPIP 28% - CO PFR 14% = 14% gap)
  BB flat defend:       30% (BB VPIP 42% - BB 3-bet 12% = 30% gap — largest)
  Limps/overlimps:      2 (negligible)
Main contributor: BB defend via flat too wide (30pp gap — should 3-bet more)
```

---

## Part 7: Analyst Workflow (step by step)

### 7.1 Without Analyst (quick mode)

```
1. Pipeline runs Stages 1-10 fully automated
2. ~50% of candidates get HIGH-confidence auto verdicts
3. ~30% get tentative verdicts
4. ~20% remain "pending review"
5. Report renders with auto verdicts + "pending" tags
6. No session narrative, no exploit assessments
7. Headline numbers may be inflated (detector FP not cleared)
```

### 7.2 With Analyst (full mode)

```
1. Pipeline runs Stages 1-10, emits candidate file + template
2. Analyst (Claude Chat or human) opens template
3. For each candidate (sorted by EV priority):
   a. Read auto-coach fields (correct_action, threshold, math)
   b. Confirm or override the prefill verdict
   c. Write argument for MEDIUM/LOW confidence hands
   d. Clear false positives (III.3)
   e. Flag additional hands not in candidate set
4. Save session_analysis_<date>.json
5. Pipeline re-runs with --render-only (~3-5s)
   a. Loads analyst file
   b. _refresh_discipline_tier (recomputes counts)
   c. Renders report with analyst verdicts baked in
6. Report now shows:
   - Confirmed mistakes (detector + analyst)
   - Cleared false positives removed from counts
   - Full coaching boxes with analyst arguments
   - Session narrative
```

### 7.3 Analyst Efficiency Targets

| Metric | Current | Target (with Batch 1-3) |
|--------|---------|------------------------|
| Time per hand (auto-resolved) | 0s | 0s (no change) |
| Time per hand (tentative verdict) | ~30s | ~10s (math pre-computed) |
| Time per hand (blank — analyst decides) | ~2min | ~30s (auto-coach context) |
| Total analyst time (500-hand candidate set) | ~4 hours | ~1.5 hours |
| Candidate file availability | After equity (may timeout) | Before equity (always available) |
| False positive rate | ~20% | ~12% (calibrated detectors) |

---

## Part 8: Renderer Adapter Layer

The renderer MUST NOT read hand fields directly. It calls adapter helpers
that handle backward compatibility, field resolution, and fallbacks.

```python
# gem_report_draft/_adapters.py (NEW)

def get_decision_points(hand):
    """Return decision_points[] or empty list for legacy hands."""
    return hand.get('decision_points') or []

def get_key_decision(hand):
    """Return the key decision_point or None."""
    dp = get_decision_points(hand)
    kid = hand.get('key_decision_id')
    if kid:
        return next((d for d in dp if d['id'] == kid), None)
    # Fallback: first dp marked is_key_decision
    return next((d for d in dp if d.get('is_key_decision')), dp[0] if dp else None)

def get_primary_villain(hand):
    """Return primary villain dict or empty dict."""
    pv = hand.get('primary_villain') or {}
    if not pv:
        # Legacy fallback: use opener_position
        op = hand.get('opener_position')
        if op:
            for name, v in (hand.get('villains') or {}).items():
                if v.get('position') == op:
                    return {'name': name, **v}
    return pv

def get_villain_full(hand, villain_name):
    """Resolve full villain data from hand['villains']."""
    return (hand.get('villains') or {}).get(villain_name, {})

def get_analysis_confidence(hand):
    """Return analysis_confidence or safe default."""
    return hand.get('analysis_confidence') or {
        'confidence': 'LOW', 'risk_flags': ['no_analysis'],
        'needs_review': True, 'review_tier': 'unreviewed'}

def get_math_display(dp):
    """Return display-ready math fields based on math_type."""
    mt = dp.get('math_type', 'facing_bet')
    if mt == 'facing_bet':
        return {
            'label': f"need {dp.get('required_equity', 0)*100:.0f}%",
            'detail': f"Call {dp.get('hero_call_amount_bb', 0):.1f}BB into "
                      f"{dp.get('pot_facing_hero_bb', 0):.1f}BB pot",
            'ev': dp.get('ev_call_bb'),
        }
    elif mt == 'hero_bet':
        return {
            'label': f"need {dp.get('fold_equity_required', 0)*100:.0f}% folds",
            'detail': f"Bet {dp.get('risk_bb', 0):.1f}BB to win "
                      f"{dp.get('reward_bb', 0):.1f}BB pot",
            'ev': dp.get('ev_bet_bb'),
        }
    elif mt == 'hero_jam':
        return {
            'label': f"eq if called: {(dp.get('equity_when_called') or 0)*100:.0f}%",
            'detail': f"Jam {dp.get('hero_risk_bb', 0):.1f}BB",
            'ev': dp.get('ev_jam_bb'),
        }
    elif mt == 'check_or_bet':
        return {
            'label': dp.get('preferred_action', '?'),
            'detail': f"EV(bet)={dp.get('ev_bet_bb', 0):+.1f} vs "
                      f"EV(check)={dp.get('ev_check_bb', 0):+.1f}",
            'ev': max(dp.get('ev_bet_bb', 0), dp.get('ev_check_bb', 0)),
        }
    return {'label': '', 'detail': '', 'ev': None}
```

**Rule:** Every renderer file imports from `_adapters.py`. No direct
`hand.get('primary_villain')` or `hand.get('decision_points')` in
renderer code — always through the adapter.

---

## Part 9: Testing & Validation

> **Batch 1 is considered complete only when the golden fixture suite proves
> decision points are extracted correctly, detector flags attach to valid
> decision-point IDs, non-NLH/timeout/duplicate cases are handled safely,
> and render-only still works through the adapter layer.**

### 9.1 Golden Fixture Inventory (Batch 1)

| Fixture File | Scenario | What It Tests |
|---|---|---|
| `pf_fold_first_in.txt` | Hero folds UTG first-in | 0 decision_points (no strategic choice) |
| `pf_open_first_in.txt` | Hero opens BTN 2.5x | 1 DP: hero_action=raise, action_class=open |
| `pf_sb_flat_vs_btn.txt` | SB calls BTN open at 25BB | DP: cold_call, primary_villain=BTN, position_relative=oop |
| `pf_3bet.txt` | Hero 3-bets from BB vs CO | DP: action_class=3bet, facing_villain_role=opener |
| `pf_face_3bet_fold.txt` | Hero opens, faces 3-bet, folds | 2 DPs: open + fold_vs_bet, root_mistake if open was wrong |
| `pf_squeeze.txt` | BB squeezes vs open+call | primary_villain = squeezer (NOT opener) |
| `flop_cbet.txt` | Hero PFR, c-bets flop IP | DP: action_class=cbet, math_type=hero_bet, hero_is_pfr=True |
| `flop_check_call.txt` | Hero calls flop bet OOP | DP: facing_bet math, required_equity populated |
| `flop_check_raise.txt` | Hero check-raises vs c-bet | DP: action_class=check_raise, math_type=hero_raise |
| `turn_barrel.txt` | Hero double-barrels turn | DP: action_class=barrel, street=turn |
| `river_call.txt` | Hero calls river bet | DP: facing_bet math, full pot-odds formula verified |
| `river_value_bet.txt` | Hero bets river for value | DP: math_type=hero_bet, risk_bb/reward_bb populated |
| `multiway_flop.txt` | 3-way flop, Hero in middle | position_relative=middle, players_in_hand=3 |
| `multiway_donk.txt` | BB donk-bets into 3 players | DP: action_class=donk, multiway context |
| `multiway_allin.txt` | 3-way all-in preflop | Multiple facing villains, equity triway |
| `side_pot.txt` | Side pot / short-stack all-in | eff_stack_bb correct per decision |
| `uncalled_bet.txt` | Hero bets, all fold | 1 DP: hero_bet, no facing_villain on fold-through |
| `timeout_hand.txt` | Hero disconnected/timed out | hand['disconnected']=True, excluded from all metrics |
| `plo_hand.txt` | Pot-Limit Omaha hand | game_type='PLO', quarantined, no NLH detector fires |
| `short_deck.txt` | Short Deck Hold'em (if avail) | game_type='ShortDeck', quarantined |
| `duplicate_ids.txt` | Same hand ID appears twice | Second occurrence removed, warning logged |
| `hand_gap.txt` | IDs jump from 100 to 105 | Gap detected, warning logged |
| `bad_pot_balance.txt` | Action ledger pot != result pot | QA gate catches pot_mismatch |
| `impossible_stack.txt` | Negative stack or >500BB micro | QA gate catches impossible_stack |

**24 fixture files. Each tests a specific behavior.**

---

### 9.2 Batch 1 Core Tests

Tests are BEHAVIORAL — test output contracts, not text in source files.

```python
# ============================================================
# GROUP A: Decision Point Extractor (gem_dp_extractor.py)
# ============================================================

# A1: Parser does NOT create decision_points (Extractor does)
def test_parser_does_not_create_dp():
    hands = parse_fixture('pf_sb_flat_vs_btn.txt')
    for h in hands:
        assert 'decision_points' not in h

# A2: Extractor creates decision_points
def test_extractor_creates_dp():
    hands = parse_fixture('pf_sb_flat_vs_btn.txt')
    hands = extract_decision_points(hands)
    assert all('decision_points' in h for h in hands if h.get('vpip'))

# A3: DP ID uniqueness across all hands
def test_dp_ids_unique():
    hands = parse_and_extract_all_fixtures()
    all_ids = [dp['id'] for h in hands for dp in h.get('decision_points', [])]
    assert len(all_ids) == len(set(all_ids)), "Duplicate decision_point IDs"

# A4: DP links back to correct action_ledger entry
def test_dp_action_index_valid():
    hands = parse_and_extract('river_call.txt')
    for h in hands:
        for dp in h.get('decision_points', []):
            action = h['action_ledger'][dp['action_index']]
            assert action['is_hero'], f"DP {dp['id']} points to non-Hero action"
            assert action['action'] == dp['hero_action'] or \
                   (dp['hero_action'] == 'jam' and action.get('is_all_in'))

# A5: hero_action_class is semantically correct
def test_dp_action_class():
    h = parse_and_extract('pf_sb_flat_vs_btn.txt')[0]
    dp = h['decision_points'][0]
    assert dp['hero_action_class'] == 'cold_call'
    assert dp['hero_action'] == 'call'

    h2 = parse_and_extract('flop_cbet.txt')[0]
    dp2 = [d for d in h2['decision_points'] if d['street'] == 'flop'][0]
    assert dp2['hero_action_class'] == 'cbet'

# A6: position_relative correct for multiway
def test_multiway_position():
    h = parse_and_extract('multiway_flop.txt')[0]
    flop_dp = [d for d in h['decision_points'] if d['street'] == 'flop'][0]
    assert flop_dp['position_relative'] in ('middle', 'multiway_unclear')
    assert flop_dp['players_in_hand'] >= 3

# A7: facing_villain_name resolves to hand['villains']
def test_facing_villain_resolves():
    h = parse_and_extract('pf_sb_flat_vs_btn.txt')[0]
    dp = h['decision_points'][0]
    if dp.get('facing_villain_name'):
        assert dp['facing_villain_name'] in h['villains']

# A8: fold hand has 0 decision_points (no strategic choice to analyze)
def test_fold_no_dp():
    h = parse_and_extract('pf_fold_first_in.txt')[0]
    assert len(h.get('decision_points', [])) == 0

# ============================================================
# GROUP B: Ownership Contracts
# ============================================================

# B1: Parser does NOT set primary_villain
def test_parser_no_primary_villain():
    hands = parse_fixture('pf_squeeze.txt')
    assert all('primary_villain' not in h for h in hands)

# B2: Analyzer DOES set primary_villain
def test_analyzer_sets_primary_villain():
    analyzed = full_pipeline_fixture('pf_squeeze.txt')
    for h in analyzed:
        if h.get('decision_points'):
            assert 'primary_villain' in h

# B3: Primary villain is CORRECT (not always opener)
def test_primary_villain_is_squeezer():
    h = full_pipeline_fixture('pf_squeeze.txt')[0]
    pv = h['primary_villain']
    # In a squeeze pot, primary villain should be the squeezer
    key_dp = next(d for d in h['decision_points'] if d.get('is_key_decision'))
    assert key_dp['facing_villain_role'] == 'squeezer'

def test_primary_villain_is_river_bettor():
    h = full_pipeline_fixture('river_call.txt')[0]
    river_dp = [d for d in h['decision_points'] if d['street'] == 'river'][0]
    assert river_dp['facing_villain_role'] == 'bettor'

# ============================================================
# GROUP C: Detector-to-DP Linkage
# ============================================================

# C1: Every detector flag has a valid decision_point_id
def test_detector_flags_link_to_dp():
    hands, stats = full_pipeline_with_stats('golden_session/')
    all_dp_ids = {dp['id'] for h in hands for dp in h.get('decision_points', [])}
    for flag in stats.get('mistakes', []) + stats.get('punts', {}).get('hands', []):
        dpid = flag.get('decision_point_id')
        if dpid:
            assert dpid in all_dp_ids, f"Flag {flag['id']} links to invalid DP {dpid}"

# C2: Cold-call detector attaches to preflop call DP, not later DP
def test_cold_call_attaches_to_preflop():
    hands, stats = full_pipeline_with_stats_fixture('pf_sb_flat_vs_btn.txt')
    cc_flags = [f for f in stats.get('mistakes', []) if 'cold_call' in f.get('type', '').lower()]
    for f in cc_flags:
        dp = get_dp_by_id(hands, f['decision_point_id'])
        assert dp['street'] == 'preflop', "Cold-call flag attached to non-preflop DP"

# ============================================================
# GROUP D: Game-Type Quarantine
# ============================================================

# D1: PLO hand is parsed but quarantined
def test_plo_parsed_not_detected():
    hands, stats = full_pipeline_with_stats_fixture('plo_hand.txt')
    plo = [h for h in hands if h.get('game_type') == 'PLO']
    assert len(plo) >= 1, "PLO hand not parsed"
    mistake_ids = {m['id'] for m in stats.get('mistakes', [])}
    assert all(h['id'] not in mistake_ids for h in plo), "PLO hand went through NLH detector"

# D2: PLO hand still renders (with badge, no NLH analysis)
def test_plo_renders_with_badge():
    # Render QA check: PLO cards appear but no detector verdict
    pass  # render-level test

# D3: NLH hands still go through detectors normally
def test_nlh_detected():
    hands, stats = full_pipeline_with_stats('golden_session/')
    nlh = [h for h in hands if h.get('game_type') == 'NLH']
    assert len(stats.get('mistakes', [])) > 0, "No NLH detections at all"

# ============================================================
# GROUP E: Disconnection / Timeout
# ============================================================

# E1: Disconnected hand flagged
def test_disconnect_flagged():
    h = parse_and_extract('timeout_hand.txt')[0]
    assert h.get('disconnected') is True

# E2: Disconnected hand excluded from metrics (not just flagged)
def test_disconnect_excluded_from_metrics():
    hands, stats = full_pipeline_with_stats_fixture('timeout_hand.txt')
    dc_hand = [h for h in hands if h.get('disconnected')][0]
    assert dc_hand['id'] not in stats.get('_vpip_hand_ids', set())
    assert dc_hand['id'] not in stats.get('_pfr_hand_ids', set())
    assert dc_hand['id'] not in stats.get('_missed_steal_ids', set())

# ============================================================
# GROUP F: Duplicate / Gap Detection
# ============================================================

# F1: Duplicate hand removed
def test_duplicate_removed():
    hands = parse_fixture('duplicate_ids.txt')
    ids = [h['id'] for h in hands]
    assert len(ids) == len(set(ids)), "Duplicate hand not removed"

# F2: Gap detected
def test_gap_detected():
    hands, warnings = parse_fixture_with_warnings('hand_gap.txt')
    assert any('gap' in w.lower() for w in warnings)

# ============================================================
# GROUP G: Pipeline Ordering
# ============================================================

# G1: Candidates emitted before slow equity
def test_candidates_before_equity():
    log = run_pipeline_fixture('golden_session/')
    assert log['candidate_emit_time'] < log['slow_equity_start_time']

# G2: Slow equity timeout does not lose candidates
def test_equity_timeout_graceful():
    log = run_pipeline_fixture('golden_session/', force_slow_equity_timeout=True)
    assert log['candidate_file_exists']
    assert log['template_file_exists']
    assert log['candidate_equity_backfill_status'] == 'timeout'
    # Quick-mode render still works
    assert log['render_quick_mode_success']

# ============================================================
# GROUP H: QA Gate (good data AND bad data)
# ============================================================

# H1: Clean data passes QA
def test_qa_clean():
    hands = parse_fixture('golden_hands.txt')
    qa = run_parser_qa(hands)
    assert qa['pot_mismatch_count'] == 0
    assert qa['impossible_stack_count'] == 0

# H2: Bad pot balance caught
def test_qa_catches_pot_mismatch():
    hands = parse_fixture('bad_pot_balance.txt')
    qa = run_parser_qa(hands)
    assert qa['pot_mismatch_count'] > 0

# H3: Impossible stacks caught
def test_qa_catches_impossible_stack():
    hands = parse_fixture('impossible_stack.txt')
    qa = run_parser_qa(hands)
    assert qa['impossible_stack_count'] > 0

# ============================================================
# GROUP I: Adapter Layer
# ============================================================

# I1: Legacy hand without dp[] returns empty list
def test_adapter_legacy_no_dp():
    legacy = {'id': 'TM123', 'vpip': True}
    assert get_decision_points(legacy) == []

# I2: get_key_decision returns matching DP
def test_adapter_key_decision():
    h = {'decision_points': [
        {'id': 'dp1', 'is_key_decision': False},
        {'id': 'dp2', 'is_key_decision': True},
    ], 'key_decision_id': 'dp2'}
    assert get_key_decision(h)['id'] == 'dp2'

# I3: Legacy opener fallback for primary_villain
def test_adapter_opener_fallback():
    h = {'opener_position': 'BTN',
         'villains': {'Player_x': {'position': 'BTN', 'stack_bb': 30}}}
    pv = get_primary_villain(h)
    assert pv['position'] == 'BTN'

# I4: Missing villain returns safe empty dict
def test_adapter_missing_villain():
    assert get_villain_full({}, 'nonexistent') == {}

# I5: get_math_display handles all math_types without crash
def test_adapter_math_display_all_types():
    for mt in ['facing_bet', 'hero_bet', 'hero_jam', 'check_or_bet', 'fold_vs_bet']:
        dp = {'math_type': mt, 'hero_call_amount_bb': 5, 'final_pot_if_call_bb': 15,
              'required_equity': 0.33, 'risk_bb': 5, 'reward_bb': 10,
              'fold_equity_required': 0.33, 'hero_risk_bb': 20,
              'equity_when_called': 0.45, 'ev_check_bb': -0.5, 'ev_bet_bb': 1.2,
              'preferred_action': 'bet', 'ev_call_bb': 0.5, 'ev_jam_bb': 0.8}
        result = get_math_display(dp)
        assert result['label'], f"Empty label for math_type={mt}"

# I6: Renderer files don't bypass adapters (architectural lint)
def test_renderer_uses_adapters():
    import glob
    for f in glob.glob('gem_report_draft/*.py'):
        if '_adapters.py' in f or '__init__' in f:
            continue
        code = open(f).read()
        # These direct accesses should go through adapters
        assert "hand.get('decision_points')" not in code or '_adapters' in code, \
            f"{f} bypasses adapter for decision_points"
        assert "hand.get('primary_villain')" not in code or '_adapters' in code, \
            f"{f} bypasses adapter for primary_villain"

# ============================================================
# GROUP J: Pot-Odds Formula Correctness
# ============================================================

# J1: Facing-bet math is correct
def test_pot_odds_formula():
    h = full_pipeline_fixture('river_call.txt')[0]
    for dp in h.get('decision_points', []):
        if dp.get('math_type') == 'facing_bet' and dp.get('hero_call_amount_bb'):
            # Formula: required_equity = hero_call / (pot_facing + hero_call)
            expected = dp['hero_call_amount_bb'] / dp['final_pot_if_call_bb']
            assert abs(dp['required_equity'] - expected) < 0.001
            # EV formula: ev = hero_eq * final_pot - hero_call
            if dp.get('hero_equity_vs_range') is not None:
                expected_ev = (dp['hero_equity_vs_range'] * dp['final_pot_if_call_bb']
                               - dp['hero_call_amount_bb'])
                assert abs(dp['ev_call_bb'] - expected_ev) < 0.01
```

**Total: 10 test groups, 30+ test functions, 24 fixture files.**

---

### 9.3 Structural Guarantees (all batches, run post-render)

| # | Check | Assert |
|---|-------|--------|
| G1 | Every red/amber metric clickable | No red/amber in watchlist without `<a>` |
| G2 | Every popup renders >= 1 hand | No `data-hids` with 0 renderable rows |
| G3 | Every /B metric same denominator | ITM/B = Top1/B = Top5/B = FT/B denominator |
| G4 | Every hand ref has appendix card | Every `sec-app-hand-X` anchor exists |
| G5 | Every stat table has drill-down | Every section with `<table>` has hand-list-trigger |
| G6 | Defend targets per-opener | No defend matrix row uses aggregate band |
| G7 | Mistake counts match 4 surfaces | strip = TL;DR = S2 header = S2.2 heading |
| G8 | Pot odds on every hero call | Every call with amt > 0 shows need X% |
| G9 | Board texture on postflop cards | Every hand with board >= 3 shows texture |
| G10 | No raw "N% underdog" | Narrative uses Suckout/Flip/Behind classification |
| G11 | Coaching box on reviewed hands | Every III.1/III.2 has correct_action (Batch 3+) |
| G12 | Threshold on range mistakes | Every wide/missed hand shows boundary (Batch 3+) |
| G13 | No PLO through NLH detectors | game_type == 'NLH' on all detected hands |
| G14 | No disconnection in metrics | disconnected hands excluded from VPIP/PFR |
| G15 | decision_points on candidates | >= 95% of candidate hands have dp[] |

---

## Part 10: File Ownership Map (updated for v2 pipeline)

| File | Owns | Reads |
|------|------|-------|
| `gem_parser.py` | hand[] base fields, action_ledger, villains{}, board, game_type, disconnected | Raw HH text |
| `gem_dp_extractor.py` (NEW) | decision_points[] identity + position + board fields | Parsed hand, action_ledger |
| `gem_analyzer.py` | stats[], primary_villain, coaching_flags, variance_outcome. Detectors attach to dp IDs | hand[], decision_points[], ranges |
| `gem_eai_equity.py` | hero_equity (exact), is_favorite, suckout | hand cards + board |
| `gem_auto_coach.py` (NEW) | Fills dp[] math, coaching, root-mistake, exploit, ICM fields | Candidates, ranges, population data |
| `gem_candidate_builder.py` | candidate buckets, re-ranking | stats, hands, EAI, dp[] |
| `gem_report_data.py` | rd[], appendix_hand_details, discipline_tier refresh | stats, hands, analyst |
| `gem_leak_watchlist.py` | watchlist metrics, section_map, breakdowns | CSV stats, targets |
| `gem_qa_gate.py` (NEW) | QA results, warnings, errors | hands, stats, HTML |
| `gem_population_exploits.py` (NEW) | exploit recommendations | spot type, villain archetype |
| `gem_ranges.py` | range expansion, hand_in_range(), range_boundary() | Range text files |
| `gem_report_draft/_adapters.py` (NEW) | Adapter helpers for renderer | hand, dp[], villains |
| `gem_report_draft/*.py` | HTML/MD output via adapters | rd, stats, hands (READ ONLY) |

---

## Part 11: Batch 1 Strict Scope

**Give to Claude FIRST. Nothing else until this passes.**

### Batch 1 implements ONLY:

1. `gem_dp_extractor.py` — decision_point extraction stage (identity/position/board fields only)
2. `decision_points[]` schema on every parsed hand
3. `primary_villain` set by analyzer (not parser)
4. Pot-odds field normalization for CALL decisions only (math_type='facing_bet')
5. Candidate emission before slow equity
6. Duplicate hand detection in parser
7. Game-type quarantine (NLH/PLO flag + detector gating)
8. Disconnection/timeout filtering in parser
9. Basic QA gate (parser + analyzer sanity checks)
10. `gem_report_draft/_adapters.py` renderer adapter helpers

### Batch 1 does NOT implement:

- Range-based equity estimation
- Minimum hand thresholds
- Line-class clustering
- Population exploits
- ICM computation
- Sizing-tell detection
- Counterexample generation
- Drill pack generation
- Board-texture matrices
- EV-weighted leak ranking
- Hero-bet / hero-jam / check-or-bet math types (only facing_bet in Batch 1)
- Auto-Coach coaching fields (correct_action, memory_rule, drill_bucket)

### Why this boundary:

Batch 1 establishes the INFRASTRUCTURE that everything else builds on.
`decision_points[]` exist on every hand with identity/position/board populated.
Detectors attach flags to dp IDs. Candidates are emitted before equity.
The renderer uses adapters. The QA gate catches garbage.

Once this passes, Batch 2-6 are additive — they fill in the empty math and
coaching fields on the decision_points that already exist. No re-architecture
needed.

### Batch 1 test gate:

All 8 behavioral tests from Part 9.1 must pass.
Zero legacy field names in new code (old code shimmed via adapters).
Candidate file written before slow equity starts.
No PLO hands processed by NLH detectors.
No disconnected hands in VPIP/PFR.

**Do not implement Batch 2+ until Batch 1 tests pass and legacy fields are
either migrated or explicitly shimmed.**
