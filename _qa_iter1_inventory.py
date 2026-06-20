#!/usr/bin/env python3
"""v8.17.1 Iteration 1 (REV3) — exact-report inventories + preserve-list checks.

Builds the inventories the corrective program requires from the REGENERATED
June-16 artifacts and asserts the required zero-counts:

  future-contaminated bounty contexts = 0
  aggregate/reason contradictions     = 0
  non-all-in eligible bounty opponents= 0
  unreconciled pot totals             = 0
  unjustified unavailable call prices  = 0

Usage:
  python _qa_iter1_inventory.py <hands_json> <worklist_json> <report_html> <out_json>
"""
import io
import json
import re
import sys

sys.path.insert(0, '.')
import gem_decision_snapshot as ds
import _qa_parity as qp
from gem_analyst_worklist import _reviewed_action_index

_ALLIN = ('call_vs_jam', 'call_off', 'open_shove', 'rejam_over_live_raise',
          'overjam_with_side_pot')


def _load(p):
    with io.open(p, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _bare(s):
    return str(s)[-8:]


def main():
    hands = _load(sys.argv[1])
    worklist = _load(sys.argv[2])
    html = io.open(sys.argv[3], 'r', encoding='utf-8').read()
    out_path = sys.argv[4]

    by_id = {}
    for h in hands:
        for key in (h.get('id'), h.get('tournament_hand_id'), h.get('hand_id')):
            if key:
                by_id[str(key)] = h
                by_id[_bare(key)] = h

    inv = {
        'decision_time_eligible_bounties': [],
        'aggregate_reason_combinations': {},
        'pots_with_dead_money': [],
        'main_side_layer_reconciliations': [],
        'call_vs_jam_and_call_off_prices': [],
    }
    viol = {
        'future_contaminated_bounty_contexts': [],
        'aggregate_reason_contradictions': [],
        'non_allin_eligible_bounty_opponents': [],
        'unreconciled_pot_totals': [],
        'unjustified_unavailable_call_prices': [],
    }

    # iterate every hand once (decision = Hero's last action) for model inventories
    for h in hands:
        hid = str(h.get('tournament_hand_id') or h.get('id') or h.get('hand_id') or '')
        if not hid:
            continue
        ridx = ds.resolve_decision_ref(h)['hero_action_index']
        kind = ds.hero_action_kind(h, ridx)
        dbc = ds.build_decision_bounty_context(h, ridx)
        rc = ds.build_realized_contest(h, ridx)

        # (1) decision-time eligible bounty opponents
        elig = dbc.get('eligible_bounties_by_opponent') or {}
        if elig:
            inv['decision_time_eligible_bounties'].append(
                {'hand': hid, 'kind': kind, 'eligible': elig,
                 'aggregate': dbc['aggregate'], 'reason': dbc['reason']})
            # every eligible opp must be all-in at/before the reviewed action
            for p in elig:
                if not qp._opp_all_in_at_or_before(h, p, ridx):
                    viol['non_allin_eligible_bounty_opponents'].append({'hand': hid, 'who': p})

        # (2) aggregate/reason combinations + consistency
        if dbc.get('is_bounty'):
            combo = '%s / %s' % (dbc['aggregate'], dbc['reason'])
            inv['aggregate_reason_combinations'][combo] = \
                inv['aggregate_reason_combinations'].get(combo, 0) + 1
            if not qp.aggregate_reason_consistent(dbc['aggregate'], dbc['reason']):
                viol['aggregate_reason_contradictions'].append(
                    {'hand': hid, 'aggregate': dbc['aggregate'], 'reason': dbc['reason']})
            # prefix invariance — a later opponent/Hero all-in cannot change this ctx
            pv = qp.prefix_invariance_violations(
                h, ridx, qp._future_contamination_actions(dbc.get('street', 'preflop')))
            if pv:
                viol['future_contaminated_bounty_contexts'].append({'hand': hid, 'fields': pv})

        # (3) pots with dead money + (4) layer reconciliation
        prv = qp.pot_reconciliation_violation(rc)
        if prv:
            viol['unreconciled_pot_totals'].append({'hand': hid, 'why': prv})
        if (rc.get('dead_money_bb') or 0) > 0.001:
            inv['pots_with_dead_money'].append(
                {'hand': hid, 'total_committed_pot_bb': rc['total_committed_pot_bb'],
                 'dead_money_bb': rc['dead_money_bb'], 'dead_money_by_player': rc['dead_money_by_player'],
                 'reconciles': prv is None})
        if len(rc.get('pot_layers') or []) > 1:
            inv['main_side_layer_reconciliations'].append(
                {'hand': hid, 'total': rc['total_committed_pot_bb'],
                 'layer_sum': round(sum(l['total_layer_bb'] for l in rc['pot_layers']), 2),
                 'kinds': [l['kind'] for l in rc['pot_layers']], 'reconciles': prv is None})

        # (5) call_vs_jam / call_off prices + depths
        if kind in ('call_vs_jam', 'call_off'):
            snap = ds.build_decision_snapshot(h, ridx)
            inv['call_vs_jam_and_call_off_prices'].append(
                {'hand': hid, 'kind': kind,
                 'callable_amount_bb': snap.get('callable_amount_bb'),
                 'to_call_bb': snap.get('to_call_bb'),
                 'decision_depth_bb': snap.get('effective_stack_at_decision_bb'),
                 'price_source': 'canonical_action_ledger'})

    # unjustified unavailable call prices — from the worklist decision nodes
    items = worklist.get('items') or {}
    if isinstance(items, dict):
        items = list(items.values())
    for it in items:
        hid = str(it.get('hand_id') or '')
        h = by_id.get(hid) or by_id.get(_bare(hid))
        if h is None:
            continue
        k = it.get('decision_kind') or it.get('bucket')
        ridx = _reviewed_action_index(h, k)
        if ridx is None:
            continue
        snap = ds.build_decision_snapshot(h, ridx)
        dn = it.get('decision_node') or {}
        if (snap.get('hero_action_kind') in ('call_vs_jam', 'call_off')
                and (snap.get('callable_amount_bb') or 0) > 0
                and (dn.get('price_unavailable') or dn.get('price_source') == 'unavailable')):
            viol['unjustified_unavailable_call_prices'].append(
                {'hand': hid, 'snapshot_callable': snap.get('callable_amount_bb')})

    # ---- preserve-list named fixtures ----
    def _depth(hid):
        h = by_id.get(hid) or by_id.get(_bare(hid))
        if not h:
            return None
        s = ds.build_decision_snapshot(h)
        return {'kind': s['hero_action_kind'], 'street': s['street'],
                'callable_bb': s.get('callable_amount_bb'),
                'to_call_bb': s.get('to_call_bb'),
                'depth_bb': s.get('effective_stack_at_decision_bb')}
    fixtures = {x: _depth(x) for x in
                ['TM6083526894', 'TM6084295102', 'TM6083974506', '84990829',
                 '83915520', '83578445', '84107187',
                 'TM6083973489', 'TM6083975040', 'TM6084295885']}

    # ---- report-surface preserve metrics (from HTML) ----
    rng_lens = len(re.findall(r'class=["\'][^"\']*range-lens', html))
    hero_combo = html.count('Hero:') if 'Hero:' in html else None
    modal_total = None
    m = re.search(r'(\d+)\s*/\s*(\d+)\s*hands?', html)
    metrics = {
        'range_lens_spans': rng_lens,
        'hands_in_html_appendix': len(set(re.findall(r"data-hand-id='(\w+)'", html))),
    }

    summary = {
        'hands': len(hands),
        'inventory_counts': {k: (len(v) if isinstance(v, list) else v)
                             for k, v in inv.items()},
        'required_zero_counts': {k: len(v) for k, v in viol.items()},
        'all_required_zero': all(len(v) == 0 for v in viol.values()),
        'named_fixtures': fixtures,
        'report_metrics': metrics,
    }

    out = {'summary': summary, 'inventories': inv, 'violations': viol}
    with io.open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    print('=' * 64)
    print('ITERATION 1 (REV3) — exact-report inventories')
    print('=' * 64)
    print('hands:', len(hands))
    for k, v in summary['inventory_counts'].items():
        print('  %-42s %s' % (k, v))
    print('-' * 64)
    print('REQUIRED ZERO-COUNTS:')
    for k, v in summary['required_zero_counts'].items():
        print('  %-42s %d  %s' % (k, v, 'OK' if v == 0 else 'FAIL'))
    print('-' * 64)
    print('aggregate/reason combinations seen:')
    for k, v in sorted(inv['aggregate_reason_combinations'].items()):
        print('  %-40s %d' % (k, v))
    print('-' * 64)
    print('named fixtures:')
    for k, v in fixtures.items():
        print('  %-14s %s' % (k, v))
    print('-' * 64)
    print('RESULT:', 'PASS' if summary['all_required_zero'] else 'FAIL')
    print('wrote', out_path)
    sys.exit(0 if summary['all_required_zero'] else 1)


if __name__ == '__main__':
    main()
