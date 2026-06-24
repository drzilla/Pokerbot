"""Render Runout Transition player-facing examples through the REAL report note renderer
(gem_report_draft._html._md_inline) -> v821_range/RENDERED_EXAMPLES.md. No separate mini-renderer."""
import os
import re
import gem_parser
import gem_runout_transition as RT
from gem_report_draft._html import _md_inline

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v821_range')


def hh(hid, hole, flop, turn, river=None):
    hole = hole if ' ' in hole else hole[:2] + ' ' + hole[2:]
    L = ["Poker Hand #%s: Tournament #888: RR Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01" % hid,
         "Table '1' 8-max Seat #1 is the button", "Seat 1: Hero (25000 in chips)", "Seat 2: V1 (25000 in chips)",
         "Hero: posts small blind 125", "V1: posts big blind 250", "*** HOLE CARDS ***",
         "Dealt to Hero [%s]" % hole, "Hero: raises 375 to 625", "V1: calls 375",
         "*** FLOP *** [%s]" % ' '.join(flop), "V1: checks", "Hero: bets 400", "V1: calls 400",
         "*** TURN *** [%s] [%s]" % (' '.join(flop), turn)]
    board = flop + [turn]
    if river:
        L += ["V1: checks", "Hero: bets 900", "V1: calls 900",
              "*** RIVER *** [%s] [%s]" % (' '.join(board), river), "V1: checks", "Hero: bets 1500",
              "V1: folds", "Uncalled bet (1500) returned to Hero"]
        board = board + [river]
    else:
        L += ["V1: checks", "Hero: bets 900", "V1: folds", "Uncalled bet (900) returned to Hero"]
    L += ['*** SUMMARY ***', 'Total pot 3000 | Rake 0', 'Board [%s]' % ' '.join(board), 'Seat 1: Hero collected (3000)']
    return gem_parser.parse_one_hand('\n'.join(L), 'GG - Test.txt')


def rec_for(h, street):
    for r in RT.transitions_for_hand(h):
        if r.get('street') == street and not r.get('unresolved'):
            return r
    return None


CASES = [
    ('Hero completes a flush with hole cards (turn)', hh('TM99300001', 'AhKh', ['Qh', '7h', '2c'], 'Th'), 'turn'),
    ('Shared board change — board pairs, no Hero improvement (turn)', hh('TM99300002', '9h2d', ['Ks', 'Qd', '7c'], 'Kh'), 'turn'),
    ('Hero private improvement — pocket pair, board pairs low card (turn)', hh('TM99300003', '8h8d', ['Qs', '7d', '2c'], '7h'), 'turn'),
    ('Three suited — a flush is possible for two-of-suit holdings (turn)', hh('TM99300004', 'AsKd', ['7h', '6h', '2c'], 'Th'), 'turn'),
    ('Four suited — one-of-suit holdings make a flush (turn)', hh('TM99300010', 'AsKd', ['7h', '6h', '2h'], 'Th'), 'turn'),
    ('Five suited — flush on the board, shared (river)', hh('TM99300011', 'AsKd', ['7h', '6h', '2h'], 'Th', river='Qh'), 'river'),
    ('Straight present on the board, shared (river)', hh('TM99300012', 'AsKd', ['9c', '8d', '7h'], '6s', river='5c'), 'river'),
    ('Blank — nothing meaningful changed (turn)', hh('TM99300005', 'TcTd', ['Ks', '9d', '2c'], '5h'), 'turn'),
    ('Board four-to-a-straight via the wheel (turn)', hh('TM99300006', 'KdQc', ['As', '2d', '3c'], '4h'), 'turn'),
    ('Board-only two pair on the river (no Hero contribution)', hh('TM99300007', '3d2c', ['Ks', 'Kd', '7c'], '7h', river='9s'), 'river'),
]


def strip(html):
    return re.sub(r'\s+', ' ', re.sub('<[^>]*>', ' ', html)).strip()


lines = ['# V821 Runout Transition — rendered player-facing examples',
         '',
         'Each block is the Markdown note from `gem_runout_transition.transition_note_text(rec)` rendered '
         'through the **real** report note renderer `gem_report_draft._html._md_inline` (the same pipeline the '
         'hand-detail per-street commentary uses — no separate inline-style mini-renderer). Deterministic, '
         'canonical facts only; the contribution direction is computed in the module. Inline markdown only '
         '(no fixed pixel widths), so it reflows on desktop and mobile.', '']
for title, h, street in CASES:
    rec = rec_for(h, street)
    if rec is None:
        lines.append('\n## %s\n\n_(no resolved record for this fixture)_' % title)
        print('-', title, ':: (unresolved)')
        continue
    note = RT.transition_note_text(rec)
    html = _md_inline(note)
    lines.append('\n## %s' % title)
    lines.append('- %s → **%s** | category `%s → %s` | hole-cards contribute: `%s` | tags `%s`'
                 % ('-'.join(rec['prev_board']), '-'.join(rec['resulting_board']),
                    rec['best_five_category_before'], rec['best_five_category_after'],
                    rec['hero_hole_cards_contribute_after'], rec['transition_tags']))
    lines.append('\n**Player-facing (rendered):**\n\n> %s' % strip(html))
    lines.append('\n**HTML (via the real renderer `_md_inline`):**\n\n```html\n%s\n```' % html)
    print('-', title, '::', strip(html)[:140])

open(os.path.join(OUT, 'RENDERED_EXAMPLES.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print('wrote v821_range/RENDERED_EXAMPLES.md')
