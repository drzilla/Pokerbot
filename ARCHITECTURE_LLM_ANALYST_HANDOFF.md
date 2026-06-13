# LLM Analyst Handoff — Architecture & Data Contract

**Version:** v8.9.0 candidate
**Date:** 2026-06-08
**Status:** Architecture review — no code until approved

---

## 1. Overview

The deterministic pipeline (`gem_villain_intel.py`) produces exploit opportunities,
evidence atoms, and read states. These are high-recall, moderate-precision. The LLM
analyst layer sits **after** the deterministic pipeline and **before** the renderer.

```
gem_villain_intel.py          gem_analyst_villain.py       sections_xiv.py / _html.py
(deterministic detectors) --> (LLM review + annotate) --> (render with analyst verdicts)
```

The LLM does NOT:
- Change detector thresholds or firing conditions
- Add new read labels or grouping categories
- Modify atom fields (signal, dimension, strength)
- Create exploit opportunities that the deterministic pipeline didn't find

The LLM DOES:
- Confirm or reject borderline exploit verdicts
- Upgrade evidence-only atoms to "learning hand" when pedagogically valuable
- Write short coaching text for confirmed items
- Flag unclear timing for human review
- Provide severity context (is this a $0.02 spot or a $5 spot?)

---

## 2. Candidate Builder

### 2.1 New file: `gem_analyst_villain.py`

Single public function:

```python
def build_opponent_adjustment_candidates(
    villain_intel: dict,   # return of build_villain_intel()
    hands: list[dict],     # parsed hands
    stats: dict,           # analyzer stats (for stack/blind context)
    *,
    max_candidates: int = 40,
) -> list[dict]:
    """Build worksheet candidates from deterministic villain_intel output.
    
    Does NOT call the LLM. Returns a list of candidate dicts ready for
    the analyst worksheet JSON.
    """
```

### 2.2 Candidate sources (5 types)

Each candidate has a `source_type` field identifying where it came from:

| source_type | Source data | Selection criteria | Priority |
|---|---|---|---|
| `exploit_miss` | `exploit_opportunities` where `exploit_outcome == 'missed'` | All — these are the most coaching-valuable items | P0 |
| `exploit_good` | `exploit_opportunities` where `exploit_outcome == 'good'` | All — reinforcement is valuable | P1 |
| `timing_unclear` | `exploit_opportunities` where timing classified as `unknown` or `same_hand_after` | These were downgraded from exploit to evidence by the timing gate; LLM decides if the downgrade was correct | P1 |
| `mixed_signal` | `atoms_by_villain` entries where a single villain has atoms in 2+ conflicting dimensions (e.g., both `loose_passive` and `aggressive`) | The deterministic pipeline picks the dominant read; the LLM evaluates whether the minority dimension matters | P2 |
| `learning_hand` | `atoms_by_hand` entries with 3+ atoms in a single hand, OR atoms with `strength >= 4`, OR line_stories with `confidence == 'high'` | Pedagogically rich hands for teaching even without an exploit decision | P2 |

### 2.3 Candidate dict structure

```python
{
    # Identity
    'candidate_id': str,         # deterministic: f"{source_type}_{hand_id}_{villain_key}"
    'source_type': str,          # one of 5 types above
    'priority': str,             # 'P0', 'P1', 'P2'
    
    # Hand context
    'hand_id': str,              # full format (TM60...)
    'hand_id_short': str,        # 8-digit
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
    
    # Deterministic verdict (what pipeline already decided)
    'det_verdict': str,          # 'missed_exploit' | 'good_exploit' | 'evidence_only' | 'timing_downgrade' | 'mixed_signal'
    'det_severity': str,         # 'A' | 'B' | 'C' | None
    'det_timing': str,           # 'known_before' | 'same_hand_before' | 'same_hand_after' | 'unknown'
    'det_exploit_detector': str, # e.g., 'missed_steal_vs_nit' or '' for non-exploit
    
    # Coaching seed (deterministic coaching text from SIGNAL_COACHING / _EXPLOIT_COACHING)
    'seed_suggests': str,
    'seed_so_what': str,
    'seed_next_time': str,
    
    # Evidence summary for LLM context
    'evidence_summary': str,     # 1-3 sentence plaintext: what happened in the hand
    'atoms_in_hand': list[dict], # slim atom dicts (signal, street, evidence_text, strength)
    
    # Analyst fields (empty until LLM fills them)
    'analyst_verdict': str,      # '' → LLM fills: 'confirmed' | 'rejected' | 'borderline' | 'upgraded'
    'analyst_coaching': str,     # '' → LLM fills: 1-3 sentence coaching text
    'analyst_severity': str,     # '' → LLM fills: 'high' | 'medium' | 'low' | 'trivial'
    'analyst_confidence': str,   # '' → LLM fills: 'high' | 'medium' | 'low'
    'analyst_note': str,         # '' → LLM fills: optional freeform note
}
```

### 2.4 Budget and ordering

- `max_candidates` defaults to 40 (tunable).
- Priority ordering: all P0 first, then P1, then P2.
- Within a priority tier: sort by `n_evidence_atoms` descending (more evidence = more confident).
- Dedup: if a hand+villain pair appears as both `exploit_miss` and `timing_unclear`, keep only the higher-priority entry.

### 2.5 `evidence_summary` generation (deterministic, no LLM)

Built from existing fields — NOT an LLM call:

```python
def _build_evidence_summary(hand, atoms, exploit=None):
    """Deterministic 1-3 sentence summary from parsed hand + atom data."""
    parts = []
    parts.append(f"Hand {hand['id'][-8:]}: Hero in {hero_pos} with {hero_cards}.")
    if exploit:
        parts.append(f"Exploit: {exploit['recommended_exploit']}. "
                      f"Hero {exploit['hero_action']}.")
    if atoms:
        signals = ', '.join(set(a['signal'].replace('_', ' ') for a in atoms))
        parts.append(f"Evidence signals: {signals}.")
    return ' '.join(parts)
```

---

## 3. Analyst Worksheet Input

### 3.1 File format

```
_analyst_villain_worksheet_{session_date}.json
```

Written to the session output directory alongside the report. This is the file
the LLM analyst receives.

### 3.2 Schema

```json
{
  "schema_version": "1.0",
  "session_date": "20260604",
  "hero_name": "Knockman",
  "generated_at": "2026-06-08T10:00:00Z",
  "pipeline_version": "v8.9.0",
  "total_candidates": 40,
  "instructions": "For each candidate, fill analyst_verdict, analyst_coaching, analyst_severity, analyst_confidence. Do not modify det_* fields.",
  "candidates": [
    { ... candidate dict ... },
    { ... candidate dict ... }
  ]
}
```

### 3.3 Worksheet generation entry point

Called from `gem_analyzer.py` after `build_villain_intel()` returns:

```python
# In gem_analyzer.py __main__ block, after villain_intel is built:
from gem_analyst_villain import build_opponent_adjustment_candidates, write_worksheet

candidates = build_opponent_adjustment_candidates(
    villain_intel, hands, stats, max_candidates=40
)
worksheet_path = write_worksheet(candidates, session_date, hero_name, out_dir)
```

### 3.4 Governance constraint

The worksheet file is written to the **output directory**, never to the HH input
directory. The `--analyst-file` flag on the renderer points to the completed
(LLM-annotated) version of this file. This preserves the rule:

> "--analyst-file must NOT be placed inside HH input directory;
>  renderer must not create analytical facts"

---

## 4. Analyst JSON Output

### 4.1 File format

Same JSON structure as the worksheet, but with analyst fields filled:

```
_analyst_villain_reviewed_{session_date}.json
```

### 4.2 LLM analyst fills these fields per candidate

| Field | Type | Valid values | Required |
|---|---|---|---|
| `analyst_verdict` | str | `confirmed`, `rejected`, `borderline`, `upgraded` | Yes |
| `analyst_coaching` | str | 1-3 sentences, plain English | Yes (may be empty for `rejected`) |
| `analyst_severity` | str | `high`, `medium`, `low`, `trivial` | Yes |
| `analyst_confidence` | str | `high`, `medium`, `low` | Yes |
| `analyst_note` | str | Optional freeform | No |

### 4.3 Verdict semantics

| Verdict | Meaning | Renderer effect |
|---|---|---|
| `confirmed` | Deterministic verdict is correct | Show full coaching block with analyst text |
| `rejected` | Deterministic verdict is wrong (false positive) | Suppress or collapse the coaching block |
| `borderline` | Defensible either way | Show with softer language ("this is debatable") |
| `upgraded` | Evidence-only item promoted to learning hand | Show as coaching opportunity even without exploit |

### 4.4 Fallback: no analyst file

If `--analyst-file` is not provided or doesn't contain villain candidates:
- The renderer uses deterministic output only (current behavior)
- No analyst coaching text appears
- No verdict overrides

This ensures the pipeline never requires the LLM to produce a report.

### 4.5 Validation

```python
def load_analyst_villain_review(path: str) -> dict:
    """Load and validate analyst review JSON.
    
    Returns dict keyed by candidate_id → analyst fields.
    Rejects entries with invalid verdict values.
    Logs warnings for missing candidates (worksheet evolved).
    """
```

Validation rules:
- `analyst_verdict` must be one of 4 valid values
- `analyst_coaching` must be non-empty for `confirmed` and `upgraded`
- `analyst_severity` must be one of 4 valid values
- Unknown `candidate_id` values are silently ignored (forward compat)
- Missing candidates get deterministic-only rendering (no crash)

---

## 5. Renderer Integration

### 5.1 Data flow

```
                                                analyst_review (optional)
                                                      |
gem_villain_intel.py → build_opponent_adjustment_candidates → write_worksheet
                                                                    |
                                                            LLM fills analyst_*
                                                                    |
                                                      load_analyst_villain_review
                                                                    |
                        sections_xiv.py ← merged into hand_opponent_contexts
```

### 5.2 Merge point: `_build_hand_opponent_contexts`

The existing function builds contexts from deterministic data. Add an optional
`analyst_review` parameter:

```python
def _build_hand_opponent_contexts(rd, s, *, analyst_review=None):
    """Build per-hand coaching contexts.
    
    If analyst_review is provided, overlay analyst verdicts:
    - 'rejected' → remove context from rendering (or collapse)
    - 'confirmed' → add analyst_coaching to context dict
    - 'borderline' → add softer framing + analyst_coaching
    - 'upgraded' → create new context with bucket='analyst_learning'
    """
```

### 5.3 New context fields (added when analyst review present)

```python
{
    # Existing fields unchanged...
    
    # Analyst overlay (only present when analyst reviewed)
    'analyst_reviewed': bool,          # True if this candidate was reviewed
    'analyst_verdict': str,            # confirmed | rejected | borderline | upgraded
    'analyst_coaching': str,           # LLM-written coaching text
    'analyst_severity': str,           # high | medium | low | trivial
    'analyst_note': str,               # optional
}
```

### 5.4 JS modal rendering changes

In `_html.py`, the coaching block renderer checks for `analyst_reviewed`:

```javascript
// If analyst reviewed, show analyst coaching text instead of/alongside deterministic
if (ctx.analyst_reviewed) {
    var badge = ctx.analyst_verdict === 'confirmed' ? '🔍 Analyst confirmed' :
                ctx.analyst_verdict === 'borderline' ? '🔍 Debatable' :
                ctx.analyst_verdict === 'upgraded' ? '🔍 Learning opportunity' : '';
    if (badge) {
        var aDiv = document.createElement('div');
        aDiv.className = 'cb-analyst';
        aDiv.innerHTML = '<strong>' + badge + '</strong><br>' + _esc(ctx.analyst_coaching);
        _cb.appendChild(aDiv);
    }
}
// 'rejected' → skip rendering this context entirely (already filtered in Python)
```

### 5.5 Rejected items

Two strategies (choose one):

**Option A: Filter in Python** — `_build_hand_opponent_contexts` excludes rejected
candidates entirely. The JS never sees them. Simpler.

**Option B: Collapse in JS** — Pass rejected items with `analyst_verdict='rejected'`
and render as tiny collapsed note "Analyst: not a real miss". More transparent but
noisier.

**Recommendation: Option A** (filter in Python). The user said "LLM reviews and
annotates; it does not change detector thresholds." Filtering rejected items at
render time is presentation, not threshold change.

---

## 6. Candidate-to-Worksheet Pipeline

### 6.1 Integration into `gem_analyzer.py`

```python
# After line ~11201 (render_both), before file write:
if _build_villain_worksheet:
    from gem_analyst_villain import build_opponent_adjustment_candidates, write_worksheet
    _vi = stats.get('villain_intel', {})
    _candidates = build_opponent_adjustment_candidates(_vi, hands, stats)
    _ws_path = write_worksheet(
        _candidates, date_compact, _pname_file, out_dir
    )
    print(f"  Analyst worksheet: {_ws_path} ({len(_candidates)} candidates)")
```

### 6.2 Loading analyst review into renderer

```python
# In gem_analyzer.py, before render_both():
_analyst_villain = None
if analyst_file_path:
    from gem_analyst_villain import load_analyst_villain_review
    _analyst_villain = load_analyst_villain_review(analyst_file_path)
    # This gets threaded into report_data for the renderer
    report_data['analyst_villain_review'] = _analyst_villain
```

Then in `sections_xiv.py`:

```python
_analyst_review = rd.get('analyst_villain_review')
contexts = _build_hand_opponent_contexts(rd, s, analyst_review=_analyst_review)
```

---

## 7. Tests and Failure Modes

### 7.1 Unit tests (new file: test layer in `_test_scratch.py`)

| Test ID | What | How |
|---|---|---|
| T-AV1 | Candidate builder returns list | Call with mock villain_intel, assert list |
| T-AV2 | All 5 source_types generated | Assert each source_type appears when data supports it |
| T-AV3 | Candidate dedup | Same hand+villain in two source types → keep higher priority |
| T-AV4 | Budget cap respected | max_candidates=5 → exactly 5 returned |
| T-AV5 | Priority ordering | P0 before P1 before P2 |
| T-AV6 | Candidate dict has all required fields | Schema check against field list |
| T-AV7 | evidence_summary is non-empty | All candidates have summary |
| T-AV8 | Worksheet JSON round-trips | Write → read → assert identical |
| T-AV9 | Analyst review loads valid JSON | Load mock review, assert parsed correctly |
| T-AV10 | Analyst review rejects invalid verdict | 'foo' verdict → logged warning, skipped |
| T-AV11 | Missing analyst file → no crash | analyst_file=None → deterministic-only |
| T-AV12 | Rejected candidate filtered from contexts | analyst_verdict='rejected' → not in handOpponentContexts |
| T-AV13 | Confirmed candidate adds coaching text | analyst_verdict='confirmed' → analyst_coaching in context |
| T-AV14 | Upgraded candidate creates learning context | analyst_verdict='upgraded' → new bucket in contexts |
| T-AV15 | Worksheet never written to HH dir | Assert worksheet path is in output dir, not session dir |

### 7.2 Failure modes and mitigations

| Failure | Impact | Mitigation |
|---|---|---|
| LLM returns invalid JSON | Worksheet unusable | `load_analyst_villain_review` validates; falls back to deterministic |
| LLM changes det_* fields | Deterministic integrity compromised | Validator ignores det_* changes; only reads analyst_* fields |
| LLM invents new candidate_ids | Unknown candidates in review | Validator silently drops unknown IDs; logs warning |
| LLM leaves analyst_coaching empty for confirmed | Coaching block renders blank | Validator rejects: confirmed requires non-empty coaching |
| Candidate builder sees 0 exploits | Empty worksheet | Legal state; worksheet written with 0 candidates; log message |
| analyst_file from different session | Stale data merged | Validate `session_date` matches; reject mismatch |
| Pipeline version mismatch | Field names diverged | `schema_version` field checked; reject unknown versions |
| Very large session (5000+ hands) | Too many candidates | `max_candidates` cap; budget planner already trims appendix |

### 7.3 Canaries for `verify_release.py`

```python
# In verify_release.py CANARIES list:
("gem_analyst_villain.py",
 "build_opponent_adjustment_candidates",
 "v8.9.0: candidate builder public function"),
("gem_analyst_villain.py",
 "analyst_verdict",
 "v8.9.0: analyst verdict field in candidate schema"),
("gem_analyst_villain.py",
 "schema_version",
 "v8.9.0: worksheet schema versioning"),
```

---

## 8. File Change Summary

| File | Change | New/Modified |
|---|---|---|
| `gem_analyst_villain.py` | **New file**: candidate builder + worksheet I/O + review loader | New |
| `gem_analyzer.py` | Call candidate builder after villain_intel; load analyst review before render | Modified |
| `gem_report_draft/sections_xiv.py` | Thread `analyst_review` into `_build_hand_opponent_contexts` | Modified |
| `gem_report_draft/_html.py` | JS: render analyst coaching block when `analyst_reviewed` is present | Modified |
| `_test_scratch.py` | T-AV1 through T-AV15 | Modified |
| `verify_release.py` | New hashes + canaries for gem_analyst_villain.py | Modified |

---

## 9. What Stays Parked

- Per-atom review state (analyst reviews candidates, not individual atoms)
- New detectors (candidate builder only uses existing 8 exploit + 10 evidence detectors)
- BUG-C (parser mislabel) and BUG-D (appendix cap)
- Racer MDA caveat
- cEV/100 analyzer-layer scaling
- All-ins hid/count misalignment

---

## 10. Open Questions for User

1. **Worksheet delivery mechanism**: Should the worksheet be written as a standalone
   JSON file (current plan), or embedded in the existing `_analyst_commentary.json`
   under a new key? Standalone is cleaner for LLM tooling; embedded keeps one file.

2. **Upgraded learning hands**: When the LLM upgrades an evidence-only hand to a
   "learning opportunity," what bucket should it render as? Options:
   - New bucket `analyst_learning` (5th bucket type)
   - Render as enriched `villain_evidence` with a "Learning opportunity" badge

3. **Max candidates default**: 40 covers a typical session. Should this be
   configurable via CLI flag (`--max-villain-candidates N`)?

4. **Borderline softening**: For `borderline` verdicts, should the renderer show
   the deterministic verdict with a caveat ("This is debatable — ...") or suppress
   the verdict entirely and only show the analyst coaching text?
