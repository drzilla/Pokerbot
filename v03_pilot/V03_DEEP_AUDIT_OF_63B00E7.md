# V03_DEEP_AUDIT_OF_63B00E7

Independent audit of the first V03 pilot commit `63b00e7` (per-hand `flop_cbet_sizing` detector), its tests,
queue routing, packet output, semantic audit, and deliverables. Conducted without defending the prior
conclusion. **Three material defects found and corrected this run.**

## Verified-correct properties of `63b00e7`

| Property | Finding |
|---|---|
| Consumes canonical decision-time owners (no recreated calc) | **PROVEN** — sizing % from `hand['hero_bets']`; band from `gem_textures`; record sealed by `atomic_snapshot` (the two `gem_decision_snapshot` owners). No parallel pot/price/stack/SPR/equity/EV calc. |
| Atomic, zero-analyst-calculation records | **PROVEN** — `semantic_audit` `zero_analyst_calculations_required=true`, action line truncated at Hero's c-bet. |
| No result/showdown/future/net/prior-verdict leak in nomination | **PROVEN** — `_LEAK_KEYS` clean; `future_information_leaks=0`. |
| Candidate dedup `(hand_id, street, family)` + optional cap | **PROVEN** — unchanged; re-tested. |
| Dual-strategy band cannot auto-confirm | **PROVEN** — dual bands never graded `gross`. |
| Decision id resolves to the c-bet node | **PROVEN** — clean-single-c-bet gate. |

## Defect 1 (CRITICAL) — detector OWNED the terminal `CONFIRMED_MISTAKE` verdict

`review_value` mapped a `gross` sizing deviation directly to `CONFIRMED_MISTAKE`, which `build_packet`
promoted to `required` via `confirmed_ids`, and `run_value.metrics` counted as a confirmed new mistake —
**before any analyst review.** This contradicts (a) the explicit owner contract of the existing aggregate
detector ("a single off-size c-bet is never auto-graded as an error"), and (b) terminal-verdict ownership,
which must stay with the analyst/final-truth path for a degree-based sizing judgment (unlike the binary
owner-rule families such as SB 3-bet-or-fold).

**Correction:** `flop_cbet_sizing` now maps to `READ_DEPENDENT` with a `nomination_confidence` (gross=high,
moderate=moderate). The detector NOMINATES; the analyst owns the terminal verdict. Gross nominations are
force-routed to `required` review (so they are reviewed once) **without** being pre-confirmed
(`build_packet._force_required`). `run_value` now confirms **0** sizing mistakes by construction.

## Defect 2 (CRITICAL) — chart applied to nodes where it does not hold

The `gto_texture_archetypes.json` bands are calibrated for **heads-up, single-raised-pot, range c-bets**.
`63b00e7` applied them to **any** flop c-bet. Evidence: the prior "confirmed mistake" **TM91000015** is a
**3-bet pot** AND an **all-in** c-bet — an SRP range-c-bet chart was applied to a 3BP jam. All three fixture
c-bets are in fact **3-bet pots**.

**Correction:** `_chart_applies(hand)` fails closed unless `pot_type == 'SRP'`, the flop is heads-up
(`not multiway_flop` and `players_at_flop <= 2`), and the c-bet is **not** all-in (a jam is a
commitment/stack-off decision, not a free sizing choice). Result: the fixture corpus now yields **0**
candidates (correct — it is all 3BP), and the prior fixture "confirmed mistake" is retracted.

## Defect 3 (precision) — discrete-point matching over-nominated multi-size bands

A multi-size band (e.g. `[50,100]`, `[100,125,150]`) sanctions a **spread** of sizes for the range. The
`±10pp`-around-each-discrete-point test flagged an in-between compromise size (e.g. 75% vs `[50,100]`) as a
deviation, even though it sits inside the sanctioned spread. On the real corpus this over-nominated 4 of 33.

**Correction:** a size within `[min(band), max(band)]` of a multi-size band is treated as compliant; only a
size outside the whole sanctioned spread is a real off-band deviation. Real nominations 33 → 29.

## Special attention item (from the brief)

> "whether the detector itself is assigning CONFIRMED_MISTAKE before an analyst reviews the decision"

**Confirmed as the central defect (Defect 1) and corrected.** The detector no longer assigns
`CONFIRMED_MISTAKE`; terminal verdict ownership is restored to the analyst one-pass review path.

## Post-correction safety re-verification

- 40/40 targeted + adversarial tests pass (SRP/3BP/4BP, HU/multiway, IP/OOP, all-in, dual-strategy,
  within-spread, fail-closed, leakage, dedup, mutation/unresolved).
- `semantic_audit` over real records: `failing=0`, `future_information_leaks=0`,
  `zero_analyst_calculations_required=true`.
- No regression: `test_metrics` 533, `test_textures` 135, `test_lint` 48, `test_gtow` 58, `test_detectors`
  88/5 (the 5 are pre-existing on the clean tree).
