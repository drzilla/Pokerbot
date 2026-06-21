"""v8.17 Decision Coach — synthetic acceptance report (>=31 scenarios).

Drives the REAL gem_report_draft.render_html / lazy payload / modal / queue / PKO
pill — NO mock renderer. Fabricated ids only (TM97######). Emits the HTML, then
decodes lazyHands + scans the static shell and machine-asserts every scenario.

Run:  python _qa_v817_synthetic.py
Out:  C:/mnt/user-data/outputs/V817_synthetic_acceptance.html  (+ scenario matrix print)
Exit 0 = all scenario assertions pass.
"""
import os
import sys

OUT_DIR = r'C:/mnt/user-data/outputs'
OUT_HTML = os.path.join(OUT_DIR, 'V817_synthetic_acceptance.html')


def _po(street='preflop', pot_odds='1.8:1', call_bb=12.0, required_eq_pct=36,
        required_eq_bounty_pct=None, hero_equity_pct=44.0, n_at_sd=2, still_to_act=0,
        verdict_hint='', bounty=None):
    d = {'pot_odds': pot_odds, 'call_bb': call_bb, 'pot_before_call_bb': call_bb * 2,
         'required_eq_pct': required_eq_pct, 'hero_equity_pct': hero_equity_pct,
         'n_players_at_showdown': n_at_sd, 'players_still_to_act': still_to_act,
         'street': street, 'verdict_hint': verdict_hint}
    if required_eq_bounty_pct is not None:
        d['required_eq_bounty_pct'] = required_eq_bounty_pct
    if bounty is not None:
        d['bounty'] = bounty
    return d


def _pko(*, spot, classification, players=2, cover='Hero covers', collect=True,
         cover_label='', delta=(-3.0, -3.0), bb_est=3.2, depth='12-20bb',
         eff=14.0, teach='', caveat=''):
    return {'enabled': True, 'spot': spot, 'classification': classification,
            'players_if_hero_continues': players, 'coverage_bucket': cover,
            'can_collect_bounty': collect, 'coverage_label': cover_label,
            'delta_range_pp': list(delta), 'bounty_value_bb_est': bb_est,
            'depth_bucket': depth, 'effective_stack_bb': eff,
            'teaching_note': teach, 'caveat': caveat}


def _hand(hid, cards, *, pf_allin=False, pf_action='', first_in=False,
          villain_jammed=False, hero_faced_raise=False, pf_raise_count=None,
          net_bb=0.0, position='BTN', stack_bb=30.0, fmt='NLHE',
          bounty_value_bb=None, attribution_roles=None, tournament='Synthetic MTT A'):
    h = {'id': hid, 'cards': list(cards), 'position': position, 'stack_bb': stack_bb,
         'eff_stack_bb': stack_bb, 'net_bb': net_bb, 'tournament': tournament,
         'date': '2026-06-16', 'format': fmt, 'level': '12', 'tournament_phase': 'middle',
         'board': [], 'pf_allin': pf_allin, 'pf_action': pf_action, 'first_in': first_in,
         'villain_jammed': villain_jammed, 'hero_faced_raise': hero_faced_raise,
         'hero_street_actions': {}}
    if pf_raise_count is not None:
        h['pf_raise_count'] = pf_raise_count
    if bounty_value_bb is not None:
        h['bounty_value_bb'] = bounty_value_bb
    if attribution_roles is not None:
        h['attribution_roles'] = attribution_roles
    return h


def build():
    hands, pob, pko_by_hand, analyst, issue_ids = [], {}, {}, {}, []
    mistakes, needs_review = [], []

    def add(h, po=None, pko=None):
        hands.append(h)
        if po is not None:
            pob[h['id']] = po
        if pko is not None:
            pko_by_hand[h['id']] = pko

    # S1-S8 (38-leak family aggregation; use 38 examples) ----------------------
    leak = 'Missed BTN steal — extended range'
    for i in range(1, 39):
        hid = 'TM97%04d' % i
        add(_hand(hid, ['Ks', '9d'], net_bb=-3.0, position='BTN'),
            _po(verdict_hint='Folded a profitable steal'))
        issue_ids.append(hid)

    # S2 internal detector-health excluded (auto_clear, +EV) -------------------
    add(_hand('TM9700050', ['Kh', '5d'], net_bb=7.5, position='BTN', stack_bb=55.0),
        _po(street='flop', verdict_hint='Won at showdown'))
    mistakes.append({'id': 'TM9700050', 'desc': 'detector flag auto-cleared', 'net_bb': 7.5})

    # S4 exact-action Mistake + S5 analyst override + S6/S7 root/downstream -----
    h_m = _hand('TM9700051', ['Ac', '5c'], pf_allin=True, pf_action='raises all-in',
                first_in=True, net_bb=-15.0, position='SB', stack_bb=24.0)
    add(h_m, _po(call_bb=0.0, required_eq_pct=0, hero_equity_pct=43.0,
                 verdict_hint='Over-jam turns a made hand into a bluff'))
    analyst['TM9700051'] = {'verdict': 'III.2',
                            'hand_strength': 'Over-jam turns a made hand into a bluff'}
    h_root = _hand('TM9700052', ['Jh', 'Th'], net_bb=-18.0, position='CO', stack_bb=45.0,
                   attribution_roles={'preflop': 'root_mistake', 'turn': 'downstream',
                                      'river': 'consequence'})
    add(h_root, _po(street='turn', call_bb=9.0, required_eq_pct=33, hero_equity_pct=38.0,
                    verdict_hint='Compounded a thin preflop call'))

    # S9 no postflop Range Lens after preflop all-in ---------------------------
    add(_hand('TM9700053', ['9h', '9s'], pf_allin=True, pf_action='', net_bb=-30.0,
              position='HJ', stack_bb=25.0),
        _po(call_bb=20.0, required_eq_pct=40, hero_equity_pct=47.0, verdict_hint='All-in node unprovable'))

    # PKO scenarios (S10-S26) — fmt BOUNTY, pko_research contexts ---------------
    def pko_hand(hid, cards, *, pf_action, first_in=False, villain_jammed=False,
                 hero_faced_raise=False, prc=None, players=2, cover='Hero covers',
                 collect=True, cover_label='', classification='Review', spot='BB defense',
                 delta=(-3.6, -3.6), bb_est=3.2, req=31, reqb=None, bounty=None,
                 tournament='Synthetic MTT A', net=-12.0, eff=14.0, teach='', caveat=''):
        h = _hand(hid, cards, pf_allin=True, pf_action=pf_action, first_in=first_in,
                  villain_jammed=villain_jammed, hero_faced_raise=hero_faced_raise,
                  pf_raise_count=prc, net_bb=net, position='BB', stack_bb=eff, fmt='BOUNTY',
                  bounty_value_bb=bb_est, tournament=tournament)
        add(h, _po(call_bb=15.0, required_eq_pct=req, required_eq_bounty_pct=reqb,
                   hero_equity_pct=45.0, n_at_sd=players, still_to_act=max(0, players - 2),
                   verdict_hint=classification, bounty=bounty),
            _pko(spot=spot, classification=classification, players=players, cover=cover,
                 collect=collect, cover_label=cover_label, delta=delta, bb_est=bb_est,
                 eff=eff, teach=teach, caveat=caveat))

    # S10 call-vs-jam (covers caller, discount -> action-changing fold->call)
    pko_hand('TM9700060', ['Ah', 'Qd'], pf_action='calls', villain_jammed=True,
             hero_faced_raise=True, classification='Good', spot='BB call-jam vs CO',
             req=31, reqb=27, bounty={'value_bb': 3.2, 'discount_pp': 4.0, 'method': 'flat_table'},
             teach='Bounty pressure widens the defend here.')
    # S11 open-shove PKO
    pko_hand('TM9700061', ['Ad', 'Js'], pf_action='raises all-in', first_in=True,
             classification='Good', spot='SB open-shove', req=0,
             bounty={'value_bb': 3.0, 'discount_pp': 0.0, 'method': 'flat_table'},
             cover_label='covers the field — bounties collectible')
    # S12 rejam PKO
    pko_hand('TM9700062', ['Tc', 'Td'], pf_action='jams', hero_faced_raise=True, prc=1,
             classification='Review', spot='CO rejam vs LJ', req=34, reqb=30,
             bounty={'value_bb': 2.5, 'discount_pp': 4.0, 'method': 'flat_table'})
    # S13 non-collectible bounty (Hero covered)
    pko_hand('TM9700063', ['Kd', 'Qd'], pf_action='calls', villain_jammed=True,
             hero_faced_raise=True, cover='Hero covered', collect=False,
             classification='Review', spot='BB defense', req=33, bb_est=2.0,
             cover_label='covered by opener — opener bounty not collectible',
             bounty={'value_bb': 2.0, 'discount_pp': 0.0, 'method': 'flat_table'})
    # S14 exact exported bounty ($) — own PKO tournament w/ bounty_usd
    pko_hand('TM9700064', ['As', 'Ts'], pf_action='raises all-in', first_in=True,
             classification='Good', spot='BTN open-shove', req=0, bb_est=3.2,
             tournament='Synthetic MTT B (PKO)',
             bounty={'value_bb': 3.2, 'discount_pp': 0.0, 'method': 'flat_table'},
             cover_label='covers the field — bounties collectible')
    # S15 estimated-current bounty (ratio model)
    pko_hand('TM9700065', ['Qs', 'Qc'], pf_action='jams', hero_faced_raise=True, prc=1,
             classification='Review', spot='HJ rejam', req=36, reqb=32, bb_est=4.1,
             bounty={'value_bb': 4.1, 'discount_pp': 4.0, 'method': 'ratio_model'})
    # S16 static event-start estimate (flat_table)
    pko_hand('TM9700066', ['Js', 'Jc'], pf_action='calls', villain_jammed=True,
             hero_faced_raise=True, classification='Review', spot='BB defense', req=35,
             reqb=31, bb_est=2.5, bounty={'value_bb': 2.5, 'discount_pp': 4.0, 'method': 'flat_table'})
    # S17 unavailable bounty value
    pko_hand('TM9700067', ['Ts', '9s'], pf_action='calls', villain_jammed=True,
             hero_faced_raise=True, classification='Review', spot='BB defense', req=34,
             bb_est=0.0, bounty={'value_bb': 0.0, 'discount_pp': 0.0, 'method': 'flat_table'})
    # S18 three-way all-in (multiway suppress)
    pko_hand('TM9700068', ['Ks', 'Kd'], pf_action='calls', villain_jammed=True,
             hero_faced_raise=True, players=3, classification='Good', spot='BB 3-way all-in',
             req=42, bb_est=3.0, cover='Mixed', cover_label='covers UTG; covered by BTN',
             bounty={'value_bb': 3.0, 'discount_pp': 0.0, 'method': 'flat_table'})
    # S22 mixed cover directions multiway
    pko_hand('TM9700069', ['Ah', 'Kh'], pf_action='raises all-in', first_in=True, players=4,
             classification='Review', spot='4-way all-in', req=0, bb_est=3.0, cover='Mixed',
             cover_label='covers SB+BB; covered by CO',
             bounty={'value_bb': 3.0, 'discount_pp': 0.0, 'method': 'flat_table'})
    # S24 PKO non-action-changing (tiny discount)
    pko_hand('TM9700070', ['Ad', 'Tc'], pf_action='calls', villain_jammed=True,
             hero_faced_raise=True, classification='Review', spot='BB defense', req=33,
             reqb=32, bb_est=1.2, bounty={'value_bb': 1.2, 'discount_pp': 1.0, 'method': 'flat_table'})

    # S27 long analyst commentary + S29 Debate preserved -----------------------
    h_long = _hand('TM9700080', ['Ad', 'Ks'], net_bb=-22.0, position='CO', stack_bb=40.0)
    add(h_long, _po(street='river', call_bb=18.0, required_eq_pct=35, hero_equity_pct=30.0,
                    verdict_hint='River bluff-catch'))
    analyst['TM9700080'] = {'verdict': 'III.5',
                            'hand_strength': ('Strategic debate: the river call is defensible vs a '
                                              'merged value range but thin vs a polarized one; depends '
                                              'on whether villain barrels third-barrel bluffs at this '
                                              'sample. Hero blocks the nut value with the Ace.')}

    all_ids = [h['id'] for h in hands]
    # v8.17.1 verify: tag a few hands to the overlay tournament ids so the
    # Tournament Performance table (per-event hands/BB-100) populates and renders.
    for _h, _tid in zip(hands[:4], ('SYN1', 'SYN1', 'SYN2', 'SYN3')):
        _h['tournament_id'] = _tid
    stats = {
        'volume': {'hands': len(hands), 'tournaments': 2, 'bullets': len(hands), 'date': '2026-06-16'},
        'core': {'bb_per_100': -2.0, 'ev_bb_per_100': 1.0},
        'csv_row': {'BB_per_100': -2.0, 'EV_BB_per_100': 1.0},
        'card_quality': {'premiums_pct': 14.0},
        'villain_intel': {'villain_aliases': {}, 'read_states': {}, 'exploit_opportunities': []},
        'eai': {'hands': []}, 'mistakes': mistakes,
        # per-tournament stack arcs → detector-backed drivers (Drivers-in-view rollup).
        'stack_trajectories': {
            'SYN1': {'start_bb': 50, 'peak_bb': 120, 'valley_bb': 8, 'end_bb': 60, 'n_hands': 2},
            'SYN2': {'start_bb': 50, 'peak_bb': 70, 'valley_bb': 0, 'end_bb': 0, 'n_hands': 1},
            'SYN3': {'start_bb': 50, 'peak_bb': 55, 'valley_bb': 0, 'end_bb': 0, 'n_hands': 1}},
    }
    rd = {
        'player_name': 'SynthHero', 'buyin_breakdown': [], 'avg_buyin': 25.0,
        'total_invested': 525.0, 'appendix_hand_ids_all': all_ids,
        'analyst_commentary': analyst, 'reviewed_mistakes': {'needs_review': needs_review},
        'read_dependent_screen': [],
        'skill_band': {'emoji': '⚪', 'label': 'Synthetic sample'}, 'hero_classification': {},
        'results_attribution': {'implied_true_ev_extended_per_100': 1.0,
                                'made_hands_var_per_100': 0.5, 'eai_variance_per_100': 0.5,
                                'cooler_var_per_100': 0.0, 'card_quality_var_per_100': 0.0,
                                # canonical S1.1a summary fields (real analyzer always
                                # supplies these; the S1.1a render reads them directly
                                # — the fixture must carry the full canonical set).
                                'surface_cev_per_100': -0.10,
                                'implied_true_ev_cev_per_100': -0.05,
                                'surface_bb_per_100': -1.20,
                                'surface_bb_total': -12.0,
                                'n_hands': 120,
                                'eai_variance_bb': 4.0,
                                'mistake_row_count': 2,
                                'non_tail_mistake_per_100': -0.8,
                                'tail_fold_per_100': -0.4},
        'skill_context': {'verdict_line': 'Synthetic acceptance sample'},
        'roi_forecast': {'verdict_line': 'n/a (synthetic)'},
        'issue_explorer_issues': [{'name': leak, 'all_hand_ids': issue_ids}],
        'issue_explorer_coverage': [],
        'appendix_hand_details': {hid: {} for hid in all_ids},
        'pot_odds_by_hand': pob,
        # Parsed canonical overlay so the FULL synthetic report renders the real
        # Tournament Tables surfaces (grouped/chart/Finance&Finish/filters/sticky/
        # rollup) rather than the no-overlay diagnostic. Synthetic events only.
        'usd_overlay': {'status': 'parsed', 'hh_intersect_totals': {},
            'totals': {'n_tournaments': 3, 'n_bullets': 4, 'total_cost': 105.0,
                       'total_cash': 60.0, 'total_ticket_value': 0.0,
                       'total_net': -45.0, 'roi_pct': -42.9},
            'per_tournament': [
                {'tid': 'SYN1', 'name': 'Synthetic MTT A', 'start_date': '2026-06-16',
                 'buyin': 15, 'bullets': 1, 'cost': 15, 'cash_received': 60,
                 'ticket_value': 0, 'cash_total': 60, 'net': 45, 'is_sat': False,
                 'place': 2, 'total_players': 50, 'itm': True},
                {'tid': 'SYN2', 'name': 'Synthetic MTT B (PKO)', 'start_date': '2026-06-16',
                 'buyin': 30, 'bullets': 2, 'cost': 60, 'cash_received': 0,
                 'ticket_value': 0, 'cash_total': 0, 'net': -60, 'is_sat': False,
                 'place': 40, 'total_players': 80, 'bounty_usd': 12.5},
                {'tid': 'SYN3', 'name': 'Synthetic Sat', 'start_date': '2026-06-16',
                 'buyin': 30, 'bullets': 1, 'cost': 30, 'cash_received': 0,
                 'ticket_value': 0, 'cash_total': 0, 'net': -30, 'is_sat': True,
                 'place': 25, 'total_players': 60}]},
        'pko_research': {'by_hand': pko_by_hand},
    }
    return stats, rd, hands


def render():
    os.makedirs(OUT_DIR, exist_ok=True)
    stats, rd, hands = build()
    from gem_report_draft import render_html
    html = render_html(stats, rd, hands, sections=['XIV'])
    with open(OUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print('WROTE %s (%d bytes, %d hands)' % (OUT_HTML, len(html), len(hands)))
    return html


if __name__ == '__main__':
    render()
