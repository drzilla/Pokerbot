"""
gem_bounty.py — Bounty value & equity-adjustment estimator
===========================================================
Ron 2026-05-26. Estimates the PKO/bounty equity adjustment from two pieces of
observable hand metadata:

  1. the tournament NAME  — regular Bounty / Big Bounties / Mystery Bounty
  2. the relative PHASE   — late_reg ... ft_zone

A bounty's chip value is roughly fixed once seeded; what changes is its EV
WEIGHT — how far it shifts a call/jam decision. That weight scales with
(a) how large the format's bounty pool is and (b) how big the bounty has
grown relative to the (shrinking) effective stacks as the tournament
progresses. Hence: a base figure from the name, a multiplier from the phase.

Replaces the flat BOUNTY_DISCOUNT_PP (8.0) / BOUNTY_VALUE_BB (4.0) constants
previously hard-coded in gem_pko.py. The regular-format / post_reg-phase
combination reproduces the documented ~8pp anchor, so existing PKO output is
unchanged for the typical case; Big Bounties / Mystery, and the early vs late
phases, now scale away from it instead of all sharing one number.

All figures are transparent, labelled ESTIMATES. A per-hand read from live
bounty amounts in the HH is a future refinement — GG's anonymised exports do
not reliably expose live bounty values.
"""

# --- Base figures by bounty TYPE -------------------------------------------
# discount_pp : caller-path equity discount, in percentage points, at the
#               post_reg baseline phase. Regular = the documented ~8pp anchor.
# value_bb    : jammer-path BB credit on the called-and-won branch, baseline.
# Big Bounties allocate a larger share of the prize pool to bounties than a
# standard PKO; Mystery pools are large but paid as a lottery — the per-KO
# AVERAGE (what a chip-EV model uses) sits between regular and big.
_BOUNTY_TYPES = {
    'regular': {'discount_pp':  8.0, 'value_bb': 4.0, 'label': 'Regular bounty (PKO)'},
    'big':     {'discount_pp': 12.0, 'value_bb': 6.5, 'label': 'Big Bounties'},
    'mystery': {'discount_pp': 10.0, 'value_bb': 5.5, 'label': 'Mystery Bounty'},
    'none':    {'discount_pp':  0.0, 'value_bb': 0.0, 'label': 'Freezeout / no bounty'},
}

# --- Phase multiplier ------------------------------------------------------
# As the tournament runs, stacks shrink and collected bounties compound, so
# the bounty grows as a fraction of effective stacks -> its EV weight rises.
# post_reg is the baseline (multiplier 1.0) -> regular/post_reg == ~8pp anchor.
_PHASE_WEIGHT = {
    'late_reg':    0.80,   # registration still open, deepest stacks
    'post_reg':    1.00,   # mid tournament — baseline
    'bubble_zone': 1.20,   # short stacks, bounty a big fraction of the pot
    'post_bubble': 1.10,
    'ft_zone':     1.35,   # final table — bounty weight at its peak
}
_DEFAULT_PHASE_WEIGHT = 1.00

# Hard ceiling so a pathological name/phase combination can never emit an
# absurd discount.
_MAX_DISCOUNT_PP = 20.0


def classify_bounty(tournament_name, fmt=None):
    """Classify the bounty TYPE from the tournament name (and the parser's
    `format` tag when supplied).

    `fmt` is the gem_parser format field ('BOUNTY' / 'MYSTERY_BOUNTY' /
    'SATELLITE' / 'FREEZEOUT'); when given it gates the result so a freezeout
    is never mis-typed off a stray name keyword.

    Returns: {'bounty_type', 'discount_pp', 'value_bb', 'label'} where the
    pp/bb figures are the BASE (post_reg-baseline) values for that type.
    """
    name = (tournament_name or '').lower()
    fmt = (fmt or '').upper()

    # Format tag is authoritative when it rules a bounty out.
    if fmt in ('FREEZEOUT', 'SATELLITE'):
        btype = 'none'
    elif fmt == 'MYSTERY_BOUNTY' or 'mystery' in name:
        btype = 'mystery'
    elif 'big bount' in name or 'big bonus bount' in name:
        # GG "[Big Bounties]" variant — larger share of the pool in bounties.
        btype = 'big'
    elif fmt == 'BOUNTY' or 'bounty' in name or ' pko' in name or 'bh ' in name:
        btype = 'regular'
    else:
        btype = 'none'

    base = _BOUNTY_TYPES[btype]
    return {
        'bounty_type': btype,
        'discount_pp': base['discount_pp'],
        'value_bb':    base['value_bb'],
        'label':       base['label'],
    }


def phase_weight(phase):
    """Return the phase multiplier. Unknown / missing phase -> 1.0 baseline."""
    return _PHASE_WEIGHT.get((phase or '').lower(), _DEFAULT_PHASE_WEIGHT)


def bounty_discount_pp(tournament_name, phase, fmt=None, hero_covers=True):
    """Caller-path equity discount in percentage points.

    required_equity(bounty) = required_equity(chips) - bounty_discount_pp

    The discount applies ONLY when Hero COVERS the jammer — winning the pot
    must actually claim the bounty (eliminate the villain) for the credit to
    exist. A non-covering Hero gets 0 (preserves the gem_pko rule).
    """
    if not hero_covers:
        return 0.0
    base = classify_bounty(tournament_name, fmt)['discount_pp']
    if base <= 0.0:
        return 0.0
    disc = base * phase_weight(phase)
    return round(min(disc, _MAX_DISCOUNT_PP), 1)


def bounty_value_bb(tournament_name, phase, fmt=None, hero_covers=True,
                    bounty_ratio=None, eff_stack_bb=None, starting_stack_bb=None):
    """Jammer-path bounty credit in BB — extra value on the called-and-won
    branch of a shove EV calc. Like the discount, 0 unless Hero covers.

    v8.6.3: when bounty_ratio + eff_stack_bb are provided, uses per-event
    ratio-based credit instead of the flat _BOUNTY_TABLE. Falls back to
    the flat table when buy-in structure is unavailable.

    bounty_ratio = bounty_face / prize from the 3-part buy-in line.
    eff_stack_bb = min(Hero, shortest active opponent) at the decision.
    starting_stack_bb = starting stack in BB for this tournament.
    """
    if not hero_covers:
        return 0.0

    # v8.6.3: per-event ratio-based credit when data available
    if bounty_ratio is not None and bounty_ratio > 0 and eff_stack_bb and eff_stack_bb > 0:
        # 0.5 = half-on-own-head PKO convention
        _PKO_HALF = 0.5
        credit = _PKO_HALF * bounty_ratio * eff_stack_bb
        # Cap at contestable stack (credit cannot exceed what is winnable)
        if starting_stack_bb and starting_stack_bb > 0:
            credit = min(credit, _PKO_HALF * bounty_ratio * starting_stack_bb)
        value = round(credit * phase_weight(phase), 2)
        return value

    # Flat table fallback
    base = classify_bounty(tournament_name, fmt)['value_bb']
    if base <= 0.0:
        return 0.0
    return round(base * phase_weight(phase), 2)


def bounty_context(tournament_name, phase, fmt=None, hero_covers=True,
                   bounty_ratio=None, eff_stack_bb=None, starting_stack_bb=None):
    """Bundle everything for a candidate / report block — one call, all the
    estimate's inputs and outputs, so the analyst can see how it was derived."""
    cls = classify_bounty(tournament_name, fmt)
    pw = phase_weight(phase)
    _vbb = bounty_value_bb(tournament_name, phase, fmt, hero_covers,
                           bounty_ratio=bounty_ratio,
                           eff_stack_bb=eff_stack_bb,
                           starting_stack_bb=starting_stack_bb)
    return {
        'bounty_type':    cls['bounty_type'],
        'label':          cls['label'],
        'phase':          (phase or 'unknown'),
        'phase_weight':   pw,
        'hero_covers':    bool(hero_covers),
        'discount_pp':    bounty_discount_pp(tournament_name, phase, fmt, hero_covers),
        'value_bb':       _vbb,
        'bounty_ratio':   bounty_ratio,
        'method':         'ratio_model' if bounty_ratio else 'flat_table',
        'basis':          ('per-event ratio model' if bounty_ratio
                           else 'flat table fallback from tournament name + phase'),
    }
