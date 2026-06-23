# V821_SIZING_LINES_FINAL_SCOPE

The single current authority for the Pokerbot v8.21 **Sizing & Lines** workstream. Supersedes the per-hand
pilot documents in `v03_pilot/` (kept for audit, banner-marked superseded).

## The completed feature (locked)

**Aggregate flop c-bet sizing leak detection.** Pokerbot tells the player when their **flop bet sizing is
repeatedly too large or too small** on a given board class, so they can fix a real recurring habit — without
Pokerbot making unreliable hand-by-hand judgments.

Behavior (locked):
- analyze **eligible heads-up, single-raised-pot, non-all-in flop c-bets**;
- **exclude multiway, 3-bet-pot, 4-bet-pot and all-in** situations from sizing judgment;
- compare sizing against the **existing canonical reference bands** (`gto_texture_archetypes.json` via
  `gem_textures`); no new bands invented;
- identify **repeatable aggregate over-sizing or under-sizing** patterns (per board archetype × IP/OOP);
- explain the practical adjustment in plain poker language;
- state explicitly that this is a **recurring-pattern signal, not proof that one individual hand was a mistake**.

## Business value

The player learns a **bankable habit fix**: e.g. "on middling dynamic boards in position you keep c-betting
~33% when the proven sizing is 100–150% — bet bigger." That is a recurring leak worth real chips, surfaced
without the false precision of grading individual hands.

## Why per-hand was rejected

A per-hand sizing verdict produced **0 confirmed mistakes across 3,609 real hands**: the archetype band is a
**range-level** reference and cannot prove an individual hand was a mistake without inventing range/equity.
Per-hand candidates also now route to the v8.20 `unresolved`/debt population, never to `required`. The
aggregate altitude is the correct and only reliable one.

## Report wording contract (all seven points present — see `RENDERED_EXAMPLES.md`)

The "## Sizing & Line Patterns" section states, per signal, in plain poker language:
1. **what** sizing pattern was observed (board class + IP/OOP);
2. **how often** it occurred ("off-size on N of M eligible flop c-bets");
3. **direction** — too large or too small (explicit text + a colored tag);
4. **which** eligible board/context bucket;
5. the **practical adjustment** (bet bigger / smaller, toward the band);
6. that it is an **aggregate leak, not a per-hand mistake** (intro + per-signal framing);
7. **what was excluded** (heads-up single-raised-pot non-all-in only; multiway, 3-bet/4-bet, all-in excluded).
The no-signal state also explains what is judged and excluded ("insufficient evidence", never "perfect play").
Report destination unchanged; `sec-SL` navigation anchor valid (fixed in v8.20).

## Out of scope (not added)

per-hand sizing verdicts · turn or river sizing judgments · multi-street line coaching · range/equity/EV
calculations · speculative "wrong barrel" logic · renderer- or analyst-created calculations. The "**Lines**"
half beyond flop sizing is **deferred**.

## Blocked by missing canonical reference owners

Turn, river, 3-bet-pot, 4-bet-pot and multiway sizing remain **blocked** — `gto_texture_archetypes.json` is
**flop-c-bet only**; there is no canonical reference band owner for those contexts, so judging them would mean
inventing a reference. A second family (turn double-barrel / "wrong barrel") is blocked because confirming it
needs villain continue-range / fold-equity (invents range/equity or leaks result).

## Trust boundary (enforced)

- **parser/analyzer** owns observed action, pot, stack, sizing facts;
- **canonical engines** own deterministic derived values (`gem_textures` bands, `gem_decision_snapshot`);
- the **analyst may not** invent sizing, pot, price, range, equity or EV operands;
- the **renderer may display but not derive** strategic operands — the over/under **direction** is computed in
  the detector (`gem_sizing_detector`), the renderer only displays it.

## Production footprint (vs released v8.20.0)

3 files, **+92 / −19**:
- `gem_analyzer.py` **+8** — folds the SRP/HU/non-all-in gate into `_gto_sizing_pct` (sizing dimension gated,
  c-bet frequency denominator untouched);
- `gem_sizing_detector.py` **+67 / −10** — `cbet_chart_applies` gate + over/under direction + player-facing copy;
- `gem_report_draft/draft.py` **+17 / −9** — player-facing wording, direction tag, exclusions note, empty state.

(The stale `+235` figure was the removed `summarize_offband_sizing` aggregate; the surviving gate was +41,
finalized at +92/−19 with the closeout wording.) `gem_discovery_context.py` and `gem_analyst_packet.py` remain
v8.20-authoritative; `build_sizing_leak_signals` and `gem_coverage_builder` wiring unchanged.

## Production chain (single, canonical)

```
gem_parser hero_bets → gem_analyzer._gto_sizing_pct [GATE cbet_chart_applies]
  → gem_textures.aggregate_compliance → gem_sizing_detector.build_sizing_leak_signals
  → gem_coverage_builder report_data['sizing_leak_signals']
  → gem_report_draft._emit_sizing_lines  "## Sizing & Line Patterns" (anchor sec-SL)
```
No per-hand candidate enters the analyst packet; no analyst schema change; no renderer calculation.
