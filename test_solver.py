#!/usr/bin/env python3
"""
test_solver.py — regression harness for gem_solver, gem_ranges,
gem_solver_history, and gem_drift_monitor.

Pins expected outputs on fixed specs so any future change that silently
shifts an EV number or range classification gets caught.

Run after EVERY change to solver/ranges/history/drift modules. All
tests must pass before shipping. Exit 0 = pass, 1 = fail.

Usage: python3 test_solver.py
"""
import sys, os, json, tempfile, shutil

# Path setup
HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
# Prefer /home/claude if we're running under GEM
for p in ['/home/claude', HERE]:
    if os.path.exists(os.path.join(p, 'gem_solver.py')):
        sys.path.insert(0, p)
        break

# ============================================================
# TEST INFRASTRUCTURE
# ============================================================
TESTS_RUN = 0
TESTS_PASSED = 0
FAILURES = []

def check(label, got, want, tol=0.05):
    """Numeric tolerance or exact match for strings."""
    global TESTS_RUN, TESTS_PASSED
    TESTS_RUN += 1
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        ok = abs(got - want) <= tol
        detail = f'got={got}, want={want}±{tol}'
    else:
        ok = got == want
        detail = f'got={got!r}, want={want!r}'
    if ok:
        TESTS_PASSED += 1
        print(f"  ✅ {label}: {detail}")
    else:
        FAILURES.append(f'{label}: {detail}')
        print(f"  ❌ {label}: {detail}")

def section(name):
    print(f"\n=== {name} ===")

# ============================================================
# FIXTURES
# ============================================================
CALL_FOLD_SPEC = {
    'hand_id': 'REGRESS_CALL_FOLD',
    'mode': 'call_fold',
    'hero_cards': ['Js', 'Jc'],
    'board': ['Qh', '8d', '3s', '6c', '2d'],
    'villain_value_range': [
        {'desc': 'QQ',  'weight': 1.0},
        {'desc': '88',  'weight': 1.0},
        {'desc': '33',  'weight': 1.0},
        {'desc': '66',  'weight': 1.0},
        {'desc': '22',  'weight': 1.0},
        {'desc': '54s', 'weight': 1.0},
        {'desc': 'AQs', 'weight': 0.3},
        {'desc': 'KQs', 'weight': 0.3},
    ],
    'villain_bluff_range': [
        {'desc': 'T9s', 'weight': 1.0},
        {'desc': 'J9s', 'weight': 1.0},
        {'desc': 'A5s', 'weight': 0.7},
        {'desc': 'A4s', 'weight': 0.5},
        {'desc': '97s', 'weight': 0.5},
    ],
    'pot_before_bet': 15.5,
    'bet_facing': 11.5,
    'population_underblff_factor': 0.6,
}

VALUE_BET_SPEC = {
    'hand_id': 'REGRESS_VALUE_BET',
    'mode': 'value_bet',
    'hero_cards': ['Kh', 'Ks'],
    'board': ['Qh', '8d', '3s', '6c', '2d'],
    'pot_before_bet': 15.5,
    'hero_bet_size_bb': 11.6,
    'villain_range': [
        {'desc': 'QQ',  'weight': 0.3}, {'desc': 'AQs', 'weight': 1.0},
        {'desc': 'KQs', 'weight': 1.0}, {'desc': 'QJs', 'weight': 1.0},
        {'desc': 'QTs', 'weight': 1.0}, {'desc': 'AJs', 'weight': 0.6},
        {'desc': 'JJ',  'weight': 0.3}, {'desc': '88',  'weight': 0.3},
        {'desc': '33',  'weight': 0.3}, {'desc': 'T9s', 'weight': 0.5},
        {'desc': 'J9s', 'weight': 0.5}, {'desc': 'A5s', 'weight': 0.3},
    ],
}

BLUFF_SPEC = {
    'hand_id': 'REGRESS_BLUFF',
    'mode': 'bluff',
    'hero_cards': ['7h', '6h'],
    'board': ['Qh', '8d', '3s', '6c', '2d'],
    'pot_before_bet': 15.5,
    'hero_bet_size_bb': 11.6,
    'villain_range': [
        {'desc': 'AQs', 'weight': 1.0}, {'desc': 'KQs', 'weight': 1.0},
        {'desc': 'QJs', 'weight': 1.0}, {'desc': 'QTs', 'weight': 1.0},
        {'desc': 'JJ',  'weight': 0.5}, {'desc': 'TT',  'weight': 0.5},
        {'desc': '99',  'weight': 0.5}, {'desc': 'A8s', 'weight': 0.5},
        {'desc': 'A3s', 'weight': 0.5}, {'desc': 'T9s', 'weight': 0.3},
        {'desc': 'J9s', 'weight': 0.3},
    ],
}

# ============================================================
# TESTS
# ============================================================
def test_solver_call_fold():
    section('solver: call_fold mode')
    from gem_solver import solve
    with tempfile.TemporaryDirectory() as td:
        r = solve(CALL_FOLD_SPEC, td)
        res = r['results']
        check('mode',                r['mode'],                  'call_fold')
        check('equity_full_pct',     res['equity_full_pct'],      38.10)
        check('equity_value_only',   res['equity_value_only_pct'], 0.00)
        check('pot_odds_pct',        res['pot_odds_pct'],          29.87)
        # B139: EV(call) = eq*(pot+bet)-(1-eq)*bet (was pot+2*bet — that
        # double-counted Hero's own call). Corrected value: 7.55 - eq*bet.
        check('ev_call_gto',         res['ev_call_gto'],           3.17)
        check('ev_call_worst',       res['ev_call_worst'],        -11.50)
        check('m13_decision',        res['m13_decision'],         'FOLD (stack protection)')
        check('value_combo_ct',      res['value_combo_ct'],        25)
        check('bluff_combo_ct',      res['bluff_combo_ct'],        18)
        # Audit bundle files exist
        for fn in ['inputs.json','command.txt','raw_stdout.txt','result.json','caveats.txt']:
            check(f'audit file exists: {fn}', os.path.exists(os.path.join(td, fn)), True)

def test_solver_value_bet():
    section('solver: value_bet mode')
    from gem_solver import solve
    with tempfile.TemporaryDirectory() as td:
        r = solve(VALUE_BET_SPEC, td)
        res = r['results']
        check('mode',                  r['mode'],                    'value_bet')
        check('equity_vs_call_range',  res['equity_vs_call_range_pct'], 82.58)
        check('villain_fold_freq',     res['villain_fold_freq_pct'],    32.90)
        check('delta_bet_vs_check',    res['delta_bet_vs_check'],       11.50)
        check('decision',              res['decision'],              'BET')

def test_solver_bluff():
    section('solver: bluff mode')
    from gem_solver import solve
    with tempfile.TemporaryDirectory() as td:
        r = solve(BLUFF_SPEC, td)
        res = r['results']
        check('mode',                    r['mode'],                      'bluff')
        check('breakeven_fold_freq',     res['breakeven_fold_freq_pct'],  42.80)
        check('villain_fold_freq',       res['villain_fold_freq_pct'],     9.09)
        check('delta_bluff_vs_check',    res['delta_bluff_vs_check'],     -8.57)
        check('decision',                res['decision'],               'CHECK')

def test_ranges_library():
    section('gem_ranges: auto-construction')
    from gem_ranges import construct_villain_river_range
    r = construct_villain_river_range(
        villain_position='BB',
        hero_position='BTN',
        hero_open_size_pct=22,
        stack_depth_bb=40,
        hero_cards=['Js','Jc'],
        board=['Qh','8d','3s','6c','2d'],
        action_sequence=[
            {'street':'flop','hero':'bet','villain':'call','hero_size_pct':33},
            {'street':'turn','hero':'bet','villain':'call','hero_size_pct':55},
            {'street':'river','hero':'check','villain':'bet','villain_size_pct':75},
        ],
    )
    check('starting_range_key',  r['starting_range_key'], 'BB_DEF_vs20pct')
    # Structural, not numeric pins (narrowing heuristics may drift intentionally)
    check('value_range_nonempty', len(r['value_range']) > 0,   True)
    check('bluff_range_nonempty', len(r['bluff_range']) > 0,   True)
    check('audit_log_has_4_steps', len(r['audit_log']) == 4,   True)
    # Audit step ordering
    step_names = [s.get('step') for s in r['audit_log']]
    check('audit_step_0', step_names[0], 'preflop_range_loaded')
    check('audit_step_1', step_names[1], 'flop_call_narrowing')
    check('audit_step_2', step_names[2], 'turn_call_narrowing')
    check('audit_step_3', step_names[3], 'river_lead_split')

def test_history_io():
    section('gem_solver_history: read/append/roundtrip')
    from gem_solver_history import make_row, append_rows, read_history, HISTORY_COLS
    with tempfile.TemporaryDirectory() as td:
        read_p  = os.path.join(td, 'read.csv')
        write_p = os.path.join(td, 'write.csv')
        row1 = make_row('sess1','TM1','call_fold','Type A','🟢 HIGH',
                        -2.0, -5.0, '/tmp/a', 'KEY1', False)
        row2 = make_row('sess1','TM2','value_bet','Type B','🟡 MED',
                        0.0, 3.2, '/tmp/b', 'KEY2', False)
        check('row1 delta correct',  row1['delta_bb'],        -3.0)
        check('row2 delta correct',  row2['delta_bb'],         3.2)
        check('row has all cols', all(c in row1 for c in HISTORY_COLS), True)
        # Empty initial read
        check('read empty file',  read_history(read_p),        [])
        # Append + roundtrip
        append_rows([row1, row2], read_path=read_p, write_path=write_p)
        rt = read_history(write_p)
        check('roundtrip count',  len(rt),                     2)
        check('roundtrip values preserved',
              rt[0]['heuristic_ev_bb'] == -2.0 and rt[1]['delta_bb'] == 3.2,
              True)
        # Dedup: appending same rows shouldn't duplicate
        # (uses read_path for deduplication base)
        append_rows([row1, row2], read_path=write_p, write_path=write_p)
        rt2 = read_history(write_p)
        check('dedup on resubmit', len(rt2),                   2)

def test_drift_monitor_empty():
    section('gem_drift_monitor: empty history safe path')
    from gem_drift_monitor import run as drift_run
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, 'cal.md')
        r = drift_run(history_path=os.path.join(td, 'nothing.csv'), out_path=out)
        check('handles missing history', r['total_rows'], 0)
        check('still writes output',     os.path.exists(out), True)

def test_drift_monitor_aggregation():
    section('gem_drift_monitor: aggregation logic')
    from gem_solver_history import make_row, append_rows
    from gem_drift_monitor import run as drift_run, aggregate
    with tempfile.TemporaryDirectory() as td:
        hist_p = os.path.join(td, 'hist.csv')
        out_p  = os.path.join(td, 'cal.md')
        # Build 12 rows of one type with consistent delta to force 🔴 RECALIBRATE
        rows = []
        for i in range(12):
            rows.append(make_row(f's{i}', f'TM{i}', 'call_fold',
                                 'Bad River Call', '🟢 HIGH',
                                 -2.0, -5.0, '/tmp', 'K', False))
        # 3 rows of another type — should be MONITORING (n<10)
        for i in range(3):
            rows.append(make_row(f's{i}', f'TN{i}', 'value_bet',
                                 'Missed Thin Value', '🟡 MED',
                                 0.0, 1.5, '/tmp', 'K', False))
        # 2 rows that should be EXCLUDED (M14 indifferent)
        for i in range(2):
            rows.append(make_row(f's{i}', f'TX{i}', 'call_fold',
                                 'Close Spot', '🟢 HIGH',
                                 -0.5, -0.6, '/tmp', 'K', True))
        # 2 rows LOW confidence — should be EXCLUDED
        for i in range(2):
            rows.append(make_row(f's{i}', f'TL{i}', 'call_fold',
                                 'Bad River Call', '🔴 LOW',
                                 -2.0, -100.0, '/tmp', 'K', False))
        append_rows(rows, read_path=hist_p, write_path=hist_p)

        r = drift_run(history_path=hist_p, out_path=out_p)
        check('total rows read',      r['total_rows'],     19)
        check('excluded rows',        r['excluded'],        4)
        check('types analyzed',       r['types_analyzed'],  2)
        check('at least 1 actionable', r['actionable'] >= 1, True)

        # Verify the high-n type got flagged correctly
        from gem_solver_history import read_history
        agg = aggregate(read_history(hist_p))
        bad_river = next((a for a in agg if a['mistake_type'] == 'Bad River Call'), None)
        check('Bad River Call in agg',   bad_river is not None, True)
        check('Bad River Call n',        bad_river['n'],         12)
        check('Bad River Call delta',    bad_river['mean_delta'], -3.0)
        check('Bad River Call action',   bad_river['action'],    '🔴 RECALIBRATE')

# ============================================================
# B175 (Ron 2026-05-25): preflop equity vs range — CVJ villain-jam clause
# ============================================================
def test_preflop_equity_vs_range():
    """check(label, got, want, tol) — numeric tolerance or exact match."""
    from gem_solver import preflop_equity_vs_range, expand_hand_desc

    def _combos(descs, dead):
        out = []
        for d in descs:
            for c1, c2 in expand_hand_desc(d):
                if c1 in dead or c2 in dead:
                    continue
                out.append((c1, c2, 1.0, d))
        return out

    # AKs vs 22 preflop is the classic near-coinflip (~49.5%).
    eq, _ = preflop_equity_vs_range(('Ah', 'Kh'),
                                    _combos(['22'], {'Ah', 'Kh'}),
                                    n_samples=30000)
    check('AKs vs 22 ~ coinflip', eq, 49.5, tol=2.0)

    # AA crushes a broadway-ish range (~84-86%).
    eq2, _ = preflop_equity_vs_range(
        ('Ah', 'Ad'),
        _combos(['QQ', 'JJ', 'TT', 'AKo', 'AQo', 'KQo'], {'Ah', 'Ad'}),
        n_samples=30000)
    check('AA vs broadways ~85%', eq2, 85.0, tol=3.0)

    # Empty range -> None (caller omits the clause).
    eq3, n3 = preflop_equity_vs_range(('Ah', 'Kh'), [])
    check('empty range -> None equity', eq3, None)
    check('empty range -> n=0', n3, 0)

    # Determinism: same seed -> identical result.
    a, _ = preflop_equity_vs_range(('Ah', 'Kh'), _combos(['99'], {'Ah', 'Kh'}),
                                   n_samples=8000, seed=4242)
    b, _ = preflop_equity_vs_range(('Ah', 'Kh'), _combos(['99'], {'Ah', 'Kh'}),
                                   n_samples=8000, seed=4242)
    check('seeded MC reproducible', a, b)


# ============================================================
# MAIN
# ============================================================
def main():
    test_solver_call_fold()
    test_solver_value_bet()
    test_solver_bluff()
    test_ranges_library()
    test_history_io()
    test_drift_monitor_empty()
    test_drift_monitor_aggregation()
    test_preflop_equity_vs_range()

    print(f"\n{'=' * 60}")
    print(f"{TESTS_PASSED}/{TESTS_RUN} passed")
    if FAILURES:
        print(f"\nFAILURES ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
