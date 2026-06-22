# -*- coding: utf-8 -*-
"""Tournament Tables v8.15 — typed event-level model (Phase 1 / SP-1 data layer).

Pure data-contract layer: turns the canonical committed-cost financial overlay
(`rd['usd_overlay']`, the SAME `usd_overlay` / `_financial_source` contract v8.14.3
sealed) into one typed row per tournament EVENT (not per bullet, not per name
string), joined by `tournament_id`. NO rendering, NO deletion of existing Results
tables, NO new estimators — this module only builds the model + provenance so the
data layer can be reviewed before any UI work (handoff SP-1).

Authoritative spec: Tournament_Tables_v3_1_spec_package/specs/DATA_CONTRACT.md +
CALCULATION_RULES.md + PRODUCT_REQUIREMENTS.md "Financial source of truth".

Contract highlights enforced here:
  * Unit = tournament event; repeated names stay separate events (keyed by the
    canonical `tid`); multi-bullet stays ONE event (overlay already collapses
    bullets into a per-event row with a `bullets` count).
  * Cost = committed cost; Return = cash + ticket value (unless configured
    cash-only); Net/ROI derive from the same basis. Session totals are the
    canonical `usd_overlay.totals` (never a divergent recomputation); per-event
    rows reconcile to them (diagnostic if not).
  * `field_provenance` for every inferred/unknown field (unknown → blank).
  * `event_day` from the canonical report timezone else Asia/Bangkok; never the
    report label date.
  * `cev_per_100` is raw chip-EV/100 (no `%`); blank when unavailable per event.
  * Prize type may be name-token inferred (provenance `inferred`); bounty DOLLAR
    amount is never inferred (stays blank).
  * Stack trajectories are NOT a standalone surface — only detector-backed
    `comeback`/`collapse` drivers survive (passed in via `drivers_by_tid`).
  * Stale `session_financials*.csv` ⇒ diagnostic, never a blocker.
"""

TZ_FALLBACK = 'Asia/Bangkok'

# Name tokens → bounty / mystery (inference only; never a dollar amount).
_BOUNTY_TOKENS = ('knockout', 'bounty', 'six shooter', 'heater', 'ko', 'pko',
                  'gladiator', 'hunter')
_MYSTERY_TOKENS = ('mystery',)

# Single canonical buy-in band config (CALCULATION_RULES.md) — non-overlapping,
# $220+ terminal catch-all, sort by floor.
_BUYIN_BANDS = (
    ('$0-$5', 0, 5), ('$5-$11', 5, 11), ('$11-$22', 11, 22),
    ('$22-$55', 22, 55), ('$55-$110', 55, 110), ('$110-$220', 110, 220),
    ('$220+', 220, None),
)


def _buyin_band(buyin):
    try:
        b = float(buyin)
    except (TypeError, ValueError):
        return None
    for label, lo, hi in _BUYIN_BANDS:
        if b >= lo and (hi is None or b < hi):
            return label
    return None


def _infer_prize_type(name, is_sat):
    """Return (prize_type, bounty_kind, provenance). Satellite from the parser's
    is_sat signal is exact; bounty/standard from name tokens is `inferred`."""
    if is_sat:
        return 'satellite', None, 'exact'
    nm = (name or '').lower()
    if any(tok in nm for tok in _BOUNTY_TOKENS):
        kind = 'mystery' if any(t in nm for t in _MYSTERY_TOKENS) else 'standard'
        return 'bounty', kind, 'inferred'
    if nm.strip():
        # a recognizable cash MTT name with no bounty/satellite signal
        return 'standard', None, 'inferred'
    return 'unknown', None, 'unknown'


def _return_object(cash_received, ticket_value, config):
    """Typed return per CALCULATION_RULES. Default basis = cash + ticket value;
    config={'return_basis':'cash_only'} excludes ticket value. Settled => exact."""
    cash_only = bool(config) and config.get('return_basis') == 'cash_only'
    cash_received = round(float(cash_received or 0), 2)
    ticket_value = round(float(ticket_value or 0), 2)
    value = cash_received if cash_only else round(cash_received + ticket_value, 2)
    if cash_only or ticket_value == 0:
        basis = 'exact_cash'
    elif cash_received == 0:
        basis = 'ticket'
    else:
        basis = 'composite'   # cash + satellite ticket value
    ret = {'value': value, 'exact': True, 'basis': basis,
           'cash_received': cash_received, 'ticket_value': ticket_value}
    if basis == 'composite':
        ret['components'] = [
            {'kind': 'exact_cash', 'amount': cash_received, 'exact': True},
            {'kind': 'ticket', 'amount': ticket_value, 'exact': True},
        ]
    return ret


# ── v8.17.1 P4: finish object — canonical sort domain (CALCULATION_RULES) ──
# Exact Top% finishes use 0.0–100.0; sentinels start ABOVE 100 so a Top 61%
# exact finish never collides with Ticket/Day2/etc.
_FINISH_SENTINEL = {
    'ticket': 101, 'day2': 102, 'itm_est': 103, 'pending': 104,
    'no_cash': 105, 'unknown': 999,
}


def _top_pct_label(tp):
    """'Top X.Y%' -- v8.18.0 Tournament Results contract: ALWAYS one decimal (Top 0.4% / Top 5.0% /
    Top 61.0%), so the column reads consistently and a totals row can carry an average Top%."""
    if tp is None:
        return None
    tp = max(0.0, min(100.0, float(tp)))
    return 'Top %.1f%%' % tp


def _finish_state(finish, ret):
    """Derive {label, state, sort_key, is_in_play} for a finish object from the
    typed finish fields + the typed return (CALCULATION_RULES finish domain).
    state ∈ exact|estimated|pending|no_cash|unknown."""
    place = finish.get('place')
    tp = finish.get('top_percent')
    itm = bool(finish.get('itm'))
    is_sat = bool(finish.get('is_satellite'))
    advanced = bool(finish.get('advanced_day2'))
    exact = bool(ret.get('exact'))
    basis = ret.get('basis', '')
    if is_sat and (ret.get('ticket_value') or 0) > 0:
        return {'label': 'Ticket', 'state': 'exact',
                'sort_key': _FINISH_SENTINEL['ticket'], 'is_in_play': False}
    if not exact:
        if basis == 'day2_mean' or advanced:
            return {'label': 'Day 2', 'state': 'estimated',
                    'sort_key': _FINISH_SENTINEL['day2'], 'is_in_play': True}
        if basis in ('min_cash_likely', 'mystery_avg', 'composite') or itm:
            return {'label': 'Est. ITM', 'state': 'estimated',
                    'sort_key': _FINISH_SENTINEL['itm_est'], 'is_in_play': False}
        return {'label': 'Pending', 'state': 'pending',
                'sort_key': _FINISH_SENTINEL['pending'], 'is_in_play': True}
    # settled / exact -- v8.18.0 final product-truth correction: the FINISH is the place/field/Top%; a
    # non-cash RESULT is a RETURN outcome (shown in the Return column), NEVER a substitute for a valid
    # finish. So an event with a valid Top% always shows it here, whether or not it cashed; the 'no_cash'
    # state only tells the Return column to read "No cash".
    if tp is not None:
        cashed = bool(itm or (ret.get('value') or 0) > 0)
        return {'label': _top_pct_label(tp), 'state': 'exact' if cashed else 'no_cash',
                'sort_key': max(0.0, min(100.0, float(tp))), 'is_in_play': False}
    if place is not None:
        return {'label': '#%d' % place, 'state': 'no_cash',
                'sort_key': _FINISH_SENTINEL['no_cash'], 'is_in_play': False}
    return {'label': '—', 'state': 'unknown',
            'sort_key': _FINISH_SENTINEL['unknown'], 'is_in_play': False}


# v8.18.0 final product-truth correction: every event receives exactly ONE typed speed value
# (STANDARD | TURBO | HYPER | UNKNOWN), with the SOURCE recorded (explicit metadata vs a documented
# name-pattern fallback). A scheduled GG MTT with no turbo/hyper token is STANDARD by default.
_SPEED_TOKENS = (('hyper', 'HYPER'), ('turbo', 'TURBO'))


def classify_speed(name, explicit_speed=None):
    """Return (speed, speed_source). Explicit metadata wins; else a name-pattern token; else STANDARD."""
    es = (explicit_speed or '').strip().upper()
    if es in ('STANDARD', 'TURBO', 'HYPER'):
        return es, 'explicit_metadata'
    n = (name or '').lower()
    for tok, sp in _SPEED_TOKENS:
        if tok in n:
            return sp, 'name_pattern:%s' % tok
    if name:
        return 'STANDARD', 'default_scheduled_mtt'
    return 'UNKNOWN', 'no_source'


def build_tournament_model(rd, cev_by_tid=None, drivers_by_tid=None,
                           session_financials_covers_session=None, config=None,
                           hands_by_tid=None, bb100_by_tid=None,
                           reviewed_by_tid=None, exit_by_tid=None):
    """Build the typed event-level Tournament Tables model from the canonical
    overlay. Pure (no render). Returns a dict:

        { 'events': [event,...], 'totals': {...}, 'return_basis': str,
          'financial_source': 'usd_overlay'|'unavailable',
          'event_day_tz_source': 'canonical_report_tz'|'asia_bangkok',
          'diagnostics': {...} }

    `cev_by_tid` / `drivers_by_tid`: optional {tid: cev_per_100} (raw) and
    {tid: [driver,...]} (detector-backed comeback/collapse only). Absent ⇒ blank.
    `session_financials_covers_session`: True/False/None — False ⇒ stale CSV
    diagnostic, NEVER a blocker. `config`: e.g. {'return_basis':'cash_only',
    'report_timezone': 'America/New_York'}."""
    config = config or {}
    cev_by_tid = cev_by_tid or {}
    drivers_by_tid = drivers_by_tid or {}
    # v8.17.1 P4: canonical per-event performance maps (derived from the session
    # hands + analyst commentary, joined by tournament id). cEV/100 stays in
    # cev_by_tid (blank unless a canonical per-tid source exists); hands / BB-100 /
    # reviewed-count / exit-hand are canonically derivable and feed the Performance
    # table + the hand-weighted grouped BB/100.
    hands_by_tid = hands_by_tid or {}
    bb100_by_tid = bb100_by_tid or {}
    reviewed_by_tid = reviewed_by_tid or {}
    exit_by_tid = exit_by_tid or {}
    rd = rd or {}

    ov = rd.get('usd_overlay') or {}
    parsed = ov.get('status') == 'parsed'
    per_t = ov.get('per_tournament') or []
    ov_tot = ov.get('totals') or {}

    # event_day timezone: canonical report TZ if available, else Asia/Bangkok.
    report_tz = (config.get('report_timezone')
                 or rd.get('report_timezone')
                 or (rd.get('usd_overlay') or {}).get('report_timezone'))
    tz_source = 'canonical_report_tz' if report_tz else 'asia_bangkok'

    cash_only = config.get('return_basis') == 'cash_only'
    return_basis_label = 'cash only' if cash_only else 'cash + ticket'

    platform = rd.get('platform') or 'GG'

    events = []
    inferred_prize = unknown_prize = cev_present = 0
    for t in per_t:
        tid = str(t.get('tid', '') or '')
        name = t.get('name', '') or ''
        start_date = t.get('start_date') or ''          # canonical local date
        buyin = t.get('buyin', 0)
        bullets = t.get('bullets', 1)
        cost = round(float(t.get('cost', 0) or 0), 2)    # committed cost
        ret = _return_object(t.get('cash_received'), t.get('ticket_value'), config)
        net = round(ret['value'] - cost, 2)
        roi_pct = round(net / cost * 100, 1) if cost else None

        prize_type, bounty_kind, prize_prov = _infer_prize_type(name, t.get('is_sat'))
        if prize_prov == 'inferred':
            inferred_prize += 1
        elif prize_type == 'unknown':
            unknown_prize += 1

        # cEV: raw chip-EV/100; blank when unavailable per event. No %.
        cev = cev_by_tid.get(tid)
        cev_prov = 'exact' if cev is not None else 'unknown'
        if cev is not None:
            cev_present += 1

        place = t.get('place', 0) or 0
        total_players = t.get('total_players', 0) or 0
        top_percent = (round(place / total_players * 100, 2)
                       if place and total_players else None)

        drivers = list(drivers_by_tid.get(tid, []))   # detector-backed only

        # v8.17.1 P4: typed finish object — label/state/sort_key/is_in_play from
        # the canonical finish domain (so the detail tables sort best-first and
        # Finish shows Top X% / Ticket / Day 2 / Est. ITM / Pending / No cash).
        _finish = {
            'place': place or None,
            'total_players': total_players or None,
            'itm': bool(t.get('itm')),
            'top_percent': top_percent,
            'is_satellite': bool(t.get('is_sat')),
            'advanced_day2': bool(t.get('advanced')),
        }
        _finish.update(_finish_state(_finish, ret))

        event = {
            'event_id': '%s|%s|%s' % (platform, tid, start_date),
            'tournament_id': tid,
            'name': name,
            'display_name': name,
            'event_day': start_date or None,
            'buy_in': round(float(buyin), 2) if buyin else None,
            'cost': cost,
            'currency': 'USD',
            'buyin_band': _buyin_band(buyin),
            'bullets': bullets,
            'entry_pattern': 'multi_bullet' if (bullets or 1) > 1 else 'single',
            'prize_type': prize_type,
            'bounty_kind': bounty_kind,
            'bounty_amount': None,                 # never inferred
            'speed': classify_speed(name, t.get('speed'))[0],
            'speed_source': classify_speed(name, t.get('speed'))[1],
            'entry_timing': 'unknown',
            'finish': _finish,
            'return': ret,
            'net': net,
            'roi_pct': roi_pct,
            'performance': {
                'cev100': cev, 'cev100_unit': 'raw_chip_ev',
                'hands': hands_by_tid.get(tid),     # canonical per-event hand count
                'bb100': bb100_by_tid.get(tid),     # canonical per-event BB/100
            },
            'reviewed': reviewed_by_tid.get(tid),   # {'reviewed':n,'total':m} or None
            'exit_hand': exit_by_tid.get(tid),      # canonical exit-hand id or None
            'drivers': drivers,
            'field_provenance': {
                'prize_type': prize_prov,
                'bounty_kind': ('inferred' if bounty_kind else 'unknown'),
                'bounty_amount': 'unknown',        # not parsed; blank
                'return_basis': ret['basis'],
                'cev100': cev_prov,
                'hands': ('exact' if hands_by_tid.get(tid) is not None else 'unknown'),
                'bb100': ('exact' if bb100_by_tid.get(tid) is not None else 'unknown'),
                'speed': 'unknown',
                'entry_timing': 'unknown',
                'event_day_tz_source': tz_source,
            },
        }
        events.append(event)

    # Session totals: AUTHORITATIVE = canonical usd_overlay.totals (never a
    # divergent recomputation). Per-event rows must reconcile to them.
    summed_cost = round(sum(e['cost'] for e in events), 2)
    summed_return = round(sum(e['return']['value'] for e in events), 2)
    summed_net = round(summed_return - summed_cost, 2)

    totals = {
        'n_tournaments': ov_tot.get('n_tournaments', len(events)),
        'n_bullets': ov_tot.get('n_bullets', sum(e['bullets'] for e in events)),
        'committed_cost': ov_tot.get('total_cost', summed_cost),
        'return': ov_tot.get('total_cash', summed_return),
        'ticket_value': ov_tot.get('total_ticket_value', 0),
        'net': ov_tot.get('total_net', summed_net),
        'roi_pct': ov_tot.get('roi_pct'),
        'return_basis': return_basis_label,
        'cost_basis': 'committed_cost',
    }
    # When cash-only is configured the canonical (cash+ticket) totals do not
    # apply; fall back to the summed cash-only figures.
    if cash_only:
        totals.update({'committed_cost': summed_cost, 'return': summed_return,
                       'ticket_value': 0, 'net': summed_net,
                       'roi_pct': (round(summed_net / summed_cost * 100, 1)
                                   if summed_cost else None)})

    reconciles = (not parsed) or (
        abs(summed_cost - float(totals['committed_cost'] or 0)) <= 0.01
        and abs(summed_return - float(totals['return'] or 0)) <= 0.01)

    n_ev = len(events)
    diagnostics = {
        'financial_source': 'usd_overlay' if parsed else 'unavailable',
        'n_events': n_ev,
        'reconciles_canonical': bool(reconciles),
        'summed_cost': summed_cost,
        'summed_return': summed_return,
        # stale CSV is a diagnostic, NEVER a blocker (handoff §financial source).
        'canonical_financials_cover_session': session_financials_covers_session,
        'stale_session_financials_is_blocker': False,
        'prize_type_inferred_share': round(inferred_prize / n_ev, 3) if n_ev else 0.0,
        'prize_type_unknown_share': round(unknown_prize / n_ev, 3) if n_ev else 0.0,
        'cev_per_event_coverage': round(cev_present / n_ev, 3) if n_ev else 0.0,
        'cev100_unit': 'raw_chip_ev',
        'event_day_tz_source': tz_source,
        'event_day_source': 'start_date',          # never the report label date
        'has_stack_trajectory_surface': False,      # deleted; drivers-only
    }
    if not parsed:
        diagnostics['financial_unavailable_reason'] = ov.get('status') or 'no_overlay'

    return {
        'events': events,
        'totals': totals,
        'return_basis': return_basis_label,
        'financial_source': diagnostics['financial_source'],
        'event_day_tz_source': tz_source,
        'diagnostics': diagnostics,
    }


# ============================================================
# v8.17.1 P4: pure aggregation helpers (CALCULATION_RULES) — consumed by the
# Tournament-Tables grouped surface. No rendering; no recompute of canonical
# per-event values; just grouping + pooled/settled/hand-weighted math.
# ============================================================

_BAND_FLOOR = {label: lo for label, lo, hi in _BUYIN_BANDS}


def buyin_band_sort_key(label):
    """Sort buy-in bands by numeric floor, never lexicographically."""
    return _BAND_FLOOR.get(label, 10 ** 9)


def finish_sort_key(event):
    """Best-first finish sort key (0–100 exact percent, sentinels >100)."""
    return ((event or {}).get('finish') or {}).get('sort_key', _FINISH_SENTINEL['unknown'])


# RES-006 (v8.19.0): a DISJOINT phase taxonomy. The old grouper keyed on the exact-Top% finish LABEL,
# producing one singleton "Top X%" category per event. Each event now belongs to EXACTLY ONE meaningful
# phase; the exact Top% still shows on the event row.
PHASE_ORDER = ('PENDING', 'DAY_2', 'TICKET', 'FINAL_TABLE', 'DEEP_RUN', 'ITM', 'NO_CASH', 'BOTTOM_50', 'UNKNOWN')
PHASE_LABELS = {'PENDING': 'Pending', 'TICKET': 'Ticket', 'DAY_2': 'Day 2', 'FINAL_TABLE': 'Final table',
                'DEEP_RUN': 'Deep run', 'ITM': 'ITM', 'NO_CASH': 'No cash', 'BOTTOM_50': 'Bottom 50%',
                'UNKNOWN': 'Unknown'}
_FINAL_TABLE_MAX = 9   # finish within the final-table seat count


def phase_category(ev):
    """The single canonical phase an event reached (RES-006). Disjoint -- evaluated in priority order so
    one event maps to exactly one phase. Exact Top% stays on the event row."""
    fin = (ev or {}).get('finish') or {}
    ret = (ev or {}).get('return') or {}
    if fin.get('is_in_play') or fin.get('state') == 'in_play':
        return 'DAY_2' if fin.get('advanced_day2') else 'PENDING'
    if fin.get('is_satellite') and (ret.get('ticket_value') or fin.get('state') == 'ticket'):
        return 'TICKET'
    place = fin.get('place')
    total = fin.get('total_players')
    tp = fin.get('top_percent')
    if place is None or total is None:
        return 'UNKNOWN'
    if place <= _FINAL_TABLE_MAX:                 # explicit FT or finish within final-table size
        return 'FINAL_TABLE'
    if tp is not None and tp <= 5:                # resolved, not FT, deep
        return 'DEEP_RUN'
    if fin.get('itm'):                            # regular cash, not Deep Run / FT
        return 'ITM'
    if tp is not None and tp <= 50:               # resolved non-cash, top half
        return 'NO_CASH'
    if tp is not None and tp > 50:                # resolved non-cash, bottom half
        return 'BOTTOM_50'
    return 'UNKNOWN'


_GROUP_KEY = {
    'buyin': lambda e: e.get('buyin_band'),
    'prize_type': lambda e: e.get('prize_type'),
    'speed': lambda e: e.get('speed'),
    'entry_pattern': lambda e: e.get('entry_pattern'),
    'entry_timing': lambda e: e.get('entry_timing'),
    'phase_reached': phase_category,
    'by_day': lambda e: e.get('event_day'),
}


def group_events(events, tab):
    """Group events by the tab dimension → {category: [events]} (insertion order;
    None/unknown categories kept under their literal key so the UI can auto-hide
    an unknown-coverage tab)."""
    keyfn = _GROUP_KEY.get(tab)
    if keyfn is None:
        return {}
    out = {}
    for e in events or []:
        out.setdefault(keyfn(e), []).append(e)
    return out


def aggregate_group(events):
    """CALCULATION_RULES group aggregate. Pooled ROI on the COVERED subset (events
    with a non-null return); committed cost includes ALL bullets; unresolved cost
    disclosed; ITM/Top5/Top1 on SETTLED denominators; BB/100 + cEV/100
    hand-weighted. Never invents a Net for a blank-return event; never a fake
    -100%."""
    evs = list(events or [])
    committed_cost = round(sum(float(e.get('cost') or 0) for e in evs), 2)
    covered = [e for e in evs if (e.get('return') or {}).get('value') is not None]
    covered_cost = round(sum(float(e.get('cost') or 0) for e in covered), 2)
    covered_return = round(sum(float((e.get('return') or {}).get('value') or 0)
                               for e in covered), 2)
    net = round(covered_return - covered_cost, 2) if covered else None
    roi_pct = (round(net / covered_cost * 100, 1)
               if (covered and covered_cost > 0) else None)
    settled = [e for e in evs
               if (e.get('finish') or {}).get('state') in ('exact', 'no_cash')]
    n_settled = len(settled)

    def _share(pred):
        return (round(sum(1 for e in settled if pred(e)) / n_settled * 100, 1)
                if n_settled else None)
    # COR-004 (v8.18.1): a hand-weighted metric must be weighted over ONLY the events that actually
    # carry it, and must be None (rendered as an em dash, never +0.0) when NO event in the group has a
    # canonical value. Using the shared hand denominator turned "no cEV anywhere" into a real-looking
    # +0.0. Each metric carries typed availability for the renderer.
    hw_bb = hw_cev = hw_den = 0.0
    hw_bb_den = hw_cev_den = 0.0
    for e in evs:
        perf = e.get('performance') or {}
        hnd = float(perf.get('hands') or 0)
        if hnd <= 0:
            continue
        hw_den += hnd
        if perf.get('bb100') is not None:
            hw_bb += float(perf['bb100']) * hnd
            hw_bb_den += hnd
        if perf.get('cev100') is not None:
            hw_cev += float(perf['cev100']) * hnd
            hw_cev_den += hnd
    return {
        'events': len(evs),
        'bullets': sum(int(e.get('bullets') or 1) for e in evs),
        'committed_cost': committed_cost,
        'covered_cost': covered_cost,
        'covered_return': covered_return,
        'unresolved_cost': round(committed_cost - covered_cost, 2),
        'results_covered': len(covered),
        'net': net,
        'roi_pct': roi_pct,
        'estimated': any(not (e.get('return') or {}).get('exact', True) for e in covered),
        'itm_pct': _share(lambda e: (e.get('finish') or {}).get('itm')),
        'top5_pct': _share(lambda e: ((e.get('finish') or {}).get('top_percent') or 999) <= 5),
        'top1_pct': _share(lambda e: ((e.get('finish') or {}).get('top_percent') or 999) <= 1),
        'n_settled': n_settled,
        'bb100': round(hw_bb / hw_bb_den, 1) if hw_bb_den else None,
        'bb100_availability': 'exact' if hw_bb_den else 'unavailable',
        'cev100': round(hw_cev / hw_cev_den, 1) if hw_cev_den else None,
        'cev100_availability': 'exact' if hw_cev_den else 'unavailable',
        'hands': int(hw_den),
    }


# Deterministic category colour (NOT array index) — stable across Cost/Return/Net
# + filters + tab changes (CALCULATION_RULES "color stability").
_TT_PALETTE = ('#2563eb', '#16a34a', '#d97706', '#9333ea', '#dc2626', '#0891b2',
               '#ca8a04', '#4f46e5', '#059669', '#db2777', '#65a30d', '#0284c7')


def color_for(tab, category):
    """Deterministic colour for (tab, category) — hashed, never a visible index."""
    h = 0
    for ch in '%s:%s' % (tab, category):
        h = (h * 31 + ord(ch)) & 0xffffffff
    return _TT_PALETTE[h % len(_TT_PALETTE)]


def distribution_shares(groups_agg, metric):
    """Cost/Return = share of total; Net = diverging (neg share of |neg|, pos
    share of pos). groups_agg = {category: aggregate_group()}. Returns
    {category: {'value', 'share', 'sign'}}."""
    out = {}
    if metric in ('cost', 'return'):
        key = 'committed_cost' if metric == 'cost' else 'covered_return'
        tot = sum(max(0.0, float(g.get(key) or 0)) for g in groups_agg.values()) or 1.0
        for cat, g in groups_agg.items():
            v = float(g.get(key) or 0)
            out[cat] = {'value': round(v, 2), 'share': round(v / tot * 100, 1), 'sign': 1}
    else:  # net — diverging around zero
        pos = sum(float(g['net']) for g in groups_agg.values()
                  if g.get('net') and g['net'] > 0) or 1.0
        neg = sum(-float(g['net']) for g in groups_agg.values()
                  if g.get('net') and g['net'] < 0) or 1.0
        for cat, g in groups_agg.items():
            v = g.get('net')
            if v is None:
                out[cat] = {'value': None, 'share': 0.0, 'sign': 0}
            elif v >= 0:
                out[cat] = {'value': round(v, 2), 'share': round(v / pos * 100, 1), 'sign': 1}
            else:
                out[cat] = {'value': round(v, 2), 'share': round(-v / neg * 100, 1), 'sign': -1}
    return out
