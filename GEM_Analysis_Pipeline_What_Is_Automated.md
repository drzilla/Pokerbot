# GEM Hand Analysis Pipeline — What's Automated vs What Goes to Analyst

Generated 2026-06-03. Covers the full journey of every hand from raw HH text
to rendered report card.

---

## The Pipeline at a Glance

```
Raw HH files
    |
    v
[1] PARSER ──────────────── 176 fields per hand (ALL hands)
    |
    v
[2] DETECTORS ───────────── 60+ rules flag mistakes/punts/coolers (ALL hands)
    |
    v
[3] EAI EQUITY ──────────── True multiway equity (10-15% — all-in to showdown)
    |
    v
[4] VARIANCE CLASSIFIER ─── Suckout / flip / top-of-range (all-in hands)
    |
    v
[5] COACHING RULES ──────── 5 session-wide rule checks (ALL hands)
    |
    v
[6] CANDIDATE BUILDER ───── 8 typed buckets for review (10-15% of volume)
    |
    v
[7] PRE-FILL VERDICTS ───── Auto-classify HIGH-confidence hands (~50% of candidates)
    |
    v
[8] ══ ANALYST STEP ══ ──── Human reviews remaining candidates
    |
    v
[9] POST-ANALYST REFRESH ── Override counts, recompute discipline tier
    |
    v
[10] REPORT RENDER ──────── 1400+ appendix cards, 14 sections, full HTML
```

---

## Stage 1: PARSER — Fully Automated, ALL Hands

**What it does:** Reads raw hand history text and extracts 176 structured fields.
Every single hand gets the full treatment.

**Key outputs per hand:**

| Category | Fields | Notes |
|----------|--------|-------|
| **Identity** | id, tournament, date, format, buyin | Always populated |
| **Table state** | table_size, level, sb_blind, bb_blind, ante | Always |
| **Hero position** | position, eff_pos, hero_ip, hero_late_position | Always |
| **Stacks** | stack_bb, eff_stack_bb, eff_stack_bb_at_decision, seat_stacks_bb_all | All seats |
| **Cards** | cards (hero), board (community), villains (shown cards at SD) | Hero always; villains only at showdown |
| **Preflop action** | vpip, pfr, first_in, hero_3bet, cold_called, pf_allin, pf_sequence, opener_position | Conditional on action taken |
| **Postflop action** | hero_cbet_flop, double_barreled, triple_barreled, probe_turn, check_raises, river_action | Conditional on streets seen |
| **Action ledger** | action_ledger (per-action: street/player/position/action/amount_bb/is_all_in) | Always (canonical source) |
| **Pot ledger** | pot_ledger (main pot/side pots) | Always |
| **Board analysis** | board_texture (dry/wet/monotone), board_archetype, spr | When flop exists |
| **Outcome** | net_bb, won, went_to_sd, hand_strength | Always |
| **Villain identity** | villains dict (seat/position/stack/shown_cards/archetype) | Per opponent |
| **Tournament context** | tournament_phase, format (bounty/freezeout/satellite) | Always |

**What the parser CAN'T do:**
- Doesn't know if a play was correct or incorrect (no strategy engine)
- Doesn't compute equity (that's EAI's job)
- Doesn't know villain ranges (only shown cards)
- Doesn't detect patterns across hands (that's detectors' job)

---

## Stage 2: DETECTORS — Fully Automated, ALL Hands

**What it does:** 60+ rule-based detectors scan every hand for strategic errors.
Each detector has a confidence level (CLEAR/HIGH/MEDIUM/MARGINAL) and a
suggested verdict category.

### Punt Detectors (severe errors, verdict: III.1 Punt)

| Detector | What it catches | Trigger |
|----------|----------------|---------|
| **P1-CVJ** | Cold 4-bet jam with weak hand | Cold-called then jammed, hand not in top range |
| **P1-IsoJam** | Isolation jam at <8BB vs limper | Short-stack iso with wrong sizing |
| **P2-LightFourBet** | Light 4-bet that got called | 4-bet bluff at wrong stack depth |
| **P3-DeepFlatSpew** | Flat-called 3-bet too wide deep | Called 3-bet >30BB with dominated hand |
| **P4-DrawJamDeep** | Jammed draw >15BB deep | Should bet-fold, not jam |
| **P5-SmallSmallJam** | Jammed 5-9BB into 6+ players | Wrong stack for open-jam |
| **P6-BluffOverbet** | River bluff overbet | Huge bluff vs uncapped range |

### Mistake Detectors (errors, confidence: CLEAR to MARGINAL)

| Category | Detectors | What they catch |
|----------|-----------|----------------|
| **Preflop opens** | Missed steal (BTN/CO/SB), wide open, wrong sizing | First-in opportunities missed or butchered |
| **Preflop defends** | Missed defend (BB/SB), fold-to-3bet wrong, cold-call errors | Defend range vs opener position violations |
| **3-bet / 4-bet** | Reshove ceiling (J33-J37), light 3-bet, missed squeeze | Preflop aggression mistakes |
| **C-bet** | Flop cbet sizing wrong (MW too small, 3BP too large), missed cbet | Continuation bet frequency and sizing |
| **Barrel** | Missed double/triple barrel, wrong barrel sizing | Multi-street aggression |
| **Check-raise** | Missed check-raise opportunity, wrong check-raise sizing | Defensive aggression |
| **River** | Missed value bet, bad bluff, wrong call/fold | Final street decisions |
| **Passivity** | Check-call when should bet, missed probe, passive line OOP | Aggregate passivity signals |

### Cooler Screen

Identifies structural coolers — unavoidable big-pot losses where both players
have strong hands. These are NOT mistakes; they're separated to prevent
inflating the error count.

**Confidence assignments:**
- CLEAR (highest): Obvious errors detectable from action sequence alone
- HIGH: Very likely errors but context-dependent
- MEDIUM: Possible errors needing position/stack/range context
- MARGINAL: Borderline cases (e.g., marginal missed steals)

**What detectors CAN'T do:**
- Can't evaluate exploitative plays (may flag a correct exploit as "wrong")
- Can't account for opponent-specific reads (plays villain profile)
- Can't assess multi-street EV when line involves future street planning
- Can't weigh tournament equity (ICM, bubble, bounty) beyond basic formulas
- Can't distinguish "ran bad" from "played bad" on missed value bets

---

## Stage 3: EAI EQUITY — Automated, Showdown All-In Hands Only (~10-15%)

**Trigger:** Hand went to showdown AND at least one player was all-in AND
villain cards are known (shown at SD).

**What it computes:**
- True multiway equity at the moment of the all-in
- Method: exact enumeration (postflop, <=990 remaining boards) or Monte Carlo
  (preflop, 120K samples)
- Is_favorite: whether Hero had highest equity in the field
- Suckout direction: Hero got sucked out / Hero sucked out / neither

**Output fields:** hero_equity (0-1 fraction), opp_equity[], is_favorite, category
(ahead/flip/behind), suckout, equity_method, n_allin

**What EAI CAN'T do:**
- Can't compute equity when villain cards are unknown (non-showdown)
- Can't compute range equity (only exact cards vs exact cards)
- Can't compute equity mid-hand (only at the all-in decision point)
- Can't account for ICM/bounty equity adjustments
- Multiway equity with 4+ players and preflop can be slow (degrades to lighter MC)

---

## Stage 4: VARIANCE CLASSIFIER — Automated, All-In Hands

**What it does:** Classifies every all-in outcome into a variance category:

| Outcome | Definition | Impact |
|---------|-----------|--------|
| **Suckout (against Hero)** | Hero was >=60% favourite, lost | Pure bad luck |
| **Suckout (by Hero)** | Hero was <=40% dog, won | Pure good luck |
| **Lost flip** | 40-60% equity at all-in, lost | Coin-flip variance |
| **Top of range** | Hero's hand was good but villain had the top of their range | Structural — may or may not be a mistake |
| **Semi-bluff cooler** | Hero had a draw with backup equity, lost to made hand | Standard variance |

**What it CAN'T do:**
- Can't distinguish "unlucky spot" from "shouldn't have been there"
  (that's the analyst's job — was it a good jam that ran into the top, or
  a bad jam that was always behind?)

---

## Stage 5: COACHING RULES — Automated, ALL Hands

**5 session-wide rules (from Amit/Dave coaching sessions):**

| Rule | Detection | When it fires |
|------|----------|--------------|
| **MW_SMALL_SIZING** | Hero c-bets <50% pot multiway with strong hand | Should bloat pot more |
| **OOP_CHECK_CALL_SHOULD_BET** | Hero check-called OOP flop, lost 5+ BB | Should've bet for fold equity |
| **CHEAP_TOURNEY_SMALL_SIZING** | Avg c-bet <50% in <$100 buy-ins | Villains inelastic — size up |
| **BVB_DEEP_RAGGED_OPEN** | Opened ragged offsuit BvB >40BB deep | Fold bottom-range hands deep |
| **CBET_BARREL_CORRELATION** | Tracks big-cbet barrel rate vs small-cbet barrel rate | Stats only (not a flag) |

**What coaching rules CAN'T do:**
- Only 5 rules — many coaching insights aren't codified yet
- Can't detect complex multi-street patterns
- Can't adapt to specific coach's current focus areas
- Fire on all players identically (no player-specific rule adjustments)

---

## Stage 6: CANDIDATE BUILDER — Automated Bucket Assignment

**Builds 8 typed buckets for analyst review:**

| Bucket | What goes in | Source | Size |
|--------|-------------|--------|------|
| **bust_audit** | Stacked off (30BB+ lost, all-in or 95%+ committed) | Parser + EAI | 5-10% |
| **coolers** | Structural coolers from cooler screen | Detector | 1-3% |
| **mistakes** | Detector-flagged errors (CLEAR/HIGH/MEDIUM) | Detector | 2-5% |
| **punts** | P1-P6 detector-flagged severe errors | Detector | 0.5-2% |
| **iii4_screening** | Ambiguous all-ins — below flip equity, above pure dog | EAI + Detector | 1-2% |
| **read_dependent_screening** | GTO-correct but population-exploitable calls | Solver pass | 0.5-1% |
| **bestplay_screening** | Rare high-quality plays worth studying | Detector | <0.5% |
| **blindspot_sample** | Random 5-10 non-flagged hands (control group) | Random | Fixed |

**What goes into the candidate file per hand:** 55 fields — full context snapshot
including cards, board, position, stacks, action sequence, draw profiles,
villain archetype, bounty context, tournament phase, per-street decision nodes.

---

## Stage 7: PRE-FILL VERDICTS — Automated Classification

**Auto-resolved (no analyst needed):**

| Hand Type | Auto Verdict | Confidence | Why it's safe |
|-----------|-------------|-----------|---------------|
| EAI equity 40-60% lost | III.5 Justified (lost flip) | HIGH | Pure variance — math is unambiguous |
| EAI equity 60%+ favorite lost | III.5 Justified (suckout) | HIGH | Hero was correct, ran bad |
| CLEAR-confidence detector mistake | III.2 Mistake | HIGH | Action sequence + range analysis is clear |
| Structural cooler (both strong) | I.7 Cooler | HIGH | Neither player can fold this matchup |
| Semi-bluff cooler | III.5 Justified (variance) | MEDIUM | Draw with equity had correct line |

**Needs analyst review:**

| Hand Type | Pre-fill | Why analyst needed |
|-----------|---------|-------------------|
| Top-of-range loss, <50% committed | III.4 Read-dependent | Was the initial call/raise correct? Context matters |
| Top-of-range loss, fully committed | I.7 Cooler (tentative) | Might be a bad call that ran into nuts |
| MEDIUM-confidence mistakes | III.2 (tentative) | Exploit/read might justify the play |
| MARGINAL missed steals | Empty (analyst decides) | Position + stack + table dynamics needed |
| Ambiguous all-ins (iii4) | Empty | Need range analysis + exploit assessment |
| Read-dependent calls | III.4 (tentative) | Population vs specific villain matters |
| Bestplay screening | Empty | Curator picks, not auto-classifiable |
| P1-P6 punts | III.1 (tentative) | Analyst must write the argument |

**Pre-fill coverage:** ~50% of candidates get HIGH-confidence auto verdicts.
~30% get tentative verdicts the analyst can confirm or override.
~20% are blank — analyst must evaluate from scratch.

---

## Stage 8: THE ANALYST STEP — Human (Claude Chat or human)

**This is where automation ends and judgment begins.**

### What the analyst does that automation can't:

| Capability | Why it needs a human/LLM |
|-----------|------------------------|
| **Range construction** | "What does villain's range look like after open-raise, 3-bet, call?" — requires game-tree reasoning |
| **Exploit evaluation** | "Was this a correct exploit against this specific villain type?" — needs population vs individual judgment |
| **Multi-street planning** | "Was the flop call correct given turn/river plan?" — requires forward-looking EV assessment |
| **Context-dependent sizing** | "Is 33% pot or 75% pot correct here?" — depends on board, range, villain, stack depth interaction |
| **ICM assessment** | "Should I fold AQ here at the bubble?" — requires pay jump modeling |
| **Narrative writing** | "Why did this session go wrong?" — needs synthesis across 50+ data points |
| **Priority judgment** | "Which leak matters most for this player's development?" — coaching wisdom |
| **Counterexample awareness** | "Is this pattern real or cherry-picked?" — needs base-rate reasoning |

### What the analyst provides per hand:

```
verdict:     III.2 Mistake (or III.1 Punt / III.3 Cleared / III.4 Read-dep / III.5 Justified / I.7 Cooler)
argument:    "TL;DR: Open-min at 12BB exploitable. Population jams wide..."
             "### PRICE -> REQUIRED EQUITY"
             "- Call 8.5BB into 12.3BB pot -> need 34%"
             "- Hero AJs vs villain's estimated range -> ~42%"
             "- EV of call: +1.2 BB"
confidence:  HIGH / MEDIUM / LOW
outcome:     suckout / lost_flip / variance / cooler (optional sub-label)
```

### What gets skipped without an analyst:

When no analyst file is provided (quick mode), the pipeline uses ONLY automated
classifications. This means:

- ~20% of candidates have no verdict at all → render as "pending review"
- ~30% of candidates have tentative verdicts → render as-is (may be wrong)
- No synthesized session narrative
- No exploit-aware hand evaluations
- No custom coaching recommendations
- Mistake count may be inflated (detector false positives not cleared)

---

## Stage 9: POST-ANALYST REFRESH — Automated

**What it does:** Merges analyst verdicts back into the automated counts.

| If analyst says... | Effect on automated counts |
|-------------------|---------------------------|
| III.3 Cleared (was III.2 mistake) | Removes from mistake count |
| III.4 Read-dependent (was III.1 punt) | Removes from punt count |
| III.5 Justified (was flagged) | Removes from mistake/punt count |
| I.7 Cooler (was anything) | Moves to cooler count |
| III.1 Punt (was not flagged) | ADDS to punt count |
| III.2 Mistake (was not flagged) | ADDS to mistake count |

This ensures the headline numbers (MISTAKES/100, PUNTS/100) reflect the
analyst's judgment, not just the detector's raw flags.

---

## Stage 10: REPORT RENDER — Automated

**Appendix hand selection (which hands get full detail cards):**

~1400 hands get appendix cards in a large session. Selection criteria:

| Priority | Source | Why included |
|----------|--------|-------------|
| 90+ | Suckouts, key coolers, analyst-reviewed mistakes | Most important pedagogically |
| 80-89 | CLEAR mistakes, P1-P6 punts | Confirmed errors to drill |
| 70-79 | Bestplay screening, interesting plays | Positive reinforcement |
| 60-69 | Bust audit, read-dependent | Context for big losses |
| 50-59 | Coaching flag hits, blind-spot sample | Training candidates |
| <50 | Not included in appendix | Only in stats/aggregates |

**Each appendix card shows:**
- Full hand grid (visual action table with colored actions)
- Board cards with street-by-street dealing
- Draw profiles per street (flush draw, straight draw, etc.)
- Pot size and sizing percentages per action
- IP/OOP badge (NEW in CP23)
- Board texture label (NEW in CP23)
- Pot odds "need X%" on every call (NEW in CP23)
- Villain archetype + exploit note (NEW in CP23)
- All-in equity when available
- Showdown villain cards + made-hand description
- Analyst notes yellow block (verdict + argument)
- Result footer (net BB won/lost)

---

## What's Still Manual vs What Could Be Automated

### Currently manual, COULD be automated:

| Task | Current State | Automation Path |
|------|--------------|----------------|
| **Range estimation for non-showdown hands** | Analyst estimates | Precomputed range tables + position/action inference |
| **"Minimum correct hand" threshold** | Not shown | Range membership function from _DEFEND_RANGES + _OPEN_RANGES |
| **Multi-street EV calculation** | Analyst estimates | Backward induction from river → flop with assumed ranges |
| **ICM fold/call thresholds** | Not computed | ICM calculator with pay structure from tournament headers |
| **"What should I study" prioritization** | Analyst judgment | EV-weighted leak ranking + recurrence detection |
| **Exploit vs GTO classification** | Analyst judgment | Population frequency database + villain archetype matching |
| **Decision tree per leak** | Not shown | Static lookup table per leak category |
| **Session-over-session trend** | Partially (skill band) | Persist watchlist values, diff against previous session |
| **Board texture impact on c-bet** | Computed but dormant | Wire board_texture into c-bet decision analysis |

### Fundamentally needs human judgment:

| Task | Why it can't be automated |
|------|--------------------------|
| **"Was this exploit correct against THIS villain?"** | Requires real-time read assessment |
| **"Is this pattern real or sample noise?"** | Requires statistical intuition beyond CI |
| **"What's the biggest thing holding this player back?"** | Requires coaching experience |
| **"Should I change this habit or is it a feature?"** | Requires understanding player's style goals |
| **Writing the narrative session read** | Requires synthesis of 50+ data points into coaching prose |
| **Identifying non-obvious leaks** | Pattern recognition across hands that no single detector catches |

---

## Coverage Summary

| What | Coverage | Automation Level |
|------|---------|-----------------|
| Parsing (extract fields) | 100% of hands | Fully automated |
| Mistake/punt detection | 100% of hands scanned | Fully automated (but ~20% false positive rate) |
| EAI equity | 10-15% (showdown all-ins only) | Fully automated |
| Variance classification | All-in hands | Fully automated |
| Coaching rules | 100% of hands | Fully automated (5 rules only) |
| Pre-fill verdicts | ~50% of candidates | Fully automated |
| Analyst review | ~5-8% of hands | Manual (Claude Chat or human) |
| Appendix rendering | 30-60% of hands | Fully automated |
| Session narrative | 0% automated | Manual (analyst writes) |

**The gap:** The pipeline is strong on DETECTION (finding what's wrong) and
CLASSIFICATION (categorizing the error). It's weak on EXPLANATION (why it's
wrong in context), CORRECTION (what the right play was), and TRAINING
(how to not repeat it). These are the coaching spine improvements in the
GEM_Next_Improvements_Spec.md.
