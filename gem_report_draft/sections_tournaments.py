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
from gem_tournament_model import build_tournament_model
from gem_report_draft._blocks import financial_table_block
from gem_report_draft.sections_financial import _fmt_usd

EMDASH = '—'  # —

_PRIZE_LABEL = {'bounty': 'Bounty', 'standard': 'Standard',
                'satellite': 'Satellite', 'unknown': EMDASH}


def _usd_or_dash(v):
    return _fmt_usd(v) if v is not None else EMDASH


def _pct_or_dash(v):
    return ('%+.1f%%' % v) if v is not None else EMDASH


def _emit_tournament_tables(doc, s, rd, hands):
    """Additive S-section: render the event-level Tournament Tables from the
    SP-1 model. Fail-soft: with no canonical overlay it emits a diagnostic line
    and returns (never crashes, never recomputes)."""
    # No cev_by_tid passed: no canonical per-event cEV/100 source exists (SP-2
    # product decision) → per-event cEV stays blank.
    model = build_tournament_model(rd)
    events = model.get('events') or []
    tot = model.get('totals') or {}
    diag = model.get('diagnostics') or {}

    doc.subsection('sec-tournaments', 'Tournament Tables (event-level)',
                   'financial-first; one row per tournament event')

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

    # ---- Summary strip (canonical session totals) ----
    s_hdr = ('| Events | Bullets | Cost | Return (cash+ticket) | of which Ticket | '
             'Net | ROI | Return basis |')
    s_sep = '|---:|---:|---:|---:|---:|---:|---:|---|'
    s_row = ('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
        tot.get('n_tournaments', len(events)), tot.get('n_bullets', EMDASH),
        _fmt_usd(tot.get('committed_cost', 0)), _fmt_usd(tot.get('return', 0)),
        _fmt_usd(tot.get('ticket_value', 0)),
        _fmt_usd(tot.get('net', 0), plus=True), _pct_or_dash(tot.get('roi_pct')),
        tot.get('return_basis', EMDASH)))
    doc.write_block(financial_table_block(
        'tt-summary', 'financial_summary', s_hdr, s_sep, [s_row]))
    doc.w('')

    # ---- Event table (one row per tournament event) ----
    hdr = ('| Date | Tournament | Type | Buy-in | Bullets | Cost | Cash | Ticket | '
           'Return | Net | ROI | Finish | Adv/Seat | cEV/100 |')
    sep = '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|'
    rows = []
    has_inferred = False
    for e in events:
        ret = e.get('return') or {}
        prov = e.get('field_provenance') or {}
        fin = e.get('finish') or {}

        pt = _PRIZE_LABEL.get(e.get('prize_type'), EMDASH)
        if prov.get('prize_type') == 'inferred' and pt != EMDASH:
            pt += '*'
            has_inferred = True

        finish_txt = ('%s/%s' % (fin['place'], fin['total_players'])
                      if fin.get('place') and fin.get('total_players') else EMDASH)
        if fin.get('advanced_day2'):
            adv = 'Day 2'
        elif fin.get('is_satellite') and fin.get('itm'):
            adv = 'seat'
        else:
            adv = EMDASH

        cev = (e.get('performance') or {}).get('cev100')
        cev_txt = ('%.2f' % cev) if cev is not None else EMDASH   # raw chip-EV/100, NO %

        tick = ret.get('ticket_value')
        name = (e.get('name') or EMDASH).replace('|', '/')
        rows.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            e.get('event_day') or EMDASH, name, pt,
            _usd_or_dash(e.get('buy_in')), e.get('bullets', 1),
            _fmt_usd(e.get('cost', 0)),
            _fmt_usd(ret.get('cash_received', 0)),
            (_fmt_usd(tick) if tick else EMDASH),
            _fmt_usd(ret.get('value', 0)),
            _fmt_usd(e.get('net', 0), plus=True),
            _pct_or_dash(e.get('roi_pct')),
            finish_txt, adv, cev_txt))
    doc.write_block(financial_table_block(
        'tt-events', 'tournament_pnl', hdr, sep, rows))
    doc.w('')

    # ---- Footnotes (auditability) ----
    if has_inferred:
        doc.w('*\\* Prize type inferred from the tournament name '
              '(provenance: inferred).*')
    doc.w('*cEV/100 is raw chip-EV per 100 hands; shown blank (—) per event '
          'because no canonical per-tournament cEV/100 source exists — it is never '
          'approximated. Session/aggregate cEV remains where it already appears.*')
    doc.w('*Bounty dollar amounts are shown only when safely sourced (never '
          'inferred); blank otherwise.*')
    doc.w('')
