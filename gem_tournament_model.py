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


def build_tournament_model(rd, cev_by_tid=None, drivers_by_tid=None,
                           session_financials_covers_session=None, config=None):
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
            'speed': 'unknown',                    # name-token speed deferred to render phase
            'entry_timing': 'unknown',
            'finish': {
                'place': place or None,
                'total_players': total_players or None,
                'itm': bool(t.get('itm')),
                'top_percent': top_percent,
                'is_satellite': bool(t.get('is_sat')),
                'advanced_day2': bool(t.get('advanced')),
            },
            'return': ret,
            'net': net,
            'roi_pct': roi_pct,
            'performance': {'cev100': cev, 'cev100_unit': 'raw_chip_ev'},
            'drivers': drivers,
            'field_provenance': {
                'prize_type': prize_prov,
                'bounty_kind': ('inferred' if bounty_kind else 'unknown'),
                'bounty_amount': 'unknown',        # not parsed; blank
                'return_basis': ret['basis'],
                'cev100': cev_prov,
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
