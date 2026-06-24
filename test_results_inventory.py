#!/usr/bin/env python3
"""R1 invariant: the canonical Tournament Results owner (gem_tournament_model) must surface EVERY
HH-backed canonical event EXACTLY ONCE, each contributing its known committed cost + bullets, with an
HH-only (no-game-summary) event carried as UNRESOLVED (blank Return/Net/ROI, cost still counted).

Run: PYTHONUTF8=1 python test_results_inventory.py    (exit 0 iff all pass)
"""
import json
import os
import gem_tournament_model as TM

_P = _F = 0


def check(name, cond):
    global _P, _F
    if cond:
        _P += 1
    else:
        _F += 1
        print('  FAIL:', name)


def _rd(per_t, totals):
    return {'platform': 'GG', 'usd_overlay': {
        'status': 'parsed', 'per_tournament': per_t, 'totals': totals, 'hh_intersect_totals': totals}}


# ── §1 synthetic invariant: 2 resolved + 1 unresolved HH-only event ──────────────────────────────
PER_T = [
    {'tid': 'A', 'name': 'Daily 25', 'start_date': '2026-06-24', 'buyin': 25, 'bullets': 1, 'cost': 25.0,
     'cash_received': 100.0, 'ticket_value': 0.0, 'cash_total': 100.0, 'net': 75.0,
     'place': 3, 'total_players': 100, 'is_sat': False, 'itm': True, 'advanced': False},
    {'tid': 'B', 'name': 'Bounty Special 50', 'start_date': '2026-06-24', 'buyin': 50, 'bullets': 2, 'cost': 100.0,
     'cash_received': 0.0, 'ticket_value': 0.0, 'cash_total': 0.0, 'net': -100.0,
     'place': 400, 'total_players': 500, 'is_sat': False, 'itm': False, 'advanced': False},
    {'tid': 'C', 'name': 'Mini Big Game 10.80', 'start_date': '2026-06-24', 'buyin': 10.8, 'bullets': 1,
     'cost': 10.8, 'cash_received': None, 'ticket_value': None, 'cash_total': None, 'net': None,
     'place': 0, 'total_players': 0, 'is_sat': False, 'itm': False, 'advanced': False, 'unresolved': True},
]
TOT = {'n_tournaments': 3, 'n_bullets': 4, 'total_cost': 135.8, 'total_cash': 100.0, 'total_net': -25.8,
       'roi_pct': -19.0, 'resolved_events': 2, 'total_events': 3, 'unresolved_events': 1,
       'coverage_partial': True}
m = TM.build_tournament_model(_rd(PER_T, TOT))
ev = m['events']
ids = [e['tournament_id'] for e in ev]
check('every HH-backed event present exactly once', sorted(ids) == ['A', 'B', 'C'] and len(ids) == len(set(ids)))
check('committed cost sum includes the unresolved event', round(sum(e['cost'] for e in ev), 2) == 135.8)
check('bullets sum includes the unresolved event', sum(e['bullets'] for e in ev) == 4)
unres = [e for e in ev if e['return'].get('value') is None]
check('exactly one unresolved event', len(unres) == 1)
check('unresolved Return/Net/ROI are blank (None), not $0', unres[0]['net'] is None and unres[0]['roi_pct'] is None)
check('unresolved event still carries its committed cost', unres[0]['cost'] == 10.8)
check('resolved event keeps its real net (not blanked)', any(e['tournament_id'] == 'A' and e['net'] == 75.0 for e in ev))
check('totals are coverage-partial (2 of 3)', m['totals']['coverage_partial']
      and m['totals']['resolved_events'] == 2 and m['totals']['total_events'] == 3)

# ── §2 real-session invariant (skipped if the cache is absent): the model events == the HH tids ──
_RD = r'C:/home/claude/gem_report_data_Knockman.json'
_HANDS = r'C:/home/claude/gem_hands_Knockman_input.json'
if os.path.isfile(_RD) and os.path.isfile(_HANDS):
    rd = json.load(open(_RD, encoding='utf-8'))
    hands = json.load(open(_HANDS, encoding='utf-8'))
    hh_tids = {str(h.get('tournament_id')) for h in hands if isinstance(h, dict) and h.get('tournament_id')}
    model = TM.build_tournament_model(rd)
    ev_tids = [str(e['tournament_id']) for e in model['events']]
    check('real: every HH tournament id is an event exactly once',
          set(ev_tids) == hh_tids and len(ev_tids) == len(set(ev_tids)))
    check('real: event count equals HH tournament count', len(ev_tids) == len(hh_tids))

print('RESULTS: %d passed, %d failed' % (_P, _F))
if _F:
    raise SystemExit(1)
print('ALL INVARIANTS PASSED')
