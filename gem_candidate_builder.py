#!/usr/bin/env python3
"""
gem_candidate_builder.py — Analyst candidate generation (extracted from gem_analyzer.py).

Phase 1 of the A1 strangler split. Contains the CandidateContext (frozen,
read-only), pure helper functions for candidate building, and the worksheet
assembly logic.

The full extraction (~900 lines from __main__ block's 7 closures) is Phase 2
and requires golden-diff verification.
"""
from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True)
class CandidateContext:
    """Read-only context shared by all candidate-building functions.
    NOT a garbage bag — explicit fields, no mutable state."""
    hands_by_id: Mapping
    eai_by_id: Mapping
    variance_outcomes: Mapping
    aggression_by_id: Mapping


@dataclass
class CandidateBuildResult:
    """Phase output contract for candidate building."""
    candidates: dict
    worksheet: dict
    coverage_summary: dict


def to_chart_notation(cards_str):
    """Convert 'AhKd' → 'AKo', 'AsKs' → 'AKs', 'JdJc' → 'JJ'."""
    cs = cards_str.replace(' ', '')
    if len(cs) != 4:
        return cards_str
    r0, s0, r1, s1 = cs[0], cs[1], cs[2], cs[3]
    if r0 == r1:
        return f'{r0}{r1}'
    return f'{r0}{r1}{"s" if s0 == s1 else "o"}'


def compute_draw_profiles(h):
    """Compute draw_profile at each postflop street for a hand."""
    try:
        from gem_made_hands import draw_profile as _dp
    except Exception:
        return {}
    hero_cards = h.get('cards', [])
    board = h.get('board', [])
    if not isinstance(hero_cards, list) or len(hero_cards) != 2:
        return {}
    if not isinstance(board, list) or len(board) < 3:
        return {}
    profiles = {}
    for st, n in [('flop', 3), ('turn', 4), ('river', 5)]:
        if len(board) >= n:
            p = _dp(hero_cards, board[:n])
            if p:
                profiles[st] = p.get('summary', '')
    return profiles


def compute_board_state(h):
    """Compute board-centric per-street state for a hand (v8.7.7).

    Returns {} if board < 3 cards or gem_board_state unavailable.
    """
    try:
        from gem_board_state import board_state
    except Exception:
        return {}
    board = h.get('board', [])
    hero = h.get('cards', [])
    if not isinstance(board, list) or len(board) < 3:
        return {}
    return board_state(board, hero if isinstance(hero, list) and len(hero) == 2 else None)
