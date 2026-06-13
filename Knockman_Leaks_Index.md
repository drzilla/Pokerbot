# Knockman Leaks Index

A living document of recurring leak patterns identified across sessions. Each entry includes the structural signature, examples from session data, the EV cost when triggered, and the actionable fix. Coaches and Claude reference this file during session reviews.

---

## L1 — BB-CR-Pattern: x/r flop → multi-street commit when equity dies

**First identified:** 2026-05-12 session (TM5945923397, TM5946055701, TM5944954984; -135.6 BB combined)
**Coaching tier:** Dave (K-series no-SDV binary), Jaka (postflop range construction)
**Detector status:** Specification draft; not yet coded.

### Structural signature
1. Hero defends BB vs single PFR open
2. Flop hits a draw-related texture (FD, OESD, 2-flush board with backdoors)
3. Hero check-raises flop with semi-bluff or value
4. Villain calls (call range is now pair+/draw-heavy, narrowed but not eliminated)
5. Turn card changes equity distribution (FD busts, FD completes against Hero, board pairs into villain's range, scare overcard)
6. Hero overcommits on turn or river: barrel 75%+ pot or jam with insufficient equity vs villain's calling range

### Why the leak persists
The check-raise polarizes Hero's perceived range. On a subsequent street, a check by Hero reads as abandoned-bluff to the pool (sticky MTT calling tendencies), so Hero feels compelled to barrel. But the pool's actual fold-frequency to a 75% turn barrel after x/r is 20-25%, while the math requires 43%+. Pool calls wider than GTO suggests, especially after x/r telegraphs strength.

### Examples
| Hand | Holding | Texture | Turn event | Action | EV cost |
|---|---|---|---|---|---|
| TM5945923397 | 36s | 8d-2d-3c (NFD + bottom pair) | Js bricks FD | 75% turn barrel → river jam no SDV | -50.1 BB |
| TM5946055701 | 35s | 5c-Jh-3h (bottom 2pr, 2-flush) | Th completes 3-flush | Jam turn with 9% equity vs flushes | -48.1 BB |
| TM5944954984 | 87o | 6h-5c-6c (OESD, paired) | 5d double-pairs board | Triple-barrel to river K-high bluff | -37.4 BB |

### Fix framework (applied during session)

**Pre-x/r plan (mental checklist before clicking x/r flop):**

| Turn type | Planned action |
|---|---|
| Equity-completing (FD/SD hits) | 65-75% bet (commit narrative) |
| Brick (draw alive, equity preserved) | 50% bet OR x/c — depends on villain frequency |
| **Equity-killing (FD busts, board changes to favor villain)** | **x/c-small or x/f, NEVER barrel** |

If all three branches can't be articulated confidently → do not x/r → flat-call instead.

**Sizing rules:**
- Flop x/r: cap at 2.2-2.5x. Larger x/r commits Hero to turn barrel by SPR alone.
- Turn after x/r: if planned bet would put SPR < 1 (commit-to-river), switch to x/c or smaller bet.
- Build a thin-value x/r range (sets, TPGK, 2-pair occasionally) so future-check range includes strong hands.

**K-series binary (Dave):** when SDV = 0 and turn equity is dead, choices are JAM (if FE > required) or CHECK-FOLD. Never half-barrel — burns chips without committing to either branch.

### Detector spec (v7.49+ candidate)
Trigger: position=BB, stack 30-80bb, action_sequence contains "x/r flop" AND ("barrel turn ≥65%" OR "jam turn" OR "barrel river ≥65%") AND went_to_sd=lost. EV-loss threshold: ≥25 BB. Coaching tag: L1.

---

## L2 — "Scared Poker" / "No Foreplay": premature commit to avoid post-flop play

**First identified:** 2026-05-12 session (named by Ron)
**Coaching tier:** Dave + Amit (N4 value-sizing rule), this index builds on N4
**Detector status:** Conceptual; signature too broad for a single detector. Tracks via verdict pattern.

### Structural signature
1. Hero has a hand with value/protection concern
2. Prior action gives Hero comfort the hand is "ahead-but-vulnerable"
3. Instead of bet-sizing for max EV across multiple streets, Hero jams the current street
4. Jam concentrates risk into one decision and forfeits future-street EV extraction
5. Often loses to villain's value range that wouldn't have called multiple smaller bets

### Mechanism
Emotion-driven sizing escalation. "I want this over" + "what if villain draws out" = compressed multi-street decisions into a single-bet jam. The cost is two-fold:
- Lost EV from villain's marginal value-hands that fold to a jam but call a half-pot bet
- Concentrated variance — a single jam swings EV more than three smaller bets averaging the same total

### Examples
| Hand | Spot | Better line | Cost of jam |
|---|---|---|---|
| TM5944926324 | JJ x/r-AI flop in satellite vs 3-bettor | x/c flop + reassess turn | -95 BB |
| TM5946055701 | 35s turn jam with 2-pair on 3-flush turn | Bet 55% turn, fold to raise | (counted under L1) |

### Fix framework

**Practice prompts (build during decision-making):**

1. **Alternative-line check:** before any planned jam, force one explicit alternative: "If I bet half-pot instead, what does villain do with each part of his range?" If half-pot extracts more from at least one range component (typically marginal value-hands), default to half-pot.

2. **Boring-sizing rule:** in spots where adrenaline pushes toward all-in, deliberately downsize one notch (pot → 75%, 75% → 50%, 50% → 33%). The downsize captures more pool calls without meaningfully sacrificing FE — the FE curve is flatter than emotion suggests.

3. **Amit/Dave N4 inversion (codified):** "If you'd jam for value, you can also bet small for value." The corollary: if your half-pot bet wouldn't extract value, your jam isn't a value bet either — it's a protection-bet or fear-bet that should be reconsidered.

### Related rules
- N4 (Amit) — value sizing default; bet-small alternative
- N6 (Amit) — flop CR for value; size up (CR is the opposite spot from L2)
- N7 (Amit) — bluff sizing; name the fold target
- N11 (Amit) — deep stack philosophy; size up before scare cards

---

## L3 — Multi-way 3BP over-jamming: ignoring villain's prior action

**First identified:** 2026-05-12 session (TM5946402276, TM5944037855; -96 BB combined)
**Coaching tier:** Dave (range-narrowing protocol)
**Detector status:** Specification draft.

### Structural signature
1. Multi-way preflop pot (3+ players)
2. One villain has performed action that caps their range to premium (flat-of-squeeze, flat-of-3-bet, cold-call of 3-bet at deep stacks)
3. Hero faces a 4-bet or 5-bet jam decision
4. Hero jams a marginal hand (77, ATs, AJo, KQs) treating the spot as heads-up math
5. The capped villain calls; Hero is dominated by the call range

### Why it persists
The 3-way+ structure dilutes the "read" feeling — Hero focuses on the most recent aggressor (the squeezer or 3-bettor) and underweights the caller's range narrowing. The flatter caller's range is functionally AA/KK/QQ in most pools at MTT mid-stakes.

### Examples
| Hand | Spot | Action | Cost |
|---|---|---|---|
| TM5946402276 | 77 HJ 40bb 4-bet jam after CO 3-bet + UTG flat | UTG flat = capped to JJ+/AK | -39.6 BB |
| TM5944037855 | ATs MP 57bb 4-bet jam after SB squeeze + UTG flat | UTG flat-of-squeeze = AA/KK/QQ | -56.7 BB |

### Fix framework

**Multi-way 3BP cancellation rule:**

When two villains have acted and one has called/flatted, treat that flatter's range as the binding constraint. Hero's decision is no longer "vs the aggressor" — it's "vs the strongest range among continuing villains."

Range-narrowing checklist before any jam in multi-way 3BP:
1. What is the aggressor's range?
2. What is the flatter's range AFTER the aggressor acted?
3. **What range continues vs my jam?** (typically the flatter's range, not the aggressor's)
4. What is my equity vs THAT range, not vs the aggressor's range?

Pool tendency: flat-of-squeeze and cold-call-of-3-bet are 80%+ value in MTT mid-stakes pools. AA/KK/QQ flat with the intent to trap. JJ/AKs sometimes. Bluffs essentially zero.

### Detector spec (v7.49+ candidate)
Trigger: hand has ≥2 PF aggressors AND ≥1 caller of the most recent aggressor AND Hero performs 4-bet+ jam. Compare Hero's hand to typical flat-of-aggression range. Flag if equity < 30%. Coaching tag: L3.

---

## L4 — Polar-3-bettor x/r OOP with second-best: never raise dominated hands vs narrow ranges

**First identified:** 2026-05-12 session (TM5944926324, JJ flop x/r-AI sat; -95 BB)
**Coaching tier:** Dave (range-narrowing), Jaka (postflop construction)

### Structural signature
1. Hero is OOP vs a deep-stack 3-bettor (95bb+)
2. Hero has a strong-but-second-best hand (JJ, QQ when villain reps AA/KK; TT vs KK+/AK range)
3. Flop comes low/dry favoring Hero's perceived range
4. Hero attempts to "rep strength" with x/r
5. Villain's 3-bet range is narrow enough that x/r folds out only the hands Hero beats; calls/raises with the hands that beat Hero

### Heuristic
**When opponent's range is narrow and polar, never raise your second-best holdings.** Either call-down or fold. Raises only work when opponent's range has BOTH bluffs to fold AND value to fold — at deep-3-bet ranges, both are absent.

### Action map for JJ in 3BP OOP at deep stacks
- **4-bet/fold pre** (preferred vs polar 3-bettors)
- **Fold pre** (legitimate vs tight 3-bettors; JJ dominated by ~60% of range)
- **Flat + x/c-down line** (acceptable but punishing OOP)
- **NEVER x/r postflop on low/dry boards** — folds out only AK/AQ (which you beat), keeps in AA/KK/QQ (which crush you)

---

## L5 — Low-dry IP HU under-c-bet: missed range-bet target

**First identified:** 2026-05-13 session (TM5949704704 A3s CO 8-3-7r, TM5950042242 QJo BTN 6-8-3r; Hero c-bet 1 of 3 HU-IP-PFR low-dry-rainbow spots = 33% vs 60-80% target)
**Coaching tier:** Dave (Q-series IP-as-PFR range betting)
**Detector status:** Tracking-only — small per-session sample (3-5 hands typical). Needs cross-session aggregation.

### Structural signature
1. Hero opens or 3-bets as PFR
2. Caller flats — heads-up to flop
3. Hero IP, opponent OOP
4. Flop is low-dry: unpaired, top card ≤ 8, NOT three-connected (low_straight catches connected ones)
5. Texture examples: 8-3-7 rainbow, 6-8-3 rainbow, 7-2-5 rainbow, 8-4-2 two-tone
6. Hero checks back instead of c-betting

### Why the leak persists
Low-dry rainbow IP HU is a classic range-bet target: Hero's PFR range hits the flop better than caller's flat range (more overpairs, more A-high, more aceX kickers). C-betting small (B25-B33) prints chips from villain's marginal-pair-fold + bluff-fold range. Checking back surrenders range advantage and lets villain realize equity with marginal holdings (small pairs, gutshots, overcards).

Pool tendency: floats wider than GTO IP-caller-vs-IP-cbet rate suggests on these boards, so c-bet works as both value and folding-equity collector.

### Examples (2026-05-13)
| Hand | Holding | Pos | Texture | Action | Verdict |
|---|---|---|---|---|---|
| TM5949704704 | A3s | CO IP | 8-3-7 rainbow | check back | Miss — pair + overcard with BDFD |
| TM5950042242 | QJo | BTN IP | 6-8-3 rainbow | check back | Miss — overcards + BDFD |
| TM5949860960 | QJo | CO IP | 2-6-8 rainbow | c-bet ✓ | Correct (the 1 of 3 Hero hit) |

### Fix framework
**IP HU low-dry rainbow as PFR → default range-bet small (B25-B33)** with:
- All value (overpairs, top pair+, sets) — small for protection
- All pair-equity hands (any pocket pair below top card)
- Backdoor-flush hands (any 2-card with BDFD)
- Overcards with backdoor anything (KQ, AK, QJ with BDFD)

Only check back: hands with **zero equity / zero showdown / zero blocker value** (very rare on these boards) and the rare slow-played monster (mixed strategy, ~10% of overpair combos).

### Cross-references
- Q-series Dave (range betting in HU SRP) — same target band 60-80%
- Aligned with GTO Wizard low-dry textures: B33 range bet for ~95% of opener range

### Promotion criteria
Promote from "tracking" to "active leak" when:
- ≥2 sessions show <50% c-bet rate on HU-IP-PFR-low-dry-rainbow with n≥3 each, OR
- Single session n≥8 with <40% c-bet rate

---

## Index integration with Quick Reference

Quick Reference v7.49 cross-references this file via `L1`-`L4` tags. Pre-flight checklist (PREFLIGHT-3, new in v7.49): before classifying any bust or large mistake as cooler/punt/read-dependent, check whether it matches any L1-L4 signature. Pattern-matched busts route to III.1 punt with L-tag note rather than I.7 cooler, regardless of pair-over-pair shape, when the LINE itself was -EV before villain's specific cards mattered.

---

## Roadmap (post-2026-05-13)

- L1 detector spec → code in v7.49.1
- L3 detector spec → code in v7.49.1
- L5 tracking metric (low-dry IP HU c-bet rate) → already surfaced via V.1 GTO Texture Compliance per-archetype table; promote to active leak after 2+ sessions confirm
- L5 candidate (deferred): Late-session decision quality drift (busts cluster in late sessions per 2026-05-12 data; need 3+ sessions to confirm) — RENUMBER to L6
- L6 candidate (deferred): Re-entry bullet decision-quality decay (per-bullet ROI dropped meaningfully on re-entries; not enough data) — RENUMBER to L7
