#!/usr/bin/env python3
"""
gem_decision_snapshot.py — Canonical decision-time model (v8.17.1 Iteration 1, rev).

ONE owner of the decision-time facts that trust surfaces kept deriving (and getting
wrong). Two clearly separated typed concepts:

  DecisionSnapshot  — what Hero knew AT his exact action index. Replays the ledger
                      ONLY through the state immediately before Hero's action. Reads
                      NO future same-street action, no later all-ins, no later board
                      cards, no showdown. Two hands identical through Hero's action
                      produce identical DecisionSnapshots regardless of what happens
                      afterwards.

  RealizedContest   — what actually happened after Hero acted: who called, who folded,
                      the main/side-pot layers, and which bounties became eligible.

Design invariants (per the Iteration-1 acceptance review):
  * There is NO absolute stack threshold for "relevance". A short all-in is a full
    participant in the pot, the count, equity, and bounty collectibility; it is only
    a separate *layer* for side-pot-depth questions. Relevance is decided by the
    actual contest LAYER, never by an absolute BB cutoff.
  * Effective stack is per opponent: min(hero remaining at the decision street, that
    opponent's remaining at the decision street). Preflop -> full starting stacks;
    postflop -> stacks remaining after prior-street commitments (replayed from the
    ledger's `added_bb`). Scalars are NAMED for what they represent — no single
    ambiguous `effective_stack_bb`.
  * Bounty coverage is per opponent with a typed aggregate (all / none / mixed /
    unknown / not_applicable). It is never collapsed to not_collectible.

Pure stdlib. Reads only the parsed hand dict.
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


def decision_street(h):
    """The street of Hero's reviewed decision = Hero's LAST voluntary (non-post)
    action. A preflop all-in is always preflop. Matches the card-street convention."""
    if h.get('pf_allin'):
        return 'preflop'
    hero = _hero(h)
    st = 'preflop'
    for a in (h.get('action_ledger') or []):
        if a.get('player') == hero and a.get('action') != 'posts':
            st = a.get('street', 'preflop')
    return st


def _hero_action_index(ledger, hero, street):
    """Index of Hero's reviewed action = his LAST non-post action on `street`."""
    idx = None
    for i, a in enumerate(ledger):
        if a.get('street') == street and a.get('player') == hero and a.get('action') != 'posts':
            idx = i
    return idx


def _added(a):
    """Chips committed by an action (bb). Prefer the exact `added_bb` the parser
    records; fall back to amount_bb for older ledgers."""
    v = a.get('added_bb')
    if v is None:
        v = a.get('amount_bb', 0) or 0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ── DecisionSnapshot (action-indexed, no future reads) ─────────────

def build_decision_snapshot(h):
    """Action-indexed decision-time snapshot. Replays the ledger ONLY up to Hero's
    action index. Returns the canonical typed dict (see module docstring)."""
    hero = _hero(h)
    ledger = h.get('action_ledger') or []
    starting = _starting_stacks(h)
    street = decision_street(h)
    sidx = _street_index(street)
    idx = _hero_action_index(ledger, hero, street)
    warnings = []
    if not ledger:
        warnings.append('no_action_ledger')
    if not starting:
        warnings.append('no_starting_stacks')

    # --- replay strictly BEFORE Hero's action ---
    committed_total = {}            # all chips a player put in before Hero acts (all streets)
    committed_street = {}           # chips on the decision street before Hero acts
    committed_before_street = {}    # chips on streets strictly before the decision street
    folded_before, all_in_before, acted_street = set(), set(), set()
    universe = set()
    faced_aggressor = None          # last opp raise/bet Hero faces on this street
    faced_aggressor_all_in = False  # was that faced raise/bet an all-in jam?
    stop = idx if idx is not None else len(ledger)
    for i, a in enumerate(ledger):
        p = a.get('player', '')
        if p:
            universe.add(p)
        if i >= stop:
            break
        st = a.get('street', 'preflop')
        add = _added(a)
        committed_total[p] = committed_total.get(p, 0.0) + add
        if st == street:
            committed_street[p] = committed_street.get(p, 0.0) + add
        if st in _ORDER and _street_index(st) < sidx:
            committed_before_street[p] = committed_before_street.get(p, 0.0) + add
        act = a.get('action', '')
        if act == 'folds':
            folded_before.add(p)
        if a.get('is_all_in'):
            all_in_before.add(p)
        if st == street and p != hero and act in ('raises', 'bets', 'calls', 'checks'):
            acted_street.add(p)
        # the aggressor Hero faces is the last player to RAISE/BET (set the level) —
        # a short all-in CALL does not set the level Hero faces.
        if st == street and p != hero and act in ('raises', 'bets'):
            faced_aggressor = p
            faced_aggressor_all_in = bool(a.get('is_all_in'))

    def remaining_at_street(p):
        return round(starting.get(p, 0.0) - committed_before_street.get(p, 0.0), 2)

    hero_remaining = remaining_at_street(hero)
    pot_before = round(sum(committed_total.values()), 2)
    level_street = max([committed_street.get(p, 0.0) for p in committed_street] or [0.0])
    hero_committed_total = round(committed_total.get(hero, 0.0), 2)
    hero_committed_street = round(committed_street.get(hero, 0.0), 2)
    to_call = round(max(0.0, level_street - hero_committed_street), 2)
    hero_stack_before = round(starting.get(hero, 0.0) - hero_committed_total, 2)

    # opponents live (not folded) at the decision
    opp_keys = [p for p in universe if p != hero and p not in folded_before]

    def opp_entry(p):
        return {
            'player': p,
            'position': _pos_of(ledger, p),
            'starting_stack_bb': round(starting.get(p, 0.0), 2) if p in starting else None,
            'committed_before_decision_bb': round(committed_total.get(p, 0.0), 2),
            'remaining_at_decision_bb': remaining_at_street(p) if p in starting else None,
            'is_all_in': p in all_in_before,
        }

    players_active = [opp_entry(p) for p in opp_keys]
    players_all_in = [opp_entry(p) for p in opp_keys if p in all_in_before]
    players_folded = sorted(folded_before)
    players_yet_to_act = [opp_entry(p) for p in opp_keys
                          if p not in acted_street and p not in all_in_before]

    # per-opponent effective stack at the decision (named scalars, no ambiguity)
    eff_by_opp = {}
    for p in opp_keys:
        if p in starting:
            eff_by_opp[p] = round(min(hero_remaining, remaining_at_street(p)), 2)
    eff_vs_faced = (eff_by_opp.get(faced_aggressor)
                    if faced_aggressor in eff_by_opp else None)
    max_eff_active = (round(min(hero_remaining, max(remaining_at_street(p) for p in opp_keys
                                                    if p in starting)), 2)
                      if any(p in starting for p in opp_keys) else None)

    # per-opponent bounty coverage (decision-time, total stacks) — supports mixed
    is_bounty = bool(h.get('format') == 'BOUNTY' or (h.get('bounty_value_bb', 0) or 0) > 0)
    cover_by_opp = {}
    if is_bounty:
        for p in opp_keys:
            cover_by_opp[p] = _coverage(starting.get(hero), starting.get(p))

    # decision-time pot layers (caps from committed-before amounts of live players)
    pot_layers = _pot_layers({p: committed_total.get(p, 0.0)
                              for p in ([hero] + opp_keys)
                              if committed_total.get(p, 0.0) > _EPS})

    if faced_aggressor is None and not players_yet_to_act and not players_all_in:
        warnings.append('no_live_opponent_before_action')

    return {
        'hand_id': h.get('id', ''),
        'street': street,
        'hero_action_index': idx,
        'hero_action_kind': hero_action_kind(h),
        'board_at_decision': board_at_decision(h.get('board'), street),

        'pot_before_action_bb': pot_before,
        'to_call_bb': to_call,
        'hero_stack_before_action_bb': hero_stack_before,
        'hero_committed_before_action_bb': hero_committed_total,

        'players_active_before_action': players_active,
        'players_folded_before_action': players_folded,
        'players_all_in_before_action': players_all_in,
        'players_yet_to_act': players_yet_to_act,

        'faced_aggressor': faced_aggressor,
        'faced_aggressor_all_in': faced_aggressor_all_in,
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


def hero_in_allin_confrontation(h):
    """Is Hero in an all-in bounty confrontation at the decision? True if Hero is
    all-in, OR Hero's reviewed decision FACES an all-in (a jam Hero is calling/raising
    into — Hero can still collect a covered jammer's bounty without being all-in).
    A side all-in Hero is NOT matching does not count. ONE predicate shared by the
    realized-contest eligibility gate and the analyzer's bounty stamping."""
    hero = _hero(h)
    ledger = h.get('action_ledger') or []
    if h.get('pf_allin') or any(a.get('player') == hero and a.get('is_all_in') for a in ledger):
        return True
    street = decision_street(h)
    idx = _hero_action_index(ledger, hero, street)
    fa = False
    for i, a in enumerate(ledger):
        if a.get('street') != street or (idx is not None and i >= idx):
            continue
        if a.get('player') == hero:
            continue
        if a.get('action') in ('raises', 'bets'):
            fa = bool(a.get('is_all_in'))
    return fa


def _coverage(hero_total, opp_total):
    """Per-opponent bounty coverage from TOTAL stacks."""
    if hero_total is None or opp_total is None:
        return 'unknown'
    if abs(hero_total - opp_total) <= _EPS:
        return 'equal_stack_boundary'
    return 'collectible' if hero_total > opp_total else 'not_collectible'


def _pot_layers(committed_by_player):
    """Side-pot layer caps from per-player committed amounts. Each layer: the depth
    band [prev_cap, cap] and the players eligible for it. No threshold — every
    distinct commitment, however small, defines a layer."""
    if not committed_by_player:
        return []
    caps = sorted(set(round(v, 2) for v in committed_by_player.values() if v > _EPS))
    layers = []
    prev = 0.0
    for cap in caps:
        elig = sorted(p for p, v in committed_by_player.items() if v + _EPS >= cap)
        layers.append({'from_bb': round(prev, 2), 'to_bb': round(cap, 2),
                       'participants': elig})
        prev = cap
    return layers


# ── RealizedContest (what actually happened after Hero acted) ──────

def build_realized_contest(h):
    """What happened from Hero's action onward: callers, folds, main/side pot layers,
    eligible bounties. May read future actions — that is its job — but it never
    rewrites the DecisionSnapshot."""
    hero = _hero(h)
    ledger = h.get('action_ledger') or []
    starting = _starting_stacks(h)
    street = decision_street(h)
    idx = _hero_action_index(ledger, hero, street)

    # contesting opponents = committed voluntarily on the decision street and did
    # NOT fold on it (folders who bailed to Hero's action are not in the contest).
    committed_street, folded_street = set(), set()
    callers_after, folds_after = [], []
    for i, a in enumerate(ledger):
        if a.get('street') != street:
            continue
        p = a.get('player', '')
        if p == hero:
            continue
        act = a.get('action', '')
        if act in ('calls', 'raises', 'bets') or a.get('is_all_in'):
            committed_street.add(p)
        if act == 'folds':
            folded_street.add(p)
        if idx is not None and i > idx:
            if act in ('calls', 'raises') or a.get('is_all_in'):
                callers_after.append(p)
            elif act == 'folds':
                folds_after.append(p)
    contesting = sorted(committed_street - folded_street)

    # committed totals (full hand) for layer math
    committed_total = {}
    for a in ledger:
        p = a.get('player', '')
        committed_total[p] = committed_total.get(p, 0.0) + _added(a)

    participants = [hero] + contesting
    layers = _pot_layers({p: committed_total.get(p, 0.0) for p in participants
                          if committed_total.get(p, 0.0) > _EPS})
    main_pot = layers[0]['participants'] if layers else participants

    # eligible bounties: per contesting opponent, can Hero collect (cover their total)?
    # A bounty is only IN PLAY when there is an actual all-in confrontation — Hero is
    # all-in, or a contesting opponent is all-in against Hero. A non-all-in multiway pot
    # has no eligible bounty yet (no one can be eliminated this decision).
    is_bounty = bool(h.get('format') == 'BOUNTY' or (h.get('bounty_value_bb', 0) or 0) > 0)
    eligible = {}
    if is_bounty and hero_in_allin_confrontation(h):
        for p in contesting:
            eligible[p] = _coverage(starting.get(hero), starting.get(p))

    return {
        'hand_id': h.get('id', ''),
        'street': street,
        'hero_action_index': idx,
        'callers_after_hero_action': callers_after,
        'folds_after_hero_action': folds_after,
        'realized_contesting_opponents': contesting,
        'realized_participant_count': 1 + len(contesting),
        'main_pot_participants': main_pot,
        'side_pot_layers': layers,
        'eligible_bounties': eligible,
    }


# ── action-kind taxonomy (ledger-based) ────────────────────────────

def hero_action_kind(h):
    """Full ledger-based taxonomy of Hero's reviewed action. Returns one of:
    first_in_open / open_shove / 3bet / 4bet / 5bet_plus / call / call_vs_jam /
    call_off / rejam_over_live_raise / overjam_with_side_pot / fold / check / unknown.
    """
    hero = _hero(h)
    ledger = h.get('action_ledger') or []
    street = decision_street(h)
    idx = _hero_action_index(ledger, hero, street)
    if idx is None:
        return 'none'
    evt = ledger[idx]
    act = evt.get('action', '')
    hero_allin = bool(evt.get('is_all_in'))

    # prior street actions before Hero's reviewed action
    prior = [a for i, a in enumerate(ledger)
             if a.get('street') == street and i < idx and a.get('action') != 'posts']
    n_raises_before = sum(1 for a in prior
                          if a.get('action') in ('raises', 'bets') or a.get('is_all_in'))
    faced = None
    for a in prior:
        if a.get('player') == hero:
            continue
        if a.get('action') in ('raises', 'bets'):   # level-setter, not a short call-all-in
            faced = a
    faced_allin = bool(faced.get('is_all_in')) if faced else False

    # is there another LIVE opponent (not the faced player, not folded, not all-in)
    # who can still respond after Hero acts? (decides call-off vs side-pot overjam)
    folded = set()
    live_others = set()
    for i, a in enumerate(ledger):
        if a.get('street') != street or i >= idx:
            continue
        p = a.get('player', '')
        if a.get('action') == 'folds':
            folded.add(p)
    for i, a in enumerate(ledger):
        if a.get('street') != street:
            continue
        p = a.get('player', '')
        if p == hero or p in folded:
            continue
        if faced is not None and p == faced.get('player'):
            continue
        if a.get('action') in ('calls', 'raises', 'bets') or a.get('is_all_in'):
            live_others.add(p)
    has_other_live = len(live_others) > 0

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
            # raising "over" a player already all-in: the excess is uncalled unless
            # another live opponent can still call it.
            if not has_other_live:
                return 'call_vs_jam'           # functional call-off of the short jam
            return 'overjam_with_side_pot' if hero_allin else '3bet'
        # facing a LIVE (non-all-in) raise
        if hero_allin:
            return 'rejam_over_live_raise'
        if n_raises_before == 1:
            return '3bet'
        if n_raises_before == 2:
            return '4bet'
        return '5bet_plus'
    return 'unknown'


# ── consumer-facing accessors (single canonical source) ────────────

def relevant_opponents(h, street=None):
    """Live opponents contesting at the decision (DecisionSnapshot view). No absolute
    threshold — every live committed opponent is included, short stacks too."""
    return build_decision_snapshot(h).get('players_active_before_action', [])


def contesting_count(h, street=None):
    """Participants (incl. Hero) actually contesting the realized pot — short all-ins
    INCLUDED (they are participants). Used to label a pot N-way. Folders and pure
    blind-posters are excluded."""
    return build_realized_contest(h).get('realized_participant_count', 1)


def relevant_effective_stack_bb(h, street=None):
    """The effective stack of the confrontation: vs the faced aggressor when Hero
    faces a bet/raise/jam, else the deepest active opponent (capped by Hero)."""
    snap = build_decision_snapshot(h)
    v = snap.get('effective_stack_vs_faced_aggressor')
    if v is None:
        v = snap.get('max_effective_stack_among_active_opponents')
    if v is None:
        return round(h.get('stack_bb') or 0.0, 2)
    return v


def bounty_coverage_by_opponent(h):
    """Per-opponent coverage over the REALIZED contesting opponents (who Hero is
    actually all-in against). Falls back to decision-time live opponents if the
    realized contest is empty."""
    rc = build_realized_contest(h)
    elig = rc.get('eligible_bounties') or {}
    if elig:
        return elig
    return build_decision_snapshot(h).get('bounty_coverage_by_opponent', {})


def bounty_aggregate(h):
    """Typed aggregate over per-opponent coverage: all / none / mixed / unknown /
    not_applicable. 'not_applicable' when there is no realized confrontation."""
    is_bounty = bool(h.get('format') == 'BOUNTY' or (h.get('bounty_value_bb', 0) or 0) > 0)
    if not is_bounty:
        return 'not_applicable'
    rc = build_realized_contest(h)
    cover = rc.get('eligible_bounties') or {}
    if not cover:
        return 'not_applicable'          # uncontested — no confrontation
    vals = list(cover.values())
    known = [v for v in vals if v in ('collectible', 'not_collectible', 'equal_stack_boundary')]
    if not known:
        return 'unknown'
    collectible = [v for v in known if v == 'collectible']
    not_coll = [v for v in known if v in ('not_collectible', 'equal_stack_boundary')]
    if collectible and not_coll:
        return 'mixed'
    if collectible:
        return 'all'
    return 'none'


def bounty_coverage(h, street=None):
    """Back-compat scalar consumed by the analyzer/coaching/render: maps the typed
    aggregate onto the stamped bounty_collectible vocabulary.
        all -> collectible | none -> not_collectible | mixed -> mixed
        unknown -> unknown | not_applicable -> unknown (no confrontation)
    """
    agg = bounty_aggregate(h)
    return {'all': 'collectible', 'none': 'not_collectible', 'mixed': 'mixed',
            'unknown': 'unknown', 'not_applicable': 'unknown'}[agg]
