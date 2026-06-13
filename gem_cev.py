"""gem_cev.py — cEV/stack background tracking (Ron 2026-05-20).

STORE-ONLY MODULE. Computes per-tournament cEV/stack (chip-EV expressed in
units of one starting stack) and stores it alongside the existing financial
data. NOTHING in the report depends on this yet — it is pure background
accumulation so the metric has history when/if Ron decides to use it.

WHY cEV/stack: BB/100 divides by the *current* blind, which inflates through
an MTT, so it shrinks late-stage pots and is biased toward early phases.
cEV/stack divides by a *fixed* starting-stack reference, so a pot is scored
by how many starting stacks of chips changed hands — phase-neutral.

  cev_per_stack = (sum of Hero net chips over the tournament) / starting_chips
  net_chips for a hand = net_bb * bb_blind   (exact; verified against HH)

STARTING-STACK RESOLUTION CASCADE (confidence order):
  1. l1_observed       — earliest hand we have for the tournament is Level 1,
                         so Hero's chip count on that hand IS the starting
                         stack. Exact, no assumptions.
  2. ladder_extrapolated — earliest hand is L2+, but its (level, sb, bb)
                         matches a known GG ladder progression, so the L1
                         starting stack is identified from the structure.
  3. table             — tournament_structures.json name_overrides entry.
                         Marked low-confidence if the override is 'unverified'.
  4. unresolved        — none of the above. cev_per_stack stored as None and
                         skipped from aggregates. An honest gap beats a wrong
                         denominator.

Re-entries / late-reg: handled naturally — tier 1 only fires when the earliest
hand is genuinely L1; a re-entry that sat down mid-tournament has its earliest
hand at L2+ and falls through to tier 2/3/4.
"""

import json
import os
import re
from collections import defaultdict

_STRUCT_PATHS = [
    'tournament_structures.json',
    '/home/claude/tournament_structures.json',
    '/mnt/project/tournament_structures.json',
]


def _load_structures():
    for p in _STRUCT_PATHS:
        try:
            with open(p, encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return {}


def _ladder_l1_starting_chips(level, sb, bb, structs):
    """Tier 2: given an observed (level, sb, bb), try to match a known GG
    ladder progression and return the L1 starting stack for that structure.
    Returns (starting_chips, ladder_name) or (None, None)."""
    progressions = structs.get('ladder_progressions', {}) or {}
    ladders = structs.get('ladders', {}) or {}
    for lname, prog in progressions.items():
        if lname.startswith('_'):
            continue
        for (lv, psb, pbb) in prog:
            if lv == level and psb == sb and pbb == bb:
                # Found the structure. Its L1 is the first entry.
                l1 = prog[0]
                l1_key = f"{l1[1]}/{l1[2]}"
                meta = ladders.get(l1_key)
                if meta and meta.get('starting_chips'):
                    return meta['starting_chips'], lname
    return None, None


def _resolve_starting_chips(tid, name, earliest, structs):
    """Run the resolution cascade for one tournament.

    earliest: dict {level, sb, bb, hero_chips} for the earliest hand we hold.
    Returns dict {starting_chips, source, confidence, note}.
    """
    lvl = earliest.get('level')
    sb = earliest.get('sb')
    bb = earliest.get('bb')
    hero_chips = earliest.get('hero_chips')

    # Tier 1 — earliest observed hand is Level 1: chip count IS the start.
    if lvl == 1 and hero_chips:
        # The earliest hand we hold may be a deal or two into Level 1 (a
        # blind/ante already posted), so the read can be a hair off the true
        # start. If it is within 5% of a known GG standard stack, snap to the
        # standard — that is what it actually was. Otherwise keep the raw read
        # (Hero genuinely already won/lost chips before our earliest hand).
        ladders = structs.get('ladders', {}) or {}
        snap = structs.get('snap_standards', {}) or {}
        standards = sorted(snap.get('values') or
                           {m['starting_chips'] for m in ladders.values()
                            if isinstance(m, dict) and m.get('starting_chips')})
        snapped = None
        for std in standards:
            if abs(hero_chips - std) <= 0.05 * std:
                snapped = std
                break
        if snapped and snapped != hero_chips:
            return {'starting_chips': snapped, 'source': 'l1_observed',
                    'confidence': 'exact',
                    'note': f'Level-1 hand observed (Hero {hero_chips:,}); '
                            f'snapped to standard start {snapped:,}'}
        return {'starting_chips': hero_chips, 'source': 'l1_observed',
                'confidence': 'exact' if snapped else 'high',
                'note': (f'Level-1 hand observed; Hero held {hero_chips:,}'
                         + ('' if snapped else
                            ' — no standard-stack match, may be a few deals '
                            'into L1'))}

    # Tier 2 — extrapolate L1 from the blind ladder.
    if lvl and sb and bb:
        sc, lname = _ladder_l1_starting_chips(lvl, sb, bb, structs)
        if sc:
            return {'starting_chips': sc, 'source': 'ladder_extrapolated',
                    'confidence': 'high',
                    'note': f'Earliest hand L{lvl} {sb}/{bb} matched '
                            f'ladder "{lname}" -> L1 start {sc:,}'}

    # Tier 3 — name_overrides table.
    overrides = structs.get('name_overrides', {}) or {}
    ov = overrides.get(name)
    if ov is not None:
        # Conflict handling: a list means the name has date-dependent values.
        if isinstance(ov, list):
            return {'starting_chips': None, 'source': 'unresolved',
                    'confidence': 'none',
                    'note': f'name_overrides has {len(ov)} date-dependent '
                            f'entries for "{name}" — ambiguous, not guessed'}
        if isinstance(ov, dict):
            sc = ov.get('starting_chips')
            conf = ov.get('confidence', 'unverified')
            return {'starting_chips': sc, 'source': 'table',
                    'confidence': 'low' if conf == 'unverified' else 'medium',
                    'note': ov.get('note', 'name_overrides table entry')}
        if isinstance(ov, (int, float)):
            return {'starting_chips': int(ov), 'source': 'table',
                    'confidence': 'medium', 'note': 'name_overrides table entry'}

    # Tier 4 — unresolved. Honest gap.
    return {'starting_chips': None, 'source': 'unresolved',
            'confidence': 'none',
            'note': f'earliest hand L{lvl} {sb}/{bb} — not L1, no ladder '
                    f'match, no table entry'}


def compute_cev_per_stack(hands):
    """Main entry point. Given the parsed hand list, return a dict:

      {
        'per_tournament': { tid: {name, starting_chips, starting_chips_source,
                                  starting_chips_confidence, net_chips,
                                  cev_per_stack, n_hands, resolution_note} },
        'session': {net_chips_total, cev_per_stack_total, n_resolved,
                    n_unresolved},
      }

    cev_per_stack is None for unresolved tournaments and they are skipped
    from the session aggregate.
    """
    structs = _load_structures()

    # Earliest hand + net-chip sum, per tournament.
    earliest = {}          # tid -> {level, sb, bb, hero_chips, ts}
    net_chips = defaultdict(float)
    n_hands = defaultdict(int)
    names = {}

    for h in hands:
        tid = h.get('tournament_id') or h.get('tournament')
        if not tid:
            continue
        names[tid] = h.get('tournament', '')
        n_hands[tid] += 1

        bb_blind = h.get('bb_blind') or 0
        net_bb = h.get('net_bb') or 0
        # Exact: chips = bb * bb_blind. Verified against raw HH.
        net_chips[tid] += net_bb * bb_blind

        lvl = h.get('level')
        sb = h.get('sb_blind')
        bb = h.get('bb_blind')
        hero_chips = h.get('hero_stack_chips')
        if hero_chips is None:
            # Reconstruct from stack_bb * bb_blind when chips not stored.
            sbb = h.get('stack_bb')
            if sbb is not None and bb:
                hero_chips = int(round(sbb * bb))
        # Earliest hand: order by level, then by the TM hand-id number, which
        # is monotonic in deal order. The datetime field is not reliably
        # populated, so a timestamp tiebreak picked an arbitrary L1 hand —
        # and a hand 2-3 deals into Level 1 has already drifted off the
        # starting stack (blinds posted, pots played).
        hid = h.get('id', '')
        hid_num = int(re.sub(r'\D', '', hid) or 0)
        key = (lvl if lvl is not None else 9999, hid_num)
        if tid not in earliest or key < earliest[tid]['_key']:
            earliest[tid] = {'_key': key, 'level': lvl, 'sb': sb, 'bb': bb,
                             'hero_chips': hero_chips}

    per_tournament = {}
    sess_net = 0.0
    sess_cev_sum = 0.0       # Σ per-tournament (net_t / start_t) — decomposable
    n_resolved = n_unresolved = 0
    n_hands_resolved = 0
    for tid in names:
        res = _resolve_starting_chips(tid, names[tid], earliest.get(tid, {}),
                                      structs)
        sc = res['starting_chips']
        nc = round(net_chips[tid], 2)
        cev = round(nc / sc, 4) if sc else None
        if cev is not None:
            sess_net += nc
            sess_cev_sum += nc / sc
            n_resolved += 1
            n_hands_resolved += n_hands[tid]
        else:
            n_unresolved += 1
        per_tournament[tid] = {
            'name': names[tid],
            'starting_chips': sc,
            'starting_chips_source': res['source'],
            'starting_chips_confidence': res['confidence'],
            'net_chips': nc,
            'cev_per_stack': cev,
            'n_hands': n_hands[tid],
            'resolution_note': res['note'],
        }

    # v7.63 (Ron 2026-05-21): the session cEV is the SUM of per-tournament
    # (net_t / start_t). This is the decomposable, chip-conserving form: any
    # layer's cEV is Σ over its events of (event_chips / start_of_that_
    # tournament), so layers sum to the surface and the ledger balances. The
    # old Σnet/mean_start form is NOT decomposable (no layer can be written
    # as Σ event_chips/mean_start and still nest) and silently weighted
    # tournaments by absolute chip magnitude. Kept as _meanstart for
    # back-compat only — it is not the spine.
    resolved_starts = [pt['starting_chips'] for pt in per_tournament.values()
                       if pt['cev_per_stack'] is not None]
    mean_start = (sum(resolved_starts) / len(resolved_starts)
                  if resolved_starts else None)
    sess_cev = round(sess_cev_sum, 4) if n_resolved else None
    sess_cev_meanstart = (round(sess_net / mean_start, 4)
                          if mean_start else None)
    # Per-100 rate — volume-invariant. v7.63: denominator is RESOLVED hands
    # only (n_hands_resolved), matching the numerator's scope. Dividing a
    # resolved-tournament numerator by all-tournament hands diluted the rate.
    sess_n_hands = sum(n_hands.values()) or 0
    sess_cev_per_100 = (round(sess_cev / n_hands_resolved * 100, 4)
                        if sess_cev is not None and n_hands_resolved else None)

    return {
        'per_tournament': per_tournament,
        'session': {
            'net_chips_total': round(sess_net, 2),
            'cev_per_stack_total': sess_cev,
            'cev_per_stack_total_meanstart': sess_cev_meanstart,
            'cev_per_stack_per_100': sess_cev_per_100,
            'n_hands': sess_n_hands,
            'n_hands_resolved': n_hands_resolved,
            'mean_starting_stack': round(mean_start, 1) if mean_start else None,
            'n_resolved': n_resolved,
            'n_unresolved': n_unresolved,
        },
    }


def compute_eai_cev_per_stack(hands, eai_block, per_tournament_cev):
    """EAI luck axis, expressed in effective-stacks-at-risk (Ron 2026-05-20).

    IMPORTANT denominator correction. An earlier draft normalized each all-in
    swing by the tournament STARTING stack — that breaks badly late game:
    chip totals balloon through an MTT (a 3M stack at L37 is not 120 starting
    stacks of value, it is still one stack of tournament life), so chips/
    starting_stack produced nonsense like -84 stacks from one tournament.

    Correct unit for a per-all-in luck swing is the EFFECTIVE STACK AT THAT
    ALL-IN: "how much of the tournament life I had at risk did variance
    swing." That is bounded (you cannot swing more than the stack in play)
    and it is the ICM-flavoured quantity the luck axis actually wants.

    Per all-in spot:
      - eff_stack_chips = eff_stack_bb * bb_blind  (life at risk)
      - realized_frac   = net_bb / eff_stack_bb    (result as a fraction of
                          the stack at risk; +1.0 = doubled, -1.0 = busted)
      - expected_frac   = 2*win_rate - 1           (category expectation)
      - eai_swing       = realized_frac - expected_frac, in stacks-at-risk
      Summed per tournament -> total luck swing in effective-stack units.

    PRECISION NOTE: still category-based (ahead/flip/behind win-rates), not
    true equity. Strict improvement on approx_bb_variance. Exact version
    (real equity per all-in via phevaluator, ICM-weighted) is deferred to
    ICM module M1. Flagged 'category_approx_effstack'.
    """
    if not eai_block or not eai_block.get('hands'):
        return {}

    # B140: expected win-rate per equity category is a FIXED population
    # baseline. eai_block[cat]['pct'] is THIS session's realized rate —
    # feeding that as "expected" zeroes the luck signal (swing becomes a
    # residual around the session mean). Fixed baselines only.
    cat_winrate = {'ahead': 0.926, 'flip': 0.442, 'behind': 0.318}
    hands_by_id = {h.get('id'): h for h in hands}

    by_tid = defaultdict(lambda: {'n': 0, 'swing': 0.0, 'skipped': 0})
    for e in eai_block['hands']:
        h = hands_by_id.get(e.get('id'))
        if not h:
            continue
        tid = h.get('tournament_id') or h.get('tournament')
        eff = h.get('eff_stack_bb') or 0
        net_bb = h.get('net_bb') or 0
        b = by_tid[tid]
        b['n'] += 1
        if eff <= 0:
            b['skipped'] += 1
            continue
        # realized result as a fraction of the effective stack at risk.
        # Clamp to [-1, +1.x]: you cannot lose more than the stack; a win can
        # exceed 1 stack when villain covers, so cap winning side generously.
        realized_frac = net_bb / eff
        realized_frac = max(-1.0, min(realized_frac, 3.0))
        wr = cat_winrate.get(e.get('category'), 0.5)
        expected_frac = 2 * wr - 1
        b['swing'] += realized_frac - expected_frac

    out = {}
    for tid, b in by_tid.items():
        scored = b['n'] - b['skipped']
        out[tid] = {
            'n_allins': b['n'],
            'eai_swing_stacks': round(b['swing'], 4) if scored else None,
            'skipped_allins': b['skipped'],
            'method': 'category_approx_effstack',
        }
    return out


# ============================================================
# v7.61: PER-LAYER VARIANCE cEV (real chip-derived, not BB-translated)
# ============================================================
def _hand_net_chips(h):
    """Net result of a hand in CHIPS = net_bb * the hand's big blind."""
    return (h.get('net_bb') or 0) * (h.get('bb_blind') or 0)


def _start_by_tid(per_tournament_cev):
    """tid -> resolved starting stack (chips). Unresolved tournaments absent.

    The single source of the cEV denominator. Every cEV layer divides each
    event's chips by the starting stack of the tournament that event belongs
    to — so the layers share one unit with the surface and the ledger sums.
    """
    pt = (per_tournament_cev or {}).get('per_tournament', {}) or {}
    return {tid: d['starting_chips'] for tid, d in pt.items()
            if isinstance(d, dict) and d.get('starting_chips')}


def _is_premium_deal(cards):
    """AA / KK / QQ / AK — matches card_quality 'prem_strong'."""
    if not cards or len(cards) != 2:
        return False
    r0, r1 = cards[0][0], cards[1][0]
    if r0 == r1:
        return r0 in ('A', 'K', 'Q')
    return {r0, r1} == {'A', 'K'}


def compute_variance_cev(hands, stats, results_attribution,
                         per_tournament_cev=None):
    """
    Per-layer variance cEV, in cEV-per-stack (chips / mean starting stack) —
    computed from actual chips, NOT translated from the BB attribution.

    EAI and Cooler are genuine chip attributions: EAI sums each all-in's
    realized-minus-expected chip swing; Cooler uses the session's actual
    average cooler chip loss times the count deviation from expected.
    Made-hands uses the made-hands conversion module's stack figure.
    Card quality has NO realized-chip measure — dealt-card luck is a common
    cause that flows through the EAI / made-hands layers (a separate chip
    figure would double-count), so it returns cev_stacks=None by design.

    Returns {available, mean_starting_stack, eai, cooler, made_hands,
    card_quality} where each layer is {cev_stacks, method, ...}.
    """
    n = (stats.get('volume', {}) or {}).get('hands', 0) or len(hands) or 1
    sess = (per_tournament_cev or {}).get('session')
    if not sess or not (per_tournament_cev or {}).get('per_tournament'):
        per_tournament_cev = compute_cev_per_stack(hands)
        sess = per_tournament_cev['session']
    start_by_tid = _start_by_tid(per_tournament_cev)
    if not start_by_tid:
        return {'available': False, 'reason': 'no_resolved_starting_stacks'}
    # v7.63: per-100 normalization uses RESOLVED hands only. Every layer's
    # numerator sums chips over resolved tournaments, so the denominator must
    # share that scope or the rate is diluted by ~n_unresolved hands.
    n_res = sess.get('n_hands_resolved') or n
    mean_start = sess.get('mean_starting_stack') or 0
    by_id = {h.get('id'): h for h in hands if h.get('id')}
    tid_by_id = {h.get('id'): (h.get('tournament_id') or h.get('tournament'))
                 for h in hands if h.get('id')}
    out = {'available': True, 'mean_starting_stack': mean_start,
           'n_hands_resolved': n_res,
           'unit': 'chips / tournament starting stack'}

    # ---- EAI all-in luck ----
    # B140: expected win-rate per equity category is a FIXED population
    # baseline (way-ahead 92.6 / flip 44.2 / way-behind 31.8), not this
    # session's realized rate (which would collapse the luck signal to ~0).
    # v7.63 (Ron 2026-05-21): REVERTS B142's effective-stacks-at-risk reframe.
    # B142 bounded each all-in by dividing by the EFFECTIVE stack at that
    # all-in — but that put the EAI layer in a different unit from the cEV
    # surface (chips / tournament STARTING stack), so the ledger rows no
    # longer shared a unit and could not sum. The genuine fix is to keep
    # chips and divide by the per-tournament STARTING stack — the SAME
    # denominator the surface uses — NOT a session-wide mean, NOT the
    # effective stack. Late-game all-ins legitimately carry more chip-EV;
    # that is real chip accounting and the overfit guard flags it when the
    # corrections overrun the surface. Unit: tournament starting stacks.
    eai = stats.get('eai', {}) or {}
    cat_wr = {'ahead': 0.926, 'flip': 0.442, 'behind': 0.318}
    eai_cev = 0.0
    n_ai = 0
    n_ai_skipped = 0
    for e in eai.get('hands', []) or []:
        h = by_id.get(e.get('id'))
        if not h:
            continue
        start_t = start_by_tid.get(tid_by_id.get(e.get('id')))
        eff = h.get('eff_stack_bb') or 0
        bb_blind = h.get('bb_blind') or 0
        if not start_t or eff <= 0 or bb_blind <= 0:
            n_ai_skipped += 1
            continue
        realized_chips = (h.get('net_bb') or 0) * bb_blind
        wr = cat_wr.get(e.get('category'), 0.5)
        # expected net chips for this all-in given its equity category:
        # (2*wr - 1) is expected net as a fraction of the stake at risk.
        expected_chips = (2 * wr - 1) * eff * bb_blind
        eai_cev += (realized_chips - expected_chips) / start_t
        n_ai += 1
    _eai = round(eai_cev, 4)
    out['eai'] = {
        'cev_stacks': _eai,
        'cev_per_100': round(_eai / n_res * 100, 4),
        'n_events': n_ai,
        'n_skipped': n_ai_skipped,
        'method': ('per-all-in (realized - expected) chips / tournament '
                   'starting stack — chip-conserving, same unit as surface'),
    }

    # ---- Cooler frequency: count deviation x avg loss, in starting stacks --
    # v7.63: each losing cooler's chip loss / that tournament's starting
    # stack (was: effective-stacks-at-risk, B142 — wrong unit for the ledger).
    co = stats.get('coolers', {}) or {}
    _cl_fracs = []
    for c in (co.get('hands', []) or []):
        if c.get('direction') != 'negative':
            continue
        h = by_id.get(c.get('id'))
        if not h:
            continue
        start_t = start_by_tid.get(tid_by_id.get(c.get('id')))
        bb_blind = h.get('bb_blind') or 0
        if not start_t or bb_blind <= 0:
            continue
        _cl_fracs.append(abs((h.get('net_bb') or 0) * bb_blind) / start_t)
    avg_cooler_loss = (sum(_cl_fracs) / len(_cl_fracs)) if _cl_fracs else 0.0
    exp_mid = (co.get('expected_low', 0.15) + co.get('expected_high', 0.30)) / 2.0
    expected_coolers = exp_mid * n_res / 100.0
    cooler_delta = (co.get('count', 0) or 0) - expected_coolers
    _cooler = round(-cooler_delta * avg_cooler_loss, 4)
    out['cooler'] = {
        'cev_stacks': _cooler,
        'cev_per_100': round(_cooler / n_res * 100, 4),
        'n_events': co.get('count', 0) or 0,
        'expected': round(expected_coolers, 2),
        'avg_loss_stacks': round(avg_cooler_loss, 4),
        'method': ('count deviation from expected x avg cooler chip loss / '
                   'tournament starting stack'),
    }

    # ---- Made hands: conversion-gap stacks from the made-hands module ----
    # v7.63: pass start_by_tid so the module's per-class value is realized
    # net chips / tournament starting stack (same unit), not net_bb/eff_stack.
    mh_total = None
    try:
        from gem_cev_attribution import collect_made_hands_conversion
        mh = collect_made_hands_conversion(hands, start_by_tid=start_by_tid)
        mh_total = mh.get('total_conversion_gap_stacks')
        if mh_total is None and mh.get('classes'):
            mh_total = sum((c.get('conversion_gap_stacks') or 0)
                           for c in mh['classes'].values())
    except Exception:
        mh_total = None
    _mh_stacks = round(mh_total, 4) if mh_total is not None else None
    out['made_hands'] = {
        'cev_stacks': _mh_stacks,
        'cev_per_100': (round(_mh_stacks / n_res * 100, 4)
                        if _mh_stacks is not None else None),
        'method': ('made-hands rate gap x realized per-class value '
                   '(chips / tournament starting stack)'),
    }

    # ---- Card quality: count deviation x per-premium expected value ----
    # Dealt-card luck has NO clean realized-chip measure: the realized value
    # of premium hands is the made-hands / EAI luck of those same hands
    # (double-count), and it can flip sign. So card quality stays a count
    # deviation x the EXPECTED value of a premium hand. 5.0 BB/premium over a
    # ~100 BB starting stack => 0.05 starting-stacks/premium — already in the
    # ledger unit. This is the one model-expected layer.
    PREMIUM_VALUE_STACKS = 0.05  # 5.0 BB / 100 BB starting stack
    cq = stats.get('card_quality', {}) or {}
    prem_pct = cq.get('prem_strong_pct', 0) or 0
    prem_delta_n = (prem_pct - 5.9) / 100.0 * n_res
    prem = [h for h in hands if _is_premium_deal(h.get('cards'))]
    _cq_stacks = round(prem_delta_n * PREMIUM_VALUE_STACKS, 4)
    out['card_quality'] = {
        'cev_stacks': _cq_stacks,
        'cev_per_100': round(_cq_stacks / n_res * 100, 4),
        'n_events': len(prem),
        'prem_delta_n': round(prem_delta_n, 2),
        'method': ('premium-count deviation from 5.9% baseline x per-premium '
                   'expected value (0.05 starting stacks) — model-expected, '
                   'not realized-chip: dealt-card luck has no clean realized '
                   'measure (would double-count made-hands / EAI).'),
    }
    out['n_hands'] = n
    out['n_hands_resolved'] = n_res
    return out


if __name__ == '__main__':
    import sys
    hands_path = sys.argv[1] if len(sys.argv) > 1 else 'gem_hands.json'
    with open(hands_path) as f:
        hands = json.load(f)
    result = compute_cev_per_stack(hands)
    pt = result['per_tournament']
    print(f"{'tid':>11} {'start':>8} {'src':>20} {'net_chips':>13} "
          f"{'cEV/stk':>9}  name")
    for tid, d in sorted(pt.items(),
                         key=lambda kv: (kv[1]['cev_per_stack'] is None,
                                         -(kv[1]['cev_per_stack'] or 0))):
        sc = f"{d['starting_chips']:,}" if d['starting_chips'] else '—'
        cev = f"{d['cev_per_stack']:+.3f}" if d['cev_per_stack'] is not None else 'unresolved'
        print(f"{tid:>11} {sc:>8} {d['starting_chips_source']:>20} "
              f"{d['net_chips']:>13,.0f} {cev:>9}  {d['name'][:30]}")
    s = result['session']
    print(f"\nSession: net {s['net_chips_total']:+,.0f} chips | "
          f"cEV/stack total {s['cev_per_stack_total']} | "
          f"{s['n_resolved']} resolved, {s['n_unresolved']} unresolved")

    # EAI-in-stacks luck axis (category-approx) — store-only demo.
    try:
        with open('gem_stats.json') as f:
            _stats = json.load(f)
        eai_block = _stats.get('eai', {})
        eai_cev = compute_eai_cev_per_stack(hands, eai_block, pt)
        if eai_cev:
            print("\n--- EAI luck axis (category-approx, effective-stacks-at-risk) ---")
            print(f"{'tid':>11} {'allins':>6} {'swing_stacks':>13}  name")
            tot = 0.0
            for tid, d in sorted(eai_cev.items(),
                                 key=lambda kv: -(kv[1]['eai_swing_stacks'] or 0)):
                ss = (f"{d['eai_swing_stacks']:+.3f}"
                      if d['eai_swing_stacks'] is not None else 'n/a')
                nm = pt.get(tid, {}).get('name', tid)[:30]
                print(f"{tid:>11} {d['n_allins']:>6} {ss:>13}  {nm}")
                if d['eai_swing_stacks'] is not None:
                    tot += d['eai_swing_stacks']
            print(f"\nSession EAI luck: {tot:+.2f} effective-stacks "
                  f"(positive = ran above category expectation)")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

