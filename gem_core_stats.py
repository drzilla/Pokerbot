#!/usr/bin/env python3
"""
gem_core_stats.py — Pure statistics computation (extracted from gem_analyzer.py).

Phase 1 of the A1 strangler split. Contains stateless helper functions that
compute per-hand and cross-hand statistics. These are the first functions
extracted from the monolithic analyze_session() — they take explicit inputs
and return explicit outputs with no side effects or closure captures.

The full extraction (moving the 2500-line stats block from analyze_session)
is Phase 2 and requires golden-diff verification on real sessions.
"""
from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass
class CoreStatsResult:
    """Phase output contract for core statistics computation."""
    stats: dict
    hands_by_id: dict
    tournaments: dict


def to_legacy_stats(core_result):
    """Adapter: merge CoreStatsResult back into the legacy stats dict."""
    return core_result.stats


# ============================================================
# Pure helper functions (extracted from gem_analyzer.py)
# These are stateless — safe to call from anywhere.
# ============================================================

def compute_positional_vpip(hands):
    """Compute VPIP% by position."""
    from collections import defaultdict
    by_pos = defaultdict(lambda: {'n': 0, 'vpip': 0})
    for h in hands:
        pos = h.get('position', '?')
        by_pos[pos]['n'] += 1
        if h.get('vpip'):
            by_pos[pos]['vpip'] += 1
    return {pos: {'n': d['n'], 'vpip': d['vpip'],
                  'pct': round(100.0 * d['vpip'] / d['n'], 1) if d['n'] else 0}
            for pos, d in by_pos.items()}


def compute_street_aggression(hands):
    """Compute aggression factor by street."""
    from collections import defaultdict
    by_street = defaultdict(lambda: {'bets': 0, 'raises': 0, 'calls': 0})
    for h in hands:
        hsa = h.get('hero_street_actions', {}) or {}
        for st, act in hsa.items():
            if act in ('bet', 'cbet', 'donk'):
                by_street[st]['bets'] += 1
            elif act in ('raise', 'xr'):
                by_street[st]['raises'] += 1
            elif act in ('call', 'xc'):
                by_street[st]['calls'] += 1
    result = {}
    for st, d in by_street.items():
        agg = d['bets'] + d['raises']
        af = agg / max(d['calls'], 1)
        result[st] = {'bets': d['bets'], 'raises': d['raises'],
                      'calls': d['calls'], 'af': round(af, 2)}
    return result
