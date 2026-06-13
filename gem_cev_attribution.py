"""gem_cev_attribution.py — background cEV/stack attribution collector
(Ron 2026-05-20).

STORE-ONLY. Collects every cEV/stack-denominated signal into one structure
so the data accumulates while the decision to surface it is deferred. NOTHING
in the report changes.

This is the data-collection layer for the eventual Result Attribution ledger
and the cEV-denominated leaks table. It does NOT yet produce a balancing
ledger (that needs precise EAI from ICM module M1) — it collects the inputs.

WHAT IT COLLECTS, per session, all in cEV/stack-style units:

  1. EAI luck            — already in gem_cev.compute_eai_cev_per_stack
                           (effective-stack-at-risk normalized).
  2. Red line            — non-showdown cEV. The complement of EAI: chips
                           won/lost WITHOUT showdown (steals, c-bets, folds).
                           PHASE-WEIGHTED: a hand's contribution is weighted
                           by 1/eff_stack_bb so a non-SD swing late (short,
                           every chip is tournament life) weighs more than the
                           same swing early (deep).
  3. Cooler luck         — chips lost in cooler spots, effective-stack
                           normalized. Always <= 0 (coolers lose by defn).
  4. Read-dependent      — NOT verdicted per hand. Just the bucket: n hands,
     bucket                their summed net_bb and effective-stack-normalized
                           cEV, positive and negative split out. Over a real
                           sample the bucket's running total IS the verdict.

PHASE-WEIGHTING PRINCIPLE (Ron 2026-05-20): the cost of running cold, or of a
mistake, or of a non-SD bleed, depends on WHEN in the tournament it happens.
Card-dead at 150bb early is free; card-dead at 9bb deep is severe. Every axis
here is therefore normalized by the effective stack at the moment — small
eff_stack => bigger weight — rather than summed flat.

DEFERRED (documented, not built here):
  - Precise EAI (real equity, ICM-weighted) -> ICM module M1.
  - Per-mistake EV cost: GEM mistake records are flagged spots, not
    EV-quantified. Small-mistake cEV/stack needs that quantification step
    first. collect_small_mistakes() below returns the spots + phase weight
    but cev_cost is None until mistake-EV-quantification lands.
  - The balancing ledger (layers sum to session result) — waits on precise
    EAI so the skill residual is not polluted by luck-model error.
"""

import json


# Effective-stack phase weighting. A hand at eff_stack_bb E contributes with
# weight (REF / E): at the reference depth weight is 1.0, shorter => heavier,
# deeper => lighter. Capped so a 0.2bb stack does not produce a 100x weight.
#
# SCOPE (corrected 2026-05-20): this multiplier is for RATE-type layers only
# — dealt-card quality, small-mistake spots — where there is no chip amount to
# divide. For MAGNITUDE layers (red line, made-hands, EAI, coolers) the sole
# correct phase normalization is dividing net_bb by eff_stack_bb; those layers
# do NOT use this multiplier (using both double-applies the depth correction).
_PHASE_REF_BB = 25.0      # reference depth ~ a fresh-ish stack
_PHASE_WEIGHT_CAP = 5.0   # max multiplier for very short stacks
_PHASE_WEIGHT_FLOOR = 0.15  # min multiplier for very deep stacks


def phase_weight(eff_stack_bb):
    """Return the phase weight for a hand at the given effective stack.
    Short stacks (late, short) weigh more; deep stacks (early) weigh less."""
    if not eff_stack_bb or eff_stack_bb <= 0:
        return 1.0
    w = _PHASE_REF_BB / eff_stack_bb
    return max(_PHASE_WEIGHT_FLOOR, min(w, _PHASE_WEIGHT_CAP))


# ----------------------------------------------------------------------
# Tournament-phase segmentation (B174, Ron 2026-05-24).
#
# The conversion-gap layers (dealt-card quality, made-hands) carried only a
# DEPTH cut. Depth is a proxy for phase but not the same: a 45bb stack on the
# bubble is high-ICM-pressure yet depth-buckets as "40bb+", indistinguishable
# from hour one. `tournament_phase` is already computed on every hand by
# gem_analyzer.estimate_tournament_phases — segment by it directly so "ran
# cold late, when it mattered" is a first-class signal, not an inference.
#
# UNIT IS UNCHANGED: the phase blocks are an additive VIEW. They re-partition
# the same chip-stack conversion, they do not re-weight it — so no historical
# session number moves. ICM risk-premium weighting of the late slices is a
# separate, deliberately deferred task (it WOULD shift historical numbers).
# ----------------------------------------------------------------------

# Canonical phase order (matches gem_analyzer.estimate_tournament_phases).
_PHASE_ORDER = ['late_reg', 'post_reg', 'bubble_zone', 'ft_zone', 'post_bubble']

# A phase cell needs at least this many opportunities before its gap is
# reported as a standalone signal. Below the floor the cell still appears but
# is tagged low-sample — the session-aggregate stays the authority. Mirrors
# the n>=MH_NMIN discipline used in the I.6 made-hands table.
_PHASE_OPP_FLOOR = 12


def _phase_of(h):
    """Tournament phase for a hand; 'unknown' if not yet estimated."""
    return h.get('tournament_phase') or 'unknown'


def collect_red_line(hands):
    """Non-showdown cEV in EFFECTIVE-STACKS. Red line = result on hands that
    did NOT reach showdown — the non-showdown complement of the EAI axis.

    UNIT (corrected 2026-05-20): each hand contributes net_bb / eff_stack_bb
    — its result as a fraction of the stack at risk — matching the EAI axis.
    An earlier version used net_bb * phase_weight, which (a) left the layer in
    BB not stacks and (b) double-applied the depth correction once the
    division was added. Dividing by eff_stack_bb IS the phase normalization,
    done once: a non-SD swing late (short stack) naturally produces a larger
    fraction than the same swing early. No separate phase_weight multiplier.
    """
    from collections import defaultdict
    by_tid = defaultdict(lambda: {'n': 0, 'raw_bb': 0.0,
                                  'stacks': 0.0, 'skipped': 0})
    for h in hands:
        if h.get('went_to_sd'):
            continue   # red line = NON-showdown only
        tid = h.get('tournament_id') or h.get('tournament')
        net_bb = h.get('net_bb') or 0
        eff = h.get('eff_stack_bb') or h.get('eff_stack_bb_at_decision') or 0
        b = by_tid[tid]
        b['n'] += 1
        b['raw_bb'] += net_bb
        if eff > 0:
            b['stacks'] += max(-1.0, min(net_bb / eff, 3.0))
        else:
            b['skipped'] += 1
    return {tid: {'n_hands': b['n'],
                  'red_line_raw_bb': round(b['raw_bb'], 2),
                  'red_line_stacks': round(b['stacks'], 4),
                  'skipped_hands': b['skipped']}
            for tid, b in by_tid.items()}


def collect_cooler_luck(hands, cooler_block):
    """Cooler luck axis. Chips lost in cooler spots, effective-stack
    normalized so a late cooler (short) weighs more than an early one.
    Always <= 0 — coolers lose by definition."""
    if not cooler_block or not cooler_block.get('hands'):
        return {}
    hands_by_id = {h.get('id'): h for h in hands}
    from collections import defaultdict
    by_tid = defaultdict(lambda: {'n': 0, 'loss_stacks': 0.0})
    for c in cooler_block['hands']:
        h = hands_by_id.get(c.get('id'))
        if not h:
            continue
        tid = h.get('tournament_id') or h.get('tournament')
        eff = h.get('eff_stack_bb') or 0
        net_bb = h.get('net_bb') or 0
        b = by_tid[tid]
        b['n'] += 1
        if eff > 0:
            # loss as a fraction of the effective stack at the cooler.
            frac = max(-1.0, net_bb / eff)
            b['loss_stacks'] += frac
    return {tid: {'n_coolers': b['n'],
                  'cooler_loss_stacks': round(b['loss_stacks'], 4)}
            for tid, b in by_tid.items()}


def collect_read_dependent_bucket(hands, analyst_commentary):
    """Read-dependent bucket — NOT verdicted per hand (Ron 2026-05-20).

    Just the bucket numbers: n hands, summed net_bb, effective-stack-
    normalized cEV, split positive vs negative. Over a real sample the
    running bucket total is the verdict — consistently negative => the
    reads are not working; consistently positive => they earn their keep.
    No per-hand leak/not-leak call is imposed.
    """
    iii4 = [(hid, c) for hid, c in (analyst_commentary or {}).items()
            if isinstance(c, dict)
            and str(c.get('verdict', '')).startswith('III.4')
            and hid.startswith('TM')]
    if not iii4:
        return {'n_hands': 0, 'hands': []}
    hands_by_id = {h.get('id'): h for h in hands}
    rows = []
    sum_bb = sum_stacks = 0.0
    pos_bb = neg_bb = 0.0
    n_pos = n_neg = 0
    for hid, cmt in iii4:
        h = hands_by_id.get(hid)
        if not h:
            continue
        net_bb = h.get('net_bb') or 0
        eff = h.get('eff_stack_bb') or 0
        stacks = (max(-1.0, min(net_bb / eff, 3.0)) if eff > 0 else None)
        rows.append({
            'hand_id': hid,
            'pattern': cmt.get('pattern', ''),
            'key_decision': cmt.get('key_decision', ''),
            'net_bb': round(net_bb, 2),
            'cev_stacks': round(stacks, 4) if stacks is not None else None,
        })
        sum_bb += net_bb
        if stacks is not None:
            sum_stacks += stacks
        if net_bb >= 0:
            pos_bb += net_bb
            n_pos += 1
        else:
            neg_bb += net_bb
            n_neg += 1
    return {
        'n_hands': len(rows),
        'sum_net_bb': round(sum_bb, 2),
        'sum_cev_stacks': round(sum_stacks, 4),
        'positive': {'n': n_pos, 'net_bb': round(pos_bb, 2)},
        'negative': {'n': n_neg, 'net_bb': round(neg_bb, 2)},
        'hands': rows,
        'note': ('Bucket only — no per-hand verdict. Running total over a '
                 'real sample is the signal: consistently negative => reads '
                 'not working; positive => reads earn their keep.'),
    }


# Starting-hand classes are mutually exclusive and exhaustive — every dealt
# hand lands in exactly one. Expected frequencies are computed once over all
# 1,326 combos (see _compute_class_expectations below), so they are exact
# combinatorics with no modelling assumption.



def _starting_hand_class(cards):
    """Classify a 2-card starting hand into a poker-meaningful class. Classes
    are mutually exclusive and exhaustive — every hand lands in exactly one."""
    if not cards or len(cards) < 2:
        return None
    order = '23456789TJQKA'
    r = sorted([c[0] for c in cards], key=lambda x: -order.index(x))
    suited = len(cards) == 2 and cards[0][1] == cards[1][1]
    hi, lo = order.index(r[0]), order.index(r[1])
    pair = r[0] == r[1]
    if pair:
        if r[0] in 'AKQ':
            return 'premium_pair'
        if r[0] in 'JT98':
            return 'mid_pair'
        return 'low_pair'
    # non-pair
    if r == ['A', 'K']:
        return 'premium_ax'
    is_broadway = r[0] in 'AKQJT' and r[1] in 'AKQJT'
    if is_broadway:
        return 'broadway'
    if r[0] == 'A':            # any other ace
        return 'ace_rag'
    if suited and (hi - lo) <= 2 and lo >= order.index('5'):
        return 'suited_connector'
    return 'other'


# Exact expected frequencies for the full class set, computed once over all
# 1,326 combos so they sum to 1.0 and carry no modelling assumption.
def _compute_class_expectations():
    ranks = '23456789TJQKA'
    suits = 'cdhs'
    deck = [r + s for r in ranks for s in suits]
    from collections import Counter
    import itertools
    cnt = Counter()
    n = 0
    for a, b in itertools.combinations(deck, 2):
        cls = _starting_hand_class([a, b])
        cnt[cls] += 1
        n += 1
    return {k: v / n for k, v in cnt.items()}, n


_CLASS_EXPECTED, _TOTAL_COMBOS = _compute_class_expectations()


def collect_dealt_card_quality(hands):
    """Dealt-card quality — exact combinatorial, depth-bucketed (Ron 2026-05-20).

    Replaces the earlier 0..1 strength-score version. Approach: bucket hands
    by EFFECTIVE-STACK DEPTH (40bb+ / 20-40 / 12-20 / <12bb), and within each
    bucket compare the ACTUAL distribution of dealt starting-hand classes
    against the EXACT combinatorial expected distribution.

    Why this is the right shape:
      - The dealt-hand distribution is the ONE poker quantity with a known,
        fixed, skill-free expectation (pure combinatorics). So this layer is
        provably clean — no model, no skill term, nothing else can leak in.
      - Depth-bucketing converts a trivially-true statistic ("dealt 0.4% AA
        vs 0.45%") into the signal that matters: were you card-dead WHEN SHORT
        — i.e. when you could not afford to wait. "Premium frequency 60% of
        expected in the <12bb bucket over 120 hands" is the actionable form.

    SCOPE / KNOWN LIMITATION: this cleanly answers "was the deck kind, by
    phase." It does NOT by itself card-adjust red line / ATS / PFR / AF — card
    quality is a common cause that leaks into all of them. Deconfounding those
    needs phase-level card-luck (this metric) correlated against phase-level
    output across many sessions — tractable BECAUSE this produces the right
    intermediate signal, but deferred until sample size allows. Documented in
    the module 'known_limitations' block.
    """
    from collections import defaultdict

    def _depth_bucket(eff):
        if eff is None or eff <= 0:
            return 'unknown'
        if eff >= 40:
            return '40bb+'
        if eff >= 20:
            return '20-40bb'
        if eff >= 12:
            return '12-20bb'
        return '<12bb'

    # actual class counts per depth bucket
    by_bucket = defaultdict(lambda: defaultdict(int))
    bucket_n = defaultdict(int)
    for h in hands:
        cls = _starting_hand_class(h.get('cards'))
        if cls is None:
            continue
        bkt = _depth_bucket(h.get('eff_stack_bb')
                            or h.get('eff_stack_bb_at_decision'))
        by_bucket[bkt][cls] += 1
        bucket_n[bkt] += 1

    out = {}
    for bkt, classes in by_bucket.items():
        n = bucket_n[bkt]
        cls_rows = {}
        for cls, exp_freq in _CLASS_EXPECTED.items():
            actual = classes.get(cls, 0)
            expected = exp_freq * n
            # ratio of actual to expected; 1.0 = ran exactly neutral.
            ratio = (actual / expected) if expected > 0 else None
            cls_rows[cls] = {
                'actual': actual,
                'expected': round(expected, 1),
                'ratio_vs_expected': round(ratio, 3) if ratio is not None else None,
            }
        out[bkt] = {'n_hands': n, 'classes': cls_rows}

    # B174 (Ron 2026-05-24): phase x depth cross-tab. Depth alone cannot tell
    # "card-dead at 12bb in level 3" from "card-dead at 12bb on the bubble" —
    # same deck luck, very different cost. Dealt-card quality is pure
    # combinatorics (no `opp` denominator, no skill term), so it survives a
    # finer cut better than the made-hands layer: every cell still has an
    # exact expectation. Reports the premium-class ratio per (phase, depth)
    # cell; thin cells are tagged low_sample on hand count alone.
    by_phase_depth = {}
    for h in hands:
        cls = _starting_hand_class(h.get('cards'))
        if cls is None:
            continue
        phase = _phase_of(h)
        bkt = _depth_bucket(h.get('eff_stack_bb')
                            or h.get('eff_stack_bb_at_decision'))
        cell = by_phase_depth.setdefault((phase, bkt),
                                         {'n': 0, 'classes': defaultdict(int)})
        cell['n'] += 1
        cell['classes'][cls] += 1
    phase_depth_out = {}
    for (phase, bkt), cell in by_phase_depth.items():
        n = cell['n']
        cls_rows = {}
        for cls, exp_freq in _CLASS_EXPECTED.items():
            actual = cell['classes'].get(cls, 0)
            expected = exp_freq * n
            ratio = (actual / expected) if expected > 0 else None
            cls_rows[cls] = {
                'actual': actual,
                'expected': round(expected, 1),
                'ratio_vs_expected': round(ratio, 3) if ratio is not None else None,
            }
        phase_depth_out.setdefault(phase, {})[bkt] = {
            'n_hands': n,
            'classes': cls_rows,
            'low_sample': n < _PHASE_OPP_FLOOR,
        }
    # Order phases canonically.
    ordered_pd = {
        p: phase_depth_out[p]
        for p in (_PHASE_ORDER + sorted(set(phase_depth_out) - set(_PHASE_ORDER)))
        if p in phase_depth_out
    }

    return {
        'by_depth_bucket': out,
        'by_phase_depth': ordered_pd,
        'method': 'exact_combinatorial_depth_bucketed',
        'by_phase_depth_note': (
            'Dealt-hand class distribution vs exact combinatorial expectation, '
            'cross-tabbed by tournament phase and effective-stack depth. Still '
            'provably skill-free (pure combinatorics). A premium ratio < 1.0 '
            'in a bubble_zone / ft_zone cell = card-dead when ICM pressure was '
            f'highest. Cells with n_hands < {_PHASE_OPP_FLOOR} are low_sample.'),
        'note': ('Actual vs exact combinatorial expected dealt-hand class '
                 'distribution, bucketed by effective-stack depth. Provably '
                 'skill-free. ratio_vs_expected < 1.0 in a short bucket = '
                 'card-dead when it mattered. Does NOT card-adjust red line / '
                 'ATS / PFR — see known_limitations.'),
    }


def collect_made_hands_conversion(hands, made_hands_block=None,
                                  start_by_tid=None):
    """Layer 2 of the causal chain: made-hands conversion.

    v7.63 (Ron 2026-05-21): when start_by_tid is supplied, per-class value is
    realized net CHIPS / that tournament's starting stack — the same unit as
    the EAI / cooler / surface cEV layers, so the Result Attribution ledger
    sums in one unit. The legacy net_bb/eff_stack proxy is kept only for
    store-only callers that pass start_by_tid=None.

    Measures ONLY whether the flop cooperated — did Hero make sets / two-pair
    / flushes etc. above or below the expected rate — CONDITIONAL on the hands
    already dealt. It does not re-credit card quality (layer 1 owns that); it
    takes the dealt holdings as given (set rate is denominated only over
    pocket pairs, etc.) and scores the increment. Disjoint by construction.

    Conversion to stacks: (actual_rate - expected_rate) * opportunities *
    per-class value, where per-class value is the mean of (net_bb /
    eff_stack_bb) over Hero's OWN hands that made the class. Dividing by
    effective stack puts the layer in effective-stacks (same unit as EAI,
    coolers, red line) AND is the phase normalization — done once. An earlier
    version used mean(net_bb) * phase_weight, which left the layer in BB and
    double-applied the depth correction.

    PRECISION NOTE: per-class value uses realized net_bb/eff_stack as the
    value proxy. It is directional — a made hand's realized value is itself
    partly skill (how well Hero extracted) and partly the rest of the runout.
    The exact version would use the made hand's all-in equity value; that is
    folded into the same M1 precision pass as EAI. Flagged
    'rate_x_realized_stacks'.
    """
    try:
        from gem_made_hands import compute as _mh_compute
    except Exception:
        return {'available': False,
                'note': 'gem_made_hands import failed'}
    mh = made_hands_block or _mh_compute(hands)
    if not mh:
        return {'available': False, 'note': 'no made-hands data'}

    out_classes, total_gap_stacks = _made_hands_gap_for_subset(
        hands, mh, start_by_tid)

    result = {
        'available': True,
        'method': 'rate_x_realized_stacks',
        'classes': out_classes,
        'total_conversion_gap_stacks': round(total_gap_stacks, 4),
        'note': ('Conversion luck = (actual-expected rate) x opportunities x '
                 'per-class realized value, in effective-stacks. Conditional '
                 'on dealt hands (disjoint from dealt-card-quality layer). '
                 'Per-class value is realized net_bb/eff_stack proxy — exact '
                 'equity-value version folds into the M1 precision pass.'),
    }

    # B174 (Ron 2026-05-24): per-tournament-phase breakdown. A made-hand miss
    # on the bubble matters more than the same miss in level 3; this surfaces
    # WHERE in the tournament the conversion luck landed. Each phase cell runs
    # the made-hands module on that phase's hands only.
    #
    # NOT ADDITIVE — read this. The phase cells do NOT sum back to the session
    # aggregate, and that is structural, not a bug: each cell recomputes BOTH
    # the made-hands `expected` rate AND `per_class_value` (a mean of realized
    # stacks) on its own subset. A subset mean is a different, noisier number
    # than the session-wide mean, so sum(phase gaps) != aggregate gap. The
    # aggregate stays the authority for the session total; the phase split is
    # a directional view of WHERE luck concentrated, not an exact decomposition
    # of the total. Cells below _PHASE_OPP_FLOOR opportunities are tagged
    # low_sample — there, even the directional read is unreliable.
    by_phase = {}
    phase_partition = {}
    for h in hands:
        phase_partition.setdefault(_phase_of(h), []).append(h)
    for phase, ph_hands in phase_partition.items():
        ph_mh = _mh_compute(ph_hands)
        if not ph_mh:
            continue
        ph_classes, ph_total = _made_hands_gap_for_subset(
            ph_hands, ph_mh, start_by_tid)
        ph_opp = sum(c.get('opp', 0) for c in ph_classes.values())
        by_phase[phase] = {
            'n_hands': len(ph_hands),
            'classes': ph_classes,
            'total_conversion_gap_stacks': round(ph_total, 4),
            'total_opp': ph_opp,
            'low_sample': ph_opp < _PHASE_OPP_FLOOR,
        }
    # Order the phases canonically; unknown/extra phases trail.
    result['by_phase'] = {
        p: by_phase[p]
        for p in (_PHASE_ORDER + sorted(set(by_phase) - set(_PHASE_ORDER)))
        if p in by_phase
    }
    result['by_phase_additive'] = False
    result['by_phase_note'] = (
        'Conversion gap split by tournament phase (late_reg -> post_reg -> '
        'bubble_zone -> ft_zone -> post_bubble). NOT ADDITIVE: each cell '
        're-estimates the expected rate and per-class value on its own '
        'subset, so the cells do not sum to total_conversion_gap_stacks. '
        'Treat the split as "where did conversion luck concentrate", not as '
        'an exact decomposition of the session total. Cells with total_opp < '
        f'{_PHASE_OPP_FLOOR} are low_sample. ICM risk-premium weighting of the '
        'late phases is a separate deferred task (it would shift historical '
        'numbers).')
    return result


def _made_hands_gap_for_subset(hands, mh, start_by_tid):
    """B174: per-class conversion-gap computation for one hand subset.

    Extracted so both the session-aggregate and each tournament-phase cell run
    identical logic. `mh` is the made-hands module output computed on exactly
    this `hands` subset. Returns (out_classes dict, total_gap_stacks float).
    """
    from collections import defaultdict

    def _is_pp(c):
        return c and len(c) >= 2 and c[0][0] == c[1][0]

    # Identify made-class hands by hand_strength. All five classes the
    # made-hands module tracks must be covered, else a class with a real rate
    # gap but no value term silently scores 0.
    class_hands = defaultdict(list)
    for h in hands:
        hs = h.get('hand_strength')
        cards = h.get('cards')
        if hs in ('full_house', 'quads') and _is_pp(cards):
            class_hands['set'].append(h)        # set-derived boats/quads
        elif hs == 'trips' and _is_pp(cards):
            class_hands['set'].append(h)
        if hs == 'two_pair':
            class_hands['two_pair'].append(h)
        elif hs == 'flush':
            class_hands['flush'].append(h)
        elif hs == 'straight':
            class_hands['straight'].append(h)
        elif hs == 'full_house':
            class_hands['full_house'].append(h)

    out_classes = {}
    total_gap_stacks = 0.0
    for cls, cls_stats in mh.items():
        if not isinstance(cls_stats, dict) or 'rate' not in cls_stats:
            continue
        opp = cls_stats.get('opp', 0)
        actual = cls_stats.get('rate', 0) / 100.0
        expected = cls_stats.get('expected', 0) / 100.0
        made_hs = class_hands.get(cls, [])
        # per-class value. v7.63: with start_by_tid, value is realized net
        # CHIPS / tournament starting stack (the ledger unit). Without it,
        # the legacy net_bb/eff_stack effective-stacks proxy.
        stack_vals = []
        for h in made_hs:
            nb = h.get('net_bb')
            if nb is None:
                continue
            if start_by_tid is not None:
                tid = h.get('tournament_id') or h.get('tournament')
                start_t = start_by_tid.get(tid)
                bb_blind = h.get('bb_blind') or 0
                if start_t and bb_blind > 0:
                    # v7.63: realized net chips / tournament starting stack,
                    # clamped to [-1, 3] — the same bound the legacy
                    # net_bb/eff_stack proxy carried. Without it a single
                    # late-game stack-someone pot (huge chips at a huge
                    # blind) dominates the whole made-hands layer.
                    stack_vals.append(
                        max(-1.0, min((nb * bb_blind) / start_t, 3.0)))
            else:
                eff = h.get('eff_stack_bb') or 0
                if eff > 0:
                    stack_vals.append(max(-1.0, min(nb / eff, 3.0)))
        per_class_value_stacks = (sum(stack_vals) / len(stack_vals)
                                  if stack_vals else 0.0)
        # rate gap converted to a stack figure.
        rate_gap = actual - expected
        gap_hits = rate_gap * opp                     # extra/fewer hits
        gap_stacks = gap_hits * per_class_value_stacks
        out_classes[cls] = {
            'opp': opp,
            'actual_rate': round(actual * 100, 2),
            'expected_rate': round(expected * 100, 2),
            'rate_gap_pp': round(rate_gap * 100, 2),
            'per_class_value_stacks': round(per_class_value_stacks, 4),
            'conversion_gap_stacks': round(gap_stacks, 4),
        }
        total_gap_stacks += gap_stacks
    return out_classes, total_gap_stacks


def collect_small_mistakes(hands, mistakes_block):
    """Small-mistake spots with phase weight attached. cev_cost is None —
    GEM mistake records are flagged spots, not EV-quantified. This collects
    the spots + phase weight so that once mistake-EV-quantification lands,
    the cEV cost is a trivial multiply. DEFERRED dependency, documented."""
    if not mistakes_block:
        return {'n': 0, 'hands': [], 'note': 'mistake-EV-quantification pending'}
    hands_by_id = {h.get('id'): h for h in hands}
    rows = []
    for m in mistakes_block:
        hid = m.get('id')
        h = hands_by_id.get(hid)
        eff = (h.get('eff_stack_bb') if h else None) or m.get('stack_bb') or 0
        rows.append({
            'hand_id': hid,
            'type': m.get('type', ''),
            'confidence': m.get('confidence', ''),
            'eff_stack_bb': eff,
            'phase_weight': round(phase_weight(eff), 3),
            'cev_cost': None,   # pending mistake-EV-quantification
        })
    return {'n': len(rows), 'hands': rows,
            'note': 'cev_cost pending mistake-EV-quantification step'}


def collect_all(hands, stats, analyst_commentary, per_tournament_cev=None):
    """Top-level background collector. Returns one structure with every
    cEV/stack axis. Store-only — nothing here drives the report yet."""
    from gem_cev import compute_eai_cev_per_stack

    eai_block = (stats or {}).get('eai', {})
    cooler_block = (stats or {}).get('coolers', {})
    mistakes_block = (stats or {}).get('mistakes', [])

    return {
        '_doc': ('Background cEV/stack attribution collection. Store-only. '
                 'Inputs for the eventual Result Attribution ledger (gated '
                 'on precise EAI from ICM module M1) and the cEV-denominated '
                 'leaks table. Layers form a strict causal chain — dealt '
                 'cards -> made-hands conversion (conditional on the deal) -> '
                 'EAI luck (conditional on equity got-in-with) — so they are '
                 'disjoint and do not double-count.'),
        'dealt_card_quality': collect_dealt_card_quality(hands),
        'made_hands_conversion': collect_made_hands_conversion(hands),
        'eai_luck': compute_eai_cev_per_stack(hands, eai_block,
                                              per_tournament_cev or {}),
        'red_line': collect_red_line(hands),
        'cooler_luck': collect_cooler_luck(hands, cooler_block),
        'read_dependent_bucket': collect_read_dependent_bucket(
            hands, analyst_commentary),
        'small_mistakes': collect_small_mistakes(hands, mistakes_block),
        'deferred': {
            'precise_eai': 'real equity + ICM weighting -> ICM module M1',
            'mistake_ev_cost': 'mistake-EV-quantification step not yet built',
            'made_hands_exact_value': ('per-class value uses realized net_bb '
                                       'proxy; exact equity-value folds into '
                                       'the M1 precision pass'),
            'balancing_ledger': 'waits on precise EAI for clean skill residual',
        },
        'known_limitations': {
            'card_quality_confound': (
                'Dealt-card quality is a COMMON CAUSE, not an isolated layer. '
                'A cold/hot run of cards leaks into red line (fewer/more '
                'uncontested pots to win), ATS, PFR, AF and made-hands '
                'simultaneously. The raw red-line / ATS / PFR / AF figures '
                'are therefore NOT card-adjusted: a card-dead session can '
                'show a red-line "leak" that is really just deck luck. The '
                'dealt_card_quality layer measures the deck luck cleanly '
                '(exact combinatorics, depth-bucketed) but does not yet '
                'subtract it out of the downstream metrics.'),
            'deconfound_path': (
                'Correlate phase-level card luck (dealt_card_quality '
                'ratio_vs_expected per depth bucket) against phase-level red '
                'line / ATS across many sessions — a phase-bucketed '
                'regression, far more stable than a per-hand model. Deferred '
                'until sample size allows; tractable because dealt_card_'
                'quality now produces the right intermediate signal.'),
        },
    }


if __name__ == '__main__':
    import sys
    hands = json.load(open(sys.argv[1] if len(sys.argv) > 1
                           else 'gem_hands.json'))
    stats = json.load(open('gem_stats.json'))
    # Analyst commentary: prefer the live session_analysis file, fall back to
    # whatever is baked into gem_report_data.json.
    analyst = {}
    import glob as _glob
    for _ap in (_glob.glob('session_analysis_*.json')
                + ['gem_report_data.json']):
        try:
            _d = json.load(open(_ap))
            if _ap.startswith('session_analysis'):
                analyst = {k: v for k, v in _d.items()
                           if not k.startswith('_')}
            else:
                analyst = _d.get('analyst_commentary', {}) or {}
            if analyst:
                break
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    try:
        from gem_cev import compute_cev_per_stack
        pt_cev = compute_cev_per_stack(hands)['per_tournament']
    except Exception:
        pt_cev = {}

    result = collect_all(hands, stats, analyst, pt_cev)

    rl = result['red_line']
    print("=== RED LINE (non-showdown, effective-stacks) ===")
    print(f"{'tid':>11} {'nonSD':>6} {'raw_bb':>10} {'stacks':>10}")
    tot_raw = tot_s = 0.0
    for tid, d in sorted(rl.items(), key=lambda kv: kv[1]['red_line_stacks']):
        print(f"{tid:>11} {d['n_hands']:>6} {d['red_line_raw_bb']:>10,.1f} "
              f"{d['red_line_stacks']:>10,.3f}")
        tot_raw += d['red_line_raw_bb']
        tot_s += d['red_line_stacks']
    print(f"{'TOTAL':>11} {'':>6} {tot_raw:>10,.1f} {tot_s:>10,.3f}")

    cl = result['cooler_luck']
    print("\n=== COOLER LUCK (effective-stacks lost) ===")
    for tid, d in sorted(cl.items(),
                         key=lambda kv: kv[1]['cooler_loss_stacks']):
        print(f"  {tid}  {d['n_coolers']} cooler(s)  "
              f"{d['cooler_loss_stacks']:+.3f} stacks")

    rb = result['read_dependent_bucket']
    print(f"\n=== READ-DEPENDENT BUCKET — {rb['n_hands']} hands ===")
    if rb['n_hands']:
        print(f"  sum net: {rb['sum_net_bb']:+.1f} BB | "
              f"sum cEV: {rb['sum_cev_stacks']:+.3f} stacks")
        print(f"  positive: {rb['positive']['n']} hands "
              f"({rb['positive']['net_bb']:+.1f} BB) | "
              f"negative: {rb['negative']['n']} hands "
              f"({rb['negative']['net_bb']:+.1f} BB)")

    sm = result['small_mistakes']
    print(f"\n=== SMALL MISTAKES — {sm['n']} spots collected "
          f"(cev_cost pending) ===")

    dcq = result['dealt_card_quality']
    print("\n=== DEALT-CARD QUALITY (actual vs exact expected, by depth) ===")
    bkt_order = ['40bb+', '20-40bb', '12-20bb', '<12bb']
    by_bkt = dcq.get('by_depth_bucket', {})
    for bkt in bkt_order:
        d = by_bkt.get(bkt)
        if not d:
            continue
        # show premium-pair + premium_ax ratio — the "card-dead when short" read
        prem = d['classes'].get('premium_pair', {})
        pax = d['classes'].get('premium_ax', {})
        pr = prem.get('ratio_vs_expected')
        ar = pax.get('ratio_vs_expected')
        print(f"  {bkt:>9} ({d['n_hands']:>4} hands): "
              f"premium-pair {pr if pr is not None else '—'}x exp, "
              f"AK {ar if ar is not None else '—'}x exp")
    print("  (ratio <1.0 in a short bucket = card-dead when it mattered)")

    mhc = result['made_hands_conversion']
    print("\n=== MADE-HANDS CONVERSION (rate gap x value, effective-stacks) ===")
    if mhc.get('available'):
        for cls, d in mhc['classes'].items():
            print(f"  {cls:>10}: {d['actual_rate']:>5.1f}% vs "
                  f"{d['expected_rate']:>5.1f}% exp "
                  f"({d['rate_gap_pp']:+.1f}pp) -> "
                  f"{d['conversion_gap_stacks']:+.3f} stacks")
        print(f"  total conversion luck: "
              f"{mhc['total_conversion_gap_stacks']:+.3f} stacks")
    else:
        print(f"  unavailable: {mhc.get('note')}")

