#!/usr/bin/env python3
"""
gem_decision_snapshot.py — Canonical decision-time snapshot (v8.17.1 Iteration 1).

ONE owner of the decision-time facts that downstream trust surfaces kept deriving
independently (and getting wrong): the board Hero actually saw at the decision, the
players actually CONTESTING the pot (not everyone dealt, not dead-short side pots),
the relevant effective stack, bounty collectibility, and Hero's action kind.

Pure stdlib. Reads ONLY the already-parsed hand dict (action_ledger, villains,
stack_bb, board). It does NOT recompute equity, ranges, or charts, and it does NOT
introduce a second definition of "decision street" — callers pass the canonical
street they already own (e.g. gem_coaching_cards._key_street, the card street), or
default to 'preflop' for the all-in/coverage helpers whose decision is preflop.

Design notes / invariants:
  * A "dead-short all-in" is a villain already all-in for <= DEAD_SHORT_MAX_BB at the
    decision. It forms a trivial side pot; it must NOT define the effective stack and
    must NOT inflate the multiway entrant count. It IS still counted for bounty
    coverage (you do collect a covered short stack's bounty).
  * "Contesting" = a villain who VOLUNTARILY committed chips (call/raise/bet/all-in,
    NOT a blind post) on/before the decision street AND did not fold. Folders and
    pure blind-posters are excluded (kills the "8-way pot" = table-size bug).
  * board_at_decision slices the FINAL board to the number of community cards dealt
    by the decision street — preflop -> [], so no future-board reads.
"""

DEAD_SHORT_MAX_BB = 1.5
_BOARD_BY_STREET = {'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}
_ORDER = ('preflop', 'flop', 'turn', 'river')


def board_at_decision(board, street):
    """The community cards Hero had seen at the decision street.

    preflop -> []   flop -> first 3   turn -> first 4   river -> all 5.
    Guarantees no future-runout cards leak into a preflop/flop decision.
    """
    n = _BOARD_BY_STREET.get(street, 0)
    return list(board or [])[:n]


def _street_index(street):
    try:
        return _ORDER.index(street)
    except ValueError:
        return 0


def relevant_opponents(h, decision_street='preflop'):
    """Villains actually contesting the pot at Hero's decision.

    Walks the action ledger up to and including the decision street. A villain is
    'contesting' if they committed chips voluntarily (calls/raises/bets/all-in) and
    are NOT folded by the decision street. Returns a list of dicts:
        {player, stack_bb, is_all_in, is_dead_short}
    """
    ledger = h.get('action_ledger') or []
    hero = h.get('hero', 'Hero')
    dstop = _street_index(decision_street)

    folded, committed, allin = set(), set(), set()
    for a in ledger:
        st = a.get('street', 'preflop')
        if st in _ORDER and _street_index(st) > dstop:
            break
        p = a.get('player', '')
        if p == hero:
            continue
        act = a.get('action', '')
        if act == 'folds':
            folded.add(p)
        elif act in ('calls', 'raises', 'bets') or a.get('is_all_in'):
            committed.add(p)
            if a.get('is_all_in'):
                allin.add(p)

    vstacks = {}
    for p, d in (h.get('villains') or {}).items():
        vstacks[p] = (d.get('stack_bb') if isinstance(d, dict) else d)

    opps = []
    for p in committed:
        if p in folded:
            continue
        stk = vstacks.get(p)
        opps.append({
            'player': p,
            'stack_bb': stk,
            'is_all_in': p in allin,
            'is_dead_short': bool(p in allin and stk is not None
                                  and stk <= DEAD_SHORT_MAX_BB),
        })
    return opps


def contesting_count(h, decision_street='preflop'):
    """Live contesting entrants INCLUDING Hero, EXCLUDING dead-short side pots.

    This is the number to call a pot 'N-way'. A preflop jam everyone folds to is
    1 (heads-up-or-less); a 0.8BB dead-short all-in alongside one real caller is 2.
    """
    real = [o for o in relevant_opponents(h, decision_street) if not o['is_dead_short']]
    return 1 + len(real)


def relevant_effective_stack_bb(h, decision_street='preflop'):
    """min(hero_stack, largest non-dead-short contesting opponent stack).

    Falls back to Hero's stack when no live contesting opponent has a known stack
    (e.g. a first-in jam that folds out). Excludes dead-short all-ins so a 0.8BB
    side pot can never define the effective stack of a 17BB decision.
    """
    hero_stack = h.get('stack_bb') or 0
    opps = [o for o in relevant_opponents(h, decision_street)
            if not o['is_dead_short'] and o['stack_bb'] is not None]
    if not opps:
        return round(hero_stack, 2)
    biggest = max(o['stack_bb'] for o in opps)
    return round(min(hero_stack, biggest), 2)


def bounty_coverage(h, decision_street='preflop'):
    """Canonical bounty collectibility from the live contesting opponents.

    Independent of WHO jammed (fixes jammer_stack_bb==0 -> false 'unknown' when Hero
    calls a jam, jams first and gets called, or it is multiway):
        'collectible'      Hero strictly covers EVERY live contesting villain
        'not_collectible'  at least one live contesting villain covers Hero (>=)
        'unknown'          no contesting villain stack resolvable
    Caller gates on bounty format + Hero actually being all-in.
    """
    hero_stack = h.get('stack_bb') or 0
    opps = [o for o in relevant_opponents(h, decision_street)
            if o['stack_bb'] is not None]
    if not opps or not hero_stack:
        return 'unknown'
    if any(o['stack_bb'] >= hero_stack for o in opps):
        return 'not_collectible'
    return 'collectible'


def hero_action_kind(h):
    """Hero's preflop action kind from the ledger.

    Returns one of: open / open_shove / 3bet / rejam / call / call_vs_jam /
    fold / check / none.

    KEY FIX (v8.17.1 Iter-1): when Hero 'raises' all-in but the action he faced was
    ALREADY all-in, he cannot apply pressure — there is no live raise to re-jam over,
    so the extra chips are uncalled. That is a call-off vs a (short) jam, NOT a
    'rejam'. Mislabelling it 'rejam' implies fold equity that does not exist.
    """
    hero = h.get('hero', 'Hero')
    pf = [a for a in (h.get('action_ledger') or [])
          if a.get('street') == 'preflop' and a.get('action') != 'posts']
    hero_pos = [i for i, a in enumerate(pf) if a.get('player') == hero]
    if not hero_pos:
        return 'none'
    last_i = hero_pos[-1]
    last = pf[last_i]
    act = last.get('action', '')
    hero_allin = bool(last.get('is_all_in'))

    faced = None
    for a in pf[:last_i]:
        if a.get('player') == hero:
            continue
        if a.get('action') in ('raises', 'bets') or a.get('is_all_in'):
            faced = a

    if act == 'folds':
        return 'fold'
    if act == 'checks':
        return 'check'
    if act == 'calls':
        if faced is not None and faced.get('is_all_in'):
            return 'call_vs_jam'
        return 'call'
    if act in ('raises', 'bets'):
        if faced is None:
            return 'open_shove' if hero_allin else 'open'
        # Hero raised over a villain who is ALREADY all-in -> call-off, not rejam.
        if faced.get('is_all_in'):
            return 'call_vs_jam'
        return 'rejam' if hero_allin else '3bet'
    return act or 'unknown'
