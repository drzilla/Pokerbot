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
import _qa_ledger_oracle as oracle   # REV11 G: INDEPENDENT ledger oracle (no canonical imports)

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
    idx = {'_all_hands': list(hands)}
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


def _num_eq(a, b, tol=0.05):
    fa, fb = _f(a), _f(b)
    if fa is None and fb is None:
        return True
    if fa is None or fb is None:
        return False
    return abs(fa - fb) <= tol


def gate_worklist(hands_idx, worklist):
    """A. (REV10 A5/B8) COMPLETE-FIELD parity: every exported worklist decision_node is a
    byte-faithful SERIALIZATION of the canonical ReviewedDecisionView built from the SAME hand
    at the SAME reviewed action index. The prior gate compared only street/kind/eff/bounty and
    gave false confidence (the worklist still carried legacy facing=unknown / raw call prices).
    Now every canonical field is compared, plus two hard invariants:
      * an authoritative worklist node must never have facing_state 'unknown';
      * a non-price action must never carry a populated call price."""
    from gem_report_draft.sections_xiv import reviewed_range_ownership as _rro
    items = worklist.get('items') or {}
    if isinstance(items, dict):
        items = list(items.values())
    out = {'checked': 0, 'mismatches': [], 'facing_unknown': 0, 'nonprice_with_call': 0}
    # field path -> (extractor from worklist dn, extractor from canonical cn, comparator)
    EXACT = lambda a, b: (a or None) == (b or None)
    for it in items:
        hid = str(it.get('hand_id') or '')
        h = hands_idx.get(hid) or hands_idx.get(hid[-8:])
        if h is None:
            continue
        kind = it.get('decision_kind') or it.get('bucket')
        ridx = _reviewed_action_index(h, kind)
        if ridx is None:
            continue
        out['checked'] += 1
        dn = it.get('decision_node') or {}
        # rebuild the canonical node the SAME way the worklist does
        try:
            _rdref = ds.build_reviewed_decision_ref(h, ridx, kind, 'worklist_reviewed_action')
            _rown = _rro(h, _rdref)
            cn = ds.serialize_reviewed_decision_node(
                h, ridx, kind, 'worklist_reviewed_action',
                reference_node_type=_rown.get('reference_node_type'),
                evidence_purpose=_rown.get('evidence_purpose'))
        except Exception as e:
            out['mismatches'].append({'hand': hid, 'field': '_canonical_build', 'error': str(e)})
            continue

        def _pc(d, k):
            return (d.get('price_contract') or {}).get(k)

        def _sc(d, k):
            return (d.get('stack_contract') or {}).get(k)

        def _sel(d, k):
            return (d.get('selection') or {}).get(k)

        checks = [
            ('hero_action_index', dn.get('hero_action_index'), cn.get('hero_action_index'), EXACT),
            ('street', dn.get('street'), cn.get('street'), EXACT),
            ('hero_action_kind', dn.get('hero_action_kind'), cn.get('hero_action_kind'), EXACT),
            ('hero_actual_action', dn.get('hero_actual_action'), cn.get('hero_actual_action'), EXACT),
            ('action_display', dn.get('action_display'), cn.get('action_display'), EXACT),
            ('decision_facing_state', dn.get('decision_facing_state'), cn.get('decision_facing_state'), EXACT),
            ('faced_action_kind', dn.get('faced_action_kind'), cn.get('faced_action_kind'), EXACT),
            ('faced_player', dn.get('faced_player'), cn.get('faced_player'), EXACT),
            ('limpers_before_hero', dn.get('limpers_before_hero'), cn.get('limpers_before_hero'), EXACT),
            ('no_hero_decision', bool(dn.get('no_hero_decision')), bool(cn.get('no_hero_decision')), EXACT),
            ('price_applicable', _pc(dn, 'price_applicable'), _pc(cn, 'price_applicable'), EXACT),
            ('price_reason', _pc(dn, 'price_reason'), _pc(cn, 'price_reason'), EXACT),
            ('raw_amount_to_match_bb', _pc(dn, 'raw_amount_to_match_bb'), _pc(cn, 'raw_amount_to_match_bb'), _num_eq),
            ('callable_amount_bb', _pc(dn, 'callable_amount_bb'), _pc(cn, 'callable_amount_bb'), _num_eq),
            ('contestable_pot_before_action_bb', _pc(dn, 'contestable_pot_before_action_bb'),
             _pc(cn, 'contestable_pot_before_action_bb'), _num_eq),
            ('uncallable_overjam_bb', _pc(dn, 'uncallable_overjam_bb'), _pc(cn, 'uncallable_overjam_bb'), _num_eq),
            ('required_equity_pct', _pc(dn, 'required_equity_pct'), _pc(cn, 'required_equity_pct'), _num_eq),
            ('hero_stack_before_action_bb', _sc(dn, 'hero_stack_before_action_bb'),
             _sc(cn, 'hero_stack_before_action_bb'), _num_eq),
            ('effective_stack_at_decision_bb', _sc(dn, 'effective_stack_at_decision_bb'),
             _sc(cn, 'effective_stack_at_decision_bb'), _num_eq),
            ('selection_source', _sel(dn, 'source'), _sel(cn, 'source'), EXACT),
            ('selection_confidence', _sel(dn, 'confidence'), _sel(cn, 'confidence'), EXACT),
            ('bounty_applicability', dn.get('bounty_applicability'), cn.get('bounty_applicability'), EXACT),
            ('bounty_certainty', dn.get('bounty_certainty'), cn.get('bounty_certainty'), EXACT),
            ('actual_node_type', dn.get('actual_node_type'), cn.get('actual_node_type'), EXACT),
            ('reference_node_type', dn.get('reference_node_type'), cn.get('reference_node_type'), EXACT),
            ('evidence_purpose', dn.get('evidence_purpose'), cn.get('evidence_purpose'), EXACT),
        ]
        for field, wl_v, sn_v, cmp in checks:
            if not cmp(wl_v, sn_v):
                out['mismatches'].append(
                    {'hand': hid, 'field': field, 'worklist': wl_v, 'snapshot': sn_v})
        # hard invariants
        if _sel(dn, 'confidence') == 'authoritative' and dn.get('decision_facing_state') == 'unknown':
            out['facing_unknown'] += 1
            out['mismatches'].append({'hand': hid, 'field': 'authoritative_facing_unknown'})
        if _pc(dn, 'price_applicable') is False and _pc(dn, 'callable_amount_bb') not in (None, 0, 0.0):
            out['nonprice_with_call'] += 1
            out['mismatches'].append(
                {'hand': hid, 'field': 'nonprice_with_call_price',
                 'callable': _pc(dn, 'callable_amount_bb')})
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
            # a STANDALONE 0.1xBB token (collapsed depth) — NOT the '0.12' inside a larger
            # number like '20.12BB' (REV6: the visible 'call 20.12BB' reviewed line).
            for m in re.finditer(r'(?<![\d.])(0\.1[0-9])\s?BB', body):
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
    """REV5: a realized contest reconciles iff
        sum(real pot-layer totals) == contestable pot,
        gross commitments == contestable + uncalled returns,
        sum(layer dead) == total dead money, and each layer total == eligible + dead.
    `total_committed_pot_bb` is the GROSS commitments (incl. uncalled); the layers sum to
    the CONTESTABLE pot. Returns a reason string or None."""
    layers = rc.get('pot_layers') or []
    gross = rc.get('total_committed_pot_bb')
    if gross is None:
        return 'missing_total_committed_pot'
    contestable = rc.get('contestable_pot_bb')
    uncalled = rc.get('uncalled_return_bb') or 0.0
    lsum = round(sum(l.get('total_layer_bb', 0.0) for l in layers), 2)
    if contestable is not None and abs(lsum - contestable) > 0.02:
        return 'layer_sum_%s_!=_contestable_%s' % (lsum, contestable)
    # gross == contestable + uncalled (contestable defaults to the layer sum)
    _cont = contestable if contestable is not None else lsum
    if abs(round(_cont + uncalled, 2) - gross) > 0.02:
        return 'gross_%s_!=_contestable_%s_+_uncalled_%s' % (gross, _cont, uncalled)
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


def worklist_bounty_consistency_violations(bnt):
    """REV4 B1: a worklist bounty_context must be internally consistent with its typed
    aggregate — no field may contradict not_applicable / empty eligibility. Returns a
    list of violation tokens ([] == ok)."""
    out = []
    agg = bnt.get('coverage_aggregate')
    if agg is None:
        return out   # no canonical context (hand absent) — out of scope for this gate
    elig = bnt.get('eligible_bounties_by_opponent')
    if agg == 'not_applicable':
        if elig:
            out.append('not_applicable_with_nonempty_eligible')
        if bnt.get('adjustment_applied_to_decision'):
            out.append('not_applicable_with_adjustment_applied')
        if bnt.get('hero_covers_relevant_villain') is not None:
            out.append('not_applicable_with_hero_covers_not_null')
        if bnt.get('collectibility_known'):
            out.append('not_applicable_with_collectibility_known')
    if agg in ('all', 'mixed') and not elig:
        out.append('collectible_aggregate_with_empty_eligible')
    bek = bnt.get('bounty_eligibility_known')
    if bek is not None and bool(bnt.get('collectibility_known')) != bool(bek):
        out.append('collectibility_known_is_not_eligibility_known')
    if bnt.get('adjustment_applied_to_decision') and agg not in ('all', 'mixed'):
        out.append('adjustment_applied_without_eligible_collectible')
    if not aggregate_reason_consistent(agg, bnt.get('coverage_reason') or bnt.get('reason')):
        out.append('aggregate_reason_contradiction')
    return out


def pot_semantic_violations(rc):
    """REV4 B3/B4/B5: main/side-pot SEMANTICS (not just arithmetic) on a realized
    contest. A side pot exists only when the eligible winner set changes; folded players
    are dead money only; legacy participant fields equal the canonical pot layers."""
    out = []
    layers = rc.get('pot_layers') or []
    for a, b in zip(layers, layers[1:]):
        if a['eligible_participants'] == b['eligible_participants']:
            out.append('unmerged_adjacent_identical_eligible')
            break
    for i in range(1, len(layers)):
        if layers[i]['kind'] == 'side' and \
                layers[i]['eligible_participants'] == layers[i - 1]['eligible_participants']:
            out.append('side_without_eligible_change')
            break
    mains = [i for i, l in enumerate(layers) if l['kind'] == 'main']
    if layers and mains != [0]:
        out.append('main_not_single_lowest')
    main_set = set(layers[0]['eligible_participants']) if layers else set()
    if set(rc.get('main_pot_participants') or []) != main_set:
        out.append('main_participants_mismatch')
    side_set = (set().union(*[set(l['eligible_participants']) for l in layers if l['kind'] == 'side'])
                if any(l['kind'] == 'side' for l in layers) else set())
    if set(rc.get('side_pot_participants') or []) != side_set:
        out.append('side_participants_mismatch')
    folded = set(rc.get('folded_players') or [])
    for l in layers:
        if folded & set(l['eligible_participants']):
            out.append('folded_in_eligible_set')
            break
    elig_all = (set().union(*[set(l['eligible_participants']) for l in layers]) if layers else set())
    if rc.get('realized_participant_count') != len(elig_all):
        out.append('participant_count_ne_eligible')
    # REV5 B3: a real pot layer needs >=2 eligible participants, OR exactly 1 eligible
    # plus folded dead money (an uncontested dead-money award). A 1-eligible-no-dead
    # layer is uncalled excess masquerading as a side pot; a 0-eligible layer is invalid.
    for l in layers:
        ne = len(l.get('eligible_participants') or [])
        dead = l.get('dead_money_bb', 0.0) or 0.0
        if ne == 0:
            out.append('zero_player_pot_layer')
            break
        if ne == 1 and dead <= 0.02:
            out.append('one_player_side_pot')
            break
    # REV5 B4: a Hero who LATER folded cannot win any layer, so realized bounty
    # capability must be empty — decision-time eligibility must NOT survive the fold.
    if rc.get('hero_remained_eligible') is False:
        if rc.get('realized_collectible_bounties'):
            out.append('hero_folded_but_realized_collectible_nonempty')
        if rc.get('hero_eligible_pot_layers'):
            out.append('hero_folded_but_eligible_layers_nonempty')
    prv = pot_reconciliation_violation(rc)
    if prv:
        out.append('reconcile:' + prv)
    return out


def gate_report_bounty(hands_idx, html):
    """REV4 B2: every rendered BOUNTY hand carries data-bounty-aggregate / -reason equal
    to the canonical decision-time context — proving the report consumes the canonical
    object and never reconstructs coverage from the legacy scalar."""
    out = {'checked': 0, 'mismatches': []}
    for m in re.finditer(
            r"<article[^>]*data-hand-id='(\w+)'[^>]*data-bounty-aggregate='([^']*)'"
            r"[^>]*data-bounty-reason='([^']*)'", html):
        hid, agg, rsn = m.group(1), m.group(2), m.group(3)
        h = hands_idx.get(hid) or hands_idx.get(hid[-8:])
        if h is None:
            continue
        out['checked'] += 1
        ctx = ds.build_decision_bounty_context(h)
        if (ctx.get('coverage_aggregate') != agg) or (ctx.get('coverage_reason') != rsn):
            out['mismatches'].append(
                {'hand': hid, 'field': 'rendered_bounty_ne_canonical', 'rendered': [agg, rsn],
                 'canonical': [ctx.get('coverage_aggregate'), ctx.get('coverage_reason')]})
    return out


def gate_report_decision_bounty(hands_idx, html):
    """REV5 B2: EVERY rendered per-decision bounty block (data-decision-action-index +
    data-bounty-aggregate/-reason/-applicability) equals build_decision_bounty_context(
    hand, that_index). Proves each decision in a multi-decision hand uses its OWN
    action-index context — not one article-level default. Compares per DECISION, not per
    article (the gate fails if a decision block carries another Hero action's context)."""
    bodies = decode_lazy_hands(html)
    out = {'checked': 0, 'mismatches': []}
    pat = re.compile(
        r"decision-bounty-meta' data-decision-action-index='(\d+)'"
        r"[^>]*data-bounty-aggregate='([^']*)'[^>]*data-bounty-reason='([^']*)'"
        r"[^>]*data-bounty-applicability='([^']*)'")
    for hid, body in bodies.items():
        h = hands_idx.get(str(hid)) or hands_idx.get(str(hid)[-8:])
        if h is None:
            continue
        for m in pat.finditer(body):
            idx, agg, rsn, app = int(m.group(1)), m.group(2), m.group(3), m.group(4)
            out['checked'] += 1
            ctx = ds.build_decision_bounty_context(h, idx)
            if (ctx.get('coverage_aggregate') != agg or ctx.get('coverage_reason') != rsn
                    or ctx.get('bounty_applicability') != app):
                out['mismatches'].append(
                    {'hand': hid, 'action_index': idx,
                     'rendered': [agg, rsn, app],
                     'canonical': [ctx.get('coverage_aggregate'), ctx.get('coverage_reason'),
                                   ctx.get('bounty_applicability')]})
    return out


def gate_report_visible_decision(hands_idx, html, worklist=None):
    """REV6 B2/B5: the USER-VISIBLE decision lesson grades the SAME action the worklist
    reviewed. Parses the RENDERED markdown — the visible 'Reviewed decision: <street>, call
    <X>BB, effective depth ≈<Y>BB' line plus the data-decision-action-index of the div that
    CONTAINS it — NOT a hidden span (the REV5 gate proved only hidden-metadata parity).
    Three checks:
      1. the visible block carries a data-decision-action-index;
      2. the visible street / call / depth equal build_decision_snapshot(hand, rendered_idx)
         (proves the lesson is built from the canonical snapshot, never gem_pot_odds' own
         first-all-in-call reconstruction — the 83526894 'turn 7.9BB' vs 'river 13.5BB' bug);
      3. the rendered index IS the canonical reviewed action. The authoritative reviewed
         action is the WORKLIST's (decision_kind -> _reviewed_action_index); a preflop-graded
         deviation/all-in is legitimately preflop even when Hero also acts later, so trusting
         the worklist avoids a false 'should be postflop'. Falls back to the ledger-inferred
         action only when no worklist item exists for the hand.
    Fails if the visible lesson uses a different action than the canonical reviewed one."""
    import gem_decision_snapshot as _ds
    # authoritative reviewed-action index per hand from the worklist (decision_kind-aware)
    wl_ridx = {}
    if worklist:
        from gem_analyst_worklist import _reviewed_action_index as _wl_rai
        _items = worklist.get('items') or {}
        _items = list(_items.values()) if isinstance(_items, dict) else _items
        for _it in _items:
            _hid = str(_it.get('hand_id') or '')
            _h = hands_idx.get(_hid) or hands_idx.get(_hid[-8:])
            if _h is None:
                continue
            _ri = _wl_rai(_h, _it.get('decision_kind'))
            if _ri is not None:
                wl_ridx[_hid] = _ri
                wl_ridx[_hid[-8:]] = _ri
    bodies = decode_lazy_hands(html)
    out = {'checked': 0, 'mismatches': []}
    # REV7: the action phrase is action-TYPED ('call XBB' / 'open to XBB' / 'fold facing XBB' /
    # 're-jam XBB over a YBB price'), so capture the whole phrase between street and depth.
    # REV8 D1: an authoritative selection renders 'Reviewed decision'; a ledger-inferred
    # fallback renders 'Inferred decision context'. The gate parses BOTH and validates the
    # SAME semantic invariants; a separate check below verifies the label matches the ref's
    # selection_confidence.
    line_pat = re.compile(
        r"(Reviewed decision|Inferred decision context):(?:\s*</strong>|\s*\*\*)?\s*"
        r"([A-Za-z]+),\s*(.+?),\s*effective depth\s*[≈~]?\s*([0-9.]+)\s*BB")
    call_amt_pat = re.compile(r"\bcall\s+([0-9.]+)\s*BB")
    idx_pat = re.compile(r"data-decision-action-index='(\d+)'")
    for hid, body in bodies.items():
        h = hands_idx.get(str(hid)) or hands_idx.get(str(hid)[-8:])
        if h is None:
            continue
        lm = line_pat.search(body)
        if not lm:
            continue
        out['checked'] += 1
        v_label = lm.group(1)
        v_street, v_phrase, v_depth = lm.group(2).lower(), lm.group(3).strip(), _f(lm.group(4))
        # the data-decision-action-index belongs to the DIV CONTAINING the visible reviewed
        # line — i.e. the NEAREST PRECEDING attribute, NOT the first in the body (a hidden
        # per-decision-bounty-meta span at an earlier Hero action index).
        pre = list(idx_pat.finditer(body[:lm.start()]))
        if not pre:
            out['mismatches'].append({'hand': hid, 'field': 'missing_decision_action_index'})
            continue
        ridx = int(pre[-1].group(1))
        snap = _ds.build_decision_snapshot(h, ridx)
        disp = _ds.reviewed_action_display(h, ridx, snap)
        if (snap.get('street') or '').lower() != v_street:
            out['mismatches'].append(
                {'hand': hid, 'field': 'visible_street_ne_snapshot',
                 'visible': v_street, 'snapshot': snap.get('street'), 'idx': ridx})
        # REV7 A2: the visible action phrase must EXACTLY equal the canonical action-typed
        # display (catches a non-call action rendered as 'call', or a wrong amount).
        if v_phrase != (disp.get('display_text') or ''):
            out['mismatches'].append(
                {'hand': hid, 'field': 'visible_action_ne_canonical_display',
                 'visible': v_phrase, 'canonical': disp.get('display_text'), 'idx': ridx})
        # REV10 B3: the VISIBLE depth is the canonical effective decision depth (callable <=
        # depth <= hero stack), the same value the report renders — never the bare stack-behind.
        sd = (snap.get('canonical_effective_decision_depth_bb')
              if snap.get('canonical_effective_decision_depth_bb') is not None
              else snap.get('effective_stack_at_decision_bb'))
        if sd is not None and abs(_f(sd) - v_depth) > 0.15:
            out['mismatches'].append(
                {'hand': hid, 'field': 'visible_depth_ne_snapshot',
                 'visible': v_depth, 'snapshot': sd, 'idx': ridx})
        # REV7 B1: independent semantic invariants on the VISIBLE call amount — NOT derived
        # from the same raw to_call. A displayed call must be the CALLABLE amount, never exceed
        # Hero's effective depth, and never be the raw overjam.
        cm = call_amt_pat.search(v_phrase)
        if cm:
            v_call = _f(cm.group(1))
            callable_amt = _f(snap.get('callable_amount_bb'))
            raw_to_match = _f(snap.get('raw_amount_to_match_bb'))
            if sd is not None and v_call is not None and v_call > _f(sd) + 0.20:
                out['mismatches'].append(
                    {'hand': hid, 'field': 'visible_call_gt_effective_depth',
                     'visible_call': v_call, 'depth': sd, 'idx': ridx})
            # REV11 B4: callable / raw can be None for a non-price action — the overjam/callable
            # checks apply ONLY to a priced call (both present).
            if v_call is not None and callable_amt is not None and v_call > callable_amt + 0.20:
                out['mismatches'].append(
                    {'hand': hid, 'field': 'visible_call_gt_callable',
                     'visible_call': v_call, 'callable': callable_amt, 'idx': ridx})
            # if there is an uncallable overjam, the visible price must be the CALLABLE amount,
            # never the raw to_match (the REV6 83974506 'call 111.46BB' bug).
            if (raw_to_match is not None and callable_amt is not None and v_call is not None
                    and (raw_to_match - callable_amt) > 0.20 and abs(v_call - raw_to_match) <= 0.20):
                out['mismatches'].append(
                    {'hand': hid, 'field': 'visible_call_is_raw_overjam',
                     'visible_call': v_call, 'raw_to_match': raw_to_match,
                     'callable': callable_amt, 'idx': ridx})
        # authoritative reviewed action: the worklist's (decision_kind-aware) if present,
        # else the ledger-inferred default.
        canon_idx = (wl_ridx.get(str(hid)) or wl_ridx.get(str(hid)[-8:])
                     or _ds.infer_reviewed_action_index(h))
        if canon_idx is not None and ridx != canon_idx:
            cs = _ds.build_decision_snapshot(h, canon_idx)
            if snap.get('street') != cs.get('street'):
                out['mismatches'].append(
                    {'hand': hid, 'field': 'rendered_idx_not_reviewed_action',
                     'rendered_idx': ridx, 'reviewed_idx': canon_idx,
                     'rendered_street': snap.get('street'), 'reviewed_street': cs.get('street')})
        # REV8 D1: the visible LABEL must match the selection AUTHORITY — a worklist-selected
        # decision is "Reviewed decision"; a ledger-inferred fallback must be "Inferred
        # decision context" and never presented as analyst-selected. Only enforced when the
        # worklist is supplied (the authority source).
        if worklist is not None:
            _is_auth = (str(hid) in wl_ridx or str(hid)[-8:] in wl_ridx)
            if _is_auth and v_label != 'Reviewed decision':
                out['mismatches'].append(
                    {'hand': hid, 'field': 'authoritative_labelled_inferred', 'label': v_label})
            if (not _is_auth) and v_label == 'Reviewed decision':
                out['mismatches'].append(
                    {'hand': hid, 'field': 'inferred_labelled_reviewed', 'label': v_label})
    return out


def _gate_reviewed_ref(h, hid, wl_kind):
    """Build the reviewed ref the SAME way the report does: worklist decision_kind (kind-aware)
    when present, else ledger-inferred. Returns the canonical ref dict."""
    import gem_decision_snapshot as _ds
    kind = wl_kind.get(str(hid)) or wl_kind.get(str(hid)[-8:])
    if kind:
        from gem_analyst_worklist import _reviewed_action_index as _wl_rai
        ridx = _wl_rai(h, kind)
        return _ds.build_reviewed_decision_ref(h, ridx, kind, 'worklist_reviewed_action')
    return _ds.build_reviewed_decision_ref(h)


def gate_report_full_render(hands_idx, html, worklist=None):
    """REV8 E1: parse the COMPLETE rendered hand article (not only the reviewed-decision line)
    and prove EVERY decision-specific consumer agrees with the selected action's canonical
    view — range evidence, verdict text, all-in math, PKO bounty teaching, price applicability,
    and the authoritative/inferred label. Catches the REV7 boundary leaks that gate F (which
    only validated the reviewed-decision sentence) missed."""
    import gem_decision_snapshot as _ds
    wl_kind = {}
    if worklist:
        _items = worklist.get('items') or {}
        _items = list(_items.values()) if isinstance(_items, dict) else _items
        for _it in _items:
            _hid = str(_it.get('hand_id') or '')
            if _hid and _it.get('decision_kind'):
                wl_kind[_hid] = _it['decision_kind']
                wl_kind[_hid[-8:]] = _it['decision_kind']
    bodies = decode_lazy_hands(html)
    out = {'checked': 0, 'mismatches': []}
    _AGGR = ('first_in_open', '3bet', '4bet', '5bet_plus', 'open_shove',
             'rejam_over_live_raise', 'overjam_with_side_pot', 'bet')
    _ALLIN = ('call_vs_jam', 'call_off', 'open_shove', 'rejam_over_live_raise',
              'overjam_with_side_pot')
    for hid, body in bodies.items():
        h = hands_idx.get(str(hid)) or hands_idx.get(str(hid)[-8:])
        if h is None:
            continue
        ref = _gate_reviewed_ref(h, hid, wl_kind)
        if not ref:
            continue
        out['checked'] += 1
        kind = ref.get('hero_action_kind')
        street = ref.get('street')
        price_appl = ref.get('price_applicable')
        bapp = ref.get('bounty_applicability')
        facing = ref.get('decision_facing_state')

        def viol(field, **kw):
            d = {'hand': hid, 'field': field}
            d.update(kw)
            out['mismatches'].append(d)

        # 1) a non-price decision (first-in / open / bet / check) must not show a call price
        if price_appl is False:
            if 'Pot odds:' in body:
                viol('nonprice_action_shows_pot_odds', kind=kind, facing=facing)
            if 'Required equity:' in body:
                viol('nonprice_action_shows_required_equity', kind=kind, facing=facing)
            if 'EV of call:' in body or '**Verdict:** _' in body:
                viol('nonprice_action_shows_call_verdict', kind=kind)
        # 2) a NON-all-in reviewed action must not show all-in (call-vs-jam) math as selected
        if kind not in _ALLIN and re.search(r'All-in math|call-vs-jam math|the complete call-vs-jam', body):
            viol('non_allin_action_shows_allin_math', kind=kind)
        # 3) an AGGRESSIVE preflop reviewed action must not show a 'call a jam' range as selected
        if kind in _AGGR and re.search(r'call a (UTG|MP|HJ|CO|BTN|SB|LJ)', body):
            viol('aggressive_action_shows_call_jam_range', kind=kind)
        # 4) a POSTFLOP reviewed action that shows a preflop range block must label it as
        #    earlier context (never present it as the selected decision's range evidence)
        if street and street != 'preflop' and re.search(r'(first-in open|Range Logic|RFI core)', body):
            if 'Earlier preflop context' not in body:
                viol('postflop_selected_shows_preflop_range_as_selected', street=street)
        # 5) a not_applicable bounty action must show NO collectible-bounty / positive-incentive
        if bapp == 'not_applicable':
            if 'bounty collectible' in body:
                viol('not_applicable_bounty_collectible_teaching')
            if 'positive incentive to continue' in body:
                viol('not_applicable_bounty_positive_incentive')
        # 6) REV9: a FACING-LIMP decision must NEVER render as first-in (another player limped).
        if facing == 'facing_limp' and re.search(
                r'(?:Reviewed decision|Inferred decision context):</strong>\s*[a-z]+,\s*fold first-in', body):
            viol('facing_limp_rendered_first_in')
        # 7) REV10 D: a NO-HERO-DECISION hand (a walk) must never fabricate an 'act' decision,
        #    a price, or bounty teaching.
        if ref.get('no_hero_decision') or ref.get('actual_node_type') == 'no_hero_decision':
            if re.search(r'(?:Reviewed decision|Inferred decision context):</strong>\s*[a-z]+,\s*act', body):
                viol('no_decision_rendered_as_act')
            if re.search(r'Bounty trust:|Bounty \(combined\)|bounty collectible', body):
                viol('no_decision_shows_bounty_teaching')
            if 'Pot odds:' in body:
                viol('no_decision_shows_pot_odds')
        # 8/9) REV10 B2/B3: a fold-facing displayed price must be the CALLABLE amount (never the
        #    raw wager) and must never exceed the canonical effective decision depth.
        if kind == 'fold' and price_appl:
            _cap = ref.get('callable_amount_bb')
            _depth = ref.get('canonical_effective_decision_depth_bb')
            _m = re.search(r'fold facing\s*([0-9.]+)\s*BB', body)
            if _m:
                _shown = float(_m.group(1))
                if _cap is not None and _shown - float(_cap) > 0.1:
                    viol('fold_price_exceeds_callable', shown=_shown, callable=_cap)
                if _depth is not None and _shown - float(_depth) > 0.1:
                    viol('fold_price_exceeds_effective_depth', shown=_shown, depth=_depth)
        # 10) REV10 B3 contract: the callable price can never exceed the effective decision depth.
        if price_appl:
            _cap = ref.get('callable_amount_bb')
            _depth = ref.get('canonical_effective_decision_depth_bb')
            if _cap is not None and _depth is not None and float(_cap) - float(_depth) > 0.1:
                viol('callable_exceeds_effective_depth', callable=_cap, depth=_depth)
    return out


def gate_ledger_oracle(hands_idx, worklist, html):
    """H. (REV11 G) INDEPENDENT-ORACLE parity + semantic invariants. The expected answer comes
    from `_qa_ledger_oracle` (raw ledger only — it imports NONE of canonical_node_type /
    serialize_reviewed_decision_node / reviewed_action_display), so this is NOT self-agreement.
    For every authoritative item: oracle == canonical view == serialized worklist node == visible
    reviewed line. Plus the G3 semantic invariants over all 844 hands."""
    bodies = decode_lazy_hands(html)
    items = worklist.get('items') or {}
    if isinstance(items, dict):
        items = list(items.values())
    out = {'authoritative_checked': 0, 'all_hands_checked': 0, 'mismatches': []}

    def viol(hid, field, **kw):
        d = {'hand': hid, 'field': field}
        d.update(kw)
        out['mismatches'].append(d)

    # ── 5-surface parity on the authoritative items ──
    for it in items:
        hid = str(it.get('hand_id') or '')
        h = hands_idx.get(hid) or hands_idx.get(hid[-8:])
        if h is None:
            continue
        kind = it.get('decision_kind') or it.get('bucket')
        ridx = _reviewed_action_index(h, kind)
        if ridx is None:
            continue
        out['authoritative_checked'] += 1
        o = oracle.oracle_identity(h, ridx)
        snap = ds.build_decision_snapshot(h, ridx)
        dn = it.get('decision_node') or {}
        # oracle <-> canonical
        if not oracle.semantic_consistent(o['action_semantics'], snap.get('hero_action_kind')):
            viol(hid, 'oracle_vs_canonical_kind', oracle_sem=o['action_semantics'],
                 canonical_kind=snap.get('hero_action_kind'))
        if o['became_all_in'] != bool(snap.get('became_all_in_on_this_action')):
            viol(hid, 'oracle_vs_canonical_all_in', oracle=o['became_all_in'],
                 canonical=snap.get('became_all_in_on_this_action'))
        if o['raw_action'] != (snap.get('hero_actual_action') or dn.get('hero_actual_action')) \
                and o['raw_action'] is not None:
            viol(hid, 'oracle_vs_canonical_raw_action', oracle=o['raw_action'],
                 canonical=snap.get('hero_actual_action'))
        # canonical <-> worklist node
        if dn.get('hero_action_kind') and dn['hero_action_kind'] != snap.get('hero_action_kind'):
            viol(hid, 'worklist_vs_canonical_kind', worklist=dn.get('hero_action_kind'),
                 canonical=snap.get('hero_action_kind'))
        if dn.get('actual_node_type') and dn['actual_node_type'] != snap.get('actual_node_type'):
            viol(hid, 'worklist_vs_canonical_node', worklist=dn.get('actual_node_type'),
                 canonical=snap.get('actual_node_type'))
        # visible reviewed line <-> canonical display
        body = bodies.get(str(hid)) or bodies.get(str(hid)[-8:]) or ''
        disp = ds.reviewed_action_display(h, ridx, snap).get('display_text') or ''
        # the canonical display itself may contain commas; capture up to the tag, then strip the
        # optional ", effective depth ≈XBB" suffix before comparing.
        m = re.search(r'(?:Reviewed decision|Inferred decision context):</strong>\s*[a-z]+,\s*([^<]+)', body)
        if m and disp:
            shown = re.sub(r',?\s*effective depth.*$', '', m.group(1)).strip()
            if shown != disp.strip():
                viol(hid, 'visible_line_vs_canonical_display', visible=shown, canonical=disp)

    # ── G3 semantic invariants over EVERY hand (oracle-derived) ──
    for h in (hands_idx.get('_all_hands') or []):
        hid = str(h.get('tournament_hand_id') or h.get('id') or '')
        ridx = ds.infer_reviewed_action_index(h)
        o = oracle.oracle_identity(h, ridx)
        snap = ds.build_decision_snapshot(h, ridx)
        out['all_hands_checked'] += 1
        k = snap.get('hero_action_kind')
        # ledger bets postflop (non-all-in) => canonical kind 'bet', never first_in_open
        if o['action_semantics'] == 'bet' and k == 'first_in_open':
            viol(hid, 'postflop_bet_typed_first_in_open', kind=k)
        # ledger raise/jam over a jam => re_jam family, never a call
        if o['action_semantics'] == 're_jam' and k in ('call', 'call_vs_jam', 'call_off'):
            viol(hid, 'rejam_typed_call', kind=k)
        # first-in complete => not call_vs_jam node
        if o['action_semantics'] == 'complete' and snap.get('actual_node_type') == 'call_vs_jam':
            viol(hid, 'first_in_complete_typed_call_vs_jam')
        # first-in short all-in => short_all_in, never limp/call_off
        if o['action_semantics'] == 'short_all_in' and k in ('call', 'call_off') \
                and snap.get('actual_node_type') != 'first_in_short_all_in':
            viol(hid, 'underblind_all_in_typed_ordinary_call', kind=k)
        # no voluntary wager faced => no voluntary raw price on the contract
        if not o['has_voluntary_wager_faced'] and snap.get('raw_amount_to_match_bb') is not None:
            viol(hid, 'no_wager_carries_raw_price', raw=snap.get('raw_amount_to_match_bb'))
    return out


_NODE_GRID_VERB = {
    'first_in_limp': ('complete', 'limp'),
    'sb_complete_after_limp': ('complete',),
    'overlimp': ('limp', 'overlimp', 'call'),
    'first_in_open': ('open to', 'raise', 'bet'),
    'fold_first_in': ('fold',), 'fold_over_limp': ('fold',), 'fold_vs_open': ('fold',),
    'fold_vs_jam': ('fold',), 'fold_vs_three_bet': ('fold',), 'postflop_fold': ('fold',),
    'check_option': ('check',), 'postflop_check': ('check',),
    'first_in_short_all_in': ('all-in',),
    'first_in_open_shove': ('jam', 'all-in'), 'iso_shove': ('jam', 'all-in'),
    're_jam': ('jam', 'all-in'), 'postflop_jam': ('jam', 'all-in'),
    'three_bet': ('3-bet to', 'raise'), 'four_bet': ('4-bet to', 'raise'),
    'iso_raise': ('raise', 'open to'),
    'call_vs_jam': ('call',), 'call_vs_open': ('call',), 'call_vs_three_bet': ('call',),
    'postflop_call': ('call',), 'postflop_bet': ('bet',), 'postflop_raise': ('raise',),
}
# nodes whose grid row must NEVER read as an ordinary priced "Call X / need Y%"
_NO_PLAIN_CALL_ROW = ('first_in_limp', 'sb_complete_after_limp', 'first_in_short_all_in',
                      're_jam', 'first_in_open_shove', 'iso_shove')


_ROW_AMT_RE = r'([\d]+(?:\.[\d]+)?)\s*BB'
_ROW_LABEL_PATS = (
    ('adds', r'adds\s+' + _ROW_AMT_RE),
    ('raises by', r'raises by\s+' + _ROW_AMT_RE),
    ('all-in to', r'all-in to\s+' + _ROW_AMT_RE),
    ('all-in', r'all-in\s+' + _ROW_AMT_RE),
    ('open to', r'open to\s+' + _ROW_AMT_RE),
    ('3-bet to', r'3-bet to\s+' + _ROW_AMT_RE),
    ('4-bet to', r'4-bet to\s+' + _ROW_AMT_RE),
    ('5-bet to', r'5-bet to\s+' + _ROW_AMT_RE),
    ('raise to', r'raise to\s+' + _ROW_AMT_RE),
    ('iso-raise', r'iso-raise to\s+' + _ROW_AMT_RE),
    ('jam', r'jam\s+' + _ROW_AMT_RE),
    ('bet', r'bet\s+' + _ROW_AMT_RE),
    ('overlimp', r'overlimp\s+' + _ROW_AMT_RE),
    ('complete', r'complete\s+' + _ROW_AMT_RE),
    ('limp', r'limp\s+' + _ROW_AMT_RE),
    ('call', r'call\s+' + _ROW_AMT_RE),
)


def _parse_action_row(txt):
    """REV13 E1: extract (amount_label, amount, total_to) from ONE visible Hero action-grid row.
    'all-in to Y' is captured separately as the total; the primary label is the FIRST sizing token
    (so 'adds X, all-in to Y' -> label='adds', amount=X, total=Y). Returns (None, None, total) for a
    fold/check (no amount)."""
    t = txt or ''
    tt = None
    m_tt = re.search(r'all-in to\s+' + _ROW_AMT_RE, t, re.I)
    if m_tt:
        tt = float(m_tt.group(1))
    for lbl, pat in _ROW_LABEL_PATS:
        m = re.search(pat, t, re.I)
        if m:
            return lbl, float(m.group(1)), tt
    return None, None, tt


def _row_close(a, b, tol=0.06):
    return a is not None and b is not None and abs(round(a, 1) - round(b, 1)) <= tol


def check_action_row_numeric(lbl, amt, tt, oz):
    """REV13 E3/T5: compare ONE parsed action row to the INDEPENDENT sizing oracle `oz`. Returns the
    list of mismatch fields (empty == consistent). The gate FAILS a row that labels the raise
    INCREMENT as chips Hero 'adds' (the REV12 B1 defect): `adds X` must equal amount_added_bb, never
    raise_increment_bb."""
    sem = oz.get('action_semantics')
    added = oz.get('amount_added_bb')
    total = oz.get('total_to_bb')
    raise_inc = oz.get('raise_increment_bb')
    cont = oz.get('continue_component_bb')
    callable_amt = oz.get('callable_amount_bb')
    fields = []
    if lbl is None:
        return fields                      # no amount on this row (fold/check) — nothing numeric
    if lbl == 'adds':
        if not _row_close(amt, added):
            fields.append('adds_value_not_amount_added')
        if raise_inc is not None and _row_close(amt, raise_inc) and not _row_close(added, raise_inc):
            fields.append('amount_label_value_mismatch')      # "adds" == raise_increment
        if tt is not None and not _row_close(tt, total):
            fields.append('all_in_to_mismatch')
        # REV15 G8/B4: an IMPOSSIBLE row — the chips "adds X" can NEVER exceed the "all-in to Y" total
        # ("adds 12.3BB, all-in to 12.2BB"). amount_added <= live_betting_total_to always.
        if tt is not None and amt is not None and amt > tt + 0.06:
            fields.append('amount_added_exceeds_all_in_total')
    elif lbl == 'raises by':
        if not _row_close(amt, raise_inc):
            fields.append('raises_by_value_not_raise_increment')
        if tt is not None and not _row_close(tt, total):
            fields.append('all_in_to_mismatch')
    elif lbl in ('all-in', 'all-in to'):
        expect = added if sem == 'short_all_in' else total
        if not _row_close(amt, expect):
            fields.append('all_in_value_mismatch')
    elif lbl in ('open to', '3-bet to', '4-bet to', '5-bet to', 'raise to', 'iso-raise'):
        if not _row_close(amt, total):
            fields.append('total_to_value_mismatch')
    elif lbl == 'call':
        # REV14 B6: a literal call's visible price MUST equal the callable / continue component
        # (the live amount Hero commits), NEVER an ante-inflated amount, and a call can NEVER carry a
        # raise increment. The oracle's amount_added for a call already equals the callable price.
        _call_expect = cont if cont is not None else (callable_amt if callable_amt is not None else added)
        if not _row_close(amt, _call_expect):
            fields.append('call_value_not_callable')
        if raise_inc not in (None, 0):
            fields.append('call_has_raise_increment')
    elif lbl in ('bet', 'complete', 'limp', 'overlimp'):
        if not _row_close(amt, added):
            fields.append('added_value_mismatch')
    elif lbl == 'jam':
        # a Hero all-in still showing a bare "JAM X" (no adds/all-in label) — REV13 requires the
        # ActionSizingContract label, so a bare numeric jam is itself a defect.
        fields.append('unlabelled_jam_amount')
    return fields


def _hero_grid_rows(body, pos=None):
    """All Hero action-grid rows in DOM order (== ledger order), flattening any nested span (the
    villain-mini badge, the 'need X%' pot-pct, the annotation) so the full visible row text is
    captured. Hero rows are identified by the `is-hero` class the grid stamps on them (line 1144 of
    _hand_grid) — the rendered HTML uses DOUBLE quotes, which the REV12 single-quote regex never
    matched (so that gate was vacuous and missed B1)."""
    rows = []
    for _gm in re.finditer(r'<span class="grid-action ([^"]*)">', body):
        cls = _gm.group(1)
        _rest = body[_gm.end():]
        _end = re.search(r'<span class="grid-action |</td>', _rest)
        _seg = _rest[:_end.start()] if _end else _rest[:300]
        _txt = re.sub(r'<[^>]+>', '', _seg).strip()
        rows.append((cls, _txt))
    return [(cls, txt) for cls, txt in rows if 'is-hero' in cls]


def gate_action_row_parity(hands_idx, worklist, html):
    """REV13 E/B4/B6: NUMERIC action-row parity for ALL authoritative selected actions. Locates the
    EXACT selected Hero row (by Hero's per-hand action ordinal — never a token borrowed from another
    action), parses its visible amount LABEL + VALUE + total-to, and compares them to the INDEPENDENT
    ledger sizing oracle (`_qa_ledger_oracle.oracle_sizing`, which calls NO production formatter). A
    row that labels the raise increment as 'adds' (REV12 B1), or whose displayed value disagrees with
    the canonical field it claims, FAILS. Emits one DETAILED record per authoritative row (observed
    text/label/value + expected type/value), not just summary counts (REV12 B4)."""
    bodies = decode_lazy_hands(html)
    items = worklist.get('items') or {}
    if isinstance(items, dict):
        items = list(items.values())
    out = {'authoritative_action_rows_checked': 0, 'semantic_mismatches': 0,
           'amount_type_mismatches': 0, 'verb_mismatches': 0, 'row_not_found': 0,
           'mismatches': [], 'records': []}
    for it in items:
        hid = str(it.get('hand_id') or '')
        h = hands_idx.get(hid) or hands_idx.get(hid[-8:])
        if h is None:
            continue
        kind = it.get('decision_kind') or it.get('bucket')
        ridx = _reviewed_action_index(h, kind)
        if ridx is None:
            continue
        body = bodies.get(hid) or bodies.get(hid[-8:]) or ''
        snap = ds.build_decision_snapshot(h, ridx)
        node = snap.get('actual_node_type')
        pos = snap.get('hero_position') or '?'
        oz = oracle.oracle_sizing(h, ridx)
        contract = ds.build_action_sizing_contract(h, ridx)   # production display contract (labels)
        canon_req_eq = snap.get('required_equity_pct')        # canonical required equity (capsule value)
        out['authoritative_action_rows_checked'] += 1
        led = h.get('action_ledger') or []
        hero = h.get('hero', 'Hero')
        # the SELECTED row = Hero's `ordinal`-th non-posts action (DOM Hero rows are in ledger order)
        hero_ordinal = sum(1 for i, a in enumerate(led)
                           if i <= ridx and a.get('player') == hero and a.get('action') != 'posts')
        hero_rows = _hero_grid_rows(body, pos)
        selected_text = ''
        if 1 <= hero_ordinal <= len(hero_rows):
            selected_text = hero_rows[hero_ordinal - 1][1]
        lbl, amt, tt = _parse_action_row(selected_text)
        mism = []
        # A body that renders NO action grid at all (no Hero rows) is N/A for action-row parity —
        # the grid is a specific render surface a partial/synthetic render may omit. A MISSING row
        # when the grid IS present (Hero rows exist but the reviewed ordinal is out of range) is a
        # real failure. This keeps the gate strict on the full report (every authoritative hand has
        # a grid) without false-failing gridless bodies.
        grid_absent = not hero_rows
        if not selected_text and not grid_absent:
            out['row_not_found'] += 1
            mism.append('selected_row_not_found')
        # 1) the expected verb token must appear in the SELECTED row (never borrowed from another)
        want = _NODE_GRID_VERB.get(node)
        if selected_text and want and not any(w in selected_text.lower() for w in want):
            out['verb_mismatches'] += 1
            mism.append('action_row_verb_missing')
        # 2) the selected non-priced action must never read as an ordinary "Call X / need Y%"
        if node in _NO_PLAIN_CALL_ROW and re.search(r'call\s+[\d.]+\s*bb.{0,40}need', selected_text.lower()):
            out['semantic_mismatches'] += 1
            mism.append('action_row_plain_call_potodds')
        # 3) NUMERIC: the visible label/value/total must match the independent sizing oracle
        num_fields = check_action_row_numeric(lbl, amt, tt, oz)
        if num_fields:
            out['amount_type_mismatches'] += 1
            mism.extend(num_fields)
        # 4) REQUIRED-EQUITY parity (REV14 B5): a Hero call's visible "need X%" must equal the
        # canonical required_equity (the capsule value, from the contestable pot) AND the independent
        # oracle's contestable-pot required equity — never a raw running-pot recompute (83915165 56%).
        _m_need = re.search(r'need\s+([\d.]+)\s*%', selected_text)
        observed_need = float(_m_need.group(1)) if _m_need else None
        if observed_need is not None:
            if canon_req_eq is not None and abs(observed_need - canon_req_eq) > 0.6:
                out['amount_type_mismatches'] += 1
                mism.append('required_equity_row_vs_canonical_mismatch')
            if oz.get('required_equity_pct') is not None and abs(observed_need - oz['required_equity_pct']) > 0.6:
                out['amount_type_mismatches'] += 1
                mism.append('required_equity_row_vs_oracle_mismatch')
        # 5) COMPOSITE DISPLAY (REV14 B7): a composite all-in row "adds X, all-in to Y" must map its
        # 'adds' value to amount_added and its 'all-in to' value to live_total_to — never one
        # ambiguous amount_type. (The numeric check above already verifies the 'adds' value ==
        # amount_added and the 'all-in to' value == total_to; here we record the typed display.)
        _prim = (contract.get('primary_display') or {})
        _sec = contract.get('secondary_display')
        if lbl == 'adds' and tt is not None and _sec is not None:
            # a true composite: the secondary 'all-in to' value must equal live_total_to
            if _sec.get('field') != 'live_betting_total_to_bb':
                out['amount_type_mismatches'] += 1
                mism.append('composite_secondary_field_wrong')
        rec = {
            'hand_id': hid,
            'selected_action_index': ridx,
            'selected_street': snap.get('street'),
            'node': node,
            'action_semantics': oz.get('action_semantics'),
            'observed_row_text': selected_text or None,
            'observed_amount_label': lbl,
            'observed_amount': amt,
            'observed_total_to': tt,
            'observed_need_pct': observed_need,
            'primary_display': _prim,
            'secondary_display': _sec,
            'expected_amount_added_bb': oz.get('amount_added_bb'),
            'expected_live_total_to_bb': oz.get('total_to_bb'),
            'expected_continue_component_bb': oz.get('continue_component_bb'),
            'expected_raise_increment_bb': oz.get('raise_increment_bb'),
            'expected_required_equity_pct': canon_req_eq,
            'oracle_required_equity_pct': oz.get('required_equity_pct'),
            'grid_absent': grid_absent,
            'mismatch_fields': mism,
        }
        out['records'].append(rec)
        if mism:
            out['mismatches'].append({'hand': hid, 'node': node, 'observed_row': selected_text,
                                      'observed_label': lbl, 'observed_amount': amt,
                                      'expected_added': oz.get('amount_added_bb'),
                                      'expected_total_to': oz.get('total_to_bb'),
                                      'fields': mism})
    out['total_mismatches'] = (out['semantic_mismatches'] + out['amount_type_mismatches']
                               + out['verb_mismatches'] + out['row_not_found'])
    return out


def check_view_node_parity(view, node):
    """REV13 F/T5: the serialized decision_node must be an EXACT serialization of the canonical
    ReviewedDecisionView — no serializer may 'clean' or override a view field. Returns the list of
    fields where the node and the view disagree (empty == exact). Used by the deep-parity gate AND
    the failure-injection test (restore a non-price callable on the view and prove this fails)."""
    fields = []
    ref = view.get('decision_ref') or {}
    snap = view.get('snapshot') or {}
    # 1) the two foundational canonical contracts must be byte-equal
    if node.get('price_contract') != view.get('price_contract'):
        fields.append('price_contract')
    if node.get('action_sizing_contract') != view.get('action_sizing_contract'):
        fields.append('action_sizing_contract')
    # 2) action identity
    if node.get('hero_action_kind') != view.get('hero_action_kind'):
        fields.append('hero_action_kind')
    if node.get('actual_node_type') != ref.get('actual_node_type'):
        fields.append('actual_node_type')
    if node.get('hero_action_index') != view.get('hero_action_index'):
        fields.append('hero_action_index')
    # 3) facing state
    if node.get('decision_facing_state') != ref.get('decision_facing_state'):
        fields.append('decision_facing_state')
    # 4) stack contract
    sc = node.get('stack_contract') or {}
    if sc.get('effective_stack_at_decision_bb') != snap.get('canonical_effective_decision_depth_bb'):
        fields.append('stack_effective_depth')
    if sc.get('hero_stack_before_action_bb') != snap.get('hero_stack_before_action_bb'):
        fields.append('stack_hero_before')
    # 5) selection
    sel = node.get('selection') or {}
    if sel.get('source') != view.get('selection_source'):
        fields.append('selection_source')
    if sel.get('confidence') != view.get('selection_confidence'):
        fields.append('selection_confidence')
    # 6) bounty context (the reviewed-index applicability/certainty, not a hand-level default)
    if node.get('bounty_applicability') != ref.get('bounty_applicability'):
        fields.append('bounty_applicability')
    if node.get('bounty_certainty') != ref.get('bounty_certainty'):
        fields.append('bounty_certainty')
    return fields


def gate_canonical_view_node_parity(hands_idx, worklist):
    """REV13 Part F/B2: for EVERY authoritative worklist item, deep-compare the serialized
    decision_node against the canonical ReviewedDecisionView it is supposed to serialize — the
    REV12 defect was the worklist's nested node disagreeing with the embedded view on
    `price_contract.callable_amount_bb` (47/77). The expected object is the supplied view; the
    serializer must not alter a field. Emits one detailed record per authoritative item."""
    items = worklist.get('items') or {}
    if isinstance(items, dict):
        items = list(items.values())
    out = {'authoritative_items_checked': 0, 'mismatches': 0,
           'price_contract_mismatches': 0, 'sizing_mismatches': 0, 'records': []}
    for it in items:
        hid = str(it.get('hand_id') or '')
        h = hands_idx.get(hid) or hands_idx.get(hid[-8:])
        if h is None:
            continue
        kind = it.get('decision_kind') or it.get('bucket')
        ridx = _reviewed_action_index(h, kind)
        if ridx is None:
            continue
        view = ds.build_reviewed_decision_view(h, ridx, kind, 'worklist_reviewed_action')
        node = ds.serialize_reviewed_decision_node(h, ridx, kind, 'worklist_reviewed_action')
        fields = check_view_node_parity(view, node)
        out['authoritative_items_checked'] += 1
        if fields:
            out['mismatches'] += 1
            if 'price_contract' in fields:
                out['price_contract_mismatches'] += 1
            if 'action_sizing_contract' in fields:
                out['sizing_mismatches'] += 1
        out['records'].append({
            'hand_id': hid,
            'selected_action_index': ridx,
            'node_type': node.get('actual_node_type'),
            'price_applicable': (node.get('price_contract') or {}).get('price_applicable'),
            'node_price_callable_bb': (node.get('price_contract') or {}).get('callable_amount_bb'),
            'view_price_callable_bb': (view.get('price_contract') or {}).get('callable_amount_bb'),
            'continue_component_bb': (node.get('action_sizing_contract') or {}).get('continue_component_bb'),
            'mismatch_fields': fields,
        })
    return out


def gate_persisted_view_node_parity(worklist):
    """REV14 H4/B8: PERSISTED parity — compares the worklist's STORED item['reviewed_decision_view']
    and item['decision_node'] WITHOUT rebuilding either object. This proves the EXPORTED worklist
    embeds the SAME serialized view it ships (a builder-parity gate that reconstructs both sides could
    miss corruption introduced during persistence/packaging). Builder parity stays a SEPARATE gate
    (gate_canonical_view_node_parity)."""
    items = worklist.get('items') or {}
    if isinstance(items, dict):
        items = list(items.values())
    out = {'persisted_items_checked': 0, 'items_with_both_objects': 0, 'mismatches': 0, 'records': []}
    for it in items:
        view = it.get('reviewed_decision_view')
        node = it.get('decision_node')
        out['persisted_items_checked'] += 1
        if not isinstance(view, dict) or not isinstance(node, dict):
            continue                       # degenerate/stack-less item carries no canonical view — N/A
        out['items_with_both_objects'] += 1
        fields = []
        if node.get('price_contract') != view.get('price_contract'):
            fields.append('price_contract')
        if node.get('action_sizing_contract') != view.get('action_sizing_contract'):
            fields.append('action_sizing_contract')
        if fields:
            out['mismatches'] += 1
        out['records'].append({
            'hand_id': it.get('hand_id'),
            'node_price_callable_bb': (node.get('price_contract') or {}).get('callable_amount_bb'),
            'view_price_callable_bb': (view.get('price_contract') or {}).get('callable_amount_bb'),
            'mismatch_fields': fields,
        })
    return out


def check_relational_contract(sc):
    """REV15 B4/G7: the RELATIONAL invariants WITHIN one ActionSizingContract — a gate that validates
    each field independently (REV14) accepts an internally-impossible contract. Returns the list of
    violated relationships (empty == internally consistent)."""
    f = []
    aa = sc.get('amount_added_bb')
    lt = sc.get('live_betting_total_to_bb')
    lb = sc.get('live_street_committed_before_bb')
    dead = sc.get('dead_forced_posts_bb')
    pot = sc.get('pot_contribution_total_bb')
    sb = sc.get('hero_stack_before_bb')
    sa = sc.get('hero_stack_after_bb')
    allin = bool(sc.get('became_all_in'))
    _c = lambda a, b: (a is not None and b is not None and abs(a - b) <= 0.06)
    if aa is not None and aa < -0.06:
        f.append('amount_added_negative')
    if lb is not None and aa is not None and lt is not None and not _c(lt, round(lb + aa, 2)):
        f.append('live_total_ne_live_before_plus_added')
    if dead is not None and lt is not None and pot is not None and not _c(pot, round(dead + lt, 2)):
        f.append('pot_ne_dead_plus_live_total')
    if allin:
        if sa is not None and abs(sa) > 0.06:
            f.append('allin_stack_after_nonzero')
        if sb is not None and aa is not None and not _c(aa, sb):
            f.append('allin_amount_added_ne_stack_before')
    else:
        if sb is not None and aa is not None and sa is not None and not _c(sa, round(sb - aa, 2)):
            f.append('stack_after_ne_before_minus_added')
    if aa is not None and lt is not None and aa > lt + 0.06:
        f.append('amount_added_exceeds_live_total')
    return f


def gate_relational_contract(hands_idx, worklist):
    """REV15 B4/G7: every authoritative item's ActionSizingContract must satisfy its OWN relational
    identities (live_total == live_before + amount_added; pot == dead + live_total; all-in =>
    stack_after 0 and amount_added == stack_before; amount_added never exceeds the live total). Emits
    one detailed record per item."""
    items = worklist.get('items') or {}
    if isinstance(items, dict):
        items = list(items.values())
    out = {'authoritative_items_checked': 0, 'mismatches': 0, 'records': []}
    for it in items:
        hid = str(it.get('hand_id') or '')
        h = hands_idx.get(hid) or hands_idx.get(hid[-8:])
        if h is None:
            continue
        kind = it.get('decision_kind') or it.get('bucket')
        ridx = _reviewed_action_index(h, kind)
        if ridx is None:
            continue
        sc = ds.build_action_sizing_contract(h, ridx)
        fields = check_relational_contract(sc)
        out['authoritative_items_checked'] += 1
        if fields:
            out['mismatches'] += 1
        out['records'].append({
            'hand_id': hid, 'node': sc.get('actual_node_type'),
            'amount_added_bb': sc.get('amount_added_bb'),
            'live_street_committed_before_bb': sc.get('live_street_committed_before_bb'),
            'live_betting_total_to_bb': sc.get('live_betting_total_to_bb'),
            'dead_forced_posts_bb': sc.get('dead_forced_posts_bb'),
            'pot_contribution_total_bb': sc.get('pot_contribution_total_bb'),
            'hero_stack_after_bb': sc.get('hero_stack_after_bb'),
            'mismatch_fields': fields,
        })
    return out


def gate_visible_semantic(hands_idx, html, worklist=None):
    """REV12 Part I: full-render SEMANTIC gates over the decoded bodies + coaching payload. The
    legacy verdict/range/CVJ surfaces must agree with the canonical node; coaching ownership must
    be VISIBLY labelled and point at the actual context action."""
    bodies = decode_lazy_hands(html)
    out = {'checked': 0, 'violations': []}
    cc = {}
    m = re.search(r'window\.coachingCards=(\{.*?\});', html)
    if m:
        try:
            cc = json.loads(m.group(1))
        except Exception:
            cc = {}

    def viol(hid, field, **kw):
        d = {'hand': hid, 'field': field}
        d.update(kw)
        out['violations'].append(d)

    # the ownership LABEL is rendered CLIENT-SIDE by _renderCoachingCard from the card's ownership
    # field — verify (once) the renderer emits a label for each non-selected class, and (per card)
    # that the card actually carries the ownership field + a real context link.
    _renderer_ok = {
        'earlier_context': ('ownership-earlier' in html and 'Earlier ' in html),
        'population_research': ('ownership-population' in html and 'Population research' in html),
        'whole_hand': ('ownership-wholehand' in html and 'Whole-hand lesson' in html),
    }
    for _cls, _ok in _renderer_ok.items():
        if not _ok:
            viol('_renderer', 'ownership_label_renderer_missing', ownership=_cls)

    for hid, body in bodies.items():
        h = hands_idx.get(str(hid)) or hands_idx.get(str(hid)[-8:])
        if h is None:
            continue
        out['checked'] += 1
        snap = ds.build_decision_snapshot(h, ds.infer_reviewed_action_index(h))
        node = snap.get('actual_node_type')
        # short all-in: no call verdict / push-chart grade / Wrong-push flag
        if node == 'first_in_short_all_in':
            if re.search(r'call \+EV', body):
                viol(hid, 'short_all_in_with_call_verdict')
            if 'Wrong push' in body or 'Correct push' in body:
                viol(hid, 'short_all_in_with_push_flag')
            if re.search(r'open-shove,? \d+BB', body) and 'short of the big blind' not in body.split('open-shove')[0][-200:]:
                viol(hid, 'short_all_in_with_open_shove_chart')
        # re-jam: no "Wide CVJ (Call Villain Jam)" headline, no unowned acceptable-call teaching
        if node == 're_jam':
            if 'Wide CVJ (Call Villain Jam)' in body:
                viol(hid, 'rejam_with_wide_cvj_headline')
        # coaching ownership must carry the field (renderer labels it) + be context-linked
        for c in (cc.get(str(hid)) or cc.get(str(hid)[-8:]) or []):
            own = (c.get('decision_content_ownership') or {}).get('ownership') or c.get('ownership')
            dco = c.get('decision_content_ownership') or {}
            if own in ('earlier_context', 'population_research', 'whole_hand') and not own:
                viol(hid, 'non_selected_card_without_ownership_field', card=c.get('card_type'))
            if own == 'earlier_context':
                # the context action index must be the ACTUAL earlier action, never the reviewed one
                if (dco.get('context_action_index') is not None
                        and dco.get('context_action_index') == dco.get('reviewed_action_index')):
                    viol(hid, 'earlier_context_card_points_to_reviewed_action', card=c.get('card_type'))
    return out


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
            # INV11 (REV5 B1): a Hero SHOVE (open-shove / re-jam / overjam) with live
            # potential callers or a committed opponent must be exact_committed or
            # potential_if_called — NEVER not_applicable ("bounty irrelevant").
            if dbc.get('hero_action_kind') in ('open_shove', 'rejam_over_live_raise',
                                               'overjam_with_side_pot'):
                _pot = dbc.get('potential_calling_bounties_by_opponent') or {}
                _comm = dbc.get('committed_allin_bounties_by_opponent') or {}
                if (_pot or _comm) and dbc.get('bounty_applicability') == 'not_applicable':
                    out['violations'].append({'hand': hid, 'inv': 'shove_classified_bounty_irrelevant',
                                              'kind': dbc.get('hero_action_kind')})
        # INV9 (pot semantics): main/side semantics + folded dead money + reconciliation.
        psv = pot_semantic_violations(ds.build_realized_contest(h, ridx))
        if psv:
            out['violations'].append({'hand': hid, 'inv': 'pot_semantics', 'why': psv})
        # INV10 (worklist field consistency): no bounty_context field may contradict the
        # typed aggregate (not_applicable => no eligible/adjustment/cover/known).
        wbv = worklist_bounty_consistency_violations(it.get('bounty_context') or {})
        if wbv:
            out['violations'].append({'hand': hid, 'inv': 'worklist_bounty_inconsistent', 'why': wbv})
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
    g_rb = gate_report_bounty(hands_idx, html)
    g_pd = gate_report_decision_bounty(hands_idx, html)
    g_vd = gate_report_visible_decision(hands_idx, html, worklist)
    g_fr = gate_report_full_render(hands_idx, html, worklist)
    g_or = gate_ledger_oracle(hands_idx, worklist, html)
    g_ar = gate_action_row_parity(hands_idx, worklist, html)
    g_vs = gate_visible_semantic(hands_idx, html, worklist)
    g_vn = gate_canonical_view_node_parity(hands_idx, worklist)
    g_pv = gate_persisted_view_node_parity(worklist)
    g_rc = gate_relational_contract(hands_idx, worklist)

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
    print(f"D. RENDERED BOUNTY == CANONICAL : {g_rb['checked']} bounty hands checked, "
          f"{len(g_rb['mismatches'])} mismatch(es)")
    for mm in g_rb['mismatches'][:40]:
        print('   ✗', mm)
    print(f"E. PER-DECISION BOUNTY == CANONICAL : {g_pd['checked']} decision blocks checked, "
          f"{len(g_pd['mismatches'])} mismatch(es)")
    for mm in g_pd['mismatches'][:40]:
        print('   ✗', mm)
    print(f"F. VISIBLE DECISION == REVIEWED ACTION : {g_vd['checked']} visible decision blocks checked, "
          f"{len(g_vd['mismatches'])} mismatch(es)")
    for mm in g_vd['mismatches'][:40]:
        print('   ✗', mm)
    print(f"G. FULL-RENDER CONSUMER OWNERSHIP : {g_fr['checked']} hand bodies checked, "
          f"{len(g_fr['mismatches'])} mismatch(es)")
    for mm in g_fr['mismatches'][:40]:
        print('   ✗', mm)
    print(f"H. INDEPENDENT LEDGER ORACLE : {g_or['authoritative_checked']} authoritative + "
          f"{g_or['all_hands_checked']} all-hand checks, {len(g_or['mismatches'])} mismatch(es)")
    for mm in g_or['mismatches'][:40]:
        print('   ✗', mm)
    print(f"I. ACTION-ROW PARITY (numeric) : {g_ar['authoritative_action_rows_checked']} authoritative rows, "
          f"{g_ar.get('total_mismatches', len(g_ar['mismatches']))} mismatch(es)")
    for mm in g_ar['mismatches'][:40]:
        print('   ✗', mm)
    print(f"J. VISIBLE SEMANTIC (legacy/coaching) : {g_vs['checked']} bodies, "
          f"{len(g_vs['violations'])} violation(s)")
    for mm in g_vs['violations'][:40]:
        print('   ✗', mm)
    print(f"K. CANONICAL VIEW == NODE (deep, builder) : {g_vn['authoritative_items_checked']} authoritative items, "
          f"{g_vn['mismatches']} mismatch(es) "
          f"(price {g_vn['price_contract_mismatches']}, sizing {g_vn['sizing_mismatches']})")
    for mm in [r for r in g_vn['records'] if r['mismatch_fields']][:40]:
        print('   ✗', mm)
    print(f"L. PERSISTED VIEW == NODE : {g_pv['items_with_both_objects']} stored items, "
          f"{g_pv['mismatches']} mismatch(es)")
    for mm in [r for r in g_pv['records'] if r['mismatch_fields']][:40]:
        print('   ✗', mm)
    print(f"M. RELATIONAL CONTRACT : {g_rc['authoritative_items_checked']} authoritative items, "
          f"{g_rc['mismatches']} mismatch(es)")
    for mm in [r for r in g_rc['records'] if r['mismatch_fields']][:40]:
        print('   ✗', mm)
    ok = (not g_wl['mismatches'] and not g_rp['mismatches'] and not g_sem['violations']
          and not g_rb['mismatches'] and not g_pd['mismatches'] and not g_vd['mismatches']
          and not g_fr['mismatches'] and not g_or['mismatches']
          and not g_ar.get('total_mismatches', len(g_ar['mismatches']))
          and not g_vs['violations'] and not g_vn['mismatches'] and not g_pv['mismatches']
          and not g_rc['mismatches'])
    print('-' * 64)
    print('RESULT:', 'PASS — all surfaces agree with the snapshot + semantics hold' if ok
          else 'FAIL — see mismatches above')
    if out_json:
        with io.open(out_json, 'w', encoding='utf-8') as fh:
            json.dump({'worklist': g_wl, 'report': g_rp, 'semantic': g_sem,
                       'report_bounty': g_rb, 'report_decision_bounty': g_pd,
                       'report_visible_decision': g_vd, 'report_full_render': g_fr,
                       'ledger_oracle': g_or, 'action_row_parity': g_ar,
                       'visible_semantic': g_vs, 'canonical_view_node_parity': g_vn,
                       'persisted_view_node_parity': g_pv, 'relational_contract': g_rc,
                       'pass': ok}, fh, indent=2)
        print('wrote', out_json)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
