# TRUE_POSITIVE_EVIDENCE_CARDS

Bounded one-pass analyst review of the genuinely-new `flop_cbet_sizing` candidates, using **only** each
emitted atomic decision record and its referenced chart excerpt (no raw files reopened, no operand
recomputed). Corpus: in-worktree real-structure fixtures (see the data-availability caveat in the package
report). Every cited number is a key of the sealed record.

---

## Card 1 — CONFIRMED_MISTAKE · `TM91000015:flop:20`

**Decision (decision-time facts, no runout):** Hero in the **SB, out of position, heads-up**, is the preflop
aggressor. Flop **J♠ 7♥ 8♥** → archetype **middling_disconnected, OOP**. Made hand: **high_card** (A-T high).
Pot before action **27.9 bb**. Hero c-bets **61.18 bb — all-in — = 217% of pot** (`chosen_incremental_bb
61.18`, `became_all_in true`, `eff_stack_bb 61.18`).

**Canonical reference (`evidence_ref: chart.flop_cbet_sizing_band`):** the COMPLETE middling_disconnected OOP
sizing band is **`[85]`% of pot** (single sanctioned size; `gto_texture_archetypes.json`, Dave 2026-05-13).

**The exact decision error:** the c-bet size is **217% of pot vs a single sanctioned 85% size — over-band by
132 pp and > 2× the only correct size**, and it commits Hero's entire 61 bb stack into a 28 bb pot with a
non-made hand. This is a gross over-size / over-commitment, not a defensible mix (a single-target complete
band admits no second size).

**Better action:** size the flop c-bet toward **85% of pot (~24 bb)**, retaining stack and fold-equity
geometry; do not turn a marginal-equity OOP c-bet into an all-in overbet.

**Why result-independent:** the verdict is computed from the decision-time chosen size vs the canonical band
only. No card after the flop, no showdown, no net result, and no prior verdict enter the judgment (confirmed
by `semantic_audit`: 0 leaks). The conclusion is identical whether the hand won or lost.

**Evidence tier:** `CHART_BACKED`. **Severity:** gross. **Routing:** required.

---

## Card 2 — READ_DEPENDENT · `TM90000006:flop:12`

**Decision:** Hero **IP**, preflop aggressor, flop **2♥ 7♦ 4♣** → **low_ragged, IP**, made hand a pair (JJ
overpair). Hero c-bets **36.9% of pot**.

**Canonical reference:** low_ragged IP band **`[50,100]`% (dual-strategy)** — the chart sanctions **two**
sizes (a half-pot and a pot bet) at high frequency.

**Assessment:** 36.9% is **13.1 pp below** the smaller sanctioned size (50%). Because the band is
**dual-strategy**, the detector does **not** auto-confirm: a modest under-size on a dry low board can be a
deliberate small range-bet. Clearing vs confirming this exact spot needs the analyst's read on whether the
37% bet was an intentional small-bet line — so the terminal verdict is **READ_DEPENDENT**, not a mistake.

**Better action (if a leak):** size toward the **50%** sanctioned floor of the band. **Evidence tier:**
`CHART_BACKED`. **Severity:** moderate. **Routing:** optional.

---

## Reviewer's note

The pilot surfaced **one** new result-independent confirmed mistake on this corpus (Card 1), distinct in kind
from the v8.20 confirmed mistake (KQs SB preflop flat) — a **postflop sizing** error. Card 2 demonstrates the
detector's restraint: a dual-strategy band correctly down-grades a moderate deviation to analyst judgment
rather than manufacturing a confirmed mistake. This is the precision-first behaviour the charter requires.
