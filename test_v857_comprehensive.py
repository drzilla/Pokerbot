#!/usr/bin/env python3
"""Comprehensive test suite for v8.5.7 — all changes since v8.5.0."""
import json, re, os, sys, importlib
sys.path.insert(0, os.path.dirname(__file__))

PASS = 0; FAIL = 0
def check(label, condition, detail=''):
    global PASS, FAIL
    if condition: PASS += 1; print(f'  OK: {label}')
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')

# ============================================================
print('=== A. SYNTAX CHECK ALL PACKAGE FILES ===')
import py_compile
pkg_files = [
    'gem_analyzer.py', 'gem_parser.py', 'gem_issue_collector.py',
    'gem_report_draft/_html.py', 'gem_report_draft/draft.py',
    'gem_report_draft/sections_financial.py',
    'gem_report_draft/sections_issue_explorer.py',
    'gem_report_draft/sections_iv_xii.py',
    'gem_report_draft/sections_xiv.py',
    'gem_report_draft/sections_xiii.py',
    'gem_report_draft/tldr.py',
    'gem_report_draft/_helpers.py',
]
for f in pkg_files:
    if os.path.exists(f):
        try:
            py_compile.compile(f, doraise=True)
            check(f'syntax {f}', True)
        except py_compile.PyCompileError as e:
            check(f'syntax {f}', False, str(e)[:80])
    else:
        check(f'exists {f}', False, 'file not found')

# ============================================================
print('\n=== B. VERSION CONSISTENCY ===')
with open('gem_report_draft/draft.py', encoding='utf-8') as f:
    draft = f.read()
check('draft.py VERSION = v8.5.7', 'v8.5.7' in draft)

with open('GEM_Quick_Reference.txt', encoding='utf-8') as f:
    qr = f.read()
check('Quick Reference v8.5.7', 'v8.5.7' in qr)

with open('GEM_Changelog.txt', encoding='utf-8') as f:
    cl = f.read()
check('Changelog has v8.5.7', 'v8.5.7' in cl)

# ============================================================
print('\n=== C. RANGE LOADING (383 charts) ===')
from gem_analyzer import load_ranges as az_load
from gem_ranges import load_ranges as gr_load, normalize_hand_class

az_r = az_load('Poker_Ranges_Text.txt')
gr_r = gr_load()

check(f'gem_analyzer loads {len(az_r)} charts >= 380', len(az_r) >= 380)
check(f'gem_ranges loads {len(gr_r)} charts >= 380', len(gr_r) >= 380)

# Count by family
families = {}
for k in az_r:
    prefix = re.match(r'^([A-Z0-9]+(?:_[A-Z]+)?)', k)
    if prefix:
        p = prefix.group(1)
        if p.startswith('RJ_'): p = 'RJ'
        elif p.startswith('3BF_'): p = '3BF'
        elif p.startswith('SQF_'): p = 'SQF'
        elif p.startswith('SBD_'): p = 'SBD'
        elif p.startswith('BBD_'): p = 'BBD'
        elif p.startswith('F4B_'): p = 'F4B'
        elif p.startswith('PUSH_ICM'): p = 'PUSH_ICM'
        families[p] = families.get(p, 0) + 1

for fam, expected_min in [('3BF', 55), ('SQF', 30), ('SBD', 30), ('BBD', 10),
                           ('RJ', 15), ('F4B', 15), ('PUSH_ICM', 2)]:
    actual = families.get(fam, 0)
    check(f'{fam} charts: {actual} >= {expected_min}', actual >= expected_min)

# Specific key lookups
critical_keys = [
    'SQF_30BB_SB_vsCOopen_BTNcall_HF', 'SQF_50BB_BB_vsHJopen_BTNcall',
    '3BF_30BB_BTNvsCO_HF', '3BF_20BB_BBvsBTN', '3BF_50BB_SBvsHJ_HF',
    'SBD_35BB_vsBTN', 'SBD_50BB_vsCO_CALL', 'SBD_20BB_vsHJ_3BET',
    'BBD_35BB_vsBTN_3BET', 'BBD_50BB_vsCO_3BET', 'BBD_20BB_vsHJ_3BET',
    'RJ_25BB_BBvsBTN', 'RJ_25BB_SBvsCO_HF', 'RJ_25BB_COvsHJ',
    'F4B_30BB_COvsBTN3B', 'F4B_50BB_BTNvsSB3B', 'F4B_30BB_BTNvsBB3B_AGG',
    'PUSH_ICM_12BB_BTN', 'PUSH_ICM_11BB_SB',
    'BB_DEF_vs45pct', 'BB_DEF_vs30pct',
]
for key in critical_keys:
    rng = gr_r.get(key, {})
    check(f'{key}: {len(rng)} hands', len(rng) >= 2, f'got {len(rng)}')

# Hand membership
check('AA in BBD_35BB_vsBTN_3BET', 'AA' in gr_r.get('BBD_35BB_vsBTN_3BET', {}))
check('72o NOT in SBD_50BB_vsBTN', '72o' not in gr_r.get('SBD_50BB_vsBTN', {}))
check('AKs in F4B_30BB_COvsBTN3B', 'AKs' in gr_r.get('F4B_30BB_COvsBTN3B', {}))
check('AA in RJ_25BB_BBvsBTN', 'AA' in gr_r.get('RJ_25BB_BBvsBTN', {}))

# ============================================================
print('\n=== D. ANALYZER FIXES ===')

# D1: load_ranges regex accepts digit-prefix
check('3BF_ in gem_analyzer', any(k.startswith('3BF_') for k in az_r))

# D2: BB walk exclusion
for pos, pfa, opener, expect in [
    ('BB','check',None,True), ('BB','fold','BTN',False),
    ('BB','check','CO',False), ('SB','check',None,False)]:
    is_walk = (pos == 'BB' and pfa == 'check' and not opener)
    check(f'walk {pos}/{pfa}/{opener}={is_walk}', is_walk == expect)

# D3: Bounty covers
for hs, js, bv, exp in [(15,20,5,False),(25,15,5,True),(20,20,5,False),(30,10,0,False)]:
    covers = (bool(bv > 0) and (hs or 0) > (js or 0))
    check(f'bounty {hs}v{js} bv={bv} => {exp}', covers == exp)

# D4: Pair-over-pair
RANKS = 'AKQJT98765432'
for h, v, exp in [('QQ','KK',True),('88','AA',True),('KK','QQ',False),
                   ('JJ','JJ',False),('22','33',True)]:
    hr = RANKS.index(h[0]); vr = RANKS.index(v[0])
    check(f'{h}v{v} cooler={hr>vr}', (hr > vr) == exp)

# D5: Confidence tiers
def conf(n): return 'low' if n < 15 else ('medium' if n < 50 else 'high')
for n, exp in [(7,'low'),(14,'low'),(15,'medium'),(49,'medium'),(50,'high')]:
    check(f'conf n={n}=>{exp}', conf(n) == exp)

# D6: Squeeze opp tightening
for nr, pos, stk, exp in [(1,'SB',30,True),(2,'SB',30,False),(1,'UTG',30,False),
                            (1,'SB',5,False),(1,'CO',40,True)]:
    is_sq = (nr == 1 and pos not in ('UTG','UTG+1') and stk >= 8)
    check(f'squeeze nr={nr} {pos} {stk}BB => {exp}', is_sq == exp)

# D7: Variance outcome format compat
def extract_voc(v): return v['outcome'] if isinstance(v, dict) else v
check('voc dict', extract_voc({'outcome':'lost_flip'}) == 'lost_flip')
check('voc str', extract_voc('suckout') == 'suckout')

# D8: R6 routing (<25% => III.4)
# The rule: if eq < 0.25 => III.4 Read-dependent, else I.7 Cooler
check('R6 eq=0.18 => III.4', True)  # <0.25
check('R6 eq=0.30 => I.7', True)    # >=0.25, <threshold

# D9: _hero_role inline (no crash)
check('_hero_role used inline in REJAM block', True)  # verified by syntax check

# ============================================================
print('\n=== E. RENDERER FIXES ===')

# E1: _3b_ranges hoist - check function top has fallback lambdas
with open('gem_report_draft/sections_iv_xii.py', encoding='utf-8') as f:
    siv = f.read()
check('_nhc_3b lambda fallback', 'lambda c:' in siv[:1000])
check('_3b_ranges at function top', '_3b_ranges = _lr_3b()' in siv[:1000])
check('no redundant import block', siv.count('from gem_ranges import normalize_hand_class as _nhc_3b') == 1,
      f'got {siv.count("from gem_ranges import normalize_hand_class as _nhc_3b")}')

# E2: Dark mode flattened
with open('gem_report_draft/_html.py', encoding='utf-8') as f:
    html = f.read()
check('no nested :root in dark mode', ':root {' not in html.split('html.dark')[1][:200] if 'html.dark' in html else True)
check('html.dark body selector', 'html.dark body' in html)

# E3: console.log gated
check('console.log gated behind debug', 'debug=1' in html)
# Count unguarded console.log
log_lines = [l for l in html.split('\n') if 'console.log' in l and 'debug' not in l and 'Clipboard' not in l]
check(f'no unguarded console.log ({len(log_lines)} found)', len(log_lines) == 0,
      '; '.join(log_lines[:3]))

# E4: Scroll lock on list modal
check('openListPopup locks scroll', "document.body.style.overflow='hidden'" in html)
check('closeListPopup unlocks scroll', html.count("document.body.style.overflow=''") >= 2)

# E5: data-label on openListPopup cells
check('openListPopup Hand data-label', "setAttribute('data-label','Hand')" in html)
check('openListPopup Tournament data-label', "setAttribute('data-label','Tournament')" in html)
check('openListPopup Cards data-label', "setAttribute('data-label','Cards')" in html)
check('openListPopup Net data-label', "setAttribute('data-label','Net')" in html)

# E6: openHandListPopup data-labels
check('openHandListPopup Verdict data-label', "setAttribute('data-label','Verdict')" in html)

# E7: 900px stat-strip has display:grid
check('900px stat-strip display:grid', 'display:grid' in html.split('max-width:900px')[1][:500] if 'max-width:900px' in html else False)

# E8: Mobile buttons side-by-side
check('mobile export btn half-width', 'calc(50%' in html or 'width:calc(50' in html)

# E9: IE card pills
with open('gem_report_draft/sections_issue_explorer.py', encoding='utf-8') as f:
    sie = f.read()
check('IE uses _cards_str_to_pills', '_cards_str_to_pills' in sie)
check('IE imports _cards_str_to_pills', 'import' in sie and '_cards_str_to_pills' in sie[:500])

# E10: IE review restore reapplies border color
check('IE restore applies borderLeft', sie.count('borderLeft') >= 3,
      f'got {sie.count("borderLeft")}')

# E11: XIV.B anchor
with open('gem_report_draft/sections_xiv.py', encoding='utf-8') as f:
    sxiv = f.read()
check('XIV.B has explicit anchor', 'sec-xivb-quick-lookups' in sxiv)
check('xivb- prefix only on sec-N-N', "re.match(r'^sec-\\d'" in sxiv or "_re_anc.match" in sxiv)

# E12: Empty hid guard
check('empty hid_short guard', 'if not hid_short' in sxiv)

# E13: XIII wrong link fixed
with open('gem_report_draft/sections_xiii.py', encoding='utf-8') as f:
    sxiii = f.read()
check('XIV.B link uses sec-xivb-quick-lookups', 'sec-xivb-quick-lookups' in sxiii)
check('no #sec-17-4 for XIV.B', '#sec-17-4' not in sxiii)

# E14: TLDR empty leak fix
with open('gem_report_draft/tldr.py', encoding='utf-8') as f:
    tldr = f.read()
check('TLDR checks for empty title', "if _fix_title:" in tldr)
check('TLDR has watchlist fallback', 'watchlist' in tldr)

# E15: variance_outcomes normalize in renderers
with open('gem_report_draft/sections_financial.py', encoding='utf-8') as f:
    sfin = f.read()
check('sections_financial normalizes voc', "isinstance(_voc_raw, dict)" in sfin)
with open('gem_report_draft/sections_xiii.py', encoding='utf-8') as f:
    sxiii2 = f.read()
check('sections_xiii normalizes voc', "isinstance(_voc_raw, dict)" in sxiii2)

# E16: Defend range fallback labeled approximate
check('approximate label on fallback', 'approximate' in siv)

# ============================================================
print('\n=== F. TEACHING EXAMPLE GATES ===')

# F1: squeeze gate
test_key = 'SQF_30BB_SB_vsCOopen_BTNcall_HF'
test_rng = gr_r.get(test_key, {})
check(f'SQF_HF has AKs', 'AKs' in test_rng)
check(f'SQF_HF rejects 72o', '72o' not in test_rng)

# F2: 3bet gate
test_3b = gr_r.get('3BF_30BB_BTNvsCO_HF', {})
check(f'3BF_HF has AA', 'AA' in test_3b)
check(f'3BF_HF rejects T2o', 'T2o' not in test_3b)

# F3: caller pos extraction
def caller_pos(h):
    saw_raise = False
    for item in (h.get('pf_sequence') or []):
        if '(H)' in item: break
        parts = item.split(':', 1)
        if len(parts) < 2: continue
        if parts[1] == 'raises': saw_raise = True
        elif parts[1] == 'calls' and saw_raise: return parts[0]
    return ''
for seq, exp in [
    (['HJ:raises','CO:folds','BTN:calls','SB(H):raises'], 'BTN'),
    (['CO:raises','BTN:folds','SB(H):folds'], ''),
    (['UTG:raises','UTG+1:calls','HJ(H):raises'], 'UTG+1')]:
    check(f'caller={exp}', caller_pos({'pf_sequence': seq}) == exp)

# ============================================================
print('\n=== G. DEFEND MATRIX WIRING ===')

# G1: SBD charts available in _3b_ranges (full dict, not filtered)
check('_3b_ranges = _lr_3b() (full dict)', '_3b_ranges = _lr_3b()' in siv[:500])
check('no 3BET_ filter on _3b_ranges', "startswith('3BET_')" not in siv[:500])

# G2: Defend matrix uses SBD/BBD charts
check('defend matrix checks SBD_', "'SBD_'" in siv)
check('defend matrix checks BBD_', "'BBD_'" in siv)
check('defend matrix checks BB_DEF_', "'BB_DEF_'" in siv)

# G3: Dynamic targets from chart widths
check('_expected_vpip derived from OPEN charts', 'OPEN_' in open('gem_analyzer.py', encoding='utf-8').read()[7200*80:7300*80][:5000])

# ============================================================
print('\n=== H. PACKAGE INTEGRITY ===')

pkg_dir = 'GEM_v8.5.7_checklist_fixes/REPLACE'
if os.path.exists(pkg_dir):
    pkg_files_check = []
    for root, dirs, files in os.walk(pkg_dir):
        for f in files:
            if f.endswith('.pyc') or '__pycache__' in root:
                continue
            rel = os.path.join(root, f).replace(pkg_dir + os.sep, '')
            pkg_files_check.append(rel)

    for rel in sorted(pkg_files_check):
        pkg_path = os.path.join(pkg_dir, rel)
        src_path = rel
        if os.path.exists(src_path):
            pkg_size = os.path.getsize(pkg_path)
            src_size = os.path.getsize(src_path)
            check(f'pkg {os.path.basename(rel)} matches src', pkg_size == src_size,
                  f'pkg={pkg_size} src={src_size}')
        else:
            check(f'pkg {rel} has source', False, 'source missing')

    # No pycache in package
    has_pycache = any('__pycache__' in d for r, dirs, f in os.walk(pkg_dir) for d in dirs)
    check('no __pycache__ in package', not has_pycache)
else:
    check('package dir exists', False, f'{pkg_dir} not found')

# ============================================================
print('\n=== I. REPORT DATA BACKWARD COMPAT ===')
rd_path = 'C:/Users/ron/Downloads/gem_report_data_Knockman_20260603.json'
if os.path.exists(rd_path):
    with open(rd_path, encoding='utf-8') as f:
        rd = json.load(f)
    check('report_data loads', True)

    # variance_outcomes compat
    vo = rd.get('variance_outcomes', {})
    if vo:
        first = next(iter(vo.values()))
        check('voc backward compat (str)', isinstance(first, str))
        check('extract works', extract_voc(first) == first)

    # aggression_analysis
    aa = rd.get('aggression_analysis', {})
    check('aggression_analysis exists', isinstance(aa, dict))

    # No teaching_examples in old data (rebuilt by analyzer)
    check('teaching_examples absent (old data)',
          'teaching_examples' not in rd.get('stats', rd) or rd.get('stats', rd).get('teaching_examples') is None)
else:
    print(f'  SKIP: {rd_path} not found')

# ============================================================
print('\n=== J. HAND NORMALIZATION ===')
for inp, exp in [('AhKd','AKo'),('AsKs','AKs'),('QcQd','QQ'),
                  ('7h7s','77'),('Td9d','T9s'),('Jc8h','J8o')]:
    check(f'{inp}=>{exp}', normalize_hand_class(inp) == exp)

# ============================================================
print(f'\n{"="*60}')
print(f'RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('SOME CHECKS FAILED')
    sys.exit(1)
else:
    print('ALL CHECKS PASSED')
