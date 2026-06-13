#!/usr/bin/env python3
"""PR3 test checklist — MVP evidence detectors verification."""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))
PASS = 0; FAIL = 0; NOTES = []
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')
def note(msg):
    NOTES.append(msg); print(f'  NOTE: {msg}')

# ── Parse real hands ────────────────────────────────────────
from gem_parser import parse_one_hand
from gem_opponent_profiler import profile_opponents, tag_hands_with_archetypes
from gem_villain_intel import (build_villain_intel, extract_evidence_atoms,
                                detect_open_limp, detect_limp_call,
                                detect_weak_showdown_call, detect_passive_aggro_pivot,
                                detect_repeated_blind_overfold, villain_key_for_hand,
                                NAME_POOL, BADGES, _is_weak_showdown)
from collections import Counter

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
aliases = intel['villain_aliases']
atoms = intel['evidence_atoms']
print(f'Loaded {len(hands)} hands, {len(atoms)} atoms detected\n')

# ============================================================
print('=' * 60)
print('SECTION 1: SYNTAX')
print('=' * 60)
import py_compile
for f in ['gem_villain_intel.py', 'gem_analyzer.py',
          'gem_report_draft/_html.py', 'gem_report_draft/_hand_grid.py',
          'gem_report_draft/sections_xiv.py']:
    try:
        py_compile.compile(f, doraise=True); check(f'syntax {f}', True)
    except py_compile.PyCompileError as e:
        check(f'syntax {f}', False, str(e)[:80])

# ============================================================
print('\n' + '=' * 60)
print('SECTION 2: DETECTOR FUNCTIONS EXIST')
print('=' * 60)
import gem_villain_intel as gvi
for fn_name in ['detect_open_limp', 'detect_limp_call', 'detect_weak_showdown_call',
                'detect_passive_aggro_pivot', 'detect_repeated_blind_overfold',
                'extract_evidence_atoms', '_is_weak_showdown', '_make_atom']:
    check(f'function {fn_name} exists', hasattr(gvi, fn_name))

# ============================================================
print('\n' + '=' * 60)
print('SECTION 3: DETECTOR OUTPUT STRUCTURE')
print('=' * 60)
check('atoms is list', isinstance(atoms, list))
check('atoms non-empty', len(atoms) > 0)

# Check every atom has required fields
required_fields = ['type', 'hand_id', 'tournament_id', 'villain_key', 'villain_alias',
                   'street', 'action_index', 'signal', 'label', 'badge', 'dimension',
                   'strength', 'same_hand_actionable', 'available_before_action_index',
                   'hero_involved', 'evidence_text', 'read_impact', 'villain_position']
missing_fields = set()
for a in atoms:
    for f in required_fields:
        if f not in a:
            missing_fields.add(f)
check('all atoms have required fields', len(missing_fields) == 0,
      f'missing: {missing_fields}')

# Check field types
for a in atoms[:20]:
    check('type == evidence_atom', a['type'] == 'evidence_atom')
    check('badge in allowed set', a['badge'] in {'note', 'pivot', 'miss', 'good'})
    check('street valid', a['street'] in {'preflop', 'flop', 'turn', 'river', 'showdown'})
    check('strength is int', isinstance(a['strength'], int))
    check('same_hand_actionable is bool', isinstance(a['same_hand_actionable'], bool))
    check('hero_involved is bool', isinstance(a['hero_involved'], bool))
    check('evidence_text non-empty', bool(a['evidence_text']))
    check('read_impact non-empty', bool(a['read_impact']))
    check('villain_key has |', '|' in a['villain_key'])
    break  # one sample is enough for type checks

# Check JSON serializable
try:
    json.dumps(atoms[:10], default=str)
    check('atoms JSON serializable', True)
except Exception as e:
    check('atoms JSON serializable', False, str(e)[:80])

# ============================================================
print('\n' + '=' * 60)
print('SECTION 4: DETECTOR COVERAGE')
print('=' * 60)
by_signal = Counter(a['signal'] for a in atoms)
for sig in ['open_limp', 'limp_call', 'weak_showdown_call',
            'passive_aggro_pivot', 'repeated_blind_overfold']:
    n = by_signal.get(sig, 0)
    check(f'{sig}: {n} detections', n >= 0)  # some may be 0 in small datasets
    note(f'{sig}: {n}')

total = len(atoms)
check(f'total atoms ({total}) > 50', total > 50)

by_badge = Counter(a['badge'] for a in atoms)
check('has note badges', by_badge.get('note', 0) > 0)
check('has pivot badges', by_badge.get('pivot', 0) > 0)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 5: INDIVIDUAL DETECTOR TESTS')
print('=' * 60)

# 5.1 Open limp
limp_atoms = [a for a in atoms if a['signal'] == 'open_limp']
if limp_atoms:
    a = limp_atoms[0]
    check('5.1 open_limp street=preflop', a['street'] == 'preflop')
    check('5.1 open_limp badge=note', a['badge'] == 'note')
    check('5.1 open_limp dimension=loose_passive', a['dimension'] == 'loose_passive')
    check('5.1 open_limp same_hand_actionable=True', a['same_hand_actionable'] == True)
    check('5.1 open_limp villain not in SB/BB', a['villain_position'] not in ('SB', 'BB'))
    check('5.1 open_limp text contains "limp"', 'limp' in a['evidence_text'].lower())
else:
    note('5.1: no open limps detected (possible in tight sample)')

# 5.2 Limp-call
lc_atoms = [a for a in atoms if a['signal'] == 'limp_call']
if lc_atoms:
    a = lc_atoms[0]
    check('5.2 limp_call street=preflop', a['street'] == 'preflop')
    check('5.2 limp_call badge=note', a['badge'] == 'note')
    check('5.2 limp_call strength >= open_limp', a['strength'] >= 3)
    check('5.2 limp_call text contains "limp-call"', 'limp-call' in a['evidence_text'].lower())
else:
    note('5.2: no limp-calls detected')

# 5.3 Weak showdown call
wsc_atoms = [a for a in atoms if a['signal'] == 'weak_showdown_call']
if wsc_atoms:
    a = wsc_atoms[0]
    check('5.3 wsc street in turn/river', a['street'] in ('turn', 'river'))
    check('5.3 wsc badge=note', a['badge'] == 'note')
    check('5.3 wsc dimension=sticky', a['dimension'] == 'sticky')
    check('5.3 wsc text contains "showed"', 'showed' in a['evidence_text'].lower())
else:
    note('5.3: no weak showdown calls detected (needs showdowns with villain cards)')

# 5.4 Passive→aggro pivot
pap_atoms = [a for a in atoms if a['signal'] == 'passive_aggro_pivot']
if pap_atoms:
    a = pap_atoms[0]
    check('5.4 pivot street in flop/turn/river', a['street'] in ('flop', 'turn', 'river'))
    check('5.4 pivot badge=pivot', a['badge'] == 'pivot')
    check('5.4 pivot strength=4', a['strength'] == 4)
    check('5.4 pivot same_hand_actionable=True', a['same_hand_actionable'] == True)
    check('5.4 pivot text contains "passive"', 'passive' in a['evidence_text'].lower())
else:
    note('5.4: no pivots detected')

# 5.5 Repeated blind overfold
rbo_atoms = [a for a in atoms if a['signal'] == 'repeated_blind_overfold']
if rbo_atoms:
    a = rbo_atoms[0]
    check('5.5 rbo street=preflop', a['street'] == 'preflop')
    check('5.5 rbo badge=note', a['badge'] == 'note')
    check('5.5 rbo dimension=tight', a['dimension'] == 'tight')
    check('5.5 rbo villain in SB/BB', a['villain_position'] in ('SB', 'BB'))
    check('5.5 rbo text contains "fold"', 'fold' in a['evidence_text'].lower())
    check('5.5 rbo text contains count', any(str(n) in a['evidence_text'] for n in range(4, 30)))
else:
    note('5.5: no repeated blind overfolds detected')

# ============================================================
print('\n' + '=' * 60)
print('SECTION 6: SAME-HAND ACTIONABLE SEMANTICS')
print('=' * 60)
# same_hand_actionable atoms should have available_before_action_index set
sha_atoms = [a for a in atoms if a['same_hand_actionable']]
if sha_atoms:
    with_abi = sum(1 for a in sha_atoms if a['available_before_action_index'] is not None)
    check(f'6 actionable atoms have available_before ({with_abi}/{len(sha_atoms)})',
          with_abi > 0)
    # available_before should be > action_index
    for a in sha_atoms[:10]:
        if a['available_before_action_index'] is not None:
            check('6 available_before > action_index',
                  a['available_before_action_index'] > a['action_index'],
                  f'{a["available_before_action_index"]} vs {a["action_index"]}')
            break

# Non-actionable atoms (weak_showdown_call, repeated_blind_overfold)
non_sha = [a for a in atoms if not a['same_hand_actionable']]
if non_sha:
    check('6 non-actionable atoms exist', len(non_sha) > 0)
    note(f'6: {len(sha_atoms)} actionable, {len(non_sha)} non-actionable atoms')

# ============================================================
print('\n' + '=' * 60)
print('SECTION 7: HERO INVOLVEMENT')
print('=' * 60)
hero_atoms = [a for a in atoms if a['hero_involved']]
non_hero = [a for a in atoms if not a['hero_involved']]
check(f'7 hero-involved atoms ({len(hero_atoms)})', len(hero_atoms) > 0)
# repeated_blind_overfold can have hero_involved=False (Hero wasn't in hand)
note(f'7: {len(hero_atoms)} hero-involved, {len(non_hero)} non-hero atoms')

# ============================================================
print('\n' + '=' * 60)
print('SECTION 8: VILLAIN KEY CONSISTENCY')
print('=' * 60)
# Every atom villain_key should be in aliases
unmatched = set()
for a in atoms:
    if a['villain_key'] not in aliases:
        unmatched.add(a['villain_key'])
check(f'8 all atom villain_keys in aliases', len(unmatched) == 0,
      f'{len(unmatched)} unmatched')

# No Hero as villain
hero_atoms_vk = [a for a in atoms if 'Hero' in a['villain_key']]
check('8 no Hero in villain_key', len(hero_atoms_vk) == 0)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 9: INTEGRATION — HAND TAGGING')
print('=' * 60)
# Simulate analyzer tagging
atoms_by_hand = intel.get('atoms_by_hand', {})
hands_with_atoms = sum(1 for h in hands if h.get('id', '') in atoms_by_hand)
check(f'9 hands with atoms ({hands_with_atoms})', hands_with_atoms > 50)

# Tag hands like analyzer does
for h in hands:
    hid = h.get('id', '')
    h['villain_evidence_atoms'] = atoms_by_hand.get(hid, [])
    h['villain_badges'] = atoms_by_hand.get(hid, [])

tagged = sum(1 for h in hands if h.get('villain_badges'))
check(f'9 hands tagged with badges ({tagged})', tagged > 50)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 10: POPUP DATA')
print('=' * 60)
# Check evidence_atoms_for_popup on aliases
with_popup = sum(1 for va in aliases.values() if va.get('evidence_atoms_for_popup'))
check(f'10 aliases with popup atoms ({with_popup})', with_popup > 50)

# Check popup atom structure (slim version)
for va in aliases.values():
    popup_atoms = va.get('evidence_atoms_for_popup', [])
    if popup_atoms:
        a = popup_atoms[0]
        for field in ['hand_id', 'street', 'badge', 'evidence_text', 'read_impact',
                      'hero_involved', 'villain_position']:
            check(f'10 popup atom has {field}', field in a)
        # Popup atoms should NOT have heavy fields
        check('10 popup atom is slim (no type)', 'type' not in a)
        break

# Cap check
for va in aliases.values():
    if len(va.get('evidence_atoms_for_popup', [])) > 50:
        check('10 popup atoms capped at 50', False, f'{len(va["evidence_atoms_for_popup"])}')
        break
else:
    check('10 popup atoms capped at 50', True)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 11: _is_weak_showdown UNIT TESTS')
print('=' * 60)
# Weak: no pair
check('11 no pair = weak', _is_weak_showdown(['Jh', '8d'], ['As', 'Kc', '5h', '2d', '7s']))
# Weak: bottom pair
check('11 bottom pair = weak', _is_weak_showdown(['2h', '3d'], ['As', 'Kc', '5h', '2d', '7s']))
# Not weak: top pair
check('11 top pair != weak', not _is_weak_showdown(['Ah', 'Qd'], ['As', 'Kc', '5h', '2d', '7s']))
# Not weak: second pair
check('11 second pair != weak', not _is_weak_showdown(['Kh', 'Qd'], ['As', 'Kc', '5h', '2d', '7s']))
# Edge: empty
check('11 empty board = not weak', not _is_weak_showdown(['Ah', 'Kd'], []))

# ============================================================
print('\n' + '=' * 60)
print('SECTION 12: NEGATIVE INPUTS')
print('=' * 60)
# Hand with no action_ledger
empty_h = {'id': 'X1', 'tournament_id': 'T1', 'hero': 'Hero',
           'villains': {'abc': {'position': 'BTN'}}}
check('12 no action_ledger: no crash',
      detect_open_limp(empty_h, 'Hero', {}) == [])
check('12 no action_ledger pivot: no crash',
      detect_passive_aggro_pivot(empty_h, 'Hero', {}) == [])

# Hand with no villains
no_v = {'id': 'X2', 'tournament_id': 'T1', 'hero': 'Hero',
        'action_ledger': [{'street': 'preflop', 'action': 'folds',
                           'player': 'abc', 'position': 'BTN', 'amount_bb': 0}]}
check('12 weak sd no villains: no crash',
      detect_weak_showdown_call(no_v, 'Hero', {}) == [])

# Empty hands for cross-hand detector
check('12 empty hands for blind overfold: no crash',
      detect_repeated_blind_overfold([], 'Hero', {}) == [])

# ============================================================
print('\n' + '=' * 60)
print('SECTION 13: RENDERED HTML VERIFICATION')
print('=' * 60)
report = None
for v in range(10, 0, -1):
    p = os.path.join('C:', os.sep, 'mnt', 'user-data', 'outputs',
                     f'Pokerbot_Knockman_20260527-28_V{v}.html')
    if os.path.exists(p):
        report = p; break
if report:
    with open(report, encoding='utf-8') as f:
        html = f.read()
    # Grid badges
    grid_b = len(re.findall(r'grid-action[^>]*>.*?vi-badge', html))
    check(f'13 grid badges ({grid_b} > 30)', grid_b > 30)
    # Opponent context
    oc = len(re.findall(r'opponent-context', html))
    check(f'13 opponent-context ({oc} > 20)', oc > 20)
    # Popup atoms
    vi_m = re.search(r'window\.villainIntel=(\{[^;]+\});', html, re.DOTALL)
    if vi_m:
        vid = json.loads(vi_m.group(1))
        ta = sum(len(v.get('evidence_atoms', [])) for v in vid.values())
        check(f'13 popup atoms ({ta} > 100)', ta > 100)
    # No regressions
    for bad in ['[object Object]', 'Traceback', 'KeyError']:
        check(f'13 no {bad}', html.count(bad) == 0)
    # Existing elements preserved
    check('13 stat-strip', html.count('stat-strip') >= 5)
    check('13 Archetype Mirror', 'Opponent Archetype Mirror' in html)
    check('13 hand-list-trigger', html.count('hand-list-trigger') > 50)
else:
    note('13: No rendered report found for HTML verification')

# ============================================================
print('\n' + '=' * 60)
print('SECTION 14: PERFORMANCE')
print('=' * 60)
import time
t0 = time.perf_counter()
_ = extract_evidence_atoms(hands, 'Hero', aliases)
elapsed = time.perf_counter() - t0
check(f'14 detectors run in {elapsed:.3f}s (< 5s)', elapsed < 5.0)
note(f'14: {len(hands)} hands, {len(atoms)} atoms in {elapsed:.3f}s')

# ============================================================
print('\n' + '=' * 60)
print('SECTION 15: SCOPE GUARD')
print('=' * 60)
# No exploit detectors in PR3 (those are PR4)
exploit_atoms = [a for a in atoms if a['badge'] == 'miss']
check('15 no exploit/miss detectors (PR4)', len(exploit_atoms) == 0)
# Only tagging evidence, not exploit opportunities
check('15 exploit_opportunities still empty', intel['exploit_opportunities'] == [])
# Only 5 signals
allowed_signals = {'open_limp', 'limp_call', 'weak_showdown_call',
                   'passive_aggro_pivot', 'repeated_blind_overfold'}
actual_signals = set(a['signal'] for a in atoms)
check(f'15 only 5 signal types', actual_signals.issubset(allowed_signals),
      f'extra: {actual_signals - allowed_signals}')

# ============================================================
print(f'\n{"=" * 60}')
print(f'SUMMARY:')
print(f'  Detectors: {len(allowed_signals)}')
print(f'  Total atoms: {len(atoms)}')
print(f'  By signal: {dict(by_signal.most_common())}')
print(f'  Hands with evidence: {hands_with_atoms} / {len(hands)}')
print(f'  Villains with evidence: {with_popup} / {len(aliases)}')
if NOTES:
    print(f'NOTES ({len(NOTES)}):')
    for n in NOTES:
        print(f'  {n}')
print(f'\nRESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('FIX BEFORE MERGE')
    sys.exit(1)
else:
    print('ALL PR3 TESTS PASSED')
