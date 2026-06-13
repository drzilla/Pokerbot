#!/usr/bin/env python3
"""Pre-release gate — run before every version upload.
Catches the recurring bug patterns from the v8.5.x development cycle."""
import sys, os, re, ast, importlib
sys.path.insert(0, os.path.dirname(__file__))

PASS = 0; FAIL = 0
def check(label, condition, detail=''):
    global PASS, FAIL
    if condition: PASS += 1
    else: FAIL += 1; print(f'  FAIL: {label} -- {detail}')

# ============================================================
# 1. SYNTAX CHECK — all Python files
# ============================================================
print('=== 1. Syntax ===')
import py_compile
for root, dirs, files in os.walk('.'):
    if '__pycache__' in root or 'node_modules' in root or 'GEM_v' in root or 'Checkpoint' in root:
        continue
    for f in files:
        if f.endswith('.py') and not f.startswith('test_'):
            path = os.path.join(root, f)
            try:
                py_compile.compile(path, doraise=True)
            except py_compile.PyCompileError as e:
                check(f'syntax {path}', False, str(e)[:80])

# ============================================================
# 2. IMPORT SMOKE TEST — catch ImportError at module level
# ============================================================
print('=== 2. Import smoke ===')
for mod in ['gem_analyzer', 'gem_parser', 'gem_issue_collector',
            'gem_report_draft.draft', 'gem_report_draft._html',
            'gem_report_draft._helpers', 'gem_report_draft.sections_financial',
            'gem_report_draft.sections_iv_xii', 'gem_report_draft.sections_xiv',
            'gem_report_draft.sections_xiii', 'gem_report_draft.tldr',
            'gem_report_draft.sections_issue_explorer']:
    try:
        importlib.import_module(mod)
        check(f'import {mod}', True)
    except Exception as e:
        check(f'import {mod}', False, f'{type(e).__name__}: {e}')

# ============================================================
# 3. VERSION CONSISTENCY
# ============================================================
print('=== 3. Version ===')
with open('gem_report_draft/draft.py', encoding='utf-8') as f:
    ver_match = re.search(r'VERSION\s*=\s*["\']v([\d.]+)', f.read())
ver = ver_match.group(1) if ver_match else '?'
print(f'  Version: v{ver}')

with open('GEM_Quick_Reference.txt', encoding='utf-8') as f:
    qr = f.read()
check('Quick Reference matches', f'v{ver}' in qr, f'v{ver} not found')

with open('GEM_Changelog.txt', encoding='utf-8') as f:
    cl = f.read()
check('Changelog has version', f'v{ver}' in cl[:500], f'v{ver} not in first 500 chars')

# ============================================================
# 4. NO BARE try/except:pass ON IMPORTS (silent failure pattern)
# ============================================================
print('=== 4. Silent import failures ===')
for root, dirs, files in os.walk('gem_report_draft'):
    for f in files:
        if not f.endswith('.py'): continue
        path = os.path.join(root, f)
        with open(path, encoding='utf-8') as fh:
            lines = fh.readlines()
        for i, line in enumerate(lines):
            if 'except' in line and 'pass' in line:
                # Check if this is an import try/except:pass with no fallback
                context = ''.join(lines[max(0,i-5):i+1])
                if 'import' in context and 'lambda' not in context and '= None' not in context and "= ''" not in context:
                    check(f'{path}:{i+1} import swallowed', False,
                          'try/except:pass on import with no fallback binding')

# ============================================================
# 5. RANGE CHART LOADING
# ============================================================
print('=== 5. Range charts ===')
try:
    from gem_analyzer import load_ranges
    r = load_ranges('Poker_Ranges_Text.txt')
    check(f'charts loaded: {len(r)}', len(r) >= 380, f'got {len(r)}, expected >= 380')
    # Check key families exist
    for prefix, min_count in [('3BF_', 50), ('SQF_', 30), ('SBD_', 30),
                               ('BBD_', 10), ('RJ_', 15), ('F4B_', 15)]:
        n = sum(1 for k in r if k.startswith(prefix))
        check(f'{prefix}* charts: {n} >= {min_count}', n >= min_count)
except Exception as e:
    check('range loading', False, str(e))

# ============================================================
# 6. DATA FORMAT CONTRACTS — variance_outcomes consumers handle both formats
# ============================================================
print('=== 6. Data contracts ===')
renderer_files = ['gem_report_draft/sections_financial.py',
                  'gem_report_draft/sections_xiii.py',
                  'gem_report_draft/sections_xiv.py']
for rf in renderer_files:
    if not os.path.exists(rf): continue
    with open(rf, encoding='utf-8') as f:
        src = f.read()
    if 'variance_outcomes' in src:
        check(f'{rf} normalizes variance_outcomes',
              'isinstance' in src and '_voc_raw' in src,
              'uses variance_outcomes without isinstance dict check')

# ============================================================
# 7. INITIATIVE CHECK — no raw pfr for c-bet in 3BP
# ============================================================
print('=== 7. Initiative gate ===')
with open('gem_analyzer.py', encoding='utf-8') as f:
    az = f.read()
# Count sites where pfr is used as c-bet gate
pfr_cbet_sites = []
for i, line in enumerate(az.split('\n')):
    if ("h.get('pfr')" in line or "h['pfr']" in line) and ('cbet' in az.split('\n')[max(0,i-3):i+4].__repr__().lower() or 'missed_cbet' in line):
        pfr_cbet_sites.append(i+1)
# The only allowed pfr check should be inside an initiative predicate, not standalone
# We can't perfectly detect this statically, but we can flag any raw pfr near c-bet
if pfr_cbet_sites:
    # Check if they're inside _has_initiative blocks
    for line_no in pfr_cbet_sites:
        context = '\n'.join(az.split('\n')[max(0,line_no-8):line_no+2])
        if '_has_init' not in context and 'pot_type' not in context:
            check(f'line {line_no}: raw pfr for c-bet (no initiative check)',
                  False, 'should use _has_initiative or pot_type gate')

# ============================================================
# 8. MODULE-LEVEL FUNCTIONS — check _open_chart_pos is accessible
# ============================================================
print('=== 8. Function scope ===')
# Functions that must be module-level (not nested inside another function)
required_module_level = ['_open_chart_pos', '_depth_tier_open', '_chart_pos', 'load_ranges']
tree = ast.parse(az)
module_funcs = {node.name for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and isinstance(ast.get_docstring(node), (str, type(None)))}
# This is approximate — ast.walk finds ALL functions including nested ones
# A better check: grep for 'def _open_chart_pos' at column 0 (module level)
for func_name in required_module_level:
    pattern = f'\ndef {func_name}('
    check(f'{func_name} at module level', pattern in az or f'def {func_name}(' in az[:2000])

# ============================================================
# 9. STRUCTURAL COOLER GATE — R2/R4 check for pair-over-pair
# ============================================================
print('=== 9. Cooler structural checks ===')
for rule, pattern in [('R2', 'R2_open_shove_cooler'), ('R4', 'R4_3betjam_cooler')]:
    # Find the rule and verify it has a structural check before returning I.7
    idx = az.find(pattern)
    if idx > 0:
        context = az[max(0,idx-500):idx+100]
        check(f'{rule} has structural pair check',
              '_structural' in context or '_hero_pair' in context or '_r2_structural' in context,
              'returns I.7 without structural matchup verification')

# ============================================================
# 10. PACKAGE INTEGRITY (if package dir exists)
# ============================================================
print('=== 10. Package check ===')
pkg_dirs = [d for d in os.listdir('.') if d.startswith('GEM_v') and os.path.isdir(d)]
if pkg_dirs:
    latest = sorted(pkg_dirs)[-1]
    pkg_path = os.path.join(latest, 'REPLACE')
    if os.path.exists(pkg_path):
        print(f'  Checking {latest}/')
        for root, dirs, files in os.walk(pkg_path):
            # No pycache
            check(f'no __pycache__ in {latest}', '__pycache__' not in root or not files)
            for f in files:
                if f.endswith('.pyc'):
                    check(f'no .pyc: {f}', False)
                # Check file matches working copy
                rel = os.path.join(root, f).replace(pkg_path + os.sep, '')
                if os.path.exists(rel):
                    s1 = os.path.getsize(os.path.join(root, f))
                    s2 = os.path.getsize(rel)
                    if s1 != s2:
                        check(f'{f} size matches working copy', False, f'pkg={s1} src={s2}')

# ============================================================
print(f'\n{"="*60}')
print(f'RESULTS: {PASS} passed, {FAIL} failed')
if FAIL:
    print('\nFIX THE ABOVE BEFORE UPLOADING')
    sys.exit(1)
else:
    print('\nPRE-RELEASE GATE PASSED')
