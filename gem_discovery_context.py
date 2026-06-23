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
import gem_sizing_detector

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
        # owner correction #2: a hand the CANONICAL betting class calls 'value' (top pair / overpair /
        # two pair) is NOT a weak-pair over-barrel -- suppress it unless a separate explicit runout/range
        # condition makes betting questionable (none available without a range -> suppress).
        if (f.get('betting_class') or '').lower() == 'value':
            continue
        if weak and not strong_draw:
            out.append(_record(h, 'turn', 'turn_overbarrel',
                               'bet flop and turn with a weak made hand (%s, betting_class=%s) and no strong draw'
                               % (made or 'n/a', f.get('betting_class')), f, prior_records))
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


# =========================================================================================== #
# Iteration-3 rule-backed high-precision sweep (the only added families). Confirmable WITHOUT a #
# range: each finding is backed by an existing canonical chart or an accepted owner rule.       #
# =========================================================================================== #

CHART_BACKED = 'CHART_BACKED'
OWNER_RULE_BACKED = 'OWNER_RULE_BACKED'
_PREMIUM_CODES = {'AA', 'KK', 'QQ', 'AKs', 'AKo'}


def _preflop(h):
    return [a for a in (h.get('action_ledger') or []) if isinstance(a, dict) and a.get('street') == 'preflop']


def _hero_eff_stack(h):
    for k in ('eff_stack_bb', 'effective_stack_bb', 'hero_eff_stack_bb', 'stack_bb', 'hero_stack_bb'):
        if isinstance(h.get(k), (int, float)):
            return h[k]
    return None


def hand_code(cards):
    if len(cards) != 2:
        return ''
    order = '23456789TJQKA'
    a, b = cards[0][0], cards[1][0]
    if order.index(a) < order.index(b):
        a, b = b, a
    if a == b:
        return a + b
    return a + b + ('s' if cards[0][1] == cards[1][1] else 'o')


def _is_premium(cards):
    return hand_code(cards) in _PREMIUM_CODES


def _rule_record(hand, street, family, reason, facts, prior_records, tier, source, alt):
    rec = _record(hand, street, family, reason, facts, prior_records)
    rec['evidence_tier'] = tier
    rec['rule_source'] = source
    rec['proposed_alternative'] = alt
    rec['missing_assumptions'] = []     # rule-backed: nothing missing
    return rec


def family_sb_flat_vs_late_open(hands, prior_records=None):
    """F3: Hero in the SB, 20-40bb, a SINGLE BTN/CO open, Hero FLATS (a genuine call of a raise -- NOT a
    limp-complete), HEADS-UP (no other voluntary player), non-premium. The accepted owner rule is
    3-bet-or-fold from the SB versus a late open at this depth, so an OOP flat is the leak."""
    out = []
    for h in hands:
        if (h.get('position') or '') != 'SB':
            continue
        e = _hero_eff_stack(h)
        if not (e and 20 <= e <= 40):
            continue
        cards = h.get('cards') or []
        if len(cards) != 2 or _is_premium(cards):
            continue
        pf = _preflop(h)
        raises = [a for a in pf if a.get('action') == 'raises' and a.get('player') != 'Hero']
        if len(raises) != 1:                              # exactly one opener (no 3-bet, no limp-raise)
            continue
        opener = raises[0]
        if (opener.get('position') or '') not in ('BTN', 'CO'):
            continue
        if not [a for a in pf if a.get('player') == 'Hero' and a.get('action') == 'calls']:
            continue                                       # Hero must FLAT (genuine call of the raise)
        others = [a for a in pf if a.get('player') not in ('Hero', opener.get('player'))
                  and a.get('action') in ('calls', 'raises') and (a.get('amount_bb') or 0) > 0.6]
        if others:                                         # heads-up only (no multiway / limpers)
            continue
        facts = {'street': 'preflop', 'hero_cards': cards, 'position': 'SB',
                 'eff_stack_bb': round(e, 1), 'opener_position': opener.get('position'),
                 'hand_code': hand_code(cards), 'active_players': 2,
                 'action_line': [(a.get('player'), a.get('position'), a.get('action')) for a in pf]}
        out.append(_rule_record(
            h, 'preflop', 'sb_flat_vs_late_open',
            'SB flat-called a %s open heads-up at %.0fbb with %s -- the accepted rule is 3-bet-or-fold from the SB'
            % (opener.get('position'), e, hand_code(cards)), facts, prior_records,
            OWNER_RULE_BACKED, 'owner-rule: SB vs a single late (BTN/CO) open at 20-40bb is 3-bet-or-fold; no OOP flat',
            '3-bet, or fold -- never flat out of position from the SB at this depth'))
    return out


def family_deep_preflop_stackoff(hands, prior_records=None):
    """F1: eff > 40bb, Hero commits all-in preflop, not AA/KK. Surfaced for review (chart/forced
    exceptions are resolved in the review, not asserted by the detector)."""
    out = []
    for h in hands:
        cards = h.get('cards') or []
        if len(cards) != 2:
            continue
        e = _hero_eff_stack(h)
        if not (e and e > 40):
            continue
        pf = _preflop(h)
        if not (h.get('pf_allin') or any(a.get('player') == 'Hero' and a.get('is_all_in') for a in pf)):
            continue
        if hand_code(cards) in ('AA', 'KK'):
            continue
        facts = {'street': 'preflop', 'hero_cards': cards, 'eff_stack_bb': round(e, 1),
                 'hand_code': hand_code(cards), 'position': h.get('position'),
                 'action_line': [(a.get('player'), a.get('position'), a.get('action')) for a in pf]}
        out.append(_record(h, 'preflop', 'deep_preflop_stackoff',
                           'committed all-in preflop at %.0fbb without AA/KK (%s)' % (e, hand_code(cards)),
                           facts, prior_records))
    return out


def family_short_stack_coldcall(hands, prior_records=None):
    """F2: decision-time eff < 15bb, Hero not in the BB, Hero cold-calls an existing raise. Confirmed
    only when the canonical chart/rule does not permit the call (resolved in review)."""
    out = []
    for h in hands:
        cards = h.get('cards') or []
        if len(cards) != 2:
            continue
        if (h.get('position') or '') == 'BB':
            continue
        e = _hero_eff_stack(h)
        if not (e and e < 15):
            continue
        pf = _preflop(h)
        hero_calls = [a for a in pf if a.get('player') == 'Hero' and a.get('action') == 'calls']
        if not hero_calls:
            continue
        if not [a for a in pf if a.get('player') != 'Hero' and a.get('action') == 'raises']:
            continue
        # owner 0.2: distinguish a GENUINE flat (chips behind) from an all-in call (remaining stack below
        # the raise). An all-in call is push/fold, NOT the cold-call leak -- exclude it from the family,
        # do not classify the whole family by one template.
        max_call = max((a.get('amount_bb') or 0) for a in hero_calls)
        all_in_call = bool(any(a.get('is_all_in') for a in hero_calls) or max_call >= e)
        if all_in_call:
            continue
        facts = {'street': 'preflop', 'hero_cards': cards, 'eff_stack_bb': round(e, 1),
                 'hand_code': hand_code(cards), 'position': h.get('position'),
                 'all_in_call': False, 'chips_behind': True,
                 'action_line': [(a.get('player'), a.get('position'), a.get('action')) for a in pf]}
        out.append(_record(h, 'preflop', 'short_stack_coldcall',
                           'flat-called a raise at %.0fbb outside the BB with chips behind (%s)'
                           % (e, hand_code(cards)), facts, prior_records))
    return out


def family_flop_cbet_sizing(hands, prior_records=None):
    """v8.21 pilot Family A: per-hand flop c-bet SIZING mismatch vs the canonical board-archetype band.

    Chart-backed and result-independent. Consumes only canonical inputs (hand['hero_bets'] sizing %,
    hand['board_archetype'], hand['hero_ip'], hand['eff_stack_bb']) and the gem_textures GTO band via
    gem_sizing_detector.assess_flop_cbet_sizing -- it invents no sizing math and no range. Fails closed
    (emits nothing) on any missing canonical input. The graded node is a CLEAN single flop c-bet (Hero's
    last flop action is the c-bet), so the decision_id action_index resolves to the c-bet itself."""
    out = []
    for h in hands:
        cards = h.get('cards') or []
        if len(cards) != 2:
            continue
        hflop = _hero_acts(h, 'flop')
        # only grade a clean single flop c-bet: exactly one Hero flop action and it is the bet. A
        # later flop action (call/fold facing a raise) is a different decision and is excluded.
        if len(hflop) != 1 or (hflop[0].get('action') or '') != 'bets':
            continue
        a = gem_sizing_detector.assess_flop_cbet_sizing(h)
        if not a:
            continue
        board = (h.get('board') or [])[:3]
        try:
            made = gem_parser.hand_strength_name(cards, board)
        except Exception:
            made = None
        if not made:
            continue                                   # postflop packet-completeness needs a made-hand class
        facts = {
            'street': 'flop', 'hero_cards': cards, 'board': board,
            'made_hand_class': made, 'position': h.get('position'), 'hero_ip': h.get('hero_ip'),
            'eff_stack_bb': a['eff_stack_bb_flop'], 'pot_before_bb': _pot_before(h, 'flop'),
            'sizing_assessment': a,
            # merged VERBATIM into the sealed atomic record (via _norm_decision) so the analyst can cite
            # the exact canonical sizing numbers (fact_refs: ['sizing_assessment']) with no calculation.
            'packet_facts': {'sizing_assessment': a},
            'action_line': [(x.get('player'), x.get('action'), x.get('amount_bb'))
                            for x in _street_acts(h, 'flop')],
        }
        reason = ('flop c-bet %.0f%% of pot on a %s board %s at %.0fbb; the canonical complete band is %s '
                  '(%s-size by %.0fpp, %s)'
                  % (a['actual_sizing_pct'], a['board_archetype'].replace('_', ' '), a['cbet_side'].upper(),
                     a['eff_stack_bb_flop'], '/'.join('%d%%' % t for t in a['target_sizings_pct']),
                     a['direction'], a['deviation_pp'], a['severity']))
        alt = ('size the flop c-bet toward %d%% of pot (the canonical %s %s band)'
               % (a['proposed_sizing_pct'], a['board_archetype'].replace('_', ' '), a['cbet_side'].upper()))
        out.append(_rule_record(
            h, 'flop', 'flop_cbet_sizing', reason, facts, prior_records, CHART_BACKED,
            'gto_texture_archetypes.json sizing band for %s %s %s'
            % (a['board_archetype'], a['cbet_side'].upper(), a['depth_band']), alt))
    return out


def packet_present_fields(c):
    """The list of required packet fields that are actually PRESENT for this candidate (owner 0.2: a
    separate present-fields list, distinct from the strict boolean verdict)."""
    f = c.get('context', {}) or {}
    base = [k for k in ('decision_id',) if c.get(k)] + \
           [k for k in ('hero_cards',) if f.get(k)] + \
           [k for k in ('detector_reason',) if c.get(k)]
    if c['family'] in ('sb_flat_vs_late_open', 'deep_preflop_stackoff', 'short_stack_coldcall'):
        base += [k for k in ('eff_stack_bb', 'hand_code') if f.get(k) is not None and f.get(k) != '']
    else:
        base += [k for k in ('made_hand_class', 'board') if f.get(k)]
    return base


def _packet_complete(c):
    """STRICT boolean (owner 0.2): a one-pass-ready packet carries the decision id + hero hand + detector
    reason + the canonical decision context for its family. Always returns a real bool."""
    f = c.get('context', {}) or {}
    base = bool(c.get('decision_id') and f.get('hero_cards') and c.get('detector_reason'))
    if c['family'] in ('sb_flat_vs_late_open', 'deep_preflop_stackoff', 'short_stack_coldcall'):
        return bool(base and f.get('eff_stack_bb') is not None and f.get('hand_code'))
    return bool(base and f.get('made_hand_class') and f.get('board'))


def review_value(candidates):
    """The bounded review including the rule-backed families. Only the rule-backed SB-flat (an explicit
    accepted owner rule, confirmable without a range) confirms; everything range-dependent stays
    READ_DEPENDENT; deep stack-off / short cold-call of reasonable hands are JUSTIFIED."""
    out = []
    for c in candidates:
        fam = c['family']
        if fam == 'sb_flat_vs_late_open':
            verdict, tier = CONFIRMED_MISTAKE, OWNER_RULE_BACKED
            note = ('SB flat-call out of position versus a single late open violates the accepted '
                    '3-bet-or-fold rule at 20-40bb; %s is a 3-bet-or-fold hand, not an OOP flat' % c['context'].get('hand_code'))
            better = c.get('proposed_alternative')
        elif fam == 'deep_preflop_stackoff':
            # owner 0.2: do NOT auto-justify a >40bb non-AA/KK stack-off. The accepted rule is to avoid
            # it; confirming or clearing the exact spot needs the canonical jam/4-bet range or a chart/
            # forced-action exception, which is not available here -> read-dependent (never inferred from
            # the result). e.g. JJ calling a 4-bet jam off 43bb is genuinely range-dependent.
            verdict, tier, note, better = READ_DEPENDENT, '', \
                ('a >40bb non-AA/KK preflop stack-off goes against the accepted rule; confirming/clearing '
                 'this exact spot needs the canonical opponent jam range or a chart/forced exception'), None
        elif fam == 'short_stack_coldcall':
            verdict, tier, note, better = READ_DEPENDENT, '', \
                'a genuine non-BB short-stack flat with chips behind -- needs the canonical short-stack calling chart to confirm/clear', None
        elif fam == 'flop_cbet_sizing':
            a = (c.get('context') or {}).get('sizing_assessment') or {}
            _band = '/'.join('%d%%' % t for t in (a.get('target_sizings_pct') or []))
            if a.get('severity') == 'gross':
                verdict, tier = CONFIRMED_MISTAKE, CHART_BACKED
                note = ('flop c-bet size %.0f%% of pot grossly deviates from the canonical complete %s %s '
                        'band %s (%s-size by %.0fpp) -- a result-independent sizing error'
                        % (a.get('actual_sizing_pct', 0), a.get('board_archetype', ''),
                           (a.get('cbet_side') or '').upper(), _band, a.get('direction', ''),
                           a.get('deviation_pp', 0)))
                better = c.get('proposed_alternative')
            else:
                verdict, tier = READ_DEPENDENT, CHART_BACKED
                note = ('flop c-bet size %.0f%% of pot is off the %s %s band %s but within a range a '
                        'deliberate mix/exploit could justify -- analyst confirms vs the canonical band'
                        % (a.get('actual_sizing_pct', 0), a.get('board_archetype', ''),
                           (a.get('cbet_side') or '').upper(), _band))
                better = c.get('proposed_alternative')
        elif fam == 'river_value':
            verdict, tier = CONFIRMED_MISTAKE, 'canonical_made_hand_class'
            note = 'strong made hand took no value on the river (decision error, result-independent)'
            better = 'bet a standard value size'
        elif fam in ('turn_overbarrel', 'river_curiosity'):
            verdict, tier, note, better = READ_DEPENDENT, '', \
                'confirming needs a canonical opponent range (not available) -- preserved read-dependent', None
        else:
            verdict, tier, note, better = INSUFFICIENT_EVIDENCE, '', 'insufficient context', None
        out.append({
            'decision_id': c['decision_id'], 'hand_id': c['hand_id'], 'family': fam,
            'relationship': c.get('relationship'), 'terminal_verdict': verdict,
            'evidence_tier': tier, 'evidence_source': c.get('rule_source'),
            'decision_error': note if verdict == CONFIRMED_MISTAKE else None,
            'evidence': c['detector_reason'], 'better_action': better, 'review_note': note,
            'result_independent': verdict == CONFIRMED_MISTAKE,
        })
    return out


def run_value(hands, prior_records=None, n_hands=None, session='june16_844'):
    """The Iteration-3 product-value run: recalibrated postflop families + the rule-backed sweep,
    reconciled vs prior truth, packet-completeness-audited, reviewed, gated."""
    hands = hands or []
    n = n_hands if n_hands is not None else len(hands)
    raw = (family_turn_overbarrel(hands, prior_records) + family_river_curiosity(hands, prior_records)
           + family_river_value(hands, prior_records) + family_sb_flat_vs_late_open(hands, prior_records)
           + family_deep_preflop_stackoff(hands, prior_records) + family_short_stack_coldcall(hands, prior_records)
           + family_flop_cbet_sizing(hands, prior_records))    # v8.21 pilot Family A (chart-backed sizing)
    candidates, suppressed, debt = [], [], []
    seen = set()
    for c in raw:
        if c['relationship'] == 'ALREADY_REVIEWED_SAME_NODE':
            suppressed.append(c)
            continue
        if not _packet_complete(c):
            debt.append({'hand_id': c['hand_id'], 'family': c['family'], 'reason': 'packet incomplete'})
            continue
        key = (c['hand_id'], c['street'], c['family'])
        if key in seen:
            continue
        seen.add(key)
        candidates.append(c)
    reviewed = review_value(candidates)
    confirmed = [r for r in reviewed if r['terminal_verdict'] == CONFIRMED_MISTAKE]
    fams = sorted({c['family'] for c in raw})
    by_family = {}
    for fam in fams:
        rev = [r for r in reviewed if r['family'] == fam]
        by_family[fam] = {
            'raw_candidates': sum(1 for c in raw if c['family'] == fam),
            'suppressed_prior_reviewed': sum(1 for c in suppressed if c['family'] == fam),
            'packet_complete': sum(1 for c in candidates if c['family'] == fam),
            'reviewed': len(rev),
            'confirmed_mistakes': sum(1 for r in rev if r['terminal_verdict'] == CONFIRMED_MISTAKE),
            'justified': sum(1 for r in rev if r['terminal_verdict'] == JUSTIFIED),
            'read_dependent': sum(1 for r in rev if r['terminal_verdict'] == READ_DEPENDENT),
            'insufficient': sum(1 for r in rev if r['terminal_verdict'] == INSUFFICIENT_EVIDENCE),
        }
    metrics = {
        'session': session, 'n_hands': n, 'by_family': by_family,
        'engineering_debt_count': len(debt),
        'total_confirmed_new_mistakes': len(confirmed),
        'confirmed_mistakes_per_100_hands': round(100.0 * len(confirmed) / max(n, 1), 3),
        'product_value_gate': 'PASS' if len(confirmed) >= 1 else 'FAIL',
    }
    return {'candidates': candidates, 'suppressed': suppressed, 'engineering_debt': debt,
            'reviewed': reviewed, 'confirmed': confirmed, 'metrics': metrics}
