#!/usr/bin/env python3
"""
gem_phase.py — Tournament phase estimation via chip-fraction model (v8.6.3).

Replaces the level-proxy heuristic with a field-independent chip-fraction
approach. Core identity: field × starting_stack = players_left × avg_stack,
so field_fraction = starting_stack / avg_stack (no field size needed).

Validated against ground truth:
  - Incumbent (level proxy): 65-73% terminal accuracy, 11-12% ITM recall
  - Chip-fraction (this): 86-89% terminal accuracy, 72-79% ITM recall
  - McNemar p<0.001 on both Elliott (103 tourneys) and Ron (175 tourneys)
"""
import os
import re
import statistics
from collections import defaultdict

# ============================================================
# SHARED PRIMITIVES
# ============================================================

def monotonic_smooth(observations, lower_bound, upper_bound,
                     terminal_anchor, direction="non_increasing"):
    """Clamp each obs to [lower_bound, upper_bound], enforce monotonic
    (non-increasing) order, and force the final element to terminal_anchor.
    Pure function: same input -> same output, no globals, no randomness."""
    out = []
    prev = upper_bound
    for v in observations:
        v = min(max(v, lower_bound), upper_bound)
        if direction == "non_increasing":
            v = min(v, prev)
        else:
            v = max(v, prev)
        out.append(v)
        prev = v
    if out:
        out[-1] = terminal_anchor
    return out


def robust_avg_stack(current_hand, level_hands, seat_stacks_fn=None):
    """Variance-reduced average stack at this blind level.
    Pure function of its inputs."""
    if seat_stacks_fn is None:
        seat_stacks_fn = _default_seat_stacks_chips

    stacks = []
    for h in level_hands:
        stacks.extend(seat_stacks_fn(h))

    if len(stacks) < 5:
        fallback = seat_stacks_fn(current_hand)
        return statistics.median(fallback) if fallback else 0

    med = statistics.median(stacks)
    if med <= 0:
        return statistics.mean(stacks) if stacks else 0

    # Trim outliers: keep within 0.33x to 3.0x of median
    kept = [s for s in stacks if 0.33 * med <= s <= 3.0 * med] or stacks

    # Winsorize at 10th/90th percentile
    kept_sorted = sorted(kept)
    n = len(kept_sorted)
    lo_idx = max(0, int(n * 0.10))
    hi_idx = min(n - 1, int(n * 0.90))
    lo, hi = kept_sorted[lo_idx], kept_sorted[hi_idx]
    clipped = [min(max(s, lo), hi) for s in kept]

    # Trimmed mean (trim 10%)
    clipped_sorted = sorted(clipped)
    trim_n = max(1, int(len(clipped_sorted) * 0.10))
    trimmed = clipped_sorted[trim_n:-trim_n] if trim_n < len(clipped_sorted) // 2 else clipped_sorted
    return statistics.mean(trimmed) if trimmed else statistics.mean(clipped)


def _default_seat_stacks_chips(h):
    """Extract seat stacks in chips from a hand dict."""
    # Try seat_stacks_chips first, then seat_stacks_bb_all * bb
    chips = h.get('seat_stacks_chips')
    if chips and isinstance(chips, (list, dict)):
        if isinstance(chips, dict):
            return [v for v in chips.values() if v and v > 0]
        return [v for v in chips if v and v > 0]

    # Fallback: convert BB stacks to chips
    bb_stacks = h.get('seat_stacks_bb_all', {})
    bb = h.get('bb_blind', 0) or 1
    if isinstance(bb_stacks, dict):
        return [v * bb for v in bb_stacks.values() if v and v > 0]
    return []


def sustained_short_handed(recent_hands_newest_first, ring_size):
    """True only if the table has been below ring_size for a sustained run."""
    threshold = max(12, 2 * ring_size)
    run = 0
    for h in recent_hands_newest_first:
        n = h.get('n_players')
        if n is None or balancing_or_sitout_artifact(h):
            continue
        if n < ring_size:
            run += 1
            if run >= threshold:
                return True
        else:
            run = 0
    return False


def balancing_or_sitout_artifact(h):
    """Conservative: only flag when a concrete parser signal exists."""
    return bool(
        h.get('seat_count_unreliable') or
        h.get('table_balancing_flag')
    )


# ============================================================
# STARTING STACK ESTIMATION
# ============================================================

_SNAP_STANDARDS = [5000, 10000, 15000, 20000, 25000, 30000, 50000]

def snap_to_standard(avg_stack):
    """Snap an observed average stack to the nearest standard starting stack."""
    if not avg_stack or avg_stack <= 0:
        return None
    return min(_SNAP_STANDARDS, key=lambda s: abs(s - avg_stack))


def resolve_via_structure(tournament_name, earliest_hand):
    """Try to resolve starting stack via gem_cev structure tables."""
    try:
        import gem_cev
        structs = gem_cev._load_structures()
        result = gem_cev._resolve_starting_chips(tournament_name, structs)
        if result and result > 0:
            return result
    except Exception:
        pass
    return None


# ============================================================
# PHASE THRESHOLDS
# ============================================================

def _late_reg_threshold(format_speed):
    """Level at which late registration closes (proxy)."""
    if format_speed == 'hyper':
        return 6
    elif format_speed == 'turbo':
        return 10
    else:
        return 14


def _detect_format_speed(name):
    """Detect tournament speed from name."""
    upper = (name or '').upper()
    if 'HYPER' in upper:
        return 'hyper'
    elif 'TURBO' in upper:
        return 'turbo'
    return 'standard'


def _payout_fraction(name):
    """Fraction of field that gets paid. Default 0.15 (15%)."""
    # Could be per-structure in future; for now, GGPoker standard
    return 0.15


# ============================================================
# ICM PRESSURE (continuous, asymmetric)
# ============================================================

def icm_pressure(money_state, frac, itm_frac, table_stage, players_left=None, field=None):
    """Continuous ICM pressure score 0.0-1.0."""
    p = 0.0
    if frac is not None:
        d = (frac - itm_frac) / max(itm_frac, 1e-6)
        if d >= 0:
            prox = max(0.0, 1.0 - min(d, 1.0))
        else:
            prox = max(0.0, 1.0 - min(abs(d) * 3.0, 1.0))
        p = max(p, prox)
    if money_state == "bubble_zone":
        p = max(p, 0.7)
    if money_state == "in_money":
        p = max(p, 0.10)
    if table_stage == "final_two_tables":
        p = max(p, 0.6)
    if table_stage == "final_table":
        p = max(p, 0.85)
    if table_stage == "hu":
        return 0.0
    if money_state == "in_money" and table_stage == "normal":
        p = min(p, 0.35)
    return round(min(p, 1.0), 3)


# ============================================================
# MAIN PHASE ESTIMATOR
# ============================================================

def estimate_tournament_phases_v2(hands, summaries=None):
    """Assign tournament phase fields to each hand using chip-fraction model.

    New fields per hand:
      reg_state, money_state, table_stage, icm_pressure,
      field_fraction_est, players_left_est, starting_stack_method,
      true_starting_stack_est, observed_entry_stack_est,
      phase_confidence, phase_confidence_score, phase_source,
      legacy_phase, tournament_phase (alias), old_phase (QA)
    """
    summaries = summaries or {}

    # Group by tournament
    tourney_hands = defaultdict(list)
    for h in hands:
        tid = h.get('tournament_id') or h.get('tournament', '')
        tourney_hands[tid].append(h)

    for tid, th in tourney_hands.items():
        # Sort chronologically
        th.sort(key=lambda h: h.get('id', ''))

        tname = th[0].get('tournament', '') if th else ''
        format_speed = _detect_format_speed(tname)
        ring_size = _modal_table_size(th)
        ft_size = ring_size + 1

        # Get summary if available
        summary = summaries.get(str(tid), {})
        field = summary.get('field') or summary.get('total_players')
        finish = summary.get('place') or summary.get('finish_place')

        # Starting stack estimation
        earliest = th[0] if th else None
        earliest_level_hands = [h for h in th if h.get('level', 99) <= (th[0].get('level', 1) if th else 1)]

        true_start = resolve_via_structure(tname, earliest) if earliest else None
        snap_start = None
        if earliest_level_hands:
            avg = robust_avg_stack(earliest, earliest_level_hands)
            snap_start = snap_to_standard(avg) if avg > 0 else None

        starting_stack = snap_start or true_start
        method = 'snap' if snap_start else ('resolver' if true_start else 'unknown')

        # Choose algorithm based on data availability
        if field and finish and starting_stack:
            # Algorithm A: summary known — chip smoother
            _phase_with_summary(th, field, finish, starting_stack, ring_size,
                                ft_size, format_speed, tname, method,
                                true_start, snap_start)
        elif starting_stack:
            # Algorithm B: summary absent — chips-only fraction
            _phase_chips_only(th, starting_stack, ring_size, ft_size,
                              format_speed, tname, method, true_start, snap_start)
        else:
            # Last resort: level fallback
            _phase_level_fallback(th, format_speed, tname, method,
                                  true_start, snap_start)


def _modal_table_size(hands):
    """Get the most common table size across a tournament's hands."""
    from collections import Counter
    sizes = Counter(h.get('table_size', 8) for h in hands)
    return sizes.most_common(1)[0][0] if sizes else 8


def _phase_with_summary(hands, field, finish, starting_stack, ring_size,
                         ft_size, format_speed, tname, method,
                         true_start, snap_start):
    """Algorithm A: summary known — chip share + monotonic smoothing."""
    # Build level-grouped hands for robust_avg_stack
    by_level = defaultdict(list)
    for h in hands:
        by_level[h.get('level', 0)].append(h)

    # Compute raw players_left estimate per hand
    players_obs = []
    for h in hands:
        level = h.get('level', 0)
        level_hands = by_level.get(level, [h])
        avg = robust_avg_stack(h, level_hands)
        if avg > 0:
            pl = field * starting_stack / avg
        else:
            pl = field
        players_obs.append(pl)

    # Monotonic smooth with terminal anchor
    players_left = monotonic_smooth(
        players_obs,
        lower_bound=max(finish, 1),
        upper_bound=field,
        terminal_anchor=max(finish, 1),
        direction="non_increasing"
    )

    itm_frac = _payout_fraction(tname)
    late_reg_level = _late_reg_threshold(format_speed)

    for i, h in enumerate(hands):
        pl = players_left[i]
        frac = pl / field if field > 0 else None
        _assign_phase_fields(
            h, frac=frac, players_left=round(pl),
            field=field, ring_size=ring_size, ft_size=ft_size,
            format_speed=format_speed, tname=tname, itm_frac=itm_frac,
            late_reg_level=late_reg_level, method=method,
            true_start=true_start, snap_start=snap_start,
            source='summary_chip_smoother', conf_base='high'
        )


def _phase_chips_only(hands, starting_stack, ring_size, ft_size,
                       format_speed, tname, method, true_start, snap_start):
    """Algorithm B: summary absent — field fraction from chips alone."""
    by_level = defaultdict(list)
    for h in hands:
        by_level[h.get('level', 0)].append(h)

    itm_frac = _payout_fraction(tname)
    late_reg_level = _late_reg_threshold(format_speed)

    for h in hands:
        level = h.get('level', 0)
        level_hands = by_level.get(level, [h])
        avg = robust_avg_stack(h, level_hands)
        frac = starting_stack / avg if avg > 0 else None

        _assign_phase_fields(
            h, frac=frac, players_left=None,
            field=None, ring_size=ring_size, ft_size=ft_size,
            format_speed=format_speed, tname=tname, itm_frac=itm_frac,
            late_reg_level=late_reg_level, method=method,
            true_start=true_start, snap_start=snap_start,
            source='chips_only_fraction', conf_base='medium'
        )


def _phase_level_fallback(hands, format_speed, tname, method,
                           true_start, snap_start):
    """Last resort: level-based phase estimation (the old algorithm)."""
    itm_frac = _payout_fraction(tname)
    late_reg_level = _late_reg_threshold(format_speed)

    if format_speed == 'hyper':
        bubble_start, bubble_end = 10, 16
    elif format_speed == 'turbo':
        bubble_start, bubble_end = 18, 26
    else:
        bubble_start, bubble_end = 22, 30

    for h in hands:
        level = h.get('level', 0)
        n_pl = h.get('n_players', 9)
        ts = h.get('table_size', 8)

        if level <= late_reg_level:
            reg = 'reg_open'; money = 'pre_money'; stage = 'normal'
        elif level <= bubble_start:
            reg = 'post_reg'; money = 'pre_money'; stage = 'normal'
        elif level <= bubble_end:
            reg = 'post_reg'; money = 'bubble_zone'; stage = 'normal'
        elif n_pl <= 2:
            reg = 'post_reg'; money = 'in_money'; stage = 'hu'
        elif n_pl < ts:
            reg = 'post_reg'; money = 'in_money'; stage = 'unknown_late_stage'
        else:
            reg = 'post_reg'; money = 'in_money'; stage = 'normal'

        # Derive legacy
        legacy = _derive_legacy(stage, money, reg)
        _icm = icm_pressure(money, None, itm_frac, stage)

        h['reg_state'] = reg
        h['money_state'] = money
        h['table_stage'] = stage
        h['icm_pressure'] = _icm
        h['field_fraction_est'] = None
        h['players_left_est'] = None
        h['starting_stack_method'] = method
        h['true_starting_stack_est'] = true_start
        h['observed_entry_stack_est'] = snap_start
        h['phase_confidence'] = 'low'
        h['phase_confidence_score'] = 0.2
        h['phase_source'] = 'level_fallback'
        h['legacy_phase'] = legacy
        h['tournament_phase'] = legacy


def _assign_phase_fields(h, frac, players_left, field, ring_size, ft_size,
                          format_speed, tname, itm_frac, late_reg_level,
                          method, true_start, snap_start, source, conf_base):
    """Assign all phase fields to a hand from the computed fraction."""
    level = h.get('level', 0)
    bubble_band = 0.05

    # reg_state
    if level <= late_reg_level:
        reg = 'reg_open'
    else:
        reg = 'post_reg'

    # money_state (field-independent via fraction)
    if frac is None:
        money = 'unknown'
    elif reg == 'reg_open':
        money = 'pre_money'
    elif frac > itm_frac + bubble_band:
        money = 'pre_money'
    elif frac > itm_frac:
        money = 'bubble_zone'
    else:
        money = 'in_money'

    # table_stage
    if players_left is not None and field is not None:
        if players_left <= 2:
            stage = 'hu'
        elif players_left <= ft_size:
            stage = 'final_table'
        elif players_left <= ft_size + ring_size:
            stage = 'final_two_tables'
        else:
            stage = 'normal'
    else:
        # No field — conservative
        stage = 'normal'

    # ICM pressure
    _icm = icm_pressure(money, frac, itm_frac, stage, players_left, field)

    # Legacy derivation
    legacy = _derive_legacy(stage, money, reg)

    # Confidence
    conf_rank = {'low': 0, 'medium': 1, 'high': 2}[conf_base]
    conf_score = {'low': 0.2, 'medium': 0.7, 'high': 1.0}[conf_base]
    if frac is None:
        conf_rank = 0; conf_score = min(conf_score, 0.2)
    if method == 'unknown':
        conf_rank = 0; conf_score = min(conf_score, 0.2)
    if reg == 'reg_open' and level > late_reg_level:
        conf_rank = min(conf_rank, 1); conf_score = min(conf_score, 0.7)

    conf_label = ['low', 'medium', 'high'][conf_rank]

    h['reg_state'] = reg
    h['money_state'] = money
    h['table_stage'] = stage
    h['icm_pressure'] = _icm
    h['field_fraction_est'] = round(frac, 4) if frac is not None else None
    h['players_left_est'] = round(players_left) if players_left is not None else None
    h['starting_stack_method'] = method
    h['true_starting_stack_est'] = true_start
    h['observed_entry_stack_est'] = snap_start
    h['phase_confidence'] = conf_label
    h['phase_confidence_score'] = round(conf_score, 3)
    h['phase_source'] = source
    h['legacy_phase'] = legacy
    h['tournament_phase'] = legacy


def _derive_legacy(table_stage, money_state, reg_state):
    """Derive legacy_phase label from the three axes."""
    if table_stage == 'hu':
        return 'ft_zone'  # legacy vocab uses ft_zone for HU too
    elif table_stage == 'final_table':
        return 'ft_zone'
    elif money_state == 'in_money':
        return 'post_bubble'
    elif money_state == 'bubble_zone':
        return 'bubble_zone'
    elif reg_state == 'reg_open':
        return 'late_reg'
    else:
        return 'post_reg'
