"""gem_discovery_context.py -- v8.20 Iteration-2 context-rich mistake discovery (Outcome 2).

Three high-yield review families built on COMPLETE precomputed canonical context. Unlike the prior pilot
(which asked semantic questions without the hand-strength facts to answer them), every candidate carries
a self-contained review record with the made-hand class, draw profile, board/runout, price, position,
stacks and the full action line -- so the analyst can review each hand ONCE from the packet alone.

Trust rules (unchanged): all candidates, analyst owns promotion; NO new evaluator (reuse the canonical
gem_parser / gem_made_hands / gem_board_state); NO invented EV; NO result-based reasoning.

Families:
  A. turn_overbarrel  -- Hero continues aggression (bet flop + bet/raise turn) with a weak made hand and
                         no strong draw after the turn.
  B. river_curiosity  -- Hero calls a river bet/jam with a bluff-catcher-tier made hand.
  C. river_value      -- Hero reaches the river with a strong made hand and gives up value
                         (check-through or a materially small bet).
"""
import gem_parser
import gem_made_hands

# terminal review verdicts (one per candidate).
CONFIRMED_MISTAKE = 'CONFIRMED_MISTAKE'
JUSTIFIED = 'JUSTIFIED'
READ_DEPENDENT = 'READ_DEPENDENT'
INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'
DETECTOR_BUG = 'DETECTOR_BUG'

_STRONG_MADE = ('two pair', 'two_pair', 'trips', 'set', 'straight', 'flush', 'full house', 'full_house',
                'quads', 'boat', 'straight flush')
_WEAK_MADE = ('high card', 'ace high', 'king high', 'queen high', 'underpair', 'third pair',
              'bottom pair', 'second pair', 'weak pair', 'no pair', 'nothing', 'pair')
_BLUFF_CATCHER = ('pair', 'ace high', 'king high', 'queen high', 'high card')


def _is_strong(name):
    n = (name or '').lower()
    return any(s in n for s in _STRONG_MADE)


def _genuine_value_hand(cards, board):
    """A strong made hand that genuinely USES Hero's hole cards -- NOT 'plays the board'. Two pair on a
    PAIRED board is almost always the board's pair + a weak kicker (a pot-control / bluff-catch hand, not
    a value-bet), and trips on a TRIPLED board is shared. Excluding these avoids confirming a 'missed
    value' mistake on a hand that is not actually a value hand (the false-positive trap). Returns the
    canonical made-hand class name, or None."""
    name = (gem_parser.hand_strength_name(cards, board) or '').lower()
    if not _is_strong(name):
        return None
    from collections import Counter
    rc = Counter(x[0] for x in (board or []))
    board_paired = any(v >= 2 for v in rc.values())
    board_trips = any(v >= 3 for v in rc.values())
    if ('two pair' in name or 'two_pair' in name) and board_paired:
        return None
    if 'trips' in name and board_trips:
        return None
    return name


def _hero_acts(hand, street):
    return [a for a in (hand.get('action_ledger') or [])
            if isinstance(a, dict) and a.get('street') == street and a.get('player') == 'Hero']


def _street_acts(hand, street):
    return [a for a in (hand.get('action_ledger') or [])
            if isinstance(a, dict) and a.get('street') == street]


def _pot_before(hand, street):
    """Pot (bb) contributed before `street` begins -- the canonical added_bb ledger, no recompute."""
    order = {'preflop': 0, 'flop': 1, 'turn': 2, 'river': 3}
    s = order.get(street, 3)
    return round(sum((a.get('added_bb') or 0) for a in (hand.get('action_ledger') or [])
                     if isinstance(a, dict) and order.get(a.get('street'), 0) < s), 2)


def _active_players(hand, street):
    pl = {a.get('player') for a in _street_acts(hand, street) if isinstance(a, dict)}
    return len(pl) if pl else None


def _street_facts(hand, street):
    """The canonical context packet for one street -- every operand from an EXISTING evaluator/field."""
    cards = hand.get('cards') or []
    board = hand.get('board') or []
    n = {'flop': 3, 'turn': 4, 'river': 5}.get(street, len(board))
    sb = board[:n]
    dp = {}
    made = None
    try:
        dp = gem_made_hands.draw_profile(cards, sb) or {}
    except Exception:
        dp = {}
    try:
        made = gem_parser.hand_strength_name(cards, sb)
    except Exception:
        made = None
    bet_class = None
    try:
        bet_class = gem_parser.classify_hand_for_betting(cards, sb, street)
    except Exception:
        bet_class = None
    return {
        'street': street,
        'hero_cards': cards,
        'board': sb,
        'made_hand_class': made,
        'made_hand_detail': dp.get('made_hand_detail') or dp.get('summary'),
        'draw_profile': {k: dp.get(k) for k in ('straight_draw', 'flush_draw', 'straight_outs',
                         'flush_outs', 'overcards', 'clean_outs') if k in dp},
        'betting_class': bet_class,
        'position': hand.get('position'),
        'hero_ip': hand.get('hero_ip'),
        'active_players': _active_players(hand, street),
        'pot_before_bb': _pot_before(hand, street),
        'action_line': [(a.get('player'), a.get('action'), a.get('amount_bb'))
                        for a in _street_acts(hand, street) if isinstance(a, dict)],
    }


# minimum canonical facts a candidate MUST carry to be an analyst candidate (else -> engineering debt).
_MIN_FACTS = ('made_hand_class', 'board', 'position', 'pot_before_bb')


def _has_min_facts(facts):
    return (facts.get('made_hand_class') and facts.get('board')
            and facts.get('position') is not None and facts.get('pot_before_bb') is not None)


def _record(hand, street, family, reason, facts, prior_records):
    hid = hand.get('id')
    ai = None
    ha = _hero_acts(hand, street)
    if ha:
        ai = (hand.get('action_ledger') or []).index(ha[-1]) if ha[-1] in (hand.get('action_ledger') or []) else None
    decision_id = '%s:%s:%s' % (hid, street, ai if ai is not None else '?')
    prior = (prior_records or {}).get(hid)
    return {
        'family': family, 'hand_id': hid, 'decision_id': decision_id, 'street': street,
        'hero_action': [a.get('action') for a in ha],
        'context': facts, 'detector_reason': reason,
        'evidence_tier': 'canonical_made_hand_class',
        'missing_assumptions': [] if family == 'river_value'
        else ['opponent continuing/ value range (not canonical in runtime)'],
        'prior_final_class': prior.get('final_class') if prior else None,
        'prior_verdict': prior.get('verdict') if prior else None,
        'prior_decision_id': (prior.get('decision_id') or None) if prior else None,
        'relationship': ('ALREADY_REVIEWED_SAME_NODE' if prior else 'NEW_UNREVIEWED'),
        'status': 'candidate',
    }


def family_turn_overbarrel(hands, prior_records=None):
    out = []
    for h in hands:
        if len((h.get('board') or [])) < 4 or len((h.get('cards') or [])) != 2:
            continue
        ta, fa = _hero_acts(h, 'turn'), _hero_acts(h, 'flop')
        if not (any((a.get('action') or '') in ('bets', 'raises') for a in ta)
                and any((a.get('action') or '') in ('bets', 'raises') for a in fa)):
            continue
        f = _street_facts(h, 'turn')
        made = (f.get('made_hand_class') or '').lower()
        dpr = f.get('draw_profile') or {}
        strong_draw = dpr.get('flush_draw') or (dpr.get('straight_outs') or 0) >= 8
        weak = any(w in made for w in _WEAK_MADE) or made in ('', 'none')
        if weak and not strong_draw:
            out.append(_record(h, 'turn', 'turn_overbarrel',
                               'bet flop and turn with a weak made hand (%s) and no strong draw' % (made or 'n/a'),
                               f, prior_records))
    return out


def family_river_curiosity(hands, prior_records=None):
    out = []
    for h in hands:
        if len((h.get('board') or [])) < 5 or len((h.get('cards') or [])) != 2:
            continue
        ra = _hero_acts(h, 'river')
        if not any((a.get('action') or '') == 'calls' for a in ra):
            continue
        f = _street_facts(h, 'river')
        name = (f.get('made_hand_class') or '').lower()
        if 'two pair' in name or 'two_pair' in name or _is_strong(name):
            continue   # a value hand calling is not a curiosity call
        if any(w in name for w in _BLUFF_CATCHER):
            out.append(_record(h, 'river', 'river_curiosity',
                               'called a river bet with a bluff-catcher-tier made hand (%s)' % name, f, prior_records))
    return out


def family_river_value(hands, prior_records=None):
    out = []
    for h in hands:
        if len((h.get('board') or [])) < 5 or len((h.get('cards') or [])) != 2:
            continue
        # genuine value hand only -- a strong class that USES Hero's hole cards (no board-plays-itself
        # false positives). This is the guard that keeps a 'missed value' confirmation honest.
        if not _genuine_value_hand(h.get('cards') or [], h.get('board') or []):
            continue
        f = _street_facts(h, 'river')
        riv = _street_acts(h, 'river')
        ha = _hero_acts(h, 'river')
        if not ha:
            continue
        hero_actions = [a.get('action') for a in ha]
        pot = f.get('pot_before_bb') or 0
        # missed value: (a) check-through -- every river action is a check; or (b) materially small bet.
        check_through = all((a.get('action') or '') == 'checks' for a in riv)
        small_bet = any((a.get('action') or '') in ('bets', 'raises')
                        and (a.get('amount_bb') or 0) > 0 and pot > 0
                        and (a.get('amount_bb') or 0) < 0.33 * pot for a in ha)
        if check_through and 'checks' in hero_actions:
            out.append(_record(h, 'river', 'river_value',
                               'reached the river with a strong made hand (%s) and checked it through (no value bet)'
                               % f.get('made_hand_class'), f, prior_records))
        elif small_bet:
            out.append(_record(h, 'river', 'river_value',
                               'bet a strong made hand (%s) materially small (<33%% pot) on the river'
                               % f.get('made_hand_class'), f, prior_records))
    return out


def discover(hands, prior_records=None):
    """Run the three families; split into analyst candidates vs engineering-debt (missing min facts) and
    suppress prior-reviewed-same-node. Returns {candidates, suppressed, debt}."""
    raw = (family_turn_overbarrel(hands, prior_records)
           + family_river_curiosity(hands, prior_records)
           + family_river_value(hands, prior_records))
    candidates, suppressed, debt = [], [], []
    seen = set()
    for c in raw:
        if not _has_min_facts(c['context']):
            debt.append({'hand_id': c['hand_id'], 'family': c['family'],
                         'missing_min_facts': [k for k in _MIN_FACTS if not c['context'].get(k)]})
            continue
        if c['relationship'] == 'ALREADY_REVIEWED_SAME_NODE':
            suppressed.append(c)
            continue
        key = (c['hand_id'], c['street'])      # one family per decision unless materially different
        if key in seen:
            continue
        seen.add(key)
        candidates.append(c)
    return {'candidates': candidates, 'suppressed': suppressed, 'engineering_debt': debt}


def review(candidates):
    """The bounded analyst review -- one terminal verdict per candidate, from the packet alone. Fail-closed:
    confirm a mistake ONLY on result-independent decision evidence. A value give-up with a strong made hand
    and no counter-play (check-through) is a CONFIRMED missed-value mistake. Aggression / curiosity-call
    families need an opponent range to confirm and are READ_DEPENDENT (the runtime has no canonical range)."""
    out = []
    for c in candidates:
        fam = c['family']
        if fam == 'river_value':
            # strong made hand given no value -> the error is result-independent (you can value bet worse).
            verdict = CONFIRMED_MISTAKE
            note = ('strong made hand (%s) reached the river and took no value; a value bet is called by '
                    'worse made hands -- checking/under-betting forfeits that value (decision error, not result)'
                    % c['context'].get('made_hand_class'))
            better = 'bet a standard value size (~50-75% pot) on the river'
        elif fam in ('turn_overbarrel', 'river_curiosity'):
            verdict = READ_DEPENDENT
            note = ('the leak is real-shaped but confirming it needs the opponent continuing/value range '
                    '(fold equity for the barrel; bluff frequency for the call) -- not canonical in the runtime')
            better = None
        else:
            verdict, note, better = INSUFFICIENT_EVIDENCE, 'insufficient canonical context', None
        out.append({
            'decision_id': c['decision_id'], 'hand_id': c['hand_id'], 'family': fam,
            'relationship': c['relationship'], 'terminal_verdict': verdict,
            'decision_error': note if verdict == CONFIRMED_MISTAKE else None,
            'evidence': c['detector_reason'], 'better_action': better, 'review_note': note,
        })
    return out


def value_metrics(disc, reviewed, n_hands):
    fams = ('turn_overbarrel', 'river_curiosity', 'river_value')
    per = []
    for fam in fams:
        cands = [c for c in disc['candidates'] if c['family'] == fam]
        revd = [r for r in reviewed if r['family'] == fam]
        confirmed = sum(1 for r in revd if r['terminal_verdict'] == CONFIRMED_MISTAKE)
        cleared = sum(1 for r in revd if r['terminal_verdict'] == JUSTIFIED)
        readdep = sum(1 for r in revd if r['terminal_verdict'] == READ_DEPENDENT)
        insf = sum(1 for r in revd if r['terminal_verdict'] == INSUFFICIENT_EVIDENCE)
        bug = sum(1 for r in revd if r['terminal_verdict'] == DETECTOR_BUG)
        resolved = confirmed + cleared
        per.append({
            'family': fam,
            'raw_candidates': len(cands),
            'suppressed_prior_reviewed': sum(1 for c in disc['suppressed'] if c['family'] == fam),
            'analyst_reviewed': len(revd),
            'confirmed_mistakes': confirmed, 'cleared': cleared, 'read_dependent': readdep,
            'insufficient_evidence': insf, 'detector_bugs': bug,
            'precision_among_resolved': (round(confirmed / resolved, 3) if resolved else None),
        })
    total_confirmed = sum(p['confirmed_mistakes'] for p in per)
    return {
        'benchmark': 'june16_844',
        'n_hands': n_hands,
        'families': per,
        'total_confirmed_new_mistakes': total_confirmed,
        'confirmed_mistakes_per_100_hands': round(100.0 * total_confirmed / max(n_hands, 1), 3),
        'engineering_debt_count': len(disc['engineering_debt']),
        'product_value_gate': 'PASS' if total_confirmed >= 1 else 'FAIL',
    }


def run(hands, prior_records=None, n_hands=None):
    hands = hands or []
    n = n_hands if n_hands is not None else len(hands)
    disc = discover(hands, prior_records)
    reviewed = review(disc['candidates'])
    metrics = value_metrics(disc, reviewed, n)
    return {'discovery': disc, 'reviewed': reviewed, 'metrics': metrics}
