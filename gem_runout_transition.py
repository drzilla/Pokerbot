"""gem_runout_transition.py -- v8.21 Range Reasoning / Runout Transition (descriptive foundation).

Builds ONE deterministic, result-independent transition record per eligible TURN or RIVER Hero decision:
what the new card changed about the board and Hero's hand, what remained valid, and what to reassess.

Trust rules (enforced): every operand is CONSUMED from a canonical owner --
  gem_decision_snapshot.build_decision_snapshot (identity / decision state),
  gem_parser.hand_strength_name (made hand), gem_made_hands.draw_profile (draws/outs),
  gem_analyst_packet._board_texture (texture). NO new evaluator; NO invented range/equity/EV; NO analyst math;
  NO later action/board/showdown leakage (board is the street-exact board_at_decision; the new card is its
  last card; prev board is the strict prefix). Strategic recommendations (continue/resize/slow/pivot/abandon)
  need an opponent-range/fold-equity owner that does NOT exist -> planning_implication is always
  'insufficient_evidence' in this MVP (the blocked layer is documented as engineering debt).
"""
from collections import Counter

import gem_parser
import gem_made_hands as _mh

_ORDER = '23456789TJQKA'
_MADE_RANK = {'high_card': 0, 'high card': 0, 'pair': 1, 'two_pair': 2, 'two pair': 2, 'trips': 3, 'set': 3,
              'straight': 4, 'flush': 5, 'full_house': 6, 'full house': 6, 'boat': 6, 'quads': 7,
              'straight_flush': 8, 'straight flush': 8}
_INSUFFICIENT = ('Insufficient evidence for a reliable action recommendation -- reassess the changed board '
                 'features.')


def _rank(card):
    return _ORDER.index(card[0])


def _made_rank(name):
    return _MADE_RANK.get((name or '').lower(), 0)


def _board_texture(board):
    import gem_analyst_packet as _ap
    try:
        return _ap._board_texture(board)
    except Exception:
        return None


def _made(cards, board):
    try:
        return gem_parser.hand_strength_name(cards, board) or 'unknown'
    except Exception:
        return 'unknown'


def _draw(cards, board):
    try:
        return _mh.draw_profile(cards, board) or {}
    except Exception:
        return {}


def _real_draw(dp):
    """A LIVE draw (one card from completing) -- a backdoor is not a real draw whose busting matters."""
    return dp.get('flush_draw') == 'flush_draw' or dp.get('straight_draw') in ('OESD', 'gutshot', 'double_gutshot')


def _draw_completed(db, da, made_b, made_a):
    bs = 'straight' in (made_a or '').lower() and 'straight' not in (made_b or '').lower()
    bf = 'flush' in (made_a or '').lower() and 'flush' not in (made_b or '').lower()
    return ((bs and db.get('straight_draw') in ('OESD', 'gutshot', 'double_gutshot'))
            or (bf and db.get('flush_draw') == 'flush_draw'))


def _draw_busted(db, da, completed):
    return _real_draw(db) and not _real_draw(da) and not completed


def _max_straight_window(board):
    idxs = sorted({_ORDER.index(c[0]) for c in board})
    best = 1
    for i in idxs:
        best = max(best, sum(1 for j in idxs if i <= j <= i + 4))
    return best


def transition_tags(prev_board, new_card, resulting_board, db, da, made_b, made_a, completed, outs_delta):
    """Deterministic transition tags from the raw board cards + canonical Hero state. Each tag is emitted
    ONLY when clearly true; never free-form classification."""
    tags = []
    prev_ranks = [c[0] for c in prev_board]
    nr_idx = _rank(new_card)
    # pairing
    if new_card[0] in prev_ranks:
        tags.append('board_paired')
        top = max(prev_board, key=_rank)[0]
        tags.append('top_card_pair' if new_card[0] == top else 'low_card_pair')
    rc = Counter(c[0] for c in resulting_board)
    if sum(1 for v in rc.values() if v >= 2) >= 2:
        tags.append('double_paired')
    # over / under relative to the previous board
    if all(nr_idx > _ORDER.index(r) for r in prev_ranks):
        tags.append('overcard')
    elif all(nr_idx < _ORDER.index(r) for r in prev_ranks):
        tags.append('undercard_or_brick')
    # flush dimension
    sc = Counter(c[1] for c in resulting_board)
    n = sc[new_card[1]]
    if n >= 5:
        tags.append('monotone_complete')
    elif n >= 4:
        tags.append('four_flush')
    elif n >= 3:
        tags.append('flush_card')
    # straight coordination: a card can only ADD board straightness. 3 board cards in a 5-rank window is a
    # connectivity increase; 4 in a window means a straight is one card away (a genuine straight threat).
    pw, nw = _max_straight_window(prev_board), _max_straight_window(resulting_board)
    if nw > pw and nw >= 3:
        tags.append('connectivity_increase')
    if nw >= 4:
        tags.append('straight_completing')
    # counterfeit: Hero's made hand was weakened by the runout
    if _made_rank(made_a) < _made_rank(made_b):
        tags.append('counterfeit')
    # blank vs Hero's draws: only meaningful when Hero is still drawing (no made hand) and the card neither
    # completes/extends the draw nor pairs/flushes/coordinates the board.
    if (not completed and outs_delta <= 0 and _made_rank(made_a) == 0
            and not any(t in tags for t in ('board_paired', 'flush_card', 'four_flush', 'monotone_complete',
                                            'straight_completing', 'connectivity_increase'))):
        tags.append('blank_vs_hero_draws')
    return sorted(set(tags))


def _hero_status(made_b, made_a, completed, busted_meaningful):
    rb, ra = _made_rank(made_b), _made_rank(made_a)
    if ra > rb or completed:
        return 'improved'
    if ra < rb or busted_meaningful:
        return 'weakened'
    return 'unchanged'


def _suit_name(s):
    return {'h': 'hearts', 'd': 'diamonds', 'c': 'clubs', 's': 'spades'}.get(s, s)


def build_transition(hand, action_index):
    """Return one deterministic transition record (dict) for a Hero turn/river decision, or an explicit
    fail-closed unresolved record. No future-information leakage; no invented numbers."""
    import gem_decision_snapshot as _ds
    hid = hand.get('id')
    cards = hand.get('cards') or []
    try:
        snap = _ds.build_decision_snapshot(hand, action_index)
    except Exception:
        snap = None

    def _unresolved(reason):
        return {'hand_id': hid, 'street': (snap or {}).get('street'), 'action_index': action_index,
                'unresolved': True, 'unresolved_reason': reason, 'planning_implication': 'insufficient_evidence',
                'register': 'Insufficient evidence', 'planning_text': _INSUFFICIENT}

    if (snap is None or snap.get('no_hero_decision')
            or snap.get('pot_before_action_bb') is None
            or snap.get('hero_stack_before_action_bb') is None
            or snap.get('canonical_effective_decision_depth_bb') is None):
        return _unresolved('no_canonical_decision_or_operand')
    street = snap.get('street')
    board = list(snap.get('board_at_decision') or [])
    if street not in ('turn', 'river') or len(board) not in (4, 5) or len(cards) != 2:
        return _unresolved('not_a_turn_or_river_node')
    # all-in / no-future-decision suppression
    al = hand.get('action_ledger') or []
    act = al[action_index] if isinstance(action_index, int) and 0 <= action_index < len(al) else None
    if (act and act.get('is_all_in')) or snap.get('became_all_in_on_this_action'):
        return _unresolved('all_in_or_no_future_decision')

    prev_board = board[:-1]
    new_card = board[-1]
    db = _draw(cards, prev_board)
    da = _draw(cards, board)
    made_b = _made(cards, prev_board)
    made_a = _made(cards, board)
    completed = _draw_completed(db, da, made_b, made_a)
    busted = _draw_busted(db, da, completed)
    # a busted draw only WEAKENS Hero when it leaves no made hand (high card); a redundant draw on a made
    # hand (e.g. a flush draw alongside a straight) missing is not a weakening.
    busted_meaningful = busted and _made_rank(made_a) == 0
    outs_delta = (da.get('clean_outs') or 0) - (db.get('clean_outs') or 0)
    status = _hero_status(made_b, made_a, completed, busted_meaningful)
    tags = transition_tags(prev_board, new_card, board, db, da, made_b, made_a, completed, outs_delta)

    contestable = snap.get('contestable_pot_before_action_bb')
    eff = snap.get('canonical_effective_decision_depth_bb')
    spr = round(eff / contestable, 2) if (contestable and eff is not None and contestable > 0) else None
    n_players = len(snap.get('players_active_before_action') or []) + 1

    # ---- planning evidence: facts (Factual) vs reassess prompts; strategic implication is blocked ----
    changed, remained, reassess = [], [], []
    T = 'canonical'
    if _made_rank(made_a) > _made_rank(made_b):
        changed.append({'fact': 'Your hand improved from %s to %s.' % (made_b, made_a),
                        'source': 'gem_parser.hand_strength_name', 'tier': 'canonical_made_hand_class'})
    elif _made_rank(made_a) < _made_rank(made_b):
        changed.append({'fact': 'Your made hand was counterfeited (%s -> %s) by this card.' % (made_b, made_a),
                        'source': 'gem_parser.hand_strength_name', 'tier': 'canonical_made_hand_class'})
    if completed:
        changed.append({'fact': 'Your draw completed.', 'source': 'gem_made_hands.draw_profile',
                        'tier': 'canonical_draw_profile'})
    if busted_meaningful:
        changed.append({'fact': 'Your draw missed -- you have no made hand.',
                        'source': 'gem_made_hands.draw_profile', 'tier': 'canonical_draw_profile'})
    if 'board_paired' in tags:
        changed.append({'fact': 'The board paired (%s).' % new_card, 'source': '_board_texture',
                        'tier': 'canonical_board_texture'})
        reassess.append('A pair on board makes trips/full houses possible -- reassess one-pair and overpair hands.')
    if any(t in tags for t in ('flush_card', 'four_flush', 'monotone_complete')):
        if 'flush' not in (made_a or '').lower():
            changed.append({'fact': 'A %s flush is now possible.' % _suit_name(new_card[1]),
                            'source': '_board_texture', 'tier': 'canonical_board_texture'})
            reassess.append('A flush is now possible -- reassess thin value bets and continued bluffs.')
    if 'straight_completing' in tags and 'straight' not in (made_a or '').lower():
        changed.append({'fact': 'The board is now straight-coordinated.', 'source': '_board_texture',
                        'tier': 'canonical_board_texture'})
        reassess.append('A straight is now possible -- reassess one-pair hands.')
    if 'overcard' in tags:
        changed.append({'fact': 'An overcard (%s) arrived above the previous board.' % new_card,
                        'source': '_board_texture', 'tier': 'canonical_board_texture'})
    if 'blank_vs_hero_draws' in tags and status == 'unchanged':
        changed.append({'fact': 'The %s is a blank -- it did not change your hand or the board structure.' % new_card,
                        'source': 'gem_made_hands.draw_profile', 'tier': 'canonical_draw_profile'})
    # what remained valid
    if _made_rank(made_a) >= 1:
        remained.append({'fact': 'You still hold %s (showdown value).' % made_a,
                         'source': 'gem_parser.hand_strength_name', 'tier': 'canonical_made_hand_class'})
    if status == 'unchanged' and not changed:
        remained.append({'fact': 'Nothing material changed for your hand this street.',
                         'source': 'gem_made_hands.draw_profile', 'tier': 'canonical_draw_profile'})

    unresolved_fields = []
    if spr is None:
        unresolved_fields.append('spr')

    register = 'Factual' if (changed or remained) else 'Insufficient evidence'
    return {
        'hand_id': hid, 'street': street, 'action_index': action_index,
        'decision_id': '%s:%s:%s' % (hid, street, action_index),
        'prev_board': prev_board, 'new_card': new_card, 'resulting_board': board,
        'position': snap.get('hero_position'), 'ip': hand.get('hero_ip'),
        'pot_type': hand.get('pot_type'), 'n_players': n_players, 'multiway': n_players >= 3,
        'initiative_pfr': bool(hand.get('pfr')), 'eff_stack_bb': eff, 'spr': spr,
        'prev_texture': _board_texture(prev_board), 'new_texture': _board_texture(board),
        'transition_tags': tags,
        'made_before': made_b, 'made_after': made_a,
        'made_detail_before': db.get('made_hand'), 'made_detail_after': da.get('made_hand'),
        'draw_before': {k: db.get(k) for k in ('straight_draw', 'flush_draw', 'straight_outs', 'flush_outs',
                        'clean_outs', 'overcards') if k in db},
        'draw_after': {k: da.get(k) for k in ('straight_draw', 'flush_draw', 'straight_outs', 'flush_outs',
                       'clean_outs', 'overcards') if k in da},
        'hero_status': status, 'outs_delta': outs_delta,
        'draw_completed': completed, 'draw_busted': busted,
        'has_showdown_value': _made_rank(made_a) >= 1,
        'changed': changed, 'remained': remained, 'reassess': sorted(set(reassess)),
        # strategic layer is BLOCKED (no opponent-range/fold-equity owner) -> honest reassessment prompt
        'planning_implication': 'insufficient_evidence', 'planning_text': _INSUFFICIENT,
        'register': register, 'evidence_tier': 'canonical_descriptive',
        'confidence': 'high', 'unresolved_fields': unresolved_fields,
        'canonical_resolved': True, 'canonical_source': 'gem_decision_snapshot+gem_parser+gem_made_hands',
    }


def teaching_block(rec):
    """Compact, player-facing teaching object from a transition record (the 5-part structure). Pure
    presentation of canonical facts -- it derives no new strategic operand."""
    if rec.get('unresolved'):
        return None
    return {
        'street': rec['street'], 'new_card': rec['new_card'],
        'before': 'Board %s (%s)%s' % ('-'.join(rec['prev_board']), rec['prev_texture'] or '?',
                                       ' -- you held %s' % rec['made_before'] if rec.get('made_before') else ''),
        'card': 'The %s fell%s.' % (rec['new_card'], (' (' + ', '.join(rec['transition_tags']) + ')') if rec['transition_tags'] else ''),
        'changed': [c['fact'] for c in rec['changed']],
        'remained': [r['fact'] for r in rec['remained']],
        'reassess': rec['reassess'],
        'implication': rec['planning_text'],
        'register': rec['register'], 'confidence': rec['confidence'],
    }


def render_html(rec):
    """The compact street-level HTML block (what the report surface would emit). No calculation here."""
    tb = teaching_block(rec)
    if tb is None:
        return ''
    badge = ("<span style='margin-left:6px;padding:2px 8px;border-radius:10px;background:#eef2ff;"
             "color:#3730a3;font-size:.78em;font-weight:700'>%s</span>" % tb['register'])
    parts = ["<div style='margin:6px 0;padding:8px 12px;border:1px solid #e5e7eb;border-radius:10px;background:#fff'>"]
    parts.append("<div style='font-weight:700;color:#111827'>Runout — the %s%s</div>" % (tb['new_card'], badge))
    if tb['changed']:
        parts.append("<div style='color:#374151'><strong>What changed:</strong> %s</div>" % ' '.join(tb['changed']))
    if tb['remained']:
        parts.append("<div style='color:#374151'><strong>Still valid:</strong> %s</div>" % ' '.join(tb['remained']))
    if tb['reassess']:
        parts.append("<div style='color:#374151'><strong>Reassess:</strong> %s</div>" % ' '.join(tb['reassess']))
    parts.append("<div style='margin-top:2px;color:#6b7280;font-size:.92em'>%s</div>" % tb['implication'])
    parts.append("</div>")
    return ''.join(parts)


def _hero_turn_river_decisions(hand):
    """Canonical enumeration of Hero's turn/river voluntary decision action indices (descriptive owner;
    same predicate the snapshot owners use)."""
    hero = hand.get('hero', 'Hero')
    out = []
    for i, a in enumerate(hand.get('action_ledger') or []):
        if (a.get('player') == hero and a.get('street') in ('turn', 'river')
                and (a.get('action') not in ('posts',))):
            out.append((a.get('street'), i))
    return out


def transitions_for_hand(hand):
    """All resolved transition records for a hand's turn/river Hero decisions (one per decision node)."""
    recs = []
    seen = set()
    for street, i in _hero_turn_river_decisions(hand):
        if street in seen:
            continue          # one transition per street (first Hero decision on that street)
        seen.add(street)
        recs.append(build_transition(hand, i))
    return recs
