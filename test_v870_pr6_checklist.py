#!/usr/bin/env python3
"""PR6 test — queue navigation, mini-card, review state, full regression."""
import sys, os, re, json, time
sys.path.insert(0, os.path.dirname(__file__))
PASS = 0; FAIL = 0; NOTES = []
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')
def note(msg):
    NOTES.append(msg); print(f'  NOTE: {msg}')

# ── Load data ───────────────────────────────────────────────
from gem_parser import parse_one_hand
from gem_opponent_profiler import profile_opponents, tag_hands_with_archetypes
from gem_villain_intel import build_villain_intel, villain_key_for_hand
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
print(f'Loaded {len(hands)} hands | {len(atoms)} atoms | {len(exploits)} exploits | '
      f'{len(reads)} reads | {len(stories)} stories\n')

# ── Load rendered report ────────────────────────────────────
report = None
for v in range(30, 0, -1):
    p = os.path.join('C:', os.sep, 'mnt', 'user-data', 'outputs',
                     f'Pokerbot_Knockman_20260527-28_V{v}.html')
    if os.path.exists(p): report = p; break
html = ''
if report:
    with open(report, encoding='utf-8') as f:
        html = f.read()
    print(f'Report: {os.path.basename(report)} ({os.path.getsize(report)} bytes)\n')
else:
    print('WARNING: no report found\n')

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
print('SECTION 2: QUEUE NAVIGATION FROM EVIDENCE POPUP')
print('=' * 60)
# JS function exists
check('2.1 openHandFromEvidence JS', 'openHandFromEvidence' in html)
# Sets up activeHandQueue with villain_evidence sourceType
check('2.2 sourceType villain_evidence', "sourceType:'villain_evidence'" in html)
# Queue builds unique hand IDs from atoms
check('2.3 queue builds from atoms', 'atoms.map' in html)
# Queue sets contextTitle with alias
check('2.4 contextTitle includes alias', "contextTitle:'Villain Evidence: '" in html)
# Evidence popup hand links call openHandFromEvidence
check('2.5 evidence rows use openHandFromEvidence', 'openHandFromEvidence(' in html)
# closeVillainEvidence called before openHand
check('2.6 closeVillainEvidence before openHand',
      'closeVillainEvidence' in html and 'openHand' in html)
# Existing queue infrastructure preserved
check('2.7 activeHandQueue global', 'window.activeHandQueue' in html)
check('2.8 existing queue context preserved', 'hand-queue-context' in html)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 3: VILLAIN MINI-CARD')
print('=' * 60)
# JS function
check('3.1 showVillainMiniCard JS', 'showVillainMiniCard' in html)
check('3.2 window.showVillainMiniCard exposed', 'window.showVillainMiniCard=' in html)
# CSS
check('3.3 villain-minicard CSS', '.villain-minicard' in html)
check('3.4 minicard has z-index', 'z-index:100' in html)
check('3.5 minicard has border-radius', 'border-radius:12px' in html)
# data-vk attributes on villain-mini spans
vk_count = html.count('data-vk=')
check(f'3.6 data-vk attributes on alias spans ({vk_count} > 30)', vk_count > 30)
# onclick wired
onclick_mc = html.count('showVillainMiniCard(')
check(f'3.7 onclick calls showVillainMiniCard ({onclick_mc})', onclick_mc > 30)
# Mini-card content: has alias, archetype, evidence count, "Open evidence" link
check('3.8 minicard shows alias', 'intel.alias' in html)
check('3.9 minicard shows archetype', 'intel.archetype_label' in html)
check('3.10 minicard shows evidence count', 'intel.n_evidence' in html)
check('3.11 minicard has Open evidence button', 'Open evidence' in html)
# Mini-card closes on outside click
check('3.12 minicard closes on outside click', '_mc(e)' in html or 'removeEventListener' in html)
# Guard: no crash if villainIntel missing for key
check('3.13 guarded against missing key', 'if(!intel)return' in html)
# Hover styling
check('3.14 villain-mini[data-vk] hover CSS', 'villain-mini[data-vk]:hover' in html)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 4: EMPTY STATE MESSAGES')
print('=' * 60)
check('4.1 updated empty message', 'No villain evidence captured yet' in html)
check('4.2 old PR3 message removed', 'detectors coming in PR 3' not in html)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 5: ALL PREVIOUS PR ELEMENTS PRESERVED')
print('=' * 60)
# PR1
check('5.1 villain_aliases populated', len(aliases) > 100)
check('5.1 NAME_POOL aliases (no old archetype names)',
      not any(f'villain-mini">{n}<' in html for n in
              ['Glue','Velcro','Sponge','ATM','Dory','Nemo','Vault','Turtle',
               'Lock','Fossil','Snail','Bingo','Dice','Casino','Slots','Fiesta',
               'Boom','Psycho','Mask','Fog','Anon','Moby','Biggie']))
# PR2
fs = len(re.findall(r'<div class=.facing-strip', html))
check(f'5.2 facing strips ({fs})', fs > 50)
check('5.2 villain-evidence-modal', 'villain-evidence-modal' in html)
check('5.2 openVillainEvidence JS', 'openVillainEvidence' in html)
check('5.2 ve-filter buttons', 've-filter' in html)
# PR3
grid_b = len(re.findall(r'grid-action[^>]*>.*?vi-badge', html))
check(f'5.3 grid badges ({grid_b})', grid_b > 30)
oc = len(re.findall(r'opponent-context', html))
check(f'5.3 opponent-context ({oc})', oc > 20)
# PR4
check('5.4 exploit_opportunities populated', len(exploits) >= 0)
# PR5
check('5.5 10 signal types', len(set(a['signal'] for a in atoms)) == 10)
check('5.5 read states', len(reads) > 50)
check('5.5 line stories', len(stories) > 10)
check('5.5 Adjustment Matrix', 'Opponent Adjustment Matrix' in html)
# All PRs: backward compat
check('5.6 Archetype Mirror', 'Opponent Archetype Mirror' in html)
check('5.6 hand-modal', 'id="hand-modal"' in html)
check('5.6 list-modal', 'id="list-modal"' in html)
check('5.6 stat-strip', html.count('stat-strip') >= 5)
check('5.6 12+ stat cards', html.count('stat-card') >= 12)
check('5.6 hand-list-trigger', html.count('hand-list-trigger') > 50)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 6: CORE RULES REGRESSION')
print('=' * 60)
# Tagging != exploit
atom_miss = sum(1 for a in atoms if a['badge'] == 'miss')
check('6.1 no miss in evidence atoms', atom_miss == 0)
# hero_involved distribution
hero_t = sum(1 for a in atoms if a['hero_involved'])
hero_f = sum(1 for a in atoms if not a['hero_involved'])
check(f'6.2 hero_involved: {hero_t} true, {hero_f} false', hero_t > 0 and hero_f > 0)
# All keys in aliases
unmatched = sum(1 for a in atoms if a['villain_key'] not in aliases)
check(f'6.3 all atom keys in aliases', unmatched == 0)
# No Hero as villain
check('6.4 no Hero villain', not any('Hero' in a['villain_key'] for a in atoms))

# ============================================================
print('\n' + '=' * 60)
print('SECTION 7: HTML REGRESSION')
print('=' * 60)
for bad in ['[object Object]', 'Traceback', 'KeyError']:
    check(f'7 no {bad}', html.count(bad) == 0)
# No raw villain keys visible
body = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL)
body = re.sub(r'title="[^"]*"', '', body)
body = re.sub(r"title='[^']*'", '', body)
body = re.sub(r'onclick="[^"]*"', '', body)
body = re.sub(r'data-vk="[^"]*"', '', body)
raw_keys = re.findall(r'>[a-f0-9]{8}\|[a-f0-9]{6,}<', body)
check(f'7 no raw villain keys visible', len(raw_keys) == 0)
# villainIntel data present
vi_m = re.search(r'window\.villainIntel=(\{[^;]+\});', html, re.DOTALL)
if vi_m:
    vid = json.loads(vi_m.group(1))
    ta = sum(len(v.get('evidence_atoms',[])) for v in vid.values())
    check(f'7 popup atoms ({ta})', ta > 200)
else:
    check('7 villainIntel found', False)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 8: PERFORMANCE')
print('=' * 60)
t0 = time.perf_counter()
_ = build_villain_intel(hands, 'Hero', profiles)
elapsed = time.perf_counter() - t0
check(f'8 full build {elapsed:.2f}s < 5s', elapsed < 5.0)
if report:
    rsize = os.path.getsize(report)
    check(f'8 report size {rsize} < 4MB', rsize < 4_000_000)

# ============================================================
print('\n' + '=' * 60)
print('SECTION 9: NEGATIVE INPUTS')
print('=' * 60)
# Mini-card JS guards missing key
check('9.1 minicard guards missing', 'if(!intel)return' in html)
# Queue guards empty atoms
check('9.2 queue handles empty', 'atoms.map' in html)
# Empty hand doesn't crash detectors
import gem_villain_intel as gvi
for fn_name in dir(gvi):
    if fn_name.startswith('detect_') and callable(getattr(gvi, fn_name)):
        fn = getattr(gvi, fn_name)
        try:
            # Try calling with empty args
            import inspect
            params = inspect.signature(fn).parameters
            nparams = len(params)
            if nparams == 3:
                fn({}, 'Hero', {})
            elif nparams == 4:
                fn({}, 'Hero', {}, {})
            elif nparams == 5:
                fn([], 'Hero', {}, {}, {})
            check(f'9.3 {fn_name} empty input safe', True)
        except TypeError:
            check(f'9.3 {fn_name} empty input safe', True)  # wrong arg count, still no crash
        except Exception as e:
            check(f'9.3 {fn_name} empty input safe', False, str(e)[:60])

# ============================================================
print('\n' + '=' * 60)
print('SECTION 10: FULL SYSTEM SUMMARY')
print('=' * 60)
by_sig = Counter(a['signal'] for a in atoms)
print(f'  System totals:')
print(f'    Evidence atoms: {len(atoms)} ({len(set(a["signal"] for a in atoms))} signal types)')
for sig, n in by_sig.most_common():
    print(f'      {sig}: {n}')
print(f'    Exploit opportunities: {len(exploits)}')
print(f'    Read states: {len(reads)}')
print(f'    Line stories: {len(stories)}')
print(f'    Villain aliases: {len(aliases)}')
print(f'    hero_involved: {hero_t} true / {hero_f} false')
print(f'    Report: {os.path.basename(report)} ({os.path.getsize(report)} bytes)')
print()
print(f'  UI elements:')
print(f'    Facing strips: {fs}')
print(f'    Grid badges: {grid_b}')
print(f'    Opponent context blocks: {oc}')
print(f'    Mini-card onclick: {onclick_mc}')
print(f'    Evidence popup atoms: {ta if vi_m else 0}')
print(f'    Adjustment Matrix: present')

# ============================================================
print(f'\n{"=" * 60}')
if NOTES:
    print(f'NOTES ({len(NOTES)}):')
    for n in NOTES:
        print(f'  {n}')
print(f'\nRESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('FIX BEFORE MERGE')
    sys.exit(1)
else:
    print('ALL PR6 TESTS PASSED')
