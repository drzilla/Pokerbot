# V821_SIZING_LINES_NEXT_IMPLEMENTATION_PLAN

## Posture: STOP AT THE GREEN SYNCHRONIZED BASELINE

The synchronization is complete and green, and the only unambiguous, safe slice — the
`cbet_chart_applies` SRP/heads-up/non-all-in gate folded into the one canonical aggregate path — is **already
implemented and verified** (`test_sizing_line_pilot.py` 25/25; renders in a real v8.20-synchronized report).
Per the requirement matrix, **every other capability is BLOCKED_BY_CANONICAL_INFRASTRUCTURE or
DEFER_BEYOND_V821.** No further implementation slice qualifies as both safe and unambiguous, so this run
**does not open any new sizing/line family** (Stage-6 guard honored). Expansion is held behind the owner
decisions below.

This is consistent with the parked deep validation: per-hand sizing produced **0 confirmed mistakes on 3,609
real hands**; the archetype band is range-level and cannot prove an individual-hand mistake without invented
equity/range; and v8.20's new `unresolved`/no-node routing reinforces that a per-hand sizing candidate would
route to debt, not `required`.

## Smallest-safe-slice analysis (why nothing else ships now)

| Candidate next slice | Blocker | Verdict |
|---|---|---|
| Turn/river/3BP/4BP sizing judgment | no chart owner (`gto_texture_archetypes.json` is flop-cbet only) | BLOCKED — needs a canonical chart |
| Second family (turn double-barrel / "wrong barrel") | needs villain continue-range / fold-equity → invents range/equity or leaks result | BLOCKED — affirm the hard lock |
| Per-hand sizing verdict | needs a canonical decision node + analyst verdict; 0/3,609; routes to `unresolved` | BLOCKED |
| Multiway / pot-type sizing dimensions | no MW/3BP/4BP bands | BLOCKED |
| Surface raw chips/BB · SPR · pre/post pot copy | safe but descriptive-only; not authorized as v8.21 scope and risks per-hand framing | DEFER |
| Descriptive (non-verdict) "Lines" sequence view | overlaps Runout Transition; needs ownership decision | DEFER |
| Population-vs-theory baseline | no field baseline data | DEFER |

A genuinely safe *descriptive* enrichment (e.g. show chips/BB + SPR alongside the existing aggregate signal)
is the **most plausible future slice**, but it (a) is not in the current charter, (b) edges toward per-hand
framing, and (c) should wait on Owner Decision #1. Recommended sequence **if** later authorized:
1. canonical data contract (read-only consume `action_ledger`/`spr`/`eff_stack_bb`) →
2. deterministic display model (no new derivation) →
3. provenance/trust invariants (descriptive, "not a verdict") →
4. (skip detector/analyst/packet — descriptive only) →
5. report copy under the existing aggregate signal →
6. responsive →
7. tests →
8. real-report evidence.

## Owner decisions required (present, do not unilaterally resolve)

1. **Per-hand sizing evidence vs aggregate-only.**
   - Alternatives: (a) stay aggregate-only (gated); (b) invest in per-hand confirmability.
   - **Recommended: (a) aggregate-only.** Consequence of (b): 0/3,609 confirmed historically; every candidate
     now routes to `unresolved`/debt (never blocks ANALYST_COMPLETE) and must carry an
     `ONEPASS_TO_REPORT_VERDICT` enum + a resolvable `decision_id`; high false-precision risk.

2. **Preflop all-in / commitment eligibility ownership** (overlaps the v8.20 preflop-owner debt).
   - Alternatives: (a) assign a v8.21 owner now; (b) keep deferred to the existing preflop-owner thread.
   - **Recommended: (b) keep deferred.** Consequence of (a): scope creep; an all-in c-bet is both
     sizing-deviation and stack-off, and the c-bet gate could wrongly exclude valid voluntary jams.

3. **Range-reasoning boundary / second family.**
   - Alternatives: (a) affirm the hard lock — none; (b) open a turn/line family.
   - **Recommended: (a) affirm the lock** until a result-independent owner rule exists. Consequence of (b):
     hindsight/result-leak in teaching copy; silent broadening into range/EV/runout coaching.

4. **Large `REAL_*.json` evidence in-tree (~9k-line `REAL_CANDIDATE_QUEUE.json` et al.).**
   - Alternatives: (a) keep committed as audit evidence; (b) archive externally + link from
     `CORRECTED_CLAIM_MATRIX.md` / `V03_DEEP_VALIDATION_PACKAGE.md`.
   - **Recommended: (b) prune from tree + archive** — but **not unilaterally in this sync** (no work lost
     without owner sign-off). Kept committed for now; flagged here.

5. **Do a Stage-6 slice now vs stop at green baseline.**
   - **Recommended: stop at green baseline** (this plan). Reopen only behind decisions #1–#3.

## Doc hygiene to apply (ADAPT_TO_V820, non-blocking)

- Reconcile `AGGREGATE_CLOSEOUT_PACKAGE.md` "+235L" → true net **+41L**.
- Confirm the superseded banners on the per-hand-era `v03_pilot/` docs remain accurate post-sync.
(These are documentation reconciliations, not code changes; safe to apply or defer.)

## Definition of done for this run (met)

Synchronized onto v8.20.0 with all baseline gates green, parked work preserved, fixed defects not
reintroduced, no v8.20 functionality duplicated, true remaining scope reconstructed, and no speculative
feature opened. Branch ready to commit (deliverables) and push (branch only — no merge to `main`, no tag
change, no release).
