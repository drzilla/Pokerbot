"""gem_discovery_pilot.py -- v8.20 mistake-discovery pilot (Track 3).

Three CANDIDATE families. Every output is a *candidate* with a decision node, observed facts and a
detector reason -- never a confirmed mistake. The analyst remains the promotion owner: nothing here
enters the canonical confirmed-mistake / punt populations (gem_final_truth) automatically.

Trust rules (non-negotiable):
  * no invented equity / EV / fold-equity. A numeric equity/EV operand is emitted ONLY when it already
    exists on the canonical decision_point (with its equity_source provenance); otherwise it is omitted
    and recorded as a MISSING ASSUMPTION.
  * every candidate carries `decision_id` = "<hand_id>:<street>:<action_index>".
  * reuse the existing parser / decision_points / board-state / sizing infrastructure -- no new evaluator.

Families:
  3.1 material_loss_commitment -- anchors the top material losses to the node where the chips were
      actually committed (the later commitment over an earlier preflop nomination) and routes them to
      required review. (Addresses the live decision-node-misattribution defect.)
  3.2 sizing_line -- wraps the existing gem_sizing_detector aggregate-leak signals as candidates.
  3.3 turn_river_active -- river/turn active-error candidates from observed action + board facts.
"""

_STREET_ORDER = {'preflop': 0, 'flop': 1, 'turn': 2, 'river': 3}
CANDIDATE = 'candidate'        # the only status a detector may assign; analyst owns promotion


# --------------------------------------------------------------------------- #
# shared helpers                                                               #
# --------------------------------------------------------------------------- #

def _num(v):
    return v if isinstance(v, (int, float)) else None


def _decision_id(hand_id, street, action_index):
    return '%s:%s:%s' % (hand_id, street or '?', action_index if action_index is not None else '?')


def _raw_risk(dp):
    """The raw canonical hero_risk_bb (cumulative; may double-count prior commitments / villain stack)."""
    return _num(dp.get('hero_risk_bb')) or _num(dp.get('hero_amount_bb')) or 0.0


def _decision_risk(dp):
    """B2: the decision-LEVEL chips Hero can lose because of THIS decision -- bounded by the decision-time
    effective stack. The raw hero_risk_bb is cumulative and on some nodes exceeds the effective stack
    (it is not a clean decision-level operand); a quantity labelled 'decision risk' must never exceed
    what Hero can actually put at risk from the node, so it is capped at eff_stack_bb when known."""
    raw = _raw_risk(dp)
    eff = _num(dp.get('eff_stack_bb'))
    if eff is not None and eff >= 0 and raw > eff:
        return eff
    return raw


def _risk_reconciled(dp):
    """True when the raw cumulative risk had to be capped to the effective stack (recorded for audit)."""
    raw = _raw_risk(dp)
    eff = _num(dp.get('eff_stack_bb'))
    return bool(eff is not None and raw > eff)


def _canonical_equity(dp):
    """Return (equity, source) ONLY if the canonical decision_point already carries it -- never invent.
    Otherwise (None, None)."""
    eq = _num(dp.get('hero_equity_vs_range'))
    src = dp.get('equity_source')
    if eq is not None and src:
        return eq, src
    return None, None


def commitment_node(hand):
    """3.1 core: the decision node where Hero actually committed the material chips -- the dp with the
    greatest hero_risk_bb, breaking ties toward the LATER street / action index (so a big flop/turn
    stack-off wins over the earlier preflop defend). Returns (dp, reason) or (None, reason)."""
    dps = hand.get('decision_points') or []
    if not dps:
        return None, 'no canonical decision points'
    # select on the BOUNDED decision risk (B2), ties to the later street / action index.
    best = max(dps, key=lambda d: (_decision_risk(d), _STREET_ORDER.get(d.get('street'), 0),
                                   d.get('action_index') or 0))
    first = min(dps, key=lambda d: (_STREET_ORDER.get(d.get('street'), 0), d.get('action_index') or 0))
    if best is first or _STREET_ORDER.get(best.get('street'), 0) == _STREET_ORDER.get(first.get('street'), 0):
        reason = 'single / earliest node carried the largest decision-level commitment'
    else:
        reason = ('commitment node moved later: %s (decision risk %.1fbb) over the earliest %s node'
                  % (best.get('street'), _decision_risk(best), first.get('street')))
    return best, reason


def _observed_facts(dp):
    """Operands pulled from the CANONICAL decision_point only (no fabrication)."""
    facts = {
        'street': dp.get('street'),
        'action_index': dp.get('action_index'),
        'hero_action': dp.get('hero_action') or dp.get('hero_action_class'),
        'pot_facing_hero_bb': _num(dp.get('pot_facing_hero_bb')),
        'villain_bet_bb': _num(dp.get('villain_bet_bb')),
        # B2: the audited operands -- the raw cumulative field AND the bounded decision-level risk.
        'raw_hero_risk_bb': _raw_risk(dp) or None,
        'decision_risk_bb': _decision_risk(dp) or None,
        'risk_capped_to_eff_stack': _risk_reconciled(dp) or None,
        'eff_stack_bb': _num(dp.get('eff_stack_bb')),
        'spr': _num(dp.get('spr')),
        'players_in_hand': dp.get('players_in_hand'),
        'board': dp.get('board'),
        'board_texture': dp.get('board_texture'),
    }
    eq, src = _canonical_equity(dp)
    if eq is not None:
        facts['hero_equity_vs_range'] = eq
        facts['equity_source'] = src
    return {k: v for k, v in facts.items() if v is not None}


def _missing_assumptions(dp, need_range=False):
    miss = []
    eq, _ = _canonical_equity(dp)
    if need_range and eq is None:
        miss.append('villain continuing range (no canonical equity_vs_range on this node)')
    return miss


# --------------------------------------------------------------------------- #
# 3.1 material-loss commitment candidates                                      #
# --------------------------------------------------------------------------- #

def material_loss_commitment_candidates(hands, *, top_n=12, min_loss_bb=10.0):
    """For the top material net-chip losses, emit a candidate anchored at the commitment node and route
    it to required review. This detector does NOT declare a mistake -- it selects WHERE the analyst
    should look. A loss with no reviewable decision becomes an explicit ungraded blocker."""
    losers = [h for h in hands
              if _num(h.get('net_bb')) is not None and h['net_bb'] <= -abs(min_loss_bb)]
    losers.sort(key=lambda h: h['net_bb'])
    out = []
    for h in losers[:top_n]:
        hid = h.get('id')
        dp, reason = commitment_node(h)
        if dp is None:
            out.append({
                'family': 'material_loss_commitment', 'hand_id': hid,
                'decision_id': _decision_id(hid, None, None),
                'status': CANDIDATE, 'confidence': 'insufficient context',
                'route': 'ungraded_blocker',
                'detector_reason': 'material loss (%.1fbb) with no reviewable decision node' % h['net_bb'],
                'observed_facts': {'net_bb': h['net_bb'], 'board': h.get('board')},
                'missing_assumptions': ['no canonical decision points to anchor review'],
                'node_select_reason': reason,
            })
            continue
        out.append({
            'family': 'material_loss_commitment', 'hand_id': hid,
            'decision_id': _decision_id(hid, dp.get('street'), dp.get('action_index')),
            'status': CANDIDATE, 'confidence': 'candidate', 'route': 'required_review',
            'detector_reason': ('material net loss %.1fbb; review the committing decision, not the '
                                'first voluntary action' % h['net_bb']),
            'observed_facts': dict(_observed_facts(dp), net_bb=h['net_bb'],
                                   went_to_sd=h.get('went_to_sd')),
            'missing_assumptions': _missing_assumptions(dp, need_range=True),
            'node_select_reason': reason,
        })
    return out


# --------------------------------------------------------------------------- #
# 3.2 sizing / line-pattern candidates                                         #
# --------------------------------------------------------------------------- #

def sizing_line_candidates(stats):
    """Wrap the existing gem_sizing_detector aggregate-leak signals as candidates. Reuses that module's
    safe-context matching (>=8 opportunities, >=3 judged, compliance floor); adds no new evaluator and
    no exact EV."""
    try:
        import gem_sizing_detector as _sd
        findings = (stats.get('texture_gto_findings') if isinstance(stats, dict) else None) or []
        res = _sd.build_sizing_leak_signals(findings)
        signals = res.get('signals', []) if isinstance(res, dict) else []
    except Exception:
        signals = []
    out = []
    for sig in signals:
        # B4: a sizing signal is an AGGREGATE across many opportunities, NOT a hand-level decision node.
        # It carries example hand-ids/nodes for review but must never be counted as a per-hand node.
        examples = (sig.get('example_hand_ids') or sig.get('hand_ids')
                    or sig.get('contributing_hand_ids') or [])
        out.append({
            'family': 'sizing_line', 'is_aggregate': True,
            'hand_id': '',                                   # aggregate: no single hand
            'decision_id': 'aggregate:sizing:%s:%s' % (sig.get('archetype', '?'), sig.get('side', '?')),
            'relationship': 'AGGREGATE_SIGNAL',
            'status': CANDIDATE, 'confidence': sig.get('confidence', 'tracking'),
            'route': 'aggregate_review',
            'detector_reason': (sig.get('reason') or sig.get('trigger')
                                or 'aggregate sizing compliance below the matched texture/position/depth prescription'),
            'observed_facts': {k: sig.get(k) for k in ('archetype', 'side', 'opportunities',
                               'judged', 'sizing_compliance', 'depth_band') if k in sig},
            'example_hand_ids': list(examples),
            'missing_assumptions': ([] if examples else
                                    ['concrete example hand ids / nodes for the aggregate signal']),
            'signal_type': sig.get('signal_type', 'aggregate_leak'),
        })
    return out


# --------------------------------------------------------------------------- #
# 3.3 turn / river active-error candidates                                     #
# --------------------------------------------------------------------------- #

def _has_strength_input(dp):
    """B3: true only when a CANONICAL street-time hand-strength / equity input exists on the node.
    went_to_sd is an OUTCOME flag and is deliberately NOT consulted here."""
    return any((dp.get(k) not in (None, '')) for k in
               ('draw_profile', 'minimum_continue_hand', 'hero_equity_vs_range'))


def turn_river_active_candidates(hands):
    """River/turn active-error candidates from CANONICAL street-time inputs only -- never from the
    outcome flag went_to_sd (B3). A label that needs hand strength (bluff vs value) is emitted only when
    a canonical strength/equity input exists; otherwise the node is surfaced as INSUFFICIENT_INPUT rather
    than a confident semantic claim. A river call facing material aggression is supportable from the
    OBSERVED action alone (Hero called a large bet) and does not need a showdown flag."""
    out = []
    for h in hands:
        hid = h.get('id')
        for dp in (h.get('decision_points') or []):
            st = dp.get('street')
            if st not in ('turn', 'river'):
                continue
            act = (dp.get('hero_action') or dp.get('hero_action_class') or '').lower()
            vbet = _num(dp.get('villain_bet_bb')) or 0.0
            pot = _num(dp.get('pot_facing_hero_bb')) or 0.0
            has_strength = _has_strength_input(dp)
            label, conf, subfamily = None, 'candidate', None
            # (a) river call facing material aggression -- OBSERVED action, no strength/showdown needed.
            if st == 'river' and 'call' in act and pot > 0 and vbet >= 0.66 * pot \
                    and _num(h.get('net_bb')) is not None and h['net_bb'] < 0:
                label = ('river call facing material aggression (villain %.1fbb into ~%.1fbb)'
                         % (vbet, pot))
                subfamily = 'river_call_vs_aggression'
            # (b) a river BET -- bluff vs thin-value classification REQUIRES canonical hand strength.
            elif st in ('turn', 'river') and ('bet' in act or 'jam' in act):
                subfamily = 'river_bet_classification'
                if has_strength:
                    label = '%s bet -- review value vs bluff (canonical strength input present)' % st
                else:
                    # do NOT infer SDV / bluff from went_to_sd -- the strength input is absent.
                    label = '%s bet -- hand-strength/range input absent, cannot classify value vs bluff' % st
                    conf = 'insufficient_input'
            if not label:
                continue
            out.append({
                'family': 'turn_river_active', 'subfamily': subfamily, 'hand_id': hid,
                'decision_id': _decision_id(hid, st, dp.get('action_index')),
                'status': CANDIDATE, 'confidence': conf,
                'route': 'optional_review' if conf == 'candidate' else 'needs_input',
                'detector_reason': label,
                'observed_facts': dict(_observed_facts(dp), net_bb=_num(h.get('net_bb'))),
                'missing_assumptions': _missing_assumptions(dp, need_range=not has_strength),
            })
    return out


# --------------------------------------------------------------------------- #
# 3.4 yield metrics + analyst-ready queue                                      #
# --------------------------------------------------------------------------- #

_PENDING = 'pending'   # only used when no review has been run

# B1 candidate-vs-prior-truth relationships.
NEW_UNREVIEWED = 'NEW_UNREVIEWED'
RE_REVIEW_CHANGED_NODE = 'RE_REVIEW_CHANGED_NODE'
ALREADY_REVIEWED_SAME_NODE = 'ALREADY_REVIEWED_SAME_NODE'
AGGREGATE_SIGNAL = 'AGGREGATE_SIGNAL'
# B6 terminal review outcomes.
CONFIRMED_MISTAKE = 'CONFIRMED_MISTAKE'
CLEARED = 'CLEARED'
READ_DEPENDENT = 'READ_DEPENDENT'
INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'
DETECTOR_OR_OPERAND_BUG = 'DETECTOR_OR_OPERAND_BUG'


def _is_hand_level(c):
    """A hand-level candidate with a concrete decision node (aggregate signals + node-less blockers are
    NOT hand-level decision nodes -- B4)."""
    if c.get('is_aggregate'):
        return False
    did = c.get('decision_id') or ''
    return bool(did) and not did.endswith(':?:?') and not did.startswith('aggregate:')


def reconcile_with_prior_truth(candidates, prior_records):
    """B1: stamp each candidate with the prior canonical final class/verdict/node and its relationship to
    prior analyst truth, so re-flagging an already-adjudicated hand is not miscounted as discovery."""
    prior_records = prior_records or {}
    out = []
    for c in candidates:
        c = dict(c)
        if c.get('is_aggregate'):
            c['relationship'] = AGGREGATE_SIGNAL
            c.setdefault('prior_final_class', None)
            out.append(c)
            continue
        rec = prior_records.get(c.get('hand_id'))
        if not rec:
            c.update({'relationship': NEW_UNREVIEWED, 'prior_final_class': None,
                      'prior_verdict': None, 'prior_decision_id': None})
        else:
            prior_node = rec.get('decision_id') or ''
            new_node = c.get('decision_id') or ''
            c['prior_final_class'] = rec.get('final_class')
            c['prior_verdict'] = rec.get('verdict')
            c['prior_decision_id'] = prior_node or None
            if prior_node and prior_node != new_node:
                c['relationship'] = RE_REVIEW_CHANGED_NODE
                c['node_diff'] = {'prior': prior_node, 'new': new_node}
            else:
                c['relationship'] = ALREADY_REVIEWED_SAME_NODE
        out.append(c)
    return out


def _prior_outcome(prior_class):
    return {'CONFIRMED_MISTAKE': CONFIRMED_MISTAKE, 'PUNT': CONFIRMED_MISTAKE,
            'COOLER': CLEARED, 'JUSTIFIED': CLEARED, 'STANDARD': CLEARED,
            'READ_DEPENDENT': READ_DEPENDENT, 'INSUFFICIENT': INSUFFICIENT_EVIDENCE}.get(
        prior_class, CLEARED)


def review_candidates(reconciled):
    """B6: the bounded analyst review. ONE terminal outcome per candidate. Fail-closed: a candidate
    lacking the canonical inputs to confirm is READ_DEPENDENT / INSUFFICIENT_EVIDENCE, never a confirmed
    mistake. Already-adjudicated hands carry their prior terminal outcome and are NOT incremental."""
    reviewed = []
    for c in reconciled:
        rel = c.get('relationship')
        incremental = rel in (NEW_UNREVIEWED, RE_REVIEW_CHANGED_NODE)
        if rel == ALREADY_REVIEWED_SAME_NODE:
            outcome = _prior_outcome(c.get('prior_final_class'))
            note = ('already adjudicated %s at the same / whole-hand node -- not incremental discovery'
                    % c.get('prior_final_class'))
        elif rel == AGGREGATE_SIGNAL:
            outcome = INSUFFICIENT_EVIDENCE
            note = 'aggregate signal -- needs concrete example nodes before a per-hand review'
        elif c.get('confidence') == 'insufficient_input':
            outcome = INSUFFICIENT_EVIDENCE
            note = 'detector flagged missing canonical strength/range input -- cannot classify'
        else:
            # a genuinely new / re-review hand candidate. Without a canonical villain range or decision
            # EV, a material loss / river-call candidate cannot be CONFIRMED a mistake here -- the read
            # is required. This fails closed (no fabricated confirmation).
            miss = c.get('missing_assumptions') or []
            outcome = READ_DEPENDENT
            note = ('review requires analyst read: %s' % '; '.join(miss)) if miss \
                else 'no canonical range/EV to confirm a mistake; analyst read required'
        reviewed.append({
            'decision_id': c.get('decision_id'), 'hand_id': c.get('hand_id'),
            'family': c.get('family'), 'subfamily': c.get('subfamily'),
            'relationship': rel, 'incremental': incremental,
            'prior_final_class': c.get('prior_final_class'),
            'detector_reason': c.get('detector_reason'),
            'terminal_outcome': outcome, 'review_note': note,
        })
    return reviewed


def _family_metrics(name, reconciled, reviewed, eligible):
    cands = [c for c in reconciled if c['family'] == name]
    rev = [r for r in reviewed if r['family'] == name]
    rel = {k: sum(1 for c in cands if c.get('relationship') == k)
           for k in (NEW_UNREVIEWED, RE_REVIEW_CHANGED_NODE, ALREADY_REVIEWED_SAME_NODE, AGGREGATE_SIGNAL)}
    incr = [r for r in rev if r['incremental']]
    confirmed = sum(1 for r in incr if r['terminal_outcome'] == CONFIRMED_MISTAKE)
    cleared = sum(1 for r in incr if r['terminal_outcome'] == CLEARED)
    readdep = sum(1 for r in incr if r['terminal_outcome'] == READ_DEPENDENT)
    insf = sum(1 for r in incr if r['terminal_outcome'] == INSUFFICIENT_EVIDENCE)
    bb = [abs(c['observed_facts'].get('net_bb')) for c in cands
          if isinstance(c.get('observed_facts'), dict)
          and isinstance(c['observed_facts'].get('net_bb'), (int, float))]
    fps = sorted({(c.get('subfamily') or c.get('family')) for c in cands
                  if any(r['hand_id'] == c['hand_id'] and r['incremental']
                         and r['terminal_outcome'] in (CLEARED, INSUFFICIENT_EVIDENCE) for r in rev)})
    return {
        'family': name,
        'eligible_opportunities': eligible,
        'candidates_generated': len(cands),
        'relationship_breakdown': rel,
        'new_unreviewed': rel[NEW_UNREVIEWED] + rel[RE_REVIEW_CHANGED_NODE],
        'suppressed_already_reviewed_same_node': rel[ALREADY_REVIEWED_SAME_NODE],
        'aggregate_signals': rel[AGGREGATE_SIGNAL],
        'incremental_reviewed': len(incr),
        'confirmed_mistakes': confirmed,
        'cleared_candidates': cleared,
        'read_dependent': readdep,
        'insufficient_evidence': insf,
        'precision_among_reviewed': (round(confirmed / len(incr), 3) if incr else None),
        # honestly named: realized whole-hand net exposed by the candidates -- NOT mistake impact / EV.
        'gross_abs_hand_net_bb_exposed': round(sum(bb), 1) if bb else None,
        'confirmed_mistake_ev_bb': None,   # only when canonical decision EV exists (none here)
        'top_false_positive_signatures': fps or None,
    }


def run_discovery_pilot(hands, stats, *, prior_records=None, n_hands=None, do_review=True):
    """Run all three families, reconcile vs prior analyst truth, optionally run the bounded review, and
    return {candidates, reconciled, reviewed, metrics, analyst_queue}. Nothing is auto-promoted."""
    hands = hands or []
    n = n_hands if n_hands is not None else len(hands)
    candidates = (material_loss_commitment_candidates(hands)
                  + sizing_line_candidates(stats or {})
                  + turn_river_active_candidates(hands))
    reconciled = reconcile_with_prior_truth(candidates, prior_records or {})
    reviewed = review_candidates(reconciled) if do_review else []

    eligible_ml = sum(1 for h in hands
                      if isinstance(h.get('net_bb'), (int, float)) and h['net_bb'] <= -10.0)
    eligible_tr = sum(1 for h in hands for dp in (h.get('decision_points') or [])
                      if dp.get('street') in ('turn', 'river'))
    fams = [_family_metrics('material_loss_commitment', reconciled, reviewed, eligible_ml),
            _family_metrics('sizing_line', reconciled, reviewed,
                            len([c for c in reconciled if c['family'] == 'sizing_line'])),
            _family_metrics('turn_river_active', reconciled, reviewed, eligible_tr)]
    incr_reviewed = sum(f['incremental_reviewed'] for f in fams)
    incr_confirmed = sum(f['confirmed_mistakes'] for f in fams)
    metrics = {
        'pilot': 'MISTAKE_DISCOVERY_PILOT', 'n_hands': n,
        'all_candidates_status': CANDIDATE,
        'auto_promoted_to_confirmed': 0,
        'review_performed': bool(do_review),
        'families': fams,
        'totals': {
            'total_opportunities': eligible_ml + eligible_tr,
            'raw_candidates': len(candidates),
            'aggregate_signals': sum(1 for c in reconciled if c.get('is_aggregate')),
            'with_decision_node': sum(1 for c in reconciled if _is_hand_level(c)),
            'suppressed_already_reviewed_same_node': sum(
                1 for c in reconciled if c.get('relationship') == ALREADY_REVIEWED_SAME_NODE),
            'new_unreviewed_or_changed_node': sum(
                1 for c in reconciled if c.get('relationship') in (NEW_UNREVIEWED, RE_REVIEW_CHANGED_NODE)),
            'incremental_reviewed': incr_reviewed,
            'incremental_confirmed_mistakes': incr_confirmed,
            'incremental_confirmed_per_100_hands': round(100.0 * incr_confirmed / max(n, 1), 3),
            'precision_among_incremental_reviewed': (round(incr_confirmed / incr_reviewed, 3)
                                                     if incr_reviewed else None),
            'unsupported_exact_math': _count_unsupported_math(candidates),
        },
    }
    return {'candidates': candidates, 'reconciled': reconciled, 'reviewed': reviewed,
            'metrics': metrics, 'analyst_queue': analyst_queue(reconciled)}


def analyst_queue(reconciled):
    """An analyst-ready queue. Suppresses ALREADY_REVIEWED_SAME_NODE; reports new vs re-review vs
    aggregate separately. Decision node + observed facts + missing assumptions; no unsupported math."""
    out = {'new_unreviewed': [], 're_review_changed_node': [], 'aggregate_signals': []}
    for c in reconciled:
        rel = c.get('relationship')
        if rel == ALREADY_REVIEWED_SAME_NODE:
            continue   # already adjudicated at this node -- not a review item
        item = {
            'decision_id': c.get('decision_id'), 'hand_id': c.get('hand_id'),
            'family': c.get('family'), 'subfamily': c.get('subfamily'),
            'confidence': c.get('confidence'), 'route': c.get('route'),
            'prior_final_class': c.get('prior_final_class'),
            'observed_facts': c.get('observed_facts', {}),
            'detector_reason': c.get('detector_reason'),
            'missing_assumptions': c.get('missing_assumptions', []),
            'promotion': 'analyst-owned (candidate only)',
        }
        if rel == AGGREGATE_SIGNAL:
            item['example_hand_ids'] = c.get('example_hand_ids', [])
            out['aggregate_signals'].append(item)
        elif rel == RE_REVIEW_CHANGED_NODE:
            item['node_diff'] = c.get('node_diff')
            out['re_review_changed_node'].append(item)
        else:
            out['new_unreviewed'].append(item)
    return out


def _count_unsupported_math(candidates):
    """An invariant guard: a candidate must not carry an INVENTED equity / EV / fold-equity number.
    Observed canonical statistics (realized net bb, pot/bet bb, sizing-compliance %) are allowed -- only
    a fabricated equity/EV/fold-equity claim is not. Counts violations (acceptance requires 0)."""
    import re
    # a number tied to an equity / EV / fold-equity claim -- e.g. "~28% equity", "62% folds", "-5.7bb EV".
    pat = re.compile(
        r'(?:equity|fold[- ]?equity|fold\s*equity|\bev\b|expected value)[^\n]{0,16}[-+]?\d'
        r'|[-+]?\d+(?:\.\d+)?\s*%\s*(?:equity|fold|fe)\b'
        r'|[-+]?\d+(?:\.\d+)?\s*bb\s*(?:ev|equity|vs\b)')
    bad = 0
    for c in candidates:
        facts = c.get('observed_facts', {}) or {}
        if ('hero_equity_vs_range' in facts) and not facts.get('equity_source'):
            bad += 1   # an equity number without its canonical provenance
        if pat.search(str(c.get('detector_reason', '')).lower()):
            bad += 1
    return bad
