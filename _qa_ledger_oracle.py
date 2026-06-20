"""REV11 Part G — INDEPENDENT LEDGER ORACLE.

A QA-only deriver of Hero's literal action identity, facing state and all-in transition
straight from the RAW action ledger + starting stacks + blind/ante values. It does NOT import
or call any production canonical function (canonical_node_type / serialize_reviewed_decision_node
/ reviewed_action_display / build_decision_snapshot / hero_action_kind) — those are the values
UNDER TEST, never the oracle's expected answer. The parity gate (in _qa_parity) compares this
oracle to the canonical ReviewedDecisionView, the serialized worklist node, the visible
reviewed-decision line and the selected Hero action row.
"""

_EPS = 0.011


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _added(a):
    v = a.get('added_bb')
    if v is None:
        v = a.get('amount_bb', 0)
    return _f(v)


def _starting(h):
    sbp = h.get('seat_stack_by_player')
    out = {}
    if isinstance(sbp, dict):
        for p, s in sbp.items():
            out[p] = _f(s)
    return out


def oracle_identity(h, idx):
    """Independently derive Hero's literal action identity at ledger index `idx`. Returns a dict
    with raw_action / street / amount_added_bb / total_to_bb / hero_stack_before_bb /
    hero_stack_after_bb / became_all_in / facing_state / action_semantics — all from the raw
    ledger, with NO canonical-model call."""
    led = h.get('action_ledger') or []
    hero = h.get('hero', 'Hero')
    if idx is None or not (0 <= idx < len(led)):
        # no Hero action at all (a walk) — the oracle reports no decision.
        return {'no_hero_decision': True, 'raw_action': None, 'street': 'preflop',
                'facing_state': 'no_hero_decision', 'action_semantics': 'no_hero_decision',
                'became_all_in': False, 'amount_added_bb': None, 'total_to_bb': None,
                'hero_stack_before_bb': None, 'hero_stack_after_bb': None,
                'has_voluntary_wager_faced': False}
    evt = led[idx]
    street = evt.get('street', 'preflop')
    act = evt.get('action', '')
    added = _added(evt)
    starting = _starting(h)
    hero_start = starting.get(hero)
    # chips Hero committed BEFORE this action (all streets)
    hero_committed_before = sum(_added(a) for i, a in enumerate(led) if i < idx and a.get('player') == hero)
    hero_committed_street = sum(_added(a) for i, a in enumerate(led)
                                if i < idx and a.get('player') == hero and a.get('street') == street)
    stack_before = round(hero_start - hero_committed_before, 2) if hero_start is not None else None
    stack_after = round(stack_before - added, 2) if stack_before is not None else None
    became_all_in = bool(evt.get('is_all_in')) or (
        stack_after is not None and added > _EPS and stack_after <= _EPS)
    total_to = round(hero_committed_street + added, 2)

    # prior VOLUNTARY actions on this street (forced posts excluded)
    prior = [a for i, a in enumerate(led)
             if i < idx and a.get('street') == street and a.get('action') != 'posts']
    raisers = [a for a in prior if a.get('player') != hero and a.get('action') in ('raises', 'bets')]
    limpers = [a for a in prior if a.get('player') != hero and a.get('action') == 'calls']
    faced = raisers[-1] if raisers else None
    faced_allin = bool(faced.get('is_all_in')) if faced else False
    n_raises = len(raisers)

    # the level Hero must match this street (max voluntary + forced street commit among others)
    street_commit = {}
    for a in prior + [a for i, a in enumerate(led)
                      if i < idx and a.get('street') == street and a.get('action') == 'posts']:
        p = a.get('player', '')
        street_commit[p] = street_commit.get(p, 0.0) + _added(a)
    level = max(street_commit.values()) if street_commit else 0.0
    to_call = round(max(0.0, level - hero_committed_street), 2)
    hero_pos = next((a.get('position') for a in led
                     if a.get('player') == hero and a.get('position') not in (None, '?')), '?')

    # ── independent FACING-STATE truth table (forced posts never create a facing action) ──
    if faced is not None:
        if faced_allin:
            facing = 'facing_jam'
        elif n_raises >= 2:
            facing = 'facing_reopen'
        elif street == 'preflop':
            facing = 'facing_open'
        else:
            facing = 'facing_postflop_bet'
    elif street == 'preflop' and limpers:
        facing = 'check_option' if to_call <= _EPS else 'facing_limp'
    elif street == 'preflop':
        facing = 'check_option' if (hero_pos == 'BB' or to_call <= _EPS) else 'first_in'
    else:
        facing = 'check_option'

    has_voluntary_wager = faced is not None

    # ── independent LITERAL ACTION-SEMANTIC truth table ──
    if act == 'folds':
        sem = 'fold'
    elif act == 'checks':
        sem = 'check'
    elif act == 'calls':
        if faced is None and became_all_in:
            sem = 'short_all_in'              # first-in forced all-in (underblind)
        elif faced is None:
            sem = 'complete'                  # first-in complete/limp (no voluntary wager)
        else:
            sem = 'call'                      # a genuine call (incl. call vs jam — still a call)
    elif act == 'bets':
        if became_all_in:
            sem = 'open_shove'                # a first-aggressive lead that is ALL-IN is a shove
        else:
            sem = 'bet' if street != 'preflop' else 'open'
    elif act == 'raises':
        if faced is None:
            sem = 'open_shove' if became_all_in else 'open'
        elif faced_allin:
            sem = 're_jam' if became_all_in else 'three_bet'
        elif became_all_in:
            sem = 're_jam'
        elif n_raises == 1:
            sem = 'three_bet'
        elif n_raises == 2:
            sem = 'four_bet'
        else:
            sem = 'raise'
    else:
        sem = 'unknown'

    return {
        'no_hero_decision': False,
        'raw_action': act,
        'street': street,
        'amount_added_bb': round(added, 2),
        'total_to_bb': total_to,
        'hero_stack_before_bb': stack_before,
        'hero_stack_after_bb': stack_after,
        'became_all_in': became_all_in,
        'facing_state': facing,
        'action_semantics': sem,
        'has_voluntary_wager_faced': has_voluntary_wager,
        'to_call_bb': to_call,
        'hero_position': hero_pos,
    }


# Map the oracle's literal action_semantics -> the set of canonical hero_action_kind values that
# are CONSISTENT with it (the canonical is the value under test; this is the independent check).
_SEM_TO_CANON = {
    'fold': {'fold'},
    'check': {'check'},
    'complete': {'call', 'call_vs_jam', 'call_off'},     # a first-in complete is a 'call' verb
    'short_all_in': {'short_all_in'},
    'call': {'call', 'call_vs_jam', 'call_off'},
    'bet': {'bet'},
    'open': {'first_in_open'},
    'open_shove': {'open_shove'},
    'three_bet': {'3bet'},
    'four_bet': {'4bet', '5bet_plus'},
    're_jam': {'rejam_over_live_raise', 'overjam_with_side_pot'},
    'raise': {'3bet', '4bet', '5bet_plus', 'raise'},
    'no_hero_decision': {'none', 'no_hero_decision'},
    'unknown': set(),
}


def semantic_consistent(oracle_sem, canonical_kind):
    """True when the canonical hero_action_kind is consistent with the oracle's literal semantic."""
    allowed = _SEM_TO_CANON.get(oracle_sem)
    if allowed is None:
        return False
    if not allowed:
        return canonical_kind in (None, '', 'unknown')
    return canonical_kind in allowed
