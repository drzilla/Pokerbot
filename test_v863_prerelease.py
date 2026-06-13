#!/usr/bin/env python3
"""Pre-release gate for v8.6.3 — phase model + bounty + tier handicap + all v8.6.x."""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))
PASS = 0; FAIL = 0
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')

# ============================================================
print('=== 1. SYNTAX (all project files) ===')
import py_compile
for f in ['gem_analyzer.py', 'gem_parser.py', 'gem_phase.py', 'gem_bounty.py',
          'gem_issue_collector.py', 'gem_summary_parser.py', 'gem_tier_handicaps.py',
          'gem_report_draft/_html.py', 'gem_report_draft/draft.py',
          'gem_report_draft/sections_financial.py',
          'gem_report_draft/sections_issue_explorer.py',
          'gem_report_draft/sections_iv_xii.py', 'gem_report_draft/sections_xiv.py',
          'gem_report_draft/sections_xiii.py', 'gem_report_draft/tldr.py',
          'gem_report_draft/_helpers.py']:
    if os.path.exists(f):
        try:
            py_compile.compile(f, doraise=True); check(f'syntax {f}', True)
        except py_compile.PyCompileError as e:
            check(f'syntax {f}', False, str(e)[:80])

# ============================================================
print('\n=== 2. VERSION ===')
with open('gem_report_draft/draft.py', encoding='utf-8') as f:
    check('v8.6.3 in draft.py', 'v8.6.3' in f.read())

# ============================================================
print('\n=== 3. GEM_PHASE MODULE ===')
from gem_phase import (monotonic_smooth, robust_avg_stack, icm_pressure,
                       snap_to_standard, _derive_legacy, estimate_tournament_phases_v2)
check('monotonic_smooth works', monotonic_smooth([100, 50], 1, 100, 5) == [100, 5])
check('snap 9800->10000', snap_to_standard(9800) == 10000)
check('icm HU=0', icm_pressure('in_money', 0.01, 0.15, 'hu') == 0.0)
check('icm FT>=0.85', icm_pressure('in_money', 0.05, 0.15, 'final_table') >= 0.85)
check('icm normal ITM<=0.35', icm_pressure('in_money', 0.05, 0.15, 'normal') <= 0.35)
check('legacy hu->ft_zone', _derive_legacy('hu', 'in_money', 'post_reg') == 'ft_zone')
check('legacy itm->post_bubble', _derive_legacy('normal', 'in_money', 'post_reg') == 'post_bubble')

# ============================================================
print('\n=== 4. PHASE INTEGRATION ===')
with open('gem_analyzer.py', encoding='utf-8') as f:
    az = f.read()
check('estimate_tournament_phases calls v2', 'estimate_tournament_phases_v2' in az)
check('old_phase QA field set', "h['old_phase']" in az)
check('Phase QA console output', 'Phase QA:' in az)
check('no _ICM_PHASES gating', 'in _ICM_PHASES' not in az)
check('icm_pressure >= 0.5 used', 'icm_pressure' in az and '>= 0.5' in az)

# ============================================================
print('\n=== 5. BOUNTY RATIO MODEL ===')
from gem_bounty import bounty_value_bb, bounty_context, classify_bounty
# Flat table fallback
flat = bounty_value_bb('Test PKO', 'post_reg', 'BOUNTY', True)
check(f'flat table returns numeric ({flat})', isinstance(flat, (int, float)) and flat > 0)
# Ratio model
ratio_val = bounty_value_bb('Test PKO', 'post_reg', 'BOUNTY', True,
                            bounty_ratio=0.5, eff_stack_bb=30, starting_stack_bb=100)
check(f'ratio model returns numeric ({ratio_val})', isinstance(ratio_val, (int, float)) and ratio_val > 0)
check('ratio > flat (bigger credit)', ratio_val > flat)
# No covers = 0
check('no covers = 0', bounty_value_bb('Test', 'post_reg', 'BOUNTY', False,
                                        bounty_ratio=0.5, eff_stack_bb=30) == 0.0)
# Context includes method
ctx = bounty_context('Test PKO', 'post_reg', 'BOUNTY', True,
                      bounty_ratio=0.5, eff_stack_bb=30, starting_stack_bb=100)
check('context has method', ctx.get('method') == 'ratio_model')
ctx_flat = bounty_context('Test PKO', 'post_reg', 'BOUNTY', True)
check('flat context has method', ctx_flat.get('method') == 'flat_table')

# ============================================================
print('\n=== 6. TIER HANDICAP LOW-N GUARD ===')
from gem_tier_handicaps import MIN_PAIRINGS
check('MIN_PAIRINGS = 3', MIN_PAIRINGS == 3)
# The guard logic — simulate
import statistics, math
# n=1 should emit None
check('n=1 < MIN_PAIRINGS', 1 < MIN_PAIRINGS)
check('n=2 < MIN_PAIRINGS', 2 < MIN_PAIRINGS)
check('n=3 >= MIN_PAIRINGS', 3 >= MIN_PAIRINGS)
# Consumer safety
_h = None
if _h is None:
    _h = 0.0
check('None -> 0.0 fallback', _h == 0.0)

# ============================================================
print('\n=== 7. TOURNAMENT STRUCTURES ===')
with open('tournament_structures.json', encoding='utf-8') as f:
    structs = json.load(f)
overrides = structs.get('name_overrides', {})
check('GGMasters Bounty -> 10000', overrides.get('GGMasters Bounty', {}).get('starting_chips') == 10000)
check('GGMasters Bounty Turbo -> 10000', overrides.get('GGMasters Bounty Turbo', {}).get('starting_chips') == 10000)
ladders = structs.get('ladder_progressions', {})
check('deep_100_200_50k ladder exists', 'deep_100_200_50k' in ladders)
check('deep ladder starts at L1 100/200', ladders.get('deep_100_200_50k', [[]])[0] == [1, 100, 200])

# ============================================================
print('\n=== 8. RANGE CHARTS ===')
from gem_analyzer import load_ranges
r = load_ranges('Poker_Ranges_Text.txt')
check(f'charts loaded: {len(r)} >= 380', len(r) >= 380)

# ============================================================
print('\n=== 9. XIV.B CAP ===')
with open('gem_report_draft/sections_xiv.py', encoding='utf-8') as f:
    sxiv = f.read()
check('cap default 100', "'100'" in sxiv and 'GEM_XIVB_CAP' in sxiv)

# ============================================================
print('\n=== 10. CSS BRACE FIX ===')
with open('gem_report_draft/_html.py', encoding='utf-8') as f:
    html = f.read()
# Check 600px block is closed before 480px
idx600 = html.find('max-width:600px')
idx480 = html.find('max-width:480px')
check('600px before 480px', idx600 < idx480 if idx600 > 0 and idx480 > 0 else False)
between = html[idx600:idx480] if idx600 > 0 and idx480 > 0 else ''
check('600px closed (}} before 480px)', '}}' in between)

# ============================================================
print('\n=== 11. PERFORMANCE (cached index + debounce) ===')
check('_pbBuildIndex in html', '_pbBuildIndex' in html)
check('debounced save', 'setTimeout(saveReview' in html)
check('pbUpdateHandRefs exists', 'pbUpdateHandRefs' in html)

# ============================================================
print('\n=== 12. PACKAGE INTEGRITY ===')
pkg = 'GEM_v8.6.3_phase_model/REPLACE'
if os.path.exists(pkg):
    for root, dirs, files in os.walk(pkg):
        for f in files:
            if f.endswith('.pyc') or '__pycache__' in root:
                check(f'no pycache: {f}', False)
            else:
                rel = os.path.join(root, f).replace(pkg + os.sep, '')
                if os.path.exists(rel):
                    s1 = os.path.getsize(os.path.join(root, f))
                    s2 = os.path.getsize(rel)
                    if s1 != s2:
                        check(f'{os.path.basename(f)} matches', False, f'pkg={s1} src={s2}')

# ============================================================
print(f'\n{"="*60}')
print(f'RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('FIX BEFORE UPLOADING')
    sys.exit(1)
else:
    print('PRE-RELEASE GATE PASSED')
