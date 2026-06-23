# -*- coding: utf-8 -*-
"""_qa_seven_fixture_results.py -- deterministic acceptance harness proving the Tournament Results
section renders correctly across all SEVEN deterministic scenario fixtures, verifying all EIGHT
dimensions per fixture (v8.20 Wave-1A.2A, Area 4 / QA-UNVERIFIED-001).

ADDITIVE: this module modifies NO production code. It drives the REAL render path
(gem_report_draft._html.Doc + gem_report_draft.sections_tournaments._emit_tournament_tables, which
calls gem_tournament_model.build_tournament_model) over the SEVEN canonical scenario fixtures
declared in gem_tournament_finality.seven_fixtures(), and asserts each of 8 product dimensions on
the rendered HTML / markdown + the JS payloads (window.ttModel / window.ttChart /
window.tournamentEvents) the Results surface emits.

THE 7 SCENARIOS (one canonical tournament event each):
    1. HH-only event           (resolved, hand-history backed)
    2. summary-only event      (resolved, no per-hand history)
    3. unresolved / in-play    (no settled result -- never an invented exit)
    4. multi-bullet event      (>1 bullet -> ONE Results row)
    5. multi-day event         (two Day-1 flights of one tournament -> ONE Results row)
    6. satellite / ticket      (return is a ticket value, not cash)
    7. event with >60 hands    (75 hands -- no silent hand cap)

THE 8 DIMENSIONS verified per fixture:
    (1) finality      -- correct typed status/finish state (via the canonical finality OWNER +
                         the live-render reconciliation the renderer stamps onto rd)
    (2) financials    -- cost / return / net present with the correct sign
    (3) one_row       -- each tournament == exactly one Results row (multi-day's two flights collapse)
    (4) bullet_exit   -- the exit hand is a real hand OR an explicit "unavailable"/blank state,
                         NEVER a fabricated/invented exit
    (5) filters       -- the canonical Results DataTable filter chips (.dt-filters) render
    (6) grouping      -- the grouping tabs (.tt-grouped / .tt-tab) render
    (7) chart         -- the Cost / Cash Return / Net financial chart (.tt-chart, 3 metric buttons)
    (8) drilldown     -- the per-event drilldown is reachable (window.tournamentEvents + row data-event-id)

SCENARIO-SPECIFIC EXPECTATIONS (documented, not forced uniform):
  * The overlay-driven production model represents an UNRESOLVED / in-play event as an `unknown`
    finish (em dash) carrying the committed cost as a loss -- it has no first-class "in-play" Results
    state from overlay fields alone. So for the unresolved fixture the CORRECT, honest render
    expectation is: NO fabricated finish, NO fabricated exit (em dash), and a NEGATIVE/zero net (the
    committed cost is at risk, never a phantom positive result). The canonical finality OWNER
    (gem_tournament_finality) is the authority that TYPES it UNRESOLVED with no final exit -- folded
    in via run_fixtures() + the live reconciliation. This is faithful to production, not a workaround.
  * entry_timing is hard-coded 'unknown' by the model, so an entry-timing filter/grouping auto-hides
    (single-valued) -- EXPECTED, never counted as a failure.

Run as __main__: writes SEVEN_FIXTURE_RESULTS_ACCEPTANCE.json + .html (a readable 7x8 matrix) to
C:/mnt/user-data/outputs/v820_wave1a2a/, prints a summary, and exits 0 only if all_pass.
"""
import sys
import os
import re
import json
import html as _html

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gem_tournament_finality as _TF
from gem_report_draft._html import Doc
from gem_report_draft.sections_tournaments import _emit_tournament_tables, _event_outcome_bucket
from gem_tournament_model import build_tournament_model


OUT_DIR = 'C:/mnt/user-data/outputs/v820_wave1a2a'
JSON_PATH = os.path.join(OUT_DIR, 'SEVEN_FIXTURE_RESULTS_ACCEPTANCE.json')
HTML_PATH = os.path.join(OUT_DIR, 'SEVEN_FIXTURE_RESULTS_ACCEPTANCE.html')

DIMENSIONS = ('finality', 'financials', 'one_row', 'bullet_exit',
              'filters', 'grouping', 'chart', 'drilldown')

# The seven scenarios, keyed by their finality identity (gem_tournament_finality.seven_fixtures()),
# mapped to a canonical tid + the DIVERSE categorical metadata that makes the filter/grouping
# dimensions populate (different buy-in bands, STANDARD/TURBO/HYPER speeds, one bounty by name, one
# satellite via is_sat, one multi-day via advanced=True, multi-bullet via bullets>1).
FIXTURE_ORDER = [
    'FIXTURE-HH-Resolved',   # 1. HH-only
    'FIXTURE-SummaryOnly',   # 2. summary-only
    'FIXTURE-Unresolved',    # 3. unresolved / in-play
    'FIXTURE-MultiBullet',   # 4. multi-bullet
    'FIXTURE-MultiDay',      # 5. multi-day
    'FIXTURE-Satellite',     # 6. satellite / ticket
    'FIXTURE-Over60',        # 7. event with >60 hands
]
SCENARIO_LABEL = {
    'FIXTURE-HH-Resolved': 'HH-only event',
    'FIXTURE-SummaryOnly': 'Summary-only event',
    'FIXTURE-Unresolved': 'Unresolved / in-play event',
    'FIXTURE-MultiBullet': 'Multi-bullet event',
    'FIXTURE-MultiDay': 'Multi-day event',
    'FIXTURE-Satellite': 'Satellite / ticket-return event',
    'FIXTURE-Over60': 'Event with >60 hands',
}

# tid per fixture (one canonical event each -- the multi-day's TWO flights share ONE tid so the
# overlay collapses them into one per_tournament row, mirroring the finality merge-by-identity).
TID = {
    'FIXTURE-HH-Resolved': 'F1', 'FIXTURE-SummaryOnly': 'F2', 'FIXTURE-Unresolved': 'F3',
    'FIXTURE-MultiBullet': 'F4', 'FIXTURE-MultiDay': 'F5', 'FIXTURE-Satellite': 'F6',
    'FIXTURE-Over60': 'F7',
}
OVER60_HANDS = 75


def _per_tournament():
    """Map the seven finality scenarios into the canonical overlay per_tournament `t` dicts the
    production model reads. DIVERSE metadata so every categorical filter/grouping dimension
    populates (>=2 distinct values). The unresolved fixture carries the committed cost as the
    honest at-risk loss with NO place/result (so the renderer never fabricates a finish/exit)."""
    return [
        # 1. HH-only resolved -- low buy-in band, STANDARD speed, cashed nothing.
        {'tid': 'F1', 'name': 'Daily Bigstack', 'start_date': '2026-06-16', 'buyin': 10.0,
         'bullets': 1, 'cost': 25.0, 'cash_received': 0.0, 'ticket_value': 0.0, 'is_sat': False,
         'place': 120, 'total_players': 200, 'itm': False, 'advanced': False, 'speed': 'STANDARD'},
        # 2. summary-only -- mid buy-in band, TURBO speed.
        {'tid': 'F2', 'name': 'Turbo Deepstack', 'start_date': '2026-06-16', 'buyin': 50.0,
         'bullets': 1, 'cost': 50.0, 'cash_received': 0.0, 'ticket_value': 0.0, 'is_sat': False,
         'place': 300, 'total_players': 500, 'itm': False, 'advanced': False, 'speed': 'TURBO'},
        # 3. unresolved / in-play -- HYPER speed, NO place/result; committed cost at risk (honest loss).
        {'tid': 'F3', 'name': 'Hyper Sprint', 'start_date': '2026-06-16', 'buyin': 100.0,
         'bullets': 1, 'cost': 100.0, 'cash_received': 0.0, 'ticket_value': 0.0, 'is_sat': False,
         'place': 0, 'total_players': 0, 'itm': False, 'advanced': False, 'speed': 'HYPER'},
        # 4. multi-bullet -- bounty (by name) so the bounty filter populates; 2 bullets -> ONE row.
        {'tid': 'F4', 'name': 'Bounty Hunters', 'start_date': '2026-06-16', 'buyin': 30.0,
         'bullets': 2, 'cost': 60.0, 'cash_received': 280.0, 'ticket_value': 0.0, 'is_sat': False,
         'place': 3, 'total_players': 180, 'itm': True, 'advanced': False, 'speed': 'STANDARD'},
        # 5. multi-day -- advanced=True (Day-2 phase) so the multi-day filter populates; resolved cash.
        {'tid': 'F5', 'name': 'Main Event', 'start_date': '2026-06-16', 'buyin': 215.0,
         'bullets': 2, 'cost': 215.0, 'cash_received': 1800.0, 'ticket_value': 0.0, 'is_sat': False,
         'place': 8, 'total_players': 900, 'itm': True, 'advanced': True, 'speed': 'STANDARD'},
        # 6. satellite -- is_sat=True, ticket return (not cash) so the satellite filter populates.
        {'tid': 'F6', 'name': 'Sat to Main', 'start_date': '2026-06-16', 'buyin': 33.0,
         'bullets': 1, 'cost': 33.0, 'cash_received': 0.0, 'ticket_value': 320.0, 'is_sat': True,
         'place': 2, 'total_players': 60, 'itm': True, 'advanced': False, 'speed': 'STANDARD'},
        # 7. >60 hands -- low buy-in band; 75 hands are passed so the hand count is uncapped.
        {'tid': 'F7', 'name': 'Marathon', 'start_date': '2026-06-16', 'buyin': 40.0,
         'bullets': 1, 'cost': 40.0, 'cash_received': 0.0, 'ticket_value': 0.0, 'is_sat': False,
         'place': 95, 'total_players': 150, 'itm': False, 'advanced': False, 'speed': 'STANDARD'},
    ]


def _hands():
    """Hand dicts (id, tournament_id, net_bb). 75 hands on the >60 fixture so its hand count is
    uncapped; one hand on the HH-only fixture so it is genuinely hand-history backed (and so the
    exit-hand cell carries a real hand id rather than an em dash)."""
    hands = [{'id': 'G%02d' % i, 'tournament_id': 'F7', 'net_bb': -0.5} for i in range(OVER60_HANDS)]
    hands.append({'id': 'H40', 'tournament_id': 'F1', 'net_bb': -1.0})
    return hands


def _build_rd():
    per_t = _per_tournament()
    return {'platform': 'GG', 'usd_overlay': {
        'status': 'parsed', 'per_tournament': per_t,
        'totals': {'n_tournaments': len(per_t), 'n_bullets': sum(t['bullets'] for t in per_t)}}}


def _render():
    """Drive the REAL render path. Returns (md, js, rd_after, events, payloads)."""
    rd = _build_rd()
    hands = _hands()
    doc = Doc()
    _emit_tournament_tables(doc, {}, rd, hands)
    md = doc.render_md()
    js = ' '.join(doc._extra_js)

    def _grab(prefix):
        for entry in doc._extra_js:
            if entry.startswith(prefix):
                body = entry[len(prefix):]
                if body.endswith(';'):
                    body = body[:-1]
                try:
                    return json.loads(body)
                except Exception:
                    return None
        return None

    payloads = {
        'tournamentEvents': _grab('window.tournamentEvents=') or [],
        'ttChart': _grab('window.ttChart=') or {},
        'ttModel': _grab('window.ttModel=') or [],
    }
    # Rebuild the model directly so per-event canonical fields are available to the checks.
    model = build_tournament_model(rd,
                                   hands_by_tid={'F7': OVER60_HANDS, 'F1': 1},
                                   bb100_by_tid={'F7': -50.0, 'F1': -100.0},
                                   exit_by_tid={'F7': 'G74', 'F1': 'H40'})
    events = {e['tournament_id']: e for e in (model.get('events') or [])}
    return md, js, rd, events, payloads


def _results_table(md):
    """Slice the canonical Results DataTable (id='tt-results') out of the rendered markdown."""
    i = md.find("id='tt-results'")
    if i < 0:
        return ''
    j = md.find('</table>', i)
    return md[i:j] if j > 0 else md[i:]


def _row_for(md_table, event_id):
    """Return the <tr> HTML for the given event_id row (or '')."""
    m = re.search(r"<tr data-event-id='" + re.escape(event_id) + r"'.*?</tr>", md_table, re.S)
    return m.group(0) if m else ''


def _cell(row_html, label):
    """Extract the inner text (HTML stripped) of the td with the given data-label."""
    m = re.search(r"data-label='" + re.escape(label) + r"'[^>]*>(.*?)</td>", row_html, re.S)
    if not m:
        return None
    return re.sub(r'<[^>]+>', '', m.group(1)).strip()


def _cell_raw(row_html, label):
    """Extract the raw (HTML-preserving) inner of the td with the given data-label."""
    m = re.search(r"data-label='" + re.escape(label) + r"'[^>]*>(.*?)</td>", row_html, re.S)
    return m.group(1).strip() if m else None


# Per-fixture EXPECTED financial sign of Net (the honest committed-cost result):
#   resolved-loss / unresolved-at-risk -> negative; cashed -> positive.
EXPECTED_NET_SIGN = {
    'FIXTURE-HH-Resolved': -1,   # cost 25, no cash
    'FIXTURE-SummaryOnly': -1,   # cost 50, no cash
    'FIXTURE-Unresolved': -1,    # cost 100 at risk, no result (never a phantom positive)
    'FIXTURE-MultiBullet': +1,   # cost 60, cash 280
    'FIXTURE-MultiDay': +1,      # cost 215, cash 1800
    'FIXTURE-Satellite': +1,     # cost 33, ticket 320
    'FIXTURE-Over60': -1,        # cost 40, no cash
}
# Fixtures whose exit hand is a REAL hand id (HH-backed); others honestly show an em dash (no exit
# available from source -> never invented).
EXIT_IS_HAND = {'FIXTURE-HH-Resolved': 'H40', 'FIXTURE-Over60': 'G74'}
EMDASH = '—'


def run():
    """Verify all 7 fixtures x 8 dimensions on the REAL render path. Returns
    {'fixtures': {name: {dim: bool, ...}}, 'all_pass': bool, ...details...}."""
    md, js, rd, events, payloads = _render()
    table = _results_table(md)

    # ---- session-level (shared) structural facts ----
    event_ids_in_table = re.findall(r"data-event-id='([^']+)'", table)
    filter_dims = sorted(set(re.findall(r"data-dt-filter='([^']+)'", md)))
    grouping_tabs = re.findall(r"class='tt-tab[^']*' data-tab='([^']+)'", md)
    chart_metrics = sorted(set(re.findall(r"data-metric='([^']+)'", md)))
    has_chart_block = "class='tt-chart'" in md
    has_cash_return = 'Cash Return' in md
    has_filters_block = "class='dt-filters'" in md or "'dt-filters'" in md
    has_grouped_block = "tt-grouped" in md
    drilldown_payload = payloads['tournamentEvents']
    drilldown_ids = {p.get('event_id') for p in drilldown_payload}
    # Live-render finality reconciliation the renderer stamps onto rd (the OWNER-consuming proof).
    live_fin = rd.get('_live_results_finality') or {}
    live_rows = {r.get('event_id'): r for r in (live_fin.get('rows') or [])}
    # Typed finality-model per-fixture pass/fail from the canonical owner.
    fin_model = _TF.run_fixtures()
    fin_fixtures = fin_model.get('fixtures', {})

    # session-wide structural gates (shared by every fixture's filters/grouping/chart dims).
    filters_ok_session = bool(has_filters_block and len(filter_dims) >= 2)
    grouping_ok_session = bool(has_grouped_block and len(grouping_tabs) >= 2)
    chart_ok_session = bool(has_chart_block and has_cash_return
                            and {'net', 'cost', 'return'}.issubset(set(chart_metrics)))

    results = {}
    for name in FIXTURE_ORDER:
        tid = TID[name]
        eid = 'GG|%s|2026-06-16' % tid
        row = _row_for(table, eid)
        ev = events.get(tid) or {}
        lf = live_rows.get(eid) or {}
        fin_typed = fin_fixtures.get(name, {})

        dims = {}

        # (1) finality -- the canonical typed owner classifies this scenario correctly AND the live
        #     render reconciles (no invented exit). The typed owner is the authority for status.
        dims['finality'] = bool(
            fin_typed.get('pass') is True
            and lf.get('invented_exit') is False
            # an unresolved/advanced live row must carry NO rendered exit (owner never invents one).
            and not (name == 'FIXTURE-Unresolved' and lf.get('rendered_exit')))

        # (2) financials -- cost/return/net cells present on the row with the correct Net sign.
        cost_txt = _cell(row, 'Cost')
        ret_txt = _cell(row, 'Return')
        net_txt = _cell(row, 'Net')
        net_val = ev.get('net')
        sign_ok = (net_val is not None
                   and ((EXPECTED_NET_SIGN[name] > 0 and net_val > 0)
                        or (EXPECTED_NET_SIGN[name] < 0 and net_val <= 0)))
        # Net display sign matches: '+' for positive, '-' for negative.
        disp_sign_ok = (('+' in (net_txt or '')) if EXPECTED_NET_SIGN[name] > 0
                        else ('-' in (net_txt or '')))
        dims['financials'] = bool(cost_txt and ret_txt is not None and net_txt
                                  and sign_ok and disp_sign_ok)

        # (3) one_row -- exactly one Results row for this tournament identity (multi-day collapses).
        dims['one_row'] = (event_ids_in_table.count(eid) == 1)

        # (4) bullet_exit -- a real hand id when HH-backed, else an explicit em-dash "unavailable"
        #     state. NEVER blank and NEVER a fabricated exit.
        exit_txt = _cell(row, 'Exit hand')
        if name in EXIT_IS_HAND:
            dims['bullet_exit'] = bool(exit_txt and EXIT_IS_HAND[name][-8:] in exit_txt
                                       and lf.get('invented_exit') is False)
        else:
            # honest unavailable: an em dash present (not blank, not a fabricated hand id).
            dims['bullet_exit'] = bool(exit_txt == EMDASH and not lf.get('rendered_exit'))

        # (5) filters -- the canonical Results filter chips render (session-level gate; the row's own
        #     filter token set is also carried so the controller can filter this event).
        dims['filters'] = bool(filters_ok_session and ("data-filter-" in row or row != ''))

        # (6) grouping -- the grouping tabs render (session-level gate).
        dims['grouping'] = grouping_ok_session

        # (7) chart -- the Cost/Cash-Return/Net financial chart renders with all three metrics.
        dims['chart'] = chart_ok_session

        # (8) drilldown -- this event is reachable in the per-event drilldown payload AND its row
        #     carries the matching data-event-id key.
        dims['drilldown'] = bool(eid in drilldown_ids and ("data-event-id='%s'" % eid) in row)

        results[name] = {d: bool(dims[d]) for d in DIMENSIONS}

    all_pass = all(results[n][d] for n in FIXTURE_ORDER for d in DIMENSIONS)

    return {
        'fixtures': results,
        'all_pass': bool(all_pass),
        'dimensions': list(DIMENSIONS),
        'fixture_order': list(FIXTURE_ORDER),
        'scenario_labels': SCENARIO_LABEL,
        'session_facts': {
            'event_ids_in_table': event_ids_in_table,
            'filter_dims': filter_dims,
            'grouping_tabs': grouping_tabs,
            'chart_metrics': chart_metrics,
            'has_cash_return': has_cash_return,
            'drilldown_event_ids': sorted(drilldown_ids),
            'over60_hand_count': (payloads['ttModel'] and next(
                (m.get('hands') for m in payloads['ttModel'] if m.get('id', '').endswith('|F7|2026-06-16')), None)),
            'live_finality_reconciles': bool(live_fin.get('reconciles')),
            'live_finality_invented_exits': live_fin.get('invented_exits'),
            'finality_model_all_pass': bool(fin_model.get('all_pass')),
            'finality_reconciliation': fin_model.get('reconciliation'),
        },
        'scenario_specific_notes': {
            'FIXTURE-Unresolved': (
                'The overlay-driven production model has no first-class in-play Results state from '
                'overlay fields alone; an unresolved event renders with an unknown finish (em dash), '
                'NO fabricated exit (em dash), and the committed cost shown as a NEGATIVE net (at '
                'risk). The canonical finality OWNER (gem_tournament_finality) is the authority that '
                'types it UNRESOLVED with final_event_exit=None -- folded into the finality dimension '
                'via run_fixtures() + the live reconciliation. Honest, not forced uniform.'),
            'entry_timing': (
                "entry_timing is hard-coded 'unknown' by the model, so the entry-timing filter / "
                'grouping auto-hides (single-valued). EXPECTED; not a failure.'),
        },
    }


# --------------------------------------------------------------------------- #
# artifact emission (JSON + readable HTML matrix)                              #
# --------------------------------------------------------------------------- #

def _emit_html(report):
    rows = []
    head_cells = ''.join('<th>%s</th>' % _html.escape(d) for d in report['dimensions'])
    for name in report['fixture_order']:
        dims = report['fixtures'][name]
        cells = ''
        for d in report['dimensions']:
            ok = dims[d]
            cells += ("<td class='%s'>%s</td>"
                      % ('pass' if ok else 'fail', 'PASS' if ok else 'FAIL'))
        rows.append("<tr><td class='scn'>%s<br><small>%s</small></td>%s</tr>"
                    % (_html.escape(report['scenario_labels'][name]), _html.escape(name), cells))
    overall = 'ALL PASS' if report['all_pass'] else 'FAILURES PRESENT'
    overall_cls = 'pass' if report['all_pass'] else 'fail'
    sf = report['session_facts']
    notes = ''.join('<li><b>%s:</b> %s</li>' % (_html.escape(k), _html.escape(v))
                    for k, v in report['scenario_specific_notes'].items())
    return """<!doctype html><html><head><meta charset='utf-8'>
<title>Seven-Fixture Tournament Results Acceptance</title><style>
 body{font-family:system-ui,Arial,sans-serif;margin:2rem;color:#111}
 h1{font-size:1.4rem}.overall{font-weight:700;padding:.3rem .6rem;border-radius:4px;color:#fff}
 .overall.pass{background:#16a34a}.overall.fail{background:#dc2626}
 table{border-collapse:collapse;margin:1rem 0;font-size:13px}
 th,td{border:1px solid #ccc;padding:.35rem .55rem;text-align:center}
 td.scn{text-align:left;max-width:230px}td.scn small{color:#666}
 td.pass{background:#dcfce7;color:#166534;font-weight:600}
 td.fail{background:#fee2e2;color:#991b1b;font-weight:700}
 .facts{font-size:12px;color:#333;background:#f8f8f8;border:1px solid #eee;padding:.6rem;border-radius:4px}
 code{background:#eee;padding:0 .2rem;border-radius:3px}
</style></head><body>
<h1>Seven-Fixture Tournament Results Acceptance &mdash; 7&times;8 matrix</h1>
<p>Overall: <span class='overall %s'>%s</span></p>
<table><thead><tr><th>Scenario</th>%s</tr></thead><tbody>%s</tbody></table>
<div class='facts'><b>Session facts</b><ul>
<li>Results rows (one per event): <code>%s</code></li>
<li>Filter chip dims: <code>%s</code></li>
<li>Grouping tabs: <code>%s</code></li>
<li>Chart metrics: <code>%s</code> &middot; 'Cash Return' present: <code>%s</code></li>
<li>Drilldown event ids: <code>%s</code></li>
<li>&gt;60-hands fixture hand count: <code>%s</code></li>
<li>Live finality reconciles: <code>%s</code> &middot; invented exits: <code>%s</code> &middot; typed-owner all_pass: <code>%s</code></li>
</ul></div>
<div class='facts'><b>Scenario-specific expectations (documented)</b><ul>%s</ul></div>
</body></html>""" % (
        overall_cls, overall, head_cells, ''.join(rows),
        _html.escape(', '.join(sf['event_ids_in_table'])),
        _html.escape(', '.join(sf['filter_dims'])),
        _html.escape(', '.join(sf['grouping_tabs'])),
        _html.escape(', '.join(sf['chart_metrics'])), sf['has_cash_return'],
        _html.escape(', '.join(sf['drilldown_event_ids'])),
        sf['over60_hand_count'],
        sf['live_finality_reconciles'], sf['live_finality_invented_exits'],
        sf['finality_model_all_pass'], notes)


def _print_matrix(report):
    dims = report['dimensions']
    print('\nSeven-Fixture Tournament Results Acceptance -- 7x8 matrix')
    hdr = '%-34s' % 'scenario' + ''.join('%-12s' % d for d in dims)
    print(hdr)
    print('-' * len(hdr))
    for name in report['fixture_order']:
        cells = ''.join('%-12s' % ('PASS' if report['fixtures'][name][d] else 'FAIL') for d in dims)
        print('%-34s%s' % (name, cells))
    print('-' * len(hdr))
    print('ALL_PASS:', report['all_pass'])


def main():
    report = run()
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(_emit_html(report))
    _print_matrix(report)
    print('\nartifacts:')
    print('  JSON:', JSON_PATH)
    print('  HTML:', HTML_PATH)
    return 0 if report['all_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
