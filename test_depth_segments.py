"""test_depth_segments.py — tests for gem_depth_segments.py (v7.64).

Depth-segmented BB/100: bucket boundaries, the eff-stack-at-decision fallback,
the ICM-pressure split, aggregation arithmetic, and the cluster-bootstrap CI.
"""

import sys
from gem_depth_segments import (compute_depth_segments, _bucket_of, _eff_bb,
                                _icm_band, DEPTH_BUCKETS)

PASS, FAIL = '  \u2713', '  \u2717'


def _h(tid, eff_at_dec, net_bb, phase='late_reg', eff_start=None):
    return {'tournament_id': tid, 'tournament': f'T{tid}',
            'eff_stack_bb_at_decision': eff_at_dec,
            'eff_stack_bb': eff_start if eff_start is not None else eff_at_dec,
            'net_bb': net_bb, 'tournament_phase': phase}


def t1_bucket_boundaries():
    print("\nT1: depth-bucket boundaries (upper-inclusive 8 / 25 / 40)")
    cases = [(3, '<=8BB'), (8.0, '<=8BB'), (8.01, '8-25BB'), (20, '8-25BB'),
             (25.0, '8-25BB'), (25.01, '25-40BB'), (40.0, '25-40BB'),
             (40.01, '>40BB'), (180, '>40BB')]
    ok = True
    for eff, want in cases:
        got = _bucket_of(eff)
        ok &= got == want
        if got != want:
            print(f"{FAIL} {eff}BB -> {got} (expected {want})")
    print(f"{PASS if ok else FAIL} all 9 boundary cases assigned correctly")
    # the four buckets are contiguous and exhaustive
    labels = [b[0] for b in DEPTH_BUCKETS]
    exhaustive = labels == ['<=8BB', '8-25BB', '25-40BB', '>40BB']
    print(f"{PASS if exhaustive else FAIL} 4-tier scheme intact ({labels})")
    return ok and exhaustive


def t2_eff_bb_fallback():
    print("\nT2: eff-stack uses at-decision, falls back to start-of-hand")
    ok = _eff_bb({'eff_stack_bb_at_decision': 18.0, 'eff_stack_bb': 30.0}) == 18.0
    print(f"{PASS if ok else FAIL} at-decision value preferred (18 over 30)")
    ok2 = _eff_bb({'eff_stack_bb_at_decision': None, 'eff_stack_bb': 30.0}) == 30.0
    print(f"{PASS if ok2 else FAIL} falls back to eff_stack_bb when at-decision missing")
    ok3 = _eff_bb({'eff_stack_bb_at_decision': 0, 'eff_stack_bb': 0}) is None
    print(f"{PASS if ok3 else FAIL} returns None when no usable depth")
    return ok and ok2 and ok3


def t3_icm_band():
    print("\nT3: ICM band — bubble/FT are high-pressure, rest standard")
    ok = (_icm_band({'tournament_phase': 'bubble_zone'}) == 'high'
          and _icm_band({'tournament_phase': 'ft_zone'}) == 'high')
    print(f"{PASS if ok else FAIL} bubble_zone + ft_zone -> high")
    ok2 = all(_icm_band({'tournament_phase': p}) == 'std'
              for p in ('late_reg', 'post_reg', 'post_bubble', None))
    print(f"{PASS if ok2 else FAIL} late_reg / post_reg / post_bubble / none -> std")
    return ok and ok2


def t4_aggregation():
    print("\nT4: per-bucket BB/100 aggregation arithmetic")
    # tournament A: 3 hands at 20BB (8-25 bucket), net +10/+10/+10 -> +30 / 3 = +1000/100
    # tournament B: 2 hands at 50BB (>40 bucket), net -5/-5 -> -10 / 2 = -500/100
    hands = [_h('A', 20, 10), _h('A', 20, 10), _h('A', 20, 10),
             _h('B', 50, -5), _h('B', 50, -5)]
    ds = compute_depth_segments(hands, n_boot=200)
    by = {b['depth']: b for b in ds['buckets']}
    ok = by['8-25BB']['n_hands'] == 3 and abs(by['8-25BB']['bb100'] - 1000.0) < 0.01
    print(f"{PASS if ok else FAIL} 8-25BB: 3 hands, BB/100 = +1000 "
          f"({by['8-25BB']['bb100']})")
    ok2 = by['>40BB']['n_hands'] == 2 and abs(by['>40BB']['bb100'] - (-500.0)) < 0.01
    print(f"{PASS if ok2 else FAIL} >40BB: 2 hands, BB/100 = -500 "
          f"({by['>40BB']['bb100']})")
    ok3 = by['<=8BB']['n_hands'] == 0 and by['<=8BB']['bb100'] is None
    print(f"{PASS if ok3 else FAIL} empty bucket -> 0 hands, BB/100 None")
    ok4 = ds['n_hands'] == 5 and ds['n_tournaments'] == 2
    print(f"{PASS if ok4 else FAIL} totals: 5 hands / 2 tournaments")
    return ok and ok2 and ok3 and ok4


def t5_icm_split():
    print("\nT5: ICM split routes hands to std vs high cells")
    hands = [_h('A', 20, 10, phase='late_reg'),     # std
             _h('A', 20, 20, phase='bubble_zone'),  # high
             _h('A', 20, 30, phase='ft_zone')]      # high
    ds = compute_depth_segments(hands, n_boot=100)
    b = {x['depth']: x for x in ds['buckets']}['8-25BB']
    ok = b['n_std'] == 1 and b['n_high'] == 2
    print(f"{PASS if ok else FAIL} 1 std hand, 2 high-ICM hands "
          f"({b['n_std']}/{b['n_high']})")
    # std cell = +10/1 -> +1000 ; high cell = (20+30)/2 -> +2500
    ok2 = (abs(b['bb100_std_icm'] - 1000.0) < 0.01
           and abs(b['bb100_high_icm'] - 2500.0) < 0.01)
    print(f"{PASS if ok2 else FAIL} std +1000, high +2500 "
          f"({b['bb100_std_icm']}/{b['bb100_high_icm']})")
    return ok and ok2


def t6_bootstrap_ci():
    print("\nT6: cluster-bootstrap CI present with >=2 tournaments")
    # 6 tournaments, all 8-25BB, varied nets so the bootstrap has spread
    hands = []
    for i, net in enumerate([5, -3, 8, -1, 12, -6]):
        for _ in range(40):
            hands.append(_h(f'T{i}', 18, net))
    ds = compute_depth_segments(hands, n_boot=500)
    b = {x['depth']: x for x in ds['buckets']}['8-25BB']
    ci = b['ci90']
    ok = ci is not None and ci[0] < b['bb100'] < ci[1]
    print(f"{PASS if ok else FAIL} 90% CI brackets the point estimate "
          f"(CI {ci}, point {b['bb100']})")
    # single-tournament input -> no CI (cannot resample a cluster of one)
    single = [_h('only', 18, 5) for _ in range(30)]
    ds1 = compute_depth_segments(single, n_boot=500)
    b1 = {x['depth']: x for x in ds1['buckets']}['8-25BB']
    ok2 = b1['ci90'] is None
    print(f"{PASS if ok2 else FAIL} single tournament -> CI is None")
    return ok and ok2


def t7_unsegmentable():
    print("\nT7: graceful handling of unsegmentable input")
    ds = compute_depth_segments([{'net_bb': 5}, {'eff_stack_bb_at_decision': 0}])
    ok = ds.get('available') is False
    print(f"{PASS if ok else FAIL} no usable depth -> available False")
    ds2 = compute_depth_segments([])
    ok2 = ds2.get('available') is False
    print(f"{PASS if ok2 else FAIL} empty input -> available False")
    return ok and ok2


if __name__ == '__main__':
    results = [t1_bucket_boundaries(), t2_eff_bb_fallback(), t3_icm_band(),
               t4_aggregation(), t5_icm_split(), t6_bootstrap_ci(),
               t7_unsegmentable()]
    if all(results):
        print(f"\nALL {len(results)} TESTS PASSED \u2713")
    else:
        print(f"\n{results.count(False)} TEST(S) FAILED \u2717")
        sys.exit(1)
