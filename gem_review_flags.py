"""
gem_review_flags.py — v8.12.1 P2 review-tier flags (owner-approved batch)
==========================================================================
G4 River Bluff-Catcher Review · G6 Missed Value Check-Raise (narrow) ·
G12 Sizing Review. REVIEW TIER ONLY: cautious copy, never "punt"/"wrong"/
"GTO mistake", never counted as confirmed mistakes, never in Top Punts or
BB/100. Output renders as small hand-detail notes (data-street routed).
"""

_BANNED = ('punt', 'wrong', 'gto mistake')


def _runout_flags(board):
    if not board or len(board) < 5:
        return []
    suits = [c[1] for c in board if len(c) >= 2]
    flags = []
    for su in set(suits):
        if suits.count(su) >= 4:
            flags.append('4-flush runout')
            break
    ranks = sorted({'23456789TJQKA'.index(c[0]) for c in board
                    if c and c[0] in '23456789TJQKA'})
    for i in range(len(ranks) - 3):
        if ranks[i + 3] - ranks[i] <= 4:
            flags.append('4-straight runout')
            break
    if len({c[0] for c in board}) <= 3:
        flags.append('double-paired board')
    return flags


def build_review_flags(hands, cap=40):
    """Returns {hand_id: [flag, ...]}; each flag has kind/street/copy."""
    out = {}
    n = 0
    for h in hands or []:
        hid = h.get('id', '')
        if not hid:
            continue
        if n >= cap:
            break
        flags = []
        hero = h.get('hero', '')
        board = h.get('board') or []
        ledger = [a for a in (h.get('action_ledger') or [])
                  if a.get('action') != 'posts']

        # G4: river bluff-catcher review — Hero CALLED a river bet on a
        # scary runout and lost at showdown.
        if len(board) >= 5 and (h.get('net_bb') or 0) < 0 \
                and h.get('went_to_sd'):
            river = [a for a in ledger if a.get('street') == 'river']
            faced_bet = False
            for a in river:
                if a.get('player') == hero:
                    if faced_bet and a.get('action') == 'calls':
                        rf = _runout_flags(board)
                        if rf:
                            flags.append({
                                'kind': 'river_bluffcatch_review',
                                'street': 'river',
                                'copy': ('River call review on a '
                                         + ', '.join(rf) + ' — checklist: '
                                         'what beats us? what bluffs remain? '
                                         'do we block value / unblock '
                                         'bluffs? what price? is this '
                                         'villain type underbluffing?')})
                        break
                elif a.get('action') in ('bets', 'raises'):
                    faced_bet = True

        # G12: sizing review — min-click raises by Hero postflop.
        prev_bet = 0.0
        for a in ledger:
            if a.get('street') == 'preflop':
                continue
            amt = a.get('amount_bb') or 0
            if a.get('player') == hero and a.get('action') == 'raises' \
                    and prev_bet > 0 and amt > 0 \
                    and abs(amt - prev_bet) / prev_bet < 0.12 \
                    and not a.get('is_all_in'):
                flags.append({
                    'kind': 'sizing_review_minclick',
                    'street': a.get('street', ''),
                    'copy': ('Sizing review: min-click raise '
                             f'({amt:.1f}BB over {prev_bet:.1f}BB) — '
                             'rarely achieves a fold and reopens the '
                             'action; consider call or a larger raise '
                             'sizing.')})
                break
            if a.get('action') in ('bets', 'raises'):
                prev_bet = amt or prev_bet

        _g6 = g6_missed_value_checkraise(h)
        if _g6:
            flags.append(_g6)

        if flags:
            out[hid] = flags[:2]
            n += 1
    for fl in out.values():
        for f in fl:
            low = f['copy'].lower()
            assert not any(b in low for b in _BANNED), f
    return out

def _rank_class(cards, board):
    """phevaluator rank for hero at this board (lower = stronger);
    None when unavailable. 3325 = worst two-pair."""
    try:
        from phevaluator import evaluate_cards
        if len(cards) == 2 and len(board) >= 3:
            return evaluate_cards(*cards, *board)
    except Exception:
        pass
    return None


def _wet(board):
    if len(board) < 3:
        return False
    suits = [c[1] for c in board if len(c) >= 2]
    if any(suits.count(x) >= 2 for x in set(suits)):
        return True
    rk = sorted({'23456789TJQKA'.index(c[0]) for c in board
                 if c and c[0] in '23456789TJQKA'})
    return any(rk[i + 2] - rk[i] <= 4 for i in range(len(rk) - 2))


def g6_missed_value_checkraise(h):
    """v8.12.2 G6 (narrow first scope per review): Hero OOP, HU, check-CALLS
    turn or river holding two-pair-or-better on a wet texture. Review-tier.
    Bluff/thin/multiway explicitly excluded."""
    if h.get('hero_ip') is not False or (h.get('players_at_flop') or 0) != 2:
        return None
    cards = h.get('cards') or []
    board = h.get('board') or []
    hero = h.get('hero', '')
    for street, n in (('turn', 4), ('river', 5)):
        if len(board) < n or not _wet(board[:n]):
            continue
        seq = [a for a in (h.get('action_ledger') or [])
               if a.get('street') == street and a.get('action') != 'posts']
        pat = [(a.get('player') == hero, a.get('action')) for a in seq[:3]]
        if (len(pat) >= 3 and pat[0] == (True, 'checks')
                and pat[1][0] is False and pat[1][1] in ('bets',)
                and pat[2] == (True, 'calls')):
            rank = _rank_class(cards, board[:n])
            if rank is not None and rank <= 3325:
                return {'kind': 'missed_value_checkraise', 'street': street,
                        'copy': ('Check-raise review: OOP heads-up '
                                 f'check-call on the {street} holding a '
                                 'two-pair-or-better hand on a wet board — '
                                 'worse made hands and draws can plausibly '
                                 'pay a raise here. Worth a solver look at '
                                 'the raise line.')}
    return None


def build_p4_worksheet(hands, stats=None):
    """v8.12.2 P4 (analyst worksheet ONLY — never user-facing):
    G11 overbluff candidates · G14 post-loss aggression clusters ·
    G15 big-stack bubble pressure row. Neutral wording throughout."""
    out = {'g11_overbluff_candidates': [], 'g14_post_loss_clusters': [],
           'g15_big_stack_bubble': {}}
    try:
        hands = list(hands or [])
        vpip_flags = [1 if h.get('vpip') else 0 for h in hands]
        base_vpip = (sum(vpip_flags) / len(vpip_flags) * 100) if hands else 0
        for h in hands:
            hero = h.get('hero', '')
            board = h.get('board') or []
            if len(board) >= 5 and h.get('went_to_sd') \
                    and (h.get('net_bb') or 0) < 0:
                river = [a for a in (h.get('action_ledger') or [])
                         if a.get('street') == 'river'
                         and a.get('player') == hero
                         and a.get('action') in ('bets', 'raises')]
                if river:
                    rank = _rank_class(h.get('cards') or [], board)
                    if rank is not None and rank > 6185:
                        out['g11_overbluff_candidates'].append({
                            'id': h.get('id', ''),
                            'street': 'river',
                            'note': 'river aggression with no made pair, '
                                    'called and lost — candidate for bluff '
                                    'selection review (worksheet only)'})
        for i, h in enumerate(hands):
            if (h.get('net_bb') or 0) <= -25:
                nxt = vpip_flags[i + 1:i + 11]
                if len(nxt) >= 6:
                    v = sum(nxt) / len(nxt) * 100
                    if v - base_vpip >= 15:
                        out['g14_post_loss_clusters'].append({
                            'after_hand': h.get('id', ''),
                            'window_vpip': round(v, 1),
                            'session_vpip': round(base_vpip, 1),
                            'note': 'post-loss aggression cluster '
                                    '(sequence review — neutral wording)'})
        bub = [h for h in hands
               if (h.get('tournament_phase') or '') == 'bubble_zone']
        big = []
        for h in bub:
            stacks = [v for v in (h.get('seat_stacks_bb_all') or {}).values()
                      if isinstance(v, (int, float))]
            if stacks and (h.get('stack_bb') or 0) >= max(stacks) - 0.01:
                big.append(h)
        if big:
            steal_opps = [h for h in big if h.get('position') in
                          ('CO', 'BTN', 'SB') and not h.get('hero_faced_raise')]
            stole = [h for h in steal_opps if h.get('vpip')]
            out['g15_big_stack_bubble'] = {
                'bubble_hands_as_cover': len(big),
                'steal_opps': len(steal_opps),
                'steal_attempts': len(stole),
                'note': 'aggregate only — requires icm_context + covers '
                        'reliability before any verdict tier'}
    except Exception:
        pass
    return out
