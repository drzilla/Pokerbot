#!/usr/bin/env python3
"""QA for v8.6.2 — all changes since v8.6.0."""
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
for f in ['gem_analyzer.py', 'gem_parser.py', 'gem_issue_collector.py',
          'gem_report_draft/_html.py', 'gem_report_draft/draft.py',
          'gem_report_draft/sections_financial.py',
          'gem_report_draft/sections_issue_explorer.py',
          'gem_report_draft/sections_iv_xii.py',
          'gem_report_draft/sections_xiv.py',
          'gem_report_draft/sections_xiii.py',
          'gem_report_draft/tldr.py',
          'gem_report_draft/_helpers.py']:
    try:
        py_compile.compile(f, doraise=True); check(f'syntax {f}', True)
    except py_compile.PyCompileError as e:
        check(f'syntax {f}', False, str(e)[:80])

# ============================================================
print('\n=== 2. VERSION ===')
with open('gem_report_draft/draft.py', encoding='utf-8') as f:
    check('v8.6.2 in draft.py', 'v8.6.2' in f.read())
with open('GEM_Quick_Reference.txt', encoding='utf-8') as f:
    check('v8.6.2 in QuickRef', 'v8.6.2' in f.read())
with open('GEM_Changelog.txt', encoding='utf-8') as f:
    cl = f.read()
    check('v8.6.2 in Changelog', 'v8.6.2' in cl[:500])

# ============================================================
print('\n=== 3. CSS BRACE BALANCE (the critical @media fix) ===')
with open('gem_report_draft/_html.py', encoding='utf-8') as f:
    html = f.read()
# Extract CSS between style tags (approximate — check doubled braces)
# Count {{ and }} — they should balance in the f-string template
open_braces = html.count('{{')
close_braces = html.count('}}')
check(f'CSS brace balance: {open_braces} open vs {close_braces} close',
      abs(open_braces - close_braces) <= 2,  # allow small variance for non-CSS uses
      f'diff={open_braces - close_braces}')

# Specifically check the 600px block is closed before 480px
idx_600 = html.find('max-width:600px')
idx_480 = html.find('max-width:480px')
if idx_600 > 0 and idx_480 > 0:
    between = html[idx_600:idx_480]
    # Count }} in between — should have at least 2 (one closing the 600px rules, one closing the @media)
    closes_between = between.count('}}')
    check(f'600px block closed before 480px ({closes_between} closes)',
          closes_between >= 4)  # rules + @media close

# ============================================================
print('\n=== 4. IE LAYOUT (flex not grid) ===')
with open('gem_report_draft/sections_issue_explorer.py', encoding='utf-8') as f:
    sie = f.read()
check('IE uses flex not grid', 'display: flex' in sie and 'flex-wrap: nowrap' in sie)
check('IE right panel fixed width', 'flex: 0 0 340px' in sie)
check('IE breakpoint 820px', 'max-width: 820px' in sie)
check('IE left min-width:0', '.ie-left' in sie and 'min-width: 0' in sie)

# ============================================================
print('\n=== 5. PBReview CACHED INDEX ===')
check('_pbBuildIndex in _html.py', '_pbBuildIndex' in html)
check('availableSet (Set, not querySelector)', 'availableSet' in html or 'availableHands' in html)
check('refsByHid map', 'refsByHid' in html)
check('no querySelector in coverage()', 'querySelector' not in html[html.find('coverage:function'):html.find('coverage:function')+500] if 'coverage:function' in html else False)

# ============================================================
print('\n=== 6. DEBOUNCED SAVES ===')
check('saveReview debounced', 'setTimeout(saveReview' in html)
check('_ieSave debounced', 'setTimeout(_ieSave' in sie)
check('pbDecorateDebounced exists', 'pbDecorateDebounced' in html)
check('closeHand calls full refresh', 'pbDecorateReviewTargets' in html.split('closeHand')[1][:300] if 'closeHand' in html else False)

# ============================================================
print('\n=== 7. XIV.B CAP ===')
with open('gem_report_draft/sections_xiv.py', encoding='utf-8') as f:
    sxiv = f.read()
check('XIV.B cap default 100', "'100'" in sxiv and 'GEM_XIVB_CAP' in sxiv)
check('Metric popup cap 10', "'10'" in sxiv and 'GEM_XIVB_POPUP_CAP' in sxiv)
check('Trim note rendered', 'xivb-trim-note' in sxiv)

# ============================================================
print('\n=== 8. MDA BOLD FIX ===')
check('No **{ma}** in sections_xiv', '**{ma}**' not in sxiv)
check('<strong> used instead', '<strong>{ma}</strong>' in sxiv)

# ============================================================
print('\n=== 9. MULTIWAY COOLER GUARD ===')
with open('gem_analyzer.py', encoding='utf-8') as f:
    az = f.read()
check('Multiway pair check (_n_ai)', '_n_ai' in az and '_v_r0 == _v_r1' in az)

# ============================================================
print('\n=== 10. R2/R4 STRUCTURAL CHECKS ===')
check('R2 structural check', '_r2_structural' in az)
check('R4 structural check', '_is_structural_cooler' in az)
check('R2_open_shove_dominated rule', 'R2_open_shove_dominated' in az)
check('R4_3betjam_dominated rule', 'R4_3betjam_dominated' in az)

# ============================================================
print('\n=== 11. OVER-FOLD RANGE GATE ===')
check('fold_ids range-gated', '_of_in_range' in az)
check('fold_range_notes built', 'fold_range_notes' in az)
check('fold_range_notes propagated to stats', "fold_range_notes" in az.split('_overfold_flags')[1][:500] if '_overfold_flags' in az else False)

# ============================================================
print('\n=== 12. MISSED CR / MISSED CBET FIXES ===')
check('missed_cr HU only (players_at_flop <= 2)', 'players_at_flop' in az.split('missed_cr_flop_ids')[1][:300] if 'missed_cr_flop_ids' in az else False)
check('missed_cr no later raise', 'hero_check_raise_turn' in az)
check('missed_cbet_3bp uses hero_3bet', "h.get('hero_3bet')" in az.split('missed_cbet_3bp_ids')[1][:200] if 'missed_cbet_3bp_ids' in az else False)

# ============================================================
print('\n=== 13. BIG RIVER CALL-DOWN DETECTOR ===')
check('big_river_calldowns bucket exists', "'big_river_calldowns'" in az)
check('RIVER_CALLDOWN_MIN_BB = 8', 'RIVER_CALLDOWN_MIN_BB = 8' in az)
check('RIVER_CALLDOWN_MIN_POT_FRAC = 0.40', 'RIVER_CALLDOWN_MIN_POT_FRAC = 0.40' in az)
check('RIVER_CALLDOWN_MIN_EFF_BB = 13', 'RIVER_CALLDOWN_MIN_EFF_BB = 13' in az)
check('dup_of marker for dedup', 'dup_of' in az)
check('In worksheet builder', "'big_river_calldowns'" in az.split('for _bk_t in')[1][:300] if 'for _bk_t in' in az else False)

# ============================================================
print('\n=== 14. BLINDSPOT STRATUM 8 ===')
check('Stratum 8 big unflagged losses', 'big unflagged losses' in az.lower() or 'Stratum 8' in az)
check('Cap raised to 15', 'cap = 15' in az)

# ============================================================
print('\n=== 15. _open_chart_pos MODULE LEVEL ===')
check('_open_chart_pos at module level', '\ndef _open_chart_pos(' in az)

# ============================================================
print('\n=== 16. REVIEW PILLS CSS ===')
check('.review-pill CSS', '.review-pill' in sie)
check('.review-all CSS', '.review-pill.review-all' in sie)
check('data-issue-review CSS', 'data-issue-review' in sie)

# ============================================================
print('\n=== 17. DEDUPE IN _popup_example_ids ===')
with open('gem_report_draft/_helpers.py', encoding='utf-8') as f:
    helpers = f.read()
check('dedupe in _popup_example_ids', '_deduped' in helpers or '_seen' in helpers)

# ============================================================
print('\n=== 18. JSON IMPORT TO LOCALSTORAGE ===')
check('Import writes localStorage first', 'localStorage.setItem(prefix+hid,val)' in html)

# ============================================================
print('\n=== 19. MOBILE CSS ===')
check('600px block closed before 480px', '}}' in html[html.find('min-width:120px'):html.find('max-width:480px')] if 'min-width:120px' in html else False)
check('Mobile table truncation reset', "max-width:none" in html)
check('overflow-wrap:anywhere', 'overflow-wrap:anywhere' in html)

# ============================================================
print('\n=== 20. PACKAGE INTEGRITY ===')
pkg = 'GEM_v8.6.2_mda_cooler_fix/REPLACE'
if os.path.exists(pkg):
    for root, dirs, files in os.walk(pkg):
        for f in files:
            if f.endswith('.pyc') or '__pycache__' in root:
                check(f'no pycache: {f}', False)
            else:
                rel = os.path.join(root, f).replace(pkg + os.sep, '')
                src = rel
                if os.path.exists(src):
                    s1 = os.path.getsize(os.path.join(root, f))
                    s2 = os.path.getsize(src)
                    if s1 != s2:
                        check(f'{os.path.basename(f)} matches src', False, f'pkg={s1} src={s2}')

# ============================================================
print(f'\n{"="*60}')
print(f'RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}')
if FAIL:
    print('ISSUES FOUND — review above')
    sys.exit(1)
else:
    print('ALL QA CHECKS PASSED')
