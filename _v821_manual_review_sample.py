"""Collect >=30 REAL rendered Runout Transition examples covering every required type, for the manual-review
ledger. Writes v821_range/MANUAL_REVIEW_SAMPLE.json. Real-session only (3BP exists in the corpus); each entry
carries hand id, street, type, rendered note text, and the objective fields needed to verify correctness."""
import json
import os
import gem_parser
import gem_runout_transition as RT

SESSIONS = [r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_live_test',
            r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\hh_today',
            r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_20260527']
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v821_range')


def classify(r):
    """Assign a real transition to one or more required review categories."""
    cats = []
    t = r['transition_tags']
    if r['draw_completed'] and 'flush' in (r['best_five_category_after'] or ''):
        cats.append('flush_draw_completed')
    if r['draw_completed'] and 'straight' in (r['best_five_category_after'] or ''):
        cats.append('straight_completed_hole_cards')
    if r['category_changed'] and r['hero_hole_cards_contribute_after']:
        cats.append('hero_private_contribution')
    if r['category_changed'] and not r['hero_hole_cards_contribute_after'] and 'board_paired' in t:
        cats.append('shared_board_pair_change')
    if 'flush_card' in t and 'flush' not in (r['best_five_category_after'] or ''):
        cats.append('flush_card_no_hero_flush')
    if 'four_flush' in t:
        cats.append('four_flush_board')
    if 'monotone_complete' in t:
        cats.append('five_suited_board')
    if 'connectivity_increase' in t and 'four_to_a_straight' not in t and 'straight_on_board' not in t:
        cats.append('connectivity_increase')
    if 'four_to_a_straight' in t and 'straight_on_board' not in t:
        cats.append('four_to_a_straight')
    if 'straight_on_board' in t:
        cats.append('straight_on_board')
    if 'A' in [c[0] for c in r['resulting_board']] and any(c[0] in '2345' for c in r['resulting_board']) \
            and ('four_to_a_straight' in t or 'straight_on_board' in t or 'connectivity_increase' in t):
        cats.append('wheel_structure')
    if 'blank' in t:
        cats.append('blank')
    if r['real_draw_missed']:
        cats.append('missed_real_draw')
    if r['multiway']:
        cats.append('multiway')
    if r['street'] == 'river':
        cats.append('river')
    if r['pot_type'] == '3BP':
        cats.append('threebet_pot')
    return cats


def main():
    by_cat = {}
    unresolved = []
    n_hands = 0
    for p in SESSIONS:
        if not os.path.isdir(p):
            continue
        hh, *_ = gem_parser.parse_session(p)
        for h in hh:
            n_hands += 1
            for r in RT.transitions_for_hand(h):
                if r.get('unresolved'):
                    if len(unresolved) < 4:
                        unresolved.append({'category': 'unresolved_suppressed', 'hand': h.get('id'),
                                           'street': r.get('street'), 'reason': r.get('unresolved_reason'),
                                           'rendered': RT.transition_note_text(r)})
                    continue
                note = RT.transition_note_text(r)
                entry = {'hand': h.get('id'), 'street': r['street'], 'pot_type': r['pot_type'],
                         'board': '-'.join(r['resulting_board']),
                         'category_before': r['best_five_category_before'], 'category_after': r['best_five_category_after'],
                         'category_changed': r['category_changed'],
                         'hole_cards_contribute_after': r['hero_hole_cards_contribute_after'],
                         'board_only_or_shared': r['board_only_or_shared_category'],
                         'tags': r['transition_tags'], 'rendered': note}
                for c in classify(r):
                    by_cat.setdefault(c, [])
                    if len(by_cat[c]) < 3:
                        by_cat[c].append(entry)

    # assemble the review ledger: every required category + the unresolved cases
    required = ['shared_board_pair_change', 'hero_private_contribution', 'flush_draw_completed',
                'flush_card_no_hero_flush', 'four_flush_board', 'five_suited_board', 'connectivity_increase',
                'four_to_a_straight', 'straight_on_board', 'wheel_structure', 'blank', 'missed_real_draw',
                'multiway', 'river', 'threebet_pot']
    ledger = []
    seen = set()
    for cat in required:
        items = by_cat.get(cat, [])
        for it in items[:3]:
            key = (cat, it['hand'], it['street'])
            if key in seen:
                continue
            seen.add(key)
            ledger.append({'category': cat, **it})
    # five_suited_board (monotone river) does not occur in the approved corpus -> ONE clearly-labelled
    # deterministic fixture (NOT real-session evidence) so the rendering of that wording path is reviewed.
    if not by_cat.get('five_suited_board'):
        _fx = ("Poker Hand #TM99500001: Tournament #888: RR Hold'em No Limit - Level5(125/250(0)) - "
               "2026/04/07 00:00:01\nTable '1' 8-max Seat #1 is the button\nSeat 1: Hero (25000 in chips)\n"
               "Seat 2: V1 (25000 in chips)\nHero: posts small blind 125\nV1: posts big blind 250\n"
               "*** HOLE CARDS ***\nDealt to Hero [As Kd]\nHero: raises 375 to 625\nV1: calls 375\n"
               "*** FLOP *** [7h 6h 2h]\nV1: checks\nHero: bets 400\nV1: calls 400\n"
               "*** TURN *** [7h 6h 2h] [Th]\nV1: checks\nHero: bets 900\nV1: calls 900\n"
               "*** RIVER *** [7h 6h 2h Th] [Qh]\nV1: checks\nHero: bets 1500\nV1: folds\n"
               "Uncalled bet (1500) returned to Hero\n*** SUMMARY ***\nTotal pot 3000 | Rake 0\n"
               "Board [7h 6h 2h Th Qh]\nSeat 1: Hero collected (3000)")
        _fh = gem_parser.parse_one_hand(_fx, 'GG - Fixture.txt')
        _fr = next((r for r in RT.transitions_for_hand(_fh) if r.get('street') == 'river' and not r.get('unresolved')), None)
        if _fr:
            ledger.append({'category': 'five_suited_board', 'evidence': 'DETERMINISTIC FIXTURE (not real-session)',
                           'hand': 'TM99500001 (FIXTURE)', 'street': 'river', 'pot_type': _fr['pot_type'],
                           'board': '-'.join(_fr['resulting_board']), 'category_before': _fr['best_five_category_before'],
                           'category_after': _fr['best_five_category_after'], 'tags': _fr['transition_tags'],
                           'rendered': RT.transition_note_text(_fr)})
            by_cat['five_suited_board'] = ['fixture']

    for u in unresolved:
        ledger.append(u)

    missing = [c for c in required if not by_cat.get(c)]
    out = {'corpus_hands': n_hands, 'total_review_items': len(ledger),
           'categories_present': sorted(by_cat.keys()), 'required_categories_missing': missing,
           'ledger': ledger}
    json.dump(out, open(os.path.join(OUT, 'MANUAL_REVIEW_SAMPLE.json'), 'w', encoding='utf-8'), indent=2)
    print('corpus hands:', n_hands, '| review items:', len(ledger))
    print('categories present:', sorted(by_cat.keys()))
    print('required categories MISSING (need fixtures):', missing)
    for e in ledger:
        print('  [%s] %s %s :: %s' % (e['category'], e.get('hand'), e.get('street'), (e.get('rendered') or e.get('reason'))[:110]))


if __name__ == '__main__':
    main()
