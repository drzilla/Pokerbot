"""EAI all-in equity engine (B238, v7.99.22).

Computes TRUE multiway all-in equity for each EAI showdown and uses it to
derive the ahead / flip / behind category and suckout direction.

Why this exists
---------------
The legacy EAI categoriser (gem_analyzer, preflop hand-type heuristics +
postflop made-hand rank) had two systematic failures Ron flagged in the
2026-05-25 review:

  * Draw-vs-made-hand all-ins were bucketed by made-hand rank. Hero 35s
    on A-4-6 (15-out flush+OESD wrap) vs AcTc top pair is a ~57% EQUITY
    favourite but a made-hand underdog, so it was wrongly tagged a
    'behind' all-in and surfaced as a positive cooler / suckout.
  * Multiway all-ins were categorised against ONE villain only. JJ vs
    {AJ, A3} is a 70% field favourite, but JJ-vs-AJ alone fell through
    the heuristic to 'flip', so JJ losing was not recognised as a
    suckout against Hero.

This module replaces the heuristic with real equity: exact enumeration
when the runout space is small (all postflop spots), fixed-seed Monte
Carlo otherwise (preflop). Deterministic — same inputs, same number.

Category is bucketed by Hero's equity RELATIVE TO FAIR SHARE (1/n), so a
4-way pot where Hero holds 38% (fair share 25%) still reads 'ahead'
because Hero is the field favourite. `is_favorite` is the multiway-correct
"Hero has the highest equity" flag that drives suckout direction.
"""

from itertools import combinations

try:
    from phevaluator import evaluate_cards as _eval7
    from phevaluator.card import Card as _Card
    try:
        from phevaluator.evaluator import _evaluate_cards as _eval7_id
    except Exception:
        _eval7_id = None
    _HAVE_PHE = True
except Exception:  # pragma: no cover - environment without phevaluator
    _HAVE_PHE = False
    _eval7_id = None
    _Card = None


def _can_use_eval7_id():
    if _eval7_id is None or _Card is None:
        return False
    try:
        cards = ['As','Ks','Qs','Js','Ts','2c','3d']
        ids = [_Card.to_id(c) for c in cards]
        return _eval7(*cards) == _eval7_id(*ids)
    except Exception:
        return False

_USE_ID_PATH = _can_use_eval7_id()

_RANKS = '23456789TJQKA'
_SUITS = 'cdhs'
_DECK = [r + s for r in _RANKS for s in _SUITS]

# Exact enumeration when the number of runouts is at or below this; above
# it, fall back to fixed-seed Monte Carlo. Postflop (need <= 2) is always
# exact (<= 990 boards); only preflop (need == 5) uses Monte Carlo.
_ENUM_CAP = 250_000

# MC sample count — env-overridable for large batches.
# At 20K, non-borderline ahead/flip/behind classifications are expected
# to remain stable inside B238 tolerance bands. Fixed per-tag seed keeps
# results deterministic. Raise via GEM_EAI_MC_SAMPLES=120000 for precision runs.
import os as _os
_MC_SAMPLES = int(_os.environ.get('GEM_EAI_MC_SAMPLES', '20000'))

# Category thresholds — Hero equity as a multiple of fair share (1/n).
_AHEAD_RATIO = 1.30   # >= 30% above fair share -> clear field favourite
_BEHIND_RATIO = 0.75  # <= 25% below fair share -> clear underdog
# Suckout floors (absolute equity) so a lost/won coin-flip is not a suckout.
_SUCKOUT_FAV_FLOOR = 0.60    # Hero must be a >= 60% favourite for a loss to be a suckout
_SUCKOUT_DOG_CEIL = 0.40     # Hero must be a <= 40% underdog for a win to be a suckout


def available():
    """True when phevaluator is importable and equity can be computed."""
    return _HAVE_PHE


def _seed_for(tag):
    """Deterministic per-hand RNG seed so Monte-Carlo results are stable."""
    h = 2166136261
    for ch in str(tag):
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h or 1


def equity(hero, villains, board, tag=''):
    """Compute all-in equity for Hero vs one or more villains.

    Parameters
    ----------
    hero      : list[str]  -- Hero hole cards, e.g. ['3d', '5d']
    villains  : list[list[str]] -- each villain's hole cards
    board     : list[str]  -- community cards already out (0-5)
    tag       : str        -- hand id, used to seed Monte Carlo deterministically

    Returns
    -------
    dict or None (None when phevaluator unavailable or inputs malformed):
      hero_equity   : float  -- P(Hero wins/chops-share) in 0..1
      opp_equity    : list[float]
      is_favorite   : bool   -- Hero has the highest equity of the field
      n_players     : int
      fair_share    : float  -- 1 / n_players
      category      : 'ahead' | 'flip' | 'behind'
      method        : 'exact' | 'mc'
      samples       : int
    """
    if not _HAVE_PHE:
        return None
    hero = [c.strip() for c in hero if c and c.strip()]
    villains = [[c.strip() for c in v if c and c.strip()] for v in villains]
    villains = [v for v in villains if len(v) == 2]
    board = [c.strip() for c in board if c and c.strip()]
    if len(hero) != 2 or not villains:
        return None

    known = set(hero) + set() if False else set(hero)
    for v in villains:
        known |= set(v)
    known |= set(board)
    # Malformed / duplicate cards -> bail rather than emit a wrong number.
    if len(known) != 2 + 2 * len(villains) + len(board):
        return None
    remaining = [c for c in _DECK if c not in known]
    need = 5 - len(board)
    if need < 0:
        return None

    if _USE_ID_PATH:
        _to_id = _Card.to_id
        hero_id = [_to_id(c) for c in hero]
        vill_id = [[_to_id(c) for c in v] for v in villains]
        board_id = [_to_id(c) for c in board]
        remaining_id = [_to_id(c) for c in remaining]
        _evaluator = _eval7_id
    else:
        hero_id, vill_id, board_id, remaining_id = hero, villains, board, remaining
        _evaluator = _eval7

    n_players = 1 + len(villains)
    share = [0.0] * n_players

    def _score_runout(extra):
        full = board_id + list(extra)
        ev = [_evaluator(*hero_id, *full)]
        for v in vill_id:
            ev.append(_evaluator(*v, *full))
        best = min(ev)  # phevaluator: lower rank == stronger hand
        winners = [i for i, e in enumerate(ev) if e == best]
        w = 1.0 / len(winners)
        for i in winners:
            share[i] += w

    # Count the runout space.
    def _n_combos(nn, kk):
        if kk < 0 or kk > nn:
            return 0
        r = 1
        for i in range(kk):
            r = r * (nn - i) // (i + 1)
        return r

    total = _n_combos(len(remaining), need)
    if total == 0:
        # River all-in: board complete, single deterministic showdown.
        _score_runout([])
        n_runouts = 1
        method, samples = 'exact', 1
    elif total <= _ENUM_CAP:
        for combo in combinations(remaining_id, need):
            _score_runout(combo)
        n_runouts = total
        method, samples = 'exact', total
    else:
        import random
        rng = random.Random(_seed_for(tag))
        for _ in range(_MC_SAMPLES):
            _score_runout(rng.sample(remaining_id, need))
        n_runouts = _MC_SAMPLES
        method, samples = 'mc', _MC_SAMPLES

    eqs = [s / n_runouts for s in share]
    hero_eq = eqs[0]
    opp_eq = eqs[1:]
    fair = 1.0 / n_players
    # Favourite = Hero's equity is the maximum of the field (small epsilon
    # so a numerical tie still counts Hero as co-favourite).
    is_fav = hero_eq >= (max(opp_eq) - 1e-9)
    ratio = hero_eq / fair if fair else 1.0
    if ratio >= _AHEAD_RATIO:
        category = 'ahead'
    elif ratio <= _BEHIND_RATIO:
        category = 'behind'
    else:
        category = 'flip'

    return {
        'hero_equity': round(hero_eq, 4),
        'opp_equity': [round(x, 4) for x in opp_eq],
        'is_favorite': bool(is_fav),
        'n_players': n_players,
        'fair_share': round(fair, 4),
        'category': category,
        'method': method,
        'samples': samples,
    }


def suckout_direction(eq_result, won):
    """Classify an all-in's suckout status from an equity() result.

    Returns one of:
      'against_hero' -- Hero was the field favourite and LOST (sucked out on)
      'by_hero'      -- Hero was an underdog and WON (Hero sucked out)
      ''             -- neither (coin-flip result, or expected result)

    A lost/won coin-flip is deliberately NOT a suckout: the favourite must
    clear _SUCKOUT_FAV_FLOOR, the underdog must be under _SUCKOUT_DOG_CEIL.
    `won` may be True, False, or the string 'chop' (chop is never a suckout).
    """
    if not eq_result or won == 'chop':
        return ''
    he = eq_result.get('hero_equity', 0.5)
    fav = eq_result.get('is_favorite', False)
    if won is False and fav and he >= _SUCKOUT_FAV_FLOOR:
        return 'against_hero'
    if won is True and not fav and he <= _SUCKOUT_DOG_CEIL:
        return 'by_hero'
    return ''
