"""
gem_pko.py — Bounty / PKO equity-adjustment analysis (B226/B227, Ron 2026-05-25)
============================================================================
Powers IV.7. Objective: find preflop all-in decisions whose correct/incorrect
verdict FLIPS between the freezeout regime and the bounty regime.

Scope (heads-up preflop all-ins, bounty formats):
  v1 (B226) — Hero-as-CALLER (Hero calls a jam).
  v2 (B227) — Hero-as-JAMMER (Hero shoves / re-jams, HU).
Multiway pots, side pots, and postflop all-ins remain out of scope —
see IV7_Bounty_PKO_Rebuild_Scope.md.

Caller decision math:
    required_equity   = to_call / (pot_before_call + to_call)
    freezeout_correct = hero_equity >= required_equity
    bounty_correct    = hero_equity >= required_equity - BOUNTY_DISCOUNT_PP
The bounty discount applies ONLY when Hero COVERS the jammer.

Jammer decision math (B227):
    EV_shove = P(fold)*pot_now + P(call)*(equity_vs_callrange*final_pot - cost)
  where, when Hero covers the caller and the format is a bounty, the
  equity-side payoff is lifted by the bounty value (winning a called shove
  also claims the bounty). Fold equity itself is regime-neutral. A jammer
  "flip" = EV_shove >= 0 under one regime and < 0 under the other, evaluated
  against the best ALTERNATIVE (fold = 0 EV; a min-open alternative is a v3
  refinement). The bounty can only ever make a shove BETTER for a coverer,
  so jammer flips are practically all type (a): +EV with bounty, -EV without.
"""
import re

try:
    from gem_solver import expand_range, preflop_equity_vs_range, remove_conflicts
    _SOLVER_OK = True
except Exception:
    _SOLVER_OK = False

# Bounty figures now come from gem_bounty (estimate from tournament name +
# phase) rather than the flat constants below — Ron 2026-05-26. The constants
# are kept as the fallback if gem_bounty is unavailable, and as the documented
# regular-format / baseline-phase anchor.
try:
    import gem_bounty
    _BOUNTY_MODULE_OK = True
except Exception:
    _BOUNTY_MODULE_OK = False

# Fixed ~8pp bounty discount for the CALLER path (the documented ~1.1-buy-in
# factor). For the JAMMER path the bounty enters as a chip-value uplift on the
# called-and-won branch — see BOUNTY_VALUE_BB below.
BOUNTY_DISCOUNT_PP = 8.0
# Jammer path: the bounty's worth in BB terms when claimed. ~1.1 buy-ins of
# added value; expressed as a fraction of the pot Hero is contesting is messy,
# so we model it as a flat BB credit on the win branch, scaled to the typical
# bounty ≈ 50% of buy-in in GG PKO and Hero's stack. Kept deliberately simple
# and clearly labelled; a per-hand bounty read is a v3 refinement.
BOUNTY_VALUE_BB = 4.0
_BOUNTY_FORMATS = ('BOUNTY', 'MYSTERY_BOUNTY')
_RANKORD = '23456789TJQKA'


# ---------------------------------------------------------------------------
# Jam-range model — a generic jamming range by effective stack depth.
# v1 uses a depth-bucketed approximation (clearly labelled in the report); a
# position-and-chart-exact range is a later refinement.
# ---------------------------------------------------------------------------
_JAM_RANGE_BUCKETS = [
    (12.0, "22+ A2s+ K2s+ Q5s+ J7s+ T7s+ 97s+ 86s+ 76s 65s "
           "A2o+ K7o+ Q9o+ J9o+ T9o"),                                # ~very wide
    (22.0, "22+ A2s+ K6s+ Q9s+ J9s+ T9s 98s A5o+ K9o+ QTo+ JTo"),      # ~38%
    (35.0, "22+ A8s+ A5s K9s+ QTs+ JTs A9o+ KJo+ QJo"),                # ~22%
    (999.0, "55+ A9s+ KTs+ QJs AJo+ KQo"),                             # ~13%
]

# Villain CALLING range vs a Hero jam, by Hero's effective shove depth. A
# villain calls TIGHTER than they would jam — these are deliberately tighter
# than _JAM_RANGE_BUCKETS. Used for the jammer flip's called-equity branch.
_CALL_RANGE_BUCKETS = [
    (12.0, "22+ A2s+ A7o+ K9s+ KQo QTs+ JTs"),                         # call wide vs short jam
    (22.0, "55+ A8s+ ATo+ KTs+ KQo QJs"),                              # ~14%
    (35.0, "77+ ATs+ AQo+ KQs"),                                       # ~9%
    (999.0, "99+ AQs+ AKo"),                                           # ~5%
]


def _bucket_spec(buckets, eff_bb):
    """Return the range spec string for the matching depth bucket."""
    for thresh, spec in buckets:
        if eff_bb <= thresh:
            return spec
    return buckets[-1][1]


def _expand_plus(tok):
    """Expand one range token ('22+', 'ATs+', 'KQo', 'AhKd') to explicit
    hand descriptions that gem_solver.expand_hand_desc accepts."""
    tok = tok.strip()
    if not tok:
        return []
    plus = tok.endswith('+')
    base = tok[:-1] if plus else tok
    if len(base) == 4:                       # specific combo, e.g. AhKd
        return [base]
    if len(base) == 2 and base[0] == base[1]:  # pair
        if plus:
            i = _RANKORD.index(base[0])
            return [r + r for r in _RANKORD[i:]]
        return [base]
    if len(base) == 3:                       # AKs / AKo
        r1, r2, k = base[0], base[1], base[2]
        if plus:
            i1, i2 = _RANKORD.index(r1), _RANKORD.index(r2)
            return [r1 + _RANKORD[j] + k for j in range(i2, i1)]
        return [base]
    return [base]


def _range_combos(buckets, eff_bb, dead_cards):
    """Return villain range combos for the matching depth bucket, with Hero +
    board cards removed."""
    spec_str = _bucket_spec(buckets, eff_bb)
    descs = []
    for tok in spec_str.split():
        descs.extend(_expand_plus(tok))
    combos = expand_range([{'desc': d} for d in descs])
    return remove_conflicts(combos, dead_cards)


def _jam_range_combos(eff_bb, dead_cards):
    """Villain JAM-range combos — used by the caller path."""
    return _range_combos(_JAM_RANGE_BUCKETS, eff_bb, dead_cards)


def _call_range_combos(eff_bb, dead_cards):
    """Villain CALLING-range combos vs a Hero jam — used by the jammer path."""
    return _range_combos(_CALL_RANGE_BUCKETS, eff_bb, dead_cards)


# ---------------------------------------------------------------------------
# Raw-HH reconstruction — HU preflop jam-call
# ---------------------------------------------------------------------------
def reconstruct_hu_preflop_jam_call(raw_hh, hero_name='Hero'):
    """Parse a raw HH. Return a context dict when the hand is a clean
    heads-up preflop all-in where Hero CALLED a jam; else None.

    Returned dict:
      bb, hero_cards, jammer_name, jammer_cards, hero_stack_bb,
      jammer_stack_bb, to_call_bb, pot_before_call_bb, total_pot_bb,
      required_equity, hero_covers
    """
    if not raw_hh:
        return None
    raw = raw_hh.replace(',', '')
    bb_m = re.search(r'Level\d+\((\d+)/(\d+)', raw)
    if not bb_m:
        return None
    bb = float(bb_m.group(2))
    if bb <= 0:
        return None

    # Seat stacks
    stacks = {}
    for m in re.finditer(r'Seat \d+:\s+(\S+)\s+\(([\d]+) in chips\)', raw):
        stacks[m.group(1)] = float(m.group(2))

    # Preflop section only (before the flop / showdown)
    pre = raw.split('*** FLOP ***')[0]
    hole = pre.split('*** HOLE CARDS ***')[-1] if '*** HOLE CARDS ***' in pre else pre

    # Must be a preflop all-in that Hero called all-in.
    hero_call_m = re.search(rf'{re.escape(hero_name)}:\s+calls\s+([\d]+)\s+and is all-in', hole)
    if not hero_call_m:
        return None
    to_call = float(hero_call_m.group(1))

    # The jammer = the player whose raise put them all-in that Hero then called.
    jam_m = None
    for m in re.finditer(r'(\S+):\s+raises\s+[\d]+\s+to\s+[\d]+\s+and is all-in', hole):
        if m.group(1) != hero_name:
            jam_m = m   # last jammer before Hero's call
    if not jam_m:
        return None
    jammer = jam_m.group(1)

    # HU check: exactly two players put voluntary money in preflop (Hero + jammer).
    actors = set(re.findall(r'(\S+):\s+(?:raises|calls|bets)', hole))
    if actors - {hero_name, jammer}:
        return None  # a third voluntary actor -> not heads-up, out of v1 scope

    # Hole cards
    hc_m = re.search(rf'Dealt to {re.escape(hero_name)} \[(\w\w) (\w\w)\]', raw)
    if not hc_m:
        return None
    hero_cards = (hc_m.group(1), hc_m.group(2))

    # Jammer's revealed cards (shown at the all-in showdown), if present.
    jammer_cards = None
    jm = re.search(rf'{re.escape(jammer)}(?:[^\n]*)?:?\s*show(?:s|ed)\s+\[(\w\w) (\w\w)\]', raw)
    if jm:
        jammer_cards = (jm.group(1), jm.group(2))

    total_pot_m = re.search(r'Total pot\s+([\d]+)', raw)
    if not total_pot_m:
        return None
    total_pot = float(total_pot_m.group(1))

    # pot_before_call = total pot minus Hero's calling chips (the uncalled
    # portion of the jam is already excluded from "Total pot").
    pot_before_call = total_pot - to_call
    if pot_before_call <= 0 or to_call <= 0:
        return None
    required_equity = to_call / total_pot * 100.0  # in %

    hero_stack = stacks.get(hero_name, 0.0)
    jammer_stack = stacks.get(jammer, 0.0)
    hero_covers = hero_stack >= jammer_stack and jammer_stack > 0

    return {
        'bb': bb,
        'hero_cards': hero_cards,
        'jammer_name': jammer,
        'jammer_cards': jammer_cards,
        'hero_stack_bb': round(hero_stack / bb, 1),
        'jammer_stack_bb': round(jammer_stack / bb, 1),
        'to_call_bb': round(to_call / bb, 1),
        'pot_before_call_bb': round(pot_before_call / bb, 1),
        'total_pot_bb': round(total_pot / bb, 1),
        'required_equity': round(required_equity, 1),
        'hero_covers': hero_covers,
    }


# ---------------------------------------------------------------------------
# Raw-HH reconstruction — HU preflop Hero JAM (B227)
# ---------------------------------------------------------------------------
def reconstruct_hu_preflop_hero_jam(raw_hh, hero_name='Hero'):
    """Parse a raw HH. Return a context dict when the hand is a clean
    heads-up preflop all-in where HERO jammed (shoved / re-jammed) and exactly
    one opponent was the live decision-maker against it; else None.

    Returned dict:
      bb, hero_cards, hero_jam_bb, pot_before_jam_bb, hero_invested_bb,
      villain_name, villain_stack_bb, villain_cards, hero_stack_bb,
      hero_covers, was_called
    """
    if not raw_hh:
        return None
    raw = raw_hh.replace(',', '')
    bb_m = re.search(r'Level\d+\((\d+)/(\d+)', raw)
    if not bb_m:
        return None
    bb = float(bb_m.group(2))
    if bb <= 0:
        return None

    stacks = {}
    for m in re.finditer(r'Seat \d+:\s+(\S+)\s+\(([\d]+) in chips\)', raw):
        stacks[m.group(1)] = float(m.group(2))

    pre = raw.split('*** FLOP ***')[0]
    hole = pre.split('*** HOLE CARDS ***')[-1] if '*** HOLE CARDS ***' in pre else pre

    # Hero jammed: a "raises X to Y and is all-in" by Hero.
    hero_jam_m = re.search(
        rf'{re.escape(hero_name)}:\s+raises\s+[\d]+\s+to\s+([\d]+)\s+and is all-in',
        hole)
    if not hero_jam_m:
        return None
    hero_jam_to = float(hero_jam_m.group(1))   # cumulative chips Hero put in

    # HU: the only OTHER voluntary actors must reduce to a single opponent who
    # had a live decision facing Hero's jam. Collect voluntary actors.
    actors = set(re.findall(r'(\S+):\s+(?:raises|calls|bets)', hole))
    others = actors - {hero_name}
    # The opponent facing the jam = whoever acted (call / fold) AFTER Hero's
    # jam. Find actions after the jam position.
    jam_pos = hole.find(hero_jam_m.group(0))
    after = hole[jam_pos + len(hero_jam_m.group(0)):]
    pre_jam = hole[:jam_pos]   # everything before Hero's jam, for pot math
    callers = re.findall(r'(\S+):\s+calls\s+([\d]+)', after)
    folders_after = re.findall(r'(\S+):\s+folds', after)
    # Out-of-scope: more than one caller (multiway all-in).
    if len(callers) > 1:
        return None
    # The decision-facing opponent: the caller, or (if all folded) the last
    # player who could have called. For a clean HU read we require that the
    # voluntary actors besides Hero number exactly 1 (a single villain who
    # opened/3-bet or who Hero jammed over).
    if len(others) != 1:
        return None
    villain = next(iter(others))

    was_called = bool(callers)
    villain_call_bb = (float(callers[0][1]) / bb) if was_called else 0.0

    # pot_before_jam = sum of antes+blinds + the largest pre-jam "raises to N"
    # per player on the preflop street (a raise "to N" sets that player's
    # cumulative street contribution, so the last raise-to per player wins).
    ante_blind = 0.0
    for m in re.finditer(r'\S+:\s+posts (?:the ante|small blind|big blind)\s+([\d]+)',
                         raw.split('*** HOLE CARDS ***')[0]):
        ante_blind += float(m.group(1))
    pre_jam_raise_to = {}
    for m in re.finditer(r'(\S+):\s+raises\s+[\d]+\s+to\s+([\d]+)', pre_jam):
        pre_jam_raise_to[m.group(1)] = float(m.group(2))   # last raise-to wins
    pot_before_jam = ante_blind + sum(pre_jam_raise_to.values())

    hero_cards = None
    hc_m = re.search(rf'Dealt to {re.escape(hero_name)} \[(\w\w) (\w\w)\]', raw)
    if hc_m:
        hero_cards = (hc_m.group(1), hc_m.group(2))
    if not hero_cards:
        return None

    villain_cards = None
    vm = re.search(rf'{re.escape(villain)}(?:[^\n]*)?:?\s*show(?:s|ed)\s+\[(\w\w) (\w\w)\]',
                   raw)
    if vm:
        villain_cards = (vm.group(1), vm.group(2))

    hero_stack = stacks.get(hero_name, 0.0)
    villain_stack = stacks.get(villain, 0.0)
    hero_covers = hero_stack >= villain_stack and villain_stack > 0

    # Hero's chips actually at risk = min(hero_jam_to, villain can match).
    # For the EV model we use the effective contest = min(hero stack, villain
    # stack), measured from the start of the hand.
    eff_contest_bb = min(hero_stack, villain_stack) / bb

    return {
        'bb': bb,
        'hero_cards': hero_cards,
        'hero_jam_to_bb': round(hero_jam_to / bb, 1),
        'pot_before_jam_bb': round(pot_before_jam / bb, 1),
        'villain_name': villain,
        'villain_cards': villain_cards,
        'villain_stack_bb': round(villain_stack / bb, 1),
        'hero_stack_bb': round(hero_stack / bb, 1),
        'eff_contest_bb': round(eff_contest_bb, 1),
        'hero_covers': hero_covers,
        'was_called': was_called,
        'villain_call_bb': round(villain_call_bb, 1),
    }


def jammer_shove_ev(ctx, fold_pct, hero_equity_pct, bounty_credit_bb):
    """Compute EV (in BB) of Hero's preflop shove.

      EV = P(fold)*pot_now + P(call)*(eq*final_pot - cost) + bounty term

    cost          = Hero's chips at risk (effective contest)
    final_pot     = pot when called = 2*cost + dead money already in
    pot_now       = pot Hero wins immediately on a fold
    bounty_credit = extra BB credited on the called-and-won branch (0 unless
                    Hero covers and the format is a bounty)
    """
    cost = ctx['eff_contest_bb']
    dead = ctx['pot_before_jam_bb']             # blinds/antes/opener already in
    pot_now = dead                              # what a fold wins Hero
    final_pot = 2 * cost + dead
    p_fold = fold_pct / 100.0
    p_call = 1.0 - p_fold
    eq = hero_equity_pct / 100.0
    ev_called = eq * (final_pot + bounty_credit_bb) - cost
    return p_fold * pot_now + p_call * ev_called


# ---------------------------------------------------------------------------
# Main entry — analyse bounty preflop all-in calls for flips
# ---------------------------------------------------------------------------
def analyze_pko_flips(hands, raw_hh_map):
    """hands: list of parsed hand dicts. raw_hh_map: {hand_id: raw_hh_text}.

    Returns a dict:
      {'flips_a': [...], 'flips_b': [...], 'evaluated': N, 'skipped': N,
       'scope_note': str}
    flip (a) = correct WITH bounty, wrong WITHOUT.
    flip (b) = correct WITHOUT bounty, wrong WITH.
    """
    out = {'flips_a': [], 'flips_b': [], 'evaluated': 0, 'skipped': 0,
           'eligible': 0, 'evaluated_caller': 0, 'evaluated_jammer': 0,
           'scope_note': 'HU preflop all-ins, bounty formats — Hero as caller '
                         'AND as jammer.'}
    if not _SOLVER_OK:
        out['scope_note'] += ' (solver unavailable — equity not computed)'
        return out

    for h in hands:
        if not h.get('pf_allin'):
            continue
        if (h.get('format') or '') not in _BOUNTY_FORMATS:
            continue
        out['eligible'] += 1
        raw = raw_hh_map.get(h.get('id'))
        if not raw:
            out['skipped'] += 1
            continue
        ctx = reconstruct_hu_preflop_jam_call(raw)
        if not ctx:
            # Not a HU jam-call — try the HU Hero-jam path (B227).
            jctx = reconstruct_hu_preflop_hero_jam(raw)
            if not jctx:
                out['skipped'] += 1   # multiway / out of scope
                continue
            _spot = _eval_jammer_flip(h, jctx)
            if _spot is None:
                out['skipped'] += 1
                continue
            out['evaluated'] += 1
            out['evaluated_jammer'] += 1
            if _spot.get('flip') == 'a':
                out['flips_a'].append(_spot)
            elif _spot.get('flip') == 'b':
                out['flips_b'].append(_spot)
            continue

        hero_cards = ctx['hero_cards']
        dead = set(hero_cards)
        combos = _jam_range_combos(ctx['jammer_stack_bb'], dead)
        eq, _n = preflop_equity_vs_range(hero_cards, combos)
        if eq is None:
            out['skipped'] += 1
            continue
        out['evaluated'] += 1
        out['evaluated_caller'] += 1

        req = ctx['required_equity']
        freezeout_correct = eq >= req
        # Bounty discount only when Hero covers the jammer. Estimated from the
        # tournament name + phase (gem_bounty); falls back to the flat ~8pp
        # anchor if the module is unavailable.
        if _BOUNTY_MODULE_OK:
            discount = gem_bounty.bounty_discount_pp(
                h.get('tournament', ''), h.get('tournament_phase', ''),
                fmt=h.get('format'), hero_covers=ctx['hero_covers'])
        else:
            discount = BOUNTY_DISCOUNT_PP if ctx['hero_covers'] else 0.0
        bounty_correct = eq >= (req - discount)

        if freezeout_correct == bounty_correct:
            continue  # not a flip

        spot = {
            'id': h.get('id'),
            'role': 'caller',
            'cards': ''.join(hero_cards),
            'tournament': h.get('tournament', ''),
            'date': h.get('date', ''),
            'position': h.get('position', ''),
            'hero_equity': round(eq, 1),
            'required_fo': round(req, 1),
            'required_pko': round(req - discount, 1),
            'hero_covers': ctx['hero_covers'],
            'to_call_bb': ctx['to_call_bb'],
            'pot_before_call_bb': ctx['pot_before_call_bb'],
            'jammer_stack_bb': ctx['jammer_stack_bb'],
        }
        if bounty_correct and not freezeout_correct:
            spot['flip'] = 'a'   # bounty makes the call correct
            out['flips_a'].append(spot)
        else:
            spot['flip'] = 'b'   # bounty should make Hero fold
            out['flips_b'].append(spot)

    return out


def _eval_jammer_flip(h, jctx):
    """B227: evaluate a HU Hero-jam for a bounty flip. Returns a spot dict
    (with 'flip' set to 'a'/'b' if it flips, or no 'flip' key if it doesn't),
    or None if equity could not be computed.

    The shove is compared against folding (EV 0). A flip = the shove is +EV
    under one regime and -EV under the other."""
    hero_cards = jctx['hero_cards']
    dead = set(hero_cards)
    call_combos = _call_range_combos(jctx['villain_stack_bb'], dead)
    eq, _n = preflop_equity_vs_range(hero_cards, call_combos)
    if eq is None:
        return None

    # Villain's fold % vs the jam: the complement of how often the calling
    # range continues. Modelled from the depth bucket — a villain facing a
    # shove folds more the deeper the jam. Transparent, clearly-labelled.
    depth = jctx['eff_contest_bb']
    if depth <= 12:
        fold_pct = 55.0
    elif depth <= 22:
        fold_pct = 68.0
    elif depth <= 35:
        fold_pct = 78.0
    else:
        fold_pct = 85.0

    # Freezeout: no bounty credit. Bounty: credit only if Hero covers —
    # estimated from the tournament name + phase (gem_bounty).
    ev_fo = jammer_shove_ev(jctx, fold_pct, eq, 0.0)
    if _BOUNTY_MODULE_OK:
        bounty_credit = gem_bounty.bounty_value_bb(
            h.get('tournament', ''), h.get('tournament_phase', ''),
            fmt=h.get('format'), hero_covers=jctx['hero_covers'])
    else:
        bounty_credit = BOUNTY_VALUE_BB if jctx['hero_covers'] else 0.0
    ev_pko = jammer_shove_ev(jctx, fold_pct, eq, bounty_credit)

    fo_correct = ev_fo >= 0.0
    pko_correct = ev_pko >= 0.0

    spot = {
        'id': h.get('id'),
        'role': 'jammer',
        'cards': ''.join(hero_cards),
        'tournament': h.get('tournament', ''),
        'date': h.get('date', ''),
        'position': h.get('position', ''),
        'hero_equity': round(eq, 1),
        'fold_pct_modelled': fold_pct,
        'ev_freezeout_bb': round(ev_fo, 2),
        'ev_bounty_bb': round(ev_pko, 2),
        'hero_covers': jctx['hero_covers'],
        'eff_contest_bb': jctx['eff_contest_bb'],
        'villain_stack_bb': jctx['villain_stack_bb'],
        'was_called': jctx['was_called'],
    }
    if fo_correct != pko_correct:
        spot['flip'] = 'a' if (pko_correct and not fo_correct) else 'b'
    return spot
