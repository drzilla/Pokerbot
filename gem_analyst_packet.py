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


def build_packet(hands, rd, *, session_id='', input_hashes=None, runtime_version='', optional_cap=8):
    """Build the ONE sealed analyst packet: required queue (high-confidence rule/chart violations) +
    optional queue (lower-confidence, capped) + keyed evidence + manifest. Each hand/decision appears
    once. Pure."""
    import gem_discovery_context as _dc
    prior = (rd.get('final_truth') or {}).get('records', {}) if isinstance(rd, dict) else {}
    val = _dc.run_value(hands, prior)
    required, optional, seen = [], [], set()
    # required: rule/chart violations confirmable now (the rule-backed SB-flat family). optional: the rest.
    confirmed_ids = {r['decision_id'] for r in val['confirmed']}
    for c in val['candidates']:
        did = c.get('decision_id')
        if did in seen:
            continue
        seen.add(did)
        rec = _norm_decision(c)
        if c.get('family') == 'sb_flat_vs_late_open' or did in confirmed_ids:
            required.append(rec)
        else:
            optional.append(rec)
    optional = optional[:optional_cap]
    manifest = {
        'schema': SCHEMA_VERSION, 'session_id': session_id,
        'input_hashes': input_hashes or {}, 'runtime_version': runtime_version,
        'required_count': len(required), 'optional_count': len(optional),
        'optional_cap': optional_cap,
        'evidence_keys': sorted(EVIDENCE.keys()),
        'allowed_verdicts': list(ALLOWED_VERDICTS),
    }
    manifest['packet_hash'] = hashlib.sha256(
        ('%s|%s|%d|%d' % (SCHEMA_VERSION, session_id, len(required), len(optional))).encode()).hexdigest()[:16]
    return {'manifest': manifest, 'evidence': {k: EVIDENCE[k] for k in
            sorted({d['evidence_ref'] for d in required + optional if d['evidence_ref']})},
            'required': required, 'optional': optional}


def validate_analyst_output(packet, analyst):
    """Fail-closed validator run BEFORE the quick render. Returns {valid, errors}. Rejects unknown/dup
    decisions, missing required decisions, out-of-enum verdicts, wrong session/packet binding, and any
    exact numeric claim not present in the packet. Never silently launches another analyst pass."""
    errors = []
    decisions = {d['decision_id']: d for d in packet['required'] + packet['optional']}
    required_ids = {d['decision_id'] for d in packet['required']}
    import re
    seen = set()
    for a in (analyst.get('verdicts') or []):
        did = a.get('decision_id')
        if did not in decisions:
            errors.append('unknown decision id: %s' % did)
            continue
        if did in seen:
            errors.append('duplicate decision: %s' % did)
        seen.add(did)
        if a.get('verdict') not in ALLOWED_VERDICTS:
            errors.append('verdict outside allowed enum (%s): %s' % (did, a.get('verdict')))
        # an exact numeric claim in the reason must already be present in the decision's packet facts.
        d = decisions[did]
        facts_blob = str({k: d.get(k) for k in ('eff_stack_bb', 'pot_before_bb', 'spr', 'board',
                          'hand_code', 'action_line', 'detector_reason')})
        for num in re.findall(r'\d+(?:\.\d+)?\s*(?:%|bb|BB)', str(a.get('reason', ''))):
            base = re.match(r'\d+(?:\.\d+)?', num).group(0)
            if base not in facts_blob:
                errors.append('exact numeric claim not in packet (%s): %s' % (did, num))
    missing = sorted(required_ids - seen)
    if missing:
        errors.append('missing required decisions: %s' % missing)
    if analyst.get('session_id') and analyst['session_id'] != packet['manifest']['session_id']:
        errors.append('analyst output bound to the wrong session: %s' % analyst.get('session_id'))
    if analyst.get('packet_hash') and analyst['packet_hash'] != packet['manifest']['packet_hash']:
        errors.append('analyst output bound to the wrong packet hash')
    if analyst.get('cited_external_evidence'):
        errors.append('analyst cited unprovided external evidence')
    return {'valid': not errors, 'errors': errors,
            'required_coverage': round(len(seen & required_ids) / max(len(required_ids), 1), 3)}
