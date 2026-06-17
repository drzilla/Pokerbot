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


def _tt_perf_maps(hands, rd):
    """v8.17.1 P4: canonical per-event performance maps joined by tournament id,
    derived ONLY from the session hands + analyst commentary (no recompute, no
    synthesis): hand count, BB/100 (sum net_bb / hands * 100), reviewed count
    ({reviewed,total}), and the exit-hand id (last hand of the event). Returns
    (hands_by_tid, bb100_by_tid, reviewed_by_tid, exit_by_tid)."""
    ac = (rd or {}).get('analyst_commentary') or {}
    _ac_keys = set()
    for _k in ac:
        _ac_keys.add(str(_k))
        _ac_keys.add(str(_k)[-8:])
    n_by, net_by, rev_by, exit_by = {}, {}, {}, {}
    for h in (hands or []):
        tid = str(h.get('tournament_id') or h.get('tournament') or '')
        hid = h.get('id')
        if not tid or not hid:
            continue
        n_by[tid] = n_by.get(tid, 0) + 1
        net_by[tid] = net_by.get(tid, 0.0) + float(h.get('net_bb') or 0)
        _hs = str(hid)[-8:]
        if str(hid) in _ac_keys or _hs in _ac_keys:
            r = rev_by.setdefault(tid, {'reviewed': 0, 'total': 0})
            r['reviewed'] += 1
        exit_by[tid] = hid                       # last hand seen = exit hand
    hands_by_tid, bb100_by_tid, reviewed_by_tid = {}, {}, {}
    for tid, n in n_by.items():
        hands_by_tid[tid] = n
        bb100_by_tid[tid] = round(net_by.get(tid, 0.0) / n * 100, 1) if n else None
        reviewed_by_tid[tid] = {'reviewed': rev_by.get(tid, {}).get('reviewed', 0),
                                'total': n}
    return hands_by_tid, bb100_by_tid, reviewed_by_tid, exit_by


_TT_TABS = (
    ('buyin', 'Buy-in'), ('prize_type', 'Prize type'), ('speed', 'Speed'),
    ('entry_pattern', 'Entry pattern'), ('entry_timing', 'Entry timing'),
    ('phase_reached', 'Phase reached'),
)
_TT_CAT_LABEL = {'single': 'Single', 'multi_bullet': 'Multi-bullet',
                 'bounty': 'Bounty', 'standard': 'Standard',
                 'satellite': 'Satellite'}


def _tt_ordered_cats(_TM, key, groups):
    """Ordered category list for a tab, with the unknown/None bucket last; returns
    [] when the tab has NO meaningful (non-unknown) category so the caller can
    auto-hide it (e.g. speed / entry-timing when every event is 'unknown')."""
    meaningful = [c for c in groups if c not in (None, 'unknown')]
    if key == 'buyin':
        meaningful = sorted(meaningful, key=_TM.buyin_band_sort_key)
    elif key == 'by_day':
        meaningful = sorted(meaningful)
    else:
        meaningful = sorted(meaningful, key=lambda c: str(c))
    if not meaningful:
        return []
    tail = []
    if None in groups:
        tail.append(None)
    if 'unknown' in groups:
        tail.append('unknown')
    return meaningful + tail


def _emit_one_aggregate_table(doc, _TM, key, groups, ordered, n_events):
    """Render ONE grouped-aggregate table for a tab: pooled ROI on the covered
    subset, settled-only ITM/Top denominators, hand-weighted BB/100·cEV/100, and a
    deterministic legend-square colour per group (the table IS the chart legend)."""
    doc.w("<div class='table-shell'><div class='table-scroll'>")
    doc.w("<table class='data-table tt-aggregate'>")
    doc.w("<thead><tr><th>Group</th><th>Events</th><th>Bullets</th>"
          "<th title='Final financial results available for X of Y events; the "
          "rest are estimated or still running'>Results</th><th>Cost</th>"
          "<th>Return</th><th>Net</th><th>ROI</th><th>ITM</th><th>Top 5%</th>"
          "<th>Top 1%</th><th>BB/100</th><th>cEV/100</th></tr></thead><tbody>")
    _settled_total = 0
    for cat in ordered:
        ag = _TM.aggregate_group(groups[cat])
        _settled_total += ag['n_settled']
        approx = '≈' if ag['estimated'] else ''
        sq = ("<span class='legend-square' style='background:%s'></span>"
              % _TM.color_for(key, cat))
        _lbl = _TT_CAT_LABEL.get(cat, cat) if cat not in (None, 'unknown') else EMDASH
        _net = (approx + _fmt_usd(ag['net'], plus=True)) if ag['net'] is not None else EMDASH
        _roi = (approx + _pct_or_dash(ag['roi_pct'])) if ag['roi_pct'] is not None else EMDASH
        _itm = ('%.0f%%' % ag['itm_pct']) if ag['itm_pct'] is not None else EMDASH
        _t5 = ('%.0f%%' % ag['top5_pct']) if ag['top5_pct'] is not None else EMDASH
        _t1 = ('%.0f%%' % ag['top1_pct']) if ag['top1_pct'] is not None else EMDASH
        _bb = ('%+.1f' % ag['bb100']) if ag['bb100'] is not None else EMDASH
        _cev = ('%+.1f' % ag['cev100']) if ag['cev100'] is not None else EMDASH
        doc.w("<tr data-cat='%s'><td>%s<b>%s</b></td><td>%d</td><td>%d</td>"
              "<td>%d/%d</td><td>%s</td><td>%s%s</td><td>%s</td><td>%s</td>"
              "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                  _esc_tt(str(_lbl)), sq, _esc_tt(str(_lbl)), ag['events'], ag['bullets'],
                  ag['results_covered'], ag['events'],
                  _fmt_usd(ag['committed_cost']), approx, _fmt_usd(ag['covered_return']),
                  _net, _roi, _itm, _t5, _t1, _bb, _cev))
    doc.w("</tbody></table></div></div>")
    doc.w("<p class='tt-coverage-note'>Results available for %d of %d events; the "
          "rest are estimated or still running.</p>" % (_settled_total, n_events))


def _emit_grouped_aggregate(doc, events):
    """v8.17.1 P4 surface 3: grouped AGGREGATE table with ALL tabs (Buy-in default;
    Prize type / Speed / Entry pattern / Entry timing / Phase reached; By-day only
    for multi-day reports). A tab whose every event is unknown is auto-hidden.
    Built from the pure aggregation helpers — pooled ROI on the covered subset,
    settled-only denominators, hand-weighted BB/100. The grouped view is the FIRST
    Results table (aggregate-first), above the per-event detail; the legend squares
    ARE the chart legend (stable colours via color_for(tab, category))."""
    import gem_tournament_model as _TM
    tabs = list(_TT_TABS)
    _days = set(e.get('event_day') for e in events if e.get('event_day'))
    if len(_days) > 1:                       # By-day only for multi-day reports
        tabs.append(('by_day', 'By day'))
    visible = []
    for key, label in tabs:
        groups = _TM.group_events(events, key) or {}
        ordered = _tt_ordered_cats(_TM, key, groups)
        if not ordered:                      # auto-hide all-unknown / empty tab
            continue
        visible.append((key, label, groups, ordered))
    if not visible:
        return
    default_key = visible[0][0]              # Buy-in by default (first visible)
    doc.w("<div class='tt-grouped' data-tab='%s'>" % default_key)
    _btns = ''.join(
        "<button class='tt-tab%s' data-tab='%s'>%s</button>" % (
            ' active' if k == default_key else '', k, _esc_tt(lbl))
        for k, lbl, _g, _o in visible)
    doc.w("<div class='tt-grouped-tabs'>%s</div>" % _btns)
    for key, label, groups, ordered in visible:
        _hidden = '' if key == default_key else " style='display:none'"
        doc.w("<div class='tt-tabpane' data-tabpane='%s'%s>" % (key, _hidden))
        _emit_one_aggregate_table(doc, _TM, key, groups, ordered, len(events))
        doc.w("</div>")
    doc.w("</div>")
    doc.w("")


def _tt_chart_bars_html(_TM, key, groups, ordered, metric):
    """Div-based distribution bars for one (tab, metric): Cost/Return = share of
    total; Net = diverging around zero. Colours from color_for (== legend squares).
    Viewport-safe tooltip via data-tip (the JS positions a clamped tooltip)."""
    agg_map = {cat: _TM.aggregate_group(groups[cat]) for cat in ordered}
    shares = _TM.distribution_shares(agg_map, metric)
    rows = []
    for cat in ordered:
        sh = shares.get(cat) or {}
        share = float(sh.get('share') or 0)
        sign = sh.get('sign', 0)
        col = _TM.color_for(key, cat)
        lbl = _TT_CAT_LABEL.get(cat, cat) if cat not in (None, 'unknown') else EMDASH
        val = sh.get('value')
        vtxt = (_fmt_usd(val, plus=(metric == 'net')) if val is not None else EMDASH)
        sq = "<span class='legend-square' style='background:%s'></span>" % col
        if metric == 'net':
            w = min(50.0, share / 2.0)
            ml = 50.0 if sign >= 0 else max(0.0, 50.0 - w)
            bar = ("<span class='tt-bar-track tt-diverge'><span class='tt-bar' "
                   "style='margin-left:%.1f%%;width:%.1f%%;background:%s'></span></span>"
                   % (ml, w, col))
        else:
            bar = ("<span class='tt-bar-track'><span class='tt-bar' "
                   "style='width:%.1f%%;background:%s'></span></span>"
                   % (min(100.0, share), col))
        rows.append("<div class='tt-bar-row' data-cat='%s' tabindex='0' data-tip='%s: %s'>"
                    "<span class='tt-bar-label'>%s%s</span>%s"
                    "<span class='tt-bar-val'>%s</span></div>" % (
                        _esc_tt(str(lbl)), _esc_tt(str(lbl)), _esc_tt(vtxt),
                        sq, _esc_tt(str(lbl)), bar, _esc_tt(vtxt)))
    return ''.join(rows) or "<p class='tt-coverage-note'>No data for this metric.</p>"


def _tt_chart_data(_TM, events):
    """Precompute the distribution dataset for EVERY visible tab × metric so the JS
    re-renders the chart on tab/metric change from canonical numbers (no JS
    re-aggregation, no drift). {tab:{cats:[{key,label,color}], metrics:{m:{cat:{value,share,sign}}}}}."""
    tabs = list(_TT_TABS)
    _days = set(e.get('event_day') for e in events if e.get('event_day'))
    if len(_days) > 1:
        tabs.append(('by_day', 'By day'))
    out = {}
    for key, _label in tabs:
        groups = _TM.group_events(events, key) or {}
        ordered = _tt_ordered_cats(_TM, key, groups)
        if not ordered:
            continue
        agg_map = {cat: _TM.aggregate_group(groups[cat]) for cat in ordered}
        cats = [{'key': ('__none__' if c is None else ('__unknown__' if c == 'unknown' else c)),
                 'label': (_TT_CAT_LABEL.get(c, c) if c not in (None, 'unknown') else EMDASH),
                 'color': _TM.color_for(key, c)} for c in ordered]
        metrics = {}
        for m in ('net', 'cost', 'return'):
            sh = _TM.distribution_shares(agg_map, m)
            metrics[m] = {('__none__' if c is None else ('__unknown__' if c == 'unknown' else c)):
                          sh.get(c) for c in ordered}
        out[key] = {'cats': cats, 'metrics': metrics}
    return out


def _emit_distribution_chart(doc, events):
    """v8.17.1 P4 surface 4: distribution chart directly BELOW the grouped table.
    Cost/Return share + diverging Net; bars share the table's category colours (the
    legend squares ARE the legend — no separate legend). Server-rendered for the
    default Buy-in tab + Net metric; the JS controller re-renders on tab / metric
    change. Safe empty / partial-coverage states."""
    import gem_tournament_model as _TM
    groups = _TM.group_events(events, 'buyin') or {}
    ordered = _tt_ordered_cats(_TM, 'buyin', groups)
    doc.w("<div class='tt-chart' data-tab='buyin' data-metric='net'>")
    doc.w("<div class='tt-chart-head'><span class='tt-chart-title' data-tt-chart-title>"
          "Distribution — Buy-in · Net</span>"
          "<div class='tt-chart-metrics'>"
          "<button type='button' class='tt-metric active' data-metric='net'>Net</button>"
          "<button type='button' class='tt-metric' data-metric='cost'>Cost</button>"
          "<button type='button' class='tt-metric' data-metric='return'>Return</button>"
          "</div></div>")
    doc.w("<div class='tt-chart-body'>")
    if ordered:
        doc.w(_tt_chart_bars_html(_TM, 'buyin', groups, ordered, 'net'))
    else:
        doc.w("<p class='tt-coverage-note'>No grouped data to chart.</p>")
    doc.w("</div>")
    doc.w("<div class='tt-tooltip' role='status' aria-live='polite' hidden></div>")
    doc.w("</div>")
    doc.w("")


def _emit_performance(doc, events, hids_by_tid):
    """v8.17.1 P4 surface 6: Tournament Performance — per-event Hands / BB-100 /
    cEV-100 (ONLY where canonical; column hidden cleanly otherwise) / Drivers /
    Reviewed (the canonical review store + the existing hand-list popup) / Exit hand.
    Collapsed behind a disclosure at 30+ events; open below 30."""
    has_cev = any(((e.get('performance') or {}).get('cev100')) is not None for e in events)
    has_hands = any(((e.get('performance') or {}).get('hands')) is not None for e in events)
    if not (has_cev or has_hands):
        return
    n = len(events)
    _open = '' if n >= 30 else ' open'
    doc.w("<details class='tt-perf-detail'%s><summary><strong>Tournament Performance</strong>"
          " — hands · BB/100%s · drivers · reviewed (%d events)</summary>" % (
              _open, (' · cEV/100' if has_cev else ''), n))
    doc.w("<div class='table-shell' data-mobile-mode='scroll'><div class='table-scroll'>")
    _cevh = "<th data-tt-sort='4' data-tt-num='1'>cEV/100</th>" if has_cev else ''
    doc.w("<table class='data-table tt-performance' id='tt-performance-table'><thead><tr>"
          "<th data-tt-sort='0'>Tournament</th>"
          "<th data-tt-sort='1' data-tt-num='1'>Bullets</th>"
          "<th data-tt-sort='2' data-tt-num='1'>Hands</th>"
          "<th data-tt-sort='3' data-tt-num='1'>BB/100</th>" + _cevh +
          "<th>Drivers</th><th>Reviewed</th><th>Exit hand</th></tr></thead><tbody>")
    for e in events:
        perf = e.get('performance') or {}
        name = (e.get('name') or EMDASH).replace('|', '/')
        tid = str(e.get('tournament_id') or '')
        hd = perf.get('hands')
        bb = perf.get('bb100')
        cv = perf.get('cev100')
        rev = e.get('reviewed') or {}
        hd_t = ('%d' % hd) if hd is not None else EMDASH
        bb_t = ('%+.1f' % bb) if bb is not None else EMDASH
        _cevc = ''
        if has_cev:
            _cevc = ("<td data-sort-value='%s'>%s</td>"
                     % ((cv if cv is not None else ''), (('%.2f' % cv) if cv is not None else EMDASH)))
        drv = '; '.join(e.get('drivers') or []) or EMDASH
        _hids = (hids_by_tid.get(tid) or [])[:60]
        rv_n = rev.get('reviewed', 0) or 0
        rv_m = rev.get('total', hd or 0) or 0
        if _hids:
            _rev_cell = ("<a href='#' class='hand-list-trigger' data-title='%s — hands' "
                         "data-hids='%s'>%d/%d reviewed</a>" % (
                             _esc_tt(name), _esc_tt(','.join(str(x)[-8:] for x in _hids)),
                             rv_n, rv_m))
        else:
            _rev_cell = '%d/%d reviewed' % (rv_n, rv_m)
        _exit = e.get('exit_hand')
        _exit_cell = (("<a href='#' class='hand-ref xref' data-hid='%s'>%s</a>"
                       % (_esc_tt(str(_exit)[-8:]), _esc_tt(str(_exit)[-8:])))
                      if _exit else EMDASH)
        doc.w("<tr><td data-label='Tournament'>%s</td>"
              "<td data-label='Bullets' data-sort-value='%d'>%d</td>"
              "<td data-label='Hands' data-sort-value='%s'>%s</td>"
              "<td data-label='BB/100' data-sort-value='%s'>%s</td>%s"
              "<td data-label='Drivers'>%s</td>"
              "<td data-label='Reviewed'>%s</td>"
              "<td data-label='Exit hand'>%s</td></tr>" % (
                  _esc_tt(name), e.get('bullets', 1), e.get('bullets', 1),
                  (hd if hd is not None else ''), hd_t,
                  (bb if bb is not None else ''), bb_t, _cevc,
                  _esc_tt(drv), _rev_cell, _exit_cell))
    doc.w("</tbody></table></div></div>")
    doc.w("</details>")
    doc.w("")


def _emit_drivers_rollup(doc, events):
    """v8.17.1 P4 surface 7: Drivers-in-view rollup — the detector-backed driver
    descriptions across the current event set (human descriptions only; never
    internal keys / debug provenance / raw detector labels)."""
    rows = [(e.get('name') or EMDASH, d)
            for e in events for d in (e.get('drivers') or [])]
    if not rows:
        return
    doc.w("<div class='tt-drivers-rollup' data-tt-rollup>")
    doc.w("<p class='tt-rollup-head'><strong>Drivers in view</strong> — what moved "
          "the deep runs and collapses across these events.</p>")
    doc.w("<ul class='tt-rollup-list'>")
    for nm, d in rows:
        doc.w("<li><span class='tt-rollup-evt'>%s</span> — %s</li>" % (
            _esc_tt(str(nm).replace('|', '/')), _esc_tt(str(d))))
    doc.w("</ul></div>")
    doc.w("")


def _emit_tournament_tables(doc, s, rd, hands):
    """Additive S-section: render the event-level Tournament Tables from the
    SP-1 model. Fail-soft: with no canonical overlay it emits a diagnostic line
    and returns (never crashes, never recomputes)."""
    # No cev_by_tid passed: no canonical per-event cEV/100 source exists (SP-2
    # product decision) → per-event cEV stays blank.
    # v8.17 Epic 4: fold the canonical per-tournament stack trajectory (already
    # computed, detector-backed) into event['drivers'] for the row drilldown.
    # v8.17.1 P4: wire the canonical per-event performance maps (hands / BB-100 /
    # reviewed / exit-hand, joined by tid) so the Tournament Performance table and
    # the hand-weighted grouped BB/100 populate. cEV/100 stays blank (no canonical
    # per-tid source — hidden cleanly).
    _hb, _bbb, _revb, _exb = _tt_perf_maps(hands, rd)
    model = build_tournament_model(
        rd, drivers_by_tid=_tt_drivers_by_tid(s),
        hands_by_tid=_hb, bb100_by_tid=_bbb,
        reviewed_by_tid=_revb, exit_by_tid=_exb)
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
    doc.w('*Single primary **Tournament Results** — the first Results surface. The '
          'grouped aggregate + distribution chart sit on top; **Finance & Finish** '
          'is the canonical per-event financial + finish table (sortable; click '
          '**Details ▸** for the per-event drilldown — bullets, finish/field, prize '
          '+ bounty breakdown, deep-run status + stack arc, and the event’s hands), '
          'and **Tournament Performance** carries hands / BB-100 / cEV / drivers / '
          'reviewed. The legacy per-tournament P&L / Deep Runs / Stack Trajectories '
          'render only inside ONE collapsed secondary reconciliation disclosure in '
          'S1 (below).*')
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

    # ---- v8.17.1 P4 surface 3: grouped AGGREGATE table (aggregate-first) ----
    # Where did the buy-ins go / which bands are profitable — pooled ROI, settled
    # denominators, legend-square colours. Rendered ABOVE the per-event detail.
    _emit_grouped_aggregate(doc, events)

    # ---- v8.17.1 P4 surface 4: distribution chart directly below the grouped table ----
    _emit_distribution_chart(doc, events)

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

        # --- v8.17.1 P4 surface 5: Finance & Finish row (the split of the former
        # unified table — financial + typed-finish + exit-hand; the duplicate
        # markdown cross-check table is removed, this is the canonical surface) ---
        _eid = e.get('event_id') or ('%s|%s' % (tid, e.get('event_day') or ''))
        _fin_lbl = fin.get('label') or finish_txt
        _fin_sort = fin.get('sort_key')
        _fin_sort = _fin_sort if _fin_sort is not None else 999
        _exit = e.get('exit_hand')
        _exit_cell = (("<a href='#' class='hand-ref xref' data-hid='%s'>%s</a>"
                       % (_esc_tt(str(_exit)[-8:]), _esc_tt(str(_exit)[-8:])))
                      if _exit else EMDASH)
        _uni_rows.append(
            "<tr>"
            "<td data-label='Date' data-sort-value='%s'>%s</td>"
            "<td data-label='Tournament'>%s</td>"
            "<td data-label='Type'>%s</td>"
            "<td data-label='Bullets' data-sort-value='%s'>%s</td>"
            "<td data-label='Finish' data-sort-value='%s'>%s</td>"
            "<td data-label='Cost' data-sort-value='%s'>%s</td>"
            "<td data-label='Return' data-sort-value='%s'>%s</td>"
            "<td data-label='Net' data-sort-value='%s'>%s</td>"
            "<td data-label='ROI' data-sort-value='%s'>%s</td>"
            "<td data-label='Exit hand'>%s</td>"
            "<td data-label='' class='tt-details-cell'>"
            "<a href='#' onclick=\"openTournamentDetail('%s');return false;\">Details ▸</a></td>"
            "</tr>" % (
                _esc_tt(e.get('event_day') or ''), _esc_tt(e.get('event_day') or EMDASH),
                _esc_tt(name), _esc_tt(pt),
                e.get('bullets', 1), e.get('bullets', 1),
                _fin_sort, _esc_tt(_fin_lbl),
                e.get('cost', 0), _esc_tt(_cost),
                (ret.get('value', 0) or 0), _esc_tt(_retv),
                (e.get('net', 0) or 0), _esc_tt(_net),
                (e.get('roi_pct') if e.get('roi_pct') is not None else ''), _esc_tt(_roi),
                _exit_cell, _esc_tt(_eid)))

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

    # v8.17.1 P4 surface 5: Finance & Finish — the canonical per-event financial +
    # typed-finish surface (the split of the former unified table; the duplicate
    # markdown cross-check below it is removed). Sortable (Finish sorts on the typed
    # domain sort_key: exact Top% best, then Ticket/Day 2/Est. ITM/Pending/No cash;
    # blanks last). Keeps the per-event Details drilldown. id retained so the
    # existing sort JS (initTournamentResultsTable/_ttSort) binds unchanged.
    doc.w('#### Finance & Finish')
    doc.w('')
    _uhdr = (
        "<th data-tt-sort='0'>Date</th>"
        "<th data-tt-sort='1'>Tournament</th>"
        "<th data-tt-sort='2'>Type</th>"
        "<th data-tt-sort='3' data-tt-num='1'>Bullets</th>"
        "<th data-tt-sort='4' data-tt-num='1'>Finish</th>"
        "<th data-tt-sort='5' data-tt-num='1'>Cost</th>"
        "<th data-tt-sort='6' data-tt-num='1'>Return</th>"
        "<th data-tt-sort='7' data-tt-num='1'>Net</th>"
        "<th data-tt-sort='8' data-tt-num='1'>ROI</th>"
        "<th>Exit hand</th>"
        "<th>Details</th>")
    doc.w("<div class='table-shell' data-mobile-mode='scroll' "
          "style='--mobile-table-min-width:920px'><div class='table-scroll'>"
          "<table class='data-table tt-unified tt-finance' id='tt-unified-table'>"
          "<thead><tr>" + _uhdr + "</tr></thead><tbody>"
          + ''.join(_uni_rows) + "</tbody></table></div></div>")
    doc.w('')

    # ---- v8.17.1 P4 surface 6: Tournament Performance (separate detail table) ----
    _emit_performance(doc, events, _hids_by_tid)
    # ---- v8.17.1 P4 surface 7: Drivers-in-view rollup ----
    _emit_drivers_rollup(doc, events)

    try:
        doc._extra_js.append('window.tournamentEvents=%s;'
                             % _json_tt.dumps(_payload, ensure_ascii=False, default=str))
        # v8.17.1 P4: precomputed distribution dataset (every visible tab × metric)
        # so the chart re-renders on tab/metric change from canonical numbers.
        import gem_tournament_model as _TM_chart
        doc._extra_js.append('window.ttChart=%s;' % _json_tt.dumps(
            _tt_chart_data(_TM_chart, events), ensure_ascii=False, default=str))
        doc._extra_js.append('if(window.initTournamentResultsTable)'
                             'window.initTournamentResultsTable();'
                             'if(window.initTtChart)window.initTtChart();')
        # v8.17.1 P4: grouped-aggregate tab switching — show the matching tabpane,
        # mark the active button, and (if wired) re-render the distribution chart.
        doc._extra_js.append(
            "(function(){var gs=document.querySelectorAll('.tt-grouped');"
            "gs.forEach(function(g){g.querySelectorAll('.tt-tab').forEach("
            "function(btn){btn.addEventListener('click',function(){"
            "var tab=btn.getAttribute('data-tab');g.setAttribute('data-tab',tab);"
            "g.querySelectorAll('.tt-tab').forEach(function(b){"
            "b.classList.toggle('active',b===btn);});"
            "g.querySelectorAll('.tt-tabpane').forEach(function(p){"
            "p.style.display=(p.getAttribute('data-tabpane')===tab)?'':'none';});"
            "if(window.ttRenderChart)window.ttRenderChart(g,tab);});});});})();")
    except Exception:
        pass

    # v8.17.1 P4: the duplicate per-event financial cross-check table is REMOVED —
    # Finance & Finish (above) is the single canonical per-event financial surface,
    # and Tournament Performance carries hands/BB-100/cEV/drivers/reviewed. The
    # legacy P&L / Deep Runs / Stack Trajectories remain only inside the ONE closed
    # S1 reconciliation disclosure (sections_financial s1-recon-detail).

    # ---- Footnotes (auditability) ----
    if has_inferred:
        doc.w('*\\* Prize type inferred from the tournament name '
              '(provenance: inferred).*')
    if has_cev:                           # only when the Performance cEV column shows
        doc.w('*cEV/100 is raw chip-EV per 100 hands. Session/aggregate cEV '
              'remains where it already appears.*')
    doc.w('*Bounty dollar amounts are shown only when safely sourced (never '
          'inferred); blank otherwise.*')
    doc.w('')
