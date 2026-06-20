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

    # REV10 D1: a hand where Hero takes NO voluntary action (a walk in the BB, or a hand Hero
    # is never dealt into) has NO reviewed decision. It must never be rendered as an 'act'
    # decision with a price / bounty / range / verdict. Detected from the ledger alone.
    _hero_voluntary = [a for a in ledger
                       if a.get('player') == hero and a.get('action') != 'posts']
    no_hero_decision = (len(_hero_voluntary) == 0)

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
    # REV8 A1: facing-state counters — voluntary raises/bets and limps (calls) by OTHER
    # players on Hero's street BEFORE Hero's action. Forced posts are excluded so a blind/
    # ante is never mistaken for a voluntary wager Hero faces.
    n_street_raises_before = 0
    n_street_limps_before = 0
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
            n_street_raises_before += 1
            # commit the aggressor had on THIS street strictly before this action
            faced_aggressor_committed_before_faced = round(
                committed_total.get(p, 0.0) - add, 2)
        if st == street and p != hero and act == 'calls':
            n_street_limps_before += 1

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

    # ── REV7 A1: DECISION-TIME PRICE CONTRACT — the chips Hero can actually CALL and WIN ──
    # `to_call` (raw_amount_to_match) is the full wager to match the aggressor; it can exceed
    # Hero's stack and include overjam chips Hero can never win — it must NEVER be Hero's
    # displayed price. `callable_amount` is what Hero can actually commit. The CONTESTABLE pot
    # caps every contributor at Hero's total-if-call (hero_cap), so an opponent's overjam above
    # Hero's stack — and any side-pot layer above Hero — is excluded from required equity.
    hero_cap = round(hero_committed_total + callable_amount, 2)
    # contestable pot BEFORE Hero's call: every player's committed chips capped at hero_cap
    # (folded dead money included up to the cap; the uncallable overjam is excluded).
    contestable_pot_before_action = round(
        sum(min(round(v, 2), hero_cap) for v in committed_total.values()), 2)
    uncallable_overjam = round(max(0.0, to_call - callable_amount), 2)
    # ── REV10 B3: canonical EFFECTIVE DECISION DEPTH — the contestable effective stack for
    # THIS call/fold, GUARANTEED  callable_amount <= depth <= hero_stack_before_action.
    # `effective_stack_at_decision_bb` (REV2) measures the stack BEHIND a non-all-in bet (for
    # multi-street planning) and can fall BELOW the current callable amount (84075480: 2.23
    # behind a 16.06 bet) — that must never be displayed as Hero's decision depth. For an
    # all-in confrontation the depth IS the jammed stack (eff_at_decision, already >= callable);
    # for a non-all-in faced bet it is callable + the aggressor's stack still behind, capped by
    # Hero's stack. For an unbet/first-in/limp spot it falls back to the confrontation depth.
    if faced_aggressor is not None and not faced_aggressor_all_in and faced_remaining_after is not None:
        _depth_base = callable_amount + max(0.0, faced_remaining_after)
    elif eff_at_decision is not None:
        _depth_base = eff_at_decision
    else:
        _depth_base = callable_amount
    canonical_effective_decision_depth = round(
        min(hero_remaining, max(_depth_base, callable_amount)), 2)
    # ── REV8 A1: canonical DECISION-FACING STATE (NOT inferred from to_call_bb > 0) ──
    # A forced big blind makes to_call>0 even when Hero is first-in; pricing a first-in fold
    # as a 'call 1BB' is wrong. Derive the facing state from the VOLUNTARY action before Hero.
    _hkind = hero_action_kind(h, idx)
    _hero_pos = _pos_of(ledger, hero)
    # REV11 B3: whether THIS action puts Hero all-in — derived from Hero's stack AFTER applying
    # the action (the ledger is_all_in flag, or remaining-minus-added <= 0). `all_in_before` is
    # the pre-action set and does NOT include an action that itself jams Hero, so the canonical
    # node type must be told about the post-action all-in (the 84078253 underblind-shove bug).
    _revt = ledger[idx] if (idx is not None and 0 <= idx < len(ledger)) else {}
    _revt_added = _added(_revt) if _revt else 0.0
    became_all_in_on_this_action = bool(_revt.get('is_all_in')) or (
        bool(_revt) and _revt_added > _EPS and (hero_remaining - _revt_added) <= _EPS)
    hero_all_in_through_action = (hero in all_in_before) or became_all_in_on_this_action
    if faced_aggressor is not None:
        if faced_aggressor_all_in:
            facing_state = 'facing_jam'
        elif n_street_raises_before >= 2:
            facing_state = 'facing_reopen'
        elif street == 'preflop':
            facing_state = 'facing_raise'
        else:
            facing_state = 'facing_bet'
    elif street == 'preflop' and n_street_limps_before > 0:
        # limper(s) but NO voluntary raise. If Hero already matches the limp level (to_call==0,
        # e.g. the BB) he can CHECK; otherwise he faces the limp price.
        facing_state = 'check_option' if to_call <= _EPS else 'facing_limp'
    elif street == 'preflop':
        # no voluntary aggression before Hero: a player who already matches the level (BB,
        # to_call==0) has a check option; everyone else is first-in (UTG..BTN unopened, and the
        # SB unopened special case — both a decline-to-open decision, not a priced call).
        facing_state = 'check_option' if (_hero_pos == 'BB' or to_call <= _EPS) else 'first_in'
    else:
        facing_state = 'check_option'       # postflop, first to act, unbet
    # REV10 D1: a no-decision hand has no facing state at all.
    if no_hero_decision:
        facing_state = 'no_hero_decision'
    # price applicability is driven by the FACING STATE, never by to_call>0. Only a CALL/FOLD
    # that FACES a voluntary raise/bet/jam has a call price; a first-in / check-option / over-
    # limps fold faces no voluntary wager (forced posts are not a wager).
    _is_call_decision = _hkind in ('call', 'call_vs_jam', 'call_off', 'fold')
    _faces_wager = facing_state in ('facing_raise', 'facing_bet', 'facing_jam', 'facing_reopen')
    if _is_call_decision and _faces_wager and to_call > _EPS and callable_amount > _EPS:
        _denom = contestable_pot_before_action + callable_amount
        required_equity_pct = round(100.0 * callable_amount / _denom, 1) if _denom > _EPS else None
        price_applicable = True
        price_reason = 'call_or_fold_facing_wager'
    else:
        required_equity_pct = None
        price_applicable = False
        if _hkind == 'short_all_in':
            # REV11 C3: a forced first-in short/underblind all-in — no voluntary wager, no price.
            price_reason = 'first_in_short_all_in_no_wager'
        elif not _is_call_decision:
            price_reason = 'hero_aggressive_action_sets_price'
        elif facing_state == 'first_in':
            price_reason = ('first_in_no_wager_sb' if _hero_pos == 'SB' else 'first_in_no_wager')
        elif facing_state == 'check_option':
            price_reason = 'check_option_no_price'
        elif facing_state == 'facing_limp':
            # REV9 A3: a limp is NOT a voluntary raise, so no call/fold pot-odds are shown —
            # but the cost to overlimp/complete is preserved (overlimp_cost_bb), never erased.
            price_reason = 'limp_strategy_node'
        elif to_call <= _EPS:
            price_reason = 'no_wager_to_call'
        else:
            price_reason = 'no_callable_chips'
    # REV10 D1: a no-decision hand never carries a price/required-equity/reason of any kind.
    if no_hero_decision:
        required_equity_pct = None
        price_applicable = False
        price_reason = 'no_hero_decision'

    is_bounty = _is_bounty(h)
    cover_by_opp = {}
    if is_bounty:
        for p in opp_keys:
            cover_by_opp[p] = _coverage(starting.get(hero), starting.get(p))

    pot_layers = _pot_layers({p: committed_total.get(p, 0.0)
                              for p in ([hero] + opp_keys)
                              if committed_total.get(p, 0.0) > _EPS})

    # REV10 C1 / REV11 B3: the canonical action-node type for THIS reviewed action (one
    # taxonomy). Pass the THROUGH-action all-in state so a first-in action that itself jams Hero
    # below the blind is typed first_in_short_all_in, not a first_in open/limp.
    actual_node_type = canonical_node_type(
        facing_state, _hkind, street, _hero_pos,
        hero_all_in=hero_all_in_through_action, no_hero_decision=no_hero_decision)

    return {
        'hand_id': h.get('id', ''),
        'street': street,
        'hero_action_index': idx,
        'hero_action_kind': _hkind,
        # REV10 D1/C1: typed no-decision flag + canonical node type
        'no_hero_decision': no_hero_decision,
        'actual_node_type': actual_node_type,
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
        # REV11 B3: did THIS action put Hero all-in (post-action), for the underblind-shove node.
        'became_all_in_on_this_action': became_all_in_on_this_action,
        # REV7 A1 / REV11 B4: decision-time price contract (callable/contestable truth). The raw
        # voluntary amount-to-match and the uncallable overjam are populated ONLY when a call/fold
        # price actually applies (Hero faces a VOLUNTARY wager). A forced blind/ante gap must
        # never populate a voluntary-wager field (84078253: BB 1.0 is not a raw wager). The
        # diagnostic to_call_bb stays separate; the voluntary price Hero acted OVER (for an
        # aggressive 3-bet/re-jam) lives in faced_voluntary_price_bb.
        'raw_amount_to_match_bb': (to_call if price_applicable else None),
        'contestable_pot_before_action_bb': (contestable_pot_before_action if price_applicable else None),
        'uncallable_overjam_bb': (uncallable_overjam if price_applicable else None),
        'faced_voluntary_price_bb': (round(to_call, 2) if (faced_aggressor is not None and to_call > _EPS) else None),
        'required_equity_pct': required_equity_pct,
        'price_applicable': price_applicable,
        'price_reason': price_reason,
        # REV8 A1: canonical facing state at the reviewed action (forced posts excluded)
        'decision_facing_state': facing_state,
        'hero_position': _hero_pos,
        # REV9 A3: limp context — the real call/complete option a limp creates is preserved as a
        # typed field even when pot odds are not shown for a fold over a limp.
        'limpers_before_hero': n_street_limps_before,
        'overlimp_cost_bb': (callable_amount if facing_state == 'facing_limp' else None),
        'iso_raise_context': (facing_state == 'facing_limp' and n_street_limps_before > 0),
        'effective_stack_at_start_of_street_bb': eff_at_start_of_street,
        'effective_stack_at_decision_bb': eff_at_decision,
        # REV10 B3: the contract-satisfying visible decision depth (callable <= depth <= hero stack)
        'canonical_effective_decision_depth_bb': canonical_effective_decision_depth,
        'effective_stack_by_opponent': eff_by_opp,
        'effective_stack_vs_faced_aggressor': eff_vs_faced,
        'max_effective_stack_among_active_opponents': max_eff_active,
        'relevant_opponent_keys': ([faced_aggressor] if faced_aggressor else opp_keys),

        'pot_layers': pot_layers,
        'bounty_coverage_by_opponent': cover_by_opp,

        'source_warnings': warnings,
    }


def infer_reviewed_action_index(h):
    """REV6 B2: the ONE canonical reviewed (graded) Hero action index, inferred from the
    LEDGER ALONE so EVERY render path (full / --quick / analyst-rerender) — none of which
    re-runs the worklist — can still route the visible capsule / pot-odds / trust strip
    through the SAME action the worklist graded. Selection mirrors the worklist's
    `_reviewed_action_index`:
      - Hero acted on a POSTFLOP street            -> Hero's LAST action (the postflop call/jam)
      - else Hero went ALL-IN preflop              -> Hero's LAST preflop action (the jam/call-off)
      - else (preflop non-all-in)                  -> Hero's FIRST preflop action (the open/deviation)
    The worklist, when it has the candidate's decision_kind, may pass an explicit index to
    build_reviewed_decision_ref (authoritative); this is the future-blind default."""
    hero = _hero(h)
    led = h.get('action_ledger') or []
    if not led:
        return None
    pf = [i for i, a in enumerate(led)
          if a.get('street') == 'preflop' and a.get('player') == hero and a.get('action') != 'posts']
    allh = [i for i, a in enumerate(led)
            if a.get('player') == hero and a.get('action') != 'posts']
    if not allh:
        return None
    post = [i for i in allh if led[i].get('street') in ('flop', 'turn', 'river')]
    if post:
        return allh[-1]
    if any(led[i].get('is_all_in') for i in pf):
        return pf[-1] if pf else allh[-1]
    return pf[0] if pf else allh[0]


def _g(x):
    """compact bb formatter (no trailing zeros)."""
    try:
        return ('%g' % round(float(x), 2))
    except (TypeError, ValueError):
        return '?'


# ── REV10 C1: ONE canonical action-node taxonomy ───────────────────
# Distinguishes ACTUAL action from FACING state. A first-in SB limp is first_in_limp
# (NEVER call_vs_jam); overlimp / SB-complete / iso-raise / iso-shove are NEVER collapsed
# into one node; a walk where Hero never acts is no_hero_decision.
_POSTFLOP_NODE = {
    'check': 'postflop_check', 'bet': 'postflop_bet', 'first_in_open': 'postflop_bet',
    'call': 'postflop_call', 'call_vs_jam': 'postflop_call', 'call_off': 'postflop_call',
    'fold': 'postflop_fold', 'raise': 'postflop_raise', '3bet': 'postflop_raise',
    '4bet': 'postflop_raise', '5bet_plus': 'postflop_raise',
    'open_shove': 'postflop_jam', 'rejam_over_live_raise': 'postflop_jam',
    'overjam_with_side_pot': 'postflop_jam', 'short_all_in': 'postflop_jam',
}


def canonical_node_type(facing_state, hero_action_kind, street, hero_position,
                        hero_all_in=False, no_hero_decision=False):
    """The ONE preflop/postflop action-node taxonomy (REV10 C1). Pure function of the
    canonical facing state + future-blind hero_action_kind + street/position. Used by the
    snapshot (actual_node_type), the worklist serialization, the range-evidence ownership
    gate and the inventories so every surface agrees on the node by construction."""
    k = hero_action_kind or 'none'
    if no_hero_decision or facing_state == 'no_hero_decision' or k == 'none':
        return 'no_hero_decision'
    # REV11 B3: an all-in upgrade to a JAM applies ONLY to an AGGRESSIVE action (a bet/raise that
    # itself jams Hero). A CALL that happens to put Hero all-in (a call-off) is still a call —
    # never re-typed as a jam/re-jam (83974506 is a call_vs_jam, NOT a postflop_jam/re_jam).
    _aggr = k in ('bet', 'raise', 'first_in_open', '3bet', '4bet', '5bet_plus',
                  'open_shove', 'rejam_over_live_raise', 'overjam_with_side_pot')
    _aggr_jam = hero_all_in and _aggr
    if street != 'preflop':
        if _aggr_jam:
            return 'postflop_jam'
        return _POSTFLOP_NODE.get(k, 'postflop_call')
    # ── preflop ──
    if facing_state == 'check_option':
        return 'check_option'
    if facing_state == 'first_in':
        if k == 'fold':
            return 'fold_first_in'
        # REV11 C3: a first-in action that puts Hero all-in BELOW the big blind (a forced short
        # all-in) is its OWN node — never an ordinary limp/open-shove (84078253).
        if k == 'short_all_in':
            return 'first_in_short_all_in'
        if k == 'open_shove' or _aggr_jam:
            return 'first_in_open_shove'
        if k in ('call', 'call_vs_jam', 'call_off'):
            return 'first_in_limp'                 # SB complete / open-limp first-in
        return 'first_in_open'
    if facing_state == 'facing_limp':
        if k == 'fold':
            return 'fold_over_limp'
        if k == 'open_shove' or _aggr_jam:
            return 'iso_shove'
        if k in ('call', 'call_vs_jam', 'call_off'):
            return 'sb_complete_after_limp' if hero_position == 'SB' else 'overlimp'
        return 'iso_raise'
    if facing_state == 'facing_jam':
        if k == 'fold':
            return 'fold_vs_jam'
        if k in ('open_shove', 'rejam_over_live_raise', 'overjam_with_side_pot') or _aggr_jam:
            return 're_jam'
        return 'call_vs_jam'
    if facing_state == 'facing_reopen':            # a 3-bet (2+ raises) already in front of Hero
        if k == 'fold':
            return 'fold_vs_three_bet'
        if k in ('open_shove', 'rejam_over_live_raise', 'overjam_with_side_pot') or _aggr_jam:
            return 're_jam'
        if k in ('call', 'call_vs_jam', 'call_off'):
            return 'call_vs_three_bet'
        return 'four_bet'
    if facing_state == 'facing_raise':
        if k == 'fold':
            return 'fold_vs_open'
        if k in ('open_shove', 'rejam_over_live_raise', 'overjam_with_side_pot') or _aggr_jam:
            return 're_jam'
        if k in ('call', 'call_vs_jam', 'call_off'):
            return 'call_vs_open'
        return 'three_bet'
    # fallback (facing_bet on preflop should not occur)
    if k == 'fold':
        return 'fold_vs_open'
    if k in ('call', 'call_vs_jam', 'call_off'):
        return 'call_vs_open'
    return 'first_in_open'


def reviewed_action_display(h, hero_action_index, snap=None):
    """REV7 A2: the ONE typed ACTION-DISPLAY for the reviewed action. NEVER renders a
    non-call decision as 'call XBB' (the REV6 bug where folds/checks/bets/opens/jams/re-jams
    all said 'call'). The display verb + text are chosen by the canonical hero_action_kind;
    the amount is the CALLABLE amount for a call, the bet/raise SIZE for aggression, and the
    faced price for a fold. Returns a serialisable dict."""
    led = h.get('action_ledger') or []
    idx = hero_action_index
    evt = led[idx] if (idx is not None and 0 <= idx < len(led)) else {}
    snap = snap if snap is not None else build_decision_snapshot(h, idx)
    actual = evt.get('action', '')
    kind = snap.get('hero_action_kind') or actual
    added = round(_added(evt), 2) if evt else 0.0
    total_to = round((snap.get('hero_current_street_committed_before_bb') or 0.0) + added, 2)
    callable_amt = round(snap.get('callable_amount_bb') or 0.0, 2)
    facing = round(snap.get('to_call_bb') or 0.0, 2)          # raw price faced (fold/raise context)
    faced_added = snap.get('faced_action_added_bb')
    street = snap.get('street')
    _preflop = (street == 'preflop')
    _facing = snap.get('decision_facing_state')
    _faces_wager_disp = _facing in ('facing_raise', 'facing_bet', 'facing_jam', 'facing_reopen')
    hero_pos = snap.get('hero_position')
    n_limp = int(snap.get('limpers_before_hero') or 0)
    # ── REV10 D1: NO Hero decision (a walk / Hero never acted) — render neither an action verb
    # nor a price. The visible consumer suppresses the whole decision lesson. ──
    if snap.get('no_hero_decision') or _facing == 'no_hero_decision':
        return {
            'hero_action_kind': 'no_hero_decision', 'hero_actual_action': actual,
            'facing_action_kind': None, 'facing_price_bb': 0.0,
            'action_added_bb': 0.0, 'action_total_to_bb': 0.0, 'callable_amount_bb': 0.0,
            'faced_action_added_bb': None, 'display_verb': 'no decision',
            'display_text': 'no Hero decision', 'no_hero_decision': True,
        }
    # ── REV11 C3: a first-in action that puts Hero ALL-IN below the big blind is a forced short
    # all-in — never an ordinary limp/complete/call-off (84078253). ──
    if kind == 'short_all_in':
        _amt = added if added > _EPS else (callable_amt if callable_amt > _EPS else facing)
        verb, text = 'all-in', 'all-in for %sBB first-in, short of the big blind' % _g(_amt)
        return {
            'hero_action_kind': kind, 'hero_actual_action': actual,
            'facing_action_kind': None, 'facing_price_bb': 0.0,
            'action_added_bb': added, 'action_total_to_bb': total_to, 'callable_amount_bb': None,
            'faced_action_added_bb': None, 'display_verb': verb, 'display_text': text,
        }
    # ── REV10 C3: a first-in SB complete / open-limp is a LIMP — never 'call XBB' / call_vs_jam.
    if _facing == 'first_in' and (kind in ('call', 'call_vs_jam', 'call_off') or actual == 'calls'):
        _amt = callable_amt if callable_amt > _EPS else facing
        if hero_pos == 'SB':
            verb, text = 'complete', 'complete %sBB first-in' % _g(_amt)
        else:
            verb, text = 'limp', 'limp %sBB first-in' % _g(_amt)
        return {
            'hero_action_kind': kind, 'hero_actual_action': actual,
            'facing_action_kind': snap.get('faced_action_kind'), 'facing_price_bb': facing,
            'action_added_bb': added, 'action_total_to_bb': total_to, 'callable_amount_bb': callable_amt,
            'faced_action_added_bb': faced_added, 'display_verb': verb, 'display_text': text,
        }
    # ── REV9 A2: FACING-LIMP is DISTINCT from first-in — another player has entered the pot.
    # A fold over a limp is 'fold over limp' (never 'fold first-in'); a call is an overlimp /
    # SB complete; a raise is an iso-raise. ──
    if _facing == 'facing_limp':
        _lw = 'limper' if n_limp <= 1 else 'limpers'
        if kind in ('call', 'call_vs_jam', 'call_off') or actual == 'calls':
            if hero_pos == 'SB':
                verb, text = 'complete', 'complete %sBB after %d %s' % (_g(callable_amt), n_limp, _lw)
            else:
                verb, text = 'overlimp', 'overlimp %sBB' % _g(callable_amt)
        elif kind == 'open_shove' or (actual == 'raises' and evt.get('is_all_in')):
            verb, text = 'iso-shove', 'iso-shove %sBB over %d %s' % (_g(total_to), n_limp, _lw)
        elif kind in ('first_in_open', '3bet', '4bet', '5bet_plus') or actual == 'raises':
            verb, text = 'iso-raise', 'iso-raise to %sBB over %d %s' % (_g(total_to), n_limp, _lw)
        elif kind == 'check' or actual == 'checks':
            verb, text = 'check', 'check'
        elif kind == 'fold' or actual == 'folds':
            verb, text = 'fold', ('fold over limp' if n_limp <= 1 else 'fold after %d limpers' % n_limp)
        else:
            verb, text = (actual or 'act'), (actual or 'act')
        return {
            'hero_action_kind': kind, 'hero_actual_action': actual,
            'facing_action_kind': snap.get('faced_action_kind'), 'facing_price_bb': facing,
            'action_added_bb': added, 'action_total_to_bb': total_to, 'callable_amount_bb': callable_amt,
            'faced_action_added_bb': faced_added, 'display_verb': verb, 'display_text': text,
            'limpers_before_hero': n_limp, 'overlimp_cost_bb': snap.get('overlimp_cost_bb'),
        }
    if kind in ('call', 'call_vs_jam', 'call_off'):
        verb, text = 'call', 'call %sBB' % _g(callable_amt)
    elif kind == 'fold':
        # REV8 A3: a FIRST-IN / check-option fold faced NO voluntary wager — never render
        # 'fold facing 1BB' (the forced big blind). It is a decline-to-open decision.
        # REV10 B2: when Hero DOES face a wager, the displayed price is the CALLABLE amount
        # (what Hero could actually call), NEVER the raw wager. If the raw wager exceeds the
        # callable amount, state the raw separately so it can never read as Hero's price.
        if _faces_wager_disp and facing > _EPS:
            _cap = callable_amt if callable_amt > _EPS else facing
            if facing - _cap > _EPS:
                verb, text = 'fold', 'fold facing %sBB callable (villain wagered %sBB)' % (_g(_cap), _g(facing))
            else:
                verb, text = 'fold', 'fold facing %sBB' % _g(_cap)
        else:
            verb, text = 'fold', 'fold first-in'
    elif kind == 'check':
        verb, text = 'check', 'check'
    elif kind == 'first_in_open':
        # preflop first-in = an OPEN (raise-to); postflop first-in = a BET (lead).
        if _preflop:
            verb, text = 'open', 'open to %sBB' % _g(total_to)
        else:
            verb, text = 'bet', 'bet %sBB' % _g(total_to)
    elif kind == 'open_shove':
        verb, text = ('open-shove', 'open-shove %sBB' % _g(total_to)) if _preflop \
            else ('shove', 'shove %sBB' % _g(total_to))
    elif kind == '3bet':
        verb, text = '3-bet', '3-bet to %sBB' % _g(total_to)
    elif kind == '4bet':
        verb, text = '4-bet', '4-bet to %sBB' % _g(total_to)
    elif kind == '5bet_plus':
        verb, text = '5-bet', '5-bet to %sBB' % _g(total_to)
    elif kind == 'rejam_over_live_raise':
        verb, text = 're-jam', ('re-jam %sBB over a %sBB price' % (_g(total_to), _g(facing))
                                if facing > _EPS else 're-jam %sBB' % _g(total_to))
    elif kind == 'overjam_with_side_pot':
        verb, text = 'overjam', ('overjam %sBB over a %sBB price' % (_g(total_to), _g(facing))
                                 if facing > _EPS else 'overjam %sBB' % _g(total_to))
    elif actual == 'bets':
        verb, text = 'bet', 'bet %sBB' % _g(added)
    elif actual == 'raises':
        verb, text = 'raise', 'raise to %sBB' % _g(total_to)
    elif actual == 'calls':
        verb, text = 'call', 'call %sBB' % _g(callable_amt)
    elif actual == 'checks':
        verb, text = 'check', 'check'
    elif actual == 'folds':
        # REV10 B2: callable, never raw (mirror the typed fold branch above).
        _cap = callable_amt if callable_amt > _EPS else facing
        verb, text = 'fold', ('fold facing %sBB' % _g(_cap) if _cap > _EPS else 'fold')
    else:
        verb, text = (actual or 'act'), (actual or 'act')
    return {
        'hero_action_kind': kind,
        'hero_actual_action': actual,
        'facing_action_kind': snap.get('faced_action_kind'),
        'facing_price_bb': facing,
        'action_added_bb': added,
        'action_total_to_bb': total_to,
        'callable_amount_bb': callable_amt,
        'faced_action_added_bb': faced_added,
        'display_verb': verb,
        'display_text': text,
    }


def build_reviewed_decision_ref(h, hero_action_index=None, decision_kind=None,
                                selection_source='analyzer_inferred'):
    """REV6 B2 / REV7 A1-A3: the ONE canonical reviewed-decision reference (a serialisable
    ReviewedDecisionView) every VISIBLE decision-bearing block (capsule, pot-odds, bounty
    trust strip, call amount, required equity, effective depth, range evidence, coaching)
    must route through — so the visible lesson can never grade a different action than the
    worklist, and never shows a price/action Hero cannot actually make.

    REV7 A1: the displayed price is the CALLABLE amount (what Hero can actually commit), the
    required equity uses the CONTESTABLE pot (excludes the uncallable overjam) — NEVER the raw
    to_call. `raw_amount_to_match_bb` is kept for diagnostics only and must never be displayed.
    REV7 A2: `action_display` carries the action-typed verb/text (no generic 'call' template).
    REV7 A4: `selection_source`/`selection_confidence` flag whether this is the worklist's
    authoritative graded action ('worklist_reviewed_action') or a ledger-inferred fallback."""
    idx = hero_action_index if hero_action_index is not None else infer_reviewed_action_index(h)
    snap = build_decision_snapshot(h, idx)
    disp = reviewed_action_display(h, idx, snap)
    # decision-time bounty context AT THIS action index (REV5 B2 / REV7 A5) — never hand-level
    try:
        dbc = build_decision_bounty_context(h, idx)
    except Exception:
        dbc = {}
    src = selection_source or 'analyzer_inferred'
    _no_dec = bool(snap.get('no_hero_decision'))
    # REV10 D1: a walk / no-Hero-action hand is NEITHER authoritative NOR inferred — its
    # selection confidence is 'none' and it can never feed a final decision status.
    if _no_dec:
        confidence = 'none'
    elif src == 'worklist_reviewed_action':
        confidence = 'authoritative'
    else:
        confidence = 'inferred'
    return {
        'hand_id': h.get('id', ''),
        'hero_action_index': snap.get('hero_action_index'),
        'street': snap.get('street'),
        'decision_kind': decision_kind,
        'selection_source': src,
        'selection_confidence': confidence,
        'no_hero_decision': _no_dec,
        'actual_node_type': snap.get('actual_node_type'),
        'hero_action_kind': snap.get('hero_action_kind'),
        # ── REV7 A1 price contract (callable/contestable truth) ──
        'callable_amount_bb': snap.get('callable_amount_bb'),
        'raw_amount_to_match_bb': snap.get('raw_amount_to_match_bb'),
        'contestable_pot_before_action_bb': snap.get('contestable_pot_before_action_bb'),
        'uncallable_overjam_bb': snap.get('uncallable_overjam_bb'),
        'required_eq_pct': snap.get('required_equity_pct'),
        'price_applicable': snap.get('price_applicable'),
        'price_reason': snap.get('price_reason'),
        'decision_facing_state': snap.get('decision_facing_state'),
        'hero_position': snap.get('hero_position'),
        'limpers_before_hero': snap.get('limpers_before_hero'),
        'overlimp_cost_bb': snap.get('overlimp_cost_bb'),
        'eligible_allin_amount_bb': snap.get('eligible_allin_amount_bb'),
        'pot_before_action_bb': snap.get('pot_before_action_bb'),
        'effective_stack_at_decision_bb': snap.get('effective_stack_at_decision_bb'),
        # REV10 B3: the contract-satisfying decision depth (callable <= depth <= hero stack)
        'canonical_effective_decision_depth_bb': snap.get('canonical_effective_decision_depth_bb'),
        # legacy/back-compat: to_call_bb == raw (diagnostic). Consumers must NOT display it.
        'to_call_bb': snap.get('to_call_bb'),
        'faced_aggressor': snap.get('faced_aggressor'),
        'faced_action_kind': snap.get('faced_action_kind'),
        # ── REV7 A2 action display ──
        'action_display': disp,
        'display_text': disp.get('display_text'),
        'display_verb': disp.get('display_verb'),
        # ── REV7 A5 bounty context AT this action index ──
        'bounty_applicability': dbc.get('bounty_applicability'),
        'bounty_certainty': dbc.get('bounty_certainty'),
        'bounty_aggregate': dbc.get('coverage_aggregate'),
        'bounty_reason': dbc.get('coverage_reason'),
        'is_bounty': dbc.get('is_bounty'),
        'hero_in_allin_confrontation': dbc.get('hero_in_allin_confrontation'),
    }


def build_reviewed_decision_view(h, hero_action_index=None, decision_kind=None,
                                 selection_source='analyzer_inferred'):
    """REV7 A3: the ONE typed ReviewedDecisionView object for the selected reviewed action.
    Bundles the serialisable ref (decision_ref + price_contract + action_display + bounty)
    with the live snapshot and full bounty context so EVERY visible consumer reads the SAME
    object at the SAME action index — capsule, decision label, price, pot-odds, required
    equity, effective depth, bounty trust strip, bounty applicability note, range, coaching.
    No visible renderer may independently reconstruct any of these or read a hand-level
    default when a reviewed action is selected."""
    idx = hero_action_index if hero_action_index is not None else infer_reviewed_action_index(h)
    snap = build_decision_snapshot(h, idx)
    ref = build_reviewed_decision_ref(h, idx, decision_kind, selection_source)
    try:
        dbc = build_decision_bounty_context(h, idx)
    except Exception:
        dbc = {}
    return {
        'decision_ref': ref,
        'snapshot': snap,
        'action_display': ref.get('action_display'),
        'price_contract': {
            'callable_amount_bb': ref.get('callable_amount_bb'),
            'raw_amount_to_match_bb': ref.get('raw_amount_to_match_bb'),
            'contestable_pot_before_action_bb': ref.get('contestable_pot_before_action_bb'),
            'uncallable_overjam_bb': ref.get('uncallable_overjam_bb'),
            'required_equity_pct': ref.get('required_eq_pct'),
            'price_applicable': ref.get('price_applicable'),
            'price_reason': ref.get('price_reason'),
        },
        'bounty_context': dbc,
        'street': ref.get('street'),
        'hero_action_index': ref.get('hero_action_index'),
        'hero_action_kind': ref.get('hero_action_kind'),
        'selection_source': ref.get('selection_source'),
        'selection_confidence': ref.get('selection_confidence'),
    }


def serialize_reviewed_decision_node(h, hero_action_index=None, decision_kind=None,
                                     selection_source='analyzer_inferred',
                                     reference_node_type=None, evidence_purpose=None):
    """REV10 A1: the ONE serialization path for the exported analyst-worklist decision node.
    The worklist must NOT independently reconstruct hero action / street / facing state / call
    amount / price applicability / effective depth / bounty context / range node / selection
    authority — every one of those is read from the SAME canonical ReviewedDecisionView the
    report renders, so the worklist (the handoff to analyst review and the future Verdict lane)
    can never carry a parallel legacy decision model (the REV9 B1/B8 defect).

    `reference_node_type` / `evidence_purpose` describe the range chart the report shows for
    this action; the caller supplies them (computed by the SAME range-ownership helper the
    report uses) so the worklist range node equals the visible report range node.

    A non-price action (first-in fold/limp, bet, check, open, open-shove, re-jam, walk) carries
    callable_amount_bb = None and price_applicable = false — never a forced-post/rounding price."""
    idx = hero_action_index if hero_action_index is not None else infer_reviewed_action_index(h)
    snap = build_decision_snapshot(h, idx)
    ref = build_reviewed_decision_ref(h, idx, decision_kind, selection_source)
    disp = ref.get('action_display') or {}
    no_dec = bool(snap.get('no_hero_decision'))
    price_applicable = bool(ref.get('price_applicable'))
    # callable is populated ONLY for a price-bearing call/fold facing a voluntary wager.
    callable_amt = ref.get('callable_amount_bb') if price_applicable else None
    faced = snap.get('faced_aggressor')
    return {
        'hero_action_index': snap.get('hero_action_index'),
        'street': snap.get('street'),
        'decision_kind': decision_kind,

        'hero_action_kind': snap.get('hero_action_kind'),
        'hero_actual_action': disp.get('hero_actual_action'),
        'action_display': disp.get('display_text'),
        'action_display_verb': disp.get('display_verb'),

        'decision_facing_state': snap.get('decision_facing_state'),
        'faced_action_kind': snap.get('faced_action_kind'),
        'faced_player': faced,
        'limpers_before_hero': snap.get('limpers_before_hero'),
        'no_hero_decision': no_dec,

        'price_contract': {
            'price_applicable': price_applicable,
            'price_reason': snap.get('price_reason'),
            'raw_amount_to_match_bb': snap.get('raw_amount_to_match_bb'),
            'callable_amount_bb': callable_amt,
            'contestable_pot_before_action_bb': (snap.get('contestable_pot_before_action_bb')
                                                 if price_applicable else None),
            'uncallable_overjam_bb': snap.get('uncallable_overjam_bb'),
            'required_equity_pct': snap.get('required_equity_pct'),
        },
        'stack_contract': {
            'hero_stack_before_action_bb': snap.get('hero_stack_before_action_bb'),
            'effective_stack_at_start_of_street_bb': snap.get('effective_stack_at_start_of_street_bb'),
            'effective_stack_at_decision_bb': snap.get('canonical_effective_decision_depth_bb'),
            'effective_stack_by_opponent': snap.get('effective_stack_by_opponent'),
        },
        'selection': {
            'source': ref.get('selection_source'),
            'confidence': ref.get('selection_confidence'),
            'authoritative': ref.get('selection_confidence') == 'authoritative',
        },
        'bounty_applicability': ref.get('bounty_applicability'),
        'bounty_certainty': ref.get('bounty_certainty'),

        'actual_node_type': snap.get('actual_node_type'),
        'reference_node_type': reference_node_type,
        'evidence_purpose': evidence_purpose,

        # ── compatibility-only flattened aliases (mechanically derived from the canonical
        # nested object above; NO consumer may recalculate from these) ──
        'hero_action_facing': snap.get('decision_facing_state'),
        'call_amount_bb': callable_amt,
        'effective_bb_vs_relevant_villain': snap.get('canonical_effective_decision_depth_bb'),
        'price_not_applicable': (not price_applicable),
        'price_unavailable': False,   # the canonical contract never yields an 'unavailable' price
        'price_source': ('canonical_reviewed_view' if price_applicable else 'not_applicable'),
        '_compatibility_only': True,
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


def _ledger_uncalled(ledger):
    """REV6 B1: reconstruct the UNCALLED return from the ACTION LEDGER — NOT from final
    contribution totals (which conflate antes / big-blind asymmetry / rounding with a real
    uncalled bet). The LAST voluntary bet/raise whose top portion was not matched by any
    NON-FOLDED opponent is the uncalled bet; only that unmatched amount is returned to that
    aggressor. Forced posts (blinds/antes) and fully-called bets never create a return.
    Returns (uncalled_return_by_player, source_meta).

    Per the aggressor's street: matched = the highest STREET commitment among the other
    non-folded players; uncalled = aggressor's street commitment - matched (if > 0)."""
    last_agg_i = None
    for i, a in enumerate(ledger):
        if a.get('action') in ('raises', 'bets'):
            last_agg_i = i
    if last_agg_i is None:
        return {}, {'uncalled_source_action_index': None, 'uncalled_return_bb': 0.0}
    agg = ledger[last_agg_i]
    agg_player = agg.get('player', '')
    agg_street = agg.get('street', 'preflop')
    street_commit = {}
    for a in ledger:
        if a.get('street') != agg_street:
            continue
        p = a.get('player', '')
        street_commit[p] = street_commit.get(p, 0.0) + _added(a)
    agg_commit = street_commit.get(agg_player, 0.0)
    # matched = the highest STREET commitment among ALL other players (folded OR not):
    # a folded player's chips are dead money that still MATCHES the aggressor's bet up to
    # the level they put in before folding. Only the portion above the deepest other
    # contribution is genuinely uncalled.
    others = [v for p, v in street_commit.items() if p != agg_player]
    matched = max(others) if others else 0.0
    uncalled = round(agg_commit - matched, 2)
    meta = {'uncalled_source_action_index': last_agg_i, 'uncalled_source_street': agg_street,
            'uncalled_source_player': agg_player, 'uncalled_action_added_bb': round(_added(agg), 2),
            'aggressor_street_commit_bb': round(agg_commit, 2),
            'matched_amount_bb': round(matched, 2), 'uncalled_return_bb': max(0.0, uncalled)}
    if uncalled > _EPS:
        return {agg_player: uncalled}, meta
    return {}, meta


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
    # REV6 B1: fold a residual TOP band DOWN into the layer below when it is either
    #   (a) exactly ONE eligible player and no dead money — forced-post / big-blind-ante
    #       asymmetry (voluntary uncalled is removed BEFORE this fn, ledger-derived), or
    #   (b) ZERO eligible players (orphaned dead money above every live player's level —
    #       a folded player's blind/ante that no live player matched).
    # Both are DEAD-ANTE money contestable by the MAIN pot (won by the live winner), NOT a
    # one-player/zero-player side pot. Loop in case several forced posts stack.
    while len(merged) >= 2:
        top = merged[-1]
        ne = len(top['eligible_participants'])
        dead = top.get('dead_money_bb', 0.0) or 0.0
        if ne == 0 or (ne == 1 and dead <= _EPS):
            prev = merged[-2]
            prev['to_bb'] = top['to_bb']
            prev['cap_bb'] = top['cap_bb']
            prev['eligible_contribution_bb'] = round(prev['eligible_contribution_bb']
                                                     + top['eligible_contribution_bb'], 2)
            prev['dead_money_bb'] = round(prev['dead_money_bb'] + top['dead_money_bb'], 2)
            for _p, _a in top['dead_money_by_player'].items():
                prev['dead_money_by_player'][_p] = round(prev['dead_money_by_player'].get(_p, 0.0) + _a, 2)
            prev['total_layer_bb'] = round(prev['total_layer_bb'] + top['total_layer_bb'], 2)
            merged.pop()
        else:
            break
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
            # REV11 B3: a 'calls' that itself puts Hero all-in FIRST-IN (no voluntary wager
            # faced — only forced posts) is a forced short/underblind all-in, NOT a call-off of
            # a prior wager (84078253). A call-off requires a prior voluntary bet/raise.
            return 'short_all_in' if faced is None else 'call_off'
        return 'call'
    if act in ('raises', 'bets'):
        if faced is None:
            # REV11 B1: a POSTFLOP first-aggressive 'bets' is a BET, never a preflop first-in
            # open (84074399 river bet 15.01). A preflop first-in 'raises' is the open.
            if hero_allin:
                return 'open_shove'
            return 'bet' if (street != 'preflop' and act == 'bets') else 'first_in_open'
        if faced_allin:
            # REV11 B1.2: a raise OVER a faced all-in is a re-jam / over-jam — the LITERAL action
            # is a raise and must NEVER be collapsed to 'call_vs_jam' (83915520 Hero jams 12.7
            # over HJ's 8.5 jam is a re-jam, not a call). A genuine side pot forms only when
            # another live opponent already committed; otherwise it is a heads-up re-jam.
            if hero_allin:
                return 'overjam_with_side_pot' if has_other_live else 'rejam_over_live_raise'
            return '3bet'
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

    # REV6 B1: the UNCALLED return is reconstructed from the ACTION LEDGER (the last
    # voluntary bet/raise's unmatched portion) — NOT from contribution-total ranking, which
    # wrongly returned antes / big-blind asymmetry / rounding (83526894, 84611544). Subtract
    # the proven uncalled bet from the aggressor's committed total, then build the pot layers
    # on the contestable (capped) contributions. Forced-post asymmetry that remains is folded
    # into the main pot by _contest_pot_layers (dead-ante money, not a one-player side pot).
    all_contrib = {p: v for p, v in committed_total.items() if v > _EPS}
    gross_action_commitments_bb = round(sum(all_contrib.values()), 2)
    uncalled_return_by_player, uncalled_meta = _ledger_uncalled(ledger)
    uncalled_return_bb = round(sum(uncalled_return_by_player.values()), 2)
    capped_contrib = dict(all_contrib)
    for _p, _amt in uncalled_return_by_player.items():
        capped_contrib[_p] = round(capped_contrib.get(_p, 0.0) - _amt, 2)
        if capped_contrib[_p] <= _EPS:
            capped_contrib.pop(_p, None)

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
        'uncalled_source_action_index': uncalled_meta.get('uncalled_source_action_index'),
        'uncalled_source_street': uncalled_meta.get('uncalled_source_street'),
        'uncalled_source_player': uncalled_meta.get('uncalled_source_player'),
        'uncalled_action_added_bb': uncalled_meta.get('uncalled_action_added_bb'),
        'uncalled_aggressor_street_commit_bb': uncalled_meta.get('aggressor_street_commit_bb'),
        'matched_amount_bb': uncalled_meta.get('matched_amount_bb'),
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
    # REV6 B3: exact-committed and potential-if-called are INDEPENDENT dimensions and can
    # BOTH be true at once — a re-jam over a SHORT all-in (committed, eliminable now) WHILE a
    # live opponent can still call and create a contested bounty (potential). Collapsing them
    # to a mutually-exclusive scalar dropped the potential caller (84990829). The typed
    # applicability now carries exact_and_potential; the two booleans below are the
    # primitive independent facts every consumer can read without re-deriving.
    has_exact = bool(eligible)
    has_potential = bool(potential)
    if not is_bounty:
        applicability = 'not_applicable'
    elif has_exact and has_potential:
        applicability = 'exact_and_potential'
    elif has_exact:
        applicability = 'exact_committed'
    elif (hero_is_shoving or in_confront) and has_potential:
        applicability = 'potential_if_called'
    else:
        applicability = 'not_applicable'

    # REV6 B4: CERTAINTY is a SEPARATE typed dimension from applicability. A committed all-in
    # with a MISSING opponent stack is structurally exact_committed but its collectibility is
    # NOT known (unknown_stack); a potential caller's bounty EV depends on an unmodelled caller
    # distribution (unknown_caller_model); exact_and_potential mixes a known committed bounty
    # with an unmodelled potential one (mixed_known). The auto-clear gate blocks on any
    # material-unknown certainty, so an exact committed all-in with unknown stack/coverage can
    # NEVER auto-clear (the REV5 gap where applicability=exact_committed bypassed the block).
    _all_cov = list(eligible.values()) + list(potential.values())
    if not is_bounty or applicability == 'not_applicable':
        certainty = 'known'
    elif any(v == 'unknown' for v in _all_cov):
        certainty = 'unknown_stack'
    elif applicability == 'exact_committed':
        certainty = 'known'
    elif applicability == 'exact_and_potential':
        certainty = 'mixed_known'
    else:  # potential_if_called
        certainty = 'unknown_caller_model'
    bounty_material_unknown = certainty in ('unknown_stack', 'unknown_caller_model', 'mixed_known')

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
        # REV5 B1 / REV6 B3: typed STRUCTURAL applicability — exact_committed /
        # potential_if_called / exact_and_potential / not_applicable. (The old 'unknown'
        # applicability was unreachable; uncertainty now lives in the SEPARATE
        # bounty_certainty dimension below.) The report and auto-clear gate branch on THIS
        # plus certainty, not on coverage_aggregate, so an open-shove is never "bounty
        # irrelevant" and an unknown-stack committed all-in never auto-clears.
        'bounty_applicability': applicability,
        # REV6 B3: the two INDEPENDENT primitive facts (never collapse them again)
        'has_exact_committed_bounty_opportunity': has_exact,
        'has_potential_calling_bounty_opportunity': has_potential,
        # REV6 B4: certainty is SEPARATE from applicability; auto-clear blocks on a material
        # unknown even when an exact committed opponent also exists.
        'bounty_certainty': certainty,
        'bounty_material_unknown': bounty_material_unknown,
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
