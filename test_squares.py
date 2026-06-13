#!/usr/bin/env python3
"""
test_squares.py — v7.26

Test suite for gem_squares.py. Target: ~50 assertions.

Coverage:
  - Square assignment (preflop nodes, postflop assignment, edge cases)
  - Position normalization across table sizes
  - Stack / SPR bucket boundaries (off-by-one)
  - Welford variance correctness (vs reference)
  - EWMA correctness (known input series)
  - Regime threshold detection
  - Split / merge logic
  - JSON schema stability
  - Round-trip integrity
"""

import os
import sys
import json
import math
import tempfile
from datetime import datetime, timezone

# Allow running from same dir
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gem_squares import (
    Welford,
    position_norm,
    stack_bucket,
    spr_bucket,
    preflop_node,
    assign_preflop_square,
    assign_postflop_square,
    SquareAgg,
    ewma_over_recent,
    propose_split,
    propose_merge,
    neighbors_of,
    regime_flag,
    aggregate_squares,
    build_snapshot,
    append_to_history,
    SPLIT_MIN_N,
    SPLIT_VARIANCE_THRESHOLD,
    MERGE_MAX_N,
    REGIME_Z_THRESHOLD,
)


# =============================================================================
# Tracking
# =============================================================================

PASS_COUNT = 0
FAIL_COUNT = 0
FAIL_MSGS = []


def t(name, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        FAIL_MSGS.append(f"FAIL: {name} {detail}")


# =============================================================================
# Welford
# =============================================================================

def test_welford():
    # Reference: numpy mean / var of [1, 2, 3, 4, 5]
    # mean = 3.0, population variance = 2.0
    w = Welford()
    for x in [1, 2, 3, 4, 5]:
        w.add(x)
    t("welford_mean_5", abs(w.mean - 3.0) < 1e-9, f"got {w.mean}")
    t("welford_variance_5", abs(w.variance() - 2.0) < 1e-9, f"got {w.variance()}")
    t("welford_n_5", w.n == 5)

    # Empty
    w0 = Welford()
    t("welford_empty_var", w0.variance() == 0.0)
    t("welford_empty_n", w0.n == 0)

    # Single value
    w1 = Welford()
    w1.add(7.5)
    t("welford_single_mean", w1.mean == 7.5)
    t("welford_single_var", w1.variance() == 0.0)

    # Negative values
    w2 = Welford()
    for x in [-3, -1, 1, 3]:
        w2.add(x)
    # mean=0, variance = (9+1+1+9)/4 = 5
    t("welford_neg_mean", abs(w2.mean - 0.0) < 1e-9, f"got {w2.mean}")
    t("welford_neg_var", abs(w2.variance() - 5.0) < 1e-9, f"got {w2.variance()}")

    # Numerical stability with large offset
    w3 = Welford()
    base = 1e9
    for x in [base, base + 1, base + 2, base + 3, base + 4]:
        w3.add(x)
    t("welford_large_offset_var", abs(w3.variance() - 2.0) < 1e-3,
      f"got {w3.variance()}")


# =============================================================================
# Position normalization
# =============================================================================

def test_position_norm():
    t("pos_btn", position_norm("BTN") == "BTN")
    t("pos_co", position_norm("CO") == "CO")
    t("pos_hj", position_norm("HJ") == "HJ")
    t("pos_sb", position_norm("SB") == "SB")
    t("pos_bb", position_norm("BB") == "BB")
    t("pos_unknown", position_norm("FOO") == "UNK")
    # Same label across table sizes — i.e., 4-handed CO and 9-handed CO map identically
    t("pos_co_4max", position_norm("CO", n_players=4) == "CO")
    t("pos_co_9max", position_norm("CO", n_players=9) == "CO")


# =============================================================================
# Stack bucket
# =============================================================================

def test_stack_bucket():
    t("sb_5", stack_bucket(5) == "<12")
    t("sb_11_99", stack_bucket(11.99) == "<12")
    t("sb_12_lower_edge", stack_bucket(12) == "12-25")
    t("sb_24_99", stack_bucket(24.99) == "12-25")
    t("sb_25_lower_edge", stack_bucket(25) == "25-40")
    t("sb_40_lower_edge", stack_bucket(40) == "40-60")
    t("sb_60_lower_edge", stack_bucket(60) == "60+")
    t("sb_200", stack_bucket(200) == "60+")
    t("sb_none", stack_bucket(None) == "unknown")
    t("sb_garbage", stack_bucket("foo") == "unknown")


# =============================================================================
# SPR bucket
# =============================================================================

def test_spr_bucket():
    t("spr_0_5", spr_bucket(0.5) == "<1")
    t("spr_1", spr_bucket(1) == "1-3")
    t("spr_2_99", spr_bucket(2.99) == "1-3")
    t("spr_3", spr_bucket(3) == "3-7")
    t("spr_7", spr_bucket(7) == "7+")
    t("spr_50", spr_bucket(50) == "7+")
    t("spr_none", spr_bucket(None) == "unknown")


# =============================================================================
# Preflop node
# =============================================================================

def test_preflop_node():
    rfi = {"first_in": True, "pfr": True, "pf_action": "raise", "vpip": True}
    t("node_rfi", preflop_node(rfi) == "RFI")

    threebet = {"hero_3bet": True, "vpip": True, "pfr": True, "pf_action": "3bet",
                "hero_faced_raise": True}
    t("node_3bet", preflop_node(threebet) == "3bet")

    fourbet = {"pf_action": "4bet+", "vpip": True, "pfr": True,
               "hero_faced_raise": True}
    t("node_4bet+", preflop_node(fourbet) == "4bet_plus")

    cold_call = {"vpip": True, "hero_faced_raise": True, "hero_3bet": False,
                 "pfr": False, "pf_action": "call"}
    t("node_cold_call", preflop_node(cold_call) == "cold_call")

    fold = {"vpip": False, "pf_action": "fold"}
    t("node_fold", preflop_node(fold) == "fold")

    call_jam = {"villain_jammed": True, "vpip": True, "pf_action": "call"}
    t("node_call_jam", preflop_node(call_jam) == "call_jam")

    fold_jam = {"villain_jammed": True, "vpip": False, "pf_action": "fold"}
    t("node_fold_to_jam", preflop_node(fold_jam) == "fold_to_jam")

    hero_jams = {"pf_allin": True, "pfr": True, "vpip": True,
                 "hero_faced_raise": False, "first_in": True}
    t("node_hero_jams", preflop_node(hero_jams) == "hero_jams")

    faced_3bet_open = {"pfr": True, "vpip": True, "hero_faced_raise": True,
                       "hero_3bet": False, "first_in": True}
    t("node_faced_3bet_as_opener",
      preflop_node(faced_3bet_open) == "faced_3bet_as_opener")


# =============================================================================
# Square assignment
# =============================================================================

def test_assign_preflop_square():
    h = {
        "position": "BTN", "n_players": 6, "eff_stack_bb": 30,
        "first_in": True, "pfr": True, "vpip": True, "pf_action": "raise",
    }
    sid = assign_preflop_square(h)
    t("assign_pf_btn", sid == "PF_BTN_25-40_RFI", f"got {sid}")

    h2 = {
        "position": "BB", "n_players": 6, "eff_stack_bb": 50,
        "vpip": True, "hero_3bet": True, "hero_faced_raise": True,
        "pfr": True, "pf_action": "3bet",
    }
    sid2 = assign_preflop_square(h2)
    t("assign_pf_bb_3bet", sid2 == "PF_BB_40-60_3bet", f"got {sid2}")

    h3 = {"position": None, "eff_stack_bb": 30}
    t("assign_pf_no_pos", assign_preflop_square(h3) is None)


def test_assign_postflop_square():
    h = {
        "board": ["Ah", "Kd", "5c"],
        "pot_type": "SRP",
        "spr": 4.5,
        "hero_ip": True,
        "tournament_phase": "post_reg",
    }
    sid = assign_postflop_square(h)
    t("assign_post_ip_srp_3-7",
      sid == "PostF_IP_SRP_3-7_post_reg", f"got {sid}")

    h2 = {
        "board": ["Ah", "Kd", "5c", "2s", "Tc"],
        "pot_type": "3BP",
        "spr": 0.6,
        "hero_ip": False,
        "tournament_phase": "ft_zone",
    }
    sid2 = assign_postflop_square(h2)
    t("assign_post_oop_3bp_lt1_ft",
      sid2 == "PostF_OOP_3BP_<1_ft_zone", f"got {sid2}")

    h3 = {"board": ["Ah", "Kd"]}  # only 2 cards, no flop
    t("assign_post_no_flop", assign_postflop_square(h3) is None)

    h4 = {"board": []}
    t("assign_post_empty_board", assign_postflop_square(h4) is None)


# =============================================================================
# EWMA
# =============================================================================

def test_ewma():
    # No events
    val, n = ewma_over_recent([], datetime(2026, 5, 1, tzinfo=timezone.utc))
    t("ewma_empty_val", val is None)
    t("ewma_empty_n", n == 0)

    # All events outside recent window
    old_events = [("2025-01-01", 5.0), ("2025-02-01", -3.0)]
    val, n = ewma_over_recent(old_events, datetime(2026, 5, 1, tzinfo=timezone.utc))
    t("ewma_all_old_val", val is None)
    t("ewma_all_old_n", n == 0)

    # Single recent event
    ref = datetime(2026, 5, 1, tzinfo=timezone.utc)
    val, n = ewma_over_recent([("2026-04-25", 10.0)], ref)
    t("ewma_single_val", abs(val - 10.0) < 1e-6, f"got {val}")
    t("ewma_single_n", n == 1)

    # Equally weighted (same date) → mean
    val, n = ewma_over_recent(
        [("2026-04-30", 4.0), ("2026-04-30", 6.0)],
        ref,
    )
    t("ewma_equal_dates_val", abs(val - 5.0) < 1e-6, f"got {val}")
    t("ewma_equal_dates_n", n == 2)

    # Decay: more recent should weight more
    val, n = ewma_over_recent(
        [("2026-04-01", 0.0), ("2026-04-30", 10.0)],  # older=0bb, recent=10bb
        ref,
    )
    # Recent has much more weight; should be > 5
    t("ewma_decay_skew_recent", val > 5.0, f"got {val}")


# =============================================================================
# Regime detection
# =============================================================================

def test_regime():
    # Stable: recent close to long-term
    f = regime_flag(rolling_full_mean=0.5, ewma_recent=0.6, stddev=2.0)
    t("regime_stable", f == "stable")

    # Improving: recent much higher than long-term (z > 2)
    # delta = 5.0, stddev = 1.0 → z = 5.0
    f = regime_flag(rolling_full_mean=0.0, ewma_recent=5.0, stddev=1.0)
    t("regime_improving", f == "improving")

    # Regressing: recent much lower
    f = regime_flag(rolling_full_mean=0.0, ewma_recent=-5.0, stddev=1.0)
    t("regime_regressing", f == "regressing")

    # Insufficient
    f = regime_flag(None, None, None)
    t("regime_insufficient", f == "insufficient")
    f = regime_flag(0.0, None, 1.0)
    t("regime_insufficient_no_ewma", f == "insufficient")


# =============================================================================
# Split / merge
# =============================================================================

def test_split_merge():
    # Below n threshold → no split
    agg_small = SquareAgg("PF_BTN_25-40_RFI")
    for _ in range(50):
        agg_small.add({"net_bb": 0.5, "date": "2026-04-01"})
    t("split_below_n", propose_split(agg_small) is False)

    # Above n threshold but low variance → no split
    agg_lowvar = SquareAgg("PF_BTN_25-40_RFI")
    for _ in range(SPLIT_MIN_N + 10):
        agg_lowvar.add({"net_bb": 0.5, "date": "2026-04-01"})
    t("split_low_var", propose_split(agg_lowvar) is False)

    # Above n threshold AND high variance → split candidate
    agg_highvar = SquareAgg("PF_BTN_25-40_RFI")
    import random
    random.seed(42)
    for _ in range(SPLIT_MIN_N + 10):
        agg_highvar.add({"net_bb": random.gauss(0, 10), "date": "2026-04-01"})
    t("split_high_var", propose_split(agg_highvar) is True)

    # Merge: small n + similar to neighbor
    a = SquareAgg("PF_BTN_60+_RFI")
    for _ in range(20):
        a.add({"net_bb": 0.3, "date": "2026-04-01"})
    b = SquareAgg("PF_BTN_40-60_RFI")
    for _ in range(500):
        b.add({"net_bb": 0.4, "date": "2026-04-01"})
    t("merge_small_similar", propose_merge(a, [b]) is True)

    # Big n → no merge regardless
    a2 = SquareAgg("PF_BTN_60+_RFI")
    for _ in range(500):
        a2.add({"net_bb": 0.3, "date": "2026-04-01"})
    t("merge_big_n", propose_merge(a2, [b]) is False)


# =============================================================================
# Neighbors
# =============================================================================

def test_neighbors():
    ids = [
        "PF_BTN_25-40_RFI",
        "PF_BTN_40-60_RFI",
        "PF_BTN_25-40_3bet",
        "PF_CO_25-40_RFI",
        "PostF_IP_SRP_3-7_post_reg",
    ]
    nbrs = neighbors_of("PF_BTN_25-40_RFI", ids)
    t("nbrs_btn_includes_other_btn",
      "PF_BTN_40-60_RFI" in nbrs and "PF_BTN_25-40_3bet" in nbrs)
    t("nbrs_btn_excludes_co", "PF_CO_25-40_RFI" not in nbrs)
    t("nbrs_btn_excludes_postflop",
      "PostF_IP_SRP_3-7_post_reg" not in nbrs)
    t("nbrs_excludes_self", "PF_BTN_25-40_RFI" not in nbrs)


# =============================================================================
# Aggregation pipeline
# =============================================================================

def make_synthetic_hands():
    """Build a synthetic hand list that exercises the pipeline end-to-end."""
    hands = []
    # 100 BTN RFI 25-40 stack hands, mostly winning
    for i in range(100):
        hands.append({
            "id": f"RFI_BTN_{i}",
            "date": "2026-04-15",
            "position": "BTN",
            "n_players": 6,
            "eff_stack_bb": 30,
            "stack_bb": 30,
            "first_in": True,
            "pfr": True,
            "vpip": True,
            "pf_action": "raise",
            "net_bb": 1.5 + (i % 5) * 0.1,
            "board": ["Ah", "Kd", "5c"],
            "pot_type": "SRP",
            "spr": 4.0,
            "hero_ip": True,
            "tournament_phase": "post_reg",
            "won": True,
            "went_to_sd": False,
            "hero_committed_bb": 2.5,
        })
    # 50 SB BvB hands losing money
    for i in range(50):
        hands.append({
            "id": f"SB_BvB_{i}",
            "date": "2026-04-20",
            "position": "SB",
            "n_players": 2,
            "eff_stack_bb": 50,
            "stack_bb": 50,
            "first_in": True,
            "pfr": True,
            "vpip": True,
            "pf_action": "raise",
            "net_bb": -2.0 - (i % 3),
            "board": ["2h", "7d", "Jc"],
            "pot_type": "SRP",
            "spr": 5.0,
            "hero_ip": False,
            "tournament_phase": "ft_zone",
            "won": False,
            "went_to_sd": False,
            "hero_committed_bb": 5.0,
        })
    return hands


def test_aggregate_pipeline():
    hands = make_synthetic_hands()
    aggs, total = aggregate_squares(hands)
    t("agg_total_hands", total == 150)
    # Should have at least 4 squares: BTN-RFI preflop, SB-RFI preflop, IP-SRP postflop, OOP-SRP postflop
    t("agg_n_squares_min", len(aggs) >= 4, f"got {len(aggs)}")
    btn_pf = "PF_BTN_25-40_RFI"
    t("agg_btn_pf_present", btn_pf in aggs)
    t("agg_btn_pf_n", aggs[btn_pf].n == 100)
    sb_pf = "PF_SB_40-60_RFI"
    t("agg_sb_pf_present", sb_pf in aggs)
    t("agg_sb_pf_n", aggs[sb_pf].n == 50)


def test_snapshot_structure():
    hands = make_synthetic_hands()
    aggs, total = aggregate_squares(hands)
    snap = build_snapshot(aggs, total,
                          reference_date=datetime(2026, 5, 1, tzinfo=timezone.utc))
    t("snap_has_version", snap.get("version") == "7.32")
    t("snap_has_squares_list", isinstance(snap.get("squares"), list))
    t("snap_total_hands", snap.get("total_hands") == 150)
    t("snap_n_squares", snap.get("n_squares") == len(snap["squares"]))

    # Sorted by study_score desc
    scores = [s["study_score"] for s in snap["squares"]]
    t("snap_sorted_desc", scores == sorted(scores, reverse=True))

    # Each square has required keys
    if snap["squares"]:
        s = snap["squares"][0]
        required = ["square_id", "kind", "n_total", "freq_pct", "avg_pot_bb",
                    "net_bb_mean", "net_bb_variance", "ewma_recent",
                    "regime_flag", "study_score", "split_candidate", "merge_candidate"]
        for k in required:
            t(f"snap_field_{k}", k in s, f"missing: {k}")

    # Losing square should have higher study_score than winning one
    losing = [s for s in snap["squares"] if "SB" in s["square_id"]]
    winning = [s for s in snap["squares"] if "BTN_25-40_RFI" in s["square_id"]]
    if losing and winning:
        t("snap_losing_scored_higher",
          losing[0]["study_score"] > winning[0]["study_score"],
          f"losing={losing[0]['study_score']}, winning={winning[0]['study_score']}")


# =============================================================================
# Round-trip + history
# =============================================================================

def test_history_round_trip():
    hands = make_synthetic_hands()
    aggs, total = aggregate_squares(hands)
    snap = build_snapshot(aggs, total,
                          reference_date=datetime(2026, 5, 1, tzinfo=timezone.utc))

    with tempfile.TemporaryDirectory() as tmp:
        history_path = os.path.join(tmp, "gem_squares_history.json")
        # Write twice to verify append behavior
        append_to_history(snap, history_path)
        append_to_history(snap, history_path)
        with open(history_path) as f:
            history = json.load(f)
        t("history_is_list", isinstance(history, list))
        t("history_two_rows", len(history) == 2)
        t("history_row_has_summaries", "summaries" in history[0])
        t("history_summaries_match_snap_count",
          len(history[0]["summaries"]) == len(snap["squares"]))


def test_snapshot_json_serializable():
    hands = make_synthetic_hands()
    aggs, total = aggregate_squares(hands)
    snap = build_snapshot(aggs, total,
                          reference_date=datetime(2026, 5, 1, tzinfo=timezone.utc))
    try:
        s = json.dumps(snap)
        t("snap_json_serializable", len(s) > 0)
    except (TypeError, ValueError) as e:
        t("snap_json_serializable", False, str(e))


# =============================================================================
# Edge cases
# =============================================================================

def test_edge_cases():
    # Empty input
    aggs, total = aggregate_squares([])
    t("edge_empty_total", total == 0)
    t("edge_empty_aggs", len(aggs) == 0)
    snap = build_snapshot(aggs, total)
    t("edge_empty_snap_squares", snap["squares"] == [])
    t("edge_empty_snap_n", snap["n_squares"] == 0)

    # Hand with missing critical fields
    bad = [{}]
    aggs, total = aggregate_squares(bad)
    t("edge_bad_total", total == 1)
    # No square assigned (no position, no board)
    t("edge_bad_no_aggs", len(aggs) == 0)

    # Hand with garbage net_bb shouldn't crash
    weird = [{
        "position": "BTN", "n_players": 6, "eff_stack_bb": 30,
        "first_in": True, "pfr": True, "vpip": True, "pf_action": "raise",
        "net_bb": "not a number",
        "date": "2026-04-15",
    }]
    aggs, total = aggregate_squares(weird)
    t("edge_garbage_netbb_doesnt_crash", total == 1)
    t("edge_garbage_netbb_square_present",
      "PF_BTN_25-40_RFI" in aggs)
    # net_bb didn't get added but n still incremented
    t("edge_garbage_netbb_n", aggs["PF_BTN_25-40_RFI"].n == 1)
    t("edge_garbage_welford_empty",
      aggs["PF_BTN_25-40_RFI"].net_bb_welford.n == 0)


# =============================================================================
# Run
# =============================================================================

def main():
    test_welford()
    test_position_norm()
    test_stack_bucket()
    test_spr_bucket()
    test_preflop_node()
    test_assign_preflop_square()
    test_assign_postflop_square()
    test_ewma()
    test_regime()
    test_split_merge()
    test_neighbors()
    test_aggregate_pipeline()
    test_snapshot_structure()
    test_history_round_trip()
    test_snapshot_json_serializable()
    test_edge_cases()

    print(f"\n{'=' * 60}")
    print(f"PASSED: {PASS_COUNT}  |  FAILED: {FAIL_COUNT}")
    print(f"{'=' * 60}")
    if FAIL_MSGS:
        print("\nFailures:")
        for m in FAIL_MSGS:
            print(f"  {m}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
