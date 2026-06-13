#!/usr/bin/env python3
"""Unit tests for gem_phase.py primitives."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from gem_phase import (monotonic_smooth, robust_avg_stack, sustained_short_handed,
                       balancing_or_sitout_artifact, icm_pressure, snap_to_standard,
                       _derive_legacy)

PASS = 0; FAIL = 0
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')

# ============================================================
print('=== monotonic_smooth ===')
# Empty
check('empty input', monotonic_smooth([], 1, 100, 5) == [])
# Single element
check('single element', monotonic_smooth([50], 1, 100, 5) == [5])
# Clamping
check('clamp low', monotonic_smooth([0], 1, 100, 1) == [1])
check('clamp high', monotonic_smooth([200], 1, 100, 100) == [100])
# Non-increasing on noisy input
r = monotonic_smooth([100, 90, 95, 80, 85, 70], 10, 100, 10)
check('non-increasing', all(r[i] >= r[i+1] for i in range(len(r)-1)))
check('terminal anchor', r[-1] == 10)
# Deterministic
r2 = monotonic_smooth([100, 90, 95, 80, 85, 70], 10, 100, 10)
check('deterministic', r == r2)

# ============================================================
print('=== robust_avg_stack ===')
def fake_stacks(h):
    return h.get('stacks', [])

# Small sample (< 5) uses median of current hand
h_small = {'stacks': [1000, 2000, 3000]}
check('small sample uses median', robust_avg_stack(h_small, [], fake_stacks) == 2000)

# Normal sample with outliers
hands = [{'stacks': [s]} for s in [1000]*10 + [100000]]  # one huge outlier
avg = robust_avg_stack(hands[0], hands, fake_stacks)
check('outlier trimmed', 500 < avg < 5000, f'got {avg}')

# ============================================================
print('=== sustained_short_handed ===')
ring = 8
# Not enough consecutive short hands
short_run = [{'n_players': 5}] * 10 + [{'n_players': 8}] + [{'n_players': 5}] * 5
check('not sustained (broken run)', not sustained_short_handed(short_run, ring))
# Enough consecutive
long_run = [{'n_players': 5}] * 20
check('sustained (20 consecutive)', sustained_short_handed(long_run, ring))
# Full tables
full = [{'n_players': 8}] * 30
check('full tables not short', not sustained_short_handed(full, ring))

# ============================================================
print('=== balancing_or_sitout_artifact ===')
check('no signal => False', not balancing_or_sitout_artifact({}))
check('unreliable flag => True', balancing_or_sitout_artifact({'seat_count_unreliable': True}))
check('balancing flag => True', balancing_or_sitout_artifact({'table_balancing_flag': True}))

# ============================================================
print('=== icm_pressure ===')
# HU always 0
check('HU => 0', icm_pressure('in_money', 0.01, 0.15, 'hu') == 0.0)
# Final table >= 0.85
p_ft = icm_pressure('in_money', 0.05, 0.15, 'final_table')
check(f'FT >= 0.85 (got {p_ft})', p_ft >= 0.85)
# Normal table, safely ITM <= 0.35
p_safe = icm_pressure('in_money', 0.05, 0.15, 'normal')
check(f'safe ITM normal <= 0.35 (got {p_safe})', p_safe <= 0.35)
# Near bubble, high pressure
p_bubble = icm_pressure('bubble_zone', 0.16, 0.15, 'normal')
check(f'bubble >= 0.7 (got {p_bubble})', p_bubble >= 0.7)
# Range [0, 1]
for ms in ['pre_money', 'bubble_zone', 'in_money']:
    for ts in ['normal', 'final_table', 'hu']:
        p = icm_pressure(ms, 0.2, 0.15, ts)
        check(f'range [{ms},{ts}]', 0 <= p <= 1, f'got {p}')

# ============================================================
print('=== snap_to_standard ===')
check('snap 9800 => 10000', snap_to_standard(9800) == 10000)
check('snap 26000 => 25000', snap_to_standard(26000) == 25000)
check('snap 0 => None', snap_to_standard(0) is None)
check('snap None => None', snap_to_standard(None) is None)

# ============================================================
print('=== _derive_legacy ===')
check('hu => ft_zone', _derive_legacy('hu', 'in_money', 'post_reg') == 'ft_zone')
check('ft => ft_zone', _derive_legacy('final_table', 'in_money', 'post_reg') == 'ft_zone')
check('itm => post_bubble', _derive_legacy('normal', 'in_money', 'post_reg') == 'post_bubble')
check('bubble => bubble_zone', _derive_legacy('normal', 'bubble_zone', 'post_reg') == 'bubble_zone')
check('reg => late_reg', _derive_legacy('normal', 'pre_money', 'reg_open') == 'late_reg')
check('post_reg', _derive_legacy('normal', 'pre_money', 'post_reg') == 'post_reg')

# ============================================================
print(f'\n{"="*60}')
print(f'RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    sys.exit(1)
else:
    print('ALL PRIMITIVE TESTS PASSED')
