"""gem_analyst_packet.py -- the ONE sealed, self-contained analyst packet + fail-closed validator
(v8.20 Iteration-4, one-pass Claude Chat efficiency).

The deterministic full run (`python gem_analyzer.py <SESSION_DIR>`) emits ONE sealed packet that contains
every fact and pre-completed calculation the analyst needs. The analyst reads the packet ONCE, reviews
each required decision exactly once, fetches/calculates nothing, emits one schema-valid JSON, and a single
cache-guarded `--quick` render follows.

No new runner, no new evaluator: the packet is assembled from the canonical discovery candidates
(gem_discovery_context) + final-truth + the keyed owner-rule/chart evidence dictionary. Deterministic
calculations are completed BEFORE emission; the packet never asks Chat to compute equity / pot odds / EV /
effective stack / SPR / hand class / price / range weights.
"""
import hashlib

SCHEMA_VERSION = 'analyst_packet_v1'
ALLOWED_VERDICTS = ('CONFIRMED_MISTAKE', 'JUSTIFIED', 'READ_DEPENDENT', 'INSUFFICIENT_EVIDENCE', 'DETECTOR_BUG')
REQUIRED_OUTPUT_FIELDS = ('decision_id', 'verdict', 'reason')

# packet-level keyed evidence dictionary -- each excerpt stored ONCE, referenced by decision (never
# duplicated per hand, and never a full reference file the analyst must open).
EVIDENCE = {
    'owner_rule.sb_3bet_or_fold':
        'Accepted rule: in the SB versus a single late (BTN/CO) open at 20-40bb effective, the play is '
        '3-bet or fold. Flat-calling out of position is a leak (you are OOP with the BB still able to '
        'squeeze and poor equity realization).',
    'owner_rule.deep_stackoff':
        'Accepted rule: avoid deep preflop stack-offs above 40bb except AA/KK, unless a concrete canonical '
        'chart or forced-action exception applies. Do not infer from the result.',
    'owner_rule.short_stack_coldcall':
        'A genuine non-BB flat (chips behind) at <15bb is chart-governed; an all-in call is push/fold and '
        'is a different decision. BB calls are excluded from the rule.',
    'concept.missed_river_value':
        'A genuinely strong made hand (trips+ using hole cards) that checks the river through or bets a '
        'materially small size forfeits value worse made hands would pay -- a result-independent error.',
}


def _norm_decision(c):
    """One sealed decision record from a discovery candidate. Every operand is already computed."""
    ctx = c.get('context', {}) or {}
    fam = c.get('family')
    ev_key = {'sb_flat_vs_late_open': 'owner_rule.sb_3bet_or_fold',
              'deep_preflop_stackoff': 'owner_rule.deep_stackoff',
              'short_stack_coldcall': 'owner_rule.short_stack_coldcall',
              'river_value': 'concept.missed_river_value'}.get(fam)
    return {
        'decision_id': c.get('decision_id'),
        'hand_id': c.get('hand_id'),
        'family': fam,
        'street': ctx.get('street') or c.get('street'),
        'hero_action': c.get('hero_action') or ctx.get('hero_action'),
        'hero_cards': ctx.get('hero_cards'),
        'board': ctx.get('board'),
        'hand_code': ctx.get('hand_code'),
        'made_hand_class': ctx.get('made_hand_class'),
        'draw_profile': ctx.get('draw_profile'),
        'board_texture': ctx.get('board_texture'),
        'position': ctx.get('position'),
        'opener_position': ctx.get('opener_position'),
        'active_players': ctx.get('active_players'),
        'eff_stack_bb': ctx.get('eff_stack_bb'),
        'pot_before_bb': ctx.get('pot_before_bb'),
        'spr': ctx.get('spr'),
        'action_line': ctx.get('action_line'),
        'detector_reason': c.get('detector_reason'),
        'evidence_ref': ev_key,
        'evidence_tier': c.get('evidence_tier'),
        'prior_final_class': c.get('prior_final_class'),
        'prior_decision_id': c.get('prior_decision_id'),
        'relationship': c.get('relationship'),
        'missing_assumptions': c.get('missing_assumptions', []),
        'allowed_verdicts': list(ALLOWED_VERDICTS),
        'required_output_fields': list(REQUIRED_OUTPUT_FIELDS),
        'proposed_alternative': c.get('proposed_alternative'),
    }


def _legacy_required_decision(hand_id, rd):
    """A required-review decision for a hand from the CANONICAL legacy required population. Carries its
    prior reviewed decision ref + prior verdict so accepted analyst verdicts remain reproducible."""
    ft = (rd.get('final_truth') or {}).get('records', {}) or {}
    rec = ft.get(hand_id) or {}
    ref = (rd.get('reviewed_decision_ref_by_hand') or {}).get(hand_id)
    bucket = (rd.get('_candidate_need_bucket') or {}).get(hand_id)
    return {
        'decision_id': ref or ('%s:required' % hand_id),
        'hand_id': hand_id, 'family': 'legacy_required_review', 'street': None,
        'detector_reason': 'canonical required-review hand (need bucket %s)' % bucket,
        'evidence_ref': None, 'evidence_tier': 'canonical_required_population',
        'prior_final_class': rec.get('final_class'), 'prior_verdict': rec.get('verdict'),
        'prior_decision_id': ref, 'relationship': 'REQUIRED_REVIEW',
        'missing_assumptions': [], 'allowed_verdicts': list(ALLOWED_VERDICTS),
        'required_output_fields': list(REQUIRED_OUTPUT_FIELDS),
    }


def legacy_required_ids(rd):
    """The CANONICAL legacy mandatory review population (owner gap 3): the production required-review
    hands -- _candidate_need_ids plus every material-loss-population hand. NOT defined by the new packet."""
    out = list(rd.get('_candidate_need_ids') or [])
    mlp = rd.get('material_loss_population')
    if isinstance(mlp, dict):
        out += [h for h in mlp.keys() if not str(h).startswith('_')]
    elif isinstance(mlp, list):
        out += [m.get('id') for m in mlp if isinstance(m, dict) and m.get('id')]
    seen, uniq = set(), []
    for h in out:
        if h and h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def _content_hash(payload):
    """SHA-256 over the CANONICAL serialization of the packet contents (every field except the hash
    itself). Any change to a decision fact, evidence excerpt, input hash, runtime identity, cache
    identity, or queue membership changes the hash (owner gap 4)."""
    import json
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     default=str).encode('utf-8')).hexdigest()


def build_packet(hands, rd, *, session_id='', input_hashes=None, runtime_version='',
                 runtime_commit='', cache_identity='', optional_cap=8):
    """Build the ONE sealed analyst packet. REQUIRED = the canonical legacy required-review population
    (preserved 100%) PLUS the accepted rule-backed findings (the KQs SB-flat). OPTIONAL = lower-confidence
    read-dependent candidates, capped. Each hand/decision appears once; nothing required is demoted. The
    packet_hash binds all contents + input/runtime/cache identity."""
    import gem_discovery_context as _dc
    prior = (rd.get('final_truth') or {}).get('records', {}) if isinstance(rd, dict) else {}
    val = _dc.run_value(hands, prior)
    confirmed_ids = {r['decision_id'] for r in val['confirmed']}
    discovery = {c.get('decision_id'): _norm_decision(c) for c in val['candidates']}
    rule_required = {c.get('decision_id'): _norm_decision(c) for c in val['candidates']
                     if c.get('family') == 'sb_flat_vs_late_open' or c.get('decision_id') in confirmed_ids}

    required, optional, by_hand = [], [], {}
    # 1. the canonical legacy required population FIRST (parity) -- one decision per hand.
    for hid in legacy_required_ids(rd):
        if hid in by_hand:
            continue
        rec = _legacy_required_decision(hid, rd)
        by_hand[hid] = rec['decision_id']
        required.append(rec)
    # 2. add the accepted rule-backed findings (KQs) if not already covered by the legacy hand.
    for did, rec in rule_required.items():
        if rec['hand_id'] in by_hand:
            continue
        by_hand[rec['hand_id']] = did
        required.append(rec)
    # 3. optional = remaining read-dependent discovery candidates (capped), never a required hand.
    req_dids = {r['decision_id'] for r in required}
    req_hands = set(by_hand.keys())
    for did, rec in discovery.items():
        if did in req_dids or rec['hand_id'] in req_hands:
            continue
        optional.append(rec)
    optional = optional[:optional_cap]

    evidence = {k: EVIDENCE[k] for k in sorted({d['evidence_ref'] for d in required + optional if d.get('evidence_ref')})}
    manifest = {
        'schema': SCHEMA_VERSION, 'session_id': session_id,
        'input_hashes': input_hashes or {}, 'runtime_version': runtime_version,
        'runtime_commit': runtime_commit, 'cache_identity': cache_identity,
        'required_count': len(required), 'optional_count': len(optional), 'optional_cap': optional_cap,
        'evidence_keys': sorted(evidence.keys()), 'allowed_verdicts': list(ALLOWED_VERDICTS),
    }
    packet = {'manifest': manifest, 'evidence': evidence, 'required': required, 'optional': optional}
    manifest['packet_hash'] = _content_hash(packet)   # over contents that exclude packet_hash itself
    return packet


def validate_analyst_output(packet, analyst, cache_ok=True):
    """Fail-closed validator run BEFORE the quick render. REQUIRES session_id + packet_hash (rejects when
    missing), exactly one verdict per required decision, at most one per optional, the allowed enum, only
    packet-provided decision/evidence refs, no unknown/duplicate decisions, no unbound external evidence,
    and a fresh cache. A failure returns concise errors -- never a second analyst pass."""
    errors = []
    m = packet['manifest']
    if not analyst.get('session_id'):
        errors.append('missing required session_id binding')
    elif analyst['session_id'] != m['session_id']:
        errors.append('analyst output bound to the wrong session: %s' % analyst.get('session_id'))
    if not analyst.get('packet_hash'):
        errors.append('missing required packet_hash binding')
    elif analyst['packet_hash'] != m['packet_hash']:
        errors.append('analyst output bound to the wrong packet hash')
    if not cache_ok:
        errors.append('stale or missing deterministic cache -- rerun the full pipeline')
    decisions = {d['decision_id']: d for d in packet['required'] + packet['optional']}
    required_ids = {d['decision_id'] for d in packet['required']}
    optional_ids = {d['decision_id'] for d in packet['optional']}
    counts = {}
    for a in (analyst.get('verdicts') or []):
        did = a.get('decision_id')
        if did not in decisions:
            errors.append('unknown decision id: %s' % did)
            continue
        counts[did] = counts.get(did, 0) + 1
        if a.get('verdict') not in ALLOWED_VERDICTS:
            errors.append('verdict outside allowed enum (%s): %s' % (did, a.get('verdict')))
        # structured refs only: any evidence_ref / fact_ref the analyst cites must be packet-provided.
        for ref in (a.get('evidence_refs') or []):
            if ref not in packet.get('evidence', {}):
                errors.append('cites evidence not in packet (%s): %s' % (did, ref))
        for fr in (a.get('fact_refs') or []):
            if fr not in decisions[did]:
                errors.append('cites a fact not in the decision record (%s): %s' % (did, fr))
    for did in required_ids:
        if counts.get(did, 0) == 0:
            errors.append('missing required decision verdict: %s' % did)
        elif counts.get(did, 0) > 1:
            errors.append('duplicate required verdict: %s' % did)
    for did in optional_ids:
        if counts.get(did, 0) > 1:
            errors.append('duplicate optional verdict: %s' % did)
    if analyst.get('cited_external_evidence'):
        errors.append('analyst cited unprovided external evidence')
    covered = len([d for d in required_ids if counts.get(d, 0) >= 1])
    return {'valid': not errors, 'errors': errors,
            'required_coverage': round(covered / max(len(required_ids), 1), 3)}


def build_coverage_reconciliation(rd, packet):
    """Owner gap 3 artifact: reconcile the sealed packet's required population against the CANONICAL
    legacy required-review population. The invariant is legacy_required - sealed_required == empty."""
    legacy = legacy_required_ids(rd)
    sealed_required_hands = sorted({d['hand_id'] for d in packet['required']})
    sealed_optional_hands = sorted({d['hand_id'] for d in packet['optional']})
    missing = sorted(set(legacy) - set(sealed_required_hands))
    demoted = sorted(set(legacy) & set(sealed_optional_hands))
    # one decision per hand (no duplicate)
    from collections import Counter
    dup = [h for h, n in Counter(d['hand_id'] for d in packet['required']).items() if n > 1]
    kqs = 'TM6084610450'
    kqs_present_required = any(d['hand_id'] == kqs for d in packet['required'])
    return {
        'session': packet['manifest'].get('session_id'),
        'legacy_required_count': len(legacy),
        'sealed_required_count': len(sealed_required_hands),
        'legacy_minus_sealed_required': missing,
        'required_demoted_to_optional': demoted,
        'duplicate_required_hands': dup,
        'kqs_sb_flat_present_and_required': kqs_present_required,
        'optional_count': len(sealed_optional_hands), 'optional_cap': packet['manifest'].get('optional_cap'),
        'parity_pass': bool(not missing and not demoted and not dup),
        'invariants_pass': bool(not missing and not demoted and not dup and kqs_present_required),
    }
