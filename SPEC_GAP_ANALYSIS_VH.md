# Spec Gap Analysis — Claude_Task_Make_Villain_Hand_Details_Helpful.md

**Date:** 2026-06-08
**Baseline:** v8.8.6 (post hid-format fix + enriched yellow notes)

---

## Spec Section: Core product rule

| Requirement | Status | Evidence |
|---|---|---|
| Don't show read prominently unless it answers one of 6 questions | DONE | 4-bucket model: A/B prominent, C evidence, D collapsed |
| If we can't answer, collapse | DONE | passive_read = collapsed "Opponent note" |

## Spec Section: Required mental model (4 concepts)

| Concept | Status | Evidence |
|---|---|---|
| 1. Villain Evidence | DONE | atoms_by_hand, evidence_text, signal |
| 2. Read / Archetype | DONE | read_states, primary_read, dimensions |
| 3. Exploit Opportunity | DONE | exploit_opportunities, 8 detectors |
| 4. Hero Verdict | DONE | auto_verdict, exploit_outcome |
| "These must not be blended" | DONE | Separate bucket rendering for each |

## Spec Section: Hand-detail output requirements (4 buckets)

### Bucket A — Exploit Miss
| Field | Status | Notes |
|---|---|---|
| Villain: alias + V-code + archetype | DONE | "Brick . V01 . Nit / Rock" |
| Read available before decision | DONE | "Read timing: Known before Hero acted" |
| Read signal | DONE | "Read signal: Villain overfolds..." |
| Recommended exploit | DONE | via so_what |
| Hero action | DONE | "Hero action: Hero folded A7o from HJ" |
| Why missed | DONE | via evidence_text |
| Next time | DONE | "Next time: Open-raise..." |

### Bucket B — Good Exploit
| Field | Status | Notes |
|---|---|---|
| Villain + read | DONE | |
| Read timing | DONE | |
| Hero action | DONE | |
| Why good | DONE | |
| Next time / repeat rule | DONE | "Next time: Correct -- Laser overfolds..." |

### Bucket C — Villain Evidence Collected
| Field | Status | Notes |
|---|---|---|
| Villain + V-code | DONE | "Eagle . V118" |
| Street | DONE | "Street: Turn" |
| Signal | DONE | |
| Context text | PARTIAL | Shows via "What it suggests" but not raw context_text |
| Read impact | PARTIAL | Not shown in JS modal; shown in yellow notes |
| So what | DONE | |
| "not necessarily a Hero mistake" | DONE | Disclaimer renders |

### Bucket D — Passive Read
| Field | Status | Notes |
|---|---|---|
| Small/collapsed | DONE | Collapsed "Opponent note: ..." |
| No big coaching block | DONE | |

## Spec Section: Required "So What?" field

| Read type | so_what present | Source |
|---|---|---|
| Nit / Rock | DONE | SIGNAL_COACHING['repeated_blind_overfold'] |
| Loose Passive | DONE | SIGNAL_COACHING['open_limp'] + others |
| Sticky Passive | DONE | SIGNAL_COACHING['weak_showdown_call'] |
| Aggressive | DONE | SIGNAL_COACHING['passive_aggro_pivot'] |
| Passive -> Aggro Pivot | DONE | SIGNAL_COACHING['passive_aggro_pivot'] |

## Spec Section: Street-level Note / Pivot learning

| Requirement | Status | Notes |
|---|---|---|
| Badge in action grid | DONE | ❗ Note / ⚠ Pivot in XIV.B hand listings |
| Badge in grid cells (at action_index) | PARTIAL | Code exists but action_index mismatch prevents grid-cell placement; badges appear in section listings instead |
| Yellow note: signal label | DONE | "Multiway Donk" |
| Yellow note: Villain line (alias . V-code . position) | DONE | Deduped |
| Yellow note: Action (trigger_action) | DONE | "Action: donk-bet turn" |
| Yellow note: What it suggests | DONE | |
| Yellow note: So what? | DONE | |
| Yellow note: Actionable now? | DONE | |
| Yellow note: Read impact | DONE | "Read impact: Loose Passive +2" |

## Spec Section: Same-hand timing requirement

| Timing state | Status | Evidence |
|---|---|---|
| Known before hand | DONE | "Known before Hero acted" |
| Created earlier in same hand | DONE | "Detected earlier in this hand, before Hero decided" |
| Created after Hero decision | DONE | Timing gate downgrades to evidence |
| Future-only evidence | DONE | "Timing unclear -- evidence note only" |
| Exploit only if read was available before | DONE | All 8 exploits = "Known before" |

## Spec Section: Required UI placement

| Location | Status |
|---|---|
| 1. Action grid (short pills) | DONE |
| 2. Yellow notes under street | DONE (post hid-format fix) |
| 3. Opponent Adjustment block near top | DONE (one-liner + detailed) |
| 4. Passive read collapsed | DONE |

## Spec Section: Required data fields

### From evidence atoms
| Field | Status |
|---|---|
| villain_alias | DONE |
| villain_key | DONE |
| signal | DONE |
| signal_label | DONE |
| dimension | DONE |
| strength | DONE |
| context_text | DONE |
| evidence_text | DONE |
| read_impact | DONE |
| hero_involved | DONE |
| same_hand_actionable | DONE |
| available_before_action_index | DONE |
| street | DONE |
| action_index | DONE |
| villain_position | DONE |
| detail_status | DONE |
| trigger_action (spec: "Add if missing") | DONE (already existed) |
| actionable_timing (spec: "Add if missing") | DONE (= default_timing) |
| suggested_adjustment (spec: "Add if missing") | DONE (= so_what) |
| so_what (spec: "Add if missing") | DONE |
| supporting_read_label (spec: "Add if missing") | NOT ADDED — atom doesn't carry the resolved read label; available via read_states lookup at render time |

### From exploit opportunities
| Field | Status |
|---|---|
| villain_alias | DONE |
| read_label / exploit_read_label / exploit_read_display | DONE |
| hero_decision_street | DONE |
| hero_action | DONE |
| villain_read_before_decision | DONE |
| recommended_exploit | DONE |
| auto_verdict | DONE |
| exploit_outcome | DONE |
| severity | DONE |
| evidence_text | DONE |
| read_source | DONE |
| exploit_type | DONE |
| so_what (spec: "Add if missing") | DONE |
| next_time_rule (spec: "Add if missing") | DONE (via _EXPLOIT_COACHING default_timing + so_what) |
| read_available_before_decision (spec: "Add if missing") | DONE (via timing classification) |

## Spec Section: Acceptance tests

| Test | Status | Verification |
|---|---|---|
| A: Missed exploit from Matrix | PASS | TM6040061399: coaching block with all fields |
| B: Good exploit | PASS | TM6039960264: coaching block with reinforcement |
| C: Evidence-only hand | PASS | TM6039026432: evidence block, no Hero verdict |
| D: Street-level note | PASS | Yellow notes with 7 fields after enrichment |
| E: Passive read irrelevant | PASS | Collapsed, avg 2.9/hand |
| F: Timing / no future evidence | PASS | All 8 exploits "Known before Hero acted" |

## Remaining minor gaps

1. **supporting_read_label on atoms** — Spec suggests adding this field; not critical since it's available via read_states lookup at render time. Could add in v8.9.0 if LLM analyst layer needs it.

2. **Grid-cell badge placement** — The `action_index` in atoms uses a filtered index (preflop non-post actions) while the grid renderer uses the full action ledger index. Badges appear in section listings but not at the exact grid cell. This is a known index-alignment issue; fixing it requires refactoring detector indexing.

3. **Bucket C context_text** — The JS modal shows "What it suggests" (from SIGNAL_COACHING) but not the raw `context_text` field (e.g., "Tracker called river and showed third pair"). The raw context adds hand-specific detail. Could add as a "Context:" line in the evidence block.
