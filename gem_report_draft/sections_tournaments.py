# -*- coding: utf-8 -*-
"""Tournament Tables v8.15 — additive event-level render section (Phase 2 / SP-2).

ADDITIVE renderer for a NEW "Tournament Tables" section built ONLY from the SP-1
typed model (gem_tournament_model.build_tournament_model). It does NOT remove or
replace the existing Results tables (Per-Tournament P&L / Deep Runs / Stack
trajectories) — those stay in place until reconciliation is reviewed
(handoff additive-then-swap). Financial-first, event-level, auditable:

  * Unit = tournament event (one row per event; repeated names stay separate;
    multi-bullet stays ONE row with a bullets count / entry pattern).
  * Cost = committed cost; Return = cash + ticket (model default); Net/ROI from
    the same basis. Session totals come from the canonical usd_overlay.totals
    (the model never recomputes a divergent total); a reconcile status is shown.
  * Per-event cEV stays BLANK (—): there is no canonical, join-safe tid->cEV/100
    source (gem_cev exposes per-tournament cev_per_STACK, a different metric that
    is hand-derived and not persisted) — never approximated.
  * Bounty dollar amounts are never inferred (blank). Inferred prize type is
    marked with `*`. Unknown fields render as an em dash, not a fabricated label.

No financial math here; no canonical-total recompute; no parser change.
"""
import json as _json_tt

from gem_tournament_model import build_tournament_model
from gem_report_draft._blocks import financial_table_block
from gem_report_draft.sections_financial import _fmt_usd
from gem_report_draft._html import _html_escape as _esc_tt

EMDASH = '—'  # —

_PRIZE_LABEL = {'bounty': 'Bounty', 'standard': 'Standard',
                'satellite': 'Satellite', 'unknown': EMDASH}


def _usd_or_dash(v):
    return _fmt_usd(v) if v is not None else EMDASH


def _pct_or_dash(v):
    return ('%+.1f%%' % v) if v is not None else EMDASH


def _tt_status(event):
    """v8.17 Epic 4: canonical deep-run / status, derived ONLY from the model's
    finish fields (never recomputed). Returns (label, sort_rank)."""
    fin = event.get('finish') or {}
    if fin.get('advanced_day2'):
        return ('Day 2', 3)
    tp = fin.get('top_percent')
    if tp is not None and tp <= 15:
        return ('Deep run', 2)
    if fin.get('itm'):
        return ('ITM', 1)
    return (EMDASH, 0)


def _tt_format_label(event):
    """Canonical format label (PRIZE_LABEL + inferred marker). Uses the model's
    prize_type/provenance — NEVER re-infers from the name text here."""
    pt = _PRIZE_LABEL.get(event.get('prize_type'), EMDASH)
    prov = (event.get('field_provenance') or {}).get('prize_type')
    inferred = (prov == 'inferred' and pt != EMDASH)
    if inferred:
        pt += '*'
    return pt, inferred


def _tt_drivers_by_tid(s):
    """Fold the canonical per-tournament stack trajectory (s['stack_trajectories'],
    detector-backed, already computed) into a compact driver string per tid for
    the row drilldown. Read-only; no recompute, no synthesis."""
    out = {}
    for tid, tr in (s.get('stack_trajectories') or {}).items():
        try:
            out[str(tid)] = [
                'Stack arc: start %.0fbb → peak %.0fbb → low %.0fbb '
                '→ end %.0fbb (%d hands)' % (
                    tr.get('start_bb', 0) or 0, tr.get('peak_bb', 0) or 0,
                    tr.get('valley_bb', 0) or 0, tr.get('end_bb', 0) or 0,
                    tr.get('n_hands', 0) or 0)]
        except Exception:
            continue
    return out


def _tt_hand_ids_by_tid(hands):
    """Group raw hand ids by tournament id for the drilldown review-links."""
    out = {}
    for h in (hands or []):
        tid = str(h.get('tournament_id') or h.get('tournament') or '')
        hid = h.get('id')
        if tid and hid:
            out.setdefault(tid, []).append(hid)
    return out


def _emit_tournament_tables(doc, s, rd, hands):
    """Additive S-section: render the event-level Tournament Tables from the
    SP-1 model. Fail-soft: with no canonical overlay it emits a diagnostic line
    and returns (never crashes, never recomputes)."""
    # No cev_by_tid passed: no canonical per-event cEV/100 source exists (SP-2
    # product decision) → per-event cEV stays blank.
    # v8.17 Epic 4: fold the canonical per-tournament stack trajectory (already
    # computed, detector-backed) into event['drivers'] for the row drilldown.
    model = build_tournament_model(rd, drivers_by_tid=_tt_drivers_by_tid(s))
    events = model.get('events') or []
    tot = model.get('totals') or {}
    diag = model.get('diagnostics') or {}

    doc.subsection('sec-tournaments', 'Tournament Results',
                   'event-level P&L · one row per tournament event')

    if model.get('financial_source') != 'usd_overlay' or not events:
        doc.w('*Tournament Tables: no canonical committed-cost financial overlay '
              'for this session — section omitted (financial_source: %s). The '
              'existing Results tables above remain authoritative.*'
              % (model.get('financial_source') or 'unavailable'))
        doc.w('')
        return

    # ---- Trust / diagnostics line (make the basis auditable) ----
    recon = ('reconciles to canonical totals ✅' if diag.get('reconciles_canonical')
             else 'DOES NOT reconcile ⚠️')
    cover = diag.get('canonical_financials_cover_session')
    if cover is None:
        stale = ''
    elif cover:
        stale = ' · session_financials* covers this session'
    else:
        stale = (' · session_financials* is stale (diagnostic only, not a '
                 'blocker — the in-run overlay is canonical)')
    doc.w('*Financial source: **%s** · return basis: **%s** · totals vs '
          'canonical `usd_overlay.totals`: **%s**%s · event-day timezone: %s '
          '· per-event cEV/100: unavailable (no canonical per-tournament '
          'source).*'
          % (model.get('financial_source'), tot.get('return_basis', EMDASH),
             recon, stale, model.get('event_day_tz_source', EMDASH)))
    doc.w('')
    # v8.17 Epic 4: this is now the SINGLE PRIMARY unified Tournament Results
    # table (sortable; one row per event; per-event drilldown). The per-tournament
    # P&L / Deep Runs / Stack Trajectories in S1 are demoted to collapsed
    # cross-check detail; the canonical per-event financial table is retained
    # below this primary table for cross-check.
    doc.w('*Single primary **Tournament Results** — the first Results surface, one '
          'sortable row per event. Click any column header to sort; click '
          '**Details ▸** for the per-event drilldown (bullets, finish/field, prize '
          '+ bounty breakdown, deep-run status + stack arc, and the event’s hands). '
          'The legacy per-tournament P&L / Deep Runs / Stack Trajectories now render '
          'only inside ONE collapsed secondary reconciliation disclosure in S1 '
          '(below); the canonical per-event financial table is '
          'retained for cross-check below.*')
    doc.w('')

    # ---- Summary strip (canonical session totals) ----
    # v8.16.2 Phase D: user-facing labels (Invested / Cash return / Ticket return
    # / Net / ROI / Bullets / Events). Values are the canonical usd_overlay totals
    # verbatim — only the labels/order are presented. tot['return'] is the cash
    # total and ticket_value the ticket total (shown as separate columns); no
    # financial math is computed here. Return basis stays on the trust line above.
    # tot['return'] is the TOTAL return (cash + ticket); ticket_value is the
    # ticket portion. Split for display: cash = total − ticket (no new math, just
    # a presentation split of the canonical totals; the two columns sum to the
    # total return shown in the legacy S1 tables).
    _tot_return = tot.get('return', 0) or 0
    _tot_ticket = tot.get('ticket_value', 0) or 0
    _tot_cash = round(_tot_return - _tot_ticket, 2)
    s_hdr = '| Invested | Cash return | Ticket return | Net | ROI | Bullets | Events |'
    s_sep = '|---:|---:|---:|---:|---:|---:|---:|'
    s_row = ('| %s | %s | %s | %s | %s | %s | %s |' % (
        _fmt_usd(tot.get('committed_cost', 0)),
        _fmt_usd(_tot_cash),
        _fmt_usd(_tot_ticket),
        _fmt_usd(tot.get('net', 0), plus=True), _pct_or_dash(tot.get('roi_pct')),
        tot.get('n_bullets', EMDASH),
        tot.get('n_tournaments', len(events))))
    doc.write_block(financial_table_block(
        'tt-summary', 'financial_summary', s_hdr, s_sep, [s_row]))
    doc.w('')
    # v8.17 Epic 4: PKO/bounty return reconciliation (prize + bounty + total).
    # GG summaries fold bounty winnings into cash_received and never expose a
    # separate bounty line, so bounty $ is never split out (never inferred). The
    # Cash return above therefore already includes prize + bounty; cash + ticket
    # reconcile to the canonical session total.
    doc.w('*PKO / bounty return: bounty winnings are **included in Cash return** '
          'above — GG summaries do not expose a separate bounty figure, so a bounty '
          '$ line is never split out or inferred. Prize + bounty + ticket reconcile '
          'to the canonical session total (cash + ticket).*')
    doc.w('')

    # ---- v8.17 Epic 4: PRIMARY unified sortable table + per-event drilldown ----
    # Built ONCE from the canonical events; the per-event payload feeds the
    # drilldown modal (no recompute — every value is read off the model).
    _hids_by_tid = _tt_hand_ids_by_tid(hands)
    has_cev = any(((e.get('performance') or {}).get('cev100')) is not None
                  for e in events)
    has_inferred = False
    _payload = []
    _uni_rows = []          # raw-HTML rows for the primary table
    _md_rows = []           # markdown rows for the collapsed cross-check table
    for e in events:
        ret = e.get('return') or {}
        prov = e.get('field_provenance') or {}
        fin = e.get('finish') or {}
        tid = str(e.get('tournament_id') or '')

        pt, inferred = _tt_format_label(e)
        if inferred:
            has_inferred = True

        finish_txt = ('%s/%s' % (fin['place'], fin['total_players'])
                      if fin.get('place') and fin.get('total_players') else EMDASH)
        place_sort = fin.get('place') if fin.get('place') else 10 ** 9
        if fin.get('advanced_day2'):
            adv = 'Day 2'
        elif fin.get('is_satellite') and fin.get('itm'):
            adv = 'seat'
        else:
            adv = EMDASH
        status_label, status_rank = _tt_status(e)

        cev = (e.get('performance') or {}).get('cev100')
        cev_txt = ('%.2f' % cev) if cev is not None else EMDASH   # raw chip-EV/100, NO %

        tick = ret.get('ticket_value')
        name = (e.get('name') or EMDASH).replace('|', '/')
        _buy = _usd_or_dash(e.get('buy_in'))
        _cost = _fmt_usd(e.get('cost', 0))
        _retv = _fmt_usd(ret.get('value', 0))
        _net = _fmt_usd(e.get('net', 0), plus=True)
        _roi = _pct_or_dash(e.get('roi_pct'))

        # --- markdown cross-check row (UNCHANGED columns: financial-correctness) ---
        _row = '| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            e.get('event_day') or EMDASH, name, pt,
            _buy, e.get('bullets', 1), _cost,
            _fmt_usd(ret.get('cash_received', 0)),
            (_fmt_usd(tick) if tick else EMDASH),
            _retv, _net, _roi, finish_txt, adv)
        if has_cev:
            _row += ' %s |' % cev_txt
        _md_rows.append(_row)

        # --- primary unified HTML row (Format + Status + Details drilldown) ---
        _eid = e.get('event_id') or ('%s|%s' % (tid, e.get('event_day') or ''))
        _uni_rows.append(
            "<tr>"
            "<td data-label='Date' data-sort-value='%s'>%s</td>"
            "<td data-label='Tournament'>%s</td>"
            "<td data-label='Format'>%s</td>"
            "<td data-label='Bullets' data-sort-value='%s'>%s</td>"
            "<td data-label='Buy-in' data-sort-value='%s'>%s</td>"
            "<td data-label='Invested' data-sort-value='%s'>%s</td>"
            "<td data-label='Finish' data-sort-value='%s'>%s</td>"
            "<td data-label='Return' data-sort-value='%s'>%s</td>"
            "<td data-label='Net' data-sort-value='%s'>%s</td>"
            "<td data-label='ROI' data-sort-value='%s'>%s</td>"
            "<td data-label='Status' data-sort-value='%s'>%s</td>"
            "<td data-label='' class='tt-details-cell'>"
            "<a href='#' onclick=\"openTournamentDetail('%s');return false;\">Details ▸</a></td>"
            "</tr>" % (
                _esc_tt(e.get('event_day') or ''), _esc_tt(e.get('event_day') or EMDASH),
                _esc_tt(name), _esc_tt(pt),
                e.get('bullets', 1), e.get('bullets', 1),
                (e.get('buy_in') if e.get('buy_in') is not None else ''), _esc_tt(_buy),
                e.get('cost', 0), _esc_tt(_cost),
                place_sort, _esc_tt(finish_txt),
                (ret.get('value', 0) or 0), _esc_tt(_retv),
                (e.get('net', 0) or 0), _esc_tt(_net),
                (e.get('roi_pct') if e.get('roi_pct') is not None else ''), _esc_tt(_roi),
                status_rank, _esc_tt(status_label),
                _esc_tt(_eid)))

        # --- per-event drilldown payload (canonical only; no recompute) ---
        _rb = []
        if ret.get('cash_received'):
            _rb.append('Cash (incl. bounty): ' + _fmt_usd(ret.get('cash_received')))
        if tick:
            _rb.append('Ticket (satellite seat): ' + _fmt_usd(tick))
        if e.get('prize_type') == 'bounty':
            _rb.append('Bounty $ not separately sourced — folded into cash (never inferred).')
        _notes = []
        if fin.get('place') and fin.get('total_players'):
            _tp = fin.get('top_percent')
            _notes.append('Finished %s of %s%s' % (
                fin['place'], fin['total_players'],
                (' (top %.1f%%)' % _tp) if _tp is not None else ''))
        if fin.get('itm'):
            _notes.append('In the money')
        if fin.get('is_satellite'):
            _notes.append('Satellite' + (' — seat won' if fin.get('itm') else ''))
        _payload.append({
            'event_id': _eid,
            'name': name,
            'event_day': e.get('event_day') or '',
            'format': pt,
            'bullets': e.get('bullets', 1),
            'entry_pattern': e.get('entry_pattern', ''),
            'buy_in': _buy,
            'cost': _cost,
            'finish_txt': finish_txt,
            'return_txt': _retv,
            'net_txt': _net,
            'roi_txt': _roi,
            'status': status_label,
            'return_breakdown': _rb,
            'drivers': list(e.get('drivers') or []),
            'notes': ' · '.join(_notes),
            'hand_ids': _hids_by_tid.get(tid, [])[:60],
        })

    # Primary unified sortable table (raw HTML so headers sort + rows drill down).
    _uhdr = (
        "<th data-tt-sort='0'>Date</th>"
        "<th data-tt-sort='1'>Tournament</th>"
        "<th data-tt-sort='2'>Format</th>"
        "<th data-tt-sort='3' data-tt-num='1'>Bullets</th>"
        "<th data-tt-sort='4' data-tt-num='1'>Buy-in</th>"
        "<th data-tt-sort='5' data-tt-num='1'>Invested</th>"
        "<th data-tt-sort='6' data-tt-num='1'>Finish</th>"
        "<th data-tt-sort='7' data-tt-num='1'>Return</th>"
        "<th data-tt-sort='8' data-tt-num='1'>Net</th>"
        "<th data-tt-sort='9' data-tt-num='1'>ROI</th>"
        "<th data-tt-sort='10' data-tt-num='1'>Status</th>"
        "<th>Details</th>")
    doc.w("<div class='table-shell' data-mobile-mode='scroll' "
          "style='--mobile-table-min-width:960px'><div class='table-scroll'>"
          "<table class='data-table tt-unified' id='tt-unified-table'>"
          "<thead><tr>" + _uhdr + "</tr></thead><tbody>"
          + ''.join(_uni_rows) + "</tbody></table></div></div>")
    doc.w('')
    try:
        doc._extra_js.append('window.tournamentEvents=%s;'
                             % _json_tt.dumps(_payload, ensure_ascii=False, default=str))
        doc._extra_js.append('if(window.initTournamentResultsTable)'
                             'window.initTournamentResultsTable();')
    except Exception:
        pass

    # ---- Canonical per-event financial table (collapsed cross-check) ----
    # v8.16.2 Phase D: cEV/100 column hidden unless a canonical source is passed.
    _cev_h = ' cEV/100 |' if has_cev else ''
    _cev_s = '---:|' if has_cev else ''
    hdr = ('| Date | Tournament | Type | Buy-in | Bullets | Cost | Cash | Ticket | '
           'Return | Net | ROI | Finish | Adv/Seat |' + _cev_h)
    sep = '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|' + _cev_s
    doc.w('<details><summary><strong>Per-event financial detail</strong> '
          '(cross-check — same canonical numbers as the primary table above)'
          '</summary>')
    doc.w('')
    doc.write_block(financial_table_block(
        'tt-events', 'tournament_pnl', hdr, sep, _md_rows))
    doc.w('')
    doc.w('</details>')
    doc.w('')

    # ---- Footnotes (auditability) ----
    if has_inferred:
        doc.w('*\\* Prize type inferred from the tournament name '
              '(provenance: inferred).*')
    if has_cev:                           # v8.16.2 Phase D: only when the column is shown
        doc.w('*cEV/100 is raw chip-EV per 100 hands. Session/aggregate cEV '
              'remains where it already appears.*')
    doc.w('*Bounty dollar amounts are shown only when safely sourced (never '
          'inferred); blank otherwise.*')
    doc.w('')
