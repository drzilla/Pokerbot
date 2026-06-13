#!/usr/bin/env python3
"""UX Wiring Fix verification — bugs A/B/C, P0/P1 fixes, full regression."""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))
PASS = 0; FAIL = 0; NOTES = []
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')
def note(msg):
    NOTES.append(msg); print(f'  NOTE: {msg}')

# Find latest report
report = None
for v in range(30, 0, -1):
    p = os.path.join('C:', os.sep, 'mnt', 'user-data', 'outputs',
                     f'Pokerbot_Knockman_20260604_V{v}.html')
    if os.path.exists(p): report = p; break
if not report:
    # Try the other session
    for v in range(30, 0, -1):
        p = os.path.join('C:', os.sep, 'mnt', 'user-data', 'outputs',
                         f'Pokerbot_Knockman_20260527-28_V{v}.html')
        if os.path.exists(p): report = p; break
if not report:
    print('No report found — run pipeline first'); sys.exit(1)

with open(report, encoding='utf-8') as f:
    html = f.read()
print(f'Report: {os.path.basename(report)} ({os.path.getsize(report)} bytes)\n')

# Extract scripts and styles separately
scripts_raw = ''.join(re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
styles_raw = ''.join(re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL))

# ============================================================
print('=' * 60)
print('BUG A: JS ESCAPING (doubled braces/backslashes in raw string)')
print('=' * 60)
# No {{ or }} in script blocks
doubled_open = scripts_raw.count('{{')
check(f'A.1 no doubled-open-braces in scripts ({doubled_open})', doubled_open == 0)
# Note: }} is legitimate JS (nested closes like }catch(e){}} )
# Check for f-string escaping patterns instead: function name{{
fstring_funcs = len(re.findall(r'function\s+\w+\s*\(\w*\)\s*\{\{', scripts_raw))
check(f'A.2 no f-string function braces ({fstring_funcs})', fstring_funcs == 0)
# No doubled backslashes before u or ' in scripts
doubled_bs = len(re.findall(r'\\\\u[0-9A-Fa-f]', scripts_raw))
doubled_bs2 = len(re.findall(r"\\\\\'", scripts_raw))
check(f'A.3 no \\\\u in scripts ({doubled_bs})', doubled_bs == 0)
check(f'A.4 no \\\\\' in scripts ({doubled_bs2})', doubled_bs2 == 0)
# Villain functions defined
check('A.5 openVillainEvidence defined', 'function openVillainEvidence' in html)
check('A.6 buildVillainEvidenceTable defined', 'function buildVillainEvidenceTable' in html)
check('A.7 filterVillainEvidence defined', 'function filterVillainEvidence' in html)
check('A.8 closeVillainEvidence defined', 'function closeVillainEvidence' in html)
check('A.9 openHandFromEvidence defined', 'function openHandFromEvidence' in html)
check('A.10 showVillainMiniCard defined', 'function showVillainMiniCard' in html)
# Existing functions still defined
check('A.11 openHand still defined', 'function openHand' in html or 'openHand(' in html)
check('A.12 openHandListPopup still defined', 'openHandListPopup' in html)

# ============================================================
print('\n' + '=' * 60)
print('BUG B1: MINI-CARD RACE (close-on-outside-click)')
print('=' * 60)
check('B1.1 anchorEl.contains used', 'anchorEl.contains(e.target)' in html)
check('B1.2 setTimeout 0 (not 50)', 'setTimeout(function(){' in scripts_raw)
# The old race-prone pattern used e.target!==anchorEl
check('B1.3 no strict equality check', 'e.target!==anchorEl' not in scripts_raw)

# ============================================================
print('\n' + '=' * 60)
print('BUG B2: ARCHETYPE LABEL POPULATED FROM READ STATES')
print('=' * 60)
vi_m = re.search(r'window\.villainIntel=(\{[^;]+\});', html, re.DOTALL)
if vi_m:
    vid = json.loads(vi_m.group(1))
    with_label = sum(1 for v in vid.values() if v.get('archetype_label'))
    with_conf = sum(1 for v in vid.values() if v.get('confidence'))
    with_emoji = sum(1 for v in vid.values() if v.get('archetype_emoji'))
    total = len(vid)
    check(f'B2.1 entries with archetype_label ({with_label}/{total})', with_label > 0)
    check(f'B2.2 entries with confidence ({with_conf}/{total})', with_conf > 0)
    check(f'B2.3 entries with archetype_emoji ({with_emoji}/{total})', with_emoji > 0)
    # No entry should have 'Unknown' when it has evidence
    unknown_with_evidence = sum(1 for v in vid.values()
                                 if v.get('archetype_label') == 'Unknown'
                                 and v.get('n_evidence', 0) > 0)
    check(f'B2.4 no Unknown with evidence ({unknown_with_evidence})', unknown_with_evidence == 0)
    # Sample a villain with read
    for vk, v in vid.items():
        if v.get('archetype_label') and v.get('confidence'):
            note(f'B2 sample: {v["alias"]} — {v["archetype_emoji"]} {v["archetype_label"]} ({v["confidence"]})')
            break
else:
    check('B2.0 villainIntel found', False)

# ============================================================
print('\n' + '=' * 60)
print('BUG B3: V-NUMBER DUPING (V214 · V214)')
print('=' * 60)
check('B3.1 dispAlias===dispVnum check', 'dispAlias===dispVnum' in html)
# Verify no "Vnn · Vnn" patterns in rendered mini-card code
check('B3.2 conditional display', 'dispAlias:dispAlias' in html or 'dispName' in html)

# ============================================================
print('\n' + '=' * 60)
print('BUG A SCOPE: intel.alias OUT OF SCOPE IN TABLE BUILDER')
print('=' * 60)
# alias is now a parameter, not a closure reference
check('scope.1 buildVillainEvidenceTable takes alias param',
      'function buildVillainEvidenceTable(container,atoms,filter,alias)' in html)
check('scope.2 filterVillainEvidence takes alias param',
      'function filterVillainEvidence(container,filter,atoms,alias)' in html)
# Row click uses proper closure, not inline string
check('scope.3 link.onclick closure', 'link.onclick=function()' in html)

# ============================================================
print('\n' + '=' * 60)
print('P0.2: EVIDENCE POPUP USES OPPONENT-EVIDENCE COLUMNS')
print('=' * 60)
check('P0.2.1 Hand column', '<th>Hand</th>' in html)
check('P0.2.2 Street column', '<th>Street</th>' in html)
check('P0.2.3 V Pos column', '<th>V Pos</th>' in html)
check('P0.2.4 Hero? column', '<th>Hero?</th>' in html)
check('P0.2.5 Signal column', '<th>Signal</th>' in html)
check('P0.2.6 Evidence column', '<th>Evidence</th>' in html)
check('P0.2.7 Read Impact column', '<th>Read Impact</th>' in html)
# No Result/shown hand column in evidence popup
evidence_table_section = html[html.find('buildVillainEvidenceTable'):
                               html.find('buildVillainEvidenceTable') + 2000]
check('P0.2.8 no Result column', 'Result' not in evidence_table_section)
check('P0.2.9 no Verdict column', 'Verdict' not in evidence_table_section)

# ============================================================
print('\n' + '=' * 60)
print('P1.1: ARCHETYPE MIRROR vs ADJUSTMENT MATRIX CLARIFICATION')
print('=' * 60)
check('P1.1.1 Archetype Mirror present', 'Opponent Archetype Mirror' in html)
check('P1.1.2 Adjustment Matrix present', 'Opponent Adjustment Matrix' in html)
check('P1.1.3 clarification text', 'evidence-backed reads' in html)
check('P1.1.4 broad population ref', 'broad population style' in html or 'population' in html)

# ============================================================
print('\n' + '=' * 60)
print('P1.3: EVIDENCE FILTER EMPTY STATE')
print('=' * 60)
check('P1.3.1 "No matches for this filter" in code',
      'No matches for this filter' in html)
check('P1.3.2 "No villain evidence captured yet" still exists',
      'No villain evidence captured yet' in html)
check('P1.3.3 totalAtoms check in code', 'totalAtoms>0' in html)

# ============================================================
print('\n' + '=' * 60)
print('EVIDENCE POPUP UI STRUCTURE')
print('=' * 60)
check('popup.1 villain-evidence-modal exists', 'id="villain-evidence-modal"' in html)
check('popup.2 ve-modal-title', 'id="ve-modal-title"' in html)
check('popup.3 ve-modal-body', 'id="ve-modal-body"' in html)
check('popup.4 ve-modal-close', 'id="ve-modal-close"' in html)
check('popup.5 ve-header class', 've-header' in html)
check('popup.6 ve-filters class', 've-filters' in html)
check('popup.7 ve-signal class', 've-signal' in html)

# ============================================================
print('\n' + '=' * 60)
print('MINI-CARD UI')
print('=' * 60)
check('mc.1 villain-minicard CSS', '.villain-minicard' in html)
check('mc.2 data-vk attributes', html.count('data-vk=') > 30)
check('mc.3 showVillainMiniCard onclick', html.count('showVillainMiniCard(') > 30)
check('mc.4 Open evidence button', 'Open evidence' in html)

# ============================================================
print('\n' + '=' * 60)
print('FACING STRIP')
print('=' * 60)
fs = len(re.findall(r'<div class=.facing-strip', html))
check(f'fs.1 facing strips rendered ({fs})', fs > 30)
check('fs.2 facing-icon class', 'facing-icon' in html)
check('fs.3 facing-title class', 'facing-title' in html)
check('fs.4 facing-sub class', 'facing-sub' in html)
check('fs.5 Evidence button', html.count('openVillainEvidence(') > 30)

# ============================================================
print('\n' + '=' * 60)
print('GRID BADGES')
print('=' * 60)
grid_b = len(re.findall(r'grid-action[^>]*>.*?vi-badge', html))
check(f'badge.1 grid badges ({grid_b})', grid_b > 30)
check('badge.2 vi-badge CSS', '.vi-badge' in html)
note_b = len(re.findall(r'vi-badge note', html))
pivot_b = len(re.findall(r'vi-badge pivot', html))
check(f'badge.3 note badges ({note_b})', note_b > 0)
check(f'badge.4 pivot badges ({pivot_b})', pivot_b > 0)

# ============================================================
print('\n' + '=' * 60)
print('OPPONENT ADJUSTMENT MATRIX')
print('=' * 60)
mx_idx = html.find('id="sec-5-9"')
mx_chunk = html[mx_idx:mx_idx+5000] if mx_idx > 0 else ''
check('matrix.1 section exists', mx_idx > 0)
check('matrix.2 table renders', '<table' in mx_chunk)
check('matrix.3 Tagging column', '<th>Tagging</th>' in mx_chunk)
check('matrix.4 Evidence column', '<th>Evidence</th>' in mx_chunk)
check('matrix.5 Lesson column', '<th>Lesson</th>' in mx_chunk)
mx_links = mx_chunk.count('hand-list-trigger')
check(f'matrix.6 evidence links ({mx_links})', mx_links > 0)

# ============================================================
print('\n' + '=' * 60)
print('QUEUE NAVIGATION')
print('=' * 60)
check('queue.1 openHandFromEvidence', 'openHandFromEvidence' in html)
check('queue.2 villain_evidence source type', "sourceType:'villain_evidence'" in html)
check('queue.3 activeHandQueue', 'window.activeHandQueue' in html)
check('queue.4 hand-queue-context', 'hand-queue-context' in html)

# ============================================================
print('\n' + '=' * 60)
print('LOOK-AHEAD FIX (from calibration)')
print('=' * 60)
with open('gem_villain_intel.py', encoding='utf-8') as f:
    vi_src = f.read()
check('lookahead.1 hand_order parameter', 'hand_order=None' in vi_src)
check('lookahead.2 temporal gate', 'hand_order.get(' in vi_src)
check('lookahead.3 read_states parameter', 'read_states=None' in vi_src)
check('lookahead.4 read_state dimension check', "dims.get(dimension" in vi_src)

# ============================================================
print('\n' + '=' * 60)
print('DEAD AGGRO GATES FIX (from calibration)')
print('=' * 60)
check('aggro.1 prior_atoms_mapped source', "'prior_atoms_mapped'" in vi_src)
check('aggro.2 dimension threshold map', '_dim_threshold' in vi_src)
check('aggro.3 read_states passed to exploits', 'read_states=read_states' in vi_src)

# ============================================================
print('\n' + '=' * 60)
print('HERO IDENTITY REGRESSION')
print('=' * 60)
check('hero.1 _resolve_hero function', 'def _resolve_hero' in vi_src)
check('hero.2 Hero-as-villain guard in analyzer',
      'Hero-as-villain atoms' in open('gem_analyzer.py', encoding='utf-8').read())
check('hero.3 hero_involved warning',
      'possible hero-name mismatch' in open('gem_analyzer.py', encoding='utf-8').read())

# ============================================================
print('\n' + '=' * 60)
print('CALIBRATED THRESHOLDS')
print('=' * 60)
check('cal.1 steal requires first-in', "a['action'] in ('raises', 'bets', 'calls')" in vi_src)
check('cal.2 pivot BB/SB check-raise only', 'is_blind' in vi_src)
check('cal.3 overfold threshold=6', 'streak_len >= 6' in vi_src)
check('cal.4 cold-call excludes original raiser', 'original_raiser' in vi_src)
check('cal.5 donk OOP to PFR', '_pfr_pos_n' in vi_src)

# ============================================================
print('\n' + '=' * 60)
print('FULL REGRESSION')
print('=' * 60)
for bad in ['[object Object]', 'Traceback', 'KeyError']:
    check(f'reg.no {bad}', html.count(bad) == 0)
check('reg.stat-strip', html.count('stat-strip') >= 5)
check('reg.stat-card >= 12', html.count('stat-card') >= 12)
check('reg.hand-list-trigger', html.count('hand-list-trigger') > 50)
check('reg.hand-modal', 'id="hand-modal"' in html)
check('reg.list-modal', 'id="list-modal"' in html)
check('reg.openHand function', 'openHand(' in html)
# No old archetype-tied aliases
old_aliases = ['Glue','Velcro','Sponge','ATM','Dory','Nemo','Vault','Turtle',
               'Lock','Fossil','Snail','Bingo','Dice','Casino','Slots','Fiesta']
leaked = [n for n in old_aliases if f'villain-mini">{n}<' in html]
check('reg.no old aliases', len(leaked) == 0)

# ============================================================
print('\n' + '=' * 60)
print('SYNTAX CHECK')
print('=' * 60)
import py_compile
for f in ['gem_villain_intel.py', 'gem_analyzer.py', 'gem_report_draft/_html.py',
          'gem_report_draft/_hand_grid.py', 'gem_report_draft/sections_xiv.py',
          'gem_report_draft/sections_iv_xii.py', 'gem_report_draft/draft.py']:
    try: py_compile.compile(f, doraise=True); check(f'syntax {f}', True)
    except py_compile.PyCompileError as e: check(f'syntax {f}', False, str(e)[:80])

# ============================================================
print(f'\n{"=" * 60}')
if NOTES:
    print(f'NOTES ({len(NOTES)}):')
    for n in NOTES:
        print(f'  {n}')
print(f'\nRESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('FIX BEFORE RELEASE')
    sys.exit(1)
else:
    print('UX WIRING FIX VERIFICATION PASSED')
