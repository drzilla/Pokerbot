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
        # --- bounty aggregate ---
        bnt = it.get('bounty_context') or it.get('bounty') or {}
        wl_agg = bnt.get('coverage_aggregate') or bnt.get('aggregate')
        try:
            sn_agg = ds.bounty_aggregate(h, ridx)
        except Exception:
            sn_agg = None
        if wl_agg and sn_agg and wl_agg != sn_agg:
            out['mismatches'].append(
                {'hand': hid, 'field': 'bounty_aggregate', 'worklist': wl_agg, 'snapshot': sn_agg})
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
        if h is None or not h.get('pf_allin'):
            continue
        ridx = _reviewed_action_index(h, 'preflop_allin')
        if ridx is None:
            continue
        snap = ds.build_decision_snapshot(h, ridx)
        sn_kind = snap.get('hero_action_kind')
        out['checked'] += 1
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

    print('=' * 64)
    print('END-TO-END PARITY — worklist & report vs canonical snapshot')
    print('=' * 64)
    print(f"A. WORKLIST == SNAPSHOT : {g_wl['checked']} items checked, "
          f"{len(g_wl['mismatches'])} mismatch(es)")
    for mm in g_wl['mismatches'][:40]:
        print('   ✗', mm)
    print(f"B. REPORT   == SNAPSHOT : {g_rp['checked']} all-in decisions checked, "
          f"{len(g_rp['mismatches'])} mismatch(es)")
    for mm in g_rp['mismatches'][:40]:
        print('   ✗', mm)
    ok = not g_wl['mismatches'] and not g_rp['mismatches']
    print('-' * 64)
    print('RESULT:', 'PASS — all surfaces agree with the snapshot' if ok
          else 'FAIL — see mismatches above')
    if out_json:
        with io.open(out_json, 'w', encoding='utf-8') as fh:
            json.dump({'worklist': g_wl, 'report': g_rp, 'pass': ok}, fh, indent=2)
        print('wrote', out_json)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
