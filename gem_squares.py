#!/usr/bin/env python3
"""
gem_squares.py — v7.31 (2026-05-05)

Square-based history aggregation for big batches (50K-100K hands).
Bolt-on module. Daily pipeline (gem_parser.py / gem_analyzer.py /
gem_report_draft.py) is UNTOUCHED.

INVOKED MANUALLY for big-batch analysis:
  python3 gem_squares.py <history_dir>                # snapshot only
  python3 gem_squares.py <history_dir> --write-history  # also append snapshot
                                                         # to history file
  python3 gem_squares.py <history_dir> --write-gtow \\   # also write per-square
      --hh-source-dir /path/to/raw_hh                    # GTOW HH files +
                                                         # study setup MD

Why opt-in history: daily reruns during GEM fixes would otherwise pollute
the trajectory store. History append happens ONLY when --write-history is
passed.

Why opt-in GTOW: the HH files include 25 hands × 8 squares = ~200 hands
of raw HH per run. Skipping unless explicitly requested keeps default runs
lean. v7.31 integrates this since it was a high-value bridge to the actual
study workflow.

KEY DESIGN
==========
Each hand → 1 preflop square + 0-1 postflop squares.

Preflop square: PF_{pos_norm}_{stack_bucket}_{node}
  pos_norm: distance from BTN (BTN=0, CO=1, HJ=2, ...) or SB/BB
  stack_bucket: <12 / 12-25 / 25-40 / 40-60 / 60+
  node: RFI / cold_call / 3bet / 4bet+ / call_jam / hero_jams /
        faced_3bet_as_opener / fold / walked

Postflop square: PostF_{IP|OOP}_{pot_type}_{spr_bucket}_{icm_phase}
  pot_type: SRP / 3BP / 4BP
  spr_bucket: <1 / 1-3 / 3-7 / 7+
  icm_phase: from tournament_phase (late_reg/post_reg/bubble_zone/
             post_bubble/ft_zone/unknown)

PER-SQUARE METRICS
==================
- n_total, n_recent_30d, freq_pct
- avg_pot_bb (proxy: avg_eff_stack for preflop, spr * pot for postflop)
- avg_eff_stack
- net_bb per hand (Welford mean + variance)
- ewma_recent (half-life 14d) over last 30d
- rolling_full mean
- delta_z (regime detection — flag when |recent - full| / sigma > 2)
- study_score = freq_pct × avg_pot × |loss_magnitude|

KNOWN LIMITATIONS (v7.26)
=========================
- net_bb is biased by hand-strength composition. Premium-heavy squares
  show positive bias, premium-poor squares show negative. Over 50K+
  hands per square the distribution stabilizes, but cross-square
  comparison should be done with this in mind. v7.27 candidate:
  hand-strength normalization using card_quality buckets.
- Per-street postflop decomposition (separate flop/turn/river squares)
  not implemented in v0. One postflop square per hand = "the postflop
  decision context" only. v7.27 candidate.
- Pop-deviation overlay placeholder only (Appendix M catalog not yet
  programmatically wired). v7.27 candidate.
- Solver-chart preflop deviation routing stubbed (uses net_bb for now).
  v7.27 candidate when chart machine-readable form is ready.
"""

import os
import sys
import json
import math
import argparse
import glob
from datetime import datetime, timedelta, timezone
from collections import defaultdict


# =============================================================================
# CONSTANTS
# =============================================================================

VERSION = "7.32"

STACK_BUCKETS = [
    ("<12", 0, 12),
    ("12-25", 12, 25),
    ("25-40", 25, 40),
    ("40-60", 40, 60),
    ("60+", 60, float("inf")),
]

SPR_BUCKETS = [
    ("<1", 0, 1),
    ("1-3", 1, 3),
    ("3-7", 3, 7),
    ("7+", 7, float("inf")),
]

# Recent window for EWMA
RECENT_DAYS = 30
EWMA_HALF_LIFE_DAYS = 14
REGIME_Z_THRESHOLD = 2.0

# Granularity thresholds
SPLIT_MIN_N = 200
SPLIT_VARIANCE_THRESHOLD = 25.0  # net_bb^2 (~5bb std dev)
MERGE_MAX_N = 50
MERGE_PROFILE_EPSILON = 0.5  # bb/hand difference

# Position order around the table (clockwise from BTN going back)
POSITION_ORDER = ["BTN", "CO", "HJ", "MP", "UTG+1", "UTG"]


# =============================================================================
# WELFORD ONLINE VARIANCE
# =============================================================================

class Welford:
    """Single-pass numerically stable mean + variance."""

    __slots__ = ("n", "mean", "m2")

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0

    def add(self, x):
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    def variance(self):
        # Population variance (we have the population, not a sample)
        if self.n < 1:
            return 0.0
        return self.m2 / self.n

    def stddev(self):
        return math.sqrt(self.variance())


# =============================================================================
# POSITION NORMALIZATION
# =============================================================================

def position_norm(position, n_players=None):
    """
    Distance from BTN. BTN=0, CO=1, HJ=2, MP=3, UTG+1=4, UTG=5.
    SB/BB pass through unchanged. n_players is unused — positions that
    don't exist at a given table size simply don't populate.

    Returns string label (kept human-readable for square IDs).
    """
    if position in ("SB", "BB"):
        return position
    if position in POSITION_ORDER:
        return position  # use raw label; the position itself encodes distance
    return "UNK"


# =============================================================================
# BUCKETING
# =============================================================================

def stack_bucket(stack_bb):
    """Classify effective stack into bucket label."""
    if stack_bb is None:
        return "unknown"
    try:
        s = float(stack_bb)
    except (TypeError, ValueError):
        return "unknown"
    for label, lo, hi in STACK_BUCKETS:
        if lo <= s < hi:
            return label
    return "unknown"


def spr_bucket(spr):
    """Classify SPR into bucket label."""
    if spr is None:
        return "unknown"
    try:
        s = float(spr)
    except (TypeError, ValueError):
        return "unknown"
    for label, lo, hi in SPR_BUCKETS:
        if lo <= s < hi:
            return label
    return "unknown"


# =============================================================================
# SQUARE ASSIGNMENT
# =============================================================================

def preflop_node(hand):
    """Classify Hero's preflop decision context."""
    pf_action = hand.get("pf_action", "")
    vpip = hand.get("vpip", False)
    pfr = hand.get("pfr", False)
    first_in = hand.get("first_in", False)
    hero_3bet = hand.get("hero_3bet", False)
    hero_faced_raise = hand.get("hero_faced_raise", False)
    villain_jammed = hand.get("villain_jammed", False)
    pf_allin = hand.get("pf_allin", False)
    fold_to_3bet = hand.get("fold_to_3bet", False)
    fold_to_4bet = hand.get("fold_to_4bet", False)

    # Hero-initiated all-in preflop
    if pf_allin and pfr and not hero_faced_raise:
        return "hero_jams"

    # Faced a jam, called or folded
    if villain_jammed:
        if vpip:
            return "call_jam"
        return "fold_to_jam"

    # 4-bet+
    if pf_action == "4bet+":
        return "4bet_plus"

    # 3-bet
    if hero_3bet:
        return "3bet"

    # Hero opened, faced a 3-bet (and either folded or called)
    if pfr and hero_faced_raise and not hero_3bet:
        return "faced_3bet_as_opener"

    # Cold-called an open (no 3-bet)
    if vpip and hero_faced_raise and not hero_3bet:
        return "cold_call"

    # Hero opened first-in
    if first_in and pfr:
        return "RFI"

    # Folded
    if not vpip:
        return "fold"

    # Walked BB / limped pot etc
    return "other"


def assign_preflop_square(hand):
    """Returns square_id string, or None if unassignable."""
    pos = hand.get("position")
    if not pos:
        return None
    pos_n = position_norm(pos, hand.get("n_players"))
    stack = hand.get("eff_stack_bb") or hand.get("stack_bb")
    sb = stack_bucket(stack)
    node = preflop_node(hand)
    return f"PF_{pos_n}_{sb}_{node}"


def assign_postflop_square(hand):
    """
    Returns square_id string, or None if Hero didn't have a postflop decision.

    One postflop square per hand (the flop-entry context). Per-street
    decomposition is v7.27 future work.

    v7.31 fix: Exclude PF-all-in runouts and closed-pot spots. Previously these
    fell through to assign a postflop square because len(board) >= 3 was the only
    gate, but a dealt-out runout from a PF all-in has no Hero postflop decision
    to study. They were polluting the top study targets (the "unknown SPR" bucket
    was 60-86% PF all-ins). Filtering at assignment time means these hands now
    only generate a preflop square (which they should — that IS where the
    decision was).
    """
    board = hand.get("board") or []
    if len(board) < 3:
        return None

    # v7.31: Filter no-postflop-decision hands.
    # 1. Hero shoved or called a shove preflop → runout is variance, no decision
    if hand.get("pf_allin") or hand.get("pf_allin_flag"):
        return None
    # 2. Closed/degenerate pot — SPR <= 0.1 means committed > playable, no real
    #    postflop maneuvering room (e.g. Hero called a near-shove and is sub-1bb
    #    behind on the flop). Negative SPR shows up here too.
    spr = hand.get("spr")
    if spr is not None:
        try:
            if float(spr) <= 0.1:
                return None
        except (TypeError, ValueError):
            pass

    pot_type = hand.get("pot_type") or "SRP"
    spr_b = spr_bucket(spr)
    ip = hand.get("hero_ip", False)
    pos_class = "IP" if ip else "OOP"
    icm_phase = hand.get("tournament_phase") or "unknown"
    return f"PostF_{pos_class}_{pot_type}_{spr_b}_{icm_phase}"


# =============================================================================
# PER-SQUARE AGGREGATOR
# =============================================================================

class SquareAgg:
    """Accumulator for a single square."""

    def __init__(self, square_id):
        self.square_id = square_id
        self.kind = "preflop" if square_id.startswith("PF_") else "postflop"
        self.n = 0
        self.net_bb_welford = Welford()
        self.eff_stack_welford = Welford()
        self.pot_proxy_welford = Welford()
        # For EWMA / regime detection: list of (date_str, net_bb)
        self.events = []
        # Per-hand records that cap study volume
        self.went_to_sd_count = 0
        self.won_count = 0
        self.committed_bb_total = 0.0

    def add(self, hand):
        self.n += 1
        net_bb = hand.get("net_bb")
        if net_bb is not None:
            try:
                nb = float(net_bb)
                self.net_bb_welford.add(nb)
                date_str = hand.get("date") or ""
                self.events.append((date_str, nb))
            except (TypeError, ValueError):
                pass

        eff_stack = hand.get("eff_stack_bb") or hand.get("stack_bb")
        if eff_stack is not None:
            try:
                self.eff_stack_welford.add(float(eff_stack))
            except (TypeError, ValueError):
                pass

        # Pot proxy: for postflop use spr * eff_stack_bb implied pot,
        # for preflop use eff_stack_bb (what's at risk).
        if self.kind == "postflop":
            spr = hand.get("spr")
            es = hand.get("eff_stack_bb")
            if spr and es:
                try:
                    pot = float(es) / max(float(spr), 0.01)
                    self.pot_proxy_welford.add(pot)
                except (TypeError, ValueError):
                    pass
        else:
            if eff_stack is not None:
                try:
                    self.pot_proxy_welford.add(float(eff_stack))
                except (TypeError, ValueError):
                    pass

        if hand.get("went_to_sd"):
            self.went_to_sd_count += 1
        if hand.get("won"):
            self.won_count += 1
        committed = hand.get("hero_committed_bb")
        if committed is not None:
            try:
                self.committed_bb_total += float(committed)
            except (TypeError, ValueError):
                pass


# =============================================================================
# EWMA
# =============================================================================

def ewma_over_recent(events, reference_date, recent_days=RECENT_DAYS,
                     half_life_days=EWMA_HALF_LIFE_DAYS):
    """
    Compute EWMA of net_bb over the recent window.

    events: list of (date_str YYYY-MM-DD, net_bb) tuples
    reference_date: datetime — the "now" anchor
    Returns (ewma_value, n_recent) or (None, 0) if no recent events.
    """
    if not events:
        return (None, 0)
    decay = math.log(2) / max(half_life_days, 1)
    weighted_sum = 0.0
    weight_sum = 0.0
    n_recent = 0
    cutoff = reference_date - timedelta(days=recent_days)
    for date_str, value in events:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if d < cutoff:
            continue
        n_recent += 1
        age_days = (reference_date - d).total_seconds() / 86400.0
        w = math.exp(-decay * max(age_days, 0))
        weighted_sum += w * value
        weight_sum += w
    if weight_sum == 0:
        return (None, 0)
    return (weighted_sum / weight_sum, n_recent)


# =============================================================================
# SPLIT / MERGE PROPOSALS
# =============================================================================

def propose_split(agg):
    """Flag if this square is a candidate for splitting into sub-cells."""
    if agg.n < SPLIT_MIN_N:
        return False
    var = agg.net_bb_welford.variance()
    return var > SPLIT_VARIANCE_THRESHOLD


def propose_merge(agg, neighbors):
    """Flag if this square is a candidate for merging into a neighbor."""
    if agg.n >= MERGE_MAX_N:
        return False
    if agg.n == 0:
        return False
    own_mean = agg.net_bb_welford.mean
    for nbr in neighbors:
        if nbr.square_id == agg.square_id or nbr.n == 0:
            continue
        if abs(nbr.net_bb_welford.mean - own_mean) < MERGE_PROFILE_EPSILON:
            return True
    return False


def neighbors_of(square_id, all_ids):
    """Same kind + same dimensions except one — defined loosely as same prefix."""
    if not square_id:
        return []
    parts = square_id.split("_")
    if len(parts) < 3:
        return []
    prefix = "_".join(parts[:2])  # e.g. "PF_BTN" or "PostF_IP"
    return [sid for sid in all_ids if sid != square_id and sid.startswith(prefix)]


# =============================================================================
# REGIME DETECTION
# =============================================================================

def regime_flag(rolling_full_mean, ewma_recent, stddev):
    """
    Compare recent EWMA to long-term mean. Flag if |z| > threshold.
    Returns one of: 'improving' / 'regressing' / 'stable' / 'insufficient'.
    """
    if ewma_recent is None or rolling_full_mean is None or stddev is None:
        return "insufficient"
    if stddev <= 0.01:
        return "stable"
    z = (ewma_recent - rolling_full_mean) / stddev
    if z > REGIME_Z_THRESHOLD:
        return "improving"  # net_bb went UP relative to history
    if z < -REGIME_Z_THRESHOLD:
        return "regressing"  # net_bb went DOWN relative to history
    return "stable"


# =============================================================================
# MAIN AGGREGATION PIPELINE
# =============================================================================

def load_hands_from_dir(history_dir, since=None):
    """
    Stream hands from gem_hands.json files in a directory.
    Yields dicts. Tolerates missing files / malformed entries.

    since: optional 'YYYY-MM-DD' string — drop hands before this date.
    """
    if not os.path.isdir(history_dir):
        raise FileNotFoundError(f"history dir not found: {history_dir}")

    patterns = [
        os.path.join(history_dir, "**", "gem_hands.json"),
        os.path.join(history_dir, "**", "gem_hands_lean.json"),
        os.path.join(history_dir, "gem_hands*.json"),
    ]
    seen_files = set()
    paths = []
    for p in patterns:
        for f in glob.glob(p, recursive=True):
            if f not in seen_files:
                seen_files.add(f)
                paths.append(f)

    cutoff = None
    if since:
        try:
            cutoff = datetime.strptime(since, "%Y-%m-%d").date()
        except ValueError:
            cutoff = None

    n_files = 0
    n_hands = 0
    for path in paths:
        n_files += 1
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = list(data.values())
            if not isinstance(data, list):
                continue
            for hand in data:
                if not isinstance(hand, dict):
                    continue
                if cutoff:
                    d = hand.get("date") or ""
                    try:
                        if datetime.strptime(d, "%Y-%m-%d").date() < cutoff:
                            continue
                    except ValueError:
                        pass
                n_hands += 1
                yield hand
        except (json.JSONDecodeError, OSError):
            continue
    sys.stderr.write(f"[gem_squares] loaded {n_hands} hands from {n_files} files\n")


def aggregate_squares(hand_iter):
    """
    Single-pass aggregation. hand_iter is an iterable of hand dicts.
    Returns dict of {square_id: SquareAgg}.
    """
    aggs = {}
    total_hands = 0
    for hand in hand_iter:
        total_hands += 1
        pf_id = assign_preflop_square(hand)
        if pf_id:
            if pf_id not in aggs:
                aggs[pf_id] = SquareAgg(pf_id)
            aggs[pf_id].add(hand)
        post_id = assign_postflop_square(hand)
        if post_id:
            if post_id not in aggs:
                aggs[post_id] = SquareAgg(post_id)
            aggs[post_id].add(hand)
    return aggs, total_hands


def build_snapshot(aggs, total_hands, reference_date=None):
    """
    Build the gem_squares.json snapshot from aggregated data.
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc)

    all_ids = list(aggs.keys())
    squares = []
    for sid, agg in aggs.items():
        if agg.n == 0:
            continue
        ewma_val, n_recent = ewma_over_recent(agg.events, reference_date)
        rolling_mean = agg.net_bb_welford.mean
        stddev = agg.net_bb_welford.stddev()
        flag = regime_flag(rolling_mean, ewma_val, stddev)
        avg_pot = agg.pot_proxy_welford.mean if agg.pot_proxy_welford.n > 0 else 0.0

        # Study score = freq% × avg_pot × |loss_magnitude|
        # If square is winning, study_score is still computed (for split/merge),
        # but we negate the sign so positive scores = losses.
        loss_magnitude = max(-rolling_mean, 0.0)  # only count losses
        freq_pct = (agg.n / total_hands * 100.0) if total_hands > 0 else 0.0
        study_score = freq_pct * avg_pot * loss_magnitude

        squares.append({
            "square_id": sid,
            "kind": agg.kind,
            "n_total": agg.n,
            "n_recent_30d": n_recent,
            "freq_pct": round(freq_pct, 3),
            "avg_pot_bb": round(avg_pot, 2),
            "avg_eff_stack_bb": round(agg.eff_stack_welford.mean, 2),
            "net_bb_mean": round(rolling_mean, 4),
            "net_bb_variance": round(agg.net_bb_welford.variance(), 4),
            "net_bb_stddev": round(stddev, 4),
            "ewma_recent": round(ewma_val, 4) if ewma_val is not None else None,
            "regime_flag": flag,
            "delta_z": (
                round((ewma_val - rolling_mean) / stddev, 3)
                if (ewma_val is not None and stddev > 0.01) else None
            ),
            "wtsd_pct": round(100.0 * agg.went_to_sd_count / agg.n, 2),
            "win_pct": round(100.0 * agg.won_count / agg.n, 2),
            "split_candidate": propose_split(agg),
            "merge_candidate": propose_merge(agg, [aggs[i] for i in neighbors_of(sid, all_ids)]),
            "study_score": round(study_score, 4),
        })

    squares.sort(key=lambda s: s["study_score"], reverse=True)
    return {
        "version": VERSION,
        "generated_at": reference_date.isoformat(),
        "total_hands": total_hands,
        "n_squares": len(squares),
        "squares": squares,
    }


# =============================================================================
# HISTORY APPEND (opt-in)
# =============================================================================

def append_to_history(snapshot, history_path):
    """
    Append a compact snapshot row to the history JSON file.
    File format: list of {generated_at, total_hands, square_summaries: [...]}
    """
    if os.path.exists(history_path):
        try:
            with open(history_path) as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, OSError):
            history = []
    else:
        history = []

    summaries = [
        {
            "square_id": s["square_id"],
            "n_total": s["n_total"],
            "net_bb_mean": s["net_bb_mean"],
            "study_score": s["study_score"],
            "regime_flag": s["regime_flag"],
        }
        for s in snapshot["squares"]
    ]
    row = {
        "generated_at": snapshot["generated_at"],
        "total_hands": snapshot["total_hands"],
        "n_squares": snapshot["n_squares"],
        "summaries": summaries,
    }
    history.append(row)

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


# =============================================================================
# CLI
# =============================================================================

def main():
    ap = argparse.ArgumentParser(description="GEM v7.31 square aggregator")
    ap.add_argument("history_dir", help="Directory containing gem_hands*.json files (recursive)")
    ap.add_argument("--since", default=None, help="Drop hands before YYYY-MM-DD")
    ap.add_argument("--output", default="gem_squares.json", help="Snapshot output path")
    ap.add_argument("--write-history", action="store_true",
                    help="Append snapshot to gem_squares_history.json (opt-in)")
    ap.add_argument("--history-path", default="gem_squares_history.json",
                    help="History file path (only used with --write-history)")
    # v7.31: GTOW HH export integration. Opt-in like --write-history.
    # When set, also produces per-square HH files for direct GTOW import +
    # a markdown study setup with solver parameters / questions / sample hands.
    ap.add_argument("--write-gtow", action="store_true",
                    help="Also write per-square GTOW HH files + study setup MD (requires --hh-source-dir)")
    ap.add_argument("--hh-source-dir", default=None,
                    help="Directory of raw GG HH .txt files (required for --write-gtow)")
    ap.add_argument("--gtow-out-dir", default="gtow_hh",
                    help="Directory to write per-square HH files (default: gtow_hh/)")
    ap.add_argument("--gtow-setup-md", default="GTOW_Study_Setup.md",
                    help="Path for GTOW study setup markdown (default: GTOW_Study_Setup.md)")
    ap.add_argument("--gtow-top", type=int, default=8,
                    help="Number of top actionable squares to include in GTOW export (default: 8)")
    ap.add_argument("--gtow-n-max", type=int, default=25,
                    help="Max stratified hands per square HH file (default: 25)")
    args = ap.parse_args()

    # Load hands ONCE — reused by both square aggregation and (optionally) GTOW HH export.
    # Without this we'd be loading the 250MB JSON twice.
    hand_iter = list(load_hands_from_dir(args.history_dir, since=args.since))
    aggs, total_hands = aggregate_squares(hand_iter)
    snapshot = build_snapshot(aggs, total_hands)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    sys.stderr.write(f"[gem_squares] wrote {args.output}\n")

    if args.write_history:
        append_to_history(snapshot, args.history_path)
        sys.stderr.write(f"[gem_squares] appended to {args.history_path}\n")
    else:
        sys.stderr.write("[gem_squares] history append skipped (no --write-history)\n")

    # v7.31: GTOW HH export
    if args.write_gtow:
        if not args.hh_source_dir:
            sys.stderr.write("[gem_squares] ERROR: --write-gtow requires --hh-source-dir (raw HH .txt directory)\n")
            sys.exit(1)
        if not os.path.isdir(args.hh_source_dir):
            sys.stderr.write(f"[gem_squares] ERROR: --hh-source-dir not a directory: {args.hh_source_dir}\n")
            sys.exit(1)

        # Build hand_id → raw HH index from source HH files
        sys.stderr.write(f"[gem_squares] building hand_id index from {args.hh_source_dir}/...\n")
        hand_index = _build_hh_index(args.hh_source_dir)
        sys.stderr.write(f"[gem_squares] indexed {len(hand_index):,} hand_id → HH mappings\n")

        # Defer-import gem_squares_gtow to avoid circular import (it imports from this module).
        from gem_squares_gtow import build_report as build_gtow_report

        report_md = build_gtow_report(
            squares_data=snapshot,
            hands=hand_iter,
            n_top=args.gtow_top,
            hand_index=hand_index,
            hh_out_dir=args.gtow_out_dir,
            hh_n_max=args.gtow_n_max,
        )
        with open(args.gtow_setup_md, "w", encoding="utf-8") as f:
            f.write(report_md)
        sys.stderr.write(f"[gem_squares] wrote {args.gtow_setup_md}\n")
        sys.stderr.write(f"[gem_squares] wrote per-square HH files to {args.gtow_out_dir}/\n")


def _build_hh_index(hh_dir):
    """Build hand_id → (file_path, byte_start, byte_end) index for raw HH files.

    Same logic as standalone build_hand_index.py — kept in-process here to
    avoid the user having to invoke a separate command. Fast (~1s for 50K hands).
    """
    import re as _re
    hand_boundary = _re.compile(r'^Poker Hand #(TM\d+):', _re.MULTILINE)
    index = {}
    paths = sorted(glob.glob(os.path.join(hh_dir, '*.txt')))
    for path in paths:
        try:
            with open(path, 'r') as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        positions = [m.start() for m in hand_boundary.finditer(content)]
        positions.append(len(content))
        for i in range(len(positions) - 1):
            chunk_start = positions[i]
            chunk_end = positions[i + 1]
            m = hand_boundary.match(content[chunk_start:chunk_start + 60])
            if m:
                index[m.group(1)] = [path, chunk_start, chunk_end]
    return index


if __name__ == "__main__":
    main()
