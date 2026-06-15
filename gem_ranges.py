#!/usr/bin/env python3
"""
gem_ranges.py — v0.1

Villain range construction for gem_solver.
Given position + action sequence + board, produces a river range
(value + bluff buckets) with a complete audit trail of every
narrowing step.

TRANSPARENCY CONTRACT:
  The returned ranges are HEURISTIC, not solver-derived.
  Every narrowing rule applied is recorded in the `audit_log`
  returned alongside the range. Every result is reviewable.

  v0.2 caveats surfaced in audit_log:
    - Narrowing ratios are hand-classifier heuristics, not solver output
    - Board-specific value/bluff classification is rank-based
    - No explicit blocker/unblocker modeling at narrowing step
    - No ICM or bounty adjustment
"""
import os, re, itertools, json
from phevaluator import evaluate_cards

# ============================================================
# RANGE FILE LOADING
# ============================================================
RANKS = '23456789TJQKA'
RANK_VAL = {r: i+2 for i, r in enumerate(RANKS)}
SUITS = 'shdc'

def _expand_plus(token):
    """
    Expand '88+' to ['88','99','TT','JJ','QQ','KK','AA']
    Expand 'AKs+' to ['AKs','AQs'...]? NO — AKs+ means AKs only for pairs context;
      for broadway-style: K9s+ means K9s, KTs, KJs, KQs (same high card, increasing kicker)
    Expand 'T9s+' to ['T9s','J9s','Q9s','K9s','A9s']? No, convention is same high card, so T9s+ = T9s only
      Actually convention varies. Most common: T9s+ = T9s, JTs, QJs, KQs (connectors increasing)
      We'll use the CONSERVATIVE interpretation: same kicker rank, high card increasing.
      e.g. A9s+ means A9s, ATs, AJs, AQs, AKs
    """
    # Pair+: 88+
    m = re.fullmatch(r'([2-9TJQKA])\1\+', token)
    if m:
        start = RANK_VAL[m.group(1)]
        return [r+r for r in RANKS if RANK_VAL[r] >= start]
    # Kicker+: AKs+ / AQo+
    m = re.fullmatch(r'([2-9TJQKA])([2-9TJQKA])([so])\+', token)
    if m:
        r1, r2, kind = m.group(1), m.group(2), m.group(3)
        v1, v2 = RANK_VAL[r1], RANK_VAL[r2]
        out = []
        for r in RANKS:
            rv = RANK_VAL[r]
            if v1 > v2 and rv >= v2 and rv < v1:
                out.append(r1 + r + kind)
            elif v2 > v1 and rv >= v1 and rv < v2:
                out.append(r2 + r + kind)
        # Include base (AKs itself)
        out.append(token[:-1])
        return sorted(set(out))
    # Connector+: 94o+ (rare in RYE format) — expand as 9-x where x >= 4 but < 9
    # Handled by the kicker+ branch above.
    # Plain hand like 'AKo' or '88'
    return [token]

def _parse_range_line(line):
    """Parse 'OPEN_100BB_BTN: AA, KK, ... [53.8%]' → (key, {hand: weight})."""
    if ':' not in line: return None
    key, rest = line.split(':', 1)
    key = key.strip()
    # Strip trailing [X.X%]
    rest = re.sub(r'\[[\d.]+%\]$', '', rest).strip()
    hands = {}
    for tok in rest.split(','):
        tok = tok.strip()
        if not tok: continue
        for expanded in _expand_plus(tok):
            hands[expanded] = 1.0
    return key, hands

def normalize_hand_class(cards):
    """Normalize a 2-card hand to its class: 'AKs', 'AKo', 'AA', etc.
    Input: list of 2 card strings like ['Ah', 'Kd'] or string 'AhKd'."""
    if isinstance(cards, str):
        cards = [cards[i:i+2] for i in range(0, len(cards), 2)]
    if len(cards) < 2:
        return ''
    r0, s0 = cards[0][0].upper(), cards[0][1].lower()
    r1, s1 = cards[1][0].upper(), cards[1][1].lower()
    # Sort by rank (higher first)
    if RANK_VAL.get(r1, 0) > RANK_VAL.get(r0, 0):
        r0, s0, r1, s1 = r1, s1, r0, s0
    if r0 == r1:
        return f"{r0}{r1}"  # pair
    suited = 's' if s0 == s1 else 'o'
    return f"{r0}{r1}{suited}"


def hand_in_range(hand_class, range_str):
    """Check if a hand class (e.g., 'ATo', '88') is in a range string.

    Range string format: '77+, A9s+, KTs+, QJs, ATo+, KQo'
    Returns True if the hand is part of the range.

    Batch 3 (1C): used for minimum-hand threshold and defend range membership.
    """
    if not hand_class or not range_str:
        return False
    hc = hand_class.strip()
    # Expand the range into individual hand classes
    expanded = set()
    for token in range_str.split(','):
        token = token.strip()
        if not token:
            continue
        for h in _expand_plus(token):
            expanded.add(h)
    return hc in expanded


def range_boundary(range_str):
    """Return the weakest hands in a range (the boundary).

    Examines the expanded range and returns the 3 lowest-ranked hand classes.
    Useful for "minimum correct hand" display.

    Returns: string like 'Q9o, J9s, 77' or '' if range is empty.
    """
    if not range_str:
        return ''
    expanded = []
    for token in range_str.split(','):
        token = token.strip()
        if not token:
            continue
        for h in _expand_plus(token):
            expanded.append(h)
    if not expanded:
        return ''
    # Sort by hand strength (pairs highest, then by ranks)
    def _hand_strength(hc):
        if len(hc) == 2:  # pair
            return (2, RANK_VAL.get(hc[0], 0), RANK_VAL.get(hc[0], 0))
        r0 = RANK_VAL.get(hc[0], 0) if hc else 0
        r1 = RANK_VAL.get(hc[1], 0) if len(hc) > 1 else 0
        suited_bonus = 0.5 if hc.endswith('s') else 0
        return (1 + suited_bonus, r0, r1)
    expanded.sort(key=_hand_strength)
    # Return bottom 3
    bottom = expanded[:3]
    return ', '.join(bottom)


# ============================================================
# v8.14.1 P0-2: shared canonical chart selection + range evidence
# ------------------------------------------------------------
# ONE selector used by BOTH the coverage/worklist builder and the hand-detail
# renderer so the grid widget and the TL;DR can never cite different charts for
# the same decision (the 73400934 contradiction). Every result carries a
# `coverage` tag: 'exact' (this position+depth chart exists), 'proxy' (found via
# a documented position alias, e.g. UTG+1->HJ), or 'closest' (nearest depth
# tier). Callers MUST disclose proxy/closest — never present them as exact.
# ============================================================

# Mirror of gem_coverage_builder._POS_ALIAS (earlier seat -> nearest charted seat).
RANGE_POS_ALIAS = {'UTG': ['LJ'], 'EP': ['LJ'], 'LJ': ['UTG'],
                   'MP': ['HJ'], 'UTG+1': ['HJ', 'LJ'], 'UTG+2': ['HJ', 'MP']}

_JAM_DEPTH_TIERS = [8, 10, 12, 15, 20, 25]


def _jam_target_depth(stack_bb):
    s = stack_bb or 0
    if s <= 9: return 8
    if s <= 11: return 10
    if s <= 13.5: return 12
    if s <= 17.5: return 15
    if s <= 22.5: return 20
    return 25


def _open_depth_bucket(stack_bb):
    s = stack_bb or 0
    if s < 20: return '10-20BB'
    if s < 40: return '20-40BB'
    return '100BB'


def _coverage_for(idx):
    """idx into the position-tries list: 0 = the real seat (exact), >0 = alias."""
    return 'exact' if idx == 0 else 'proxy'


def select_open_jam_chart(pos, stack_bb, ranges):
    """Pick the open-SHOVE chart for (pos, effective stack). Prefers the JAM_
    (jam-subset) chart over PUSH_ (full open range) at the depth-quantised tier,
    then position aliases, then adjacent depth tiers.

    Returns (chart_key|None, target_depth, coverage) with coverage in
    {'exact','proxy','closest','none'}.
    """
    ranges = ranges or {}
    target = _jam_target_depth(stack_bb)
    pos_tries = [pos] + RANGE_POS_ALIAS.get(pos, [])
    for px in ('JAM_', 'PUSH_'):
        for i, pp in enumerate(pos_tries):
            key = f'{px}{target}BB_{pp}'
            if ranges.get(key):
                return key, target, _coverage_for(i)
    # adjacent depth tiers (nearest first), same position-tries
    adj = sorted(_JAM_DEPTH_TIERS, key=lambda d: abs(d - target))
    for at in adj:
        if at == target:
            continue
        for px in ('JAM_', 'PUSH_'):
            for pp in pos_tries:
                key = f'{px}{at}BB_{pp}'
                if ranges.get(key):
                    return key, at, 'closest'
    return None, target, 'none'


def select_open_chart(pos, stack_bb, ranges):
    """Pick the first-in OPEN (RFI) chart for (pos, Hero open depth). RFI depth
    is Hero's OWN stack (how deep you open), not effective-vs-caller.

    Returns (chart_key|None, bucket, coverage).
    """
    ranges = ranges or {}
    bucket = _open_depth_bucket(stack_bb)
    pos_tries = [pos] + RANGE_POS_ALIAS.get(pos, [])
    for i, pp in enumerate(pos_tries):
        key = f'OPEN_{bucket}_{pp}'
        if ranges.get(key):
            return key, bucket, _coverage_for(i)
    # adjacent buckets (nearest first)
    order = {'10-20BB': ['20-40BB', '100BB'],
             '20-40BB': ['10-20BB', '100BB'],
             '100BB': ['20-40BB', '10-20BB']}.get(bucket, [])
    for ab in order:
        for pp in pos_tries:
            key = f'OPEN_{ab}_{pp}'
            if ranges.get(key):
                return key, ab, 'closest'
    return None, bucket, 'none'


def _range_top_examples(chart_dict, n=5):
    """Highest n hand classes in the chart (for the 'includes' example line)."""
    if not chart_dict:
        return []
    keys = list(chart_dict.keys())

    def _rank(hc):
        a = RANK_VAL.get(hc[0], 0) if hc else 0
        b = RANK_VAL.get(hc[1], 0) if len(hc) > 1 else 0
        pair_bonus = 100 if (len(hc) == 2) else 0
        suit_bonus = 1 if hc.endswith('s') else 0
        return (pair_bonus + a, b + suit_bonus)
    keys.sort(key=_rank, reverse=True)
    return keys[:n]


def build_range_evidence(role, pos, cards, hero_stack_bb, eff_stack_bb,
                         ranges, jammer_pos=None, opener_pos=None):
    """Build a chart-backed range-evidence object for a preflop decision, or
    None when no chart applies. Invents nothing: membership/boundary come from
    the loaded chart cells; the caller humanises chart_key and discloses
    coverage. `membership` is the SINGLE SOURCE OF TRUTH for in/out wording.

    role: 'rfi' | 'open_shove' | 'call_jam' | 'rejam'
    Returns dict: {role, spot_label, position, facing, depth_bb, depth_basis,
                   chart_key, coverage, hero_hand, membership ('inside'|'outside'),
                   boundary (bool), top_examples [..], boundary_examples str, note}
    """
    hc = normalize_hand_class(cards)
    if not hc:
        return None
    ranges = ranges or {}
    chart_key = None
    coverage = 'none'
    depth_bb = 0
    depth_basis = ''
    facing = ''
    spot_label = ''
    if role == 'rfi':
        depth_bb = hero_stack_bb or 0
        depth_basis = 'hero open depth'
        chart_key, _bk, coverage = select_open_chart(pos, depth_bb, ranges)
        spot_label = f'first-in open ({pos})'
        facing = 'first-in (folded to Hero)'
    elif role == 'open_shove':
        depth_bb = eff_stack_bb or hero_stack_bb or 0
        depth_basis = 'effective vs the live blind'
        chart_key, _td, coverage = select_open_jam_chart(pos, depth_bb, ranges)
        spot_label = f'open-shove ({pos})'
        facing = 'first-in jam'
    elif role == 'call_jam':
        depth_bb = eff_stack_bb or hero_stack_bb or 0
        depth_basis = 'effective vs the jam'
        # nearest available call-jam tier (round to nearest, not ceil — a 17BB
        # call is nearer the 15BB chart than the 20BB chart, and call ranges
        # shift a lot between tiers).
        _d = min([12, 15, 20, 30], key=lambda t: abs(t - (depth_bb or 0)))
        _jp = (jammer_pos or '').strip()
        # The shallowest call-jam chart is 12BB; below ~9BB the calling range is
        # far wider than any chart, so membership against the 12BB chart would
        # falsely read 'fold'. Treat a large depth gap as closest/unreliable and
        # do NOT assert in/out (defer to pot-odds for short calls).
        _depth_gap = abs(depth_bb - _d)
        for _cand in ([f'CALLJAM_{_d}BB_vs{_jp}'] if _jp else []):
            if ranges.get(_cand):
                chart_key = _cand
                coverage = 'exact' if _depth_gap <= 3 else 'closest'
                break
        spot_label = f'call a {_jp or "?"} jam ({pos})'
        facing = f'vs {_jp or "?"} jam'
        if chart_key and coverage == 'closest' and depth_bb < (_d - 3):
            # spot is much shorter than the chart → calling widens; don't assert
            hc2 = normalize_hand_class(cards)
            return {'role': role, 'spot_label': spot_label, 'position': pos,
                    'facing': facing, 'depth_bb': round(depth_bb, 1),
                    'depth_basis': depth_basis, 'chart_key': chart_key,
                    'coverage': 'closest', 'hero_hand': hc2,
                    'membership': 'unknown', 'boundary': False,
                    'top_examples': [], 'boundary_examples': '',
                    'note': (f'at {depth_bb:.0f}BB the calling range is wider '
                             f'than the shallowest ({_d}BB) chart — use pot-odds '
                             f'/ equity, not chart membership')}
    elif role == 'rejam':
        _op = (opener_pos or '').strip().replace('+', '')
        _hp = (pos or '').strip().replace('+', '')
        for _cand in ([f'REJAM_{_hp}vs{_op}'] if (_op and _hp) else []):
            if ranges.get(_cand):
                chart_key, coverage = _cand, 'exact'
                break
        depth_bb = eff_stack_bb or hero_stack_bb or 0
        depth_basis = 'effective at the re-jam'
        spot_label = f're-jam ({pos} vs {_op or "?"})'
        facing = f'vs {_op or "?"} open'
    else:
        return None
    if not chart_key or coverage == 'none':
        return {'role': role, 'spot_label': spot_label, 'position': pos,
                'facing': facing, 'depth_bb': round(depth_bb, 1),
                'depth_basis': depth_basis, 'chart_key': None,
                'coverage': 'none', 'hero_hand': hc, 'membership': 'unknown',
                'boundary': False, 'top_examples': [], 'boundary_examples': '',
                'note': 'no charted range at this depth/position'}
    chart_dict = ranges.get(chart_key, {})
    inside = hc in chart_dict
    _bnd_str = range_boundary(', '.join(chart_dict.keys()))
    _bnd_set = set(x.strip() for x in _bnd_str.split(',') if x.strip())
    return {
        'role': role, 'spot_label': spot_label, 'position': pos,
        'facing': facing, 'depth_bb': round(depth_bb, 1),
        'depth_basis': depth_basis, 'chart_key': chart_key,
        'coverage': coverage, 'hero_hand': hc,
        'membership': 'inside' if inside else 'outside',
        'boundary': bool(inside and hc in _bnd_set),
        'top_examples': _range_top_examples(chart_dict),
        'boundary_examples': _bnd_str,
        'note': '',
    }


def load_ranges(path='/mnt/project/Poker_Ranges_Text.txt'):
    """Load all ranges from the RYE text file. Returns {key: {hand: weight}}."""
    ranges = {}
    if not os.path.exists(path):
        # Local fallback
        local = os.path.join(os.path.dirname(__file__) or '.', 'Poker_Ranges_Text.txt')
        if os.path.exists(local): path = local
        else: return ranges
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('---') or line.startswith('==') or line.startswith('POKER'): continue
            parsed = _parse_range_line(line)
            if parsed: ranges[parsed[0]] = parsed[1]
    return ranges

# ============================================================
# HAND-DESCRIPTOR → COMBO EXPANSION (same as gem_solver)
# ============================================================
def expand_hand_desc(desc):
    desc = desc.strip()
    if len(desc) == 4 and desc[1] in SUITS and desc[3] in SUITS:
        return [(desc[:2], desc[2:])]
    if len(desc) == 2 and desc[0] == desc[1]:
        r = desc[0]
        cards = [r+s for s in SUITS]
        return list(itertools.combinations(cards, 2))
    if len(desc) == 3:
        r1, r2, kind = desc[0], desc[1], desc[2]
        out = []
        for s1 in SUITS:
            for s2 in SUITS:
                if kind == 's' and s1 != s2: continue
                if kind == 'o' and s1 == s2: continue
                c1, c2 = r1+s1, r2+s2
                if c1 == c2: continue
                out.append((c1, c2))
        return out
    return []

def range_to_combos(range_dict, used_cards):
    """{hand_desc: weight} → [(c1,c2,weight,desc), ...] excluding conflicts."""
    used = set(used_cards)
    out = []
    for desc, w in range_dict.items():
        for c1, c2 in expand_hand_desc(desc):
            if c1 in used or c2 in used: continue
            out.append((c1, c2, w, desc))
    return out

# ============================================================
# HAND CLASSIFICATION ON PARTIAL BOARD
# ============================================================
def _has_flush_draw(hole, board):
    """4+ cards of same suit in hole+board."""
    suits = [c[1] for c in hole + board]
    return any(suits.count(s) >= 4 for s in SUITS)

def _has_oesd_or_straight(hole, board):
    """OESD (4 consecutive) or made straight in hole+board."""
    vals = sorted(set(RANK_VAL[c[0]] for c in hole + board))
    if 14 in vals: vals.append(1)  # wheel
    vals = sorted(set(vals))
    # check for 4 consecutive
    for i in range(len(vals) - 3):
        if vals[i+3] - vals[i] == 3: return True
    return False

def _has_gutshot(hole, board):
    """Gutshot = 4 cards in a 5-rank span, one missing."""
    vals = sorted(set(RANK_VAL[c[0]] for c in hole + board))
    if 14 in vals: vals.append(1)
    vals = sorted(set(vals))
    for i in range(len(vals) - 3):
        span = vals[i+3] - vals[i]
        if span == 4: return True  # 4 cards in 5 ranks = one gap
    return False

def _has_overcards(hole, board):
    """Both hole cards higher than top board card."""
    if not board: return False
    top = max(RANK_VAL[c[0]] for c in board)
    return all(RANK_VAL[c[0]] > top for c in hole)

def classify_on_flop(hole, flop):
    """Return one of: set, 2pair, top_pair, mid_pair, bot_pair, oc_fd, oc_sd,
                     fd_only, sd_only, gutshot, overcards, air."""
    rank = evaluate_cards(*hole, *flop)
    has_fd = _has_flush_draw(hole, flop)
    has_sd = _has_oesd_or_straight(hole, flop)
    has_gut = _has_gutshot(hole, flop)
    has_oc = _has_overcards(hole, flop)
    # phev 5-card: <= 2467 is one pair or better
    # Rough buckets (phev ranks): straight-flush ~<11, 4oak <167, FH <322, flush <1600,
    #   straight <1610, trips <2468, 2pair <3326, pair <6186
    if rank < 167: return 'monster'  # 4oak+/straight flush
    if rank < 322: return 'fullhouse'
    if rank < 1600: return 'flush'
    if rank < 1610: return 'straight'
    if rank < 2468: return 'set'
    if rank < 3326: return 'two_pair'
    if rank < 6186:
        # pair — classify by which rank
        flop_ranks = [RANK_VAL[c[0]] for c in flop]
        hole_ranks = [RANK_VAL[c[0]] for c in hole]
        # pocket pair: both hole cards same rank
        if hole[0][0] == hole[1][0]:
            hr = RANK_VAL[hole[0][0]]
            if hr > max(flop_ranks): return 'overpair'
            if hr > sorted(flop_ranks)[1]: return 'underpair_above_mid'
            return 'underpair'
        # one pair via board match
        paired_rank = None
        for hr in hole_ranks:
            if hr in flop_ranks: paired_rank = hr; break
        if paired_rank == max(flop_ranks): return 'top_pair'
        if paired_rank == sorted(flop_ranks)[1]: return 'mid_pair'
        return 'bot_pair'
    # Unpaired: classify draws
    if has_fd and has_sd: return 'fd_sd_combo'
    if has_fd and has_oc: return 'oc_fd'
    if has_fd: return 'fd_only'
    if has_sd: return 'sd_only'
    if has_gut and has_oc: return 'oc_gut'
    if has_gut: return 'gutshot'
    if has_oc: return 'overcards'
    return 'air'

def classify_on_river(hole, board):
    """Final hand strength bucket on river (5-card board)."""
    rank = evaluate_cards(*hole, *board)
    if rank < 167: return 'monster'
    if rank < 322: return 'fullhouse'
    if rank < 1600: return 'flush'
    if rank < 1610: return 'straight'
    if rank < 2468: return 'set'
    if rank < 3326: return 'two_pair'
    if rank < 6186:
        # pair analysis by kicker
        board_ranks = [RANK_VAL[c[0]] for c in board]
        hole_ranks = [RANK_VAL[c[0]] for c in hole]
        if hole[0][0] == hole[1][0]:
            hr = RANK_VAL[hole[0][0]]
            if hr > max(board_ranks): return 'overpair'
            return 'underpair'
        paired_rank = None
        for hr in hole_ranks:
            if hr in board_ranks: paired_rank = hr; break
        if paired_rank == max(board_ranks): return 'top_pair'
        if paired_rank == sorted(board_ranks)[-2]: return 'second_pair'
        return 'weak_pair'
    return 'high_card'

# ============================================================
# NARROWING RULES — HEURISTIC, DOCUMENTED
# ============================================================
# Weight multipliers per street-action, per hand class.
# These are explicit, tunable, and logged in audit trail.

FLOP_CALL_KEEP = {
    # Villain called Hero's flop bet. Caller keeps: pairs+, strong draws, some floats.
    'monster': 1.0, 'fullhouse': 1.0, 'flush': 1.0, 'straight': 1.0,
    'set': 1.0, 'two_pair': 1.0,
    'overpair': 1.0, 'top_pair': 1.0, 'mid_pair': 0.85, 'bot_pair': 0.55,
    'underpair_above_mid': 0.75, 'underpair': 0.45,
    'fd_sd_combo': 1.0, 'oc_fd': 0.95, 'fd_only': 0.75,
    'sd_only': 0.85, 'oc_gut': 0.55, 'gutshot': 0.35,
    'overcards': 0.20, 'air': 0.05,
}
TURN_CALL_KEEP = {
    # Villain called Hero's turn barrel. Range tightens further.
    'monster': 1.0, 'fullhouse': 1.0, 'flush': 1.0, 'straight': 1.0,
    'set': 1.0, 'two_pair': 1.0,
    'overpair': 1.0, 'top_pair': 0.95, 'mid_pair': 0.55, 'bot_pair': 0.20,
    'underpair_above_mid': 0.45, 'underpair': 0.15,
    'fd_sd_combo': 1.0, 'oc_fd': 0.85, 'fd_only': 0.70,
    'sd_only': 0.75, 'oc_gut': 0.35, 'gutshot': 0.20,
    'overcards': 0.08, 'air': 0.02,
}

# River lead range split: which river-classified hands go to value vs bluff bucket.
# A hand is in VALUE if it's genuinely strong enough to lead for value.
# A hand is in BLUFF if it's a hand that leads as a bluff (typically busted draws).
# The remainder (medium pairs that check-call) stays out of the lead range entirely.
RIVER_LEAD_VALUE = {'monster', 'fullhouse', 'flush', 'straight',
                    'set', 'two_pair', 'overpair', 'top_pair'}
# Bluffs: typically hands that were draws and missed. We detect "was a draw on turn, now high card."
# For simplicity at the range level, we flag high_card hands that had flop/turn draw equity.

# ============================================================
# RANGE NARROWING WITH AUDIT TRAIL
# ============================================================
def narrow_range_by_call(range_dict, board_so_far, street_name, used_cards, keep_table):
    """
    range_dict: {hand_desc: weight}
    board_so_far: 3 cards (flop) or 4 (turn)
    Returns: (new_range_dict, audit_log_entry)
    """
    combos = range_to_combos(range_dict, used_cards)
    new_weights = {}  # hand_desc → summed new weight
    class_counts = {}
    for c1, c2, w, desc in combos:
        cls = classify_on_flop([c1, c2], board_so_far)
        keep = keep_table.get(cls, 0.3)
        new_w = w * keep
        new_weights[desc] = new_weights.get(desc, 0) + new_w / len(expand_hand_desc(desc))
        # Normalize: each combo contributed 1/ncombos of the descriptor's weight
        class_counts[cls] = class_counts.get(cls, 0) + 1
    # Clean very-low-weight descriptors
    cleaned = {d: round(w, 3) for d, w in new_weights.items() if w >= 0.02}
    audit = {
        'step': f'{street_name}_call_narrowing',
        'keep_table_used': f'{street_name.upper()}_CALL_KEEP',
        'board_so_far': ' '.join(board_so_far),
        'input_combo_count': len(combos),
        'output_desc_count': len(cleaned),
        'hand_class_distribution': class_counts,
        'retention_pct': round(sum(cleaned.values()) / max(sum(range_dict.values()), 1e-9) * 100, 1),
    }
    return cleaned, audit

def split_river_lead_range(range_dict, board, hero_used_cards, river_lead_pct_pot=75):
    """
    Split villain's river-lead range into value and bluff buckets.
    Board = full 5-card river board.
    Returns: (value_range, bluff_range, audit_entry)
    """
    value = {}
    bluff = {}
    classifications = {}
    for desc, w in range_dict.items():
        combos = expand_hand_desc(desc)
        valid_combos = [(c1, c2) for c1, c2 in combos
                        if c1 not in hero_used_cards and c2 not in hero_used_cards
                        and c1 not in board and c2 not in board]
        if not valid_combos: continue
        # Classify on river — use first valid combo as representative
        c1, c2 = valid_combos[0]
        river_class = classify_on_river([c1, c2], board)
        classifications[desc] = river_class
        if river_class in RIVER_LEAD_VALUE:
            value[desc] = w
        elif river_class in ('high_card', 'weak_pair'):
            # Bluff candidate — weight by "was this a draw that missed?"
            # Heuristic: if hole has 2 suited cards AND a flush didn't complete, likely busted FD.
            # If connectors/gappers, likely busted SD.
            # Keep at reduced weight (typical bluff-mix rate).
            bluff[desc] = w * 0.4  # population leads ~40% of busted-draw combos as bluffs
    audit = {
        'step': 'river_lead_split',
        'board': ' '.join(board),
        'lead_size_pct_pot': river_lead_pct_pot,
        'classifications': classifications,
        'value_desc_count': len(value),
        'bluff_desc_count': len(bluff),
    }
    return value, bluff, audit

# ============================================================
# HIGH-LEVEL ORCHESTRATION
# ============================================================
def construct_villain_river_range(
    villain_position,
    hero_position,
    hero_open_size_pct,
    stack_depth_bb,
    hero_cards,
    board,
    action_sequence,
    ranges_file_path='/mnt/project/Poker_Ranges_Text.txt',
):
    """
    High-level: given preflop + action sequence, produce a river
    value-range + bluff-range suitable for gem_solver input.

    action_sequence: list of dicts, one per street post-flop:
      [{'street':'flop','hero':'bet','villain':'call','hero_size_pct':33}, ...]

    Returns: {
      'value_range': [{'desc':..., 'weight':...}, ...],
      'bluff_range': [{'desc':..., 'weight':...}, ...],
      'audit_log':   [dict, dict, ...],
      'starting_range_key': str,
    }
    """
    audit_log = []
    ranges = load_ranges(ranges_file_path)

    # Step 1: pick preflop starting range
    # Map stack depth to closest bucket
    if stack_depth_bb <= 20:   depth_key = '10-20BB'
    elif stack_depth_bb <= 40: depth_key = '20-40BB'
    else:                      depth_key = '100BB'

    # Pick the defend range key for villain
    # Simplification: use BB_DEF_vs<size>pct for BB defender, else use generic fallback
    starting_key = None
    candidates = []
    if villain_position == 'BB':
        # map open-size to closest BB_DEF bucket
        for pct in [15, 20, 25, 30, 35, 40, 45]:
            candidates.append(f'BB_DEF_vs{pct}pct')
        # Pick closest to hero_open_size_pct (default open ~22-30%)
        target = min(45, max(15, int(hero_open_size_pct)))
        rounded = min([15,20,25,30,35,40,45], key=lambda x: abs(x-target))
        starting_key = f'BB_DEF_vs{rounded}pct'
    else:
        # Cold-caller: use flat range from position vs opener
        flat_key = f'FLAT3B_{depth_key.replace("-", "_")}_{villain_position}vs{hero_position}'
        starting_key = flat_key
        if flat_key not in ranges:
            # Fallback: use open range for villain as rough proxy (looser assumption)
            starting_key = f'OPEN_{depth_key}_{villain_position}'

    if starting_key not in ranges:
        audit_log.append({
            'step': 'preflop_range_selection',
            'attempted_key': starting_key,
            'result': 'NOT_FOUND — fallback to wide defense approximation',
        })
        # Last-resort fallback: generic BB_DEF_vs30pct
        starting_key = 'BB_DEF_vs30pct' if 'BB_DEF_vs30pct' in ranges else list(ranges.keys())[0]

    current = dict(ranges[starting_key])  # copy
    audit_log.append({
        'step': 'preflop_range_loaded',
        'key': starting_key,
        'combo_count_pre': sum(len(expand_hand_desc(d)) for d in current),
        'desc_count': len(current),
    })

    # Step 2: walk action sequence
    used = set(hero_cards) | set(board)
    if len(board) >= 3 and action_sequence:
        flop = board[:3]
        for step in action_sequence:
            street = step['street']
            if street == 'flop' and step.get('villain') == 'call':
                current, audit = narrow_range_by_call(current, flop, 'flop', used, FLOP_CALL_KEEP)
                audit_log.append(audit)
            elif street == 'turn' and step.get('villain') == 'call':
                turn_board = board[:4] if len(board) >= 4 else flop
                current, audit = narrow_range_by_call(current, turn_board, 'turn', used, TURN_CALL_KEEP)
                audit_log.append(audit)

    # Step 3: split river range into value/bluff
    if len(board) == 5:
        # find river lead size if provided
        river_step = next((s for s in (action_sequence or []) if s.get('street') == 'river'), None)
        lead_size = (river_step or {}).get('villain_size_pct', 75)
        value_range, bluff_range, audit = split_river_lead_range(current, board, set(hero_cards), lead_size)
        audit_log.append(audit)
    else:
        value_range, bluff_range = current, {}

    # Convert to spec format
    value_spec = [{'desc': d, 'weight': round(w, 3)} for d, w in sorted(value_range.items(), key=lambda kv: -kv[1])]
    bluff_spec = [{'desc': d, 'weight': round(w, 3)} for d, w in sorted(bluff_range.items(), key=lambda kv: -kv[1])]

    return {
        'value_range': value_spec,
        'bluff_range': bluff_spec,
        'audit_log': audit_log,
        'starting_range_key': starting_key,
    }

# ============================================================
# CLI — self-test
# ============================================================
if __name__ == '__main__':
    import sys
    ranges = load_ranges()
    print(f'Loaded {len(ranges)} ranges from RYE file')
    # Self-test: reproduce the JJ scenario
    result = construct_villain_river_range(
        villain_position='BB',
        hero_position='BTN',
        hero_open_size_pct=22,
        stack_depth_bb=40,
        hero_cards=['Js','Jc'],
        board=['Qh','8d','3s','6c','2d'],
        action_sequence=[
            {'street':'flop','hero':'bet','villain':'call','hero_size_pct':33},
            {'street':'turn','hero':'bet','villain':'call','hero_size_pct':55},
            {'street':'river','hero':'check','villain':'bet','villain_size_pct':75},
        ]
    )
    print(f'Starting range: {result["starting_range_key"]}')
    print(f'Audit steps: {len(result["audit_log"])}')
    print(f'Value range: {len(result["value_range"])} descriptors')
    print(f'Bluff range: {len(result["bluff_range"])} descriptors')
    print()
    print('Top 8 value combos:')
    for e in result['value_range'][:8]:
        print(f"  {e['desc']:6}  w={e['weight']}")
    print('Top 8 bluff combos:')
    for e in result['bluff_range'][:8]:
        print(f"  {e['desc']:6}  w={e['weight']}")
