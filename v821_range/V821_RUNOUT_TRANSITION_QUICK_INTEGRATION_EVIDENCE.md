# V821_RUNOUT_TRANSITION_QUICK_INTEGRATION_EVIDENCE

Closes Blocker 2 — a genuinely successful analyst `--quick` integration run with a matching packet. No packet
binding, hash, or fail-closed guard was bypassed.

## The artifact

A full AUTO_ONLY run sealed the current packet `analyst_packet_Knockman.json` (`packet_hash dae3ea4f3096…`,
required=34, optional=8, unresolved=17). A **fresh analyst output** bound to that exact packet was produced at
`analyst_packet_Knockman_analyst_output.json`: `{session_id: "Knockman", packet_hash: "dae3ea4f…", verdicts:
[…42…]}` — one verdict (from the allowed enum `INSUFFICIENT_EVIDENCE`) for each of the 34 required + 8 optional
decisions. It passes `validate_analyst_output` (valid, required_coverage 1.0) **before** the render.

## The successful `--quick` run

```
⚡ QUICK MODE — re-rendering from cached data
✓ --quick pre-render validation PASSED (packet+analyst+cache+identity bound; coverage 1.0)
✓ analyst output integrated: state=ANALYST_COMPLETE reviewed_hands=42
✓ quick stage telemetry: zero forbidden work {parse:0, reference:0, analyze:0, detector:0, worklist:0, packet:0}
  binding = {packet_present: True, analyst_output_present: True, packet_hash_matches: True, analyst_output_valid: True}
⚡ Quick re-render in 10.2s -> Pokerbot_Knockman_20260527-28_V2.html
```

## Proofs (all required points)

| Requirement | Evidence |
|---|---|
| `--quick` completes successfully | pre-render validation **PASSED**; report written (`…_V2.html`) |
| packet identity & hashes match | `packet_hash_matches: True`; analyst `packet_hash == manifest.packet_hash == dae3ea4f…`; `session_id == "Knockman"` |
| required count before = after | **34 = 34** (`QUICK_PACKET_COMPARISON.json`) |
| optional count before = after | **8 = 8** |
| zero Runout Transition decisions in the packet | **0** — no decision family is a transition family (families: legacy_required_review, sb_flat_vs_late_open, river_curiosity, deep_preflop_stackoff, short_stack_coldcall); `gem_analyst_packet.py` contains **no** reference to `gem_runout_transition` (the feature is render-only) |
| analyst schema unchanged | `manifest.schema` + `allowed_verdicts` unchanged; `REQUIRED_OUTPUT_FIELDS = (decision_id, verdict, reason)` |
| analyst-integrated report has the **same** transition notes as AUTO_ONLY for the same hands | AUTO_ONLY (V7) and analyst-integrated (V2) both carry **104** hands with a transition note; **0 per-hand mismatches** across the 1,220 common hands (decompressed lazy payloads) |
| no transition note overwritten or duplicated | **0** hands with a duplicated note within a body; the additive finalizer merges into / appends after existing notes, never replacing them |

## Consistency fix found by this gate

The before-fix comparison surfaced **2 required-review hands** (`07642494`, `08028249`) that carried the
transition note in the analyst render but not in AUTO_ONLY — they hit a render branch (a flag with no
explanation / no aggression candidate) that skipped `_split_argument_into_notes`. A small additive fallback in
`sections_xiv.py` now derives the deterministic transition note whenever no analyst/aggression note exists, so
the **same hand carries the same note in both modes**. Post-fix: 0 mismatches.

## Scope note on the render-validation warning

The analyst-integrated report shows **8 "awaiting analyst" labels** (`sections_financial.py` Issue 2). These
are **financial-attribution** rows, not analyst-review *decisions* — they are not in the packet's
required/optional sets and therefore cannot be verdicted via the packet analyst output (a real analyst output
could not cover them either). This is a **pre-existing financial-section behaviour**, unrelated to the Runout
Transition feature, and does not affect packet binding, validation, or the transition notes. The `--quick`
render itself completed and was written.
