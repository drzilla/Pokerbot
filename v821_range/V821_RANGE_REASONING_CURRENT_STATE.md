# V821_RANGE_REASONING_CURRENT_STATE

v8.21 **Range Reasoning** — first module **Runout Transition**. Branch
`feature/v8.21-range-reasoning-foundation` off `main` (`93637eb`); safety tag `v8.21-range-reasoning-base`.

> Subagent/workflow orchestration was unavailable this run (monthly spend limit); the audit + build were done
> directly. This is recorded for provenance — it does not affect the results below.

## What works (implemented + validated)

- **Deterministic Runout Transition module** `gem_runout_transition.py` — one result-independent transition
  record per eligible turn/river Hero decision: identity/decision-state, before→new→after board, deterministic
  transition tags, made-hand + draw before/after, outs/completed/busted, "what changed / what remained /
  reassess", and a compact player-facing render. Canonical owners only; no new evaluator; no analyst math; no
  range/equity; no future-information leakage; backdoors excluded from "real draw" logic.
- **Tests** `test_runout_transition.py` — **29/29** (blank/overcard/paired/flush/straight turns;
  double-paired/four-flush/board-pairing rivers; improves/draw-disappears/unchanged; HU/MW; SRP/3BP; IP/OOP;
  all-in suppression; incomplete evidence; no-leakage; mobile-safe rendering; strategic suppression).
- **Real-session pilot** — 3,609 hands → 654 turn/river decisions, **90% resolved**, descriptive output on 589,
  0 result leaks, 0 unsupported range claims, 0 analyst workload, ~0.4 s. Rendered examples in `RENDERED_EXAMPLES.md`.

## What is partial / designed (not yet wired)

- **Live report-surface integration** — designed precisely (seam `gem_report_draft/_hand_grid.py` per-street
  notes; additive, mobile-safe, preserves sticky headers / Board+Hero / Action / `sec-SL` / Results). Not wired
  this run: the v8.20 report is QA-gated and the validation harness was unavailable; wiring + a full green
  re-validation is the immediate next bounded step (`V821_RUNOUT_TRANSITION_IMPLEMENTATION_PLAN.md`).
- **Review/Drill hooks** — `transitions_for_hand(hand)` is consumable; Read-Sensitive Reconstruction is a later
  Review/Drill integration point.

## What v8.20 already provides (reused, not duplicated)

Static board texture (`gem_textures`, `_board_texture`), made-hand (`gem_parser.hand_strength_name`), draws
(`gem_made_hands.draw_profile`), decision snapshot / eff-stack / SPR (`gem_decision_snapshot`), pot-type /
position / players (`gem_parser`). The module **reuses** these and adds the *transition* (before→after) — it
does not rename static texture as a new feature.

## What is blocked (engineering debt, named)

- **Strategic recommendations** (continue/resize/slow/pivot/abandon) and any range/nut-advantage language —
  blocked by the absent canonical **opponent-range / fold-equity owner** (debt **D1**); rendered *Insufficient
  evidence*. Nut-blocker statements blocked (**D2**). See `V821_RANGE_REASONING_DEBT_REGISTER.md`.

## What requires an owner decision

1. Commission the canonical opponent-range/fold-equity owner (D1) to unblock the strategic layer — coordinate
   with the Sizing & Lines reference-band blocker (D3) under one decision.
2. Approve the (small, designed) live report-surface wiring of the descriptive block.
3. Confirm Read-Sensitive Reconstruction belongs in Review/Drill (not a standalone mode).

## No extra analyst-LLM time

The module is fully programmatic. Nothing enters the analyst packet; the one-pass analyst contract and schema
are unchanged; analyst workload added = **0**.
