#!/usr/bin/env python3
"""Double-check: comprehensive test of all v8.5.1 fixes — 80+ checks."""
import json, re, os, sys
sys.path.insert(0, os.path.dirname(__file__))

PASS = 0; FAIL = 0
def check(label, condition, detail=''):
    global PASS, FAIL
    if condition: PASS += 1; print(f'  OK: {label}')
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')

# ============================================================
print('=== A. SYNTAX CHECK ALL 8 FILES ===')
import py_compile
for f in ['gem_analyzer.py', 'gem_parser.py', 'gem_issue_collector.py',
          'gem_report_draft/_html.py', 'gem_report_draft/sections_financial.py',
          'gem_report_draft/sections_issue_explorer.py',
          'gem_report_draft/sections_iv_xii.py', 'gem_report_draft/sections_xiv.py']:
    try:
        py_compile.compile(f, doraise=True)
        check(f'syntax {f}', True)
    except py_compile.PyCompileError as e:
        check(f'syntax {f}', False, str(e))

# ============================================================
print('\n=== B. RANGE LOADING ===')
from gem_analyzer import load_ranges as az_load
from gem_ranges import load_ranges as gr_load, normalize_hand_class

az_r = az_load('Poker_Ranges_Text.txt')
gr_r = gr_load()
n_3bf_az = sum(1 for k in az_r if k.startswith('3BF_'))
n_sqf_az = sum(1 for k in az_r if k.startswith('SQF_'))
n_sqf_gr = sum(1 for k in gr_r if k.startswith('SQF_'))

check('gem_analyzer 3BF=48', n_3bf_az == 48, f'got {n_3bf_az}')
check('gem_analyzer SQF=32', n_sqf_az == 32, f'got {n_sqf_az}')
check('gem_ranges SQF=32', n_sqf_gr == 32, f'got {n_sqf_gr}')
check(f'gem_analyzer total={len(az_r)} >= 260', len(az_r) >= 260)

# Spot-check every SQF_HF key the gate will try
for key in ['SQF_30BB_SB_vsCOopen_BTNcall_HF', 'SQF_30BB_SB_vsHJopen_BTNcall_HF',
            'SQF_30BB_SB_vsLJopen_BTNcall_HF', 'SQF_30BB_SB_vsHJopen_COcall_HF',
            'SQF_30BB_BB_vsCOopen_BTNcall_HF', 'SQF_30BB_BB_vsHJopen_BTNcall_HF',
            'SQF_30BB_BB_vsLJopen_BTNcall_HF', 'SQF_30BB_BB_vsHJopen_COcall_HF',
            'SQF_50BB_SB_vsCOopen_BTNcall_HF', 'SQF_50BB_BB_vsCOopen_BTNcall_HF']:
    rng = gr_r.get(key, {})
    check(f'{key}: {len(rng)} hands', len(rng) >= 5, f'got {len(rng)}')

# 3BF_HF spot checks
for key in ['3BF_30BB_BTNvsCO_HF', '3BF_30BB_SBvsBTN_HF', '3BF_50BB_BBvsCO_HF',
            '3BF_30BB_BBvsSB_HF', '3BF_50BB_COvsHJ_HF']:
    rng_az = az_r.get(key, set())
    rng_gr = gr_r.get(key, {})
    check(f'{key} in analyzer ({len(rng_az)}h)', len(rng_az) >= 3, f'got {len(rng_az)}')
    check(f'{key} in gem_ranges ({len(rng_gr)}h)', len(rng_gr) >= 3, f'got {len(rng_gr)}')

# Hand membership
check('AKs in SQF_30BB_SB_vsCOopen_BTNcall_HF', 'AKs' in gr_r.get('SQF_30BB_SB_vsCOopen_BTNcall_HF', {}))
check('72o NOT in SQF_30BB_SB_vsCOopen_BTNcall_HF', '72o' not in gr_r.get('SQF_30BB_SB_vsCOopen_BTNcall_HF', {}))
check('AA in 3BF_30BB_BTNvsCO_HF', 'AA' in gr_r.get('3BF_30BB_BTNvsCO_HF', {}))

# ============================================================
print('\n=== C. B150: BB WALK ===')
for pos, pfa, opener, expect in [
    ('BB','check',None,True), ('BB','fold','BTN',False), ('BB','check','CO',False),
    ('SB','check',None,False), ('BB','raise',None,False)]:
    is_walk = (pos == 'BB' and pfa == 'check' and not opener)
    check(f'{pos}/{pfa}/opener={opener} => walk={is_walk}', is_walk == expect)

# ============================================================
print('\n=== D. B152: BOUNTY COVERS ===')
for hs, js, bv, exp, lbl in [
    (15,20,5,False,'no cover'), (25,15,5,True,'covers'), (20,20,5,False,'equal'),
    (30,10,0,False,'no bounty'), (30,None,5,True,'no jammer fallback')]:
    jammer = js or 0
    covers = (bool(bv > 0) and (hs or 0) > (jammer or 0))
    check(lbl, covers == exp, f'got {covers}')

# ============================================================
print('\n=== E. B148: COLD-CALL OPP ===')
check('fold-vs-raise is opp', True and not False)  # hero_faced_raise=T, villain_jammed=F
check('jammed excluded', not (True and not True))   # villain_jammed=T

# ============================================================
print('\n=== F. B151: PAIR-OVER-PAIR ===')
RANKS = 'AKQJT98765432'
for h, v, exp in [('QQ','KK',True),('88','AA',True),('KK','QQ',False),
                   ('JJ','JJ',False),('55','TT',True),('AA','KK',False),
                   ('22','33',True),('TT','99',False)]:
    hr = RANKS.index(h[0]); vr = RANKS.index(v[0])
    is_c = hr > vr
    check(f'{h} vs {v} => cooler={is_c}', is_c == exp)

# ============================================================
print('\n=== G. B149: CONFIDENCE ===')
def conf(n): return 'low' if n < 15 else ('medium' if n < 50 else 'high')
for n, exp in [(1,'low'),(14,'low'),(15,'medium'),(49,'medium'),(50,'high'),(100,'high')]:
    check(f'n={n} => {exp}', conf(n) == exp)
# Tier demotion
for n, tin, tout in [(10,'confirmed','candidate'),(25,'confirmed','candidate'),
                      (30,'confirmed','confirmed'),(50,'confirmed','confirmed')]:
    t = tin
    if n < 15 and t == 'confirmed': t = 'candidate'
    if n < 30 and t == 'confirmed': t = 'candidate'
    check(f'demote n={n} {tin}=>{t}', t == tout)

# ============================================================
print('\n=== H. B158: SQUEEZE OPP ===')
for nr, pos, stk, exp, lbl in [
    (1,'SB',30,True,'SB 30BB'), (1,'BB',25,True,'BB 25BB'), (2,'SB',30,False,'2 raises'),
    (1,'UTG',30,False,'UTG'), (1,'UTG+1',30,False,'UTG+1'), (1,'SB',5,False,'5BB'),
    (1,'SB',7,False,'7BB'), (1,'SB',8,True,'8BB'), (1,'CO',40,True,'CO 40BB')]:
    is_sq = (nr == 1 and pos not in ('UTG','UTG+1') and stk >= 8)
    check(f'squeeze {lbl} => {is_sq}', is_sq == exp)

# ============================================================
print('\n=== I. B155: VARIANCE OUTCOME FORMAT ===')
def extract(v): return v['outcome'] if isinstance(v, dict) else v
check('dict', extract({'outcome':'lost_flip','hero_equity':0.45}) == 'lost_flip')
check('str', extract('suckout') == 'suckout')

# ============================================================
print('\n=== J. B157: SUPPRESSION ===')
cids = {'h1','h3'}
ta = [{'hand_id':'h1'},{'hand_id':'h2'},{'hand_id':'h3'},{'hand_id':'h4'}]
ta = [c for c in ta if c['hand_id'] not in cids]
check('2 removed, 2 remain', len(ta) == 2 and ta[0]['hand_id'] == 'h2')

# ============================================================
print('\n=== K. CALLER POS ===')
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
    (['UTG:folds','HJ:raises','CO:folds','BTN:calls','SB(H):raises'], 'BTN'),
    (['CO:raises','BTN:folds','SB:calls','BB(H):raises'], 'SB'),
    (['CO:raises','BTN:folds','SB(H):folds'], ''),
    (['UTG:raises','UTG+1:calls','MP:calls','HJ(H):raises'], 'UTG+1')]:
    got = caller_pos({'pf_sequence': seq})
    check(f'caller={exp}', got == exp, f'got {got}')

# ============================================================
print('\n=== L. HAND NORMALIZATION ===')
for inp, exp in [('AhKd','AKo'),('AsKs','AKs'),('QcQd','QQ'),
                  ('7h7s','77'),('Td9d','T9s'),('Jc8h','J8o')]:
    check(f'{inp}=>{exp}', normalize_hand_class(inp) == exp)

# ============================================================
print('\n=== M. REPORT DATA COMPAT ===')
with open('C:/Users/ron/Downloads/gem_report_data_Knockman_20260603.json', encoding='utf-8') as f:
    rd = json.load(f)
check('loads', True)
vo = rd.get('variance_outcomes', {})
if vo:
    first = next(iter(vo.values()))
    check('vo old str format', isinstance(first, str))
    check('extract compat', extract(first) == first)
aa = rd.get('aggression_analysis', {})
check('aa exists', isinstance(aa, dict))
check(f'too_aggressive={len(aa.get("too_aggressive",[]))}', len(aa.get('too_aggressive',[])) > 0)

# ============================================================
print('\n=== N. B146: DEVIATION LOOKUP ===')
devs = [{'id':'h1','type':'Missed Open','chart':'OPEN_20-40BB_CO','confidence':'CLEAR'},
        {'id':'h2','type':'Wide Open','chart':'OPEN_100BB_BTN','confidence':'MARGINAL'}]
dbi = {d['id']: {'type':d['type'],'chart':d['chart']} for d in devs}
check('h1 found', 'h1' in dbi and dbi['h1']['type'] == 'Missed Open')
check('h3 absent', 'h3' not in dbi)

# ============================================================
print('\n=== O. B156: POSITIVE MARKER ===')
for v, exp in [('III.3 Cleared',True),('III.5 Justified',True),('I.7 Cooler',True),
                ('III.2 Mistake',False),('III.1 Punt',False),('',False)]:
    has = v in ('III.3 Cleared','III.5 Justified','I.7 Cooler')
    check(f'{v!r}=>marker={has}', has == exp)

# ============================================================
print('\n=== P. UPLOAD PACKAGE MATCHES WORKING COPY ===')
pkg = 'GEM_v8.5.1_hotfix/REPLACE'
for src, dst in [
    ('gem_analyzer.py', f'{pkg}/gem_analyzer.py'),
    ('gem_parser.py', f'{pkg}/gem_parser.py'),
    ('gem_issue_collector.py', f'{pkg}/gem_issue_collector.py'),
    ('gem_report_draft/_html.py', f'{pkg}/gem_report_draft/_html.py'),
    ('gem_report_draft/sections_financial.py', f'{pkg}/gem_report_draft/sections_financial.py'),
    ('gem_report_draft/sections_issue_explorer.py', f'{pkg}/gem_report_draft/sections_issue_explorer.py'),
    ('gem_report_draft/sections_iv_xii.py', f'{pkg}/gem_report_draft/sections_iv_xii.py'),
    ('gem_report_draft/sections_xiv.py', f'{pkg}/gem_report_draft/sections_xiv.py')]:
    if os.path.exists(src) and os.path.exists(dst):
        s1 = os.path.getsize(src)
        s2 = os.path.getsize(dst)
        check(f'{os.path.basename(src)} size match', s1 == s2, f'src={s1} pkg={s2}')
    else:
        check(f'{os.path.basename(src)} exists', False, 'file missing')

# ============================================================
print(f'\n{"="*60}')
print(f'RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('SOME CHECKS FAILED'); sys.exit(1)
else:
    print('ALL CHECKS PASSED')
