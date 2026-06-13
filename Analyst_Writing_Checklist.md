# Analyst Writing Checklist

Read this **before** writing any `session_analysis_*.json` entry. Saves
hours of rendering, reading, and rewriting downstream.

---

## 1. Hand-strength labels — verify on the actual board, don't assume

**Top pair kicker:**
- Top kicker (A→K, K→Q, Q→J, J→T, T→9, etc): **TPTK**
- 2nd-3rd kicker: **TPGK**
- Otherwise: **TPWK**

Example: AhJh on As6s7s → **TPGK** (J kicker; K and Q rank above)

**Flush count on board** — literally count same-suit cards:
- **Monotone flop**: 3 same-suit on flop
- **3-flush**: 3 same-suit total on board (one-card flush possible)
- **4-flush**: 4 same-suit on board (one-card flush very common)

Example: As6s7s flop = 3-flush. + Ts turn = 4-flush.

Verify on the actual hand-id board cards before writing. Not from memory.

---

## 2. Range definition — always required, format scales with width

**Narrow ranges** (3BP, 4BP, opens, raised pots) — spell out structure:

> BB 3-bet range vs MP at 37BB: QQ+/AK value, JJ-99/AQ value+protect,
> AJs/KQs/A5s-A2s bluff inclusions. ~50-65 combos.

**Ultra-wide ranges** (open-limps, very-wide BB defends, BvB unraised)
— compressed threshold format:

> SB limp range: AJs+/AQo+/TT+ opens, 86o- folds, everything else limps.

Don't describe ranges with prose blobs. Use **combo counts**,
**value/protect/bluff buckets**, or **threshold cutoffs**.

The rule isn't "always describe in detail" — it's "always define, use
compressed format when the range is too wide to list combos".

---

## 3. Narrow the range street-by-street

For verdict-driving spots with multi-street action (especially 3BP+):

```
Starting range
   → fold to flop c-bet  → narrowed flop call range
   → fold/call/raise turn → narrowed turn range
   → river action         → final range
```

**Math vs the NARROWED final range, not the starting range.**

By a turn jam in a 3BP, villain's range is often 10-20% of his 3-bet
starting range. Equity vs starting range vs narrowed range can differ
20-30pp — verdicts flip on that gap.

---

## 3b. Pot-odds vs equity — show the arithmetic (REQUIRED)

Ron review 2026-05-26. For **every call/fold decision facing a bet or
jam**, and every **draw-continuation** decision, the argument MUST show
the arithmetic. A verdict of "+EV" / "-EV" / "-EV across all ranges" is
**not valid** unless the two numbers behind it are on the page. Asserting
the conclusion ("near-dead", "drawing thin", "crushed") without the math
is the bug this section exists to kill — it is the analysis, not flavour.

**Three lines, always — keep them compact (§7 still caps the argument):**

1. **Price → required equity.** State the call amount and the pot being
   called, in BB; compute `required_eq = call / (pot_after_call)`.
   > Call 26.4 BB into 59.4 BB → 2.25 : 1 → **need 30.8%**.

2. **Hero's equity — give the range, not a point estimate.** Best case
   and worst case, then the realistic blend vs villain's *narrowed*
   range (§3). For a one-card draw use `outs / 46` (turn→river) or
   `outs / 47` (flop→turn); name how many outs are dead in the worst
   case (villain holding them) vs live in the best case.
   > Nut-flush draw: best 9/46 = **19.6%**; worst (villain holds 2) 7/46
   > = **15.2%**; villain's jam range is flush-heavy → realistic ~16-18%.

3. **Compare + state the chip-EV.** Required vs actual, and the EV of the
   call vs folding in BB. The verdict line follows from this.
   > 16-20% < 30.8% → call is **-EV by ~6-13 BB**. III.2.

**Bounty adjustment** — when the spot is a PKO/bounty hand AND winning
eliminates a covered villain (villain all-in, Hero covers or is at risk
for the full stack), apply the bounty credit: required equity drops
(~8pp rule of thumb per the ~1.1-BI bounty factor, or compute it). State
both the raw and bounty-adjusted requirement — a call can be -EV on
chips but +EV with the bounty, and the verdict must reflect the right
one.

If a strength word appears ("thin", "dead", "crushed"), the number sits
next to it. No exceptions for "obvious" spots — obvious spots have short
math, not absent math.

---

## 4. Blockers — name specific combos, not buckets

When narrowing, identify the specific 2-card combos Hero blocks. "AK"
alone is wrong: **AKcc / AKdd / AKhh / AKss** are four distinct combos,
each with different board interactions.

Example: Hero AhJh on As6s7s3s board.
- Blocks AhKh, AhQh (Hero has Ah) → AK-hearts and AQ-hearts gone
- Blocks J♥-broadway hearts combos (KhJh impossible since Hero has Jh)
- Does NOT block AKcc, AKdd, AKss
- Villain "AK 6 combos starting" → realistically ~4 in line given board

State the surviving combo count, not the starting count.

---

## 5. Range protection / MDF — verdict input for capped Hero

For any fold/call where Hero's range is capped:

1. Compute equity vs narrowed villain range
2. **Also** compute: if Hero folds this combo, what % of Hero's remaining
   range folds with it?
3. If folding TPGK = folding 80%+ of remaining range, the call is forced
   by MDF — villain can profitably auto-barrel ATC if Hero overfolds.

GTOW's "100% call" frequencies on TPGK at SPR <1 in 3BPs aren't about
the equity math being profitable in isolation. They're about range
protection.

---

## 6. Verdict labels — attribute to evidence

- **I.7 Cooler**: GTO-mechanical play, ran into rare dominating combo
- **III.1 Punt**: chip-EV-negative with no strategic justifier
- **III.3 Cleared**: auto-flag overridden, line was standard
- **III.4 Read-dependent**: valid logic but only +EV vs specific reads
- **III.5 Justified**: deliberate +EV exploit (capped lead, population)

Reclassifications attribute to **evidence** ("GTOW shows 100% call freq"),
not to "Ron asked" or "Ron's request". The evidence drives it.

---

## 7. Concision rules — argument ≤ 300 words

- No tournament name (heading shows it)
- No level (meta-line shows it)
- No chip amounts (BB only — heading shows stack)
- No restating positions or grid action (grid shows it)
- One math line, one verdict line — but for any call/fold/draw spot
  that one math line MUST carry the pot-odds vs equity numbers (§3b)
- Range definitions **structured** (combo counts, buckets), not prose

---

## 8. Output formatting — structured argument (REQUIRED)

Every `argument` MUST be written as a structured block, not a prose
blob. The renderer (`_emit_structured_note`, B146) detects this format
and renders TL;DR + headers + bullets; a plain-prose argument falls
back to an unreadable blob.

Required shape:

```
**TL;DR:** 2-4 dense lines — the verdict and the single reason, up front.

### <Section header>
* one bullet per distinct logical thought
* bold the key metric / rule / range fact

### <Section header>
* ...
```

Rules:
- The argument MUST begin with `**TL;DR:**` (no text before it).
- Use `### ` headers and `* ` bullets — never a multi-line paragraph.
- 2-3 sections. Pick headers that fit the verdict:
  - III.2 mistake → `The Leak` / `The Fix` / `Why III.2, Not a Punt`
  - III.3 cleared → `Villain's Range` / `Why It's Cleared`
  - I.7 cooler → `The Matchup` / `Why It's Structural`
  - III.4 read-dependent → `The Spot` / `The Read That Decides It`
- Still obey §7: ≤300 words total, no chip amounts, no tourney name.

---

## 8b. Synthesis leak judgments — structured callout form (REQUIRED)

B169 (Ron 2026-05-24, anti-blob spec). The
`__synthesis__.leaks[<name>].judgment` field MUST be written as scannable
callout blocks — **not** a prose paragraph. The renderer
(`_emit_analyst_judgment`) emits a multi-line judgment verbatim under an
`**Analyst judgment:**` lead-in; a single-paragraph blob falls back to
sentence-splitting (legacy behaviour — avoid producing it).

Required shape — 3–6 callout paragraphs, one blank line between each:

```
🧐 **<2-4 bold keywords>:** one to three sentences.

🔴 **<2-4 bold keywords>:** one to three sentences.

🛠️ **<2-4 bold keywords>:** one to three sentences.
```

Rules:
- Each callout opens with an emoji + a **2–4 bold-keyword anchor** + `:`.
- **No callout exceeds 3 sentences.** If it would, split it into two.
- One callout per distinct facet of the verdict. Typical facets:
  sample/CI verdict, recurrence, direction, status, action / pipeline-fix.
- §7 still applies — ≤300 words, no chip amounts, no tournament name.
- Suggested emoji vocabulary (consistency matters more than the glyph):
  🧐 sample / statistics · 🔴 recurrence / red signal · 🧭 direction ·
  ⚠️ caveat · 🔀 cross-reference · 🛠️ status & action · 🔧 pipeline-fix.

This is the same anti-blob principle as §8 (no wall-of-text), applied to
the synthesis layer: structural splits and bold anchors over prose.

---

## 9. Pokerbot's Picks — III.8 (well-played hands)

III.8 is the only **positive** verdict section: well-played hands,
recognised for decision quality. Result-agnostic — a Pick is awarded
on the decision, never the river.

Pipeline → analyst handoff:
- The analyzer screens hands STRUCTURALLY into the `bestplay_screening`
  bucket of `analyst_candidates_*.json` (premium hand in a 3-bet+ pot,
  multi-street pressure lines, ICM-phase 4-bet+ pots). Screening only
  surfaces candidates — it does NOT award a Pick.
- The analyst curates the final **5-10** and assigns each ONE of the
  six framework archetypes. A screened hand with no archetype assigned
  is NOT a Pick — drop it.

The six archetypes (from Pokerbot_Picks_Framework):
- **Sick Call** — calling multi-street pressure with weak absolute
  strength, correct blocker/unblocker read on a polarized villain.
- **Sick Fold** — laying down a strong made hand vs a fully
  value-polarized line where MDF no longer applies.
- **Great Value Extraction** — sizing/pacing that extracts max from a
  second-best hand (geometric lines, threshold-targeting overbets).
- **Great Bluff** — folding out a structurally better hand via an
  asymmetric nut-advantage representation.
- **Trap-Door Play** — a deliberate passive line (check / flat) with a
  premium to induce bluffs or manufacture a squeeze cascade.
- **Macro/ICM Leverage** — deep deviation from chip-EV for tournament
  pay-jump pressure (max bubble pressure, or a big dollar-EV fold).

Entry format — same structured rules as §8. Required keys:
`verdict` MUST start with `III.8`; add an `archetype` key with the
exact archetype name. The argument MUST be result-agnostic — no
mention of chips won or the runout. If the play is read-dependent,
say so and name the read; include a short "Risk Acknowledged" section
when the line is also a known leak in the wrong configuration.

---

## Worked reference — what a good entry looks like

For Hand 68009180 (AhJh MP, vs BB 3-bet, called flop and turn-jam on
As6s7s3s8s, lost to AKdd):

The good entry defines BB's PF 3-bet range, defines Hero's PF flat
range (capped, no QQ+/AQs+/AKo), describes flop c-bet as range-bet
(board smashes 3-bet range), narrows BB's turn jam range with explicit
blocker work (Hero's Ah, Jh block specific combos), reaches **equity
vs narrowed range** (~35-42%, not the wrong-but-tempting 12-15% vs
starting range), invokes MDF/range-protection as the verdict driver,
and attributes I.7 reclassification to GTOW's 100% call frequency.

Total argument length: ~250 words. No tournament name, no chip
amounts, no restated grid action.

---

## 10. Card notation in prose — B250 lint rule

The renderer emits every card as a `<span class="card ...">` pill with a
unicode suit glyph. The **B250** lint test rejects raw card text that
bypasses this pipeline. Two patterns trip the lint:

- **Raw board strings** — 3+ space-separated card tokens on a bullet line
  (e.g. `Ks 5d Kd 8d 2h`). Write descriptive text instead:
  "a paired-King board with three diamonds" or "K-5-K-8-2 (three diamond)."
- **Concatenated hands** — 4-char rank-suit-rank-suit tokens (e.g. `AhTh`).
  Write rank-only: "A-T suited" or "ATs" (chart notation is fine — the lint
  distinguishes 3-char chart tokens like `ATs` from 4-char raw cards).

**Safe formats:**
- Chart notation: `AKo`, `T7s`, `99` — these are 2-3 chars; lint ignores them.
- Rank-only descriptive: "ace-ten suited", "A-T suited", "pocket sevens."
- The renderer auto-pills cards in table cells; this rule applies only to
  prose `argument` text on `* ` bullet or `- ` list lines.

**Rule of thumb:** if you're typing a suit letter (`c/d/h/s`) after a rank
in the argument text, stop and rephrase.


## 11. Sizing % and street anchoring — match the rendered grid (W-PCT / W-NOTE-STREET lints)

Two lints (v8.12.8) compare your prose against the action grid the reader
sees. Fix the prose when they warn — never the grid.

- **Sizing percentages must match the rendered action.** The grid computes
  every bet/raise as % of the live pot (e.g. "4.2BB into 4.6BB (91%)").
  If you write "bet turn 75%" the W-PCT lint checks 75 against the turn's
  rendered sizings (±2pp). Don't quote bucketed defaults (33/50/75) from a
  detector fact — read the per-street numbers in `_pot_odds.per_street`
  (the worksheet carries them for every bet-facing hand since v8.12.8) or
  the grid itself.
- **File notes under the street they describe.** A note anchored on FLOP
  must not narrate the turn ("bet turn 75%, won" under FLOP trips
  W-NOTE-STREET). Split multi-street narration: one note per street, each
  anchored to Hero's action on that street. Future-tense planning ("plan:
  if the turn pairs, bet") is fine — narration of what happened is not.
- **OVERBET callouts:** when `_pot_odds.per_street` marks `is_overbet`,
  say so explicitly and quote the required equity — an overbet call is the
  spot eyeballing fails worst (handover Issue 1: a 117%-pot call needing
  35.1% was cleared as "roughly pot-sized").

## 12. Preflop range context — never bare "Wide BB Defend"

A preflop verdict label without range logic teaches nothing (QA 2026-06-12,
65955000). Every preflop defend/open/3-bet comment names:
- the matchup + sizing + effective depth ("BB vs BTN 2.0x at ~27bb eff"),
- whether the hand is in/out/mixed in the relevant chart family
  (BB_DEF_*/3BF_*/SQF_* — quote the chart name the detector used), and
- one sentence of WHY (price + position + bounty/ICM modifier if any).
If no chart covers the spot, say "no chart coverage at this depth" —
do not improvise a range claim.
