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
    'chart.flop_cbet_sizing_band':
        'Canonical flop c-bet sizing comes from gto_texture_archetypes.json (Dave coaching sessions '
        '2026-05-04..05-13): each COMPLETE board archetype x side (IP/OOP) x depth band carries a '
        'sanctioned c-bet sizing band (sizings_pct, % of pot). A c-bet size outside that band by more than '
        'the 10pp tolerance is off-reference; a GROSS deviation (>=25pp AND >=2x the largest or <=0.5x the '
        'smallest sanctioned size) on a single-target complete band is a result-independent sizing error. '
        'A dual-strategy band sanctions more than one size, so an off-band size there is analyst-judged, not '
        'auto-confirmed.',
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


def _normalize_kind(kind):
    """A canonical Hero-action-kind ('call_vs_jam', 'postflop_call', 'open_raise', ...) -> one scalar
    normalized verb (owner 1.2)."""
    k = str(kind or '').strip().lower()
    for base in ('check', 'fold', 'call', 'bet', 'raise', 'jam', 'shove', 'allin', 'all-in'):
        if k == base or k.startswith(base) or ('_' + base) in k:
            return {'shove': 'jam', 'allin': 'jam', 'all-in': 'jam'}.get(base, base)
    return _normalize_action({'action': k})


def atomic_snapshot(hand, street, action_index, family, *, evidence_ref=None, evidence_tier=None,
                    detector_reason='', eff_stack_bb=None, extra=None):
    """A SEMANTICALLY ATOMIC, result-independent, NO-CALCULATION-SAFE decision record (owner Gate 1 + the
    no-calc fix): every deterministic operand is CONSUMED from the canonical decision owners
    (gem_decision_snapshot.build_decision_snapshot + build_action_sizing_contract -- the same owners the
    visible report uses), never re-derived here. The action line is truncated AT Hero's exact action (no
    opponent response, no later street); the board is the canonical street-exact board; made-hand/draw/
    texture come from the canonical evaluators on that board. NO net_bb / showdown / prior verdict. When a
    canonical operand is unavailable the record is an explicit fail-closed UNRESOLVED node -- the analyst
    reconstructs nothing."""
    import gem_parser
    import gem_made_hands
    import gem_decision_snapshot as _ds
    hid = hand.get('id')
    al = hand.get('action_ledger') or []
    cards = hand.get('cards') or []
    # ---- canonical decision owners (do NOT recompute these) ----
    try:
        snap = _ds.build_decision_snapshot(hand, action_index)
    except Exception:
        snap = None
    try:
        sizing = _ds.build_action_sizing_contract(hand, action_index)
    except Exception:
        sizing = None
    decision_id = '%s:%s:%s' % (hid, street, action_index)
    base_meta = {'decision_id': decision_id, 'hand_id': hid, 'family': family,
                 'evidence_ref': evidence_ref, 'evidence_tier': evidence_tier,
                 'detector_reason': detector_reason,
                 'allowed_verdicts': list(ALLOWED_VERDICTS),
                 'required_output_fields': list(REQUIRED_OUTPUT_FIELDS)}
    # FAIL CLOSED when the canonical owner reports no real Hero decision or omits a core operand.
    if (snap is None or snap.get('no_hero_decision')
            or snap.get('pot_before_action_bb') is None
            or snap.get('hero_stack_before_action_bb') is None
            or snap.get('canonical_effective_decision_depth_bb') is None):
        rec = dict(base_meta)
        rec.update({'street': street, 'hero_action': None, 'hero_cards': cards, 'board': [],
                    'unresolved': True, 'canonical_resolved': False,
                    'missing_assumptions': ['canonical decision snapshot unavailable or incomplete -- '
                                            'do not reconstruct'],
                    'unresolved_reason': ('no_canonical_decision'
                                          if snap is None or snap.get('no_hero_decision')
                                          else 'missing_canonical_operand')})
        if extra:
            rec.update(extra)
        return rec
    # ---- consume canonical operands ----
    cst = snap.get('street') or street
    board = list(snap.get('board_at_decision') or [])
    hero_action = _normalize_kind(snap.get('hero_action_kind'))
    pot_before = snap.get('pot_before_action_bb')
    contestable = snap.get('contestable_pot_before_action_bb')
    hero_stack_before = snap.get('hero_stack_before_action_bb')
    hero_committed = snap.get('live_street_committed_before_bb')
    eff_depth = snap.get('canonical_effective_decision_depth_bb')
    price_applicable = bool(snap.get('price_applicable'))
    price_status = snap.get('decision_facing_state')
    callable_amt = snap.get('callable_amount_bb')
    req_eq = snap.get('required_equity_pct')
    active_list = snap.get('players_active_before_action') or []
    active_players = len(active_list) + 1            # active opponents (folded excluded) + Hero
    multiway = active_players >= 3
    position = snap.get('hero_position') or hand.get('position')
    # amount-to-call is ONLY the call component (callable_amount), never Hero's full added amount. It
    # applies whenever Hero FACES a wager -- for a CALL or a RAISE-facing-aggression alike. First-in /
    # check-option decisions are explicit NOT_APPLICABLE.
    facing = str(price_status or '').startswith('facing')
    amount_to_call = callable_amt if (facing and callable_amt is not None) else 'NOT_APPLICABLE'
    # required equity is the canonical CALL/FOLD price -- only when the price contract is applicable.
    required_equity = req_eq if (price_applicable and req_eq is not None) else 'NOT_APPLICABLE'
    pot_after_call = (round(pot_before + callable_amt, 2)
                      if (facing and pot_before is not None and callable_amt is not None)
                      else 'NOT_APPLICABLE')
    # sizing facts (incremental vs raise-to vs increment) from the canonical sizing contract.
    chosen_inc = (sizing or {}).get('amount_added_bb')
    chosen_total = (sizing or {}).get('live_betting_total_to_bb')
    raise_increment = (sizing or {}).get('raise_increment_bb')
    became_all_in = (sizing or {}).get('became_all_in')
    # decision risk = chips Hero physically commits, BOUNDED by the decision-time stack.
    decision_risk = chosen_inc if chosen_inc is not None else None
    if decision_risk is not None and hero_stack_before is not None:
        decision_risk = min(decision_risk, hero_stack_before)
    spr = (round(eff_depth / contestable, 2)
           if (contestable and eff_depth is not None and contestable > 0 and cst != 'preflop') else None)
    # canonical hand/draw/texture from the canonical evaluators on the street-exact board.
    made, draw, texture = None, {}, None
    if len(board) >= 3:
        try:
            made = gem_parser.hand_strength_name(cards, board)
        except Exception:
            made = None
        try:
            _dpf = gem_made_hands.draw_profile(cards, board) or {}
            draw = {k: _dpf.get(k) for k in ('made_hand', 'straight_draw', 'flush_draw',
                    'straight_outs', 'flush_outs', 'overcards') if k in _dpf}
        except Exception:
            draw = {}
        texture = _board_texture(board)
    # action line truncated AT Hero's exact ledger action (no future action/street).
    ai = action_index if isinstance(action_index, int) and 0 <= action_index < len(al) else None
    line = []
    for i, a in enumerate(al):
        if ai is not None and i > ai:
            break
        line.append({'street': a.get('street'), 'action_index': i, 'actor': a.get('player'),
                     'position': a.get('position'), 'action': _normalize_action(a),
                     'incremental_bb': a.get('added_bb'), 'total_bb': a.get('amount_bb'),
                     'all_in': bool(a.get('is_all_in'))})
    rec = dict(base_meta)
    rec.update({
        'street': cst, 'hero_action': hero_action,
        'hero_cards': cards, 'board': board,
        'made_hand_class': made, 'draw_profile': draw, 'board_texture': texture,
        'position': position, 'ip_oop': hand.get('hero_ip'),
        'active_players': active_players, 'multiway': multiway,
        'pot_before_bb': pot_before, 'contestable_pot_bb': contestable,
        'hero_stack_before_bb': hero_stack_before, 'hero_street_committed_bb': hero_committed,
        'eff_stack_bb': eff_depth,
        'price_status': price_status, 'price_applicable': price_applicable,
        'amount_to_call_bb': amount_to_call, 'required_equity_pct': required_equity,
        'pot_after_call_bb': pot_after_call,
        'chosen_incremental_bb': chosen_inc, 'chosen_total_bb': chosen_total,
        'raise_increment_bb': raise_increment, 'became_all_in': became_all_in,
        'decision_risk_bb': decision_risk, 'spr': spr,
        'action_line_through_decision': line,
        'canonical_resolved': True, 'canonical_source': 'gem_decision_snapshot',
    })
    if extra:
        rec.update(extra)
    return rec


def _norm_decision(c, hands_by_id=None):
    """One ATOMIC sealed decision from a discovery candidate -- delegates to atomic_snapshot so the
    schema + leakage rules match every other decision (owner 1.2). NO prior verdict / net_bb in the
    analyst-visible record."""
    fam = c.get('family')
    ev_key = {'sb_flat_vs_late_open': 'owner_rule.sb_3bet_or_fold',
              'deep_preflop_stackoff': 'owner_rule.deep_stackoff',
              'short_stack_coldcall': 'owner_rule.short_stack_coldcall',
              'river_value': 'concept.missed_river_value',
              'flop_cbet_sizing': 'chart.flop_cbet_sizing_band'}.get(fam)
    did = c.get('decision_id') or ''
    parts = did.rsplit(':', 2)
    hand = (hands_by_id or {}).get(c.get('hand_id'))
    ctx = c.get('context', {}) or {}
    if hand and len(parts) == 3 and parts[1] in _STREET_BOARD_LEN and parts[2].lstrip('-').isdigit():
        return atomic_snapshot(hand, parts[1], int(parts[2]), fam, evidence_ref=ev_key,
                               evidence_tier=c.get('evidence_tier'), detector_reason=c.get('detector_reason'),
                               eff_stack_bb=ctx.get('eff_stack_bb'),
                               extra={'missing_assumptions': c.get('missing_assumptions', []),
                                      'proposed_alternative': c.get('proposed_alternative'),
                                      # detector-supplied canonical FACTS the analyst may cite (no calc).
                                      **(ctx.get('packet_facts') or {})})
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


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def semantic_audit(packet):
    """Owner Gate 1 + no-calc audit -> ATOMIC_DECISION_PACKET_SEMANTIC_AUDIT.json. Per decision: exact id,
    scalar Hero action, correct board length for street, action line terminates at Hero with no future
    action/street, no result/showdown/prior-verdict leakage, decision-time made-hand consistency, and -- for
    every RESOLVED decision -- EVERY applicable canonical operand present and self-consistent (so the analyst
    calculates nothing): canonical-resolved flag, pot-before, Hero stack-before, effective stack, explicit
    price status, active players, amount-to-call valid for calls AND raises-facing-aggression (the CALL
    COMPONENT, strictly below the raise's chosen incremental), chosen sizing for aggressive actions, decision
    risk bounded by stack, required equity when the price contract applies, SPR where applicable. A record
    that cannot supply an operand must be explicitly unresolved (fail-closed). Returns the release invariants
    incl. zero_analyst_calculations_required."""
    rows, failing, leaks, calc_required = [], 0, 0, 0
    req_ids = {d['decision_id'] for d in packet['required']}
    for d in (packet['required'] + packet['optional']):
        issues, calc_issues = [], []
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
        # ---- no-calc canonical-operand completeness (only resolved decisions) ----
        if not unresolved:
            facing = str(d.get('price_status') or '').startswith('facing')
            atc = d.get('amount_to_call_bb')
            if not d.get('canonical_resolved'):
                calc_issues.append('not canonically resolved')
            if not _num(d.get('pot_before_bb')):
                calc_issues.append('missing canonical pot_before')
            if not _num(d.get('hero_stack_before_bb')):
                calc_issues.append('missing canonical hero_stack_before')
            if not _num(d.get('eff_stack_bb')):
                calc_issues.append('missing canonical effective stack')
            if not d.get('price_status'):
                calc_issues.append('missing explicit price_status')
            if not isinstance(d.get('active_players'), int):
                calc_issues.append('missing active_players count')
            if d.get('hero_action') in ('call', 'calls') and not _num(atc):
                calc_issues.append('call decision without numeric amount_to_call')
            if facing and not _num(atc):
                calc_issues.append('facing decision without numeric call-component amount_to_call')
            if (facing and d.get('hero_action') == 'raise' and _num(atc)
                    and _num(d.get('chosen_incremental_bb')) and atc >= d['chosen_incremental_bb']):
                calc_issues.append('raise amount_to_call is not the call component (>= chosen_incremental)')
            if d.get('hero_action') in ('bet', 'raise', 'jam') and not _num(d.get('chosen_incremental_bb')):
                calc_issues.append('aggressive action without chosen_incremental')
            if (_num(d.get('decision_risk_bb')) and _num(d.get('hero_stack_before_bb'))
                    and d['decision_risk_bb'] > d['hero_stack_before_bb'] + 1e-6):
                calc_issues.append('decision risk exceeds decision-time stack')
            if d.get('price_applicable') and not _num(d.get('required_equity_pct')):
                calc_issues.append('price applicable but required_equity missing')
            if (st in ('flop', 'turn', 'river') and d.get('spr') is None
                    and _num(d.get('contestable_pot_bb')) and d.get('contestable_pot_bb')):
                calc_issues.append('postflop with contestable pot but no SPR')
        issues += calc_issues
        if calc_issues and d.get('decision_id') in req_ids:
            calc_required += 1
        if issues:
            failing += 1
            if any(('leak' in i) or ('future' in i) or ('later-street' in i) or ('runout' in i) for i in issues):
                leaks += 1
        rows.append({'decision_id': d.get('decision_id'), 'unresolved': unresolved,
                     'pass': not issues, 'canonical_complete': not calc_issues, 'issues': issues})
    req = len(packet['required'])
    return {'decisions': len(rows), 'required': req, 'failing': failing,
            'future_information_leaks': leaks, 'analyst_calculation_required_count': calc_required,
            'zero_silently_incomplete': failing == 0, 'zero_future_information_leaks': leaks == 0,
            'zero_analyst_calculations_required': calc_required == 0, 'rows': rows}


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


def artifact_cache_identity(rd, hands, runtime_id=None, input_hashes=None):
    """A cache identity derived from the ACTUAL deterministic cache CONTENTS bound to the input hashes and
    runtime/build identity (owner blocker #6). It hashes the STABLE analytical core of the cache -- every
    hand id, the full final-truth record set, the canonical required-review population, the reviewed-decision
    refs, and the material-loss population -- which is identical whether read from the in-memory full run or
    reloaded from the on-disk cache (so a fresh full->quick matches), yet changes when ANY input file, config/
    runtime build, hand, decision/final-truth fact, or queue-membership byte changes (so a stale packet/cache
    FAILS --quick). The volatile, post-emission-stamped keys (e.g. input_manifest) are deliberately excluded
    so a clean cache is not spuriously rejected."""
    import json
    hand_ids = sorted(str(h.get('id') or '') for h in (hands or []) if h.get('id'))
    rd = rd if isinstance(rd, dict) else {}
    mlp = rd.get('material_loss_population')
    ft = rd.get('final_truth') or {}
    # The analytical core uses the STABLE deterministic-analysis facts: the required-review population, the
    # per-hand reviewed-decision refs, the material-loss population, and the final-truth CLASS COUNTS. The
    # full final_truth RECORDS are deliberately excluded -- the analyst-merge during a quick re-render
    # rewrites them downstream of the seal, so including them would make --quick non-idempotent. The kept
    # keys still change on any input / hand / queue-membership / classification-population mutation.
    core = {
        'candidate_need_ids': sorted(rd.get('_candidate_need_ids') or []),
        'reviewed_decision_ref_by_hand': rd.get('reviewed_decision_ref_by_hand') or {},
        'material_loss_keys': (sorted(k for k in mlp.keys() if not str(k).startswith('_'))
                               if isinstance(mlp, dict) else []),
        'final_truth_counts': ft.get('counts') if isinstance(ft, dict) else None,
    }
    core_hash = hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, default=str)
                               .encode('utf-8')).hexdigest()
    payload = {'n_hands': len(hand_ids), 'hand_ids': hand_ids, 'analytical_core_hash': core_hash,
               'input_hashes': input_hashes or {}, 'runtime': runtime_id or {}}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return 'cache_' + hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]


def cache_identity_from_disk(rd_path, hands_path, runtime_id=None, input_hashes=None):
    """Compute the cache identity from the ON-DISK cache artifacts (the exact files --quick reloads), so the
    full-run seal and the --quick check read the SAME bytes and a fresh full->quick always matches (owner
    blocker #6). The full run computes it from disk too (not from its in-memory objects), eliminating any
    in-memory/on-disk drift."""
    import json
    try:
        with open(rd_path, encoding='utf-8') as f:
            rd = json.load(f)
    except Exception:
        rd = {}
    try:
        with open(hands_path, encoding='utf-8') as f:
            hands = json.load(f)
    except Exception:
        hands = []
    return artifact_cache_identity(rd, hands, runtime_id, input_hashes)


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
                 runtime_commit='', cache_identity='', optional_cap=8, build_identity=None):
    """Build the ONE sealed analyst packet. REQUIRED = the canonical legacy required-review population
    (preserved 100%) PLUS the accepted rule-backed findings (the KQs SB-flat). OPTIONAL = lower-confidence
    read-dependent candidates, capped. Each hand/decision appears once; nothing required is demoted. The
    packet_hash binds all contents + input/runtime/cache identity."""
    import gem_discovery_context as _dc
    try:
        import gem_stage_meter as _sm
        _sm.tick('packet')              # forbidden in --quick (Gate 2.2)
    except Exception:
        pass
    prior = (rd.get('final_truth') or {}).get('records', {}) if isinstance(rd, dict) else {}
    hands_by_id = {h.get('id'): h for h in (hands or []) if h.get('id')}
    val = _dc.run_value(hands, prior)
    confirmed_ids = {r['decision_id'] for r in val['confirmed']}

    def _force_required(c):
        # Accepted owner-rule finding (KQs SB flat) OR a confirmed finding OR a HIGH-CONFIDENCE
        # (gross) chart-backed sizing NOMINATION. The sizing nomination is force-reviewed once but is
        # NOT pre-confirmed -- its terminal verdict stays owned by the analyst's one-pass review.
        if c.get('family') == 'sb_flat_vs_late_open' or c.get('decision_id') in confirmed_ids:
            return True
        if c.get('family') == 'flop_cbet_sizing':
            sev = ((c.get('context') or {}).get('sizing_assessment') or {}).get('severity')
            return sev == 'gross'
        return False

    discovery = {c.get('decision_id'): _norm_decision(c, hands_by_id) for c in val['candidates']}
    rule_required = {c.get('decision_id'): _norm_decision(c, hands_by_id) for c in val['candidates']
                     if _force_required(c)}

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
        'build_identity': build_identity or {},
        'required_count': len(required), 'optional_count': len(optional), 'optional_cap': optional_cap,
        'evidence_keys': sorted(evidence.keys()), 'allowed_verdicts': list(ALLOWED_VERDICTS),
    }
    packet = {'manifest': manifest, 'evidence': evidence, 'required': required, 'optional': optional}
    manifest['packet_hash'] = _content_hash(packet)   # over contents that exclude packet_hash itself
    return packet


def recompute_packet_hash(packet):
    """Recompute the content hash EXACTLY as build_packet did -- over the contents with manifest.packet_hash
    excluded -- so a reloaded packet can be verified against its stored hash (owner Gate 2.2 quick binding).
    A serialize/reload round-trip is hash-stable because _content_hash itself canonicalizes via json.dumps."""
    import copy
    p = copy.deepcopy(packet)
    if isinstance(p.get('manifest'), dict):
        p['manifest'].pop('packet_hash', None)
    return _content_hash(p)


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
