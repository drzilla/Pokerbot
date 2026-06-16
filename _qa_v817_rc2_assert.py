"""v8.17.0-rc2 — four-epic synthetic acceptance via the REAL renderer.

Renders the unified Tournament Results section (Epic 4) and builds Villain
Step-3 teaching objects (Epic 3) through the production code paths, then asserts
the acceptance contract. Epics 1+2 (Commentary capsule + PKO) are covered by
_qa_v817_assert.py / T-CAP817 / T-PKO817; this harness covers the two new epics
end-to-end and emits a visible acceptance HTML for browser QA.

Run: python _qa_v817_rc2_assert.py [out_html]
Exit 0 = all pass.
"""
import json
import sys

from gem_report_draft._html import Doc
from gem_report_draft.sections_tournaments import _emit_tournament_tables
from gem_tournament_model import build_tournament_model
import gem_villain_teaching as vt

PASS = []


def ok(name, cond, detail=''):
    if not cond:
        print('FAIL  %s  %s' % (name, detail))
        raise SystemExit(1)
    PASS.append(name)
    print('OK    %s' % name)


# ---- Epic 4: unified Tournament Results (4 events: PKO re-entry deep-run /
#      satellite ticket / mid-field cash / busted; canonical totals reconcile) ----
RD = {'platform': 'GG', 'usd_overlay': {'status': 'parsed', 'totals': {
    'n_tournaments': 4, 'n_bullets': 6, 'total_cost': 148, 'total_cash': 1970,
    'total_ticket_value': 470, 'total_net': 1822, 'roi_pct': 1231.1},
    'per_tournament': [
        {'tid': 'A', 'name': 'Bounty Hunters', 'start_date': '2026-06-14', 'buyin': 22,
         'bullets': 3, 'cost': 66, 'cash_received': 1030, 'ticket_value': 0,
         'cash_total': 1030, 'net': 964, 'is_sat': False, 'place': 2, 'total_players': 1200, 'itm': True},
        {'tid': 'B', 'name': 'Daily Sat to Main', 'start_date': '2026-06-14', 'buyin': 5,
         'bullets': 1, 'cost': 5, 'cash_received': 0, 'ticket_value': 470, 'cash_total': 0,
         'net': 465, 'is_sat': True, 'place': 3, 'total_players': 40, 'itm': True},
        {'tid': 'C', 'name': 'GGMasters', 'start_date': '2026-06-15', 'buyin': 55,
         'bullets': 1, 'cost': 55, 'cash_received': 470, 'ticket_value': 0, 'cash_total': 470,
         'net': 415, 'is_sat': False, 'place': 40, 'total_players': 3000, 'itm': True},
        {'tid': 'D', 'name': 'Hot 22', 'start_date': '2026-06-15', 'buyin': 22, 'bullets': 1,
         'cost': 22, 'cash_received': 0, 'ticket_value': 0, 'cash_total': 0, 'net': -22,
         'is_sat': False, 'place': 900, 'total_players': 1000, 'itm': False}]}}
S = {'stack_trajectories': {'A': {'start_bb': 50, 'peak_bb': 220, 'valley_bb': 8,
     'end_bb': 180, 'n_hands': 310, 'peak_hand': 'H1', 'valley_hand': 'H2'}}}
HANDS = ([{'id': '7100000%d' % i, 'tournament_id': 'A'} for i in range(3)]
         + [{'id': '72000001', 'tournament_id': 'B'}, {'id': '73000001', 'tournament_id': 'C'}])

_doc = Doc()
_emit_tournament_tables(_doc, S, RD, HANDS)
TT_MD = _doc.render_md()
_pj = [j for j in _doc._extra_js if j.startswith('window.tournamentEvents=')][0]
PAYLOAD = json.loads(_pj[len('window.tournamentEvents='):-1])
BY = {p['name']: p for p in PAYLOAD}

ok('E4-01 single primary unified sortable table', "id='tt-unified-table'" in TT_MD and "data-tt-sort='0'" in TT_MD)
ok('E4-02 one drilldown per event', TT_MD.count('openTournamentDetail(') == 4)
ok('E4-03 PKO re-entry deep-run', BY['Bounty Hunters']['status'] == 'Deep run' and BY['Bounty Hunters']['bullets'] == 3)
ok('E4-04 stack arc folded into drilldown', any('Stack arc' in x for x in BY['Bounty Hunters']['drivers']))
ok('E4-05 satellite ticket return', BY['Daily Sat to Main']['status'] == 'Deep run'
   and any('Ticket' in b for b in BY['Daily Sat to Main']['return_breakdown']))
ok('E4-06 busted event is not a deep run', BY['Hot 22']['status'] == '—')
ok('E4-07 bounty $ never inferred', any('not separately sourced' in b for b in BY['Bounty Hunters']['return_breakdown'])
   and 'included in Cash return' in TT_MD)
_m = build_tournament_model(RD)
_ev, _tot = _m['events'], _m['totals']
ok('E4-08 sum(bullets)=canonical', sum(e['bullets'] for e in _ev) == _tot['n_bullets'] == 6)
ok('E4-09 sum(cost)=canonical', abs(sum(e['cost'] for e in _ev) - _tot['committed_cost']) <= 0.01)
ok('E4-10 sum(return)=canonical', abs(sum(e['return']['value'] for e in _ev) - _tot['return']) <= 0.01)
ok('E4-11 reconciles_canonical', _m['diagnostics']['reconciles_canonical'] is True)
ok('E4-12 ROI denom is committed cost', all(e['roi_pct'] is None
   or abs(e['roi_pct'] - e['net'] / e['cost'] * 100) <= 0.05 for e in _ev if e['cost']))
ok('E4-13 one row per event_id (re-entries merged)', len({e['event_id'] for e in _ev}) == 4)


# ---- Epic 3: Villain Step-3 7-part lesson (graded / non-graded / thin) ----
def _exp(**k):
    b = {'villain_key': 'T|v', 'hand_id': 'H', 'exploit_read_label': 'Nit / Rock',
         'exploit_read_display': 'Nit / Rock', 'read_source': 'prior_atoms_mapped',
         'evidence_text': 'Folded blinds 9 of last 10.', 'suggests': 'Overfolds blinds.',
         'so_what': 'Open wider from CO/BTN.', 'recommended_exploit': 'Steal wider vs this player.',
         'hero_decision_street': 'preflop', 'available_before_action_index': 0, 'gradable': True,
         'non_gradable_reason': '', 'exploit_detector': 'missed_steal_vs_nit',
         'exploit_outcome': 'missed', 'auto_verdict': 'missed_exploit'}
    b.update(k)
    return b


_rs = {'T|v': {'villain_alias': 'Reg', 'primary_read': 'Nit / Rock', 'confidence': 'high',
               'n_evidence': 9, 'evidence_hand_ids': ['P1', 'P2', 'P3'], 'profile_label': 'consistent'}}
_g = vt.teaching_from_exploit(_exp(), _rs, {'T|v': [{'dimension': 'tight'}] * 9})
_l = _g['lesson_7part']
ok('E3-01 all 7 parts present (graded)', all(_l[k] for k in (
    'q1_villain_did', 'q2_cue', 'q3_read', 'q4_confidence', 'q5_exploit_now',
    'q6_exploit_future', 'q7_do_not_overadjust')))
ok('E3-02 graded trusted exploit', _l['gradable'] is True and _l['non_gradable_reason'] == ''
   and _g['teaching_status'] in vt._GRADED_STATUSES)
_ng = vt.teaching_from_exploit(
    _exp(exploit_detector='bluffed_sticky', gradable=False, non_gradable_reason='no_trusted_baseline'),
    {'T|v': dict(_rs['T|v'], primary_read='Sticky Passive')}, {'T|v': [{'dimension': 'sticky'}] * 9})
ok('E3-03 non-trusted -> factual moment, not graded', _ng['teaching_status'] not in vt._GRADED_STATUSES
   and _ng['non_gradable_reason'] == 'no_trusted_baseline')
_thin = vt.teaching_from_exploit(_exp(evidence_text='', suggests=''),
                                 {'T|v': {'n_evidence': 1, 'evidence_hand_ids': ['H']}}, {'T|v': []})
ok('E3-04 thin read -> fallback, no grade', _thin['fallback']
   and _thin['lesson_7part']['q1_villain_did'] == vt.FALLBACK_LINE
   and not _thin['lesson_7part']['gradable'])
# split/mixed aggregate dominates; consistent keeps node-specific cue
_mx = vt.teaching_from_atom(
    {'villain_key': 'T|m', 'hand_id': 'H', 'signal': 'open_limp', 'street': 'preflop',
     'same_hand_actionable': True, 'available_before_action_index': 1, 'hero_involved': True,
     'evidence_text': 'Open-limped MP.', 'suggests': 'Loose-passive tendency.', 'so_what': 'Iso wider.'},
    {'T|m': {'primary_read': 'Aggressive', 'confidence': 'high', 'n_evidence': 9,
             'evidence_hand_ids': ['H9', 'H7', 'H5'], 'profile_label': 'mixed'}},
    {'T|m': [{'dimension': 'loose_passive'}] * 9}, signal_coaching={})
ok('E3-05 mixed aggregate dominates the Read line', _mx['profile_label'] == 'mixed'
   and any('Mixed profile' in x for x in _mx['teach_lines']))


def _emit_html(path):
    cards = []
    for nm, p in BY.items():
        cards.append(
            "<div class='ev'><b>%s</b> — %s · %s bullets · Invested %s · Finish %s · "
            "Return %s · Net %s · ROI %s · <span class='st'>%s</span></div>" % (
                nm, p['format'], p['bullets'], p['cost'], p['finish_txt'],
                p['return_txt'], p['net_txt'], p['roi_txt'], p['status']))
    teach = '<br>'.join(l for l in _g['teach_lines'])
    html = (
        "<!doctype html><meta charset='utf-8'><title>v8.17.0-rc2 four-epic acceptance</title>"
        "<style>body{font:14px system-ui;margin:24px;max-width:1000px}"
        ".ev{padding:6px 10px;border-left:4px solid #6366f1;margin:4px 0;background:#f5f7ff}"
        ".st{font-weight:700;color:#3730a3}pre{background:#f1f5f9;padding:10px;overflow:auto}"
        ".card{border:1px solid #c7d2fe;border-radius:8px;padding:12px;background:#fafbff;margin:8px 0}</style>"
        "<h1>v8.17.0-rc2 — four-epic synthetic acceptance (real renderer)</h1>"
        "<h2>Epic 4 — Unified Tournament Results (canonical events)</h2>"
        + ''.join(cards)
        + "<p>Reconciliation: sum(bullets)=%d=canonical · sum(cost)=$%.0f=canonical · "
          "reconciles_canonical=%s</p>" % (
              sum(e['bullets'] for e in _ev), sum(e['cost'] for e in _ev),
              _m['diagnostics']['reconciles_canonical'])
        + "<h3>Live unified-table markup (excerpt)</h3><pre>"
        + (TT_MD[TT_MD.find("id='tt-unified-table'") - 80:TT_MD.find("</tbody>") + 8]
           .replace('<', '&lt;')) + "</pre>"
        + "<h2>Epic 3 — Villain Step-3 7-part lesson (graded example)</h2>"
        + "<div class='card'>" + teach + "</div>"
        + "<p>gradable=%s · teaching_status=%s · profile_label=%s</p>" % (
            _l['gradable'], _g['teaching_status'], _g['profile_label'])
        + "<p style='color:#475467'>Non-graded factual moment reason: %s · "
          "thin-read fallback shown when evidence is one cue.</p>" % _ng['non_gradable_reason'])
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    print('wrote acceptance HTML ->', path)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        _emit_html(sys.argv[1])
    print('\nv8.17.0-rc2 four-epic synthetic acceptance: %d/%d PASS' % (len(PASS), len(PASS)))
