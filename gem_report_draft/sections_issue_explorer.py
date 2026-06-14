"""Issue Explorer v3 — master-detail triage system.

Main table: Priority | Tier | Confidence | Issue | Impact | Diagnosis | Evidence | Action
Expanded drawer: 4 blocks (Summary, Evidence breakdown, Representative hands table, Drill/action)
CSS/JS injected via doc._extra_css/doc._extra_js.

v8.3.0 (2026-06-04)
"""

import re as _re_ie
from gem_report_draft import _state
from gem_report_draft._helpers import (
    _new_badge, _popup_example_ids, _hand_ref, _xref)
from gem_report_draft._html import _html_escape, _md_inline, _cards_str_to_pills
from gem_chart_labels import chart_display_label as _cdl_ie

# v8.14.1 rev-4 (Blocker C): humanize any raw chart-id token (PUSH_/REJAM_/
# CALLJAM_/OPEN_) embedded in a representative-example deviation note, so the
# issue-explorer never shows a bare key like "PUSH_10BB_HJ" in visible text.
_CHART_ID_RE = _re_ie.compile(r'(?:PUSH_|REJAM_|CALLJAM_|OPEN_)[0-9A-Za-z_+]+')


def _humanize_chart_ids(txt):
    if not txt:
        return txt
    return _CHART_ID_RE.sub(lambda m: _cdl_ie(m.group(0)), txt)


def _scrub_internal(text):
    """Remove internal tokens that shouldn't appear in user-facing text."""
    _SCRUBS = {
        'fold_preflop': 'preflop fold', 'folded_preflop': 'preflop fold',
        'check_fold': 'check-fold', 'check_call': 'check-call',
        'check_raise': 'check-raise', 'hero_aggressive': '',
        'HERO_AGGRESSIVE': '', 'equity TBD': '',
    }
    for old, new in _SCRUBS.items():
        if old in text:
            text = text.replace(old, new)
    return text


_TIER_CSS = {
    'confirmed': ('Fix Now',   '#dc2626', '#fef2f2'),
    'candidate': ('Candidate', '#d97706', '#fffbeb'),
    'shadow':    ('Watch',     '#2563eb', '#eff6ff'),
    'cleared':   ('Cleared',   '#16a34a', '#f0fdf4'),
}

_TRAIN_PILL = {
    'gtowizard_drill': ('GTOW Drill',   '#2563eb'),
    'gtowizard_node':  ('GTOW Node',    '#2563eb'),
    'pokerbot_drill':  ('PB Drill',     '#7c3aed'),
    'review':          ('Review Hands', '#d97706'),
    'none':            ('—',            '#9ca3af'),
}


def _emit_issue_explorer(doc, s, rd, hands):
    """Render the Issue Explorer section."""
    issues = rd.get('issue_explorer_issues', [])
    coverage = rd.get('issue_explorer_coverage', [])
    _hbi = s.get('_hands_by_id', {})

    doc._extra_css.append(_IE_CSS)
    doc._extra_js.append(_IE_JS)

    doc.w("")
    doc.w("<<ANCHOR:sec-issue-explorer>>")
    doc.w(f"## Issue Explorer {_new_badge('issue_explorer')}")
    doc.w("")

    if not issues:
        doc.w("> *No issues detected this session.*")
        doc.w("")
        if coverage:
            doc.w(_build_trust_chip(coverage, 0))
        return

    # Counts
    _cn = {'confirmed': 0, 'candidate': 0, 'shadow': 0, 'cleared': 0}
    _has_pf = _has_post = _has_river = 0
    _has_action = 0  # issues that have hand IDs for review
    _analyst_n = 0
    for iss in issues:
        _cn[iss.get('tier', 'shadow')] += 1
        _st = iss.get('where', {}).get('streets', [])
        if 'preflop' in _st:
            _has_pf += 1
        if any(x in _st for x in ['flop', 'turn', 'river']):
            _has_post += 1
        if 'river' in _st:
            _has_river += 1
        # Count actionable: has hand IDs (actual reviewable hands)
        if iss.get('all_hand_ids'):
            _has_action += 1
        _analyst_n += iss.get('evidence_quality', {}).get('analyst_reviewed', 0)

    _open_count = _cn['confirmed'] + _cn['candidate'] + _cn['shadow']

    # ── Raw HTML ──────────────────────────────────────────────────
    _h = []
    _h.append('<div class="ie-explorer">')

    # Summary chips
    _h.append('<div class="ie-chips">')
    for label, count, cls in [
        ('Fix Now', _cn['confirmed'], 'ie-c-fix'),
        ('Candidate', _cn['candidate'], 'ie-c-cand'),
        ('Watch', _cn['shadow'], 'ie-c-watch'),
        ('Cleared', _cn['cleared'], 'ie-c-clear'),
    ]:
        if count:
            _h.append(f'<span class="ie-chip {cls}">{label} <b>{count}</b></span>')
    _h.append('</div>')

    # Trust chip
    _cov_chip = _build_trust_chip_html(coverage, _analyst_n)
    if _cov_chip:
        _h.append(f'<div class="ie-trust">{_cov_chip}</div>')

    # Filter chips
    _h.append('<div class="ie-filters">')
    _filters = [
        ('open', f'Open ({_open_count})', True),
        ('confirmed', f'Fix Now ({_cn["confirmed"]})', False),
        ('candidate', f'Candidates ({_cn["candidate"]})', False),
        ('shadow', f'Watch ({_cn["shadow"]})', False),
        ('cleared', f'Cleared ({_cn["cleared"]})', False),
        ('preflop', f'Preflop ({_has_pf})', False),
        ('postflop', f'Postflop ({_has_post})', False),
        ('has_action', f'Has Hands ({_has_action})', False),
    ]
    for fid, flabel, active in _filters:
        _act = ' ie-f-on' if active else ''
        _h.append(f'<button class="ie-f{_act}" data-filter="{fid}" '
                  f'onclick="ieFilter(\'{fid}\')">{flabel}</button>')
    _h.append('</div>')

    # Split-panel layout: table left, detail drawer right
    _h.append('<div class="ie-split">')

    # Left: table
    _h.append('<div class="ie-left"><div class="table-shell" data-mobile-mode="scroll" style="--mobile-table-min-width:800px"><div class="table-scroll">')
    _h.append('<table class="ie-tbl" id="ie-main-table">')
    _h.append('<thead><tr>')
    for col in ['#', 'Tier', 'Issue', 'Impact', 'Evidence', 'Avail.']:
        _h.append(f'<th class="ie-th" onclick="ieSort(this)">{col}</th>')
    _h.append('</tr></thead><tbody>')

    for iss in issues:
        _build_row(_h, iss, _hbi)

    _h.append('</tbody></table></div></div></div>')

    # Right: detail panel (populated by JS on row click)
    _h.append('<div class="ie-right" id="ie-detail-panel">')
    _h.append('<div class="ie-panel-empty">Click an issue row to see details</div>')
    _h.append('</div>')

    _h.append('</div>')  # ie-split

    # Hidden drawer data (read by JS, not visible)
    for iss in issues:
        _build_drawer(_h, iss, _hbi)

    _h.append('</div>')  # ie-explorer

    doc.w('\n'.join(_h))
    doc.w('')

    # Trust chip as markdown (for md output)
    if coverage:
        doc.w(_build_trust_chip(coverage, _analyst_n))
        doc.w("")

    # Review row (same pattern as all other sections)
    doc.w(f'<<REVIEWROW|sub|sec-issue-explorer|Issue Explorer>>')
    doc.w("")


def _impact_cell(issue):
    """Combine severity + EV cost into a single Impact cell."""
    _sev = issue.get('severity', 'medium')
    _sev_labels = {'critical': '🔴 Critical', 'high': '🔴 High', 'medium': '🟡 Medium',
                   'low': '🟢 Low', 'info': 'ℹ️'}
    _sev_text = _sev_labels.get(_sev, _sev)
    _ev = issue.get('evidence', {}).get('cost_bb_per_100')
    if _ev is not None and _ev != 0:
        return f'{_sev_text}<br><small>{_ev:+.1f} BB/100</small>'
    return _sev_text


def _build_row(h, issue, hbi):
    """Build one table row + hidden drawer."""
    _id = _html_escape(issue.get('id', ''))
    _tier = issue.get('tier', 'shadow')
    _tier_label, _tier_fg, _tier_bg = _TIER_CSS.get(_tier, ('?', '#666', '#f5f5f5'))
    _conf = issue.get('confidence', 'low')
    _pri = issue.get('priority', 99)
    _name = _html_escape(_scrub_internal(issue.get('name', '')))
    _diag = _html_escape(_scrub_internal(issue.get('diagnosis', '')))[:100]

    # Where chips (under issue name)
    _where = issue.get('where', {})
    _chips = []
    for st in _where.get('streets', [])[:2]:
        _chips.append(f'<span class="ie-wc">{st}</span>')
    for pt in _where.get('pot_types', [])[:2]:
        _chips.append(f'<span class="ie-wc">{pt}</span>')
    for hr in _where.get('hero_roles', [])[:1]:
        _chips.append(f'<span class="ie-wc">{hr[:12]}</span>')
    for pos in _where.get('positions', [])[:3]:
        _chips.append(f'<span class="ie-wc">{pos}</span>')
    _where_html = ' '.join(_chips) if _chips else ''

    # Evidence compact — prefer summary (has rate vs target), skip raw pp delta
    _ev = issue.get('evidence', {})
    _ev_summary = (_ev.get('summary') or '')[:60]
    if not _ev_summary:
        _ev_parts = []
        if _ev.get('frequency'):
            _ev_parts.append(f"{_ev['frequency']} spots")
        _ev_summary = ' · '.join(_ev_parts) if _ev_parts else ''
    _ev_text = _html_escape(_ev_summary)

    # Action cell: "Review N hands" button OR section link OR "Metric-only"
    _all_ids = issue.get('all_hand_ids', [])
    _rep = issue.get('representative_hands', {})
    _rep_ids = ((_rep.get('clean_mistake') or []) + (_rep.get('boundary') or []))[:20]
    _popup_ids = _rep_ids or _all_ids[:20]
    _hand_count = len(_all_ids) or len(_popup_ids)
    _prov = issue.get('source_provenance', [{}])
    _sec = _prov[0].get('section', '') if _prov else ''

    _action_parts = []
    if _hand_count and _popup_ids:
        for hid in _popup_ids:
            if isinstance(hid, str) and hid.startswith('TM'):
                _state._APPENDIX_HAND_IDS.add(hid)
                _state._register_hand_priority(hid, 0)  # P0: Issue Explorer
        _ids_csv = ','.join(_popup_ids[:20])
        _popup_n = len(_popup_ids)
        # Label must match actual popup count, not total
        _btn_label = (f'Review {_popup_n} of {_hand_count}' if _popup_n < _hand_count
                      else f'Review {_popup_n} hands')
        _action_parts.append(
            f'<a class="hand-list-trigger ie-action-btn" href="#" '
            f'data-hids="{_html_escape(_ids_csv)}" '
            f'data-list-title="{_html_escape(issue.get("name", ""))}" '
            f'>'
            f'{_btn_label}</a>')
    elif _sec and _sec.startswith('sec-'):
        _action_parts.append(
            f'<a href="#{_html_escape(_sec)}" class="ie-action-link" '
            f'onclick="ieDeepLink(event,this);return false">Open breakdown</a>')
    else:
        _action_parts.append('<span class="ie-muted">Metric-only</span>')

    # Training pill
    _train = issue.get('training', {})
    _tt = _train.get('type', 'none')
    _tl, _tc = _TRAIN_PILL.get(_tt, ('—', '#9ca3af'))
    _tlbl = _train.get('label', _tl)
    if _tt == 'review' and not _popup_ids:
        _tlbl = '—'
        _tc = '#9ca3af'
    if _tlbl and _tlbl not in ('—', 'No Drill'):
        _action_parts.append(
            f'<span class="ie-train" style="background:{_tc}">{_html_escape(_tlbl)}</span>')

    _action_html = ' '.join(_action_parts)

    # Filter tags
    _ftags = [_tier]
    if _tier != 'cleared':
        _ftags.append('open')
    for st in _where.get('streets', []):
        _ftags.append(st)
    if any(st in _where.get('streets', []) for st in ['flop', 'turn', 'river']):
        _ftags.append('postflop')
    if _hand_count:
        _ftags.append('has_action')

    _hide = ' style="display:none"' if _tier == 'cleared' else ''

    h.append(f'<tr class="ie-row" data-issue-id="{_id}" data-tier="{_tier}" '
             f'data-filters="{",".join(_ftags)}" onclick="ieToggle(this,event)"{_hide}>')
    h.append(f'<td class="ie-pri">{_pri}</td>')
    h.append(f'<td><span class="ie-pill" style="background:{_tier_bg};color:{_tier_fg};'
             f'border:1px solid {_tier_fg}">{_tier_label}</span></td>')
    h.append(f'<td class="ie-issue"><b>{_name}</b>')
    if _where_html:
        h.append(f'<div class="ie-where-chips">{_where_html}</div>')
    h.append(f'</td>')
    h.append(f'<td class="ie-impact">{_impact_cell(issue)}</td>')
    h.append(f'<td class="ie-ev">{_ev_text}</td>')
    # Available Evidence badge
    _all_ref_ids = _popup_ids
    _ref_csv = ','.join(_all_ref_ids[:20]) if _all_ref_ids else ''
    _is_metric = 'true' if not _all_ref_ids else 'false'
    h.append(f'<td class="ie-avail" data-ref-hids="{_html_escape(_ref_csv)}" '
             f'data-metric-only="{_is_metric}"><span class="evidence-badge evidence-neutral">—</span></td>')
    h.append('</tr>')
    # Drawer is built OUTSIDE the table (line ~150), not here inside <tbody>


def _build_drawer(h, issue, hbi):
    """Build the expandable detail drawer with 4 blocks."""
    _id = _html_escape(issue.get('id', ''))
    h.append(f'<div class="ie-drawer-data" id="ie-drawer-{_id}" style="display:none">')
    h.append('<div class="ie-dc">')

    # ── Block 1: Issue Summary ────────────────────────────────────
    h.append('<div class="ie-block">')
    _diag = issue.get('diagnosis', '')
    if _diag:
        h.append(f'<div class="ie-d"><b>Diagnosis:</b> {_html_escape(_diag)}</div>')
    _why = issue.get('why_it_matters', '')
    if _why:
        h.append(f'<div class="ie-d"><b>Why it matters:</b> {_html_escape(_why)}</div>')
    _act = issue.get('correct_action', '')
    if _act:
        h.append(f'<div class="ie-d"><b>Correct action:</b> {_html_escape(_act)}</div>')
    _exc = issue.get('exception', '')
    if _exc:
        h.append(f'<div class="ie-d"><b>Exception:</b> {_html_escape(_exc)}</div>')
    _mem = issue.get('memory_rule', '')
    if _mem:
        h.append(f'<div class="ie-mem"><b>Remember:</b> <em>{_html_escape(_mem)}</em></div>')
    h.append('</div>')

    # ── Block 2: Evidence Breakdown ───────────────────────────────
    _ev = issue.get('evidence', {})
    _where = issue.get('where', {})
    _prov = issue.get('source_provenance', [{}])
    _sec = _prov[0].get('section', '') if _prov else ''
    _det = _prov[0].get('detector', '') if _prov else ''
    _eq = issue.get('evidence_quality', {})

    _ev_rows = []
    if _ev.get('sample_size'):
        _ev_rows.append(('Sample', str(_ev['sample_size'])))
    if _ev.get('frequency'):
        _ev_rows.append(('Frequency', f"{_ev['frequency']} spots"))
    if _ev.get('delta_vs_target'):
        _ev_rows.append(('Delta vs target', str(_ev['delta_vs_target'])))
    if _ev.get('cost_bb_per_100') is not None:
        _ev_rows.append(('EV cost', f"{_ev['cost_bb_per_100']:+.1f} BB/100"))
    if _ev.get('recurrence_sessions'):
        _ev_rows.append(('Recurring', f"{_ev['recurrence_sessions']} sessions"))
    if _eq.get('analyst_reviewed'):
        _ev_rows.append(('Analyst-reviewed', str(_eq['analyst_reviewed'])))
    # Where details
    _wd = []
    if _where.get('streets'):
        _wd.append(f"Streets: {', '.join(_where['streets'])}")
    if _where.get('pot_types'):
        _wd.append(f"Pot: {', '.join(_where['pot_types'])}")
    if _where.get('hero_roles'):
        _wd.append(f"Hero: {', '.join(_where['hero_roles'])}")
    if _where.get('positions'):
        _wd.append(f"Positions: {', '.join(_where['positions'])}")
    if _wd:
        _ev_rows.append(('Where', ' · '.join(_wd)))
    if _sec and _sec.startswith('sec-'):
        _ev_rows.append(('Details', f'<a href="#{_html_escape(_sec)}" class="xref" '
                                    f'onclick="ieDeepLink(event,this);return false">Open breakdown →</a>'))

    if _ev_rows:
        h.append('<div class="ie-block" data-mobile-mode="compact">')
        h.append('<table class="ie-ev-tbl">')
        for label, val in _ev_rows:
            h.append(f'<tr><td class="ie-ev-l">{label}</td><td>{val}</td></tr>')
        h.append('</table></div>')

    # Evidence quality badges
    _eq = issue.get('evidence_quality', {})
    _all_ids = issue.get('all_hand_ids', [])
    _eq_parts = []
    if _eq.get('sample_size'):
        _eq_parts.append(f"{_eq['sample_size']} sample")
    _eq_parts.append(f"{len(_all_ids)} hands available" if _all_ids else "metric-only")
    if _eq.get('analyst_reviewed'):
        _eq_parts.append(f"{_eq['analyst_reviewed']} analyst-reviewed")
    h.append(f'<div class="ie-d" style="font-size:11px;color:var(--muted)">'
             f'Evidence: {" · ".join(_eq_parts)}</div>')

    # Sub-breakdowns (watchlist position breakdown)
    _bds = issue.get('sub_breakdowns', [])
    if _bds:
        h.append('<div class="ie-block" data-mobile-mode="compact">')
        h.append('<table class="ie-sub-tbl"><thead><tr><th>Position</th><th>Value</th><th>Target</th><th>Status</th></tr></thead><tbody>')
        for bd in _bds:
            _st = '🔴' if bd.get('status') == 'red' else ('🟡' if bd.get('status') == 'amber' else '🟢')
            h.append(f'<tr><td>{_html_escape(str(bd.get("position", "")))}</td>'
                     f'<td>{_html_escape(str(bd.get("value", "")))}</td>'
                     f'<td>{_html_escape(str(bd.get("target", "")))}</td>'
                     f'<td>{_st}</td></tr>')
        h.append('</tbody></table></div>')

    # ── Block 3: Representative Hands (table format) ────────────────
    _rep = issue.get('representative_hands', {})
    _has_rep = any(_rep.get(k) for k in ('clean_mistake', 'boundary', 'counterexample'))
    _all_ids = issue.get('all_hand_ids', [])

    if _has_rep or _all_ids:
        h.append('<div class="ie-block">')
        h.append('<b>Representative Hands</b>')
        # Build table rows from representative hand IDs
        _rep_rows = []
        for rtype, rlabel in [('clean_mistake', 'Clear error'), ('boundary', 'Boundary'), ('counterexample', 'Counter')]:
            for hid in (_rep.get(rtype) or [])[:2]:
                _rh = hbi.get(hid, {})
                if isinstance(_rh, dict) and _rh.get('id'):
                    _rep_rows.append((rlabel, hid, _rh))
                elif isinstance(hid, str):
                    _rep_rows.append((rlabel, hid, {}))

        if _rep_rows:
            _ie_qid = f"ie-rep-{_html_escape(_id)}"
            _ie_qtitle = f"{_html_escape(issue.get('name', 'Issue'))} — Representative Hands"
            h.append(f'<div class="table-shell" data-mobile-mode="hand-list">')
            h.append(f'<table class="ie-rep-tbl" id="{_ie_qid}"'
                     f' data-hand-queue-id="{_ie_qid}"'
                     f' data-hand-queue-title="{_ie_qtitle}">'
                     f'<thead><tr>')
            h.append('<th>Type</th><th>Hand</th><th>Spot</th><th>Cards</th><th>Stack</th><th>Net</th><th>Open</th>')
            h.append('</tr></thead><tbody>')
            _hand_devs = issue.get('hand_deviations', {})
            for _rl, _hid, _rh in _rep_rows:
                _hid_short = _hid[-8:] if len(_hid) > 8 else _hid
                _hid_full = _hid
                _pos = _html_escape(_rh.get('position', ''))
                _cards_raw = ''.join(_rh.get('cards', []))
                _cards_disp = _cards_str_to_pills(_cards_raw) if _cards_raw else '—'
                _stack = f"{_rh.get('stack_bb', 0):.0f}BB" if _rh.get('stack_bb') else '—'
                _net = _rh.get('net_bb', 0)
                _net_cls = 'net-pos' if _net > 0 else 'net-neg' if _net < 0 else ''
                _net_str = f'{_net:+.1f}' if _net else '—'
                _spot = _html_escape(f"{_pos} {_rh.get('tournament_phase', '').replace('_', ' ')[:10]}".strip())
                # V25.3 item 7b: rely on delegated handler, no inline onclick
                _open_link = (f'<a class="hand-ref xref" href="#sec-app-hand-{_hid_short}" '
                              f'data-hand-id="{_hid_short}">'
                              f'<code>{_hid_short}</code></a>')
                # B146/B160: annotate with deviation type + chart if available
                _dev = _hand_devs.get(_hid_full) or _hand_devs.get(_hid_short, {})
                _dev_note = ''
                if _dev:
                    _dt = _humanize_chart_ids(_dev.get('type', ''))
                    _dc = _humanize_chart_ids(_dev.get('chart', ''))
                    _dev_note = (f'<div style="font-size:11px;color:#888;margin-top:2px">'
                                 f'{_html_escape(_dt)}'
                                 f'{" — " + _html_escape(_dc) if _dc else ""}</div>')
                h.append(f'<tr><td class="ie-rep-type">{_rl}{_dev_note}</td>'
                         f'<td>{_open_link}</td>'
                         f'<td>{_spot}</td>'
                         f'<td>{_cards_disp}</td>'
                         f'<td>{_stack}</td>'
                         f'<td class="{_net_cls}">{_net_str}</td>'
                         f'<td>{_open_link}</td></tr>')
            h.append('</tbody></table></div>')

        if len(_all_ids) > 3:
            _ids_csv = ','.join(str(x) for x in _all_ids[:50])
            h.append(f'<div style="margin-top:6px">'
                     f'<a class="hand-list-trigger ie-action-btn" href="#" '
                     f'data-hids="{_html_escape(_ids_csv)}" '
                     f'data-list-title="{_html_escape(issue.get("name", ""))}">'
                     f'Open all {len(_all_ids)} hands</a></div>')
        h.append('</div>')

    # ── Block 4: Drill / Action ───────────────────────────────────
    _train = issue.get('training', {})
    if _train.get('description'):
        h.append('<div class="ie-block">')
        h.append(f'<div class="ie-d"><b>Training:</b> {_html_escape(_train["description"])}</div>')
        if _train.get('url'):
            h.append(f'<a href="{_html_escape(_train["url"])}" class="ie-action-btn" '
                     f'target="_blank">{_html_escape(_train.get("label", "Open"))}</a>')
        h.append('</div>')

    # Postflop drill-down
    _dd = issue.get('postflop_action_drilldown', [])
    if _dd:
        _build_drilldown(h, _dd, hbi)

    # Per-issue review row (collapsed inside drawer)
    _issue_title = _html_escape(issue.get('name', _id))
    h.append(f'<details class="audit-row" data-aid="issue:{_id}" '
             f'data-atype="issue" data-atitle="{_issue_title}">'
             f'<summary class="audit-summary">🔍 <span class="audit-tag">Review</span>'
             f'<span class="audit-context"> · {_issue_title}</span>'
             f'<span class="audit-preview"> — not yet reviewed</span></summary>'
             f'<div class="audit-body">'
             f'<label class="audit-l">Verdict</label>'
             f'<select class="audit-status">'
             f'<option value="">— select —</option>'
             f'<option>Agree</option><option>Debate</option>'
             f'<option>Report bug</option><option>Needs better evidence</option>'
             f'<option>Needs drill</option></select>'
             f'<label class="audit-l">Notes</label>'
             f'<textarea class="audit-notes" rows="2" '
             f'placeholder="Optional notes..."></textarea>'
             f'</div></details>')

    h.append('</div></div>')


def _build_drilldown(h, rows, hbi):
    """Build the Postflop Action Drill-Down table."""
    h.append('<div class="ie-dd" data-mobile-mode="scroll" style="--mobile-table-min-width:800px">')
    h.append('<b>Postflop Action Drill-Down</b>')
    h.append('<div class="table-scroll"><table class="ie-dd-tbl"><thead><tr>')
    for col in ['Street', 'Pot', 'Hero', 'Board', 'Did', 'Should', 'Error', 'Freq', 'Hands']:
        h.append(f'<th>{col}</th>')
    h.append('</tr></thead><tbody>')
    for row in rows:
        _rids = row.get('representative_hand_ids', [])[:3]
        _pills = ' '.join(_md_inline(_hand_ref(hbi.get(hid, hid))) for hid in _rids) if _rids else f'{len(row.get("all_hand_ids", []))} hands'
        h.append('<tr>')
        h.append(f'<td>{_html_escape(row.get("street", ""))}</td>')
        h.append(f'<td>{_html_escape(row.get("pot_type", ""))}</td>')
        h.append(f'<td>{_html_escape(row.get("hero_role", ""))}</td>')
        h.append(f'<td>{_html_escape(row.get("board_texture", ""))}</td>')
        h.append(f'<td>{_html_escape(row.get("hero_action", ""))}</td>')
        h.append(f'<td>{_html_escape(row.get("recommended_action", ""))}</td>')
        h.append(f'<td>{_html_escape(row.get("error_type", "").replace("_", " "))}</td>')
        h.append(f'<td>{row.get("frequency", 0)}</td>')
        h.append(f'<td>{_pills}</td>')
        h.append('</tr>')
    h.append('</tbody></table></div></div>')


# ── Trust chip ────────────────────────────────────────────────────────

def _build_trust_chip(coverage, analyst_n=0):
    """Markdown trust chip for md output."""
    _to = sum(c.get('opportunities', 0) for c in coverage)
    _ta = sum(c.get('auto_scored', 0) for c in coverage)
    _pct = round(_ta / _to * 100) if _to else 0
    _gaps = [(c['spot'], c.get('opportunities', 0), c.get('auto_scored', 0))
             for c in coverage if c.get('opportunities', 0) > c.get('auto_scored', 0)]
    _gaps.sort(key=lambda x: -(x[1] - x[2]))
    _blind = f" · Main blind spot: {_gaps[0][0]} {_gaps[0][2]}/{_gaps[0][1]}" if _gaps else ''
    return (f"> **Coverage:** {_pct}% auto-scored ({_ta}/{_to}) · "
            f"Analyst-reviewed: {analyst_n} hands{_blind}")


def _build_trust_chip_html(coverage, analyst_n=0):
    """HTML trust chip for the IE header."""
    if not coverage:
        return ''
    _to = sum(c.get('opportunities', 0) for c in coverage)
    _ta = sum(c.get('auto_scored', 0) for c in coverage)
    _pct = round(_ta / _to * 100) if _to else 0
    _gaps = [(c['spot'], c.get('opportunities', 0), c.get('auto_scored', 0))
             for c in coverage if c.get('opportunities', 0) > c.get('auto_scored', 0)]
    _gaps.sort(key=lambda x: -(x[1] - x[2]))
    _blind = f' &middot; Main blind spot: {_gaps[0][0]} {_gaps[0][2]}/{_gaps[0][1]}' if _gaps else ''
    return (f'<span class="ie-trust-text">Coverage: {_pct}% auto-scored '
            f'&middot; Analyst-reviewed: {analyst_n} hands{_blind}</span>')


# ── Coverage QA table (called from QA section, NOT from IE) ──────────

def emit_coverage_qa_table(doc, coverage):
    """Full Analysis Coverage table for QA/Appendix section. Collapsed."""
    doc.w("")
    doc.w("<<ANCHOR:sec-ie-coverage>>")
    doc.w("<details><summary><strong>Analysis Coverage — full detail</strong></summary>")
    doc.w("")
    _gaps = [(c['spot'], c.get('opportunities', 0), c.get('auto_scored', 0))
             for c in coverage if c.get('opportunities', 0) > c.get('auto_scored', 0)]
    _no_train = [c['spot'] for c in coverage if not c.get('has_drill_down')]
    _analyst_n = sum(c.get('analyst_reviewed', 0) for c in coverage)
    if _gaps or _no_train:
        doc.w("**Largest Blind Spots:**")
        doc.w("")
        for spot, opps, auto in sorted(_gaps, key=lambda x: -(x[1] - x[2]))[:3]:
            doc.w(f"- {spot}: {auto}/{opps} auto-scored")
        for spot in _no_train:
            doc.w(f"- {spot}: training unavailable")
        if _analyst_n == 0:
            doc.w("- Analyst review: 0 hands / 0 spots")
        doc.w("")
    if _analyst_n == 0:
        doc.w("> *This report is auto-scored only unless analyst review notes were provided.*")
        doc.w("")
    doc.w("| Spot | Opportunities | Auto-scored | Auto % | Analyst spots | Training |")
    doc.w("|------|--------------|-------------|--------|--------------|----------|")
    _to = _ta = _tn = 0
    for c in coverage:
        o = c.get('opportunities', 0)
        a = c.get('auto_scored', 0)
        n = c.get('analyst_reviewed', 0)
        _apct = f'{round(a / o * 100)}%' if o else '—'
        # v8.12.6: '—' not the word 'None' — read as a Python leak in QA
        d = 'Review Hands' if c.get('has_drill_down') else '—'
        _to += o; _ta += a; _tn += n
        doc.w(f"| {c['spot']} | {o} | {a} | {_apct} | {n} | {d} |")
    _pct = f'{round(_ta / _to * 100)}%' if _to else '—'
    doc.w(f"| **Total** | **{_to}** | **{_ta}** | **{_pct}** | **{_tn}** | |")
    doc.w("")
    doc.w("</details>")
    doc.w("")


# ── CSS ───────────────────────────────────────────────────────────────

_IE_CSS = """
.ie-explorer { margin: 1em 0; }
.ie-split { display: flex; flex-wrap: nowrap; align-items: stretch; min-height: 400px; border: 1px solid var(--line); border-radius: 18px; overflow: hidden; background: var(--paper); }
.ie-left { flex: 1 1 auto; min-width: 0; overflow: auto; }
/* UX-7: sticky offset matches report topbar */
.ie-right { flex: 0 0 340px; width: 340px; min-width: 0; align-self: flex-start; position: sticky; top: 70px; border-left: 1px solid var(--line); border-top: 0; background: #fbfdff; padding: 16px; overflow: auto; max-height: calc(100vh - 90px); }
.ie-panel-empty { color: var(--muted); text-align: center; padding: 40px 16px; font-size: 14px; }
.ie-row.ie-selected td { background: #eef6ff !important; }
.ie-drawer-data { display: none; }
@media (max-width: 820px) { .ie-split { flex-direction: column; } .ie-right { flex: 1 1 auto; width: auto; position: static; border-left: 0; border-top: 1px solid var(--line); max-height: none; } }
.ie-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.ie-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px;
  border-radius: 999px; font-size: 12px; font-weight: 600; border: 1px solid var(--line); }
.ie-chip b { font-size: 13px; }
.ie-c-fix { background: #fef2f2; color: #dc2626; border-color: #fecaca; }
.ie-c-cand { background: #fffbeb; color: #d97706; border-color: #fde68a; }
.ie-c-watch { background: #eff6ff; color: #2563eb; border-color: #bfdbfe; }
.ie-c-clear { background: #f0fdf4; color: #16a34a; border-color: #bbf7d0; }
.ie-avail { min-width: 60px; }
.evidence-badge { display: inline-flex; align-items: center; padding: 2px 7px;
  border-radius: 999px; font-size: 11px; font-weight: 800; white-space: nowrap; border: 1px solid transparent; }
.evidence-good { background: #ecfdf3; color: #166534; border-color: #bbf7d0; }
.evidence-warn { background: #fffbeb; color: #92400e; border-color: #fde68a; }
.evidence-bad, .evidence-missing { background: #fef2f2; color: #991b1b; border-color: #fecaca; }
.evidence-neutral { background: #f8fafc; color: #64748b; border-color: #cbd5e1; }
.ie-trust { margin-bottom: 10px; }
.ie-trust-text { font-size: 12px; color: var(--muted); }
/* UX-8: larger touch targets for filters + rows */
.ie-filters { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.ie-f { padding: 5px 12px; border-radius: 999px; border: 1px solid var(--line);
  background: var(--paper); color: var(--muted); font-size: 12.5px; cursor: pointer; font-weight: 500; }
.ie-f:hover { border-color: var(--brand2); color: var(--brand2); }
.ie-f-on { background: var(--brand); color: #fff !important; border-color: var(--brand); }
.ie-tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.ie-th { position: sticky; top: 0; background: #eff4ff; color: #172554;
  border: 0; border-bottom: 2px solid var(--line); padding: 6px 8px; text-align: left;
  font-weight: 700; font-size: 11px; white-space: nowrap; cursor: pointer; user-select: none; }
.ie-th:hover { background: #dbeafe; }
.ie-tbl td { border: 0; border-bottom: 1px solid #eef2f7; padding: 7px 10px;
  vertical-align: top; background: #fff; }
.ie-tbl tr:nth-child(even) td { background: #fbfdff; }
.ie-row { cursor: pointer; transition: background 0.1s; }
.ie-row:hover td { background: #f0f4ff !important; }
/* Issue review status tinting — via data-issue-review attr set by JS */
.ie-row[data-issue-review="agree"] td { background: #f0fdf4 !important; }
.ie-row[data-issue-review="debate"] td { background: #fffbeb !important; }
.ie-row[data-issue-review="report-bug"] td { background: #fff1f2 !important; }
.ie-row[data-issue-review="needs-evidence"] td { background: #eff6ff !important; }
.ie-row[data-issue-review="needs-drill"] td { background: #faf5ff !important; }
.ie-row[data-issue-review="agree"] td:first-child { box-shadow: inset 6px 0 0 #16a34a; }
.ie-row[data-issue-review="debate"] td:first-child { box-shadow: inset 6px 0 0 #d97706; }
.ie-row[data-issue-review="report-bug"] td:first-child { box-shadow: inset 6px 0 0 #dc2626; }
.ie-row[data-issue-review="needs-evidence"] td:first-child { box-shadow: inset 6px 0 0 #2563eb; }
.ie-row[data-issue-review="needs-drill"] td:first-child { box-shadow: inset 6px 0 0 #7c3aed; }
.ie-row.ie-selected td { outline: 1px solid rgba(29,78,216,.20);
  background-image: linear-gradient(rgba(29,78,216,.045),rgba(29,78,216,.045)); }
/* Review coverage pills */
/* UX-3: review pills bigger + clearer */
.review-pill { display: inline-flex; align-items: center; gap: 4px; margin-left: 5px;
  padding: 3px 10px; border-radius: 999px; border: 1px solid #cbd5e1; background: #f8fafc;
  color: #475569; font-size: 12px; font-weight: 800; white-space: nowrap; vertical-align: middle; }
.review-pill.review-all { background: #ecfdf3; border-color: #bbf7d0; color: #166534; }
.review-pill.review-some { background: #eff6ff; border-color: #bfdbfe; color: #1d4ed8; }
.review-pill.review-none { background: #fff7ed; border-color: #fed7aa; color: #c2410c; }
.review-pill.review-na { background: #f8fafc; border-color: #cbd5e1; color: #64748b; }
.review-pill.review-missing { background: #fef2f2; border-color: #fecaca; color: #991b1b; }
.ie-avail .review-pill { display: flex; width: max-content; margin-left: 0; margin-top: 3px; }
.hand-list-trigger + .review-pill { margin-left: 6px; }
.list-review-summary { font-size: 12px; color: #cbd5e1; font-weight: 800; margin-left: 8px; }
.ie-pri { font-weight: 800; color: var(--brand); text-align: center; width: 32px; }
.ie-pill { display: inline-block; padding: 1px 7px; border-radius: 999px;
  font-size: 11px; font-weight: 700; white-space: nowrap; }
.ie-conf { font-size: 11px; }
.ie-issue { min-width: 140px; max-width: 240px; }
.ie-issue b { font-size: 12.5px; }
.ie-where-chips { margin-top: 3px; display: flex; flex-wrap: wrap; gap: 3px; }
.ie-wc { display: inline-block; padding: 0 5px; border-radius: 3px;
  background: #f1f5f9; color: #64748b; font-size: 10px; border: 1px solid #e2e8f0; }
.ie-impact { max-width: 80px; font-size: 12px; }
.ie-impact small { color: var(--muted); }
.ie-diag { color: var(--muted); max-width: 160px; font-size: 11.5px; }
.ie-ev { max-width: 110px; font-size: 11.5px; }
.ie-action { min-width: 100px; }
.ie-action-btn { display: inline-block; padding: 3px 8px; background: var(--brand2);
  color: #fff !important; border-radius: 5px; font-size: 11px; font-weight: 600;
  text-decoration: none; white-space: nowrap; cursor: pointer; }
.ie-action-btn:hover { background: #1e40af; }
.ie-action-link { color: var(--brand2); font-size: 11px; text-decoration: none;
  border-bottom: 1px dashed var(--brand2); }
.ie-muted { color: var(--muted); font-size: 11px; font-style: italic; }
.ie-train { display: inline-block; padding: 1px 6px; border-radius: 999px;
  color: #fff; font-size: 10px; font-weight: 700; margin-left: 4px; }
/* .ie-drawer td removed — drawers are outside table now */
.ie-dc { padding: 12px 16px; font-size: 13px; line-height: 1.5; }
.ie-block { margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #eef2f7; }
.ie-block:last-child { border-bottom: 0; margin-bottom: 0; }
.ie-d { margin: 4px 0; }
.ie-d b { color: var(--brand); }
.ie-mem { background: #fffbeb; border-left: 3px solid #fbbf24; padding: 6px 10px;
  border-radius: 4px; margin: 6px 0; }
.ie-ev-tbl { border-collapse: collapse; font-size: 12px; }
.ie-ev-tbl td { padding: 2px 8px; border-bottom: 1px solid #f1f5f9; }
.ie-ev-l { color: var(--muted); font-weight: 600; width: 100px; }
.ie-sub-tbl { font-size: 12px; border-collapse: collapse; }
.ie-sub-tbl th, .ie-sub-tbl td { border: 1px solid var(--line); padding: 3px 6px; }
.ie-sub-tbl th { background: #f1f5f9; font-size: 11px; }
.ie-rep-tbl { width: 100%; border-collapse: collapse; font-size: 12px; margin: 6px 0; }
.ie-rep-tbl th { background: #f1f5f9; font-size: 10.5px; padding: 3px 6px;
  border-bottom: 1px solid var(--line); text-align: left; font-weight: 600; }
.ie-rep-tbl td { padding: 3px 6px; border-bottom: 1px solid #eef2f7; vertical-align: top; }
.ie-rep-type { color: var(--muted); font-size: 10.5px; font-weight: 600; white-space: nowrap; }
.net-pos { color: var(--good); }
.net-neg { color: var(--bad); }
.ie-dd { margin: 10px 0; padding: 8px; background: #fefce8; border: 1px solid #fde68a; border-radius: 8px; }
.ie-dd > b { display: block; margin-bottom: 6px; color: var(--brand); font-size: 12px; }
.ie-dd-tbl { width: 100%; font-size: 11px; border-collapse: collapse; }
.ie-dd-tbl th { background: #fef3c7; font-size: 10px; padding: 3px 5px; border-bottom: 1px solid #fde68a; }
.ie-dd-tbl td { padding: 3px 5px; border-bottom: 1px solid #fef9c3; }
/* Deep-link scroll + highlight */
[id^="tbl-"], [id^="row-"], h2[id], h3[id], h4[id] { scroll-margin-top: 220px; }
.deep-link-highlight { outline: 3px solid #f59e0b;
  box-shadow: 0 0 0 6px rgba(245,158,11,.18); transition: outline .3s, box-shadow .3s; }
@media (max-width: 768px) {
  /* Issue Explorer mobile card layout */
  #ie-main-table,
  #ie-main-table tbody {
    display: block !important;
    width: 100% !important;
  }
  #ie-main-table thead {
    display: none !important;
  }
  #ie-main-table .ie-row {
    display: grid !important;
    grid-template-columns: 32px minmax(0, 1fr) auto;
    grid-template-areas:
      "rank tier impact"
      "rank issue issue"
      "rank evidence evidence"
      "rank avail avail";
    gap: 5px 8px;
    width: 100% !important;
    margin: 8px 0 !important;
    padding: 10px !important;
    border: 1px solid #d7dce8 !important;
    border-radius: 14px !important;
    background: #fff !important;
    box-shadow: 0 3px 12px rgba(15,23,42,.06);
  }
  #ie-main-table .ie-row > td {
    display: block !important;
    width: auto !important;
    min-width: 0 !important;
    max-width: none !important;
    border: 0 !important;
    padding: 0 !important;
    background: transparent !important;
  }
  #ie-main-table .ie-row > td::before {
    content: none !important;
    display: none !important;
  }
  #ie-main-table .ie-pri {
    grid-area: rank;
    width: 26px !important;
    height: 26px !important;
    border-radius: 999px;
    background: #eef2ff !important;
    color: #172554 !important;
    display: grid !important;
    place-items: center;
    font-weight: 900;
    font-size: 12px;
  }
  /* Prefer .ie-tier class if renderer adds it; fall back to nth-child(2) */
  #ie-main-table .ie-tier,
  #ie-main-table .ie-row > td:nth-child(2) {
    grid-area: tier;
    display: flex !important;
    align-items: center;
  }
  #ie-main-table .ie-issue {
    grid-area: issue;
    max-width: none !important;
    min-width: 0 !important;
  }
  #ie-main-table .ie-issue b {
    display: block;
    font-size: 14px !important;
    line-height: 1.25;
    color: #0f172a;
  }
  #ie-main-table .ie-impact {
    grid-area: impact;
    display: block !important;
    white-space: nowrap;
    font-size: 12px !important;
    font-weight: 800;
    text-align: right;
  }
  #ie-main-table .ie-ev {
    grid-area: evidence;
    display: block !important;
    max-width: none !important;
    font-size: 12px !important;
    line-height: 1.35;
    color: #475569 !important;
    margin-top: 2px;
    display: -webkit-box !important;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  #ie-main-table .ie-avail {
    grid-area: avail;
    display: flex !important;
    align-items: center;
    gap: 6px;
    min-width: 0 !important;
    margin-top: 2px;
  }
  #ie-main-table .ie-conf,
  #ie-main-table .ie-diag {
    display: none !important;
  }
  #ie-main-table .ie-row.ie-selected {
    border-color: #1d4ed8 !important;
    background: #eff6ff !important;
  }
  /* IE bottom-sheet */
  .ie-right {
    position: fixed !important;
    left: 10px !important;
    right: 10px !important;
    bottom: 78px !important;
    width: auto !important;
    max-height: min(68vh, 560px) !important;
    overflow: auto !important;
    border: 1px solid #d7dce8 !important;
    border-radius: 18px !important;
    background: #fff !important;
    box-shadow: 0 18px 60px rgba(15,23,42,.28) !important;
    z-index: 120 !important;
    padding: 12px !important;
    transform: translateY(calc(100% + 100px));
    opacity: 0;
    pointer-events: none;
    transition: transform .18s ease, opacity .18s ease;
  }
  .ie-explorer.ie-mobile-detail-open .ie-right {
    transform: translateY(0);
    opacity: 1;
    pointer-events: auto;
  }
  .ie-mobile-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid #cbd5e1;
    background: #f8fafc;
    color: #334155;
    border-radius: 999px;
    padding: 7px 10px;
    font-weight: 800;
    font-size: 12px;
    float: right;
    margin: 0 0 8px 8px;
    cursor: pointer;
  }
}
"""


# ── JS ────────────────────────────────────────────────────────────────

_IE_JS = r"""
function ieToggle(row, ev) {
  /* P0 #2: don't toggle if click was on a hand-list-trigger or action link */
  if(ev&&(ev.target.closest('.hand-list-trigger')||ev.target.closest('.ie-action-link')||ev.target.closest('.ie-action-btn')))return;
  var id = row.getAttribute('data-issue-id');
  var drawer = document.getElementById('ie-drawer-' + id);
  if (!drawer) return;
  /* Split-panel: copy drawer content to right panel */
  var panel = document.getElementById('ie-detail-panel');
  if (panel) {
    /* Deselect previous row */
    document.querySelectorAll('.ie-row.ie-selected').forEach(function(r){r.classList.remove('ie-selected');});
    row.classList.add('ie-selected');
    panel.innerHTML = drawer.querySelector('.ie-dc').innerHTML;
    /* Re-init audit-row listeners on cloned content */
    panel.querySelectorAll('.audit-row').forEach(function(ar){
      var sel=ar.querySelector('.audit-status');if(!sel)return;
      var ta=ar.querySelector('.audit-notes');
      var key='pokerbot:issuereview:'+(ar.getAttribute('data-aid')||'');
      function _ieReviewSlug(v){
        return({'Agree':'agree','Debate':'debate','Report bug':'report-bug',
                'Needs better evidence':'needs-evidence','Needs drill':'needs-drill'})[v]||'';
      }
      function _ieApplyReview(r,status){
        var slug=_ieReviewSlug(status);
        if(slug)r.setAttribute('data-issue-review',slug);
        else r.removeAttribute('data-issue-review');
      }
      function _ieSave(){
        var d={status:sel.value,notes:ta?ta.value:''};
        try{localStorage.setItem(key,JSON.stringify(d));}catch(e){}
        if(sel.value&&sel.value!=='-- verdict --'){
          ar.classList.add('has-feedback');
          _ieApplyReview(row,sel.value);
        }else{
          ar.classList.remove('has-feedback');
          _ieApplyReview(row,'');
        }
        if(window.pbDecorateDebounced)window.pbDecorateDebounced();
      }
      sel.addEventListener('change',_ieSave);
      if(ta){var _ieSaveTimer=null;ta.addEventListener('input',function(){
        if(_ieSaveTimer)clearTimeout(_ieSaveTimer);_ieSaveTimer=setTimeout(_ieSave,500);});}
      /* Restore saved state */
      try{
        var saved=JSON.parse(localStorage.getItem(key)||'null');
        if(saved){
          if(saved.status)sel.value=saved.status;
          if(saved.notes&&ta)ta.value=saved.notes;
          if(saved.status&&saved.status!=='-- verdict --'){
            ar.classList.add('has-feedback');
            _ieApplyReview(row,saved.status);
          }
        }
      }catch(e){}
    });
  } else {
    /* Fallback: inline toggle if panel missing */
    drawer.style.display = drawer.style.display === 'none' ? '' : 'none';
    row.classList.toggle('ie-row-expanded');
  }
}
function ieFilter(filter) {
  var btns = document.querySelectorAll('.ie-f');
  btns.forEach(function(b) { b.classList.remove('ie-f-on'); });
  var active = document.querySelector('[data-filter="' + filter + '"]');
  if (active) active.classList.add('ie-f-on');
  var rows = document.querySelectorAll('.ie-row');
  /* Split-panel: clear the detail panel when filter changes */
  var panel = document.getElementById('ie-detail-panel');
  if(panel) panel.innerHTML = '<div class="ie-panel-empty">Click an issue row to see details</div>';
  document.querySelectorAll('.ie-row.ie-selected').forEach(function(r){r.classList.remove('ie-selected');});
  rows.forEach(function(r) {
    var tags = (r.getAttribute('data-filters') || '').split(',');
    r.style.display = tags.indexOf(filter) >= 0 ? '' : 'none';
  });
}
function ieSort(th) {
  var table = document.getElementById('ie-main-table');
  if (!table) return;
  var tbody = table.querySelector('tbody');
  var rows = Array.from(tbody.querySelectorAll('tr.ie-row'));
  var idx = Array.from(th.parentNode.children).indexOf(th);
  var asc = th.getAttribute('data-sort-dir') !== 'asc';
  th.setAttribute('data-sort-dir', asc ? 'asc' : 'desc');
  rows.sort(function(a, b) {
    var ac = a.children[idx], bc = b.children[idx];
    var av = (ac ? ac.textContent.trim() : ''), bv = (bc ? bc.textContent.trim() : '');
    var an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  /* Split-panel: only move <tr> rows, never <div> drawers into tbody */
  rows.forEach(function(r) {
    tbody.appendChild(r);
  });
}
function ieDeepLink(ev, el) {
  if(ev){ev.preventDefault();ev.stopPropagation();}
  var href = el.getAttribute('href');
  if (!href || !href.startsWith('#')) return;
  var target = document.getElementById(href.slice(1));
  if (!target) return;
  // Expand any parent <details> elements
  var p = target.parentElement;
  while (p) { if (p.tagName === 'DETAILS' && !p.open) p.open = true; p = p.parentElement; }
  target.scrollIntoView({ block: 'start', behavior: 'smooth' });
  target.classList.add('deep-link-highlight');
  setTimeout(function() { target.classList.remove('deep-link-highlight'); }, 2500);
}
/* Available Evidence badge — uses normalizeHandId for canonical comparison */
(function(){
  var nid=window.normalizeHandId||function(h){var m=String(h||'').match(/(\d{8})$/);return m?m[1]:String(h||'').replace(/^TM/,'');};
  var inspectable=new Set();
  document.querySelectorAll('article.hand-detail-card[data-hand-id]').forEach(function(el){
    inspectable.add(nid(el.getAttribute('data-hand-id')));
  });
  document.querySelectorAll('[id^="sec-app-hand-"]').forEach(function(el){
    inspectable.add(nid(el.id.replace('sec-app-hand-','')));
  });
  var totalMissing=0,totalBadIssues=0;
  document.querySelectorAll('.ie-avail').forEach(function(td){
    var raw=td.getAttribute('data-ref-hids')||'';
    var isMetric=td.getAttribute('data-metric-only')==='true';
    var badge=td.querySelector('.evidence-badge');
    if(!badge)return;
    if(!raw&&isMetric){badge.className='evidence-badge evidence-neutral';badge.textContent='Metric-only';return;}
    if(!raw){badge.className='evidence-badge evidence-missing';badge.textContent='No evidence';return;}
    var refs=raw.split(',').filter(Boolean).map(nid);
    var avail=refs.filter(function(h){return inspectable.has(h);});
    var missing=refs.length-avail.length;
    totalMissing+=missing;
    if(avail.length===refs.length){badge.className='evidence-badge evidence-good';badge.textContent=avail.length+'/'+refs.length+' avail';}
    else if(avail.length>0){badge.className='evidence-badge evidence-warn';badge.textContent=avail.length+'/'+refs.length+' avail';}
    else{badge.className='evidence-badge evidence-bad';badge.textContent='0/'+refs.length+' avail';totalBadIssues++;}
  });
  if(totalMissing>0)console.warn('IE Evidence: '+totalMissing+' referenced hand IDs missing from appendix, '+totalBadIssues+' issues with 0 available');
  /* Sanity: no <div> children inside <tbody> */
  var bad=document.querySelectorAll('#ie-main-table tbody > :not(tr)');
  if(bad.length)console.error('Invalid IE table children (non-tr in tbody):',bad.length);
})();
/* P1 #8: issue review status → colored left border on IE row */
document.querySelectorAll('.ie-row').forEach(function(r){
  var id=r.getAttribute('data-issue-id');
  var drawer=document.getElementById('ie-drawer-'+id);
  if(!drawer)return;
  var sel=drawer.querySelector('.audit-status');
  if(!sel)return;
  sel.addEventListener('change',function(){
    var slugMap={'Agree':'agree','Debate':'debate','Report bug':'report-bug',
      'Needs better evidence':'needs-evidence','Needs drill':'needs-drill'};
    var slug=slugMap[sel.value]||'';
    if(slug)r.setAttribute('data-issue-review',slug);
    else r.removeAttribute('data-issue-review');
  });
});
/* Mobile bottom-sheet behavior — handler attached unconditionally,
   checks viewport width at click time so resize/orientation changes work */
document.addEventListener('click',function(ev){
  if(!(window.matchMedia&&window.matchMedia('(max-width:768px)').matches))return;
  /* Guard: don't hijack clicks on interactive elements inside the row */
  if(ev.target.closest('a,button,.hand-list-trigger,.review-pill,input,select,textarea,.ie-right'))return;
  var row=ev.target.closest('.ie-row');
  if(!row)return;
  var root=row.closest('.ie-explorer');
  if(root)root.classList.add('ie-mobile-detail-open');
  var panel=root?root.querySelector('.ie-right'):null;
  if(panel&&!panel.querySelector('.ie-mobile-close')){
    var close=document.createElement('button');
    close.type='button';
    close.className='ie-mobile-close';
    close.textContent='Close';
    close.addEventListener('click',function(e){
      e.stopPropagation();
      if(root)root.classList.remove('ie-mobile-detail-open');
    });
    panel.insertBefore(close,panel.firstChild);
  }
});
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){
    document.querySelectorAll('.ie-explorer.ie-mobile-detail-open')
      .forEach(function(r){r.classList.remove('ie-mobile-detail-open');});
  }
});
"""
