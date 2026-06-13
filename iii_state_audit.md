Section III Shared-State Audit
==============================
Scope: _emit_section_iii() in sections_mistakes.py, lines 183-1449.
Purpose: trace every variable bound at function top; determine which
future segments (S2, S3, S4, S13) consume it; flag extraction blockers.

Result: **CLEAN SPLIT — no shared state crosses subsection boundaries.**
_compute_iii_state() is NOT needed.  Each sub-emitter takes (doc, s, rd, hands)
and computes everything from scratch, because that is already what the code does.


Variable inventory
------------------

### Header block (lines 188-232) — consumed by S2 ONLY

| Variable | Line | Source | Consumed by | Notes |
|----------|------|--------|-------------|-------|
| rev | 188 | rd['reviewed_mistakes'] | S2 header | local to header block |
| raw_mistakes | 189 | s['mistakes'] | S2 header | local |
| raw_n | 190 | len(raw_mistakes) | S2 header summary | local |
| needs_review_list | 191 | rev['needs_review'] | S2 header | local |
| auto_corrected_list | 192 | rev['auto_corrected'] | S2 header | local |
| needs_keys | 193 | set comprehension | S2 header | RECOMPUTED at line 240 for E2 block |
| auto_keys | 194 | set comprehension | S2 header | RECOMPUTED at line 241 for E2 block |
| survivors | 195-213 | filtered mistakes | S2 header | RECOMPUTED at lines 242-244 for E2 block |
| raw_punts_list | 201 | s['punts']['hands'] | S2 header | local |
| _analyst_pre | 202 | rd['analyst_commentary'] | S2 header | local; DIFFERENT from analyst_pre at line 295 |
| _analyst_iii1 | 203-204 | set of III.1 hand IDs | S2 header | local; DIFFERENT from analyst_iii1_ids (list) at 296 |
| _analyst_override | 205-207 | set of III.3/4/5 IDs | S2 header | local; DIFFERENT from analyst_iiix_override at 298 |
| clear_n | 214 | count of CLEAR survivors | S2 header | fallback for _confirmed_hdr |
| marginal_n | 215 | count of MARGINAL survivors | S2 header | local |
| _auto_punt_ids | 216 | set of auto-punt IDs | S2 header | local |
| punts | 217 | final punt count | S2 header | local |
| n_h | 220 | len(hands) or 1 | S2 header per-100 rates | local |
| _iii_conf | 224 | rd['discipline_tier'] | S2 header | local |
| _confirmed_hdr | 225 | canonical confirmed count | S2 header | local |
| summary_bits | 226-230 | list of header strings | S2 header | local |

Every variable above is consumed exclusively by the section header (doc.section
call at line 231-232) and the E2 confirmed-mistake type summary (lines 234-265).
None leak to III.1, III.2, III.3, or any later subsection.


### E2 confirmed-mistake type summary (lines 234-265) — consumed by S2 ONLY

Lines 238-264 RECOMPUTE raw_mist_iii, needs_keys, auto_keys, survivors,
_override_iii, clear_survivors from scratch — they do NOT read the header-block
variables.  Self-contained.


### III.1 Punts (lines 267-399) — consumed by S2 ONLY

| Variable | Line | Source | Consumed by | Notes |
|----------|------|--------|-------------|-------|
| _p_pre .. _total_iii1 | 270-284 | s['punts'] + rd['analyst_commentary'] | S2 | recomputed from scratch |
| p | 287 | s.get('punts', {}) | S2 | local |
| analyst_pre | 295 | rd['analyst_commentary'] | S2 | DIFFERENT variable from _analyst_pre at 202 |
| analyst_iii1_ids | 296-297 | list | S2 | list, not set; different from _analyst_iii1 |
| analyst_iiix_override | 298-300 | set | S2 | different name from _analyst_override |
| auto_punt_hands_filtered | 301-302 | filtered list | S2 | |
| auto_punt_ids | 303 | set | S2 | |
| hands_by_id_ix | 304 | {id: hand} | S2 | also available as s['_hands_by_id'] |
| auto_punt_by_id | 306 | {id: punt} | S2 | |
| iii1_ids | 327-333 | ordered list | S2 | |

All recomputed from (s, rd, hands).  Zero dependency on header block.


### III.2 Confirmed Mistakes (lines 401-479) — consumed by S2 ONLY

Lines 410-437: all _cm_-prefixed variables recomputed from scratch.
_cm_mistakes, _cm_analyst, _cm_rev, _cm_needs, _cm_auto, _cm_clear,
_cm_clear_ids, _cm_detector_ids, _cm_analyst_only, _cm_total, _cm_n_h.
Zero dependency on header block or III.1.


### III.3 Strategic Leaks (lines 481-819) — consumed by S3 ONLY

| Variable | Line | Source | Consumed by | Notes |
|----------|------|--------|-------------|-------|
| persistence | 487 | rd['leak_persistence'] | S3 | |
| promoted_pre | 488 | persistence['current_leaks'] | S3 | |
| _synth_pre | 489 | analyst_commentary['__synthesis__'] | S3 | |
| _leaks_cmt_pre | 490 | _synth_pre['leaks'] | S3 | |
| _verdict_counts | 491-499 | dict of counts | S3 | |
| promoted | 510 | alias for promoted_pre | S3 | |
| csv | 511 | s['csv_row'] | S3 | captured by _leak_meta closure |
| core | 512 | s['core'] | S3 | captured by _leak_meta closure |
| cbet | 513 | s['cbet'] | S3 | captured by _leak_meta closure |
| _leak_meta() | 516 | closure | S3 | captures csv, core, cbet |
| _candidate_hands_for_leak() | 544 | closure | S3 | captures hands, s |

All data from (s, rd).  Two closures (_leak_meta, _candidate_hands_for_leak)
capture outer-scope variables — when extracted to a standalone function, these
closures must move with it and the captured variables (csv, core, cbet) must be
recomputed in the new function scope.  Straightforward.


### III.4 Cleared / Population Deviations (lines 821-960) — consumed by S13 ONLY

Lines 837-960: _analyst_iii3, pf_devs, hands_by_id all computed from (rd, s, hands).
No dependency on any earlier subsection.


### III.5 Read-Dependent Deviations (lines 962-1085) — consumed by S13 ONLY

Lines 968-1085: analyst, rd_quant, hands_by_id, rd_screen all from (rd, s, hands).
No dependency on any earlier subsection.


### III.6 Justified Variance (lines 1087-1094) — consumed by S13 ONLY

Three prose lines, no data.  Self-contained.


### III.7 Clinical Examples (lines 1096-1127) — consumed by S4 ONLY

clinicals from rd['clinical_candidates'].  Self-contained.


### III.8 Out-of-Bound Leak Discovery (lines 1129-1228) — consumed by S4 ONLY

ds from s['deviation_summary'], dev_ev from rd['deviation_evidence'].
Self-contained.  Contains _ev_slug() function and bucket_anchor dict with
hardcoded sec-xiii-1/2/3 anchors (will need anchor-map update in commit 5).


### III.9 Pokerbot's Picks (lines 1230-1448) — consumed by S4 ONLY

analyst_all from rd['analyst_commentary'], _bp_cands from rd['bestplay_screen'].
Self-contained.  Contains _ARCHETYPE_EMOJI dict, _REASON_RULES list,
_score_candidate() function.  Two _record_citation_explicit calls at
lines 1403 and 1440 with hardcoded 'sec-iii-8' anchor (update in commit 5).


Section II Split Audit (brief)
------------------------------
_emit_section_ii in sections_financial.py, lines 1273-1597.

Split point: line 1558 (blank line after II.2 KPI bluff preview).

S6 (Verdict & KPIs): lines 1273-1558.
  - Section header + II.1 Heuristic Cheat Sheet + II.2 Top-Line KPIs.
  - Self-contained: reads from s, rd, hands.
  - The bluff preview (lines 1548-1556) reads s['bluff_profile'] independently.

S7 (Mental Game, Bluff & Exploits): lines 1560-1597.
  - II.3 calls _emit_mental_game(doc, s, rd, hands) — already separate function.
  - II.4 Bluff Profile reads s['bluff_profile'] independently.
  - _emit_mental_game computes punts, confirmed counts from (s, rd, hands) —
    zero dependency on II.1/II.2 state.

Shared state: NONE.  _emit_mental_game is already a separate function that
takes (doc, s, rd, hands).  The bluff profile at lines 1565-1596 reads
s['bluff_profile'] from scratch.  Clean split at line 1558.


Conclusion
----------
Both splits (III into 4, II into 2) have ZERO shared-state coupling.

_compute_iii_state() is NOT needed — remove from the plan.

Each sub-emitter is a plain function(doc, s, rd, hands) with no pre-computed
state argument.  The monolithic functions were already modular in data flow;
they just happened to be in one function body.

Complication count: 0 blockers, 0 flags.
