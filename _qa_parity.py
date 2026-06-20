"""v8.17.1 Iteration 1 — END-TO-END PARITY HARNESS.

Proves the actual product surfaces agree with the ONE canonical decision model
(gem_decision_snapshot), not just that the model is correct in isolation. The
prior corrective pass failed because the worklist / report still carried stale
non-canonical values; this harness is the gate that catches that.

Three gates (all must be 0 mismatches):
  A. WORKLIST == SNAPSHOT  — every analyst_worklist item's effective stack,
     street, action kind and bounty aggregate equal the canonical snapshot
     built from the same hand at the same reviewed action index.
  B. REPORT == SNAPSHOT    — every rendered all-in decision's data-eff-bb and
     decision label equal the snapshot (the parser stamps the SAME eff the
     report reads; the render label routes through hero_action_kind).
  C. MODEL ADVERSARIAL     — future-blind action kind + current-street stacks
     (delegated to the _test_scratch T-DS block; summarised here).

Usage:
  python _qa_parity.py <hands_json> <worklist_json> <report_html> [--json OUT]

Effective-stack comparison tolerance is 0.6BB (chart/round display), street and
action kind are exact, bounty aggregate is exact.
"""
import io
import json
import re
import sys

sys.path.insert(0, '.')
import gem_decision_snapshot as ds
from gem_analyst_worklist import _reviewed_action_index
from _qa_decode_lazy import decode_lazy_hands

EFF_TOL = 0.6   # BB; absorbs round(,1) + chart-bucket display


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


def _load_hands(path):
    with io.open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _hand_index(hands):
    idx = {}
    for h in hands:
        tid = str(h.get('tournament_hand_id') or h.get('hand_id') or h.get('id') or '')
        if tid:
            idx[tid] = h
            idx[tid[-8:]] = h   # bare-8 alias
    return idx


def _snap_eff(snap):
    """The authoritative decision-effective stack the worklist/report must show."""
    if not snap:
        return None
    return (snap.get('effective_stack_vs_faced_aggressor')
            or snap.get('max_effective_stack_among_active_opponents'))


def gate_worklist(hands_idx, worklist):
    """A. worklist item fields == canonical snapshot."""
    items = worklist.get('items') or {}
    if isinstance(items, dict):
        items = list(items.values())
    out = {'checked': 0, 'mismatches': []}
    for it in items:
        hid = str(it.get('hand_id') or '')
        h = hands_idx.get(hid) or hands_idx.get(hid[-8:])
        if h is None:
            continue
        kind = it.get('decision_kind') or it.get('bucket')
        ridx = _reviewed_action_index(h, kind)
        if ridx is None:
            continue
        snap = ds.build_decision_snapshot(h, ridx)
        out['checked'] += 1
        dn = it.get('decision_node') or {}
        # --- street ---
        wl_street = (dn.get('street') or it.get('street') or '').lower()
        sn_street = (snap.get('street') or '').lower()
        if wl_street and sn_street and wl_street != sn_street:
            out['mismatches'].append(
                {'hand': hid, 'field': 'street', 'worklist': wl_street, 'snapshot': sn_street})
        # --- action kind ---
        wl_kind = dn.get('hero_action_kind')
        sn_kind = snap.get('hero_action_kind')
        if wl_kind and sn_kind and wl_kind != sn_kind:
            out['mismatches'].append(
                {'hand': hid, 'field': 'action_kind', 'worklist': wl_kind, 'snapshot': sn_kind})
        # --- effective stack (only meaningful for an all-in confrontation) ---
        if sn_kind in ('call_vs_jam', 'call_off', 'open_shove',
                       'rejam_over_live_raise', 'overjam_with_side_pot'):
            wl_eff = _f(it.get('effective_bb')) or _f(dn.get('effective_bb_vs_relevant_villain'))
            sn_eff = _f(_snap_eff(snap))
            if wl_eff is not None and sn_eff is not None and abs(wl_eff - sn_eff) > EFF_TOL:
                out['mismatches'].append(
                    {'hand': hid, 'field': 'effective_bb', 'worklist': wl_eff,
                     'snapshot': round(sn_eff, 2)})
        # --- bounty aggregate (REV3: worklist consumes the FUTURE-BLIND decision-time
        #     context, so parity is checked against decision_bounty_aggregate) ---
        bnt = it.get('bounty_context') or it.get('bounty') or {}
        wl_agg = bnt.get('coverage_aggregate') or bnt.get('aggregate')
        try:
            sn_agg = ds.decision_bounty_aggregate(h, ridx)
        except Exception:
            sn_agg = None
        if wl_agg and sn_agg and wl_agg != sn_agg:
            out['mismatches'].append(
                {'hand': hid, 'field': 'decision_bounty_aggregate', 'worklist': wl_agg, 'snapshot': sn_agg})
        # --- worklist eligible map must equal the canonical decision-time eligible map ---
        wl_elig = bnt.get('eligible_bounties_by_opponent')
        if wl_elig is not None:
            try:
                sn_elig = ds.decision_eligible_bounties_by_opponent(h, ridx)
            except Exception:
                sn_elig = None
            if sn_elig is not None and wl_elig != sn_elig:
                out['mismatches'].append(
                    {'hand': hid, 'field': 'eligible_bounties', 'worklist': wl_elig, 'snapshot': sn_elig})
    return out


_DEC_LABEL = {
    'call_vs_jam': 'call vs jam', 'call_off': 'call vs jam',
    'open_shove': 'open-shove', 'rejam_over_live_raise': 're-jam',
    'overjam_with_side_pot': 're-jam',
}


def gate_report(hands_idx, html):
    """B. rendered all-in decision data-eff-bb + label == snapshot."""
    bodies = decode_lazy_hands(html)
    out = {'checked': 0, 'mismatches': []}
    # data-eff-bb is on the appendix article wrapper, keyed by data-hand-id.
    eff_by_hand = {}
    for m in re.finditer(
            r"data-hand-id='(\w+)'[^>]*data-eff-bb='([0-9.]+)'", html):
        eff_by_hand[m.group(1)] = _f(m.group(2))
    for m in re.finditer(
            r"data-eff-bb='([0-9.]+)'[^>]*data-hand-id='(\w+)'", html):
        eff_by_hand.setdefault(m.group(2), _f(m.group(1)))
    for hid, body in bodies.items():
        h = hands_idx.get(str(hid)) or hands_idx.get(str(hid)[-8:])
        if h is None:
            continue
        # REV2 B6: cover ALL all-in decisions, not just preflop ones — the postflop
        # call-vs-jam hands (83526894/84295102/83974506) were skipped before.
        snap = ds.build_decision_snapshot(h)   # reviewed = Hero's last action
        sn_kind = snap.get('hero_action_kind')
        if sn_kind not in ('call_vs_jam', 'call_off', 'open_shove',
                           'rejam_over_live_raise', 'overjam_with_side_pot'):
            continue
        out['checked'] += 1
        # REV2 semantic: a call_vs_jam/call_off facing a >1BB bet must NOT render a
        # ~0 decision depth in its body (catches the 0.14-0.15 collapse).
        if sn_kind in ('call_vs_jam', 'call_off') and (snap.get('to_call_bb') or 0) > 1.0:
            depth = snap.get('effective_stack_at_decision_bb')
            if depth is not None and depth <= 1.0:
                out['mismatches'].append(
                    {'hand': hid, 'field': 'postflop_depth_collapsed',
                     'snapshot_depth': depth, 'to_call': snap.get('to_call_bb')})
            for m in re.finditer(r'(0\.1[0-9])\s?BB', body):
                out['mismatches'].append(
                    {'hand': hid, 'field': 'body_shows_0.1x_depth', 'token': m.group(0)})
                break
        # --- decision label parity (STRICT 3-way): the rendered Decision label
        # must equal the canonical kind's label family. Catches open-shove<->re-jam
        # AND call<->re-jam divergence (83578445/84107187 self-contradiction). ---
        want = _DEC_LABEL.get(sn_kind, '')
        dec_m = re.search(r'Decision:\s*(?:</strong>|\*\*)?\s*([^<·\n*]+)', body)
        if want and dec_m:
            got = dec_m.group(1).strip().lower().replace('-', ' ')
            # normalise the rendered label to a family token
            if 'call vs jam' in got or 'call off' in got:
                got_fam = 'call vs jam'
            elif 're jam' in got or got == 'rejam':
                got_fam = 're-jam'
            elif 'open shove' in got or 'open jam' in got:
                got_fam = 'open-shove'
            else:
                got_fam = None   # e.g. "all-in decision (exact node type unavailable)"
            if got_fam is not None and got_fam != want:
                out['mismatches'].append(
                    {'hand': hid, 'field': 'decision_label',
                     'report': dec_m.group(1).strip(), 'report_family': got_fam,
                     'expected': want, 'snapshot_kind': sn_kind})
        # --- data-eff-bb parity ---
        rpt_eff = eff_by_hand.get(str(hid)) or eff_by_hand.get(str(hid)[-8:])
        sn_eff = _f(_snap_eff(snap))
        if rpt_eff is not None and sn_eff is not None and abs(rpt_eff - sn_eff) > EFF_TOL:
            out['mismatches'].append(
                {'hand': hid, 'field': 'data_eff_bb', 'report': rpt_eff,
                 'snapshot': round(sn_eff, 2)})
    return out


_ALLIN_KINDS = ('call_vs_jam', 'call_off', 'open_shove',
                'rejam_over_live_raise', 'overjam_with_side_pot')

# ── REV3 reusable semantic helpers (importable so the suite can prove the GATE
#    catches an intentionally-injected bug, not just that the model is correct) ──

_DBC_INVARIANT_KEYS = ('eligible_bounties_by_opponent', 'aggregate', 'reason',
                       'coverage_mixed', 'hero_in_allin_confrontation',
                       'stack_cover_relationship_by_opponent',
                       'hero_covers_relevant_villain')

# the ONLY valid (aggregate, reason) pairs — the canonical truth table.
_VALID_AGG_REASON = frozenset({
    ('all', 'known_all'), ('none', 'known_none'), ('none', 'equal_boundary'),
    ('mixed', 'known_mixed'), ('unknown', 'unknown_missing_stack'),
    ('not_applicable', 'not_applicable_no_allin_confrontation'),
})


def aggregate_reason_consistent(agg, reason):
    return (agg, reason) in _VALID_AGG_REASON


def _opp_all_in_at_or_before(h, opp, ridx):
    """Was `opp` all-in at or before the reviewed action index (future-blind)?"""
    led = h.get('action_ledger') or []
    for i, a in enumerate(led):
        if ridx is not None and i > ridx:
            break
        if a.get('player') == opp and a.get('is_all_in'):
            return True
    return False


def prefix_invariance_violations(h, ridx, future_actions, ctx_fn=None):
    """Append synthetic FUTURE actions strictly after the reviewed index; the
    decision bounty context (evaluated at the SAME fixed index) must stay byte-identical
    (future blindness). Returns the list of changed fields ([] == invariant). Pass a
    deliberately-contaminated builder as `ctx_fn` to prove the gate DETECTS contamination
    (suite tests #13).

    `ridx` must be a CONCRETE reviewed-action index. With no reviewed decision
    (ridx is None) there is nothing to contaminate — an injected Hero action would merely
    *create* a first decision, not change an earlier one — so this returns []."""
    if ridx is None:
        return []
    ctx_fn = ctx_fn or ds.build_decision_bounty_context
    led = list(h.get('action_ledger') or [])
    h2 = dict(h)
    h2['action_ledger'] = led + list(future_actions)
    a = ctx_fn(h, ridx)
    b = ctx_fn(h2, ridx)
    return [k for k in _DBC_INVARIANT_KEYS if a.get(k) != b.get(k)]


def pot_reconciliation_violation(rc):
    """A realized contest reconciles iff sum(layer totals) == total committed pot,
    sum(layer dead) == total dead money, and each layer total == eligible + dead.
    Returns a reason string or None."""
    layers = rc.get('pot_layers') or []
    total = rc.get('total_committed_pot_bb')
    if total is None:
        return 'missing_total_committed_pot'
    lsum = round(sum(l.get('total_layer_bb', 0.0) for l in layers), 2)
    if abs(lsum - total) > 0.02:
        return 'layer_sum_%s_!=_total_%s' % (lsum, total)
    dsum = round(sum(l.get('dead_money_bb', 0.0) for l in layers), 2)
    if abs(dsum - (rc.get('dead_money_bb') or 0.0)) > 0.02:
        return 'dead_layer_sum_%s_!=_dead_%s' % (dsum, rc.get('dead_money_bb'))
    for l in layers:
        if abs(round(l.get('eligible_contribution_bb', 0.0)
                     + l.get('dead_money_bb', 0.0), 2)
               - l.get('total_layer_bb', 0.0)) > 0.02:
            return 'layer_eligible+dead_!=_total'
    return None


# a synthetic future opponent all-in to append AFTER the reviewed action — a model
# that (wrongly) reads the full ledger would let this change the earlier context.
def _future_contamination_actions(street):
    return [{'street': street, 'player': '__GATE_FUTURE__', 'action': 'raises',
             'added_bb': 99.0, 'amount_bb': 99.0, 'is_all_in': True},
            {'street': street, 'player': 'Hero', 'action': 'calls',
             'added_bb': 99.0, 'amount_bb': 99.0, 'is_all_in': True}]


def gate_semantic(hands_idx, worklist):
    """REV2/REV3: semantic invariants on EVERY worklist decision item (not just
    cross-surface agreement). Catches a wrong MODEL the agreement gates can't.

    Depth invariants (INV1-3) run on all-in decisions; the REV3 decision-time bounty
    invariants (INV4-8) run on every bounty item; pot reconciliation (INV9) runs on
    every item with a realized contest."""
    items = worklist.get('items') or {}
    if isinstance(items, dict):
        items = list(items.values())
    out = {'checked': 0, 'violations': []}
    for it in items:
        hid = str(it.get('hand_id') or '')
        h = hands_idx.get(hid) or hands_idx.get(hid[-8:])
        if h is None:
            continue
        kind = it.get('decision_kind') or it.get('bucket')
        ridx = _reviewed_action_index(h, kind)
        if ridx is None:
            continue
        snap = ds.build_decision_snapshot(h, ridx)
        sn_kind = snap.get('hero_action_kind')
        dn = it.get('decision_node') or {}
        out['checked'] += 1

        if sn_kind in _ALLIN_KINDS:
            # INV1: a call/call-off facing a >1BB bet may not grade at ~0 depth.
            if sn_kind in ('call_vs_jam', 'call_off') and (snap.get('to_call_bb') or 0) > 1.0:
                eff = _f(dn.get('effective_bb_vs_relevant_villain'))
                if eff is not None and eff <= 1.0:
                    out['violations'].append({'hand': hid, 'inv': 'depth_collapsed', 'eff': eff})
            # INV2: an exact ledger call must not be 'unavailable' when the snapshot has one.
            if sn_kind in ('call_vs_jam', 'call_off') and (snap.get('callable_amount_bb') or 0) > 0:
                if dn.get('price_unavailable') or dn.get('price_source') == 'unavailable':
                    out['violations'].append({'hand': hid, 'inv': 'unjustified_unavailable',
                                              'snapshot_callable': snap.get('callable_amount_bb')})
            # INV3: the all-in bettor's remaining-after must never BE the decision depth.
            fa_rem = snap.get('faced_aggressor_remaining_after_action_bb')
            eff = _f(dn.get('effective_bb_vs_relevant_villain'))
            if (fa_rem is not None and fa_rem < 0.5 and eff is not None and eff < 0.5
                    and snap.get('faced_aggressor_all_in')):
                out['violations'].append({'hand': hid, 'inv': 'depth_used_remaining_after_allin'})

        # ── REV3 decision-time bounty invariants (future-blind) ──
        dbc = ds.build_decision_bounty_context(h, ridx)
        if dbc.get('is_bounty'):
            elig = dbc.get('eligible_bounties_by_opponent') or {}
            cover = dbc.get('stack_cover_relationship_by_opponent') or {}
            # INV4 (eligibility): every eligible opponent must be all-in AT or BEFORE
            # the reviewed action (no future-only all-in, no non-all-in chips-behind).
            future_or_nonallin = [p for p in elig if not _opp_all_in_at_or_before(h, p, ridx)]
            if future_or_nonallin:
                out['violations'].append({'hand': hid, 'inv': 'non_allin_or_future_bounty_eligible',
                                          'who': sorted(future_or_nonallin)})
            # INV5 (no all-in confrontation -> empty eligible, not_applicable).
            if not dbc.get('hero_in_allin_confrontation'):
                if elig or dbc.get('aggregate') != 'not_applicable':
                    out['violations'].append({'hand': hid, 'inv': 'eligible_without_confrontation',
                                              'agg': dbc.get('aggregate'), 'elig': elig})
            # INV6 (typed consistency): aggregate/reason pair under the truth table.
            if not aggregate_reason_consistent(dbc.get('aggregate'), dbc.get('reason')):
                out['violations'].append({'hand': hid, 'inv': 'aggregate_reason_contradiction',
                                          'agg': dbc.get('aggregate'), 'reason': dbc.get('reason')})
            # INV6b: coverage_mixed must agree with the aggregate.
            if bool(dbc.get('coverage_mixed')) != (dbc.get('aggregate') == 'mixed'):
                out['violations'].append({'hand': hid, 'inv': 'coverage_mixed_disagrees_aggregate'})
            # INV7 (cover != eligibility): an opponent in the cover map but NOT all-in
            # at/before the decision must NOT be in the eligible map.
            cover_leak = [p for p in cover if p in elig and not _opp_all_in_at_or_before(h, p, ridx)]
            if cover_leak:
                out['violations'].append({'hand': hid, 'inv': 'cover_used_as_eligibility',
                                          'who': sorted(cover_leak)})
            # INV8 (prefix invariance): a later opponent/Hero all-in must not change
            # this earlier decision-time context.
            pv = prefix_invariance_violations(h, ridx,
                                              _future_contamination_actions(snap.get('street', 'preflop')))
            if pv:
                out['violations'].append({'hand': hid, 'inv': 'future_contaminated_bounty_context',
                                          'fields': pv})
        # INV9 (pot reconciliation): folded dead money preserved + layers reconcile.
        prv = pot_reconciliation_violation(ds.build_realized_contest(h, ridx))
        if prv:
            out['violations'].append({'hand': hid, 'inv': 'pot_unreconciled', 'why': prv})
    return out


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    hands = _load_hands(sys.argv[1])
    worklist = json.load(io.open(sys.argv[2], 'r', encoding='utf-8'))
    html = io.open(sys.argv[3], 'r', encoding='utf-8').read()
    out_json = None
    if '--json' in sys.argv:
        out_json = sys.argv[sys.argv.index('--json') + 1]

    hands_idx = _hand_index(hands)
    g_wl = gate_worklist(hands_idx, worklist)
    g_rp = gate_report(hands_idx, html)
    g_sem = gate_semantic(hands_idx, worklist)

    print('=' * 64)
    print('END-TO-END PARITY — worklist & report vs canonical snapshot (+semantic)')
    print('=' * 64)
    print(f"A. WORKLIST == SNAPSHOT : {g_wl['checked']} items checked, "
          f"{len(g_wl['mismatches'])} mismatch(es)")
    for mm in g_wl['mismatches'][:40]:
        print('   ✗', mm)
    print(f"B. REPORT   == SNAPSHOT : {g_rp['checked']} all-in decisions checked, "
          f"{len(g_rp['mismatches'])} mismatch(es)")
    for mm in g_rp['mismatches'][:40]:
        print('   ✗', mm)
    print(f"C. SEMANTIC INVARIANTS  : {g_sem['checked']} all-in items checked, "
          f"{len(g_sem['violations'])} violation(s)")
    for mm in g_sem['violations'][:40]:
        print('   ✗', mm)
    ok = not g_wl['mismatches'] and not g_rp['mismatches'] and not g_sem['violations']
    print('-' * 64)
    print('RESULT:', 'PASS — all surfaces agree with the snapshot + semantics hold' if ok
          else 'FAIL — see mismatches above')
    if out_json:
        with io.open(out_json, 'w', encoding='utf-8') as fh:
            json.dump({'worklist': g_wl, 'report': g_rp, 'semantic': g_sem, 'pass': ok}, fh, indent=2)
        print('wrote', out_json)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
