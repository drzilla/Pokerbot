"""Integration tests for the v8.21 Runout Transition wiring into _split_argument_into_notes.

Exits NONZERO on any failed assertion. Proves the note is additive and safe: <=1 per street, turn+river each
get one, unresolved/all-in render nothing, survives the single-narrative override, existing commentary +
pill numbering + tone are preserved, no dup on multi-action streets, distinct 3/4/5-suit wording, turn
shared-board never claims a complete board-only best-five, no enum/markdown artifacts, safe through _md_inline,
no range/equity/EV/strategic directive, and no transition data in the analyst packet.
"""
import os
import re
import sys

import gem_parser
import gem_runout_transition as RT
from gem_report_draft._hand_grid import _split_argument_into_notes
from gem_report_draft._html import _md_inline

_F = [0]
_N = [0]


def check(name, cond):
    _N[0] += 1
    print(('  PASS ' if cond else '  FAIL ') + name)
    if not cond:
        _F[0] += 1


def _hole(s):
    return s if ' ' in s else (s[:2] + ' ' + s[2:])


def hand(hid, hole, flop, turn, river=None, double_turn=False, all_in_turn=False):
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
    L += ['*** SUMMARY ***', 'Total pot 3000 | Rake 0', 'Board [%s]' % ' '.join(board), 'Seat 1: Hero collected (3000)']
    return gem_parser.parse_one_hand('\n'.join(L), 'GG - Test.txt')


def hero_acts(h):
    out = {}
    for i, a in enumerate(h.get('action_ledger') or []):
        if a.get('player') == h.get('hero', 'Hero') and a.get('action') != 'posts':
            out.setdefault(a.get('street'), []).append(i)
    return out


def split(h, argument='', analyst_street=None):
    return _split_argument_into_notes(argument, '', '', '', '', hero_acts(h), analyst_street=analyst_street, hand=h)


def all_text(notes):
    return ' '.join(notes)


# ---------------------------------------------------------------------------------------------------------
print('[1] additive injection: no analyst argument -> one transition note, bound + critical tone')
h = hand('TM801', '8h8d', ['Qs', '7d', '2c'], '7h')
notes, a2n, a2t, snn = split(h)
turn_keys = [k for k in a2n if k[0] == 'turn']
check('one transition note on turn', len(notes) == 1 and len(turn_keys) == 1)
check('bound to first hero turn action', turn_keys and turn_keys[0][1] == hero_acts(h)['turn'][0])
check('tone is critical (numbered pill, not a thumbs)', a2t[turn_keys[0]] == 'critical')
check('contains the runout marker', 'Runout — the 7h' in notes[0])

print('[2] turn AND river each receive exactly one note')
h = hand('TM802', '8h8d', ['Qs', '7d', '2c'], '5s', river='9c')
notes, a2n, a2t, snn = split(h)
check('turn note present', any(k[0] == 'turn' for k in a2n))
check('river note present', any(k[0] == 'river' for k in a2n))
check('exactly one note per street', sum(1 for k in a2n if k[0] == 'turn') == 1 and sum(1 for k in a2n if k[0] == 'river') == 1)

print('[3] unresolved / all-in render nothing')
h = hand('TM803', '8h8d', ['Qs', '7d', '2c'], '7h', all_in_turn=True)
notes, a2n, a2t, snn = split(h)
check('all-in turn -> no transition note', not any('Runout' in n for n in notes))
notes2, _, _, _ = _split_argument_into_notes('', '', '', '', '', hero_acts(h), hand=None)
check('hand=None -> no transition note', notes2 == [])

print('[4] survives the single-narrative override (long prose argument)')
h = hand('TM804', '8h8d', ['Qs', '7d', '2c'], '7h')
long_arg = ('Preflop Hero opens 8h8d from the button and gets called. ' * 1 +
            'Flop comes Qs7d2c and Hero c-bets for value with a small pair and backdoor equity. '
            'Turn is the 7h which pairs the board, a meaningful node Hero must reassess carefully here. '
            'Hero continues to barrel given fold equity and the texture. River planning depends on the runout.')
notes, a2n, a2t, snn = split(h, argument=long_arg)
check('long narrative triggered single-narrative path (snn set)', snn is not None)
check('transition text survives the override', any('Runout — the 7h' in n for n in notes))
check('existing analyst commentary still present', any('Hero opens' in n or 'c-bets' in n for n in notes))

print('[5] merge preserves pill numbering + tone; no gaps/dupes')
h = hand('TM805', '8h8d', ['Qs', '7d', '2c'], '7h')
notes, a2n, a2t, snn = split(h, argument='Turn is a clear value bet.', analyst_street='turn')
nums = sorted(a2n.values())
check('note numbers are contiguous 1..N with no dupes', nums == list(range(1, len(notes) + 1)) and len(set(nums)) == len(nums))
check('transition merged into the existing turn note (not a second pill)', sum(1 for k in a2n if k[0] == 'turn') == 1
      and any('value bet' in n and 'Runout' in n for n in notes))

print('[6] non-key street behaviour unchanged (preflop/flop notes identical with vs without hand)')
h = hand('TM806', '8h8d', ['Qs', '7d', '2c'], '7h')
arg = 'Preflop Hero opens. Flop Hero c-bets.'
base = _split_argument_into_notes(arg, '', '', '', '', hero_acts(h), hand=None)
wired = _split_argument_into_notes(arg, '', '', '', '', hero_acts(h), hand=h)
pf_fl_base = {k: v for k, v in base[1].items() if k[0] in ('preflop', 'flop')}
pf_fl_wired = {k: v for k, v in wired[1].items() if k[0] in ('preflop', 'flop')}
check('preflop/flop attachments unchanged', pf_fl_base == pf_fl_wired)

print('[7] no duplicate note when Hero acts multiple times on a street')
h = hand('TM807', '8h8d', ['Qs', '7d', '2c'], '7h', double_turn=True)
notes, a2n, a2t, snn = split(h)
check('exactly one transition note on the turn (multi-action street)', sum(1 for n in notes if 'Runout' in n) == 1)

print('[8] distinct 3 / 4 / 5 suited wording')
n3 = split(hand('TM808', 'AsKd', ['7h', '6h', '2c'], 'Th'))[0]
n4 = split(hand('TM809', 'AsKd', ['7h', '6h', '2h'], 'Th'))[0]
n5 = split(hand('TM810', 'AsKd', ['7h', '6h', '2h'], 'Th', river='Qh'))[0]
check('3-suited wording', any('a third heart' in n.lower() for n in n3))
check('4-suited wording', any('four-heart' in n.lower() for n in n4))
check('5-suited wording', any('flush is now present on the board' in n.lower() for n in n5))
check('3/4/5 wordings are distinct', all_text(n3) != all_text(n4) != all_text(n5))

print('[9] turn shared-board never claims a complete board-only best-five')
n = split(hand('TM811', '9h2d', ['Ks', 'Qd', '7c'], 'Kh'))[0]
joined = all_text(n)
check('turn shared = exact board property', 'at least one pair' in joined)
check('turn does NOT say "best five ... shared by every remaining player"',
      not ('best five is' in joined and 'shared by every remaining player' in joined))

print('[10] no enum names / no literal markdown control chars / safe escaping / no range-strategy directives')
samples = [split(hand('TM82%d' % i, hole, flop, turn, river=rv))[0]
           for i, (hole, flop, turn, rv) in enumerate([
               ('8h8d', ['Qs', '7d', '2c'], '7h', None), ('AhKh', ['Qh', '7h', '2c'], 'Th', None),
               ('3d2c', ['Ks', 'Kd', '7c'], '7h', '9s'), ('AsKd', ['9c', '8d', '7h'], '6s', '5c')])]
blob = ' '.join(n for grp in samples for n in grp)
check('no raw enum names', not re.search(r'high_card|two_pair|full_house|straight_flush', blob))
check('no literal markdown underscores around words', not re.search(r'_[A-Za-z][^_]*_', blob))
rendered = _md_inline(blob)
check('renders through _md_inline to escaped HTML', isinstance(rendered, str) and '<script' not in rendered.lower())
check('no range/equity/EV term in facts/notes', not re.search(r'\b(range|equity|fold equity|\bev\b|combos?)\b', blob, re.I))
check('no strategic directive', not re.search(r'\b(you should|must (?:bet|call|raise|fold)|i recommend|gto says)\b', blob, re.I))
check('strategic line is the compact insufficient-evidence label', 'Strategic read: insufficient evidence' in blob)

print('[11] no transition data enters the analyst packet')
import gem_analyst_packet as _ap
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gem_analyst_packet.py'), encoding='utf-8').read()
check('analyst packet does not import/reference gem_runout_transition', 'gem_runout_transition' not in src)

# ---------------------------------------------------------------------------------------------------------
print('\nRESULTS: %d passed, %d failed, %d total' % (_N[0] - _F[0], _F[0], _N[0]))
if _F[0]:
    print('RUNOUT WIRING TESTS FAILED')
    sys.exit(1)
print('ALL RUNOUT WIRING TESTS PASSED')
