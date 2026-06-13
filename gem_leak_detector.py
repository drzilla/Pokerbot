#!/usr/bin/env python3
"""
gem_leak_detector.py — Leak/mistake/punt detection (extracted from gem_analyzer.py).

Phase 1 of the A1 strangler split. Contains the D2 bad river call-down
detector and will eventually receive the full mistake/punt/cooler detection
logic from analyze_session().

The full extraction (~1700 lines from analyze_session) is Phase 2 and
requires golden-diff verification on real sessions.
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class LeakDetectionResult:
    """Phase output contract for leak detection."""
    mistakes: list
    punts: list
    coolers: list
    eai: dict
    aggression: dict
    bad_calldowns: list


def detect_bad_river_calldowns(hands):
    """D2: Find showdown hands where Hero called river with a weak hand
    against a value-heavy villain line.

    Uses pot-odds + villain line profile, NOT MDF (which is a range-level
    concept, not applicable to individual hand decisions).

    Returns list of flagged hands with required_equity, villain_line,
    and reason.
    """
    bad = []
    for h in hands:
        if not h.get('went_to_sd') or not h.get('vpip'):
            continue
        hsa = h.get('hero_street_actions', {}) or {}
        river_act = hsa.get('river', '')
        if river_act not in ('call', 'xc'):
            continue
        if h.get('won'):
            continue
        strength = h.get('hand_strength', '')
        if strength in ('flush', 'straight', 'full_house', 'quads',
                        'straight_flush', 'trips', 'set', 'two_pair'):
            continue

        ledger = h.get('action_ledger', [])
        river_actions = [a for a in ledger if a.get('street') == 'river']
        if not river_actions:
            continue

        _v_bet = None
        hero = h.get('hero', 'Hero')
        for ra in reversed(river_actions):
            if ra.get('player') != hero and ra.get('action') in ('bets', 'raises'):
                _v_bet = ra
                break
        if not _v_bet or _v_bet.get('amount_bb', 0) <= 0:
            continue

        bet_bb = _v_bet['amount_bb']
        _pot_est = sum(a.get('amount_bb', 0) for a in ledger
                       if a.get('street') != 'river') + sum(
                       a.get('amount_bb', 0) for a in river_actions
                       if a != _v_bet and a.get('player') != hero)
        if _pot_est <= 0:
            _pot_est = abs(h.get('net_bb', 0)) * 0.5
        total_pot = _pot_est + bet_bb + bet_bb
        required_eq = bet_bb / total_pot * 100 if total_pot > 0 else 50

        _n_villain_bets = sum(1 for a in ledger
                              if a.get('player') != hero
                              and a.get('action') in ('bets', 'raises'))
        if _n_villain_bets >= 3:
            _v_line, _v_profile = 'triple_barrel', 'value_heavy'
        elif _n_villain_bets >= 2:
            _v_line, _v_profile = 'double_barrel', 'moderate_value'
        else:
            _v_line, _v_profile = 'single_bet', 'mixed'

        if required_eq > 25 and _v_profile in ('value_heavy', 'moderate_value'):
            bad.append({
                'id': h.get('id'),
                'type': 'bad_river_calldown',
                'required_equity': round(required_eq, 1),
                'hero_hand_class': strength or 'unknown',
                'board_texture': h.get('board_texture', ''),
                'villain_line': _v_line,
                'villain_line_profile': _v_profile,
                'net_bb': h.get('net_bb', 0),
                'reason': f'River call with {strength or "weak hand"} needed '
                          f'{required_eq:.0f}% equity vs {_v_line} — '
                          f'population range {_v_profile} at this sizing.',
            })
    return bad
