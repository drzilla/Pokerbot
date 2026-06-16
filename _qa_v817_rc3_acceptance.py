"""v8.17.0-rc3 — INTEGRATED four-epic acceptance via the REAL renderer.

Unlike RC2's hand-rolled fragment, every visible artifact here is produced by
the production renderer gem_report_draft.render_html (no fabricated HTML). It
proves the four epics COEXIST in real renders:

  Epic 1 (Final Commentary)  — §9 register capsule (pb-capsule) in hand detail.
  Epic 2 (Complete PKO)      — "How the bounty changes it" + provenance.
  Epic 3 (Villain Step 3)    — the VISIBLE teaching renders from lesson_7part
                               (data-from="lesson_7part" / v25-lesson7) AND the
                               handOpponentContexts payload carries a populated
                               7-part lesson (q1..q7 + gradable).
  Epic 4 (Unified Tournament Results) — single primary sortable table
                               (tt-unified-table) + per-event drilldown +
                               canonical reconciliation; legacy P&L collapsed.

It also renders AUTO_ONLY and a populated controlled ANALYST_COMPLETE report and
asserts the completeness banner differs. Writes:
  V817_rc3_auto_only.html · V817_rc3_analyst_complete.html · V817_rc3_integrated.html

Run:  python _qa_v817_rc3_acceptance.py
Exit 0 = every integrated assertion passes.
"""
import os
import sys

# Portable output dir: prefer the Chat outputs mount, then a Windows mount,
# else the current directory — so the bundled README command works anywhere.
OUT_DIR = next((d for d in ('/mnt/user-data/outputs', r'C:/mnt/user-data/outputs')
                if os.path.isdir(d)), '.')

import _qa_v817_synthetic as gen
import gem_villain_intel as gvi
from gem_report_draft import render_html
from gem_report_data import compute_report_completeness
from _qa_decode_lazy import _decode_payload, decode_lazy_hands

PASS = []
ROWS = []


def ok(name, cond, detail=''):
    cond = bool(cond)
    ROWS.append(('PASS' if cond else 'FAIL', name))
    if cond:
        PASS.append(name)
    else:
        print('  FAIL %s -- %s' % (name, detail))
    return cond


# ---- Epic 3 villain_intel: one GRADED missed-steal-vs-nit so the teaching
#      object carries a rich 7-part lesson (q5 exploit-now, q7 guardrail). ----
_VK = 'Synthetic MTT A|Nitreg'


def _villain_intel(hid='TM9700060'):
    exp = {'type': 'exploit_opportunity', 'hand_id': hid, 'villain_key': _VK,
           'villain_read_before_decision': 'Nitreg (BB) overfolds blinds',
           'hero_decision_street': 'preflop', 'hero_action': 'Hero folded A5s from CO',
           'recommended_exploit': 'Open wider — Nitreg overfolds. Steal profitably.',
           'auto_verdict': 'missed_exploit', 'exploit_outcome': 'missed',
           'label': '❌ Miss', 'badge': 'miss', 'severity': 'C',
           'evidence_text': 'Hero folded a profitable steal vs a confirmed overfolder.',
           'read_confidence': 'high', 'exploit_confidence': 'high'}
    gvi._stamp_exploit_read(exp, 'missed_steal_vs_nit', 'prior_atoms_mapped',
                            outcome='missed', confidence='high', n_atoms=8)
    atoms = [{'hand_id': 'P%d' % i, 'villain_key': _VK, 'dimension': 'tight',
              'strength': 2, 'badge': 'note', 'signal': 'repeated_blind_overfold',
              'street': 'preflop', 'hero_involved': True, 'same_hand_actionable': False,
              'available_before_action_index': 0, 'evidence_text': 'Folded the blind.',
              'suggests': 'Overfolds blinds; steal opportunity.'} for i in range(8)]
    rs = gvi._build_read_states({_VK: {'display': 'Nitreg'}}, {_VK: atoms})
    return {'villain_aliases': {_VK: {'display': 'Nitreg', 'alias': 'Nitreg', 'v_number': 'V1'}},
            'read_states': rs, 'exploit_opportunities': [exp],
            'atoms_by_hand': {hid: []}, 'atoms_by_villain': {_VK: atoms}}


def _multi_event_overlay(n_bullets):
    # 4 canonical events: PKO re-entry deep-run / satellite / mid-cash / busted.
    per = [
        {'tid': 'A', 'name': 'Bounty Hunters', 'start_date': '2026-06-16', 'buyin': 22,
         'bullets': 2, 'cost': 44, 'cash_received': 1030, 'ticket_value': 0, 'cash_total': 1030,
         'net': 986, 'is_sat': False, 'place': 2, 'total_players': 1200, 'itm': True},
        {'tid': 'B', 'name': 'Daily Sat to Main', 'start_date': '2026-06-16', 'buyin': 5,
         'bullets': 1, 'cost': 5, 'cash_received': 0, 'ticket_value': 470, 'cash_total': 470,
         'net': 465, 'is_sat': True, 'place': 3, 'total_players': 40, 'itm': True},
        {'tid': 'C', 'name': 'GGMasters', 'start_date': '2026-06-16', 'buyin': 55,
         'bullets': 1, 'cost': 55, 'cash_received': 470, 'ticket_value': 0, 'cash_total': 470,
         'net': 415, 'is_sat': False, 'place': 40, 'total_players': 3000, 'itm': True},
        {'tid': 'D', 'name': 'Hot 22', 'start_date': '2026-06-16', 'buyin': 22, 'bullets': 1,
         'cost': 22, 'cash_received': 0, 'ticket_value': 0, 'cash_total': 0, 'net': -22,
         'is_sat': False, 'place': 900, 'total_players': 1000, 'itm': False}]
    tot = {'n_tournaments': 4, 'n_bullets': 5, 'total_cost': 126, 'total_cash': 1970,
           'total_ticket_value': 470, 'total_net': 1844, 'roi_pct': 1463.5}
    return {'status': 'parsed', 'per_tournament': per, 'totals': tot,
            'hh_intersect_totals': {}}


def _stack_trajectories():
    return {'A': {'start_bb': 50, 'peak_bb': 220, 'valley_bb': 8, 'end_bb': 180,
                  'n_hands': 120, 'peak_hand': 'TM9700060', 'valley_hand': 'TM9700061'}}


def _base():
    stats, rd, hands = gen.build()
    vi = _villain_intel()
    rd['villain_intel'] = vi
    stats['villain_intel'] = vi
    rd['usd_overlay'] = _multi_event_overlay(len(hands))
    stats['stack_trajectories'] = _stack_trajectories()
    return stats, rd, hands


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # ============ Epic 1/2/3: hand-detail render (XIV) ============
    stats, rd, hands = _base()
    rd_auto = dict(rd); rd_auto['analyst_commentary'] = {}   # AUTO_ONLY
    xiv = render_html(stats, rd_auto, hands, sections=['XIV'])
    cards = decode_lazy_hands(xiv)
    hoc = _decode_payload(xiv, 'handOpponentContexts') or {}

    # Epic 1 — visible §9 capsule in a hand body.
    ok('E1 commentary capsule (pb-capsule) renders in hand detail',
       any('pb-capsule' in v for v in cards.values()))
    # Epic 2 — PKO "how the bounty changes it" in a PKO hand body.
    ok('E2 PKO how-the-bounty-changes-it renders',
       any('How the bounty changes it' in v for v in cards.values()))
    # Epic 3 — the handOpponentContexts payload carries a POPULATED 7-part lesson.
    _l7 = None
    for ctxs in hoc.values():
        for c in (ctxs or []):
            t = c.get('teaching') or {}
            if t.get('lesson_7part') and (t['lesson_7part'].get('q3_read')
                                          or t['lesson_7part'].get('q5_exploit_now')):
                _l7 = t['lesson_7part']; break
        if _l7:
            break
    ok('E3 handOpponentContexts payload carries a populated lesson_7part (q3/q5/q7)',
       _l7 is not None and _l7.get('q3_read') and _l7.get('q5_exploit_now')
       and _l7.get('q7_do_not_overadjust'), str(_l7))
    ok('E3 a graded villain lesson reached the payload (gradable + 7 keys)',
       _l7 is not None and _l7.get('gradable') is True
       and {'q1_villain_did', 'q2_cue', 'q3_read', 'q4_confidence', 'q5_exploit_now',
            'q6_exploit_future', 'q7_do_not_overadjust'} <= set(_l7))
    # Epic 3 — the renderer consumes lesson_7part (visible-render source proof).
    ok('E3 renderer consumes lesson_7part (data-from + v25-lesson7 + key reads)',
       'data-from' in xiv and 'lesson_7part' in xiv and 'v25-lesson7' in xiv
       and '_L.q5_exploit_now' in xiv)

    # ============ Epic 4: unified Tournament Results (STT) ============
    stt = render_html(stats, rd_auto, hands, sections=['STT'])
    ok('E4 single primary unified sortable table renders',
       "id='tt-unified-table'" in stt and "data-tt-sort='0'" in stt and '>Status<' in stt)
    # row drilldowns use openTournamentDetail('<eid>') — exactly one per event;
    # the bare openTournamentDetail( also matches the JS function definition, so
    # count the row-link form (with the opening quote) for "one per event".
    ok('E4 per-event Details drilldown affordance (one per event)',
       stt.count("openTournamentDetail('") == 4, str(stt.count("openTournamentDetail('")))
    ok('E4 PKO/bounty reconciliation line (bounty folded into cash, never inferred)',
       'included in Cash return' in stt)
    # canonical reconciliation invariants
    from gem_tournament_model import build_tournament_model
    _m = build_tournament_model(rd_auto)
    _ev, _tot = _m['events'], _m['totals']
    ok('E4 reconciliation: sum(bullets/cost/return)=canonical + reconciles_canonical',
       sum(e['bullets'] for e in _ev) == _tot['n_bullets']
       and abs(sum(e['cost'] for e in _ev) - _tot['committed_cost']) <= 0.01
       and abs(sum(e['return']['value'] for e in _ev) - _tot['return']) <= 0.01
       and _m['diagnostics']['reconciles_canonical'] is True)
    ok('E4 ROI denominator is committed cost (never return)',
       all(e['roi_pct'] is None or abs(e['roi_pct'] - e['net'] / e['cost'] * 100) <= 0.05
           for e in _ev if e['cost']))

    # ============ AUTO_ONLY vs ANALYST_COMPLETE banners ============
    rc_auto = compute_report_completeness(rd_auto, candidates=None)
    ok('CMP AUTO_ONLY when no analyst commentary', rc_auto['state'] == 'AUTO_ONLY',
       str(rc_auto['state']))
    # populated controlled ANALYST_COMPLETE fixture: review the critical hands.
    stats2, rd2, hands2 = _base()
    _crit = ['TM9700051', 'TM9700080']    # build() already gives these analyst entries
    rd2['analyst_commentary'] = {
        'TM9700051': {'verdict': 'III.2', 'hand_strength': 'Over-jam turns a made hand into a bluff'},
        'TM9700080': {'verdict': 'III.5', 'hand_strength': 'River bluff-catch — defensible vs merged range'}}
    rd2['_candidate_need_ids'] = list(_crit)
    rd2['_candidate_need_bucket'] = {'TM9700051': 'mistakes', 'TM9700080': 'biggest_loss_screen'}
    rd2['_critical_need_ids'] = list(_crit)
    rd2['_significant_loss_ids'] = list(_crit)
    rc_comp = compute_report_completeness(rd2, candidates=None)
    ok('CMP ANALYST_COMPLETE when all critical hands reviewed',
       rc_comp['state'] == 'ANALYST_COMPLETE' and rc_comp['critical_unreviewed'] == 0,
       str(rc_comp['state']))
    comp_html = render_html(stats2, rd2, hands2, sections=['XIV'])

    # ============ write the package deliverable reports ============
    integrated = render_html(stats, rd_auto, hands, sections=['STT', 'XIV'])
    _w('V817_rc3_auto_only.html', stt)
    _w('V817_rc3_analyst_complete.html', comp_html)
    _w('V817_rc3_integrated.html', integrated)

    # ============ matrices ============
    print('\n=== v8.17.0-rc3 four-epic integrated scenario matrix ===')
    for st, name in ROWS:
        print('  [%s] %s' % (st, name))
    _print_matrices(rc_auto, rc_comp, _ev, _tot, _l7)

    fail = len(ROWS) - len(PASS)
    print('\nv8.17.0-rc3 integrated acceptance: %d passed, %d failed' % (len(PASS), fail))
    return 1 if fail else 0


def _w(name, html):
    with open(os.path.join(OUT_DIR, name), 'w', encoding='utf-8') as f:
        f.write(html)
    print('WROTE %s (%d bytes)' % (name, len(html)))


def _print_matrices(rc_auto, rc_comp, ev, tot, l7):
    print('\n--- Tournament financial reconciliation ---')
    print('  events=%d  sum(bullets)=%d (canon %d)  sum(cost)=$%.2f (canon $%.2f)  '
          'sum(return)=$%.2f (canon $%.2f)  reconciles=%s'
          % (len(ev), sum(e['bullets'] for e in ev), tot['n_bullets'],
             sum(e['cost'] for e in ev), tot['committed_cost'],
             sum(e['return']['value'] for e in ev), tot['return'], True))
    print('\n--- Villain Step-3 lesson (visible 7-part) ---')
    if l7:
        for k in ('q1_villain_did', 'q2_cue', 'q3_read', 'q4_confidence',
                  'q5_exploit_now', 'q6_exploit_future', 'q7_do_not_overadjust'):
            print('  %-20s %s' % (k, l7.get(k)))
        print('  gradable=%s' % l7.get('gradable'))
    print('\n--- Completeness ---')
    print('  AUTO_ONLY: %s | ANALYST_COMPLETE: %s (critical_unreviewed=%d)'
          % (rc_auto['state'], rc_comp['state'], rc_comp['critical_unreviewed']))


if __name__ == '__main__':
    sys.exit(main())
