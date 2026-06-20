#!/usr/bin/env python3
"""
gem_decision_snapshot.py — Canonical decision-time model (v8.17.1 Iteration 1, rev2).

ONE owner of the decision-time facts. Two clearly separated typed concepts:

  DecisionSnapshot  — what Hero knew AT a SPECIFIC action index. Replays the ledger
                      ONLY through state strictly before that action. Reads NO future
                      same-street action, no later all-ins, no later board, no
                      showdown. Two hands identical through that action produce
                      identical DecisionSnapshots (and identical hero_action_kind),
                      regardless of what happens afterwards.

  RealizedContest   — what actually happened after Hero acted: callers, folds, main /
                      side-pot layers, eligible bounties.

The constructor accepts an explicit `hero_action_index` (or a DecisionRef) so a
consumer grading an EARLIER Hero action gets the snapshot for THAT action — it never
silently grades Hero's final action. Every consumer resolves and passes the same ref.

Invariants (per the Iteration-1 acceptance reviews):
  * NO absolute stack threshold for relevance. A short all-in is a full participant;
    it is only a separate side-pot-depth layer.
  * Decision-time REMAINING stacks = starting − ALL chips committed before the action
    (prior streets AND current-street commitments). Effective stack vs an opponent is
    min(hero, opp) of the start-of-decision-street stacks for a preflop all-in (the
    full-stack all-in depth) and of the remaining-before-action stacks postflop (chips
    still behind a faced bet). Scalars are NAMED — no single ambiguous effective_stack.
  * Action kind is future-blind: only ledger actions strictly before the decision
    index, plus the seat state at that moment, decide it. A short all-in CALL never
    increments the raise level.
  * Bounty coverage is per opponent with a typed aggregate; never collapsed.
"""

_BOARD_BY_STREET = {'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}
_ORDER = ('preflop', 'flop', 'turn', 'river')
_EPS = 0.01


# ── primitives ────────────────────────────────────────────────────

def _hero(h):
    return h.get('hero', 'Hero')


def _street_index(street):
    try:
        return _ORDER.index(street)
    except ValueError:
        return 0


def board_at_decision(board, street):
    """Community cards Hero had seen at the decision street (preflop -> [])."""
    return list(board or [])[:_BOARD_BY_STREET.get(street, 0)]


def _starting_stacks(h):
    """Canonical per-player STARTING stacks (bb). Single source: the parser stamps
    seat_stack_by_player (all seats incl. Hero). Falls back to villains + hero."""
    sbp = h.get('seat_stack_by_player')
    out = {}
    if isinstance(sbp, dict) and sbp:
        for p, s in sbp.items():
            try:
                out[p] = float(s)
            except (TypeError, ValueError):
                pass
    if not out:
        for p, d in (h.get('villains') or {}).items():
            v = d.get('stack_bb') if isinstance(d, dict) else d
            if v is not None:
                try:
                    out[p] = float(v)
                except (TypeError, ValueError):
                    pass
        hs = h.get('stack_bb')
        if hs is not None:
            out[_hero(h)] = float(hs)
    return out


def _last_hero_action_street(h):
    """Street of Hero's LAST voluntary (non-post) action — the default reviewed
    decision when no explicit index is supplied. A preflop all-in is always preflop."""
    if h.get('pf_allin'):
        return 'preflop'
    hero = _hero(h)
    st = 'preflop'
    for a in (h.get('action_ledger') or []):
        if a.get('player') == hero and a.get('action') != 'posts':
            st = a.get('street', 'preflop')
    return st


def decision_street(h, hero_action_index=None):
    if hero_action_index is not None:
        ledger = h.get('action_ledger') or []
        if 0 <= hero_action_index < len(ledger):
            return ledger[hero_action_index].get('street', 'preflop')
    return _last_hero_action_street(h)


def _hero_action_index(ledger, hero, street):
    """Index of Hero's reviewed action = his LAST non-post action on `street`."""
    idx = None
    for i, a in enumerate(ledger):
        if a.get('street') == street and a.get('player') == hero and a.get('action') != 'posts':
            idx = i
    return idx


def resolve_decision_ref(h, hero_action_index=None, decision_kind=None, source='default'):
    """Typed reference to exactly one reviewed ledger action. Consumers pass this (or
    the bare index) so every surface grades the SAME action."""
    hero = _hero(h)
    ledger = h.get('action_ledger') or []
    if hero_action_index is None:
        street = _last_hero_action_street(h)
        hero_action_index = _hero_action_index(ledger, hero, street)
    else:
        street = ledger[hero_action_index].get('street', 'preflop') if 0 <= hero_action_index < len(ledger) else 'preflop'
    return {'hand_id': h.get('id', ''), 'hero_action_index': hero_action_index,
            'street': street, 'decision_kind': decision_kind, 'source': source}


def _added(a):
    v = a.get('added_bb')
    if v is None:
        v = a.get('amount_bb', 0) or 0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ── DecisionSnapshot (action-indexed, no future reads) ─────────────

def build_decision_snapshot(h, hero_action_index=None):
    """Action-indexed decision-time snapshot. Replays the ledger ONLY up to (strictly
    before) the reviewed action index. `hero_action_index` defaults to Hero's last
    action; pass it to grade an earlier decision."""
    hero = _hero(h)
    ledger = h.get('action_ledger') or []
    starting = _starting_stacks(h)
    ref = resolve_decision_ref(h, hero_action_index)
    idx = ref['hero_action_index']
    street = ref['street']
    sidx = _street_index(street)
    warnings = []
    if not ledger:
        warnings.append('no_action_ledger')
    if not starting:
        warnings.append('no_starting_stacks')

    stop = idx if idx is not None else len(ledger)
    committed_total, committed_prior, committed_street = {}, {}, {}
    folded_before, all_in_before, acted_street, committed_voluntary = set(), set(), set(), set()
    universe = set(starting.keys())
    faced_aggressor = None
    faced_aggressor_all_in = False
    # typed facts about the bet/raise Hero is facing (the confrontation), captured at
    # the moment it happened so we can separate the aggressor's stack BEFORE the action
    # (the chips at risk) from the ~0 they have left AFTER an all-in (B1/REV2).
    faced_action_index = None
    faced_action_added = 0.0
    faced_aggressor_committed_before_faced = 0.0  # aggressor's commit just before this action
    for i, a in enumerate(ledger):
        p = a.get('player', '')
        if p:
            universe.add(p)
        if i >= stop:
            break
        st = a.get('street', 'preflop')
        add = _added(a)
        committed_total[p] = committed_total.get(p, 0.0) + add
        if st in _ORDER and _street_index(st) < sidx:
            committed_prior[p] = committed_prior.get(p, 0.0) + add
        if st == street:
            committed_street[p] = committed_street.get(p, 0.0) + add
        act = a.get('action', '')
        if act == 'folds':
            folded_before.add(p)
        if a.get('is_all_in'):
            all_in_before.add(p)
        if p != hero and act in ('calls', 'raises', 'bets') or (p != hero and a.get('is_all_in')):
            committed_voluntary.add(p)
        if st == street and p != hero and act in ('raises', 'bets', 'calls', 'checks'):
            acted_street.add(p)
        if st == street and p != hero and act in ('raises', 'bets'):
            faced_aggressor = p
            faced_aggressor_all_in = bool(a.get('is_all_in'))
            faced_action_index = i
            faced_action_added = add
            # commit the aggressor had on THIS street strictly before this action
            faced_aggressor_committed_before_faced = round(
                committed_total.get(p, 0.0) - add, 2)

    def remaining_before(p):
        return round(starting.get(p, 0.0) - committed_total.get(p, 0.0), 2)

    def start_of_street(p):
        return round(starting.get(p, 0.0) - committed_prior.get(p, 0.0), 2)

    # effective-stack baseline: preflop all-in risks the full start-of-street stacks
    # (84990829 -> 17.5); postflop uses the stacks remaining behind a NON-all-in faced
    # bet (F4: villain 60, 3 preflop + 10 flop committed -> 47). REV2 B1 FIX: an
    # ALL-IN player's confrontation depth is the stack they JAMMED (their start-of-street
    # stack), NOT the ~0 they have left after the jam — otherwise a call-vs-jam collapses
    # to ~0.15BB (83526894/84295102/83974506). All-in is detected for the faced
    # aggressor (current street) and any prior all-in.
    use_remaining = (street != 'preflop')

    def eff_basis(p):
        if not use_remaining:
            return start_of_street(p)
        if p in all_in_before:
            return start_of_street(p)
        return remaining_before(p)

    hero_remaining = remaining_before(hero)
    hero_eff_basis = eff_basis(hero)
    pot_before = round(sum(committed_total.values()), 2)
    level_street = max([committed_street.get(p, 0.0) for p in committed_street] or [0.0])
    hero_committed_total = round(committed_total.get(hero, 0.0), 2)
    hero_committed_street = round(committed_street.get(hero, 0.0), 2)
    to_call = round(max(0.0, level_street - hero_committed_street), 2)

    opp_keys = [p for p in universe if p != hero and p not in folded_before]

    def opp_entry(p):
        return {
            'player': p,
            'position': _pos_of(ledger, p),
            'starting_stack_bb': round(starting.get(p, 0.0), 2) if p in starting else None,
            'committed_before_action_bb': round(committed_total.get(p, 0.0), 2),
            'current_street_committed_before_bb': round(committed_street.get(p, 0.0), 2),
            'remaining_before_action_bb': remaining_before(p) if p in starting else None,
            'is_all_in': p in all_in_before,
        }

    players_active = [opp_entry(p) for p in opp_keys]
    players_all_in = [opp_entry(p) for p in opp_keys if p in all_in_before]
    players_folded = sorted(folded_before)
    # yet-to-act = live opponents (full seat universe) who have NOT acted on this
    # street and are not all-in — includes seats with no prior post/action (no-ante).
    players_yet_to_act = [opp_entry(p) for p in opp_keys
                          if p not in acted_street and p not in all_in_before]

    eff_by_opp = {}
    for p in opp_keys:
        if p in starting:
            eff_by_opp[p] = round(min(hero_eff_basis, eff_basis(p)), 2)
    eff_vs_faced = (eff_by_opp.get(faced_aggressor)
                    if faced_aggressor in eff_by_opp else None)
    max_eff_active = (round(min(hero_eff_basis, max(eff_basis(p) for p in opp_keys
                                                    if p in starting)), 2)
                      if any(p in starting for p in opp_keys) else None)

    # ── REV2 typed quantities: keep the four conflated numbers DISTINCT ──
    # The decision-effective stack is the confrontation depth (eff_basis already uses
    # the all-in jammed stack, not the ~0 left behind). callable = what Hero can
    # actually put in (capped by his own stack). to_call = the bet to match.
    fa_evt = ledger[faced_action_index] if faced_action_index is not None else None
    faced_stack_before = (round(starting.get(faced_aggressor, 0.0)
                                - faced_aggressor_committed_before_faced, 2)
                          if faced_aggressor in starting else None)
    faced_remaining_after = (remaining_before(faced_aggressor)
                             if faced_aggressor in starting else None)
    faced_action_kind_ = None
    if fa_evt is not None:
        _fk = fa_evt.get('action', '')
        faced_action_kind_ = ('all_in_' + _fk) if fa_evt.get('is_all_in') else _fk
    eff_at_decision = eff_vs_faced if eff_vs_faced is not None else max_eff_active
    eff_at_start_of_street = None
    if faced_aggressor in starting:
        eff_at_start_of_street = round(min(start_of_street(hero),
                                           start_of_street(faced_aggressor)), 2)
    elif any(p in starting for p in opp_keys):
        eff_at_start_of_street = round(min(start_of_street(hero),
                                           max(start_of_street(p) for p in opp_keys
                                               if p in starting)), 2)
    callable_amount = round(min(to_call, hero_remaining), 2) if to_call else 0.0
    # the total that can actually change hands vs the faced aggressor this confrontation
    eligible_allin_amount = (round(min(eff_at_decision, hero_remaining), 2)
                             if eff_at_decision is not None else None)

    is_bounty = _is_bounty(h)
    cover_by_opp = {}
    if is_bounty:
        for p in opp_keys:
            cover_by_opp[p] = _coverage(starting.get(hero), starting.get(p))

    pot_layers = _pot_layers({p: committed_total.get(p, 0.0)
                              for p in ([hero] + opp_keys)
                              if committed_total.get(p, 0.0) > _EPS})

    return {
        'hand_id': h.get('id', ''),
        'street': street,
        'hero_action_index': idx,
        'hero_action_kind': hero_action_kind(h, idx),
        'board_at_decision': board_at_decision(h.get('board'), street),

        'pot_before_action_bb': pot_before,
        'to_call_bb': to_call,
        'hero_stack_before_action_bb': hero_remaining,
        'hero_committed_before_action_bb': hero_committed_total,
        'hero_current_street_committed_before_bb': hero_committed_street,

        'players_active_before_action': players_active,
        'players_folded_before_action': players_folded,
        'players_all_in_before_action': players_all_in,
        'players_yet_to_act': players_yet_to_act,

        'faced_aggressor': faced_aggressor,
        'faced_aggressor_all_in': faced_aggressor_all_in,
        'faced_action_index': faced_action_index,
        'faced_action_kind': faced_action_kind_,
        'faced_action_added_bb': round(faced_action_added, 2) if faced_aggressor else None,
        'faced_aggressor_stack_before_action_bb': faced_stack_before,
        'faced_aggressor_committed_before_action_bb': (round(faced_aggressor_committed_before_faced, 2)
                                                       if faced_aggressor else None),
        'faced_aggressor_remaining_after_action_bb': faced_remaining_after,
        'hero_stack_before_decision_bb': hero_remaining,
        'hero_committed_before_decision_bb': hero_committed_total,
        'callable_amount_bb': callable_amount,
        'eligible_allin_amount_bb': eligible_allin_amount,
        'effective_stack_at_start_of_street_bb': eff_at_start_of_street,
        'effective_stack_at_decision_bb': eff_at_decision,
        'effective_stack_by_opponent': eff_by_opp,
        'effective_stack_vs_faced_aggressor': eff_vs_faced,
        'max_effective_stack_among_active_opponents': max_eff_active,
        'relevant_opponent_keys': ([faced_aggressor] if faced_aggressor else opp_keys),

        'pot_layers': pot_layers,
        'bounty_coverage_by_opponent': cover_by_opp,

        'source_warnings': warnings,
    }


def _pos_of(ledger, player):
    for a in ledger:
        if a.get('player') == player and a.get('position') not in (None, '?'):
            return a.get('position')
    return '?'


def _is_bounty(h):
    return bool(h.get('format') == 'BOUNTY' or (h.get('bounty_value_bb', 0) or 0) > 0)


_COLLECTIBLE_COVERS = ('collectible', 'collectible_equal_stack')


def _coverage(hero_total, opp_total):
    """Cover relationship for bounty purposes (REV5 B5). EQUAL stacks are COLLECTIBLE
    if Hero wins the all-in outright — the opponent loses all chips and is eliminated,
    so Hero earns the bounty. Equal stacks therefore are NOT non-collectible. Returns:
      collectible              — Hero strictly out-stacks the opponent (strict cover)
      collectible_equal_stack  — exactly equal stacks; collectible on an outright win
      not_collectible          — the opponent out-stacks Hero
      unknown                  — a stack is missing
    A chopped/split pot is an outcome handled separately and does not make the whole
    decision non-collectible."""
    if hero_total is None or opp_total is None:
        return 'unknown'
    if abs(hero_total - opp_total) <= _EPS:
        return 'collectible_equal_stack'
    return 'collectible' if hero_total > opp_total else 'not_collectible'


def _classify_bounty(eligible, in_confront, is_bounty, contested_no_eliminable=False):
    """ONE canonical typed classification of a bounty confrontation -> (aggregate,
    reason). Both consumer fields derive from this SINGLE function so aggregate and
    reason can NEVER contradict (REV3 B2). Truth table (REV5 B5 — equal stacks are
    collectible, never automatically 'none'):

        no all-in confrontation       -> not_applicable / not_applicable_no_allin_confrontation
        all eligible collectible       -> all   / known_all   (strict cover OR equal stacks)
        all eligible not-collectible   -> none  / known_none
        collectible + not-collectible  -> mixed / known_mixed
        unknown stack/eligibility      -> unknown / unknown_missing_stack
    """
    if not is_bounty or not in_confront:
        return ('not_applicable', 'not_applicable_no_allin_confrontation')
    if not eligible:
        # Hero is in an all-in confrontation but no opponent is eliminable in the
        # relevant layer. For the REALIZED view a contested-but-not-eliminable pot
        # (every caller covers Hero) collects nothing -> known_none; for a future-blind
        # decision view with no committed opponent it is N/A.
        if contested_no_eliminable:
            return ('none', 'known_none')
        return ('not_applicable', 'not_applicable_no_allin_confrontation')
    vals = list(eligible.values())
    if any(v == 'unknown' for v in vals):
        return ('unknown', 'unknown_missing_stack')
    has_c = any(v in _COLLECTIBLE_COVERS for v in vals)   # strict cover or equal stacks
    has_n = any(v == 'not_collectible' for v in vals)
    if has_c and has_n:
        return ('mixed', 'known_mixed')
    if has_c:
        return ('all', 'known_all')
    if has_n:
        return ('none', 'known_none')
    return ('unknown', 'unknown_missing_stack')


def _pot_layers(committed_by_player):
    if not committed_by_player:
        return []
    caps = sorted(set(round(v, 2) for v in committed_by_player.values() if v > _EPS))
    layers, prev = [], 0.0
    for cap in caps:
        elig = sorted(p for p, v in committed_by_player.items() if v + _EPS >= cap)
        layers.append({'from_bb': round(prev, 2), 'to_bb': round(cap, 2), 'participants': elig})
        prev = cap
    return layers


def _normalize_uncalled(committed_by_player):
    """REV5 B3: normalize UNCALLED excess out of the contestable pot. The single deepest
    contributor's chips beyond what the next-deepest contributor matched are uncalled and
    RETURNED to that player — an all-in bet nobody matched is not a one-player side pot.
    Only the single deepest overshoot is uncalled (in an all-in pot everyone else is
    all-in or has called). Returns (capped_contributions, uncalled_return_by_player)."""
    contrib = {p: round(v, 2) for p, v in committed_by_player.items() if v > _EPS}
    uncalled = {}
    if len(contrib) >= 2:
        totals = sorted(contrib.values(), reverse=True)
        top, second = totals[0], totals[1]
        if top > second + _EPS:
            tops = [p for p, v in contrib.items() if abs(v - top) <= _EPS]
            if len(tops) == 1:
                p = tops[0]
                uncalled[p] = round(top - second, 2)
                contrib[p] = round(second, 2)
    return contrib, uncalled


def _contest_pot_layers(committed_by_player, folded):
    """Side-pot layering that keeps folded 'dead' money in the pot AMOUNT while
    excluding folded players from winner ELIGIBILITY (REV4 B3/B4).

    Bands are split at every contribution cap, then ADJACENT bands with the SAME
    eligible participant set are MERGED — a new side pot begins ONLY when the eligible
    winner set changes because of an all-in cap. A folded player's smaller dead
    contribution therefore can NOT manufacture a fake `side` layer (the REV3 bug where
    `Folder 2 / Short,Deep,Hero 5` produced main 0-2 + side 2-5 with the SAME eligible
    set). Each layer reports:
      kind                    : 'main' (lowest) | 'side' (eligible set genuinely changed)
      from_bb / to_bb / cap_bb
      eligible_participants    : non-folded players who reached this layer's top
      eligible_contribution_bb : chips in this layer that CAN be won
      dead_money_bb            : folded chips trapped in this layer
      dead_money_by_player     : per-folded-player dead chips in this layer
      total_layer_bb           : eligible_contribution + dead_money
    Sum of total_layer_bb over all layers == total committed pot (incl. dead money).
    """
    contrib = {p: round(v, 2) for p, v in committed_by_player.items() if v > _EPS}
    if not contrib:
        return []
    folded = set(folded or ())
    caps = sorted(set(contrib.values()))
    raw, prev = [], 0.0
    for cap in caps:
        band = round(cap - prev, 2)
        if band <= _EPS:
            prev = cap
            continue
        elig = sorted(p for p, v in contrib.items() if v + _EPS >= cap and p not in folded)
        dead_by = {}
        for p in folded:
            amt = round(min(contrib[p], cap) - prev, 2)
            if amt > _EPS:
                dead_by[p] = amt
        dead = round(sum(dead_by.values()), 2)
        raw.append({'from_bb': round(prev, 2), 'to_bb': round(cap, 2), 'cap_bb': round(cap, 2),
                    'eligible_participants': elig,
                    'eligible_contribution_bb': round(len(elig) * band, 2),
                    'dead_money_bb': dead, 'dead_money_by_player': dead_by,
                    'total_layer_bb': round(len(elig) * band + dead, 2)})
        prev = cap
    if not raw:
        return []
    # MERGE adjacent bands with identical eligible sets (no winner-set change = one pot).
    merged = [raw[0]]
    for L in raw[1:]:
        m = merged[-1]
        if L['eligible_participants'] == m['eligible_participants']:
            m['to_bb'] = L['to_bb']
            m['cap_bb'] = L['cap_bb']
            m['eligible_contribution_bb'] = round(m['eligible_contribution_bb']
                                                  + L['eligible_contribution_bb'], 2)
            m['dead_money_bb'] = round(m['dead_money_bb'] + L['dead_money_bb'], 2)
            for p, a in L['dead_money_by_player'].items():
                m['dead_money_by_player'][p] = round(m['dead_money_by_player'].get(p, 0.0) + a, 2)
            m['total_layer_bb'] = round(m['total_layer_bb'] + L['total_layer_bb'], 2)
        else:
            merged.append(L)
    for i, L in enumerate(merged):
        L['kind'] = 'main' if i == 0 else 'side'
    return merged


# ── action-kind taxonomy (ledger-based, future-blind) ──────────────

def hero_action_kind(h, hero_action_index=None):
    """Full ledger-based taxonomy of Hero's reviewed action — FUTURE-BLIND: only
    ledger entries strictly before the decision index are inspected. Returns:
    first_in_open / open_shove / 3bet / 4bet / 5bet_plus / call / call_vs_jam /
    call_off / rejam_over_live_raise / overjam_with_side_pot / fold / check / unknown.
    """
    hero = _hero(h)
    ledger = h.get('action_ledger') or []
    if hero_action_index is None:
        street = _last_hero_action_street(h)
        idx = _hero_action_index(ledger, hero, street)
    else:
        idx = hero_action_index
        street = ledger[idx].get('street', 'preflop') if 0 <= idx < len(ledger) else 'preflop'
    if idx is None or not (0 <= idx < len(ledger)):
        return 'none'
    evt = ledger[idx]
    act = evt.get('action', '')
    hero_allin = bool(evt.get('is_all_in'))

    prior = [a for i, a in enumerate(ledger)
             if i < idx and a.get('street') == street and a.get('action') != 'posts']
    # raise LEVEL count — only level-setting bets/raises (NOT calls, incl all-in calls)
    n_raises_before = sum(1 for a in prior if a.get('action') in ('raises', 'bets'))
    faced = None
    for a in prior:
        if a.get('player') == hero:
            continue
        if a.get('action') in ('raises', 'bets'):
            faced = a
    faced_allin = bool(faced.get('is_all_in')) if faced else False
    faced_player = faced.get('player') if faced else None

    # FUTURE-BLIND "other live opponent" for the side-pot question: a non-Hero,
    # non-faced player who VOLUNTARILY committed chips strictly BEFORE Hero's action
    # and has not folded by then. Blind-posters / not-yet-acted players do NOT count
    # (no confirmed side-pot contestant), so a later fold/call cannot change the kind.
    folded_before = {a.get('player') for a in prior if a.get('action') == 'folds'}
    other_live = set()
    for a in prior:
        p = a.get('player', '')
        if p == hero or p == faced_player or p in folded_before:
            continue
        if a.get('action') in ('calls', 'raises', 'bets') or a.get('is_all_in'):
            other_live.add(p)
    has_other_live = len(other_live) > 0

    if act == 'folds':
        return 'fold'
    if act == 'checks':
        return 'check'
    if act == 'calls':
        if faced_allin:
            return 'call_vs_jam'
        if hero_allin:
            return 'call_off'
        return 'call'
    if act in ('raises', 'bets'):
        if faced is None:
            return 'open_shove' if hero_allin else 'first_in_open'
        if faced_allin:
            # raising "over" a player already all-in: a side pot forms only if another
            # live opponent (confirmed before Hero acts) can contest it.
            if not has_other_live:
                return 'call_vs_jam'            # functional call-off of the short jam
            return 'overjam_with_side_pot' if hero_allin else '3bet'
        if hero_allin:
            return 'rejam_over_live_raise'
        if n_raises_before == 1:
            return '3bet'
        if n_raises_before == 2:
            return '4bet'
        return '5bet_plus'
    return 'unknown'


# ── RealizedContest (what actually happened after the action) ──────

def build_realized_contest(h, hero_action_index=None):
    hero = _hero(h)
    ledger = h.get('action_ledger') or []
    starting = _starting_stacks(h)
    ref = resolve_decision_ref(h, hero_action_index)
    idx = ref['hero_action_index']
    street = ref['street']

    # REV2 B3: replay PERSISTENT player state across the WHOLE hand — a player who went
    # all-in on an EARLIER street takes no later action but is still a realized
    # participant in the main pot. Reconstruct committed-total + folded + all-in from
    # the full ledger, not just the reviewed street.
    committed_total, folded_anytime, all_in_anytime = {}, set(), set()
    callers_after, folds_after = [], []
    for i, a in enumerate(ledger):
        p = a.get('player', '')
        committed_total[p] = committed_total.get(p, 0.0) + _added(a)
        act = a.get('action', '')
        if act == 'folds':
            folded_anytime.add(p)
        if a.get('is_all_in'):
            all_in_anytime.add(p)
        if a.get('street') == street and p != hero and idx is not None and i > idx:
            if act in ('calls', 'raises', 'bets') or a.get('is_all_in'):
                callers_after.append(p)
            elif act == 'folds':
                folds_after.append(p)
    # realized contesters = opponents who put chips in and never folded (any street),
    # so a prior-street all-in persists. Used only for the realized bounty-eligibility
    # loop below; every PARTICIPANT view is derived from the canonical pot layers.
    contesting = sorted(p for p, v in committed_total.items()
                        if p != hero and v > _EPS and p not in folded_anytime)

    # REV4 B4/B5: the canonical typed pot layers are the ONE participant model. Folded
    # 'dead' money stays in the pot AMOUNT but folded players (INCLUDING a folded Hero)
    # are excluded from every eligible/participant view — they can never be both dead
    # money AND a "contesting participant" (the REV3 self-contradiction). Derive
    # main/side participants, contesting opponents and the realized participant COUNT
    # from the pot layers so a second, independently-calculated participant model can
    # never disagree.
    folded_contributors = {p for p in folded_anytime
                           if committed_total.get(p, 0.0) > _EPS}

    # REV5 B3: normalize UNCALLED excess out of the contestable pot BEFORE building pot
    # layers. The single deepest contributor's chips beyond what the next-deepest player
    # put in are uncalled and RETURNED — an all-in nobody matched is not a one-player
    # side pot. Pot layers are built on the capped (contestable) contributions, so no
    # layer can have a single eligible participant with no dead money.
    all_contrib = {p: v for p, v in committed_total.items() if v > _EPS}
    gross_action_commitments_bb = round(sum(all_contrib.values()), 2)
    capped_contrib, uncalled_return_by_player = _normalize_uncalled(all_contrib)
    uncalled_return_bb = round(sum(uncalled_return_by_player.values()), 2)

    pot_layers = _contest_pot_layers(capped_contrib, folded_contributors)
    eligible_all = sorted(set().union(*[set(l['eligible_participants']) for l in pot_layers])
                          if pot_layers else set())
    main_pot = pot_layers[0]['eligible_participants'] if pot_layers else []
    side_participants = sorted(set().union(
        *[set(l['eligible_participants']) for l in pot_layers if l['kind'] == 'side'])) \
        if any(l['kind'] == 'side' for l in pot_layers) else []
    realized_contesting_opponents = [p for p in eligible_all if p != hero]
    realized_participant_count = len(eligible_all)
    contributing_player_count = sum(1 for v in committed_total.values() if v > _EPS)
    # back-compat eligible-only side-pot layers (folded excluded), for older readers.
    side_pot_layers = _pot_layers({p: capped_contrib.get(p, 0.0) for p in eligible_all
                                   if capped_contrib.get(p, 0.0) > _EPS})

    # dead money = folded contributions that STAYED in the pot (capped, i.e. the folded
    # player's uncalled excess is returned, not dead).
    dead_money_by_player = {p: round(capped_contrib.get(p, 0.0), 2)
                            for p in sorted(folded_contributors)
                            if capped_contrib.get(p, 0.0) > _EPS}
    dead_money_bb = round(sum(dead_money_by_player.values()), 2)
    contestable_pot_bb = round(sum(l['total_layer_bb'] for l in pot_layers), 2)
    total_committed_pot_bb = gross_action_commitments_bb   # gross (all chips committed)

    # REV2 B4 / REV3: realized bounty eligibility — per opponent and ONLY for opponents
    # Hero can ELIMINATE in the realized contest (opponents who are ALL-IN, fully
    # committed). This DECISION-ish field describes who was all-in that Hero covers; the
    # future-blind DECISION-TIME adjustment is owned by build_decision_bounty_context.
    is_bounty = _is_bounty(h)
    eligible = {}
    if is_bounty and hero_in_allin_confrontation(h, idx):
        for p in contesting:
            if p in all_in_anytime:
                eligible[p] = _coverage(starting.get(hero), starting.get(p))

    # REV5 B4: REALIZED bounty CAPABILITY is different from decision-time eligibility. If
    # Hero LATER folded he cannot win any pot layer and so cannot collect ANY bounty —
    # realized eligibility must NOT survive Hero's fold. Only opponents Hero can eliminate
    # in a layer Hero REMAINED eligible to win count as realized-collectible.
    hero_remained_eligible = hero in eligible_all
    hero_eligible_pot_layers = ([i for i, l in enumerate(pot_layers)
                                 if hero in l['eligible_participants']]
                                if hero_remained_eligible else [])
    realized_collectible_bounties = {}
    if hero_remained_eligible:
        for p, cov in eligible.items():
            if any(hero in l['eligible_participants'] and p in l['eligible_participants']
                   for l in pot_layers):
                realized_collectible_bounties[p] = cov

    return {
        'hand_id': h.get('id', ''),
        'street': street,
        'hero_action_index': idx,
        'callers_after_hero_action': callers_after,
        'folds_after_hero_action': folds_after,
        'realized_contesting_opponents': realized_contesting_opponents,
        'realized_participant_count': realized_participant_count,
        'contributing_player_count': contributing_player_count,
        'main_pot_participants': main_pot,
        'side_pot_participants': side_participants,
        'side_pot_layers': side_pot_layers,
        'folded_players': sorted(folded_contributors),
        'gross_action_commitments_bb': gross_action_commitments_bb,
        'contestable_pot_bb': contestable_pot_bb,
        'uncalled_return_bb': uncalled_return_bb,
        'uncalled_return_by_player': uncalled_return_by_player,
        'total_committed_pot_bb': total_committed_pot_bb,
        'dead_money_bb': dead_money_bb,
        'dead_money_by_player': dead_money_by_player,
        'pot_layers': pot_layers,
        'eligible_bounties': eligible,
        # REV5 B4 realized capability (never reuse decision-time eligibility as realized)
        'hero_remained_eligible': hero_remained_eligible,
        'hero_eligible_pot_layers': hero_eligible_pot_layers,
        'realized_collectible_bounties': realized_collectible_bounties,
    }


def hero_in_allin_confrontation(h, hero_action_index=None):
    """Hero is in an all-in bounty confrontation if, AT the reviewed decision, Hero is
    all-in (at or before the reviewed index) OR Hero's reviewed decision FACES an all-in
    (a jam Hero is calling/raising into). REV2 B5 FIX: this is ACTION-INDEXED and
    FUTURE-BLIND — a LATER Hero all-in (e.g. a flop jam after an earlier preflop open)
    must NOT make an earlier decision read as an all-in confrontation. Shared by the
    eligibility gate AND the analyzer's bounty stamping so model and stamp never diverge."""
    hero = _hero(h)
    ledger = h.get('action_ledger') or []
    ref = resolve_decision_ref(h, hero_action_index)
    idx, street = ref['hero_action_index'], ref['street']
    # Hero all-in AT or BEFORE the reviewed action (never a future Hero all-in).
    for i, a in enumerate(ledger):
        if a.get('player') == hero and a.get('is_all_in') and (idx is None or i <= idx):
            return True
    # OR Hero faces an all-in bet/raise strictly before the reviewed action this street.
    fa = False
    for i, a in enumerate(ledger):
        if a.get('street') != street or (idx is not None and i >= idx):
            continue
        if a.get('player') == hero:
            continue
        if a.get('action') in ('raises', 'bets'):
            fa = bool(a.get('is_all_in'))
    return fa


# ── consumer-facing accessors (single canonical source) ────────────

def relevant_opponents(h, hero_action_index=None):
    return build_decision_snapshot(h, hero_action_index).get('players_active_before_action', [])


def contesting_count(h, hero_action_index=None):
    """Participants (incl. Hero) actually contesting the realized pot — short all-ins
    INCLUDED. Folders and pure blind-posters excluded."""
    return build_realized_contest(h, hero_action_index).get('realized_participant_count', 1)


def relevant_effective_stack_bb(h, hero_action_index=None):
    """The effective stack of the confrontation: vs the faced aggressor when Hero
    faces a bet/raise/jam, else the deepest active opponent (capped by Hero)."""
    snap = build_decision_snapshot(h, hero_action_index)
    v = snap.get('effective_stack_vs_faced_aggressor')
    if v is None:
        v = snap.get('max_effective_stack_among_active_opponents')
    if v is None:
        return round(h.get('stack_bb') or 0.0, 2)
    return v


# ── DECISION-TIME bounty context (future-blind owner — REV3 B1/B2/B3) ──

def build_decision_bounty_context(h, hero_action_index=None):
    """The ONE owner of the DECISION-TIME bounty adjustment (REV3 B1).

    FUTURE-BLIND: eligibility uses ONLY opponent all-in state AT or BEFORE the
    reviewed action index. A LATER opponent all-in (e.g. Deep jams the flop after
    Hero's reviewed preflop call) — or a later Hero all-in — can NEVER retroactively
    make a bounty eligible at the earlier decision. Two ledgers identical through the
    reviewed action therefore produce an identical DecisionBountyContext regardless of
    what happens afterwards (prefix invariance).

    SEPARATION OF CONCERNS (REV3 B3): a stack-cover relationship is NOT bounty
    eligibility. `stack_cover_relationship_by_opponent` may name an out-stacked
    opponent (decision-time knowable) while `eligible_bounties_by_opponent` stays empty
    because no opponent is ALL-IN / eliminable in the reviewed confrontation. A normal
    first-in open therefore yields eligible={}, aggregate=not_applicable even though
    Hero covers a shorter villain.

    The typed aggregate AND reason both derive from the single `_classify_bounty`
    function so they can never contradict (REV3 B2). RealizedContest is built
    separately and never overwrites this object.
    """
    hero = _hero(h)
    is_bounty = _is_bounty(h)
    ref = resolve_decision_ref(h, hero_action_index)
    idx = ref['hero_action_index']
    snap = build_decision_snapshot(h, idx)
    starting = _starting_stacks(h)
    in_confront = hero_in_allin_confrontation(h, idx)

    allin_before = {o['player'] for o in snap.get('players_all_in_before_action', [])}
    active = snap.get('players_active_before_action', [])
    faced = snap.get('faced_aggressor')

    cover_rel, eligible = {}, {}
    for o in active:
        p = o['player']
        cov = _coverage(starting.get(hero), starting.get(p))
        if is_bounty:
            cover_rel[p] = cov
        # COMMITTED eligibility only if this opponent is committed ALL-IN at/before the
        # reviewed action AND Hero is in the confrontation. A non-all-in opponent with
        # chips behind is not committed; a future all-in is never visible here.
        if is_bounty and in_confront and p in allin_before:
            eligible[p] = cov

    aggregate, reason = _classify_bounty(eligible, in_confront, is_bounty)

    # REV5 B1: separate EXACT COMMITTED eligibility (opponents already all-in that Hero
    # can eliminate now) from POTENTIAL-IF-CALLED bounty EV. When Hero SHOVES (open-shove
    # / re-jam / overjam / raise-all-in over a non-all-in opener), the live players who
    # can still call are POTENTIAL bounty opponents — their cover relationships are
    # decision-time knowable even though nobody is committed yet. "No committed all-in
    # opponent" is NOT equivalent to "bounty is irrelevant / chip-chart only".
    hero_kind = hero_action_kind(h, idx)
    hero_is_shoving = hero_kind in ('open_shove', 'rejam_over_live_raise', 'overjam_with_side_pot')
    potential = {}
    if is_bounty and hero_is_shoving:
        for o in active:
            p = o['player']
            if p in allin_before or o.get('is_all_in'):
                continue   # committed -> exact eligibility, not potential
            potential[p] = cover_rel.get(p) or _coverage(starting.get(hero), starting.get(p))
    if not is_bounty:
        applicability = 'not_applicable'
    elif eligible:
        applicability = 'exact_committed'
    elif (hero_is_shoving or in_confront) and potential:
        applicability = 'potential_if_called'
    else:
        applicability = 'not_applicable'

    # Relevant villain for the SEPARATE stack-cover relationship (NOT eligibility): the
    # faced all-in aggressor if any, else the deepest active opponent (the one who could
    # cover Hero). This is a cover fact only — it must never be read as collectibility.
    relevant = faced if faced in cover_rel else None
    if relevant is None and cover_rel:
        relevant = max(cover_rel, key=lambda p: (starting.get(p) or 0.0))
    rel_cov = cover_rel.get(relevant) if relevant else None
    cover_relationship_known = rel_cov is not None and rel_cov != 'unknown'
    hero_covers_relevant_by_cover = (rel_cov in _COLLECTIBLE_COVERS) if cover_relationship_known else None

    # REV4 B1: bounty ELIGIBILITY (collectibility) is a DIFFERENT fact from cover.
    # `bounty_eligibility_known` is true only when there is a committed confrontation with
    # a definite verdict (all / none / mixed). `hero_covers_relevant_villain` is
    # eligibility-based and MUST be null when there is no committed eligibility (invariant:
    # coverage_aggregate not_applicable => eligible {} => hero_covers null).
    bounty_eligibility_known = aggregate in ('all', 'none', 'mixed')
    if bounty_eligibility_known:
        hero_covers_relevant_villain = any(v in _COLLECTIBLE_COVERS for v in eligible.values())
    else:
        hero_covers_relevant_villain = None

    return {
        'hand_id': h.get('id', ''),
        'street': ref['street'],
        'hero_action_index': idx,
        'is_bounty': is_bounty,
        'hero_in_allin_confrontation': in_confront,
        'hero_action_kind': hero_kind,
        # REV5 B1: typed applicability — exact_committed / potential_if_called /
        # not_applicable / unknown. The report and auto-clear gate branch on THIS, not
        # on coverage_aggregate, so an open-shove is never called "bounty irrelevant".
        'bounty_applicability': applicability,
        # eligibility (collectibility) — committed all-in opponents Hero can eliminate now
        'eligible_bounties_by_opponent': eligible,
        'committed_allin_bounties_by_opponent': dict(eligible),
        'potential_calling_bounties_by_opponent': potential,
        'coverage_aggregate': aggregate,
        'coverage_reason': reason,
        'aggregate': aggregate,            # back-compat alias
        'reason': reason,                  # back-compat alias
        'coverage_mixed': aggregate == 'mixed',
        'bounty_eligibility_known': bounty_eligibility_known,
        'hero_covers_relevant_villain': hero_covers_relevant_villain,
        # stack-cover relationship — a SEPARATE fact, never eligibility (REV3/REV4 B3)
        'stack_cover_relationship_by_opponent': cover_rel,
        'relevant_villain_key': relevant,
        'cover_relationship_known': cover_relationship_known,
        'hero_cover_relationship_known': cover_relationship_known,   # back-compat alias
        'hero_covers_relevant_villain_by_cover': hero_covers_relevant_by_cover,
        'source_warnings': snap.get('source_warnings', []),
    }


def decision_bounty_aggregate(h, hero_action_index=None):
    """Future-blind decision-time aggregate (worklist/gate-facing)."""
    return build_decision_bounty_context(h, hero_action_index)['aggregate']


def decision_bounty_reason(h, hero_action_index=None):
    """Future-blind decision-time reason — always consistent with the aggregate."""
    return build_decision_bounty_context(h, hero_action_index)['reason']


def decision_eligible_bounties_by_opponent(h, hero_action_index=None):
    """Opponents Hero can ELIMINATE at the reviewed confrontation (committed all-in
    at/before the decision). Never the stack-cover map."""
    return build_decision_bounty_context(h, hero_action_index)['eligible_bounties_by_opponent']


def stack_cover_relationship_by_opponent(h, hero_action_index=None):
    """SEPARATE stack-cover facts (REV3 B3) — cover relationship vs each live
    opponent. This is NOT bounty eligibility and must never be read as such."""
    return build_decision_bounty_context(h, hero_action_index)['stack_cover_relationship_by_opponent']


# ── REALIZED bounty accessors (describe the actual hand; report-facing stamp) ──

def bounty_coverage_by_opponent(h, hero_action_index=None):
    """REALIZED per-opponent eligibility — opponents Hero could ELIMINATE in the
    realized contest (all-in, did not fold). REV3 B3: NO fallback to the stack-cover
    map; when no opponent is eliminable this returns {} (a cover relationship is not
    bounty eligibility)."""
    return dict(build_realized_contest(h, hero_action_index).get('eligible_bounties') or {})


def bounty_aggregate(h, hero_action_index=None):
    """REALIZED typed aggregate: all / none / mixed / unknown / not_applicable.
    Derived from the single `_classify_bounty` truth table so it can never contradict
    `bounty_reason` (REV3 B2)."""
    is_bounty = _is_bounty(h)
    if not is_bounty:
        return 'not_applicable'
    rc = build_realized_contest(h, hero_action_index)
    elig = rc.get('eligible_bounties') or {}
    in_confront = hero_in_allin_confrontation(h, hero_action_index)
    contested = bool(rc.get('realized_contesting_opponents') and in_confront)
    return _classify_bounty(elig, in_confront, is_bounty, contested_no_eliminable=contested)[0]


def bounty_reason(h, hero_action_index=None):
    """REALIZED typed reason — always consistent with `bounty_aggregate` (one
    `_classify_bounty` source). known_all / known_none / known_mixed / equal_boundary /
    not_applicable_no_allin_confrontation / unknown_missing_stack."""
    is_bounty = _is_bounty(h)
    if not is_bounty:
        return 'not_applicable_no_allin_confrontation'
    rc = build_realized_contest(h, hero_action_index)
    elig = rc.get('eligible_bounties') or {}
    in_confront = hero_in_allin_confrontation(h, hero_action_index)
    contested = bool(rc.get('realized_contesting_opponents') and in_confront)
    return _classify_bounty(elig, in_confront, is_bounty, contested_no_eliminable=contested)[1]


def bounty_coverage(h, hero_action_index=None):
    """Back-compat scalar consumed by analyzer/coaching/render:
    all -> collectible | none -> not_collectible | mixed -> mixed |
    unknown -> unknown | not_applicable -> unknown."""
    agg = bounty_aggregate(h, hero_action_index)
    return {'all': 'collectible', 'none': 'not_collectible', 'mixed': 'mixed',
            'unknown': 'unknown', 'not_applicable': 'unknown'}[agg]
