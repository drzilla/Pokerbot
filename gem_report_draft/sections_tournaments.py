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
# R3 (owner request): compact Type icons. The shape (not colour) carries the meaning; the full label
# stays the cell value (sort/filter) and the title (tooltip + accessible text). A legend sits by the table.
_TYPE_ICON = {'Bounty': '\U0001F3AF', 'Standard': '♠️', 'Satellite': '\U0001F3AB'}


def _type_icon_cell_html(pt, esc):
    """Render the Type column as a compact icon + tooltip/accessible title, never icon-as-colour-only."""
    base = (pt or '').rstrip('*')
    ic = _TYPE_ICON.get(base)
    if not ic:
        return esc(pt)
    star = '*' if pt.endswith('*') else ''
    return ("<span class='tt-type-ic' title='%s' aria-label='%s'>%s%s</span>"
            % (esc(pt), esc(pt), ic, star))


def _tt_name_line1(name, buy_usd):
    """R3 owner layout: a 'NN-KO 10.80 Rest' name becomes 'NN-KO: $10.80 Rest' (prefix + colon, buy-in
    pulled up with a $). Best-effort: names that do not match the prefix-then-buyin shape are left as-is."""
    import re as _re
    m = _re.match(r'^([0-9]+[-–\s][0-9A-Za-z]+)\s+\$?([0-9][0-9,]*(?:\.[0-9]+)?)\s+(.+)$', name or '')
    if not m:
        return name
    amt = buy_usd if (buy_usd and buy_usd != EMDASH) else ('$' + m.group(2))
    return '%s: %s %s' % (m.group(1), amt, m.group(3))


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
# RES-006 (v8.19.0): friendly labels for the disjoint phase taxonomy categories.
from gem_tournament_model import PHASE_LABELS as _PHASE_LABELS  # noqa: E402
_TT_CAT_LABEL.update(_PHASE_LABELS)


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
    # QA mobile-chart fix: this 11-column numeric aggregate must stay a COMPACT horizontally-scrollable
    # table on mobile. Without data-mobile-mode the .table-shell falls into the stacked-card layout
    # (.data-table tr -> display:block), which blew every group row up to ~410px tall blank panels at
    # 360/390/430. data-mobile-mode='scroll' keeps one compact row per group + horizontal swipe, exactly
    # like the per-event Results table. Pure responsive layout -- no data/filter/grouping/chart-state change.
    doc.w("<div class='table-shell' data-mobile-mode='scroll'><div class='table-scroll'>")
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
        # COR-004: an unavailable grouped/total cEV is an em dash with a typed reason -- never +0.0.
        _cev = (('%+.1f' % ag['cev100']) if ag['cev100'] is not None
                else ("<span title='cEV unavailable: no canonical per-tournament cEV/100 source for this "
                      "group'>%s</span>" % EMDASH))
        _ckey = ('__none__' if cat is None else ('__unknown__' if cat == 'unknown' else cat))
        doc.w("<tr data-cat='%s' data-cat-key='%s'><td>%s<b>%s</b></td><td>%d</td>"
              "<td>%d</td><td>%d/%d</td><td>%s</td><td>%s%s</td><td>%s</td><td>%s</td>"
              "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                  _esc_tt(str(_lbl)), _esc_tt(str(_ckey)),
                  sq, _esc_tt(str(_lbl)), ag['events'], ag['bullets'],
                  ag['results_covered'], ag['events'],
                  _fmt_usd(ag['committed_cost']), approx, _fmt_usd(ag['covered_return']),
                  _net, _roi, _itm, _t5, _t1, _bb, _cev))
    # RES-005 (v8.19.0): a totals row on EVERY grouping tab (grouping is disjoint, so the
    # union of the groups' events is all events in this tab) + average Top%.
    _all_ev = [e for cat in ordered for e in groups[cat]]
    _tot = _TM.aggregate_group(_all_ev)
    _tops = [t for t in ((e.get('finish') or {}).get('top_percent') for e in _all_ev) if t is not None]
    _avg_top = (sum(_tops) / len(_tops)) if _tops else None
    _tnet = _fmt_usd(_tot['net'], plus=True) if _tot['net'] is not None else EMDASH
    _troi = _pct_or_dash(_tot['roi_pct']) if _tot['roi_pct'] is not None else EMDASH
    _tbb = ('%+.1f' % _tot['bb100']) if _tot['bb100'] is not None else EMDASH
    _tcev = ('%+.1f' % _tot['cev100']) if _tot['cev100'] is not None else EMDASH
    _tavg = ('%.1f%%' % _avg_top) if _avg_top is not None else EMDASH
    doc.w("</tbody>")
    doc.w("<tfoot><tr class='tt-totals'><td><b>Total</b></td><td>%d</td><td>%d</td>"
          "<td>%d/%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
          "<td title='Average Top%% across settled finishes'>%s</td><td></td><td></td>"
          "<td>%s</td><td>%s</td></tr></tfoot>" % (
              _tot['events'], _tot['bullets'], _settled_total, n_events,
              _fmt_usd(_tot['committed_cost']), _fmt_usd(_tot['covered_return']),
              _tnet, _troi, _tavg, _tbb, _tcev))
    doc.w("</table></div></div>")
    doc.w("<p class='tt-coverage-note'>Results available for %d of %d events; the "
          "rest are estimated or still running. Average Top%%: %s.</p>" % (
              _settled_total, n_events, _tavg))


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
    # RES-009 (v8.19.0): explicit coverage inventory — make the events vs HH-backed vs
    # summary-only vs unresolved vs financially-resolved split visible (the "15 tournaments
    # vs 26 events" gap was previously unexplained).
    _ne = len(events)
    _hh = sum(1 for e in events if ((e.get('performance') or {}).get('hands') or 0) > 0)
    _inplay = sum(1 for e in events if ((e.get('finish') or {}).get('is_in_play')))
    _resolved = sum(1 for e in events if e.get('net') is not None)
    doc.w("<p class='tt-coverage-inventory'><strong>Coverage:</strong> %d event(s) — "
          "%d HH-backed · %d summary-only · %d financially resolved · %d unresolved/in-play."
          "</p>" % (_ne, _hh, _ne - _hh, _resolved, _inplay))
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


def _emit_financial_chart(doc, events):
    """v8.20 QA-RES-003 (owner-locked, supersedes the static finish-outcome bar): the group-aware FINANCIAL
    distribution chart as the PRIMARY Results chart. Metric controls Cost / Cash Return / Net; categories
    follow the active grouping tab; the canonical filter JS (initTtChart + renderChart) re-renders from the
    SAME filtered event set + window.ttChart on every filter / tab / metric change, so the chart values +
    categories reconcile exactly with the filtered primary table."""
    import gem_tournament_model as _TM
    tabs = list(_TT_TABS)
    _days = set(e.get('event_day') for e in events if e.get('event_day'))
    if len(_days) > 1:
        tabs.append(('by_day', 'By day'))
    default = None
    for key, label in tabs:
        groups = _TM.group_events(events, key) or {}
        ordered = _tt_ordered_cats(_TM, key, groups)
        if ordered:
            default = (key, label, groups, ordered)
            break
    if not default:
        return
    dkey, dlabel, dgroups, dordered = default
    body = _tt_chart_bars_html(_TM, dkey, dgroups, dordered, 'net')
    _btns = ''.join(
        "<button type='button' class='tt-metric%s' data-metric='%s'>%s</button>"
        % (' active' if m == 'net' else '', m, lbl)
        for m, lbl in (('net', 'Net'), ('cost', 'Cost'), ('return', 'Cash Return')))
    doc.w("<div class='tt-chart' data-tab='%s' data-metric='net'>" % dkey)
    doc.w("<div class='tt-chart-head'>"
          "<span class='tt-chart-title' data-tt-chart-title>Distribution — %s · Net</span>"
          "<span class='tt-chart-metrics'>%s</span></div>" % (_esc_tt(dlabel), _btns))
    doc.w("<div class='tt-chart-body'>%s</div>" % body)
    doc.w("<div class='tt-tooltip' hidden></div>")
    doc.w("</div>")
    doc.w("")


# v8.20 W1A.2A Track A2: the ONE finish-outcome distribution model. Mutually-exclusive buckets by
# finish percentile / cash state -- every event maps to exactly one bucket, so the segment counts sum to
# the (filtered) event count. Colours are stable per bucket.
_OUTCOME_BUCKETS = [
    ('top1', 'Top 1%', '#1b7837'),
    ('top10', 'Top 10%', '#5aae61'),
    ('itm', 'In the money', '#a6dba0'),
    ('nocash', 'No cash', '#d9d9d9'),
    ('unresolved', 'Unresolved', '#bdbdbd'),
]


def _event_outcome_bucket(e):
    """Map ONE event to exactly ONE finish-outcome bucket (B-mutually-exclusive)."""
    fin = e.get('finish') or {}
    ret = e.get('return') or {}
    state = fin.get('state')
    if state in ('in_play', 'unresolved') or (ret.get('value') is None and not fin.get('place')):
        return 'unresolved'
    tp = fin.get('top_percent')
    if tp is not None:
        if tp <= 1:
            return 'top1'
        if tp <= 10:
            return 'top10'
    itm = bool(fin.get('itm') or (fin.get('is_satellite') and fin.get('itm'))
               or (isinstance(ret.get('value'), (int, float)) and ret.get('value') > 0))
    return 'itm' if itm else 'nocash'


def outcome_distribution(events):
    """The typed outcome-distribution model: every bucket defined (zero-count included), counts + %.
    Pure -- callable on the FULL or any FILTERED event subset, so the bar recomputes from one dataset."""
    counts = {k: 0 for k, _, _ in _OUTCOME_BUCKETS}
    for e in (events or []):
        counts[_event_outcome_bucket(e)] += 1
    total = sum(counts.values())
    buckets = [{'key': k, 'label': lbl, 'color': col, 'count': counts[k],
                'pct': round(100.0 * counts[k] / total, 1) if total else 0.0}
               for k, lbl, col in _OUTCOME_BUCKETS]
    return {'total': total, 'buckets': buckets}


# v8.20 RC fix: RAW CSS rules (no <style> wrapper) injected into the HEAD stylesheet via doc._extra_css --
# matching the established sections_issue_explorer pattern. The body markdown converter (_md_to_html in
# _html.py) DELIBERATELY escapes inline <style>/<script>, so emitting this via doc.w() printed the raw CSS
# as literal text on the page instead of styling the finish-outcome stacked bar.
_OUTCOME_CSS = (
    ".tt-outcome-dist{margin:.5rem 0 1rem}.tt-outcome-bar{display:flex;width:100%;height:26px;"
    "border-radius:4px;overflow:hidden;border:1px solid var(--border,#ccc)}.tt-outcome-seg{display:flex;"
    "align-items:center;justify-content:center;font-size:11px;color:#10240f;white-space:nowrap;min-width:0;"
    "overflow:hidden}.tt-oc-top1{background:#1b7837;color:#fff}.tt-oc-top10{background:#5aae61}"
    ".tt-oc-itm{background:#a6dba0}.tt-oc-nocash{background:#d9d9d9}.tt-oc-unresolved{background:#bdbdbd}"
    ".tt-outcome-legend{margin-top:.4rem;font-size:11px;display:flex;flex-wrap:wrap;gap:.6rem}"
    ".tt-oc-legend{display:inline-flex;align-items:center;gap:.25rem}.tt-oc-sw{width:11px;height:11px;"
    "border-radius:2px;display:inline-block}")


def _emit_distribution_chart(doc, events):
    """Track A2: ONE horizontal stacked finish-outcome-distribution bar. The legacy Net/Cost/Return
    metric toggle, the multi-category bar rows and the metric-dependent title are REMOVED. Segments are
    mutually-exclusive finish-outcome buckets covering every event; each carries label, count, % and a
    tooltip. The typed bucket model is embedded (data-outcome-buckets) and each Results row carries its
    bucket (data-outcome-bucket) so the filter controller recomputes the bar from the same filtered
    dataset. Zero-count buckets are omitted from the bar but stay defined in the model + legend."""
    import json as _json
    model = outcome_distribution(events)
    if _OUTCOME_CSS not in doc._extra_css:        # head stylesheet -- inline <style> in body would escape
        doc._extra_css.append(_OUTCOME_CSS)
    doc.w("<div class='tt-outcome-dist' data-outcome-buckets='%s'>"
          % _esc_tt(_json.dumps(model, separators=(',', ':'))))
    doc.w("<div class='tt-chart-head'><span class='tt-chart-title'>Finish-outcome distribution</span> "
          "<span class='tt-outcome-total' data-outcome-total>%d event%s</span></div>"
          % (model['total'], '' if model['total'] == 1 else 's'))
    if model['total']:
        segs = []
        for b in model['buckets']:
            if b['count'] <= 0:
                continue
            segs.append(
                "<span class='tt-outcome-seg tt-oc-%s' style='width:%.4f%%' data-bucket='%s' "
                "data-count='%d' title='%s — %d event%s (%.1f%%)'>%d</span>"
                % (b['key'], b['pct'], b['key'], b['count'], _esc_tt(b['label']), b['count'],
                   '' if b['count'] == 1 else 's', b['pct'], b['count']))
        doc.w("<div class='tt-outcome-bar' role='img' aria-label='Finish-outcome distribution'>%s</div>"
              % ''.join(segs))
        leg = ' '.join(
            "<span class='tt-oc-legend'><span class='tt-oc-sw tt-oc-%s'></span>%s (%d, %.1f%%)</span>"
            % (b['key'], _esc_tt(b['label']), b['count'], b['pct']) for b in model['buckets'])
        doc.w("<div class='tt-outcome-legend'>%s</div>" % leg)
    else:
        doc.w("<p class='tt-coverage-note'>No events to chart.</p>")
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
        # v8.20 W1A.2A Track 2.2: every hand in the event must be reachable from its drilldown -- the old
        # [:60] silently capped the popup while the "X/Y reviewed" count showed the true total, so events
        # with >60 hands hid hands behind a count that did not match. No cap: the popup lists all hands.
        _hids = (hids_by_tid.get(tid) or [])
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
        doc.w("<tr data-event-id='%s'><td data-label='Tournament'>%s</td>"
              "<td data-label='Bullets' data-sort-value='%d'>%d</td>"
              "<td data-label='Hands' data-sort-value='%s'>%s</td>"
              "<td data-label='BB/100' data-sort-value='%s'>%s</td>%s"
              "<td data-label='Drivers'>%s</td>"
              "<td data-label='Reviewed'>%s</td>"
              "<td data-label='Exit hand'>%s</td></tr>" % (
                  _esc_tt(e.get('event_id') or ''),
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
    rows = [(e.get('event_id') or '', e.get('name') or EMDASH, d)
            for e in events for d in (e.get('drivers') or [])]
    if not rows:
        return
    doc.w("<div class='tt-drivers-rollup' data-tt-rollup>")
    doc.w("<p class='tt-rollup-head'><strong>Drivers in view</strong> — what moved "
          "the deep runs and collapses across these events.</p>")
    doc.w("<ul class='tt-rollup-list'>")
    for eid, nm, d in rows:
        doc.w("<li data-event-id='%s'><span class='tt-rollup-evt'>%s</span> — %s</li>"
              % (_esc_tt(str(eid)), _esc_tt(str(nm).replace('|', '/')), _esc_tt(str(d))))
    doc.w("</ul></div>")
    doc.w("")


# RES-007 (v8.19.0): "Entries" (Single / Multi-bullet — the entry COUNT) is distinct from
# "Entry timing" (Early / Mid / Late) so the two are never conflated.
_TT_FILTER_DIMS = (
    ('buyin_band', 'Buy-in'), ('prize_type', 'Prize'), ('entry_pattern', 'Entries'),
    ('speed', 'Speed'), ('entry_timing', 'Entry timing'),
)


def _emit_filters_and_sticky(doc, events):
    """v8.17.1 P4 surfaces 1+2: filters panel + sticky filtered-summary bar. Server-
    renders the default (unfiltered) state; the TTF JS controller (_html.py) derives
    ONE filtered event set and updates every surface (grouped pane, chart, sticky
    bar, detail-table rows, drivers rollup) from it. Filter counts are EVENTS, not
    bullets. Coverage language: 'Results available for X of Y events'."""
    import gem_tournament_model as _TM
    chips = []
    for dim, label in _TT_FILTER_DIMS:
        vals, seen = [], set()
        for e in events:
            v = e.get(dim)
            if v in (None, 'unknown') or v in seen:
                continue
            seen.add(v)
            vals.append(v)
        if len(vals) < 2:
            continue                       # nothing meaningful to filter on this dim
        vals = (sorted(vals, key=_TM.buyin_band_sort_key) if dim == 'buyin_band'
                else sorted(vals, key=lambda x: str(x)))
        _c = ''.join(
            "<button type='button' class='tt-filter-chip' data-dim='%s' data-val='%s'>%s</button>"
            % (_esc_tt(dim), _esc_tt(str(v)), _esc_tt(str(_TT_CAT_LABEL.get(v, v))))
            for v in vals)
        chips.append("<div class='tt-filter-group'><span class='tt-filter-label'>%s</span>%s</div>"
                     % (_esc_tt(label), _c))
    _ag = _TM.aggregate_group(events)
    doc.w("<div class='tt-sticky-summary' data-tt-sticky>"
          "<span class='tt-ss-cell'>Events <b data-ss='events'>%d</b></span>"
          "<span class='tt-ss-cell'>Bullets <b data-ss='bullets'>%d</b></span>"
          "<span class='tt-ss-cell'>Cost <b data-ss='cost'>%s</b></span>"
          "<span class='tt-ss-cell'>Return <b data-ss='return'>%s</b></span>"
          "<span class='tt-ss-cell'>Net <b data-ss='net'>%s</b></span>"
          "<span class='tt-ss-cell'>ROI <b data-ss='roi'>%s</b></span>"
          "<span class='tt-ss-cov' data-ss='coverage'>Results available for %d of %d events</span>"
          "</div>" % (
              _ag['events'], _ag['bullets'], _fmt_usd(_ag['committed_cost']),
              _fmt_usd(_ag['covered_return']),
              (_fmt_usd(_ag['net'], plus=True) if _ag['net'] is not None else EMDASH),
              (_pct_or_dash(_ag['roi_pct']) if _ag['roi_pct'] is not None else EMDASH),
              _ag['n_settled'], len(events)))
    # QA-RES-001/002: the competing top `.tt-filters` toolbar is REMOVED -- the Results DataTable filter
    # (`.dt-filters` on tt-results) is the ONE canonical filter state, and its bridge (ttApplyFiltersForIds)
    # already re-drives the sticky summary, grouped rows+footer, coverage note and the financial chart from
    # the same filtered event-ID set. The sticky bar above stays; `chips` is intentionally not emitted.
    _ = chips
    doc.w("")


# =====================================================================================================
# FROZEN_AFTER_V820_CLOSURE -- Tournament Results passed its v8.20 Iteration-2 closure:
#   * combined Date + Tournament identity (A1); ONE stacked finish-outcome bar, no metric toggle (A2);
#   * no silent hand-count cap (Track 2.2);
#   * canonical event/bullet/exit finality model (gem_tournament_finality) with all SEVEN deterministic
#     fixtures passing + reconciliation invariants (one row per tournament; Day-1 flights merge; bullet
#     exits reachable; unresolved/advanced never invents a final exit; totals reconcile).
# Future changes to this section require a DEMONSTRATED data/correctness defect (a failing acceptance
# test) or an explicit new owner decision -- no further redesign. (Browser screenshot capture is the only
# deferred item, left for the release-candidate run per the closure brief.)
# =====================================================================================================
RESULTS_FROZEN = 'FROZEN_AFTER_V820_CLOSURE'


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
    # v8.21 (R1): when an HH-only event is unresolved, the session Return / Net / ROI cover only the
    # RESOLVED subset -- mark them coverage-qualified so they never read as a complete N-event result.
    if tot.get('coverage_partial'):
        doc.w("<p class='tt-coverage-partial' style='margin:0 0 10px;padding:8px 12px;border:1px solid "
              "#fde68a;border-radius:10px;background:#fffbeb;color:#92400e'>⚠️ <strong>Session Return / "
              "Net / ROI are partial</strong> — they cover the <strong>%d financially resolved of %d "
              "canonical events</strong>; %d event(s) are unresolved / in-play (committed cost counted, "
              "return pending). These figures are coverage-qualified, not a complete %d-event result.</p>"
              % (tot.get('resolved_events', 0), tot.get('total_events', 0),
                 tot.get('unresolved_events', 0), tot.get('total_events', 0)))
        doc.w('')
    # v8.17 Epic 4: this is now the SINGLE PRIMARY unified Tournament Results
    # table (sortable; one row per event; per-event drilldown). The per-tournament
    # P&L / Deep Runs / Stack Trajectories in S1 are demoted to collapsed
    # cross-check detail; the canonical per-event financial table is retained
    # below this primary table for cross-check.
    doc.w('*Single primary **Tournament Results** — one canonical per-event table. The grouped '
          'aggregate + distribution chart sit on top; the **Results** table below is the sortable, '
          'filterable per-event surface (one row per event; finish/Top%, cost/return/net/ROI, '
          'BB/100 + cEV/100, and the exit hand as the final column). The legacy per-tournament P&L / '
          'Deep Runs / Stack Trajectories render only inside ONE collapsed secondary reconciliation '
          'disclosure in Variance (below).*')
    doc.w('')
    # R3: compact Type-icon legend (the icon shape, not colour, carries the meaning).
    doc.w("<p class='tt-type-legend' style='font-size:0.85em;color:#6b7280;margin:0 0 8px'>"
          "<strong>Type:</strong> %s Bounty · %s Standard · %s Satellite</p>"
          % (_TYPE_ICON['Bounty'], _TYPE_ICON['Standard'], _TYPE_ICON['Satellite']))
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
        'tt-summary', 'tt_session_summary', s_hdr, s_sep, [s_row]))
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

    # ---- v8.17.1 P4 surfaces 1+2: filters panel + sticky filtered-summary bar ----
    _emit_filters_and_sticky(doc, events)

    # ---- v8.17.1 P4 surface 3: grouped AGGREGATE table (aggregate-first) ----
    # Where did the buy-ins go / which bands are profitable — pooled ROI, settled
    # denominators, legend-square colours. Rendered ABOVE the per-event detail.
    _emit_grouped_aggregate(doc, events)

    # ---- R2 (owner request): restore the approved COMPACT STACKED HORIZONTAL finish-outcome distribution
    # bar as the primary Results chart. The v8.20 group-aware Cost/Cash-Return/Net diverging-bar chart was
    # a regression; the stacked horizontal distribution (one bar, mutually-exclusive outcome segments,
    # compact legend, recomputes under filters) is the canonical visualization. ----
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
    # v8.18.0 Tournament Results redesign: the canonical Results table is now a typed DataTable
    # (gem_report_draft._datatable). One Results section; the exit hand is the FINAL column rendered
    # with the canonical PokerHandDisplay; Details/Drivers/SRC removed; totals + sticky filters.
    from gem_report_draft._datatable import Column as _DTCol, build_cell as _dtcell, hand_cell as _dthand, render_datatable as _dtrender
    # v8.20 W1A.2A Track A1: ONE combined Date + Tournament identity column -- the separate Date column is
    # removed; the tournament cell carries the name (primary) + date/time + buy-in (secondary). Columns are
    # referenced by KEY (_C['name']) below, not by positional index, so the inventory stays stable.
    _RES_COLS = [
        _DTCol('tournament', 'Tournament', 'text'),
        _DTCol('type', 'Type', 'text'),
        _DTCol('bullets', 'Bullets', 'num', aggregate='sum'),
        _DTCol('finish', 'Finish', 'finish'),
        _DTCol('cost', 'Cost', 'money', aggregate='sum'),
        _DTCol('return', 'Return', 'money', aggregate='sum'),
        _DTCol('net', 'Net', 'signed', aggregate='sum'),
        _DTCol('roi', 'ROI', 'pct'),
        _DTCol('bb100', 'BB/100', 'signednum'),    # non-currency signed number (never -$8.90)
        _DTCol('cev', 'cEV/100', 'signednum'),
        _DTCol('exit', 'Exit hand', 'hand', sortable=False),
    ]
    _C = {c.key: c for c in _RES_COLS}
    _cards_by_hid = {}
    for _h in (hands or []):
        _hk = str(_h.get('tournament_hand_id') or _h.get('id') or '')
        if _hk:
            _cards_by_hid[_hk[-8:]] = _h.get('cards') or []
    _dt_rows = []
    _top_pcts = []
    _live_finality = []     # Iter3 Track 1: (eid, event, EventFinality) per row -> live reconciliation
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
        # v8.21 (R1): an unresolved HH-only event has blank Return/Net/ROI (None) -- never $0 (a loss).
        _retv = _fmt_usd(ret.get('value')) if ret.get('value') is not None else EMDASH
        _net = _fmt_usd(e.get('net'), plus=True) if e.get('net') is not None else EMDASH
        _roi = _pct_or_dash(e.get('roi_pct'))

        # --- v8.17.1 P4 surface 5: Finance & Finish row (the split of the former
        # unified table — financial + typed-finish + exit-hand; the duplicate
        # markdown cross-check table is removed, this is the canonical surface) ---
        _eid = e.get('event_id') or ('%s|%s' % (tid, e.get('event_day') or ''))
        _fin_lbl = fin.get('label') or finish_txt
        _fin_sort = fin.get('sort_key')
        _fin_sort = _fin_sort if _fin_sort is not None else 999
        # v8.20 Iter3 Track 1: the live Results Exit hand now derives from the canonical event/bullet/exit
        # finality OWNER (gem_tournament_finality), not the raw event field. The owner returns the final
        # event exit = the last resolved bullet's exit, and NEVER a final exit for an unresolved/advanced
        # event -- so the live row can no longer show an invented exit. The per-event record is collected
        # for the live reconciliation artifact.
        import gem_tournament_finality as _TFIN
        _ev_final = _TFIN.event_finality_for(e)
        _live_finality.append((_eid, e, _ev_final))
        _exit = _ev_final.final_event_exit or None
        _exit_cards = _cards_by_hid.get(str(_exit)[-8:]) if _exit else None
        # v8.18.0 final product-truth correction: return -- HH-only unresolved -> unresolved; satellite
        # seat -> ticket marker; a settled NON-CASH result reads "No cash" HERE (the finish keeps its
        # place/Top% in the Finish column). The finish is NEVER replaced by "No cash".
        _ret_val = ret.get('value')
        _ret_exact = ret.get('exact', True)
        _tick = ret.get('ticket_value')
        _fin_state = fin.get('state')
        if _ret_val is None or (not _ret_exact and not ret.get('cash_received') and not _tick):
            _ret_cell = _dtcell(_C['return'], None,
                                display="<span class='dt-unresolved' title='HH-only — return not yet resolved'>unresolved</span>")
        elif _fin_state == 'no_cash' and not _tick and not ret.get('cash_received'):
            _ret_cell = _dtcell(_C['return'], _ret_val if _ret_val is not None else 0.0,
                                display="<span class='dt-nocash' title='Did not cash'>No cash</span>")
        else:
            _rdisp = _esc_tt(_retv)
            if _tick:
                _rdisp = "<span class='dt-ticket' title='Satellite seat (ticket value)'>&#127915;</span> " + _rdisp
            _ret_cell = _dtcell(_C['return'], _ret_val, display=_rdisp)
        # Avg Top% (totals row) is computed over EVERY event with a valid source Top% -- not only cashers.
        if fin.get('top_percent') is not None:
            _top_pcts.append(float(fin['top_percent']))
        # Finish cell: the place / field + Top% (full finish), sorted by the typed top-percent.
        _fin_place = fin.get('place')
        _fin_tot = fin.get('total_players')
        _fin_tp = fin.get('top_percent')
        if _fin_place and _fin_tot:
            _fin_disp = '%s / %s &middot; %s' % ('{:,}'.format(_fin_place), '{:,}'.format(_fin_tot),
                                                 _esc_tt(_fin_lbl))
        else:
            _fin_disp = _esc_tt(_fin_lbl)
        # A1: ONE combined Date + Tournament identity cell -- name (primary), then date/time + buy-in
        # (secondary, muted). The separate Date column is gone; event identity lives in _row_id/tooltip.
        _ident_detail = ' &middot; '.join(
            _esc_tt(x) for x in (e.get('event_day') or '',
                                 (_buy if (_buy and _buy != EMDASH) else '')) if x)
        _dt_rows.append({
            'tournament': _dtcell(
                _C['tournament'], name,
                display=("<strong class='tt-tname'>%s</strong>%s" % (
                    _esc_tt(_tt_name_line1(name, _buy)),
                    ("<span class='tt-tdetail'>%s</span>" % _ident_detail) if _ident_detail else ''))),
            'type': _dtcell(_C['type'], pt, display=_type_icon_cell_html(pt, _esc_tt)),
            'bullets': _dtcell(_C['bullets'], e.get('bullets', 1)),
            'finish': _dtcell(_C['finish'], (_fin_tp if _fin_tp is not None else _fin_sort), display=_fin_disp),
            'cost': _dtcell(_C['cost'], e.get('cost', 0)),
            'return': _ret_cell,
            'net': _dtcell(_C['net'], e.get('net', 0)),
            'roi': _dtcell(_C['roi'], e.get('roi_pct')),
            # BB/100 (per-tournament, from the perf maps) + cEV/100 (per-event, canonical only) folded
            # into the ONE Results table -- the separate Performance event table is removed.
            'bb100': _dtcell(_C['bb100'], _bbb.get(tid)),
            'cev': _dtcell(_C['cev'], (e.get('performance') or {}).get('cev100')),
            'exit': _dthand(_C['exit'], _exit, _exit_cards, size='compact'),
            '_row_id': _eid,   # RES-008: drilldown key -> tournamentEvents[].event_id
            '_filters': {
                'buyin': (e.get('buyin_band') or 'unknown'),   # QA-RES-004: buy-in joins the one filter set
                'entry_time': (e.get('entry_timing') or 'unknown'),
                'speed': (e.get('speed') or 'unknown'),
                'bounty': ('bounty' if e.get('prize_type') == 'bounty' else 'non-bounty'),
                'freezeout': ('freezeout' if (e.get('entry_pattern') or '') in ('freezeout', 'single', '') else 'reentry'),
                'multibullet': ('multi' if (e.get('bullets', 1) or 1) > 1 else 'single'),
                'multiday': ('multiday' if fin.get('advanced_day2') else 'single-day'),
                'satellite': ('satellite' if fin.get('is_satellite') else 'standard'),
                'phase': (status_label or 'unknown'),
                # A2: each row carries its finish-outcome bucket so the filter controller recomputes the
                # ONE stacked outcome bar from the same currently-filtered event dataset.
                'outcome_bucket': _event_outcome_bucket(e),
            },
        })

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
            # Track 2.2: no silent 60-hand cap — the drilldown carries every hand id for the event.
            'hand_ids': _hids_by_tid.get(tid, []),
        })

    # Iter3 Track 1: stamp the live-render finality reconciliation. Each rendered Exit hand now equals the
    # canonical EventFinality.final_event_exit (the live row consumes the owner), and an unresolved/
    # advanced row carries NO final exit (the owner never invents one).
    import gem_tournament_finality as _TFIN2
    _lf_rows, _lf_invented = [], 0
    for _eid_f, _ev_e, _ev_fin in _live_finality:
        _rf = _TFIN2.render_fields(_ev_fin)
        _invented = bool(_ev_fin.status in (_TFIN2.UNRESOLVED, _TFIN2.ADVANCED, _TFIN2.IN_PROGRESS)
                         and _rf['exit_hand'])
        if _invented:
            _lf_invented += 1
        _lf_rows.append({'event_id': _eid_f, 'status': _ev_fin.status,
                         'rendered_exit': _rf['exit_hand'], 'finality_exit': _ev_fin.final_event_exit or None,
                         'raw_event_exit': _ev_e.get('exit_hand'), 'invented_exit': _invented})
    rd['_live_results_finality'] = {'events': len(_lf_rows), 'invented_exits': _lf_invented,
                                    'consumes_owner': True, 'reconciles': _lf_invented == 0, 'rows': _lf_rows}

    # v8.18.0 Tournament Results redesign — the canonical typed DataTable Results surface. Exit hand is
    # the FINAL column rendered with PokerHandDisplay; Details/Drivers/SRC removed; totals row + average
    # Top%; sticky compact filters with counts. The legacy _ttSort path is retired for this table (it now
    # carries data-datatable=1 + initDataTable; no second table engine drives it).
    doc.w('#### Results')
    doc.w('')
    _avg_top = ('Avg Top %.1f%%' % (sum(_top_pcts) / len(_top_pcts))) if _top_pcts else EMDASH
    import collections as _coll_tt
    _FILTER_DEFS = [('buyin', 'Buy-in'), ('entry_time', 'Entry time'), ('speed', 'Speed'), ('bounty', 'Bounty'),
                    ('freezeout', 'Freezeout'), ('multibullet', 'Multi-bullet'),
                    ('multiday', 'Multi-day'), ('satellite', 'Satellite'), ('phase', 'Phase')]
    # per-filter display labels for the typed values (the value stays the canonical typed token).
    _FILTER_OPT_LABELS = {'speed': {'STANDARD': 'Regular', 'TURBO': 'Turbo', 'HYPER': 'Hyper', 'UNKNOWN': 'Unknown'}}
    _filters = []
    for _fk, _flabel in _FILTER_DEFS:
        _cnts = _coll_tt.Counter((r['_filters'].get(_fk) or 'unknown') for r in _dt_rows)
        if len(_cnts) <= 1:
            continue   # only a filter the data can actually distinguish
        _lbls = _FILTER_OPT_LABELS.get(_fk, {})
        _opts = [{'value': v, 'label': _lbls.get(v) or str(v).replace('-', ' ').replace('_', ' ').title(), 'count': c}
                 for v, c in sorted(_cnts.items())]
        _filters.append({'key': _fk, 'label': _flabel, 'options': _opts})
    doc.w(_dtrender(_RES_COLS, _dt_rows, table_id='tt-results', totals=True, totals_label='Total',
                    totals_override={'finish': _avg_top}, filters=_filters, classes='tt-finance'))
    doc.w('')
    try:
        doc._extra_js.append("if(window.initDataTable)window.initDataTable('tt-results');")
    except Exception:
        pass

    # v8.18.0 final correction: the separate Tournament Performance event table is REMOVED -- its
    # BB/100 + cEV/100 are now columns in the ONE canonical Results DataTable above, so there is exactly
    # one rendered tournament-event table (no duplicate event rows).

    try:
        doc._extra_js.append('window.tournamentEvents=%s;'
                             % _json_tt.dumps(_payload, ensure_ascii=False, default=str))
        # v8.17.1 P4: precomputed distribution dataset (every visible tab × metric)
        # so the chart re-renders on tab/metric change from canonical numbers.
        import gem_tournament_model as _TM_chart
        doc._extra_js.append('window.ttChart=%s;' % _json_tt.dumps(
            _tt_chart_data(_TM_chart, events), ensure_ascii=False, default=str))
        # v8.17.1 P4 surfaces 1+2: per-event model so the filter controller derives
        # ONE filtered set and re-aggregates every surface from it.
        _model_payload = [{
            'id': e.get('event_id'),
            'buyin_band': e.get('buyin_band'),
            'prize_type': e.get('prize_type'),
            'entry_pattern': e.get('entry_pattern'),
            'speed': e.get('speed'),
            'entry_timing': e.get('entry_timing'),
            'event_day': e.get('event_day'),
            'fin_label': (e.get('finish') or {}).get('label'),
            'bullets': e.get('bullets', 1),
            'cost': e.get('cost', 0),
            'ret': (e.get('return') or {}).get('value'),
            'ret_exact': (e.get('return') or {}).get('exact', True),
            'net': e.get('net'),
            'roi': e.get('roi_pct'),
            'fin': {'state': (e.get('finish') or {}).get('state'),
                    'itm': bool((e.get('finish') or {}).get('itm')),
                    'top': (e.get('finish') or {}).get('top_percent'),
                    'sort': (e.get('finish') or {}).get('sort_key')},
            'hands': (e.get('performance') or {}).get('hands'),
            'bb100': (e.get('performance') or {}).get('bb100'),
            'cev100': (e.get('performance') or {}).get('cev100'),
        } for e in events]
        doc._extra_js.append('window.ttModel=%s;' % _json_tt.dumps(
            _model_payload, ensure_ascii=False, default=str))
        doc._extra_js.append('if(window.initTournamentResultsTable)'
                             'window.initTournamentResultsTable();'
                             'if(window.initTtChart)window.initTtChart();'
                             'if(window.initTtFilters)window.initTtFilters();'
                             # RES-008: wire the multi-bullet drilldown on the deferred-load path too.
                             'if(window.wireResultsDrilldown)window.wireResultsDrilldown();'
                             # RES-007: now that the bridge (ttApplyFiltersForIds) exists, re-apply any
                             # restored Results-table filter so the grouped/chart reflect it on reload.
                             "if(window._dtReapply&&window._dtReapply['tt-results'])"
                             "window._dtReapply['tt-results']();")
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
            # QA-RES (shared state): the grouping tab follows on the chart too, then EVERY surface re-renders
            # through the ONE canonical render (current filtered set + active metric) -- never the old
            # full-session ttRenderChart / empty-state ttApplyFilters paths. The active filter is preserved.
            "var ch=document.querySelector('.tt-chart');if(ch)ch.setAttribute('data-tab',tab);"
            "if(window.renderResultsFromCurrentState)window.renderResultsFromCurrentState();"
            "else if(window.ttRenderChart)window.ttRenderChart(g,tab);});});});})();")
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
