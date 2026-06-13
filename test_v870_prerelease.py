#!/usr/bin/env python3
"""v8.7.0 pre-release gate — complete system verification."""
import sys, os, re, json, time
sys.path.insert(0, os.path.dirname(__file__))
PASS = 0; FAIL = 0
def check(l, c, d=''):
    global PASS, FAIL
    if c: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {l} -- {d}')

# === 1. SYNTAX ===
print('=== 1. SYNTAX ===')
import py_compile
files = [
    'gem_villain_intel.py', 'gem_analyzer.py', 'gem_parser.py',
    'gem_phase.py', 'gem_bounty.py', 'gem_tier_handicaps.py',
    'gem_opponent_profiler.py', 'gem_summary_parser.py',
    'gem_report_data.py', 'gem_run.py',
    'gem_report_draft/draft.py', 'gem_report_draft/_html.py',
    'gem_report_draft/_hand_grid.py', 'gem_report_draft/_helpers.py',
    'gem_report_draft/sections_iv_xii.py', 'gem_report_draft/sections_xiv.py',
    'gem_report_draft/sections_xiii.py', 'gem_report_draft/sections_financial.py',
    'gem_report_draft/sections_issue_explorer.py', 'gem_report_draft/tldr.py',
]
for f in files:
    if os.path.exists(f):
        try:
            py_compile.compile(f, doraise=True); check(f'syntax {f}', True)
        except py_compile.PyCompileError as e:
            check(f'syntax {f}', False, str(e)[:80])

# === 2. EXISTING MODULES ===
print('\n=== 2. EXISTING MODULES ===')
from gem_phase import monotonic_smooth, snap_to_standard, icm_pressure, _derive_legacy
check('monotonic_smooth', monotonic_smooth([100, 50], 1, 100, 5) == [100, 5])
check('snap 9800->10000', snap_to_standard(9800) == 10000)
check('icm HU=0', icm_pressure('in_money', 0.01, 0.15, 'hu') == 0.0)
check('icm FT>=0.85', icm_pressure('in_money', 0.05, 0.15, 'final_table') >= 0.85)

from gem_bounty import bounty_value_bb
flat = bounty_value_bb('Test PKO', 'post_reg', 'BOUNTY', True)
check(f'bounty flat ({flat})', isinstance(flat, (int, float)) and flat > 0)
ratio = bounty_value_bb('Test PKO', 'post_reg', 'BOUNTY', True,
                         bounty_ratio=0.5, eff_stack_bb=30, starting_stack_bb=100)
check(f'bounty ratio ({ratio})', isinstance(ratio, (int, float)) and ratio > 0)

from gem_tier_handicaps import MIN_PAIRINGS
check('MIN_PAIRINGS=3', MIN_PAIRINGS == 3)

from gem_analyzer import load_ranges
r = load_ranges('Poker_Ranges_Text.txt')
check(f'ranges: {len(r)} >= 380', len(r) >= 380)

with open('tournament_structures.json', encoding='utf-8') as f:
    structs = json.load(f)
check('GGMasters 10000',
      structs.get('name_overrides', {}).get('GGMasters Bounty', {}).get('starting_chips') == 10000)

# === 3. VILLAIN INTEL ===
print('\n=== 3. VILLAIN INTEL ===')
from gem_villain_intel import (NAME_POOL, BADGES, stable_alias, build_villain_intel,
    _is_weak_showdown, _build_read_states, _build_line_stories)
check('NAME_POOL==108', len(NAME_POOL) == 108)
check('4 badges', len(BADGES) == 4)
check('stable_alias deterministic', stable_alias('x') == stable_alias('x'))
check('no archetype in pool',
      not any(n in NAME_POOL for n in ['Fish','Whale','Nit','Station','Maniac','TAG','LAG']))

from gem_parser import parse_one_hand
from gem_opponent_profiler import profile_opponents, tag_hands_with_archetypes
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

atoms = intel['evidence_atoms']
exploits = intel['exploit_opportunities']
reads = intel['read_states']
stories = intel['line_stories']
aliases = intel['villain_aliases']
by_sig = Counter(a['signal'] for a in atoms)

check(f'aliases ({len(aliases)}) > 100', len(aliases) > 100)
check(f'atoms ({len(atoms)}) > 100', len(atoms) > 100)
check(f'signals: {len(by_sig)}/10', len(by_sig) == 10)
check(f'exploits ({len(exploits)}) >= 0', len(exploits) >= 0)
check(f'reads ({len(reads)}) > 50', len(reads) > 50)
check(f'stories ({len(stories)}) > 10', len(stories) > 10)
check('tagging != exploit', sum(1 for a in atoms if a['badge'] == 'miss') == 0)
hero_f = sum(1 for a in atoms if not a['hero_involved'])
check(f'hero_involved=false ({hero_f})', hero_f > 0)
check('atoms JSON', bool(json.dumps(atoms[:5], default=str)))
check('exploits JSON', bool(json.dumps(exploits[:5], default=str)))
check('reads JSON', bool(json.dumps(dict(list(reads.items())[:3]), default=str)))
check('stories JSON', bool(json.dumps(stories[:5], default=str)))

t0 = time.perf_counter()
_ = build_villain_intel(hands, 'Hero', profiles)
elapsed = time.perf_counter() - t0
check(f'perf ({elapsed:.2f}s < 5s)', elapsed < 5.0)

# === 4. RENDERED REPORT ===
print('\n=== 4. RENDERED REPORT ===')
report = None
for v in range(30, 0, -1):
    p = os.path.join('C:', os.sep, 'mnt', 'user-data', 'outputs',
                     f'Pokerbot_Knockman_20260527-28_V{v}.html')
    if os.path.exists(p):
        report = p; break
if report:
    with open(report, encoding='utf-8') as f:
        html = f.read()
    rsize = os.path.getsize(report)
    check(f'report size ({rsize})', rsize > 2_000_000)
    check('facing-strip', len(re.findall(r'facing-strip', html)) > 50)
    check('grid badges', len(re.findall(r'grid-action[^>]*>.*?vi-badge', html)) > 30)
    check('opponent-context', html.count('opponent-context') > 20)
    check('villain-evidence-modal', 'villain-evidence-modal' in html)
    check('openVillainEvidence', 'openVillainEvidence' in html)
    check('openHandFromEvidence', 'openHandFromEvidence' in html)
    check('showVillainMiniCard', 'showVillainMiniCard' in html)
    check('data-vk', html.count('data-vk=') > 30)
    check('Adjustment Matrix', 'Opponent Adjustment Matrix' in html)
    check('Archetype Mirror', 'Opponent Archetype Mirror' in html)
    check('stat-strip', html.count('stat-strip') >= 5)
    check('stat-card >= 12', html.count('stat-card') >= 12)
    check('hand-list-trigger', html.count('hand-list-trigger') > 50)
    check('hand-modal', 'id="hand-modal"' in html)
    check('list-modal', 'id="list-modal"' in html)
    for bad in ['[object Object]', 'Traceback', 'KeyError']:
        check(f'no {bad}', html.count(bad) == 0)
    old_aliases = ['Glue','Velcro','Sponge','ATM','Dory','Nemo','Vault','Turtle',
                   'Lock','Fossil','Snail','Bingo','Dice','Casino','Slots','Fiesta']
    leaked = [n for n in old_aliases if f'villain-mini">{n}<' in html]
    check('no old aliases leaked', len(leaked) == 0, str(leaked))
    vi_m = re.search(r'window\.villainIntel=(\{[^;]+\});', html, re.DOTALL)
    if vi_m:
        vid = json.loads(vi_m.group(1))
        ta = sum(len(v.get('evidence_atoms', [])) for v in vid.values())
        check(f'popup atoms ({ta})', ta > 200)
    # Matrix section has table with data
    mx_idx = html.find('id="sec-5-9"')
    if mx_idx > 0:
        mx_chunk = html[mx_idx:mx_idx+5000]
        check('matrix table', '<table' in mx_chunk)
        check('matrix links', 'hand-list-trigger' in mx_chunk)
else:
    check('report found', False)

# === SUMMARY ===
print(f'\n{"=" * 60}')
print(f'Atoms: {len(atoms)} ({len(by_sig)} signals)')
for sig, n in by_sig.most_common():
    print(f'  {sig}: {n}')
print(f'Exploits: {len(exploits)}')
print(f'Read states: {len(reads)}')
print(f'Line stories: {len(stories)}')
print(f'Aliases: {len(aliases)}')
print(f'hero_involved: {len(atoms)-hero_f} true / {hero_f} false')
print(f'Performance: {elapsed:.2f}s')
if report:
    print(f'Report: {os.path.basename(report)} ({rsize} bytes)')
print(f'\nRESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('FIX BEFORE RELEASE')
    sys.exit(1)
else:
    print('PRE-RELEASE GATE PASSED')
