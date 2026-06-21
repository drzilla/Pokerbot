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


def _forced_posts(h, player):
    """REV15 G: INDEPENDENT poker-rule classification of a player's forced posts. The ante is DEAD (a
    pot contribution that does NOT count toward matching a wager or a betting total-to); the SB/BB is
    a LIVE preflop commitment. It reads the TYPED `post_type` (preserved from the raw hand-history
    text by the parser) when present; otherwise it classifies by ORDER + POSITION (a player's LAST
    post at the SB/BB seat is the blind, every earlier post is a dead ante). It does NOT use the
    production maximum-post heuristic, so a short blind BELOW the ante is still typed as the blind."""
    led = h.get('action_ledger') or []
    pos = ''
    for a in led:
        if a.get('player') == player and a.get('position') not in (None, '?'):
            pos = (a.get('position') or '').upper()
            break
    posts = [(i, a) for i, a in enumerate(led)
             if a.get('player') == player and a.get('action') == 'posts']
    ante = sb = bb = 0.0
    for k, (i, a) in enumerate(posts):
        amt = round(_f(a.get('amount_bb', a.get('added_bb', 0)) or 0.0), 2)
        stamped = a.get('post_type')
        if stamped in ('ante', 'small_blind', 'big_blind', 'dead_blind', 'straddle'):
            pt = stamped
        else:                                       # ORDER+POSITION (last post at SB/BB = blind)
            is_last = (k == len(posts) - 1)
            pt = ('small_blind' if (is_last and pos == 'SB')
                  else 'big_blind' if (is_last and pos == 'BB') else 'ante')
        if pt == 'small_blind':
            sb = round(sb + amt, 2)
        elif pt == 'big_blind':
            bb = round(bb + amt, 2)
        else:
            ante = round(ante + amt, 2)
    return {'ante_bb': ante, 'live_blind_bb': round(sb + bb, 2),
            'position': pos, 'total_posts_bb': round(ante + sb + bb, 2)}


def _post_types(h):
    """REV15 G: {ledger_index: post_type} — typed from the parser's raw-text `post_type` when present,
    else order+position (a player's LAST post at the SB/BB seat is the blind). Independent of the
    production normalizer."""
    led = h.get('action_ledger') or []
    by_player = {}
    for i, a in enumerate(led):
        if a.get('action') == 'posts':
            by_player.setdefault(a.get('player', ''), []).append(i)
    out = {}
    for p, idxs in by_player.items():
        pos = ''
        for a in led:
            if a.get('player') == p and a.get('position') not in (None, '?'):
                pos = (a.get('position') or '').upper()
                break
        for k, i in enumerate(idxs):
            stamped = led[i].get('post_type')
            if stamped in ('ante', 'small_blind', 'big_blind', 'dead_blind', 'straddle'):
                out[i] = stamped
            else:
                is_last = (k == len(idxs) - 1)
                out[i] = ('small_blind' if (is_last and pos == 'SB')
                          else 'big_blind' if (is_last and pos == 'BB') else 'ante')
    return out


def oracle_full_replay(h):
    """REV16 §11: the INDEPENDENT full-history physical-chip replay (poker rules). It computes each
    action's physical chips from the LIVE LEVEL it reaches (typed posts + ante-clean to_bb / call
    levels), with the dead ante reducing the stack but NOT live commitment — a SEPARATE implementation
    importing NONE of production's replay, so a production prior-stack bug is caught, not echoed. The
    raw added_bb is never summed for the stack. Returns {ledger_idx: {stack_before_bb, physical_bb}}."""
    led = h.get('action_ledger') or []
    ptypes = _post_types(h)
    stack = {p: _f(v) for p, v in _starting(h).items()}
    out = {}
    cur_street = None
    live = {}
    level = 0.0
    for i, a in enumerate(led):
        p = a.get('player', ''); act = a.get('action', ''); st = a.get('street', 'preflop')
        if st != cur_street:
            cur_street = st; live = {}; level = 0.0
        amt = _f(a.get('amount_bb', 0) or 0.0)
        lb = round(live.get(p, 0.0), 2)
        sb = stack.get(p)
        physical = 0.0
        ai = bool(a.get('is_all_in'))
        if act == 'posts':
            physical = round(amt, 2)
            # REV17 §1.4: the INDEPENDENT oracle mirrors the frozen dead-blind contract — dead_blind is
            # dead (reduces stack, never live), like the ante; only SB/BB/straddle are live.
            if ptypes.get(i) in ('small_blind', 'big_blind', 'straddle'):
                live[p] = round(lb + physical, 2); level = max(level, live[p])
            # else dead ante / dead_blind: reduces stack only
        elif act in ('raises', 'bets'):
            _to = a.get('to_bb')
            target = (round(_f(_to), 2) if (act == 'raises' and _to is not None) else round(level + amt, 2))
            if sb is not None and (ai or (target - lb) >= sb - 0.01):
                physical = round(sb, 2)
            else:
                physical = round(target - lb, 2)
            live[p] = round(lb + physical, 2); level = max(level, live[p])
        elif act == 'calls':
            need = round(max(0.0, level - lb), 2)
            if sb is not None and (ai or need >= sb - 0.01):
                physical = round(sb, 2)
            else:
                physical = round(need, 2)
            live[p] = round(lb + physical, 2)
        out[i] = {'stack_before_bb': (round(sb, 2) if sb is not None else None),
                  'physical_bb': round(physical, 2)}
        if sb is not None:
            stack[p] = round(sb - physical, 2)
    return out


def oracle_replay(h, idx):
    """REV15 G / REV16 §11: the INDEPENDENT commitment + stack replay (poker rules) the QA gates expect
    from. It derives the LIVE bet level from ante-clean amount_bb raise INCREMENTS + typed posts (the
    blind is live, the ante dead) and the stack-before from its OWN full-history physical replay
    (oracle_full_replay — never raw added_bb) — importing NONE of the production replay, so a bug in
    production's prior-stack arithmetic is caught (not echoed). Returns hero_live_before, faced_live
    and the chips Hero adds for the action at idx."""
    led = h.get('action_ledger') or []
    hero = h.get('hero', 'Hero')
    if idx is None or not (0 <= idx < len(led)):
        return {}
    street = led[idx].get('street', 'preflop')
    ptypes = _post_types(h)
    cur_level = 0.0
    live_by = {}
    dead_by = {}
    for j, a in enumerate(led):
        if a.get('street') != street or j >= idx:
            continue
        pj = a.get('player', ''); aj = a.get('action', ''); amtj = _f(a.get('amount_bb', 0) or 0.0)
        if aj == 'posts':
            if ptypes.get(j) in ('small_blind', 'big_blind', 'straddle'):   # REV17 §1.4: dead_blind is dead
                live_by[pj] = round(live_by.get(pj, 0.0) + amtj, 2)
                cur_level = max(cur_level, live_by[pj])
            else:
                dead_by[pj] = round(dead_by.get(pj, 0.0) + amtj, 2)
        elif aj in ('raises', 'bets'):
            _toj = a.get('to_bb')
            cur_level = (round(_f(_toj), 2) if (_toj is not None and aj == 'raises')
                         else round(cur_level + amtj, 2))
            live_by[pj] = cur_level
        elif aj == 'calls':
            live_by[pj] = cur_level
    ident = oracle_identity(h, idx)
    # REV16 §11/B4: the stack-before is from the INDEPENDENT full-history physical replay (never the
    # raw-added identity path the production bug shared) — so the oracle closes to the chip flow.
    _ofr = oracle_full_replay(h)
    stack_before = _ofr.get(idx, {}).get('stack_before_bb')
    if stack_before is None:
        stack_before = ident.get('hero_stack_before_bb')
    became_all_in = bool(ident.get('became_all_in'))
    hero_live_before = round(live_by.get(hero, 0.0), 2)
    faced_live = round(cur_level, 2)
    dead_ante = round(dead_by.get(hero, 0.0), 2)
    sem = ident.get('action_semantics')
    amt = _f(led[idx].get('amount_bb', 0) or 0.0)
    callable_amt = (round(min(max(0.0, faced_live - hero_live_before),
                              stack_before if stack_before is not None else faced_live), 2))
    if became_all_in:
        amount_added = round(stack_before, 2) if stack_before is not None else ident.get('amount_added_bb')
    elif sem in ('call', 'complete'):              # a call / first-in complete adds the callable price
        amount_added = callable_amt
    elif sem in ('open', 'bet', 'three_bet', 'four_bet', 're_jam', 'raise', 'open_shove'):
        # aggressive: the live chips to reach the new bet level — prefer the parser's raise-to.
        _toh = led[idx].get('to_bb')
        _newh = (round(_f(_toh), 2) if (_toh is not None and led[idx].get('action') == 'raises')
                 else round(faced_live + amt, 2))
        amount_added = round(_newh - hero_live_before, 2)
    else:                                          # check / fold
        amount_added = 0.0
    amount_added = round(amount_added, 2)
    live_total = round(hero_live_before + amount_added, 2)
    return {'hero_live_before_bb': hero_live_before, 'faced_live_total_to_bb': faced_live,
            'dead_ante_bb': dead_ante, 'amount_added_bb': amount_added,
            'live_betting_total_to_bb': live_total,
            'pot_contribution_total_bb': round(dead_ante + live_total, 2),
            'stack_after_bb': 0.0 if became_all_in else (round(stack_before - amount_added, 2)
                                                         if stack_before is not None else None),
            'callable_amount_bb': callable_amt, 'became_all_in': became_all_in}


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
    became_all_in = bool(evt.get('is_all_in')) or (
        stack_before is not None and added > _EPS and (stack_before - added) <= _EPS)
    # REV14 G: an all-in EXHAUSTS the remaining stack (poker rule) — stack_after is exactly 0,
    # never an ante-sized residual. A non-all-in action leaves stack_before minus the live amount.
    stack_after = (0.0 if became_all_in
                   else (round(stack_before - added, 2) if stack_before is not None else None))
    # REV14 G: the DEAD ante (preflop only) is excluded from live betting commitment.
    _fp = _forced_posts(h, hero)
    dead_ante = _fp['ante_bb'] if street == 'preflop' else 0.0
    live_committed_street = round(max(0.0, hero_committed_street - dead_ante), 2)
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
        'amount_added_bb': round(added, 2),       # RAW ledger added (ante-contaminated; sizing corrects it)
        'total_to_bb': total_to,
        'hero_stack_before_bb': stack_before,
        'hero_stack_after_bb': stack_after,
        'became_all_in': became_all_in,
        'facing_state': facing,
        'action_semantics': sem,
        'has_voluntary_wager_faced': has_voluntary_wager,
        'to_call_bb': to_call,
        'hero_position': hero_pos,
        'dead_ante_bb': round(dead_ante, 2),
        'live_committed_street_bb': live_committed_street,
    }


def oracle_sizing(h, idx):
    """REV13 E2: the INDEPENDENT sizing oracle for the selected Hero action — amount_added,
    total_to, continue_component, raise_increment, extra_isolation and display_amount_type derived
    straight from the raw ledger, with NO call to build_action_sizing_contract or any production
    row formatter. The action-row parity gate compares the VISIBLE row's label + value to THIS, so
    a row that labels the raise INCREMENT as chips Hero "adds" is caught (the REV12 B1 defect).

    Key identity (independent of production): raise_increment == amount_added - continue_component,
    because faced_total_to == continue_component + hero_street_committed_before and
    total_to == hero_street_committed_before + amount_added."""
    ident = oracle_identity(h, idx)
    if ident.get('no_hero_decision') or ident.get('raw_action') is None:
        return {'amount_added_bb': None, 'total_to_bb': None, 'continue_component_bb': None,
                'raise_increment_bb': None, 'extra_isolation_amount_bb': None,
                'display_amount_type': None, 'action_semantics': ident.get('action_semantics'),
                'became_all_in': bool(ident.get('became_all_in')), 'callable_amount_bb': None,
                'contestable_pot_bb': None, 'required_equity_pct': None, 'hero_stack_after_bb': None,
                'live_betting_total_to_bb': None, 'pot_contribution_total_bb': None}
    led = h.get('action_ledger') or []
    hero = h.get('hero', 'Hero')
    raw_added = ident['amount_added_bb']
    to_call = ident.get('to_call_bb')
    stack_before = ident.get('hero_stack_before_bb')
    sem = ident['action_semantics']
    has_faced = bool(ident.get('has_voluntary_wager_faced'))
    became_all_in = bool(ident.get('became_all_in'))
    live_before = ident.get('live_committed_street_bb') or 0.0
    dead_ante = ident.get('dead_ante_bb') or 0.0
    # REV15 G: the INDEPENDENT commitment replay owns amount_added / live total-to / pot / stack-after
    # (ante-clean amount_bb increments + typed posts) — NEVER the ante-contaminated raw ledger added.
    rp = oracle_replay(h, idx)
    callable_amount = round(rp.get('callable_amount_bb') or 0.0, 2)
    continue_component = callable_amount if (has_faced and callable_amount > _EPS) else None
    amount_added = round(rp.get('amount_added_bb') or 0.0, 2)
    live_total_to = round(rp.get('live_betting_total_to_bb') or 0.0, 2)
    pot_contribution_total = round(rp.get('pot_contribution_total_bb') or 0.0, 2)
    hero_after = rp.get('stack_after_bb')
    # REV14 C2/G: a call/check/fold NEVER has a raise increment; only a bet/raise does.
    if sem in ('call', 'check', 'fold'):
        raise_increment = None
        extra_isolation = None
    elif continue_component is not None and amount_added > continue_component + _EPS:
        raise_increment = round(amount_added - continue_component, 2)
        extra_isolation = raise_increment
    else:
        raise_increment = None
        extra_isolation = None
    # REV14 E/G: independent CONTESTABLE-POT required equity — Hero can only win up to his own stack
    # from each contributor, so cap every player's committed chips at hero_cap; this excludes the
    # uncallable overjam / side-pot chips Hero cannot win (the 83915165 56% vs 37.5% root).
    committed_total = {}
    for i, a in enumerate(led):
        if i >= idx:
            break
        committed_total[a.get('player', '')] = committed_total.get(a.get('player', ''), 0.0) + _added(a)
    hero_committed_total = round(committed_total.get(hero, 0.0), 2)
    hero_cap = round(hero_committed_total + callable_amount, 2)
    contestable_pot = round(sum(min(round(v, 2), hero_cap) for v in committed_total.values()), 2)
    required_equity = None
    if has_faced and callable_amount > _EPS:
        denom = contestable_pot + callable_amount
        required_equity = round(100.0 * callable_amount / denom, 1) if denom > _EPS else None
    if sem in ('open', 'three_bet', 'four_bet', 'open_shove', 're_jam', 'raise'):
        disp = 'total_to'
    elif sem == 'call':
        disp = 'callable_component'
    else:
        disp = 'amount_added'
    return {
        'amount_added_bb': amount_added,
        'total_to_bb': live_total_to,
        'live_betting_total_to_bb': live_total_to,
        'pot_contribution_total_bb': pot_contribution_total,
        'continue_component_bb': continue_component,
        'callable_amount_bb': callable_amount if continue_component is not None else None,
        'raise_increment_bb': raise_increment,
        'extra_isolation_amount_bb': extra_isolation,
        'contestable_pot_bb': contestable_pot,
        'required_equity_pct': required_equity,
        'hero_stack_after_bb': hero_after,
        'display_amount_type': disp,
        'action_semantics': sem,
        'became_all_in': became_all_in,
    }


# Map the oracle's literal action_semantics -> the set of canonical hero_action_kind values that
# are CONSISTENT with it (the canonical is the value under test; this is the independent check).
# REV12 B5: the mapping is STRICT — a first-in 'complete' is ONLY the plain 'call' verb, never an
# overloaded call_vs_jam / call_off kind. The low-level ledger verb cannot serve as the semantic.
_SEM_TO_CANON = {
    'fold': {'fold'},
    'check': {'check'},
    'complete': {'call'},                                # a first-in complete is a plain 'call' verb
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

# REV12 B5/F1: the oracle's TYPED literal semantic -> the canonical NODE families that are
# consistent with it. This is checked IN ADDITION to the kind, so a 'complete' that resolves to a
# call_vs_jam / call_off NODE is rejected (the overloaded family REV11 was meant to eliminate).
_SEM_TO_NODE = {
    'fold': {'fold_first_in', 'fold_over_limp', 'fold_vs_open', 'fold_vs_jam',
             'fold_vs_three_bet', 'postflop_fold'},
    'check': {'check_option', 'postflop_check'},
    'complete': {'first_in_limp', 'sb_complete_after_limp', 'overlimp'},
    'short_all_in': {'first_in_short_all_in'},
    'call': {'call_vs_jam', 'call_vs_open', 'call_vs_three_bet', 'postflop_call', 'first_in_limp'},
    'bet': {'postflop_bet'},
    'open': {'first_in_open'},
    'open_shove': {'first_in_open_shove', 'postflop_jam', 'iso_shove'},
    'three_bet': {'three_bet', 'postflop_raise'},
    'four_bet': {'four_bet', 'postflop_raise'},
    're_jam': {'re_jam', 'postflop_jam'},
    'raise': {'three_bet', 'four_bet', 'postflop_raise', 'iso_raise'},
    'no_hero_decision': {'no_hero_decision'},
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


def node_consistent(oracle_sem, canonical_node):
    """REV12 B5: True when the canonical actual_node_type is consistent with the oracle's TYPED
    literal semantic — a stricter, node-level check than the kind alone (a 'complete' must resolve
    to a first_in_limp / sb_complete node, never call_vs_jam / call_off)."""
    allowed = _SEM_TO_NODE.get(oracle_sem)
    if allowed is None:
        return False
    if not allowed:
        return canonical_node in (None, '', 'unknown')
    return canonical_node in allowed
