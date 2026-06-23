# V821_SIZING_LINES_CLOSEOUT_REPORT

Finalization and packaging of the Pokerbot v8.21 **Sizing & Lines** feature on the released v8.20.0 baseline.

## Business capability delivered

Pokerbot now tells the player when their **flop bet sizing is repeatedly too large or too small** on a board
class, so they can fix a real recurring habit — without unreliable hand-by-hand judgments. It analyzes only
**heads-up, single-raised-pot, non-all-in flop c-bets**, compares them to the proven canonical sizing bands,
and surfaces an **aggregate** over-sizing / under-sizing pattern with a clear adjustment.

### Example player lesson (from a real session)

> **Flop c-bets off-size on middling disconnected boards (IP)** — high confidence · aggregate · *bets too small*
> **What:** On middling disconnected boards in position, your flop c-bets were repeatedly **too small** — 3 of 3
> were off the proven sizing band. You bet around 33–60% of pot where the band is 100%/125%/150%.
> **Why it matters:** Betting too small leaves value and protection on the table — you aren't charging draws or
> building the pot on boards where you hold the range advantage.
> **Adjustment:** Size your flop c-bets **bigger** — toward 100%/125%/150% of pot.
> *(Off-size on 3 of 3 eligible c-bets. Judged only on heads-up single-raised-pot non-all-in c-bets; multiway,
> 3-bet/4-bet and all-in bets are excluded. An aggregate habit, not a per-hand verdict.)*

## What was done this closeout

1. **Product wording finalized** (`gem_sizing_detector.build_sizing_leak_signals` + `gem_report_draft._emit_sizing_lines`):
   the section now states, in plain poker language, all seven required points — the pattern, how often, the
   **direction** (too large / too small, with a colored tag), the board/context bucket, the practical
   adjustment, the aggregate-not-per-hand framing, and the **excluded** situations. The no-signal state also
   explains what is judged and excluded. Report destination unchanged; `sec-SL` navigation valid.
   The over/under direction is computed in the **detector** (it owns the comparison); the renderer only
   displays it — no renderer-side calculation.
2. **Documentation reconciled**: `V821_SIZING_LINES_FINAL_SCOPE.md` written as the single current authority;
   the stale `+235` footprint corrected (true: gate +41 → **+92/−19 across 3 files** with the closeout
   wording); per-hand pilot docs clearly marked **SUPERSEDED**.
3. **Obsolete pilot evidence archived**: 10 per-hand `REAL_*`/`PILOT_*`/`OPPORTUNITY_BASELINE` JSON files
   (~10.2k lines, 320,435 bytes) moved to an **external** audit ZIP outside the repo
   (`V821_SIZING_LINES_EVIDENCE_ARCHIVE.zip`, sha256 `f2d18af1f4b53b6406925524805933176bdaffc1dddd5c5c536da5ee42d901f6`)
   with per-file path/size/SHA-256/branch/commit + README, then removed from the tree. Active implementation,
   tests, requirements, sync reports, the safety tag, and the narrative that explains the accepted feature
   were **retained**.
4. **User-facing behavior verified** end-to-end on a real session + deterministic fixtures (over / under /
   no-signal rendered examples in `RENDERED_EXAMPLES.md`).
5. **Regression gates** all green (see `V821_SIZING_LINES_TEST_EVIDENCE.md`): `_test_scratch` 2024/2024,
   sizing 25/25, `verify_release` 0 canary / 0 regression, 278/278 anchors, analyst full + one `--quick`,
   Results 7×8 ALL_PASS, responsive 360/390/430 + 1280. Pre-existing failures (`test_detectors` 88/5,
   `test_report_draft` 67/3 pot-amount) proven unchanged.

## Production footprint (vs v8.20.0)

3 files, **+92 / −19**: `gem_analyzer.py` +8 (gate), `gem_sizing_detector.py` +67/−10 (gate + direction +
copy), `gem_report_draft/draft.py` +17/−9 (wording). `gem_discovery_context.py` / `gem_analyst_packet.py`
remain v8.20-authoritative; `build_sizing_leak_signals` / `gem_coverage_builder` wiring unchanged. No analyst
schema change; no per-hand candidate in the packet; no renderer calculation.

## Why no further Sizing & Lines development is currently justified

The feature is complete, green, and player-actionable. Every remaining capability is **blocked by missing
canonical reference owners** (no turn / river / 3-bet-pot / 4-bet-pot / multiway sizing bands —
`gto_texture_archetypes.json` is flop-c-bet only) or would require **range / equity / EV** that the trust
boundary forbids (per-hand verdicts, second "wrong barrel" family, multi-street line coaching). There is no
safe, unambiguous next slice; expansion would mean inventing a reference or leaking result/hindsight.

## Recommended next product workstream

Commission the **canonical sizing reference-band owner for turn / river / 3-bet-pot / 4-bet-pot / multiway**
(a coaching-charts/data effort, like the existing flop `gto_texture_archetypes.json`). That single dependency
is what blocks every Sizing & Lines extension; once it exists, the **same** aggregate engine and report
surface extend with no new trust risk. Do **not** start Range Reasoning or Runout Transition under this
workstream — they are separate, not-yet-authorized epics. If charts are not pursued, the next-best workstream
is a **descriptive (non-verdict) line-sequence view**, scoped to *describe* observed lines (barrel counts,
check-raise/bet-fold branches) without judging them, and only after deciding its ownership vs Runout Transition.
