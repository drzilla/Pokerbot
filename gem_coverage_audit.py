"""
gem_coverage_audit.py — P0 measurement-only detector coverage audit
====================================================================
Classifies EVERY hero decision point and reports which detector families
were eligible / evaluated / fired, and WHY uncovered points are uncovered.

Contract (P0, external review):
  - Measurement only: no verdicts, no cards, no report changes. With the
    flag off, report output is FUNCTIONALLY IDENTICAL (this module is never
    imported on the default path).
  - Registry/adapter layer: existing detectors are described here via
    metadata — P0 does NOT refactor detector modules.
  - net_bb is PRIORITIZATION EVIDENCE, NOT CAUSAL PROOF: multiple decision
    points in one hand each carry the full hand result. Both raw-sum and
    median metrics are reported to limit outlier distortion.
  - `fired` counts are mapped only where existing outputs expose hand ids;
    otherwise reported as None ("—") rather than guessed.

Invocation: `--coverage-audit` on the analyzer command line sets
GEM_COVERAGE_AUDIT=1; gem_report_data calls run_coverage_audit() at the end
of report-data assembly (read-only) and writes JSON + a stderr table.
"""
import json
import os
import sys
from collections import defaultdict

UNCOVERED_REASONS = (
    'no_detector_family', 'detector_exists_but_missing_chart',
    'detector_exists_but_context_out_of_scope', 'parse_missing_required_field',
    'quarantine_bound_chart', 'intentionally_excluded_by_governance',
    'disabled_by_flag', 'unknown')


# --- Detector registry (adapter layer — metadata only, no detector edits) ---
# trigger(dp) -> bool : does this decision point match the documented shape?
# chart_present(ranges, dp) -> bool|None : None = no chart required
# fired_ids(stats, rd) -> set|None : hand ids the detector flagged (None =
#   existing output does not expose ids; fired column shows "—").

def _ids_from_deviations(stats, types):
    out = set()
    # v8.12.2 FIX: analyzer stores s['preflop_deviations'] (same
    # wrong-key bug class as the pko_research one caught in QA).
    for d in (stats or {}).get('preflop_deviations', []) or []:
        if d.get('type') in types:
            hid = d.get('id') or d.get('hand_id')
            if hid:
                out.add(hid)
    return out


DETECTOR_REGISTRY = [
    {'id': 'open_chart', 'family': 'preflop_chart', 'tier': 'verdict',
     'street': 'preflop', 'requires_chart': True, 'chart_families': ['OPEN_'],
     'trigger': lambda dp: dp['street'] == 'preflop'
        and dp['facing'] == 'unopened' and dp['pos'] not in ('SB', 'BB'),
     'chart_present': lambda r, dp: any(k.startswith('OPEN_') for k in r),
     'fired_ids': lambda s, rd: _ids_from_deviations(
         s, {'Wide Open', 'Missed Open', 'Missed Steal'})},
    {'id': 'bb_defend', 'family': 'preflop_chart', 'tier': 'verdict',
     'street': 'preflop', 'requires_chart': True,
     'chart_families': ['BB_DEF_vs'],
     'trigger': lambda dp: dp['street'] == 'preflop'
        and dp['pos'] == 'BB' and dp['facing'] == 'vs_open',
     'chart_present': lambda r, dp: any(k.startswith('BB_DEF_vs') for k in r),
     'fired_ids': lambda s, rd: _ids_from_deviations(
         s, {'Missed BB Defend', 'Wide BB Defend'})},
    {'id': 'sb_defend', 'family': 'preflop_chart', 'tier': 'verdict',
     'street': 'preflop', 'requires_chart': True, 'chart_families': ['SBD2_'],
     'quarantined_families': ['SBD_'],
     'trigger': lambda dp: dp['street'] == 'preflop'
        and dp['pos'] == 'SB' and dp['facing'] == 'vs_open',
     'chart_present': lambda r, dp: any(k.startswith('SBD2_') for k in r),
     'fired_ids': lambda s, rd: set()},
    {'id': 'push_fold', 'family': 'preflop_chart', 'tier': 'verdict',
     'street': 'preflop', 'requires_chart': True,
     'chart_families': ['PUSH_', 'JAM_'],
     'trigger': lambda dp: dp['street'] == 'preflop'
        and dp['facing'] == 'unopened' and (dp['eff_bb'] or 99) <= 15,
     'chart_present': lambda r, dp: any(k.startswith(('PUSH_', 'JAM_'))
                                        for k in r),
     'fired_ids': lambda s, rd: _ids_from_deviations(
         s, {'Missed Push', 'Missed Rejam'})},
    {'id': 'call_jam', 'family': 'preflop_chart', 'tier': 'verdict',
     'street': 'preflop', 'requires_chart': True,
     'chart_families': ['CALLJAM_'],
     'trigger': lambda dp: dp['street'] == 'preflop'
        and dp['facing'] == 'vs_jam',
     'chart_present': lambda r, dp: any(k.startswith('CALLJAM_') for k in r),
     'fired_ids': lambda s, rd: _ids_from_deviations(
         s, {'Wide CVJ (Call Villain Jam)', 'Wide Iso-Jam',
             'Wide Call-Rejam', 'Missed Call-Rejam'})},
    {'id': 'cold_call_width', 'family': 'preflop_chart', 'tier': 'verdict',
     'street': 'preflop', 'requires_chart': True, 'chart_families': ['CC_'],
     'trigger': lambda dp: dp['street'] == 'preflop'
        and dp['facing'] == 'vs_open'
        and dp['pos'] in ('UTG', 'UTG+1', 'MP', 'LJ', 'HJ', 'CO', 'BTN'),
     'chart_present': lambda r, dp: any(k.startswith('CC_') for k in r),
     'fired_ids': lambda s, rd: _ids_from_deviations(s, {'Wide Cold-Call'})},
    {'id': 'bvb', 'family': 'preflop_chart', 'tier': 'verdict',
     'street': 'preflop', 'requires_chart': True, 'chart_families': ['BVB_'],
     'trigger': lambda dp: dp['street'] == 'preflop'
        and dp['pos'] in ('SB', 'BB') and dp['facing'] in ('unopened',),
     'chart_present': lambda r, dp: any(k.startswith('BVB_') for k in r),
     'fired_ids': lambda s, rd: _ids_from_deviations(
         s, {'Missed BvB Open', 'Missed BvB Defend'})},
    {'id': 'iso_vs_limp', 'family': 'preflop_chart', 'tier': 'verdict',
     'street': 'preflop', 'requires_chart': True, 'chart_families': ['ISO_'],
     'trigger': lambda dp: dp['street'] == 'preflop'
        and dp['facing'] == 'unopened',
     'chart_present': lambda r, dp: any(k.startswith('ISO_') for k in r),
     'fired_ids': lambda s, rd: _ids_from_deviations(s, {'Missed Iso vs Limp'})},
    {'id': 'three_bet_response', 'family': 'preflop_chart', 'tier': 'verdict',
     'street': 'preflop', 'requires_chart': True, 'chart_families': ['3BF_'],
     'trigger': lambda dp: dp['street'] == 'preflop'
        and dp['facing'] == 'vs_3bet',
     'chart_present': lambda r, dp: any(k.startswith(('3BF_', 'F3B_'))
                                        for k in r),
     'fired_ids': lambda s, rd: _ids_from_deviations(
         s, {'Missed 3-Bet', 'Missed 3-Bet Defense'})},
    {'id': 'pko_research', 'family': 'pko_aggregate', 'tier': 'review',
     'street': 'preflop', 'requires_chart': False, 'chart_families': [],
     'trigger': lambda dp: dp['street'] == 'preflop' and dp['pos'] == 'BB'
        and dp['facing'] == 'vs_open' and dp['is_bounty'],
     'chart_present': lambda r, dp: None,
     'fired_ids': lambda s, rd: {
         hid for hid, c in ((rd.get('pko_research') or {})
                            .get('by_hand', {}) or {}).items()
         if c.get('enabled') and c.get('classification') in
         ('Review', 'Missed', 'Too wide')}},
    {'id': 'postflop_aggression', 'family': 'postflop_gates',
     'tier': 'review', 'street': 'postflop', 'requires_chart': False,
     'chart_families': [],
     'trigger': lambda dp: dp['street'] in ('flop', 'turn', 'river'),
     'chart_present': lambda r, dp: None,
     'fired_ids': lambda s, rd: None},
    {'id': 'large_loss_audit', 'family': 'result_audit', 'tier': 'review',
     'street': 'any', 'requires_chart': False, 'chart_families': [],
     'trigger': lambda dp: abs(dp['net_bb'] or 0) > 25,
     'chart_present': lambda r, dp: None,
     'fired_ids': lambda s, rd: None},
]


def extract_decision_points(hands):
    """Every hero action opportunity, normalized. One row per hero action."""
    points = []
    for h in hands or []:
        hero = h.get('hero', '')
        hid = h.get('id', '')
        if not hid:
            continue
        fmt = (h.get('format') or '').upper()
        net = h.get('net_bb') or 0
        eff = h.get('eff_stack_bb_at_decision') or h.get('eff_stack_bb') or \
            h.get('stack_bb') or 0
        n_raises = 0
        jam_seen = False
        idx = 0
        missing = not bool(h.get('action_ledger'))
        for a in (h.get('action_ledger') or []):
            act = a.get('action', '')
            if act == 'posts':
                continue
            street = a.get('street', '')
            is_hero = a.get('player') == hero
            if not is_hero:
                if act in ('raises', 'bets'):
                    n_raises += 1
                    if a.get('is_all_in'):
                        jam_seen = True
                continue
            if street == 'preflop':
                facing = ('vs_jam' if jam_seen else
                          'unopened' if n_raises == 0 else
                          'vs_open' if n_raises == 1 else 'vs_3bet')
            else:
                facing = 'postflop'
            points.append({
                'hand_id': hid, 'street': street, 'action_index': idx,
                'pos': h.get('position', '?'), 'facing': facing,
                'eff_bb': eff, 'net_bb': net, 'is_bounty':
                    fmt in ('BOUNTY', 'PKO', 'MYSTERY_BOUNTY'),
                'hero_action': act,
                'n_players': h.get('n_players', 0),
                'phase': h.get('tournament_phase', ''),
                'parse_missing': missing,
            })
            idx += 1
            if act in ('raises', 'bets'):
                n_raises += 1
        if missing:
            points.append({
                'hand_id': hid, 'street': 'unknown', 'action_index': 0,
                'pos': h.get('position', '?'), 'facing': 'unknown',
                'eff_bb': eff, 'net_bb': net, 'is_bounty': False,
                'hero_action': 'unknown', 'n_players': 0, 'phase': '',
                'parse_missing': True})
    return points


def run_coverage_audit(hands, stats, rd, out_dir=None):
    """Read-only audit. Writes JSON + stderr table; returns the summary."""
    try:
        from gem_ranges import load_ranges
        ranges = load_ranges()
    except Exception:
        ranges = {}
    fired_cache = {}
    for det in DETECTOR_REGISTRY:
        try:
            fired_cache[det['id']] = det['fired_ids'](stats, rd)
        except Exception:
            fired_cache[det['id']] = None

    points = extract_decision_points(hands)
    groups = defaultdict(lambda: {
        'count': 0, 'net_bb_sum': 0.0, 'abs_losses': [],
        'eligible': 0, 'evaluated': 0, 'fired': 0, 'fired_known': False,
        'reasons': defaultdict(int), 'examples': []})

    for dp in points:
        key = (dp['street'], dp['pos'], dp['facing'])
        g = groups[key]
        g['count'] += 1
        g['net_bb_sum'] += dp['net_bb'] or 0
        if (dp['net_bb'] or 0) < 0:
            g['abs_losses'].append(abs(dp['net_bb']))
        if len(g['examples']) < 8:
            g['examples'].append(dp['hand_id'])

        eligible_here, reason = 0, None
        if dp.get('parse_missing'):
            reason = 'parse_missing_required_field'
        for det in DETECTOR_REGISTRY:
            try:
                if not det['trigger'](dp):
                    continue
            except Exception:
                continue
            chart_ok = True
            if det.get('requires_chart'):
                present = det['chart_present'](ranges, dp)
                chart_ok = bool(present)
                if not chart_ok and reason is None:
                    reason = ('quarantine_bound_chart'
                              if det.get('quarantined_families')
                              else 'detector_exists_but_missing_chart')
            if chart_ok:
                eligible_here += 1
                g['evaluated'] += 1
                fids = fired_cache.get(det['id'])
                if fids is not None:
                    g['fired_known'] = True
                    if dp['hand_id'] in fids:
                        g['fired'] += 1
        g['eligible'] += eligible_here
        if eligible_here == 0:
            g['reasons'][reason or 'no_detector_family'] += 1

    rows = []
    for (street, pos, facing), g in groups.items():
        losses = sorted(g['abs_losses'])
        med = losses[len(losses) // 2] if losses else 0.0
        top_reason = (max(g['reasons'].items(), key=lambda x: x[1])[0]
                      if g['reasons'] else '')
        rows.append({
            'decision_type': f'{street}/{pos}/{facing}',
            'street': street, 'position': pos, 'action_faced': facing,
            'count': g['count'],
            'net_bb': round(g['net_bb_sum'], 1),
            'avg_bb': round(g['net_bb_sum'] / g['count'], 2) if g['count'] else 0,
            'median_abs_bb_loss': round(med, 2),
            'eligible_detector_count': g['eligible'],
            'evaluated_detector_count': g['evaluated'],
            'fired_detector_count': (g['fired'] if g['fired_known'] else None),
            'uncovered_points': sum(g['reasons'].values()),
            'top_uncovered_reason': top_reason,
            'priority_score': round(
                sum(g['reasons'].values()) * abs(g['net_bb_sum']), 1),
            'priority_score_robust': round(
                sum(g['reasons'].values()) * med, 1),
            'example_hand_ids': g['examples'],
        })
    rows.sort(key=lambda r: -r['priority_score'])

    summary = {
        'caveat': ('net_bb is prioritization evidence, NOT causal proof: '
                   'multiple decision points in one hand each inherit the '
                   'full hand result. Use median_abs_bb_loss to limit '
                   'outlier distortion. These metrics rank review priority; '
                   'they do not prove leak size.'),
        'n_hands': len(hands or []),
        'n_decision_points': len(points),
        'rows': rows,
    }
    try:
        out_dir = out_dir or '.'
        import datetime
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        out_path = os.path.join(out_dir, f'coverage_audit_{ts}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=1, ensure_ascii=False)
        summary['json_path'] = out_path
    except Exception as e:
        summary['json_path'] = f'WRITE FAILED: {e}'

    print('\n=== COVERAGE AUDIT (P0, measurement only) ===', file=sys.stderr)
    print(summary['caveat'], file=sys.stderr)
    print(f"hands={summary['n_hands']} decision_points="
          f"{summary['n_decision_points']} json={summary.get('json_path')}",
          file=sys.stderr)
    hdr = (f"{'decision_type':38s} {'cnt':>4s} {'netBB':>8s} {'medL':>6s} "
           f"{'elig':>4s} {'eval':>4s} {'fired':>5s} {'uncov':>5s} "
           f"top_uncovered_reason")
    print(hdr, file=sys.stderr)
    for r in rows[:25]:
        fired = '—' if r['fired_detector_count'] is None else \
            str(r['fired_detector_count'])
        print(f"{r['decision_type']:38s} {r['count']:>4d} "
              f"{r['net_bb']:>8.1f} {r['median_abs_bb_loss']:>6.1f} "
              f"{r['eligible_detector_count']:>4d} "
              f"{r['evaluated_detector_count']:>4d} {fired:>5s} "
              f"{r['uncovered_points']:>5d} {r['top_uncovered_reason']}",
              file=sys.stderr)
    return summary
