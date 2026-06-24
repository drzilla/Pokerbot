"""Standalone: render Runout Transition player-facing examples -> v821_range/RENDERED_EXAMPLES.md."""
import os
import re
import gem_parser
import gem_runout_transition as RT

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v821_range')


def hh(hid, hole, flop, turn, river=None):
    L = ["Poker Hand #%s: Tournament #888888, RR Test Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01" % hid,
         "Table '1' 8-max Seat #1 is the button", "Seat 1: Hero (25000 in chips)",
         "Seat 2: V1 (25000 in chips)", "Seat 3: V2 (25000 in chips)",
         "V1: posts small blind 125", "V2: posts big blind 250", "*** HOLE CARDS ***",
         "Dealt to Hero [%s]" % hole, "Hero: raises 375 to 625", "V1: folds", "V2: calls 375",
         "*** FLOP *** [%s]" % ' '.join(flop), "V2: checks", "Hero: bets 400", "V2: calls 400",
         "*** TURN *** [%s] [%s]" % (' '.join(flop), turn)]
    if river:
        L += ["V2: checks", "Hero: bets 900", "V2: calls 900",
              "*** RIVER *** [%s] [%s]" % (' '.join(flop + [turn]), river),
              "V2: checks", "Hero: bets 1500", "V2: folds", "Uncalled bet (1500) returned to Hero"]
        board = flop + [turn, river]
    else:
        L += ["V2: checks", "Hero: bets 900", "V2: folds", "Uncalled bet (900) returned to Hero"]
        board = flop + [turn]
    L += ["Hero collected 2050 from pot", "*** SUMMARY ***", "Total pot 2050 | Rake 0",
          "Board [%s]" % ' '.join(board), "Seat 1: Hero (button) collected (2050)"]
    return gem_parser.parse_one_hand('\n'.join(L), 'GG - Test.txt')


def rec_for(h, street):
    for r in RT.transitions_for_hand(h):
        if r.get('street') == street and not r.get('unresolved'):
            return r
    return None


CASES = [
    ('Improved to flush (turn)', hh('TM99300001', 'Ah Kh', ['Qh', '7h', '2c'], 'Th'), 'turn'),
    ('Flush now possible, Hero not made (turn)', hh('TM99300002', 'As Kd', ['7h', '6h', '2c'], 'Th'), 'turn'),
    ('Board paired on the river, overpair holds (river)', hh('TM99300003', 'Kh Kd', ['Qh', '8d', '2c'], '5s', '8c'), 'river'),
    ('Blank turn, nothing changed', hh('TM99300004', 'Kh Qd', ['Ah', '7d', '2c'], '3s'), 'turn'),
    ('Straight threat on the board (turn)', hh('TM99300005', 'Ac Kc', ['9h', '8d', '7c'], '6s'), 'turn'),
]


def strip(html):
    return re.sub(r'\s+', ' ', re.sub('<[^>]*>', ' ', html)).strip()


lines = ['# V821 Runout Transition - rendered player-facing examples\n',
         'Rendered by `gem_runout_transition.render_html`. Deterministic, canonical facts only; the '
         'improve/weaken direction is computed in the module, not the renderer. Mobile-safe (no fixed pixel widths).\n']
for title, h, street in CASES:
    rec = rec_for(h, street)
    if rec is None:
        lines.append('\n## %s\n\n_(no resolved record for this fixture)_\n' % title)
        print('-', title, ':: (unresolved)')
        continue
    html = RT.render_html(rec)
    lines.append('\n## %s\n' % title)
    lines.append('- %s -> **%s** | status `%s` | tags `%s` | register `%s` | mobile-safe: %s\n'
                 % ('-'.join(rec['prev_board']), '-'.join(rec['resulting_board']), rec['hero_status'],
                    rec['transition_tags'], rec['register'], 'width:' not in html.replace('border', '')))
    lines.append('**Player-facing:**\n\n> %s\n' % strip(html))
    lines.append('**Desktop HTML:**\n\n```html\n%s\n```\n' % html)
    print('-', title, '::', strip(html)[:150])

open(os.path.join(OUT, 'RENDERED_EXAMPLES.md'), 'w', encoding='utf-8').write('\n'.join(lines))
print('wrote v821_range/RENDERED_EXAMPLES.md')
