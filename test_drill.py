#!/usr/bin/env python3
"""
test_drill.py — basic suite for gem_drill.py prototype.
Per intake checklist: tests must ship with the detector.
"""

import sys
import random
sys.path.insert(0, '/home/claude')
from gem_drill import (
    spr_bucket, hand_to_record, bootstrap_ci_mean, gates_pass, drill,
    collect_leaves, generate_tldr, generate_roadmap, generate_questions,
    expand_untextured_leaf, filter_records_by_path,
    EXPANSION_MIN_N, EXPANSION_MIN_LOSS, EXPANSION_TOP_K,
    MIN_N, MIN_LOSS_BB, TOP_K, DIM_PRIORITY,
    # v0.4 additions
    stack_bucket, position_bucket, extract_action_type,
    hand_to_postflop_record, hand_to_preflop_record,
    generate_postflop_questions, generate_preflop_questions,
    POSTFLOP_PROFILE, PREFLOP_PROFILE, run_profile, expand_leaf_by_dim,
)
# MAX_DEPTH is no longer a module constant in v0.4 (now derived per-profile from
# len(dim_priority)). Tests that referenced it now use len(DIM_PRIORITY) directly.
MAX_DEPTH = len(DIM_PRIORITY)


tests_run = 0
tests_passed = 0


def check(cond, msg):
    global tests_run, tests_passed
    tests_run += 1
    if cond:
        tests_passed += 1
        print(f'  ✓ {msg}')
    else:
        print(f'  ✗ FAIL: {msg}')


# --- spr_bucket ---
def test_spr_bucket():
    print('spr_bucket:')
    check(spr_bucket(None) == 'unknown', 'None → unknown')
    check(spr_bucket(-0.1) == 'unknown', 'negative → unknown')
    check(spr_bucket(0.5) == '<1', '0.5 → <1')
    check(spr_bucket(1.0) == '1-3', '1.0 → 1-3 (lower bound)')
    check(spr_bucket(2.99) == '1-3', '2.99 → 1-3')
    check(spr_bucket(3.0) == '3-7', '3.0 → 3-7 (lower bound)')
    check(spr_bucket(6.99) == '3-7', '6.99 → 3-7')
    check(spr_bucket(7.0) == '7+', '7.0 → 7+ (lower bound)')
    check(spr_bucket(100) == '7+', '100 → 7+')


# --- hand_to_record ---
def test_hand_to_record():
    print('hand_to_record:')
    h = {
        'board': ['7c','7s','9d'], 'pfr': True, 'pot_type': '3BP',
        'tournament_phase': 'late_reg', 'hero_ip': True,
        'board_texture': 'paired', 'spr': 2.5, 'net_bb': -10.0,
    }
    r = hand_to_record(h)
    check(r is not None, 'postflop hand → record')
    check(r['pfr_role'] == 'PFR', 'pfr=True → PFR')
    check(r['pos_class'] == 'IP', 'hero_ip=True → IP')
    check(r['spr'] == '1-3', 'spr 2.5 → 1-3 bucket')
    check(r['net_bb'] == -10.0, 'net_bb passes through')

    check(hand_to_record({'pfr': False, 'net_bb': -1}) is None, 'no board → None')

    h_allin = {**h, 'pf_allin': True}
    check(hand_to_record(h_allin) is None, 'pf_allin=True → None (no postflop decision)')

    h_caller = {**h, 'pfr': False, 'hero_ip': False}
    r2 = hand_to_record(h_caller)
    check(r2['pfr_role'] == 'caller' and r2['pos_class'] == 'OOP', 'caller OOP correctly tagged')


# --- bootstrap_ci_mean ---
def test_bootstrap_ci_mean():
    print('bootstrap_ci_mean:')
    check(bootstrap_ci_mean([]) is None, 'empty → None')
    ci = bootstrap_ci_mean([-2.0]*100, n_samples=200, seed=1)
    check(ci[1] < 0, f'all-negative input → CI hi<0 (got {ci})')
    ci_zero = bootstrap_ci_mean([0.0]*100, n_samples=200, seed=1)
    check(ci_zero[0] == 0.0 and ci_zero[1] == 0.0, 'all-zero input → CI=(0,0)')
    # Determinism
    a = bootstrap_ci_mean([1.0,-1.0,2.0,-2.0]*30, n_samples=300, seed=99)
    b = bootstrap_ci_mean([1.0,-1.0,2.0,-2.0]*30, n_samples=300, seed=99)
    check(a == b, 'same seed → identical CI')


# --- gates_pass ---
def test_gates_n_floor():
    print('gates: n floor')
    recs = [{'net_bb': -10}] * (MIN_N - 1)
    ok, reason = gates_pass(recs)
    check(not ok and 'n=' in reason, f'n<{MIN_N} rejected ({reason})')


def test_gates_winning():
    print('gates: winning child')
    recs = [{'net_bb': 5}] * 50
    ok, reason = gates_pass(recs)
    check(not ok and 'winning' in reason, f'winning child rejected ({reason})')


def test_gates_small_loss():
    print('gates: small absolute loss')
    recs = [{'net_bb': -0.5}] * 50  # -25 BB total < 50
    ok, reason = gates_pass(recs)
    check(not ok and 'loss=' in reason, f'small loss rejected ({reason})')


def test_gates_noisy_mean():
    print('gates: noisy mean (heavy tail)')
    rng = random.Random(0)
    # Heavy-tail mostly +/- 50, mean barely negative
    vals = [50 if rng.random() < 0.49 else -50 for _ in range(200)]
    recs = [{'net_bb': v} for v in vals]
    ok, reason = gates_pass(recs)
    # CI should cross 0 due to massive variance even though total loss > 50
    if abs(sum(vals)) >= 50:  # only test if we hit the abs-loss gate
        check(not ok and 'CI' in reason, f'heavy-tail mean rejected by CI ({reason})')
    else:
        print(f'    (skipped — random draw landed below loss floor: total={sum(vals)})')


def test_gates_clean_pass():
    print('gates: clean concentrated leak')
    recs = [{'net_bb': -2}] * 100  # -200 BB total, low variance
    ok, reason = gates_pass(recs)
    check(ok, f'clean leak passes ({reason})')


# --- drill ---
def _make_recs(role, pot, phase, pos, tex, spr_b, net, count):
    return [{'pfr_role': role, 'pot_type': pot, 'icm_phase': phase,
             'pos_class': pos, 'texture': tex, 'spr': spr_b, 'net_bb': net}
            for _ in range(count)]


def test_drill_max_depth():
    print('drill: max depth termination')
    # Build a population that splits cleanly at every level
    recs = []
    for role in ['PFR', 'caller']:
        for pot in ['SRP', '3BP']:
            for phase in ['late_reg', 'post_reg']:
                # PFR×SRP×late_reg has the biggest leak
                if role == 'PFR' and pot == 'SRP' and phase == 'late_reg':
                    net = -3.0
                else:
                    net = -0.05
                for pos in ['IP', 'OOP']:
                    for tex in ['dynamic', 'paired']:
                        recs.extend(_make_recs(role, pot, phase, pos, tex, '3-7', net, 50))

    tree = drill(recs, [], 0, 0)
    def maxd(n):
        if not n.get('children'): return n['depth']
        return max(maxd(c) for c in n['children'])
    md = maxd(tree)
    check(md <= MAX_DEPTH, f'depth ≤ {MAX_DEPTH} (got {md})')


def test_drill_skip_uniform():
    print('drill: skip uniform dim')
    # All hands uniform on pfr_role and pot_type, vary on icm_phase
    recs = (_make_recs('PFR', '3BP', 'late_reg', 'IP', 'dynamic', '3-7', -3, 100) +
            _make_recs('PFR', '3BP', 'post_reg', 'IP', 'dynamic', '3-7', -0.05, 100))
    tree = drill(recs, [], 0, 0)
    check(tree.get('drilled_dim') == 'icm_phase',
          f'first split skips uniform pfr_role+pot_type, lands on icm_phase '
          f'(got {tree.get("drilled_dim")})')


def test_drill_fanout_cap():
    print(f'drill: fanout cap (top-{TOP_K})')
    # 4 distinct icm_phases all losing big — should drill into top-2 only
    recs = []
    for phase, net in [('late_reg', -3), ('post_reg', -2.5),
                       ('bubble_zone', -2), ('ft_zone', -1.5)]:
        recs.extend(_make_recs('PFR', '3BP', phase, 'IP', 'dynamic', '3-7', net, 50))
    tree = drill(recs, [], 0, 0)
    n_drilled = len(tree.get('children', []))
    check(n_drilled <= TOP_K, f'drilled into ≤{TOP_K} children (got {n_drilled})')
    # Skipped should contain the rest
    n_skipped_rest = sum(1 for s in tree.get('skipped', []) if s['dim'] == 'icm_phase')
    check(n_skipped_rest >= 4 - TOP_K,
          f'remaining children listed in skipped ({n_skipped_rest} skipped)')


def test_drill_no_drill_when_all_winning():
    print('drill: no drill if all sub-buckets winning')
    recs = _make_recs('PFR', 'SRP', 'late_reg', 'IP', 'dynamic', '3-7', +1.0, 100)
    tree = drill(recs, [], 0, 0)
    check(not tree.get('children'), 'all-winning uniform population → no drill')


def test_drill_finds_hidden_loss_in_winning_root():
    print('drill: finds losing pocket inside winning root')
    # Big winning bucket + small losing pocket in a different dim value
    recs = (_make_recs('PFR', 'SRP', 'late_reg', 'IP', 'dynamic', '3-7', +2.0, 500) +  # +1000 BB
            _make_recs('caller', '3BP', 'late_reg', 'OOP', 'dynamic', '<1', -3.0, 100))  # -300 BB
    # Root is +700 BB net, but caller branch is a real leak
    tree = drill(recs, [], 0, 0)
    check(tree['total_bb'] > 0, f'root is winning ({tree["total_bb"]:+.0f}BB)')
    check(bool(tree.get('children')), 'drill happened despite winning root')
    leaves = collect_leaves(tree)
    found_caller_leaf = any(
        any(d == 'pfr_role' and v == 'caller' for d, v in l['path']) for l in leaves
    )
    check(found_caller_leaf, 'losing caller branch surfaced as study target')


def test_drill_priority_order():
    print('drill: priority order respected when multiple dims would split')
    # Multiple dims could split; pfr_role should win (priority #1)
    recs = (_make_recs('PFR', '3BP', 'late_reg', 'IP', 'dynamic', '3-7', -3.0, 100) +
            _make_recs('caller', '3BP', 'late_reg', 'IP', 'dynamic', '3-7', -0.05, 100))
    tree = drill(recs, [], 0, 0)
    check(tree.get('drilled_dim') == 'pfr_role',
          f'priority-#1 dim chosen (got {tree.get("drilled_dim")})')


# --- v0.2 additions: TLDR / roadmap / questions ---

def test_generate_tldr_empty():
    print('TLDR: empty leaves')
    out = generate_tldr([])
    check('No confirmed leaks' in out, f'empty → no-leak message ({out[:60]})')


def test_generate_tldr_single():
    print('TLDR: single leaf')
    leaf = {'path': [('pfr_role','caller'), ('pot_type','3BP')], 'n': 100, 'mean_bb': -0.5}
    out = generate_tldr([leaf])
    check('Single confirmed leak' in out, f'single → single-leak message')


def test_generate_tldr_unanimous_pattern():
    print('TLDR: detects unanimous pattern')
    leaves = [
        {'path': [('pfr_role','caller'), ('pos_class','OOP'), ('pot_type','3BP')], 'n': 100, 'mean_bb': -0.5},
        {'path': [('pfr_role','caller'), ('pos_class','OOP'), ('pot_type','4BP')], 'n': 80, 'mean_bb': -0.4},
        {'path': [('pfr_role','caller'), ('pos_class','OOP'), ('pot_type','SRP')], 'n': 60, 'mean_bb': -0.3},
    ]
    out = generate_tldr(leaves)
    check('all 3' in out and 'pfr_role=caller' in out, f'unanimous pfr_role detected ({out[:120]})')
    check('pos_class=OOP' in out, f'unanimous pos_class detected')


def test_generate_tldr_strong_majority():
    print('TLDR: detects 75%+ majority')
    leaves = [
        {'path': [('pfr_role','caller'), ('pos_class','OOP')], 'n': 100, 'mean_bb': -0.5},
        {'path': [('pfr_role','caller'), ('pos_class','OOP')], 'n': 80, 'mean_bb': -0.4},
        {'path': [('pfr_role','caller'), ('pos_class','OOP')], 'n': 60, 'mean_bb': -0.3},
        {'path': [('pfr_role','PFR'),    ('pos_class','IP')],  'n': 40, 'mean_bb': -0.2},
    ]
    out = generate_tldr(leaves)
    # 3 of 4 = 75%
    check('3 of 4' in out and 'pfr_role=caller' in out, f'75% majority surfaced ({out[:120]})')


def test_generate_tldr_diffuse():
    print('TLDR: no pattern (diffuse)')
    leaves = [
        {'path': [('pfr_role','caller'), ('pot_type','SRP')], 'n': 100, 'mean_bb': -0.5},
        {'path': [('pfr_role','PFR'),    ('pot_type','3BP')], 'n': 80, 'mean_bb': -0.4},
        {'path': [('pfr_role','caller'), ('pot_type','4BP')], 'n': 60, 'mean_bb': -0.3},
        {'path': [('pfr_role','PFR'),    ('pot_type','SRP')], 'n': 40, 'mean_bb': -0.2},
    ]
    out = generate_tldr(leaves)
    check('diverse' in out or 'no single dim' in out, f'diffuse → diverse message ({out[:120]})')


def test_generate_roadmap_below_target():
    print('roadmap: leaves capture less than 10%')
    records = [{'net_bb': -10}] * 1000  # total negative = 10,000
    leaves = [{'total_bb': -200}, {'total_bb': -100}]  # 300/10000 = 3%
    out = generate_roadmap(records, leaves)
    check('10,000 BB' in out, 'shows total negative')
    check('300 BB' in out and '3.0%' in out, 'shows captured + percentage')
    check('⚠' in out and 'short' in out, 'flags as below target')


def test_generate_roadmap_meets_target():
    print('roadmap: leaves capture 10%+')
    records = [{'net_bb': -10}] * 100  # total negative = 1,000
    leaves = [{'total_bb': -200}]  # 200/1000 = 20%
    out = generate_roadmap(records, leaves)
    check('✓' in out and 'clears' in out.lower() or 'threshold' in out.lower(),
          f'flags as meeting target ({out[:200]})')


def test_generate_questions_caller_3bp_oop_paired():
    print('questions: caller × 3BP × OOP × paired generates ≥5 questions')
    leaf = {'path': [
        ('pfr_role','caller'), ('pot_type','3BP'), ('icm_phase','late_reg'),
        ('pos_class','OOP'), ('texture','paired'), ('spr','<1')
    ]}
    qs = generate_questions(leaf)
    check(len(qs) >= 5, f'at least 5 questions (got {len(qs)})')
    check(any('3-bet' in q for q in qs), 'mentions 3-bet (caller in 3BP context)')
    check(any('paired' in q for q in qs), 'mentions paired texture')
    check(any('SPR' in q or 'commitment' in q.lower() for q in qs), 'mentions SPR/commitment')
    check(any('population' in q.lower() or 'exploit' in q.lower() for q in qs), 'has pop-exploit question')


def test_generate_questions_pfr_srp_ip_dynamic():
    print('questions: PFR × SRP × IP × dynamic')
    leaf = {'path': [
        ('pfr_role','PFR'), ('pot_type','SRP'), ('icm_phase','bubble_zone'),
        ('pos_class','IP'), ('texture','dynamic'), ('spr','3-7')
    ]}
    qs = generate_questions(leaf)
    check(len(qs) >= 5, f'at least 5 questions (got {len(qs)})')
    check(any('PFR' in q or 'opening' in q for q in qs), 'mentions PFR / opening')
    check(any('bubble_zone' in q or 'ICM' in q for q in qs), 'mentions ICM (bubble phase)')
    check(any('multi-street' in q.lower() or 'streets' in q.lower() for q in qs), 'mentions street planning')


# --- v0.3 additions: texture expansion ---

def test_filter_records_by_path():
    print('filter_records_by_path: subsets by path constraints')
    recs = (_make_recs('PFR', '3BP', 'late_reg', 'IP', 'dynamic', '3-7', -1, 50) +
            _make_recs('caller', '3BP', 'late_reg', 'IP', 'dynamic', '3-7', -1, 30))
    filtered = filter_records_by_path(recs, [('pfr_role','PFR')])
    check(len(filtered) == 50, f'PFR-only filter (got {len(filtered)})')
    filtered2 = filter_records_by_path(recs, [('pfr_role','caller'), ('pot_type','3BP')])
    check(len(filtered2) == 30, f'caller × 3BP filter (got {len(filtered2)})')
    filtered3 = filter_records_by_path(recs, [('pfr_role','PFR'), ('pot_type','SRP')])
    check(len(filtered3) == 0, 'no-match filter returns empty')


def test_expand_skips_textured_leaves():
    print('expand: skips leaves that already have texture in path')
    leaf = {'path': [('pfr_role','caller'), ('texture','paired')]}
    sub = expand_untextured_leaf(leaf, [])
    check(sub == [], 'textured leaf returns empty (no expansion)')


def test_expand_returns_top_k_textures():
    print(f'expand: returns top-{EXPANSION_TOP_K} textures by loss')
    # Build a leaf that aggregates 3 textures with different losses
    recs = (_make_recs('caller', '3BP', 'late_reg', 'OOP', 'paired', '<1', -3.0, 50) +    # -150
            _make_recs('caller', '3BP', 'late_reg', 'OOP', 'dynamic', '<1', -1.5, 40) +   # -60
            _make_recs('caller', '3BP', 'late_reg', 'OOP', 'monotone', '<1', -0.5, 30) +  # -15 (below MIN_LOSS)
            _make_recs('caller', '3BP', 'late_reg', 'OOP', 'low_dry', '<1', -2.0, 35))    # -70
    leaf = {'path': [('pfr_role','caller'), ('pot_type','3BP'), ('icm_phase','late_reg'),
                     ('pos_class','OOP'), ('spr','<1')]}
    sub = expand_untextured_leaf(leaf, recs)
    check(len(sub) == EXPANSION_TOP_K, f'returns exactly {EXPANSION_TOP_K} sub-rows (got {len(sub)})')
    # Should be sorted: paired (-150) first, low_dry (-70) second
    check(sub[0]['path'][-1] == ('texture', 'paired'), f'#1 is paired (worst loss): {sub[0]["path"][-1]}')
    check(sub[1]['path'][-1] == ('texture', 'low_dry'), f'#2 is low_dry: {sub[1]["path"][-1]}')


def test_expand_filters_low_n_and_low_loss():
    print('expand: drops sub-buckets below n or loss floor')
    # All textures below thresholds
    recs = (_make_recs('caller', '3BP', 'late_reg', 'OOP', 'paired', '<1', -1.0, 10) +     # n<20
            _make_recs('caller', '3BP', 'late_reg', 'OOP', 'dynamic', '<1', -0.1, 50))     # loss=-5<20
    leaf = {'path': [('pfr_role','caller'), ('pot_type','3BP'), ('icm_phase','late_reg'),
                     ('pos_class','OOP'), ('spr','<1')]}
    sub = expand_untextured_leaf(leaf, recs)
    check(sub == [], f'all sub-buckets fail loose gates → empty (got {len(sub)})')


def test_expand_sub_paths_preserve_parent():
    print('expand: sub-row paths extend (not replace) parent path')
    recs = _make_recs('caller', '3BP', 'late_reg', 'OOP', 'paired', '<1', -2.0, 50)
    leaf = {'path': [('pfr_role','caller'), ('pot_type','3BP'), ('icm_phase','late_reg'),
                     ('pos_class','OOP'), ('spr','<1')]}
    sub = expand_untextured_leaf(leaf, recs)
    check(len(sub) == 1, 'one passing sub')
    check(sub[0]['path'][:5] == leaf['path'], 'sub path begins with parent path')
    check(sub[0]['path'][-1][0] == 'texture', 'sub path ends with texture')


# --- v0.4 additions: profile architecture, preflop drill ---

def test_stack_bucket():
    print('stack_bucket: preflop depth bucketing')
    check(stack_bucket(None) == 'unknown', 'None → unknown')
    check(stack_bucket(5) == '<12', '5 → <12')
    check(stack_bucket(11.99) == '<12', '11.99 → <12')
    check(stack_bucket(12) == '12-25', '12 → 12-25 (lower bound)')
    check(stack_bucket(25) == '25-40', '25 → 25-40')
    check(stack_bucket(40) == '40-60', '40 → 40-60')
    check(stack_bucket(60) == '60+', '60 → 60+')
    check(stack_bucket(150) == '60+', '150 → 60+')


def test_position_bucket():
    print('position_bucket: coarse position bucketing')
    check(position_bucket('UTG') == 'EP', 'UTG → EP')
    check(position_bucket('MP') == 'MP', 'MP → MP')
    check(position_bucket('BTN') == 'LP', 'BTN → LP')
    check(position_bucket('CO') == 'LP', 'CO → LP')
    check(position_bucket('SB') == 'SB', 'SB → SB')
    check(position_bucket('BB') == 'BB', 'BB → BB')
    check(position_bucket(None) == 'unknown', 'None → unknown')


def test_extract_action_type_RFI():
    print('action_type: RFI detection')
    h = {'pfr': True, 'first_in': True, 'vpip': True}
    check(extract_action_type(h) == 'RFI', f"open RFI → 'RFI' (got {extract_action_type(h)})")


def test_extract_action_type_3bet():
    print('action_type: 3bet detection')
    h = {'hero_3bet': True, 'pfr': True, 'vpip': True}
    check(extract_action_type(h) == '3bet', f"3bet → '3bet'")
    h2 = {'hero_3bet': True, 'is_squeeze': True, 'pfr': True, 'vpip': True}
    check(extract_action_type(h2) == '3bet_squeeze', f"squeeze → '3bet_squeeze'")


def test_extract_action_type_call_jam():
    print('action_type: call_jam_lt15 detection (Ron-relevant)')
    h = {'lt15bb_call_jam': True, 'vpip': True}
    check(extract_action_type(h) == 'call_jam_lt15',
          f"≤15bb call jam → 'call_jam_lt15'")


def test_extract_action_type_call_4bet():
    print('action_type: call_4bet (the stack-off)')
    h = {'hero_called_4bet': True, 'vpip': True}
    check(extract_action_type(h) == 'call_4bet', f"call 4bet → 'call_4bet'")


def test_extract_action_type_priority_5bet_over_4bet():
    print('action_type: 5bet+ takes priority over 4bet')
    h = {'hero_5bet_plus': True, 'hero_4bet_only': True, 'pfr': True, 'vpip': True}
    check(extract_action_type(h) == '5bet+', "5bet+ priority over 4bet")


def test_hand_to_preflop_record_RFI():
    print('hand_to_preflop_record: RFI hand maps cleanly')
    h = {
        'pfr': True, 'first_in': True, 'vpip': True,
        'tournament_phase': 'late_reg', 'eff_stack_bb': 45,
        'position': 'CO', 'pot_type': 'SRP', 'net_bb': +2.5,
    }
    r = hand_to_preflop_record(h)
    check(r is not None, 'returns a record')
    check(r['action_type'] == 'RFI', f"action_type='RFI' (got {r['action_type']})")
    check(r['stack_bucket'] == '40-60', f"stack_bucket='40-60'")
    check(r['position_bucket'] == 'LP', f"position_bucket='LP'")
    check(r['pot_type'] == 'SRP', "pot_type passes through")
    check(r['net_bb'] == 2.5, "net_bb passes through")


def test_hand_to_preflop_record_walked_excluded():
    print('hand_to_preflop_record: walked hand returns None (no decision)')
    h = {'vpip': False, 'pfr': False}
    check(hand_to_preflop_record(h) is None, 'walked → None')


def test_hand_to_preflop_record_includes_postflop_seen():
    print('hand_to_preflop_record: includes hands that saw a flop')
    # A 3bet hand that saw a flop: the preflop decision (3bet) is what's measured
    h = {
        'hero_3bet': True, 'pfr': True, 'vpip': True,
        'board': ['Ah','7s','2c'],  # saw a flop
        'tournament_phase': 'late_reg', 'eff_stack_bb': 45,
        'position': 'BTN', 'pot_type': '3BP', 'net_bb': -8.0,
    }
    r = hand_to_preflop_record(h)
    check(r is not None, 'returns record despite board being present')
    check(r['action_type'] == '3bet', "preflop decision captured")


def test_drill_with_explicit_dim_priority():
    print('drill: accepts dim_priority parameter')
    # Build records using preflop schema
    recs = []
    for i in range(100):
        recs.append({
            'action_type': 'call_jam_lt15', 'icm_phase': 'late_reg',
            'stack_bucket': '12-25', 'position_bucket': 'BB', 'pot_type': 'SRP',
            'net_bb': -3.0,
        })
    pre_priority = ['action_type', 'icm_phase', 'stack_bucket', 'position_bucket', 'pot_type']
    tree = drill(recs, [], 0, 0, dim_priority=pre_priority)
    # All records identical → no drill possible (uniform on every dim)
    check(not tree.get('children'),
          'uniform records → no drill (algorithm respects custom dim_priority)')


def test_run_profile_postflop():
    print('run_profile: postflop profile end-to-end')
    hands = []
    for i in range(100):
        hands.append({
            'board': ['Ah','7s','2c'], 'pfr': False, 'pot_type': '3BP',
            'tournament_phase': 'late_reg', 'hero_ip': False,
            'board_texture': 'paired', 'spr': 0.5, 'net_bb': -2.0,
            'pf_allin': False,
        })
    # Add some PFR-side winning hands so the root is mixed
    for i in range(100):
        hands.append({
            'board': ['Kh','9s','3c'], 'pfr': True, 'pot_type': 'SRP',
            'tournament_phase': 'late_reg', 'hero_ip': True,
            'board_texture': 'dynamic', 'spr': 5, 'net_bb': +1.5,
            'pf_allin': False,
        })
    result = run_profile(hands, POSTFLOP_PROFILE)
    check(len(result['records']) == 200, f'extracted 200 records ({len(result["records"])})')
    check(result['profile'].name == 'postflop', 'profile name correct')
    check(len(result['leaves']) >= 1, f'at least 1 leaf surfaced ({len(result["leaves"])})')
    # Caller branch should be in a leaf
    if result['leaves']:
        leaf_path = result['leaves'][0]['path']
        check(any(d == 'pfr_role' and v == 'caller' for d, v in leaf_path),
              f'caller branch surfaced (path: {leaf_path})')


def test_run_profile_preflop():
    print('run_profile: preflop profile end-to-end')
    hands = []
    # Bad call_jam_lt15 hands (the leak)
    for i in range(100):
        hands.append({
            'lt15bb_call_jam': True, 'vpip': True,
            'tournament_phase': 'late_reg', 'eff_stack_bb': 14,
            'position': 'BB', 'pot_type': 'SRP', 'net_bb': -8.0,
        })
    # Good RFI hands (winning)
    for i in range(100):
        hands.append({
            'pfr': True, 'first_in': True, 'vpip': True,
            'tournament_phase': 'late_reg', 'eff_stack_bb': 50,
            'position': 'BTN', 'pot_type': 'SRP', 'net_bb': +1.5,
        })
    result = run_profile(hands, PREFLOP_PROFILE)
    check(len(result['records']) == 200, f'extracted 200 records')
    check(result['profile'].name == 'preflop', 'profile name correct')
    check(len(result['leaves']) >= 1, f'at least 1 leaf ({len(result["leaves"])})')
    if result['leaves']:
        path = result['leaves'][0]['path']
        check(any(d == 'action_type' and v == 'call_jam_lt15' for d, v in path),
              f'call_jam_lt15 surfaced as leak (path: {path})')


def test_generate_preflop_questions_call_jam():
    print('preflop questions: call_jam_lt15 generates push/fold thinking')
    leaf = {'path': [
        ('action_type', 'call_jam_lt15'), ('icm_phase', 'bubble_zone'),
        ('stack_bucket', '12-25'), ('position_bucket', 'BB'), ('pot_type', 'SRP'),
    ]}
    qs = generate_preflop_questions(leaf)
    check(len(qs) >= 5, f'at least 5 questions (got {len(qs)})')
    check(any('push/fold' in q.lower() or 'equity threshold' in q.lower() for q in qs),
          'mentions push/fold or equity threshold')
    check(any('bubble' in q.lower() or 'ICM' in q for q in qs), 'mentions ICM/bubble')


def test_generate_preflop_questions_call_4bet_warns():
    print('preflop questions: call_4bet flags it as stack-off')
    leaf = {'path': [
        ('action_type', 'call_4bet'), ('icm_phase', 'late_reg'),
        ('stack_bucket', '40-60'), ('position_bucket', 'LP'), ('pot_type', '4BP'),
    ]}
    qs = generate_preflop_questions(leaf)
    check(any('stack-off' in q.lower() or '⚠' in q for q in qs),
          'stack-off warning present')


def test_expand_leaf_by_dim_none():
    print('expand_leaf_by_dim: None expansion_dim → empty')
    leaf = {'path': [('action_type', 'RFI')]}
    sub = expand_leaf_by_dim(leaf, [], expansion_dim=None)
    check(sub == [], 'expansion_dim=None → no expansion')


def test_expand_leaf_by_dim_already_present():
    print('expand_leaf_by_dim: dim already in path → empty')
    leaf = {'path': [('texture', 'paired')]}
    sub = expand_leaf_by_dim(leaf, [], expansion_dim='texture')
    check(sub == [], 'texture already in path → no expansion')


# --- main ---
if __name__ == '__main__':
    print('test_drill.py — gem_drill v0.1 prototype suite\n')
    test_spr_bucket(); print()
    test_hand_to_record(); print()
    test_bootstrap_ci_mean(); print()
    test_gates_n_floor()
    test_gates_winning()
    test_gates_small_loss()
    test_gates_noisy_mean()
    test_gates_clean_pass(); print()
    test_drill_max_depth()
    test_drill_skip_uniform()
    test_drill_fanout_cap()
    test_drill_no_drill_when_all_winning()
    test_drill_finds_hidden_loss_in_winning_root()
    test_drill_priority_order(); print()
    test_generate_tldr_empty()
    test_generate_tldr_single()
    test_generate_tldr_unanimous_pattern()
    test_generate_tldr_strong_majority()
    test_generate_tldr_diffuse(); print()
    test_generate_roadmap_below_target()
    test_generate_roadmap_meets_target(); print()
    test_generate_questions_caller_3bp_oop_paired()
    test_generate_questions_pfr_srp_ip_dynamic(); print()
    test_filter_records_by_path()
    test_expand_skips_textured_leaves()
    test_expand_returns_top_k_textures()
    test_expand_filters_low_n_and_low_loss()
    test_expand_sub_paths_preserve_parent(); print()
    # v0.4 — preflop profile + architecture
    test_stack_bucket()
    test_position_bucket(); print()
    test_extract_action_type_RFI()
    test_extract_action_type_3bet()
    test_extract_action_type_call_jam()
    test_extract_action_type_call_4bet()
    test_extract_action_type_priority_5bet_over_4bet(); print()
    test_hand_to_preflop_record_RFI()
    test_hand_to_preflop_record_walked_excluded()
    test_hand_to_preflop_record_includes_postflop_seen(); print()
    test_drill_with_explicit_dim_priority()
    test_run_profile_postflop()
    test_run_profile_preflop(); print()
    test_generate_preflop_questions_call_jam()
    test_generate_preflop_questions_call_4bet_warns(); print()
    test_expand_leaf_by_dim_none()
    test_expand_leaf_by_dim_already_present()
    print(f'\n{tests_passed}/{tests_run} passed')
    sys.exit(0 if tests_passed == tests_run else 1)
