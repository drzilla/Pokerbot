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

    # REV9 C2: load the persisted report_data (for coaching-card ownership) if available.
    import glob as _glob_inv
    report_data = {}
    try:
        _rd_files = sorted(_glob_inv.glob('/home/claude/gem_report_data_*.json')
                           + _glob_inv.glob('C:/home/claude/gem_report_data_*.json'))
        if _rd_files:
            report_data = json.load(io.open(_rd_files[-1], 'r', encoding='utf-8'))
    except Exception:
        report_data = {}

    inv = {
        'decision_time_eligible_bounties': [],
        'aggregate_reason_combinations': {},
        'pots_with_dead_money': [],
        'main_side_layer_reconciliations': [],
        'call_vs_jam_and_call_off_prices': [],
        # REV5 inventories
        'bounty_applicability_combinations': {},
        'hero_shoves_potential_if_called': [],
        'uncalled_returns': [],
        'realized_bounty_eligibility': [],
        'equal_stack_confrontations': [],
        # REV6 inventories
        'ledger_uncalled_inventory': [],
        'fully_called_hands': [],
        'combined_bounty_opportunities': [],
        'bounty_certainty_combinations': {},
    }
    viol = {
        'future_contaminated_bounty_contexts': [],
        'aggregate_reason_contradictions': [],
        'non_allin_eligible_bounty_opponents': [],
        'unreconciled_pot_totals': [],
        'unjustified_unavailable_call_prices': [],
        # REV4 additions
        'fake_side_pot_layers': [],
        'folded_players_in_eligible_sets': [],
        'legacy_canonical_participant_mismatches': [],
        'rendered_report_bounty_mismatches': [],
        'collectibility_known_with_not_applicable': [],
        'adjustment_applied_with_not_applicable_none_unknown': [],
        # REV5 additions
        'open_shove_rejam_rendered_bounty_irrelevant': [],
        'rendered_wrong_action_index': [],
        'one_player_side_pots': [],
        'zero_player_pot_layers': [],
        'uncalled_excess_in_contestable_pot': [],
        'gross_contestable_return_reconciliation_failures': [],
        'hero_folded_realized_bounty_eligibility': [],
        'equal_stack_classified_non_collectible': [],
        # REV6 required zero-counts
        'ledger_uncalled_sub_0_2bb_false_returns': [],
        'fully_called_hands_with_uncalled_return': [],
        'named_fixture_false_uncalled': [],
        'exact_and_potential_collapsed': [],
        'committed_unknown_stack_not_flagged': [],
        'visible_decision_not_reviewed_action': [],
        # REV7 required zero-counts (visible callable-price / action-typed truth)
        'visible_call_gt_callable': [],
        'visible_call_gt_effective_depth': [],
        'raw_overjam_rendered_as_price': [],
        'non_call_action_rendered_as_call': [],
        'visible_call_0bb': [],
        'capsule_or_action_mismatch': [],
        # REV8 required zero-counts (facing-state + full consumer ownership)
        'first_in_fold_priced': [],
        'nonprice_action_shows_pot_odds': [],
        'non_allin_action_shows_allin_math': [],
        'aggressive_action_shows_call_jam_range': [],
        'postflop_selected_shows_preflop_range_as_selected': [],
        'not_applicable_bounty_collectible_teaching': [],
        'inferred_labelled_reviewed': [],
        # REV9 required zero-counts (facing-limp + structured range + coaching ownership)
        'facing_limp_rendered_first_in': [],
        'facing_limp_using_first_in_price_reason': [],
        'facing_limp_using_first_in_range_as_selected': [],
        'range_block_wrong_node_as_selected': [],
        'coaching_selected_action_mismatch': [],
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
            # REV5 B1: applicability combinations + shove inventory
            app = dbc.get('bounty_applicability')
            inv['bounty_applicability_combinations'][app] = \
                inv['bounty_applicability_combinations'].get(app, 0) + 1
            # REV6 B3: a hand with BOTH a committed and a potential bounty opportunity must
            # be exact_and_potential (never collapsed to a scalar that drops the caller).
            _he = dbc.get('has_exact_committed_bounty_opportunity')
            _hp = dbc.get('has_potential_calling_bounty_opportunity')
            if _he and _hp:
                inv['combined_bounty_opportunities'].append(
                    {'hand': hid, 'applicability': app,
                     'committed': dbc.get('committed_allin_bounties_by_opponent'),
                     'potential': dbc.get('potential_calling_bounties_by_opponent')})
                if app != 'exact_and_potential':
                    viol['exact_and_potential_collapsed'].append({'hand': hid, 'applicability': app})
            # REV6 B4: certainty distribution + an unknown-stack committed all-in must be
            # flagged material-unknown (so the auto-clear gate blocks it).
            _cert = dbc.get('bounty_certainty')
            inv['bounty_certainty_combinations'][_cert] = \
                inv['bounty_certainty_combinations'].get(_cert, 0) + 1
            if (app in ('exact_committed', 'exact_and_potential') and _cert == 'unknown_stack'
                    and not dbc.get('bounty_material_unknown')):
                viol['committed_unknown_stack_not_flagged'].append({'hand': hid})
            _hk = dbc.get('hero_action_kind')
            if _hk in ('open_shove', 'rejam_over_live_raise', 'overjam_with_side_pot'):
                inv['hero_shoves_potential_if_called'].append(
                    {'hand': hid, 'action_index': ridx, 'kind': _hk, 'applicability': app,
                     'potential_callers': dbc.get('potential_calling_bounties_by_opponent'),
                     'committed': dbc.get('committed_allin_bounties_by_opponent')})
                _pot = dbc.get('potential_calling_bounties_by_opponent') or {}
                _comm = dbc.get('committed_allin_bounties_by_opponent') or {}
                if (_pot or _comm) and app == 'not_applicable':
                    viol['open_shove_rejam_rendered_bounty_irrelevant'].append({'hand': hid, 'kind': _hk})
            # REV5 B5: an equal-stack opponent must never make the aggregate 'none'
            cover_vals = list((dbc.get('stack_cover_relationship_by_opponent') or {}).values())
            elig_vals = list((dbc.get('eligible_bounties_by_opponent') or {}).values())
            if any(v == 'collectible_equal_stack' for v in elig_vals + cover_vals):
                inv['equal_stack_confrontations'].append(
                    {'hand': hid, 'aggregate': dbc['aggregate'], 'eligible': dbc.get('eligible_bounties_by_opponent')})
                if dbc['aggregate'] == 'none':
                    viol['equal_stack_classified_non_collectible'].append({'hand': hid})

        # (3) pots with dead money + (4) layer reconciliation + REV4 pot semantics
        prv = qp.pot_reconciliation_violation(rc)
        if prv:
            viol['unreconciled_pot_totals'].append({'hand': hid, 'why': prv})
        psv = qp.pot_semantic_violations(rc)
        for v in psv:
            if v in ('unmerged_adjacent_identical_eligible', 'side_without_eligible_change'):
                viol['fake_side_pot_layers'].append({'hand': hid, 'why': v})
            elif v == 'folded_in_eligible_set':
                viol['folded_players_in_eligible_sets'].append({'hand': hid})
            elif v in ('main_participants_mismatch', 'side_participants_mismatch',
                       'participant_count_ne_eligible', 'main_not_single_lowest'):
                viol['legacy_canonical_participant_mismatches'].append({'hand': hid, 'why': v})
            elif v == 'one_player_side_pot':
                viol['one_player_side_pots'].append({'hand': hid})
            elif v == 'zero_player_pot_layer':
                viol['zero_player_pot_layers'].append({'hand': hid})
            elif v.startswith('reconcile:'):
                viol['gross_contestable_return_reconciliation_failures'].append({'hand': hid, 'why': v})
            elif v in ('hero_folded_but_realized_collectible_nonempty',
                       'hero_folded_but_eligible_layers_nonempty'):
                viol['hero_folded_realized_bounty_eligibility'].append({'hand': hid, 'why': v})
        # REV5 B3: gross == contestable + uncalled; uncalled never inside contestable
        _gross = rc.get('gross_action_commitments_bb')
        _cont = rc.get('contestable_pot_bb')
        _unc = rc.get('uncalled_return_bb') or 0.0
        if _gross is not None and _cont is not None:
            if abs((_cont + _unc) - _gross) > 0.02:
                viol['gross_contestable_return_reconciliation_failures'].append(
                    {'hand': hid, 'gross': _gross, 'contestable': _cont, 'uncalled': _unc})
            if _unc > 0.001:
                inv['uncalled_returns'].append(
                    {'hand': hid, 'gross': _gross, 'contestable': _cont,
                     'uncalled_by_player': rc.get('uncalled_return_by_player')})
                # uncalled excess must NOT be inside any contestable layer
                if _cont + _unc - _gross > 0.02:
                    viol['uncalled_excess_in_contestable_pot'].append({'hand': hid})
        # REV6 B1: LEDGER-derived uncalled — typed source fields + false-return detection.
        _src_idx = rc.get('uncalled_source_action_index')
        _src_added = rc.get('uncalled_action_added_bb')
        _matched = rc.get('matched_amount_bb')
        if _unc > 0.001:
            inv['ledger_uncalled_inventory'].append(
                {'hand': hid, 'uncalled_bb': _unc,
                 'source_action_index': _src_idx, 'source_street': rc.get('uncalled_source_street'),
                 'source_player': rc.get('uncalled_source_player'),
                 'action_added_bb': _src_added, 'matched_amount_bb': _matched})
            # a forced post / ante / rounding diff can NEVER be a genuine uncalled bet: a
            # sub-0.20BB return is the REV5 false-return signature (must be 0 post-fix).
            if _unc <= 0.20:
                viol['ledger_uncalled_sub_0_2bb_false_returns'].append(
                    {'hand': hid, 'uncalled': _unc, 'source_index': _src_idx})
        # fully-called: the final aggressor's FULL STREET commitment was matched by another
        # player (matched >= aggressor street commit) -> uncalled MUST be 0. Uses the
        # aggressor's street commit (NOT just the last action's added amount, which mislabels
        # a bet-then-raise sequence whose total exceeds what an opponent matched).
        _agg_commit = rc.get('uncalled_aggressor_street_commit_bb')
        if (_agg_commit is not None and _matched is not None and _matched + 0.001 >= _agg_commit
                and _agg_commit > 0.001):
            inv['fully_called_hands'].append(
                {'hand': hid, 'matched_amount_bb': _matched, 'aggressor_street_commit_bb': _agg_commit})
            if _unc > 0.02:
                viol['fully_called_hands_with_uncalled_return'].append(
                    {'hand': hid, 'uncalled': _unc, 'matched': _matched, 'agg_commit': _agg_commit})
        # named fixtures must carry ZERO uncalled (BB-ante / rounding asymmetry, fully called)
        if hid in ('TM6083526894', 'TM6084611544', '83526894', '84611544') and _unc > 0.001:
            viol['named_fixture_false_uncalled'].append({'hand': hid, 'uncalled': _unc})
        # REV5 B4: realized eligibility inventory (Hero folded => realized {})
        if rc.get('eligible_bounties'):
            inv['realized_bounty_eligibility'].append(
                {'hand': hid, 'hero_remained_eligible': rc.get('hero_remained_eligible'),
                 'decision_eligible': rc.get('eligible_bounties'),
                 'realized_collectible': rc.get('realized_collectible_bounties')})
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
        # REV4: worklist bounty-field contradictions
        _bnt = it.get('bounty_context') or {}
        if (_bnt.get('coverage_aggregate') == 'not_applicable'
                and (_bnt.get('eligible_bounties_by_opponent') in ({}, None))):
            if _bnt.get('collectibility_known') is True:
                viol['collectibility_known_with_not_applicable'].append({'hand': hid})
        if (_bnt.get('adjustment_applied_to_decision') is True
                and _bnt.get('coverage_aggregate') in ('not_applicable', 'none', 'unknown')):
            viol['adjustment_applied_with_not_applicable_none_unknown'].append(
                {'hand': hid, 'aggregate': _bnt.get('coverage_aggregate')})
        for v in qp.worklist_bounty_consistency_violations(_bnt):
            if v == 'not_applicable_with_collectibility_known' and \
                    not any(x['hand'] == hid for x in viol['collectibility_known_with_not_applicable']):
                viol['collectibility_known_with_not_applicable'].append({'hand': hid})

    # REV4: rendered-report bounty context == canonical (data-attr parity)
    _grb = qp.gate_report_bounty(by_id, html)
    for mm in _grb.get('mismatches', []):
        viol['rendered_report_bounty_mismatches'].append(mm)
    inv['rendered_bounty_hands_checked'] = _grb.get('checked', 0)

    # REV5 B2: per-decision rendered bounty context == canonical (action-index routing)
    _gpd = qp.gate_report_decision_bounty(by_id, html)
    for mm in _gpd.get('mismatches', []):
        viol['rendered_wrong_action_index'].append(mm)
    inv['rendered_decision_blocks_checked'] = _gpd.get('checked', 0)
    # REV6 B2/B5 + REV7 B1: the VISIBLE decision lesson grades the reviewed action AND uses
    # the callable price / action-typed display (parses rendered markdown).
    _gvd = qp.gate_report_visible_decision(by_id, html, worklist)
    _REV7_CATS = {
        'visible_call_gt_callable': 'visible_call_gt_callable',
        'visible_call_gt_effective_depth': 'visible_call_gt_effective_depth',
        'visible_call_is_raw_overjam': 'raw_overjam_rendered_as_price',
        'visible_action_ne_canonical_display': 'capsule_or_action_mismatch',
    }
    for mm in _gvd.get('mismatches', []):
        _fld = mm.get('field')
        if _fld in _REV7_CATS:
            viol[_REV7_CATS[_fld]].append(mm)
            # a canonical 'call ...' phrase rendered for a non-call canonical action is the
            # 'non-call rendered as call' case; an injected 'call 0BB' lands here too.
            if _fld == 'visible_action_ne_canonical_display':
                if str(mm.get('visible', '')).strip().lower().startswith('call'):
                    viol['non_call_action_rendered_as_call'].append(mm)
        else:
            viol['visible_decision_not_reviewed_action'].append(mm)
    # REV8 D1: an inferred decision labelled "Reviewed decision" (gate F, worklist authority).
    for mm in _gvd.get('mismatches', []):
        if mm.get('field') == 'inferred_labelled_reviewed':
            viol['inferred_labelled_reviewed'].append(mm)
    inv['visible_decision_blocks_checked'] = _gvd.get('checked', 0)
    # REV8 E1: the FULL-RENDER consumer-ownership gate (range / verdict / all-in math / PKO /
    # price applicability across the complete hand body).
    _gfr = qp.gate_report_full_render(by_id, html, worklist)
    _FR_CATS = {
        'nonprice_action_shows_pot_odds': 'nonprice_action_shows_pot_odds',
        'nonprice_action_shows_required_equity': 'nonprice_action_shows_pot_odds',
        'nonprice_action_shows_call_verdict': 'nonprice_action_shows_pot_odds',
        'non_allin_action_shows_allin_math': 'non_allin_action_shows_allin_math',
        'aggressive_action_shows_call_jam_range': 'aggressive_action_shows_call_jam_range',
        'postflop_selected_shows_preflop_range_as_selected': 'postflop_selected_shows_preflop_range_as_selected',
        'not_applicable_bounty_collectible_teaching': 'not_applicable_bounty_collectible_teaching',
        'not_applicable_bounty_positive_incentive': 'not_applicable_bounty_collectible_teaching',
        'facing_limp_rendered_first_in': 'facing_limp_rendered_first_in',
    }
    for mm in _gfr.get('mismatches', []):
        _c = _FR_CATS.get(mm.get('field'))
        if _c:
            viol[_c].append(mm)
    inv['full_render_blocks_checked'] = _gfr.get('checked', 0)
    # REV9 A/D/C2: model-level facing-limp + structured range-node + coaching ownership.
    from gem_report_draft.sections_xiv import range_ownership_record as _ror
    from gem_report_draft._helpers import hand_range_evidence as _hre_inv
    for h in hands:
        _hid_inv = (h.get('tournament_hand_id') or h.get('id'))
        _idx_inv = ds.infer_reviewed_action_index(h)
        if _idx_inv is None:
            continue
        _s_inv = ds.build_decision_snapshot(h, _idx_inv)
        _ref_inv = ds.build_reviewed_decision_ref(h, _idx_inv)
        if _s_inv.get('decision_facing_state') == 'facing_limp':
            # a facing-limp decision must use the limp price reason, never a first-in one.
            if str(_s_inv.get('price_reason') or '').startswith('first_in'):
                viol['facing_limp_using_first_in_price_reason'].append({'hand': _hid_inv})
            _ev_inv = _hre_inv(h) or {}
            if _ev_inv.get('role') in ('rfi', 'open', 'first_in'):
                _rec = _ror(h, _ev_inv, _ref_inv)
                if _rec.get('ownership') == 'selected':
                    viol['facing_limp_using_first_in_range_as_selected'].append({'hand': _hid_inv})
        # structured range-node: a SELECTED range block must share the reviewed node family.
        _ev2 = _hre_inv(h) or {}
        if _ev2.get('role'):
            _rec2 = _ror(h, _ev2, _ref_inv)
            inv.setdefault('range_ownership_records', []).append(_rec2)
            if _rec2.get('ownership') == 'selected' and _rec2.get('selected_node_type') != _rec2.get('range_node_type'):
                from gem_report_draft.sections_xiv import _NODE_COMPAT as _NC
                if _rec2.get('range_node_type') not in _NC.get(_rec2.get('selected_node_type'), set()):
                    viol['range_block_wrong_node_as_selected'].append(_rec2)
    # REV9 C2: coaching-card bounty context must derive from the reviewed action index.
    _cc_inv = report_data.get('coaching_cards') or {}
    inv['coaching_cards_checked'] = sum(len(v) for v in _cc_inv.values())
    for _hid_cc, _cards_cc in _cc_inv.items():
        for _card in _cards_cc:
            if (_card.get('bounty_context_owner') == 'hand_level_default'):
                viol['coaching_selected_action_mismatch'].append(
                    {'hand': _hid_cc, 'card': _card.get('card_type')})
    # REV8 A2: a first-in / check / over-limps fold must never carry a call price.
    for h in hands:
        idx2 = ds.infer_reviewed_action_index(h)
        if idx2 is None:
            continue
        s2 = ds.build_decision_snapshot(h, idx2)
        if (s2.get('hero_action_kind') == 'fold'
                and s2.get('decision_facing_state') in ('first_in', 'facing_limp', 'check_option')
                and s2.get('price_applicable')):
            viol['first_in_fold_priced'].append(
                {'hand': (h.get('tournament_hand_id') or h.get('id')),
                 'facing': s2.get('decision_facing_state'), 'pos': s2.get('hero_position')})
    # REV7: report-wide scans for the impossible-render signatures.
    import re as _re_rev7
    _decoded = ' '.join((qp.decode_lazy_hands(html) or {}).values())
    for _m in _re_rev7.finditer(r'Reviewed decision:[^<]*?,\s*(call 0\s*BB)', _decoded):
        viol['visible_call_0bb'].append({'token': _m.group(1)})
    # REV5 B1: the OLD "bounty irrelevant / not a decision-time factor" copy must be GONE
    for _bad in ('not a decision-time factor', 'no committed all-in opponent at the decision'):
        _n = html.count(_bad)
        if _n:
            viol['open_shove_rejam_rendered_bounty_irrelevant'].append({'text': _bad, 'count': _n})

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
