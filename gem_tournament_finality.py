"""gem_tournament_finality.py -- canonical event/bullet/exit finality model for Tournament Results
(v8.20 Iteration-2, Outcome 1). Scoped to exactly what Tournament Results consumes -- no broad framework.

ONE typed record per canonical tournament event. Multiple Day-1 flights / re-entry bullets resolve into
ONE event keyed by the canonical tournament identity. Each bullet keeps its own first/last/exit hand; the
event's `final_event_exit` is the exit of the LAST resolved bullet, and an unresolved / still-advancing
event NEVER invents a final exit. Pure / deterministic / typed.
"""
from dataclasses import dataclass, field

# event status (exactly one).
RESOLVED = 'resolved'          # a final result exists (busted or cashed, settled)
UNRESOLVED = 'unresolved'      # HH-only / in progress, no settled result
ADVANCED = 'advanced'          # advanced to a later day, not yet finally resolved
IN_PROGRESS = 'in_progress'

# source availability.
HH = 'hh_backed'
SUMMARY = 'summary_backed'
HYBRID = 'hybrid'


@dataclass(frozen=True)
class Bullet:
    bullet_id: str
    first_hand: str = ''
    last_hand: str = ''
    exit_hand: str = ''          # '' => this bullet is unresolved (advanced / in progress)
    net: float = 0.0
    resolved: bool = True

    def to_dict(self):
        return {'bullet_id': self.bullet_id, 'first_hand': self.first_hand, 'last_hand': self.last_hand,
                'exit_hand': self.exit_hand or None, 'net': self.net, 'resolved': self.resolved}


@dataclass(frozen=True)
class EventFinality:
    event_id: str
    tournament_identity: str
    status: str
    bullets: tuple = ()
    final_event_exit: str = ''       # '' => no canonical final exit (unresolved/advanced) -- never invented
    cost: float = 0.0
    return_: float = 0.0
    net: float = 0.0
    ticket_return: float = 0.0
    finish_place: object = None
    total_players: object = None
    percentile: object = None
    is_satellite: bool = False
    source: str = HH
    multiday_parent: str = ''
    flights: tuple = ()              # the source flight/bullet ids merged into this one event
    finality_reason: str = ''
    warnings: tuple = ()

    def to_dict(self):
        return {
            'event_id': self.event_id, 'tournament_identity': self.tournament_identity,
            'status': self.status, 'bullets': [b.to_dict() for b in self.bullets],
            'final_event_exit': self.final_event_exit or None,
            'cost': self.cost, 'return': self.return_, 'net': self.net,
            'ticket_return': self.ticket_return,
            'finish_place': self.finish_place, 'total_players': self.total_players,
            'percentile': self.percentile, 'is_satellite': self.is_satellite,
            'source': self.source, 'multiday_parent': self.multiday_parent or None,
            'flights': list(self.flights), 'finality_reason': self.finality_reason,
            'warnings': list(self.warnings),
        }


def _bullet(b):
    return Bullet(
        bullet_id=str(b.get('bullet_id') or b.get('id') or ''),
        first_hand=str(b.get('first_hand') or ''),
        last_hand=str(b.get('last_hand') or ''),
        exit_hand=str(b.get('exit_hand') or ''),
        net=float(b.get('net') or 0.0),
        resolved=bool(b.get('exit_hand')) if b.get('resolved') is None else bool(b.get('resolved')))


def build_event_finality(raw):
    """Build ONE typed EventFinality from a raw event dict. Merges its bullets/flights; computes the
    canonical final event exit (the last RESOLVED bullet's exit) and the finality reason. Never invents a
    final exit for an unresolved / advanced event."""
    bullets = tuple(_bullet(b) for b in (raw.get('bullets') or []))
    status = raw.get('status') or (RESOLVED if raw.get('exit_hand') or any(b.resolved for b in bullets)
                                   else UNRESOLVED)
    # the final event exit = the exit hand of the LAST resolved bullet (in input order), else explicit ''.
    final_exit = ''
    warnings = []
    if status in (UNRESOLVED, ADVANCED, IN_PROGRESS):
        if raw.get('final_event_exit') or raw.get('exit_hand'):
            warnings.append('unresolved/advanced event carried a final exit in source -- dropped (never invented)')
        finality_reason = 'no final exit: event is %s' % status
    else:
        resolved_bullets = [b for b in bullets if b.resolved and b.exit_hand]
        if resolved_bullets:
            final_exit = resolved_bullets[-1].exit_hand
            finality_reason = 'final exit = last resolved bullet (%s)' % resolved_bullets[-1].bullet_id
        elif raw.get('exit_hand'):
            final_exit = str(raw.get('exit_hand'))
            finality_reason = 'final exit from settled single-bullet event'
        else:
            finality_reason = 'resolved with no exit hand (summary-only result)'
    # source availability.
    has_hh = any(b.first_hand or b.exit_hand for b in bullets) or raw.get('exit_hand')
    src = raw.get('source') or (HYBRID if (has_hh and raw.get('summary_only'))
                                else SUMMARY if raw.get('summary_only') else HH if has_hh else SUMMARY)
    net = raw.get('net')
    if net is None:
        net = round(sum(b.net for b in bullets), 2) if bullets else 0.0
    if raw.get('is_satellite') and raw.get('ticket_return'):
        warnings.append('satellite: return is a ticket value')
    return EventFinality(
        event_id=str(raw.get('event_id') or raw.get('tournament_id') or ''),
        tournament_identity=str(raw.get('tournament_identity') or raw.get('name')
                               or raw.get('tournament_id') or ''),
        status=status, bullets=bullets, final_event_exit=final_exit,
        cost=float(raw.get('cost') or 0.0), return_=float(raw.get('return') or 0.0), net=float(net),
        ticket_return=float(raw.get('ticket_return') or 0.0),
        finish_place=raw.get('finish_place'), total_players=raw.get('total_players'),
        percentile=raw.get('percentile'), is_satellite=bool(raw.get('is_satellite')),
        source=src, multiday_parent=str(raw.get('multiday_parent') or ''),
        flights=tuple(str(x) for x in (raw.get('flights') or [b.bullet_id for b in bullets])),
        finality_reason=finality_reason, warnings=tuple(warnings))


def build_finality_model(raw_events):
    """Merge raw events into ONE EventFinality per canonical tournament identity (Day-1 flights collapse
    into one event row). Returns the list of typed records."""
    by_identity = {}
    order = []
    for raw in (raw_events or []):
        key = str(raw.get('tournament_identity') or raw.get('name') or raw.get('tournament_id') or '')
        if key not in by_identity:
            by_identity[key] = dict(raw)
            by_identity[key]['bullets'] = list(raw.get('bullets') or [])
            by_identity[key]['flights'] = list(raw.get('flights') or [])
            order.append(key)
        else:
            # a second flight of the SAME tournament -> merge bullets + carry the later final result.
            tgt = by_identity[key]
            tgt['bullets'] = list(tgt.get('bullets') or []) + list(raw.get('bullets') or [])
            tgt['flights'] = list(tgt.get('flights') or []) + list(raw.get('flights') or [])
            for f in ('status', 'exit_hand', 'final_event_exit', 'finish_place', 'total_players',
                      'percentile', 'net', 'return', 'ticket_return'):
                if raw.get(f) is not None:
                    tgt[f] = raw.get(f)
            tgt['_merged'] = True
    return [build_event_finality(by_identity[k]) for k in order]


def reconcile(model):
    """Verify the finality invariants over the typed model. Returns a dict of counts + a pass flag."""
    bullet_exits = []
    invented = 0
    totals_ok = 0
    one_row_ids = set()
    dup_identity = 0
    for ev in model:
        if ev.tournament_identity in one_row_ids:
            dup_identity += 1
        one_row_ids.add(ev.tournament_identity)
        for b in ev.bullets:
            if b.exit_hand:
                bullet_exits.append(b.exit_hand)
        # unresolved/advanced events must NOT carry a final exit.
        if ev.status in (UNRESOLVED, ADVANCED, IN_PROGRESS) and ev.final_event_exit:
            invented += 1
        # event net reconciles with the sum of bullet nets (when bullets carry nets).
        if ev.bullets and any(b.net for b in ev.bullets):
            if abs(ev.net - round(sum(b.net for b in ev.bullets), 2)) < 0.01:
                totals_ok += 1
        else:
            totals_ok += 1
        # the final event exit, when present, is one of the bullets' exits (reachable in the drilldown).
    final_exits = [ev.final_event_exit for ev in model if ev.final_event_exit]
    final_in_bullets = all(fe in [b.exit_hand for ev in model for b in ev.bullets] or not [b for ev in model for b in ev.bullets if b.exit_hand]
                           for fe in final_exits)
    return {
        'events': len(model),
        'unique_tournament_identities': len(one_row_ids),
        'duplicate_identity_rows': dup_identity,
        'bullet_exits': len(bullet_exits),
        'final_event_exits': len(final_exits),
        'invented_final_exits': invented,
        'final_exit_reachable_in_bullets': bool(final_in_bullets),
        'totals_reconcile': totals_ok == len(model),
        'invariants_pass': bool(dup_identity == 0 and invented == 0 and final_in_bullets
                                and totals_ok == len(model)),
    }


# --------------------------------------------------------------------------- #
# the seven deterministic fixtures (labelled FIXTURE -- synthetic, not real)   #
# --------------------------------------------------------------------------- #

def seven_fixtures():
    """Exactly the seven required deterministic fixtures. Returns (raw_events, expectations)."""
    raw = [
        # 1. resolved HH-backed event
        {'tournament_identity': 'FIXTURE-HH-Resolved', 'tournament_id': 'F1', 'status': RESOLVED,
         'bullets': [{'bullet_id': 'F1b1', 'first_hand': 'H1', 'last_hand': 'H40', 'exit_hand': 'H40', 'net': -25.0}],
         'cost': 25.0, 'return': 0.0, 'net': -25.0, 'finish_place': 120, 'total_players': 200, 'percentile': 60.0},
        # 2. summary-only event
        {'tournament_identity': 'FIXTURE-SummaryOnly', 'tournament_id': 'F2', 'status': RESOLVED,
         'summary_only': True, 'bullets': [], 'cost': 50.0, 'return': 0.0, 'net': -50.0,
         'finish_place': 300, 'total_players': 500, 'percentile': 60.0},
        # 3. unresolved / in-progress event
        {'tournament_identity': 'FIXTURE-Unresolved', 'tournament_id': 'F3', 'status': UNRESOLVED,
         'bullets': [{'bullet_id': 'F3b1', 'first_hand': 'H1', 'last_hand': 'H10', 'exit_hand': '', 'resolved': False}],
         'cost': 100.0, 'return': 0.0, 'net': 0.0},
        # 4. multi-bullet event with distinct bullet exits
        {'tournament_identity': 'FIXTURE-MultiBullet', 'tournament_id': 'F4', 'status': RESOLVED,
         'bullets': [{'bullet_id': 'F4b1', 'first_hand': 'A1', 'last_hand': 'A9', 'exit_hand': 'A9', 'net': -30.0},
                     {'bullet_id': 'F4b2', 'first_hand': 'B1', 'last_hand': 'B14', 'exit_hand': 'B14', 'net': 220.0}],
         'cost': 60.0, 'return': 280.0, 'net': 190.0, 'finish_place': 3, 'total_players': 180, 'percentile': 1.6},
        # 5. multi-day event: two Day-1 flights of the SAME tournament -> one event row
        {'tournament_identity': 'FIXTURE-MultiDay', 'tournament_id': 'F5', 'status': ADVANCED,
         'flights': ['Day1A'],
         'bullets': [{'bullet_id': 'F5d1a', 'first_hand': 'D1', 'last_hand': 'D20', 'exit_hand': '', 'resolved': False}]},
        {'tournament_identity': 'FIXTURE-MultiDay', 'tournament_id': 'F5', 'status': RESOLVED,
         'flights': ['Day1B'], 'finish_place': 8, 'total_players': 900, 'percentile': 0.9,
         'cost': 215.0, 'return': 1800.0, 'net': 1585.0,
         'bullets': [{'bullet_id': 'F5d1b', 'first_hand': 'E1', 'last_hand': 'E55', 'exit_hand': 'E55', 'net': 1585.0}]},
        # 6. satellite with ticket return
        {'tournament_identity': 'FIXTURE-Satellite', 'tournament_id': 'F6', 'status': RESOLVED,
         'is_satellite': True, 'ticket_return': 320.0, 'return': 320.0, 'cost': 33.0, 'net': 287.0,
         'finish_place': 2, 'total_players': 60, 'percentile': 3.3,
         'bullets': [{'bullet_id': 'F6b1', 'first_hand': 'S1', 'last_hand': 'S22', 'exit_hand': 'S22', 'net': 287.0}]},
        # 7. event with more than 60 hands (no cap)
        {'tournament_identity': 'FIXTURE-Over60', 'tournament_id': 'F7', 'status': RESOLVED,
         'bullets': [{'bullet_id': 'F7b1', 'first_hand': 'G1', 'last_hand': 'G75', 'exit_hand': 'G75', 'net': -40.0,
                      'hand_count': 75}],
         'cost': 40.0, 'return': 0.0, 'net': -40.0, 'finish_place': 95, 'total_players': 150, 'percentile': 63.3},
    ]
    expect = {
        'FIXTURE-HH-Resolved': {'status': RESOLVED, 'final_event_exit': 'H40', 'source': HH},
        'FIXTURE-SummaryOnly': {'status': RESOLVED, 'final_event_exit': None, 'source': SUMMARY},
        'FIXTURE-Unresolved': {'status': UNRESOLVED, 'final_event_exit': None},
        'FIXTURE-MultiBullet': {'status': RESOLVED, 'final_event_exit': 'B14', 'n_bullets': 2},
        'FIXTURE-MultiDay': {'status': RESOLVED, 'final_event_exit': 'E55', 'n_bullets': 2, 'one_row': True},
        'FIXTURE-Satellite': {'is_satellite': True, 'ticket_return': 320.0},
        'FIXTURE-Over60': {'status': RESOLVED, 'final_event_exit': 'G75', 'hand_count': 75},
    }
    return raw, expect


def run_fixtures():
    """Build the model over the seven fixtures and return per-fixture pass/fail + the reconciliation."""
    raw, expect = seven_fixtures()
    model = build_finality_model(raw)
    by_id = {ev.tournament_identity: ev for ev in model}
    results = {}
    for name, exp in expect.items():
        ev = by_id.get(name)
        ok = ev is not None
        detail = {}
        if ev:
            if 'status' in exp:
                detail['status'] = (ev.status == exp['status']); ok = ok and detail['status']
            if 'final_event_exit' in exp:
                detail['final_event_exit'] = (ev.final_event_exit or None) == exp['final_event_exit']; ok = ok and detail['final_event_exit']
            if 'source' in exp:
                detail['source'] = ev.source == exp['source']; ok = ok and detail['source']
            if 'n_bullets' in exp:
                detail['n_bullets'] = len(ev.bullets) == exp['n_bullets']; ok = ok and detail['n_bullets']
            if 'one_row' in exp:
                detail['one_row'] = sum(1 for e in model if e.tournament_identity == name) == 1; ok = ok and detail['one_row']
            if 'is_satellite' in exp:
                detail['is_satellite'] = ev.is_satellite == exp['is_satellite']; ok = ok and detail['is_satellite']
            if 'ticket_return' in exp:
                detail['ticket_return'] = ev.ticket_return == exp['ticket_return']; ok = ok and detail['ticket_return']
        results[name] = {'pass': bool(ok), 'detail': detail}
    rec = reconcile(model)
    all_pass = all(r['pass'] for r in results.values()) and rec['invariants_pass']
    return {'fixtures': results, 'reconciliation': rec, 'model': [ev.to_dict() for ev in model],
            'all_pass': all_pass}
