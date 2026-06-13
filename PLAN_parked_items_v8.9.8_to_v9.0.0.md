# GEM Parked Items — Implementation Plan (v3, reviewed)

**Date:** 2026-06-10
**Current version:** v8.9.7
**Codebase:** GEM MTT Analyzer — a Python pipeline that parses poker hand histories, runs exploit/evidence detectors, generates per-hand coaching verdicts, and renders an HTML report.

---

## Implementation Rules

**Before coding P1-C**, implement conservative/table-size-aware position normalization. When in doubt, cap confidence at MARGINAL. Never upgrade confidence because of a fuzzy chart match.

**Do not improvise.** If required fields are missing or ambiguous, fail soft by lowering confidence or skipping the candidate. Do not invent thresholds, detector rules, bounty adjustments, ICM adjustments, or renderer text. Every new helper must be covered by at least one positive and one negative regression test.

**After each phase, run this verification sequence:**
1. `python -m py_compile` on every touched file
2. Run `_test_scratch.py` targeted tests for the phase
3. If targeted tests pass, run full regression (`_test_scratch.py` end-to-end)
4. Generate one sample HTML report from a real session
5. Manually verify:
   - No PLO hand in analyst-needed surfaces
   - No all-in-preflop hand in postflop mistake buckets
   - No deterministic villain text appears when rejected by analyst (Phase 4)

---

## Architecture Overview (for context)

The pipeline runs in this order inside `gem_analyzer.py __main__`:

1. **Parse** — `gem_parser.py` reads hand history text files → list of hand dicts
2. **Analyze** — ~40 inline detector loops in `gem_analyzer.py` classify each hand (mistakes, punts, coolers, exploits, reads, etc.)
3. **Equity** — `gem_eai_equity.py` runs Monte Carlo equity simulations for all-in hands
4. **Opponent profiler** — `gem_opponent_profiler.py` builds villain VPIP/PFR/AF stats
5. **Villain intel** — `gem_villain_intel.py` extracts evidence atoms + exploit opportunities per villain
6. **Coverage gate** — determines which hands need analyst verdicts
7. **Candidate emission** — builds the analyst worksheet (lines 8794–10558, currently inline)
8. **Render** — `gem_report_draft/` package builds the HTML report from `stats` + `report_data`

Key files:
- `gem_analyzer.py` (~621K, 11,500+ lines) — the monolith; detectors, pipeline, `__main__`
- `gem_villain_intel.py` (~109K) — villain evidence atoms + exploit detection
- `gem_analyst_villain.py` (~22K) — LLM analyst handoff scaffolding (exists, partially built)
- `gem_report_draft/sections_xiv.py` (~139K) — V25 hand details rendering + per-hand coaching context builder
- `gem_report_draft/_html.py` (~330K) — HTML/JS/CSS template + modal rendering
- `gem_report_lint.py` — QA lint rules (board-contradiction checks, etc.)
- `Poker_Ranges_Text.txt` (~100K) — 405 GTO charts including REJAM position-dependent ranges
- `_test_scratch.py` (~183K) — 571 regression tests

Governance rules:
- Renderer must not create analytical facts — `Suggests:` and `So what?` come from existing context fields only
- `--analyst-file` must NOT be placed inside the HH input directory
- No new detectors or threshold changes without explicit approval
- PLO hands must be quarantined from NLH-calibrated detectors

---

## Phase 1 — Detector Fixes (v8.9.8)

**Goal:** Fix four independent detector bugs that produce wrong verdicts. All can be implemented in parallel — no dependencies between them.

**Estimated effort:** ~1 day

---

### P1-C: Reshove detector — add opener range gate

**Severity:** P1 — produces HIGH-confidence wrong auto-verdicts that would ship to analyst

**What's broken:**
The reshove detector (lines 2820–2871 of `gem_analyzer.py`) flags Hero folds at <8BB as "Missed Reshove" when Hero's hand matches hardcoded class thresholds:
```python
# Stack 5-8BB threshold (line ~2850):
should_reshove = (is_pair and r2 >= 4) or (is_ace and r2 >= 5) or (is_ace and is_suited)
# Confidence (line ~2857):
confidence = 'CLEAR' if (is_ace or is_pair) else 'MARGINAL'
```
This ignores who opened. A8o reshoving 6.7BB into a UTG open is dominated and -EV, but the detector says `CLEAR`. The same A8o vs a BTN steal is a fine reshove.

**Test hand:** `TM6032413497` — A8o, MP, 6.7BB, facing UTG open. Detector said "Missed Reshove <8BB (CLEAR)" + "III.2 Mistake, HIGH". Analyst corrected to III.3 Cleared.

**Fix approach:**
1. After `should_reshove` is determined (line 2853) and before confidence assignment (line 2857), add an opener-position gate
2. Look up the `REJAM_*vs*` charts from `Poker_Ranges_Text.txt` (these already encode position-dependent reshove ranges, keyed as `REJAM_{stack}BB_{hero_pos}_vs_{opener_pos}`)
3. If Hero's hand is NOT in the reshove chart for that position-vs-opener pair → `should_reshove = False`
4. If no chart exists for that combo → keep current logic but cap confidence at MARGINAL for early openers (UTG/UTG+1/MP)
5. ICM demotion (bubble_zone → MARGINAL) stays as-is

**Stack depth → chart normalization (exact rules):**
```
5.00–7.49BB → use 5BB chart if it exists; else 8BB chart as fallback
7.50–12.49BB → use 10BB or 12BB chart (whichever naming convention exists)
12.50–15.00BB → use 15BB chart if it exists
If no chart exists at any tier → do not emit CLEAR
```
Never silently use a wider/later-position chart when the exact opener position is missing. If the required chart does not exist, the detector may still fire but confidence must be capped at MARGINAL.

**Position alias normalization (must happen before chart lookup):**

Position normalization must be table-size aware if `table_size` / `max_players` is available in the hand dict.

If table size is unknown:
- Do not collapse earlier positions into later positions for chart lookup.
- Prefer conservative mapping.
- Unknown or ambiguous opener position → confidence capped at MARGINAL, never CLEAR.

Allowed safe aliases (always valid):
```
BTN = BU = Button
CO = Cutoff
SB = Small Blind
BB = Big Blind
HJ = Hijack
LJ = Lojack
UTG = EP1 (only if chart uses EP1)
UTG+1 = EP2 (only if chart uses EP2)
```

Do NOT map MP → HJ unless the hand is confirmed 6-max.

If `opener_position` cannot be normalized to a known alias, do not emit CLEAR. Cap at MARGINAL and log the unrecognized position.

**Available inputs at decision point:**
- `h.get('opener_position')` — the villain's position who opened
- `h.get('position')` — Hero's position
- `h.get('stack_bb')` — Hero's stack
- `h.get('cards')` — Hero's hole cards
- The `REJAM_*` charts are already loaded and indexed in the ranges module

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P1C-01 | A8o vs UTG open at 6.7BB → NOT flagged CLEAR (MARGINAL or no flag) |
| T-P1C-02 | A8o vs BTN steal at 6.7BB → still flagged (correct reshove spot) |
| T-P1C-03 | 77 vs UTG open at 5BB → MARGINAL at most (pair, early opener) |
| T-P1C-04 | ATs vs CO open at 7BB → still flagged (good reshove candidate) |
| T-P1C-05 | Regression — existing reshove verdicts unchanged when opener is late position |
| T-P1C-06 | Unrecognized opener_position → confidence capped at MARGINAL, not CLEAR |
| T-P1C-07 | Stack 6.7BB uses 5BB chart (not 8BB or 10BB) |

---

### P2-A: Shared preflop-terminal-allin helper

**Severity:** P2 — wrong-but-harmless (gets cleared in analyst pass), but pollutes worksheet

**What's broken:**
The M1 detector (lines 3592–3668 of `gem_analyzer.py`) fires "Missed Turn Delayed C-bet" on hands that went all-in preflop with no postflop play. A guard exists at line 3611:
```python
if h.get('pf_allin'): continue
```
But it didn't catch the test hands — suggesting `pf_allin` is only set when Hero jams, NOT when Hero calls an all-in.

**Test hands:**
- `TM6036110047` — AQo SB called BB reshove (all-in preflop, no flop)
- `TM6032397035` — A3o SB called 3.4BB MP shove (all-in preflop, no flop)

Both got flagged "Missed Turn Delayed C-bet (M1)" and pre-filled with postflop-line reasoning despite no postflop streets existing.

**Fix approach — do NOT add a one-off guard. Build a shared helper:**

**Concept definition:** Terminal preflop all-in means all money went in before the first postflop decision AND Hero had no decision on flop/turn/river. Do NOT require board to be empty — some all-in preflop hands still have board runout cards recorded by the parser.

1. Create a module-level helper in `gem_analyzer.py`:
   ```python
   def _is_preflop_terminal_allin(h):
       """True when Hero had no postflop decision because all relevant money
       went in preflop. Covers hero-jams, hero-calls-a-jam, and multi-way
       all-in-preflop regardless of whether board runout is recorded."""
       if h.get('pf_allin'):
           return True
       # Check action ledger: all-in preflop with no Hero postflop actions
       ledger = h.get('action_ledger') or []
       pf_allin_found = False
       hero_postflop_action = False
       for entry in ledger:
           if entry.get('street') == 'preflop' and entry.get('allin'):
               pf_allin_found = True
           if entry.get('is_hero') and entry.get('street') != 'preflop':
               hero_postflop_action = True
       if pf_allin_found and not hero_postflop_action:
           return True
       return False
   ```
2. Use this helper in ALL postflop-line detectors that assume flop/turn/river actions exist:
   - M1 (delayed c-bet) — line 3611
   - Any other detector that references `hero_street_actions['turn']`, `hero_street_actions['river']`, or postflop board cards
3. Investigate why `pf_allin` is not set for hero-call-shove scenarios — fix the root field if possible, but the helper is the safety net regardless

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P2A-01 | `_is_preflop_terminal_allin` returns True for hero-call-shove (no board) |
| T-P2A-02 | `_is_preflop_terminal_allin` returns True for hero-jam (pf_allin=True) |
| T-P2A-03 | `_is_preflop_terminal_allin` returns False for normal postflop hand |
| T-P2A-04 | AQo SB calling BB reshove (TM6036110047) → zero postflop-line flags |
| T-P2A-05 | A3o SB calling 3.4BB shove (TM6032397035) → zero postflop-line flags |
| T-P2A-06 | Normal SRP with check-check flop still fires M1 when appropriate |
| T-P2A-07 | At least one non-M1 postflop detector also uses the helper (prove it's shared) |
| T-P2A-08 | `_is_preflop_terminal_allin` returns True for all-in preflop WITH board runout recorded |

---

### P2-B: R6 call-jam — use actual pot odds instead of static threshold

**Severity:** P2 — wrong prefill direction on every short-stack call-off; recurs in turbo/hyper bounty sessions

**What's broken:**
The R6 call-jam verdict (lines 10304–10324 of `gem_analyzer.py`, inside `_role_aware_verdict()`) splits on `_eq_av` vs `_adj_threshold`:
```python
if _role in ('caller', 'caller_vs_jam') and _eq_av < _adj_threshold:
    if _eq_av < 0.25:
        verdict = 'III.4 Read-dependent'
    else:
        verdict = 'I.7 Cooler'
```
At micro-effective-stacks (<6BB), pot odds dominate raw equity. A3o calling a 3.4BB shove gets ~3:1 odds (needs only ~25% equity), which any ace has. But R6 routes it to "I.7 Cooler" because `_eq_av` is below the static threshold.

**Test hand:** `TM6032397035` — A3o SB calling 3.4BB MP open-shove. Price is ~3:1. Any ace crushes that price. Should be "III.5 Priced call", got "R6_call_jam_lowEq → I.7 Cooler".

**Fix approach:**

**Pot-odds field semantics (exact definition):**
```
pot_before_call = pot at the decision point BEFORE Hero's call is added
call_amount = the amount Hero must put in to call
required_eq = call_amount / (pot_before_call + call_amount)
```
If the available pot field already includes Hero's call, do NOT add `call_amount` again. Verify which convention `ctx.pot_odds` uses before computing.

**Debug/log fields to emit (at least in `--profile` mode):**
- `pot_before_call`
- `call_amount`
- `required_eq`
- `equity_used` (= `_eq_av`)
- `effective_stack_bb`

**Implementation:**
1. Compute `required_eq` from the decision node data (available via `ctx.pot_odds` or action ledger)
2. Compare `_eq_av` against `required_eq` (not static `_adj_threshold`) for `caller_vs_jam` role
3. Micro-stack heuristic: when effective stack < 6BB AND `required_eq < 0.30` (better than ~2.3:1 odds), default to R5 (priced call → III.5) unless equity is truly terrible (< 15%)

**Fallback when pot fields are unavailable:**
If `pot_before_call` or `call_amount` cannot be reconstructed confidently from the action ledger or context, fall back to current static-threshold logic but cap confidence and route to III.4 (read-dependent), not I.7 (cooler). The "fail soft" rule applies: uncertain pot data must not produce a confident wrong verdict.

**Bounty/ICM prohibition:**
For v8.9.8, use chip pot odds only. Do NOT attempt bounty-value or ICM adjustment in this formula. If bounty value exists in the hand context, attach it as a context note but do not change the verdict formula. Bounty/ICM adjustment to pot-odds is a separate feature requiring its own approval.

**Test tolerance:**
Tests comparing `required_eq` should allow ±0.02 absolute tolerance unless exact pot fields are known. Antes, blinds, and dead chips can shift the precise pot-odds calculation slightly depending on which fields the parser populates.

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P2B-01 | A3o calling 3.4BB shove at ~3:1 odds → III.5 priced call, not I.7 (±0.02 tolerance on required_eq) |
| T-P2B-02 | 72o calling 20BB shove at 1.5:1 odds → still I.7 or III.4 (bad equity) |
| T-P2B-03 | Regression — normal all-in calls at standard stacks unchanged |
| T-P2B-04 | No bounty/ICM math in the required_eq computation (canary: no "bounty" in R5/R6 formula code) |
| T-P2B-05 | Missing pot fields → routes to III.4, not I.7 (fallback test) |

---

### P2-C: PLO quarantine — centralized invariant

**Severity:** P2 — inflated analyst surface by 47 hands; could be hundreds on PLO-heavy batches

**What's broken:**
The PLO exclusion gate (lines 7657–7682 of `gem_analyzer.py`) builds `_non_nlh_ids` and strips them from `mistakes` and `punts`:
```python
_non_nlh_ids = {h.get('id') for h in hands if h.get('game_type', 'NLH') != 'NLH'}
if _non_nlh_ids:
    s['mistakes'] = [m for m in s.get('mistakes', []) if m.get('id') not in _non_nlh_ids]
    s['punts']['hands'] = [p for p in _raw_punts if p.get('id') not in _non_nlh_ids]
```
But it does NOT strip from `bust_audit`, `coolers`, `iii4_screening`, `read_dependent_screening`, or `bestplay_screening`. These buckets feed the coverage gate, so PLO hands appear as NLH items "needing analyst verdicts."

**Fix approach — do NOT enumerate buckets inline. Create a centralized helper:**
```python
def _filter_non_nlh_from_candidate_buckets(s, non_nlh_ids):
    """Remove non-NLH hand IDs from every bucket that can feed:
    - coverage gate
    - analyst worksheet
    - mistake/punt/cooler/read-dependent/bestplay surfaces
    - villain-intel candidate surfaces (if those assume NLH)
    
    PLO hands remain in volume/financials — they're real hands played.
    """
    _CANDIDATE_BUCKETS = (
        'mistakes', 'bust_audit', 'coolers',
        'iii4_screening', 'read_dependent_screening', 'bestplay_screening',
    )
    for key in _CANDIDATE_BUCKETS:
        if key in s and isinstance(s[key], list):
            s[key] = [x for x in s[key] if x.get('id') not in non_nlh_ids]
    # Punts has nested structure
    if 'punts' in s and 'hands' in s['punts']:
        s['punts']['hands'] = [p for p in s['punts']['hands']
                                if p.get('id') not in non_nlh_ids]
        s['punts']['count'] = len(s['punts']['hands'])
```
Call this once after all detectors have run. If a new bucket is added in the future, it must be added to `_CANDIDATE_BUCKETS` — the helper is the single source of truth.

**Post-condition invariant (add at coverage gate construction, lines ~10895–10909):**

In tests: assert hard.
In production: log ERROR and remove leaked non-NLH ids from `_need_verdict_ids` before continuing. The report must not crash because of a PLO quarantine leak.

```python
_plo_leak = _need_verdict_ids & _non_nlh_ids
if _plo_leak:
    import logging
    logging.error("PLO quarantine leak: %s — removing from verdict surface", _plo_leak)
    _need_verdict_ids -= _plo_leak
```

Tests should use a stricter check:
```python
assert not (_need_verdict_ids & _non_nlh_ids), \
    f"PLO quarantine leak: {_need_verdict_ids & _non_nlh_ids}"
```

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P2C-01 | Post-condition: `not (_need_verdict_ids & non_nlh_ids)` holds |
| T-P2C-02 | PLO hand present in volume stats but absent from bust_audit |
| T-P2C-03 | PLO hand absent from coolers bucket |
| T-P2C-04 | PLO hand absent from iii4_screening |
| T-P2C-05 | Regression — NLH hands in all buckets unchanged |
| T-P2C-06 | `_CANDIDATE_BUCKETS` tuple exists as single source of truth |

---

### P2-D: Lint print visibility (pulled forward from Phase 3)

**Rationale for pulling into Phase 1:** Lint visibility helps debug all future phases and is cheap. Don't wait until v8.9.10.

**Severity:** P2 — non-blocking, but errors invisible without `GEM_QA_BLOCK=1`

**What's broken:**
`lint_and_gate` (line ~717 of `gem_report_lint.py`) prints only the count of errors (`0 BLOCKER · 1 ERROR · …`). The actual rule ID + message are invisible unless `GEM_QA_BLOCK=1` is set.

**Fix approach:**
Have `lint_and_gate` print every ERROR/BLOCKER finding as: `LINT: {rule} | {block_id} | {message}` to console by default (one line per finding).

**Note:** The board-rule tightening (B-BOARD-FLUSH/STRAIGHT matcher accuracy) remains in Phase 3. This phase only makes findings visible.

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P2D-01 | Lint findings printed to console by default (not just count) |

---

## Phase 2 — Pipeline Resilience (v8.9.9)

**Goal:** Make 8K+ hand sessions completable in one shot. Extract the coverage/worksheet builder to a standalone module, add `--resume-from-cache` recovery path.

**Estimated effort:** ~2-3 days

**Dependency:** Phase 1 should land first so detector fixes are in the extracted code.

---

### P1-A: Extract coverage/worksheet builder + memory optimization

**Severity:** P1 — blocks one-shot completion on 8K+ hand sessions

**What's broken:**
The full pipeline runs as one uninterrupted process. On large sessions (8K+ hands, 110MB input JSON), it exceeds both the 295s timeout and 4GB memory limit. The candidate emission + worksheet emission block (lines 8794–10558 of `gem_analyzer.py`, ~1,750 lines of code) is inline in `__main__` and unreachable from `--quick` or `--render-only`.

Peak memory: `gem_hands.json` (110MB) + `gem_hands_lean.json` (95MB) + `gem_report_data.json` (39MB) all resident simultaneously during villain-intel + render.

**Naming convention:**
There are two distinct "candidate" concepts in the codebase. Use these names consistently:

| Module | Purpose | Concept |
|--------|---------|---------|
| `gem_coverage_builder.py` (NEW) | Extract of lines 8794–10558: coverage gate + NLH verdict candidate set + existing worksheet | Coverage candidates — "which hands need analyst verdicts" |
| `gem_analyst_villain.py` (EXISTS) | Phase 4: opponent-adjustment LLM candidate builder | Villain-review candidates — "which villain-intel findings should the LLM review" |

Do NOT name the extracted module `gem_candidate_builder.py` — it is ambiguous and will cause confusion in Phase 4.

**Fix — three sub-steps:**

**A1. Extract to `gem_coverage_builder.py`**
Move lines 8794–10558 into a new callable module:
```python
# gem_coverage_builder.py
def build_and_write(stats, report_data, hands, out_dir, date_compact, pname):
    """Build coverage candidates + emit worksheet. Standalone-callable from --resume-from-cache."""
    # ... existing logic from lines 8794-10558 ...
```
`gem_analyzer.py __main__` calls `build_and_write()` instead of inline code. The function is importable for use by `--resume-from-cache`.

**A2. Stream/free large intermediates**
- After `gem_hands_lean.json` is written, release the lean list from memory (`del hands_lean`)
- After `report_data` is written and before coverage builder runs, consider passing a slim hand index (id → position/cards/net_bb) instead of full 110MB hand list
- Log peak RSS per stage if `--profile` flag is set

**A3. `--profile` flag**
Add optional `--profile` that logs `resource.getrusage(RUSAGE_SELF).ru_maxrss` after each pipeline stage. Makes wall/memory budget visible pre-run so large sessions can be anticipated.

**Files changed:**
- `gem_analyzer.py` — extract 1,750 lines to module call; add `--profile` flag
- `gem_coverage_builder.py` — new file

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P1A-01 | `gem_coverage_builder.py` importable; `build_and_write` is callable |
| T-P1A-02 | `py_compile` clean on both files |
| T-P1A-03 | Canary — `build_and_write` string present in gem_coverage_builder.py |
| T-P1A-04 | `--profile` flag accepted without error (argparse check) |
| T-P1A-05 | Regression — full pipeline on test session produces identical stats/report_data |

---

### P1-B: --resume-from-cache flag

**Severity:** P1 — blocks fast worksheet recovery after crash

**What's broken:**
When the pipeline dies after analysis is cached but before candidate/worksheet emission:
- `--quick` loads cache and re-renders, but `sys.exit(0)` at line ~7963 before candidates
- `--render-only` does the same at line ~8051
- No path exists to "load cache → build candidates → emit worksheet → render" without re-running the full 5-minute analyze pass

**Fix approach:**
Add `--resume-from-cache` flag to `gem_analyzer.py`:
1. Load cached `gem_hands_*.json`, `gem_stats.json`, `gem_report_data_*.json`
2. Validate session fingerprint (B142) matches between ALL cached files
3. Call `gem_coverage_builder.build_and_write(stats, report_data, hands, ...)` from P1-A
4. Run render
5. Skip full analyze pass entirely

**Cache discovery rules (exact contract):**
```
1. If --cache-date YYYYMMDD is supplied, look only for files with that date stamp
2. Otherwise, choose the newest complete cache set by file modified time
3. A COMPLETE SET requires all three: gem_hands_*.json + gem_stats.json + gem_report_data_*.json
4. All three files must have matching session fingerprint (B142: player, n_hands, first_hand_id, date_range)
5. Never mix newest-hands with older-stats — all files must come from the same set
6. If multiple complete sets exist, prefer the one with the newest modified time
7. Abort with clear error if no complete matching set exists
```

**Error handling:**
- Abort with clear message if any cache file is missing
- Abort on session fingerprint mismatch (prevents stale cross-session mixing)
- Print which cached files were loaded and their timestamps

**Dependency:** Requires P1-A (coverage builder extraction) to be complete first.

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P1B-01 | `--resume-from-cache` flag accepted by argparse |
| T-P1B-02 | Produces worksheet output when cache files exist |
| T-P1B-03 | Aborts with clear error message on missing cache file |
| T-P1B-04 | Aborts on session fingerprint mismatch |
| T-P1B-05 | Output matches full-run output (diff stats/report_data) |
| T-P1B-06 | Two cache sets exist; resume chooses one complete matching set, not a mixed latest-per-file set |

---

### P3-A: _versioned_path dedup (piggyback on refactoring)

**Severity:** P3 — code duplication drift risk

**What's broken:**
`def _versioned_path(directory, prefix, date, ext)` is defined identically at two locations in `gem_analyzer.py`:
- Line 7982 (inside `--quick` block)
- Line 8524 (inside main `__main__` block)

Both have identical logic; only the second has a docstring.

**Fix:** During P1-A refactoring, hoist to a module-level function before line 1445 (before first use). Delete both inline copies.

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P3A-01 | Only one `def _versioned_path` in gem_analyzer.py source |

---

## Phase 3 — QA + Cleanup (v8.9.10)

**Goal:** Tighten lint rules, reduce QA noise, fix remaining low-priority bugs.

**Estimated effort:** ~1 day

**All items are independent — no dependencies between them.**

---

### P2-D-B: B-BOARD lint rule accuracy (board-state checking)

**Note:** Lint visibility was pulled forward to Phase 1 (P2-D). This item covers the board-state accuracy improvement only.

**Severity:** P2 — non-blocking, but risks false positives on correct analyst text

**What's broken:**
The `B-BOARD-FLUSH` / `B-BOARD-STRAIGHT` matchers (lines 555–632 of `gem_report_lint.py`) use loose substring regex like `flush[- ]complet` that catches accurate analyst prose ("flush completers" describing texture on a board where a flush genuinely completed).

**Test hand:** `TM6032395339` — board Th Td 3c 9d 8d. Analyst wrote "flush/straight completers" (describing board texture). Lint fired B-BOARD-STRAIGHT because no straight completed — but the matcher is too loose.

**Fix approach:**
1. Before the board-contradiction rules fire, check actual board state:
   - If text says "flush completing" AND board actually has a flush → suppress (accurate text)
   - If text says "straight completing" AND board actually has a straight → suppress
   - Only fire when the claim contradicts the actual board
2. Document safe phrasing in analyst checklist: "Use 'three-flush texture' instead of 'flush completers' when describing board texture vs. made hands"

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P2DB-01 | "flush completers" on board with actual flush → no error |
| T-P2DB-02 | "flush completers" on board without flush → error (correct) |

---

### P3-B: QA noise reduction

**Severity:** P3 — no incorrect output, but noise hides genuine warnings

**What's broken:**
1. **ID-gap check** (lines 8268–8287 of `gem_analyzer.py`): Counts per-tournament numeric gaps of 2–20 as "missing hands". On multi-table/multi-format sessions (NLH + PLO interleaved), GG hand IDs are not contiguous per table → massive false alarm: "~1204 possible missing hands (ID gaps)".
2. **Shown-cards warning**: Fires per villain per hand, not aggregated → prints ~2,000 lines of identical warnings.

**Fix approach:**
1. ID-gap: Downgrade to INFO (or suppress entirely) when session spans >1 game type or session has >5 concurrent tournaments (multi-table indicator). Keep for single-table single-format sessions where gaps are meaningful.
2. Shown-cards: Aggregate to single summary line: `{N} villains had shown_cards without parsed showdown across {M} hands`

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P3B-01 | Multi-format session → ID-gap warning suppressed or downgraded to INFO |
| T-P3B-02 | Shown-cards warning prints ≤ 2 lines (aggregated) |

---

### P3-C: Punt detector equity gate

**Severity:** P3 — caught in analyst pass; would over-report punts if rubber-stamped

**What's broken:**
All 7 punt patterns (lines 4970–5056 of `gem_analyzer.py`) fire based on action deviation type (e.g., "Wide CVJ", "Wide Iso-Jam") with magnitude gate but NO equity check. An AK + nut-flush-draw 252% turn overbet gets flagged as III.1 Punt (reckless) even though it's a coherent polarized semi-bluff with strong equity.

**Test hands:**
- `TM6040310418` — AK + NFD overbet → should be III.4 read-dependent, got III.1 Punt
- `TM6025333121` — river jam on paired/draw-heavy board after barreling → coherent line
- `TM6033111124` — flush-draw barrel-jam → semi-bluff with equity + blockers

**Fix approach — strict downgrade criteria (do NOT be overly forgiving):**

Downgrade III.1 → III.4 **only** if one of these conditions is met:
- Nut or near-nut flush draw (NFD, 2nd-nut FD)
- Combo draw (flush draw + straight draw)
- OESD + overcards
- Pair + draw (e.g., top pair + flush draw)
- Blocker-driven river jam with coherent prior-street aggression story (bet-bet-jam, not check-check-jam)

Do **NOT** downgrade on:
- Generic two overcards + weak backdoor (not strong enough to justify reckless sizing)
- Any "equity" claim without a specific draw name
- A-high no draw overbet-jam into a capped-but-sticky line

Punt bucket stays reserved for large -EV commitments with NO strategic justifier.

Implementation: check `h.get('draw_flags')` or `h.get('hand_strength')` at the punt-fire point. Only reclassify from III.1 → III.4 if a qualifying draw is explicitly present.

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-P3C-01 | AK + NFD overbet (TM6040310418) → III.4 not III.1 |
| T-P3C-02 | True reckless spew (no equity, no story) → still III.1 |
| T-P3C-03 | A-high no draw overbet-jam → still III.1 (negative test) |
| T-P3C-04 | Regression — existing punt hands without equity unchanged |

---

### BUG-C: Parser over-fold baseline labels

**Severity:** Low — label clarity issue

**What's broken:** Over-fold baseline labels in the parser output are unclear/ambiguous.

**Fix:** Update label strings to be unambiguous. Specific scope depends on current label code review.

**Tests:** Label string assertions in `_test_scratch.py`.

---

### BUG-D: Appendix multi-street TL;DR formatting

**Severity:** Low — formatting issue

**What's broken:** Multi-street verdict summaries in the appendix don't use arrow (`→`) segment splitting, making them harder to scan.

**Fix:** Add arrow splitter for `→` segments in multi-street TL;DR strings.

**Tests:** Format string assertions.

---

### B144: Phase bubble→post_bubble audit

**Severity:** P3 — audit, not urgent; needs more sample data

**What's broken:** The phase detector's `chips_only_fraction` heuristic may downgrade `bubble_zone` to `post_bubble` at low confidence when payout/ITM data is absent. Hand 60344687 was tagged `post_bubble` but Ron believes it was the actual bubble.

**Fix approach:**
- When `chips_only_fraction` confidence < 0.75 AND the heuristic disagrees with the initial `old_phase`, flag the phase assignment as low-confidence instead of silently overriding
- Emit a warning: `"Phase assignment low-confidence: {old_phase} → {new_phase} (conf={conf:.2f})"`
- Collect more sample data to validate whether the heuristic threshold needs adjusting

**Tests to add:**
| Test ID | Assertion |
|---------|-----------|
| T-B144-01 | Low-confidence phase downgrade emits warning |
| T-B144-02 | Regression — high-confidence phase assignments unchanged |

---

## Phase 4 — LLM Analyst Handoff (v9.0.0)

**Goal:** Build the villain candidate builder + worksheet I/O + renderer overlay so an LLM analyst can review villain-intel verdicts and produce coaching text.

**Estimated effort:** ~3-5 days

**Dependency:** Phase 2 (coverage builder extraction) should land first.

---

### Design decisions (resolved)

| Question | Decision | Rationale |
|----------|----------|-----------|
| Worksheet delivery | **Standalone JSON**: `_analyst_villain_worksheet_{date}.json` | Keeps new workflow isolated; avoids corrupting existing `_analyst_commentary.json` |
| Upgraded learning hands | **New bucket**: `analyst_learning` | It is a promoted coaching object, not merely villain evidence — deserves distinct type |
| Max candidates CLI flag | **Yes**: `--max-villain-candidates N`, default 40 | Cheap and useful for tuning |
| Borderline verdict | **Show analyst text first**, deterministic verdict as muted/debatable context | User should read the analyst's explanation, not a deterministic label the analyst softened |

---

### 4A: Candidate builder (`gem_analyst_villain.py`)

**What it does:** Takes the output of `build_villain_intel()` (evidence atoms + exploit opportunities) and selects the most coaching-valuable hands into a structured candidate list for LLM review.

**Public function:**
```python
def build_opponent_adjustment_candidates(
    villain_intel: dict,   # return of build_villain_intel()
    hands: list,           # parsed hands
    stats: dict,           # analyzer stats
    *,
    max_candidates: int = 40,
) -> list:
```

**5 candidate source types:**

| source_type | Source data | Selection criteria | Priority |
|---|---|---|---|
| `exploit_miss` | `exploit_opportunities` where `exploit_outcome == 'missed'` | All missed exploits | P0 |
| `exploit_good` | `exploit_opportunities` where `exploit_outcome == 'good'` | All good exploits (reinforcement) | P1 |
| `timing_unclear` | `exploit_opportunities` where timing is `unknown` or `same_hand_after` | Timing-downgraded; LLM re-evaluates | P1 |
| `mixed_signal` | `atoms_by_villain` with 2+ conflicting dimensions per villain | Pipeline picks dominant; LLM evaluates minority | P2 |
| `learning_hand` | `atoms_by_hand` with 3+ atoms, strength ≥ 4, or high-confidence line_stories | Pedagogically rich even without exploit | P2 |

**Candidate dict fields:**
```python
{
    # Identity
    'candidate_id': str,         # "{source_type}_{hand_id}_{villain_key}" — must use stable villain_key, not display alias or v_number (aliases are cosmetic and must not affect candidate identity)
    'source_type': str,          # one of 5 types above
    'priority': str,             # 'P0' | 'P1' | 'P2'

    # Hand context
    'hand_id': str,
    'hand_id_short': str,        # last 8 digits
    'tournament_id': str,
    'hero_position': str,
    'hero_cards': str,
    'board': str,
    'hero_net_bb': float,
    'stack_bb': float,

    # Villain context
    'villain_key': str,
    'villain_alias': str,
    'v_number': str,
    'villain_read_label': str,   # from read_states
    'read_confidence': str,
    'n_evidence_atoms': int,

    # Deterministic verdict (pipeline-decided, read-only for LLM)
    'det_verdict': str,          # 'missed_exploit' | 'good_exploit' | 'evidence_only' | 'timing_downgrade' | 'mixed_signal'
    'det_severity': str,         # 'A' | 'B' | 'C' | None
    'det_timing': str,           # 'known_before' | 'same_hand_before' | 'same_hand_after' | 'unknown'
    'det_exploit_detector': str, # e.g. 'missed_steal_vs_nit'

    # Coaching seed (deterministic text from SIGNAL_COACHING / _EXPLOIT_COACHING)
    'seed_suggests': str,
    'seed_so_what': str,
    'seed_next_time': str,

    # Evidence summary (deterministic, for LLM context)
    'evidence_summary': str,     # 1-3 sentence plaintext
    'atoms_in_hand': list,       # slim atom dicts: {signal, street, evidence_text, strength}

    # Analyst fields (LLM fills these; empty on initial worksheet)
    'analyst_verdict': str,      # '' → 'confirmed' | 'rejected' | 'borderline' | 'upgraded'
    'analyst_coaching': str,     # '' → 1-3 sentence coaching text
    'analyst_severity': str,     # '' → 'high' | 'medium' | 'low' | 'trivial'
    'analyst_confidence': str,   # '' → 'high' | 'medium' | 'low'
    'analyst_note': str,         # '' → optional freeform
}
```

**Ordering and dedup:**
- Priority ordering: all P0 first, then P1, then P2
- Within tier: sort by `n_evidence_atoms` descending (more evidence = more confident)
- Dedup: if same hand+villain appears in two source types, keep the higher-priority entry
- Budget cap: `max_candidates` (default 40)

---

### 4B: Worksheet I/O

**Write worksheet:**
```python
def write_worksheet(candidates, session_date, hero_name, out_dir, session_fingerprint):
    """Write analyst worksheet JSON to output directory (never HH input dir)."""
```

Output file: `{out_dir}/_analyst_villain_worksheet_{session_date}.json`

**File collision behavior:**
If `_analyst_villain_worksheet_{date}.json` already exists:
- Do not overwrite by default — a reviewed worksheet could be lost.
- Write `_analyst_villain_worksheet_{date}_v2.json`, `_v3.json`, etc. (increment until unused filename found).
- Print which filename was actually written.
- If explicit `--overwrite-analyst-worksheet` is later needed, that is separate scope.

**Schema (with session fingerprint and version safety):**
```json
{
    "schema_version": "1.0",
    "session_date": "20260604",
    "hero_name": "Knockman",
    "generated_at": "2026-06-08T10:00:00Z",
    "pipeline_version": "v9.0.0",
    "session_fingerprint": {
        "player": "Knockman",
        "n_hands": 1446,
        "first_hand_id": "TM6025300001",
        "last_hand_id": "TM6040399999",
        "date_range": "2026-06-04"
    },
    "source_report_version": "v8.9.9",
    "villain_intel_schema_version": "1.0",
    "total_candidates": 40,
    "instructions": "For each candidate, fill analyst_verdict, analyst_coaching, analyst_severity, analyst_confidence. Do not modify det_* fields.",
    "candidates": [ ... ]
}
```

**Load analyst review:**
```python
def load_analyst_villain_review(path, expected_fingerprint=None):
    """Load and validate analyst review JSON. Returns dict keyed by candidate_id → analyst fields."""
```

**Validation rules:**
- `schema_version` must be supported (reject unknown versions)
- `session_fingerprint` must match expected fingerprint (reject on mismatch — session_date alone is NOT sufficient; two runs on the same date are possible)
- `analyst_verdict` must be one of: `confirmed`, `rejected`, `borderline`, `upgraded`
- `analyst_coaching` must be non-empty for `confirmed` and `upgraded` verdicts
- `analyst_severity` must be one of: `high`, `medium`, `low`, `trivial`
- Unknown `candidate_id` → ignored with warning count; no crash (forward compat)
- Missing candidates → deterministic-only rendering (no crash)
- `det_*` field changes by LLM → ignored (validator only reads `analyst_*` fields)

---

### 4C: Pipeline integration (`gem_analyzer.py`)

**After villain_intel stage (after coverage builder extraction from P1-A):**
```python
from gem_analyst_villain import build_opponent_adjustment_candidates, write_worksheet

candidates = build_opponent_adjustment_candidates(villain_intel, hands, stats)
worksheet_path = write_worksheet(
    candidates, session_date, hero_name, out_dir,
    session_fingerprint=stats.get('_session_fingerprint', {})
)
print(f"  Analyst worksheet: {worksheet_path} ({len(candidates)} candidates)")
```

**Before render (when `--analyst-file` points to a reviewed worksheet):**
```python
from gem_analyst_villain import load_analyst_villain_review

analyst_villain = load_analyst_villain_review(
    analyst_file_path,
    expected_fingerprint=stats.get('_session_fingerprint', {})
)
report_data['analyst_villain_review'] = analyst_villain
```

---

### 4D: Renderer overlay (`sections_xiv.py` + `_html.py`)

**Python merge point — `_build_hand_opponent_contexts()` in `sections_xiv.py`:**
```python
def _build_hand_opponent_contexts(rd, s, *, analyst_review=None):
    """Build per-hand coaching contexts. If analyst_review provided, overlay verdicts."""
```

Overlay logic per verdict:
| Verdict | Renderer behavior |
|---------|-------------------|
| `confirmed` | Show full coaching block with analyst text + "Analyst confirmed" badge |
| `rejected` | Filter out of rendering entirely (Python-side, JS never sees it) |
| `borderline` | Show analyst text first, deterministic verdict as muted "Debatable" context |
| `upgraded` | Create new context with `bucket='analyst_learning'` + coaching text |

**New context fields added when analyst review is present:**
```python
{
    'analyst_reviewed': True,
    'analyst_verdict': str,
    'analyst_coaching': str,
    'analyst_severity': str,
    'analyst_note': str,
}
```

**JS rendering in `_html.py`** (inside `_renderOpponentContextBlock`):
- When `ctx.analyst_reviewed` is true, render a badge div with verdict-dependent text and coaching
- **All `analyst_coaching` text must be HTML-escaped** before insertion into DOM (LLM-filled JSON becomes rendered UI text — XSS risk if unescaped)
- Rejected items are already filtered in Python — JS never encounters them
- Fallback (no analyst file): current deterministic rendering, unchanged

---

### 4E: Future scope (post v9.0.0, NOT in this plan)

These remain parked until v9.0.0 baseline is stable:

- **New detectors** — expand beyond current 18 (8 exploit + 10 evidence). Each new detector needs its own approval cycle.
- **Per-atom review state** — LLM tags individual evidence atoms as reviewed/rejected/upgraded (not just whole candidates). Requires schema extension and finer-grained rendering.
- **C4 action `!` marker** — red `!` on the exact villain action column cell that triggered a mistake. Blocked until upstream provides explicit `anchorActionId` field in context data (renderer must not infer which action to mark).

---

### Phase 4 tests (T-AV series)

| Test ID | Assertion |
|---------|-----------|
| T-AV-01 | `build_opponent_adjustment_candidates` returns a list |
| T-AV-02 | All 5 `source_type` values are generated (when data supports them) |
| T-AV-03 | Dedup: same hand+villain in 2 source types → only higher-priority kept |
| T-AV-04 | Budget cap: `max_candidates=5` → exactly ≤ 5 results |
| T-AV-05 | Priority ordering: P0 entries before P1 before P2 |
| T-AV-06 | Every candidate dict has all required fields (schema check) |
| T-AV-07 | `evidence_summary` is non-empty for every candidate |
| T-AV-08 | Worksheet JSON round-trips: write → read → identical candidates |
| T-AV-09 | `load_analyst_villain_review` loads valid JSON without error |
| T-AV-10 | Invalid verdict value ('foo') → warning logged, entry skipped |
| T-AV-11 | Missing analyst file → no crash; deterministic-only rendering |
| T-AV-12 | Rejected candidate filtered from `handOpponentContexts` |
| T-AV-13 | Confirmed candidate adds `analyst_coaching` to context |
| T-AV-14 | Upgraded candidate creates `analyst_learning` bucket context |
| T-AV-15 | Worksheet file never written to HH input directory |
| T-AV-16 | Rejected candidate does NOT appear in raw JS payload / stringified `handOpponentContexts` |
| T-AV-17 | No analyst file → semantic equality with pre-v9.0.0 baseline: same hand IDs, same context count per hand, same bucket/type/verdict/coaching text, no `analyst_*` fields present. Byte-identical preferred only if serialization path is unchanged. |
| T-AV-18 | `analyst_coaching` is HTML-escaped in rendered output (no raw `<script>` passthrough) |
| T-AV-19 | `det_*` modifications in analyst file are ignored and do not affect rendering |
| T-AV-20 | Unknown `candidate_id` in analyst file → ignored with warning count, not crash |

---

## Version & Test Summary

| Version | Phase | Items | New tests (est.) |
|---------|-------|-------|-----------------|
| v8.9.8 | 1: Detector fixes + lint visibility | P1-C, P2-A, P2-B, P2-C, P2-D (visibility only) | ~22-25 |
| v8.9.9 | 2: Pipeline resilience | P1-A, P1-B, P3-A | ~12-14 |
| v8.9.10 | 3: QA + cleanup | P2-D-B (board accuracy), P3-B, P3-C, BUG-C, BUG-D, B144 | ~10-12 |
| v9.0.0 | 4: LLM analyst handoff | 4A-4D (candidate builder, worksheet, pipeline, renderer) | ~20 |
| **Total** | | **21 items** | **~64-71** |

Current test count: 571. Projected after all phases: ~635-642.

---

## Execution Constraints

- **Do not improvise** — if required fields are missing or ambiguous, fail soft (lower confidence / skip candidate). Do not invent thresholds, detector rules, bounty adjustments, ICM adjustments, or renderer text.
- **No new detectors or threshold changes** without explicit approval (Phase 1 fixes gate existing detectors, not adding new ones)
- **Renderer must not create analytical facts** — all coaching text comes from deterministic pipeline or LLM analyst fields
- **`--analyst-file` must NOT be in HH input directory** — worksheet writes to output dir only
- **Package naming**: v8.9.7 is current; next versions are v8.9.8, v8.9.9, v8.9.10, v9.0.0
- **Desktop UX for non-V25 areas must not change** — Phase 4 renderer changes are V25-only
- **Every new helper must have at least one positive and one negative regression test**
