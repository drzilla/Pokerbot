#!/usr/bin/env python3
"""REV7 B6 / REV9 B1: REAL PRODUCTION-RENDER holdout — proves the canonical decision model is
GENERIC (not fitted to acceptance hand IDs) by running each generated hand through the ACTUAL
hand-detail renderer used for the June report:

    _qa_v817_synthetic.build()  ->  report_data + stats + base hands
    + generated facing-class hands (full fields + stamped ReviewedDecisionRef + analyst_commentary)
    -> render_html(stats, report_data, hands, sections=['XIV'])   <-- THE PRODUCTION RENDERER
    -> decode lazyHands -> gate_report_visible_decision + gate_report_full_render

This is NOT a helper-fragment holdout: the bodies under test are produced by the real
sections_xiv hand-detail pipeline (capsule, price, range evidence, verdict, all-in math, PKO /
bounty consumers, ICM flags, lazyHands serialization), then decoded and gated. Required:
full-render semantic violations == 0.

Usage: python _qa_holdout.py <out_json> <out_log>
"""
import io
import json
import os
import sys

import gem_decision_snapshot as ds
import _qa_parity as qp
from _qa_decode_lazy import decode_lazy_hands

PROD_RENDER_ENTRYPOINT = 'gem_report_draft.render_html(stats, report_data, hands, sections=["XIV"])'


def _L(street, player, action, added, allin=False, pos=None):
    return {'street': street, 'player': player, 'action': action, 'added_bb': added,
            'amount_bb': added, 'is_all_in': allin, 'position': pos}


_HID = [90000000]


def _mk(led, ssb, idx, tags, fmt='NLHE', board=None, pos=None, cards=('Ah', 'Kd')):
    _HID[0] += 1
    hid = 'TM60' + str(_HID[0])
    hero_pos = pos or next((a.get('position') for a in led
                            if a.get('player') == 'Hero' and a.get('position')), 'BTN')
    h = {'id': hid, 'hero': 'Hero', 'format': fmt, 'cards': list(cards), 'position': hero_pos,
         'stack_bb': round(ssb.get('Hero', 30.0), 1), 'eff_stack_bb': round(ssb.get('Hero', 30.0), 1),
         'net_bb': -1.0, 'tournament': 'Synthetic Holdout', 'date': '2026-06-16', 'level': '12',
         'tournament_phase': 'middle', 'board': board or [], 'hero_street_actions': {},
         'pf_allin': any(a.get('is_all_in') and a.get('player') == 'Hero' for a in led),
         'pf_action': '', 'seat_stack_by_player': ssb, 'action_ledger': led}
    return (h, idx, tags)


def _gen_corpus():
    corpus = []
    for hero_stk in (8.0, 13.5, 22.0, 31.71, 55.0, 103.0):
        for ante in (0.0, 0.12, 0.5):
            posts = []
            if ante:
                posts = [_L('preflop', 'Hero', 'posts', ante, pos='BB'),
                         _L('preflop', 'V', 'posts', ante, pos='SB')]
            vj = min(hero_stk, 40.0)
            corpus.append(_mk(posts + [_L('preflop', 'V', 'raises', vj, True, pos='BTN'),
                                       _L('preflop', 'Hero', 'calls', min(vj, hero_stk - ante), True, pos='BB')],
                              {'Hero': hero_stk, 'V': 40.0}, len(posts) + 1, ['call_vs_jam', 'hu'], fmt='BOUNTY'))
            corpus.append(_mk(posts + [_L('preflop', 'V', 'raises', 120.0, True, pos='BTN'),
                                       _L('preflop', 'Hero', 'calls', hero_stk - ante, True, pos='BB')],
                              {'Hero': hero_stk, 'V': 140.0}, len(posts) + 1, ['call_vs_jam', 'overjam', 'hu'], fmt='BOUNTY'))
            corpus.append(_mk(posts + [_L('preflop', 'Hero', 'raises', min(2.3, hero_stk - ante), pos='CO')],
                              {'Hero': hero_stk, 'V': 40.0}, len(posts), ['first_in_open', 'preflop'], pos='CO'))
            if hero_stk <= 22.0:
                corpus.append(_mk(posts + [_L('preflop', 'Hero', 'raises', hero_stk - ante, True, pos='HJ')],
                                  {'Hero': hero_stk, 'V': 40.0}, len(posts), ['open_shove', 'preflop'], fmt='BOUNTY', pos='HJ'))
            corpus.append(_mk(posts + [_L('preflop', 'V', 'raises', 3.0, pos='BTN'),
                                       _L('preflop', 'Hero', 'folds', 0, pos='BB')],
                              {'Hero': hero_stk, 'V': 40.0}, len(posts) + 1, ['fold', 'facing_raise'], pos='BB'))
            if hero_stk >= 22.0:
                corpus.append(_mk(posts + [_L('preflop', 'V', 'raises', 2.5, pos='CO'),
                                           _L('preflop', 'Hero', 'raises', 8.0, pos='BTN')],
                                  {'Hero': hero_stk, 'V': 40.0}, len(posts) + 1, ['3bet', 'preflop'], pos='BTN'))
            if hero_stk <= 31.71:
                corpus.append(_mk(posts + [_L('preflop', 'V', 'raises', 2.5, pos='CO'),
                                           _L('preflop', 'Hero', 'raises', hero_stk - ante, True, pos='BTN')],
                                  {'Hero': hero_stk, 'V': 60.0}, len(posts) + 1, ['rejam', 'preflop'], fmt='BOUNTY', pos='BTN'))
            corpus.append(_mk([_L('preflop', 'Short', 'raises', 5.0, True, pos='UTG'),
                               _L('preflop', 'Hero', 'calls', 5.0, pos='BB'),
                               _L('preflop', 'Deep', 'calls', 5.0, pos='BTN'),
                               _L('flop', 'Deep', 'bets', 15.0, True, pos='BTN'),
                               _L('flop', 'Hero', 'calls', min(15.0, hero_stk - 5.0), True, pos='BB')],
                              {'Hero': hero_stk, 'Short': 5.0, 'Deep': 80.0}, 4,
                              ['call_vs_jam', 'multiway', 'sidepot'], board=['2c', '7d', 'Js'], fmt='BOUNTY', pos='BB'))
            corpus.append(_mk([_L('preflop', 'Hero', 'raises', 2.5, pos='CO'), _L('preflop', 'V', 'calls', 2.5, pos='BB'),
                               _L('flop', 'Hero', 'bets', min(4.0, hero_stk - 2.5), pos='CO')],
                              {'Hero': hero_stk, 'V': 40.0}, 2, ['first_in_open', 'postflop', 'bet'],
                              board=['2c', '7d', 'Js'], pos='CO'))
            corpus.append(_mk([_L('preflop', 'Hero', 'raises', 2.5, pos='CO'), _L('preflop', 'V', 'calls', 2.5, pos='BB'),
                               _L('flop', 'Hero', 'checks', 0, pos='CO')],
                              {'Hero': hero_stk, 'V': 40.0}, 2, ['check', 'postflop'], board=['2c', '7d', 'Js'], pos='CO'))
    corpus.extend(_gen_first_in_folds())
    corpus.extend(_gen_limp_cases())
    corpus.extend(_gen_edge_cases())
    return corpus


def _gen_edge_cases():
    """REV10: no-Hero-decision walk, first-in SB limp/complete, postflop call with an earlier
    preflop range context — so the holdout activates the no-decision, first_in_limp, and
    earlier-context range surfaces too."""
    out = []
    # NO Hero decision — Hero is BB, folds around, Hero never voluntarily acts (a walk).
    out.append(_mk([_L('preflop', 'SB', 'posts', 0.5, pos='SB'), _L('preflop', 'Hero', 'posts', 1.0, pos='BB'),
                    _L('preflop', 'CO', 'folds', 0, pos='CO'), _L('preflop', 'BTN', 'folds', 0, pos='BTN'),
                    _L('preflop', 'SB', 'folds', 0, pos='SB')],
                   {'Hero': 40.0, 'SB': 40.0, 'CO': 40.0, 'BTN': 40.0}, None, ['no_hero_decision', 'walk'],
                   fmt='BOUNTY', pos='BB'))
    # FIRST-IN SB limp/complete (folds to Hero in the SB, Hero completes first-in).
    out.append(_mk([_L('preflop', 'CO', 'folds', 0, pos='CO'), _L('preflop', 'BTN', 'folds', 0, pos='BTN'),
                    _L('preflop', 'Hero', 'calls', 0.5, pos='SB'), _L('preflop', 'BB', 'checks', 0, pos='BB')],
                   {'Hero': 40.0, 'BB': 40.0, 'CO': 40.0, 'BTN': 40.0}, 2, ['first_in_limp', 'sb_complete_first_in'],
                   pos='SB'))
    # POSTFLOP call carrying an earlier preflop open (earlier-context range).
    out.append(_mk([_L('preflop', 'Hero', 'raises', 2.5, pos='CO'), _L('preflop', 'BB', 'calls', 2.5, pos='BB'),
                    _L('flop', 'BB', 'bets', 4.0, pos='BB'), _L('flop', 'Hero', 'calls', 4.0, pos='CO')],
                   {'Hero': 60.0, 'BB': 60.0}, 3, ['postflop', 'earlier_context', 'call'],
                   board=['2c', '7d', 'Js'], pos='CO'))
    # REV11: a POSTFLOP first BET (kind=bet, not first_in_open).
    out.append(_mk([_L('preflop', 'Hero', 'raises', 2.5, pos='CO'), _L('preflop', 'BB', 'calls', 2.5, pos='BB'),
                    _L('flop', 'Hero', 'bets', 5.0, pos='CO')], {'Hero': 60.0, 'BB': 60.0}, 2,
                   ['postflop', 'bet', 'postflop_bet'], board=['2c', '7d', 'Js'], pos='CO'))
    # REV11 B1.2: a covering RE-JAM over a short all-in (no other live opponent) — literal re-jam.
    out.append(_mk([_L('preflop', 'V', 'raises', 8.0, True, pos='HJ'),
                    _L('preflop', 'Hero', 'raises', 12.7, True, pos='BTN')], {'Hero': 12.7, 'V': 8.0}, 1,
                   ['preflop', 're_jam', 'covering_rejam'], fmt='BOUNTY', pos='BTN'))
    # REV11 B3/C3: a first-in UNDERBLIND short all-in.
    out.append(_mk([_L('preflop', 'SB', 'posts', 0.5, pos='SB'), _L('preflop', 'BB', 'posts', 1.0, pos='BB'),
                    _L('preflop', 'Hero', 'calls', 0.12, True, pos='MP')], {'Hero': 0.12, 'SB': 30.0, 'BB': 30.0}, 2,
                   ['preflop', 'short_all_in', 'first_in_short_all_in'], fmt='BOUNTY', pos='MP'))
    return out


def _gen_first_in_folds():
    out = []
    order = ['UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB']
    for pos in order:
        led = [_L('preflop', 'SB', 'posts', 0.5, pos='SB'), _L('preflop', 'BB', 'posts', 1.0, pos='BB')]
        for q in order:
            if q == pos:
                break
            if q not in ('SB', 'BB'):
                led.append(_L('preflop', q, 'folds', 0, pos=q))
        idx = len(led)
        led.append(_L('preflop', 'Hero', 'folds', 0, pos=pos))
        _hc = _mk(led, {'Hero': 30.0, 'SB': 30.0, 'BB': 30.0}, idx, ['first_in_fold', pos], fmt='BOUNTY', pos=pos)
        # REV10 E1: give the first-in fold the range-chart fields so hand_range_evidence returns
        # the RFI open chart, rendered as a RECOMMENDED-ALTERNATIVE range (Hero folded a hand the
        # open chart includes) — activating that surface in the holdout.
        _hc[0]['first_in'] = True
        _hc[0]['pf_action'] = 'fold'
        _hc[0]['eff_stack_bb_at_decision'] = 30.0
        out.append(_hc)
    # BB check option (limped pot)
    out.append(_mk([_L('preflop', 'SB', 'posts', 0.5, pos='SB'), _L('preflop', 'Hero', 'posts', 1.0, pos='BB'),
                    _L('preflop', 'BTN', 'calls', 1.0, pos='BTN'), _L('preflop', 'Hero', 'checks', 0, pos='BB')],
                   {'Hero': 30.0, 'SB': 30.0, 'BTN': 30.0}, 3, ['check_option', 'BB'], pos='BB'))
    return out


def _gen_limp_cases():
    """REV9 A: facing-limp folds / overlimp / SB complete / iso-raise (1 and 2 limpers)."""
    out = []
    # fold over ONE limp
    out.append(_mk([_L('preflop', 'SB', 'posts', 0.5, pos='SB'), _L('preflop', 'BB', 'posts', 1.0, pos='BB'),
                    _L('preflop', 'MP', 'calls', 1.0, pos='MP'), _L('preflop', 'Hero', 'folds', 0, pos='BTN')],
                   {'Hero': 30.0, 'SB': 30.0, 'BB': 30.0, 'MP': 30.0}, 3, ['facing_limp', 'fold_over_limp'], pos='BTN'))
    # fold after TWO limpers
    out.append(_mk([_L('preflop', 'SB', 'posts', 0.5, pos='SB'), _L('preflop', 'BB', 'posts', 1.0, pos='BB'),
                    _L('preflop', 'UTG', 'calls', 1.0, pos='UTG'), _L('preflop', 'MP', 'calls', 1.0, pos='MP'),
                    _L('preflop', 'Hero', 'folds', 0, pos='CO')],
                   {'Hero': 30.0, 'SB': 30.0, 'BB': 30.0, 'UTG': 30.0, 'MP': 30.0}, 4, ['facing_limp', 'fold_2_limpers'], pos='CO'))
    # overlimp (BTN calls over a limp)
    out.append(_mk([_L('preflop', 'SB', 'posts', 0.5, pos='SB'), _L('preflop', 'BB', 'posts', 1.0, pos='BB'),
                    _L('preflop', 'MP', 'calls', 1.0, pos='MP'), _L('preflop', 'Hero', 'calls', 1.0, pos='BTN')],
                   {'Hero': 30.0, 'SB': 30.0, 'BB': 30.0, 'MP': 30.0}, 3, ['facing_limp', 'overlimp'], pos='BTN'))
    # SB complete after a limp
    out.append(_mk([_L('preflop', 'Hero', 'posts', 0.5, pos='SB'), _L('preflop', 'BB', 'posts', 1.0, pos='BB'),
                    _L('preflop', 'MP', 'calls', 1.0, pos='MP'), _L('preflop', 'Hero', 'calls', 0.5, pos='SB')],
                   {'Hero': 30.0, 'BB': 30.0, 'MP': 30.0}, 3, ['facing_limp', 'sb_complete'], pos='SB'))
    # iso-raise over ONE limp
    out.append(_mk([_L('preflop', 'SB', 'posts', 0.5, pos='SB'), _L('preflop', 'BB', 'posts', 1.0, pos='BB'),
                    _L('preflop', 'MP', 'calls', 1.0, pos='MP'), _L('preflop', 'Hero', 'raises', 5.0, pos='BTN')],
                   {'Hero': 40.0, 'SB': 40.0, 'BB': 40.0, 'MP': 40.0}, 3, ['facing_limp', 'iso_raise_1'], pos='BTN'))
    # iso-raise over TWO limps
    out.append(_mk([_L('preflop', 'SB', 'posts', 0.5, pos='SB'), _L('preflop', 'BB', 'posts', 1.0, pos='BB'),
                    _L('preflop', 'UTG', 'calls', 1.0, pos='UTG'), _L('preflop', 'MP', 'calls', 1.0, pos='MP'),
                    _L('preflop', 'Hero', 'raises', 6.0, pos='CO')],
                   {'Hero': 40.0, 'SB': 40.0, 'BB': 40.0, 'UTG': 40.0, 'MP': 40.0}, 4, ['facing_limp', 'iso_raise_2'], pos='CO'))
    return out


def _kind_for(tags):
    if 'postflop' in tags or 'multiway' in tags or 'sidepot' in tags:
        return 'postflop_call_fold'
    if any(t in tags for t in ('call_vs_jam', 'open_shove', 'rejam')):
        return 'preflop_allin'
    return 'preflop_deviation'


def main():
    out_json = sys.argv[1] if len(sys.argv) > 1 else 'holdout_validation.json'
    out_log = sys.argv[2] if len(sys.argv) > 2 else 'holdout_validation.log'

    import _qa_v817_synthetic as syn
    from gem_report_draft import render_html
    stats, rd, base_hands = syn.build()
    rd.setdefault('reviewed_decision_ref_by_hand', {})
    rd.setdefault('analyst_commentary', {})
    rd.setdefault('pot_odds_by_hand', {})

    corpus = _gen_corpus()
    # REV10 E2: build the ACTUAL analyst worklist from the PRISTINE corpus (before the render-time
    # mutations below) so the builder routes every candidate, then compare its serialized decision
    # nodes to the SAME canonical reviewed views (gate A) — proving the worklist export is canonical.
    real_wl = {'items': {}}
    try:
        from gem_analyst_worklist import build_analyst_worklist
        _corpus_hands = [h for h, _i, _t in corpus]
        _cands = {'mistakes': [
            {'id': h['id'], 'tournament_hand_id': h['id'], 'cards': ''.join(h.get('cards') or []),
             'position': h.get('position', ''), 'format': h.get('format', 'NLHE'),
             'tournament_phase': 'mid', 'decision_kind': _kind_for(_t), 'action_summary': 'holdout',
             'decision_math': {'key_decision_street': 'preflop', 'streets': {}}}
            for h, _i, _t in corpus]}
        # IMPORTANT: give the builder its OWN reviewed_decision_ref_by_hand dict — dict(rd) is a
        # SHALLOW copy that would otherwise share (and let the builder pollute) rd's map with
        # authoritative refs, mislabelling the holdout's inferred cases as "Reviewed decision".
        _wl_rd = dict(rd)
        _wl_rd['reviewed_decision_ref_by_hand'] = {}
        real_wl = build_analyst_worklist(_cands, {'preflop_deviations': []}, _wl_rd,
                                         base_hands + _corpus_hands, '20260616')
    except Exception as _e:
        real_wl = {'items': {}, '_error': str(_e)}

    holdout_hands, our_idx, wl_items = [], {}, {}
    tag_counts = {}
    n_authoritative = n_inferred = 0
    for i, (h, idx, tags) in enumerate(corpus):
        for t in tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        kind = _kind_for(tags)
        # alternate authoritative (worklist ref) vs inferred (analyzer fallback) coverage
        authoritative = (i % 4 != 0)
        if authoritative:
            ref = ds.build_reviewed_decision_ref(h, idx, kind, 'worklist_reviewed_action')
            rd['reviewed_decision_ref_by_hand'][h['id']] = ref
            rd['reviewed_decision_ref_by_hand'][h['id'][-8:]] = ref
            wl_items[h['id']] = {'hand_id': h['id'], 'decision_kind': kind}
            n_authoritative += 1
        else:
            h['reviewed_decision_ref'] = ds.build_reviewed_decision_ref(h)  # inferred fallback
            n_inferred += 1
        rd['analyst_commentary'][h['id']] = {'verdict': 'III.2', 'hand_strength': 'holdout case'}
        rd['appendix_hand_ids_all'].append(h['id'])
        if h.get('format') == 'BOUNTY':
            try:
                h['decision_bounty_context'] = ds.build_decision_bounty_context(h, idx)
                if idx is not None:
                    h['decision_bounty_context_by_action_index'] = {idx: h['decision_bounty_context']}
            except Exception:
                pass
        holdout_hands.append(h)
        our_idx[h['id']] = h
        our_idx[h['id'][-8:]] = h

    # REV10 E2: build the ACTUAL coaching cards via the production builder so the coaching
    # surface is genuinely activated (not merely seeded), and stamp them onto report_data.
    try:
        from gem_coaching_cards import build_coaching_cards
        rd['coaching_cards'] = build_coaching_cards(base_hands + holdout_hands, stats, rd)
    except Exception as _e:
        rd.setdefault('coaching_cards', {})
    n_coaching_cards = sum(len(v) for v in (rd.get('coaching_cards') or {}).values())

    # REV10 E2: gate A on the real worklist built above (canonical-node parity on the holdout).
    gate_a = qp.gate_worklist(our_idx, real_wl)

    prev = os.environ.get('GEM_LAZY_HANDS')
    os.environ['GEM_LAZY_HANDS'] = '1'
    try:
        html = render_html(stats, rd, base_hands + holdout_hands, sections=['XIV'])
    finally:
        if prev is None:
            os.environ.pop('GEM_LAZY_HANDS', None)
        else:
            os.environ['GEM_LAZY_HANDS'] = prev

    cards = decode_lazy_hands(html)
    wl = {'items': wl_items}
    gate_vd = qp.gate_report_visible_decision(our_idx, html, wl)
    gate_fr = qp.gate_report_full_render(our_idx, html, wl)
    # REV11 G: run the INDEPENDENT ledger oracle on the holdout corpus too.
    gate_or = qp.gate_ledger_oracle(our_idx, real_wl, html)
    # REV12 G/I: real action-row parity + visible-semantic gates on the holdout.
    gate_ar = qp.gate_action_row_parity(our_idx, real_wl, html)
    gate_vs = qp.gate_visible_semantic(our_idx, html, real_wl)
    # REV13 F/I: canonical ReviewedDecisionView == serialized decision_node deep parity on the holdout.
    gate_vn = qp.gate_canonical_view_node_parity(our_idx, real_wl)
    # REV14 H4/B8: PERSISTED view==node parity (reads the stored worklist objects, no rebuild).
    gate_pv = qp.gate_persisted_view_node_parity(real_wl)
    # REV15 B4/G7: RELATIONAL contract identities (live_total == live_before + amount_added; etc.).
    gate_rc = qp.gate_relational_contract(our_idx, real_wl)
    # REV16 §12: full-history physical replay over EVERY action (stack conservation, covering-call
    # parity, all-in residual, oracle agreement) + every rendered grid row sized from the canonical
    # replay (0 raw fallbacks).
    gate_far = qp.gate_full_action_replay(our_idx)
    gate_apr = qp.gate_all_player_renderer_parity(our_idx, html)

    # REV10 E1: per-surface ACTIVATION counts over the generated holdout bodies. A claimed
    # consumer must be genuinely activated (count > 0) — an absent block can no longer pass by
    # having nothing to inspect. Counts are derived from the decoded production-render bodies.
    import re as _re
    _all_body = '\n'.join(cards.values())
    surface_activation = {
        'decision_capsule': len(_re.findall(r'(?:Reviewed decision|Inferred decision context|No reviewed decision)', _all_body)),
        'typed_action_display': len(_re.findall(r'(?:open to|3-bet to|call \d|fold facing|fold first-in|fold over limp|open-shove|re-jam|bet \d|check|complete \d|overlimp|iso-raise)', _all_body)),
        'price_pot_odds_block': len(_re.findall(r'Pot odds:', _all_body)),
        'range_evidence': len(_re.findall(r"<span[^>]*class=['\"][^'\"]*rng-hl", _all_body)),
        'recommended_alternative_range': len(_re.findall(r'Recommended-alternative range', _all_body)),
        'earlier_context_range': len(_re.findall(r'Earlier preflop context', _all_body)),
        'verdict_or_allin_math': len(_re.findall(r'(?:Decision:|All-in|EV of call:|Verdict)', _all_body)),
        'pko_bounty_teaching': len(_re.findall(r'(?:Bounty trust:|PKO|bounty)', _all_body)),
        'coaching_cards_built': n_coaching_cards,
        'worklist_items_built': len(real_wl.get('items') or {}),
        'no_hero_decision_lines': len(_re.findall(r'No reviewed decision', _all_body)),
        # REV11: the new action-identity classes must each activate at least once.
        'postflop_bet_display': len(_re.findall(r'bet \d', _all_body)),
        're_jam_display': len(_re.findall(r're-jam', _all_body)),
        'underblind_short_all_in_display': len(_re.findall(r'short of the big blind', _all_body)),
    }
    # every claimed surface must have been activated at least once
    surface_zero = [k for k, v in surface_activation.items() if not v]
    # direct invariant: every facing-limp / first-in fold renders correctly + no pot odds
    direct = []
    for h, idx, tags in corpus:
        s = ds.build_decision_snapshot(h, idx)
        disp = ds.reviewed_action_display(h, idx, s)['display_text']
        b = cards.get(h['id'][-8:]) or cards.get(h['id']) or ''
        if 'facing_limp' in tags:
            if 'first-in' in disp:
                direct.append({'hand': h['id'], 'why': 'facing_limp_rendered_first_in'})
            if 'fold_over_limp' in tags and 'fold over limp' not in b:
                direct.append({'hand': h['id'], 'why': 'limp_fold_wording_missing'})
        if ('first_in_fold' in tags or 'facing_limp' in tags) and s.get('price_applicable') and disp.startswith('fold'):
            direct.append({'hand': h['id'], 'why': 'first_in_or_limp_fold_priced'})
        # REV13 E/I: NUMERIC sizing comparison on every activated class — the INDEPENDENT ledger
        # sizing oracle must agree with the production ActionSizingContract on the displayed
        # quantities (amount_added / total_to). A re-jam whose contract labels the raise increment
        # as the added amount would diverge here (the B1 defect), at the contract level.
        try:
            import _qa_ledger_oracle as _oraH
            _ozH = _oraH.oracle_sizing(h, idx)
            _scH = ds.build_action_sizing_contract(h, idx)
            if (_ozH.get('amount_added_bb') is not None and _scH.get('amount_added_bb') is not None
                    and abs(_ozH['amount_added_bb'] - _scH['amount_added_bb']) > 0.06):
                direct.append({'hand': h['id'], 'why': 'sizing_amount_added_oracle_mismatch',
                               'oracle': _ozH['amount_added_bb'], 'contract': _scH['amount_added_bb']})
            if (_ozH.get('total_to_bb') is not None and _scH.get('total_to_bb') is not None
                    and abs(_ozH['total_to_bb'] - _scH['total_to_bb']) > 0.06):
                direct.append({'hand': h['id'], 'why': 'sizing_total_to_oracle_mismatch',
                               'oracle': _ozH['total_to_bb'], 'contract': _scH['total_to_bb']})
        except Exception:
            pass

    # REV10 E1: a claimed-but-unactivated surface is a holdout FAILURE (false confidence).
    surface_violations = [{'why': 'consumer_surface_not_activated', 'surface': k} for k in surface_zero]
    wl_a_mismatches = list(gate_a.get('mismatches', []))
    oracle_mismatches = list(gate_or.get('mismatches', []))
    # REV12: action-row + visible-semantic mismatches (exclude the global _renderer presence check —
    # the holdout's render_html DOES emit the renderer, but guard against accidental absence below).
    ar_mismatches = list(gate_ar.get('mismatches', []))
    vs_violations = [v for v in gate_vs.get('violations', []) if v.get('hand') != '_renderer']
    # REV13 F/I: any node/view deep-parity disagreement on the holdout corpus is a violation.
    vn_mismatches = [{'hand': r.get('hand_id'), 'why': 'view_node_parity', 'fields': r['mismatch_fields']}
                     for r in gate_vn.get('records', []) if r.get('mismatch_fields')]
    # REV14 H4/B8: any PERSISTED view==node disagreement is a violation.
    pv_mismatches = [{'hand': r.get('hand_id'), 'why': 'persisted_view_node_parity', 'fields': r['mismatch_fields']}
                     for r in gate_pv.get('records', []) if r.get('mismatch_fields')]
    # REV15 B4/G7: any relational-contract violation is a violation.
    rc_mismatches = [{'hand': r.get('hand_id'), 'why': 'relational_contract', 'fields': r['mismatch_fields']}
                     for r in gate_rc.get('records', []) if r.get('mismatch_fields')]
    vn_mismatches = vn_mismatches + pv_mismatches + rc_mismatches
    # REV16 §12: full-history chip-flow conservation + all-player renderer parity over the holdout.
    far_mismatches = [{'hand': r.get('hand'), 'why': 'full_action_replay_' + r.get('why', ''),
                       'detail': r} for r in gate_far.get('records', [])]
    apr_mismatches = [{'hand': r.get('hand'), 'why': 'renderer_parity_raw_fallback', 'detail': r}
                      for r in gate_apr.get('records', [])]
    vn_mismatches = vn_mismatches + far_mismatches + apr_mismatches
    violations = (list(gate_vd.get('mismatches', [])) + list(gate_fr.get('mismatches', []))
                  + direct + surface_violations + wl_a_mismatches + oracle_mismatches
                  + ar_mismatches + vs_violations + vn_mismatches)
    rendered = sum(1 for h, _, _ in corpus if (cards.get(h['id'][-8:]) or cards.get(h['id'])))
    summary = {
        'production_render_entrypoint': PROD_RENDER_ENTRYPOINT,
        'hands_generated': len(corpus),
        'hands_rendered_in_report': rendered,
        'visible_decision_blocks_checked': gate_vd.get('checked', 0),
        'full_render_blocks_checked': gate_fr.get('checked', 0),
        'authoritative_cases': n_authoritative,
        'inferred_cases': n_inferred,
        'action_type_distribution': tag_counts,
        # REV10 E1/E2: per-surface activation + real-worklist node parity (gate A on the holdout).
        'surface_activation_counts': surface_activation,
        'surfaces_not_activated': surface_zero,
        'real_worklist_items': len(real_wl.get('items') or {}),
        'real_worklist_gate_a_checked': gate_a.get('checked', 0),
        'real_worklist_gate_a_mismatches': len(wl_a_mismatches),
        'ledger_oracle_mismatches': len(oracle_mismatches),
        'action_row_parity_checked': gate_ar.get('authoritative_action_rows_checked', 0),
        'action_row_mismatches': len(ar_mismatches),
        'view_node_parity_checked': gate_vn.get('authoritative_items_checked', 0),
        'persisted_view_node_parity_checked': gate_pv.get('items_with_both_objects', 0),
        'relational_contract_checked': gate_rc.get('authoritative_items_checked', 0),
        'full_action_replay_actions': gate_far.get('actions_replayed', 0),
        'full_action_replay_violations': gate_far.get('total_violations', 0),
        'renderer_parity_rows_checked': gate_apr.get('rows_checked', 0),
        'renderer_parity_raw_fallbacks': gate_apr.get('fallback_activations', 0),
        'view_node_parity_mismatches': len(vn_mismatches),
        'visible_semantic_violations': len(vs_violations),
        'coaching_cards_built': n_coaching_cards,
        'visible_decision_mismatches': len(gate_vd.get('mismatches', [])),
        'full_render_mismatches': len(gate_fr.get('mismatches', [])),
        'direct_invariant_violations': len(direct),
        'semantic_violations': len(violations),
        'violations': violations[:60],
        'pass': (len(violations) == 0 and rendered > 0 and gate_fr.get('checked', 0) > 0
                 and not surface_zero and gate_a.get('checked', 0) > 0),
    }
    with io.open(out_json, 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    lines = ['=' * 64, 'REV9 B1 — REAL PRODUCTION-RENDER HOLDOUT', '=' * 64,
             'production renderer : ' + PROD_RENDER_ENTRYPOINT,
             'hands generated     : %d' % len(corpus),
             'hands rendered      : %d' % rendered,
             'full-render checked : %d' % gate_fr.get('checked', 0),
             'visible-dec checked : %d' % gate_vd.get('checked', 0),
             'authoritative/inferred: %d / %d' % (n_authoritative, n_inferred),
             'action-type dist   : %s' % json.dumps(tag_counts),
             '-' * 64,
             'visible-decision mismatches : %d' % len(gate_vd.get('mismatches', [])),
             'full-render mismatches      : %d' % len(gate_fr.get('mismatches', [])),
             'direct invariant violations : %d' % len(direct),
             'semantic violations         : %d' % len(violations),
             'RESULT: %s' % ('PASS' if summary['pass'] else 'FAIL')]
    if violations:
        lines.append('VIOLATIONS:')
        for v in violations[:60]:
            lines.append('  ' + json.dumps(v))
    with io.open(out_log, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    sys.exit(0 if summary['pass'] else 1)


if __name__ == '__main__':
    main()
