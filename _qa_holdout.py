#!/usr/bin/env python3
"""REV7 B6: GENERATED-CORPUS holdout validation — proves the canonical decision-price /
action-display repair is GENERIC, not fitted to the named acceptance hands.

Generates synthetic hands across the canonical action classes (call_vs_jam / call_off /
first-in open / postflop bet / fold / check / 3-bet / open-shove / re-jam / overjam-with-
side-pot), stack sizes, streets, opponent counts, side-pot structures and ante structures —
NONE of which are acceptance hand IDs. For each it builds the canonical ReviewedDecisionView,
renders the visible reviewed-decision line + pot-odds block through the SAME report helpers
the real report uses, then runs the visible-decision gate AND independent price-contract
invariants. Required: semantic violations == 0.

Usage: python _qa_holdout.py <out_json> <out_log>
"""
import base64
import io
import json
import sys
import zlib

import gem_decision_snapshot as ds
import _qa_parity as qp
from gem_report_draft.sections_xiv import (_reconcile_po_to_reviewed,
                                           _reviewed_decision_line_md)


def _L(street, player, action, added, allin=False, pos=None):
    return {'street': street, 'player': player, 'action': action, 'added_bb': added,
            'amount_bb': added, 'is_all_in': allin, 'position': pos}


def _mk_lazy_html(cards):
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = co.compress(json.dumps(cards).encode('utf-8')) + co.flush()
    return ('<html>PB_PAYLOADS["lazyHands"] = {"encoding":"deflate-raw+base64","data":"%s"}</html>'
            % base64.b64encode(raw).decode('ascii'))


def _gen_corpus():
    """Return a list of (hand, reviewed_index, tags) generated across canonical classes."""
    corpus = []
    hid = 90000000

    def add(led, ssb, idx, tags, fmt='NLHE', board=None):
        nonlocal hid
        hid += 1
        h = {'id': str(hid), 'tournament_hand_id': str(hid), 'hero': 'Hero', 'format': fmt,
             'seat_stack_by_player': ssb, 'board': board or [], 'action_ledger': led}
        corpus.append((h, idx, tags))

    # vary stacks / antes / opponents systematically
    for hero_stk in (8.0, 13.5, 22.0, 31.71, 55.0, 103.0):
        for ante in (0.0, 0.12, 0.5):
            posts = []
            if ante:
                posts = [_L('preflop', 'Hero', 'posts', ante), _L('preflop', 'V', 'posts', ante)]
            # (a) CALL vs JAM (HU, Hero covers): V jams to min(hero,villain), Hero calls
            vj = min(hero_stk, 40.0)
            add(posts + [_L('preflop', 'V', 'raises', vj, True),
                         _L('preflop', 'Hero', 'calls', min(vj, hero_stk - ante), True)],
                {'Hero': hero_stk, 'V': 40.0}, len(posts) + 1, ['call_vs_jam', 'hu'], fmt='BOUNTY')
            # (b) OVERJAM: V (deep) jams far above Hero -> callable capped, big overjam
            add(posts + [_L('preflop', 'V', 'raises', 120.0, True),
                         _L('preflop', 'Hero', 'calls', hero_stk - ante, True)],
                {'Hero': hero_stk, 'V': 140.0}, len(posts) + 1, ['call_vs_jam', 'overjam', 'hu'],
                fmt='BOUNTY')
            # (c) FIRST-IN OPEN preflop
            add(posts + [_L('preflop', 'Hero', 'raises', min(2.3, hero_stk - ante))],
                {'Hero': hero_stk, 'V': 40.0}, len(posts), ['first_in_open', 'preflop'])
            # (d) OPEN-SHOVE preflop (short)
            if hero_stk <= 22.0:
                add(posts + [_L('preflop', 'Hero', 'raises', hero_stk - ante, True)],
                    {'Hero': hero_stk, 'V': 40.0}, len(posts), ['open_shove', 'preflop'], fmt='BOUNTY')
            # (e) FOLD facing a raise
            add(posts + [_L('preflop', 'V', 'raises', 3.0), _L('preflop', 'Hero', 'folds', 0)],
                {'Hero': hero_stk, 'V': 40.0}, len(posts) + 1, ['fold', 'preflop'])
            # (f) 3-BET (not all-in)
            if hero_stk >= 22.0:
                add(posts + [_L('preflop', 'V', 'raises', 2.5),
                             _L('preflop', 'Hero', 'raises', 8.0)],
                    {'Hero': hero_stk, 'V': 40.0}, len(posts) + 1, ['3bet', 'preflop'])
            # (g) RE-JAM over a live raise
            if hero_stk <= 31.71:
                add(posts + [_L('preflop', 'V', 'raises', 2.5),
                             _L('preflop', 'Hero', 'raises', hero_stk - ante, True)],
                    {'Hero': hero_stk, 'V': 60.0}, len(posts) + 1, ['rejam', 'preflop'], fmt='BOUNTY')
            # (h) postflop CALL vs JAM (multiway + side pot): Short all-in, Deep over, Hero calls
            add([_L('preflop', 'Short', 'raises', 5.0, True), _L('preflop', 'Hero', 'calls', 5.0),
                 _L('preflop', 'Deep', 'calls', 5.0),
                 _L('flop', 'Deep', 'bets', 15.0, True),
                 _L('flop', 'Hero', 'calls', min(15.0, hero_stk - 5.0), True)],
                {'Hero': hero_stk, 'Short': 5.0, 'Deep': 80.0}, 4, ['call_vs_jam', 'multiway', 'sidepot'],
                board=['2c', '7d', 'Js'], fmt='BOUNTY')
            # (i) postflop BET (lead)
            add([_L('preflop', 'Hero', 'raises', 2.5), _L('preflop', 'V', 'calls', 2.5),
                 _L('flop', 'Hero', 'bets', min(4.0, hero_stk - 2.5))],
                {'Hero': hero_stk, 'V': 40.0}, 2, ['first_in_open', 'postflop', 'bet'],
                board=['2c', '7d', 'Js'])
            # (j) CHECK
            add([_L('preflop', 'Hero', 'raises', 2.5), _L('preflop', 'V', 'calls', 2.5),
                 _L('flop', 'Hero', 'checks', 0)],
                {'Hero': hero_stk, 'V': 40.0}, 2, ['check', 'postflop'], board=['2c', '7d', 'Js'])
    return corpus


def main():
    out_json = sys.argv[1] if len(sys.argv) > 1 else 'holdout_validation.json'
    out_log = sys.argv[2] if len(sys.argv) > 2 else 'holdout_validation.log'
    corpus = _gen_corpus()
    cards = {}
    tag_counts, hands_idx = {}, {}
    overjam_n = multiway_n = bounty_n = 0
    direct_violations = []
    for h, idx, tags in corpus:
        hands_idx[h['id']] = h
        for t in tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        ref = ds.build_reviewed_decision_ref(h, idx, None, 'worklist_reviewed_action')
        snap = ds.build_decision_snapshot(h, idx)
        if (snap.get('uncallable_overjam_bb') or 0) > 0.2:
            overjam_n += 1
        if 'multiway' in tags:
            multiway_n += 1
        if h.get('format') == 'BOUNTY':
            bounty_n += 1
        # render the visible block through the SAME report helpers
        _po = _reconcile_po_to_reviewed(None, ref)
        rev_line = _reviewed_decision_line_md(_po)
        lines = [rev_line]
        if _po.get('reviewed_price_applicable') is not False and _po.get('reviewed_price_applicable'):
            lines.append("**Pot odds:** %s (call %sBB into %sBB)" % (
                _po.get('pot_odds', '—'), _po.get('call_bb', '—'), _po.get('pot_before_call_bb', '—')))
        dai = _po.get('decision_action_index')
        body = ("<div class='analyst-notes' data-decision-action-index='%s'>📊 %s</div>"
                % (dai, ' · '.join(lines)))
        cards[h['id']] = body
        # ---- independent price-contract invariants (NOT via the gate) ----
        ctext = _po.get('reviewed_action_display') or ''
        if 'call' in ctext.lower() and ctext.lower().startswith('call'):
            v_call = snap['callable_amount_bb']
            depth = snap.get('effective_stack_at_decision_bb')
            if depth is not None and v_call > depth + 0.2:
                direct_violations.append({'hand': h['id'], 'why': 'callable_gt_depth'})
            if (snap['raw_amount_to_match_bb'] - v_call) > 0.2 and abs(_po.get('call_bb', 0) - snap['raw_amount_to_match_bb']) <= 0.2:
                direct_violations.append({'hand': h['id'], 'why': 'displayed_raw_overjam'})
        # required equity only when price applies
        if _po.get('reviewed_price_applicable') is False and _po.get('required_eq_pct') is not None:
            direct_violations.append({'hand': h['id'], 'why': 'required_eq_on_nonprice_action'})

    html = _mk_lazy_html(cards)
    gate = qp.gate_report_visible_decision(hands_idx, html)
    violations = list(direct_violations) + list(gate.get('mismatches', []))

    summary = {
        'hands_tested': len(corpus),
        'decisions_tested': gate.get('checked', 0),
        'action_type_distribution': tag_counts,
        'overjam_cases': overjam_n,
        'multiway_cases': multiway_n,
        'bounty_cases': bounty_n,
        'gate_mismatches': len(gate.get('mismatches', [])),
        'direct_invariant_violations': len(direct_violations),
        'semantic_violations': len(violations),
        'violations': violations[:50],
        'pass': len(violations) == 0,
    }
    with io.open(out_json, 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    lines = ['=' * 64, 'REV7 B6 — GENERATED-CORPUS HOLDOUT VALIDATION (generic, not hand-ID-fitted)',
             '=' * 64,
             'hands tested            : %d' % summary['hands_tested'],
             'decisions tested (gate) : %d' % summary['decisions_tested'],
             'overjam cases           : %d' % overjam_n,
             'multiway cases          : %d' % multiway_n,
             'bounty cases            : %d' % bounty_n,
             'action-type distribution: %s' % json.dumps(tag_counts),
             'gate mismatches         : %d' % summary['gate_mismatches'],
             'direct invariant viols  : %d' % summary['direct_invariant_violations'],
             '-' * 64,
             'semantic violations     : %d' % summary['semantic_violations'],
             'RESULT: %s' % ('PASS' if summary['pass'] else 'FAIL')]
    if violations:
        lines.append('VIOLATIONS:')
        for v in violations[:50]:
            lines.append('  ' + json.dumps(v))
    with io.open(out_log, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    sys.exit(0 if summary['pass'] else 1)


if __name__ == '__main__':
    main()
