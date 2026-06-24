"""gem_runout_transition.py -- v8.21 Range Reasoning / Runout Transition (descriptive foundation).

Builds ONE deterministic, result-independent transition record per eligible TURN or RIVER Hero decision:
what the new card OBJECTIVELY changed about the board and Hero's hand, what remained factually true, and what
needs reassessment.

SAFETY CONTRACT (enforced + tested):
  * Every operand is CONSUMED from a canonical owner -- gem_decision_snapshot.build_decision_snapshot
    (identity / decision state), gem_parser.hand_strength_name (best-five made-hand class),
    gem_made_hands.draw_profile (draws/outs), gem_analyst_packet._board_texture (texture). NO new
    hand-strength/equity evaluator; NO invented range/equity/EV; NO analyst math.
  * NO later action / later board card / showdown leakage: the board is the street-exact board_at_decision,
    the new card is its last card, the previous board is the strict prefix.
  * FAIL CLOSED: any required canonical evaluator failure (or invalid cards / incomplete snapshot) yields an
    unresolved record with an exact reason -- NO Factual high-confidence claims, NO rendered block.
  * NO unsafe relative-strength claim. We do NOT say Hero "improved", "weakened", was "counterfeited", or has
    "showdown value" -- a shared board change (e.g. the board pairing) lifts the formal best-five category for
    EVERY remaining player without improving Hero's private-card contribution. We state only objective facts:
    the best-five category before/after, whether Hero's HOLE CARDS contribute (proven by comparing Hero's
    best-five against the BOARD-ONLY best-five), whether that category is shared by the whole field, and
    whether a real draw completed or missed. Relative strength / the correct action is explicitly UNRESOLVED
    without a canonical opponent-range owner (which does not exist).
"""
from collections import Counter

import gem_parser
import gem_made_hands as _mh

_ORDER = '23456789TJQKA'
_MADE_RANK = {'high_card': 0, 'high card': 0, 'pair': 1, 'two_pair': 2, 'two pair': 2, 'trips': 3, 'set': 3,
              'straight': 4, 'flush': 5, 'full_house': 6, 'full house': 6, 'boat': 6, 'quads': 7,
              'straight_flush': 8, 'straight flush': 8}
_A = _ORDER.index('A')
# the strategic action / relative strength is UNRESOLVED without a canonical opponent-range owner
_UNRESOLVED_STRATEGY = ('Relative hand strength and the correct action are unresolved here: that needs a '
                        'canonical opponent-range owner, which does not exist. Reassess the changed board '
                        'features rather than assuming a stronger relative position.')


class _EvidenceError(Exception):
    """A required canonical owner failed -- the record must fail closed with this reason."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _rank(card):
    return _ORDER.index(card[0])


def _made_rank(name):
    return _MADE_RANK.get((name or '').lower(), 0)


def _valid_card(c):
    return isinstance(c, str) and len(c) == 2 and c[0] in _ORDER and c[1] in 'hdcs'


# ---- canonical owners, fail-closed --------------------------------------------------------------------

def _made_or_fail(cards, board, reason):
    try:
        v = gem_parser.hand_strength_name(cards, board)
    except Exception:
        raise _EvidenceError(reason)
    if not v or str(v).strip().lower() in ('unknown', 'none', ''):
        raise _EvidenceError(reason)
    return v


def _draw_or_fail(cards, board, reason):
    try:
        v = _mh.draw_profile(cards, board)
    except Exception:
        raise _EvidenceError(reason)
    if v is None or not isinstance(v, dict):
        raise _EvidenceError(reason)
    return v


def _texture_or_fail(board, reason):
    import gem_analyst_packet as _ap
    try:
        v = _ap._board_texture(board)
    except Exception:
        raise _EvidenceError(reason)
    if v is None:
        raise _EvidenceError(reason)
    return v


def _board_category(board):
    """Best-five category available from the BOARD ALONE (everyone shares it). River (>=5 cards): reuse the
    canonical evaluator on the 5 board cards. Turn (4 cards): only rank-count categories are possible (a board
    straight/flush needs 5 cards), computed from board ranks. Raises _EvidenceError on evaluator failure."""
    if len(board) >= 5:
        return _made_or_fail(board[:2], board[2:], 'missing_made_hand_evidence')
    rc = sorted(Counter(c[0] for c in board).values(), reverse=True)
    if not rc:
        return 'high_card'
    if rc[0] >= 4:
        return 'quads'
    if rc[0] == 3:
        return 'trips'
    if rc[0] == 2 and len(rc) > 1 and rc[1] == 2:
        return 'two_pair'
    if rc[0] == 2:
        return 'pair'
    return 'high_card'


# ---- draws --------------------------------------------------------------------------------------------

def _real_draw(dp):
    """A LIVE draw (one card from completing). A backdoor is NOT a real draw whose completion/busting matters."""
    return dp.get('flush_draw') == 'flush_draw' or dp.get('straight_draw') in ('OESD', 'gutshot', 'double_gutshot')


def _draw_completed(db, made_b, made_a):
    """A real draw completed iff Hero's category gained straight/flush AND he held the corresponding real draw."""
    gained_straight = 'straight' in (made_a or '').lower() and 'straight' not in (made_b or '').lower()
    gained_flush = 'flush' in (made_a or '').lower() and 'flush' not in (made_b or '').lower()
    return ((gained_straight and db.get('straight_draw') in ('OESD', 'gutshot', 'double_gutshot'))
            or (gained_flush and db.get('flush_draw') == 'flush_draw'))


def _real_draw_missed(db, da, completed):
    return _real_draw(db) and not _real_draw(da) and not completed


# ---- straight windows (ace plays high AND low) --------------------------------------------------------

def _max_straight_window(board):
    base = {_ORDER.index(c[0]) for c in board}
    candidate_sets = [base]
    if _A in base:                                   # ace also plays low (A-2-3-4-5 wheel)
        low = set(base)
        low.discard(_A)
        low.add(-1)
        candidate_sets.append(low)
    best = 1 if board else 0
    for s in candidate_sets:
        for i in s:
            best = max(best, sum(1 for j in s if i <= j <= i + 4))
    return best


# ---- transition tags ----------------------------------------------------------------------------------

def transition_tags(prev_board, new_card, resulting_board, hole_contributes_after):
    """Deterministic, objective board tags. Each is emitted ONLY when clearly true. No private-card
    strength inference (no 'counterfeit'); no connectivity_decrease (a card cannot reduce coordination)."""
    tags = []
    prev_ranks = [c[0] for c in prev_board]
    nr_idx = _rank(new_card)
    # pairing of the board by the new card
    if new_card[0] in prev_ranks:
        tags.append('board_paired')
        top = max(prev_board, key=_rank)[0]
        tags.append('top_card_pair' if new_card[0] == top else 'low_card_pair')
    rc = Counter(c[0] for c in resulting_board)
    if sum(1 for v in rc.values() if v >= 2) >= 2:
        tags.append('double_paired')
    if any(v >= 3 for v in rc.values()):
        tags.append('trips_on_board')
    # over / under relative to the previous board
    if prev_ranks and all(nr_idx > _ORDER.index(r) for r in prev_ranks):
        tags.append('overcard')
    elif prev_ranks and all(nr_idx < _ORDER.index(r) for r in prev_ranks):
        tags.append('undercard_or_brick')
    # flush dimension (count of the new card's suit on the resulting board)
    sc = Counter(c[1] for c in resulting_board)
    n = sc[new_card[1]]
    if n >= 5:
        tags.append('monotone_complete')
    elif n >= 4:
        tags.append('four_flush')
    elif n >= 3:
        tags.append('flush_card')
    # straight coordination (a card can only ADD board straightness)
    pw, nw = _max_straight_window(prev_board), _max_straight_window(resulting_board)
    if nw > pw and nw >= 3:
        tags.append('connectivity_increase')
    if nw >= 4:
        tags.append('four_to_a_straight')
    if nw >= 5:
        tags.append('straight_on_board')
    return tags


def _suit_name(s):
    return {'h': 'heart', 'd': 'diamond', 'c': 'club', 's': 'spade'}.get(s, s)


def _label(name):
    """Player-facing label for a best-five category enum (no raw implementation names in the report)."""
    n = (name or '').lower()
    return {'high_card': 'high card', 'two_pair': 'two pair', 'full_house': 'full house', 'boat': 'full house',
            'straight_flush': 'straight flush', 'set': 'a set'}.get(n, n.replace('_', ' '))


def _f(fact, source, tier):
    return {'fact': fact, 'source': source, 'tier': tier}


# ---- main builder -------------------------------------------------------------------------------------

def build_transition(hand, action_index):
    """Return one deterministic transition record (dict) for a Hero turn/river decision, or an explicit
    fail-closed unresolved record. No future-information leakage; no invented numbers; no unsafe relative
    -strength claim."""
    import gem_decision_snapshot as _ds
    hid = hand.get('id')
    cards = hand.get('cards') or []
    try:
        snap = _ds.build_decision_snapshot(hand, action_index)
    except Exception:
        snap = None

    def _unresolved(reason, kind):
        return {'hand_id': hid, 'street': (snap or {}).get('street'), 'action_index': action_index,
                'unresolved': True, 'unresolved_reason': reason, 'unresolved_kind': kind,
                'register': 'Insufficient evidence', 'confidence': 'none',
                'strategic_implication': 'unresolved', 'strategic_text': _UNRESOLVED_STRATEGY,
                'changed': [], 'remained': [], 'reassess': []}

    if (snap is None or snap.get('no_hero_decision')
            or snap.get('pot_before_action_bb') is None
            or snap.get('hero_stack_before_action_bb') is None
            or snap.get('canonical_effective_decision_depth_bb') is None):
        return _unresolved('incomplete_decision_snapshot', 'incomplete_decision_snapshot')
    street = snap.get('street')
    board = list(snap.get('board_at_decision') or [])
    if street not in ('turn', 'river') or len(board) not in (4, 5):
        return _unresolved('not_a_turn_or_river_node', 'not_a_turn_or_river_node')
    if len(cards) != 2 or not all(_valid_card(c) for c in cards) or not all(_valid_card(c) for c in board):
        return _unresolved('invalid_cards', 'invalid_cards')
    # all-in / no-future-decision suppression
    al = hand.get('action_ledger') or []
    act = al[action_index] if isinstance(action_index, int) and 0 <= action_index < len(al) else None
    if (act and act.get('is_all_in')) or snap.get('became_all_in_on_this_action'):
        return _unresolved('all_in_or_no_future_decision', 'all_in_or_no_future_decision')

    prev_board = board[:-1]
    new_card = board[-1]
    try:
        made_b = _made_or_fail(cards, prev_board, 'missing_made_hand_evidence')
        made_a = _made_or_fail(cards, board, 'missing_made_hand_evidence')
        db = _draw_or_fail(cards, prev_board, 'missing_draw_evidence')
        da = _draw_or_fail(cards, board, 'missing_draw_evidence')
        board_cat_b = _board_category(prev_board)            # may raise missing_made_hand_evidence (river)
        board_cat_a = _board_category(board)
        prev_texture = _texture_or_fail(prev_board, 'missing_texture_evidence')
        new_texture = _texture_or_fail(board, 'missing_texture_evidence')
    except _EvidenceError as e:
        return _unresolved(e.reason, e.reason)

    # ---- objective Hero-state facts (NO improved/weakened/counterfeit/showdown-value) ----
    rb, ra = _made_rank(made_b), _made_rank(made_a)
    category_changed = ra != rb
    hole_contributes_before = rb > _made_rank(board_cat_b)
    hole_contributes_after = ra > _made_rank(board_cat_a)
    board_only_or_shared = not hole_contributes_after        # Hero's category is fully available from the board
    completed = _draw_completed(db, made_b, made_a)
    real_draw_missed = _real_draw_missed(db, da, completed)
    outs_delta = (da.get('clean_outs') or 0) - (db.get('clean_outs') or 0)

    tags = transition_tags(prev_board, new_card, board, hole_contributes_after)
    structural = any(t in tags for t in ('board_paired', 'double_paired', 'trips_on_board', 'flush_card',
                                         'four_flush', 'monotone_complete', 'four_to_a_straight',
                                         'straight_on_board', 'connectivity_increase'))
    hero_event = category_changed or completed or real_draw_missed
    if not structural and not hero_event and 'overcard' not in tags and 'undercard_or_brick' not in tags:
        tags.append('blank')
    tags = sorted(set(tags))

    contestable = snap.get('contestable_pot_before_action_bb')
    eff = snap.get('canonical_effective_decision_depth_bb')
    spr = round(eff / contestable, 2) if (contestable and eff is not None and contestable > 0) else None
    n_players = len(snap.get('players_active_before_action') or []) + 1

    # ---- factual statements: what changed / what remained / what to reassess ----
    changed, remained, reassess = [], [], []
    SRC_M, T_M = 'gem_parser.hand_strength_name', 'canonical_made_hand_class'
    SRC_D, T_D = 'gem_made_hands.draw_profile', 'canonical_draw_profile'
    SRC_T, T_T = 'gem_analyst_packet._board_texture', 'canonical_board_texture'

    la, lb = _label(made_a), _label(made_b)
    suit = _suit_name(new_card[1])

    # 1) Hero's hand -- private-card contribution / completion / miss only (never a shared board lift).
    #    A shared (board-only) category change is expressed by the board-property facts below, so a 4-card
    #    turn board is never described as supplying a complete shared best-five hand.
    if completed:
        kind = 'straight' if 'straight' in made_a.lower() else 'flush'
        changed.append(_f('Your %s draw completed: your hole cards now make a %s.' % (kind, la), SRC_D, T_D))
    elif category_changed and hole_contributes_after:
        changed.append(_f('Your hole cards now make %s (was %s).' % (la, lb), SRC_M, T_M))
    elif real_draw_missed and not hole_contributes_after:
        changed.append(_f('Your draw did not complete and your hole cards do not make a hand on this board.',
                          SRC_D, T_D))
    elif real_draw_missed and hole_contributes_after:
        changed.append(_f('Your draw did not complete, though your hole cards still make %s.' % la, SRC_D, T_D))

    # 2) board pairing -- the precise shared property (turn: exact board property; river: complete best-five)
    if 'board_paired' in tags:
        if board_only_or_shared and category_changed:
            if street == 'river':
                changed.append(_f('The board paired (%s); your best five is %s, supplied by the board and '
                                  'shared by every remaining player.' % (new_card, la), SRC_T, T_T))
            elif 'double_paired' in tags:
                changed.append(_f('The board paired (%s) and is now double-paired; every remaining player plays '
                                  'at least two pair from the board.' % new_card, SRC_T, T_T))
            elif 'trips_on_board' in tags:
                changed.append(_f('The board paired (%s); trips are present on the board and shared by every '
                                  'remaining player.' % new_card, SRC_T, T_T))
            else:
                changed.append(_f('The paired board (%s) gives every remaining player at least one pair (your '
                                  'best five plays the board).' % new_card, SRC_T, T_T))
        else:
            changed.append(_f('The board paired (%s).' % new_card, SRC_T, T_T))
        reassess.append('A paired board makes trips and full houses possible for some holdings -- reassess '
                        'one-pair and overpair holdings.')

    # 3) flush dimension -- distinguish three / four / five suited board cards
    if 'monotone_complete' in tags:
        changed.append(_f('A %s flush is now present on the board and is shared unless a player can make a '
                          'higher flush.' % suit, SRC_T, T_T))
        reassess.append('A %s flush is on the board -- reassess unless you hold a higher card of that suit.' % suit)
    elif 'four_flush' in tags:
        changed.append(_f('The board is now four-%s; any player holding one %s can make a flush.' % (suit, suit),
                          SRC_T, T_T))
        reassess.append('Four to a flush is on the board -- reassess thin value bets and continued bluffs.')
    elif 'flush_card' in tags:
        changed.append(_f('A third %s arrived; a flush is now possible for holdings containing two %ss.'
                          % (suit, suit), SRC_T, T_T))
        reassess.append('A flush is now possible -- reassess thin value bets and continued bluffs.')

    # 4) straight dimension -- connectivity / four-to-a-straight / straight on the board (Hero completion is (1))
    if 'straight_on_board' in tags:
        if board_only_or_shared:
            changed.append(_f('A straight is now present on the board and is shared unless a player can make a '
                              'higher straight.', SRC_T, T_T))
        else:
            changed.append(_f('A straight is now present on the board; your hole cards make a higher hand.', SRC_T, T_T))
    elif 'four_to_a_straight' in tags and 'straight' not in made_a.lower():
        changed.append(_f('The board is now four-to-a-straight; some holdings can complete a straight.', SRC_T, T_T))
        reassess.append('Some holdings can now complete a straight -- reassess one-pair holdings.')
    elif 'connectivity_increase' in tags:
        changed.append(_f('The board became more connected.', SRC_T, T_T))

    # 5) overcard / blank
    if 'overcard' in tags:
        changed.append(_f('An overcard (%s) arrived above the previous board.' % new_card, SRC_T, T_T))
        reassess.append('An overcard arrived -- a prior top pair or overpair may no longer be top of the board.')
    if 'blank' in tags:
        changed.append(_f('The %s is a blank: it did not change your best five, your draws, or the board '
                          'structure.' % new_card, SRC_D, T_D))

    # what remained factually true
    if not category_changed and hole_contributes_after and ra >= 1:
        remained.append(_f('Your hole cards still make %s.' % la, SRC_M, T_M))
    elif not category_changed and board_only_or_shared and ra >= 1:
        remained.append(_f('Your best five (%s) comes from the board and is unchanged.' % la, SRC_M, T_M))
    if 'blank' in tags and not remained:
        remained.append(_f('Your best five (%s) is unchanged this street.' % la, SRC_M, T_M))

    # the descriptive block is Factual; the strategic action line is Insufficient evidence
    register = 'Factual' if (changed or remained) else 'Insufficient evidence'
    return {
        'hand_id': hid, 'street': street, 'action_index': action_index,
        'decision_id': '%s:%s:%s' % (hid, street, action_index),
        'prev_board': prev_board, 'new_card': new_card, 'resulting_board': board,
        'position': snap.get('hero_position'), 'ip': hand.get('hero_ip'),
        'pot_type': hand.get('pot_type'), 'n_players': n_players, 'multiway': n_players >= 3,
        'initiative_pfr': bool(hand.get('pfr')), 'eff_stack_bb': eff, 'spr': spr,
        'prev_texture': prev_texture, 'new_texture': new_texture,
        'transition_tags': tags,
        # objective best-five facts
        'best_five_category_before': made_b, 'best_five_category_after': made_a,
        'category_changed': category_changed,
        'board_category_before': board_cat_b, 'board_category_after': board_cat_a,
        'hero_hole_cards_contribute_before': hole_contributes_before,
        'hero_hole_cards_contribute_after': hole_contributes_after,
        'board_only_or_shared_category': board_only_or_shared,
        'made_detail_before': db.get('made_hand'), 'made_detail_after': da.get('made_hand'),
        'draw_before': {k: db.get(k) for k in ('straight_draw', 'flush_draw', 'straight_outs', 'flush_outs',
                        'clean_outs', 'overcards') if k in db},
        'draw_after': {k: da.get(k) for k in ('straight_draw', 'flush_draw', 'straight_outs', 'flush_outs',
                       'clean_outs', 'overcards') if k in da},
        'draw_completed': completed, 'real_draw_missed': real_draw_missed, 'outs_delta': outs_delta,
        'changed': changed, 'remained': remained, 'reassess': sorted(set(reassess)),
        # strategic layer BLOCKED (no opponent-range owner) -> honest unresolved line
        'strategic_implication': 'unresolved', 'strategic_text': _UNRESOLVED_STRATEGY,
        'strategic_register': 'Insufficient evidence',
        'register': register, 'evidence_tier': 'canonical_descriptive', 'confidence': 'high',
        'unresolved': False, 'canonical_resolved': True,
        'canonical_source': 'gem_decision_snapshot+gem_parser+gem_made_hands+gem_analyst_packet',
    }


def teaching_block(rec):
    """Compact, player-facing teaching object (the 5-part structure) from a RESOLVED record. Pure
    presentation of canonical facts -- derives no new operand. None for unresolved records."""
    if rec.get('unresolved'):
        return None
    return {
        'street': rec['street'], 'new_card': rec['new_card'],
        'before': 'Board %s (%s) -- your best five was %s' % ('-'.join(rec['prev_board']),
                  rec['prev_texture'], rec['best_five_category_before']),
        'card': 'The %s arrived.' % rec['new_card'],
        'changed': [c['fact'] for c in rec['changed']],
        'remained': [r['fact'] for r in rec['remained']],
        'reassess': rec['reassess'],
        'strategic': rec['strategic_text'],
        'register': rec['register'], 'strategic_register': rec['strategic_register'],
        'confidence': rec['confidence'],
    }


def transition_note_text(rec):
    """The PRODUCTION surface: plain Markdown sentences for the EXISTING per-street note renderer (no inline
    styles, no separate HTML component -- the report's canonical note pipeline escapes and styles it). Returns
    '' for unresolved records (no empty placeholder). The Factual facts come first; the relative-strength /
    action line is explicitly marked 'Insufficient evidence' in words, since no range owner exists."""
    tb = teaching_block(rec)
    if tb is None:
        return ''
    out = ['**Runout — the %s.**' % tb['new_card']]
    out.extend(tb['changed'])
    if tb['remained']:
        out.append('Still true: ' + ' '.join(tb['remained']))
    if tb['reassess']:
        out.append('Reassess: ' + ' '.join(tb['reassess']))
    # compact strategic line (the full canonical-owner explanation lives in rec['strategic_text'] / the docs,
    # not repeated in full on every street). Bold renders via _md_inline; no literal Markdown underscores.
    out.append('**Strategic read: insufficient evidence** -- relative strength and the correct action are not '
               'determinable from objective facts alone.')
    return ' '.join(s.strip() for s in out if s and s.strip())


def _hero_turn_river_decisions(hand):
    """Canonical enumeration of Hero's turn/river voluntary decision action indices."""
    hero = hand.get('hero', 'Hero')
    out = []
    for i, a in enumerate(hand.get('action_ledger') or []):
        if (a.get('player') == hero and a.get('street') in ('turn', 'river')
                and (a.get('action') not in ('posts',))):
            out.append((a.get('street'), i))
    return out


def transitions_for_hand(hand):
    """All transition records for a hand's turn/river Hero decisions -- exactly one per street (the first
    Hero decision node on that street). This is the PRODUCT PATH the report consumes."""
    recs = []
    seen = set()
    for street, i in _hero_turn_river_decisions(hand):
        if street in seen:
            continue
        seen.add(street)
        recs.append(build_transition(hand, i))
    return recs
