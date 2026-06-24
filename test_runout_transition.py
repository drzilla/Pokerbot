"""Tests for gem_runout_transition (v8.21 Range Reasoning / Runout Transition) -- corrected contract.

Exits NONZERO on any failed assertion. Covers: neutral factual semantics (no improved/weakened/counterfeit/
showdown-value), shared-board vs Hero private-card contribution, board-only categories, ace-low (wheel)
connectivity + completion, fail-closed canonical evidence (made/draw/texture/invalid-cards/incomplete-snapshot),
one-record-per-street, and rendering through the REAL report note renderer with safe escaping.
"""
import re
import sys

import gem_parser
import gem_runout_transition as RT

_F = [0]
_N = [0]


def check(name, cond):
    _N[0] += 1
    print(('  PASS ' if cond else '  FAIL ') + name)
    if not cond:
        _F[0] += 1


# ---------------------------------------------------------------------------------------------------------
# Hand builders (valid GG-format strings; ids match TM\d+; positions/IP correct).
# ---------------------------------------------------------------------------------------------------------

def _hole(s):
    """Normalize a compact hole string ('9h2d') to the parser's space-separated form ('9h 2d')."""
    return s if ' ' in s else (s[:2] + ' ' + s[2:])


def _summary(board):
    return ['*** SUMMARY ***', 'Total pot 3000 | Rake 0', 'Board [%s]' % ' '.join(board),
            'Seat 1: Hero collected (3000)']


def hu_ip(hid, hole, flop, turn, river=None, double_turn=False, all_in_turn=False):
    """Heads-up single-raised pot, Hero on the BUTTON (in position)."""
    L = ["Poker Hand #%s: Tournament #888: RR Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01" % hid,
         "Table '1' 8-max Seat #1 is the button", "Seat 1: Hero (25000 in chips)", "Seat 2: V1 (25000 in chips)",
         "Hero: posts small blind 125", "V1: posts big blind 250", "*** HOLE CARDS ***",
         "Dealt to Hero [%s]" % _hole(hole), "Hero: raises 375 to 625", "V1: calls 375",
         "*** FLOP *** [%s]" % ' '.join(flop), "V1: checks", "Hero: bets 400", "V1: calls 400",
         "*** TURN *** [%s] [%s]" % (' '.join(flop), turn)]
    board = flop + [turn]
    if double_turn:
        L += ["V1: checks", "Hero: bets 900", "V1: raises 1800 to 2700", "Hero: calls 1800"]
    elif all_in_turn:
        L += ["V1: checks", "Hero: bets 24000 and is all-in", "V1: folds", "Uncalled bet (24000) returned to Hero"]
    elif river:
        L += ["V1: checks", "Hero: bets 900", "V1: calls 900",
              "*** RIVER *** [%s] [%s]" % (' '.join(board), river), "V1: checks", "Hero: bets 1500",
              "V1: folds", "Uncalled bet (1500) returned to Hero"]
        board = board + [river]
    else:
        L += ["V1: checks", "Hero: bets 900", "V1: folds", "Uncalled bet (900) returned to Hero"]
    L += _summary(board)
    return gem_parser.parse_one_hand('\n'.join(L), 'GG - Test.txt')


def hu_oop(hid, hole, flop, turn):
    """Heads-up, Hero in the BIG BLIND (out of position), leading the turn."""
    L = ["Poker Hand #%s: Tournament #888: RR Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01" % hid,
         "Table '1' 8-max Seat #1 is the button", "Seat 1: V1 (25000 in chips)", "Seat 2: Hero (25000 in chips)",
         "V1: posts small blind 125", "Hero: posts big blind 250", "*** HOLE CARDS ***",
         "Dealt to Hero [%s]" % _hole(hole), "V1: raises 375 to 625", "Hero: calls 375",
         "*** FLOP *** [%s]" % ' '.join(flop), "Hero: checks", "V1: bets 400", "Hero: calls 400",
         "*** TURN *** [%s] [%s]" % (' '.join(flop), turn), "Hero: bets 900", "V1: folds",
         "Uncalled bet (900) returned to Hero"]
    L += _summary(flop + [turn])
    return gem_parser.parse_one_hand('\n'.join(L), 'GG - Test.txt')


def mw(hid, hole, flop, turn):
    """Three-way single-raised pot, Hero on the BUTTON."""
    L = ["Poker Hand #%s: Tournament #888: RR Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01" % hid,
         "Table '1' 8-max Seat #1 is the button", "Seat 1: Hero (25000 in chips)", "Seat 2: V1 (25000 in chips)",
         "Seat 3: V2 (25000 in chips)", "V1: posts small blind 125", "V2: posts big blind 250",
         "*** HOLE CARDS ***", "Dealt to Hero [%s]" % _hole(hole), "Hero: raises 375 to 625", "V1: calls 500",
         "V2: calls 375", "*** FLOP *** [%s]" % ' '.join(flop), "V1: checks", "V2: checks", "Hero: bets 400",
         "V1: calls 400", "V2: calls 400", "*** TURN *** [%s] [%s]" % (' '.join(flop), turn), "V1: checks",
         "V2: checks", "Hero: bets 900", "V1: folds", "V2: folds", "Uncalled bet (900) returned to Hero"]
    L += _summary(flop + [turn])
    return gem_parser.parse_one_hand('\n'.join(L), 'GG - Test.txt')


def threebet(hid, hole, flop, turn):
    """Three-bet pot, Hero in the BIG BLIND as the 3-bettor."""
    L = ["Poker Hand #%s: Tournament #888: RR Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01" % hid,
         "Table '1' 8-max Seat #1 is the button", "Seat 1: V1 (25000 in chips)", "Seat 2: Hero (25000 in chips)",
         "V1: posts small blind 125", "Hero: posts big blind 250", "*** HOLE CARDS ***",
         "Dealt to Hero [%s]" % _hole(hole), "V1: raises 375 to 625", "Hero: raises 1375 to 2000", "V1: calls 1375",
         "*** FLOP *** [%s]" % ' '.join(flop), "Hero: bets 1200", "V1: calls 1200",
         "*** TURN *** [%s] [%s]" % (' '.join(flop), turn), "Hero: bets 2400", "V1: folds",
         "Uncalled bet (2400) returned to Hero"]
    L += _summary(flop + [turn])
    return gem_parser.parse_one_hand('\n'.join(L), 'GG - Test.txt')


def turn_rec(h):
    return next((r for r in RT.transitions_for_hand(h) if r.get('street') == 'turn'), None)


def river_rec(h):
    return next((r for r in RT.transitions_for_hand(h) if r.get('street') == 'river'), None)


# ---------------------------------------------------------------------------------------------------------
print('[1] neutral factual semantics: shared board vs Hero private-card contribution')

r = turn_rec(hu_ip('TM101', '9h2d', ['Ks', 'Qd', '7c'], 'Kh'))
check('board pairs -> category_changed', r['category_changed'])
check('board pair -> Hero hole cards do NOT contribute', r['hero_hole_cards_contribute_after'] is False)
check('board pair -> board_only_or_shared_category', r['board_only_or_shared_category'] is True)
check('turn shared wording = exact board property (not a complete shared best-five)',
      any('every remaining player' in c['fact'] and 'at least one pair' in c['fact'] for c in r['changed']))
check('turn shared change does NOT claim "best five ... shared"',
      not any('best five is' in c['fact'] and 'shared by every remaining player' in c['fact'] for c in r['changed']))
check('shared change does NOT say improved', not any(re.search(r'improv', c['fact'], re.I) for c in r['changed']))

r = turn_rec(hu_ip('TM102', '8h8d', ['Qs', '7d', '2c'], '7h'))
check('pocket pair on paired board: contributes', r['hero_hole_cards_contribute_after'] is True)
check('pocket pair on paired board: category pair->two_pair', r['category_changed'] and
      r['best_five_category_after'] == 'two_pair')
check('Hero-contribution wording uses "your hole cards now make"',
      any('your hole cards now make' in c['fact'].lower() for c in r['changed']))

r = river_rec(hu_ip('TM103', '3d2c', ['Ks', 'Kd', '7c'], '7h', river='9s'))
check('board-only two pair: no contribution', r['hero_hole_cards_contribute_after'] is False)
check('board-only two pair: shared', r['board_only_or_shared_category'] is True)

print('[2] Hero genuine private improvement (draw completion via hole cards)')
r = turn_rec(hu_ip('TM110', 'AhKh', ['Qh', '7h', '2c'], 'Th'))
check('flush completes: draw_completed', r['draw_completed'] is True)
check('flush completes: hole cards contribute', r['hero_hole_cards_contribute_after'] is True)
check('flush completes: wording mentions draw completed',
      any('draw completed' in c['fact'].lower() for c in r['changed']))

print('[3] ace-low (wheel) connectivity and completion')
r = turn_rec(hu_ip('TM120', 'KdQc', ['As', '2d', '3c'], '4h'))
check('A-2-3-4 turn -> four_to_a_straight (ace plays low)', 'four_to_a_straight' in r['transition_tags'])
r = turn_rec(hu_ip('TM121', '5h4h', ['Ad', '2c', '7s'], '3d'))
check('Hero completes the wheel: draw_completed', r['draw_completed'] is True)
check('Hero completes the wheel: best-five straight', r['best_five_category_after'] == 'straight')
check('Hero completes the wheel: contributes', r['hero_hole_cards_contribute_after'] is True)

print('[4] objective board tags')
check('overcard tag', 'overcard' in turn_rec(hu_ip('TM130', '6h6d', ['9s', '5d', '2c'], 'Ah'))['transition_tags'])
check('flush card tag', 'flush_card' in turn_rec(hu_ip('TM131', 'AsKd', ['7h', '6h', '2c'], 'Th'))['transition_tags'])
check('board_paired tag', 'board_paired' in turn_rec(hu_ip('TM132', 'AcKd', ['Qh', '8d', '2c'], 'Qs'))['transition_tags'])
rb = turn_rec(hu_ip('TM133', 'TcTd', ['Ks', '9d', '2c'], '5h'))
check('blank tag only when nothing meaningful changed', 'blank' in rb['transition_tags'] and not rb['category_changed'])
check('connectivity_decrease is not a tag', not any('connectivity_decrease' in t for t in rb['transition_tags']))
check('counterfeit is not a tag anywhere',
      not any('counterfeit' in t for t in turn_rec(hu_ip('TM134', 'AhKd', ['Qh', '8d', '2c'], 'Qs'))['transition_tags']))

print('[5] fail-closed canonical evidence (each owner forced to fail)')


def _forced_unresolved(module_name, attr, hand):
    """Build the hand UNPATCHED, then force a canonical owner to fail and re-derive the record fail-closed."""
    import importlib
    mod = importlib.import_module(module_name)
    orig = getattr(mod, attr)

    def boom(*a, **k):
        raise RuntimeError('forced')

    setattr(mod, attr, boom)
    try:
        idx = next(i for s, i in RT._hero_turn_river_decisions(hand) if s == 'turn')
        return RT.build_transition(hand, idx)
    finally:
        setattr(mod, attr, orig)


hf = hu_ip('TM140', 'AhKd', ['Qh', '8d', '2c'], '5s')
r = _forced_unresolved('gem_parser', 'hand_strength_name', hf)
check('made-hand failure -> unresolved missing_made_hand_evidence',
      r.get('unresolved') and r.get('unresolved_reason') == 'missing_made_hand_evidence')
check('unresolved record carries NO factual claims', not r.get('changed') and not r.get('remained'))
check('unresolved record confidence is not high', r.get('confidence') != 'high')
r = _forced_unresolved('gem_made_hands', 'draw_profile', hf)
check('draw failure -> unresolved missing_draw_evidence',
      r.get('unresolved') and r.get('unresolved_reason') == 'missing_draw_evidence')
r = _forced_unresolved('gem_analyst_packet', '_board_texture', hf)
check('texture failure -> unresolved missing_texture_evidence',
      r.get('unresolved') and r.get('unresolved_reason') == 'missing_texture_evidence')
h = hu_ip('TM141', 'AhKd', ['Qh', '8d', '2c'], '5s')
h['cards'] = ['Zz', 'Kd']
idx = next(i for s, i in RT._hero_turn_river_decisions(h) if s == 'turn')
r = RT.build_transition(h, idx)
check('invalid cards -> unresolved invalid_cards', r.get('unresolved') and r.get('unresolved_reason') == 'invalid_cards')
r = _forced_unresolved('gem_decision_snapshot', 'build_decision_snapshot', hf)
check('snapshot failure -> unresolved incomplete_decision_snapshot',
      r.get('unresolved') and r.get('unresolved_reason') == 'incomplete_decision_snapshot')

print('[6] suppression / eligibility')
check('all-in turn -> unresolved all_in_or_no_future_decision',
      turn_rec(hu_ip('TM150', 'AhKd', ['Qh', '8d', '2c'], '5s', all_in_turn=True)).get('unresolved_reason')
      == 'all_in_or_no_future_decision')
h = hu_ip('TM151', 'AhKd', ['Qh', '8d', '2c'], '5s')
check('only turn/river decisions enumerated', all(s in ('turn', 'river') for s, _ in RT._hero_turn_river_decisions(h)))

print('[7] one record per street + no future-card leak')
h = hu_ip('TM160', 'AhKd', ['Qh', '8d', '2c'], '5s', double_turn=True)
turns = [r for r in RT.transitions_for_hand(h) if r.get('street') == 'turn']
check('exactly one record per street', len(turns) == 1)
r = turn_rec(hu_ip('TM161', 'AhKd', ['Qh', '8d', '2c'], '5s', river='9s'))
check('turn record board has exactly 4 cards (no river leak)', len(r['resulting_board']) == 4)
check('turn record never mentions the river card', '9s' not in str(r['changed']) and '9s' not in str(r['transition_tags']))

print('[8] no unsupported strength wording anywhere (batch scan)')
hands = [hu_ip('TM170', '9h2d', ['Ks', 'Qd', '7c'], 'Kh'),
         hu_ip('TM171', '8h8d', ['Qs', '7d', '2c'], '7h'),
         hu_oop('TM172', 'AhKd', ['Qh', '8d', '2c'], '5s'),
         mw('TM173', 'Td9d', ['Js', '8d', '2c'], '7h'),
         threebet('TM174', 'AhKh', ['Qh', '7h', '2c'], 'Th')]
banned = ('showdown value', 'improved', 'improve', 'weakened', 'counterfeit')
alltext = []
for h in hands:
    for r in RT.transitions_for_hand(h):
        if r.get('unresolved'):
            continue
        alltext.append(' '.join(c['fact'] for c in r['changed']))
        alltext.append(' '.join(c['fact'] for c in r['remained']))
        alltext.append(RT.transition_note_text(r))
blob = ' '.join(alltext).lower()
for w in banned:
    check('no "%s" wording' % w, w not in blob)
check('IP hand is in position', hands[0].get('hero_ip') is True)
check('OOP hand is out of position', hands[2].get('hero_ip') is False)
check('multiway hand has >=3 players', turn_rec(hands[3])['multiway'] is True)

print('[9] render through the REAL report note renderer + safe escaping')
from gem_report_draft._html import _md_inline, _html_escape
r = turn_rec(hu_ip('TM180', 'AsKd', ['7h', '6h', '2c'], 'Th'))
note = RT.transition_note_text(r)
html = _md_inline(note)
check('note renders to a non-empty HTML string', isinstance(html, str) and len(html) > 0)
check('rendered note contains no raw script injection', '<script' not in html.lower())
check('every displayed card value is a safe token',
      all(re.match(r'^[2-9TJQKA][hdcs]$', c) for c in (r['prev_board'] + [r['new_card']])))
check('canonical renderer escapes < and >', _html_escape('<b>x</b>') == '&lt;b&gt;x&lt;/b&gt;')
check('unresolved record renders to empty note (no placeholder)',
      RT.transition_note_text({'unresolved': True}) == '')

# ---------------------------------------------------------------------------------------------------------
print('\nRESULTS: %d passed, %d failed, %d total' % (_N[0] - _F[0], _F[0], _N[0]))
if _F[0]:
    print('RUNOUT TRANSITION TESTS FAILED')
    sys.exit(1)
print('ALL RUNOUT TRANSITION TESTS PASSED')
