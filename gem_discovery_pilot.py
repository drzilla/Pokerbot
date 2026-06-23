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


def _risk(dp):
    """Chips Hero put at risk at a decision node (canonical field; 0 when absent)."""
    return _num(dp.get('hero_risk_bb')) or _num(dp.get('hero_amount_bb')) or 0.0


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
    best = max(dps, key=lambda d: (_risk(d), _STREET_ORDER.get(d.get('street'), 0),
                                   d.get('action_index') or 0))
    first = min(dps, key=lambda d: (_STREET_ORDER.get(d.get('street'), 0), d.get('action_index') or 0))
    if best is first or _STREET_ORDER.get(best.get('street'), 0) == _STREET_ORDER.get(first.get('street'), 0):
        reason = 'single / earliest node carried the largest commitment'
    else:
        reason = ('commitment node moved later: %s (risk %.1fbb) over the earliest %s node'
                  % (best.get('street'), _risk(best), first.get('street')))
    return best, reason


def _observed_facts(dp):
    """Operands pulled from the CANONICAL decision_point only (no fabrication)."""
    facts = {
        'street': dp.get('street'),
        'action_index': dp.get('action_index'),
        'hero_action': dp.get('hero_action') or dp.get('hero_action_class'),
        'pot_facing_hero_bb': _num(dp.get('pot_facing_hero_bb')),
        'villain_bet_bb': _num(dp.get('villain_bet_bb')),
        'hero_risk_bb': _risk(dp) or None,
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
        out.append({
            'family': 'sizing_line', 'hand_id': sig.get('hand_id', ''),
            'decision_id': sig.get('decision_id') or ('sizing:%s' % sig.get('trigger', '?')),
            'status': CANDIDATE, 'confidence': sig.get('confidence', 'tracking'),
            'route': 'optional_review',
            'detector_reason': sig.get('reason') or sig.get('trigger') or 'sizing pattern outside matched prescription',
            'observed_facts': {k: sig.get(k) for k in ('archetype', 'side', 'opportunities',
                               'judged', 'sizing_compliance', 'depth_band') if k in sig},
            'missing_assumptions': [],
            'signal_type': sig.get('signal_type', 'aggregate_leak'),
        })
    return out


# --------------------------------------------------------------------------- #
# 3.3 turn / river active-error candidates                                     #
# --------------------------------------------------------------------------- #

def turn_river_active_candidates(hands):
    """River/turn active-error candidates from OBSERVED action + board facts only. Every candidate that
    needs a villain range we don't canonically have records the missing assumption rather than asserting
    a verdict. Patterns: weak river call facing material aggression; third-barrel with no showdown value;
    river bet with showdown value (possible thin spot)."""
    out = []
    for h in hands:
        hid = h.get('id')
        dps = h.get('decision_points') or []
        for dp in dps:
            st = dp.get('street')
            if st not in ('turn', 'river'):
                continue
            act = (dp.get('hero_action') or dp.get('hero_action_class') or '').lower()
            vbet = _num(dp.get('villain_bet_bb')) or 0.0
            pot = _num(dp.get('pot_facing_hero_bb')) or 0.0
            last_agg = dp.get('hero_is_last_aggressor')
            sd = h.get('went_to_sd')
            cand = None
            # (a) weak river call facing material aggression (>= ~0.66 pot) that lost.
            if st == 'river' and 'call' in act and vbet >= 0.66 * pot and pot > 0 \
                    and _num(h.get('net_bb')) is not None and h['net_bb'] < 0:
                cand = ('weak river call facing material aggression (villain %.1fbb into ~%.1fbb)'
                        % (vbet, pot))
            # (b) third-barrel / river bet with no showdown value (pure bluff line).
            elif st == 'river' and ('bet' in act or 'jam' in act) and last_agg and sd is False:
                cand = 'river barrel as last aggressor with no showdown reached (bluff-shaped line)'
            # (c) river bet WITH showdown value reached -- possible thin value / missed check spot.
            elif st == 'river' and ('bet' in act or 'jam' in act) and sd is True:
                cand = 'river bet that reached showdown -- review thin value vs check'
            if not cand:
                continue
            out.append({
                'family': 'turn_river_active', 'hand_id': hid,
                'decision_id': _decision_id(hid, st, dp.get('action_index')),
                'status': CANDIDATE, 'confidence': 'candidate',
                'route': 'optional_review',
                'detector_reason': cand,
                'observed_facts': dict(_observed_facts(dp), net_bb=_num(h.get('net_bb')),
                                       went_to_sd=sd),
                'missing_assumptions': _missing_assumptions(dp, need_range=True),
            })
    return out


# --------------------------------------------------------------------------- #
# 3.4 yield metrics + analyst-ready queue                                      #
# --------------------------------------------------------------------------- #

_PENDING = 'pending'   # review-dependent fields are 'pending' BEFORE analyst review, never 0


def _family_metrics(name, candidates, eligible, suppressed):
    cands = [c for c in candidates if c['family'] == name]
    bb = [abs(c['observed_facts'].get('net_bb')) for c in cands
          if isinstance(c.get('observed_facts'), dict) and isinstance(c['observed_facts'].get('net_bb'), (int, float))]
    return {
        'family': name,
        'eligible_opportunities': eligible,
        'candidates_generated': len(cands),
        'candidates_suppressed_by_guardrails': suppressed,
        'candidates_reviewed': _PENDING,
        'confirmed_mistakes': _PENDING,
        'cleared_candidates': _PENDING,
        'unresolved': _PENDING,
        'precision_among_reviewed': _PENDING,
        'incremental_confirmed_per_100_hands': _PENDING,
        'canonical_material_bb_impact': round(sum(bb), 1) if bb else None,
        'analyst_minutes_per_confirmed': _PENDING,
        'top_false_positive_signatures': _PENDING,
    }


def run_discovery_pilot(hands, stats, *, n_hands=None):
    """Run all three families, returning {candidates, metrics, analyst_queue}. Pure; no side effects.
    Nothing is promoted to a confirmed mistake."""
    hands = hands or []
    n = n_hands if n_hands is not None else len(hands)
    ml = material_loss_commitment_candidates(hands)
    sz = sizing_line_candidates(stats or {})
    tr = turn_river_active_candidates(hands)
    candidates = ml + sz + tr

    eligible_ml = sum(1 for h in hands
                      if isinstance(h.get('net_bb'), (int, float)) and h['net_bb'] <= -10.0)
    eligible_tr = sum(1 for h in hands
                      for dp in (h.get('decision_points') or [])
                      if dp.get('street') in ('turn', 'river'))
    metrics = {
        'pilot': 'MISTAKE_DISCOVERY_PILOT',
        'n_hands': n,
        'all_candidates_status': CANDIDATE,
        'auto_promoted_to_confirmed': 0,        # invariant: detectors never auto-confirm
        'families': [
            _family_metrics('material_loss_commitment', candidates, eligible_ml, 0),
            _family_metrics('sizing_line', candidates, len(sz), 0),
            _family_metrics('turn_river_active', candidates, eligible_tr,
                            max(0, eligible_tr - len([c for c in tr]))),
        ],
        'totals': {
            'candidates_generated': len(candidates),
            'with_decision_node': sum(1 for c in candidates if c.get('decision_id')
                                      and not c['decision_id'].endswith(':?:?')),
            'unsupported_exact_math': _count_unsupported_math(candidates),
        },
    }
    queue = analyst_queue(candidates)
    return {'candidates': candidates, 'metrics': metrics, 'analyst_queue': queue}


def analyst_queue(candidates):
    """An analyst-ready queue: decision node, observed facts, detector reason, missing assumptions,
    confidence -- and NO unsupported exact math."""
    q = []
    for c in candidates:
        q.append({
            'decision_id': c.get('decision_id'),
            'hand_id': c.get('hand_id'),
            'family': c.get('family'),
            'confidence': c.get('confidence'),
            'route': c.get('route'),
            'observed_facts': c.get('observed_facts', {}),
            'detector_reason': c.get('detector_reason'),
            'missing_assumptions': c.get('missing_assumptions', []),
            'promotion': 'analyst-owned (candidate only)',
        })
    return q


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
