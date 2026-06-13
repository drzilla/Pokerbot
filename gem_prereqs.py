"""
GEM Detector Prerequisites — v7.30 P1-3 structural fix

The four detector misclassifications caught in this session
(iso_raise_iso_jam_conflation, j35_multiway_3bet_misfire,
j36_4bet_jam_misfire, plus the recurring iso_raise_iso_jam_conflation
in gem_exceptions_log.csv #1-3) all share one root cause:

  Each detector hand-rolls its own action-sequence prerequisite checks,
  and easy-to-forget gates (Hero all-in? prior opener? Hero raise count?)
  get omitted at write time. Fixes happen one-at-a-time after
  misclassifications surface.

This module centralizes those prerequisite checks. Every detector that
fires off "Hero did X in scenario Y" should call out to verify the
*shape* of the preflop action matches what it expects, not just check
flag bits like `pf_allin` and `villain_jammed` independently.

Usage:
    from gem_prereqs import preflop_shape, matches_shape

    shape = preflop_shape(h)
    if not matches_shape(shape, hero_all_in=True, prior_raises_before_hero=1):
        return  # detector doesn't apply to this scenario

The shape dict is computed ONCE per hand and passed around. Cheap to
compute (~15 lines), expensive (debugging time) to omit.
"""


def preflop_shape(h):
    """Compute structured preflop shape from a parsed hand.

    Returns dict with these keys (all derived from h['pf_sequence'] +
    flag bits — no new logic, just centralized + named):

      hero_all_in:          bool — Hero is all-in by end of preflop
      hero_raise_count:     int  — number of raises Hero made preflop
      prior_raises_before_hero: int — raises in pf_sequence before Hero's
                                     first action (0=open, 1=face-raise,
                                     2=face-3bet/squeeze, 3+=4BP+)
      hero_first_raise_was_allin: bool — Hero's first raise was the all-in
      villain_jammed_before_hero: bool — any villain went all-in before Hero
      total_raises:         int  — total raises in preflop
      had_villain_limp_before_hero: bool — non-blind villain limped before Hero
      hero_acted:           bool — Hero made any action preflop

    These names are intentionally explicit. Detectors should read them
    rather than re-deriving from raw flags.
    """
    pf_seq = h.get('pf_sequence') or []
    hero_all_in = bool(h.get('pf_allin'))
    villain_jammed = bool(h.get('villain_jammed'))

    hero_raise_count = 0
    prior_raises_before_hero = 0
    hero_acted = False
    total_raises = 0
    had_villain_limp_before_hero = False

    for step in pf_seq:
        is_hero = '(H)' in step
        action = step.split(':', 1)[-1].strip() if ':' in step else ''
        is_raise = action == 'raises'
        is_call = action == 'calls'
        # Identify the position label (everything before ':' minus '(H)')
        pos_label = step.split(':', 1)[0].replace('(H)', '').strip()

        if is_raise:
            total_raises += 1

        if not hero_acted:
            if is_raise:
                prior_raises_before_hero += 1
            elif is_call:
                # Non-blind cold-call before Hero acts = a "limp" in iso-jam terminology
                # (SB/BB are blinds, not limps — they're already in for the blind)
                if pos_label not in ('SB', 'BB'):
                    had_villain_limp_before_hero = True

        if is_hero:
            hero_acted = True
            if is_raise:
                hero_raise_count += 1

    # Hero's first raise was all-in if Hero made exactly one raise AND that raise was all-in
    # (This isn't perfectly derivable from pf_sequence alone — pf_sequence doesn't carry
    # the all-in flag per action — but combined with hero_all_in + hero_raise_count==1
    # it's reliable for the open-jam case which is what J36 needs.)
    hero_first_raise_was_allin = hero_all_in and hero_raise_count == 1

    return {
        'hero_all_in': hero_all_in,
        'hero_raise_count': hero_raise_count,
        'prior_raises_before_hero': prior_raises_before_hero,
        'hero_first_raise_was_allin': hero_first_raise_was_allin,
        'villain_jammed_before_hero': villain_jammed,
        'total_raises': total_raises,
        'had_villain_limp_before_hero': had_villain_limp_before_hero,
        'hero_acted': hero_acted,
    }


def matches_shape(shape, **constraints):
    """Check if a preflop shape matches detector prerequisites.

    Pass any subset of shape keys as keyword args. Returns True iff every
    constraint matches the shape exactly.

    Examples:
        # Iso-jam: Hero all-in, prior raise was the jam, no opener before
        matches_shape(shape,
                      hero_all_in=True,
                      villain_jammed_before_hero=True,
                      prior_raises_before_hero=1)

        # Open-jam: Hero's first action is the all-in raise
        matches_shape(shape, hero_first_raise_was_allin=True)

        # Iso-RAISE (NOT iso-jam): Hero raised but kept stack behind
        matches_shape(shape, hero_all_in=False, villain_jammed_before_hero=True)
    """
    for key, expected in constraints.items():
        if key not in shape:
            raise KeyError(f"Unknown shape key: {key}. "
                           f"Available: {list(shape.keys())}")
        if shape[key] != expected:
            return False
    return True


# =====================================================================
# DETECTOR PREREQUISITE PROFILES (v7.30)
# =====================================================================
# Each entry names a detector and the prerequisite shape it requires.
# When adding a new mistake/deviation detector, define its profile here
# rather than scattering gates throughout gem_analyzer.py. Then call
# matches_shape(shape, **PREREQS['my_detector']) at the top of the
# detector's loop.
#
# This makes it impossible to forget a gate — the prerequisites are
# named and version-controlled. New detectors without a profile entry
# get caught at code review.
# =====================================================================

PREREQS = {
    # Wide Iso-Jam: Hero all-in over a villain jam, with no prior opener
    # (pure iso scenario, not squeeze/4-bet over jam).
    'wide_iso_jam': {
        'hero_all_in': True,
        'villain_jammed_before_hero': True,
        # Note: prior_raises_before_hero==1 is implied by villain_jammed==True
        # AND that being the only prior raise. Not enforced separately yet
        # because some valid iso-jam scenarios have a limp+jam pattern
        # (limp, then villain over-jams). Detector body still needs to
        # check the limp case if added.
    },

    # J35 Reshove Ceiling: HU vs jammer scenario, no prior opener.
    'j35_reshove_ceiling': {
        'villain_jammed_before_hero': True,
        'prior_raises_before_hero': 1,  # only the jam, no opener
    },

    # J36 ICM Open-Jam: Hero's all-in IS the open. Excludes 4-bet jams
    # (Hero opened normally, got 3-bet, jammed back — different decision).
    'j36_icm_open_jam': {
        'hero_first_raise_was_allin': True,
        'hero_raise_count': 1,
    },

    # J37 Shallow BvB BB Jam: Hero in BB, n_players=2, Hero jammed.
    # (n_players check stays in detector; this profile covers PF shape only.)
    'j37_shallow_bb_jam': {
        'hero_all_in': True,
        'hero_raise_count': 1,
    },

    # v7.31 Patch 6: V15a 4BP Flat-Call requires Hero hasn't raised the
    # 4-bet pot. If pf_action ends as 'call' but Hero made an earlier raise
    # (4-bet then called the 5-bet jam), V15a should not fire — the leak
    # is the 4-bet, not a flat-call. Detector body still checks pot_type.
    'v15a_4bp_flat': {
        'hero_raise_count': 0,
    },
}

# v7.31 Patch 6: PREREQS_HAND — constraints on parsed hand fields directly
# (not derivable from pf_sequence shape). Same dispatcher; checks the hand
# dict for keys instead of the preflop shape.
#
# Constraint syntax: either a literal value (matched with ==) or an
# operator dict like {'gt': 4} | {'gte': 30} | {'lt': 3} | {'eq': 2} | {'in': [...]}.
PREREQS_HAND = {
    # P4-DrawJamDeep: detector fires on flop draw-jam at >=30BB eff.
    # v7.31 adds SPR > 4 floor — at SPR <= 3 OOP, no geometric line is
    # feasible (every non-jam bet commits), so the overshove can be the
    # +EV play. Range advantage + FE may justify it. Exception #13.
    'p4_drawjamdeep': {
        'spr': {'gt': 4.0},
    },

    # J14 Monotone IP No CBet: assumes HU and Hero had the c-bet option.
    # v7.31 adds gates: must be HU (players_at_flop == 2) and Hero must
    # not have faced a prior flop bet (donk lead, check-raise before Hero
    # acted). Exception #11.
    'j14_monotone_no_cbet': {
        'players_at_flop': {'eq': 2},
        'hero_faced_prior_flop_bet': {'eq': False},
    },

    # V15c Flat 5-Bet+ OOP MW: requires pot is STILL multiway at the
    # moment of Hero's call. If everyone except the jammer folded before
    # Hero called, it's HU and V15c shouldn't fire. Exception #14.
    'v15c_5bp_flat_oop_mw': {
        'mw_at_hero_final_pf_action': {'eq': True},
    },
}


def _check_hand_constraint(actual, expected):
    """Check a single PREREQS_HAND constraint against an actual value.

    expected may be a literal (==) or an operator dict.
    Returns True if constraint satisfied.
    """
    if isinstance(expected, dict):
        if 'gt' in expected:
            if actual is None or not (actual > expected['gt']): return False
        if 'gte' in expected:
            if actual is None or not (actual >= expected['gte']): return False
        if 'lt' in expected:
            if actual is None or not (actual < expected['lt']): return False
        if 'lte' in expected:
            if actual is None or not (actual <= expected['lte']): return False
        if 'eq' in expected:
            if actual != expected['eq']: return False
        if 'ne' in expected:
            if actual == expected['ne']: return False
        if 'in' in expected:
            if actual not in expected['in']: return False
        return True
    return actual == expected


def detector_prereq_satisfied(detector_name, h, shape=None):
    """Convenience: check if hand h satisfies the named detector's prereqs.

    Returns True if the detector's prerequisite shape AND hand-field
    constraints (if any) match.

    Detectors should call:
        if not detector_prereq_satisfied('j35_reshove_ceiling', h, shape):
            continue

    Falls through (returns True) for unknown detector names so adding a
    detector without a profile doesn't silently disable it — but logs a
    warning so the omission is visible.
    """
    has_pf_profile = detector_name in PREREQS
    has_hand_profile = detector_name in PREREQS_HAND

    if not has_pf_profile and not has_hand_profile:
        # Unknown detector — log warning but don't block.
        import sys
        print(f"[gem_prereqs WARN] No profile for detector '{detector_name}' — "
              f"add to PREREQS or PREREQS_HAND in gem_prereqs.py", file=sys.stderr)
        return True

    # Check pf_shape constraints
    if has_pf_profile:
        if shape is None:
            shape = preflop_shape(h)
        if not matches_shape(shape, **PREREQS[detector_name]):
            return False

    # v7.31 Patch 6: check hand-field constraints
    if has_hand_profile:
        for key, expected in PREREQS_HAND[detector_name].items():
            actual = h.get(key)
            if not _check_hand_constraint(actual, expected):
                return False

    return True
