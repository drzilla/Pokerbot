# GEM v8.20.0 — Release State & Authority

**Release:** v8.20.0 (final) · **Runtime base:** v8.19.0 · **Report schema:** v8.12.0
**Date:** 2026-06-24
**Lineage:** v8.20.0-rc → v8.20.0 (the candidate passed the private Claude Chat retest unchanged; `-rc` dropped, no product logic changed at finalization — only the version stamp + release metadata).

## Release authority

Authorized for merge/tag/release by the project owner after an independent
verification of the **real private Claude Chat retest** artifacts (a live
2026-06-22/23 session: 1127 NLH hands across 10 tournaments). All six retest gate
categories were verified directly against the generated packet, analyst output,
report, manifests and telemetry — **not** against the chat's prose verdict:

1. **Runtime identity** — release `v8.20.0-rc`, runtime base `v8.19.0`, source
   commit `802b7a69355c` (run manifest == packet manifest == report footer).
2. **Inputs reconcile** — 15/15 sources classified (0 skipped/failed); 1127 hands /
   10 events all HH-backed + financially resolved; reproducibility flags true.
3. **Full run** — sealed packet: 17 gradable `required` (all canonical nodes) + 10
   `unresolved` (no-node debt) + 8 optional; `zero_analyst_calculations_required`,
   no semantic failure, no future-info leak.
4. **Analyst output** — schema-valid, bound to the packet+session; 17/17 required
   graded exactly once; 0 unresolved graded; optional cap (8) respected; no
   independent analyst math.
5. **Quick run** — one `--quick`, final state `ANALYST_COMPLETE`, all forbidden
   quick-stage counts 0, packet/output binding valid.
6. **Final report** — 10 Results rows (one per event), 0 invented exits, financial
   reconciliation clean (0 contradictions/orphans/duplicates), 0 dead anchors
   (300 links resolve), 0 page-level mobile overflow at 360/390/430, identity
   labels reconcile.

## What v8.20.0 delivers (over the v8.19.0 baseline)

- **Required-review split** — no-canonical-node hands route to an explicit
  `unresolved`/engineering-debt population; `required` is purely gradable; the
  completeness owner + coverage gate exclude the same set; coverage reconciliation
  proves `legacy == required + unresolved`.
- **Self-contained Chat package** — the lean runtime bundles the exact `phevaluator`
  evaluator (NLH tables; ~30 MB Omaha `.dat` excluded); exact equity with no pip
  install / network (proven with site-packages stripped).
- **Identity reconciliation** — one build identity across run manifest, report
  footer, sealed packet and package MANIFEST, with a labelled three-SHA block.
- **Production invariants / metadata** — de-hardcoded coverage reconciliation
  (session-agnostic sb_flat invariant), fixed dead `sec-SL` anchors, identity line.
- **Mobile Results** — grouped-aggregate stays a compact scroll table; `.od-row`
  grid track `minmax(0,1fr)` removes the 360px page overflow.

## Deferred to v8.21+ (known debt, not a v8.20.0 blocker)

- **Per-hand bet-sizing/line mistake discovery** — the v8.21 sizing-line pilot
  (separate worktree) found **0 confirmed per-hand mistakes** on 3609 real hands →
  kept aggregate-only ("Sizing & Line Patterns"). No per-hand candidate enters the
  analyst queue.
- **Universal preflop forced/involuntary all-in eligibility owner** + exhaustive
  steal / 3-bet / 4-bet / squeeze / exploit integration (carried from v8.19 RC3).

## Rollback

- The previous production baseline is **v8.19.0** at `905e0c6e2ef5` (tag `v8.19.0`).
- To roll back: `git checkout v8.19.0` (or reset the deployed runtime to the
  v8.19.0 lean bundle). v8.20.0 changes no v8.19.0 product behavior, so a rollback
  loses only the trust-efficiency / packaging / mobile fixes above.

## Production Claude Chat

The production Claude Chat instructions are **not** modified automatically by this
release. Upload the final artifact manually (see the release package's upload list).
