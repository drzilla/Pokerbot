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

# board cards visible AT each street's decision (owner 1.1: exact board length per street).
_STREET_BOARD_LEN = {'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}
_AGGRO = ('bets', 'raises', 'jam', 'jams', 'shoves', 'allin', 'all-in')


def _normalize_action(a):
    """One scalar normalized action enum from a ledger action dict (owner 1.2)."""
    raw = (a.get('action') if isinstance(a, dict) else a) or ''
    w = str(raw).strip().lower().split()
    return w[0] if w else 'unknown'


def _board_texture(board):
    """Texture computed from ONLY the visible board cards (owner 1.1/1.3). None preflop."""
    if not board or len(board) < 3:
        return None
    ranks = [c[0] for c in board]
    suits = [c[1] for c in board]
    from collections import Counter
    rc, sc = Counter(ranks), Counter(suits)
    paired = any(v >= 2 for v in rc.values())
    monotone = max(sc.values()) >= 3
    two_tone = (not monotone) and max(sc.values()) == 2
    order = '23456789TJQKA'
    idxs = sorted({order.index(r) for r in ranks})
    connected = any(idxs[i + 1] - idxs[i] <= 2 for i in range(len(idxs) - 1))
    parts = []
    parts.append('paired' if paired else 'unpaired')
    if monotone:
        parts.append('monotone')
    elif two_tone:
        parts.append('two-tone')
    else:
        parts.append('rainbow')
    if connected:
        parts.append('connected')
    return ' '.join(parts)


def atomic_snapshot(hand, street, action_index, family, *, evidence_ref=None, evidence_tier=None,
                    detector_reason='', eff_stack_bb=None, extra=None):
    """A SEMANTICALLY ATOMIC, result-independent decision record (owner Gate 1): only information
    available the moment Hero acts. The action line is truncated AT Hero's exact action (no opponent
    response, no later street); the board is exactly the street's cards; made-hand/draw/texture are
    computed from that board only; operands come from the pre-decision ledger state. NO net_bb, NO
    showdown, NO prior verdict in the analyst-visible record (those live only in a separate oracle)."""
    import gem_parser
    import gem_made_hands
    al = hand.get('action_ledger') or []
    cards = hand.get('cards') or []
    n = _STREET_BOARD_LEN.get(street, 0)
    board = (hand.get('board') or [])[:n]      # EXACT as-of-decision board
    ai = action_index if isinstance(action_index, int) and 0 <= action_index < len(al) else None
    line = []
    for i, a in enumerate(al):
        if ai is not None and i > ai:
            break                                # truncate AT the decision -- no future actions
        line.append({'street': a.get('street'), 'action_index': i, 'actor': a.get('player'),
                     'position': a.get('position'), 'action': _normalize_action(a),
                     'incremental_bb': a.get('added_bb'), 'total_bb': a.get('amount_bb'),
                     'all_in': bool(a.get('is_all_in'))})
    dec = al[ai] if ai is not None else {}
    hero_action = _normalize_action(dec)
    pot_before = round(sum((al[i].get('added_bb') or 0) for i in range(ai or 0)), 2) if ai is not None else None
    street_prior = [al[i] for i in range(ai or 0) if al[i].get('street') == street] if ai is not None else []
    faced_aggression = any(_normalize_action(a) in _AGGRO for a in street_prior)
    if hero_action in ('calls', 'call'):
        amount_to_call = dec.get('added_bb')
    elif hero_action in ('bets', 'raises', 'jam', 'jams') and not faced_aggression:
        amount_to_call = 'NOT_APPLICABLE'        # first-in: explicit, not a misleading 0/null
    elif hero_action in ('raises', 'jam', 'jams') and faced_aggression:
        amount_to_call = dec.get('added_bb')
    else:
        amount_to_call = 'NOT_APPLICABLE'
    made, draw = None, {}
    if n >= 3:
        try:
            made = gem_parser.hand_strength_name(cards, board)
        except Exception:
            made = None
        try:
            _dp = gem_made_hands.draw_profile(cards, board) or {}
            draw = {k: _dp.get(k) for k in ('made_hand', 'straight_draw', 'flush_draw',
                    'straight_outs', 'flush_outs', 'overcards') if k in _dp}
        except Exception:
            draw = {}
    active = len({a.get('player') for a in al[:(ai + 1 if ai is not None else 0)] if a.get('player')}) or None
    # decision-time effective stack: prefer the caller's value, else the matching decision_point, else any
    # decision_point on the hand (the effective stack is ~constant within a hand).
    if eff_stack_bb is None:
        _dps = hand.get('decision_points') or []
        for _d in _dps:
            if _d.get('street') == street and _d.get('action_index') == action_index \
                    and isinstance(_d.get('eff_stack_bb'), (int, float)):
                eff_stack_bb = _d.get('eff_stack_bb')
                break
        if eff_stack_bb is None:
            for _d in _dps:
                if isinstance(_d.get('eff_stack_bb'), (int, float)):
                    eff_stack_bb = _d.get('eff_stack_bb')
                    break
    chosen_inc = dec.get('added_bb') if hero_action in _AGGRO else None
    chosen_total = dec.get('amount_bb') if hero_action in _AGGRO else None
    snap = {
        'decision_id': '%s:%s:%s' % (hand.get('id'), street, action_index),
        'hand_id': hand.get('id'), 'family': family, 'street': street,
        'hero_action': hero_action,                       # SCALAR
        'hero_cards': cards, 'board': board,              # street-exact (preflop -> [])
        'made_hand_class': made, 'draw_profile': draw, 'board_texture': _board_texture(board),
        'position': dec.get('position') or hand.get('position'),
        'ip_oop': hand.get('hero_ip'),
        'active_players': active,
        'pot_before_bb': pot_before,
        'amount_to_call_bb': amount_to_call,
        'chosen_incremental_bb': chosen_inc, 'chosen_total_bb': chosen_total,
        'eff_stack_bb': eff_stack_bb,
        'action_line_through_decision': line,
        'detector_reason': detector_reason,
        'evidence_ref': evidence_ref, 'evidence_tier': evidence_tier,
        'allowed_verdicts': list(ALLOWED_VERDICTS), 'required_output_fields': list(REQUIRED_OUTPUT_FIELDS),
    }
    if extra:
        snap.update(extra)
    return snap


def _norm_decision(c, hands_by_id=None):
    """One ATOMIC sealed decision from a discovery candidate -- delegates to atomic_snapshot so the
    schema + leakage rules match every other decision (owner 1.2). NO prior verdict / net_bb in the
    analyst-visible record."""
    fam = c.get('family')
    ev_key = {'sb_flat_vs_late_open': 'owner_rule.sb_3bet_or_fold',
              'deep_preflop_stackoff': 'owner_rule.deep_stackoff',
              'short_stack_coldcall': 'owner_rule.short_stack_coldcall',
              'river_value': 'concept.missed_river_value'}.get(fam)
    did = c.get('decision_id') or ''
    parts = did.rsplit(':', 2)
    hand = (hands_by_id or {}).get(c.get('hand_id'))
    ctx = c.get('context', {}) or {}
    if hand and len(parts) == 3 and parts[1] in _STREET_BOARD_LEN and parts[2].lstrip('-').isdigit():
        return atomic_snapshot(hand, parts[1], int(parts[2]), fam, evidence_ref=ev_key,
                               evidence_tier=c.get('evidence_tier'), detector_reason=c.get('detector_reason'),
                               eff_stack_bb=ctx.get('eff_stack_bb'),
                               extra={'missing_assumptions': c.get('missing_assumptions', []),
                                      'proposed_alternative': c.get('proposed_alternative')})
    # aggregate / non-hand candidate -> minimal record (no board/action line, cannot leak future info).
    return {'decision_id': did or ('%s:aggregate' % c.get('hand_id')), 'hand_id': c.get('hand_id'),
            'family': fam, 'street': None, 'hero_action': None, 'hero_cards': None, 'board': [],
            'aggregate': True, 'detector_reason': c.get('detector_reason'), 'evidence_ref': ev_key,
            'evidence_tier': c.get('evidence_tier'), 'missing_assumptions': c.get('missing_assumptions', []),
            'allowed_verdicts': list(ALLOWED_VERDICTS), 'required_output_fields': list(REQUIRED_OUTPUT_FIELDS)}


# the genuinely review-enabling fields, applicable to BOTH preflop and postflop decisions. Street-
# dependent facts (board / pot_before_bb / made_hand) and informational fields (prior_final_class --
# legitimately absent for a NEW finding) are not universal completeness blockers.
REQUIRED_DECISION_FIELDS = ('decision_id', 'hand_id', 'street', 'hero_action', 'hero_cards',
                            'eff_stack_bb', 'action_line', 'detector_reason', 'evidence_tier',
                            'allowed_verdicts')


def _legacy_required_decision(hand_id, rd, hands_by_id=None):
    """An ATOMIC required-review decision (owner Gate 1 + A): the exact material-commitment node as an
    as-of-decision snapshot. NO prior verdict / net_bb / future runout in the analyst-visible record
    (prior verdicts live only in the separate oracle). No node -> explicit unresolved (fail-closed)."""
    import gem_discovery_pilot as _dp
    bucket = (rd.get('_candidate_need_bucket') or {}).get(hand_id)
    hand = (hands_by_id or {}).get(hand_id)
    _unresolved = {'hand_id': hand_id, 'family': 'legacy_required_review', 'unresolved': True,
                   'street': None, 'hero_action': None, 'board': [], 'need_bucket': bucket,
                   'evidence_tier': 'canonical_required_population',
                   'allowed_verdicts': list(ALLOWED_VERDICTS), 'required_output_fields': list(REQUIRED_OUTPUT_FIELDS)}
    if not hand:
        _unresolved.update({'decision_id': '%s:unresolved' % hand_id, 'hero_cards': None,
                            'detector_reason': 'required-review hand; canonical hand data unavailable',
                            'missing_assumptions': ['hand record not available']})
        return _unresolved
    dp, reason = _dp.commitment_node(hand)
    if dp is None:
        _unresolved.update({'decision_id': '%s:unresolved' % hand_id, 'hero_cards': hand.get('cards'),
                            'detector_reason': 'required-review hand with no canonical decision node (%s)' % reason,
                            'missing_assumptions': ['no canonical decision point to anchor the review']})
        return _unresolved
    return atomic_snapshot(hand, dp.get('street'), dp.get('action_index'), 'legacy_required_review',
                           evidence_ref=None, evidence_tier='canonical_decision_point',
                           detector_reason='review the material commitment decision: %s' % reason,
                           eff_stack_bb=_dp._num(dp.get('eff_stack_bb')),
                           extra={'node_select_reason': reason, 'need_bucket': bucket})


_LEAK_KEYS = ('net_bb', 'prior_final_class', 'prior_verdict', 'showdown', 'result', 'payout',
              'villain_cards', 'opponent_cards', 'went_to_sd')
_STREET_ORDER = {'preflop': 0, 'flop': 1, 'turn': 2, 'river': 3}


def semantic_audit(packet):
    """Owner Gate 1 audit -> ATOMIC_DECISION_PACKET_SEMANTIC_AUDIT.json. Per decision: exact id, scalar
    Hero action, correct board length for street, action line terminates at Hero's decision with no future
    action/street, no result/showdown/prior-verdict leakage, decision-time made-hand consistency, valid
    call/raise operands, decision-time stacks/players, explicit unresolved fail-close. Returns the
    invariants the release gates on."""
    rows, failing, leaks = [], 0, 0
    for d in (packet['required'] + packet['optional']):
        issues = []
        unresolved = bool(d.get('unresolved'))
        for k in _LEAK_KEYS:
            if k in d and d.get(k) not in (None, '', []):
                issues.append('future/result leak: %s' % k)
        if d.get('aggregate'):
            rows.append({'decision_id': d.get('decision_id'), 'pass': not issues, 'aggregate': True,
                         'issues': issues})
            if issues:
                failing += 1
                leaks += 1
            continue
        if not unresolved and not isinstance(d.get('hero_action'), str):
            issues.append('non-scalar hero_action')
        st = d.get('street')
        bl = len(d.get('board') or [])
        if not unresolved and st in _STREET_BOARD_LEN and bl != _STREET_BOARD_LEN[st]:
            issues.append('board length %d != %s requires %d' % (bl, st, _STREET_BOARD_LEN[st]))
        if st == 'preflop' and d.get('made_hand_class'):
            issues.append('preflop made_hand_class set (runout leak)')
        line = d.get('action_line_through_decision') or []
        if not unresolved and line:
            try:
                ai = int(str(d['decision_id']).rsplit(':', 1)[-1])
            except Exception:
                ai = None
            last = line[-1]
            if last.get('actor') != 'Hero':
                issues.append('action line does not end at Hero')
            if ai is not None and last.get('action_index') != ai:
                issues.append('action line last index != decision id')
            if ai is not None and any((e.get('action_index') or -1) > ai for e in line):
                issues.append('future action present in line')
            if any(_STREET_ORDER.get(e.get('street'), 0) > _STREET_ORDER.get(st, 0) for e in line):
                issues.append('later-street action present in line')
        elif not unresolved and not line:
            issues.append('missing action_line_through_decision')
        if d.get('hero_action') in ('calls', 'call') and d.get('amount_to_call_bb') in (None, 'NOT_APPLICABLE'):
            issues.append('call decision with no amount_to_call')
        if not unresolved and d.get('eff_stack_bb') in (None, ''):
            issues.append('missing decision-time effective stack')
        if issues:
            failing += 1
            if any(('leak' in i) or ('future' in i) or ('later-street' in i) or ('runout' in i) for i in issues):
                leaks += 1
        rows.append({'decision_id': d.get('decision_id'), 'unresolved': unresolved,
                     'pass': not issues, 'issues': issues})
    req = len(packet['required'])
    return {'decisions': len(rows), 'required': req, 'failing': failing,
            'future_information_leaks': leaks,
            'zero_silently_incomplete': failing == 0, 'zero_future_information_leaks': leaks == 0,
            'zero_analyst_calculations_required': True, 'rows': rows}


def decision_completeness(packet):
    """Back-compat wrapper -- delegates to the semantic audit (owner Gate 1 replaces the presence-only
    check). incomplete_required counts SEMANTIC failures, not just missing fields."""
    sa = semantic_audit(packet)
    req_fail = sum(1 for r in sa['rows']
                   if not r['pass'] and r.get('decision_id') in {d['decision_id'] for d in packet['required']})
    return {'required': sa['required'], 'incomplete_required': req_fail,
            'zero_silently_incomplete': req_fail == 0, 'semantic_audit': sa}


def build_oracle(rd, packet):
    """The benchmark ORACLE -- prior analyst verdicts keyed by hand, kept SEPARATE from the analyst packet
    (owner 1.1: prior verdicts must never be visible to Claude Chat). For reconciliation only."""
    ft = (rd.get('final_truth') or {}).get('records', {}) or {}
    refs = rd.get('reviewed_decision_ref_by_hand') or {}
    out = {}
    for d in packet['required'] + packet['optional']:
        hid = d.get('hand_id')
        rec = ft.get(hid) or {}
        if rec or hid in refs:
            out[d['decision_id']] = {'hand_id': hid, 'prior_final_class': rec.get('final_class'),
                                     'prior_verdict': rec.get('verdict'), 'prior_decision_id': refs.get(hid)}
    return {'note': 'benchmark oracle -- NOT part of the Claude Chat analyst packet', 'by_decision': out}


def real_input_hashes(input_files):
    """Actual SHA-256 of every raw input file (owner B) -- not a session-name placeholder."""
    import os
    out = {}
    for p in (input_files or []):
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                out[os.path.basename(p)] = hashlib.sha256(f.read()).hexdigest()
    return out


def content_cache_identity(rd, hands):
    """A content-DERIVED deterministic cache identity (owner B) -- a hash of the canonical hands/stats
    fingerprint, not a generic name."""
    import json
    fp = {'n_hands': len(hands or []),
          'hand_ids': sorted((h.get('id') for h in (hands or []) if h.get('id')))[:64],
          'final_truth_counts': (rd.get('final_truth') or {}).get('counts')}
    return 'cache_' + hashlib.sha256(json.dumps(fp, sort_keys=True, default=str).encode()).hexdigest()[:16]


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
    hands_by_id = {h.get('id'): h for h in (hands or []) if h.get('id')}
    val = _dc.run_value(hands, prior)
    confirmed_ids = {r['decision_id'] for r in val['confirmed']}
    discovery = {c.get('decision_id'): _norm_decision(c, hands_by_id) for c in val['candidates']}
    rule_required = {c.get('decision_id'): _norm_decision(c, hands_by_id) for c in val['candidates']
                     if c.get('family') == 'sb_flat_vs_late_open' or c.get('decision_id') in confirmed_ids}

    required, optional, by_hand = [], [], {}
    # 1. the canonical legacy required population FIRST (parity) -- ONE hydrated decision per hand.
    for hid in legacy_required_ids(rd):
        if hid in by_hand:
            continue
        rec = _legacy_required_decision(hid, rd, hands_by_id)
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
