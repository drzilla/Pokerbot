#!/usr/bin/env python3
"""Tests for gem_board_state.py — pinned board-fact assertions."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
PASS = 0; FAIL = 0
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')

from gem_board_state import board_state

# === TM6042997501: 5h Qs 8h Qd 4s (the motivating case) ===
print('=== TM6042997501: 5h Qs 8h Qd 4s ===')
bs = board_state(['5h', 'Qs', '8h', 'Qd', '4s'], hero_cards=['Kh', 'As'])

# Flop
check('flop flush_status=two-tone', bs['flop']['flush_status'] == 'two-tone')
check('flop paired=False', bs['flop']['paired'] == False)
check('flop hero_plays_board=False', bs['flop']['hero_plays_board'] == False)

# Turn: Qd pairs the board
check('turn flush_completed=False', bs['turn']['flush_completed_this_street'] == False)
check('turn paired=True', bs['turn']['paired'] == True)
check('turn pair_ranks=[Q]', bs['turn']['pair_ranks'] == ['Q'])
check('turn board_pair_outranks_hero=True', bs['turn']['board_pair_outranks_hero_pair'] == True)

# River: 4s — no flush
check('river flush_completed=False', bs['river']['flush_completed_this_street'] == False)
check('river flush_status=two-tone', bs['river']['flush_status'] == 'two-tone')
check('river hero_plays_board=False', bs['river']['hero_plays_board'] == False)

# === K-5-K-3-5 with 9d8d: Hero does NOT play the board (9 kicker > 3) ===
print('\n=== Kh 5h Ks 3d 5d with 9d8d ===')
bs2 = board_state(['Kh', '5h', 'Ks', '3d', '5d'], hero_cards=['9d', '8d'])

check('river paired=True', bs2['river']['paired'] == True)
check('river pair_ranks has K and 5', 'K' in bs2['river']['pair_ranks'] and '5' in bs2['river']['pair_ranks'])
# 9d8d improves the kicker (9 > board's 3), so hero does NOT play the board
check('river hero_plays_board=False (9 kicker)', bs2['river']['hero_plays_board'] == False)

# True hero-plays-board: 2d3d on Kh Ks Qh Qd Js (all board cards > hero cards)
print('\n=== Kh Ks Qh Qd Js with 2d3d (true plays-board) ===')
bs2b = board_state(['Kh', 'Ks', 'Qh', 'Qd', 'Js'], hero_cards=['2d', '3d'])
check('true plays-board', bs2b['river']['hero_plays_board'] == True)

# === 4-flush completing river: Ad 8s Ts 2d 9d ===
print('\n=== Ad 8s Ts 2d 9d ===')
bs3 = board_state(['Ad', '8s', 'Ts', '2d', '9d'])

check('flop flush_status=two-tone', bs3['flop']['flush_status'] == 'two-tone')
check('turn flush_status=two-tone', bs3['turn']['flush_status'] == 'two-tone')
check('river flush_status=3-flush', bs3['river']['flush_status'] == '3-flush')
check('river flush_completed=True', bs3['river']['flush_completed_this_street'] == True)

# === Monotone flop: Ah Kh Qh ===
print('\n=== Ah Kh Qh (monotone flop) ===')
bs4 = board_state(['Ah', 'Kh', 'Qh'])

check('flop flush_status=3-flush', bs4['flop']['flush_status'] == '3-flush')
check('flop one_card_flush=True', bs4['flop']['one_card_flush_possible'] == True)

# === Rainbow flop: As Kd Qc ===
print('\n=== As Kd Qc (rainbow) ===')
bs5 = board_state(['As', 'Kd', 'Qc'])

check('flop flush_status=rainbow', bs5['flop']['flush_status'] == 'rainbow')
check('flop paired=False', bs5['flop']['paired'] == False)

# === Straight on turn: 5 6 7 8 ===
print('\n=== 5h 6d 7s 8c (straight on turn) ===')
bs6 = board_state(['5h', '6d', '7s', '8c', '2h'])

check('turn straight_status=open_on_board', bs6['turn']['straight_status'] == 'open_on_board'
      or bs6['turn']['straight_status'] == 'completed_this_street')

# === Empty / short board ===
print('\n=== Edge cases ===')
check('empty board', board_state([]) == {})
check('2 cards', board_state(['Ah', 'Kd']) == {})
check('None board', board_state(None) == {})

# === No hero cards ===
print('\n=== No hero cards ===')
bs7 = board_state(['5h', 'Qs', '8h', 'Qd', '4s'])
check('no hero: hero_plays_board=None', bs7['turn']['hero_plays_board'] is None)
check('no hero: board_pair_outranks=None', bs7['turn']['board_pair_outranks_hero_pair'] is None)

# === JSON serializable ===
import json
try:
    json.dumps(bs)
    check('JSON serializable', True)
except Exception as e:
    check('JSON serializable', False, str(e)[:80])

print(f'\nRESULTS: {PASS} passed, {FAIL} failed')
if FAIL:
    sys.exit(1)
else:
    print('ALL BOARD STATE TESTS PASSED')
