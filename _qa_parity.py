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
    line_pat = re.compile(
        r"Reviewed decision:(?:\s*</strong>|\s*\*\*)?\s*([A-Za-z]+),\s*(.+?),\s*"
        r"effective depth\s*[≈~]?\s*([0-9.]+)\s*BB")
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
        v_street, v_phrase, v_depth = lm.group(1).lower(), lm.group(2).strip(), _f(lm.group(3))
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
        sd = snap.get('effective_stack_at_decision_bb')
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
            if sd is not None and v_call > _f(sd) + 0.20:
                out['mismatches'].append(
                    {'hand': hid, 'field': 'visible_call_gt_effective_depth',
                     'visible_call': v_call, 'depth': sd, 'idx': ridx})
            if v_call > callable_amt + 0.20:
                out['mismatches'].append(
                    {'hand': hid, 'field': 'visible_call_gt_callable',
                     'visible_call': v_call, 'callable': callable_amt, 'idx': ridx})
            # if there is an uncallable overjam, the visible price must be the CALLABLE amount,
            # never the raw to_match (the REV6 83974506 'call 111.46BB' bug).
            if (raw_to_match - callable_amt) > 0.20 and abs(v_call - raw_to_match) <= 0.20:
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
    ok = (not g_wl['mismatches'] and not g_rp['mismatches'] and not g_sem['violations']
          and not g_rb['mismatches'] and not g_pd['mismatches'] and not g_vd['mismatches'])
    print('-' * 64)
    print('RESULT:', 'PASS — all surfaces agree with the snapshot + semantics hold' if ok
          else 'FAIL — see mismatches above')
    if out_json:
        with io.open(out_json, 'w', encoding='utf-8') as fh:
            json.dump({'worklist': g_wl, 'report': g_rp, 'semantic': g_sem,
                       'report_bounty': g_rb, 'report_decision_bounty': g_pd,
                       'report_visible_decision': g_vd, 'pass': ok}, fh, indent=2)
        print('wrote', out_json)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
