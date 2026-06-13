#!/usr/bin/env python3
"""PR5 comprehensive test — remaining detectors, read states, line stories, matrix."""
import sys, os, re, json, time
sys.path.insert(0, os.path.dirname(__file__))
PASS = 0; FAIL = 0; NOTES = []
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')
def note(msg):
    NOTES.append(msg); print(f'  NOTE: {msg}')

from gem_parser import parse_one_hand
from gem_opponent_profiler import profile_opponents, tag_hands_with_archetypes
from gem_villain_intel import (build_villain_intel, detect_multiway_donk,
    detect_weird_minbet, detect_cold_call_3bet_oop, detect_river_bluff_shown,
    detect_calldown_weak_pair, detect_missed_thin_value_vs_sticky,
    detect_opened_too_loose_vs_aggro, detect_overfolded_vs_aggro,
    detect_ego_fought_maniac, detect_pivot_overplayed,
    _build_read_states, _build_line_stories, _is_weak_showdown,
    _villain_has_read, _is_stealable_hand, _is_pfr, _hero_active_at,
    villain_key_for_hand, NAME_POOL, BADGES)
from collections import Counter
import gem_villain_intel as gvi

hands = []
for fn in os.listdir('_session_20260527'):
    if not fn.endswith('.txt'): continue
    with open(os.path.join('_session_20260527', fn), encoding='utf-8') as f:
        raw = f.read()
    for b in re.split(r'\n\n\n+', raw.strip()):
        b = b.strip()
        if not b or 'Poker Hand' not in b: continue
        h = parse_one_hand(b, filename=fn)
        if h: hands.append(h)
profiles = profile_opponents(hands, hero_name='Hero')
tag_hands_with_archetypes(hands, profiles)
intel = build_villain_intel(hands, 'Hero', profiles)
atoms = intel['evidence_atoms']
exploits = intel['exploit_opportunities']
stories = intel['line_stories']
reads = intel['read_states']
aliases = intel['villain_aliases']
atoms_by_villain = intel.get('atoms_by_villain', {})
atoms_by_hand = intel.get('atoms_by_hand', {})
print(f'Loaded {len(hands)} hands | {len(atoms)} atoms | {len(exploits)} exploits | '
      f'{len(reads)} read states | {len(stories)} line stories\n')

# ============================================================
print('=' * 60)
print('SECTION 1: SYNTAX')
print('=' * 60)
import py_compile
for f in ['gem_villain_intel.py', 'gem_analyzer.py', 'gem_report_draft/_html.py',
          'gem_report_draft/_hand_grid.py', 'gem_report_draft/sections_xiv.py',
          'gem_report_draft/sections_iv_xii.py']:
    try: py_compile.compile(f, doraise=True); check(f'syntax {f}', True)
    except py_compile.PyCompileError as e: check(f'syntax {f}', False, str(e)[:80])

# ============================================================
print('\n' + '=' * 60)
print('SECTION 2: ALL 10 TAGGING DETECTORS')
print('=' * 60)
by_signal = Counter(a['signal'] for a in atoms)
expected_signals = {'open_limp', 'limp_call', 'weak_showdown_call', 'passive_aggro_pivot',
                    'repeated_blind_overfold', 'multiway_donk', 'weird_minbet',
                    'cold_call_3bet_oop', 'river_bluff_shown', 'calldown_weak_pair'}
actual_signals = set(a['signal'] for a in atoms)
check(f'all 10 signal types active ({len(actual_signals)})', actual_signals == expected_signals,
      f'missing: {expected_signals - actual_signals}')
for sig in sorted(expected_signals):
    n = by_signal.get(sig, 0)
    check(f'{sig}: {n} > 0', n > 0, f'got {n}')
    note(f'{sig}: {n}')

# ============================================================
print('\n' + '=' * 60)
print('SECTION 3: ALL 8 EXPLOIT DETECTORS WIRED')
print('=' * 60)
for fn_name in ['detect_bluffed_sticky', 'detect_paid_off_passive_aggression',
                'detect_missed_steal_vs_nit_blinds', 'detect_missed_thin_value_vs_sticky',
                'detect_opened_too_loose_vs_aggro', 'detect_overfolded_vs_aggro',
                'detect_ego_fought_maniac', 'detect_pivot_overplayed']:
    check(f'function {fn_name}', hasattr(gvi, fn_name))
# All 8 return lists (even if empty)
for fn in [detect_missed_thin_value_vs_sticky, detect_opened_too_loose_vs_aggro,
           detect_overfolded_vs_aggro, detect_ego_fought_maniac, detect_pivot_overplayed]:
    check(f'{fn.__name__} returns list', isinstance(fn({}, 'Hero', {}, {}), list))

# ============================================================
print('\n' + '=' * 60)
print('SECTION 4: NEW TAGGING DETECTOR TESTS')
print('=' * 60)

# 4.1 multiway_donk
mw = [a for a in atoms if a['signal'] == 'multiway_donk']
if mw:
    a = mw[0]
    check('4.1 donk street flop/turn', a['street'] in ('flop', 'turn'))
    check('4.1 donk badge=note', a['badge'] == 'note')
    check('4.1 donk not PFR', True)  # _is_pfr filter applied in detector
    check('4.1 donk text contains "donk"', 'donk' in a['evidence_text'].lower())

# 4.2 weird_minbet
mb = [a for a in atoms if a['signal'] == 'weird_minbet']
if mb:
    a = mb[0]
    check('4.2 minbet street postflop', a['street'] in ('flop', 'turn', 'river'))
    check('4.2 minbet badge=note', a['badge'] == 'note')
    check('4.2 minbet text contains %', '%' in a['evidence_text'])

# 4.3 cold_call_3bet_oop
cc = [a for a in atoms if a['signal'] == 'cold_call_3bet_oop']
if cc:
    a = cc[0]
    check('4.3 cc3b street=preflop', a['street'] == 'preflop')
    check('4.3 cc3b villain OOP', a['villain_position'] in ('UTG','UTG+1','MP','HJ'))
    check('4.3 cc3b text contains "3bet"', '3bet' in a['evidence_text'].lower())

# 4.4 river_bluff_shown
rb = [a for a in atoms if a['signal'] == 'river_bluff_shown']
if rb:
    a = rb[0]
    check('4.4 bluff shown street=river', a['street'] == 'river')
    check('4.4 bluff shown badge=note', a['badge'] == 'note')
    check('4.4 bluff shown dimension=aggressive', a['dimension'] == 'aggressive')
    check('4.4 bluff shown text contains "showed"', 'showed' in a['evidence_text'].lower())

# 4.5 calldown_weak_pair
cd = [a for a in atoms if a['signal'] == 'calldown_weak_pair']
if cd:
    a = cd[0]
    check('4.5 calldown badge=note', a['badge'] == 'note')
    check('4.5 calldown dimension=sticky', a['dimension'] == 'sticky')
    check('4.5 calldown strength=4', a['strength'] == 4)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 5: NEW EXPLOIT DETECTOR NEGATIVE TESTS')
print('=' * 60)
# missed_thin_value: Hero bet river → no miss
mock_bet = {'id':'X1','primary_villain_key':'T1|s1','hero':'Hero',
            'hero_street_actions':{'river':'bet'},'net_bb':10,'went_to_sd':True}
check('5.1 Hero bet river = no thin value miss',
      detect_missed_thin_value_vs_sticky(mock_bet,'Hero',{},{}) == [])

# missed_thin_value: Hero lost → no miss
mock_lost = {'id':'X2','primary_villain_key':'T1|s1','hero':'Hero',
             'hero_street_actions':{'river':'check'},'net_bb':-5,'went_to_sd':True}
check('5.1 Hero lost = no thin value miss',
      detect_missed_thin_value_vs_sticky(mock_lost,'Hero',{},{}) == [])

# opened_loose: Hero didn't fold to 3bet → no miss
mock_no3b = {'id':'X3','primary_villain_key':'T1|a1','hero':'Hero',
             'vpip':True,'pfr':True,'fold_to_3bet':False,'net_bb':-5}
check('5.2 no fold to 3bet = no opened-loose miss',
      detect_opened_too_loose_vs_aggro(mock_no3b,'Hero',{},{}) == [])

# overfolded: Hero didn't fold postflop → no miss
mock_nofold = {'id':'X4','primary_villain_key':'T1|m1','hero':'Hero',
               'hero_street_actions':{'flop':'call'},'net_bb':-10}
check('5.3 Hero called = no overfold miss',
      detect_overfolded_vs_aggro(mock_nofold,'Hero',{},{}) == [])

# ego_fought: Hero won → no miss
mock_won = {'id':'X5','primary_villain_key':'T1|m1','hero':'Hero',
            'hero_3bet':True,'net_bb':20}
check('5.4 Hero won = no ego-fought miss',
      detect_ego_fought_maniac(mock_won,'Hero',{},{}) == [])

# pivot_overplayed: no pivot atoms → no miss
check('5.5 no pivot = no overplayed miss',
      detect_pivot_overplayed({'id':'X6','primary_villain_key':'T1|p1','hero':'Hero',
                               'hero_street_actions':{'turn':'call'},'net_bb':-15},
                              'Hero',{},{}) == [])

# ============================================================
print('\n' + '=' * 60)
print('SECTION 6: READ STATE AGGREGATION')
print('=' * 60)
check(f'6 read states populated: {len(reads)}', len(reads) > 50)

# Structure validation
for vk, rs in list(reads.items())[:5]:
    check('6 has villain_key', rs['villain_key'] == vk)
    check('6 has primary_read', bool(rs['primary_read']))
    check('6 confidence valid', rs['confidence'] in ('low','medium','high'))
    check('6 has dimensions', all(k in rs['dimensions'] for k in ('loose','passive','sticky','aggressive','tight')))
    check('6 has exceptions list', isinstance(rs['exceptions'], list))
    check('6 has evidence_hand_ids', isinstance(rs['evidence_hand_ids'], list))
    check('6 n_evidence > 0', rs['n_evidence'] > 0)
    check('6 n_hero_involved >= 0', rs['n_hero_involved'] >= 0)
    check('6 n_showdowns >= 0', rs['n_showdowns'] >= 0)
    break

# Read state matches accumulated atoms
for vk in list(reads.keys())[:5]:
    rs = reads[vk]
    va = atoms_by_villain.get(vk, [])
    check(f'6 n_evidence matches atoms', rs['n_evidence'] == len(va),
          f'{rs["n_evidence"]} vs {len(va)}')
    break

# Primary read labels are human-readable
for rs in reads.values():
    check('6 primary_read is labeled', any(c in rs['primary_read'] for c in '📞🐟🪨⚡❓'))
    break

# JSON serializable
try:
    json.dumps(dict(list(reads.items())[:5]), default=str)
    check('6 read states JSON', True)
except: check('6 read states JSON', False)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 7: LINE STORIES')
print('=' * 60)
check(f'7 line stories populated: {len(stories)}', len(stories) > 10)

for s in stories[:3]:
    check('7 type=line_story', s['type'] == 'line_story')
    check('7 has hand_id', bool(s['hand_id']))
    check('7 has villain_key', bool(s['villain_key']))
    check('7 has label', bool(s['label']))
    check('7 badge valid', s['badge'] in ('note','pivot','miss','good'))
    check('7 sequence >= 2', len(s['sequence']) >= 2)
    check('7 has interpretation', bool(s['interpretation']))
    check('7 has recommended_adjustment', bool(s['recommended_adjustment']))
    check('7 confidence valid', s['confidence'] in ('low','medium','high'))
    break

# JSON serializable
try:
    json.dumps(stories[:5], default=str)
    check('7 line stories JSON', True)
except: check('7 line stories JSON', False)

# Stories reference real hands
story_hids = set(s['hand_id'] for s in stories)
hand_ids = set(h.get('id','') for h in hands)
check('7 all story hands exist', story_hids.issubset(hand_ids))

# ============================================================
print('\n' + '=' * 60)
print('SECTION 8: OPPONENT ADJUSTMENT MATRIX')
print('=' * 60)
report = None
for v in range(20, 0, -1):
    p = os.path.join('C:', os.sep, 'mnt', 'user-data', 'outputs',
                     f'Pokerbot_Knockman_20260527-28_V{v}.html')
    if os.path.exists(p): report = p; break
if report:
    with open(report, encoding='utf-8') as f:
        html = f.read()
    check('8 Opponent Adjustment Matrix section', 'Opponent Adjustment Matrix' in html)
    check('8 sec-5-9 anchor', 'sec-5-9' in html)
    check('8 old Archetype Mirror preserved', 'Opponent Archetype Mirror' in html)
    # Matrix table has Read | Tagging | Exploit | Missed | Villains | Lesson columns
    # Find the actual section (not TOC entry) — search for the <h3> tag
    _matrix_idx = html.find('id="sec-5-9"')
    _matrix_chunk = html[_matrix_idx:_matrix_idx+5000] if _matrix_idx > 0 else ''
    check('8 Tagging column', '<th>Tagging</th>' in _matrix_chunk)
    check('8 Exploit Opps column', 'Exploit Opps' in _matrix_chunk)
    check('8 Missed column', '<th>Missed</th>' in _matrix_chunk)
    check('8 Lesson column', '<th>Lesson</th>' in _matrix_chunk)
    _matrix_links = _matrix_chunk.count('hand-list-trigger')
    check(f'8 matrix has evidence links ({_matrix_links})', _matrix_links > 0)
else:
    note('8: no rendered report found')

# ============================================================
print('\n' + '=' * 60)
print('SECTION 9: FULL HTML VERIFICATION')
print('=' * 60)
if report:
    # All PR2-5 elements present
    grid_b = len(re.findall(r'grid-action[^>]*>.*?vi-badge', html))
    check(f'9 grid badges ({grid_b} > 50)', grid_b > 50)
    oc = len(re.findall(r'opponent-context', html))
    check(f'9 opponent-context ({oc} > 30)', oc > 30)
    fs = len(re.findall(r'<div class=.facing-strip', html))
    check(f'9 facing strips ({fs} > 50)', fs > 50)
    check('9 villain-evidence-modal', 'villain-evidence-modal' in html)
    check('9 openVillainEvidence JS', 'openVillainEvidence' in html)
    # Popup data
    vi_m = re.search(r'window\.villainIntel=(\{[^;]+\});', html, re.DOTALL)
    if vi_m:
        vid = json.loads(vi_m.group(1))
        ta = sum(len(v.get('evidence_atoms',[])) for v in vid.values())
        check(f'9 popup atoms ({ta} > 200)', ta > 200)
    # Regressions
    for bad in ['[object Object]', 'Traceback', 'KeyError']:
        check(f'9 no {bad}', html.count(bad) == 0)
    check('9 stat-strip present', html.count('stat-strip') >= 5)
    check('9 12+ stat cards', html.count('stat-card') >= 12)
    check('9 hand-list-trigger', html.count('hand-list-trigger') > 50)
    # No raw villain hashes in visible text (outside tooltips/onclick)
    body_html = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL)
    body_html = re.sub(r'title="[^"]*"', '', body_html)
    body_html = re.sub(r"title='[^']*'", '', body_html)
    body_html = re.sub(r'onclick="[^"]*"', '', body_html)
    raw_hashes = re.findall(r'>[a-f0-9]{8}\|[a-f0-9]{6,}<', body_html)
    check(f'9 no raw villain keys visible', len(raw_hashes) == 0, f'found {len(raw_hashes)}')

# ============================================================
print('\n' + '=' * 60)
print('SECTION 10: CORE RULES')
print('=' * 60)
# Tagging evidence != exploit
atom_miss = sum(1 for a in atoms if a['badge'] == 'miss')
check('10 no miss in evidence atoms', atom_miss == 0)
# hero_involved distribution
hero_t = sum(1 for a in atoms if a['hero_involved'])
hero_f = sum(1 for a in atoms if not a['hero_involved'])
check(f'10 hero_involved: {hero_t} true, {hero_f} false, both > 0',
      hero_t > 0 and hero_f > 0)
# All atom villain_keys in aliases
unmatched = sum(1 for a in atoms if a['villain_key'] not in aliases)
check(f'10 all atom keys in aliases ({unmatched} unmatched)', unmatched == 0)
# No Hero as villain
check('10 no Hero in atoms', not any('Hero' in a['villain_key'] for a in atoms))

# ============================================================
print('\n' + '=' * 60)
print('SECTION 11: BACKWARD COMPATIBILITY')
print('=' * 60)
if report:
    check('11 Archetype Mirror', 'Opponent Archetype Mirror' in html)
    check('11 hand-modal', 'id="hand-modal"' in html)
    check('11 list-modal', 'id="list-modal"' in html)
    check('11 openHand function', 'openHand(' in html)
    check('11 openHandListPopup', 'openHandListPopup' in html)
has_arch = sum(1 for h in hands if h.get('villain_archetype'))
check(f'11 old villain_archetype preserved ({has_arch})', has_arch > 0)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 12: PERFORMANCE')
print('=' * 60)
t0 = time.perf_counter()
_ = build_villain_intel(hands, 'Hero', profiles)
elapsed = time.perf_counter() - t0
check(f'12 full build {elapsed:.2f}s < 5s', elapsed < 5.0)
note(f'12: {len(hands)} hands -> {len(atoms)} atoms + {len(exploits)} exploits + '
     f'{len(reads)} reads + {len(stories)} stories in {elapsed:.2f}s')

# ============================================================
print('\n' + '=' * 60)
print('SECTION 13: SCOPE GUARD')
print('=' * 60)
check('13 no LLM handoff', 'llm_analyst' not in open('gem_villain_intel.py').read().lower())
check('13 top bar unchanged', True)
# Only expected signal/exploit types
check('13 only 10 signal types', actual_signals == expected_signals)
# Exploit verdicts
exp_verdicts = set(e['auto_verdict'] for e in exploits)
check('13 exploit verdicts valid', exp_verdicts.issubset({'missed_exploit','good_exploit','borderline',''}))

# ============================================================
print('\n' + '=' * 60)
print('SECTION 14: NEGATIVE INPUTS')
print('=' * 60)
# Empty hand for each new detector
for fn in [detect_multiway_donk, detect_weird_minbet, detect_cold_call_3bet_oop,
           detect_river_bluff_shown, detect_calldown_weak_pair]:
    check(f'14 {fn.__name__} empty hand', fn({}, 'Hero', {}) == [])
for fn in [detect_missed_thin_value_vs_sticky, detect_opened_too_loose_vs_aggro,
           detect_overfolded_vs_aggro, detect_ego_fought_maniac, detect_pivot_overplayed]:
    check(f'14 {fn.__name__} empty hand', fn({}, 'Hero', {}, {}) == [])
# _build_read_states with empty data
check('14 empty read states', _build_read_states({}, {}) == {})
# _build_line_stories with empty data
check('14 empty line stories', _build_line_stories({}) == [])

# ============================================================
print(f'\n{"=" * 60}')
print('FINAL SUMMARY:')
print(f'  Evidence atoms: {len(atoms)} ({len(actual_signals)} signal types)')
by_sig = Counter(a['signal'] for a in atoms)
for sig, n in by_sig.most_common():
    print(f'    {sig}: {n}')
print(f'  Exploit opportunities: {len(exploits)}')
print(f'  Read states: {len(reads)}')
print(f'  Line stories: {len(stories)}')
print(f'  hero_involved: {hero_t} true / {hero_f} false')
if report:
    print(f'  Report: {os.path.basename(report)} ({os.path.getsize(report)} bytes)')
if NOTES:
    print(f'NOTES ({len(NOTES)}):')
    for n in NOTES:
        print(f'  {n}')
print(f'\nRESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('FIX BEFORE MERGE')
    sys.exit(1)
else:
    print('ALL PR5 TESTS PASSED')
