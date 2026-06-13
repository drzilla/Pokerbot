#!/usr/bin/env python3
"""
End-to-End Validation: Analyst Villain Handoff Integration
v8.8.6 pre-production release check

Tests:
  1. Report renders normally without analyst-villain file
  2. Worksheet generation produces valid JSON in output dir
  3. Mock reviewed JSON with confirmed/rejected/borderline/upgraded
  4. Report renders correctly with --analyst-villain-file overlay
  5. Specific HTML content checks for analyst-related rendering
  6. Regression checks for existing features
"""
import json, os, sys, io, tempfile, hashlib, re, time

# Fix console encoding for emoji/unicode on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(__file__))

PASS = 0
FAIL = 0

def check(label, condition, detail=''):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f'  OK  {label}')
    else:
        FAIL += 1
        print(f'  FAIL {label} -- {detail}')


# ============================================================
# SETUP: Load cached pipeline data
# ============================================================
print('=' * 70)
print('E2E Analyst Villain Handoff Validation')
print('=' * 70)

stats_path = os.path.join(os.path.dirname(__file__), 'gem_stats_20260606.json')
print(f'\nLoading stats: {stats_path}')
with open(stats_path, 'r', encoding='utf-8') as f:
    stats = json.load(f)

hands = stats.get('_hands_ref', [])
print(f'  Hands loaded: {len(hands)}')

vi = stats.get('villain_intel', {})
print(f'  Villain intel: {len(vi.get("exploit_opportunities", []))} exploits, '
      f'{len(vi.get("atoms_by_hand", {}))} atom-hands, '
      f'{len(vi.get("villain_aliases", {}))} villains')

# Build _hands_by_id for the renderer
stats['_hands_by_id'] = {h['id']: h for h in hands if 'id' in h}
print(f'  _hands_by_id: {len(stats["_hands_by_id"])} entries')

from gem_report_draft.draft import render_both

# ============================================================
# TEST 1: Report renders normally WITHOUT analyst-villain file
# ============================================================
print(f'\n{"=" * 70}')
print('TEST 1: Report without analyst-villain file')
print('=' * 70)

t0 = time.perf_counter()
try:
    html_no_analyst, md_no_analyst = render_both(stats, {}, hands)
    t_render = time.perf_counter() - t0
    print(f'  Render time: {t_render:.1f}s')
    check('T-E2E-1a: report renders without crash',
          len(html_no_analyst) > 100000,
          f'HTML too small: {len(html_no_analyst)} chars')
except Exception as e:
    check('T-E2E-1a: report renders without crash', False, str(e))
    html_no_analyst = ''

if html_no_analyst:
    # Deterministic coaching should still appear
    check('T-E2E-1b: deterministic coaching blocks present',
          'opponent-coaching' in html_no_analyst or 'coaching-block' in html_no_analyst
          or 'handOpponentContexts' in html_no_analyst,
          'No coaching block markers found')

    # No analyst-reviewed data in handOpponentContexts (JS template code will
    # reference the field name, but no actual context should have the flag set)
    _hoc_no_match = re.search(r'window\.handOpponentContexts\s*=\s*(\{.*?\});',
                               html_no_analyst, re.DOTALL)
    _has_analyst_data = False
    if _hoc_no_match:
        try:
            _hoc_no = json.loads(_hoc_no_match.group(1))
            for ctxs in _hoc_no.values():
                for c in ctxs:
                    if c.get('analyst_reviewed'):
                        _has_analyst_data = True
                        break
        except Exception:
            pass
    check('T-E2E-1c: no analyst-reviewed data without analyst file',
          not _has_analyst_data,
          'analyst_reviewed=True found in context data without analyst file')

    # Fallback label check: should appear only where coaching blocks exist
    # but no analyst review is present
    check('T-E2E-1d: fallback label CSS defined',
          'cb-fallback-label' in html_no_analyst,
          'fallback label CSS class missing from HTML')

    # Check that the JS fallback logic is present
    check('T-E2E-1e: fallback label JS logic present',
          'not yet analyst-reviewed' in html_no_analyst,
          'fallback text not in HTML')


# ============================================================
# TEST 2: Worksheet generation
# ============================================================
print(f'\n{"=" * 70}')
print('TEST 2: Villain analyst worksheet generation')
print('=' * 70)

from gem_analyst_villain import (
    build_opponent_adjustment_candidates, write_worksheet,
    load_analyst_villain_review, _stable_candidate_id,
    SCHEMA_VERSION, FALLBACK_LABELS)

candidates = build_opponent_adjustment_candidates(vi, hands, stats, max_candidates=40)
print(f'  Candidates generated: {len(candidates)}')

check('T-E2E-2a: candidates is a non-empty list',
      isinstance(candidates, list) and len(candidates) > 0,
      f'got {type(candidates).__name__} len={len(candidates) if isinstance(candidates, list) else "?"}')

# Source type distribution
from collections import Counter
src_counts = Counter(c.get('source_type', '?') for c in candidates)
print(f'  By source type: {dict(src_counts)}')
check('T-E2E-2b: multiple source types generated',
      len(src_counts) >= 2,
      f'Only {len(src_counts)} source type(s): {dict(src_counts)}')

# Stable candidate IDs
if candidates:
    c0 = candidates[0]
    expected_cid = _stable_candidate_id(
        c0['source_type'], c0['hand_id'], c0['villain_key'])
    check('T-E2E-2c: candidate_id is stable hash',
          c0['candidate_id'] == expected_cid,
          f'expected {expected_cid}, got {c0["candidate_id"]}')

    # Full hand_id used for joins (Requirement B)
    check('T-E2E-2d: hand_id is full format (not 8-digit)',
          all(len(c.get('hand_id', '')) > 8 for c in candidates),
          'Some candidates have short hand_id')

    # hand_id_short for display
    check('T-E2E-2e: hand_id_short is 8 digits',
          all(len(c.get('hand_id_short', '')) == 8 for c in candidates),
          'Some candidates have wrong short form')

# Write worksheet to temp dir (NOT HH input dir)
tmpdir = tempfile.mkdtemp(prefix='gem_e2e_')
ws_path = write_worksheet(candidates, '20260606', 'TestHero', tmpdir)
check('T-E2E-2f: worksheet written to output dir',
      ws_path and os.path.isfile(ws_path),
      f'ws_path={ws_path}')

if ws_path:
    # Verify it's NOT in the HH input directory
    check('T-E2E-2g: worksheet NOT in HH input directory',
          tmpdir in ws_path,
          f'worksheet at unexpected path: {ws_path}')

    # Verify it's valid JSON with schema_version
    with open(ws_path, 'r', encoding='utf-8') as f:
        ws_data = json.load(f)
    check('T-E2E-2h: worksheet has schema_version',
          ws_data.get('schema_version') == SCHEMA_VERSION,
          f'got {ws_data.get("schema_version")}')
    check('T-E2E-2i: worksheet candidates match builder output',
          len(ws_data.get('candidates', [])) == len(candidates),
          f'{len(ws_data.get("candidates",[]))} vs {len(candidates)}')


# ============================================================
# TEST 3: Create mock reviewed analyst JSON
# ============================================================
print(f'\n{"=" * 70}')
print('TEST 3: Mock reviewed analyst JSON')
print('=' * 70)

# Pick 4 real candidates from the generated list for mock review
reviewed_candidates = []
_verdicts = ['confirmed', 'rejected', 'borderline', 'upgraded']
_used = set()
for verdict in _verdicts:
    for c in candidates:
        if c['candidate_id'] not in _used:
            reviewed_c = dict(c)
            reviewed_c['analyst_verdict'] = verdict
            if verdict in ('confirmed', 'upgraded'):
                reviewed_c['analyst_coaching'] = (
                    f'Mock coaching for {verdict}: {c["source_type"]} '
                    f'vs {c.get("villain_alias", "?")}.')
            elif verdict == 'borderline':
                reviewed_c['analyst_coaching'] = (
                    f'This is debatable. The evidence is mixed for '
                    f'{c.get("villain_alias", "?")}.')
            else:
                reviewed_c['analyst_coaching'] = ''
            reviewed_c['analyst_severity'] = 'medium'
            reviewed_c['analyst_confidence'] = 'high' if verdict == 'confirmed' else 'medium'
            reviewed_c['analyst_note'] = f'E2E test {verdict}' if verdict == 'borderline' else ''
            reviewed_candidates.append(reviewed_c)
            _used.add(c['candidate_id'])
            print(f'  {verdict}: hand={c["hand_id_short"]} villain={c.get("villain_alias","")} '
                  f'source={c["source_type"]}')
            break

check('T-E2E-3a: 4 reviewed candidates created',
      len(reviewed_candidates) == 4,
      f'got {len(reviewed_candidates)}')

# Write mock review JSON
mock_review_data = {
    'schema_version': SCHEMA_VERSION,
    'session_date': '20260606',
    'hero_name': 'TestHero',
    'generated_at': '2026-06-08T12:00:00Z',
    'pipeline_version': 'v8.8.6',
    'total_candidates': len(reviewed_candidates),
    'candidates': reviewed_candidates,
}
review_path = os.path.join(tmpdir, '_analyst_villain_reviewed_20260606.json')
with open(review_path, 'w', encoding='utf-8') as f:
    json.dump(mock_review_data, f, indent=2, ensure_ascii=False)

print(f'  Review file: {review_path} ({os.path.getsize(review_path):,} bytes)')

# Load and validate
review = load_analyst_villain_review(review_path, expected_session_date='20260606')
check('T-E2E-3b: review loaded successfully',
      'candidates_by_id' in review and len(review['candidates_by_id']) >= 3,
      f'got {len(review.get("candidates_by_id",{}))} candidates')

debug = review.get('debug', {})
print(f'  Debug: {debug}')
check('T-E2E-3c: confirmed count correct',
      debug.get('confirmed', 0) == 1,
      f'confirmed={debug.get("confirmed")}')
check('T-E2E-3d: rejected count correct',
      debug.get('rejected', 0) == 1,
      f'rejected={debug.get("rejected")}')
check('T-E2E-3e: borderline count correct',
      debug.get('borderline', 0) == 1,
      f'borderline={debug.get("borderline")}')
check('T-E2E-3f: upgraded count correct',
      debug.get('upgraded', 0) == 1,
      f'upgraded={debug.get("upgraded")}')

# by_hand_villain index
by_hv = review.get('by_hand_villain', {})
check('T-E2E-3g: by_hand_villain index populated',
      len(by_hv) >= 1,
      f'got {len(by_hv)} entries')


# ============================================================
# TEST 4: Render report WITH --analyst-villain-file
# ============================================================
print(f'\n{"=" * 70}')
print('TEST 4: Report with analyst-villain-file overlay')
print('=' * 70)

report_data_with = {'analyst_villain_review': review}
t0 = time.perf_counter()
try:
    html_with_analyst, md_with_analyst = render_both(
        stats, report_data_with, hands)
    t_render = time.perf_counter() - t0
    print(f'  Render time: {t_render:.1f}s')
    check('T-E2E-4a: report with analyst renders without crash',
          len(html_with_analyst) > 100000,
          f'HTML too small: {len(html_with_analyst)} chars')
except Exception as e:
    check('T-E2E-4a: report with analyst renders without crash', False, str(e))
    html_with_analyst = ''

if html_with_analyst:
    # Get the confirmed candidate's hand_id for targeted checks
    confirmed_c = [c for c in reviewed_candidates if c['analyst_verdict'] == 'confirmed'][0]
    rejected_c = [c for c in reviewed_candidates if c['analyst_verdict'] == 'rejected'][0]
    borderline_c = [c for c in reviewed_candidates if c['analyst_verdict'] == 'borderline'][0]
    upgraded_c = [c for c in reviewed_candidates if c['analyst_verdict'] == 'upgraded'][0]

    # The analyst overlay is in JS data (window.handOpponentContexts)
    # Check that the JS data includes analyst fields
    hoc_match = re.search(r'window\.handOpponentContexts\s*=\s*(\{.*?\});',
                          html_with_analyst, re.DOTALL)
    if hoc_match:
        try:
            hoc_data = json.loads(hoc_match.group(1))
            print(f'  handOpponentContexts: {len(hoc_data)} hands with contexts')

            # Check confirmed hand has analyst_reviewed
            conf_short = confirmed_c['hand_id_short']
            conf_ctxs = hoc_data.get(conf_short, [])
            conf_reviewed = [c for c in conf_ctxs if c.get('analyst_reviewed')]
            check('T-E2E-4b: confirmed hand has analyst_reviewed context',
                  len(conf_reviewed) >= 1,
                  f'hand {conf_short}: {len(conf_ctxs)} contexts, '
                  f'{len(conf_reviewed)} reviewed')

            if conf_reviewed:
                check('T-E2E-4c: confirmed context has analyst_coaching',
                      conf_reviewed[0].get('analyst_coaching', '') != '',
                      'coaching is empty')
                check('T-E2E-4d: confirmed context analyst_verdict=confirmed',
                      conf_reviewed[0].get('analyst_verdict') == 'confirmed',
                      f'got {conf_reviewed[0].get("analyst_verdict")}')

            # Check rejected hand — context should be ABSENT (Option A)
            rej_short = rejected_c['hand_id_short']
            rej_ctxs = hoc_data.get(rej_short, [])
            rej_buckets = [c.get('bucket') for c in rej_ctxs]
            rej_src = rejected_c['source_type']
            # Map source_type to expected bucket
            _src_to_bucket = {
                'exploit_miss': 'exploit_miss', 'exploit_good': 'good_exploit',
                'timing_unclear': 'villain_evidence', 'mixed_signal': 'villain_evidence',
                'learning_hand': 'villain_evidence',
            }
            rej_bucket = _src_to_bucket.get(rej_src, rej_src)
            # The rejected context should be filtered out
            # But other contexts for the same hand may still exist
            rej_matching = [c for c in rej_ctxs
                           if c.get('analyst_reviewed') and
                           c.get('analyst_verdict') == 'rejected']
            check('T-E2E-4e: rejected context filtered from output',
                  len(rej_matching) == 0,
                  f'found {len(rej_matching)} rejected contexts still present')

            # Check borderline hand
            bord_short = borderline_c['hand_id_short']
            bord_ctxs = hoc_data.get(bord_short, [])
            bord_reviewed = [c for c in bord_ctxs if c.get('analyst_reviewed')]
            check('T-E2E-4f: borderline hand has reviewed context',
                  len(bord_reviewed) >= 1,
                  f'hand {bord_short}: {len(bord_reviewed)} reviewed')
            if bord_reviewed:
                check('T-E2E-4g: borderline context has coaching text',
                      'debatable' in bord_reviewed[0].get('analyst_coaching', '').lower()
                      or bord_reviewed[0].get('analyst_verdict') == 'borderline',
                      'borderline coaching/verdict wrong')

            # Check upgraded hand — should be analyst_learning bucket
            upg_short = upgraded_c['hand_id_short']
            upg_ctxs = hoc_data.get(upg_short, [])
            upg_learning = [c for c in upg_ctxs if c.get('bucket') == 'analyst_learning']
            check('T-E2E-4h: upgraded context has analyst_learning bucket',
                  len(upg_learning) >= 1,
                  f'hand {upg_short}: buckets={[c.get("bucket") for c in upg_ctxs]}')

            # Non-reviewed candidates should still have deterministic output
            all_hoc_hands = list(hoc_data.keys())
            non_reviewed_hands = [h for h in all_hoc_hands
                                  if h not in {conf_short, rej_short, bord_short, upg_short}]
            check('T-E2E-4i: non-reviewed hands still have contexts',
                  len(non_reviewed_hands) > 0,
                  'no non-reviewed hands found in contexts')

        except json.JSONDecodeError as e:
            check('T-E2E-4b: handOpponentContexts parseable', False, str(e))
    else:
        print('  WARNING: handOpponentContexts not found in HTML — '
              'may be empty for this dataset')
        check('T-E2E-4b: handOpponentContexts present', False,
              'regex did not match')


# ============================================================
# TEST 5: HTML content checks
# ============================================================
print(f'\n{"=" * 70}')
print('TEST 5: HTML content checks')
print('=' * 70)

html = html_with_analyst or html_no_analyst

# Analyst badge rendering in JS
check('T-E2E-5a: analyst badge JS present',
      'Analyst confirmed' in html and 'Debatable' in html
      and 'Learning opportunity' in html,
      'missing badge text in HTML')

# Analyst learning bucket CSS
check('T-E2E-5b: analyst_learning CSS present',
      'coaching-analyst_learning' in html and 'cb-learning' in html,
      'missing analyst_learning CSS')

# cb-analyst styling
check('T-E2E-5c: cb-analyst CSS present',
      '.cb-analyst' in html,
      'missing .cb-analyst CSS rule')

# Fallback label
check('T-E2E-5d: fallback label in HTML',
      'cb-fallback-label' in html,
      'fallback label class missing')

# FALLBACK_LABELS constant exists in gem_analyst_villain.py
check('T-E2E-5e: FALLBACK_LABELS has required keys',
      all(k in FALLBACK_LABELS for k in ('not_reviewed', 'stale', 'invalid')),
      f'keys: {list(FALLBACK_LABELS.keys())}')


# ============================================================
# TEST 6: Regression checks
# ============================================================
print(f'\n{"=" * 70}')
print('TEST 6: Regression checks')
print('=' * 70)

# 6a: villain_evidence contexts still exist
if hoc_match:
    try:
        hoc_data = json.loads(hoc_match.group(1))
        all_buckets = set()
        for ctxs in hoc_data.values():
            for c in ctxs:
                all_buckets.add(c.get('bucket'))
        check('T-E2E-6a: villain_evidence bucket still present',
              'villain_evidence' in all_buckets,
              f'buckets found: {all_buckets}')
    except Exception:
        check('T-E2E-6a: villain_evidence bucket still present', False, 'parse error')

# 6b: Badges still render (Note / Pivot)
check('T-E2E-6b: Note/Pivot badge code present',
      "'type': 'note'" in html or '"type":"note"' in html
      or 'badge-note' in html or "'type': 'pivot'" in html
      or "villain_badges" in html or 'villain-street-notes' in html,
      'badge/note rendering missing')

# 6c: Yellow street notes
check('T-E2E-6c: yellow street notes CSS present',
      'villain-street-notes' in html,
      'villain-street-notes CSS missing')

# 6d: No "Unknown missed exploit" row — verify exploit buckets are properly labeled
check('T-E2E-6d: exploit coaching headers present',
      'Opponent Adjustment' in html,
      'exploit coaching headers missing')

# 6e: Timing labels present (ensures timing gate not broken)
check('T-E2E-6e: timing labels in coaching blocks',
      'Read timing:' in html or 'timing_label' in html,
      'timing rendering missing')

# 6f: handAvailability (HA system) still works
check('T-E2E-6f: handAvailability system present',
      'handAvailability' in html,
      'handAvailability missing from HTML')

# 6g: Queue navigation still works (inline + popup)
check('T-E2E-6g: queue navigation JS present',
      'activeHandQueue' in html and 'buildInlineHandQueueFromClickedRef' in html,
      'queue navigation code missing')

# 6h: Back to table/list label logic present
check('T-E2E-6h: back label logic present',
      'Back to table' in html and 'Back to list' in html,
      'back label variants missing')

# 6i: Verdict chips still render
check('T-E2E-6i: verdict chip system present',
      'verdict-chip-row' in html,
      'verdict chips missing')

# 6j: P&L table init (DOMContentLoaded, not synchronous)
check('T-E2E-6j: P&L DOMContentLoaded init',
      'initPerTournamentPnlTable' in html or 'DOMContentLoaded' in html,
      'P&L init pattern missing')


# ============================================================
# WRITE HTML FILES FOR BROWSER QA
# ============================================================
print(f'\n{"=" * 70}')
print('OUTPUT FILES FOR BROWSER QA')
print('=' * 70)

html_dir = os.path.join(tmpdir, 'browser_qa')
os.makedirs(html_dir, exist_ok=True)

if html_no_analyst:
    path1 = os.path.join(html_dir, 'report_NO_analyst.html')
    with open(path1, 'w', encoding='utf-8') as f:
        f.write(html_no_analyst)
    print(f'  NO analyst:   {path1}')
    print(f'                ({len(html_no_analyst):,} chars, {os.path.getsize(path1):,} bytes)')

if html_with_analyst:
    path2 = os.path.join(html_dir, 'report_WITH_analyst.html')
    with open(path2, 'w', encoding='utf-8') as f:
        f.write(html_with_analyst)
    print(f'  WITH analyst: {path2}')
    print(f'                ({len(html_with_analyst):,} chars, {os.path.getsize(path2):,} bytes)')

# Print the candidate IDs used in mock review for browser QA reference
print(f'\n  Mock review candidates (for browser QA):')
for c in reviewed_candidates:
    print(f'    {c["analyst_verdict"]:12s}  hand={c["hand_id_short"]}  '
          f'villain={c.get("villain_alias","?"):12s}  source={c["source_type"]}')


# ============================================================
# SUMMARY
# ============================================================
print(f'\n{"=" * 70}')
print(f'RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL}')
if FAIL:
    print('⚠ FIX BEFORE PRODUCTION RELEASE')
    sys.exit(1)
else:
    print('✅ ALL E2E CHECKS PASSED')
    print(f'\n  Temp dir: {tmpdir}')
    print(f'  Worksheet: {ws_path}')
    print(f'  Review: {review_path}')
    print(f'  Browser QA: {html_dir}')
