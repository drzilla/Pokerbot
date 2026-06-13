#!/usr/bin/env python3
"""
gem_drift_monitor.py — v0.1

Reads solver_history.csv, compares heuristic EV vs solver EV per
mistake type, flags types where recalibration is warranted.

Output: heuristic_calibration.md

TRIGGER THRESHOLDS (tunable):
  - |mean_delta| > 0.5 BB
  - n >= 10 samples
  - Excludes M14-indifferent rows (signal contaminated near zero)
  - Excludes 🔴 LOW confidence rows (range assumption too weak)

ACTION CODES:
  🔴 RECALIBRATE: strong, persistent delta
  🟡 WATCH: directional signal but n smaller or delta smaller
  ⏳ MONITORING: n<10, too early to call
  ✅ ALIGNED: heuristic and solver agree within tolerance
"""
import os, json, statistics
from collections import defaultdict
from datetime import datetime, timezone

MIN_N_FOR_ACTION = 10
DELTA_THRESHOLD_RECALIBRATE = 1.5   # BB — strong signal
DELTA_THRESHOLD_WATCH       = 0.5   # BB — directional signal


def aggregate(rows):
    """
    Group rows by mistake_type, compute summary stats.
    Returns list of dicts, sorted by |delta| descending.
    """
    # Filter: exclude M14-indifferent (signal near zero) and LOW confidence
    valid = [r for r in rows
             if not r.get('within_m14_band')
             and '🔴' not in (r.get('confidence') or '')
             and r.get('mistake_type')]

    groups = defaultdict(list)
    for r in valid:
        groups[r['mistake_type']].append(r)

    results = []
    for mtype, rs in groups.items():
        heur_evs   = [r['heuristic_ev_bb'] for r in rs]
        solver_evs = [r['solver_ev_bb']    for r in rs]
        deltas     = [r['delta_bb']        for r in rs]
        n = len(rs)
        mean_heur   = statistics.mean(heur_evs)
        mean_solver = statistics.mean(solver_evs)
        mean_delta  = statistics.mean(deltas)
        stdev_delta = statistics.stdev(deltas) if n > 1 else 0.0

        # Action classification
        if n < MIN_N_FOR_ACTION:
            action = '⏳ MONITORING'
            reason = f'n={n}<{MIN_N_FOR_ACTION}'
        elif abs(mean_delta) >= DELTA_THRESHOLD_RECALIBRATE:
            direction = 'softer' if mean_delta > 0 else 'harsher'
            action = '🔴 RECALIBRATE'
            reason = f'heuristic too {direction} by {abs(mean_delta):.1f}BB'
        elif abs(mean_delta) >= DELTA_THRESHOLD_WATCH:
            direction = 'softer' if mean_delta > 0 else 'harsher'
            action = '🟡 WATCH'
            reason = f'trending {direction} ({abs(mean_delta):.1f}BB)'
        else:
            action = '✅ ALIGNED'
            reason = f'|delta|<{DELTA_THRESHOLD_WATCH}BB'

        results.append({
            'mistake_type': mtype,
            'n': n,
            'mean_heuristic_ev': round(mean_heur, 2),
            'mean_solver_ev': round(mean_solver, 2),
            'mean_delta': round(mean_delta, 2),
            'stdev_delta': round(stdev_delta, 2),
            'action': action,
            'reason': reason,
        })

    return sorted(results, key=lambda r: -abs(r['mean_delta']))


def render_markdown(rows_all, rows_excluded, agg, out_path):
    """Write the calibration report."""
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    sessions = sorted(set(r.get('session_tag', '') for r in rows_all))

    lines = []
    w = lines.append
    w('# Solver ↔ Heuristic Calibration')
    w('')
    w(f'Generated: {ts}')
    w(f'Total solver runs: {len(rows_all)}  '
      f'(excluded from aggregation: {len(rows_excluded)} — M14-indifferent or 🔴 LOW confidence)')
    w(f'Sessions covered: {len(sessions)} ({", ".join(sessions[-5:])}{" ..." if len(sessions)>5 else ""})')
    w('')
    w('## Thresholds')
    w(f'- Minimum n for action: **{MIN_N_FOR_ACTION}**')
    w(f'- 🔴 RECALIBRATE when |mean delta| ≥ **{DELTA_THRESHOLD_RECALIBRATE} BB**')
    w(f'- 🟡 WATCH when |mean delta| ≥ **{DELTA_THRESHOLD_WATCH} BB**')
    w('- Deltas interpreted as: `solver_ev - heuristic_ev`')
    w('  - positive delta → heuristic too soft (solver says it costs less than we thought)')
    w('  - negative delta → heuristic too harsh (solver says it costs more than we thought)')
    w('')

    if not agg:
        w('## No aggregatable data yet')
        w('')
        w('Needs solver runs on confirmed mistakes. After ~3–5 real sessions the table below will populate.')
    else:
        actionable  = [r for r in agg if r['action'] in ('🔴 RECALIBRATE', '🟡 WATCH')]
        monitoring  = [r for r in agg if r['action'] == '⏳ MONITORING']
        aligned     = [r for r in agg if r['action'] == '✅ ALIGNED']

        if actionable:
            w('## Actionable')
            w('')
            w('| Type | N | Heur EV | Solver EV | Δ | σ(Δ) | Action | Reason |')
            w('|------|---|---------|-----------|---|------|--------|--------|')
            for r in actionable:
                w(f"| {r['mistake_type']} | {r['n']} | "
                  f"{r['mean_heuristic_ev']:+.2f} | {r['mean_solver_ev']:+.2f} | "
                  f"{r['mean_delta']:+.2f} | {r['stdev_delta']:.2f} | "
                  f"{r['action']} | {r['reason']} |")
            w('')

        if aligned:
            w('## Aligned (no action)')
            w('')
            w('| Type | N | Heur EV | Solver EV | Δ |')
            w('|------|---|---------|-----------|---|')
            for r in aligned:
                w(f"| {r['mistake_type']} | {r['n']} | "
                  f"{r['mean_heuristic_ev']:+.2f} | {r['mean_solver_ev']:+.2f} | "
                  f"{r['mean_delta']:+.2f} |")
            w('')

        if monitoring:
            w('## Monitoring (n below threshold)')
            w('')
            w('| Type | N | Heur EV | Solver EV | Δ |')
            w('|------|---|---------|-----------|---|')
            for r in monitoring:
                w(f"| {r['mistake_type']} | {r['n']} | "
                  f"{r['mean_heuristic_ev']:+.2f} | {r['mean_solver_ev']:+.2f} | "
                  f"{r['mean_delta']:+.2f} |")
            w('')

    w('## Recalibration protocol')
    w('')
    w('When a type hits 🔴 RECALIBRATE:')
    w('1. Review 2-3 audit bundles of that type (links in history CSV `audit_path` column)')
    w('2. Check range assumptions in `range_audit.json` — is the issue the solver or the range?')
    w('3. If range is wrong, fix `gem_ranges.py` narrowing table; solver output becomes correct automatically')
    w('4. If range is right and solver consistently differs from heuristic, update the heuristic constant in `gem_report_data.py` section 10')
    w('5. Heuristic changes are a coaching discussion, not an automatic patch — flag to Dave/Amit first')
    w('')
    w('*This report is advisory — not a trigger for automatic heuristic changes.*')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def run(history_path=None, out_path='/home/claude/heuristic_calibration.md'):
    """Main entry. Reads history, aggregates, writes markdown.

    If `history_path` is supplied explicitly, that path is respected — a
    missing file is treated as empty (NO fallback). Falling back to a
    global default when the caller named a path would silently swap data
    sources, which broke test isolation in v7.36 (test_solver.py
    `handles missing history`) and is a data-leak hazard in production.

    Only when `history_path is None` (default-config call) do we walk the
    fallback chain: /mnt/project/solver_history.csv then /home/claude/...
    """
    from gem_solver_history import read_history
    if history_path is not None:
        # Caller specified — respect it. Missing file == empty.
        path = history_path
        rows_all = read_history(path) if os.path.exists(path) else []
    else:
        path = '/mnt/project/solver_history.csv'
        if not os.path.exists(path):
            path = '/home/claude/solver_history.csv'
        rows_all = read_history(path) if os.path.exists(path) else []
    if not rows_all:
        # Still write an empty report so the pipeline has a consistent output
        render_markdown([], [], [], out_path)
        return {'total_rows': 0, 'excluded': 0, 'types_analyzed': 0, 'out_path': out_path}

    # Track what got excluded for transparency
    excluded = [r for r in rows_all
                if r.get('within_m14_band') or '🔴' in (r.get('confidence') or '')]
    agg = aggregate(rows_all)
    render_markdown(rows_all, excluded, agg, out_path)
    return {
        'total_rows': len(rows_all),
        'excluded': len(excluded),
        'types_analyzed': len(agg),
        'actionable': sum(1 for r in agg if r['action'] in ('🔴 RECALIBRATE', '🟡 WATCH')),
        'out_path': out_path,
    }


if __name__ == '__main__':
    import sys
    result = run()
    print(json.dumps(result, indent=2))


# =====================================================================
# N5 — CBET SIZING TIER × TURN BARREL FREQUENCY CORRELATION TRACKER
# =====================================================================
# Amit hypothesis (2026-05-12): the freq at which villain barrels the
# turn correlates with Hero's flop cbet sizing. Smaller flop cbets →
# higher villain turn-barrel %. If validated, Hero can hero-fold marginal
# made hands to flop cbets that signal weakness via small size.
#
# This is INFORMATIONAL only in v7.48. No detector fires until the
# validation gate passes (|Δ| >= 10pp over n>=200 cbets per sizing tier).
#
# Sizing tiers (vs pot):
#   small  : 25-40% pot
#   medium : 41-65% pot
#   large  : 66-100% pot
#   over   : >100% pot
#
# Outcome bucket (villain action on turn AFTER calling flop cbet):
#   bet  : villain bets out OR check-raises after Hero's turn check
#   check: villain checks (passive)
#   raise: villain raises Hero's turn cbet
# =====================================================================

CBET_SIZING_TIERS = ('small', 'medium', 'large', 'over')
N5_VALIDATION_GATE_DELTA_PP = 10
N5_VALIDATION_GATE_MIN_N = 200


def _classify_cbet_sizing(bet_bb, pot_bb):
    """Bucket a flop cbet into sizing tier (vs pot before bet)."""
    if not pot_bb or pot_bb <= 0:
        return None
    pct = (bet_bb / pot_bb) * 100
    if pct < 25:
        return None  # tiny stab — not a "real" cbet
    if pct <= 40:
        return 'small'
    if pct <= 65:
        return 'medium'
    if pct <= 100:
        return 'large'
    return 'over'


def aggregate_cbet_turn_correlation(hands):
    """
    N5 informational tracker.

    Input: parsed hands list (from gem_parser).
    Output: dict {tier: {n, villain_bet_pct, villain_check_pct, villain_raise_pct}}
            + validation_gate_passed (bool) + delta_pp between small/large.

    NOTE: this is a STUB. Requires that hand records carry:
      - hero_flop_cbet_bb, hero_flop_cbet_pot_bb (to classify tier)
      - villain_turn_action ('bet', 'check', 'raise', 'fold')
    These fields may not yet exist in the parser — the tracker degrades
    gracefully and emits 'insufficient data' until they do.
    """
    buckets = {tier: {'n': 0, 'villain_bet': 0,
                      'villain_check': 0, 'villain_raise': 0}
               for tier in CBET_SIZING_TIERS}
    skipped = 0
    for h in hands:
        bet_bb = h.get('hero_flop_cbet_bb')
        pot_bb = h.get('hero_flop_cbet_pot_bb')
        turn_action = h.get('villain_turn_action')
        if not bet_bb or not pot_bb or not turn_action:
            skipped += 1
            continue
        tier = _classify_cbet_sizing(bet_bb, pot_bb)
        if not tier:
            continue
        buckets[tier]['n'] += 1
        if turn_action == 'bet':
            buckets[tier]['villain_bet'] += 1
        elif turn_action == 'check':
            buckets[tier]['villain_check'] += 1
        elif turn_action == 'raise':
            buckets[tier]['villain_raise'] += 1

    # Compute percentages and validation gate
    summary = {}
    for tier in CBET_SIZING_TIERS:
        b = buckets[tier]
        n = b['n']
        summary[tier] = {
            'n': n,
            'villain_bet_pct': (100.0 * b['villain_bet'] / n) if n else 0.0,
            'villain_check_pct': (100.0 * b['villain_check'] / n) if n else 0.0,
            'villain_raise_pct': (100.0 * b['villain_raise'] / n) if n else 0.0,
        }

    # Validation gate: compare small vs large tiers
    small_n = summary['small']['n']
    large_n = summary['large']['n']
    small_bet = summary['small']['villain_bet_pct']
    large_bet = summary['large']['villain_bet_pct']
    delta_pp = small_bet - large_bet
    gate_passed = (
        small_n >= N5_VALIDATION_GATE_MIN_N and
        large_n >= N5_VALIDATION_GATE_MIN_N and
        abs(delta_pp) >= N5_VALIDATION_GATE_DELTA_PP
    )

    return {
        'tiers': summary,
        'delta_small_vs_large_pp': round(delta_pp, 1),
        'validation_gate_passed': gate_passed,
        'min_n_required': N5_VALIDATION_GATE_MIN_N,
        'min_delta_required_pp': N5_VALIDATION_GATE_DELTA_PP,
        'skipped_missing_data': skipped,
        'status': ('VALIDATED — promote to detector' if gate_passed
                   else f'INFORMATIONAL — need n>={N5_VALIDATION_GATE_MIN_N} per tier '
                        f'+ |Δ|>={N5_VALIDATION_GATE_DELTA_PP}pp to promote'),
    }
