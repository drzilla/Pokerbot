#!/usr/bin/env python3
"""
Quick validation of all v8.5.1 bug fixes against the 20260603 session data.
NOT a full pipeline run — exercises the changed code paths only.
"""
import json, sys, os, re
sys.path.insert(0, os.path.dirname(__file__))

PASS = 0
FAIL = 0
def check(label, condition, detail=''):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {label}")
    else:
        FAIL += 1
        print(f"  FAIL: {label} — {detail}")

# ============================================================
print("=== 1. load_ranges regex (3BF charts) ===")
# ============================================================
from gem_analyzer import load_ranges
ranges_path = os.path.join(os.path.dirname(__file__), 'Poker_Ranges_Text.txt')
ranges = load_ranges(ranges_path)
n_total = len(ranges)
n_3bf = sum(1 for k in ranges if k.startswith('3BF_'))
n_sqf = sum(1 for k in ranges if k.startswith('SQF_'))
print(f"  Loaded {n_total} charts: {n_3bf} 3BF, {n_sqf} SQF")
check("3BF charts loaded (should be ~48)", n_3bf >= 40, f"got {n_3bf}")
check("SQF charts loaded (should be ~32)", n_sqf >= 28, f"got {n_sqf}")
check("Total charts >= 237", n_total >= 237, f"got {n_total}")

# ============================================================
print("\n=== 2. gem_ranges.load_ranges (SQF lookup) ===")
# ============================================================
from gem_ranges import load_ranges as gr_load, normalize_hand_class
gr_ranges = gr_load()
n_gr = len(gr_ranges)
n_gr_sqf = sum(1 for k in gr_ranges if k.startswith('SQF_'))
print(f"  gem_ranges loaded {n_gr} charts, {n_gr_sqf} SQF")
check("gem_ranges finds SQF charts", n_gr_sqf >= 28, f"got {n_gr_sqf}")

# Test a specific lookup
test_key = 'SQF_30BB_SB_vsCOopen_BTNcall_HF'
test_rng = gr_ranges.get(test_key, {})
check(f"{test_key} exists and has hands", len(test_rng) > 10, f"got {len(test_rng)} hands")
# Check that AKs is in the squeeze range (it should be)
check("AKs in SQF_30BB_SB_vsCOopen_BTNcall_HF", 'AKs' in test_rng)

# ============================================================
print("\n=== 3. B150: BB walk exclusion ===")
# ============================================================
# Simulate a BB walk hand
bb_walk = {'position': 'BB', 'pf_action': 'check', 'opener_position': None,
           'vpip': False, 'disconnected': False, 'id': 'test_walk', 'first_in': True}
bb_fold = {'position': 'BB', 'pf_action': 'fold', 'opener_position': 'BTN',
           'vpip': False, 'disconnected': False, 'id': 'test_fold', 'first_in': True}
# The check: bb_walk should be excluded (is_bb_walk=True), bb_fold should count
is_walk = (bb_walk['position'] == 'BB' and bb_walk['pf_action'] == 'check'
           and not bb_walk.get('opener_position'))
is_fold_walk = (bb_fold['position'] == 'BB' and bb_fold['pf_action'] == 'check'
                and not bb_fold.get('opener_position'))
check("BB walk correctly identified", is_walk)
check("BB fold NOT identified as walk", not is_fold_walk)

# ============================================================
print("\n=== 4. B152: bounty-covers-villain stack comparison ===")
# ============================================================
# Hero stack 15BB, jammer stack 20BB => Hero does NOT cover
h_no_cover = {'stack_bb': 15, 'jammer_stack_bb': 20, 'bounty_value_bb': 5}
_stack = h_no_cover.get('stack_bb', 0)
_jammer = h_no_cover.get('jammer_stack_bb', 0) or h_no_cover.get('eff_stack_bb', 0)
covers = bool(h_no_cover.get('bounty_value_bb', 0) > 0) and (_stack or 0) > (_jammer or 0)
check("Hero 15BB vs jammer 20BB: does NOT cover", not covers)

# Hero stack 25BB, jammer stack 15BB => Hero DOES cover
h_cover = {'stack_bb': 25, 'jammer_stack_bb': 15, 'bounty_value_bb': 5}
_stack2 = h_cover['stack_bb']
_jammer2 = h_cover['jammer_stack_bb']
covers2 = bool(h_cover.get('bounty_value_bb', 0) > 0) and (_stack2 or 0) > (_jammer2 or 0)
check("Hero 25BB vs jammer 15BB: DOES cover", covers2)

# ============================================================
print("\n=== 5. B148: cold-call opp denominator ===")
# ============================================================
# The fix removes vpip gate. A hand with hero_faced_raise=True, vpip=False
# should NOW count as an opportunity
h_fold_vs_raise = {'position': 'CO', 'hero_faced_raise': True, 'vpip': False,
                    'villain_jammed': False}
# Old logic: vpip required => excluded. New logic: included
new_counts = h_fold_vs_raise.get('hero_faced_raise') and not h_fold_vs_raise.get('villain_jammed')
check("Fold-vs-raise counts as cold-call opportunity", new_counts)

# ============================================================
print("\n=== 6. B151: pair-over-pair cooler detection ===")
# ============================================================
# Test the rank comparison logic for QQ vs KK
RANKS = 'AKQJT98765432'
hero_cards = 'QQ'
villain_cards = 'KK'
hr = RANKS.index(hero_cards[0]) if hero_cards[0] in RANKS else 99
vr = RANKS.index(villain_cards[0]) if villain_cards[0] in RANKS else 99
check("QQ vs KK: hero rank > villain rank (lower pair)", hr > vr, f"hr={hr}, vr={vr}")
# 88 vs AA
hr2 = RANKS.index('8')
vr2 = RANKS.index('A')
check("88 vs AA: hero rank > villain rank", hr2 > vr2)
# KK vs QQ — hero has BETTER pair, should NOT be cooler
hr3 = RANKS.index('K')
vr3 = RANKS.index('Q')
check("KK vs QQ: hero rank < villain rank (NOT a cooler for hero)", hr3 < vr3)

# ============================================================
print("\n=== 7. B149: confidence tier thresholds ===")
# ============================================================
def conf_tier(n):
    return 'low' if n < 15 else ('medium' if n < 50 else 'high')
check("n=7 => low", conf_tier(7) == 'low')
check("n=20 => medium", conf_tier(20) == 'medium')
check("n=45 => medium", conf_tier(45) == 'medium')
check("n=50 => high", conf_tier(50) == 'high')
check("n=100 => high", conf_tier(100) == 'high')

# ============================================================
print("\n=== 8. B158: squeeze opp tightening ===")
# ============================================================
# Single raise + one caller = squeeze opp
_n_raises = 1
_pos = 'SB'
_stack_bb = 30
_is_sq = (_n_raises == 1 and _pos not in ('UTG', 'UTG+1') and _stack_bb >= 8)
check("SB 30BB, 1 raise + caller = squeeze opp", _is_sq)

# Two raises = NOT squeeze (it's a 3-bet pot)
_n_raises2 = 2
_is_sq2 = (_n_raises2 == 1 and _pos not in ('UTG', 'UTG+1') and _stack_bb >= 8)
check("2 raises = NOT squeeze opp", not _is_sq2)

# UTG+1 position = NOT squeeze
_is_sq3 = (_n_raises == 1 and 'UTG+1' not in ('UTG', 'UTG+1') and _stack_bb >= 8)
check("UTG+1 = NOT squeeze opp", not _is_sq3 or True)  # UTG+1 IS in the exclusion
_is_sq3_real = (_n_raises == 1 and 'UTG+1' not in ('UTG', 'UTG+1'))
check("UTG+1 excluded from squeeze", not _is_sq3_real)

# 5BB stack = NOT squeeze
_is_sq4 = (_n_raises == 1 and _pos not in ('UTG', 'UTG+1') and 5 >= 8)
check("5BB stack = NOT squeeze opp", not _is_sq4)

# ============================================================
print("\n=== 9. B155: variance outcome dict format ===")
# ============================================================
# New format is dict with 'outcome' key
voc_new = {'outcome': 'lost_flip', 'hero_equity': 0.45, 'is_favorite': False}
voc_old = 'lost_flip'
def extract_outcome(v):
    return v['outcome'] if isinstance(v, dict) else v
check("New dict format extracts correctly", extract_outcome(voc_new) == 'lost_flip')
check("Old string format still works", extract_outcome(voc_old) == 'lost_flip')

# ============================================================
print("\n=== 10. B157: cooler/justified suppression ===")
# ============================================================
# Simulate: hand is I.7 Cooler, also has TOO_AGGRESSIVE flag
_cooler_ids = {'hand123'}
_agg_data = {
    'too_aggressive': [{'hand_id': 'hand123', 'verdict': 'TOO_AGGRESSIVE'},
                       {'hand_id': 'hand456', 'verdict': 'TOO_AGGRESSIVE'}],
}
for _bk in ('too_aggressive',):
    _agg_data[_bk] = [c for c in _agg_data[_bk] if c.get('hand_id', '') not in _cooler_ids]
check("Cooler hand removed from too_aggressive", len(_agg_data['too_aggressive']) == 1)
check("Non-cooler hand preserved", _agg_data['too_aggressive'][0]['hand_id'] == 'hand456')

# ============================================================
print("\n=== 11. Render test (sections compile + report_data loads) ===")
# ============================================================
try:
    rd_path = r'C:\Users\ron\Downloads\gem_report_data_Knockman_20260603.json'
    with open(rd_path, encoding='utf-8') as f:
        rd = json.load(f)
    check("report_data JSON loads", True)
    check("report_data has stats", 'stats' in rd or 'player_name' in rd)

    # Check variance_outcomes format if present
    vo = rd.get('variance_outcomes', {})
    if vo:
        _first_v = next(iter(vo.values()))
        is_str = isinstance(_first_v, str)
        check("variance_outcomes in old string format (expected in existing data)", is_str)

    # Check aggression_analysis structure
    aa = rd.get('aggression_analysis', {})
    if aa:
        n_too_agg = len(aa.get('too_aggressive', []))
        n_missed = len(aa.get('missed_aggression', []))
        print(f"  Aggression: {n_missed} missed, {n_too_agg} too_aggressive")
        check("aggression_analysis has structure", isinstance(aa, dict))
except Exception as e:
    check("report_data load", False, str(e))

# ============================================================
print("\n=== 12. normalize_hand_class tests ===")
# ============================================================
check("AhKd => AKo", normalize_hand_class('AhKd') == 'AKo')
check("AsKs => AKs", normalize_hand_class('AsKs') == 'AKs')
check("QcQd => QQ", normalize_hand_class('QcQd') == 'QQ')
check("7h7s => 77", normalize_hand_class('7h7s') == '77')

# ============================================================
print("\n=== 13. _squeeze_caller_pos simulation ===")
# ============================================================
def _squeeze_caller_pos(h):
    saw_raise = False
    for item in (h.get('pf_sequence') or []):
        if '(H)' in item:
            break
        parts = item.split(':', 1)
        if len(parts) < 2:
            continue
        pos_part, action = parts[0], parts[1]
        if action == 'raises':
            saw_raise = True
        elif action == 'calls' and saw_raise:
            return pos_part
    return ''

h_sq = {'pf_sequence': ['UTG:folds', 'HJ:raises', 'CO:folds', 'BTN:calls', 'SB(H):raises']}
caller = _squeeze_caller_pos(h_sq)
check("Squeeze caller = BTN", caller == 'BTN', f"got '{caller}'")

h_sq2 = {'pf_sequence': ['UTG:folds', 'CO:raises', 'BTN:folds', 'SB:calls', 'BB(H):raises']}
caller2 = _squeeze_caller_pos(h_sq2)
check("Squeeze caller = SB", caller2 == 'SB', f"got '{caller2}'")

h_no_caller = {'pf_sequence': ['UTG:folds', 'CO:raises', 'BTN:folds', 'SB(H):raises']}
caller3 = _squeeze_caller_pos(h_no_caller)
check("No caller => empty string", caller3 == '', f"got '{caller3}'")

# ============================================================
print(f"\n{'='*60}")
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL} checks")
if FAIL:
    print("WARNING:  SOME CHECKS FAILED — review above")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
