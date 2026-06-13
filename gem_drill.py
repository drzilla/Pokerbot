#!/usr/bin/env python3
"""
gem_drill.py — v0.4

Hierarchical drill-down leak finder for GEM. Loads parsed hands, aggregates
across N dimensions, walks priority order with bootstrap-CI significance gating
to produce GTOW-ready study targets.

Two profiles:

POSTFLOP (default) — drills hands with a flop using:
  pfr_role → pot_type → icm_phase → pos_class → texture → spr
  Texture decomposition for sim-loadability.

PREFLOP — drills preflop decisions (including hands without a flop) using:
  action_type → icm_phase → stack_bucket → position_bucket → pot_type
  Action types: RFI, cold_call, 3bet, call_3bet, 4bet, call_4bet, call_jam_lt15,
  iso_raise, fold_to_3bet, fold_vs_open, etc.

Both can run in one pass (--mode=both); output is a single combined report
with two TLDRs and a unified roadmap.

Algorithm (shared across profiles):
  At each node, try the next dim. If at least one child passes the gates,
  drill into the top-K passing children (by loss magnitude) and advance
  dim_idx. If no child passes, skip the dim and try the next one.

Gates per child (all three must hold):
  - n >= 30 (CLT floor for mean estimation)
  - |total loss| >= 50 BB (practical significance)
  - Bootstrap 90% CI on child mean excludes 0 on the negative side
    (mean loss is real, not noise from heavy-tailed distribution)

Fanout cap: top-2 passing children per parent. Max depth: dim_priority length.

Usage:
  python3 gem_drill.py <gem_hands.json> [--mode {postflop,preflop,both}]
                                        [--output ...] [--text-report ...]
"""

import json
import sys
import random
import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional


VERSION = "0.4.0"

# Algorithm constants (apply to both profiles)
MIN_N = 30
MIN_LOSS_BB = 50.0
BOOTSTRAP_SAMPLES = 1000
CI_ALPHA = 0.05  # two-sided 90% CI
TOP_K = 2

# Postflop dim priority (kept as module constant for backwards-compat with tests)
DIM_PRIORITY = ['pfr_role', 'pot_type', 'icm_phase', 'pos_class', 'texture', 'spr']


# =============================================================================
# BUCKETING
# =============================================================================

def spr_bucket(spr):
    """Match the bucket boundaries used by gem_squares.py for consistency."""
    if spr is None:
        return 'unknown'
    if spr < 0:
        return 'unknown'
    if spr < 1:
        return '<1'
    if spr < 3:
        return '1-3'
    if spr < 7:
        return '3-7'
    return '7+'


def stack_bucket(eff_bb):
    """Stack-depth bucket for preflop analysis (matches gem_squares.py preflop schema)."""
    if eff_bb is None:
        return 'unknown'
    if eff_bb < 12:
        return '<12'
    if eff_bb < 25:
        return '12-25'
    if eff_bb < 40:
        return '25-40'
    if eff_bb < 60:
        return '40-60'
    return '60+'


def position_bucket(pos):
    """Coarse position bucket for preflop analysis: EP / MP / LP / SB / BB."""
    if not pos:
        return 'unknown'
    if pos in ('UTG', 'UTG+1', 'UTG+2'):
        return 'EP'
    if pos in ('MP', 'MP+1', 'LJ'):
        return 'MP'
    if pos in ('HJ', 'CO', 'BTN'):
        return 'LP'
    if pos == 'SB':
        return 'SB'
    if pos == 'BB':
        return 'BB'
    return 'other'


def extract_action_type(h):
    """
    Derive Hero's primary preflop action from the hand's action flags.
    Priority order = specificity (most specific action first).
    Returns one of: '5bet+', '4bet', 'call_4bet', 'call_jam_lt15', '3bet_squeeze',
    '3bet', 'call_3bet', 'cold_call', 'iso_raise', 'RFI', 'fold_to_3bet',
    'fold_vs_open', 'walked', 'unknown'.
    """
    # Aggressive actions (most specific first)
    if h.get('hero_5bet_plus'):
        return '5bet+'
    if h.get('hero_4bet_only'):
        return '4bet'
    # Calling actions
    if h.get('hero_called_5bet'):
        return 'call_5bet'
    if h.get('hero_called_4bet'):
        return 'call_4bet'
    if h.get('lt15bb_call_jam'):
        return 'call_jam_lt15'
    if h.get('hero_called_3bet'):
        return 'call_3bet'
    # 3-bet / squeeze
    if h.get('hero_3bet'):
        return '3bet_squeeze' if h.get('is_squeeze') else '3bet'
    # Cold call
    if h.get('cold_called'):
        return 'cold_call'
    # First-in raise
    if h.get('pfr') and h.get('first_in'):
        return 'RFI'
    # Iso-raise (raised but not first in — over a limper)
    if h.get('pfr'):
        return 'iso_raise'
    # Folds (only meaningful when Hero faced action)
    if not h.get('vpip'):
        if h.get('fold_to_3bet'):
            return 'fold_to_3bet'
        if h.get('faced_steal_bb') and h.get('fold_to_steal_bb'):
            return 'fold_bb_vs_steal'
        # 'fold_vs_open' requires evidence of a faced open. Without any of:
        # fold_to_3bet, faced_steal_bb, faced_squeeze, opener_position — we treat
        # this as a walk (no actionable decision).
        if h.get('opener_position') or h.get('faced_squeeze'):
            return 'fold_vs_open'
        return 'walked'
    return 'unknown'


def hand_to_postflop_record(h):
    """Extract 6-dim postflop key + outcome. Returns None for non-postflop or all-in-PF hands."""
    if not h.get('board'):
        return None
    if h.get('pf_allin') or h.get('pf_allin_flag'):
        return None  # no postflop decision was made
    return {
        'pfr_role': 'PFR' if h.get('pfr') else 'caller',
        'pot_type': h.get('pot_type') or 'unknown',
        'icm_phase': h.get('tournament_phase') or 'unknown',
        'pos_class': 'IP' if h.get('hero_ip') else 'OOP',
        'texture': h.get('board_texture') or 'unknown',
        'spr': spr_bucket(h.get('spr')),
        'net_bb': float(h.get('net_bb') or 0),
    }


def hand_to_preflop_record(h):
    """
    Extract 5-dim preflop key + outcome. Returns None for hands where Hero either:
      - made no voluntary preflop action (walked / unknown)
      - took a fold action (fold_vs_open / fold_to_3bet / fold_bb_vs_steal)
        — these have outcomes determined by the blind/ante structure, not by
        decision quality, so the drill methodology (per-hand BB analysis)
        doesn't apply. Range-deviation analysis (gem_analyzer's
        preflop_deviations) is the right tool for fold-side leaks.

    Includes all VPIP'd actions: RFI, cold_call, 3bet/squeeze, 4bet, 5bet+,
    call_3bet, call_4bet, call_5bet, call_jam_lt15, iso_raise. These are
    decisions where the per-hand outcome reflects Hero's choice quality.
    """
    action = extract_action_type(h)
    DRILL_ACTIONS = {
        'RFI', 'cold_call', '3bet', '3bet_squeeze', '4bet', '5bet+',
        'call_3bet', 'call_4bet', 'call_5bet', 'call_jam_lt15', 'iso_raise',
    }
    if action not in DRILL_ACTIONS:
        return None
    return {
        'action_type': action,
        'icm_phase': h.get('tournament_phase') or 'unknown',
        'stack_bucket': stack_bucket(h.get('eff_stack_bb')),
        'position_bucket': position_bucket(h.get('position')),
        'pot_type': h.get('pot_type') or 'unknown',
        'net_bb': float(h.get('net_bb') or 0),
    }


# Backwards-compat alias for tests written against v0.1-0.3 API
def hand_to_record(h):
    return hand_to_postflop_record(h)


# =============================================================================
# BOOTSTRAP CI
# =============================================================================

def bootstrap_ci_mean(values, n_samples=BOOTSTRAP_SAMPLES, alpha=CI_ALPHA, seed=42):
    """
    Two-sided (1 - 2*alpha) bootstrap CI on the mean.
    Returns (low, high) tuple, or None if input is empty.
    """
    if not values:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_samples):
        s = 0.0
        for _ in range(n):
            s += values[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(n_samples * alpha)]
    hi = means[int(n_samples * (1 - alpha)) - 1]
    return (lo, hi)


# =============================================================================
# GATES
# =============================================================================

def gates_pass(child_records):
    """
    Three-gate significance test on a candidate child node.
    Returns (passes: bool, reason: str).
    """
    n = len(child_records)
    if n < MIN_N:
        return False, f'n={n}<{MIN_N}'

    vals = [r['net_bb'] for r in child_records]
    total = sum(vals)

    if total >= 0:
        return False, f'net=+{total:.0f}BB (winning, not a leak)'

    if abs(total) < MIN_LOSS_BB:
        return False, f'loss={abs(total):.0f}BB<{MIN_LOSS_BB}'

    ci = bootstrap_ci_mean(vals)
    if ci is None:
        return False, 'no CI'
    lo, hi = ci
    if hi >= 0:
        return False, f'mean CI [{lo:.2f},{hi:.2f}] crosses 0'

    return True, f'CI[{lo:.2f},{hi:.2f}]'


# =============================================================================
# DRILL WALKER
# =============================================================================

def drill(records, parent_path, depth, dim_idx, dim_priority=None):
    """
    Recursive drill walker.

    records:      list of records at this node
    parent_path:  list of (dim, value) leading here
    depth:        current depth (root = 0)
    dim_idx:      index into dim_priority for next dim to try
    dim_priority: list of dim names to walk (defaults to module DIM_PRIORITY for
                  backwards compatibility with v0.3 tests)

    Returns a node dict with possibly a 'children' list.
    """
    if dim_priority is None:
        dim_priority = DIM_PRIORITY
    max_depth = len(dim_priority)

    n = len(records)
    total_net = sum(r['net_bb'] for r in records)
    mean_bb = total_net / n if n > 0 else 0

    node = {
        'path': list(parent_path),
        'depth': depth,
        'n': n,
        'total_bb': total_net,
        'mean_bb': mean_bb,
    }

    if depth >= max_depth:
        return node

    # Note: we do NOT short-circuit on total_net >= 0. A winning parent can
    # still hide losing sub-buckets — that's exactly what we want to surface.
    parent_loss = abs(total_net) if total_net < 0 else 0

    # Walk priority order until a dim produces drill-worthy children
    for try_idx in range(dim_idx, len(dim_priority)):
        dim = dim_priority[try_idx]
        groups = defaultdict(list)
        for r in records:
            groups[r[dim]].append(r)

        if len(groups) <= 1:
            continue  # uniform on this dim — try next

        # Test each child against the gates
        passing = []
        skipped = []
        for value, child_recs in groups.items():
            child_total = sum(r['net_bb'] for r in child_recs)
            child_n = len(child_recs)
            ok, reason = gates_pass(child_recs)
            entry = {
                'value': value, 'records': child_recs, 'n': child_n,
                'total_bb': child_total, 'reason': reason,
                'parent_loss_pct': (
                    abs(child_total) / parent_loss * 100
                    if parent_loss > 0 and child_total < 0 else None
                ),
            }
            (passing if ok else skipped).append(entry)

        if not passing:
            continue  # no child passed — try next dim

        # Sort passing by absolute loss (worst first), cap at TOP_K
        passing.sort(key=lambda e: e['total_bb'])  # most negative first
        drilled = passing[:TOP_K]
        not_drilled = passing[TOP_K:]

        node['drilled_dim'] = dim
        node['children'] = []
        for entry in drilled:
            child_node = drill(
                entry['records'],
                parent_path + [(dim, entry['value'])],
                depth + 1,
                try_idx + 1,
                dim_priority=dim_priority,
            )
            child_node['gate_reason'] = entry['reason']
            child_node['parent_loss_pct'] = entry['parent_loss_pct']
            node['children'].append(child_node)

        # Stash siblings (skipped + passed-but-not-drilled) as informational
        node['skipped'] = []
        for entry in skipped + not_drilled:
            node['skipped'].append({
                'dim': dim, 'value': entry['value'], 'n': entry['n'],
                'total_bb': entry['total_bb'], 'reason': entry['reason'],
                'parent_loss_pct': entry['parent_loss_pct'],
            })
        return node

    return node  # walked all dims, found nothing drillable


# =============================================================================
# RENDER
# =============================================================================

def render_tree(node, lines=None, indent=0):
    if lines is None:
        lines = []
    pad = '  ' * indent

    if node['depth'] == 0:
        lines.append(
            f"ROOT (postflop): n={node['n']:,}  net={node['total_bb']:+,.0f}BB  "
            f"mean={node['mean_bb']:+.2f}BB/h"
        )
    else:
        dim, val = node['path'][-1]
        gate = node.get('gate_reason', '')
        pct = node.get('parent_loss_pct')
        is_leaf = not node.get('children')
        prefix = '✓ STUDY' if is_leaf else '└─'
        pct_str = f"  ({pct:.0f}% of parent loss)" if pct is not None else ""
        lines.append(
            f"{pad}{prefix}  {dim}={val}  n={node['n']:,}  "
            f"net={node['total_bb']:+,.0f}BB  mean={node['mean_bb']:+.2f}BB/h{pct_str}  "
            f"[{gate}]"
        )
        if is_leaf and node['depth'] > 0:
            sim = ' × '.join(f'{d}={v}' for d, v in node['path'])
            lines.append(f"{pad}    →  GTOW sim: {sim}")

    if node.get('drilled_dim') and node.get('children'):
        lines.append(f"{pad}  ┊ split on {node['drilled_dim']}:")

    for child in node.get('children', []):
        render_tree(child, lines, indent + 1)

    # Sibling info — shown briefly so you can see what was skipped
    skipped = node.get('skipped', [])
    if skipped and node.get('children'):
        for s in skipped[:5]:  # cap noise
            pct = s.get('parent_loss_pct')
            pct_str = f"  ({pct:.0f}%)" if pct is not None else ""
            lines.append(
                f"{pad}  ┊ ✗ {s['dim']}={s['value']}  n={s['n']:,}  "
                f"net={s['total_bb']:+,.0f}BB{pct_str}  [{s['reason']}]"
            )
        if len(skipped) > 5:
            lines.append(f"{pad}  ┊ ... +{len(skipped)-5} more skipped")

    return lines


def collect_leaves(node, leaves=None):
    if leaves is None:
        leaves = []
    if node['depth'] > 0 and not node.get('children'):
        leaves.append(node)
    for c in node.get('children', []):
        collect_leaves(c, leaves)
    return leaves


# =============================================================================
# TEXTURE EXPANSION (decomposition of untextured leaves into sim-loadable rows)
# =============================================================================

# Decomposition uses LOOSER gates than discovery: this isn't claiming a new
# confirmed leak, just splitting an already-confirmed bucket into sim-loadable
# texture sub-specs. The parent leaf already passed strict gates; sub-rows just
# need enough sample to be GTOW-loadable, not enough to independently confirm.
EXPANSION_MIN_N = 15
EXPANSION_MIN_LOSS = 15.0
EXPANSION_TOP_K = 2


def filter_records_by_path(records, path):
    """Return subset of records matching every (dim, value) in path."""
    out = records
    for dim, val in path:
        out = [r for r in out if r.get(dim) == val]
    return out


# NOTE: expand_untextured_leaf was the v0.3 function for texture decomposition.
# It's now an alias to expand_leaf_by_dim(..., expansion_dim='texture'), defined
# below alongside the profile machinery. Tests using the old name still work.



# =============================================================================
# REPORT SECTIONS — TLDR / ROADMAP / DRILL QUESTIONS
# =============================================================================

def generate_tldr(leaves):
    """Auto-detect the dominant pattern across study targets."""
    if not leaves:
        return "_No confirmed leaks surfaced — play looks clean by drill criteria for this scope._"
    n = len(leaves)
    if n == 1:
        path_desc = ' × '.join(f'{d}={v}' for d, v in leaves[0]['path'])
        return f"**Single confirmed leak:** `{path_desc}` — {leaves[0]['n']:,} hands, {leaves[0]['mean_bb']:+.2f} BB/h."
    dim_counts = defaultdict(lambda: defaultdict(int))
    for leaf in leaves:
        for dim, val in leaf['path']:
            dim_counts[dim][val] += 1
    patterns = []
    for dim, val_counts in dim_counts.items():
        for val, ct in val_counts.items():
            frac = ct / n
            if frac >= 0.75:
                if frac == 1.0:
                    patterns.append(f"all {n} are **{dim}={val}**")
                else:
                    patterns.append(f"{ct} of {n} are **{dim}={val}**")
    if not patterns:
        return f"**{n} confirmed leaks** across diverse spots — no single dim dominates. See targets below."
    return f"**{n} confirmed leaks share a structural pattern:** " + "; ".join(patterns) + "."


def generate_roadmap(records, leaves):
    """Honest framing of what the drill captures vs. what it misses."""
    total_negative = abs(sum(r['net_bb'] for r in records if r['net_bb'] < 0))
    leaf_total = abs(sum(l['total_bb'] for l in leaves))
    leaf_pct = (leaf_total / total_negative * 100) if total_negative > 0 else 0
    target_recovery = total_negative * 0.10
    lines = []
    lines.append(f"- **Total negative postflop:** {total_negative:,.0f} BB across all losing hands")
    lines.append(f"- **Drill captured:** {leaf_total:,.0f} BB across {len(leaves)} confirmed-leak buckets ({leaf_pct:.1f}% of negative pool)")
    lines.append(f"- **10% recovery target:** {target_recovery:,.0f} BB")
    lines.append("")
    if leaf_pct >= 10:
        lines.append(
            f"✓ Fixing the {len(leaves)} drill targets clears the 10% threshold. "
            f"Start with target #1 (largest leaf) and work down."
        )
    else:
        gap = target_recovery - leaf_total
        lines.append(
            f"⚠ The drill alone captures {leaf_pct:.1f}% — short of the 10% target by {gap:,.0f} BB. "
            "Closing the gap requires looking outside the drill output:"
        )
        lines.append("  - **CI-rejected buckets** (high variance, mean unclear) — e.g. SRP caller pool")
        lines.append(f"  - **Buckets below n={MIN_N} floor** — small samples, unreliable individually but real in aggregate")
        lines.append("  - **Fold-side leaks** (over-folding to opens / 3-bets / steals) — drill methodology doesn't apply to folds; use gem_analyzer's preflop_deviations report")
    return '\n'.join(lines)


def generate_postflop_questions(leaf):
    """
    Socratic prep questions per postflop sim spec. 5-7 questions, weighted toward the
    leaf's specific dim values. Goal: force thinking BEFORE loading the sim.
    """
    path = dict(leaf['path'])
    role = path.get('pfr_role', '')
    pot = path.get('pot_type', '')
    phase = path.get('icm_phase', '')
    pos = path.get('pos_class', '')
    tex = path.get('texture', '')
    spr_b = path.get('spr', '')

    qs = []

    # Q1: Range mapping
    if role == 'PFR':
        qs.append(
            f"As PFR in {pot}, {pos}, ICM={phase} — what's your opening/3-bet range and "
            f"how does villain's continuing range narrow against you? Where's villain's "
            f"strongest concentration of hands?"
        )
    else:  # caller
        action = '3-bet' if pot == '3BP' else ('4-bet' if pot == '4BP' else 'open')
        qs.append(
            f"You called villain's {action} from {pos} (ICM={phase}). What hands are in "
            f"your defending range that you'd never raise back, and what hands are too "
            f"weak even to call here? Be explicit about marginal Ax / suited-broadway / "
            f"low-pair selection."
        )

    # Q2: Texture (if specified) or range-advantage question
    if tex:
        tex_pretty = tex.replace('_', ' ')
        qs.append(
            f"Flop is **{tex_pretty}**. Map villain's c-bet frequency and sizing "
            f"distribution. Which sizing tells you what about their range — small bet "
            f"(33%) vs. large bet (75%) — and what's the equity floor at each?"
        )
        if tex in ('paired', 'monotone', 'dry_a_high'):
            qs.append(
                f"On a {tex_pretty} board, which hands in your range gain the most from "
                f"check-raising as a bluff? Which blockers matter most for the bluff/value "
                f"split? Name 3 specific combos."
            )
    else:
        qs.append(
            f"Without texture specified, this leaf aggregates across all flops. Pick the "
            f"two textures that produced the most loss in this bucket and treat each as a "
            f"separate sim. What boards favor whom?"
        )

    # Q3: SPR / commitment planning
    if spr_b == '<1':
        qs.append(
            f"At SPR <1 you're commitment-locked. Define your check-call vs. check-shove "
            f"vs. lead-shove ranges. What's the equity threshold to get-it-in vs. fold? "
            f"Which marginal hands are pure folds despite SPR pressure?"
        )
    elif spr_b == '1-3':
        qs.append(
            f"SPR 1-3 — the next bet sets up the river jam. How does this reshape your "
            f"continuing range vs. higher SPR? Specifically: which medium-strength hands "
            f"that would call at 7+ SPR become folds here, and why?"
        )
    elif spr_b in ('3-7', '7+'):
        qs.append(
            f"At SPR {spr_b} you have multi-street planning room. Build the 3-street "
            f"value/bluff pairing: which hands bet flop-turn-river and which check back "
            f"flop to balance your check-back range?"
        )

    # Q4: Multi-street runout planning
    qs.append(
        "Plan all three streets in advance. What turn cards are 'go' vs. 'shut down' for "
        "your continuing range? What rivers are auto-give-up if villain barrels? Pick 3 "
        "specific runouts and decide before the sim runs."
    )

    # Q5: ICM-aware adjustment
    if phase in ('bubble_zone', 'post_bubble', 'ft_zone'):
        qs.append(
            f"ICM phase = {phase}. The ICM premium adjusts call vs. raise vs. fold "
            f"thresholds significantly. Identify whether you're (a) over-folding due to "
            f"ladder pressure, or (b) under-folding because 'someone always has it'. "
            f"Cite a specific hand class for each."
        )
    elif phase == 'late_reg':
        qs.append(
            f"Late-reg ICM is mild. Pick one spot where you'd play differently in chip-EV "
            f"vs. ICM mode. Which way does the ICM push — tighter or looser?"
        )

    # Q6: Sizing ladder
    if role == 'PFR' or pot in ('3BP', '4BP'):
        qs.append(
            "Your sizing options on this flop: 25%, 33%, 50%, 75%, overbet. What does "
            "each size communicate about your range? Which hands belong in each bucket? "
            "Where does the population over/under-defend?"
        )

    # Q7: Population exploit (last — pulls Hero out of pure GTO mode)
    qs.append(
        f"Name one population tendency in this exact spot ({pot} {pos} {phase}) that "
        f"overrides GTO. Are villains more likely to over-fold rivers, over-call rivers, "
        f"under-bluff turns, or auto-stab when checked to? Which exploit do you apply?"
    )

    return qs


# Backwards-compat alias for v0.1-v0.3 tests
def generate_questions(leaf):
    return generate_postflop_questions(leaf)


def generate_preflop_questions(leaf):
    """
    Socratic prep questions per preflop sim spec. 5-7 questions, weighted toward
    the leaf's action_type and depth context.
    """
    path = dict(leaf['path'])
    action = path.get('action_type', '')
    phase = path.get('icm_phase', '')
    stack = path.get('stack_bucket', '')
    pos = path.get('position_bucket', '')
    pot = path.get('pot_type', '')

    qs = []

    # Q1: Range definition (action-specific)
    if action == 'RFI':
        qs.append(
            f"You're opening first-in from {pos} at {stack}BB (ICM={phase}). "
            "Define your opening range explicitly: which suited connectors / suited "
            "Ax / offsuit broadways are in vs. out? What's your sizing and why does "
            "it suit this depth?"
        )
    elif action == 'cold_call':
        qs.append(
            f"You're cold-calling an open from {pos} at {stack}BB. What hands are in "
            "your cold-call range that you'd never 3-bet, and what hands are too weak "
            "to call? Be explicit about Ax / suited gappers / pocket pairs."
        )
    elif action in ('3bet', '3bet_squeeze'):
        squeeze = ' over a caller (squeeze)' if action == '3bet_squeeze' else ''
        qs.append(
            f"You're 3-betting{squeeze} from {pos} at {stack}BB. Linear (tight value) "
            "or polar (value + bluff)? Which combos are in each bucket? Specifically: "
            "which suited Ax block villain's calling range vs. burn equity?"
        )
    elif action == 'call_3bet':
        qs.append(
            f"You called villain's 3-bet from {pos} at {stack}BB. ⚠️ At <50BB this often "
            "violates J11 (3-bet-fold pairs). What's your continuing range here? Which "
            "pairs are in vs. out, and which suited broadways play vs. fold?"
        )
    elif action == '4bet':
        qs.append(
            f"You're 4-betting from {pos} at {stack}BB. Linear value, or balanced with "
            "blocker bluffs? What sizing — small (~2.2x) for stack-leverage or big (3x+) "
            "for fold equity? Which 4-bet bluffs do you actually have here?"
        )
    elif action == 'call_4bet':
        qs.append(
            f"⚠️ Stack-off decision. You called villain's 4-bet from {pos} at {stack}BB. "
            "What's your equity threshold for getting all-in on the flop here? What hands "
            "PASS that threshold and which marginally fail (likely fold pre)?"
        )
    elif action == 'call_jam_lt15':
        qs.append(
            f"Push/fold call from {pos}, ≤15BB jammer (ICM={phase}). What's your equity "
            "threshold given pot odds and ICM? Which hands are calls vs. mucks at the "
            "exact stack depth? Pick 5 borderline combos and decide."
        )
    elif action == 'iso_raise':
        qs.append(
            f"Iso-raising over a limper from {pos} at {stack}BB. Sizing should scale "
            "with limpers + position. What's your value range, your iso-bluff range, "
            "and what hands flat the limp instead?"
        )
    elif action == '5bet+':
        qs.append(
            f"5-betting+ from {pos} at {stack}BB — usually a stack-off shove. At this "
            "depth, this is basically a value-only range. What's actually in it? "
            "Are you ever 5-bet bluffing, and with what blockers?"
        )
    elif action == 'fold_to_3bet':
        qs.append(
            f"Folding to villain's 3-bet from {pos} at {stack}BB. Are you over-folding "
            "(giving up too much) or correctly folding bottom of opening range? "
            "Which hands should defend by calling vs. 4-betting?"
        )
    else:
        qs.append(f"What's your range for action={action} from {pos} at {stack}BB?")

    # Q2: ICM adjustment
    if phase in ('bubble_zone', 'post_bubble', 'ft_zone'):
        qs.append(
            f"ICM phase = {phase}. The ICM premium changes calling-vs-shoving "
            f"thresholds significantly here. Pick one combo where ICM flips your "
            f"chip-EV decision (e.g., a TT call that becomes a fold under ICM, or "
            f"a shove that becomes a min-raise). Name the combo and the flip."
        )
    elif phase == 'late_reg':
        qs.append(
            "Late-reg ICM is mild but accumulating. How does the chip-EV vs. ICM "
            "decision diverge for marginal calling/3-betting hands at this depth?"
        )

    # Q3: Stack-depth-specific question
    if stack == '<12':
        qs.append(
            "Sub-12BB territory: every action is a push/fold/call-jam. What's your "
            f"jamming range from {pos} at this depth? Where does it end (e.g. K3o, "
            "Q5s, J8o)? What's the floor for calling a jam vs. folding?"
        )
    elif stack == '12-25':
        qs.append(
            "12-25BB is the awkward zone — too deep for pure push/fold, too shallow "
            "for postflop play. What hands open vs. limp vs. jam? How does your "
            "range change vs. the deeper bracket above?"
        )
    elif stack in ('25-40', '40-60'):
        qs.append(
            f"At {stack}BB you have postflop play but stack-off pressure. How does "
            "your 3-bet/4-bet range narrow vs. deep, and what suited gappers / Ax "
            "hands fall out of your opening range here?"
        )
    elif stack == '60+':
        qs.append(
            "60+BB is full-stack territory: maximum range freedom, full postflop "
            "playability. Where are you UNDER-opening (missed steals) and where "
            "are you OVER-opening (out-of-range)?"
        )

    # Q4: Pot-type context
    if pot == '3BP':
        qs.append(
            "This decision created (or sat in) a 3-bet pot. What's the implied "
            "postflop game look like — SPR, ranges, who has range advantage on "
            "different boards? Walk through one flop you'd c-bet vs. one you'd check."
        )
    elif pot == '4BP':
        qs.append(
            "4-bet pot. Stacks are committed-ish, ranges are tight. What's villain's "
            "calling range vs. shoving range? Which board textures favor your range "
            "vs. villain's, and how does that affect your c-bet/check frequency?"
        )

    # Q5: Position-specific exploit
    if pos == 'BB':
        qs.append(
            "BB-specific: you have closing action and pot odds. Where does the "
            "population over-fold vs. opens (justifying wider 3-bets), and where "
            "do they over-call vs. 3-bets (justifying tighter ranges)?"
        )
    elif pos == 'SB':
        qs.append(
            "SB-specific: BvB dynamics + worst position vs. limper-pots. What's your "
            f"actual SB strategy at {stack}BB — limp-heavy (J29), raise-heavy, or "
            "mixed? What's the threshold between modes?"
        )
    elif pos == 'LP':
        qs.append(
            "LP (CO/BTN/HJ) — widest opening, most postflop edge as PFR. Are you "
            "extracting that edge, or playing too tight by stack pressure?"
        )

    # Q6: Population exploit
    qs.append(
        f"Name one population tendency for this exact spot ({action} from {pos} at "
        f"{stack}BB, ICM={phase}). Do villains over-defend / under-defend / call too "
        f"light / fold too tight here? Which exploit do you apply, and what hand class "
        f"is the exploit's main target?"
    )

    return qs


# =============================================================================
# PROFILES
# =============================================================================

@dataclass
class Profile:
    """Configures the drill engine for a specific decision domain (pre/postflop)."""
    name: str
    dim_priority: list
    extract_record: Callable
    expansion_dim: Optional[str]  # which dim to decompose untextured-style; None to skip
    question_generator: Callable
    description: str = ''


POSTFLOP_PROFILE = Profile(
    name='postflop',
    dim_priority=['pfr_role', 'pot_type', 'icm_phase', 'pos_class', 'texture', 'spr'],
    extract_record=hand_to_postflop_record,
    expansion_dim='texture',
    question_generator=generate_postflop_questions,
    description='Postflop decisions on hands that saw a flop (excludes preflop all-ins).',
)

PREFLOP_PROFILE = Profile(
    name='preflop',
    dim_priority=['action_type', 'icm_phase', 'stack_bucket', 'position_bucket', 'pot_type'],
    extract_record=hand_to_preflop_record,
    expansion_dim=None,  # preflop sim specs are naturally loadable; no decomposition needed in v0.4
    question_generator=generate_preflop_questions,
    description='Preflop decisions (RFI, 3-bet, call-jam, etc.). Includes hands with and without a flop.',
)


def expand_leaf_by_dim(leaf, records, expansion_dim):
    """
    Profile-aware decomposition: split an untextured (or unexpanded) leaf into
    sub-rows along expansion_dim. Returns [] if expansion_dim is None or already
    in the leaf's path.
    """
    if expansion_dim is None:
        return []
    path_dims = {d for d, _ in leaf['path']}
    if expansion_dim in path_dims:
        return []
    leaf_records = filter_records_by_path(records, leaf['path'])
    by_value = defaultdict(list)
    for r in leaf_records:
        by_value[r[expansion_dim]].append(r)
    sub_rows = []
    for val, recs in by_value.items():
        n = len(recs)
        total = sum(r['net_bb'] for r in recs)
        if n < EXPANSION_MIN_N or total >= 0 or abs(total) < EXPANSION_MIN_LOSS:
            continue
        sub_rows.append({
            'path': leaf['path'] + [(expansion_dim, val)],
            'n': n,
            'total_bb': total,
            'mean_bb': total / n,
            'parent_path': leaf['path'],
        })
    sub_rows.sort(key=lambda x: x['total_bb'])
    return sub_rows[:EXPANSION_TOP_K]


def run_profile(records, profile):
    """Execute a drill for a single profile. Returns (tree, leaves_sorted, decomposition)."""
    profile_records = [r for r in (profile.extract_record(h) for h in records) if r is not None]
    tree = drill(profile_records, [], 0, 0, dim_priority=profile.dim_priority)
    leaves = collect_leaves(tree)
    leaves_sorted = sorted(leaves, key=lambda x: x['total_bb'])
    decomposition = {
        id(l): expand_leaf_by_dim(l, profile_records, profile.expansion_dim)
        for l in leaves_sorted
    }
    return {
        'profile': profile,
        'records': profile_records,
        'tree': tree,
        'leaves': leaves_sorted,
        'decomposition': decomposition,
    }


def render_profile_section(result, section_prefix=''):
    """Render TLDR + study targets table + drill questions for one profile run."""
    profile = result['profile']
    leaves = result['leaves']
    decomposition = result['decomposition']
    records = result['records']

    lines = []
    title = section_prefix + profile.name.upper()
    lines.append(f'## {title}')
    lines.append(f"_{len(records):,} {profile.name} decisions analyzed | "
                 f"net {sum(r['net_bb'] for r in records):+,.0f}BB_")
    lines.append('')

    # TLDR for this profile
    lines.append(f'### TLDR ({profile.name})')
    lines.append(generate_tldr(leaves))
    lines.append('')

    if not leaves:
        lines.append(f'_No {profile.name} targets passed gating._')
        lines.append('')
        return lines

    # Targets table
    leaf_pool = abs(sum(l['total_bb'] for l in leaves))
    n_subs = sum(len(s) for s in decomposition.values())
    lines.append(f'### {profile.name.capitalize()} Study Targets')
    if n_subs > 0:
        lines.append(
            f'_{len(leaves)} confirmed leaks → {len(leaves) + n_subs} sim-loadable rows '
            f'after {profile.expansion_dim} decomposition._'
        )
    lines.append('')
    lines.append('| # | Sim Spec | n | Total BB | BB/h | % of leak pool | CI |')
    lines.append('|---|----------|---|----------|------|----------------|----|')
    for i, leaf in enumerate(leaves, 1):
        sim = ' × '.join(f'{d}={v}' for d, v in leaf['path'])
        pct = abs(leaf['total_bb']) / leaf_pool * 100 if leaf_pool > 0 else 0
        lines.append(
            f"| {i} | `{sim}` | {leaf['n']:,} | {leaf['total_bb']:+,.0f} | "
            f"{leaf['mean_bb']:+.2f} | {pct:.0f}% | {leaf.get('gate_reason','')} |"
        )
        for sub in decomposition.get(id(leaf), []):
            sub_sim = ' × '.join(f'{d}={v}' for d, v in sub['path'])
            sub_pct = abs(sub['total_bb']) / leaf_pool * 100 if leaf_pool > 0 else 0
            lines.append(
                f"| {i}↳ | `{sub_sim}` | {sub['n']:,} | {sub['total_bb']:+,.0f} | "
                f"{sub['mean_bb']:+.2f} | {sub_pct:.0f}% | (decomposition) |"
            )
    lines.append('')

    # Drill questions per leaf
    lines.append(f'### Drill Questions Per {profile.name.capitalize()} Sim')
    lines.append(
        '*Answer these BEFORE running the GTOW sim.*'
    )
    lines.append('')
    for i, leaf in enumerate(leaves, 1):
        sim = ' × '.join(f'{d}={v}' for d, v in leaf['path'])
        lines.append(f'#### Target #{i}: `{sim}`')
        lines.append(
            f'_n={leaf["n"]:,} | net {leaf["total_bb"]:+,.0f} BB | '
            f'{leaf["mean_bb"]:+.2f} BB/h | {leaf.get("gate_reason","")}_'
        )
        lines.append('')
        for j, q in enumerate(profile.question_generator(leaf), 1):
            lines.append(f'{j}. {q}')
        lines.append('')

    return lines


# Backwards-compat alias for v0.3 tests using the old name
def expand_untextured_leaf(leaf, records):
    return expand_leaf_by_dim(leaf, records, expansion_dim='texture')


# =============================================================================
# MAIN
# =============================================================================

def generate_gto_texture_drill(hands):
    """
    v7.31: Build GTO-texture-compliance drill targets from Dave taxonomy.

    For each archetype where Hero shows deviation from GTO targets, emit
    a study card with: example flop, GTO target (freq + sizings), Hero's
    actual stats, sample size, and 4 Socratic drill questions tied to
    the specific deviation. Drives the [GTO ref] section of the drill
    output.

    Returns dict { 'cards': [...], 'meta': {...} } suitable for JSON
    embedding and Markdown rendering.
    """
    try:
        import gem_textures
    except ImportError:
        return {'cards': [], 'meta': {'enabled': False,
                'reason': 'gem_textures not importable'}}

    # Build the same eligibility filter the analyzer uses
    eligible = []
    for h in hands:
        if not h.get('pfr'):
            continue
        if not (h.get('board') and len(h['board']) >= 3):
            continue
        if h.get('pf_allin') or h.get('pf_allin_flag'):
            continue
        eligible.append({
            '_arch': h.get('board_archetype', 'unknown'),
            '_side': 'ip' if h.get('hero_ip') else 'oop',
            '_eff': h.get('eff_stack_bb') or h.get('stack_bb') or 100,
            '_cb': any(b[0] == 'flop' and b[2] == 'cbet'
                       for b in h.get('hero_bets', [])),
            '_sz': next((b[1] for b in h.get('hero_bets', [])
                         if b[0] == 'flop' and b[2] == 'cbet'), None),
            'id': h.get('id'),
        })

    findings = gem_textures.aggregate_compliance(
        eligible,
        get_archetype_fn=lambda h: h.get('_arch'),
        get_side_fn=lambda h: h.get('_side'),
        get_depth_fn=lambda h: h.get('_eff'),
        get_did_cbet_fn=lambda h: h.get('_cb'),
        get_sizing_fn=lambda h: h.get('_sz'),
    )

    # Build cards for any archetype/side with verdict=deviation
    cards = []
    for arch_id, sides in findings.items():
        meta = gem_textures.archetype_meta(arch_id) or {}
        example = meta.get('example', '')
        for side, b in sides.items():
            if b.get('verdict') != 'deviation':
                continue
            target_freq = b.get('target_freq_pct')
            target_sizings = []
            scenarios = (meta.get(f'{side}_cbet') or {}).get('scenarios', [])
            if scenarios:
                # Use the first scenario's sizings as a representative; depth
                # bands seen are listed in the card so reader knows the spread
                target_sizings = scenarios[0].get('sizings_pct', [])

            # Drill questions tailored to the specific deviation
            disp = arch_id.replace('_', ' ')
            qs = []
            qs.append(
                f"On a {disp} flop ({example}), what does GTO say about RANGE "
                f"ADVANTAGE for the PFR {side.upper()}? Identify the structural "
                f"reason — high-card density, connectivity, suit structure — "
                f"that drives the c-bet target of "
                f"{target_freq[0]}-{target_freq[1]}%." if target_freq else
                f"On a {disp} flop ({example}), what does GTO say about RANGE "
                f"ADVANTAGE for the PFR {side.upper()}? Identify the structural "
                f"reason — high-card density, connectivity, suit structure — "
                f"that drives the strategy on this texture."
            )
            sz_str = '/'.join(f'B{x}' for x in target_sizings) if target_sizings else 'n/a'
            qs.append(
                f"GTO sizing on this texture: {sz_str}. Why this sizing and not a "
                f"different one? What does each sizing tell villain about your range, "
                f"and what hands populate each bucket?"
            )
            actual_freq = b.get('cbet_pct', 0)
            target_str = (f"{target_freq[0]}-{target_freq[1]}%"
                          if target_freq else 'no specific freq target')
            qs.append(
                f"Your actual c-bet rate on {disp} this session: {actual_freq}% "
                f"(target {target_str}, n={b.get('n_opps', 0)}). What population "
                f"read would JUSTIFY a deviation from GTO here? If no population "
                f"read justifies it, this is a pure leak — name the corrective "
                f"action."
            )
            qs.append(
                f"On the TURN after a c-bet gets called on {disp} ({example}), "
                f"how does the equity-shift question change for each turn-card "
                f"category (overcard, paired, flush-completing, brick)? Pick one "
                f"category and walk a barrel/check decision-tree."
            )

            cards.append({
                'archetype': arch_id,
                'archetype_display': disp.title(),
                'example': example,
                'side': side.upper(),
                'n_opps': b.get('n_opps', 0),
                'cbet_pct': actual_freq,
                'target_freq_pct': target_freq,
                'target_sizings_pct': target_sizings,
                'sizing_compliance_pct': b.get('sizing_compliance_pct'),
                'depth_bands_seen': b.get('depth_bands_seen', []),
                'sample_size_label': b.get('sample_size_label', 'small'),
                'quality_label': (
                    '⚪ small sample' if b.get('sample_size_label') == 'small'
                    else '🟡 thin' if b.get('sample_size_label') == 'thin'
                    else '✅ verified'
                ),
                'questions': qs,
            })

    # Sort cards: sufficient samples first, then by n_opps desc
    sample_rank = {'sufficient': 0, 'thin': 1, 'small': 2}
    cards.sort(key=lambda c: (
        sample_rank.get(c['sample_size_label'], 9),
        -c['n_opps'],
    ))

    return {
        'cards': cards,
        'meta': {
            'enabled': True,
            'source': 'gto_texture_archetypes.json (Dave session 2026-05-04)',
            'eligible_hands': len(eligible),
            'archetypes_with_deviations': len(set(c['archetype'] for c in cards)),
            'total_cards': len(cards),
        },
    }


def render_gto_texture_drill_md(drill_data):
    """Render the GTO texture drill section as Markdown lines."""
    lines = []
    cards = drill_data.get('cards', [])
    meta = drill_data.get('meta', {})
    if not meta.get('enabled'):
        return lines  # silent if not enabled
    lines.append('## GTO Texture Compliance Drill  `[GTO ref]`')
    lines.append(
        f"_Source: {meta.get('source', 'gto_texture_archetypes.json')} | "
        f"{meta.get('eligible_hands', 0)} eligible PFR-saw-flop hands | "
        f"{meta.get('total_cards', 0)} deviation cards_"
    )
    lines.append('')
    if not cards:
        lines.append('*No GTO texture deviations this session.*')
        lines.append('')
        return lines
    lines.append(
        '*Each card pairs Hero\'s actual c-bet behaviour on a Dave-taxonomy '
        'archetype with the solver-derived GTO target. Drill questions force '
        'reasoning about WHY the GTO baseline exists before considering exploit '
        'overrides.*'
    )
    lines.append('')
    for i, c in enumerate(cards, 1):
        target_freq = c.get('target_freq_pct')
        target_str = (f"{target_freq[0]}-{target_freq[1]}%"
                      if target_freq else 'no freq target')
        sizings = c.get('target_sizings_pct', [])
        sz_str = '/'.join(f"B{x}" for x in sizings) if sizings else 'n/a'
        bands = c.get('depth_bands_seen', [])
        bands_str = ', '.join(bands) if bands else '—'
        sizing_pct = c.get('sizing_compliance_pct')
        sizing_compliance_str = (f"{sizing_pct}%" if sizing_pct is not None
                                 else 'n/a (no c-bets to score)')
        lines.append(
            f"### Card {i}: {c['archetype_display']} *({c['example']})* — "
            f"{c['side']}  `{c['quality_label']}`"
        )
        lines.append('')
        lines.append('| | |')
        lines.append('|---|---|')
        lines.append(f"| Hero c-bet rate | {c['cbet_pct']}% (n={c['n_opps']}) |")
        lines.append(f"| GTO freq target | {target_str} |")
        lines.append(f"| GTO sizings | {sz_str} |")
        lines.append(f"| Sizing compliance | {sizing_compliance_str} |")
        lines.append(f"| Depth bands seen | {bands_str} |")
        lines.append('')
        lines.append('**Drill questions:**')
        for q_i, q in enumerate(c.get('questions', []), 1):
            lines.append(f"{q_i}. {q}")
        lines.append('')
    return lines


def main():
    ap = argparse.ArgumentParser(description=f'GEM drill-down leak finder v{VERSION}')
    ap.add_argument('hands_json', help='Path to gem_hands.json')
    ap.add_argument('--mode', choices=['postflop', 'preflop', 'both'], default='both',
                    help='Which decision domain(s) to analyze (default: both)')
    ap.add_argument('--output', default='gem_drill.json', help='JSON output path')
    ap.add_argument('--text-report', default='gem_drill_report.md', help='Markdown output')
    args = ap.parse_args()

    with open(args.hands_json) as f:
        hands = json.load(f)

    # Determine which profiles to run
    profiles = []
    if args.mode in ('postflop', 'both'):
        profiles.append(POSTFLOP_PROFILE)
    if args.mode in ('preflop', 'both'):
        profiles.append(PREFLOP_PROFILE)

    sys.stderr.write(f'[gem_drill] mode={args.mode} | hands={len(hands):,}\n')

    # Run each profile
    results = {}
    for profile in profiles:
        result = run_profile(hands, profile)
        results[profile.name] = result
        net = sum(r['net_bb'] for r in result['records'])
        sys.stderr.write(
            f'[gem_drill] {profile.name}: {len(result["records"]):,} records, '
            f'net {net:+,.0f}BB, {len(result["leaves"])} confirmed leaks\n'
        )

    # v7.31: GTO Texture Compliance Drill (Dave taxonomy). Generated up-front
    # so it lands in both the JSON output and the Markdown report.
    gto_drill = generate_gto_texture_drill(hands)
    sys.stderr.write(
        f"[gem_drill] gto_texture_drill: "
        f"{gto_drill['meta'].get('total_cards', 0)} deviation cards "
        f"from {gto_drill['meta'].get('eligible_hands', 0)} eligible hands\n"
    )

    # Write JSON output (combined tree from all profiles)
    def clean(node):
        out = {k: v for k, v in node.items() if k != 'records'}
        if 'children' in out:
            out['children'] = [clean(c) for c in out['children']]
        return out
    json_out = {
        'version': VERSION,
        'mode': args.mode,
        'profiles': {
            name: {
                'profile_name': name,
                'dim_priority': r['profile'].dim_priority,
                'n_records': len(r['records']),
                'tree': clean(r['tree']),
            }
            for name, r in results.items()
        },
        'gto_texture_drill': gto_drill,
    }
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(json_out, f, indent=2, default=str)
    sys.stderr.write(f'[gem_drill] wrote {args.output}\n')

    # Build the markdown report
    lines = []
    lines.append(f'# GEM Drill-Down Study Targets')
    mode_str = args.mode if args.mode != 'both' else 'preflop + postflop'
    total_records = sum(len(r['records']) for r in results.values())
    lines.append(f'_v{VERSION} | mode={mode_str} | {total_records:,} decision records analyzed_')
    lines.append('')

    # --- Combined Recovery Roadmap (uses postflop records as the negative-pool denominator
    #     since that's the most stable cross-batch baseline; preflop leaks add to the
    #     captured pool numerator for the combined view) ---
    if results:
        # Use postflop records for total negative if available (most stable), else preflop
        baseline_records = (results.get('postflop') or results.get('preflop'))['records']
        all_leaves = []
        for r in results.values():
            all_leaves.extend(r['leaves'])
        lines.append('## Recovery Roadmap (combined)')
        lines.append(generate_roadmap(baseline_records, all_leaves))
        lines.append('')

    # --- Algorithm note (compact) ---
    lines.append('## Algorithm')
    algo_lines = []
    for profile in profiles:
        algo_lines.append(
            f"- **{profile.name}:** {' → '.join(profile.dim_priority)}"
        )
    algo_lines.append(
        f"Gates: n≥{MIN_N}, |loss|≥{MIN_LOSS_BB}BB, bootstrap 90% CI on mean excludes 0. "
        f"Fanout {TOP_K}/node. Full tree in `{args.output}`."
    )
    lines.extend(algo_lines)
    lines.append('')

    # --- Per-profile sections (TLDR, targets, drill questions) ---
    for profile in profiles:
        lines.extend(render_profile_section(results[profile.name]))

    # --- v7.31: GTO Texture Compliance Drill (Dave taxonomy) ---
    # gto_drill was already generated and embedded in json_out above; just
    # render the Markdown view here.
    lines.extend(render_gto_texture_drill_md(gto_drill))

    with open(args.text_report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    sys.stderr.write(f'[gem_drill] wrote {args.text_report}\n')


if __name__ == '__main__':
    main()
