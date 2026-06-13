#!/usr/bin/env python3
"""PR 1 verification: Identity + alias + data contract for Opponent Intelligence."""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
PASS = 0; FAIL = 0
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')

# ============================================================
print('=== 1. SYNTAX ===')
import py_compile
for f in ['gem_villain_intel.py', 'gem_analyzer.py', 'gem_opponent_profiler.py',
          'gem_report_draft/sections_xiv.py']:
    try:
        py_compile.compile(f, doraise=True); check(f'syntax {f}', True)
    except py_compile.PyCompileError as e:
        check(f'syntax {f}', False, str(e)[:80])

# ============================================================
print('\n=== 2. NAME_POOL ===')
from gem_villain_intel import NAME_POOL, _OVERFLOW_POOL, BADGES
check(f'NAME_POOL has 108 entries', len(NAME_POOL) == 108, f'got {len(NAME_POOL)}')
check('all unique names', len(set(NAME_POOL)) == len(NAME_POOL))
check('overflow pool exists', len(_OVERFLOW_POOL) >= 40)
# No archetype names
BAD = {'Fish', 'Whale', 'Nit', 'Station', 'Maniac', 'TAG', 'LAG'}
check('no archetype names', not (BAD & set(NAME_POOL)))

# ============================================================
print('\n=== 3. STABLE_ALIAS ===')
from gem_villain_intel import stable_alias, _stable_hash
# Deterministic
a1 = stable_alias('288240360|3dcb37e4')
a2 = stable_alias('288240360|3dcb37e4')
check('stable_alias deterministic', a1 == a2)
# Different keys → mostly different aliases
aliases_20 = set(stable_alias(f'T{i}|p{i}') for i in range(20))
check(f'alias diversity: {len(aliases_20)}/20 unique', len(aliases_20) >= 15)
# Cross-platform: MD5 is deterministic
h = _stable_hash('test_key')
check('_stable_hash is int', isinstance(h, int))
check('_stable_hash > 0', h > 0)

# ============================================================
print('\n=== 4. BADGES ===')
check('4 badge types', len(BADGES) == 4)
for badge_code in ('note', 'pivot', 'miss', 'good'):
    b = BADGES.get(badge_code, {})
    check(f'{badge_code} has emoji', bool(b.get('emoji')))
    check(f'{badge_code} has label', bool(b.get('label')))

# ============================================================
print('\n=== 5. BUILD_VILLAIN_KEYS ===')
from gem_villain_intel import build_villain_keys, assign_aliases
mock = [
    {'id': 'H1', 'tournament_id': 'T100', 'villains': {
        'abc': {'position': 'BTN'}, 'def': {'position': 'SB'}},
     'primary_villain': {'name': 'abc', 'role': 'opener'}},
    {'id': 'H2', 'tournament_id': 'T100', 'villains': {
        'abc': {'position': 'CO'}, 'ghi': {'position': 'BB'}},
     'primary_villain': {'name': 'abc', 'role': 'opener'}},
]
vkeys = build_villain_keys(mock)
check('3 villain keys', len(vkeys) == 3)
check('abc 2 hands', vkeys['T100|abc']['n_hands'] == 2)
check('abc 2 positions', len(vkeys['T100|abc']['positions_seen']) == 2)

# ============================================================
print('\n=== 6. ASSIGN_ALIASES ===')
aliases = assign_aliases(vkeys)
check('3 aliases', len(aliases) == 3)
# V01 should be abc (most hands)
v01 = next((v for v in aliases.values() if v['v_number'] == 'V01'), None)
check('V01 is most frequent', v01['player_hash'] == 'abc')
# All unique
names = [v['alias'] for v in aliases.values()]
check('all aliases unique', len(names) == len(set(names)))
# Display format
check('display has · V', ' · V' in v01['display'])

# ============================================================
print('\n=== 7. COLLISION HANDLING ===')
# Find a colliding key
idx0 = _stable_hash('T100|abc') % len(NAME_POOL)
collider = None
for i in range(100000):
    k = f'T{i}|Z'
    if _stable_hash(k) % len(NAME_POOL) == idx0 and k != 'T100|abc':
        collider = k; break
if collider:
    test_vk = {
        'T100|abc': {'player_hash': 'abc', 'tournament_id': 'T100',
                     'positions_seen': set(), 'hand_ids': [], 'n_hands': 5},
        collider: {'player_hash': 'Z', 'tournament_id': str(collider.split('|')[0][1:]),
                   'positions_seen': set(), 'hand_ids': [], 'n_hands': 3},
    }
    coll_aliases = assign_aliases(test_vk)
    a_set = {v['alias'] for v in coll_aliases.values()}
    check('collision gives unique aliases', len(a_set) == 2)
else:
    check('SKIP collision test', True)

# ============================================================
print('\n=== 8. VILLAIN_KEY_FOR_HAND ===')
from gem_villain_intel import villain_key_for_hand
vk = villain_key_for_hand(mock[0])
check('villain_key format', vk == 'T100|abc')
check('no pv → empty string', villain_key_for_hand({'tournament_id': 'T1'}) == '')

# ============================================================
print('\n=== 9. BUILD_VILLAIN_INTEL ===')
from gem_villain_intel import build_villain_intel
intel = build_villain_intel(mock, 'Hero')
check('has villain_aliases', 'villain_aliases' in intel)
check('has evidence_atoms (empty)', intel['evidence_atoms'] == [])
check('has line_stories (empty)', intel['line_stories'] == [])
check('has read_states (empty)', intel['read_states'] == {})
check('has exploit_opportunities (empty)', intel['exploit_opportunities'] == [])
check('has hand_villain_keys', len(intel['hand_villain_keys']) == 2)
check('has queue_context_template', 'source_type' in intel['queue_context_template'])

# ============================================================
print('\n=== 10. DATA CONTRACT TEMPLATES ===')
from gem_villain_intel import (_empty_evidence_atom, _empty_line_story,
                                _empty_read_state, _empty_exploit_opportunity,
                                _empty_queue_context)
ea = _empty_evidence_atom()
check('evidence_atom has same_hand_actionable', 'same_hand_actionable' in ea)
check('evidence_atom has available_before_action_index', 'available_before_action_index' in ea)
check('evidence_atom has hero_involved', 'hero_involved' in ea)
check('evidence_atom has action_index', 'action_index' in ea)
ls = _empty_line_story()
check('line_story has sequence', isinstance(ls['sequence'], list))
rs = _empty_read_state()
check('read_state has dimensions', 'loose' in rs['dimensions'])
eo = _empty_exploit_opportunity()
check('exploit has severity', eo['severity'] == 'C')
qc = _empty_queue_context()
check('queue has source_type', qc['source_type'] == '')
check('queue has hand_ids', isinstance(qc['hand_ids'], list))

# ============================================================
print('\n=== 11. ANALYZER INTEGRATION (static check) ===')
with open('gem_analyzer.py', encoding='utf-8') as f:
    az = f.read()
check('imports build_villain_intel', 'from gem_villain_intel import build_villain_intel' in az)
check('imports villain_key_for_hand', 'villain_key_for_hand' in az)
check('sets primary_villain_key', "h['primary_villain_key']" in az)
check('sets villain_badges', "h['villain_badges']" in az)
check('sets villain_evidence_atoms', "h['villain_evidence_atoms']" in az)
check('sets exploit_opportunities', "h['exploit_opportunities']" in az)
check('old _ALIAS_POOLS removed', '_ALIAS_POOLS' not in az)
check('neutral aliases label in output', 'neutral aliases' in az)

# ============================================================
print('\n=== 12. RENDERER BACKWARD COMPAT (static check) ===')
with open('gem_report_draft/sections_xiv.py', encoding='utf-8') as f:
    sx = f.read()
check('villain_key in tooltip', 'villain key:' in sx)
check('primary_villain_key used for evidence lookup', 'primary_villain_key' in sx)
check('fallback to position-based lookup preserved', 'stacks_behind' in sx)

# ============================================================
print(f'\n{"="*60}')
print(f'RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('FIX BEFORE PROCEEDING')
    sys.exit(1)
else:
    print('PR 1 VERIFICATION PASSED')
