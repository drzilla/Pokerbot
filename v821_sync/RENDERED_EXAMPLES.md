# V821 Sizing & Lines — final player-facing rendered examples

Rendered through the canonical `gem_report_draft.draft._emit_sizing_lines` fed by the production `gem_sizing_detector.build_sizing_leak_signals`. Deterministic fixtures; no renderer-side calculation.


## REPEATED UNDER-SIZING (bets too small)

**Detector signal:** direction=`under` · signals=1 · trigger=`flop c-bet sizing off-reference (too small) on 8 of 9 sized c-bets (11% within ±10pp of 100%/125%/150%) on middling disconnected boards IP`

**Player-facing section (rendered, tags stripped):**

```
## Sizing & Line Patterns
*Each item below is a repeated flop c-bet sizing habit across a whole board class — an AGGREGATE pattern, not a per-hand verdict. The example hands are evidence, not graded mistakes.*
*Judged only on **heads-up, single-raised-pot, non-all-in** flop c-bets. Multiway pots, 3-bet and 4-bet pots, and all-in bets are excluded from sizing judgment (no proven reference band applies).*
Flop c-bets off-size on middling disconnected boards (IP)high confidence · aggregatebets too smallWhat: On middling disconnected boards IP, your flop c-bets were repeatedly too small: 8 of 9 were off the proven sizing band. You bet around 33% of pot where the band is 100%/125%/150%.Why it matters: Betting too small here leaves value and protection on the table -- you are not charging draws or building the pot on boards where you hold the range advantage.Adjustment: On middling disconnected boards IP, size your flop c-bets bigger — toward 100%/125%/150% of pot.Off-size on 8 of 9 eligible flop c-bets (11.0% within the band) · example hands: 8
```


## REPEATED OVER-SIZING (bets too large)

**Detector signal:** direction=`over` · signals=1 · trigger=`flop c-bet sizing off-reference (too large) on 8 of 9 sized c-bets (11% within ±10pp of 25%) on ace high dry boards IP`

**Player-facing section (rendered, tags stripped):**

```
## Sizing & Line Patterns
*Each item below is a repeated flop c-bet sizing habit across a whole board class — an AGGREGATE pattern, not a per-hand verdict. The example hands are evidence, not graded mistakes.*
*Judged only on **heads-up, single-raised-pot, non-all-in** flop c-bets. Multiway pots, 3-bet and 4-bet pots, and all-in bets are excluded from sizing judgment (no proven reference band applies).*
Flop c-bets off-size on ace high dry boards (IP)high confidence · aggregatebets too largeWhat: On ace high dry boards IP, your flop c-bets were repeatedly too large: 8 of 9 were off the proven sizing band. You bet around 75% of pot where the band is 25%.Why it matters: Betting too large here bleeds chips and folds out the weaker hands you actually want to keep in the pot.Adjustment: On ace high dry boards IP, size your flop c-bets smaller — toward 25% of pot.Off-size on 8 of 9 eligible flop c-bets (11.0% within the band) · example hands: 8
```


## NO SIGNAL / INSUFFICIENT EVIDENCE

**Detector signal:** direction=`—` · signals=0 · trigger=`(none)`

**Player-facing section (rendered, tags stripped):**

```
## Sizing & Line Patterns
No repeated flop c-bet sizing leak was found this session. This judges only your heads-up, single-raised-pot, non-all-in flop c-bets against the proven sizing bands — multiway pots, 3-bet/4-bet pots and all-in bets are excluded. It does not imply perfect play — 1 board class(es) had too thin a sample to judge and were set aside.
```
