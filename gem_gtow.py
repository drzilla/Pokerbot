#!/usr/bin/env python3
"""
gem_gtow.py — Per-hand GTO Wizard URL builder for GEM reports.

v2.0 (Phase 4.8+) — Fully validated against GTOW live testing.

Statuses
--------
  ready       – flop root or preflop decision, high-confidence URL
  partial     – preflop root (fallback: raise code unknown or 4+ way)
  unavailable – insufficient data

Link strategy (validated 2026-05-30)
-------------------------------------
  Postflop (≤3-way):  Link to FLOP ROOT (board + preflop_actions, no flop_actions).
                       User navigates the flop tree interactively.
  Postflop (4+ way):  Link to PREFLOP ROOT (flop root, gametype + depth only).
                       GTOW has no 4+-way postflop trees.
  Preflop only:        Link to hero's preflop decision point.
  Fallback:            If any raise R-code is uncertain, link to preflop root
                       (history_spot=0). Always resolves.

Data contract
-------------
  hand         – lean hand record (board, cards, position, stack_bb, eff_stack_bb,
                 pf_sequence, table_size, n_players, format, players_at_flop, …)
  app_details  – rich per-hand parse (seats, actions per street, is_bounty, …)

Usage::

    from gem_gtow import build_gtow_schema

    schema = build_gtow_schema(hand, app_details)
    # schema['status']  -> 'ready' | 'partial' | 'unavailable'
    # schema['url']     -> str | None
    # schema['label']   -> button label text
"""

import json
import os
from urllib.parse import urlencode


VERSION = "2.2.1"
# v2.2.1 (2026-06-11) — B149: flop-root gate also honors pf_settled
#   (jam-over-jam preflop all-ins between villains; parser exports it).
# v2.2.0 (2026-06-11) — fixes from the live Chrome-extension verification pass
#   (GTOW_URL_Verification_RESULTS.md, 60-hand sample, 40/60 OK):
#   - removed 152 from the 8m depth grid (GTOW backend rejected it live;
#     206 verified OK)
#   - bounty hands: label '⚡GTOW≈' + 'ChipEV approx (bounty)' in summary —
#     confirmed 8/8 bounty hands were silently served ChipEV
#   - PKO regimes inventoried (ICM family only): _PKO_GAMETYPES added with
#     routing behind GEM_GTOW_PKO_ROUTING flag, DEFAULT OFF until the ICMPKO
#     URL parameter space (depths/actions) is validated by a follow-up pass
#   - limp-before-raise paths now fall back to preflop root (open R-codes
#     are invalid in GTOW limp trees — confirmed SOMETHING_WENT_WRONG)
#   - snap-gap honesty: spot_summary notes when the snapped depth is far
#     from the hand's effective stack (7m grid caps at 65bb)
#   - one-time stderr warning when _gtow_situations.json is absent


# ============================================================================
# CONSTANTS — validated against GTOW live testing 2026-05-30
# ============================================================================

GTOW_BASE = "https://app.gtowizard.com/solutions"

# AI Solve dialog parameter — appending this to a valid solution URL
# auto-opens the AI Solve dialog pre-filled with the spot's context.
# Requires Elite/Wizard subscription. Validated 2026-05-30.
AI_SOLVE_PARAM = ('dialogs=solfigr-create-custom-solution-dialog'
                  '_namespace-tmp/primary_instaPrefill-true_mode-keepboard')

# ChipEV gametype by table_size (position labels differ per size)
CHIPEV_GAMETYPES = {
    3: 'MTTGeneral_3m',
    4: 'MTTGeneral_4m',
    5: 'MTTGeneral_5m',
    6: 'MTT6mSimple',
    7: 'MTTGeneral_7m',
    8: 'MTTGeneral_8m',
    9: 'MTTGeneralV2',
}

# ----------------------------------------------------------------------------
# PKO gametypes — inventoried live 2026-06-11 (Chrome-extension pass).
# PKO solutions exist ONLY inside the ICM family; there is NO PKO ChipEV.
# Naming: MTTGeneral_ICMPKO{n}m{field}PT{PHASE}. Bounty size is baked into
# the regime (no coverage parameter). Phases observed: near-bubble (8m only)
# and final table (3-9m selectable). No regime exists for late-reg/post-reg —
# i.e. for MOST bounty hands the honest answer remains "ChipEV approx".
#
# Routing is gated behind GEM_GTOW_PKO_ROUTING (env var, default OFF):
# the ICMPKO families' valid depth grids and preflop_actions acceptance are
# NOT yet validated, so auto-routing would risk creating a new class of
# broken links. Enable only after a targeted verification pass.
# ----------------------------------------------------------------------------
_PKO_GAMETYPES = {
    # phase_key -> {table_size: gametype}
    'bubble_zone': {8: 'MTTGeneral_ICMPKO8m1000PTBUBBLE152PT'},
    'ft_zone': {n: f'MTTGeneral_ICMPKO{n}m1000PTFT' for n in range(3, 10)},
}

_PKO_PHASE_KEYS = {
    # gem phase labels -> _PKO_GAMETYPES keys
    'bubble_zone': 'bubble_zone', 'bubble': 'bubble_zone',
    'ft_zone': 'ft_zone', 'final_table': 'ft_zone', 'ft': 'ft_zone',
}


def _is_bounty_hand(hand, app_details=None):
    """True when the hand is from a bounty/PKO/Mystery tournament."""
    fmt = (hand.get('format') or '').upper()
    if fmt in ('BOUNTY', 'PKO', 'MYSTERY_BOUNTY'):
        return True
    if app_details and app_details.get('is_bounty'):
        return True
    return False


def route_pko_gametype(hand, table_size):
    """Return an ICMPKO gametype for a bounty hand, or None.

    Only returns a regime when (a) GEM_GTOW_PKO_ROUTING=1 is set,
    (b) the hand's phase maps to an inventoried PKO regime, and
    (c) the table size is offered by that regime. Otherwise None —
    the caller stays on ChipEV with the 'approx' label.
    """
    if os.environ.get('GEM_GTOW_PKO_ROUTING') != '1':
        return None
    phase = (hand.get('tournament_phase') or '').lower()
    key = _PKO_PHASE_KEYS.get(phase)
    if not key:
        return None
    return _PKO_GAMETYPES.get(key, {}).get(table_size)

# GEM parser position name → GTOW position name (per table size)
_POS_MAP = {
    5: {'UTG': 'HJ', 'HJ': 'HJ', 'CO': 'CO', 'BTN': 'BTN',
        'SB': 'SB', 'BB': 'BB'},
    6: {'UTG': 'LJ', 'MP': 'HJ', 'HJ': 'HJ', 'LJ': 'LJ',
        'CO': 'CO', 'BTN': 'BTN', 'SB': 'SB', 'BB': 'BB'},
    7: {'UTG': 'UTG', 'LJ': 'LJ', 'HJ': 'HJ',
        'CO': 'CO', 'BTN': 'BTN', 'SB': 'SB', 'BB': 'BB'},
    8: {'UTG': 'UTG', 'UTG+1': 'UTG1', 'MP': 'LJ', 'LJ': 'LJ',
        'HJ': 'HJ', 'CO': 'CO', 'BTN': 'BTN', 'SB': 'SB', 'BB': 'BB'},
    9: {'UTG': 'UTG', 'UTG+1': 'UTG1', 'UTG+2': 'UTG2', 'MP': 'LJ',
        'LJ': 'LJ', 'HJ': 'HJ', 'CO': 'CO', 'BTN': 'BTN',
        'SB': 'SB', 'BB': 'BB'},
}

# Open-raise R-codes by depth tier and GTOW position.
# Rule: wrong R-code → "no solution". RAI for all-in (literal, no amount).
# depth_tier: use nearest LOWER key for interpolation.
# Validated: R2 universally ≤80bb (non-SB). R2.1 at 91bb+ for EP.
# Late positions transition earlier (HJ/CO at 60bb).
_OPEN_RAISE = {
    15:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2',
          'CO': 'R2', 'BTN': 'R2', 'SB': 'R2.5'},
    20:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2',
          'CO': 'R2', 'BTN': 'R2', 'SB': 'R2'},
    25:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2',
          'CO': 'R2', 'BTN': 'R2', 'SB': 'R3'},
    30:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2',
          'CO': 'R2', 'BTN': 'R2', 'SB': 'R3'},
    35:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2',
          'CO': 'R2', 'BTN': 'R2', 'SB': 'R3'},
    40:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2',
          'CO': 'R2', 'BTN': 'R2'},
    45:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2',
          'CO': 'R2', 'BTN': 'R2'},
    50:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2',
          'CO': 'R2', 'BTN': 'R2'},
    60:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2.1',
          'CO': 'R2.1', 'BTN': 'R2.2'},
    70:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2.1',
          'CO': 'R2.1', 'BTN': 'R2.2'},
    80:  {'UTG': 'R2', 'UTG1': 'R2', 'LJ': 'R2', 'HJ': 'R2.1',
          'CO': 'R2.1', 'BTN': 'R2.2'},
    91:  {'UTG': 'R2.1', 'UTG1': 'R2.1', 'LJ': 'R2.1', 'HJ': 'R2.1',
          'CO': 'R2.2', 'BTN': 'R2.5'},
    100: {'UTG': 'R2.1', 'UTG1': 'R2.1', 'LJ': 'R2.1', 'HJ': 'R2.1',
          'CO': 'R2.2', 'BTN': 'R2.5', 'SB': 'R3.5'},
}
_OPEN_TIERS = sorted(_OPEN_RAISE.keys())

# 3bet R-codes by depth tier and 3bettor position.
# Validated vs UTG open; assumed similar vs other openers (confirmed for CO).
_THREBET = {
    14:  {'BTN': 'R4'},
    15:  {'BTN': 'R4', 'LJ': 'R4', 'HJ': 'R4', 'CO': 'R4'},
    20:  {'BTN': 'R4.5', 'LJ': 'R4.5', 'HJ': 'R4.5', 'CO': 'R4.5',
          'SB': 'R5', 'BB': 'R6'},
    25:  {'BTN': 'R5', 'LJ': 'R5', 'HJ': 'R5', 'CO': 'R5',
          'SB': 'R6', 'BB': 'R7'},
    30:  {'BTN': 'R5.5', 'LJ': 'R5', 'HJ': 'R5', 'CO': 'R5.5',
          'SB': 'R6.5', 'BB': 'R7.5'},
    35:  {'BTN': 'R5', 'LJ': 'R5', 'HJ': 'R5', 'CO': 'R5',
          'SB': 'R5', 'BB': 'R7'},
    45:  {'BTN': 'R6.5', 'LJ': 'R6', 'HJ': 'R6', 'CO': 'R6.5',
          'SB': 'R7.5', 'BB': 'R8.5'},
    60:  {'BTN': 'R7', 'LJ': 'R6.5', 'HJ': 'R6.5', 'CO': 'R7',
          'SB': 'R8', 'BB': 'R9.5'},
}
_THREBET_TIERS = sorted(_THREBET.keys())

# Per-gametype ChipEV depth grids (validated against GTOW 2026-05-30).
# .125 suffix added at URL build time — these are integer depths.
# Source: gtow_reference.json scraped from GTOW solutions UI.
_DEPTH_GRIDS = {
    'MTTGeneral_3m': [
        6, 8, 10, 12, 15, 16, 20, 25, 30, 35, 40, 50, 60, 70,
    ],
    'MTTGeneral_4m': [
        6, 8, 9, 10, 12, 15, 18, 20, 25, 30, 32, 33, 35, 38, 40, 45, 50,
        60, 70,
    ],
    'MTTGeneral_5m': [
        4, 8, 10, 15, 20, 22, 25, 30, 35, 40, 45, 50, 60, 90,
    ],
    'MTT6mSimple': [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
        19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 32, 33, 34, 35,
        36, 37, 38, 40, 41, 42, 44, 46, 47, 48, 50, 52, 54, 55, 56, 58,
        60, 63, 65, 66, 70, 72, 74, 75, 80, 90, 100, 130, 140, 150, 200,
    ],
    'MTTGeneral_7m': [
        2, 5, 7, 10, 11, 12, 14, 15, 20, 22, 25, 27, 28, 30, 32, 35, 38,
        40, 45, 50, 60, 65,
    ],
    'MTTGeneral_8m': [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
        19, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
        37, 38, 40, 42, 45, 48, 49, 50, 51, 54, 55, 56, 58, 60, 63, 66,
        68, 70, 76, 78, 80, 91, 96, 100, 110, 120, 125, 130, 160,
        200, 206,
        # 152 removed v2.2.0: GTOW backend rejected depth=152.125 live
        # (hand 60027362, verification pass 2026-06-11). 206 verified OK.
    ],
    'MTTGeneralV2': [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
        19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
        35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50,
        51, 52, 53, 54, 56, 58, 60, 62, 64, 66, 68, 70, 72, 74, 75, 76,
        78, 80, 82, 84, 85, 86, 88, 90, 92, 94, 100, 110, 120, 125, 130,
        160, 200,
    ],
}

# Backward-compatible alias used by tests and external callers
_DEPTH_GRID_8M = _DEPTH_GRIDS['MTTGeneral_8m']


# ============================================================================
# DEPTH SNAPPING
# ============================================================================

def snap_depth(eff_bb, grid=None, gametype=None):
    """Snap effective BB to the nearest available depth in the GTOW grid.

    If gametype is provided (e.g. 'MTTGeneral_8m'), uses that gametype's
    validated depth grid.  Falls back to grid parameter, then 8-max default.

    Returns integer depth (without .125 suffix — that's added at URL time).
    """
    if grid is None:
        if gametype and gametype in _DEPTH_GRIDS:
            grid = _DEPTH_GRIDS[gametype]
        else:
            grid = _DEPTH_GRID_8M
    if not grid:
        return max(1, round(eff_bb))
    best = grid[0]
    best_dist = abs(eff_bb - best)
    for d in grid[1:]:
        dist = abs(eff_bb - d)
        if dist < best_dist:
            best_dist = dist
            best = d
    return best


# ============================================================================
# STACKS MATCHING (from _gtow_situations.json)
# ============================================================================

# Lazy-loaded stacks lookup: {gametype: {depth_int: [[stacks_int, ...], ...]}}
_STACKS_LOOKUP = None


def _load_stacks_lookup():
    """Load _gtow_situations.json and build compact lookup.

    Returns {gametype: {depth_int: [[s1, s2, ...], ...]}} or empty dict.
    File is optional — if missing, stacks param is omitted from URLs.
    """
    global _STACKS_LOOKUP
    if _STACKS_LOOKUP is not None:
        return _STACKS_LOOKUP

    _STACKS_LOOKUP = {}
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     '_gtow_situations.json'),
        os.path.join(os.getcwd(), '_gtow_situations.json'),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for gt, gt_data in data.items():
                    if gt not in CHIPEV_GAMETYPES.values():
                        continue  # skip ICM gametypes — ChipEV only
                    by_depth = {}
                    for sit in gt_data.get('situations', []):
                        eff_int = int(float(
                            str(sit['eff']).replace('.125', '')))
                        stacks_int = [
                            int(float(str(v).replace('.125', '')))
                            for v in sit['stacks']
                        ]
                        by_depth.setdefault(eff_int, []).append(stacks_int)
                    _STACKS_LOOKUP[gt] = by_depth
            except Exception:
                _STACKS_LOOKUP = {}
            break
    if not _STACKS_LOOKUP:
        # v2.2.0: surface the gap once. Verified live 2026-06-11: GTOW still
        # renders with a fallback stack row, so this is a correctness issue
        # (which curated stacks load), not a crash driver — but it should be
        # visible at build time and checked by verify_release.py.
        import sys as _sys
        print('[gem_gtow] WARNING: _gtow_situations.json not found — '
              'stacks= param omitted from all GTOW URLs (GTOW will pick '
              'a default stack row).', file=_sys.stderr)
    return _STACKS_LOOKUP


# GTOW position order per table size (stacks arrays use this order).
_GTOW_POS_ORDER = {
    3: ['BTN', 'SB', 'BB'],
    4: ['CO', 'BTN', 'SB', 'BB'],
    5: ['HJ', 'CO', 'BTN', 'SB', 'BB'],
    6: ['LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
    7: ['UTG', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
    8: ['UTG', 'UTG1', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
    9: ['UTG', 'UTG1', 'UTG2', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
}


def _pick_stacks(gametype, depth, table_size, app_details=None):
    """Pick the best-matching stacks row for a gametype+depth.

    If app_details has seat data, matches against actual per-player stacks.
    Otherwise picks the equal-stacks row (most generic solution).

    Returns stacks string 'd1.125-d2.125-...' or None if unavailable.
    """
    lookup = _load_stacks_lookup()
    gt_data = lookup.get(gametype)
    if not gt_data:
        return None

    rows = gt_data.get(depth)
    if not rows:
        return None

    if len(rows) == 1:
        # Only one option — use it
        chosen = rows[0]
    else:
        # Multiple rows — try to match against hand's actual stacks
        chosen = _match_stacks(rows, table_size, app_details)

    # Format: 'd1.125-d2.125-...'
    return '-'.join(f'{s}.125' for s in chosen)


def _match_stacks(rows, table_size, app_details):
    """Pick the best stacks row from multiple options.

    Strategy:
      1. If app_details has per-seat stacks → minimize sum-of-squared-
         differences vs actual stacks (in GTOW position order).
      2. Else → prefer equal-stacks row (lowest variance).
    """
    # Try to extract actual stacks from app_details
    actual = _extract_actual_stacks(table_size, app_details)

    if actual and len(actual) == len(rows[0]):
        # Match by distance to actual stacks
        best_row = rows[0]
        best_dist = sum((a - s) ** 2 for a, s in zip(actual, rows[0]))
        for row in rows[1:]:
            dist = sum((a - s) ** 2 for a, s in zip(actual, row))
            if dist < best_dist:
                best_dist = dist
                best_row = row
        return best_row
    else:
        # No actual stacks — pick the lowest-variance row (most "equal")
        best_row = rows[0]
        best_var = _variance(rows[0])
        for row in rows[1:]:
            v = _variance(row)
            if v < best_var:
                best_var = v
                best_row = row
        return best_row


def _extract_actual_stacks(table_size, app_details):
    """Extract per-position stacks from app_details in GTOW position order.

    Returns list of integer stacks or None if data unavailable.
    """
    if not app_details:
        return None
    seats = app_details.get('seats')
    if not seats:
        return None

    pos_order = _GTOW_POS_ORDER.get(table_size)
    if not pos_order:
        return None

    # Build position → stack_bb map from seats (using parser positions)
    pos_map = _POS_MAP.get(table_size, _POS_MAP.get(8, {}))
    # Invert: parser_pos → gtow_pos
    seat_stacks = {}  # gtow_pos → stack_bb
    for seat in seats:
        parser_pos = seat.get('position', '')
        stack_bb = seat.get('stack_bb')
        if not parser_pos or not stack_bb:
            continue
        gtow_pos = pos_map.get(parser_pos, parser_pos)
        seat_stacks[gtow_pos] = round(stack_bb)

    # Build ordered stacks array
    result = []
    for pos in pos_order:
        if pos not in seat_stacks:
            return None  # incomplete — can't match
        result.append(seat_stacks[pos])

    return result


def _variance(stacks):
    """Variance of a stacks list. Used to identify equal-stacks rows."""
    if not stacks:
        return float('inf')
    mean = sum(stacks) / len(stacks)
    return sum((s - mean) ** 2 for s in stacks) / len(stacks)


# ============================================================================
# RAISE CODE LOOKUP
# ============================================================================

def _tier_lookup(tiers_dict, tier_keys, depth_bb):
    """Find the nearest-lower tier dict for a given depth."""
    tier = tier_keys[0]
    for t in tier_keys:
        if t <= depth_bb:
            tier = t
        else:
            break
    return tiers_dict.get(tier, {})


def _get_open_rcode(gtow_pos, depth_bb):
    """Look up open-raise R-code for a position at a given depth.

    Returns R-code string (e.g. 'R2', 'R2.1') or None if unknown.
    """
    tier = _tier_lookup(_OPEN_RAISE, _OPEN_TIERS, depth_bb)
    return tier.get(gtow_pos)


def _get_3bet_rcode(gtow_pos, depth_bb):
    """Look up 3bet R-code for a position at a given depth.

    Returns R-code string or None.
    """
    tier = _tier_lookup(_THREBET, _THREBET_TIERS, depth_bb)
    return tier.get(gtow_pos)


# ============================================================================
# PREFLOP ACTION ENCODING
# ============================================================================

def _parse_pf_entry(entry):
    """Parse 'UTG(H):raises' -> (position_raw, action, is_hero)."""
    parts = entry.split(':')
    if len(parts) != 2:
        return None, None, False
    pos_raw, action = parts[0].strip(), parts[1].strip()
    is_hero = '(H)' in pos_raw
    pos_clean = pos_raw.replace('(H)', '').strip()
    return pos_clean, action, is_hero


def encode_preflop_actions(pf_sequence, table_size, depth_bb):
    """Encode pf_sequence list into GTOW preflop_actions string.

    Returns (tokens_str, hero_action_index, success).
      tokens_str:        'R2-F-F-F-F-C-F-F' or '' on failure
      hero_action_index: index of hero's FIRST action (0-based) or -1
      success:           True if all R-codes were resolved

    On failure (unknown R-code), returns ('', -1, False).
    The caller falls back to preflop root (history_spot=0).

    Defensive padding (v2.1.1): if pf_sequence starts mid-table (e.g.
    BTN opens but UTG-CO folds are not recorded), leading F tokens are
    prepended so history_spot counts ALL positions. This is critical for
    non-8-max tables where history_spot=3 on a 9-player table lands on
    a preflop node instead of the flop root.
    """
    pos_map = _POS_MAP.get(table_size, _POS_MAP.get(8, {}))
    pos_order = _GTOW_POS_ORDER.get(table_size, [])
    tokens = []
    hero_idx = -1
    raise_count = 0  # 1st=open, 2nd=3bet, 3rd+=4bet/jam
    call_before_raise = False  # limp pot marker (v2.2.0)

    # Pad leading folds: if the first actor isn't UTG (position 0),
    # earlier positions implicitly folded — prepend F tokens for them.
    if pf_sequence and pos_order:
        first_pos_raw, _, _ = _parse_pf_entry(pf_sequence[0])
        if first_pos_raw:
            first_gtow = pos_map.get(first_pos_raw, first_pos_raw)
            if first_gtow in pos_order:
                lead_folds = pos_order.index(first_gtow)
                for _ in range(lead_folds):
                    tokens.append('F')

    for i, entry in enumerate(pf_sequence):
        pos_raw, action, is_hero = _parse_pf_entry(entry)
        if pos_raw is None:
            continue

        gtow_pos = pos_map.get(pos_raw, pos_raw)

        if is_hero and hero_idx == -1:
            hero_idx = len(tokens)

        if action == 'folds':
            tokens.append('F')
        elif action == 'calls':
            if raise_count == 0:
                call_before_raise = True  # open limp
            tokens.append('C')
        elif action == 'checks':
            tokens.append('X')
        elif action == 'raises':
            # v2.2.0: raise-over-limp uses different sizes in GTOW's limp
            # trees — our open R-codes are invalid there (confirmed
            # SOMETHING_WENT_WRONG live, hand 41017571). Fall back to
            # preflop root rather than emit a known-broken path.
            if call_before_raise:
                return '', -1, False
            raise_count += 1
            if raise_count == 1:
                # Open raise
                rcode = _get_open_rcode(gtow_pos, depth_bb)
                if rcode is None:
                    return '', -1, False
                tokens.append(rcode)
            elif raise_count == 2:
                # 3bet
                rcode = _get_3bet_rcode(gtow_pos, depth_bb)
                if rcode is None:
                    return '', -1, False
                tokens.append(rcode)
            else:
                # 4bet+ → treat as all-in (RAI) at tournament depths
                tokens.append('RAI')
        else:
            # Unknown action type — skip (e.g. 'posts')
            continue

    return '-'.join(tokens), hero_idx, True


# ============================================================================
# BOARD ENCODING
# ============================================================================

def encode_board(board_cards):
    """['Ks', '9c', 'Js'] -> 'Ks9cJs'.  Lowercase suits confirmed working."""
    return ''.join(board_cards) if board_cards else ''


# ============================================================================
# URL ASSEMBLY
# ============================================================================

def _build_url(gametype, depth_bb, preflop_actions='', board='',
               history_spot=0, ai_solve=False, stacks=None):
    """Assemble the full GTOW solutions URL.

    Required params: gametype, depth, solution_type, soltab, history_spot.
    Optional:        preflop_actions (when not at root), board (postflop),
                     stacks (e.g. '50.125-45.125-30.125-...').

    stacks: dash-separated depth values with .125 suffix, UTG-first order.
            When provided, GTOW loads the exact pre-solved configuration
            matching this stack distribution. When omitted, GTOW picks a
            default row for the depth.

    ai_solve: when True, append the AI Solve dialog param so the dialog
              opens pre-filled on page load. Only useful for postflop spots
              where a flop root solution exists — preflop-only spots fail
              pre-fill (error toast). Validated 2026-05-30 Round 3.
    """
    params = {
        'gametype': gametype,
        'depth': f'{depth_bb}.125',
        'solution_type': 'gwiz',
        'soltab': 'strategy',
        'history_spot': str(history_spot),
    }
    if stacks:
        params['stacks'] = stacks
    if preflop_actions:
        params['preflop_actions'] = preflop_actions
    if board:
        params['board'] = board
    if ai_solve:
        params['dialogs'] = ('solfigr-create-custom-solution-dialog'
                             '_namespace-tmp/primary'
                             '_instaPrefill-true_mode-keepboard')

    return f"{GTOW_BASE}?{urlencode(params)}"


# ============================================================================
# BUILD SCHEMA (per-hand) — main entry point
# ============================================================================

def build_gtow_schema(hand, app_details=None, rd=None):
    """Build the GTOW URL schema for one hand.

    Returns dict: {status, url, label, spot_summary}.
      status:       'ready' | 'partial' | 'unavailable'
      url:          full GTOW URL or None
      label:        button label text (e.g. 'GTOW')
      spot_summary: human-readable description of the link target
    """
    result = {
        'status': 'unavailable',
        'url': None,
        'label': '',
        'spot_summary': '',
    }

    # ---- Extract hand data ----
    try:
        table_size = int(hand.get('table_size') or hand.get('n_players') or 0)
    except (ValueError, TypeError):
        table_size = 0
    if table_size < 2 or table_size > 9:
        result['spot_summary'] = f'unsupported table size ({table_size})'
        return result

    stack_bb = hand.get('eff_stack_bb') or hand.get('stack_bb') or 0
    if stack_bb < 1:
        result['spot_summary'] = 'no stack data'
        return result

    board = hand.get('board') or []
    pf_seq = hand.get('pf_sequence') or []
    players_at_flop = hand.get('players_at_flop') or 0
    has_postflop = len(board) >= 3

    if not pf_seq:
        result['spot_summary'] = 'no preflop sequence'
        return result

    # ---- Gametype + depth ----
    gametype = CHIPEV_GAMETYPES.get(table_size)
    if not gametype:
        result['spot_summary'] = f'no ChipEV gametype for {table_size}-max'
        return result

    # Bounty awareness (v2.2.0): 8/8 bounty hands in the live verification
    # pass were silently served ChipEV. Label honestly; optionally route to
    # an ICMPKO regime when the flag is on and the phase has one.
    is_bounty = _is_bounty_hand(hand, app_details)
    regime_note = ''
    family = 'ChipEV'
    if is_bounty:
        pko_gt = route_pko_gametype(hand, table_size)
        if pko_gt:
            gametype = pko_gt
            family = 'ICM-PKO'
        else:
            regime_note = ' — ChipEV approx (bounty)'

    depth = snap_depth(stack_bb, gametype=gametype)

    # Snap-gap honesty (v2.2.0): the 7m grid caps at 65bb, so deep 7-max
    # hands silently load far from the true effective stack. Surface it.
    snap_gap = abs(depth - stack_bb)
    gap_note = ''
    if snap_gap > max(5.0, 0.15 * stack_bb):
        gap_note = f' (nearest grid {depth}bb; hand ~{stack_bb:.0f}bb)'

    # ---- Best-match stacks for this gametype + depth ----
    stacks_str = _pick_stacks(gametype, depth, table_size, app_details)

    # ---- Encode preflop actions ----
    pf_tokens, hero_idx, pf_ok = encode_preflop_actions(
        pf_seq, table_size, depth)

    # ---- Determine link target ----

    if (has_postflop and pf_ok and players_at_flop <= 3
            and not hand.get('pf_allin')
            and not hand.get('pf_settled')):  # v8.8.9 BUG-5 + B149:
        # pf_settled covers preflop all-ins where Hero is not the
        # jammer/caller (jam-over-jam between villains) — the board
        # ran out with no postflop tree, so a flop-root URL returns
        # 'no solution'. pf_allin stays hero-centric for equity uses.
        # BEST: flop root with board + full preflop context
        board_str = encode_board(board[:3])  # flop only (3 cards)
        pf_action_count = len(pf_tokens.split('-')) if pf_tokens else 0
        history_spot = pf_action_count

        url = _build_url(gametype, depth,
                         preflop_actions=pf_tokens,
                         board=board_str,
                         history_spot=history_spot,
                         ai_solve=True,
                         stacks=stacks_str)

        result['status'] = 'ready'
        result['url'] = url
        result['label'] = '⚡GTOW≈' if (is_bounty and family == 'ChipEV') else '⚡GTOW'
        result['spot_summary'] = (
            f'Flop root: {board_str}, {pf_action_count} PF actions, '
            f'{depth}bb {table_size}-max {family}'
            f'{regime_note}{gap_note}')
        return result

    if not has_postflop and pf_ok and hero_idx >= 0:
        # GOOD: hero's preflop decision point
        # Encode only actions BEFORE hero's first action
        pf_parts = pf_tokens.split('-')
        pf_before_hero = '-'.join(pf_parts[:hero_idx])
        history_spot = hero_idx

        url = _build_url(gametype, depth,
                         preflop_actions=pf_before_hero,
                         history_spot=history_spot,
                         stacks=stacks_str)

        result['status'] = 'ready'
        result['url'] = url
        result['label'] = '⚡GTOW≈' if (is_bounty and family == 'ChipEV') else '⚡GTOW'
        result['spot_summary'] = (
            f'Preflop: hero at spot {hero_idx}, '
            f'{depth}bb {table_size}-max {family}'
            f'{regime_note}{gap_note}')
        return result

    # FALLBACK: preflop root (always works)
    url = _build_url(gametype, depth, history_spot=0, stacks=stacks_str)
    reason = ''
    if not pf_ok:
        reason = 'raise code unknown'
    elif players_at_flop > 3:
        reason = f'{players_at_flop}-way (no GTOW tree)'
    elif hero_idx < 0:
        reason = 'hero position not found'
    else:
        reason = 'fallback'

    result['status'] = 'partial'
    result['url'] = url
    result['label'] = '⚡GTOW≈' if (is_bounty and family == 'ChipEV') else '⚡GTOW'
    result['spot_summary'] = (
        f'Preflop root: {depth}bb {table_size}-max {family} ({reason})'
        f'{regime_note}{gap_note}')
    return result


# ============================================================================
# MANIFEST (CSV/JSON for sample-testing)
# ============================================================================

def build_manifest(hands_with_details, rd=None):
    """Build a manifest with one row per hand.

    hands_with_details: list of (hand, app_details) tuples.
    Returns list[dict] suitable for CSV/JSON export.
    """
    rows = []
    for hand, app_details in hands_with_details:
        schema = build_gtow_schema(hand, app_details, rd)
        hid = hand.get('id', '')
        hid_short = hid[-8:] if len(hid) > 8 else hid
        rows.append({
            'hand_id': hid_short,
            'status': schema['status'],
            'url': schema['url'] or '',
            'label': schema['label'],
            'spot_summary': schema['spot_summary'],
        })
    return rows
