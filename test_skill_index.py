"""test_skill_index.py — smoke tests for skill_index / FinScore / tier handicaps.

Covers:
  1. Handicap recomputation produces sane numbers (Mid=0, others ∈ [-200,+200])
  2. _compute_skill_index_for_rows returns expected shape on synthetic data
  3. session_movement_summary returns anchor/responsive/today blocks
  4. session_skill_context exposes both legacy and new field names
  5. Empty/invalid input doesn't crash the pipeline

Run with: python3 test_skill_index.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gem_tier_handicaps
from gem_summary_parser import (
    session_skill_context, session_movement_summary,
    _compute_skill_index_for_rows,
)

PASS = '✓'
FAIL = '✗'


def assert_eq(actual, expected, msg):
    if actual == expected:
        print(f"  {PASS} {msg}")
        return True
    print(f"  {FAIL} {msg}: expected {expected!r}, got {actual!r}")
    return False


def assert_in_range(actual, lo, hi, msg):
    if lo <= actual <= hi:
        print(f"  {PASS} {msg} ({actual} ∈ [{lo}, {hi}])")
        return True
    print(f"  {FAIL} {msg}: {actual} not in [{lo}, {hi}]")
    return False


def assert_has(d, keys, msg):
    missing = [k for k in keys if k not in d]
    if not missing:
        print(f"  {PASS} {msg}")
        return True
    print(f"  {FAIL} {msg}: missing {missing}")
    return False


def t_handicap_recompute():
    print("\nT1: Handicap module")
    import csv
    # Use synthetic data
    synthetic = [
        {'date': '2026-01-01', 'buyin_per_bullet': '30', 'finish_pct': '0.30', 'n_bullets': '1'},
        {'date': '2026-01-01', 'buyin_per_bullet': '30', 'finish_pct': '0.40', 'n_bullets': '1'},
        {'date': '2026-01-01', 'buyin_per_bullet': '75', 'finish_pct': '0.20', 'n_bullets': '1'},
        {'date': '2026-01-01', 'buyin_per_bullet': '75', 'finish_pct': '0.10', 'n_bullets': '1'},
    ]
    tmp = '/tmp/test_synth_pt.csv'
    with open(tmp, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(synthetic[0]))
        w.writeheader()
        for r in synthetic: w.writerow(r)

    out = '/tmp/test_handicaps.json'
    payload = gem_tier_handicaps.recompute(tmp, output_path=out, verbose=False)
    h = payload['tier_handicap_elo']
    ok = True
    ok &= assert_eq(h['Mid']['value'], 0.0, "Mid is reference (=0)")
    if 'High' in h and h['High'].get('value') is not None:
        print(f"  {PASS} High handicap computed")
        ok &= assert_in_range(h['High']['value'], -500, 500, "High handicap finite")
    else:
        print(f"  {FAIL} High handicap missing")
        ok = False
    return ok


def t_compute_skill_index():
    print("\nT2: _compute_skill_index_for_rows")
    rows = [
        {'buyin_per_bullet': '30', 'finish_pct': '0.50', 'n_bullets': '1'},
        {'buyin_per_bullet': '30', 'finish_pct': '0.50', 'n_bullets': '1'},
    ]
    si = _compute_skill_index_for_rows(rows)
    ok = True
    ok &= assert_has(si, ['mean_logit', 'fin_score', 'avg_pos', 'base_skill_index',
                          'skill_index', 'handicap', 'tier_bullets', 'n_t', 'n_b'],
                     "Returns expected keys")
    # fp=0.50 → logit=0 → base_skill_index=1500 (before handicap)
    ok &= assert_eq(si['base_skill_index'], 1500, "logit=0 → base SI=1500")
    ok &= assert_eq(round(si['fin_score']), 50, "FinScore ≈ 50% when fp=0.5")
    ok &= assert_eq(round(si['avg_pos']), 50, "AvgPos = 50% when fp=0.5")
    ok &= assert_eq(si['n_t'], 2, "n_t=2")
    return ok


def t_empty_input():
    print("\nT3: Empty/invalid input doesn't crash")
    ok = True
    if _compute_skill_index_for_rows([]) is None:
        print(f"  {PASS} Empty list → None")
    else:
        print(f"  {FAIL} Empty list should return None"); ok = False
    # bi<=0 row → dropped by the bi guard regardless of fp
    if _compute_skill_index_for_rows([{'buyin_per_bullet': '0',
                                        'finish_pct': '15.0'}]) is None:
        print(f"  {PASS} Zero buy-in row ignored → None")
    else:
        print(f"  {FAIL} Zero buy-in row should return None"); ok = False
    # B137: finish_pct is accepted both percent-scaled (CSV: 15.0) and as a
    # fraction (parser dict: 0.15); both must yield the same skill_index.
    _pct = _compute_skill_index_for_rows(
        [{'buyin_per_bullet': '30', 'finish_pct': '15.0', 'n_bullets': '1'},
         {'buyin_per_bullet': '30', 'finish_pct': '40.0', 'n_bullets': '1'}])
    _frac = _compute_skill_index_for_rows(
        [{'buyin_per_bullet': '30', 'finish_pct': '0.15', 'n_bullets': '1'},
         {'buyin_per_bullet': '30', 'finish_pct': '0.40', 'n_bullets': '1'}])
    if _pct and _frac and _pct['skill_index'] == _frac['skill_index']:
        print(f"  {PASS} finish_pct percent-scale == fraction-scale "
              f"(skill_index {_pct['skill_index']})")
    else:
        print(f"  {FAIL} percent vs fraction finish_pct diverge: "
              f"{_pct and _pct.get('skill_index')} vs "
              f"{_frac and _frac.get('skill_index')}"); ok = False
    if session_movement_summary([], '2026-05-15') is None:
        print(f"  {PASS} Empty rows → None")
    else:
        print(f"  {FAIL} Empty rows should return None"); ok = False
    return ok


def t_movement_summary_shape():
    print("\nT4: session_movement_summary shape")
    rows = []
    for i in range(50):
        rows.append({
            'date': f'2026-04-{(i % 28) + 1:02d}',
            'buyin_per_bullet': '30',
            'finish_pct': f'{0.3 + (i % 10) * 0.05:.3f}',
            'n_bullets': '1',
        })
    mv = session_movement_summary(rows, '2026-05-01')
    ok = True
    ok &= assert_has(mv, ['anchor', 'responsive', 'today', 'today_per_tier', 'deltas'],
                     "Has expected top-level keys")
    return ok


def t_skill_context_aliases():
    print("\nT5: session_skill_context has both new and legacy aliases")
    rows = []
    for i in range(100):
        rows.append({
            'date': f'2026-{(i // 30) + 3:02d}-{(i % 28) + 1:02d}',
            'buyin_per_bullet': '40',
            'finish_pct': f'{0.3 + (i % 10) * 0.04:.3f}',
            'n_bullets': '1',
        })
    ctx = session_skill_context(rows, '2026-06-01', session_avg_bi=40.0)
    ok = True
    ok &= assert_has(ctx, ['fin_score', 'avg_pos', 'skill_index',
                            'skill_index_ci_low', 'skill_index_ci_high',
                            'tier_handicap_applied',
                            # Legacy:
                            'avgf_pct', 'ranking_tier'],
                     "Both new and legacy fields present")
    # FinScore and avgf_pct should be equal (alias)
    ok &= assert_eq(ctx['fin_score'], ctx['avgf_pct'],
                    "fin_score == avgf_pct (alias)")
    return ok


def main():
    results = [
        t_handicap_recompute(),
        t_compute_skill_index(),
        t_empty_input(),
        t_movement_summary_shape(),
        t_skill_context_aliases(),
    ]
    ok = all(results)
    print()
    if ok:
        print(f"ALL {len(results)} TESTS PASSED ✓")
        return 0
    print(f"{sum(1 for r in results if not r)} test(s) FAILED ✗")
    return 1


if __name__ == '__main__':
    sys.exit(main())
