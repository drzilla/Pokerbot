# V821_RUNOUT_TRANSITION_IMPLEMENTATION_PLAN

## Done in this run (descriptive MVP)

| Step | Status | Artifact |
|---|---|---|
| 1. Canonical data contract | ✅ | `V821_RUNOUT_TRANSITION_CANONICAL_CONTRACT.md` |
| 2. Deterministic transition classifier | ✅ | `gem_runout_transition.py` (`build_transition`, `transition_tags`) |
| 3. Provenance / evidence-tier model | ✅ | per-fact `{source, tier}`; `V821_RUNOUT_TRANSITION_TRUST_MODEL.md` |
| 4. Report-data shape | ✅ (object) | `teaching_block(rec)` — the 5-part report-data object |
| 5. Compact street rendering | ✅ (function) | `render_html(rec)` — mobile-safe block; **live wiring = next step (below)** |
| 6. Analyst-packet exposure | ✅ **not needed** | nothing flows into the packet (0 analyst workload) |
| 7. Review/Drill hooks | deferred (designed) | `transitions_for_hand(hand)` is consumable by Review/Drill later |
| 8. Tests | ✅ | `test_runout_transition.py` — **29/29** |
| 9. Real-report evidence | ✅ | pilot 589/654 real decisions + rendered examples |

## Stage-5 integration design (live report wiring — next bounded step)

**Seam (audited):** `gem_report_draft/_hand_grid.py` ≈line 417 — "Build notes per street and attach to hero
action on that street." The per-street note list on the turn/river Hero action is the attach point.

**Plan (additive, low-risk):**
1. In the per-street note build, for `street in ('turn','river')`, call
   `gem_runout_transition.build_transition(hand, hero_action_index_for_that_street)`; if resolved, append
   `render_html(rec)` (or feed `teaching_block(rec)` to the existing note renderer) as one compact note under
   the existing per-street commentary — **after** Board+Hero context and the Action column, before any sizing
   note. Skip silently when `unresolved` (no empty block).
2. Reuse the existing register styling so the `Factual` / `Insufficient evidence` chip matches the page.
3. Preserve: sticky street headers, Board+Hero context, Action column, desktop/mobile nav, the `sec-SL`
   sizing section, and Results — the block is additive within an existing street row and uses no fixed pixel
   widths (mobile-safe, proven in tests).

**Why deferred in this run:** the live report path is v8.20-authoritative with extensive QA gates
(`_test_scratch` 2024, `_qa_seven_fixture_results`, `_qa_mobile_360_overflow`, 278-anchor validation). Wiring
must land **with** a full green re-validation; the multi-agent validation harness was unavailable this run
(monthly spend limit), so the wiring + its regression sweep is the immediate, well-scoped follow-up rather
than a partially-validated change to the shipped report. The MVP module is fully implemented and validated
independently; the wire is mechanical.

## Strategic recommendation layer (blocked)

`planning_implication ∈ {continue, resize, slow_down, pivot, abandon}` is **not** implemented — each requires
the opponent's continuing range + fold-equity (no canonical owner). It renders *Insufficient evidence* and is
recorded in `V821_RANGE_REASONING_DEBT_REGISTER.md`. Do not implement these labels without a documented
canonical owner + acceptance rule.

## Order for the follow-up

1. Provide the canonical opponent-range/fold-equity owner (debt D1) — unblocks the strategic layer.
2. Then add rule-backed `continue/resize/...` implications (Coaching register) with per-rule owners + tests.
3. Wire the descriptive block into `_hand_grid.py` (above) + full report re-validation.
4. Later: Read-Sensitive Reconstruction hooks in Review/Drill.
