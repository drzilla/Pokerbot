"""gem_analyst_villain.py — LLM Analyst Handoff for Opponent Adjustments.

Sits between the deterministic pipeline (gem_villain_intel.py) and the renderer
(sections_xiv.py / _html.py).  Builds worksheet candidates from existing
deterministic output; the LLM reviews and annotates but does NOT change
detector thresholds, read labels, or core grouping.

v8.9.0  2026-06-08

GPT-approved requirements:
  A. candidate_id = stable hash, collision-safe
  B. Canonical joins use full hand_id, never 8-digit short
  C. LLM output must never overwrite det_* fields
  D. Rejected items: filter in Python, keep debug count
  E. candidate_reason on every candidate
  F. mixed_signal candidates include dimension_counts
  G. timing_unclear candidates include action-index fields
  H. Renderer fallback labels for missing/stale/invalid analyst review
  I. analyst_coaching max 350 chars
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

SCHEMA_VERSION = '1.0'
MAX_COACHING_CHARS = 350
VALID_VERDICTS = frozenset({'confirmed', 'rejected', 'borderline', 'upgraded'})
VALID_SEVERITIES = frozenset({'high', 'medium', 'low', 'trivial'})
VALID_CONFIDENCES = frozenset({'high', 'medium', 'low'})

_CANDIDATE_FIELDS = (
    'candidate_id', 'source_type', 'priority', 'candidate_reason',
    'hand_id', 'hand_id_short', 'tournament_id',
    'hero_position', 'hero_cards', 'board', 'hero_net_bb', 'stack_bb',
    'villain_key', 'villain_alias', 'v_number',
    'villain_read_label', 'read_confidence', 'n_evidence_atoms',
    'det_verdict', 'det_severity', 'det_timing', 'det_exploit_detector',
    'seed_suggests', 'seed_so_what', 'seed_next_time',
    'evidence_summary', 'atoms_in_hand',
    'analyst_verdict', 'analyst_coaching', 'analyst_severity',
    'analyst_confidence', 'analyst_note',
)


# ── Stable hash ID (Requirement A) ──────────────────────────────────

def _stable_candidate_id(source_type: str, hand_id: str,
                         villain_key: str) -> str:
    """Collision-safe deterministic ID from source + hand + villain."""
    raw = f'{source_type}|{hand_id}|{villain_key}'
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Evidence summary builder (deterministic, no LLM) ────────────────

def _build_evidence_summary(hand: dict, atoms: list,
                            exploit: dict | None = None) -> str:
    """Deterministic 1-3 sentence summary from parsed hand + atom data."""
    parts = []
    hid_short = str(hand.get('id', '?'))[-8:]
    hero_pos = hand.get('position', '?')
    hero_cards = ''.join(hand.get('cards', [])) or '?'
    parts.append(f"Hand {hid_short}: Hero in {hero_pos} with {hero_cards}.")
    if exploit:
        rec = exploit.get('recommended_exploit', '')
        hero_act = exploit.get('hero_action', '')
        if rec:
            parts.append(f"Exploit: {rec}. Hero {hero_act}.")
    if atoms:
        signals = ', '.join(sorted(set(
            a.get('signal', '').replace('_', ' ')
            for a in atoms if a.get('signal')
        )))
        if signals:
            parts.append(f"Evidence signals: {signals}.")
    return ' '.join(parts)


def _slim_atom(a: dict) -> dict:
    """Trim atom to worksheet-relevant fields only."""
    return {
        'signal': a.get('signal', ''),
        'street': a.get('street', ''),
        'evidence_text': a.get('evidence_text', ''),
        'strength': a.get('strength', 0),
        'dimension': a.get('dimension', ''),
        'action_index': a.get('action_index'),
    }


# ── Candidate extraction per source_type ────────────────────────────

def _extract_exploit_candidates(vi: dict, hands_by_id: dict,
                                outcome: str, source_type: str,
                                priority: str) -> list[dict]:
    """Extract candidates from exploit_opportunities by outcome."""
    exploits = vi.get('exploit_opportunities', [])
    abh = vi.get('atoms_by_hand', {}) or {}
    read_states = vi.get('read_states', {}) or {}
    aliases = vi.get('villain_aliases', {}) or {}
    candidates = []

    for exp in exploits:
        if exp.get('exploit_outcome') != outcome:
            continue
        # Skip timing-downgraded exploits — handled by _extract_timing_unclear
        tc = exp.get('timing_classification', '')
        if tc in ('unknown', 'same_hand_after'):
            continue
        hid = exp.get('hand_id', '')
        vk = exp.get('villain_key', '')
        if not hid or not vk:
            continue

        hand = hands_by_id.get(hid, {})
        atoms = abh.get(hid, [])
        rs = read_states.get(vk, {})
        va = aliases.get(vk, {})

        det_timing = 'known_before'
        if exp.get('timing_classification'):
            det_timing = exp['timing_classification']

        reason = (f"Hero {outcome.replace('_', ' ')} "
                  f"vs {va.get('alias', vk)} — "
                  f"{exp.get('exploit_type', 'unknown')} detector fired")

        c = _make_candidate(
            source_type=source_type,
            priority=priority,
            candidate_reason=reason,
            hand=hand,
            hand_id=hid,
            villain_key=vk,
            aliases=aliases,
            read_states=read_states,
            atoms=atoms,
            exploit=exp,
            det_verdict=f'{outcome}_exploit' if outcome in ('missed', 'good') else outcome,
            det_severity=exp.get('severity', ''),
            det_timing=det_timing,
            det_exploit_detector=exp.get('exploit_type', ''),
        )
        candidates.append(c)
    return candidates


def _extract_timing_unclear(vi: dict, hands_by_id: dict) -> list[dict]:
    """P1: exploits downgraded by timing gate."""
    exploits = vi.get('exploit_opportunities', [])
    abh = vi.get('atoms_by_hand', {}) or {}
    aliases = vi.get('villain_aliases', {}) or {}
    read_states = vi.get('read_states', {}) or {}
    candidates = []

    for exp in exploits:
        tc = exp.get('timing_classification', '')
        if tc not in ('unknown', 'same_hand_after'):
            continue
        hid = exp.get('hand_id', '')
        vk = exp.get('villain_key', '')
        if not hid or not vk:
            continue

        hand = hands_by_id.get(hid, {})
        atoms = abh.get(hid, [])
        va = (aliases or {}).get(vk, {})

        reason = (f"Timing gate downgraded to evidence — "
                  f"classification '{tc}' for "
                  f"{exp.get('exploit_type', '?')} "
                  f"vs {va.get('alias', vk)}")

        c = _make_candidate(
            source_type='timing_unclear',
            priority='P1',
            candidate_reason=reason,
            hand=hand,
            hand_id=hid,
            villain_key=vk,
            aliases=aliases,
            read_states=read_states,
            atoms=atoms,
            exploit=exp,
            det_verdict='timing_downgrade',
            det_severity=exp.get('severity', ''),
            det_timing=tc,
            det_exploit_detector=exp.get('exploit_type', ''),
        )
        # Requirement G: action-index fields for timing-unclear
        c['det_action_index'] = exp.get('action_index')
        c['det_available_before_action_index'] = exp.get(
            'available_before_action_index')
        candidates.append(c)
    return candidates


def _extract_mixed_signal(vi: dict, hands_by_id: dict) -> list[dict]:
    """P2: villains with atoms in 2+ conflicting dimensions."""
    abv = vi.get('atoms_by_villain', {}) or {}
    aliases = vi.get('villain_aliases', {}) or {}
    read_states = vi.get('read_states', {}) or {}
    abh = vi.get('atoms_by_hand', {}) or {}
    candidates = []

    for vk, v_atoms in abv.items():
        if not v_atoms:
            continue
        dims = {}
        for a in v_atoms:
            d = a.get('dimension', '')
            if d:
                dims[d] = dims.get(d, 0) + 1
        if len(dims) < 2:
            continue

        # Use the hand with most atoms for this villain
        hand_atoms_count = {}
        for a in v_atoms:
            hid = a.get('hand_id', '')
            if hid:
                hand_atoms_count[hid] = hand_atoms_count.get(hid, 0) + 1
        if not hand_atoms_count:
            continue
        best_hid = max(hand_atoms_count, key=hand_atoms_count.get)
        hand = hands_by_id.get(best_hid, {})
        atoms = abh.get(best_hid, [])
        va = aliases.get(vk, {})

        dim_labels = ', '.join(f"{d}({n})" for d, n in
                               sorted(dims.items(), key=lambda x: -x[1]))
        reason = (f"Mixed signals for {va.get('alias', vk)}: "
                  f"{dim_labels}")

        c = _make_candidate(
            source_type='mixed_signal',
            priority='P2',
            candidate_reason=reason,
            hand=hand,
            hand_id=best_hid,
            villain_key=vk,
            aliases=aliases,
            read_states=read_states,
            atoms=atoms,
            exploit=None,
            det_verdict='mixed_signal',
            det_severity='',
            det_timing='',
            det_exploit_detector='',
        )
        # Requirement F: dimension_counts for mixed_signal
        c['dimension_counts'] = dims
        candidates.append(c)
    return candidates


def _extract_learning_hands(vi: dict, hands_by_id: dict) -> list[dict]:
    """P2: hands rich in evidence (3+ atoms or strength>=4)."""
    abh = vi.get('atoms_by_hand', {}) or {}
    aliases = vi.get('villain_aliases', {}) or {}
    read_states = vi.get('read_states', {}) or {}
    candidates = []
    seen_hids = set()

    for hid, atoms in abh.items():
        if not atoms or hid in seen_hids:
            continue
        high_strength = any(a.get('strength', 0) >= 4 for a in atoms)
        many_atoms = len(atoms) >= 3
        if not (high_strength or many_atoms):
            continue
        seen_hids.add(hid)

        # Pick the most-attested villain in this hand
        vk_counts = {}
        for a in atoms:
            vk = a.get('villain_key', '')
            if vk:
                vk_counts[vk] = vk_counts.get(vk, 0) + 1
        vk = max(vk_counts, key=vk_counts.get) if vk_counts else ''
        hand = hands_by_id.get(hid, {})

        reason_parts = []
        if many_atoms:
            reason_parts.append(f"{len(atoms)} evidence atoms in one hand")
        if high_strength:
            max_str = max(a.get('strength', 0) for a in atoms)
            reason_parts.append(f"strength {max_str} atom present")
        reason = 'Learning hand: ' + ', '.join(reason_parts)

        c = _make_candidate(
            source_type='learning_hand',
            priority='P2',
            candidate_reason=reason,
            hand=hand,
            hand_id=hid,
            villain_key=vk,
            aliases=aliases,
            read_states=read_states,
            atoms=atoms,
            exploit=None,
            det_verdict='evidence_only',
            det_severity='',
            det_timing='',
            det_exploit_detector='',
        )
        candidates.append(c)
    return candidates


# ── Candidate factory ────────────────────────────────────────────────

def _make_candidate(*, source_type, priority, candidate_reason,
                    hand, hand_id, villain_key, aliases, read_states,
                    atoms, exploit, det_verdict, det_severity,
                    det_timing, det_exploit_detector) -> dict:
    """Build a single candidate dict with all required fields."""
    va = aliases.get(villain_key, {}) if aliases else {}
    rs = read_states.get(villain_key, {}) if read_states else {}

    hid = hand_id  # Requirement B: always full hand_id
    hid_short = hid[-8:] if len(hid) > 8 else hid

    return {
        'candidate_id': _stable_candidate_id(source_type, hid, villain_key),
        'source_type': source_type,
        'priority': priority,
        'candidate_reason': candidate_reason,

        'hand_id': hid,
        'hand_id_short': hid_short,
        'tournament_id': hand.get('tournament', ''),
        'hero_position': hand.get('position', ''),
        'hero_cards': ''.join(hand.get('cards', [])),
        'board': ''.join(hand.get('board', [])) if isinstance(
            hand.get('board'), list) else hand.get('board', ''),
        'hero_net_bb': hand.get('net_bb', 0.0),
        'stack_bb': hand.get('stack_bb', 0.0),

        'villain_key': villain_key,
        'villain_alias': va.get('alias', ''),
        'v_number': va.get('v_number', ''),
        'villain_read_label': rs.get('primary_read', ''),
        'read_confidence': rs.get('confidence', ''),
        'n_evidence_atoms': len(atoms) if atoms else 0,

        'det_verdict': det_verdict,
        'det_severity': det_severity,
        'det_timing': det_timing,
        'det_exploit_detector': det_exploit_detector,

        'seed_suggests': (exploit or {}).get('suggests', ''),
        'seed_so_what': (exploit or {}).get('so_what', ''),
        'seed_next_time': (exploit or {}).get('next_time', ''),

        'evidence_summary': _build_evidence_summary(hand, atoms, exploit),
        'atoms_in_hand': [_slim_atom(a) for a in (atoms or [])],

        'analyst_verdict': '',
        'analyst_coaching': '',
        'analyst_severity': '',
        'analyst_confidence': '',
        'analyst_note': '',
    }


# ── Public API: build candidates ────────────────────────────────────

def build_opponent_adjustment_candidates(
    villain_intel: dict,
    hands: list[dict],
    stats: dict,
    *,
    max_candidates: int = 40,
) -> list[dict]:
    """Build worksheet candidates from deterministic villain_intel output.

    Does NOT call the LLM. Returns a list of candidate dicts ready for
    the analyst worksheet JSON.

    Requirement B: all joins use full hand_id.
    """
    # Build hands_by_id lookup using FULL hand_id
    hands_by_id = {}
    for h in hands:
        hid = h.get('id', '')
        if hid:
            hands_by_id[hid] = h

    vi = villain_intel or {}

    # Extract from all 5 source types
    all_candidates = []
    all_candidates.extend(
        _extract_exploit_candidates(vi, hands_by_id, 'missed',
                                    'exploit_miss', 'P0'))
    all_candidates.extend(
        _extract_exploit_candidates(vi, hands_by_id, 'good',
                                    'exploit_good', 'P1'))
    all_candidates.extend(
        _extract_timing_unclear(vi, hands_by_id))
    all_candidates.extend(
        _extract_mixed_signal(vi, hands_by_id))
    all_candidates.extend(
        _extract_learning_hands(vi, hands_by_id))

    # Dedup: if a hand+villain appears in multiple source_types,
    # keep only the highest priority
    _priority_rank = {'P0': 0, 'P1': 1, 'P2': 2}
    seen = {}
    deduped = []
    for c in sorted(all_candidates,
                    key=lambda x: _priority_rank.get(x['priority'], 9)):
        key = (c['hand_id'], c['villain_key'])
        if key in seen:
            continue
        seen[key] = True
        deduped.append(c)

    # Sort: priority ascending, then n_evidence_atoms descending
    deduped.sort(key=lambda c: (
        _priority_rank.get(c['priority'], 9),
        -c['n_evidence_atoms'],
    ))

    # Budget cap
    result = deduped[:max_candidates]
    _log.info("Analyst candidates: %d extracted, %d after dedup, "
              "%d after budget cap (max=%d)",
              len(all_candidates), len(deduped), len(result), max_candidates)
    return result


# ── Worksheet I/O ────────────────────────────────────────────────────

def write_worksheet(candidates: list[dict], session_date: str,
                    hero_name: str, out_dir: str,
                    pipeline_version: str = 'v8.9.0') -> str:
    """Write analyst worksheet JSON to output directory.

    Requirement: worksheet must NOT be placed inside HH input directory.
    """
    filename = f'_analyst_villain_worksheet_{session_date}.json'
    path = os.path.join(out_dir, filename)

    worksheet = {
        'schema_version': SCHEMA_VERSION,
        'session_date': session_date,
        'hero_name': hero_name,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'pipeline_version': pipeline_version,
        'total_candidates': len(candidates),
        'instructions': (
            "For each candidate, fill analyst_verdict, analyst_coaching, "
            "analyst_severity, analyst_confidence. "
            "Do not modify det_* fields. "
            f"analyst_coaching max {MAX_COACHING_CHARS} chars."
        ),
        'candidates': candidates,
    }

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(worksheet, f, indent=2, ensure_ascii=False)

    _log.info("Wrote analyst worksheet: %s (%d candidates)", path,
              len(candidates))
    return path


def load_analyst_villain_review(path: str,
                                expected_session_date: str = ''
                                ) -> dict:
    """Load and validate analyst review JSON.

    Returns dict keyed by candidate_id -> analyst fields.
    Requirement C: only reads analyst_* fields, never overwrites det_*.
    Requirement D: rejected items included in return with debug count.
    Requirement I: coaching truncated to MAX_COACHING_CHARS.

    Returns:
        {
            'candidates_by_id': { candidate_id: { analyst_* fields } },
            'debug': { 'total': N, 'confirmed': N, 'rejected': N,
                       'borderline': N, 'upgraded': N, 'invalid': N },
        }
    """
    if not path or not os.path.isfile(path):
        _log.warning("Analyst file not found: %s", path)
        return {'candidates_by_id': {}, 'debug': {}}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _log.error("Failed to load analyst file %s: %s", path, e)
        return {'candidates_by_id': {}, 'debug': {}}

    # Schema version check
    sv = data.get('schema_version', '')
    if sv and sv != SCHEMA_VERSION:
        _log.warning("Analyst file schema version mismatch: "
                     "expected %s, got %s", SCHEMA_VERSION, sv)

    # Session date check
    if expected_session_date and data.get('session_date', '') != expected_session_date:
        _log.warning("Analyst file session date mismatch: "
                     "expected %s, got %s",
                     expected_session_date, data.get('session_date'))

    candidates = data.get('candidates', [])
    by_id = {}
    debug = {'total': len(candidates), 'confirmed': 0, 'rejected': 0,
             'borderline': 0, 'upgraded': 0, 'invalid': 0}

    for c in candidates:
        cid = c.get('candidate_id', '')
        if not cid:
            debug['invalid'] += 1
            continue

        verdict = c.get('analyst_verdict', '')
        if verdict not in VALID_VERDICTS:
            _log.warning("Invalid analyst_verdict '%s' for candidate %s "
                         "— skipping", verdict, cid)
            debug['invalid'] += 1
            continue

        severity = c.get('analyst_severity', '')
        if severity and severity not in VALID_SEVERITIES:
            _log.warning("Invalid analyst_severity '%s' for %s "
                         "— defaulting to 'medium'", severity, cid)
            severity = 'medium'

        confidence = c.get('analyst_confidence', '')
        if confidence and confidence not in VALID_CONFIDENCES:
            confidence = 'medium'

        coaching = c.get('analyst_coaching', '')
        # Requirement I: truncate coaching
        if len(coaching) > MAX_COACHING_CHARS:
            coaching = coaching[:MAX_COACHING_CHARS].rsplit(' ', 1)[0] + '...'

        # Confirmed/upgraded require non-empty coaching
        if verdict in ('confirmed', 'upgraded') and not coaching:
            _log.warning("Candidate %s has verdict '%s' but empty coaching "
                         "— downgrading to borderline", cid, verdict)
            verdict = 'borderline'

        debug[verdict] = debug.get(verdict, 0) + 1

        # Requirement C: only extract analyst_* fields
        by_id[cid] = {
            'analyst_verdict': verdict,
            'analyst_coaching': coaching,
            'analyst_severity': severity or 'medium',
            'analyst_confidence': confidence or 'medium',
            'analyst_note': c.get('analyst_note', ''),
        }

    # Build convenience index: (hand_id_short, villain_key) → list of reviews
    # This lets the renderer look up analyst data without importing the hash func
    by_hv = {}
    for c in candidates:
        cid = c.get('candidate_id', '')
        if cid not in by_id:
            continue  # skip invalid/skipped candidates
        hid = c.get('hand_id', '')
        hid_short = hid[-8:] if len(hid) > 8 else hid
        vk = c.get('villain_key', '')
        st = c.get('source_type', '')
        by_hv.setdefault((hid_short, vk), []).append({
            **by_id[cid],
            'source_type': st,
            'candidate_id': cid,
        })

    _log.info("Loaded analyst review: %d candidates, %d valid "
              "(%d confirmed, %d rejected, %d borderline, %d upgraded, "
              "%d invalid)",
              debug['total'], debug['total'] - debug['invalid'],
              debug['confirmed'], debug['rejected'],
              debug['borderline'], debug['upgraded'], debug['invalid'])

    return {'candidates_by_id': by_id, 'by_hand_villain': by_hv,
            'debug': debug}


# ── Renderer fallback labels (Requirement H) ─────────────────────────

FALLBACK_LABELS = {
    'not_reviewed': 'Deterministic analysis — not yet analyst-reviewed',
    'stale': 'Analyst review may be stale (pipeline version mismatch)',
    'invalid': 'Analyst review had validation errors — using deterministic',
}
