"""test_cev.py — tests for gem_cev.py cEV/stack background tracking."""

from gem_cev import compute_cev_per_stack, _resolve_starting_chips, _load_structures

PASS, FAIL = '  \u2713', '  \u2717'


def _h(tid, hid, level, bb_blind, net_bb, stack_bb=None, sb_blind=None):
    return {'tournament_id': tid, 'tournament': f'T{tid}', 'id': hid,
            'level': level, 'bb_blind': bb_blind, 'sb_blind': sb_blind,
            'net_bb': net_bb, 'stack_bb': stack_bb}


def t1_l1_observed():
    print("\nT1: L1-observed — chip count is the starting stack")
    structs = _load_structures()
    ok = True
    # earliest hand is L1, Hero has exactly 25,000
    res = _resolve_starting_chips('X', 'TX',
        {'level': 1, 'sb': 100, 'bb': 200, 'hero_chips': 25000}, structs)
    ok &= res['source'] == 'l1_observed' and res['starting_chips'] == 25000
    print(f"{PASS if ok else FAIL} exact L1 read -> 25000 ({res['starting_chips']})")
    # a few deals in: 24,940 snaps to 25,000
    res = _resolve_starting_chips('X', 'TX',
        {'level': 1, 'sb': 100, 'bb': 200, 'hero_chips': 24940}, structs)
    snapped = res['starting_chips'] == 25000
    ok &= snapped
    print(f"{PASS if snapped else FAIL} 24,940 snaps to 25,000 ({res['starting_chips']})")
    # genuinely off (already doubled) — does NOT snap
    res = _resolve_starting_chips('X', 'TX',
        {'level': 1, 'sb': 100, 'bb': 200, 'hero_chips': 50000}, structs)
    ok &= res['starting_chips'] == 50000
    print(f"{PASS if res['starting_chips']==50000 else FAIL} "
          f"50,000 (already doubled) kept raw ({res['starting_chips']})")
    return ok


def t2_ladder_extrapolation():
    print("\nT2: ladder extrapolation — L2+ resolves via blind ladder")
    structs = _load_structures()
    # earliest hand L5 250/500 — classic ladder, L1 start 25000
    res = _resolve_starting_chips('X', 'TX',
        {'level': 5, 'sb': 250, 'bb': 500, 'hero_chips': 25000}, structs)
    ok = res['source'] == 'ladder_extrapolated' and res['starting_chips'] == 25000
    print(f"{PASS if ok else FAIL} L5 250/500 -> L1 start 25000 "
          f"({res['source']}, {res['starting_chips']})")
    return ok


def t3_unresolved():
    print("\nT3: unresolved — no L1, no ladder, no table -> None")
    structs = _load_structures()
    res = _resolve_starting_chips('X', 'Unknown Tourney',
        {'level': 10, 'sb': 800, 'bb': 1600, 'hero_chips': 40000}, structs)
    ok = res['source'] == 'unresolved' and res['starting_chips'] is None
    print(f"{PASS if ok else FAIL} deep-only hand -> unresolved, None")
    return ok


def t4_net_chips_and_cev():
    print("\nT4: net chips and cEV/stack arithmetic")
    # 3 hands, L1, bb_blind=200; net_bb sums to +125 -> +25,000 chips
    hands = [
        _h('A', 'TM100', 1, 200, +50.0, stack_bb=125),
        _h('A', 'TM101', 1, 200, +50.0, stack_bb=125),
        _h('A', 'TM102', 1, 200, +25.0, stack_bb=125),
    ]
    r = compute_cev_per_stack(hands)
    pt = r['per_tournament']['A']
    ok = abs(pt['net_chips'] - 25000) < 1
    print(f"{PASS if ok else FAIL} net_chips = sum(net_bb*bb_blind) = "
          f"25,000 ({pt['net_chips']})")
    # stack_bb 125 * bb 200 = 25,000 starting stack -> cev = 1.0
    ok2 = pt['cev_per_stack'] is not None and abs(pt['cev_per_stack'] - 1.0) < 0.01
    print(f"{PASS if ok2 else FAIL} cEV/stack = net/start = +1.0 "
          f"({pt['cev_per_stack']})")
    return ok and ok2


def t5_unresolved_skipped_from_aggregate():
    print("\nT5: unresolved tournaments skipped from session aggregate")
    hands = [
        _h('A', 'TM1', 1, 200, +50.0, stack_bb=125),       # resolves
        _h('B', 'TM2', 10, 1600, -30.0, stack_bb=25),      # unresolved
    ]
    r = compute_cev_per_stack(hands)
    s = r['session']
    ok = s['n_resolved'] == 1 and s['n_unresolved'] == 1
    print(f"{PASS if ok else FAIL} 1 resolved, 1 unresolved "
          f"({s['n_resolved']}/{s['n_unresolved']})")
    ok2 = r['per_tournament']['B']['cev_per_stack'] is None
    print(f"{PASS if ok2 else FAIL} unresolved tournament cev_per_stack is None")
    return ok and ok2


def t6_eai_effstack_bounded():
    print("\nT6: EAI luck axis is effective-stack-normalized and bounded")
    from gem_cev import compute_eai_cev_per_stack
    # one all-in: flip category, Hero doubled (net_bb = +eff_stack_bb)
    hands = [
        {'tournament_id': 'A', 'tournament': 'TA', 'id': 'TM1', 'level': 5,
         'bb_blind': 1000, 'net_bb': 12.0, 'eff_stack_bb': 12.0},
    ]
    eai_block = {'hands': [{'id': 'TM1', 'category': 'flip', 'won': True}],
                 'flipping': {'pct': 44.2}, 'way_ahead': {'pct': 92.6},
                 'way_behind': {'pct': 31.8}}
    r = compute_eai_cev_per_stack(hands, eai_block, {})
    sw = r['A']['eai_swing_stacks']
    # realized_frac = +1.0 (doubled); expected = 2*0.442-1 = -0.116;
    # swing = 1.0 - (-0.116) = +1.116
    ok = sw is not None and abs(sw - 1.116) < 0.01
    print(f"{PASS if ok else FAIL} flip won, doubled -> swing +1.116 ({sw})")
    # late-game huge-blind hand must NOT blow up: net_bb bounded by eff stack
    hands2 = [
        {'tournament_id': 'B', 'tournament': 'TB', 'id': 'TM2', 'level': 37,
         'bb_blind': 300000, 'net_bb': -9.7, 'eff_stack_bb': 9.9},
    ]
    eai2 = {'hands': [{'id': 'TM2', 'category': 'flip', 'won': False}],
            'flipping': {'pct': 44.2}, 'way_ahead': {'pct': 92.6},
            'way_behind': {'pct': 31.8}}
    r2 = compute_eai_cev_per_stack(hands2, eai2, {})
    sw2 = r2['B']['eai_swing_stacks']
    bounded = sw2 is not None and -2.0 < sw2 < 0
    print(f"{PASS if bounded else FAIL} late-game L37 all-in bounded, "
          f"not a runaway ({sw2})")
    return ok and bounded



def t7_attribution_collector():
    print("\nT7: cEV attribution collector — axes + phase weighting")
    from gem_cev_attribution import (phase_weight, collect_red_line,
                                     collect_read_dependent_bucket)
    ok = True
    # phase weight: short stack weighs more than deep
    w_short = phase_weight(5)
    w_deep = phase_weight(150)
    ok &= w_short > w_deep
    print(f"{PASS if ok else FAIL} short-stack weight {w_short:.2f} > "
          f"deep-stack weight {w_deep:.2f}")
    # red line: only non-SD hands counted
    hands = [
        {'tournament_id': 'A', 'id': 'T1', 'went_to_sd': False,
         'net_bb': -3.0, 'eff_stack_bb': 25},
        {'tournament_id': 'A', 'id': 'T2', 'went_to_sd': True,
         'net_bb': +99.0, 'eff_stack_bb': 25},   # SD — excluded
    ]
    rl = collect_red_line(hands)
    ok2 = rl['A']['n_hands'] == 1 and abs(rl['A']['red_line_raw_bb'] + 3.0) < 0.01
    print(f"{PASS if ok2 else FAIL} red line counts non-SD only "
          f"({rl['A']['n_hands']} hand, {rl['A']['red_line_raw_bb']} bb)")
    # read-dependent bucket: no per-hand verdict, just totals
    hands_rd = [{'tournament_id': 'A', 'id': 'TM9', 'net_bb': -10.0,
                 'eff_stack_bb': 20}]
    analyst = {'TM9': {'verdict': 'III.4 Read-dependent', 'pattern': 'X',
                       'key_decision': 'test'}}
    rb = collect_read_dependent_bucket(hands_rd, analyst)
    ok3 = rb['n_hands'] == 1 and rb['negative']['n'] == 1
    print(f"{PASS if ok3 else FAIL} read-dep bucket totals "
          f"({rb['n_hands']} hand, {rb['negative']['n']} negative)")
    return ok and ok2 and ok3


def t8_dealt_cards_and_made_hands():
    print("\nT8: dealt-card quality (exact combinatorial) + made-hands")
    from gem_cev_attribution import (collect_dealt_card_quality,
                                     _starting_hand_class, _CLASS_EXPECTED)
    ok = True
    # class assignment is exhaustive and correct
    ok &= _starting_hand_class(['Ac', 'Ad']) == 'premium_pair'
    ok &= _starting_hand_class(['Ac', 'Kd']) == 'premium_ax'
    ok &= _starting_hand_class(['7c', '2d']) == 'other'
    print(f"{PASS if ok else FAIL} starting-hand classes assigned correctly")
    # expected frequencies sum to 1.0 (exhaustive, exact combinatorics)
    tot = sum(_CLASS_EXPECTED.values())
    sums = abs(tot - 1.0) < 1e-9
    print(f"{PASS if sums else FAIL} class expectations sum to 1.0 ({tot:.6f})")
    # premium_pair expected freq ~ 5.9% would be wrong — AA/KK/QQ only = 18/1326
    pp = _CLASS_EXPECTED.get('premium_pair', 0)
    pp_ok = abs(pp - 18 / 1326) < 1e-6
    print(f"{PASS if pp_ok else FAIL} premium-pair freq = 18/1326 ({pp:.5f})")
    # depth bucketing: a short-stack hand lands in the <12bb bucket
    hands = [{'tournament_id': 'A', 'cards': ['Ac', 'Ad'], 'eff_stack_bb': 8},
             {'tournament_id': 'A', 'cards': ['Kc', 'Kd'], 'eff_stack_bb': 8}]
    dcq = collect_dealt_card_quality(hands)
    bkt_ok = '<12bb' in dcq['by_depth_bucket']
    print(f"{PASS if bkt_ok else FAIL} short-stack hands bucketed to <12bb")

    # B174: phase x depth cross-tab — reconciles to depth-only on hand counts
    # (pure combinatorics, no per-subset re-estimation, so it IS additive).
    ph_hands = [
        {'tournament_id': 'A', 'cards': ['Ac', 'Ad'], 'eff_stack_bb': 8,
         'tournament_phase': 'bubble_zone'},
        {'tournament_id': 'A', 'cards': ['Kc', 'Kd'], 'eff_stack_bb': 8,
         'tournament_phase': 'late_reg'},
        {'tournament_id': 'A', 'cards': ['7c', '2d'], 'eff_stack_bb': 8,
         'tournament_phase': 'late_reg'},
    ]
    dcq2 = collect_dealt_card_quality(ph_hands)
    pd = dcq2.get('by_phase_depth', {})
    pd_present = 'bubble_zone' in pd and 'late_reg' in pd
    # sum of phase x depth n must equal depth-only n for each bucket
    depth_n = {b: d['n_hands'] for b, d in dcq2['by_depth_bucket'].items()}
    pd_sum = {}
    for _ph, _depths in pd.items():
        for _b, _d in _depths.items():
            pd_sum[_b] = pd_sum.get(_b, 0) + _d['n_hands']
    pd_additive = depth_n == pd_sum
    print(f"{PASS if pd_present else FAIL} dealt-card by_phase_depth populated")
    print(f"{PASS if pd_additive else FAIL} phase x depth reconciles to "
          f"depth-only on counts")

    # B174: made-hands by_phase block present + low_sample tagging works
    from gem_cev_attribution import collect_made_hands_conversion, _PHASE_OPP_FLOOR
    mh = collect_made_hands_conversion(ph_hands)
    mh_phase_ok = 'by_phase' in mh and mh.get('by_phase_additive') is False
    # a 3-hand session: every phase cell is below the opp floor -> low_sample
    low_ok = all(c.get('low_sample') is True
                 for c in mh.get('by_phase', {}).values())
    print(f"{PASS if mh_phase_ok else FAIL} made-hands by_phase present + "
          f"flagged non-additive")
    print(f"{PASS if low_ok else FAIL} thin phase cells tagged low_sample")
    return (ok and sums and pp_ok and bkt_ok and pd_present
            and pd_additive and mh_phase_ok and low_ok)


def t9_decomposable_surface():
    """v7.63: session cEV is the SUM of per-tournament (net/start), not
    Sum(net)/mean_start — so it is decomposable and the ledger balances."""
    print("\nT9: session cEV is decomposable (Sigma per-tournament net/start)")
    # A: start 25,000, net +25,000 -> cev +1.0
    # B: start 50,000, net -25,000 -> cev -0.5   (stack 125 x bb 400)
    hands = [
        _h('A', 'A1', 1, 200, +125.0, stack_bb=125),
        _h('B', 'B1', 1, 400, -62.5, stack_bb=125),
    ]
    r = compute_cev_per_stack(hands)
    s = r['session']
    pa = r['per_tournament']['A']['cev_per_stack']
    pb = r['per_tournament']['B']['cev_per_stack']
    decomp = (s['cev_per_stack_total'] is not None
              and abs(s['cev_per_stack_total'] - (pa + pb)) < 1e-6)
    print(f"{PASS if decomp else FAIL} total {s['cev_per_stack_total']} "
          f"== per-t sum {round(pa + pb, 4)}")
    # NOT the old Sum(net)/mean_start form (which would be 0.0 here)
    not_meanstart = (s['cev_per_stack_total']
                     != s.get('cev_per_stack_total_meanstart'))
    print(f"{PASS if not_meanstart else FAIL} differs from Sum(net)/"
          f"mean_start form ({s.get('cev_per_stack_total_meanstart')})")
    res_scope = s.get('n_hands_resolved') == 2
    print(f"{PASS if res_scope else FAIL} per-100 denominator = resolved "
          f"hands ({s.get('n_hands_resolved')})")
    return decomp and not_meanstart and res_scope


def t10_variance_cev_unit():
    """v7.63: every variance layer is in chips / tournament starting stack,
    and per-100 is normalized over RESOLVED hands."""
    print("\nT10: variance_cev layers share the starting-stack unit")
    from gem_cev import compute_variance_cev
    hands = [
        {'tournament_id': 'A', 'tournament': 'TA', 'id': 'A1', 'level': 1,
         'bb_blind': 200, 'net_bb': -8.0, 'eff_stack_bb': 8.0,
         'stack_bb': 125, 'cards': ['Ac', 'Ad']},
        {'tournament_id': 'A', 'tournament': 'TA', 'id': 'A2', 'level': 1,
         'bb_blind': 200, 'net_bb': +3.0, 'eff_stack_bb': 50.0,
         'stack_bb': 125, 'cards': ['7c', '2d']},
    ]
    stats = {'eai': {'hands': [{'id': 'A1', 'category': 'flip'}]},
             'coolers': {'hands': [], 'count': 0},
             'card_quality': {'prem_strong_pct': 5.9}}
    out = compute_variance_cev(hands, stats, {}, compute_cev_per_stack(hands))
    unit_ok = out.get('unit') == 'chips / tournament starting stack'
    print(f"{PASS if unit_ok else FAIL} unit tag = '{out.get('unit')}'")
    avail = out.get('available') and out.get('n_hands_resolved') == 2
    print(f"{PASS if avail else FAIL} available, resolved-hand count = 2 "
          f"({out.get('n_hands_resolved')})")
    eai = out.get('eai', {})
    expect = round((eai.get('cev_stacks') or 0) / 2 * 100, 4)
    p100_ok = abs((eai.get('cev_per_100') or 0) - expect) < 1e-4
    print(f"{PASS if p100_ok else FAIL} eai per-100 normalized over resolved "
          f"hands ({eai.get('cev_per_100')} == {expect})")
    return unit_ok and avail and p100_ok


def t11_eai_normalized_by_starting_stack():
    """v7.63 reverts B142: the EAI layer divides each all-in's chip swing by
    the TOURNAMENT STARTING stack, not the effective stack. Two identical
    all-ins in tournaments with different starting stacks give different cEV."""
    print("\nT11: EAI swing normalized by starting stack (B142 reverted)")
    from gem_cev import compute_variance_cev

    def _eai_one(stack_bb):
        h = [{'tournament_id': 'T', 'tournament': 'TT', 'id': 'H1',
              'level': 1, 'bb_blind': 200, 'net_bb': -10.0,
              'eff_stack_bb': 10.0, 'stack_bb': stack_bb,
              'cards': ['Kc', 'Ks']}]
        st = {'eai': {'hands': [{'id': 'H1', 'category': 'flip'}]},
              'coolers': {'hands': [], 'count': 0},
              'card_quality': {'prem_strong_pct': 5.9}}
        return compute_variance_cev(h, st, {}, compute_cev_per_stack(h))

    small = _eai_one(125).get('eai', {}).get('cev_stacks')   # start 25,000
    big = _eai_one(250).get('eai', {}).get('cev_stacks')      # start 50,000
    # 2x starting stack -> half the cEV. Compare the ratio (cev_stacks is
    # rounded to 4 dp, so an absolute 2*big check is too tight).
    halves = (small is not None and big is not None and abs(big) > 1e-9
              and abs(small / big - 2.0) < 0.02)
    print(f"{PASS if halves else FAIL} 2x starting stack -> half the cEV "
          f"({small} vs {big}, ratio {round(small / big, 3) if big else 'n/a'})")
    not_identical = (small is not None and big is not None and small != big)
    print(f"{PASS if not_identical else FAIL} not effective-stack-normalized "
          f"(would be identical under B142)")
    return halves and not_identical


if __name__ == '__main__':
    results = [t1_l1_observed(), t2_ladder_extrapolation(), t3_unresolved(),
               t4_net_chips_and_cev(), t5_unresolved_skipped_from_aggregate(),
               t6_eai_effstack_bounded(), t7_attribution_collector(),
               t8_dealt_cards_and_made_hands(),
               t9_decomposable_surface(), t10_variance_cev_unit(),
               t11_eai_normalized_by_starting_stack()]
    if all(results):
        print(f"\nALL {len(results)} TESTS PASSED \u2713")
    else:
        print(f"\n{results.count(False)} TEST(S) FAILED \u2717")
        raise SystemExit(1)
