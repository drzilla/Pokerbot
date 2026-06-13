"""
test_textures.py — tests for gem_textures.py

Covers:
  - classify_archetype: 13 archetypes, edge cases, malformed input
  - get_gto_target: depth banding, side handling, TODO archetypes
  - sizing_within_target / freq_within_target
  - aggregate_compliance: full pipeline on synthetic hand records

Pattern matches test_parser.py / test_detectors.py — plain asserts, exit code 0
on success.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gem_textures as T

PASS, FAIL = 0, 0
def check(label, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {label}" + (f" — {detail}" if detail else ''))

# ----------------------------------------------------------------------
# CLASSIFIER — POSITIVE CASES
# ----------------------------------------------------------------------
print("=== Classifier: positive cases (one per archetype) ===")

POSITIVE = [
    # ace-high
    (['Ah','7s','2c'], 'ace_high_dry', 'A-7-2 rainbow disconnected'),
    (['As','8d','3c'], 'ace_high_dry', 'A-8-3 rainbow disconnected'),
    (['Ah','Js','9d'], 'ace_high_coordinated', 'A-J-9 rainbow with broadway'),
    (['Ah','Th','5c'], 'ace_high_coordinated', 'A-T-5 with broadway middle'),
    (['As','7s','5d'], 'ace_high_coordinated', 'A-7-5 two-tone'),
    (['Ah','7c','6s'], 'ace_high_coordinated', 'A-7-6 connected lower'),

    # broadway no-ace
    (['Kh','Qd','Tc'], 'broadway_coordinated', 'KQT three broadways rainbow'),
    (['Qh','Jd','Tc'], 'broadway_coordinated', 'QJT classic rainbow'),
    (['Ks','Jd','Tc'], 'broadway_coordinated', 'KJT rainbow (fixed: was Ks Js Td two-tone in v1.1 test)'),
    (['Kh','Qd','4c'], 'broadway_disconnected', 'K-Q-4 rainbow'),
    (['Kh','Qd','5c'], 'broadway_disconnected', 'K-Q-5 rainbow'),
    (['Qh','Jd','3c'], 'broadway_disconnected', 'Q-J-3 rainbow'),

    # middling
    (['9h','8d','7s'], 'middling_connected', '9-8-7 rainbow connected'),
    (['Th','9d','8s'], 'middling_connected', 'T-9-8 connected'),
    (['Th','9c','7s'], 'middling_connected', 'T-9-7 one-gapper'),
    (['9h','5d','2c'], 'middling_disconnected', '9-5-2 rainbow'),
    (['Th','6d','2c'], 'middling_disconnected', 'T-6-2 rainbow'),

    # low
    (['6h','5d','4s'], 'low_connected', '6-5-4 connected'),
    (['7h','6d','5s'], 'low_connected', '7-6-5 connected'),
    (['8h','6d','5s'], 'low_connected', '8-6-5 one-gapper'),
    (['7h','3d','2c'], 'low_ragged', '7-3-2 rainbow disconnected'),
    (['8h','4d','2c'], 'low_ragged', '8-4-2 rainbow disconnected'),

    # monotone
    (['Jh','6h','2h'], 'monotone', 'J-6-2 single suit'),
    (['Ah','Kh','Qh'], 'monotone', 'AKQ single suit (monotone trumps ace-high)'),
    (['5s','5s','5s'], 'monotone', 'fake test will fail other way; skip'),

    # paired
    (['8h','8d','3s'], 'paired_dry', 'rainbow paired disconnected'),
    (['Kh','Kd','3s'], 'paired_dry', 'KK3 rainbow'),
    (['9h','9d','8h'], 'paired_coordinated', '9-9-8 two-tone connected'),
    (['Th','Td','9c'], 'paired_coordinated', 'T-T-9 connected pair'),
    (['Qs','Qh','Jd'], 'paired_coordinated', 'Q-Q-J connected'),

    # tripleton
    (['5h','5d','5s'], 'tripleton', '5-5-5'),
    (['Ah','Ad','As'], 'tripleton', 'A-A-A'),

    # v1.2: broadway_two_tone (3 broadways + two-tone, separate from broadway_coordinated)
    (['Kh','Qh','Jd'], 'broadway_two_tone', 'KQJ two-tone'),
    (['Qh','Jh','Td'], 'broadway_two_tone', 'QJT two-tone'),
    (['Kh','Qh','Td'], 'broadway_two_tone', 'KQT two-tone'),

    # v1.2: high_low_low_two_tone (K/Q-high + two low cards + two-tone)
    (['Kh','6h','2d'], 'high_low_low_two_tone', 'K-6-2 two-tone'),
    (['Kh','7h','3d'], 'high_low_low_two_tone', 'K-7-3 two-tone'),
    (['Qh','5h','3d'], 'high_low_low_two_tone', 'Q-5-3 two-tone'),

    # v1.2: high_mid_low_two_tone (K/Q-high + middle 7-T card + low + two-tone)
    (['Kh','8h','3d'], 'high_mid_low_two_tone', 'K-8-3 two-tone'),
    (['Kh','9h','4d'], 'high_mid_low_two_tone', 'K-9-4 two-tone'),
    (['Qh','8h','2d'], 'high_mid_low_two_tone', 'Q-8-2 two-tone'),

    # v1.2: low_two_tone (top ≤ 8, two-tone — has FD potential vs rainbow low_ragged)
    (['5h','3h','2d'], 'low_two_tone', '5-3-2 two-tone'),
    (['6h','4h','2d'], 'low_two_tone', '6-4-2 two-tone'),
    (['7h','5h','3d'], 'low_two_tone', '7-5-3 two-tone'),
]

# Drop the placeholder (rank 5s,5s,5s would actually be tripleton but we're
# testing monotone-rules; remove that sentinel)
POSITIVE = [t for t in POSITIVE if t[2] != 'fake test will fail other way; skip']

for board, expected, desc in POSITIVE:
    got = T.classify_archetype(board)
    check(f"{' '.join(board)} -> {expected}", got == expected,
          f"got={got} ({desc})")

# ----------------------------------------------------------------------
# CLASSIFIER — PRIORITY ORDER
# ----------------------------------------------------------------------
print("\n=== Classifier: priority ordering ===")

# Monotone trumps everything except tripleton
check("Monotone with paired ranks → still treated as paired_? — actually monotone trumps if no pair",
      T.classify_archetype(['Ah','Kh','Qh']) == 'monotone')

# Tripleton trumps monotone (impossible board but tests precedence)
# can't have tripleton + monotone (3 same rank, 3 same suit = same card x3)
# Test paired+monotone instead:
# paired rank but monotone: actually monotone takes precedence
check("paired-rank monotone (8h-8c-3h is impossible, but 9h-3h-9h impossible too)",
      True, "(no valid card combo to test paired+monotone collision)")

# Ace-high paired → paired wins (because is_paired check fires first)
got = T.classify_archetype(['Ah','As','7c'])
check("AA7 paired → paired (not ace-high)", got in ('paired_dry', 'paired_coordinated'),
      f"got={got}")

# ----------------------------------------------------------------------
# CLASSIFIER — MALFORMED INPUT
# ----------------------------------------------------------------------
print("\n=== Classifier: malformed/edge cases ===")

check("Empty board → unknown", T.classify_archetype([]) == 'unknown')
check("None board → unknown", T.classify_archetype(None) == 'unknown')
check("Short board (turn cards only) → unknown",
      T.classify_archetype(['Ah','Kd']) == 'unknown')
check("Board with bogus rank → unknown",
      T.classify_archetype(['Xh','7s','2c']) == 'unknown')
check("Five-card board uses first 3 only",
      T.classify_archetype(['9h','8d','7s','2c','3d']) == 'middling_connected')

# ----------------------------------------------------------------------
# get_gto_target — DEPTH BANDING
# ----------------------------------------------------------------------
print("\n=== get_gto_target: depth bands ===")

# ace_high_dry has bands 0-25, 25-40, 40-999
deep = T.get_gto_target('ace_high_dry', 'ip', 100)
check("ace_high_dry IP @ 100BB returns deep band",
      deep is not None and deep['depth_band'] == '40-999BB')
check("ace_high_dry IP @ 100BB target sizing is [25]",
      deep is not None and deep['sizings_pct'] == [25])

mid = T.get_gto_target('ace_high_dry', 'ip', 30)
check("ace_high_dry IP @ 30BB returns mid band",
      mid is not None and mid['depth_band'] == '25-40BB')
check("ace_high_dry IP @ 30BB sizing is [20]",
      mid is not None and mid['sizings_pct'] == [20])

shallow = T.get_gto_target('ace_high_dry', 'ip', 20)
check("ace_high_dry IP @ 20BB returns shallow band (dual)",
      shallow is not None and shallow['dual_strategy'] is True)
check("ace_high_dry IP @ 20BB has 2 sizings",
      shallow is not None and len(shallow['sizings_pct']) == 2)

# ----------------------------------------------------------------------
# get_gto_target — v1.2 completed archetypes (previously TODO)
# ----------------------------------------------------------------------
print("\n=== get_gto_target: v1.2 completed archetypes ===")

# v1.2: tripleton, paired_dry, paired_coordinated, high_mid_low_two_tone (was two_tone_mixed),
# high_low_low_two_tone, broadway_two_tone, low_two_tone all now have IP+OOP scenarios.
check("tripleton IP now returns valid target (v1.2)",
      T.get_gto_target('tripleton', 'ip', 100) is not None)
check("tripleton OOP now returns valid target (v1.2)",
      T.get_gto_target('tripleton', 'oop', 100) is not None)
check("paired_dry OOP now returns valid target (v1.2)",
      T.get_gto_target('paired_dry', 'oop', 100) is not None)
check("paired_coordinated IP now returns valid target (v1.2)",
      T.get_gto_target('paired_coordinated', 'ip', 100) is not None)
check("high_mid_low_two_tone (was two_tone_mixed) IP now returns valid (v1.2)",
      T.get_gto_target('high_mid_low_two_tone', 'ip', 100) is not None)
check("v1.2 rename: two_tone_mixed no longer exists",
      T.get_gto_target('two_tone_mixed', 'ip', 100) is None)
check("broadway_two_tone IP now returns valid target (v1.2)",
      T.get_gto_target('broadway_two_tone', 'ip', 100) is not None)
check("low_two_tone IP returns valid target (v1.2 new archetype)",
      T.get_gto_target('low_two_tone', 'ip', 100) is not None)
check("low_two_tone OOP returns valid target (v1.2 new archetype)",
      T.get_gto_target('low_two_tone', 'oop', 100) is not None)
check("high_low_low_two_tone IP now returns valid target (v1.2)",
      T.get_gto_target('high_low_low_two_tone', 'ip', 100) is not None)

# v1.2: all 9 OOP-TODO archetypes now have OOP scenarios
check("ace_high_dry OOP now returns valid (v1.2)",
      T.get_gto_target('ace_high_dry', 'oop', 100) is not None)
check("monotone OOP now returns valid (v1.2)",
      T.get_gto_target('monotone', 'oop', 100) is not None)
check("low_ragged OOP now returns valid (v1.2)",
      T.get_gto_target('low_ragged', 'oop', 100) is not None)
check("middling_connected OOP now returns valid (v1.2)",
      T.get_gto_target('middling_connected', 'oop', 100) is not None)

# Unknown archetype
check("unknown archetype returns None",
      T.get_gto_target('does_not_exist', 'ip', 100) is None)

# ----------------------------------------------------------------------
# COMPLIANCE HELPERS
# ----------------------------------------------------------------------
print("\n=== Compliance helpers ===")

# sizing_within_target
check("Sizing 50 vs target [50] within tol 10 → True",
      T.sizing_within_target(50, [50]) is True)
check("Sizing 60 vs target [50] within tol 10 → True (exact edge)",
      T.sizing_within_target(60, [50]) is True)
check("Sizing 75 vs target [50] within tol 10 → False",
      T.sizing_within_target(75, [50]) is False)
check("Sizing 75 vs target [50, 100] within tol 10 → False (closest is 50, 25 away)",
      T.sizing_within_target(75, [50, 100]) is False)
check("Sizing 100 vs target [50, 100] within tol 10 → True",
      T.sizing_within_target(100, [50, 100]) is True)
check("No target sizings → None (unjudged)",
      T.sizing_within_target(50, []) is None)
check("None actual → None (unjudged)",
      T.sizing_within_target(None, [50]) is None)

# freq_within_target
check("Freq 80 in [80,95] → True",
      T.freq_within_target(80, [80, 95]) is True)
check("Freq 95 in [80,95] → True (high edge)",
      T.freq_within_target(95, [80, 95]) is True)
check("Freq 70 in [80,95] → False",
      T.freq_within_target(70, [80, 95]) is False)
check("Freq 100 in [80,95] → False (above range)",
      T.freq_within_target(100, [80, 95]) is False)
check("None target → None (unjudged)",
      T.freq_within_target(80, None) is None)
check("None actual → None (unjudged)",
      T.freq_within_target(None, [80, 95]) is None)

# ----------------------------------------------------------------------
# AGGREGATE COMPLIANCE — FULL PIPELINE
# ----------------------------------------------------------------------
print("\n=== aggregate_compliance: synthetic hands ===")

# Build synthetic hand records:
# Hero IP PFR on 9-8-7 (middling_connected, target IP freq 75-85, sizing [50])
#  - 5 hands, c-bet 4 (80% freq, on target)
#  - of the 4 c-bets, 3 used 50% sizing (on), 1 used 100% (off)
synthetic = []
for i, (cbet, sizing) in enumerate([(True, 50), (True, 50), (True, 50),
                                     (True, 100), (False, None)]):
    synthetic.append({
        'id': f'TEST{i:03d}',
        'board_archetype': 'middling_connected',
        'cbet_side': 'ip',
        'eff_stack_bb_flop': 80,
        'cbet_flop': cbet,
        'cbet_sizing_pct': sizing,
    })

result = T.aggregate_compliance(synthetic)
check("middling_connected/ip bucket exists",
      'middling_connected' in result and 'ip' in result['middling_connected'])

mc_ip = result['middling_connected']['ip']
check("n_opps == 5", mc_ip['n_opps'] == 5,
      f"got {mc_ip['n_opps']}")
check("n_cbet == 4", mc_ip['n_cbet'] == 4,
      f"got {mc_ip['n_cbet']}")
check("cbet_pct == 80.0", mc_ip['cbet_pct'] == 80.0,
      f"got {mc_ip['cbet_pct']}")
check("freq_compliant True (80 in [75,85])",
      mc_ip['freq_compliant'] is True)
check("sizing_judged_n == 4",
      mc_ip['sizing_judged_n'] == 4,
      f"got {mc_ip['sizing_judged_n']}")
check("sizing_compliant_n == 3 (3 of 4 used 50%)",
      mc_ip['sizing_compliant_n'] == 3,
      f"got {mc_ip['sizing_compliant_n']}")
check("sizing_compliance_pct == 75.0",
      mc_ip['sizing_compliance_pct'] == 75.0,
      f"got {mc_ip['sizing_compliance_pct']}")
check("verdict is 'deviation' (75% sizing < 60% threshold? actually 75%>=60% ⇒ compliant)",
      mc_ip['verdict'] == 'compliant',
      f"got {mc_ip['verdict']}")

# Test bad sample: low_connected/ip target freq is [0,10], if Hero c-bets always → deviation
synthetic2 = []
for i in range(5):
    synthetic2.append({
        'id': f'TEST2{i:03d}',
        'board_archetype': 'low_connected',
        'cbet_side': 'ip',
        'eff_stack_bb_flop': 60,
        'cbet_flop': True,
        'cbet_sizing_pct': 50,
    })
result2 = T.aggregate_compliance(synthetic2)
lc = result2['low_connected']['ip']
check("low_connected over-c-bet → freq_compliant False",
      lc['freq_compliant'] is False)
check("low_connected over-c-bet → verdict 'deviation'",
      lc['verdict'] == 'deviation')

# Test JUDGED archetype: v1.2 paired_dry now has targets (used to be TODO)
synthetic3 = [{
    'id': 'TEST3', 'board_archetype': 'paired_dry', 'cbet_side': 'ip',
    'eff_stack_bb_flop': 100, 'cbet_flop': True, 'cbet_sizing_pct': 50,
}]
result3 = T.aggregate_compliance(synthetic3)
# v1.2: paired_dry/ip now has scenarios so it should produce a verdict, not 'unjudged'
check("paired_dry/ip bucket now produces a real verdict in v1.2 (no longer unjudged)",
      'paired_dry' in result3 and result3['paired_dry']['ip']['verdict'] != 'unjudged',
      f"got verdict='{result3.get('paired_dry',{}).get('ip',{}).get('verdict','?')}'")

# Test truly-unknown archetype: passing a bogus id should produce unjudged or be ignored
synthetic3b = [{
    'id': 'TEST3b', 'board_archetype': 'does_not_exist_archetype', 'cbet_side': 'ip',
    'eff_stack_bb_flop': 100, 'cbet_flop': True, 'cbet_sizing_pct': 50,
}]
result3b = T.aggregate_compliance(synthetic3b)
check("unknown archetype is unjudged or absent from compliance result",
      'does_not_exist_archetype' not in result3b
      or result3b['does_not_exist_archetype']['ip']['verdict'] == 'unjudged',
      f"got: {result3b}")

# Test sample size labels
synthetic4 = [{
    'id': f'TEST4{i}', 'board_archetype': 'monotone', 'cbet_side': 'ip',
    'eff_stack_bb_flop': 80, 'cbet_flop': True, 'cbet_sizing_pct': 33,
} for i in range(2)]
result4 = T.aggregate_compliance(synthetic4)
check("n=2 → sample_size_label 'small'",
      result4['monotone']['ip']['sample_size_label'] == 'small')

synthetic5 = [{
    'id': f'TEST5{i}', 'board_archetype': 'monotone', 'cbet_side': 'ip',
    'eff_stack_bb_flop': 80, 'cbet_flop': True, 'cbet_sizing_pct': 33,
} for i in range(5)]
result5 = T.aggregate_compliance(synthetic5)
check("n=5 → sample_size_label 'thin'",
      result5['monotone']['ip']['sample_size_label'] == 'thin')

synthetic6 = [{
    'id': f'TEST6{i}', 'board_archetype': 'monotone', 'cbet_side': 'ip',
    'eff_stack_bb_flop': 80, 'cbet_flop': True, 'cbet_sizing_pct': 33,
} for i in range(10)]
result6 = T.aggregate_compliance(synthetic6)
check("n=10 → sample_size_label 'sufficient'",
      result6['monotone']['ip']['sample_size_label'] == 'sufficient')

# Hands with unknown archetype → silently dropped
synthetic7 = [{
    'id': 'TEST7', 'board_archetype': 'unknown', 'cbet_side': 'ip',
    'eff_stack_bb_flop': 80, 'cbet_flop': True, 'cbet_sizing_pct': 33,
}]
result7 = T.aggregate_compliance(synthetic7)
check("Unknown archetype → no bucket",
      'unknown' not in result7)

# ----------------------------------------------------------------------
# JSON STRUCTURE INTEGRITY
# ----------------------------------------------------------------------
print("\n=== JSON structure integrity ===")

T.load_data()
# v1.2 (2026-05-13): expanded from 13 to 16 archetypes
# (renamed two_tone_mixed → high_mid_low_two_tone, added low_two_tone +
# broadway_two_tone + high_low_low_two_tone — net +3 net of rename)
check("All 16 archetypes present (v1.2)",
      len(T.all_archetypes()) == 16,
      f"got {len(T.all_archetypes())}")

required_keys = {'id', 'display_name', 'example', 'groups_into',
                 'ip_cbet', 'oop_cbet', 'confidence', 'source'}
for a in T.all_archetypes():
    missing = required_keys - set(a.keys())
    check(f"Archetype {a.get('id')} has all required keys",
          not missing, f"missing={missing}")

# every groups_into value should be one of the existing parser buckets
EXISTING_PARSER_BUCKETS = {
    'paired', 'monotone', 'connected_mid', 'dry_ahigh', 'dynamic',
    'low_dry', 'other', 'unknown', 'none'
}
for a in T.all_archetypes():
    check(f"{a['id']} groups_into is a valid parser bucket",
          a['groups_into'] in EXISTING_PARSER_BUCKETS,
          f"got '{a['groups_into']}'")

# ----------------------------------------------------------------------
print(f"\n{'='*50}")
print(f"PASS: {PASS} | FAIL: {FAIL}")
sys.exit(0 if FAIL == 0 else 1)
