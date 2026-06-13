#!/usr/bin/env python3
"""Regression test: Hero-identity mismatch between analyzer display name and parsed name.

Tests that all detectors correctly resolve the per-hand hero name and:
1. Never emit evidence atoms attributed to Hero
2. Correctly compute hero_involved=False when Hero folded preflop
3. Work when analyzer passes display name ("Knockman") but parser uses "Hero"
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
PASS = 0; FAIL = 0
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')

from gem_villain_intel import (build_villain_intel, extract_evidence_atoms,
    detect_exploit_opportunities, build_villain_keys, assign_aliases,
    _resolve_hero, _hero_active_at)

# === Synthetic test hands ===
# Hero = "Hero" in parser, but analyzer will pass "Knockman"
HERO_PARSER_NAME = "Hero"
HERO_DISPLAY_NAME = "Knockman"

# Hand 1: Hero folds preflop, villain limps (evidence after Hero fold)
hand1 = {
    'id': 'REG_H1', 'tournament_id': 'T_REG', 'hero': HERO_PARSER_NAME,
    'position': 'UTG', 'cards': ['2h', '3d'], 'vpip': False,
    'villains': {
        'villain_abc': {'position': 'CO', 'stack_bb': 50},
        'villain_def': {'position': 'BB', 'stack_bb': 30},
    },
    'primary_villain': {'name': 'villain_abc', 'role': 'opener'},
    'action_ledger': [
        {'street': 'preflop', 'action': 'posts', 'player': 'villain_def', 'position': 'BB', 'amount_bb': 1.0},
        {'street': 'preflop', 'action': 'folds', 'player': HERO_PARSER_NAME, 'position': 'UTG', 'amount_bb': 0},
        {'street': 'preflop', 'action': 'calls', 'player': 'villain_abc', 'position': 'CO', 'amount_bb': 1.0},
        {'street': 'preflop', 'action': 'checks', 'player': 'villain_def', 'position': 'BB', 'amount_bb': 0},
        {'street': 'flop', 'action': 'checks', 'player': 'villain_def', 'position': 'BB', 'amount_bb': 0},
        {'street': 'flop', 'action': 'bets', 'player': 'villain_abc', 'position': 'CO', 'amount_bb': 2.0},
    ],
    'went_to_sd': False, 'net_bb': -0.1,
    'hero_street_actions': {},
    'pf_raise_count': 0,
    'stacks_behind': {},
}

# Hand 2: Hero plays and villain limps (evidence with Hero active)
hand2 = {
    'id': 'REG_H2', 'tournament_id': 'T_REG', 'hero': HERO_PARSER_NAME,
    'position': 'BTN', 'cards': ['Ah', 'Kd'], 'vpip': True,
    'villains': {
        'villain_abc': {'position': 'MP', 'stack_bb': 48},
        'villain_def': {'position': 'BB', 'stack_bb': 29},
    },
    'primary_villain': {'name': 'villain_abc', 'role': 'opener'},
    'action_ledger': [
        {'street': 'preflop', 'action': 'posts', 'player': 'villain_def', 'position': 'BB', 'amount_bb': 1.0},
        {'street': 'preflop', 'action': 'calls', 'player': 'villain_abc', 'position': 'MP', 'amount_bb': 1.0},
        {'street': 'preflop', 'action': 'raises', 'player': HERO_PARSER_NAME, 'position': 'BTN', 'amount_bb': 3.5},
        {'street': 'preflop', 'action': 'folds', 'player': 'villain_def', 'position': 'BB', 'amount_bb': 0},
        {'street': 'preflop', 'action': 'calls', 'player': 'villain_abc', 'position': 'MP', 'amount_bb': 3.5},
    ],
    'went_to_sd': False, 'net_bb': 2.0,
    'hero_street_actions': {'preflop': 'raise'},
    'pf_raise_count': 1,
    'stacks_behind': {},
}

hands = [hand1, hand2]

# === 1. _resolve_hero ===
print('=== 1. _resolve_hero ===')
check('resolve uses hand.hero', _resolve_hero(hand1, HERO_DISPLAY_NAME) == HERO_PARSER_NAME)
check('resolve fallback', _resolve_hero({}, HERO_DISPLAY_NAME) == HERO_DISPLAY_NAME)
check('resolve empty hero', _resolve_hero({'hero': ''}, HERO_DISPLAY_NAME) == HERO_DISPLAY_NAME)

# === 2. _hero_active_at with resolved name ===
print('\n=== 2. _hero_active_at ===')
al1 = hand1['action_ledger']
# Hero folded preflop — should NOT be active at flop
check('Hero folded PF: not active at flop',
      not _hero_active_at(al1, HERO_PARSER_NAME, 'flop', 4))
# With wrong name ("Knockman") — would incorrectly return True
check('Wrong name would miss fold',
      _hero_active_at(al1, HERO_DISPLAY_NAME, 'flop', 4) == True)
# With resolved name — correct
resolved = _resolve_hero(hand1, HERO_DISPLAY_NAME)
check('Resolved name catches fold',
      not _hero_active_at(al1, resolved, 'flop', 4))

# === 3. build_villain_intel with display name ===
print('\n=== 3. build_villain_intel invariants ===')
intel = build_villain_intel(hands, HERO_DISPLAY_NAME, profiles={})
atoms = intel['evidence_atoms']
aliases = intel['villain_aliases']

# 3a. Hero must never appear as villain key
hero_vk = [vk for vk in aliases if HERO_PARSER_NAME in vk]
check('no Hero villain_key in aliases', len(hero_vk) == 0, str(hero_vk))

# 3b. No atom attributed to Hero
hero_atoms = [a for a in atoms if HERO_PARSER_NAME in a.get('villain_key', '')]
check('no Hero-as-villain atoms', len(hero_atoms) == 0, str(len(hero_atoms)))

# 3c. hero_involved=False for hand1 atoms (Hero folded preflop)
h1_atoms = [a for a in atoms if a['hand_id'] == 'REG_H1']
for a in h1_atoms:
    check(f'H1 atom hero_involved=False ({a["signal"]})', a['hero_involved'] == False)

# 3d. hero_involved=True for hand2 atoms (Hero active)
h2_atoms = [a for a in atoms if a['hand_id'] == 'REG_H2']
for a in h2_atoms:
    check(f'H2 atom hero_involved=True ({a["signal"]})', a['hero_involved'] == True)

# 3e. Top villains by evidence should not contain Hero
atom_vks = set(a['villain_key'] for a in atoms)
for vk in atom_vks:
    check(f'villain_key {vk} is not Hero', HERO_PARSER_NAME not in vk)

# === 4. All detectors produce correct hero_involved ===
print('\n=== 4. Per-detector hero_involved check ===')
# Run on real data if available
if os.path.exists('_session_live_test'):
    import re
    from gem_parser import parse_one_hand
    from gem_opponent_profiler import profile_opponents, tag_hands_with_archetypes

    real_hands = []
    for fn in os.listdir('_session_live_test'):
        if not fn.endswith('.txt'): continue
        with open(os.path.join('_session_live_test', fn), encoding='utf-8') as f:
            raw = f.read()
        for b in re.split(r'\n\n\n+', raw.strip()):
            b = b.strip()
            if not b or 'Poker Hand' not in b: continue
            h = parse_one_hand(b, filename=fn)
            if h: real_hands.append(h)

    real_profiles = profile_opponents(real_hands, hero_name=HERO_DISPLAY_NAME)
    tag_hands_with_archetypes(real_hands, real_profiles)
    real_intel = build_villain_intel(real_hands, HERO_DISPLAY_NAME, real_profiles)
    real_atoms = real_intel['evidence_atoms']
    real_aliases = real_intel['villain_aliases']

    # 4a. No Hero atoms in real data
    hero_names = set(h.get('hero', '') for h in real_hands if h.get('hero'))
    hero_real_atoms = [a for a in real_atoms
                       if any(hn in a.get('villain_key', '') for hn in hero_names)]
    check(f'real data: 0 Hero-as-villain atoms', len(hero_real_atoms) == 0,
          str(len(hero_real_atoms)))

    # 4b. hero_involved=false exists in real data
    hero_f = sum(1 for a in real_atoms if not a['hero_involved'])
    check(f'real data: hero_involved=false > 0 ({hero_f})', hero_f > 0)

    # 4c. Hero not in aliases
    hero_aliases = [vk for vk in real_aliases if any(hn in vk for hn in hero_names)]
    check(f'real data: Hero not in aliases', len(hero_aliases) == 0)

    # 4d. Hero not in top-5 evidence villains
    from collections import Counter
    atom_counts = Counter(a['villain_key'] for a in real_atoms)
    top5 = atom_counts.most_common(5)
    hero_in_top5 = [vk for vk, _ in top5 if any(hn in vk for hn in hero_names)]
    check(f'real data: Hero not in top-5 evidence', len(hero_in_top5) == 0)

    print(f'\n  Real data: {len(real_atoms)} atoms, {hero_f} hero_involved=false, '
          f'{len(hero_real_atoms)} Hero-as-villain')
else:
    print('  (skipping real data test — _session_live_test not found)')

# === 5. Calibrated thresholds preserved ===
print('\n=== 5. Calibrated thresholds ===')
with open('gem_villain_intel.py', encoding='utf-8') as f:
    src = f.read()
check('steal requires first-in check', 'not first-in' in src or "a['action'] in ('raises', 'bets', 'calls')" in src)
check('pivot BB/SB check-raise only', "a == 'raises'" in src and 'is_blind' in src)
check('overfold threshold = 6', 'streak_len >= 6' in src)
check('cold-call excludes original raiser', 'original_raiser' in src)
check('donk requires OOP to PFR', '_pfr_pos_n' in src or 'OOP' in src.lower())
check('read scoring diversified', "dims['tight'] >= 6" in src or "dims['sticky'] >= 8" in src)

# === SUMMARY ===
print(f'\n{"=" * 60}')
print(f'RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('REGRESSION DETECTED — FIX BEFORE RELEASE')
    sys.exit(1)
else:
    print('ALL HERO-IDENTITY REGRESSION TESTS PASSED')
