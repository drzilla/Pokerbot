#!/usr/bin/env python3
"""Build SB defend ranges (3-bet + call + total) at 20BB, 35BB, 50BB."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from gem_ranges import load_ranges

r = load_ranges()
def S(key): return set(r.get(key, {}).keys())  # chart -> set of hand strings

RANKS = 'AKQJT98765432'
rv = {r: i for i, r in enumerate(RANKS)}

def hand_sort_key(h):
    if len(h) == 2: return (0, rv.get(h[0], 99))
    suit = 1 if h.endswith('s') else 2
    return (suit, rv.get(h[0], 99), rv.get(h[1], 99))

def fmt(hands):
    if not hands: return ''
    return ', '.join(sorted(hands, key=hand_sort_key))

def pct(n): return round(n / 169 * 100, 1)

opener_bb_def_pct = {'BTN': 45, 'CO': 35, 'HJ': 25}
lines = []

lines.append("")
lines.append("--- SB DEFEND RANGES (derived from 3BF/3BET + BB_DEF heuristic, Jun 2026) ---")
lines.append("# 3-bet portion: from GTOW ICM extraction (3BF/3BET charts).")
lines.append("# Call portion: derived — hands in BB defend range for this opener%,")
lines.append("#   filtered to suited/pairs/broadway-offsuit, minus the 3-bet hands.")
lines.append("#   SB flats tighter than BB (no discount, OOP to all).")
lines.append("# 20BB: jam-or-fold only (SPR too shallow for SB flat OOP).")
lines.append("# 35BB: 3-bet + selective flat. 50BB: polarized 3-bet + wider flat.")

# ============================================================
# 20BB: JAM OR FOLD
# ============================================================
lines.append("")
lines.append("# --- SB Defend 20BB (jam or fold, no flatting) ---")
data_20 = {
    'BTN': S('3BET_20BB_SBvsBTN'),
    'CO': S('3BET_20BB_SBvsCO'),
    'HJ': S('3BF_30BB_SBvsHJ'),  # no 20BB SB vs HJ chart; 30BB proxy
}
for opener in ['BTN', 'CO', 'HJ']:
    threeb = data_20[opener]
    lines.append(f"SB_DEF_20BB_vs{opener}_3BET: {fmt(threeb)} [{pct(len(threeb))}%]")
    lines.append(f"SB_DEF_20BB_vs{opener}: {fmt(threeb)} [{pct(len(threeb))}%]")

# ============================================================
# 35BB: 3-BET + FLAT
# ============================================================
lines.append("")
lines.append("# --- SB Defend 35BB (3-bet + selective flat) ---")
for opener in ['BTN', 'CO', 'HJ']:
    threeb = S(f'3BF_30BB_SBvs{opener}')
    bb_def = S(f'BB_DEF_vs{opener_bb_def_pct[opener]}pct')

    call = set()
    for h in bb_def:
        if h in threeb:
            continue
        is_pair = len(h) == 2
        is_suited = h.endswith('s') if len(h) == 3 else False
        is_bway_o = (h.endswith('o') and len(h) == 3
                     and rv.get(h[0], 99) <= 3    # J+ high card
                     and rv.get(h[1], 99) <= 6)    # 8+ second card
        if is_pair or is_suited or is_bway_o:
            call.add(h)

    total = threeb | call
    lines.append(f"SB_DEF_35BB_vs{opener}_3BET: {fmt(threeb)} [{pct(len(threeb))}%]")
    lines.append(f"SB_DEF_35BB_vs{opener}_CALL: {fmt(call)} [{pct(len(call))}%]")
    lines.append(f"SB_DEF_35BB_vs{opener}: {fmt(total)} [{pct(len(total))}%]")

# ============================================================
# 50BB: POLARIZED 3-BET + WIDER FLAT
# ============================================================
lines.append("")
lines.append("# --- SB Defend 50BB (polarized 3-bet + wider flat) ---")
for opener in ['BTN', 'CO', 'HJ']:
    threeb = S(f'3BF_50BB_SBvs{opener}')
    bb_def = S(f'BB_DEF_vs{opener_bb_def_pct[opener]}pct')

    call = set()
    for h in bb_def:
        if h in threeb:
            continue
        is_pair = len(h) == 2
        is_suited = h.endswith('s') if len(h) == 3 else False
        is_bway_o = (h.endswith('o') and len(h) == 3
                     and rv.get(h[0], 99) <= 4    # T+ high card
                     and rv.get(h[1], 99) <= 7)    # 7+ second card
        if is_pair or is_suited or is_bway_o:
            call.add(h)

    total = threeb | call
    lines.append(f"SB_DEF_50BB_vs{opener}_3BET: {fmt(threeb)} [{pct(len(threeb))}%]")
    lines.append(f"SB_DEF_50BB_vs{opener}_CALL: {fmt(call)} [{pct(len(call))}%]")
    lines.append(f"SB_DEF_50BB_vs{opener}: {fmt(total)} [{pct(len(total))}%]")

# ============================================================
# PRINT SUMMARY
# ============================================================
print("=== SB DEFEND RANGES ===\n")
for line in lines:
    if line.startswith('SB_DEF'):
        name = line.split(':')[0]
        body = line.split(':', 1)[1].strip() if ':' in line else ''
        n = len([h for h in body.split('[')[0].split(',') if h.strip()]) if body else 0
        pval = body.split('[')[1].split('%')[0] if '[' in body else '0'
        print(f"  {name}: {n} hands ({pval}%)")
    elif line.startswith('#'):
        print(line)

# Write full output
output = '\n'.join(lines)
print(f"\n=== FULL OUTPUT ===\n")
print(output)
