#!/usr/bin/env python3
"""
GEM Analyzer v7.18 — Session analysis, metrics, deviations, output.
Imports parsed hands from gem_parser.py, computes all GEM metrics.

Usage: python3 gem_analyzer.py /path/to/hand/files/ [session_name]

Outputs:
  - gem_stats.json: Complete stats for report generation
  - gem_hands.json: All parsed hands with classifications
  - gem_report_data.json: Pre-staged report data (v7.12)
  - GTO Wizard export file (auto-generated, v7.12)
  - Console: Summary + sanity checks

v7.18: HH rename — Appendix L detectors relabeled from (H5)/(H10#1)
  to (HH5)/(HH10#1) to eliminate namespace collision with original
  Appendix H short-stack crash course rules. Detector logic unchanged.
  Test assertions and mistake count pins updated.

v7.17: M1 and M6 detectors wired in (MechanicsOfPoker Appendix M).
  M1 flags Hero turn-checks in HU SRP after flop X/X as PFR as MARGINAL
  missed-delayed-c-bet candidates (population turn CR vs delayed cbet
  is <2% — minbet turn range is high-EV exploit). Direct fix for Ron
  leak #1 (check-call-call-showdown OOP PFR). M6 flags Hero barrels
  in HU 3BPs on double-FD turn textures with medium-equity hands
  (TP, OESD, combo draw, non-nut FD) as MARGINAL review candidates —
  population turn CR rate >8% on these textures forces Hero to fold
  and lose the equity. Barrel air, check equity on these turns.
  Other M-rules (M2-M5, M7-M25) are manual-only drill-mode prompts —
  require semantic range analysis or villain-specific metadata.

v7.16: HH5 and HH10#1 detectors wired in (Hungry Horse Appendix L).
  HH5 flags Hero river-overbet-bluffs at ≤100BB on boards where
  villain could have TP as MARGINAL review candidates. HH10#1 flags
  Hero continuing with TP or weaker vs villain check-back-flop +
  raise-turn line as CLEAR mistakes (trap range, never bluffed).
  Other H-rules (HH1-HH4 sizing, HH6-HH7 opponent selection, HH8-HH9-HH14
  OOP protocols, HH10#2-9 underbluff catalog, HH11 overbluff catalog,
  HH12-HH13 spot inventories, HH15-HH18 reinforcing) are manual-only
  drill-mode prompts — too context-dependent for auto-detection.

v7.14: J33-J37 detection wired in (jam blocker, ICM MP flat, reshove
  ceiling, ICM jam compression, shallow BvB BB jam range). J38-J40
  kept as manual-review rules — too context-dependent for reliable
  auto-detection.
"""

import re, os, json, sys, csv
import gem_stage_meter as _stage_meter   # Gate 2.2: per-process heavy-stage meter (proves --quick is clean)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    try: sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
from collections import defaultdict, Counter
from pathlib import Path
from gem_parser import (
    parse_session, normalize_hand, pct, evaluate_best_hand,
    is_made_hand, hand_strength_name, classify_draw,
    classify_hand_for_betting, classify_board,
    RANKS, RANK_VAL, RANK_NUM, RANKS_ORDER
)
from gem_report_data import generate_report_data, _resolve_analyst_file
from gem_report_draft import generate_report_draft, render_html, render_md, render_both
# v7.30: shared detector prerequisite schema + quality gates
from gem_prereqs import preflop_shape, matches_shape, detector_prereq_satisfied
from gem_quality import run_preflight, plausibility_gate, end_of_run_learning, validate_pipeline_outputs
# v7.31: GTO texture archetype compliance (Dave session 2026-05-04)
try:
    import gem_textures
    _HAS_TEXTURES = True
except ImportError:
    _HAS_TEXTURES = False

# B238 (v7.99.22, Ron review 2026-05-26): real multiway all-in equity for
# the EAI categoriser + suckout detection.
try:
    import gem_eai_equity
    _HAS_EAI_EQUITY = gem_eai_equity.available()
except Exception:
    _HAS_EAI_EQUITY = False
if not _HAS_EAI_EQUITY:
    # v8.12.8 (handover Issue 2): a missing phevaluator used to SILENTLY
    # flip the EAI buckets to a crude rank heuristic — True EV moved by
    # ~5.5 BB/100 between two runs of the same session with no signal.
    import sys as _sys_eai
    print('WARN: phevaluator unavailable — EAI all-in buckets fall back to '
          'the rank heuristic; True EV / all-in-luck layer is APPROXIMATE. '
          'Run `pip install phevaluator` for exact equity.',
          file=_sys_eai.stderr)

# ============================================================
# Issue 6 (Ron 2026-05-30): reusable CORE push-range check for <8BB.
# Used by (a) the Missed Push detector, (b) the chart-match auto-resolve
# that tags bust-audit hands as chart-standard and excludes them from the
# analyst coverage gate.
# Returns (is_core, push_range_description) — True only for CLEAR-confidence
# hands (the CORE push range, not MARGINAL/EXTENDED).
# ============================================================
_PUSH_RANGES = {
    ('SB', True):  'PP, Ax, Kx, Qx, suited, connected',
    ('SB', False): 'PP, Ax, Kx, suited Qx+/connected/5+',
    ('BB', True):  'PP, Ax, Kx, Qx, suited, connected',
    ('BB', False): 'PP, Ax, Kx, suited Qx+/connected/5+',
    ('BTN', True): 'PP, Ax, Kx, suited, broadway, J+x',
    ('BTN', False):'PP, Ax, Kx, suited 6+, broadway',
    ('CO', True):  'PP, Ax, Kx (incl. offsuit), suited K+, broadway',
    ('CO', False): 'PP, Ax, Kx (incl. offsuit), suited K/Q, broadway T+',
    ('HJ', True):  'PP 4+, A8+, suited KT+',
    ('HJ', False): 'PP 4+, A8+, suited KT+',
}

def _is_core_push(hs, pos, stack_bb):
    """Check if normalized hand `hs` is a CORE (CLEAR-confidence) open-jam
    at `pos` with `stack_bb` < 8. Returns (is_core, push_range_str).

    This extracts the confidence == 'CLEAR' subset of the <8BB push
    heuristic so both the Missed Push detector and the chart-match
    auto-resolver use the same logic.
    """
    if stack_bb >= 8 or not hs or len(hs) < 2:
        return False, ''
    is_pair = len(hs) == 2
    is_suited = len(hs) == 3 and hs[2] == 's'
    is_ace = hs[0] == 'A'
    is_king = hs[0] == 'K'
    r1 = RANK_NUM.get(hs[0], 0)
    r2 = RANK_NUM.get(hs[1], 0)

    is_core = False
    if pos in ('SB', 'BB'):
        is_core = is_ace or is_king or is_pair
    elif pos == 'BTN':
        if stack_bb < 5:
            is_core = is_ace or is_pair or is_king
        else:
            is_core = is_ace or is_pair
    elif pos == 'CO':
        is_core = is_ace or is_pair or is_king
    elif pos == 'HJ':
        is_core = (is_ace and r2 >= 10) or (is_pair and r1 >= 7)

    pr = _PUSH_RANGES.get((pos, stack_bb < 5),
                          _PUSH_RANGES.get((pos, False), ''))
    return is_core, pr


# ============================================================
# ICM-pressure phases — single source of truth.  Was hardcoded in 4
# separate locations (lines 1165, 1226, 2436, 6819).  All now reference
# this constant.  Add new phases here ONCE.
# ============================================================
_ICM_PHASES = frozenset({'bubble_zone', 'post_bubble', 'ft_zone'})

# ============================================================
# B175 (Ron 2026-05-25): CVJ villain-jam-range + Hero-equity helper.
# The CVJ flag now shows what villain is jamming and Hero's equity vs
# that range, not just "outside threshold".
# ============================================================
_CVJ_RANGE_CACHE = {}

_PKO_BONUS_CACHE = {}

def _pko_open_chart_bonus(pos, stack_bb):
    """v8.12.1 C2: data-derived PKO widening for iso-jam/CVJ thresholds.

    bonus = PKO_OPEN_{d}BB_{pos} minus OPEN_{d2}BB_{pos} (nearest extracted
    depths). Provenance is carried in the returned note. Returns
    (set(), '') when either chart side is missing - per the review
    guardrail, no chart pair means Classic thresholds + no generic bonus.
    """
    key = (pos, int(stack_bb or 0) // 5)
    if key in _PKO_BONUS_CACHE:
        return _PKO_BONUS_CACHE[key]
    out = (set(), '')
    try:
        from gem_ranges import load_ranges
        ranges = load_ranges()
        import re as _re
        pko_keys, open_keys = {}, {}
        for k in ranges:
            m = _re.match(r'PKO_OPEN_(\d+)BB_%s$' % _re.escape(pos or ''), k)
            if m:
                pko_keys[int(m.group(1))] = k
            m2 = _re.match(r'OPEN_(\d+)BB_%s$' % _re.escape(pos or ''), k)
            if m2:
                open_keys[int(m2.group(1))] = k
        if pko_keys and open_keys:
            tgt = stack_bb or 20
            dp = min(pko_keys, key=lambda d: abs(d - tgt))
            do = min(open_keys, key=lambda d: abs(d - tgt))
            # Same-node guardrail: the diff is only a measured bonus when the
            # PKO and Classic charts sit at (near-)matching depths AND near
            # the hand's actual stack. Mismatched pairings produced bogus
            # widenings (e.g. a +25-hand BTN bonus where the research says
            # BTN TIGHTENS) — those now return no bonus.
            if abs(dp - do) > 3 or abs(dp - tgt) > 6:
                _PKO_BONUS_CACHE[key] = out
                return out
            diff = set(ranges[pko_keys[dp]]) - set(ranges[open_keys[do]])
            if diff:
                out = (diff, f'PKO chart-diff bonus '
                             f'({pko_keys[dp]} minus {open_keys[do]}, '
                             f'+{len(diff)} hands)')
    except Exception:
        pass
    _PKO_BONUS_CACHE[key] = out
    return out


def _cvj_push_chart_name(jammer_pos):
    """Jammer position -> PUSH chart key. Only 10BB push charts exist in
    Poker_Ranges_Text.txt; used as the proxy for any genuinely short jam."""
    alias = {'EP': 'UTG', 'LJ': 'MP'}
    return 'PUSH_10BB_' + alias.get(jammer_pos, jammer_pos or '')

def _cvj_villain_equity(jammer_pos, jammer_bb, hero_cards, fmt, hero_stack_bb):
    """Returns {chart, n_combos, hero_eq_pct, req_eq_pct, verdict} or None.

    Villain jam range = PUSH_10BB_<pos>; Hero equity = MC vs that range;
    required equity = simple all-in pot-odds model (bounty-adjusted). Returns
    None for non-short jams (no push chart at that depth) or if phevaluator /
    the range file is unavailable - the caller then omits the clause.
    """
    if not hero_cards or len(hero_cards) != 2:
        return None
    if not (6 <= (jammer_bb or 0) <= 16):
        return None  # 10BB push chart is only a sane proxy for short jams
    chart_name = _cvj_push_chart_name(jammer_pos)
    try:
        if 'ranges' not in _CVJ_RANGE_CACHE:
            from gem_ranges import load_ranges, range_to_combos
            _CVJ_RANGE_CACHE['ranges'] = load_ranges()
            _CVJ_RANGE_CACHE['r2c'] = range_to_combos
        from gem_solver import preflop_equity_vs_range
    except Exception:
        return None
    chart = (_CVJ_RANGE_CACHE.get('ranges') or {}).get(chart_name)
    if not chart:
        return None
    combos = _CVJ_RANGE_CACHE['r2c'](chart, hero_cards)
    if not combos:
        return None
    try:
        hero_eq, _n = preflop_equity_vs_range(tuple(hero_cards), combos)
    except Exception:
        return None
    if hero_eq is None:
        return None
    # Required equity: Hero calls an effective jam C into dead money D.
    # Pot won on call = C (villain matched) + C (Hero call) + D, so
    # req_eq = C / (2C + D). D ~ blinds + antes ~ 2.3BB at 8-handed.
    call = min(jammer_bb, hero_stack_bb or jammer_bb)
    req_eq = call / (2 * call + 2.3) * 100
    if (fmt or '').upper() in ('BOUNTY', 'PKO'):
        # v8.12.0: numeric bounty discount only when Hero can ELIMINATE the
        # jammer on the winning branch (covers; equal stacks = collectible).
        # Covered spots: bounty not capturable -> no discount. Mystery is
        # format-distinct (MYSTERY_BOUNTY) and never reaches this branch.
        # v8.12.1 C1: the depth-scaled model is now AUTHORITATIVE (S4.4
        # migration audit on the 2026-06-09/10 session: 7 math-only changes,
        # 0 verdict flips). Research: PKO effect ~3-4x larger at 20bb than
        # 50bb -> 8pp at <=20bb, 4pp at 20-35bb, 2pp above.
        if (hero_stack_bb or jammer_bb or 0) >= (jammer_bb or 0):
            _eff_pko = hero_stack_bb or jammer_bb or 0
            _pko_scale = 1.0 if _eff_pko <= 20 else (
                0.5 if _eff_pko <= 35 else 0.25)
            req_eq -= 8.0 * _pko_scale
    req_eq = round(max(req_eq, 0.0), 1)
    verdict = ('above the call price' if hero_eq >= req_eq
               else 'below the call price')
    return {'chart': chart_name, 'n_combos': len(combos),
            'hero_eq_pct': hero_eq, 'req_eq_pct': req_eq, 'verdict': verdict}


# ============================================================
# B178 (Ron 2026-05-25): Blind-Spot Audit - random sample of hands that
# NO detector flagged, for analyst review. The coded heuristics have
# blind spots (e.g. a CVJ-call pattern with no detector); a small
# reproducible random sample of un-flagged decision hands surfaces leaks
# the rules miss. A sampled hand found to be a real leak is the trigger
# to build a new detector (New Learning Intake).
# ============================================================
def _compute_blindspot_audit(hands, s):
    """Frame = VPIP hands (real decisions; preflop fold-outs excluded) minus
    every already-surfaced hand. Sample ~1% of total hands, floor 3, cap 12,
    drawn with a date-seeded RNG so a re-run of the same input reproduces.

    B233 (Ron review 2026-05-25): cap raised 8 -> 12 — Ron wants a wider
    blind-spot net per session."""
    import random
    flagged = set()
    for m in (s.get('mistakes') or []):
        if isinstance(m, dict) and m.get('id'):
            flagged.add(m['id'])
    for d in (s.get('preflop_deviations') or []):
        if isinstance(d, dict) and d.get('id'):
            flagged.add(d['id'])
    for p in ((s.get('punts') or {}).get('hands') or []):
        if isinstance(p, dict) and p.get('id'):
            flagged.add(p['id'])
    for c in ((s.get('coolers') or {}).get('hands') or []):
        if isinstance(c, dict) and c.get('id'):
            flagged.add(c['id'])
    frame = [h for h in hands
             if h.get('vpip') and h.get('id') and h['id'] not in flagged]
    total = len(hands)
    cap = 15  # v8.6.2: raised from 12 to accommodate big-loss stratum
    target = min(cap, max(3, round(0.01 * total)))
    date_str = ''
    for h in hands:
        if h.get('date'):
            date_str = str(h['date'])
            break
    seed = int(''.join(ch for ch in date_str if ch.isdigit()) or '0')
    rng = random.Random(seed)
    # Batch 2 (0J): STRATIFIED sampling instead of pure random.
    # Pick from specific strata that reveal hidden leaks.
    if len(frame) <= target:
        picked = list(frame)
    else:
        strata_picks = []
        _used_ids = set()
        def _pick_one(pool):
            for h in pool:
                if h.get('id') not in _used_ids:
                    _used_ids.add(h['id'])
                    strata_picks.append(h)
                    return
        # Stratum 1: largest non-flagged loss (possible hidden mistake)
        _losses = sorted(frame, key=lambda h: h.get('net_bb', 0))
        _pick_one(_losses[:3])
        _pick_one(_losses[3:6])
        # Stratum 2: largest non-flagged win (possible lucky mistake)
        _wins = sorted(frame, key=lambda h: h.get('net_bb', 0), reverse=True)
        _pick_one(_wins[:3])
        # Stratum 3: river fold with strong made hand (possible missed value)
        _river_folds = [h for h in frame if h.get('river_action') == 'fold'
                        and h.get('hand_strength', '') in ('two_pair', 'trips', 'straight', 'flush')]
        _pick_one(_river_folds)
        # Stratum 4: checked-back river after villain checked (thin value?)
        _check_backs = [h for h in frame if h.get('river_action') == 'check_sdv']
        _pick_one(_check_backs)
        # Stratum 5: SB flat that was not flagged
        _sb_flats = [h for h in frame if h.get('position') == 'SB' and h.get('cold_called')]
        _pick_one(_sb_flats)
        # Stratum 6: CO/BTN fold first-in (possible missed steal)
        _lp_folds = [h for h in frame if h.get('position') in ('CO', 'BTN')
                      and h.get('first_in') and not h.get('vpip')]
        # (these may not be in frame since frame requires vpip=True)
        # Stratum 7: c-bet skipped on dry board
        _missed_cbet = [h for h in frame if h.get('pfr') and not h.get('hero_cbet_flop')
                        and h.get('board_texture', '').startswith('dry')]
        _pick_one(_missed_cbet)
        # Stratum 8 (v8.6.2): big unflagged losses ≥15BB — the detector's
        # blind spot. These are hands where Hero lost significant chips but
        # no rule flagged them. Up to 5 included regardless of cap.
        _big_unflagged = [h for h in frame if (h.get('net_bb', 0) or 0) <= -15
                          and h.get('id') not in _used_ids]
        _big_unflagged.sort(key=lambda h: h.get('net_bb', 0))
        for _bu in _big_unflagged[:5]:
            _used_ids.add(_bu['id'])
            strata_picks.append(_bu)
        # Fill remaining slots with random from frame
        remaining = target - len(strata_picks)
        _pool = [h for h in frame if h.get('id') not in _used_ids]
        if remaining > 0 and _pool:
            strata_picks.extend(rng.sample(_pool, min(remaining, len(_pool))))
        picked = strata_picks[:target]
    picked.sort(key=lambda h: h.get('id', ''))
    sampled = [{
        'id': h.get('id'),
        'cards': h.get('cards', []),
        'hand_class': normalize_hand(h.get('cards', [])),
        'pos': h.get('position'),
        'stack_bb': round(h.get('stack_bb', 0)),
        'pot_type': h.get('pot_type', 'SRP'),
        'net_bb': round(h.get('net_bb', 0), 1),
        'tournament': (h.get('tournament', '') or '')[:45],
        'date': h.get('date'),
    } for h in picked]
    return {
        'sampled': sampled,
        'frame_size': len(frame),
        'total_hands': total,
        'target_n': target,
        'cap': cap,
        'rate': 0.01,
        'seed': seed,
    }


PREMIUMS = {'AA','KK','QQ','JJ','AKs','AKo'}
STRONG = {'TT','99','AQs','AQo','AJs','KQs'}

EP_POS = {'UTG', 'UTG+1'}
MP_POS = {'MP'}
LP_POS = {'HJ', 'CO', 'BTN'}
BLIND_POS = {'SB', 'BB'}

# Steal position ranges — DEPTH AWARE (v7.2)
# Core ranges = hands that are CLEAR opens at any depth.
# Extended ranges = marginal hands only at 100BB+ depth.
# Parser will flag core misses as "Clear Missed Steal" and extended as "Marginal Missed Steal"

BTN_CORE = {'AA','KK','QQ','JJ','TT','99','88','77',
    'AKs','KQs','QJs','JTs','T9s','98s','87s',
    'AKo','AQo','AJo','ATo','A9o','A8o','A7o','A6o','A5o',
    'KQo','KJo','KTo','QJo','QTo','JTo','T9o','98o'}
BTN_EXTENDED = {'J9s','J8s','J6s','J5s','J4s','J3s','J2s',
    'T8s','T6s','T5s','T4s','T3s','T2s',
    'A3o','K3o','87o','76o','75o'}

CO_CORE = {'AA','KK','QQ','JJ','TT','99','88','77',
    'AKs','KQs','KJs','KTs','K9s','QJs','QTs','Q9s','JTs','J9s','T9s',
    'AKo','AQo','AJo','ATo','A9o','A8o',
    'KQo','KJo','KTo','K9o','QJo','QTo','JTo','J9o','T9o'}
# v7.43 (Ron 2026-05-09): T8o demoted from CO_CORE to CO_EXTENDED.
# Offsuit broadway-low (T8o) from CO is not a CLEAR steal — depends on
# table dynamics, BB/SB tendencies, and stack depths. Suited equivalent
# T8s remains in extended for missed-steal MARGINAL flagging.
CO_EXTENDED = {'44','22','K8s','K7s','K6s','K5s','K4s',
    'Q8s','Q7s','Q6s','Q5s','J8s','J7s','J6s','J5s',
    'T6s','T5s','95s','94s','84s','74s',
    'K8o','Q9o','Q8o','J8o','T8o'}

SB_CORE = {'AA','KK','QQ','JJ','TT','99','88',
    'AKs','KQs','QJs','JTs','T9s','98s',
    'AKo','AQo','AJo','ATo','A9o','A8o',
    'KQo','KJo','KTo','K9o','QJo','QTo','JTo','T9o','98o'}
SB_EXTENDED = {'J9s','J8s','J7s','J6s','J5s','J3s','J2s',
    'T8s','T7s','T6s','T5s','T3s','T2s',
    '95s','93s','92s','85s','83s','82s','75s','54s',
    'A3o','A2o','K8o','K2o','Q9o','Q8o','Q7o','Q6o','Q5o',
    'J9o','97o'}
# v7.79 (Ron 2026-05-23): removed T4o/T3o/T2o/94o/92o/83o/72o/62o from
# SB_EXTENDED at all depths. These are the bottom of the J29 SB BvB ~10%
# fold band — folding them is correct, not a missed steal. Their presence
# here made the Missed-Steal detector flag correct folds (e.g. 72o SB 78BB
# on TM5986805688). They belong in no opening tier; a fold now produces no
# flag. Caught by Ron reviewing tail-folds.

# ============================================================
# B206 (Ron 2026-05-25): CORE-FRINGE — bottom 5% of each position's CORE
# open tier. The missed-steal detector used a hard CORE/EXTENDED binary:
# a hand one notch into CORE was stamped "Missed Steal (CLEAR)" and counted
# in mistakes/100 with the SAME weight as a 30BB punt — even though it sits
# at the very bottom of the opening range and folding it is a ~1.5BB tail
# decision. Ron's rule (re-affirmed): bottom-of-range / close-to-bottom
# missed opens are MARGINAL, not CLEAR. So the weakest ~5% of each CORE
# tier is split off as a "core-fringe" band → flagged MARGINAL, routed to
# the info-only tail-folds section, excluded from mistakes/100.
#
# Strength proxy (ordering only — not an EV model): pairs always rank top
# (never fringe); non-pairs = hi*2 + lo + suited-bonus - gap-penalty, with
# the gap penalty waived when an ace is present (offsuit aces carry blocker
# + showdown value, so A5o is NOT bottom-of-range — it stays CLEAR).
_PF_RANK = {'A': 14, 'K': 13, 'Q': 12, 'J': 11, 'T': 10,
            '9': 9, '8': 8, '7': 7, '6': 6, '5': 5, '4': 4, '3': 3, '2': 2}


def _preflop_strength(hc):
    """Ordering proxy for a hand-class string ('AKs','JTo','99'). Higher =
    stronger. Used only to rank within a CORE tier to find its bottom 5%."""
    if not hc or len(hc) < 2:
        return 0
    r1 = _PF_RANK.get(hc[0], 0)
    r2 = _PF_RANK.get(hc[1], 0)
    if hc[0] == hc[1]:                       # pair — never core-fringe
        return 100 + r1
    hi, lo = max(r1, r2), min(r1, r2)
    suited = hc.endswith('s')
    gap = hi - lo - 1
    gap_pen = 0 if hi == 14 else gap * 1.5   # ace carries it; no connectivity need
    return hi * 2 + lo + (8 if suited else 0) - gap_pen


def _core_fringe(core_set):
    """Bottom 5% (min 1) of a CORE tier by _preflop_strength — kept for
    reference / any future computed use."""
    if not core_set:
        return set()
    n = max(1, round(0.05 * len(core_set)))
    ranked = sorted(core_set, key=_preflop_strength)
    return set(ranked[:n])


# B207 (Ron review 2026-05-25): the computed bottom-5% slice (B206) ranked
# connectors (98o/T9o) as the weakest opens and left JTo / A5o mid-tier — but
# "bottom of the opening range" is a framework judgment, not a structural
# formula: from a steal seat the genuinely-marginal opens are the low-
# playability OFFSUIT hands (offsuit broadways like JTo, weak offsuit aces
# like A5o/A7o), which a connectivity/high-card proxy cannot rank as "bottom".
# Ron named them explicitly, twice. So core-fringe is now a CURATED set per
# position — these open-tier hands are flagged MARGINAL (not CLEAR), routed
# to the info-only tail-folds section, and excluded from mistakes/100.
# Adjust these sets to re-tune; nothing else needs to change.
#   A7o is included on Ron's "we can discuss" note — pull it from BTN if not.
BTN_CORE_FRINGE = {'98o', 'T9o', 'JTo', 'A5o', 'A7o'}
CO_CORE_FRINGE = {'T9o', 'J9o', 'JTo'}
SB_CORE_FRINGE = {'98o', 'T9o', 'JTo'}


# ============================================================
# 1b. DYNAMIC RANGE LOADER + PREFLOP DEVIATION CHECKER (v7.2)
# ============================================================

def load_targets(filepath):
    """Load *_TARGET_* lines from Poker_Ranges_Text.txt into {target_name: (lo, hi)}.

    v7.32 (C1/C2/C3/C7/C8): target chart families are NOT range charts (no
    hand-list); they're frequency bands. Recognized formats per line:
        TURN_CBET_TARGET_BTN: 47-57
        F2CB_TARGET_CO: 28-35
        SQUEEZE_TARGET_BTN: 8-12

    Lines are matched by the suffix `_TARGET_<POS>` followed by a colon and
    a numeric `lo-hi` range. Returns dict; missing/invalid file → {}.
    """
    targets = {}
    try:
        with open(filepath, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                # Match `<NAME>_TARGET_<POS>: <lo>-<hi>`. NAME and POS may
                # contain alnum/underscore/plus/hyphen; lo/hi are integers
                # or simple decimals.
                m = re.match(r'^([A-Z][A-Z0-9_]*_TARGET_[A-Z0-9+]+)\s*:\s*([\d.]+)\s*-\s*([\d.]+)\s*$', line)
                if not m: continue
                name = m.group(1)
                try:
                    lo, hi = float(m.group(2)), float(m.group(3))
                except ValueError:
                    continue
                if lo > hi: lo, hi = hi, lo
                targets[name] = (lo, hi)
    except FileNotFoundError:
        pass
    return targets

def load_ranges(filepath):
    """Load all ranges from Poker_Ranges_Text.txt into {chart_name: set(hands)}.

    Expands the '+' notation into concrete 2-card tokens:
      Pairs:    77+   -> {77,88,99,TT,JJ,QQ,KK,AA}
      Non-pair: XYx+  -> all X-high hands with second rank in [Y, X) and same suit-tag
                e.g., KJs+ = {KJs, KQs}; T4o+ = {T4o, T5o, T6o, T7o, T8o, T9o};
                      AKs+ = {AKs}; QJs+ = {QJs}
    Skips metadata-looking lines (e.g. 'Charts: 130') — a line only becomes a chart
    if every non-'+' token parses as a valid hand-class string.
    """
    RANKS_HI = 'AKQJT98765432'  # index 0 = A, 12 = 2
    rank_idx = {r: i for i, r in enumerate(RANKS_HI)}

    def _expand(tok):
        """Return a set of concrete tokens for a range entry like 'AKs+', '77+', 'QTs'."""
        tok = tok.strip()
        if not tok: return set()
        # Pair: e.g. '77' or '77+'
        if len(tok) >= 2 and tok[0].isalnum() and tok[0] == tok[1]:
            if tok[0] not in rank_idx: return set()
            if tok.endswith('+'):
                top = rank_idx[tok[0]]  # smaller idx = higher rank
                return {RANKS_HI[i]*2 for i in range(top+1)}  # this pair and all higher
            return {tok[:2]} if len(tok) == 2 else set()
        # Non-pair: XYs, XYo, XYs+, XYo+  (X must be higher than Y)
        if len(tok) >= 3 and tok[2] in ('s', 'o'):
            x, y, suit = tok[0], tok[1], tok[2]
            if x not in rank_idx or y not in rank_idx: return set()
            xi, yi = rank_idx[x], rank_idx[y]
            if xi >= yi: return set()  # x must be strictly higher (lower index) than y
            if tok.endswith('+'):
                # second card spans from Y up to (but not including) X
                return {x + RANKS_HI[i] + suit for i in range(yi, xi, -1) if i > xi}
            if len(tok) == 3:
                return {tok}
        return set()

    ranges = {}
    try:
        with open(filepath, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                # Allow hyphen in chart names (e.g. OPEN_20-40BB_SB).
                m = re.match(r'^([A-Za-z0-9][A-Za-z0-9_+\-]+):\s*(.+)$', line)
                if not m: continue
                name = m.group(1)
                hands_part = re.sub(r'\s*\[[\d.]+%\]\s*$', '', m.group(2))
                tokens = [t.strip() for t in hands_part.split(',') if t.strip()]
                # Reject metadata lines: every token must expand to >=1 hand.
                expanded = set()
                all_parsed = bool(tokens)
                for t in tokens:
                    e = _expand(t)
                    if not e:
                        all_parsed = False
                        break
                    expanded |= e
                if all_parsed and expanded:
                    ranges[name] = expanded
    except FileNotFoundError:
        pass
    return ranges


# ============================================================
# v7.39: CHART SANITY VALIDATOR (B32 mitigation)
# ============================================================
#
# Several PUSH_10BB_* and REJAM_*vs* charts in Poker_Ranges_Text.txt have OCR
# corruption from the pixel-color extraction pipeline:
#   - PUSH_10BB_UTG+1 (n=23): missing AQs/AJs/ATs/...A2s, missing JJ/TT
#   - PUSH_10BB_UTG (n=36): missing A2s/A3s/A4s/A6s, contains J2o/Q2o/K2o
#                            (implausible push hands at UTG)
#   - PUSH_10BB_UTG+2 (n=30): missing 22-99 except 22, has T2s/J2s/Q2s/K2s
#                              (implausible)
#   - REJAM_*vsUTG / REJAM_*vsUTG1 / REJAM_*vsMP series: contain T4o/J4o/J2o
#                                                         (implausible)
#
# Strategy: at chart-load time, run sanity tests against an anchor-set per chart
# family. If sanity fails, AUGMENT the chart with the missing anchor hands so
# detection still works on real spots — but record the fact in
# `chart_quality_issues` so any deviation flagged against an augmented chart
# can carry a `⚠️ chart-augmented` marker downstream. We do NOT remove the
# implausible cells (J2o etc.) — keep-if-not-sure per Ron's instruction. The
# augmentation only ADDS missing premium content; it doesn't subtract.
#
# This is a v7.39 mitigation for B32. The real fix is to re-OCR source PNGs.

# Anchor sets — minimum content a chart MUST contain to be considered sane.
# These are conservative (the actual GTO range is wider) — they only catch
# OCR catastrophes, not GTO mixed-strategy edges.
_PUSH_10BB_EARLY_ANCHORS = {
    # Any UTG/UTG+1/UTG+2 push at 10BB MUST contain these:
    'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77',
    'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A5s',
    'KQs', 'KJs', 'KTs',
    'AKo', 'AQo', 'AJo',
}
_PUSH_10BB_LATE_ANCHORS = {
    # CO/HJ/MP push at 10BB — wider but minimum
    'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66',
    'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s',
    'KQs', 'KJs', 'KTs', 'K9s',
    'QJs', 'QTs',
    'AKo', 'AQo', 'AJo', 'ATo', 'A9o',
    'KQo', 'KJo',
}
_PUSH_10BB_BTN_SB_ANCHORS = {
    # BTN/SB push at 10BB — very wide, anchors are conservative
    'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55',
    'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s',
    'KQs', 'KJs', 'KTs', 'K9s',
    'QJs', 'QTs', 'JTs', 'T9s',
    'AKo', 'AQo', 'AJo', 'ATo', 'A9o', 'A8o', 'A7o',
    'KQo', 'KJo', 'KTo',
    'QJo', 'JTo',
}
_OPEN_EARLY_ANCHORS = {
    # OPEN_*_UTG / UTG+1 / UTG+2 minimum content (any depth)
    'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
    'AKs', 'AQs', 'AJs', 'ATs', 'A9s',
    'KQs', 'KJs', 'KTs',
    'AKo', 'AQo', 'AJo',
}
# v7.39 — B32 expansion: REJAM and OPEN_LATE anchors.
# REJAM ranges at 12-25BB always contain at least the premium pairs and AK
# (per Dave J33-J40 short-stack framework + MDA-4 confirmation: at this
# stack depth, premium pairs are MASSIVELY +EV to rejam — +9 BB/event).
_REJAM_ANCHORS = {
    'AA', 'KK', 'QQ', 'JJ', 'TT',
    'AKs', 'AQs',
    'AKo',
}
# OPEN_*_MP/HJ/CO — at any depth, must contain pairs + premium broadways.
_OPEN_LATE_ANCHORS = {
    'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
    'AKs', 'AQs', 'AJs', 'ATs',
    'KQs', 'KJs', 'KTs',
    'QJs', 'QTs',
    'AKo', 'AQo', 'AJo',
    'KQo',
}
# OPEN_*_BTN/SB — wider; only pairs + premium Ax + premium Kx required.
_OPEN_BTN_SB_ANCHORS = {
    'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66',
    'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A5s',
    'KQs', 'KJs', 'KTs',
    'QJs',
    'AKo', 'AQo', 'AJo', 'ATo',
    'KQo', 'KJo',
}
# BB_DEF — at any open%, must contain the pairs + premium broadways.
_BB_DEF_ANCHORS = {
    'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
    'AKs', 'AQs', 'AJs', 'ATs',
    'KQs', 'KJs',
    'QJs',
    'AKo', 'AQo', 'AJo',
    'KQo',
}

# OCR-noise pattern detector. v7.39: the source PNG OCR pipeline produces
# clusters of implausible cells along certain rank-columns when borderline
# cell colors fail the threshold test. Two recognizable patterns:
#   "4o-column": K4o, Q4o, J4o, T4o appearing TOGETHER in a chart that
#                doesn't otherwise feature low offsuits (e.g. REJAM ranges)
#   "2-column" : K2o, Q2o, J2o, T2o appearing TOGETHER in same context
# When detected, log a warning. We don't strip — Ron's rule is keep-if-not-sure.
_OCR_NOISE_4O_CLUSTER = {'K4o', 'Q4o', 'J4o', 'T4o'}
_OCR_NOISE_2O_CLUSTER = {'K2o', 'Q2o', 'J2o', 'T2o'}

def _anchor_set_for_chart(chart_name):
    """Return (anchor_set, family_label) for sanity checking, or (None, None) if N/A."""
    if chart_name.startswith('PUSH_10BB_'):
        pos = chart_name.replace('PUSH_10BB_', '')
        if pos in ('UTG', 'UTG+1', 'UTG+2'):
            return _PUSH_10BB_EARLY_ANCHORS, 'push10_early'
        if pos in ('CO', 'HJ', 'MP'):
            return _PUSH_10BB_LATE_ANCHORS, 'push10_late'
        if pos in ('BTN', 'SB'):
            return _PUSH_10BB_BTN_SB_ANCHORS, 'push10_btn_sb'
    elif chart_name.startswith('OPEN_'):
        # OPEN_<depth>_<pos>
        parts = chart_name.split('_')
        if len(parts) >= 3:
            pos = parts[-1]
            # SB special charts (OPEN_100BB_SB_LIMP/RAISE/AGGRO) shouldn't
            # be sanity-checked against the standard anchor sets — they have
            # very different intended content.
            if 'SB_LIMP' in chart_name or 'SB_RAISE' in chart_name or 'SB_VS' in chart_name:
                return None, None
            if pos in ('UTG', 'UTG+1', 'UTG+2'):
                return _OPEN_EARLY_ANCHORS, 'open_early'
            if pos in ('MP', 'HJ', 'CO'):
                return _OPEN_LATE_ANCHORS, 'open_late'
            if pos in ('BTN', 'SB'):
                return _OPEN_BTN_SB_ANCHORS, 'open_btn_sb'
    elif chart_name.startswith('REJAM_'):
        # REJAM_<HeroPos>vs<OpenerPos> — all need premium pairs + AK
        return _REJAM_ANCHORS, 'rejam'
    elif chart_name.startswith('BB_DEF_'):
        return _BB_DEF_ANCHORS, 'bb_def'
    return None, None


def _detect_ocr_noise(chart_set):
    """Return list of OCR-noise pattern names triggered in this chart_set.
    Only reports — does not modify the set."""
    triggered = []
    if _OCR_NOISE_4O_CLUSTER.issubset(chart_set):
        triggered.append('4o_column_cluster')
    if _OCR_NOISE_2O_CLUSTER.issubset(chart_set):
        triggered.append('2o_column_cluster')
    return triggered


def sanity_check_ranges(ranges):
    """v7.39 — B32 mitigation. Run sanity tests on each chart and AUGMENT
    where corruption is detected. Returns the augmented ranges dict and a
    side-channel report.

    Two checks per chart:
      1. Anchor-set test: chart must contain a minimum set of premium hands
         appropriate to its family. Missing anchors → augment + report.
      2. OCR-noise pattern test: chart contains a recognizable cluster of
         implausible cells (4o-column, 2o-column). Detected → report only;
         we don't strip cells (Ron's keep-if-not-sure rule).

    Output: (ranges_augmented, sanity_report) where sanity_report is:
        {chart_name: {
            'augmented': bool,
            'family': str,
            'missing_before': sorted list of hands that were missing,
            'augmented_count': int (combos added),
            'ocr_noise_patterns': list of triggered pattern names,
        }}
    """
    sanity_report = {}
    for chart_name, chart_set in list(ranges.items()):
        anchors, family = _anchor_set_for_chart(chart_name)
        # OCR noise check applies to ALL chart families regardless of anchors
        ocr_patterns = _detect_ocr_noise(chart_set) if chart_set else []
        if anchors is None:
            # No anchor coverage for this chart family — but still report
            # OCR noise so Ron sees it.
            if ocr_patterns:
                sanity_report[chart_name] = {
                    'augmented': False,
                    'family': 'unknown',
                    'missing_before': [],
                    'augmented_count': 0,
                    'ocr_noise_patterns': ocr_patterns,
                }
            continue
        missing = anchors - chart_set
        if not missing and not ocr_patterns:
            continue
        # Augment the chart with any missing anchor hands.
        if missing:
            ranges[chart_name] = chart_set | anchors
        sanity_report[chart_name] = {
            'augmented': bool(missing),
            'family': family,
            'missing_before': sorted(missing),
            'augmented_count': len(missing),
            'ocr_noise_patterns': ocr_patterns,
        }
    return ranges, sanity_report


# A module-level singleton populated when load_ranges + sanity_check_ranges
# are run by the analyzer __main__. Read by the deviation block to mark each
# affected deviation with `chart_augmented=True`.
_RANGE_SANITY_REPORT = {}




def _chart_pos(pos):
    """Map parser position names to chart position names."""
    return pos.replace('+', '')  # UTG+1 → UTG1, UTG+2 → UTG2

def _depth_tier_open(stack_bb):
    """Map stack depth to OPEN chart tier."""
    if stack_bb < 12: return 'PUSH_10BB'
    if stack_bb < 20: return 'OPEN_10-20BB'
    if stack_bb < 40: return 'OPEN_20-40BB'
    return 'OPEN_100BB'

def _open_chart_pos(position, n_players=8):
    """Map (position, n_players) to OPEN chart suffix. Accounts for short tables."""
    if position in ('SB', 'BB', 'BTN', 'CO', 'HJ'):
        return position
    if n_players >= 8:
        return position
    if n_players == 7:
        return {'UTG': 'UTG+1', 'UTG+1': 'MP', 'MP': 'HJ'}.get(position, position)
    if n_players == 6:
        return {'UTG': 'MP', 'UTG+1': 'HJ', 'MP': 'HJ'}.get(position, position)
    return position

def _depth_tier_flat3b(stack_bb):
    """Map stack depth to FLAT3B chart tier."""
    if stack_bb < 25: return '20BB'
    if stack_bb < 35: return '30BB'
    if stack_bb < 45: return '40BB'
    return '50BB'

# v7.71 (Ron 2026-05-23): hoisted to module level so the Missed-Steal
# detector in analyze_session() can surface the correct opening range
# (issue 2). Previously nested inside check_preflop_deviations. Pure
# functions — only dependency is the module-global RANK_NUM.
def _find_kicker_runs(hand_list):
    """Return a list of runs. Each run is a list of hands sorted by
    kicker rank ASCENDING (low to high). Input is a list of hands at
    the same high card, same suited-ness."""
    if not hand_list: return []
    sorted_h = sorted(hand_list, key=lambda h: RANK_NUM.get(h[1], 0))
    runs = []
    cur = [sorted_h[0]]
    for h in sorted_h[1:]:
        prev_rank = RANK_NUM.get(cur[-1][1], 0)
        this_rank = RANK_NUM.get(h[1], 0)
        if this_rank - prev_rank == 1:
            cur.append(h)
        else:
            runs.append(cur)
            cur = [h]
    runs.append(cur)
    return runs

def _format_kicker_run(run):
    """Format a single run (low-to-high) using +/-/X-Y notation."""
    if len(run) == 1:
        return run[0]
    low = run[0]; high = run[-1]
    high_card_rank = RANK_NUM.get(low[0], 0)
    max_kicker_rank = high_card_rank - 1  # AA blocks A-A → max kicker is K, etc.
    high_kicker_rank = RANK_NUM.get(high[1], 0)
    if high_kicker_rank == max_kicker_rank:
        return f"{low}+"          # extends to top → "low+"
    if low[1] == '2':
        return f"{high}-"         # extends to bottom → "high-"
    return f"{low}-{high}"        # middle run

def _format_pair_run(run):
    """Format a pair run (low-to-high)."""
    if len(run) == 1:
        return run[0]
    low = run[0]; high = run[-1]
    if high == 'AA':
        return f"{low}+"
    return f"{low}-{high}"

def _chart_summary(chart_set):
    """Compact one-line summary using standard poker shorthand.
    Example output:
      '22+, A2s+, A8o+, A5o-, K6s+, KTo+, Q8s+, QTo+, J8s+, JTo, T8s+, 97s+, 87s, 76s, 65s'
    """
    if not chart_set: return None
    pairs = [h for h in chart_set if len(h) == 2 and h[0] == h[1]]
    suited_by_high = {}
    offsuit_by_high = {}
    for h in chart_set:
        if len(h) == 3:
            if h[2] == 's':
                suited_by_high.setdefault(h[0], []).append(h)
            else:
                offsuit_by_high.setdefault(h[0], []).append(h)

    out_parts = []
    # Pairs
    if pairs:
        sp = sorted(pairs, key=lambda h: RANK_NUM.get(h[0], 0))
        # Pair runs: walk for consecutive ranks
        pruns = []
        cur = [sp[0]]
        for p in sp[1:]:
            if RANK_NUM.get(p[0], 0) - RANK_NUM.get(cur[-1][0], 0) == 1:
                cur.append(p)
            else:
                pruns.append(cur); cur = [p]
        pruns.append(cur)
        out_parts.extend(_format_pair_run(r) for r in pruns)

    # Suited then offsuit, by high card from A down
    for high in 'AKQJT98765432':
        for d in (suited_by_high, offsuit_by_high):
            hl = d.get(high, [])
            if not hl: continue
            runs = _find_kicker_runs(hl)
            for r in runs:
                out_parts.append(_format_kicker_run(r))

    return ", ".join(out_parts)


def _dark_chart_detectors(hands, ranges):
    """v8.12.2 P3 scaffolding (owner-approved): G7 cold-call width, G8
    facing-3-bet response, G9 blind-vs-blind, G10 iso-vs-limpers.

    DARK BY DESIGN: each fires only when its exact chart key exists in the
    ranges file — none of these chart families are extracted yet, so the
    detectors stay silent and the coverage audit reports
    detector_exists_but_missing_chart instead of no_detector_family.
    Chart-key contracts (the extraction must use these names):
      G7  CC_{20|30|50}BB_{pos}vs{opener}            (cold-call/continue set)
      G8  F3B_{20|30|50}BB_{pos}vs{threebettor}_CONT (continue vs 3-bet)
      G9  BVB_SB_OPEN_{20|30|50}BB / BVB_BB_DEF_{20|30|50}BB
      G10 ISO_{20|30|50}BB_{pos}
    """
    out = []
    if not ranges:
        return out
    def _dk(stack):
        return '20' if stack <= 25 else ('30' if stack <= 40 else '50')
    for h in hands:
        try:
            pos = h.get('position', '')
            hs = normalize_hand(h.get('cards', []))
            if not hs:
                continue
            stack = h.get('eff_stack_bb') or h.get('stack_bb') or 0
            if not 12 <= stack <= 60:
                continue
            hero = h.get('hero', '')
            base = {'id': h.get('id', ''), 'cards': hs, 'pos': pos,
                    'stack_bb': round(stack), 'format': h.get('format', ''),
                    'tournament': (h.get('tournament', '') or '')[:40],
                    'action_summary': h.get('action_summary', ''),
                    'opener_position': h.get('opener_position', '')}
            opener, callers, hero_act, n_r, limpers = None, [], None, 0, []
            three_bettor = None
            hero_opened = False
            for a in (h.get('action_ledger') or []):
                if a.get('street') != 'preflop' or a.get('action') == 'posts':
                    continue
                is_hero = a.get('player') == hero
                act = a.get('action')
                if act in ('raises', 'bets'):
                    n_r += 1
                    if is_hero and n_r == 1:
                        hero_opened = True
                    elif n_r == 1:
                        opener = a.get('position', '')
                    elif n_r == 2 and hero_opened and not is_hero:
                        three_bettor = a.get('position', '')
                elif act == 'calls':
                    if n_r == 0:
                        limpers.append(a.get('position', ''))
                    elif n_r == 1 and not is_hero:
                        callers.append(a.get('position', ''))
                if is_hero and not hero_opened and hero_act is None \
                        and act in ('calls', 'folds', 'raises', 'bets'):
                    hero_act = ('call' if act == 'calls' else
                                'fold' if act == 'folds' else 'raise')
            dk = _dk(stack)
            # G7: non-blind cold-flat width
            if (pos in ('UTG', 'UTG+1', 'MP', 'LJ', 'HJ', 'CO', 'BTN')
                    and opener and not callers and hero_act == 'call'):
                key = f'CC_{dk}BB_{pos}vs{opener}'
                ch = ranges.get(key)
                if ch and hs not in ch:
                    out.append({**base, 'type': 'Wide Cold-Call',
                                'chart': key, 'confidence': 'MARGINAL',
                                'note': f'{hs} outside {key}'})
            # G8: hero opened, faced 3-bet, folded a chart-continue hand
            if hero_opened and three_bettor and hero_act is None:
                for a in (h.get('action_ledger') or []):
                    if (a.get('player') == hero
                            and a.get('street') == 'preflop'
                            and a.get('action') == 'folds'):
                        key = f'F3B_{dk}BB_{pos}vs{three_bettor}_CONT'
                        ch = ranges.get(key)
                        if ch and hs in ch:
                            out.append({**base,
                                        'type': 'Missed 3-Bet Defense',
                                        'chart': key,
                                        'confidence': 'MARGINAL',
                                        'note': f'{hs} is a chart continue '
                                                f'vs {three_bettor} 3-bet '
                                                f'({key})'})
                        break
            # G9: blind-vs-blind
            if pos == 'SB' and not opener and not limpers \
                    and hero_act == 'fold':
                key = f'BVB_SB_OPEN_{dk}BB'
                ch = ranges.get(key)
                if ch and hs in ch:
                    out.append({**base, 'type': 'Missed BvB Open',
                                'chart': key, 'confidence': 'MARGINAL',
                                'note': f'{hs} opens in {key}'})
            if pos == 'BB' and opener == 'SB' and hero_act == 'fold':
                key = f'BVB_BB_DEF_{dk}BB'
                ch = ranges.get(key)
                if ch and hs in ch:
                    out.append({**base, 'type': 'Missed BvB Defend',
                                'chart': key, 'confidence': 'MARGINAL',
                                'note': f'{hs} defends in {key}'})
            # G10: iso vs limpers
            if limpers and not opener and hero_act == 'fold':
                key = f'ISO_{dk}BB_{pos}'
                ch = ranges.get(key)
                if ch and hs in ch:
                    out.append({**base, 'type': 'Missed Iso vs Limp',
                                'chart': key, 'confidence': 'MARGINAL',
                                'note': f'{hs} isolates in {key}'})
        except Exception:
            continue
    return out


def _g1_g2_chart_deviations(hands, ranges):
    """v8.12.1 P1: G1 Missed 3-Bet (3BF_*) + G2 Missed Squeeze (SQF_*).

    Exact-chart-only verdict tier: a deviation is emitted ONLY when the
    chart key for (position, opener[, caller], depth) exists and Hero's
    hand class is in it. _HF membership upgrades confidence to CLEAR.
    No chart -> silent (coverage audit counts the gap)."""
    out = []
    if not ranges:
        return out
    for h in hands:
        try:
            pos = h.get('position', '')
            if pos not in ('BB', 'SB', 'BTN', 'CO'):
                continue
            hs = normalize_hand(h.get('cards', []))
            if not hs:
                continue
            hero = h.get('hero', '')
            opener, callers, hero_act, n_r = None, [], None, 0
            for a in (h.get('action_ledger') or []):
                if a.get('street') != 'preflop' or a.get('action') == 'posts':
                    continue
                if a.get('player') == hero:
                    act = a.get('action')
                    if act in ('raises', 'bets'):
                        hero_act = 'raise'
                    elif act in ('calls', 'folds'):
                        hero_act = 'call' if act == 'calls' else 'fold'
                    break
                act = a.get('action')
                if act in ('raises', 'bets'):
                    n_r += 1
                    if n_r > 1:
                        opener = None
                        break
                    opener = a.get('position', '')
                    if a.get('is_all_in'):
                        opener = None
                        break
                elif act == 'calls' and n_r == 1:
                    callers.append(a.get('position', ''))
            if not opener or hero_act is None:
                continue
            stack = h.get('eff_stack_bb') or h.get('stack_bb') or 0
            base = {'id': h.get('id', ''), 'cards': hs, 'pos': pos,
                    'stack_bb': round(stack),
                    'format': h.get('format', ''),
                    'tournament': (h.get('tournament', '') or '')[:40],
                    'action_summary': h.get('action_summary', ''),
                    'opener_position': opener}
            if not callers and hero_act == 'call' and 12 <= stack <= 60:
                dk = '20' if stack <= 25 else ('30' if stack <= 40 else '50')
                key = f'3BF_{dk}BB_{pos}vs{opener}'
                chart = ranges.get(key)
                if chart and hs in chart:
                    hf = hs in (ranges.get(key + '_HF') or ())
                    out.append({**base, 'type': 'Missed 3-Bet', 'chart': key,
                                'confidence': 'CLEAR' if hf else 'MARGINAL',
                                'opener': opener,
                                'note': f'{hs} is a chart 3-bet vs {opener} '
                                        f'open at {dk}BB ({key}) - flatting '
                                        f'caps the range'})
            if callers and hero_act in ('call', 'fold') and 25 <= stack <= 40:
                key = f'SQF_30BB_{pos}_vs{opener}open_{callers[0]}call'
                chart = ranges.get(key)
                if chart and hs in chart:
                    hf = hs in (ranges.get(key + '_HF') or ())
                    verb = 'flatting' if hero_act == 'call' else 'folding'
                    out.append({**base, 'type': 'Missed Squeeze',
                                'chart': key,
                                'confidence': 'CLEAR' if hf else 'MARGINAL',
                                'opener': opener,
                                'note': f'{hs} is a chart squeeze vs '
                                        f'{opener} open + {callers[0]} call '
                                        f'({key}) - {verb} misses it'})
        except Exception:
            continue
    return out


def check_preflop_deviations(hands, ranges):
    """Check every hand's preflop action against range charts.
    Returns list of deviation dicts for the report."""
    if not ranges: return []
    deviations = []

    # v7.36c (Ron's compact-notation request): use standard poker shorthand.
    #   X+   — this hand and stronger up to the top of the row
    #          (e.g. "A8o+" = A8o, A9o, ATo, AJo, AQo, AKo)
    #   X-   — this hand and weaker down to rank 2
    #          (e.g. "A5o-" = A5o, A4o, A3o, A2o)
    #   X-Y  — explicit range (middle runs that don't touch top or bottom)
    # Charts can have multiple disjoint runs per row (e.g. A8o-AKo + A2o-A5o
    # with a gap at A6o/A7o → "A8o+, A5o-").


    # v7.31 Patch 7: chart lookup needs to account for short tables.
    # At 8+max, position name matches chart suffix directly. At 7-max, EP
    # positions effectively play one rank later (UTG+1@7max ≈ MP@8max because
    # both have 5 players to act behind). This function maps (position,
    # n_players) → chart suffix, handling short-table position-shift correctly.
    # Per Ron's note on TM5915670562 QJo at 7-handed.
    # NOTE: named _open_chart_pos to avoid shadowing module-level _chart_pos
    # which is called with 1 arg from other branches in this same function.
    def _open_chart_pos(position, n_players):
        if position in ('SB', 'BB', 'BTN', 'CO', 'HJ'):
            return position  # unambiguous across ring sizes
        if n_players >= 8:
            return position  # 8+max: seat name == chart suffix
        if n_players == 7:
            # Shift early positions one rank later (fewer players behind = looser
            # opening range, so use the chart for one position later in 8-max).
            return {'UTG': 'UTG+1', 'UTG+1': 'MP', 'MP': 'HJ'}.get(position, position)
        if n_players == 6:
            return {'UTG': 'MP', 'UTG+1': 'HJ', 'MP': 'HJ'}.get(position, position)
        # 5-max or less: minimal Hero data; fall back to raw position.
        return position

    for h in hands:
        n_players = h.get('n_players', 8)
        pos = _open_chart_pos(h.get('position', ''), n_players)
        stack = h.get('stack_bb', 0)
        cards_raw = h.get('cards', [])
        hs = normalize_hand(cards_raw)
        if not hs or pos in ('', 'UNK'): continue
        
        opener_pos = h.get('opener_position', '')
        pf_raise_count = h.get('pf_raise_count', 0)
        
        base = {'id': h['id'], 'cards': hs, 'pos': pos, 'stack_bb': round(stack),
                'format': h.get('format', ''), 'tournament': h.get('tournament', '')[:40],
                'action_summary': h.get('action_summary', ''),
                'opener_position': opener_pos}
        
        # ============================================================
        # SCENARIO A: FIRST-IN (open or fold)
        # ============================================================
        if h.get('first_in') and pos != 'BB':
            tier = _depth_tier_open(stack)
            # SB at 100BB has separate LIMP and RAISE charts
            if pos == 'SB' and tier == 'OPEN_100BB':
                chart_name_raise = 'OPEN_100BB_SB_RAISE'
                chart_name_limp = 'OPEN_100BB_SB_LIMP'
                raise_range = ranges.get(chart_name_raise, set())
                limp_range = ranges.get(chart_name_limp, set())
                combined = raise_range | limp_range
                if h['pfr'] and hs not in raise_range and hs not in limp_range:
                    deviations.append({**base, 'type': 'Wide Open', 'chart': chart_name_raise,
                                       'confidence': 'CLEAR'})
                elif not h['vpip'] and hs in combined:
                    conf = 'CLEAR' if hs in raise_range else 'MARGINAL'
                    # v8.12.8 QA3 (66796283): membership can come from the
                    # LIMP chart (Q7o) — recording the RAISE chart made the
                    # teaching copy claim the hand is "inside" a chart that
                    # doesn't contain it. Record the chart actually hit.
                    _sb_chart_hit = (chart_name_raise if hs in raise_range
                                     else chart_name_limp)
                    deviations.append({**base, 'type': 'Missed Open', 'chart': _sb_chart_hit,
                                       'confidence': conf})
            else:
                chart_name = f"{tier}_{pos}"
                chart = ranges.get(chart_name, set())
                if not chart: continue
                if h['pfr'] and hs not in chart:
                    # GTO ranges use mixed strategies — some hands are "fold" in GTO
                    # but profitable opens in practice. Mark as MARGINAL not CLEAR.
                    is_pair = len(hs) == 2 and hs[0] == hs[1]
                    is_suited = len(hs) == 3 and hs[2] == 's'
                    is_lp = pos in ('HJ', 'CO', 'BTN')
                    is_mp_plus = pos in ('MP', 'HJ', 'CO', 'BTN')
                    is_push = tier == 'PUSH_10BB'
                    # Broadway offsuit from BTN (K9o, Q9o etc. standard BTN opens)
                    is_broadway_o = (len(hs) == 3 and hs[2] == 'o' 
                                     and RANK_NUM.get(hs[0], 0) >= 11  # K+
                                     and RANK_NUM.get(hs[1], 0) >= 7)  # 9+
                    
                    if is_pair:
                        conf = 'MARGINAL'  # pairs always playable from any position
                    elif is_suited and is_mp_plus:
                        conf = 'MARGINAL'  # suited hands from MP+ often GTO mixed
                    elif is_broadway_o and pos == 'BTN':
                        conf = 'MARGINAL'  # K9o/KTo/Q9o standard BTN opens
                    elif is_push and is_pair:
                        conf = 'MARGINAL'  # medium pairs obvious jams at <12BB
                    else:
                        conf = 'CLEAR'
                    deviations.append({**base, 'type': 'Wide Open', 'chart': chart_name,
                                       'confidence': conf})
                elif not h['vpip'] and hs in chart:
                    # Confidence: check if hand is in the tighter depth tier too
                    tighter_tier = 'OPEN_20-40BB' if tier == 'OPEN_100BB' else 'OPEN_10-20BB' if tier == 'OPEN_20-40BB' else tier
                    tighter_chart = ranges.get(f"{tighter_tier}_{pos}", set())
                    conf = 'CLEAR' if (tighter_chart and hs in tighter_chart) else 'MARGINAL'
                    deviations.append({**base, 'type': 'Missed Open', 'chart': chart_name,
                                       'confidence': conf})
        
        # ============================================================
        # SCENARIO B: FACING ONE OPEN (flat, 3-bet, or fold)
        # ============================================================
        elif h.get('hero_faced_raise') and pf_raise_count == 1 and not h.get('first_in'):
            if not opener_pos or opener_pos == 'UNK': continue
            
            # BB DEFENSE — separate logic using BB_DEF charts
            if pos == 'BB':
                # B29 fix: apply n_players-aware position shift before pct lookup.
                # An "UTG" at 7-max has fewer to act behind than "UTG" at 8-max,
                # opens looser, so BB defends like vs UTG+1@8max. Same shift logic
                # _open_chart_pos uses for hero opens — applied here for parity.
                shifted_opener = _open_chart_pos(opener_pos, n_players)
                # Derive opener open% from OPEN chart widths when available
                _opm_defaults = {'UTG': 15, 'UTG+1': 20, 'MP': 25, 'HJ': 30,
                                 'CO': 35, 'BTN': 45, 'SB': 50}
                _opm = dict(_opm_defaults)
                for _op_pos in _opm_defaults:
                    _op_widths = []
                    for _rk, _rv in ranges.items():
                        if _rk.startswith('OPEN_') and _rk.endswith(f'_{_op_pos}'):
                            _op_widths.append(round(len(_rv) / 169 * 100))
                    if _op_widths:
                        _opm[_op_pos] = round(sum(_op_widths) / len(_op_widths))
                opener_pct = _opm.get(shifted_opener, 30)
                pct_options = [15, 20, 25, 30, 35, 40, 45, 50]
                closest = min(pct_options, key=lambda x: abs(x - opener_pct))
                bb_def_name = f"BB_DEF_vsSB{closest}pct" if opener_pos == 'SB' else f"BB_DEF_vs{closest}pct"
                bb_def_chart = ranges.get(bb_def_name, set())
                # v8.12.1 C3 (exact-chart-only): when an opener-keyed BBD
                # chart pair exists, defend = CALL union 3BET from the
                # measured chart for THIS opener (vs CO is far wider than vs
                # BTN). Missing pair -> the pct-width fallback above stands.
                _bbd_dk = ('20BB' if stack <= 25 else
                           '35BB' if stack <= 42 else '50BB')
                _bbd_c = ranges.get(f'BBD_{_bbd_dk}_vs{shifted_opener}_CALL')
                _bbd_3 = ranges.get(f'BBD_{_bbd_dk}_vs{shifted_opener}_3BET')
                if _bbd_c or _bbd_3:
                    bb_def_name = f'BBD_{_bbd_dk}_vs{shifted_opener}'
                    bb_def_chart = set(_bbd_c or ()) | set(_bbd_3 or ())
                
                if bb_def_chart:
                    if not h['vpip'] and hs in bb_def_chart:
                        deviations.append({**base, 'type': 'Missed BB Defend', 'chart': bb_def_name,
                                           'confidence': 'MARGINAL', 'opener': opener_pos,
                                           'opener_effective': shifted_opener, 'n_players': n_players})
                    elif h['vpip'] and hs not in bb_def_chart:
                        deviations.append({**base, 'type': 'Wide BB Defend', 'chart': bb_def_name,
                                           'confidence': 'MARGINAL', 'opener': opener_pos,
                                           'opener_effective': shifted_opener, 'n_players': n_players})
                continue  # BB done, skip the LP/MP defend logic below
            
            cpos = _chart_pos(pos)
            cop = _chart_pos(opener_pos)
            depth = _depth_tier_flat3b(stack)
            
            # Look up FLAT3B chart (continue range: flat or 3-bet)
            flat3b_name = f"FLAT3B_{depth}_{cpos}vs{cop}"
            flat3b_chart = ranges.get(flat3b_name, set())
            # Fallback: some charts use generic "vsBTN" etc
            if not flat3b_chart:
                flat3b_name = f"FLAT3B_{depth}_vs{cop}"
                flat3b_chart = ranges.get(flat3b_name, set())
            
            # Look up REJAM chart (jam sub-range)
            rejam_name = f"REJAM_{cpos}vs{cop}"
            rejam_chart = ranges.get(rejam_name, set())
            
            if flat3b_chart:
                if not h['vpip'] and hs in flat3b_chart:
                    # Folded a hand that should continue
                    conf = 'CLEAR' if hs in (rejam_chart or set()) else 'MARGINAL'
                    deviations.append({**base, 'type': 'Missed Defend/3-Bet', 'chart': flat3b_name,
                                       'confidence': conf, 'opener': opener_pos})
                elif h.get('hero_3bet') and hs not in flat3b_chart:
                    deviations.append({**base, 'type': 'Wide 3-Bet', 'chart': flat3b_name,
                                       'confidence': 'CLEAR', 'opener': opener_pos})
            
            if rejam_chart and h['vpip'] and not h.get('hero_3bet'):
                # Hero flatted but should have jammed
                # REJAM charts assume short-stack play. Only flag at <35BB where
                # a 3-bet essentially commits you. Above 35BB, non-all-in 3-bet
                # or flat are both valid — jamming is not the only correct action.
                if hs in rejam_chart and stack < 35:
                    deviations.append({**base, 'type': 'Missed Rejam', 'chart': rejam_name,
                                       'confidence': 'CLEAR', 'opener': opener_pos})
                elif hs in rejam_chart and stack < 50:
                    deviations.append({**base, 'type': 'Missed Rejam', 'chart': rejam_name,
                                       'confidence': 'MARGINAL', 'opener': opener_pos})
        
        # ============================================================
        # SCENARIO E: HERO FACES A SINGLE LIMP, ISO-RAISES OR ISO-JAMS
        # ============================================================
        # Closes the 52s gap (Ron 2026-05-17, hand TM5962754945): BvB
        # BB iso-jam vs SB limp at 15BB eff with 52s was never flagged
        # because SCENARIO A requires first_in (not true if SB already
        # limped) and SCENARIO B requires hero_faced_raise (not true
        # for a limp). Iso vs limp had NO detector.
        #
        # Logic: flag when Hero iso-raises/iso-jams a SHORT-STACK hand
        # (eff < 25BB) below a conservative iso-jam threshold. The
        # threshold mirrors the "any-two-playable" base but excludes
        # the unplayable bottom (low offsuit garbage, junk gappers).
        # Hands like 52s, 72s, 32o, 84o below threshold = flagged.
        if (h.get('vpip') and h.get('pfr')
                and not h.get('first_in')
                and not h.get('hero_faced_raise')
                and h.get('bb_iso_sb_limp')):
            # BB iso vs SB limp specifically — most common BvB case
            eff_stack = h.get('eff_stack_bb_at_decision', stack)
            is_jam = bool(h.get('pf_allin'))
            # Threshold: hands that should iso-raise or iso-jam BvB
            # at 15-25BB eff. Excludes unplayable bottom-of-range.
            # Derived from REJAM_BBvsSB + standard short-stack iso range.
            iso_threshold_short = {
                # All pairs
                'AA','KK','QQ','JJ','TT','99','88','77','66','55','44','33','22',
                # All Ax
                'AKs','AQs','AJs','ATs','A9s','A8s','A7s','A6s','A5s','A4s','A3s','A2s',
                'AKo','AQo','AJo','ATo','A9o','A8o','A7o','A6o','A5o','A4o','A3o','A2o',
                # Kx down to K6
                'KQs','KJs','KTs','K9s','K8s','K7s','K6s',
                'KQo','KJo','KTo','K9o','K8o',
                # Qx broadways + suited down to Q8
                'QJs','QTs','Q9s','Q8s','QJo','QTo','Q9o',
                # Jx broadways + suited down to J8
                'JTs','J9s','J8s','JTo','J9o',
                # Suited connectors and 1-gappers from T down
                'T9s','T8s','T7s','98s','97s','87s','86s','76s','75s','65s','64s','54s',
                # Selected suited bluffs (frequency-mix in equilibrium)
                'K5s','K4s','K3s','K2s', 'Q7s','J7s',
            }
            if hs and hs not in iso_threshold_short and eff_stack < 25:
                conf = 'CLEAR' if is_jam else 'MARGINAL'
                deviations.append({**base, 'type': 'Wide BvB Iso (vs limp)',
                                   'chart': 'iso_threshold_short_bvb',
                                   'confidence': conf,
                                   'opener': 'SB-limp',
                                   'n_players': h.get('n_players', 0)})

        # ============================================================

        elif h.get('pfr') and h.get('villain_jammed') and pf_raise_count >= 2:
            # Find who jammed — look at preflop sequence for the jammer
            jammer_pos = h.get('jammer_position', '')
            jammer_bb = h.get('jammer_stack_bb', 0)
            if not jammer_pos:
                # Fallback: parse from sequence
                for step in h.get('pf_sequence', []):
                    if '(H)' in step: continue
                    if 'raises' in step or 'calls' in step:
                        jammer_pos = step.split(':')[0].strip()
                if not jammer_pos: continue
            
            cpos = _chart_pos(pos)  # Hero position
            cjam = _chart_pos(jammer_pos)
            callrj_name = f"CALLRJ_{cpos}vs{cjam}"
            callrj_chart = ranges.get(callrj_name, set())
            
            if callrj_chart:
                hero_called = h['vpip'] and not h.get('fold_to_3bet') and not h.get('fold_to_4bet')
                if not hero_called and hs in callrj_chart:
                    deviations.append({**base, 'type': 'Missed Call-Rejam', 'chart': callrj_name,
                                       'confidence': 'CLEAR', 'jammer': jammer_pos})
                elif hero_called and hs not in callrj_chart:
                    deviations.append({**base, 'type': 'Wide Call-Rejam', 'chart': callrj_name,
                                       'confidence': 'CLEAR', 'jammer': jammer_pos})
    
        # ============================================================
        # SCENARIO D: CALL VILLAIN JAM (CVJ) — villain jammed,
        # Hero calls (or iso-raises). v7.10. Standalone check.
        # B-V10 BUG-3 (2026-06-01): gate tightened — skip multiway pots
        # where ≥3 players saw the flop. CVJ is a HU call-vs-jam decision;
        # a multiway limped/raised pot with an incidental all-in is a
        # different spot the detector wasn't designed for.
        # ============================================================
        _paf_d = h.get('players_at_flop', 0) or 0
        if (h.get('villain_jammed') and h.get('vpip') and stack > 8
                and _paf_d <= 2):
            jammer_pos_raw = h.get('jammer_position', '')
            jammer_bb = h.get('jammer_stack_bb', 0)
            if jammer_pos_raw and hs:
                # Determine calling thresholds by jammer position
                ep_positions = {'UTG', 'UTG+1', 'EP'}
                mp_positions = {'MP', 'LJ'}
                lp_positions = {'HJ', 'CO', 'BTN'}
                
                # B120 (Ron 2026-05-20): stack-adjusted threshold, SHARED by
                # both the call (CVJ) and the re-jam-over-jam path. Previously
                # the re-jam path used FLAT thresholds with no jammer-stack
                # adjustment, so 88 re-jamming over a ~13BB UTG+1 shove was
                # flagged "Wide Iso-Jam" → P1-IsoJam punt. That is wrong:
                # re-jamming a hand you would correctly CALL the jam with is
                # never a punt — re-jamming adds fold equity / isolation when
                # Hero covers, so the re-jam range is AT LEAST as wide as the
                # CVJ-call range. NB: this branch is a re-jam OVER A JAM, not
                # an iso-jam over limpers; the legacy "Iso-Jam" flag label is
                # retained only for tracker continuity.
                if jammer_pos_raw in ep_positions:
                    threshold = ({'AA','KK','QQ','JJ','TT','99','88','AKs','AQs','AJs','ATs','AKo','AQo','AJo','KQs'}
                                 if jammer_bb <= 15 else
                                 {'AA','KK','QQ','JJ','TT','AKs','AQs','AKo'})
                elif jammer_pos_raw in mp_positions:
                    threshold = ({'AA','KK','QQ','JJ','TT','99','88','77','AKs','AQs','AJs','ATs','A9s','AKo','AQo','AJo','ATo','KQs','KJs'}
                                 if jammer_bb <= 15 else
                                 {'AA','KK','QQ','JJ','TT','99','AKs','AQs','AJs','AKo','AQo'})
                elif jammer_pos_raw in lp_positions:
                    threshold = ({'AA','KK','QQ','JJ','TT','99','88','77','66','AKs','AQs','AJs','ATs','A9s','AKo','AQo','AJo','ATo','KQs','KJs','KTs','QJs'}
                                 if jammer_bb <= 15 else
                                 {'AA','KK','QQ','JJ','TT','99','88','AKs','AQs','AJs','ATs','AKo','AQo','AJo','KQs'})
                else:
                    threshold = {'AA','KK','QQ','JJ','TT','99','88','AKs','AQs','AJs','AKo','AQo','AJo','KQs'}
                if h.get('pfr'):
                    # Hero RE-RAISED ALL-IN over a villain jam.
                    # v7.30 P1-3: shared prereq schema. detector_prereq_satisfied()
                    # checks Hero is all-in (re-JAM, not raise-with-stack-behind).
                    # Recurring exception in gem_exceptions_log.csv #1, #2, #3.
                    if not detector_prereq_satisfied('wide_iso_jam', h):
                        continue
                    # B176 (Ron 2026-05-25): when Hero re-jams over a jam AND
                    # covers the jammer, the chips committed vs the jammer are
                    # identical to a flat call (the excess is returned) - vs
                    # the jammer it IS a call; the raise only isolates players
                    # still to act. Label it a CVJ (call decision), evaluated
                    # on the shared call threshold (B120). True "Iso-Jam"
                    # framing is kept only when Hero does NOT cover.
                    _hero_covers = (stack or 0) >= (jammer_bb or 0)
                    _n_behind = len(h.get('stacks_behind') or {})
                    # Iteration-1 root fix (83915520): the legacy detector
                    # labelled EVERY covering re-jam "re-jam over jam", but the
                    # canonical decision model treats a HU covering re-jam as a
                    # call vs the jammer (the excess is returned \u2014 exactly the
                    # B176 reasoning above). Only keep the "re-jam over jam"
                    # framing when the canonical action kind is a genuine
                    # side-pot over-jam that isolates a live opponent. A
                    # canonical call_vs_jam renders as a plain CVJ call so the
                    # report/worklist never show "re-jam over jam" for a call.
                    try:
                        from gem_decision_snapshot import hero_action_kind as _ds_akind
                        _canon_kind = _ds_akind(h)
                    except Exception:
                        _canon_kind = None
                    _genuine_rejam = _canon_kind == 'overjam_with_side_pot'
                    if _hero_covers and _genuine_rejam:
                        flag_type = 'Wide CVJ \u2014 re-jam over jam (covers)'
                        flag_note = (f'Re-jam over {jammer_pos_raw} jam '
                                     f'({round(jammer_bb)}BB) with {hs} \u2014 '
                                     f'Hero covers, so vs the jammer this is a '
                                     f'call; the raise isolates {_n_behind} '
                                     f'player(s) behind')
                    elif _hero_covers:
                        # Canonical call_vs_jam \u2014 HU covering re-jam == a call
                        # vs the jammer. No "re-jam over jam" framing.
                        flag_type = 'Wide CVJ (Call Villain Jam)'
                        flag_note = (f'Called {jammer_pos_raw} jam '
                                     f'({round(jammer_bb)}BB) with {hs}')
                    else:
                        # Defensive fallback - effectively unreachable: to
                        # RAISE over a jam Hero must out-chip it, so every
                        # pfr re-jam-over-jam covers the jammer. A Hero who
                        # cannot cover can only call all-in (pfr=False) and
                        # routes to the plain-CVJ branch below.
                        flag_type = 'Wide Iso-Jam'
                        flag_note = f'Re-jammed {hs} over {jammer_pos_raw} jam ({round(jammer_bb)}BB)'
                else:
                    flag_type = 'Wide CVJ (Call Villain Jam)'
                    flag_note = f'Called {jammer_pos_raw} jam ({round(jammer_bb)}BB) with {hs}'

                # v7.43 (Ron 2026-05-09): context modifiers — expand the base
                # threshold based on PKO bounty equity, Ace blocker, and short
                # jammer wide-range adjustment. Then ICM-aware confidence
                # demotion in late phases (bubble/post-bubble/ft).
                ctx_threshold = set(threshold)
                ctx_notes = []
                fmt = (h.get('format') or '').upper()
                # PKO/BOUNTY: bounty equity widens iso-jam range by ~2-3 BB EV
                # via bounty potential. Add Ax-suited, suited broadways, mid pairs.
                if fmt in ('BOUNTY', 'PKO'):
                    # v8.12.1 C2 (review guardrail): NO hand-authored bonus
                    # sets. The widening is the measured diff between the
                    # extracted PKO_OPEN_* chart and the Classic OPEN_* chart
                    # for this position at the nearest extracted depth; no
                    # chart pair -> no bonus (Classic + caveat). BTN tightens
                    # in the research and now correctly gets nothing.
                    _pko_add, _pko_note = _pko_open_chart_bonus(
                        h.get('position', ''), h.get('stack_bb', 0))
                    if _pko_add:
                        ctx_threshold |= _pko_add
                        ctx_notes.append(_pko_note)
                # Ace blocker: holding an Ace removes ~25% of villain AA/AK
                # combos — reduces dominator weight in caller range, expands
                # Ax-suited iso-jam.
                if hs and (hs[0].upper() == 'A' or (len(hs) > 1 and hs[1].upper() == 'A')):
                    ctx_threshold |= {'A9s','A8s','A7s','A6s','A5s','A4s','A3s','A2s'}
                    ctx_notes.append('Ax blocker')
                # Short jammer (≤12BB): jammer's range is wide (e.g. <=10BB
                # often any pair, any Ace, any broadway), so Hero's iso-jam /
                # CVJ range correspondingly widens since dominator combos
                # are diluted.
                if jammer_bb and jammer_bb <= 12:
                    ctx_threshold |= {'ATs','A9s','A8s','A7s','A6s','A5s',
                                      'KQs','KJs','KTs','QJs','QTs','JTs',
                                      '99','88','77','66','55',
                                      'ATo','A9o','KQo','KJo','QJo'}
                    ctx_notes.append(f'short jammer ({round(jammer_bb)}BB)')

                if hs in ctx_threshold:
                    continue  # in expanded threshold — not a deviation

                # ICM-aware confidence: bubble/post-bubble/ft phases demote
                # CLEAR → MARGINAL because ladder-up considerations may justify
                # tighter play that the chip-EV detector can't see. Ron's
                # request 2026-05-09: don't auto-mark as confirmed mistake;
                # surface it with the ICM context so review can decide.
                phase = h.get('tournament_phase', '')
                base_conf = 'CLEAR'
                _icm_p = h.get('icm_pressure', 0) or 0
                if _icm_p >= 0.5:
                    base_conf = 'MARGINAL'
                    ctx_notes.append(f'ICM pressure: {_icm_p:.2f} — ladder-up may justify')

                if ctx_notes:
                    flag_note = f'{flag_note} | context: {", ".join(ctx_notes)}'

                # B175 (Ron 2026-05-25): show the villain JAM range and Hero's
                # equity vs it - the CVJ note now answers "called what, vs
                # what, at what price", not just "outside threshold".
                _cvjq = _cvj_villain_equity(jammer_pos_raw, jammer_bb,
                                            h.get('cards'), fmt, stack)
                if _cvjq:
                    flag_note = (f"{flag_note} | Villain {jammer_pos_raw} "
                                 f"~10BB push range (~{_cvjq['n_combos']} "
                                 f"combos): Hero {hs} ~{_cvjq['hero_eq_pct']}% "
                                 f"equity, call price ~{_cvjq['req_eq_pct']}% "
                                 f"({_cvjq['verdict']})")

                # B-V10 (2026-06-01): eff_stack_bb = min(Hero, jammer).
                # Without this, the report shows Hero's nominal stack (62BB)
                # when the decision-relevant stack is the jammer's (5.8BB).
                _eff_cvj = round(min(stack, jammer_bb), 1) if jammer_bb else round(stack)
                deviations.append({**base, 'type': flag_type,
                                   'confidence': base_conf,
                                   'jammer': jammer_pos_raw,
                                   'jammer_bb': round(jammer_bb),
                                   'eff_stack_bb': _eff_cvj,
                                   'tournament_phase': phase,
                                   # B150 (Ron 2026-05-23): carry the context-
                                   # adjusted iso-jam range so the report can
                                   # SHOW the correct range beside the flag.
                                   'iso_range': sorted(ctx_threshold),
                                   # B175: structured villain-jam-range equity.
                                   'cvj_villain_chart': (_cvjq or {}).get('chart'),
                                   'cvj_hero_eq_pct': (_cvjq or {}).get('hero_eq_pct'),
                                   'cvj_req_eq_pct': (_cvjq or {}).get('req_eq_pct'),
                                   'note': flag_note})
        
        # ============================================================
        # SCENARIO F: ICM PRESSURE FLAG — medium pair jam >30BB in bubble+. v7.11
        # ============================================================
        if h.get('pfr') and h.get('pf_allin') and stack > 30:
            phase = h.get('tournament_phase', '')
            medium_pairs = {'22','33','44','55','66','77','88','99','TT'}
            if phase in ('bubble_zone', 'post_bubble', 'ft_zone') and hs in medium_pairs:
                deviations.append({**base, 'type': 'ICM Pressure Flag',
                                   'confidence': 'MARGINAL',
                                   'tournament_phase': phase,
                                   'note': f'{hs} jam at {round(stack)}BB in {phase} — review ICM'})
        
        # ============================================================
        # SCENARIO G: ICM FLAT ALERT — flat-call in ICM phase from non-BTN/BB.
        # v7.10 original: FT Flat Alert (EP/MP openers, level≥15 heuristic, EP/MP only)
        # v7.25 expanded (J43): tournament_phase-based trigger covering
        # bubble_zone / post_bubble / ft_zone, ANY opener position, Hero
        # position ∉ {BTN, BB}. BTN closes action, BB has good odds → both
        # are natural flatting positions in ICM and excluded.
        # Subject to Leak Validation Gate before promotion to confirmed leak.
        # ============================================================
        if h.get('vpip') and not h.get('pfr') and h.get('hero_faced_raise'):
            phase = h.get('tournament_phase', '')
            hero_pos_for_j43 = h.get('position', '')
            opener = h.get('opener_position', '')
            non_flat_positions = {'UTG', 'UTG+1', 'UTG+2', 'MP', 'HJ', 'CO', 'SB'}
            if (phase in _ICM_PHASES
                    and hero_pos_for_j43 in non_flat_positions
                    and stack < 80
                    and opener):  # opener identified (not a limped pot)
                deviations.append({**base, 'type': 'ICM Flat Alert',
                                   'confidence': 'MARGINAL',
                                   'requires_confirmation': True,
                                   'opener': opener,
                                   'tournament_phase': phase,
                                   'note': f'Flatted {opener} open from {hero_pos_for_j43} in {phase} with {hs} ({round(stack)}BB) — J43: raise/fold preferred (3-bet or fold, no flat)'})

    # v7.36 (#6 enhancement): enrich each deviation with chart context so the
    # renderer can show what's actually in the chart. Replaces prior single-
    # boundary "loosest hand per category" representation that misled because
    # rank-sum is not a valid 1D ordering of poker hands.
    for d in deviations:
        chart_name = d.get('chart')
        if not chart_name: continue
        chart_set = ranges.get(chart_name) or set()
        d['chart_size'] = len(chart_set)
        d['chart_summary'] = _chart_summary(chart_set)
        # Whether this hand IS in the chart (for "wide" we expect not-in;
        # for "missed" we expect in). Useful for the renderer's reasoning column.
        d['in_chart'] = (d.get('cards') in chart_set)
        # v7.39 — B32 mitigation: if the chart was augmented to pass sanity
        # checks, mark the deviation so the renderer can show ⚠️ chart-augmented.
        # This lets Ron spot deviations that fired against a fixed-up chart vs
        # the raw OCR output.
        if chart_name in _RANGE_SANITY_REPORT:
            d['chart_augmented'] = True
            d['chart_augmented_count'] = _RANGE_SANITY_REPORT[chart_name]['augmented_count']
            # Downgrade verdict on Wide-* flags from corrupted charts: if Hero's
            # action was "wide" (i.e. Hero opened/3-bet a hand the chart says
            # fold), and the chart was missing premium content, the chart can't
            # be trusted to call it a Wide flag. Downgrade CLEAR→MARGINAL.
            if d.get('type', '').startswith('Wide ') and d.get('confidence') == 'CLEAR':
                d['confidence'] = 'MARGINAL'
                d['confidence_downgrade_reason'] = 'chart_augmented (B32)'

    # v8.12.1 P1 (owner-approved): chart-backed Missed 3-Bet / Missed
    # Squeeze. EXACT-CHART-ONLY - the key must exist for position, opener,
    # caller and depth; anything else is silent (no heuristic fallback).
    deviations.extend(_g1_g2_chart_deviations(hands, ranges))
    # v8.12.2 P3 scaffolding: dark until CC_/F3B_/BVB_/ISO_ charts land.
    deviations.extend(_dark_chart_detectors(hands, ranges))
    return deviations



# ============================================================
# 2b. TOURNAMENT PHASE ESTIMATOR (v8.6.3 chip-fraction model)
# ============================================================
# v8.6.3: replaced level-proxy heuristic with chip-fraction model.
# Core identity: field × start_stack = players_left × avg_stack
# so field_fraction = start_stack / avg_stack (no field size needed).
# Validated: 86-89% terminal accuracy vs 65-73% incumbent.
# See gem_phase.py for the full implementation.

def estimate_tournament_phases(hands, summaries=None):
    """Assign tournament_phase + new orthogonal axes to each hand.
    v8.6.3: uses chip-fraction model via gem_phase module.
    Falls back to level proxy if gem_phase import fails."""
    # First: run the OLD estimator to populate old_phase (QA comparison)
    _legacy_estimate_tournament_phases(hands)
    for h in hands:
        h['old_phase'] = h.get('tournament_phase', '')

    # Then: run the NEW chip-fraction estimator
    try:
        from gem_phase import estimate_tournament_phases_v2
        estimate_tournament_phases_v2(hands, summaries=summaries)
        # QA: count disagreements
        _n_disagree = sum(1 for h in hands
                          if h.get('old_phase', '') != h.get('legacy_phase', '')
                          and h.get('old_phase', '') and h.get('legacy_phase', ''))
        _n_total = sum(1 for h in hands if h.get('old_phase', ''))
        if _n_total:
            print(f"  Phase QA: {_n_disagree}/{_n_total} hands differ "
                  f"({100*_n_disagree/_n_total:.1f}%) between old and new phase model")
    except Exception as e:
        print(f"  ⚠️ gem_phase import failed ({e}), using level-proxy fallback")
        # old_phase is already set; tournament_phase stays from legacy


def _legacy_estimate_tournament_phases(hands):
    """Assign tournament_phase to each hand based on level, format speed, and table fullness."""
    
    # Group by tournament
    tourney_hands = defaultdict(list)
    for h in hands:
        tourney_hands[h['tournament']].append(h)
    
    for tname, th in tourney_hands.items():
        # Detect format speed from tournament name
        name_upper = tname.upper()
        if 'HYPER' in name_upper:
            late_reg_end = 6    # Hyper: late reg ~Level 4-6
            bubble_start = 10   # Bubble zone starts
            bubble_end = 16     # Bubble likely burst
        elif 'TURBO' in name_upper:
            late_reg_end = 10   # Turbo: late reg ~Level 8-10
            bubble_start = 18   # Bubble zone starts
            bubble_end = 26     # Bubble likely burst
        else:
            late_reg_end = 14   # Standard: late reg ~Level 10-14
            bubble_start = 22   # Bubble zone starts
            bubble_end = 30     # Bubble likely burst
        
        for h in th:
            level = h.get('level', 0)
            n_pl = h.get('n_players', 9)
            ts = h.get('table_size', 8)
            short_table = n_pl < ts
            
            if level <= late_reg_end:
                phase = 'late_reg'
            elif level <= bubble_start:
                phase = 'post_reg'
            elif level <= bubble_end:
                phase = 'bubble_zone'
            elif short_table or n_pl <= 6:
                phase = 'ft_zone'
            else:
                phase = 'post_bubble'
            
            # Override: if HU (2 players), always ft_zone
            if n_pl == 2:
                phase = 'ft_zone'
            
            h['tournament_phase'] = phase



def _versioned_path(directory, prefix, date, ext, pname_file, tag=''):
    """Find next available version: prefix_pname_date[_TAG]_V1.ext, V2, ...
    v8.12.10: optional `tag` (e.g. AUTO_ONLY) is embedded before the
    version so an auto-only report is impossible to mistake for final."""
    _tag = f"_{tag}" if tag else ''
    v = 1
    while True:
        path = os.path.join(directory,
                            f"{prefix}_{pname_file}_{date}{_tag}_V{v}.{ext}")
        if not os.path.exists(path):
            return path
        v += 1


def _decode_lazy_cards(html_str):
    """v8.14.3 Issue 4: decode PB_PAYLOADS['lazyHands'] -> {hand_key: card_html}
    INLINE so the render validator can inspect the real user-visible hand detail
    in ANY runtime (the QA-only _qa_decode_lazy helper is not in the shipped
    bundle). Mirrors that decoder's format handling. Returns {} if absent or
    undecodable."""
    import re as _re_lz, json as _json_lz, base64 as _b64_lz, zlib as _zlib_lz
    m = _re_lz.search(
        r'PB_PAYLOADS\[(?:"|\')lazyHands(?:"|\')\]\s*=\s*(\{[^}]*\})', html_str)
    if not m:
        return {}
    try:
        obj = _json_lz.loads(m.group(1))
        raw = _b64_lz.b64decode(obj.get('data', ''))
        enc = obj.get('encoding', '')
        if enc == 'deflate-raw+base64':
            raw = _zlib_lz.decompress(raw, -15)
        elif enc in ('deflate+base64', 'zlib+base64'):
            raw = _zlib_lz.decompress(raw)
        out = _json_lz.loads(raw.decode('utf-8'))
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def _quick_validate_render(html_str, rd=None):
    """v8.12.10: lightweight post-render check for --quick (full validation
    lives in the main path). Catches the broken-anchor + missing-global
    classes that slipped through quick renders (e.g. #sec-7-4). Returns a
    list of issue strings (empty = clean).

    v8.14.3 Issue 4 (Ron 2026-06-15): when ``rd`` is supplied this is the real
    pipeline trust gate — it DECODES the lazy hand payload (not just the static
    shell) and asserts the v8.14.2 post-report defects cannot recur: financial
    agreement across header / overlay / top-level, no visible "awaiting analyst"
    in an ANALYST_COMPLETE report, and no analyst-critical hand left as a
    budget_trimmed stub."""
    import re as _re_qv
    issues = []
    # internal #anchors that have no matching id=
    _ids = set(_re_qv.findall(r'id=["\']([\w-]+)["\']', html_str))
    _hrefs = set(_re_qv.findall(r'href=["\']#([\w-]+)["\']', html_str))
    _dead = sorted(h for h in _hrefs if h and h not in _ids
                   and not h.startswith('sec-app-hand-'))  # lazy anchors live in payload
    if _dead:
        issues.append(f'{len(_dead)} broken anchor link(s): {_dead[:8]}')
    # required JS globals the report's interactivity depends on
    for _g in ('window.PB_PAYLOADS', 'window.handIndex', 'window.handAvailability'):
        if _g + '=' not in html_str and _g + ' =' not in html_str:
            issues.append(f'missing JS global {_g}')
    # raw f-string leaks in visible text
    if _re_qv.search(r'>\s*\{[a-z_]+\}\s*<', html_str):
        issues.append('unresolved {placeholder} in visible text')

    # ---- v8.14.3 Issue 4: pipeline trust checks (decode payload, not shell) ----
    if isinstance(rd, dict):
        _rc = rd.get('report_completeness') or {}
        # (1) no visible "awaiting analyst" when the report claims COMPLETE
        if _rc.get('state') == 'ANALYST_COMPLETE':
            _n_await = html_str.lower().count('awaiting analyst')
            if _n_await:
                issues.append(f'{_n_await} visible "awaiting analyst" label(s) in an '
                              f'ANALYST_COMPLETE report (Issue 2)')
        # (2) financial agreement: top-level total_invested / avg_buyin must equal
        #     the parsed overlay totals (single source of truth)
        _ov = rd.get('usd_overlay') or {}
        _ovt = _ov.get('totals') or {}
        if _ov.get('status') == 'parsed' and _ovt.get('total_cost') and _ovt.get('n_bullets'):
            _exp_inv = round(float(_ovt['total_cost']), 2)
            _exp_abi = round(float(_ovt['total_cost']) / float(_ovt['n_bullets']), 2)
            if abs(round(float(rd.get('total_invested') or 0), 2) - _exp_inv) > 0.01:
                issues.append(f'financial mismatch: top-level total_invested '
                              f'{rd.get("total_invested")} != overlay total_cost {_exp_inv} (Issue 1)')
            if abs(round(float(rd.get('avg_buyin') or 0), 2) - _exp_abi) > 0.01:
                issues.append(f'financial mismatch: top-level avg_buyin '
                              f'{rd.get("avg_buyin")} != overlay cost/bullets {_exp_abi} (Issue 1)')
        # (2b) v8.14.4: when the overlay carries satellite ticket value, the active
        #      financial surface MUST visibly disclose the cash+ticket return basis
        #      (the v8.14.3 footnote lived in the disabled S7 path, so it never
        #      rendered). Guard the active by-day/financial disclosure.
        if _ov.get('status') == 'parsed' and float(_ovt.get('total_ticket_value') or 0) > 0:
            _tl = html_str.lower()
            _has_basis = ('cash + ticket' in _tl
                          or ('ticket value' in _tl and 'cash' in _tl))
            if not _has_basis:
                issues.append('financial: total_ticket_value > 0 but no visible '
                              'cash + ticket return-basis disclosure on the rendered '
                              'financial surface (v8.14.4)')
        # (3) analyst-critical hands must NOT be budget_trimmed, and the DECODED
        #     lazy payload must carry their full detail (not just a shell stub).
        #     Critical = analyst verdict III.1/III.2 OR significant/critical loss.
        _ac = rd.get('analyst_commentary') or {}
        _crit_suf = set()                       # 8-digit suffixes of critical hands
        for _hid, _cmt in _ac.items():
            if str(_hid).startswith('__') or not isinstance(_cmt, dict):
                continue
            _vd = str(_cmt.get('verdict', '') or '')
            if _vd.startswith('III.1') or _vd.startswith('III.2'):
                _crit_suf.add(str(_hid)[-8:])
        for _src in ('_significant_loss_ids', '_critical_need_ids'):
            for _x in (rd.get(_src) or []):
                _crit_suf.add(str(_x)[-8:])
        _crit_suf = {s for s in _crit_suf if s and s.isdigit()}
        if _crit_suf:
            # (3a) static shell: any budget_trimmed card whose id is a critical hand
            _trim_ids = {m[-8:] for m in _re_qv.findall(
                r"data-hand-id=['\"]([\w-]+)['\"]\s+data-availability=['\"]budget_trimmed['\"]",
                html_str)}
            _bad_trim = sorted(_crit_suf & _trim_ids)
            if _bad_trim:
                issues.append(f'{len(_bad_trim)} analyst-critical hand(s) rendered '
                              f'budget_trimmed: {_bad_trim[:8]} (Issue 3)')
            # (3b) DECODE the lazy payload — critical hands present there must not
            #      be a trimmed stub (defence-in-depth beyond the shell markers).
            _cards = _decode_lazy_cards(html_str)
            if _cards:
                _stub = 'trimmed for report size'
                _by_suf = {}
                for _k, _v in _cards.items():
                    if isinstance(_v, str):
                        _by_suf.setdefault(str(_k)[-8:], _v)
                _bad_stub = sorted(s for s in _crit_suf
                                   if s in _by_suf and _stub in _by_suf[s])
                if _bad_stub:
                    issues.append(f'{len(_bad_stub)} analyst-critical hand(s) are stub-only '
                                  f'in the decoded lazy payload: {_bad_stub[:8]} (Issue 3)')
        # (4) no full+trimmed DUPLICATE: a hand must not appear both as a
        #     budget_trimmed shell stub AND a full lazy card (Issue 3 dedup).
        _trim_all = {m[-8:] for m in _re_qv.findall(
            r"data-hand-id=['\"]([\w-]+)['\"]\s+data-availability=['\"]budget_trimmed['\"]",
            html_str)}
        if _trim_all:
            _cards2 = _decode_lazy_cards(html_str)
            _stub2 = 'trimmed for report size'
            _full_suf = {str(_k)[-8:] for _k, _v in _cards2.items()
                         if isinstance(_v, str) and _stub2 not in _v}
            _dup = sorted(_trim_all & _full_suf)
            if _dup:
                issues.append(f'{len(_dup)} hand(s) rendered BOTH a budget_trimmed '
                              f'stub and a full lazy card: {_dup[:8]} (Issue 3)')
    # (5) v8.14.4 raw chart-ID guard — user-facing prose must NEVER expose a raw
    #     internal chart id (PUSH_/CALLJAM_/REJAM_/OPEN_/JAM_...). Scans the
    #     rendered shell's VISIBLE text, the DECODED lazy hand cards, and (when
    #     rd is present) the analyst-commentary prose. Machine-only uses
    #     (data-chart-id attributes, JS payload keys) are stripped by the helper,
    #     so only visible prose is flagged. Runs even without rd.
    try:
        from gem_chart_labels import find_raw_chart_ids_in_user_text as _frci
    except Exception:
        _frci = None
    if _frci is not None:
        _raw_ids = set(_frci(html_str, is_html=True))
        for _cv in (_decode_lazy_cards(html_str) or {}).values():
            if isinstance(_cv, str):
                _raw_ids.update(_frci(_cv, is_html=True))
        if isinstance(rd, dict):
            def _collect_strs(o, acc):
                if isinstance(o, str):
                    acc.append(o)
                elif isinstance(o, dict):
                    for _v in o.values():
                        _collect_strs(_v, acc)
                elif isinstance(o, (list, tuple)):
                    for _v in o:
                        _collect_strs(_v, acc)
            _ac_strs = []
            _collect_strs(rd.get('analyst_commentary') or {}, _ac_strs)
            _raw_ids.update(_frci('\n'.join(_ac_strs), is_html=False))
        if _raw_ids:
            issues.append(f'{len(_raw_ids)} raw chart ID(s) in user-facing text — '
                          f'humanize before render: {sorted(_raw_ids)[:8]} (v8.14.4)')
    return issues


def _print_completeness(rc, where=''):
    """v8.12.10: print the report completeness state + counts to the CLI so
    the operator sees AUTO_ONLY/PARTIAL/COMPLETE without reading the HTML."""
    st = rc.get('state', '?')
    print(f"\n  Analyst status: {st}{(' (' + where + ')') if where else ''}")
    print(f"    Reviewed hands: {rc.get('reviewed_hands', 0)}")
    print(f"    Candidate hands awaiting review: "
          f"{rc.get('awaiting_candidates', 0)}")
    if st == 'AUTO_ONLY':
        print("    ⚠️  No analyst file loaded — this is NOT a final report.")


_PLO_CANDIDATE_BUCKETS = (
    'mistakes', 'bust_audit', 'coolers',
    'iii4_screening', 'read_dependent_screening', 'bestplay_screening',
)

def _filter_non_nlh_from_candidate_buckets(s, non_nlh_ids):
    for key in _PLO_CANDIDATE_BUCKETS:
        if key in s and isinstance(s[key], list):
            s[key] = [x for x in s[key] if x.get('id') not in non_nlh_ids]
    if 'punts' in s and 'hands' in s['punts']:
        s['punts']['hands'] = [p for p in s['punts']['hands']
                                if p.get('id') not in non_nlh_ids]
        s['punts']['count'] = len(s['punts']['hands'])


def _is_preflop_terminal_allin(h):
    if h.get('pf_allin'):
        return True
    ledger = h.get('action_ledger') or []
    pf_allin_found = False
    hero_postflop_action = False
    for entry in ledger:
        if entry.get('street') == 'preflop' and entry.get('allin'):
            pf_allin_found = True
        if entry.get('is_hero') and entry.get('street') != 'preflop':
            hero_postflop_action = True
    if pf_allin_found and not hero_postflop_action:
        return True
    return False


def cbet_opportunity_exclusion(h):
    """v8.19.0 Chapter D (PHF-004): typed reason a flop c-bet opportunity is NOT legal,
    or None if Hero genuinely had a flop continuation-bet DECISION.

    A 'missed c-bet' is only meaningful when a c-bet was actually possible. These structural
    exclusions are the ONE owner so the same eligible set drives the denominator, the miss
    list, the popup IDs, the leak verdict, the queue candidate and Commentary — no surface
    counts an impossible opportunity.

      NO_FLOP                  -> never reached a flop
      HERO_ALL_IN_NO_DECISION  -> Hero all-in (shoved or called a jam) before any postflop action
      BETTING_CLOSED_FLOP      -> someone jammed on the flop; no clean c-bet decision existed
      NO_ACTIONABLE_CHIPS      -> SPR<=0, effective all-in / automatic runout (no chips behind)
    Initiative (wrong aggressor) and texture validity stay with the caller.
    """
    if len(h.get('board') or []) < 3:
        return 'NO_FLOP'
    if _is_preflop_terminal_allin(h):
        return 'HERO_ALL_IN_NO_DECISION'
    if h.get('flop_allin'):
        return 'BETTING_CLOSED_FLOP'
    _spr = h.get('spr')
    if _spr is not None and _spr <= 0:
        return 'NO_ACTIONABLE_CHIPS'
    return None


def is_legal_cbet_opportunity(h):
    """True iff Hero had a legal flop c-bet decision (see cbet_opportunity_exclusion)."""
    return cbet_opportunity_exclusion(h) is None


_STREET_MIN_BOARD = {'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}


def postflop_opportunity_exclusion(h, street='flop'):
    """v8.19.0 Chapter D (PHF-004) — the GENERALIZED legal-opportunity owner for EVERY postflop
    opportunity family (flop/turn/river c-bets incl. 3BP/4BP/multiway counters, probes, delayed
    c-bets, check-raises, river value, exploit). Returns the typed structural-invalidity reason or
    None. Same exclusion class as cbet_opportunity_exclusion so every family's denominator, miss
    list, popup, leak verdict, queue candidate and Commentary count only LEGAL opportunities.

      NO_STREET                -> the relevant street was never reached
      HERO_ALL_IN_NO_DECISION  -> Hero all-in before any postflop action (TM6090177176 class)
      BETTING_CLOSED_FLOP      -> a flop jam committed the pot before this decision
      NO_ACTIONABLE_CHIPS      -> SPR<=0, effective all-in / automatic runout (no chips behind)
    Initiative / aggressor / texture validity stay with the caller — we never expand detector logic.
    """
    if len(h.get('board') or []) < _STREET_MIN_BOARD.get(street, 3):
        return 'NO_STREET'
    if _is_preflop_terminal_allin(h):
        return 'HERO_ALL_IN_NO_DECISION'
    if street in ('flop', 'turn', 'river') and h.get('flop_allin'):
        return 'BETTING_CLOSED_FLOP'
    _spr = h.get('spr')
    if _spr is not None and _spr <= 0:
        return 'NO_ACTIONABLE_CHIPS'
    return None


def is_legal_postflop_opportunity(h, street='flop'):
    """True iff Hero had a legal postflop decision on `street` (see postflop_opportunity_exclusion)."""
    return postflop_opportunity_exclusion(h, street) is None


def preflop_opportunity_exclusion(h):
    """Structural invalidity for a PREFLOP raise opportunity (3-bet / 4-bet / squeeze / steal-as-
    aggressor): Hero already committed all-in before the decision means there is no raise decision.
    The family-specific raise/stack-structure gates remain the strategic owner; this only strips the
    impossible-opportunity class so preflop families share the same structural contract."""
    if _is_preflop_terminal_allin(h):
        return 'HERO_ALL_IN_NO_DECISION'
    return None


def is_legal_preflop_opportunity(h):
    return preflop_opportunity_exclusion(h) is None


def analyze_session(hands, tournaments, n_files, parse_errors, ranges=None, targets=None):
    N = len(hands)
    s = {}  # stats dict — everything the report needs
    targets = targets or {}  # v7.32: target frequency bands keyed by chart name

    # v7.11: Assign tournament_phase to every hand before analysis
    estimate_tournament_phases(hands)

    # Estimate bounty value per hand from tournament name + phase + format.
    # Used by analyst for §3b math on covers-gated spots.
    try:
        from gem_bounty import classify_bounty, phase_weight, bounty_context
        for h in hands:
            _tname = h.get('tournament', '')
            _fmt = h.get('format', '')
            _phase = h.get('tournament_phase', '')
            _bc = bounty_context(_tname, _phase, fmt=_fmt,
                                hero_covers=True)  # estimate assumes covers
            h['bounty_type'] = _bc.get('bounty_type', 'none')
            h['bounty_discount_pp'] = _bc.get('discount_pp', 0)
            h['bounty_value_bb'] = _bc.get('value_bb', 0)
            h['bounty_label'] = _bc.get('label', '')
            # v8.17.1 P5 (sub-task 4): stamp provenance so the renderer NEVER
            # presents the flat model estimate as exact or per-hand-dynamic (the
            # recurring "≈3.2BB" leak). Hierarchy: exact (recorded $) > effective_bb
            # (ratio-model) > starting_bb_flat (flat-table estimate, explicitly
            # labelled) > unavailable. No bounty_ratio is threaded here (GG HH lack
            # buy-in structure), so a real bounty stays a LABELLED flat estimate.
            h['bounty_value_provenance'] = (
                'unavailable' if h['bounty_type'] in ('none', 'unknown')
                else 'effective_bb' if _bc.get('method') == 'ratio_model'
                else 'starting_bb_flat')
    except Exception:
        for h in hands:
            h['bounty_type'] = 'unknown'
            h['bounty_discount_pp'] = 0
            h['bounty_value_bb'] = 0
            h['bounty_label'] = ''
            h['bounty_value_provenance'] = 'unavailable'

    # --- VOLUME ---
    fmt_counts = defaultdict(int)
    for h in hands: fmt_counts[h['format']] += 1
    # COR-005 (v8.18.1): report identity / title must describe the actual CONSUMED-input date coverage,
    # not one filename date. GG names a file by the tournament-START date, so a multi-day session whose
    # files all share one start date was titled as a single day. Coverage = the UNION of the file/start
    # date AND the per-hand TIMESTAMP date (hand_ts_date), so a multi-day session shows its full span
    # while a late-night session keeps its start date in the span (it is not silently shifted forward).
    _cov_dates = set()
    for _h in hands:
        if _h.get('date'):
            _cov_dates.add(_h['date'])
        if _h.get('hand_ts_date'):
            _cov_dates.add(_h['hand_ts_date'])
    all_dates = sorted(_cov_dates)
    if len(all_dates) > 1:
        # Build compact range: 2026-04-08 to 2026-04-09 → 20260408-09
        first, last = all_dates[0], all_dates[-1]
        first_compact = first.replace('-', '')
        last_compact = last.replace('-', '')
        # If same year+month, abbreviate: 20260408-09
        if first_compact[:6] == last_compact[:6]:
            date_range = f"{first_compact}-{last_compact[6:]}"
        elif first_compact[:4] == last_compact[:4]:
            date_range = f"{first_compact}-{last_compact[4:]}"
        else:
            date_range = f"{first_compact}-{last_compact}"
    else:
        date_range = (all_dates[0] if all_dates else '').replace('-', '')
    # COR-005 (v8.18.1): a readable consumed-coverage span for the visible report identity (topbar).
    # A multi-day session shows "first to last", a single day shows the one date.
    if len(all_dates) > 1:
        date_span_display = '%s to %s' % (all_dates[0], all_dates[-1])
    else:
        date_span_display = all_dates[0] if all_dates else ''
    _cov_contig = (len(all_dates) <= 1) or _dates_contiguous(all_dates)
    s['session_coverage'] = {
        'dates': all_dates, 'first_date': all_dates[0] if all_dates else '',
        'last_date': all_dates[-1] if all_dates else '', 'contiguous': _cov_contig,
        'hand_count': len(hands), 'event_count': sum(1 for _ in tournaments),
        'date_range': date_range, 'date_span_display': date_span_display,
    }
    # CP18-FIN-3 (2026-06-01): bullets = HH file count per tournament.
    # Each bullet produces one HH file in GG's export. Re-entries create
    # separate files under the same tournament_id. Using len(tournaments)
    # (B-AVIEL BUG-3) undercounted re-entries (25 → 18 for a session with
    # 7 re-entries). File-count is correct for both single-entry splits
    # (Aviel's case: multiple files = 1 bullet, handled by the report_data
    # _tid_by_tname recount) AND re-entries (Ron's case: 3 files = 3 bullets).
    _n_bullets = sum(len(t.get('files', []) or []) for t in tournaments.values())
    # BUG FIX (CP23 QA): len(tournaments) returns 0 on the cached dict-alias
    # whose __len__ is broken. Use sum(1 for _ in ...) to count correctly.
    _n_tournaments = sum(1 for _ in tournaments)
    s['volume'] = {'hands': N, 'tournaments': _n_tournaments,
                   'bullets': _n_bullets or n_files,
                   'formats': dict(fmt_counts), 'parse_errors': parse_errors,
                   'date': hands[0].get('date', '') if hands else '',
                   'date_range': date_range,
                   'date_span_display': date_span_display}   # COR-005: visible multi-day coverage span
    s['tournament_list'] = [{'name': t['name'], 'format': t['format'], 'hands': len(t['hands']),
                             'buyin': t.get('buyin', 0),
                             # v8.7.4: file-based bullet count for re-entry awareness
                             'n_files': len(t.get('files', set()) or set())}
                            for t in sorted(tournaments.values(), key=lambda x: -len(x['hands']))]

    # ---- PLO/NON-NLH EXCLUSION (v8.8.8 BUG-1) ----
    # Shadow `hands`/`N` with NLH-only for all strategic collectors.
    # Financial/volume metrics above already used the full set.
    all_hands = hands
    N_total   = N
    _gt_counts = dict(Counter(h.get('game_type', 'NLH') for h in all_hands))
    s['volume']['game_type_counts'] = _gt_counts
    _non_nlh_ct = N_total - _gt_counts.get('NLH', 0)
    if _non_nlh_ct:
        hands = [h for h in all_hands if h.get('game_type', 'NLH') == 'NLH']
        N = len(hands)
        s['volume']['nlh_hands'] = N
        print(f"  PLO gate: {_non_nlh_ct} non-NLH hands excluded from "
              f"strategic analysis ({N} NLH retained, {N_total} total)")
    else:
        s['volume']['nlh_hands'] = N

    # --- CARD QUALITY ---
    prem_ct = sum(1 for h in hands if normalize_hand(h.get('cards',[])) in PREMIUMS)
    strong_ct = sum(1 for h in hands if normalize_hand(h.get('cards',[])) in STRONG)
    suited_ct = sum(1 for h in hands if len(h.get('cards',[]))>=2 and h['cards'][0][1]==h['cards'][1][1] and h['cards'][0][0]!=h['cards'][1][0])
    pair_ct = sum(1 for h in hands if len(h.get('cards',[]))>=2 and h['cards'][0][0]==h['cards'][1][0])
    ace_ct = sum(1 for h in hands if len(h.get('cards',[]))>=2 and 'A' in (h['cards'][0][0], h['cards'][1][0]))
    rank_sums = [RANK_NUM.get(h['cards'][0][0],2)+RANK_NUM.get(h['cards'][1][0],2) for h in hands if len(h.get('cards',[]))>=2]
    # B223 (Ron review 2026-05-25): a single non-overlapping "good hands" rate
    # — the total feel of how often Hero was dealt cards worth getting.
    # The other rows overlap (AA is premium AND a pair), so this counts each
    # hand ONCE: good = premium OR strong OR any pocket pair. Suited / Aces
    # are deliberately excluded — weak suited junk and offsuit weak aces are
    # not "good" cards. Expected ~ premium 3% + strong 4% + non-premium pairs
    # ~4.4% ≈ 11.5% of deals.
    good_ct = 0
    for h in hands:
        cc = h.get('cards', [])
        if len(cc) < 2:
            continue
        nh = normalize_hand(cc)
        if nh in PREMIUMS or nh in STRONG or cc[0][0] == cc[1][0]:
            good_ct += 1
    GOOD_HANDS_EXPECTED = 11.5  # premium ∪ strong ∪ pocket pair, % of deals
    s['card_quality'] = {'premiums': prem_ct, 'premiums_pct': pct(prem_ct, N), 'strong': strong_ct,
                         'strong_pct': pct(strong_ct, N), 'prem_strong_pct': pct(prem_ct+strong_ct, N),
                         'suited_pct': pct(suited_ct, N), 'pair_pct': pct(pair_ct, N), 'ace_pct': pct(ace_ct, N),
                         'good_hands': good_ct, 'good_hands_pct': pct(good_ct, N),
                         'good_hands_expected': GOOD_HANDS_EXPECTED,
                         'avg_rank_sum': round(sum(rank_sums)/len(rank_sums), 1) if rank_sums else 0,
                         'card_cold': prem_ct/N*100 < 3.0*0.8 if N > 0 else False}

    # --- CORE STATS ---
    vpip_ct = sum(1 for h in hands if h['vpip']); pfr_ct = sum(1 for h in hands if h['pfr'])
    # v7.22 fix: ATS scope is CO+BTN only. SB included in raise-only
    # denom pulls the metric down because J29 says SB should limp 80%
    # (raise 10%). The 35-50% target was derived for CO+BTN late-pos
    # ATS, not inclusive of SB.
    ats_pos = {'CO', 'BTN'}
    ats_opps = sum(1 for h in hands if h['position'] in ats_pos and h.get('first_in'))
    ats_ct = sum(1 for h in hands if h['position'] in ats_pos and h.get('first_in') and h['pfr'])
    # Raw (legacy, including SB) for backward compat
    ats_pos_raw = {'CO', 'BTN', 'SB'}
    ats_opps_raw = sum(1 for h in hands if h['position'] in ats_pos_raw and h.get('first_in') and h['position'] != 'BB')
    ats_ct_raw = sum(1 for h in hands if h['position'] in ats_pos_raw and h.get('first_in') and h['pfr'])
    pf_bets = sum(1 for h in hands for b in h.get('hero_bets',[]) if b[2] != 'raise')
    pf_raises = sum(1 for h in hands for b in h.get('hero_bets',[]) if b[2] == 'raise')
    pf_calls = sum(1 for h in hands for b in h.get('facing_bets',[]) if b[2] == 'call')
    af = round((pf_bets + pf_raises) / pf_calls, 2) if pf_calls > 0 else 0
    bb_hands = [h for h in hands if h['position'] == 'BB']
    bb_def_opps = sum(1 for h in bb_hands if not h.get('first_in'))
    bb_def_ct = sum(1 for h in bb_hands if not h.get('first_in') and h['vpip'])
    sb_fi = sum(1 for h in hands if h['position'] == 'SB' and h.get('first_in'))
    sb_steal = sum(1 for h in hands if h['position'] == 'SB' and h.get('first_in') and h['vpip'])  # raise OR limp = pot entry (J29: limp 80%)
    # F2-3B: only count when Hero OPENED and faced a TRUE 3-bet.
    # v7.22 fix: exclude short-stack jams and short-Hero spots.
    #   A "true" F2-3B spot requires:
    #     - Hero opened (pfr=True)
    #     - At least 2 preflop raises occurred (pf_raise_count >= 2)
    #     - Hero was NOT the 3-bettor (hero_3bet=False)
    #     - Villain's EFFECTIVE stack >= 15BB (not a short-stack jam —
    #       population 55-65% fold target doesn't apply to sub-15BB jams
    #       where pot odds compel Hero to call wide)
    #     - Hero's stack >= 15BB (Hero in push/fold mode isn't facing a
    #       conventional 3-bet; it's a call-off decision governed by
    #       pot odds, not fold-to-3bet frequency)
    def _is_true_ftb_opp(h):
        if not h.get('pfr'): return False
        if h.get('pf_raise_count', 0) < 2: return False
        if h.get('hero_3bet'): return False
        if (h.get('stack_bb') or 0) < 15: return False
        # eff_stack_bb = min(Hero, relevant villain) — if <15BB, villain is short-jamming
        eff = h.get('eff_stack_bb')
        if eff is not None and eff < 15: return False
        return True
    ftb_opps_list = [h for h in hands if _is_true_ftb_opp(h)]
    ftb_opps = len(ftb_opps_list)
    ftb_ct = sum(1 for h in ftb_opps_list if h.get('fold_to_3bet'))
    # Raw (legacy) F2-3B for backward-compat / regression tracking
    ftb_opps_raw = sum(1 for h in hands if h.get('pfr') and h.get('pf_raise_count', 0) >= 2 and not h.get('hero_3bet'))
    ftb_ct_raw = sum(1 for h in hands if h.get('fold_to_3bet'))
    cr_ct = sum(len(h.get('check_raises', [])) for h in hands)
    oad_ct = sum(1 for h in hands if h.get('one_and_done'))

    # --- CHECK-RAISE FREQUENCY (v7.12) ---
    # CR% = check-raises / opportunities where hero checked and faced a bet
    # True opportunity: hero_street_actions is 'xc' (check-call), 'xf' (check-fold), or 'xr' (check-raise)
    cr_by_street = {'flop': 0, 'turn': 0, 'river': 0}
    cr_opp_by_street = {'flop': 0, 'turn': 0, 'river': 0}
    # FEAT-4 (v7.99): per-hand IDs for clickable rate cells in S11.7
    cr_hids_by_street = {'flop': [], 'turn': [], 'river': []}
    cr_opp_hids_by_street = {'flop': [], 'turn': [], 'river': []}
    for h in hands:
        if _is_preflop_terminal_allin(h) or (h.get('spr') is not None and h['spr'] <= 0): continue
        if len(h.get('board', [])) < 3: continue
        hsa = h.get('hero_street_actions', {})
        _hid = h.get('id', '')
        for street in ('flop', 'turn', 'river'):
            fa = hsa.get(street, '')
            if fa in ('xc', 'xf', 'xr'):  # hero checked and faced a bet
                cr_opp_by_street[street] += 1
                if _hid: cr_opp_hids_by_street[street].append(_hid)
                if fa == 'xr':
                    cr_by_street[street] += 1
                    if _hid: cr_hids_by_street[street].append(_hid)
        # Also catch CRs from check_raises field not captured by hero_street_actions
        for cr in h.get('check_raises', []):
            st = cr if isinstance(cr, str) else cr.get('street', '')
            if st in cr_by_street and hsa.get(st, '') != 'xr':
                cr_by_street[st] += 1
                if _hid: cr_hids_by_street[st].append(_hid)
                if st not in cr_opp_by_street or hsa.get(st, '') not in ('xc', 'xf', 'xr'):
                    cr_opp_by_street[st] += 1
                    if _hid: cr_opp_hids_by_street[st].append(_hid)
    total_cr = sum(cr_by_street.values())
    total_cr_opp = sum(cr_opp_by_street.values())
    cr_freq = {
        'flop_cr': cr_by_street['flop'], 'flop_opp': cr_opp_by_street['flop'],
        'flop_pct': pct(cr_by_street['flop'], cr_opp_by_street['flop']),
        'turn_cr': cr_by_street['turn'], 'turn_opp': cr_opp_by_street['turn'],
        'turn_pct': pct(cr_by_street['turn'], cr_opp_by_street['turn']),
        'river_cr': cr_by_street['river'], 'river_opp': cr_opp_by_street['river'],
        'river_pct': pct(cr_by_street['river'], cr_opp_by_street['river']),
        'total_cr': total_cr, 'total_opp': total_cr_opp,
        'total_pct': pct(total_cr, total_cr_opp),
        # FEAT-4: per-hand ID lists for renderer popup triggers
        'cr_hids': {st: ids for st, ids in cr_hids_by_street.items()},
        'opp_hids': {st: ids for st, ids in cr_opp_hids_by_street.items()},
    }

    # WWSF (Won When Saw Flop — standard: ALL wins after seeing flop)
    # Non-SD Win Rate: won WITHOUT showdown (pure aggression metric)
    # B38 fix (v7.45): exclude preflop-all-in hands from the saw_flop
    # denominator. PF-AI hands always run out the full board but Hero has
    # ZERO postflop agency — the showdown is forced. Including them
    # systematically suppresses Non-SD Win rate by adding hands that can
    # never contribute to the numerator. Caught when Ron flagged 3 of 6
    # Non-SD-Win candidate hands as preflop-AIs that should be excluded.
    vpip_hands = [h for h in hands if h['vpip']]
    saw_flop = [h for h in vpip_hands
                if len(h.get('board', [])) >= 3
                and not h.get('pf_allin')]
    wwsf_ct = sum(1 for h in saw_flop if h.get('won'))
    non_sd_ct = sum(1 for h in saw_flop if h.get('won') and not h.get('went_to_sd'))
    # SD aggressor: went to showdown with playable SPR AND bet/raised postflop
    sd_hands = [h for h in hands if h.get('went_to_sd')]
    sd_playable = [h for h in sd_hands if not (h.get('pf_allin') or (h.get('spr') is not None and h['spr'] <= 0))]
    sd_aggressor = sum(1 for h in sd_playable if any(b[0] in ('flop','turn') for b in h.get('hero_bets', [])))

    # Non-blind VPIP-PFR gap (SB limps + BB defends are structural)
    non_blind = [h for h in hands if h.get('position') not in ('SB', 'BB')]
    nb_vpip = sum(1 for h in non_blind if h.get('vpip'))
    nb_pfr = sum(1 for h in non_blind if h.get('pfr'))
    nb_n = len(non_blind)

    # v7.39 — B6 fix: per-table-size VPIP/PFR breakdown.
    # The 18-25% VPIP target band is implicitly 6-max-calibrated. Applying it
    # to a session that mixes 7-max / 8-max / 9-max produces a verdict that's
    # too tight at 8-max+ (VPIP should be 14-19% at 8-max, 12-17% at 9-max)
    # and too loose at 5-max (22-28%). This block emits per-cohort stats so
    # the renderer can verdict each cohort against its own target band, and
    # also emits an aggregate "weighted target" computed by summing
    # cohort-target-midpoints weighted by per-cohort hand counts.
    # The cohort definition uses n_players seen at the moment of action
    # (post-bust), not table_size at hand start. This is the right unit for
    # preflop strategic comparisons (a 7-handed hand at table_size=8 is
    # strategically a 7-max hand).
    table_cohorts = {2: [], 3: [], 4: [], 5: [], 6: [], 7: [], 8: [], 9: []}
    for h in hands:
        np = h.get('n_players')
        if np in table_cohorts:
            table_cohorts[np].append(h)
    # Target midpoints by table size — calibrated against MTT population
    # baselines. Aligned with gem_report_draft._emit_top_line_kpis ts_targets
    # so the analyzer-side weighted aggregate matches what the renderer
    # would compute per-cohort. If you change one, change both.
    VPIP_TARGETS_BY_SIZE = {
        2: (50, 75),  # HU — anything goes, not really comparable
        3: (35, 50),
        4: (28, 38),
        5: (28, 35),  # matches renderer
        6: (22, 28),  # matches renderer
        7: (20, 26),  # matches renderer
        8: (18, 23),  # matches renderer
        9: (16, 21),  # matches renderer
    }
    PFR_TARGETS_BY_SIZE = {
        2: (40, 65),
        3: (28, 42),
        4: (24, 32),
        5: (22, 28),  # matches renderer
        6: (18, 23),  # matches renderer
        7: (16, 22),  # matches renderer
        8: (14, 19),  # matches renderer
        9: (13, 18),  # matches renderer
    }
    vpip_pfr_by_table_size = {}
    weighted_vpip_lo_n = 0.0
    weighted_vpip_hi_n = 0.0
    weighted_pfr_lo_n = 0.0
    weighted_pfr_hi_n = 0.0
    total_weighted_n = 0
    for tsize, ths in table_cohorts.items():
        if not ths: continue
        n = len(ths)
        vpip_n = sum(1 for h in ths if h.get('vpip'))
        pfr_n = sum(1 for h in ths if h.get('pfr'))
        v_tgt = VPIP_TARGETS_BY_SIZE.get(tsize)
        p_tgt = PFR_TARGETS_BY_SIZE.get(tsize)
        vpip_pfr_by_table_size[tsize] = {
            'n': n,
            'vpip_ct': vpip_n, 'vpip_pct': pct(vpip_n, n),
            'pfr_ct': pfr_n, 'pfr_pct': pct(pfr_n, n),
            'vpip_target': v_tgt,
            'pfr_target': p_tgt,
        }
        if v_tgt:
            weighted_vpip_lo_n += v_tgt[0] * n
            weighted_vpip_hi_n += v_tgt[1] * n
        if p_tgt:
            weighted_pfr_lo_n += p_tgt[0] * n
            weighted_pfr_hi_n += p_tgt[1] * n
        total_weighted_n += n
    if total_weighted_n > 0:
        weighted_vpip_target = (round(weighted_vpip_lo_n / total_weighted_n, 1),
                                round(weighted_vpip_hi_n / total_weighted_n, 1))
        weighted_pfr_target = (round(weighted_pfr_lo_n / total_weighted_n, 1),
                               round(weighted_pfr_hi_n / total_weighted_n, 1))
    else:
        weighted_vpip_target = None
        weighted_pfr_target = None
    s['vpip_pfr_by_table_size'] = vpip_pfr_by_table_size
    s['vpip_target_weighted'] = weighted_vpip_target
    s['pfr_target_weighted'] = weighted_pfr_target
    # Suspend aggregate verdict when cohorts are mixed (>=2 different
    # table sizes each with >=20 hands) — renderer should show per-cohort
    # rows instead of one aggregate verdict.
    chunky_cohorts = [t for t, info in vpip_pfr_by_table_size.items() if info['n'] >= 20]
    s['vpip_aggregate_verdict_suspended'] = len(chunky_cohorts) >= 2
    s['vpip_aggregate_suspend_reason'] = (
        f"Mixed table-size session ({', '.join(f'{t}p={info['n']}' for t, info in vpip_pfr_by_table_size.items() if info['n'] >= 20)}); "
        f"per-cohort verdicts in s['vpip_pfr_by_table_size']"
        if len(chunky_cohorts) >= 2 else None
    )

    s['core'] = {'vpip': pct(vpip_ct, N), 'pfr': pct(pfr_ct, N), 'ats': pct(ats_ct, ats_opps),
                 'ats_opps': ats_opps, 'ats_ct': ats_ct,
                 'ats_raw': pct(ats_ct_raw, ats_opps_raw),
                 'ats_opps_raw': ats_opps_raw, 'ats_ct_raw': ats_ct_raw,
                 'af': af, 'bb_def': pct(bb_def_ct, bb_def_opps), 'sb_steal': pct(sb_steal, sb_fi),
                 'ftb': pct(ftb_ct, ftb_opps), 'ftb_ct': ftb_ct, 'ftb_opps': ftb_opps,
                 'ftb_raw': pct(ftb_ct_raw, ftb_opps_raw), 'ftb_ct_raw': ftb_ct_raw, 'ftb_opps_raw': ftb_opps_raw,
                 'check_raises': cr_ct, 'one_and_done': oad_ct,
                 'lt12bb_errors': sum(1 for h in hands if h.get('stack_bb',99)<12 and h['pf_action']=='call' and not h.get('villain_jammed')),
                 'vpip_pfr_gap': round(pct(vpip_ct, N) - pct(pfr_ct, N), 1),
                 'vpip_pfr_gap_nonblind': round(pct(nb_vpip, nb_n) - pct(nb_pfr, nb_n), 1) if nb_n > 0 else 0.0,
                 'wwsf': pct(wwsf_ct, len(saw_flop)), 'wwsf_ct': wwsf_ct, 'wwsf_total': len(saw_flop),
                 'non_sd_win': pct(non_sd_ct, len(saw_flop)), 'non_sd_ct': non_sd_ct,
                 'sd_aggressor_pct': pct(sd_aggressor, len(sd_playable)), 'sd_aggressor': sd_aggressor,
                 'sd_total': len(sd_playable), 'sd_total_raw': len(sd_hands), 'sd_allin': len(sd_hands) - len(sd_playable)}
    s['cr_frequency'] = cr_freq

    # --- POSITIONAL MATRIX ---
    pos_data = {}
    for p in ['UTG','UTG+1','MP','HJ','CO','BTN','SB','BB']:
        ph = [h for h in hands if h['position'] == p]
        if not ph: continue
        fi = sum(1 for h in ph if h.get('first_in') and p != 'BB')
        # SB pot entry = raise OR limp (J29: limp 80% in BvB). Other positions = raise only.
        if p == 'SB':
            raises = sum(1 for h in ph if h.get('first_in') and h['pfr'])
            limps = sum(1 for h in ph if h.get('first_in') and h['vpip'] and not h['pfr'])
            opens = raises + limps  # pot entry = raise or limp
            missed = sum(1 for h in ph if h.get('first_in') and not h['vpip'])  # true folds only
        else:
            opens = sum(1 for h in ph if h.get('first_in') and h['pfr'] and p != 'BB')
            raises = opens
            limps = 0
            missed = sum(1 for h in ph if h.get('first_in') and not h['pfr'] and p != 'BB')
        f2_3b = sum(1 for h in ph if h.get('fold_to_3bet'))
        pos_data[p] = {'hands': len(ph), 'vpip': pct(sum(1 for h in ph if h['vpip']), len(ph)),
                       'pfr': pct(sum(1 for h in ph if h['pfr']), len(ph)),
                       'open_pct': pct(opens, fi), 'fi': fi, 'opens': opens, 'raises': raises,
                       'limps': limps, 'missed': missed, 'f2_3b': f2_3b}
    s['positions'] = pos_data

    # --- 3-BET BY OPENER ---
    tb = defaultdict(lambda: {'opps': 0, '3bets': 0})
    for h in hands:
        if not h.get('hero_faced_raise'): continue
        op = h.get('opener_position')
        if not op or op == 'UNK': continue
        g = 'EP' if op in EP_POS else 'MP' if op in MP_POS else 'LP' if op in LP_POS else 'Blinds' if op in BLIND_POS else 'Other'
        tb[g]['opps'] += 1
        if h.get('hero_3bet'): tb[g]['3bets'] += 1
    s['threebet_by_opener'] = {g: {'opps': d['opps'], '3bets': d['3bets'], 'rate': pct(d['3bets'], d['opps'])} for g, d in tb.items()}

    # --- 3-BET BY HERO POSITION (v7.12) ---
    tb_hero = defaultdict(lambda: {'opps': 0, '3bets': 0})
    for h in hands:
        if not h.get('hero_faced_raise'): continue
        pos = h.get('position', '')
        if not pos: continue
        tb_hero[pos]['opps'] += 1
        if h.get('hero_3bet'): tb_hero[pos]['3bets'] += 1
    s['threebet_by_hero_pos'] = {p: {'opps': d['opps'], '3bets': d['3bets'], 'rate': pct(d['3bets'], d['opps'])} for p, d in tb_hero.items()}

    # --- C-BET SPLIT ---
    cbet = {'hu_opp': 0, 'hu_bet': 0, 'mw_opp': 0, 'mw_bet': 0, 'turn_opp': 0, 'turn_bet': 0, 'river_opp': 0, 'river_bet': 0,
            'hu_ip_opp': 0, 'hu_ip_bet': 0, 'hu_oop_opp': 0, 'hu_oop_bet': 0}
    for h in hands:
        if not h['pfr']: continue
        if h.get('villain_bet_flop_first'): continue  # villain bet first = not a c-bet opportunity
        # v8.19.0 Chapter D (PHF-004): same centralized legal-opportunity gate as the texture
        # counter (board>=3, no terminal/flop all-in, chips behind) so the denominators agree.
        if not is_legal_cbet_opportunity(h): continue
        pf = h.get('players_at_flop', 0)
        if pf < 2: continue
        flop_cb = any(b[2] == 'cbet' and b[0] == 'flop' for b in h.get('hero_bets', []))
        if pf == 2:
            cbet['hu_opp'] += 1; cbet['hu_bet'] += int(flop_cb)
            if h.get('hero_ip'):
                cbet['hu_ip_opp'] += 1; cbet['hu_ip_bet'] += int(flop_cb)
            else:
                cbet['hu_oop_opp'] += 1; cbet['hu_oop_bet'] += int(flop_cb)
        else: cbet['mw_opp'] += 1; cbet['mw_bet'] += int(flop_cb)
        if flop_cb and len(h.get('board',[])) >= 4:
            cbet['turn_opp'] += 1
            if any(b[2] == 'barrel' and b[0] == 'turn' for b in h.get('hero_bets', [])): cbet['turn_bet'] += 1
            if any(b[2] == 'barrel' and b[0] == 'turn' for b in h.get('hero_bets', [])) and len(h.get('board',[])) >= 5:
                cbet['river_opp'] += 1
                if any(b[2] == 'barrel' and b[0] == 'river' for b in h.get('hero_bets', [])): cbet['river_bet'] += 1
    s['cbet'] = {k: v for k, v in cbet.items()}
    s['cbet']['hu_pct'] = pct(cbet['hu_bet'], cbet['hu_opp'])
    s['cbet']['mw_pct'] = pct(cbet['mw_bet'], cbet['mw_opp'])
    s['cbet']['turn_pct'] = pct(cbet['turn_bet'], cbet['turn_opp'])
    s['cbet']['river_pct'] = pct(cbet['river_bet'], cbet['river_opp'])
    s['cbet']['hu_ip_pct'] = pct(cbet['hu_ip_bet'], cbet['hu_ip_opp'])
    s['cbet']['hu_oop_pct'] = pct(cbet['hu_oop_bet'], cbet['hu_oop_opp'])

    # --- WTSD / WSD ---
    saw_flop_vol = sum(1 for h in hands if h['vpip'] and len(h.get('board',[])) >= 3 and not h.get('pf_allin'))
    went_sd = sum(1 for h in hands if h['vpip'] and h.get('went_to_sd') and not h.get('pf_allin'))
    won_sd = sum(1 for h in hands if h['vpip'] and h.get('went_to_sd') and not h.get('pf_allin') and h.get('won'))
    s['showdown'] = {'saw_flop_vol': saw_flop_vol, 'went_sd': went_sd, 'won_sd': won_sd,
                     'wtsd': pct(went_sd, saw_flop_vol), 'wsd': pct(won_sd, went_sd)}

    # --- RIVER AUDIT ---
    ra = defaultdict(int)
    for h in hands:
        if h.get('river_action'): ra[h['river_action']] += 1
    s['river_audit'] = dict(ra)

    # --- SIZING ---
    sizing = defaultdict(list)
    for h in hands:
        for street, sz, spot, ip in h.get('hero_bets', []):
            sizing[f"{street}_{spot}_{ip}"].append(sz)
    s['sizing'] = {k: {'avg': round(sum(v)/len(v), 1), 'n': len(v), 'min': round(min(v)), 'max': round(max(v))} for k, v in sizing.items()}

    # --- FACING BETS ---
    facing = defaultdict(lambda: defaultdict(int))
    for h in hands:
        for street, sz, resp in h.get('facing_bets', []):
            bucket = 'small' if sz < 40 else 'medium' if sz < 70 else 'large'
            facing[f"{street}_{bucket}"][resp] += 1
    s['facing_bets'] = {k: dict(v) for k, v in facing.items()}

    # --- BOARD TEXTURE C-BET ---
    bt = defaultdict(lambda: {'hands': 0, 'cb_opp': 0, 'cb': 0,
                              'missed_cbet_hands': []})
    for h in hands:
        btx = h.get('board_texture', 'none')
        if btx == 'none': continue
        bt[btx]['hands'] += 1
        # v8.5.9: gate on street initiative, not raw pfr. In 3BP/4BP,
        # the c-bet belongs to the LAST preflop aggressor, not the opener.
        _pt = h.get('pot_type', 'SRP')
        _has_initiative = (
            (_pt == 'SRP' and h.get('pfr')) or
            (_pt == '3BP' and h.get('hero_3bet')) or
            (_pt == '4BP' and (h.get('hero_4bet') or h.get('pfr')))
        )
        # v8.19.0 Chapter D (PHF-004): the centralized legal-opportunity gate replaces the
        # old `board>=3 and not pf_allin` inline check — it also excludes flop-jammed /
        # effective-all-in spots where no clean c-bet decision existed (e.g. TM6090177176).
        if _has_initiative and is_legal_cbet_opportunity(h):
            bt[btx]['cb_opp'] += 1
            _cbet = any(b[2] == 'cbet' and b[0] == 'flop'
                        for b in h.get('hero_bets', []))
            if _cbet:
                bt[btx]['cb'] += 1
            else:
                # B2 (Aviel handoff 2026-05-25): collect the hands where Hero
                # had a c-bet opportunity as PFR but did NOT c-bet — VI.1
                # lists these per archetype (esp. low_dry) so Ron can see
                # which checks behind the aggregate rate.
                bt[btx]['missed_cbet_hands'].append({
                    'id': h.get('id'),
                    'cards': ''.join(h.get('cards', []) or []),
                    'board': ' '.join(h.get('board', []) or []),
                    'stack_bb': round(h.get('stack_bb', 0) or 0),
                    'tournament': (h.get('tournament', '') or '')[:45],
                    'date': h.get('date', ''),
                })
    s['board_texture'] = {k: {**v, 'cb_pct': pct(v['cb'], v['cb_opp'])}
                          for k, v in bt.items()}

    # --- v7.31: GTO TEXTURE ARCHETYPE COMPLIANCE (Dave taxonomy) ---
    # Per-archetype c-bet freq + sizing vs GTO targets from
    # gto_texture_archetypes.json. Findings tagged [GTO ref] in the report.
    if _HAS_TEXTURES:
        # Build extractor inputs from existing hand fields. Hero must be PFR
        # with a flop opportunity and not preflop all-in for the c-bet
        # decision to be meaningful.
        def _gto_eligible(h):
            # v8.19.0 Chapter D: same legal flop c-bet gate (board + terminal/flop all-in + chips)
            # so GTO-texture compliance shares the texture counters' denominator (no drift).
            return bool(h.get('pfr')) and is_legal_cbet_opportunity(h)

        def _gto_did_cbet(h):
            return any(b[0] == 'flop' and b[2] == 'cbet'
                       for b in h.get('hero_bets', []))

        def _gto_sizing_pct(h):
            for b in h.get('hero_bets', []):
                if b[0] == 'flop' and b[2] == 'cbet':
                    return b[1]
            return None

        def _gto_side(h):
            return 'ip' if h.get('hero_ip') else 'oop'

        eligible_hands = [h for h in hands if _gto_eligible(h)]
        # Pre-attach computed fields the aggregator expects
        for h in eligible_hands:
            h['_gto_archetype'] = h.get('board_archetype', 'unknown')
            h['_gto_side'] = _gto_side(h)
            h['_gto_eff_bb'] = h.get('eff_stack_bb') or h.get('stack_bb') or 100
            h['_gto_did_cbet'] = _gto_did_cbet(h)
            h['_gto_sizing_pct'] = _gto_sizing_pct(h)

        gto_findings = gem_textures.aggregate_compliance(
            eligible_hands,
            get_archetype_fn=lambda h: h.get('_gto_archetype'),
            get_side_fn=lambda h: h.get('_gto_side'),
            get_depth_fn=lambda h: h.get('_gto_eff_bb'),
            get_did_cbet_fn=lambda h: h.get('_gto_did_cbet'),
            get_sizing_fn=lambda h: h.get('_gto_sizing_pct'),
        )
        # Sets cannot be JSON-serialized; aggregate_compliance already converts
        # depth_bands_seen to a sorted list, but defensive in case of changes
        for arch, sides in gto_findings.items():
            for side, b in sides.items():
                if isinstance(b.get('depth_bands_seen'), set):
                    b['depth_bands_seen'] = sorted(b['depth_bands_seen'])
                # target_seen is a verbose dict; drop it from output to keep
                # findings concise (caller can re-derive from archetype meta)
                b.pop('target_seen', None)
                # v7.39 — B4 fix: downgrade verdict when sample is too thin
                # for an actionable read. The aggregator labels samples as
                # 'small' (n<3), 'thin' (3≤n<8), or 'sufficient' (n≥8). The
                # raw verdict logic flags 'deviation' on a single +/-66% c-bet
                # in a 2-sample bucket — that's noise. Renderer was masking
                # this; the analyzer field itself is now correct so any
                # downstream consumer (CSV, exports, other detectors that may
                # later read texture_gto_findings) sees the gated result.
                if b.get('sample_size_label') == 'small' and b.get('verdict') == 'deviation':
                    b['verdict_raw'] = 'deviation'  # preserve original
                    b['verdict'] = 'unjudged_thin'
                    b['verdict_downgrade_reason'] = 'B4: n<3 too small to call deviation'
        # BUG-N: collect hand IDs per archetype×side for popup drill-down
        for _eh in eligible_hands:
            _arch = _eh.get('_gto_archetype', '')
            _side = _eh.get('_gto_side', '')
            if _arch and _side and _arch in gto_findings:
                _side_data = gto_findings[_arch].get(_side, {})
                _did = _eh.get('_gto_did_cbet')
                _hid = _eh.get('id', '')
                if _hid:
                    if _did:
                        _side_data.setdefault('cbet_hand_ids', []).append(_hid)
                    else:
                        _side_data.setdefault('missed_hand_ids', []).append(_hid)
        # Cap ID lists to 20 per bucket
        for arch, sides in gto_findings.items():
            for side, b in sides.items():
                for _ik in ('cbet_hand_ids', 'missed_hand_ids'):
                    if _ik in b:
                        b[_ik] = b[_ik][:20]
        s['texture_gto_findings'] = gto_findings
        s['texture_gto_meta'] = {
            'source': 'gto_texture_archetypes.json',
            'archetype_count': len(gem_textures.all_archetypes()),
            'eligible_hands': len(eligible_hands),
        }
    else:
        s['texture_gto_findings'] = {}
        s['texture_gto_meta'] = {'source': None, 'enabled': False}

    # --- STACK DEPTH ---
    tiers = {'<12BB': [], '12-25BB': [], '25-40BB': [], '40BB+': []}
    for h in hands:
        sb = h.get('stack_bb', 0)
        tier = '<12BB' if sb < 12 else '12-25BB' if sb < 25 else '25-40BB' if sb < 40 else '40BB+'
        tiers[tier].append(h)
    s['stack_depth'] = {}
    for tier, ths in tiers.items():
        if not ths: continue
        fi = sum(1 for h in ths if h.get('first_in') and h['position'] != 'BB')
        opens = sum(1 for h in ths if h.get('first_in') and h['pfr'] and h['position'] != 'BB')
        # v7.22: also compute non-blind VPIP/PFR so the depth-by-depth gap
        # comparison matches the overall metric (both exclude BB defense).
        nb = [h for h in ths if h['position'] not in ('SB', 'BB')]
        nb_vpip_pct = pct(sum(1 for h in nb if h['vpip']), len(nb)) if nb else 0
        nb_pfr_pct = pct(sum(1 for h in nb if h['pfr']), len(nb)) if nb else 0
        s['stack_depth'][tier] = {'hands': len(ths),
                                  'vpip': pct(sum(1 for h in ths if h['vpip']), len(ths)),
                                  'pfr': pct(sum(1 for h in ths if h['pfr']), len(ths)),
                                  'rfi': pct(opens, fi),
                                  'nb_hands': len(nb),
                                  'nb_vpip': nb_vpip_pct,
                                  'nb_pfr': nb_pfr_pct,
                                  'nb_gap': round(nb_vpip_pct - nb_pfr_pct, 1)}

    # --- TOURNAMENT PHASE ---
    phases = {'Early': [], 'Mid': [], 'Late': []}
    for h in hands:
        lvl = h.get('level', 0)
        phase = 'Early' if lvl <= 10 else 'Mid' if lvl <= 18 else 'Late'
        phases[phase].append(h)
    s['phases'] = {}
    for phase, phs in phases.items():
        if not phs: continue
        s['phases'][phase] = {'hands': len(phs), 'vpip': pct(sum(1 for h in phs if h['vpip']), len(phs)),
                              'pfr': pct(sum(1 for h in phs if h['pfr']), len(phs))}

    # --- BLUFF/VALUE CLASSIFICATION (full evaluator) ---
    # v7.33 Bug #8: now passes sizing_pct to enable polar-overbet detection.
    # Was misclassifying weak made hands betting big as 'value' (e.g. 88 turn
    # polar jam on K-Q-J board was 'value' under old logic, now 'pure_bluff').
    total_bets = value = semi = pure = 0
    _bp_ids = {'value': [], 'semi': [], 'pure': []}
    for h in hands:
        cards = h.get('cards', []); board = h.get('board', [])
        for street, sz, spot, ip in h.get('hero_bets', []):
            if spot == 'raise': continue
            total_bets += 1
            board_slice = board[:3] if street == 'flop' else board[:4] if street == 'turn' else board
            if not cards or len(cards) < 2 or not board_slice: continue
            cat = classify_hand_for_betting(cards, board_slice, street, sizing_pct=sz)
            _hid = h.get('id', '')
            if cat == 'value': value += 1; _bp_ids['value'].append(_hid)
            elif cat == 'semi_bluff': semi += 1; _bp_ids['semi'].append(_hid)
            else: pure += 1; _bp_ids['pure'].append(_hid)
    s['bluff_profile'] = {'total': total_bets, 'value': value, 'semi': semi, 'pure': pure,
                          'value_pct': pct(value, total_bets), 'semi_pct': pct(semi, total_bets), 'pure_pct': pct(pure, total_bets),
                          'value_ids': _bp_ids['value'], 'semi_ids': _bp_ids['semi'], 'pure_ids': _bp_ids['pure']}

    # --- D2: BAD RIVER CALL-DOWN DETECTOR ---
    # Finds showdown hands where Hero called river with a weak hand against
    # a value-heavy villain line. Uses pot-odds + villain line profile, NOT MDF.
    bad_calldowns = []
    for h in hands:
        if not h.get('went_to_sd') or not h.get('vpip'):
            continue
        hsa = h.get('hero_street_actions', {}) or {}
        river_act = hsa.get('river', '')
        if river_act not in ('call', 'xc'):
            continue  # Hero must have CALLED the river
        if h.get('won'):
            continue  # Only flag losses
        strength = h.get('hand_strength', '')
        # Only flag weak made hands (pair or worse on the river)
        if strength in ('flush', 'straight', 'full_house', 'quads',
                        'straight_flush', 'trips', 'set', 'two_pair'):
            continue  # strong enough hand, not a bad call-down
        # Compute pot odds at the river call
        ledger = h.get('action_ledger', [])
        river_actions = [a for a in ledger if a.get('street') == 'river']
        if not river_actions:
            continue
        # Find the last villain bet/raise Hero called
        _v_bet = None
        for ra in reversed(river_actions):
            if ra.get('player') != h.get('hero', 'Hero') and ra.get('action') in ('bets', 'raises'):
                _v_bet = ra
                break
        if not _v_bet or _v_bet.get('amount_bb', 0) <= 0:
            continue
        bet_bb = _v_bet['amount_bb']
        # Estimate pot before the bet (sum of all prior actions)
        _pot_est = sum(a.get('amount_bb', 0) for a in ledger
                      if a.get('street') != 'river') + sum(
                      a.get('amount_bb', 0) for a in river_actions
                      if a != _v_bet and a.get('player') != h.get('hero', 'Hero'))
        if _pot_est <= 0:
            _pot_est = abs(h.get('net_bb', 0)) * 0.5  # rough fallback
        total_pot = _pot_est + bet_bb + bet_bb  # pot + villain bet + hero call
        required_eq = bet_bb / total_pot * 100 if total_pot > 0 else 50
        # Classify villain line
        _n_villain_bets = sum(1 for a in ledger
                             if a.get('player') != h.get('hero', 'Hero')
                             and a.get('action') in ('bets', 'raises'))
        if _n_villain_bets >= 3:
            _v_line = 'triple_barrel'
            _v_profile = 'value_heavy'
        elif _n_villain_bets >= 2:
            _v_line = 'double_barrel'
            _v_profile = 'moderate_value'
        else:
            _v_line = 'single_bet'
            _v_profile = 'mixed'
        # Check board texture for flush/straight completions
        board = h.get('board', [])
        _board_desc = h.get('board_texture', '')
        # Flag if required equity > 25% AND villain line is value-heavy
        # AND hero hand is weak (one pair or worse)
        if required_eq > 25 and _v_profile in ('value_heavy', 'moderate_value'):
            bad_calldowns.append({
                'id': h.get('id'),
                'type': 'bad_river_calldown',
                'required_equity': round(required_eq, 1),
                'hero_hand_class': strength or 'unknown',
                'board_texture': _board_desc,
                'villain_line': _v_line,
                'villain_line_profile': _v_profile,
                'net_bb': h.get('net_bb', 0),
                'reason': f'River call with {strength or "weak hand"} needed '
                          f'{required_eq:.0f}% equity vs {_v_line} — '
                          f'population range {_v_profile} at this sizing.',
            })
    s['bad_river_calldowns'] = bad_calldowns
    if bad_calldowns:
        print(f"  D2: {len(bad_calldowns)} bad river call-down(s) detected")

    # --- EAI (all-in showdowns) — SPLIT BY STREET (v7.2) ---
    # Cache-safe: uses structured fields, NOT raw_text (which is stripped
    # from the cache). The old raw_text scanning silently produced 0 EAI
    # entries on any cached re-run.
    eai_list = []
    for h in hands:
        if not h.get('went_to_sd'): continue
        # A2b-3: Hero all-in detection — action ledger is primary source
        hero_allin = h.get('pf_allin', False)
        if not hero_allin:
            # Check action ledger first (canonical)
            _ledger = h.get('action_ledger', [])
            hero_name = h.get('hero', 'Hero')
            if _ledger:
                hero_allin = any(a.get('is_all_in') and a.get('player') == hero_name
                                for a in _ledger)
            if not hero_allin:
                # Fallback to legacy fields
                _act_sum = (h.get('action_summary') or '').lower()
                hero_allin = 'all-in' in _act_sum or 'jam' in _act_sum
        if not hero_allin: continue
        # Villain shown cards: use showdown_reveals from appendix details,
        # or fall back to raw_text if available
        raw = h.get('raw_text', '')
        if raw:
            shows = re.findall(r'(\S+): shows \[([^\]]+)\]', raw)
        else:
            # Derive from structured data — the hand went to SD so villain
            # cards may be in the hand dict or appendix details
            shows = []
            hero = h.get('hero', 'Hero')
            # stacks_behind has villain positions; showdown cards from parser
            _sd_reveals = h.get('showdown_reveals', {})
            if _sd_reveals:
                for _p, _cards in _sd_reveals.items():
                    if _p != hero and _cards:
                        shows.append((_p, _cards if isinstance(_cards, str)
                                     else ' '.join(_cards)))
            # Also check villain_cards if present
            _vc_field = h.get('villain_cards', '')
            if not shows and _vc_field:
                shows.append(('Villain', _vc_field))
        hero = h.get('hero', 'Hero')
        if len(shows) < 1: continue  # need at least 1 villain shown
        # Filter out hero from shows
        shows = [(p, c) for p, c in shows if p != hero]
        if not shows: continue
        vc = shows[0][1]
        v_all = [c for p, c in shows]
        hc = h.get('cards', []); vCards = vc.split()
        hr = [c[0] for c in hc]; vr = [c[0] for c in vCards]

        # Determine which street the all-in happened — from structured data
        allin_street = 'preflop'
        # A2b-3: all-in street from action ledger (primary)
        if h.get('pf_allin'):
            allin_street = 'preflop'
        elif _ledger:
            # Find first all-in action in the ledger
            for _al_act in _ledger:
                if _al_act.get('is_all_in'):
                    allin_street = _al_act.get('street', 'preflop')
                    break
        elif raw:
            current_street = 'preflop'
            for line in raw.split('\n'):
                if '*** FLOP ***' in line: current_street = 'flop'
                elif '*** TURN ***' in line: current_street = 'turn'
                elif '*** RIVER ***' in line: current_street = 'river'
                if 'all-in' in line.lower() and ': ' in line:
                    allin_street = current_street
                    break
        else:
            hsa = h.get('hero_street_actions', {}) or {}
            for _st in ('river', 'turn', 'flop'):
                _act = str(hsa.get(_st, '')).lower()
                if 'ai' in _act or 'jam' in _act:
                    allin_street = _st
                    break
        
        board = h.get('board', [])
        
        if allin_street == 'preflop':
            # PREFLOP: classify by hand types (ahead/flip/behind)
            # v7.30 P0-4: use >= not >, so dominated cases (AA vs AKo, AQo vs AA, KK vs AKo)
            # categorize correctly. Strict > falls to 'flip' when villain's overcard rank
            # equals Hero's pair rank, mis-bucketing dominated hands as flips.
            hp = hr[0]==hr[1] if len(hr)>=2 else False
            vp = vr[0]==vr[1] if len(vr)>=2 else False
            cat = 'flip'
            if hp and vp: cat = 'ahead' if RANK_NUM.get(hr[0],0) > RANK_NUM.get(vr[0],0) else 'behind'
            elif hp and not vp: cat = 'ahead' if RANK_NUM.get(hr[0],0) >= max(RANK_NUM.get(vr[0],0),RANK_NUM.get(vr[1],0)) else 'flip'
            elif not hp and vp: cat = 'behind' if RANK_NUM.get(vr[0],0) >= max(RANK_NUM.get(hr[0],0),RANK_NUM.get(hr[1],0)) else 'flip'
            else:
                hs = sorted([RANK_NUM.get(hr[0],0),RANK_NUM.get(hr[1],0)], reverse=True)
                vs = sorted([RANK_NUM.get(vr[0],0),RANK_NUM.get(vr[1],0)], reverse=True)
                if hs[0]>vs[0] and hs[1]>vs[1]: cat='ahead'
                elif vs[0]>hs[0] and vs[1]>hs[1]: cat='behind'
                elif hs[0]==vs[0]: cat='ahead' if hs[1]>vs[1] else 'behind' if hs[1]<vs[1] else 'flip'
        else:
            # POSTFLOP: classify by who had the better hand at time of all-in
            # Use board at the all-in street
            board_at_allin = board[:3] if allin_street == 'flop' else board[:4] if allin_street == 'turn' else board
            if len(board_at_allin) >= 3:
                hero_rank = evaluate_best_hand(hc, board_at_allin)
                villain_rank = evaluate_best_hand(vCards, board_at_allin)
                if hero_rank[0] > villain_rank[0]: cat = 'ahead'
                elif hero_rank[0] < villain_rank[0]: cat = 'behind'
                elif hero_rank[2] > villain_rank[2]: cat = 'ahead'
                elif hero_rank[2] < villain_rank[2]: cat = 'behind'
                else: cat = 'flip'  # truly tied (rare)
            else:
                cat = 'flip'  # fallback
        
        eai_entry = {'id': h['id'], 'hero': ' '.join(hc), 'villain': vc,
                     'villains_all': v_all,
                     'board': ' '.join(board), 'won': h.get('won', False),
                     'category': cat, 'street': allin_street,
                     'tournament': h.get('tournament',''),
                     'date': h.get('date',''),
                     # v7.33 Bug #4 fix: surface format + multi-way info so the
                     # cooler detector can identify bounty_cover_loss patterns.
                     'format': h.get('format',''),
                     'players_at_flop': h.get('players_at_flop', 0)}

        # B238 (v7.99.22, Ron review 2026-05-26): override the made-hand /
        # hand-type heuristic above with TRUE multiway all-in equity. The
        # heuristic mis-bucketed (a) draw-vs-pair postflop all-ins by
        # made-hand rank, and (b) multiway all-ins by a single villain.
        # Equity is computed vs the WHOLE shown field at the all-in street.
        if _HAS_EAI_EQUITY:
            try:
                board_eq = (board[:3] if allin_street == 'flop'
                            else board[:4] if allin_street == 'turn'
                            else board[:5] if allin_street == 'river'
                            else [])
                eqres = gem_eai_equity.equity(
                    hc, [v.split() for v in v_all], board_eq, tag=h['id'])
                if eqres:
                    eai_entry['category'] = eqres['category']
                    eai_entry['hero_equity'] = eqres['hero_equity']
                    eai_entry['opp_equity'] = eqres['opp_equity']
                    eai_entry['is_favorite'] = eqres['is_favorite']
                    eai_entry['n_allin'] = eqres['n_players']
                    eai_entry['equity_method'] = eqres['method']
                    eai_entry['suckout'] = gem_eai_equity.suckout_direction(
                        eqres, h.get('won', False))
            except Exception:
                pass  # keep heuristic category on any failure

        eai_list.append(eai_entry)

    # Split by preflop vs postflop
    pf_eai = [e for e in eai_list if e['street'] == 'preflop']
    post_eai = [e for e in eai_list if e['street'] != 'preflop']
    
    def _eai_summary(lst):
        # v7.30 P0-5b: chops count as 0.5 wins (not full wins). Treating won='chop'
        # as truthy inflates win-rates and corrupts variance estimates.
        def _w(e):
            return 0.5 if e.get('won') == 'chop' else (1 if e.get('won') else 0)
        wa = [e for e in lst if e['category']=='ahead']
        fl = [e for e in lst if e['category']=='flip']
        wb = [e for e in lst if e['category']=='behind']
        def _bucket(b):
            wins = sum(_w(e) for e in b)
            return {'count': len(b), 'won': wins, 'pct': pct(wins, len(b))}
        return {'count': len(lst),
                'ahead': _bucket(wa),
                'flip': _bucket(fl),
                'behind': _bucket(wb)}
    
    s['eai'] = {
        'total': len(eai_list),
        'preflop': _eai_summary(pf_eai),
        'postflop': _eai_summary(post_eai),
        'by_street': {street: _eai_summary([e for e in eai_list if e['street']==street])
                      for street in ['preflop','flop','turn','river'] if any(e['street']==street for e in eai_list)},
        # Keep legacy format for backward compat (uses same chop-aware counting)
        'way_ahead': {'count': sum(1 for e in eai_list if e['category']=='ahead'),
                      'won': sum((0.5 if e.get('won')=='chop' else 1) for e in eai_list if e['category']=='ahead' and e.get('won')),
                      'pct': pct(sum((0.5 if e.get('won')=='chop' else 1) for e in eai_list if e['category']=='ahead' and e.get('won')),
                                 sum(1 for e in eai_list if e['category']=='ahead'))},
        'flipping': {'count': sum(1 for e in eai_list if e['category']=='flip'),
                     'won': sum((0.5 if e.get('won')=='chop' else 1) for e in eai_list if e['category']=='flip' and e.get('won')),
                     'pct': pct(sum((0.5 if e.get('won')=='chop' else 1) for e in eai_list if e['category']=='flip' and e.get('won')),
                                sum(1 for e in eai_list if e['category']=='flip'))},
        'way_behind': {'count': sum(1 for e in eai_list if e['category']=='behind'),
                       'won': sum((0.5 if e.get('won')=='chop' else 1) for e in eai_list if e['category']=='behind' and e.get('won')),
                       'pct': pct(sum((0.5 if e.get('won')=='chop' else 1) for e in eai_list if e['category']=='behind' and e.get('won')),
                                  sum(1 for e in eai_list if e['category']=='behind'))},
        'hands': eai_list
    }
    # v8.12.8 (handover Issue 2): stamp how the buckets were derived so the
    # degradation is observable instead of silent. An entry without
    # 'equity_method' kept the rank-heuristic category (engine missing OR
    # the per-hand equity call failed).
    _eai_heuristic_n = sum(1 for e in eai_list if 'equity_method' not in e)
    s['eai']['equity_engine'] = ('phevaluator' if _HAS_EAI_EQUITY
                                 else 'unavailable')
    s['eai']['heuristic_fallback_n'] = _eai_heuristic_n
    if eai_list and _eai_heuristic_n:
        import sys as _sys_eai2
        print('WARN: %d/%d all-in hands fell back to the rank heuristic '
              'for EAI buckets — the all-in-luck layer and True EV are '
              'approximate for this run.'
              % (_eai_heuristic_n, len(eai_list)), file=_sys_eai2.stderr)

    # --- COOLERS (strict definition, v7.13) ---
    # A cooler is NOT a flip or a domination. It's a spot where both players have
    # strong made hands and one MUST lose significant chips.
    #
    # PREFLOP coolers:
    #   - Pair vs pair at all-in (loser bound to commit: 22-QQ vs KK/AA etc.)
    #   - AK vs AA or AK vs KK (premium vs dominating premium)
    #
    # POSTFLOP coolers (at the all-in street):
    #   - Set over set / trips with better kicker
    #   - Flush over flush
    #   - Straight over straight
    #   - Full house over full house (or same-rank boats)
    #   - Straight flush / quads beating any strong hand
    #   - Over-set vs over-pair (Hero overpair, Villain flopped set)
    #
    # NOT coolers: AQ vs AK (domination), AK vs 77 on 7-high (bad beat), TPTK vs set
    # (bad postflop play), top pair vs overpair (mistake), nut flush vs straight (close).
    # B23/B24/B25 fixes (v7.38):
    #   B23: PF pair-over-pair only fires when hero has the LOWER pair (else
    #        hero was favorite — losing is variance, not a cooler).
    #   B24: Postflop coolers require SAME hand class (set-vs-set, flush-vs-
    #        flush, straight-vs-straight, boat-vs-boat). Set-over-two-pair is
    #        the one explicit cross-class case kept (per existing comment).
    #        Flush-over-straight, straight-over-set etc. are NOT coolers per
    #        the strict definition.
    #   B25: Pair-over-pair check is now street-agnostic — if both have pocket
    #        pairs and hero has the lower one, the matchup is a PF cooler
    #        regardless of where the all-in eventually landed (4-bet pot AI
    #        on river is still a PF pair-over-pair cooler).
    from gem_parser import evaluate_best_hand as _eval
    HAND_CLASS = {
        0: 'high_card', 1: 'pair', 2: 'two_pair', 3: 'trips',
        4: 'straight', 5: 'flush', 6: 'full_house', 7: 'quads', 8: 'straight_flush'
    }
    
    def _pair_rank(pair_str):
        """Return the rank-num (2-14) of a pair like 'TT', 'JJ', '99'. None if not a pair."""
        if len(pair_str) == 2 and pair_str[0] == pair_str[1]:
            return RANK_NUM.get(pair_str[0], 0)
        return None
    
    coolers = []
    for e in eai_list:
        if e['won']: continue
        hc_cards = e['hero'].split()
        vc_cards = e['villain'].split()
        if len(hc_cards) != 2 or len(vc_cards) != 2: continue
        hs = normalize_hand(hc_cards)
        vn = normalize_hand(vc_cards)
        h_is_pair = len(hs) == 2 and hs[0] == hs[1]
        v_is_pair = len(vn) == 2 and vn[0] == vn[1]

        is_cooler = False
        kind = ''

        # B23+B25: pair-over-pair check is STREET-AGNOSTIC. If both have pocket
        # pairs and hero has the LOWER pair, it's a PF cooler regardless of where
        # the all-in eventually landed. Same-pair (impossible) skipped; higher-
        # pair vs lower (hero ahead, lost) = variance not cooler.
        if h_is_pair and v_is_pair:
            hpr = _pair_rank(hs); vpr = _pair_rank(vn)
            # v8.6.2: in multiway pots, verify the villain hand is actually a
            # higher pair (not just any villain in the pot having cards that
            # normalize to a pair-looking string)
            _n_ai = e.get('n_allin', 2) or 2
            if hpr is not None and vpr is not None and hpr < vpr and _n_ai <= 2:
                is_cooler = True
            elif hpr is not None and vpr is not None and hpr < vpr and _n_ai > 2:
                # Multiway: only cooler if villain confirmed as pocket pair
                # (not AQ which has two different ranks)
                _v_r0 = vc_cards[0][0] if vc_cards else ''
                _v_r1 = vc_cards[1][0] if len(vc_cards) > 1 else ''
                if _v_r0 == _v_r1:
                    is_cooler = True
                # else: multiway with non-pair villain — not a structural cooler
                ai_street = e.get('street', 'preflop')
                if ai_street == 'preflop':
                    kind = f'PF pair-over-pair ({vn} > {hs})'
                else:
                    kind = f'PF pair-over-pair ({vn} > {hs}, AI on {ai_street})'

        if not is_cooler and e['street'] == 'preflop':
            # PF non-pair coolers: AK vs AA/KK
            if hs in ('AKs', 'AKo') and vn in ('AA', 'KK'):
                is_cooler = True; kind = 'PF AK vs AA/KK'
            # v7.33 Bug #4 fix: bounty-MTT cover-loss category. Multi-way ai pre
            # in BOUNTY format where Hero was ahead with a cover-worthy hand and
            # lost the runout. These are $EV-positive even when chipEV-negative
            # (mandatory get-in, bounty premium offsets cooler EV).
            elif (e.get('format','') in ('BOUNTY', 'MYSTERY_BOUNTY')
                  and e.get('players_at_flop', 0) >= 3
                  and e.get('category') == 'ahead'):
                is_cover_worthy = (
                    (h_is_pair and hs in ('TT','JJ','QQ','KK','AA')) or
                    hs in ('AKs','AKo','AQs','AQo','AJs','AJo','KQs','KQo')
                )
                if is_cover_worthy:
                    # v8.5.8: bounty cover get-ins are NOT coolers — they're
                    # mandatory/justified get-ins. Label as bounty-cover note
                    # but don't set is_cooler (routes to III.5 via prefill).
                    n_way = e.get('players_at_flop', 0)
                    e['bounty_cover_note'] = f'PF bounty-cover {hs} {n_way}-way ai (ahead lost runout)'
        elif not is_cooler:
            # Postflop coolers: STRICT same-class collisions only.
            # B24: previously v_cls >= h_cls accepted cross-class collisions
            # (flush-over-straight, etc.) which violates the strict cooler def.
            board = e.get('board', '').split()
            allin_street = e['street']
            board_ai = board[:3] if allin_street == 'flop' else board[:4] if allin_street == 'turn' else board[:5]
            if len(board_ai) >= 3:
                hrank = _eval(hc_cards, board_ai)  # (class, ..., kickers)
                vrank = _eval(vc_cards, board_ai)
                h_cls, v_cls = hrank[0], vrank[0]
                # Strict same-class: set-vs-set, straight-vs-straight,
                # flush-vs-flush, boat-vs-boat, quads-vs-quads.
                if h_cls >= 3 and v_cls == h_cls:
                    is_cooler = True
                    kind = f'{HAND_CLASS.get(v_cls,"?")}-over-{HAND_CLASS.get(h_cls,"?")}'
                # Set-over-two-pair: only genuine "flopped set vs flopped two-pair"
                # on an UNPAIRED board. If villain's trips come from a board pair
                # (e.g. K7 on KK board = trips via board), that's NOT the set trap.
                # Also exclude river check-call spots (Hero had agency to fold).
                elif h_cls == 2 and v_cls == 3:
                    _board = h.get('board', [])
                    _ai_st = e.get('street', 'preflop')
                    # Check if board is paired at the all-in street
                    _board_ranks = [c[0] for c in _board] if _board else []
                    _board_paired = len(_board_ranks) != len(set(_board_ranks))
                    # Check if villain's trips rank matches a board pair (trips via board, not pocket set)
                    _v_trips_via_board = False
                    if _board_paired and vn:
                        _v_rank = vn[0] if len(vn) >= 2 else ''
                        _v_trips_via_board = _board_ranks.count(_v_rank) >= 2
                    # Check if Hero check-called river (had agency)
                    _hero_river_cc = (_ai_st == 'river' and
                                      'call' in (h.get('hero_street_actions', {}).get('river', '') or '').lower())
                    if not _board_paired and not _v_trips_via_board and not _hero_river_cc:
                        is_cooler = True
                        kind = 'set-over-two_pair'
                # Everything else (flush-over-straight, straight-over-set,
                # set-over-overpair, etc.) is NOT a cooler per strict def.

        if is_cooler:
            e2 = dict(e)
            e2['kind'] = kind
            e2['direction'] = 'negative'  # F5 (v7.49): Hero lost cooler-shaped matchup
            coolers.append(e2)

    # F5 (v7.49, Ron 2026-05-13): positive cooler detection — Hero underdog WON.
    # Mirror of the loop above: walk WON all-in events and flag the same
    # cooler-shape conditions when Hero was on the underdog side and hit.
    # This balances the variance-attribution math; over many sessions Hero
    # should hit the positive direction at roughly the same rate as getting
    # cooled negatively. Visible in I.7 as a separate sub-row.
    positive_coolers = []
    for e in eai_list:
        if not e.get('won'):
            continue
        hc_cards = e['hero'].split()
        vc_cards = e['villain'].split()
        if len(hc_cards) != 2 or len(vc_cards) != 2:
            continue
        hs = normalize_hand(hc_cards)
        vn = normalize_hand(vc_cards)
        h_is_pair_p = len(hs) == 2 and hs[0] == hs[1]
        v_is_pair_p = len(vn) == 2 and vn[0] == vn[1]

        is_pos_cooler = False
        pos_kind = ''

        # PF pair-over-pair — but Hero on the LOWER side AND WON (set hit, etc.)
        if h_is_pair_p and v_is_pair_p:
            hpr = _pair_rank(hs); vpr = _pair_rank(vn)
            if hpr is not None and vpr is not None and hpr < vpr:
                is_pos_cooler = True
                ai_street = e.get('street', 'preflop')
                pos_kind = f'PF pair-over-pair UNDERDOG-HIT ({hs} vs {vn}, AI on {ai_street})'

        # PF AK vs AA/KK — Hero AK ran out into AA/KK and won via runner-runner
        if not is_pos_cooler and e['street'] == 'preflop':
            if hs in ('AKs', 'AKo') and vn in ('AA', 'KK'):
                is_pos_cooler = True
                pos_kind = f'PF AK vs AA/KK UNDERDOG-HIT ({hs} beat {vn})'

        # Postflop positive cooler: Hero was the UNDERDOG at the all-in
        # street and improved to win. B214 (Ron review 2026-05-25): the old
        # branch flagged `hrank_p > vrank_p` — Hero AHEAD at the all-in — as a
        # "positive cooler". B238 (Ron review 2026-05-26): the made-hand-rank
        # underdog test was ALSO wrong — Hero 35s on A-4-6 (15-out flush+wrap)
        # vs top pair is a made-hand underdog but a ~57% EQUITY favourite, so
        # it surfaced as a bogus suckout. The branch now requires Hero to be a
        # real EQUITY underdog at the all-in (hero_equity <= 0.45) and to
        # improve to a genuine made hand by the river.
        if not is_pos_cooler and e['street'] != 'preflop':
            from gem_parser import evaluate_best_hand as _eval_p
            board_p = e.get('board', '').split()
            allin_street_p = e['street']
            hero_eq_ai = e.get('hero_equity')
            if hero_eq_ai is not None and hero_eq_ai <= 0.45 and len(board_p) >= 5:
                try:
                    hrank_fin = _eval_p(hc_cards, board_p[:5])
                    vrank_fin = _eval_p(vc_cards, board_p[:5])
                    # Hero an equity underdog at the all-in, AHEAD by the
                    # river — a genuine underdog-hit. Require a real made hand
                    # (class >= 2, two-pair+) on at least one side.
                    if (hrank_fin > vrank_fin
                            and max(hrank_fin[0], vrank_fin[0]) >= 2):
                        is_pos_cooler = True
                        cls_name = HAND_CLASS.get(hrank_fin[0], '?')
                        pos_kind = (f'{cls_name} UNDERDOG-HIT '
                                    f'(Hero ~{hero_eq_ai*100:.0f}% at '
                                    f'{allin_street_p} all-in, improved to win)')
                except Exception:
                    pass

        if is_pos_cooler:
            e_pos = dict(e)
            e_pos['kind'] = pos_kind
            e_pos['direction'] = 'positive'
            positive_coolers.append(e_pos)

    # B238 (v7.99.22, Ron review 2026-05-26): suckout ledger — all-ins where
    # the equity favourite lost ('against_hero') or an equity underdog won
    # ('by_hero'). Distinct from coolers (structural pair-over-pair etc.):
    # a suckout is purely an equity-favourite-vs-result mismatch, e.g. JJ
    # losing to AJ that rivers a straight. Drives the XIV suckout tables.
    suckouts_against = []
    suckouts_by = []
    for e in eai_list:
        sk = e.get('suckout')
        if sk == 'against_hero':
            suckouts_against.append(dict(e))
        elif sk == 'by_hero':
            suckouts_by.append(dict(e))
    s['suckouts'] = {
        'against_hero': suckouts_against,
        'by_hero': suckouts_by,
        'against_count': len(suckouts_against),
        'by_count': len(suckouts_by),
    }

    cooler_rate = round(len(coolers)/N*100, 2) if N else 0
    # Expected cooler rate under strict definition: 0.15-0.30/100
    # (loose definition used 0.3-0.5; tightened accounts for removing flip/domination false positives)
    # F5 (v7.49): also track positive_coolers and net cooler count for variance accounting.
    pos_cooler_rate = round(len(positive_coolers)/N*100, 2) if N else 0
    s['coolers'] = {
        'count': len(coolers),
        'rate': cooler_rate,
        'expected_low': 0.15,
        'expected_high': 0.30,
        'vs_expected': (
            'above' if cooler_rate > 0.30 else
            'below' if cooler_rate < 0.15 else 'within'
        ),
        'hands': coolers,
        # F5 (v7.49): positive cooler counterparts
        'positive_count': len(positive_coolers),
        'positive_rate': pos_cooler_rate,
        'positive_hands': positive_coolers,
        'net_count': len(coolers) - len(positive_coolers),
        'net_rate': round(cooler_rate - pos_cooler_rate, 2),
    }

    # --- MISTAKES (missed steals with confidence tiers, pre-classified) ---
    # v7.30 P1-3: build cooler-hand-ID set so mistake detectors below can filter.
    # A cooler is a +EV decision that lost to a stronger holding (set-over-set,
    # AA-vs-KK PF, etc.) — it's not a mistake, it's variance. Detectors that
    # fire on PF all-ins or postflop committed lines should respect this.
    cooler_hand_ids = set(c['id'] for c in coolers)
    # B48 fix (v7.45, Ron 2026-05-11): at sub-22BB stacks, marginal offsuit
    # hands like T9o/98o/K9o transition from raise-fold (CLEAR open) to
    # open-jam-or-fold (Nash) territory. Per Jaka/Garagnani short-stack
    # guidance, at 22BB- the opening framework breaks down for these hands —
    # they're below the JAM threshold AND below the open threshold simul-
    # taneously, making a fold genuinely defensible. Demote these from CORE
    # (CLEAR) to EXTENDED (MARGINAL) at <22BB. Caught on TM5934854873
    # (Tc9s CO 21.1BB hyper freezeout 5-handed). Partial B17 mitigation.
    _SHORT_STACK_DEMOTE = {'T9o', '98o', 'K9o', 'Q9o', 'J9o', 'K8o', 'Q8o', 'J8o'}
    # B17 fix (v7.46): at 8-max+, demote marginal offsuit broadway hands
    # (T8o/J7o/J8o at CO, J9o/T8o at BTN) from CORE → EXTENDED since
    # 8-max+ has more players to act behind = tighter opens correct.
    # Parallels B48's short-stack demotion logic.
    _8MAX_PLUS_DEMOTE_CO = {'T9o', 'J9o', 'T8s'}  # demote these CO-CORE entries at 8+
    _8MAX_PLUS_DEMOTE_BTN = {'T9o', '98o', '76o'}  # demote these BTN-CORE at 8+
    _8MAX_PLUS_DEMOTE_SB = {'T9o', '98o'}
    mistakes = []
    for h in hands:
        pos = h['position']
        if pos not in ('BTN', 'CO', 'SB'): continue
        if not h.get('first_in'): continue
        if h['pfr']: continue  # opened — not a missed open
        if h['pf_action'] != 'fold': continue
        # A2 (Aviel handoff 2026-05-25): in SB-vs-BB (folded to SB), Dave's
        # J29 framework prescribes a LIMP-heavy strategy (~80% limp, ~10%
        # raise, ~10% fold) — there is no "open-raise or it's a missed steal"
        # baseline. A limp-complete already records pf_action='call' so it
        # never reaches here; but an SB *fold* in BvB was firing as a "Missed
        # Steal", which is wrong on two counts: (1) J29 prescribes a limp, not
        # a raise, so the missed action is a limp-entry, not a steal; (2) J29
        # folds ~10% of the SB range by design, so most SB folds are correct.
        # The Missed-Steal detector is a raise-or-fold-range model — it does
        # not apply to SB BvB. Skip SB here; an SB BvB limp-defend leak, if
        # GEM ever models one, belongs in a separate J29-aware detector.
        if pos == 'SB':
            continue
        hs = normalize_hand(h.get('cards', []))
        core = BTN_CORE if pos == 'BTN' else CO_CORE if pos == 'CO' else SB_CORE
        extended = BTN_EXTENDED if pos == 'BTN' else CO_EXTENDED if pos == 'CO' else SB_EXTENDED
        tier_demoted = False
        demotion_reason = ''
        if hs in core:
            confidence = 'CLEAR'
            range_tier = 'CORE'
            # B206 (Ron 2026-05-25): bottom 5% of the CORE tier — the weakest
            # opens — are MARGINAL, not CLEAR. A hand one notch inside CORE is
            # still bottom-of-range; folding it is a ~1.5BB tail decision, not
            # a punt-weight mistake. Checked first because it is a property of
            # the hand, independent of stack depth / table size.
            _fringe = (BTN_CORE_FRINGE if pos == 'BTN'
                       else CO_CORE_FRINGE if pos == 'CO' else SB_CORE_FRINGE)
            if hs in _fringe:
                confidence = 'MARGINAL'
                tier_demoted = True
                demotion_reason = f'bottom of the {pos} open range'
            # B48: short-stack demotion for marginal offsuit hands
            elif (h.get('stack_bb', 99) or 99) < 22 and hs in _SHORT_STACK_DEMOTE:
                confidence = 'MARGINAL'
                tier_demoted = True
                demotion_reason = 'short stack (<22BB)'
            # B17 (v7.46): table-size demotion at 8-max+ for loose offsuit
            elif (h.get('table_size', 6) or 6) >= 8:
                if pos == 'CO' and hs in _8MAX_PLUS_DEMOTE_CO:
                    confidence = 'MARGINAL'
                    tier_demoted = True
                    demotion_reason = '8-max+ table (more players to act behind)'
                elif pos == 'BTN' and hs in _8MAX_PLUS_DEMOTE_BTN:
                    confidence = 'MARGINAL'
                    tier_demoted = True
                    demotion_reason = '8-max+ table (more players to act behind)'
                elif pos == 'SB' and hs in _8MAX_PLUS_DEMOTE_SB:
                    confidence = 'MARGINAL'
                    tier_demoted = True
                    demotion_reason = '8-max+ table (more players to act behind)'
        elif hs in extended:
            confidence = 'MARGINAL'
            range_tier = 'EXTENDED'
        else:
            continue  # not in any range
        # ICM gate: in bubble/post-bubble/FT, folding marginal steals may
        # be correct due to ladder-up equity. Same pattern as push/fold ICM
        # demotion (line ~2845). Demote CLEAR → MARGINAL; MARGINAL stays.
        _ms_phase = h.get('tournament_phase', '')
        icm_steal_note = ''
        if _ms_phase in _ICM_PHASES:
            if confidence == 'CLEAR':
                confidence = 'MARGINAL'
                tier_demoted = True
                demotion_reason = f'{_ms_phase} — ICM may justify fold'
            icm_steal_note = f' ({_ms_phase} — ladder-up may justify)'
        # Issue 2 (v7.71, Ron 2026-05-23): surface the correct opening range
        # on every Missed-Steal flag. The detector deliberately uses the
        # curated hardcoded CORE/EXTENDED tier sets rather than the OCR'd
        # Poker_Ranges_Text.txt charts (B17) — those sets ARE the authority /
        # fallback when a matching OCR chart for this exact position+depth is
        # missing. Previously the flag told Ron a hand was a missed steal but
        # never told him the range it should have been opened from. Attach a
        # readable shorthand of both tiers + which tier the folded hand fell
        # in, so the report can say "JTo is a CORE open at CO — fold is a
        # clear missed steal".
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': pos, 'stack_bb': round(h.get('stack_bb',0)),
                         'format': h['format'], 'tournament': h.get('tournament','')[:45],
                         'type': f'Missed Steal ({confidence}){icm_steal_note}', 'confidence': confidence,
                         'is_satellite': h['format'] == 'SATELLITE',
                         'pf_sequence': ' → '.join(h.get('pf_sequence', [])),
                         'action_summary': h.get('action_summary', ''),
                         'stacks_behind': h.get('stacks_behind', {}),
                         'range_tier': range_tier,
                         'tier_demoted': tier_demoted,
                         'demotion_reason': demotion_reason,
                         'tournament_phase': _ms_phase,
                         'open_range_core': _chart_summary(core),
                         'open_range_extended': _chart_summary(extended),
                         'open_range_source': f'curated {pos} open-tier list '
                                              f'(chart fallback — see B17)'})
    # --- ULTRA-SHORT PUSH/FOLD HEURISTIC (<8BB) v7.10 ---
    # At <8BB, push ranges are MUCH wider than open ranges.
    # No charts available, so use heuristic thresholds.
    for h in hands:
        pos = h['position']
        stack = h.get('stack_bb', 99)
        if stack >= 8: continue  # only <8BB
        if not h.get('first_in'): continue
        if h['pfr']: continue  # already pushed
        if h['pf_action'] != 'fold': continue
        hs = normalize_hand(h.get('cards', []))
        if not hs or len(hs) < 2: continue
        
        is_pair = len(hs) == 2
        is_suited = len(hs) == 3 and hs[2] == 's'
        is_ace = hs[0] == 'A'
        is_king = hs[0] == 'K'
        is_queen = hs[0] == 'Q'
        is_broadway = all(c in 'AKQJT' for c in hs[:2])
        r1 = RANK_NUM.get(hs[0], 0)
        r2 = RANK_NUM.get(hs[1], 0)
        gap = r1 - r2 if not is_pair else 0
        is_connected = gap <= 2 and not is_pair
        
        should_push = False
        confidence = 'MARGINAL'
        
        if pos in ('SB', 'BB'):
            # SB/BB at <8BB: push very wide
            if stack < 5:
                # <5BB: push almost anything with any equity
                should_push = is_pair or is_ace or is_king or is_suited or is_connected or is_queen
                confidence = 'CLEAR' if (is_ace or is_king or is_pair) else 'MARGINAL'
            else:
                # 5-8BB: push Ace, King, suited, pairs, connected
                should_push = is_pair or is_ace or is_king or (is_suited and (is_queen or is_connected or r2 >= 5))
                confidence = 'CLEAR' if (is_ace or is_king or is_pair) else 'MARGINAL'
        elif pos == 'BTN':
            if stack < 5:
                # <5BB BTN: push ~70% of hands
                should_push = is_pair or is_ace or is_king or is_suited or is_broadway or r1 >= 11  # J+x
                confidence = 'CLEAR' if (is_ace or is_pair or is_king) else 'MARGINAL'
            else:
                should_push = is_pair or is_ace or is_king or (is_suited and r2 >= 6) or is_broadway
                confidence = 'CLEAR' if (is_ace or is_pair) else 'MARGINAL'
        elif pos == 'CO':
            if stack < 5:
                # v7.48 N8 (Amit 2026-05-12): include offsuit Kx (K2o-K9o) —
                # previously only suited K (K2s+) was in CO push range. Amit
                # confirmed K2+ offsuit at CO <8BB should open-shove.
                is_kx_offsuit = is_king and not is_suited and not is_pair
                should_push = is_pair or is_ace or is_kx_offsuit or (is_suited and is_king) or is_broadway
                # N8: bump KXo confidence to CLEAR (matches BTN treatment)
                confidence = 'CLEAR' if (is_ace or is_pair or is_king) else 'MARGINAL'
            else:
                # v7.48 N8: same extension at 5-8BB CO
                is_kx_offsuit = is_king and not is_suited and not is_pair
                should_push = is_pair or is_ace or is_kx_offsuit or (is_suited and (is_king or is_queen)) or (is_broadway and r2 >= 10)
                confidence = 'CLEAR' if (is_ace or (is_pair and r1 >= 6) or is_king) else 'MARGINAL'
        elif pos == 'HJ':
            should_push = (is_pair and r1 >= 4) or (is_ace and r2 >= 8) or (is_suited and is_king and r2 >= 10)
            confidence = 'CLEAR' if (is_ace and r2 >= 10) or (is_pair and r1 >= 7) else 'MARGINAL'
        
        if should_push:
            # v7.11: Soften in bubble_zone — ICM may justify tight play
            # v7.43 (Ron 2026-05-09): expand ICM demotion to all late phases
            # (bubble_zone + post_bubble + ft_zone). Ladder-up considerations
            # apply throughout the in-money phase, not just at the bubble.
            # Goal: don't auto-mark these as confirmed mistakes; surface them
            # with the ICM context so review can decide whether ladder-up
            # justified the fold.
            _icm_p3 = h.get('icm_pressure', 0) or 0
            icm_note = ''
            if _icm_p3 >= 0.5:
                if confidence == 'CLEAR':
                    confidence = 'MARGINAL'
                icm_note = f' ({phase} — ladder-up may justify)'
            # Item 14: include the push range so hand descriptions show what
            # range the missed push was judged against (per Analyst_Writing_
            # Checklist §3b — push/fold verdict must show the Nash range).
            # Uses module-level _PUSH_RANGES dict (shared with _is_core_push).
            _pr = _PUSH_RANGES.get((pos, stack < 5),
                                   _PUSH_RANGES.get((pos, False), ''))
            mistakes.append({'id': h['id'], 'cards': hs, 'pos': pos, 'stack_bb': round(stack),
                             'format': h['format'], 'tournament': h.get('tournament','')[:45],
                             'type': f'Missed Push <8BB ({confidence})', 'confidence': confidence,
                             'is_satellite': h['format'] == 'SATELLITE',
                             'action_summary': h.get('action_summary', ''),
                             'stacks_behind': h.get('stacks_behind', {}),
                             'tournament_phase': phase,
                             'icm_note': icm_note,
                             'push_range': _pr})
    # --- ULTRA-SHORT RESHOVE (<8BB vs raise) v7.10 ---
    for h in hands:
        pos = h['position']
        stack = h.get('stack_bb', 99)
        if stack >= 8: continue
        if h['pfr'] or not h.get('hero_faced_raise'): continue
        if h['pf_action'] != 'fold': continue
        # B-AVIEL (2026-06-01): skip when 2+ raises are already in (3bet pot).
        # Reshove into a 3bet is a very different spot — ranges are much
        # tighter, and flatting players may be behind Hero too. Only flag
        # reshove vs a single open.
        if h.get('pf_raise_count', 0) >= 2: continue
        # BUG: skip when opener went all-in — Hero can only call/fold, not reshove.
        # Check if any preflop raiser was all-in
        _opener_allin = any(a.get('is_all_in') and a.get('action') in ('raises', 'bets')
                           and a.get('player') != h.get('hero')
                           for a in (h.get('action_ledger') or [])
                           if a.get('street') == 'preflop')
        if _opener_allin: continue
        hs = normalize_hand(h.get('cards', []))
        if not hs or len(hs) < 2: continue
        
        is_pair = len(hs) == 2
        is_ace = hs[0] == 'A'
        is_king = hs[0] == 'K'
        is_suited = len(hs) == 3 and hs[2] == 's'
        r2 = RANK_NUM.get(hs[1], 0)
        
        # At <8BB facing a raise, reshove with decent hands
        should_reshove = False
        if stack < 5:
            should_reshove = is_pair or is_ace or (is_king and (is_suited or r2 >= 10))
        else:
            should_reshove = (is_pair and r2 >= 4) or (is_ace and r2 >= 5) or (is_ace and is_suited)
        
        if should_reshove:
            opener = h.get('opener_position', 'UNK')
            # v8.9.8 P1-C: REJAM chart gate — check if Hero's hand is
            # in the position-vs-opener REJAM range before assigning CLEAR.
            _rj_pos = pos
            _rj_opener = opener
            _POS_SAFE = {'BTN', 'BU', 'CO', 'SB', 'BB', 'HJ', 'LJ',
                         'UTG', 'UTG1', 'UTG+1', 'UTG2', 'UTG+2', 'MP', 'EP', 'EP1', 'EP2'}
            _POS_CANON = {'BU': 'BTN', 'EP': 'UTG', 'EP1': 'UTG',
                          'EP2': 'UTG1', 'UTG+1': 'UTG1', 'UTG+2': 'UTG2'}
            _rj_pos = _POS_CANON.get(_rj_pos, _rj_pos)
            _rj_opener = _POS_CANON.get(_rj_opener, _rj_opener)
            _rj_key = f'REJAM_{_rj_pos}vs{_rj_opener}'
            _rj_chart = (ranges or {}).get(_rj_key, set())
            _chart_says_reshove = None
            if _rj_chart:
                _chart_says_reshove = hs in _rj_chart
                if not _chart_says_reshove:
                    should_reshove = False
            elif _rj_opener not in _POS_SAFE or _rj_pos not in _POS_SAFE:
                should_reshove = False
        if should_reshove:
            confidence = 'CLEAR' if (is_ace or is_pair) else 'MARGINAL'
            if _rj_chart and not _chart_says_reshove:
                confidence = 'MARGINAL'
            elif not _rj_chart and _rj_opener in ('UTG', 'UTG1', 'UTG2', 'EP', 'EP1', 'EP2', 'MP'):
                confidence = 'MARGINAL'
            # v7.11: Soften in bubble_zone
            phase = h.get('tournament_phase', '')
            icm_note = ''
            if phase == 'bubble_zone':
                confidence = 'MARGINAL'
                icm_note = ' (bubble_zone — ICM may justify)'
            mistakes.append({'id': h['id'], 'cards': hs, 'pos': pos, 'stack_bb': round(stack),
                             'format': h['format'], 'tournament': h.get('tournament','')[:45],
                             'type': f'Missed Reshove <8BB ({confidence})', 'confidence': confidence,
                             'is_satellite': h['format'] == 'SATELLITE',
                             'action_summary': h.get('action_summary', ''),
                             'opener': opener,
                             'tournament_phase': phase,
                             'icm_note': icm_note})
    # Monotone IP c-bet misses (J14) — exclude PF all-ins (no postflop agency)
    for h in hands:
        if not h['pfr'] or h.get('board_texture') != 'monotone' or len(h.get('board',[])) < 3: continue
        if _is_preflop_terminal_allin(h): continue
        if any(b[2] == 'cbet' and b[0] == 'flop' for b in h.get('hero_bets', [])): continue
        # v7.31 Patch 6: J14 assumes HU + Hero had c-bet option.
        # Skip multiway and skip when villain donk-led / x-raised before Hero acted.
        if not detector_prereq_satisfied('j14_monotone_no_cbet', h): continue
        # B35 fix (v7.45): J14 uses table-position as proxy for postflop IP
        # but fails in 3BP where Hero opened from early position and was
        # 3-bet by a later position — Hero is OOP postflop despite the table
        # position. Require Hero to be the LAST preflop raiser (pf_raise_count
        # == 1) before applying the IP-only check. Caught on TM5937312814
        # (QJs CO 60BB, 3-bet by BTN, check-flop on monotone Kc-5c-Jc was
        # GTO-correct OOP play and should NOT fire as a J14 mistake).
        if h.get('pf_raise_count', 1) > 1:
            continue  # Hero is not the last raiser → OOP in 3BP+
        # BUG FIX: J14 must only fire when Hero is IP postflop.
        # Use hero_ip field (parser-computed) as primary check.
        # Position heuristic as fallback only when hero_ip is None.
        _is_ip = h.get('hero_ip')
        if _is_ip is False:
            continue  # Hero is OOP — J14 doesn't apply
        if _is_ip is None:
            # Fallback: position heuristic
            hero_pos_val = {'BTN': 6, 'CO': 5, 'HJ': 4, 'MP': 3, 'UTG+1': 2, 'UTG': 1, 'SB': 0, 'BB': 0}
            if hero_pos_val.get(h['position'], 0) < 4:
                continue  # position suggests OOP
        if True:  # IP confirmed (either hero_ip=True or position heuristic passed)
            mistakes.append({'id': h['id'], 'cards': normalize_hand(h.get('cards',[])), 'pos': h['position'],
                             'stack_bb': round(h.get('stack_bb',0)), 'format': h['format'],
                             'tournament': h.get('tournament','')[:45], 'type': 'Monotone IP No CBet (J14)',
                             'confidence': 'MARGINAL',  # B257: was missing — None promoted to CLEAR
                             'is_satellite': h['format']=='SATELLITE',
                             'board': ' '.join(h.get('board',[])[:3]),
                             'action_summary': h.get('action_summary', '')})

    # --- J33: JAM BLOCKER PREFERENCE (v7.14) ---
    # When Hero jams >=2x pot on a flush/straight-completing runout,
    # flag if Hero holds non-nut blocker (Kx/Qx of flush suit, or non-nut straight card).
    # MARGINAL flag — review candidate, not auto-CLEAR.
    for h in hands:
        board = h.get('board', [])
        if len(board) < 4: continue  # need turn or river
        cards_raw = h.get('cards', [])
        if len(cards_raw) < 2: continue
        hero_bets = h.get('hero_bets', [])
        # Find a Hero jam (>=2x pot = size_pct >=200) on turn or river
        big_jam = None
        for b in hero_bets:
            if len(b) < 3: continue
            street, size_pct, btype = b[0], b[1], b[2]
            if street in ('turn', 'river') and isinstance(size_pct, (int, float)) and size_pct >= 200:
                big_jam = (street, size_pct, board[:3] if street == 'turn' else board[:4] if street == 'river' and len(board) >= 4 else board[:3])
                break
        if not big_jam: continue
        street, size_pct, runout_board = big_jam
        # Full runout board at the point of the jam
        full_runout = board[:4] if street == 'turn' else board[:5]
        # Detect flush completion: 3+ of same suit on board including turn/river card
        suit_counts = Counter(c[-1] for c in full_runout if len(c) >= 2)
        flush_suit = None
        for suit, cnt in suit_counts.items():
            if cnt >= 3:
                flush_suit = suit
                break
        # Detect straight completion is complex — skip, focus on flush blocker
        if not flush_suit: continue
        # Hero's cards of the flush suit
        hero_flush_cards = [c for c in cards_raw if len(c) >= 2 and c[-1] == flush_suit]
        # B36 fix (v7.45): on 4-flush boards where the Ace-of-flush-suit is
        # ON THE BOARD, the King-of-flush-suit becomes the EFFECTIVE NUT
        # flush (no opponent can construct a higher flush because the Ah is
        # community). Previous code only checked Hero's hand for has_ace_flush.
        # Caught on TM5936336437 (KhQs BB 62BB, board 2h-6d-3h-Ah-4h: Hero's
        # Kh is the effective nut flush, river jam is pure VALUE not a weak-
        # blocker bluff). Fix: has_ace_flush_effective also fires when Ace
        # of flush suit is on the board.
        ace_of_flush_on_board = any(
            (len(c) >= 2 and c[0] == 'A' and c[-1] == flush_suit)
            for c in full_runout)
        # Nut blocker = Ace of flush suit. Weak blocker = K/Q of flush suit. No blocker = neither.
        has_ace_flush_in_hand = any(c[0] == 'A' for c in hero_flush_cards)
        has_ace_flush_effective = has_ace_flush_in_hand or ace_of_flush_on_board
        has_ace_flush = has_ace_flush_effective  # back-compat alias used below
        has_kq_flush = (any(c[0] in ('K', 'Q') for c in hero_flush_cards)
                        and not has_ace_flush_effective)
        # Only flag weak-blocker jams (has K/Q of suit, not A) — "thin jam" candidates
        if has_kq_flush:
            mistakes.append({'id': h['id'], 'cards': normalize_hand(cards_raw), 'pos': h['position'],
                             'stack_bb': round(h.get('stack_bb',0)), 'format': h['format'],
                             'tournament': h.get('tournament','')[:45],
                             'type': f'Weak-Blocker Jam {street.title()} (J33)',
                             'confidence': 'MARGINAL',
                             'is_satellite': h['format']=='SATELLITE',
                             'board': ' '.join(full_runout),
                             'jam_size_pct': size_pct,
                             'flush_suit': flush_suit,
                             'action_summary': h.get('action_summary', '')})

    # --- J34: ICM SHORT-STACK MP RAISE-OR-3BET (v7.14) ---
    # At <=30BB eff in ICM phases, MP vs EP/MP open: flat is a mistake for
    # AQo/AJs/ATs/AJo (should 3-bet instead). 99/AQs flat exceptions.
    ICM_PHASES = {'bubble_zone', 'post_bubble', 'ft_zone'}
    J34_FLAT_MISTAKE_HANDS = {'AQo', 'AJs', 'ATs', 'AJo'}
    for h in hands:
        pos = h.get('position', '')
        if pos not in ('MP', 'HJ'): continue  # MP or HJ (both "mid" vs EP)
        phase = h.get('tournament_phase', '')
        if phase not in ICM_PHASES: continue
        eff_stack = h.get('eff_stack_bb', 999)
        if eff_stack > 30: continue
        opener_pos = h.get('opener_position', '')
        if opener_pos not in ('UTG', 'UTG+1', 'MP', 'HJ'): continue  # EP or MP-vs-MP
        if h.get('opener_position', '') == pos: continue  # can't face own raise
        pf_raise_count = h.get('pf_raise_count', 0)
        if pf_raise_count != 1: continue  # only facing a single open
        # Hero flatted (vpip=True, pfr=False, not fold)
        if not h.get('vpip') or h.get('pfr') or h.get('hero_3bet'): continue
        if h.get('pf_action') == 'fold': continue
        hs = normalize_hand(h.get('cards', []))
        if hs not in J34_FLAT_MISTAKE_HANDS: continue
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': pos,
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'ICM Short-Stack MP Flat (J34)',
                         'confidence': 'CLEAR',
                         'is_satellite': h['format']=='SATELLITE',
                         'opener': opener_pos,
                         'tournament_phase': phase,
                         'action_summary': h.get('action_summary', '')})

    # --- AMIT WEAK-AX FLAT vs 3BET/SQUEEZE (v7.29; v7.39 B21 narrowed) ---
    # Per Amit (Day 11 review of H7 A2hh BU vs SB 3bet, H5 A4dd MP vs BU
    # squeeze): weak Aces (A2-A8 × {o,s}) facing a 3bet OR squeeze should
    # FOLD or SHOVE — never flat. Flat surrenders fold equity AND realizes
    # equity poorly OOP postflop. Generalizes J43 (ICM raise-or-fold) to
    # chip-EV phases at deeper stacks.
    #
    # B21 narrowing (v7.39): solver-confirmed (GTOW 2026-05-08) that A3s CO
    # 35BB call vs BTN 3-bet IP is PERFECT PLAY (0 EV loss). Detector was
    # over-firing past Amit's actual framing. Amit's two original spots
    # were:
    #   • BTN-vs-SB-3bet  (Hero opens BTN, SB 3-bets, Hero is BTN)
    #   • MP-vs-BTN-squeeze (Hero opens MP, someone calls, BTN squeezes)
    # Outside those two matchups, the detector still RUNS but emits
    # MARGINAL (not CLEAR) — preserves the signal for LLM analyst review
    # without polluting the confirmed-leak count or leak persistence.
    #
    # Trigger: Hero in pot pre-3bet/squeeze (vpip), pf_raise_count>=2,
    #          Hero pf_action==call, hand∈A2-A8 family, stack>=30BB,
    #          phase NOT in ICM_PHASES (J43 covers ICM cases).
    AMIT_WEAK_AX_HANDS = {
        'A2o','A2s','A3o','A3s','A4o','A4s','A5o','A5s',
        'A6o','A6s','A7o','A7s','A8o','A8s'
    }

    def _amit_three_bettor_position(pf_seq):
        """Walk pf_sequence and return position of first 3-bettor (the
        second non-blind 'raises' action), or None if not found."""
        if not pf_seq: return None
        raise_count = 0
        for item in pf_seq:
            # Format: "POS[(H)]:action"  e.g. "BTN:raises", "SB(H):3bet", "BB:calls"
            if ':' not in item: continue
            pos_part, action = item.split(':', 1)
            pos = pos_part.replace('(H)', '').strip()
            if action.strip() in ('raises', '3bet', 'raise'):
                raise_count += 1
                if raise_count == 2:
                    return pos
        return None

    def _amit_matchup_label(hero_pos, three_bettor_pos, squeeze_case):
        """Return one of: 'btn_vs_sb_3bet', 'mp_vs_btn_squeeze', 'other'.
        These are the two Amit-original matchups; everything else is 'other'."""
        if not three_bettor_pos:
            return 'other'
        # Case 1: Hero=BTN faces 3-bet from SB (single 3-bet, no caller in between)
        if (not squeeze_case) and hero_pos == 'BTN' and three_bettor_pos == 'SB':
            return 'btn_vs_sb_3bet'
        # Case 2: Hero=MP faces squeeze from BTN (caller in between)
        if squeeze_case and hero_pos == 'MP' and three_bettor_pos == 'BTN':
            return 'mp_vs_btn_squeeze'
        return 'other'

    for h in hands:
        if not h.get('vpip'): continue
        if h.get('pf_action') != 'call': continue
        pf_raises = h.get('pf_raise_count', 0)
        if pf_raises < 2: continue  # need 3bet+ in pot
        eff_stack = h.get('eff_stack_bb', 0)
        if eff_stack < 30: continue  # below 30BB the shove branch dominates
        phase = h.get('tournament_phase', '')
        if phase in ICM_PHASES: continue  # J43 territory; don't double-flag
        hs = normalize_hand(h.get('cards', []))
        if hs not in AMIT_WEAK_AX_HANDS: continue
        # Distinguish 3bet vs squeeze for note: squeeze = caller(s) before
        # the 3-bet. We approximate by checking if Hero was a caller (not
        # opener) — Hero-as-opener facing 3bet is the "vs 3bet" case;
        # Hero-as-caller facing 3bet is the "vs squeeze" case.
        # NOTE: this `squeeze_case` is the OLD (pre-B21) labeling. The
        # B21 matchup gate uses a precise definition based on pf_sequence
        # below (faced_squeeze vs faced_3bet from parser), but we keep
        # squeeze_case for the action_label only.
        squeeze_case = bool(h.get('vpip') and not h.get('pfr'))
        action_label = 'squeeze' if squeeze_case else '3bet'

        # B21 gate: classify the matchup using parser's faced_squeeze flag
        # (more reliable than the legacy squeeze_case heuristic) + the
        # 3-bettor position from pf_sequence.
        is_squeeze_real = bool(h.get('faced_squeeze'))
        three_bettor_pos = _amit_three_bettor_position(h.get('pf_sequence', []))
        hero_pos = h.get('position', '')
        matchup = _amit_matchup_label(hero_pos, three_bettor_pos, is_squeeze_real)

        if matchup == 'other':
            # Outside Amit's original framing — solver-validated this is OK at
            # 30-50BB SPR. B21 v7.46: downgrade to NOISE_FALSE_POSITIVE so it's
            # excluded from leak-count. Renderer routes NOISE flags to a
            # separate audit-only list (not promoted to III.3 metrics).
            if 30 <= eff_stack <= 50:
                confidence = 'NOISE_FALSE_POSITIVE'
                note_suffix = (f' — ✅ B21 v7.46: matchup ({hero_pos} vs '
                               f'{three_bettor_pos or "?"} '
                               f'{"squeeze" if is_squeeze_real else "3bet"}) outside '
                               f"Amit's original framing AND solver-validated at "
                               f"30-50BB SPR. Excluded from leak count.")
            else:
                confidence = 'MARGINAL'
                note_suffix = (f' — ⚠️ B21: matchup ({hero_pos} vs {three_bettor_pos or "?"} '
                               f'{"squeeze" if is_squeeze_real else "3bet"}) is outside Amit\'s '
                               f'original framing (BTN-vs-SB-3bet, MP-vs-BTN-squeeze). '
                               f'Solver-validated A3s CO 35BB call vs BTN 3bet = perfect play.')
        else:
            confidence = 'CLEAR'
            note_suffix = f' (Amit-original matchup: {matchup})'

        # B21 v7.46: skip noise false-positives entirely from the mistakes list
        if confidence == 'NOISE_FALSE_POSITIVE':
            continue

        mistakes.append({'id': h['id'], 'cards': hs,
                         'pos': hero_pos,
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': f'Weak Ax Flat vs {action_label.title()} (Amit)',
                         'confidence': confidence,
                         'is_satellite': h['format']=='SATELLITE',
                         'tournament_phase': phase,
                         # B21 metadata fields for downstream consumers
                         'amit_matchup': matchup,
                         'amit_three_bettor_pos': three_bettor_pos,
                         'note': (f'Flatted {action_label} with {hs} at {round(eff_stack)}BB — '
                                  f'Amit: weak Ax (A2-A8) facing 3bet/squeeze must fold or shove, '
                                  f'never flat' + note_suffix),
                         'action_summary': h.get('action_summary', '')})

    # --- N9: MP ATo FLAT vs PFR — CHIP-EV (Amit, v7.48 2026-05-12) ---
    # Per Amit (2026-05-12 session): "stop calling MP after PFR with ATo".
    # Ron confirmed (2026-05-12): scope = ATo only, NOT AJo (AJo stays
    # defensible as MP flat in some contexts). Chip-EV phases only —
    # J34 owns ICM <=30BB AQo/AJs/ATs/AJo flat case.
    #
    # WHY ATo: dominated by AK/AQ/AJ in UTG/UTG+1 open ranges; no flush
    # +ace draws; poor equity realization OOP. Fold or 3-bet are the
    # correct lines.
    #
    # Trigger: Hero MP + opener in {UTG, UTG+1} + pf_raise_count==1 +
    #          ATo + Hero flat-called + eff>=25BB + late_reg phase.
    for h in hands:
        pos = h.get('position', '')
        if pos != 'MP': continue
        phase = h.get('tournament_phase', '')
        # Exclude ICM phases (J34 owns those). Allow late_reg, None, post_reg.
        # Inclusion-by-exclusion: matches J34/Amit-weak-Ax pattern. Synthetic
        # test fixtures parse to phase=None; we want detector to fire there.
        if phase in ICM_PHASES: continue
        eff_stack = h.get('eff_stack_bb', 0)
        if eff_stack < 25: continue  # below 25BB = push-fold regime, other rules
        opener_pos = h.get('opener_position', '')
        if opener_pos not in ('UTG', 'UTG+1'): continue
        pf_raise_count = h.get('pf_raise_count', 0)
        if pf_raise_count != 1: continue  # single open only
        # Hero flatted: vpip=True, pfr=False, no 3-bet, action=call
        if not h.get('vpip') or h.get('pfr') or h.get('hero_3bet'): continue
        if h.get('pf_action') != 'call': continue
        hs = normalize_hand(h.get('cards', []))
        if hs != 'ATo': continue  # Ron-confirmed: ATo only, NOT AJo/AQo
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': pos,
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'MP ATo Flat vs PFR (Amit N9)',
                         'confidence': 'CLEAR',
                         'is_satellite': h['format']=='SATELLITE',
                         'opener': opener_pos,
                         'tournament_phase': phase,
                         'note': (f'Flatted UTG/UTG+1 open with ATo at MP {round(eff_stack)}BB — '
                                  f'Amit (2026-05-12): ATo MP vs PFR is fold or 3-bet, '
                                  f'never flat. AJo intentionally NOT in scope (Ron-confirmed).'),
                         'action_summary': h.get('action_summary', '')})

    # --- J35: RESHOVE CEILING — <30BB vs small villain jam (v7.14) ---
    # Mid-late tournament with <30BB eff facing villain jam <=8BB:
    # no reshove range exists. Call or fold only. Flag Hero reshoves.
    # v7.30 P1-3: gate on no prior opener — J35 logic assumes HU vs jammer.
    # In squeeze scenarios (someone opened, then villain jammed) Hero's
    # 4-bet/reshove also denies the original opener and the EV is different.
    for h in hands:
        if not detector_prereq_satisfied('j35_reshove_ceiling', h):
            continue
        # v7.30 P1-3: skip coolers — losing a +EV decision to a stronger holding
        # (e.g. 88 vs villain's 44 jam where post-flop runout was set-over-pair)
        # is not a reshove mistake; it was a fine reshove that ran into a cooler.
        if h['id'] in cooler_hand_ids: continue
        jammer_stack = h.get('jammer_stack_bb', 0)
        if not (3 <= jammer_stack <= 8): continue  # small villain jam
        hero_stack = h.get('stack_bb', 999)
        if hero_stack >= 30: continue  # deep enough to reshove — J35 doesn't apply
        phase = h.get('tournament_phase', '')
        # J35 applies mid-late tournament only (not late_reg both deep)
        if phase == 'late_reg': continue
        # Hero reshoved = Hero raised over the jam (hero_3bet or pf_raise_count increased by Hero)
        if not (h.get('hero_3bet') or h.get('pf_action') in ('raise', 'allin')): continue
        # Hero must have put in more than call — pf_allin with Hero as aggressor over villain jam
        hs = normalize_hand(h.get('cards', []))
        # Exclude premiums that are always a reshove/call anyway — AA/KK/QQ/AKs/AKo
        if hs in {'AA', 'KK', 'QQ', 'AKs', 'AKo'}: continue
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': h.get('position', ''),
                         'stack_bb': round(hero_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'Reshove Over Small Jam <30BB (J35)',
                         'confidence': 'CLEAR',
                         'is_satellite': h['format']=='SATELLITE',
                         'jammer_stack_bb': round(jammer_stack),
                         'jammer_position': h.get('jammer_position', ''),
                         'tournament_phase': phase,
                         'action_summary': h.get('action_summary', '')})

    # --- J36: ICM JAM-THRESHOLD COMPRESSION (v7.14) ---
    # In ICM phases, Hero preflop OPEN-jams at 30-37BB eff are potentially
    # oversized — 3-bet sizing should capture same EV. REVIEW flag (MARGINAL).
    # Exclude obvious small-stack pressure spots and premium jams.
    # v7.30 P1-3: shared prereq enforces open-jam (Hero raise count == 1).
    # 4-bet jams (Hero opened, got 3-bet, jammed back) face a different decision tree.
    for h in hands:
        if not detector_prereq_satisfied('j36_icm_open_jam', h): continue
        # v7.30 P1-3: skip coolers (see J35 for rationale).
        if h['id'] in cooler_hand_ids: continue
        # Hero must be the one jamming (pfr or hero_3bet or jammer is Hero)
        if not (h.get('pfr') or h.get('hero_3bet')): continue
        phase = h.get('tournament_phase', '')
        if phase not in ICM_PHASES: continue
        eff_stack = h.get('eff_stack_bb', 0)
        if not (30 <= eff_stack <= 37): continue
        hs = normalize_hand(h.get('cards', []))
        # Skip premiums — jamming AA/KK/QQ/AKs is standard at this depth
        if hs in {'AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo'}: continue
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': h.get('position', ''),
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'ICM Jam 30-37BB — Review Sizing (J36)',
                         'confidence': 'MARGINAL',
                         'is_satellite': h['format']=='SATELLITE',
                         'tournament_phase': phase,
                         'action_summary': h.get('action_summary', '')})

    # --- J37: SHALLOW BvB BB JAM RANGE (v7.14) ---
    # BvB (HU, n_players=2) at <21BB from BB, Hero jammed middling broadway.
    # Correct BB jam range = small pairs + offsuit aces (A2-AJ per J12) +
    # occasional blocker-aware hands. Middling broadways (KJo/QJo/JTo/JTs/KJs/QJs)
    # don't generate enough FE — villain folds worse, calls better.
    J37_JAM_MISTAKE_HANDS = {'KJo', 'QJo', 'JTo', 'JTs', 'KJs', 'QJs', 'KTo', 'QTo', 'T9s', 'J9s'}
    for h in hands:
        n_players = h.get('n_players', 0)
        if n_players != 2: continue  # HU only
        if h.get('position') != 'BB': continue
        stack = h.get('stack_bb', 999)
        if stack >= 21: continue
        if not h.get('pf_allin'): continue
        # Hero must be the jammer — either open-jammed (first_in + pfr) or 3-bet jammed
        if not (h.get('pfr') or h.get('hero_3bet')): continue
        hs = normalize_hand(h.get('cards', []))
        if hs not in J37_JAM_MISTAKE_HANDS: continue
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': 'BB',
                         'stack_bb': round(stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'BvB BB Shallow Jam — Middling Broadway (J37)',
                         'confidence': 'CLEAR',
                         'is_satellite': h['format']=='SATELLITE',
                         'n_players': n_players,
                         'action_summary': h.get('action_summary', '')})

    # ========================================================
    # v7.15 NEW DETECTIONS (from Apr 19 session review)
    # ========================================================

    # --- V15a: 4BP FLAT-CALL NON-PREMIUM AT DEEP SPR (v7.15) ---
    # Hero flats a 4-bet OOP or IP at 40+ BB eff with <JJ.
    # Bad SPR setup — not deep enough to set-mine, too deep to commit profitably.
    # Correct line: 5-jam (with premiums) or fold. Flat-call = worst of both worlds.
    # Example: 77 CO flats SB cold 4-bet at 53BB → checkdown loss.
    V15A_PREMIUMS = {'AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo'}
    for h in hands:
        pot_type = h.get('pot_type', '')
        if pot_type != '4BP': continue
        if h.get('pf_action') != 'call': continue  # Hero flat-called the 4-bet
        if h.get('pf_allin'): continue  # v8.7.9 FIX: calling a 4-bet JAM is not a deep flat
        # v7.31 Patch 6: V15a requires Hero hadn't raised earlier (true flat,
        # not 4-bet-then-call). If Hero made a raise the leak is the raise,
        # not a "flat-call." Exception #12.
        if not detector_prereq_satisfied('v15a_4bp_flat', h): continue
        eff_stack = h.get('eff_stack_bb', 0)
        if eff_stack < 40: continue  # need deep SPR for this to be a real error
        hs = normalize_hand(h.get('cards', []))
        if hs in V15A_PREMIUMS: continue  # premium hands — flat can be exploit vs nits
        # Exclude if Hero was pot-committed (stack <20% bigger than what's called)
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': h.get('position', ''),
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': '4BP Flat-Call Non-Premium (V15a)',
                         'confidence': 'CLEAR',
                         'is_satellite': h['format']=='SATELLITE',
                         'action_summary': h.get('action_summary', '')})

    # --- V15b: 5-BET JAM NON-PREMIUM AT DEEP SPR (v7.15) ---
    # Hero 5-bet-jams with <QQ at 40+ BB eff. Villain's cold 4-bet range at 100BB
    # is QQ+/AK. 5-jamming with A7s/77/etc has ~25% equity, heavily -EV.
    # Exception: MYSTERY_BOUNTY format when Hero covers villain → downgrade to MARGINAL
    # (6-fig mystery prize EV + elimination pickup shifts breakeven).
    # v7.15.1: require pf_raise_count >= 4 (i.e., Hero's final raise is 5-bet+, not 4-bet)
    V15B_PREMIUMS = {'AA', 'KK', 'QQ', 'AKs', 'AKo'}
    for h in hands:
        pot_type = h.get('pot_type', '')
        if pot_type != '4BP': continue
        if not h.get('pf_allin'): continue  # must be all-in preflop
        # Hero must be the aggressor (5-bet/jam over a 4-bet)
        pf_raise_count = h.get('pf_raise_count', 0)
        if pf_raise_count < 4: continue  # Hero's last raise must be a 5-bet+ (4 total raises incl. opening)
        # Hero must have raised (not called the 4-bet)
        if h.get('pf_action') not in ('4bet+', 'raise', '3bet'): continue
        # v7.48.1: prefer eff_stack_bb_at_decision for pure-PF shoves where
        # players_at_flop < 2 and the flop-time eff defaults to Hero's stack.
        eff_stack = h.get('eff_stack_bb_at_decision', h.get('eff_stack_bb', 0))
        if eff_stack < 40: continue
        hs = normalize_hand(h.get('cards', []))
        if hs in V15B_PREMIUMS: continue
        # Bounty EV adjustment: MYSTERY_BOUNTY + Hero covers villain → MARGINAL
        fmt = h.get('format', '')
        hero_covers = h.get('stack_bb', 0) > eff_stack * 1.1  # Hero stack > eff means Hero covers
        if fmt == 'MYSTERY_BOUNTY' and hero_covers:
            confidence = 'MARGINAL'
            note = 'Mystery Bounty + Hero covers — bounty EV relaxes threshold'
        elif eff_stack >= 60:
            # B22 (v7.46): at 60+ BB, GTOW returns 'no solution' for these spots
            # (e.g. 88 BTN 80BB 5BJ vs MP 4-bet). Can't confidently call them
            # mistakes without solver validation. Downgrade to MARGINAL with
            # explicit note so analyst can review case-by-case.
            confidence = 'MARGINAL'
            note = (f'Solver-validation incomplete at {round(eff_stack)}BB '
                    f'(GTOW: no solution at this depth). Reviewed case-by-case.')
        else:
            confidence = 'CLEAR'
            note = ''
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': h.get('position', ''),
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': fmt,
                         'tournament': h.get('tournament','')[:45],
                         'type': '5-Bet Jam Non-Premium Deep (V15b)',
                         'confidence': confidence,
                         'is_satellite': fmt=='SATELLITE',
                         'hero_covers': hero_covers,
                         'bounty_note': note,
                         'action_summary': h.get('action_summary', '')})

    # --- V15c: FLAT 5-BET+ OOP MULTIWAY (v7.15) ---
    # Hero calls a 5-bet or 6-bet OOP with 3+ players still live (or action pattern
    # that puts Hero in a multi-player war) with <KK. Giving up initiative deep with
    # a non-premium overpair = worst outcome (bloated pot OOP, no postflop plan).
    # Example: QQ MP flats SB 6-bet with BTN 5-bet behind → checkdown loss.
    V15C_CALLABLE = {'AA', 'KK'}  # only hands that can flat a 5-bet+
    for h in hands:
        if h.get('pf_action') != 'call': continue  # Hero flat-called
        if h.get('pf_allin'): continue  # v8.7.9 FIX: a call of an all-in is not a "flat"
        pf_raise_count = h.get('pf_raise_count', 0)
        if pf_raise_count < 4: continue  # need 5-bet or more to have happened
        # v7.31 Patch 6: V15c requires pot is STILL multiway at the moment
        # of Hero's call. If the cold-caller folded after the 5-bet jam and
        # only Hero + jammer remain at the call, it's HU and not a V15c
        # mistake. Exception #14.
        if not detector_prereq_satisfied('v15c_5bp_flat_oop_mw', h): continue
        # Hero OOP? check position
        pos = h.get('position', '')
        hero_pos_val = {'BTN': 6, 'CO': 5, 'HJ': 4, 'MP': 3, 'UTG+1': 2, 'UTG': 1, 'SB': 0, 'BB': 0}
        if hero_pos_val.get(pos, 0) >= 5: continue  # CO/BTN are effectively IP — this leak is OOP
        # Multiway check: 3+ players involved in preflop action (had put money in)
        pf_seq = h.get('pf_sequence', [])
        actors = set()
        for a in pf_seq:
            if ':' in a:
                player = a.split(':')[0]
                if 'folds' not in a:
                    actors.add(player)
        if len(actors) < 3: continue  # need 3+ non-folding actors
        hs = normalize_hand(h.get('cards', []))
        if hs in V15C_CALLABLE: continue  # AA/KK flat of 5-bet+ is exploit, not punt
        eff_stack = h.get('eff_stack_bb', 0)
        if eff_stack < 30: continue  # short-stack forced spots excluded
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': pos,
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'Flat 5-Bet+ OOP Multiway (V15c)',
                         'confidence': 'CLEAR',
                         'is_satellite': h['format']=='SATELLITE',
                         'pf_raise_count': pf_raise_count,
                         'multiway_actors': len(actors),
                         'action_summary': h.get('action_summary', '')})

    # ========================================================
    # v7.16 NEW DETECTIONS — Hungry Horse H-series (Appendix L)
    # ========================================================

    # --- N13: SB PAIR 3-BET-FOLD vs LP at <=30BB (Amit, v7.48 2026-05-12) ---
    # Per Amit (2026-05-12): "no 3-bet-fold with pair, less than 30BB. So
    # with 66 from SB vs BTN open, just shove with 30BB."
    # Sub-clause of J11 (3-bet-fold <50BB = leak), narrowed to pair-class
    # + SB position + shallow stack where shove is the specific corrective.
    #
    # Trigger: Hero SB + eff<=30BB + opener in {CO, BTN} + Hero pair +
    #          Hero raised non-all-in (the 3-bet) + faced 4-bet + folded.
    # The shove was the correct action; 3-bet then fold = J11 violation
    # + missed shove EV. CLEAR.
    PAIR_HANDS = {f'{r}{r}' for r in '23456789TJQKA'}
    for h in hands:
        pos = h.get('position', '')
        if pos != 'SB': continue
        # v7.48.1: prefer eff_stack_bb_at_decision (Hero 3-bet then folded =
        # players_at_flop=0, flop-context eff defaults to stack_bb).
        eff_stack = h.get('eff_stack_bb_at_decision', h.get('eff_stack_bb', 0))
        if eff_stack > 30: continue
        opener_pos = h.get('opener_position', '')
        if opener_pos not in ('CO', 'BTN'): continue
        hs = normalize_hand(h.get('cards', []))
        if hs not in PAIR_HANDS: continue
        # Hero must have 3-bet (raised once) and the 3-bet must NOT have
        # been all-in (otherwise the rule didn't fire — Hero correctly shoved)
        if not h.get('hero_3bet'): continue
        if h.get('pf_allin'): continue  # Hero shoved — correct line per Amit
        # Hero ultimately folded (the 3-bet-fold pattern)
        if h.get('pf_action') != 'fold': continue
        # pf_raise_count >= 3 (opener + Hero 3-bet + villain 4-bet)
        if h.get('pf_raise_count', 0) < 3: continue
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': pos,
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'SB Pair 3-bet-fold vs LP <=30BB (Amit N13)',
                         'confidence': 'CLEAR',
                         'is_satellite': h['format']=='SATELLITE',
                         'opener': opener_pos,
                         'note': (f'3-bet-then-folded {hs} from SB at {round(eff_stack)}BB '
                                  f'vs {opener_pos} open — Amit (2026-05-12): no 3-bet-fold '
                                  f'with pair <=30BB. Correct line was shove (~50% equity '
                                  f'vs called range + FE vs fold range).'),
                         'action_summary': h.get('action_summary', '')})

    # --- N3: JTs BvB SB — NO FOLD TO BB JAM <=30BB (Amit, v7.65) ---
    # Per Amit (2026-05-12): "JTs BvB — don't fold to a BB jam at <=30BB."
    # JTs retains enough equity vs a BB over-jamming range, plus the dead
    # blind money, that folding it at <=30BB is a clear -EV pass.
    # Trigger: Hero is the SB (HU button) + BvB (n_players==2) + eff<=30BB
    # + JTs + Hero folded to the BB's 3-bet/jam (and Hero did not themselves
    # commit all-in). CLEAR.
    #
    # Field note: villain_jammed is set only for OPEN-jams, so it does not
    # fire on a BB re-jam over Hero's open — fold_to_3bet is the correct
    # signal (in a HU pot the only possible 3-bettor IS the BB). The HU
    # button is parser-tagged 'BTN' (== the SB seat heads-up).
    #
    # Scope note: N3's second half ("at 60-100BB open standard and flat
    # 3-bets") is a deep-stack principle with no discrete pre-result error
    # to anchor on — it stays drill-only. Only the <=30BB fold-to-jam,
    # which IS evaluable as -EV before the result, is detected here.
    for h in hands:
        if h.get('n_players') != 2: continue            # BvB only (HU pot)
        if h.get('position') not in ('SB', 'BTN'): continue  # Hero is the SB (HU button)
        eff_stack = h.get('eff_stack_bb_at_decision', h.get('eff_stack_bb', 0))
        if eff_stack > 30: continue
        hs = normalize_hand(h.get('cards', []))
        if hs != 'JTs': continue
        if not h.get('fold_to_3bet'): continue          # Hero folded to the BB's 3-bet/jam
        if h.get('pf_allin'): continue                  # Hero called/shoved = correct line
        mistakes.append({'id': h['id'], 'cards': hs, 'pos': h.get('position', ''),
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'JTs BvB Fold to BB Jam <=30BB (Amit N3)',
                         'confidence': 'CLEAR',
                         'is_satellite': h['format']=='SATELLITE',
                         'tournament_phase': h.get('tournament_phase', ''),
                         'note': (f'Folded JTs from the SB to a BB 3-bet/jam at '
                                  f'{round(eff_stack)}BB BvB — Amit (2026-05-12): no fold '
                                  f'with JTs to a BB jam at <=30BB. JTs has the equity + '
                                  f'dead money to continue (call, or shove if not all-in).'),
                         'action_summary': h.get('action_summary', '')})

    # --- HH5: TP-FOLD OVERBET BLUFF AT ≤100BB (v7.16) ---
    # Hero river-overbets as aggressor at ≤100BB eff on a board where
    # villain could have top pair. Live/low-stakes populations don't
    # fold TP at shallow depths — empty-clip with overbet bluff on a
    # board like A72r torches money when villain has AJ.
    # MARGINAL flag because "villain could have TP" requires manual
    # verification: sometimes villain raised off TP on flop (capping
    # their range), sometimes board action implies villain can't have
    # TP (e.g., they checked back A-high flop → no Ax).
    # Exclusions: value bets, deep stacks (>100BB), very shallow (<25BB
    # where jams are expected not overbets), non-aggressor Hero,
    # boards without a broadway card (TP rare).
    for h in hands:
        hero_bets_list = h.get('hero_bets', [])
        river_bets = [b for b in hero_bets_list if len(b) >= 3 and b[0] == 'river']
        if not river_bets: continue
        river_bet = river_bets[-1]
        size_pct = river_bet[1] if len(river_bet) >= 2 else 0
        if not isinstance(size_pct, (int, float)) or size_pct < 100:
            continue  # must be overbet (>100% pot)
        if h.get('river_action') != 'bluff': continue  # must be a bluff, not value
        if not h.get('pfr'): continue  # Hero must be aggressor
        eff_stack = h.get('eff_stack_bb', 0)
        if eff_stack > 100: continue  # rule applies only at ≤100BB
        if eff_stack < 25: continue  # too shallow — jams expected, HH5 doesn't apply
        board = h.get('board', [])
        if len(board) < 5: continue  # need full river board
        # Proxy for "villain could have TP": board has Ace/King/Queen/Jack
        board_ranks = set(c[0] for c in board if c)
        if not (board_ranks & {'A','K','Q','J'}): continue
        mistakes.append({'id': h['id'],
                         'cards': normalize_hand(h.get('cards', [])),
                         'pos': h.get('position', ''),
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(eff_stack),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'TP-Fold Overbet Bluff at ≤100BB (HH5)',
                         'confidence': 'MARGINAL',
                         'is_satellite': h['format']=='SATELLITE',
                         'board': ' '.join(board),
                         'river_size_pct': size_pct,
                         'action_summary': h.get('action_summary', '')})

    # --- HH10#1: CONTINUE VS CHECK-BACK-FLOP RAISE-TURN (v7.16) ---
    # Flop goes check-check, then Hero bets turn and villain raises.
    # Live populations almost never bluff this line — it's trap range
    # (QQ+ slow-played on flop, now want to protect via fear-driven
    # sizing when turn opens draws). Continuing with TP or weaker is
    # a CLEAR mistake; only 2P+ should proceed.
    # Detection chain:
    #   1. Flop: no hero_bets AND not villain_bet_flop_first (xx flop)
    #   2. Turn: Hero bet first (hero_bets entry with spot ∈ bet/barrel/
    #      probe/cbet, NOT 'raise'), then Hero faced villain's raise
    #      (facing_bets entry on turn)
    #   3. Hero did NOT fold to the turn raise (continued)
    #   4. Hero's hand at turn was pair or weaker (not 2P+)
    for h in hands:
        hero_bets_list = h.get('hero_bets', [])
        facing_bets_list = h.get('facing_bets', [])
        # Flop must have been check-check
        if any(b[0] == 'flop' for b in hero_bets_list): continue  # Hero bet flop
        if h.get('villain_bet_flop_first'): continue  # villain bet flop
        # Turn: Hero must have bet first (spot != 'raise')
        hero_turn_bets = [b for b in hero_bets_list if len(b) >= 3 and b[0] == 'turn']
        if not hero_turn_bets: continue
        hero_turn_first = hero_turn_bets[0]
        if len(hero_turn_first) >= 3 and hero_turn_first[2] == 'raise': continue
        # Turn: Hero must have faced a villain response (villain raised Hero's bet)
        turn_facing = [b for b in facing_bets_list if len(b) >= 3 and b[0] == 'turn']
        if not turn_facing: continue
        # Hero must NOT have folded to the turn raise (folding is correct — no mistake)
        if turn_facing[-1][2] == 'fold': continue
        # Hero's hand at turn must be pair or weaker
        board = h.get('board', [])
        cards = h.get('cards', [])
        if len(board) < 4 or len(cards) < 2: continue
        turn_hand = hand_strength_name(cards, board[:4])
        if turn_hand not in ('high_card', 'pair'): continue  # 2P+ = correct continue
        # v8.16.1 Bug-2b: the "pair-or-weaker continue is a mistake" premise
        # assumes Hero has little equity. A strong DRAW (flush draw / open-ender)
        # has ~8-9+ outs plus implied odds, so continuing vs a turn check-raise
        # is correct, not a CLEAR mistake. The made-hand rank gate above ignored
        # draws entirely — 78024888 (AQhh on 9hTd2s2h = nut flush draw + 2 overs)
        # was flagged a CLEAR mistake, then rivered the nut flush. Exclude flush
        # draws and open-enders; weak made hands with no draw still flag.
        _hh10_draw = classify_draw(cards, board[:4])
        if _hh10_draw in ('nut_fd', 'fd', 'oesd'):
            continue
        mistakes.append({'id': h['id'],
                         'cards': normalize_hand(cards),
                         'pos': h.get('position', ''),
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(h.get('eff_stack_bb', 0)),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'Continue vs Check-Back-Flop Raise-Turn (HH10#1)',
                         'confidence': 'CLEAR',
                         'is_satellite': h['format']=='SATELLITE',
                         'board': ' '.join(board),
                         'turn_hand_strength': turn_hand,
                         'action_summary': h.get('action_summary', '')})

    # ========================================================
    # v7.17 NEW DETECTIONS — MechanicsOfPoker M-series (Appendix M)
    # ========================================================

    # --- M1: MISSED TURN DELAYED C-BET (v7.17) ---
    # After flop goes check-check, population turn CR vs delayed cbet is <2%.
    # Hero as PFR HU SRP should minbet turn range on non-equity-shift turns.
    # Flag Hero turn-checks (instead of betting) as MARGINAL — missed value
    # from minbet-range exploit.
    # DIRECT FIX for Ron leak #1 (check-call-call-showdown OOP PFR).
    # Exclusions:
    #   - Non-PFR (rule applies only to aggressor)
    #   - Multiway (need HU dynamic)
    #   - Villain bet flop (then it's not flop check-check)
    #   - Hero bet flop (then it's not flop check-check)
    #   - 3BP or 4BP (rule scoped to SRP — 3BP is different game)
    #   - Turn brings equity shift (FD-complete, 3-straight possible, pair):
    #     these turns are different population dynamics, not reliable M1
    #   - Hero's hand is strong enough that check-back is a clear trap-play
    #     (set, two-pair, straight+) — checking back for check-raise line is
    #     acceptable trap construction on certain textures
    for h in hands:
        if not h.get('pfr'): continue
        if _is_preflop_terminal_allin(h): continue
        # Item 13: aggression-missed detectors must not fire when Hero faces
        # an all-in (no raise/bet available — only call-jam-or-fold). Explicit
        # guard to prevent false-fire on spots like 11763529.
        if h.get('villain_allin'): continue
        if h.get('pot_type') != 'SRP': continue
        if h.get('players_at_flop', 0) != 2: continue  # HU only
        hero_bets_list = h.get('hero_bets', [])
        # Flop check-check: Hero no flop bet AND villain no flop bet first
        if any(b[0] == 'flop' for b in hero_bets_list): continue
        if h.get('villain_bet_flop_first'): continue
        # Turn must exist (4-card board)
        board = h.get('board', [])
        if len(board) < 4: continue
        # B121 (Ron 2026-05-20): the turn must have CHECKED to Hero for a
        # delayed c-bet to be possible. If Hero's turn action is anything but
        # a pure check (call / fold / raise — i.e. villain bet first, INCLUDING
        # a caller's donk-lead), there was no delayed-c-bet opportunity to
        # miss. The parser's faced_villain_bet_turn flag does not capture a
        # caller's turn donk-lead, so key off hero_street_actions instead.
        _hsa_turn = (h.get('hero_street_actions') or {}).get('turn', '')
        if _hsa_turn not in ('x', 'check', '', None): continue
        # Hero must have checked turn (no turn bet)
        if any(b[0] == 'turn' for b in hero_bets_list): continue
        # Turn equity-shift filter: skip turns that change dynamics
        flop = board[:3]; turn_card = board[3]
        flop_suits = [c[1] for c in flop]
        suit_counts = {}
        for sv in flop_suits: suit_counts[sv] = suit_counts.get(sv,0)+1
        turn_completes_fd = any(cnt >= 2 and sv == turn_card[1] for sv,cnt in suit_counts.items())
        if turn_completes_fd: continue
        flop_ranks = [c[0] for c in flop]
        if turn_card[0] in flop_ranks: continue  # board pair
        # 3-straight filter
        board4_vals = sorted(set(RANK_VAL[c[0]] for c in board[:4]))
        three_straight = False
        for i in range(len(board4_vals)-2):
            if board4_vals[i+2] - board4_vals[i] <= 4:
                three_straight = True; break
        if three_straight: continue
        # Hero hand strength filter: if 2-pair+, check-back-for-trap is acceptable
        cards = h.get('cards', [])
        if len(cards) < 2: continue
        turn_hand = hand_strength_name(cards, board[:4])
        if turn_hand not in ('high_card', 'pair'): continue
        mistakes.append({'id': h['id'],
                         'cards': normalize_hand(cards),
                         'pos': h.get('position', ''),
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(h.get('eff_stack_bb', 0)),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': 'Missed Turn Delayed C-bet (M1)',
                         'confidence': 'MARGINAL',
                         'is_satellite': h['format']=='SATELLITE',
                         'board': ' '.join(board[:4]),
                         'turn_hand_strength': turn_hand,
                         'action_summary': h.get('action_summary', '')})

    # --- M6: 3BP WET-TURN MEDIUM-EQUITY BARREL (v7.17) ---
    # In 3-bet pots on WET turns — turns that complete a flush draw, introduce
    # a second flush draw, or bring the first flush draw to a previously
    # rainbow flop — population turn CR rate spikes >8%.
    # Hero IP as 3-bettor with medium-equity hand (TP, OESD, combo draw,
    # non-nut FD) must fold to the CR and lose the equity.
    # Correct: BARREL AIR, CHECK medium equity.
    # DIRECT FIX for Ron leak #3 (one-and-done barrel on wet 3BPs).
    # Exclusions:
    #   - Not 3BP
    #   - Hero not PFR (3-bettor)
    #   - Hero OOP (rule is IP-specific)
    #   - Multiway (need HU dynamic)
    #   - Strong made hand (2P+, overpair) — barrel correct
    #   - Pure air (no pair, no draw) — barrel correct per M6
    for h in hands:
        if h.get('pot_type') != '3BP': continue
        if not h.get('pfr'): continue
        if _is_preflop_terminal_allin(h): continue
        if not h.get('hero_ip'): continue
        if h.get('players_at_flop', 0) != 2: continue  # HU only
        hero_bets_list = h.get('hero_bets', [])
        turn_bets = [b for b in hero_bets_list if len(b) >= 3 and b[0] == 'turn' and b[2] != 'raise']
        if not turn_bets: continue
        board = h.get('board', [])
        if len(board) < 4: continue
        # Wet-turn detection: turn introduces significant CR-risk. Three cases:
        #   (a) Turn COMPLETES flop's 2-suit FD (flop had 2-of-suit, turn makes 3)
        #   (b) Two distinct suits on 4-board each with 2 cards (double-FD board)
        #   (c) Flop was rainbow, turn introduces a 2-suit (FD just appeared; new
        #       draws arrive that villain can check-raise with)
        # All three trigger population turn CR rate spikes >8% in 3BPs.
        board4_suits = [c[1] for c in board[:4]]
        suit_counts = {}
        for sv in board4_suits: suit_counts[sv] = suit_counts.get(sv,0)+1
        flop_suits = [c[1] for c in board[:3]]
        flop_suit_counts = {}
        for sv in flop_suits: flop_suit_counts[sv] = flop_suit_counts.get(sv,0)+1
        # (a) turn completes flop FD
        turn_completes_fd = any(cnt == 3 and flop_suit_counts.get(sv, 0) == 2
                                for sv, cnt in suit_counts.items())
        # (b) two distinct suits each with 2 on 4-board
        two_2suits = sum(1 for cnt in suit_counts.values() if cnt == 2) >= 2
        # (c) flop was rainbow (3 different suits) + turn introduced a 2-suit pair
        flop_rainbow = len(flop_suit_counts) == 3
        turn_introduces_fd = flop_rainbow and any(cnt == 2 for cnt in suit_counts.values())
        wet_turn = turn_completes_fd or two_2suits or turn_introduces_fd
        if not wet_turn: continue
        cards = h.get('cards', [])
        if len(cards) < 2: continue
        turn_hand = hand_strength_name(cards, board[:4])
        # Strong made hands — barrel correct, skip
        if turn_hand in ('two_pair', 'trips', 'straight', 'flush', 'full_house',
                         'quads', 'straight_flush'): continue
        # Classify draw to detect medium equity
        draw = classify_draw(cards, board[:4])
        is_medium_equity = False
        if turn_hand == 'pair': is_medium_equity = True
        elif draw in ('oesd', 'fd', 'nut_fd'): is_medium_equity = True
        if not is_medium_equity: continue  # pure air = correct to barrel
        # Overpair exclusion — pocket pair higher than all board cards = strong
        if cards[0][0] == cards[1][0]:
            pp_val = RANK_VAL[cards[0][0]]
            board4_max = max(RANK_VAL[c[0]] for c in board[:4])
            if pp_val > board4_max: continue
        mistakes.append({'id': h['id'],
                         'cards': normalize_hand(cards),
                         'pos': h.get('position', ''),
                         'stack_bb': round(h.get('stack_bb', 0)),
                         'eff_stack_bb': round(h.get('eff_stack_bb', 0)),
                         'format': h['format'],
                         'tournament': h.get('tournament','')[:45],
                         'type': '3BP Wet-Turn Medium-Equity Barrel (M6)',
                         'confidence': 'MARGINAL',
                         'is_satellite': h['format']=='SATELLITE',
                         'board': ' '.join(board[:4]),
                         'turn_hand_strength': turn_hand,
                         'draw_type': draw,
                         'action_summary': h.get('action_summary', '')})

    s['mistakes'] = mistakes
    # B257: inclusive filter — only confidence='CLEAR' counts as confirmed.
    # Unset confidence (None) no longer silently promotes to confirmed.
    clear_mistakes = [m for m in mistakes if m.get('confidence') == 'CLEAR']
    s['mistakes_per_100'] = round(len(clear_mistakes)/N*100, 2) if N else 0
    s['marginal_mistakes'] = [m for m in mistakes if m.get('confidence') == 'MARGINAL']
    s['marginal_per_100'] = round(len(s['marginal_mistakes'])/N*100, 2) if N else 0

    # --- FOLD-TO-3BET DETAILS ---
    ftb_details = []
    for h in hands:
        if h.get('fold_to_3bet'):
            hs = normalize_hand(h.get('cards', []))
            is_pair = len(hs)==2
            ftb_details.append({'id': h['id'], 'cards': hs, 'pos': h['position'],
                                'stack_bb': round(h.get('stack_bb',0)), 'format': h['format'],
                                'is_pair_lt50': is_pair and h.get('stack_bb',99) < 50,
                                'pf_sequence': ' → '.join(h.get('pf_sequence', []))})
    s['fold_to_3bet_details'] = ftb_details

    # --- DEEP RUN TRACKER (v7.10: fixed reverse-chronological, added card quality + EAI) ---
    deep_runs = []
    tourney_hands = defaultdict(list)
    for h in hands: tourney_hands[h['tournament']].append(h)
    for tname, th in sorted(tourney_hands.items(), key=lambda x: -len(x[1])):
        if len(th) < 10: continue
        # GGPoker files are REVERSE chronological — reverse for correct timeline
        th_chrono = list(reversed(th))
        stacks = [h.get('stack_bb', 0) for h in th_chrono]
        start, peak, low, final = stacks[0], max(stacks), min(stacks), stacks[-1]
        low_idx = stacks.index(low)
        rec = max(stacks[low_idx:]) if low_idx < len(stacks)-1 else low
        
        # Per-tournament card quality
        t_prem = sum(1 for h in th_chrono if normalize_hand(h.get('cards',[])) in PREMIUMS)
        t_strong = sum(1 for h in th_chrono if normalize_hand(h.get('cards',[])) in STRONG)
        t_n = len(th_chrono)
        
        # Per-tournament EAI (from session eai_list)
        t_eai_ids = {h['id'] for h in th_chrono}
        t_eai = [e for e in eai_list if e['id'] in t_eai_ids]
        t_eai_won = sum(1 for e in t_eai if e['won'])
        t_eai_exp = sum(0.8 if e['category']=='ahead' else 0.55 if e['category']=='flip' else 0.2 for e in t_eai)
        
        # <8BB missed pushes in this tournament
        t_push_misses = sum(1 for m in mistakes if m.get('tournament','')[:45] == tname[:45] 
                            and 'Push <8BB' in m.get('type',''))
        
        deep_runs.append({'tournament': tname[:55], 'hands': t_n, 'start': round(start),
                          'peak': round(peak), 'low': round(low), 'final': round(final),
                          'recovery_peak': round(rec),
                          'survival': low < start*0.3 and rec > low*2,
                          'premiums_pct': round(t_prem/t_n*100, 1),
                          'prem_strong_pct': round((t_prem+t_strong)/t_n*100, 1),
                          'eai_total': len(t_eai), 'eai_won': t_eai_won,
                          'eai_expected': round(t_eai_exp, 1),
                          'push_misses_lt8bb': t_push_misses})
    s['deep_runs'] = deep_runs

    # --- ONE-AND-DONE DETAILS ---
    s['one_and_done_hands'] = [{'id': h['id'], 'cards': normalize_hand(h.get('cards',[])),
                                'pos': h['position'], 'board': ' '.join(h.get('board',[]))}
                               for h in hands if h.get('one_and_done')][:15]

    # --- MISSED RIVER VALUE OPPORTUNITIES ---
    mrv = [{'id': h['id'], 'cards': normalize_hand(h.get('cards',[])), 'pos': h['position'],
            'board': ' '.join(h.get('board',[])), 'hand_strength': h.get('hand_strength',''),
            'streets_bet': sum(1 for b in h.get('hero_bets',[]) if b[0] in ('flop','turn')),
            'tournament': h.get('tournament','')[:40],
            'action_summary': h.get('action_summary', '')}
           for h in hands if h.get('missed_river_value')
           and is_legal_postflop_opportunity(h, 'river')]   # v8.19.0 Chapter D river gate
    s['missed_river_value'] = {'count': len(mrv), 'hands': mrv}

    # --- MISSED PROBE OPPORTUNITIES ---
    mp = [{'id': h['id'], 'cards': normalize_hand(h.get('cards',[])), 'pos': h['position'],
           'board': ' '.join(h.get('board',[])), 'hand_strength': h.get('hand_strength',''),
           'draw_type': h.get('draw_type',''), 'tournament': h.get('tournament','')[:40]}
          for h in hands if h.get('missed_probe')
          and is_legal_postflop_opportunity(h, 'turn')]   # v8.19.0 Chapter D turn gate
    s['missed_probes'] = {'count': len(mp), 'hands': mp}

    # --- HAND STRENGTH DISTRIBUTION (at showdown) ---
    hs_dist = defaultdict(int)
    for h in hands:
        if h.get('went_to_sd') and len(h.get('board',[])) >= 5:
            hs_dist[h.get('hand_strength', 'unknown')] += 1
    s['hand_strength_dist'] = dict(hs_dist)

    # --- SPR DISTRIBUTION ---
    spr_ranges = {'<1': 0, '1-3': 0, '3-6': 0, '6-10': 0, '10+': 0}
    for h in hands:
        spr = h.get('spr', 0)
        if spr <= 0: continue
        if spr < 1: spr_ranges['<1'] += 1
        elif spr < 3: spr_ranges['1-3'] += 1
        elif spr < 6: spr_ranges['3-6'] += 1
        elif spr < 10: spr_ranges['6-10'] += 1
        else: spr_ranges['10+'] += 1
    s['spr_distribution'] = spr_ranges

    # --- POSTFLOP AGGRESSION BY ROLE + DRAW TYPE + POSITION ---
    from itertools import product as iterproduct
    def _classify_draw_inline(cards, board_slice):
        if not cards or len(cards)<2 or not board_slice: return 'none'
        hs2=[c[1] for c in cards]; bs2=[c[1] for c in board_slice]
        sc2=defaultdict(int)
        for s2 in hs2+bs2: sc2[s2]+=1
        for s2 in hs2:
            if sc2.get(s2,0)==4: return 'nut_fd' if any(c[0]=='A' and c[1]==s2 for c in cards) else 'fd'
        if len(board_slice)==3:
            for s2 in hs2:
                if sc2.get(s2,0)==3:
                    av2=sorted(set(RANK_VAL.get(c[0],0) for c in list(cards)+list(board_slice)))
                    for ii in range(len(av2)-3):
                        if av2[ii+3]-av2[ii]==3: return 'oesd+bdfd'
                    for ii in range(len(av2)-3):
                        if av2[ii+3]-av2[ii]==4: return 'gutshot+bdfd'
                    return 'bdfd'
        av2=sorted(set(RANK_VAL.get(c[0],0) for c in list(cards)+list(board_slice)))
        for ii in range(len(av2)-3):
            if av2[ii+3]-av2[ii]==3: return 'oesd'
        for ii in range(len(av2)-3):
            if av2[ii+3]-av2[ii]==4: return 'gutshot'
        if board_slice:
            bm=max(RANK_VAL.get(c[0],0) for c in board_slice)
            if sum(1 for c in cards if RANK_VAL.get(c[0],0)>bm)>=2: return 'overcards'
        return 'none'

    aggression_tables = {}
    for role in ['PFR', 'Caller']:
        # v7.30 P0-3: exclude PF all-ins. After Hero is all-in preflop, the board runs
        # out but Hero can't bet flop/turn — counting these as "didn't bet" inflates
        # the denominator and produces artifact "0% / made-hand turn bet" findings.
        role_hands = [h for h in hands if (h['pfr'] if role=='PFR' else (h['vpip'] and not h['pfr']))
                      and len(h.get('board',[]))>=3 and not h.get('pf_allin')]
        for street, blen in [('Flop',3), ('Turn',4)]:
            sh = [h for h in role_hands if len(h.get('board',[]))>=blen]
            for ip_label in ['IP', 'OOP']:
                subset = [h for h in sh if h.get('hero_ip')==(ip_label=='IP')]
                if not subset: continue
                draw_data = defaultdict(lambda: {'total':0,'bet':0})
                for h in subset:
                    cards=h.get('cards',[]); bs=h.get('board',[])[:blen]
                    cat = 'made_hand' if is_made_hand(cards, bs) else _classify_draw_inline(cards, bs)
                    draw_data[cat]['total'] += 1
                    sn = 'flop' if blen==3 else 'turn'
                    if any(b[0]==sn for b in h.get('hero_bets',[])): draw_data[cat]['bet'] += 1
                key = f"{role}_{street}_{ip_label}"
                aggression_tables[key] = {k: {'total':v['total'],'bet':v['bet'],
                    'pct': pct(v['bet'],v['total'])} for k,v in draw_data.items()}
    s['aggression_tables'] = aggression_tables

    # Caller IP flop aggression (single number for primary metrics)
    # v7.22 fix: HU-only denominator. The 30-40% target is per Jaka K1/K3
    # which explicitly apply to HU flop play. MW caller has much lower
    # aggression target (~5-15%) and should be tracked separately.
    # EXCLUDE delayed cbets: Hero checked flop but bet turn = not truly passive
    cip_flop_all = [h for h in hands if h['vpip'] and not h['pfr'] and len(h.get('board',[]))>=3 and h.get('hero_ip') and not h.get('pf_allin')]
    cip_flop_hu = [h for h in cip_flop_all if h.get('players_at_flop', 0) == 2]
    cip_flop_mw = [h for h in cip_flop_all if h.get('players_at_flop', 0) >= 3]
    cip_flop_bet = sum(1 for h in cip_flop_hu if any(b[0]=='flop' for b in h.get('hero_bets',[])))
    cip_flop_mw_bet = sum(1 for h in cip_flop_mw if any(b[0]=='flop' for b in h.get('hero_bets',[])))
    cip_flop_delayed = sum(1 for h in cip_flop_hu
                           if not any(b[0]=='flop' for b in h.get('hero_bets',[]))
                           and any(b[0]=='turn' for b in h.get('hero_bets',[])))
    cip_truly_passive = len(cip_flop_hu) - cip_flop_bet - cip_flop_delayed
    # FEAT-D: collect caller-IP aggression hand IDs
    _cip_bet_ids = [h.get('id','') for h in cip_flop_hu
                    if any(b[0]=='flop' for b in h.get('hero_bets',[])) and h.get('id')]
    _cip_passive_ids = [h.get('id','') for h in cip_flop_hu
                        if not any(b[0]=='flop' for b in h.get('hero_bets',[])) and h.get('id')]
    s['core']['caller_ip_bet_ids'] = _cip_bet_ids[:20]
    s['core']['caller_ip_passive_ids'] = _cip_passive_ids[:20]
    # Primary metric — HU only (matches 30-40% target from Jaka K1/K3)
    s['core']['caller_ip_flop_agg'] = pct(cip_flop_bet, len(cip_flop_hu))
    s['core']['caller_ip_flop_n'] = len(cip_flop_hu)
    s['core']['caller_ip_delayed_cbet'] = cip_flop_delayed
    s['core']['caller_ip_truly_passive'] = cip_truly_passive
    # MW tracked separately (target ~5-15%)
    s['core']['caller_ip_flop_agg_mw'] = pct(cip_flop_mw_bet, len(cip_flop_mw))
    s['core']['caller_ip_flop_n_mw'] = len(cip_flop_mw)
    # Raw (all caller-IP, HU+MW blended) kept for backward compat
    cip_flop_bet_all = cip_flop_bet + cip_flop_mw_bet
    s['core']['caller_ip_flop_agg_raw'] = pct(cip_flop_bet_all, len(cip_flop_all))
    s['core']['caller_ip_flop_n_raw'] = len(cip_flop_all)

    # === APPENDIX K METRICS (v7.13 — Jaka Advanced Flop Play) ===
    # K3: IP Stab Rate — Hero IP caller, OOP PFR checked flop to Hero, Hero bet
    # K1: IP x/r Rate — Hero IP caller, villain bet first on flop, Hero raised
    # K6: Flop Lead Rate — Hero BB/SB caller, saw flop, Hero bet first on flop
    #
    # Uses existing hand-level fields:
    #   hero_ip, pfr, vpip, villain_bet_flop_first, hero_bets, position, players_at_flop

    def _board_kind(board3):
        """Classify flop for K4/K6 tracking. Returns string.
        Uses RANK_VAL where 2=0, 3=1, ..., 9=7, T=8, J=9, Q=10, K=11, A=12."""
        if not board3 or len(board3) < 3: return 'unknown'
        ranks = [c[0] for c in board3]
        suits = [c[1] for c in board3]
        vals = sorted([RANK_VAL.get(r, 0) for r in ranks], reverse=True)
        paired = len(set(ranks)) < 3
        monotone = len(set(suits)) == 1
        two_tone = len(set(suits)) == 2
        top = vals[0]  # 0=2, 12=A
        # Ace=12, King=11, Q=10, J=9, T=8, 9=7, 8=6, 7=5, 6=4, 5=3, 4=2, 3=1, 2=0
        # Connected-middling: top 5-J (vals 3-9), spread <=4, unpaired
        connected_mid = (not paired
                         and 3 <= top <= 9
                         and vals[0] - vals[2] <= 4)
        # Low straight boards per K6: 765, 643 type — top 8 or lower, spread 2-4
        low_straight = (not paired
                        and top <= 6  # 8 or lower
                        and vals[0] - vals[2] <= 4)
        # Low paired: paired + top <= 6 (8 or lower)
        low_paired = paired and top <= 6
        # High paired: paired + top >= 8 (T or higher)
        high_paired = paired and top >= 8
        # A-high dry: A + 2 disconnected low
        a_high = top == 12  # A
        a_high_dry = (a_high and not paired
                      and vals[1] <= 6  # second card 8 or lower
                      and vals[1] - vals[2] >= 2)
        # K-high
        k_high = top == 11
        # 2 high cards (broadways 9+): rank >=7 (9=7)
        two_high = sum(1 for v in vals if v >= 7) >= 2
        if monotone: return 'monotone'
        if low_paired: return 'low_paired'
        if high_paired: return 'high_paired'
        if paired: return 'mid_paired'
        if low_straight: return 'low_straight'
        if a_high_dry: return 'a_high_dry'
        if two_high: return 'two_high'
        if connected_mid: return 'connected_mid'
        if top <= 6: return 'low_dry'
        return 'other'

    def _position_matchup(hero_pos, n_players):
        """K2/K3: classify opener-vs-caller matchup as Gentleman/Warrior."""
        # Hero IP caller — villain is PFR from earlier position
        # Hero OOP PFR — villain is caller from later position
        # We can only infer villain position approximately from Hero pos + n_players
        # Simplified: use Hero's position class
        lp_positions = {'BTN', 'CO', 'HJ'}
        mp_positions = {'MP', 'UTG+1'}
        ep_positions = {'UTG'}
        if hero_pos in lp_positions: return 'LP'
        if hero_pos in mp_positions: return 'MP'
        if hero_pos in ep_positions: return 'EP'
        return 'BLIND'

    # --- K3: IP Stab Rate (when OOP PFR checks flop) ---
    # Denominator: Hero IP, caller (vpip but not pfr), saw flop, villain did NOT bet first
    # Numerator: Hero bet flop
    # Jaka's K3 target 40-60% is a HU concept; split HU / MW for clean comparison.
    k3_denom_all = [h for h in hands
                    if h.get('vpip') and not h.get('pfr')
                    and len(h.get('board', [])) >= 3
                    and h.get('hero_ip')
                    and not h.get('villain_bet_flop_first', False)
                    and not h.get('flop_allin', False)]
    k3_denom = [h for h in k3_denom_all if h.get('players_at_flop', 2) == 2]  # HU
    k3_denom_mw = [h for h in k3_denom_all if h.get('players_at_flop', 2) > 2]
    k3_bet = [h for h in k3_denom if any(b[0] == 'flop' for b in h.get('hero_bets', []))]
    k3_bet_mw = [h for h in k3_denom_mw if any(b[0] == 'flop' for b in h.get('hero_bets', []))]
    # Primary K3 metric = HU only (matches Jaka target 40-60%)
    s['core']['ip_stab_rate'] = pct(len(k3_bet), len(k3_denom))
    s['core']['ip_stab_n'] = len(k3_denom)
    s['core']['ip_stab_bet_n'] = len(k3_bet)
    # MW reported separately (target typically ~15-25%, not 40-60%)
    s['core']['ip_stab_rate_mw'] = pct(len(k3_bet_mw), len(k3_denom_mw))
    s['core']['ip_stab_n_mw'] = len(k3_denom_mw)
    s['core']['ip_stab_bet_n_mw'] = len(k3_bet_mw)

    # Split IP stab by board type (K3/K4 cross-ref)
    # FEAT-D: collect hand IDs for popup drill-down
    ip_stab_by_board = defaultdict(lambda: {'total': 0, 'bet': 0, 'bet_ids': [], 'miss_ids': []})
    for h in k3_denom:
        bk = _board_kind(h.get('board', [])[:3])
        ip_stab_by_board[bk]['total'] += 1
        if any(b[0] == 'flop' for b in h.get('hero_bets', [])):
            ip_stab_by_board[bk]['bet'] += 1
            ip_stab_by_board[bk]['bet_ids'].append(h.get('id', ''))
        else:
            ip_stab_by_board[bk]['miss_ids'].append(h.get('id', ''))
    s['ip_stab_by_board'] = {k: {'total': v['total'], 'bet': v['bet'],
                                  'pct': pct(v['bet'], v['total']),
                                  'bet_ids': v['bet_ids'][:20],
                                  'miss_ids': v['miss_ids'][:20]}
                              for k, v in ip_stab_by_board.items()}

    # Batch 4 (ACE-1): C-bet by board texture class — ALL c-bet opportunities
    # (not just IP stab). Tracks rate + hand IDs per texture for drill-down.
    _cbet_by_texture = defaultdict(lambda: {'opps': 0, 'cbet': 0, 'ids_cbet': [], 'ids_missed': []})
    for h in hands:
        # v8.5.9: gate on street initiative, not raw pfr
        _pt2 = h.get('pot_type', 'SRP')
        _has_init2 = (
            (_pt2 == 'SRP' and h.get('pfr')) or
            (_pt2 == '3BP' and h.get('hero_3bet')) or
            (_pt2 == '4BP' and (h.get('hero_4bet') or h.get('pfr')))
        )
        if not _has_init2:
            continue
        # v8.19.0 Chapter D (PHF-004): the centralized legal-opportunity gate. This counter
        # feeds ids_missed -> the "Missed c-bets on <texture>" popup; the old check was only
        # `board>=3`, so impossible spots (Hero all-in / flop jammed / no chips behind, e.g.
        # TM6090177176) wrongly entered both the denominator and the missed list. The gate
        # excludes them with a typed reason so denominator, misses and popup all agree.
        if not is_legal_cbet_opportunity(h):
            continue
        tex = h.get('board_texture') or 'unknown'
        _cbet_by_texture[tex]['opps'] += 1
        _did_cbet = (h.get('hero_cbet_flop') or h.get('cbet_flop_srp')
                     or h.get('cbet_flop_3bp') or h.get('cbet_flop_4bp'))
        if _did_cbet:
            _cbet_by_texture[tex]['cbet'] += 1
            _cbet_by_texture[tex]['ids_cbet'].append(h.get('id', ''))
        else:
            _cbet_by_texture[tex]['ids_missed'].append(h.get('id', ''))
    s['cbet_by_texture'] = {
        k: {'opps': v['opps'], 'cbet': v['cbet'],
            'pct': round(100 * v['cbet'] / v['opps'], 1) if v['opps'] else 0,
            'ids_cbet': v['ids_cbet'][:20],
            'ids_missed': v['ids_missed'][:20]}
        for k, v in _cbet_by_texture.items() if v['opps'] >= 3
    }

    # Float → Turn Attack rate: Hero called flop IP, OOP checked turn, Hero bet turn
    # Proxy: Hero is IP caller, called flop (didn't raise/fold), turn exists,
    # Hero bet turn. (We can't directly see if villain checked turn without more parsing,
    # but if Hero bet turn as IP caller after calling flop, that's the signal we want.)
    float_turn_denom = [h for h in hands
                        if h.get('vpip') and not h.get('pfr')
                        and h.get('hero_ip')
                        and len(h.get('board', [])) >= 4
                        and h.get('villain_bet_flop_first', False)  # faced c-bet
                        and any(fb[0] == 'flop' and fb[2] == 'call' for fb in h.get('facing_bets', []))]  # called it
    float_turn_bet = [h for h in float_turn_denom
                      if any(b[0] == 'turn' for b in h.get('hero_bets', []))]
    s['core']['float_turn_attack_rate'] = pct(len(float_turn_bet), len(float_turn_denom))
    s['core']['float_turn_attack_n'] = len(float_turn_denom)

    # --- K1: IP Caller x/r on Flop (raising a c-bet) ---
    # Denominator: Hero IP caller, villain bet first on flop, Hero acted
    # Numerator: Hero raised (check_raise on flop or direct raise)
    k1_denom = [h for h in hands
                if h.get('vpip') and not h.get('pfr')
                and len(h.get('board', [])) >= 3
                and h.get('hero_ip')
                and h.get('villain_bet_flop_first', False)
                and not h.get('flop_allin', False)]
    k1_raise = [h for h in k1_denom
                if any(b[0] == 'flop' and b[2] == 'raise' for b in h.get('hero_bets', []))]
    s['core']['ip_caller_xr_rate'] = pct(len(k1_raise), len(k1_denom))
    s['core']['ip_caller_xr_n'] = len(k1_denom)
    s['core']['ip_caller_xr_bet_n'] = len(k1_raise)

    # Split by depth: <30BB raises should exclude draws
    k1_shallow = [h for h in k1_raise if h.get('stack_bb', 100) < 30]
    k1_deep = [h for h in k1_raise if h.get('stack_bb', 100) >= 30]
    # Multiway: should be 0-5%
    k1_mw_denom = [h for h in k1_denom if h.get('players_at_flop', 2) >= 3]
    k1_mw_raise = [h for h in k1_raise if h.get('players_at_flop', 2) >= 3]
    s['core']['ip_caller_xr_mw_rate'] = pct(len(k1_mw_raise), len(k1_mw_denom))
    s['core']['ip_caller_xr_mw_n'] = len(k1_mw_denom)

    # --- K6: Flop Lead Rate (Hero OOP from blinds as caller) ---
    # Denominator: Hero in BB or SB, called preflop (vpip not pfr), saw flop, HU or MW
    # Numerator: Hero bet flop first (villain_bet_flop_first=False + hero bet flop)
    k6_denom = [h for h in hands
                if h.get('vpip') and not h.get('pfr')
                and h.get('position') in ('BB', 'SB')
                and len(h.get('board', [])) >= 3
                and not h.get('flop_allin', False)]
    k6_lead = [h for h in k6_denom
               if not h.get('villain_bet_flop_first', False)
               and any(b[0] == 'flop' for b in h.get('hero_bets', []))]
    s['core']['flop_lead_rate'] = pct(len(k6_lead), len(k6_denom))
    s['core']['flop_lead_n'] = len(k6_denom)
    s['core']['flop_lead_bet_n'] = len(k6_lead)

    # Split leads by board type — K6 acceptable boards vs not
    k6_acceptable_boards = {'low_paired', 'low_straight'}
    k6_acceptable_3bp = {'connected_mid'}  # 3BP mid-connected at 30BB-
    # FEAT-D: collect hand IDs for popup drill-down
    flop_lead_by_board = defaultdict(lambda: {'total': 0, 'lead': 0, 'lead_ids': []})
    for h in k6_denom:
        bk = _board_kind(h.get('board', [])[:3])
        flop_lead_by_board[bk]['total'] += 1
        if (not h.get('villain_bet_flop_first', False)
            and any(b[0] == 'flop' for b in h.get('hero_bets', []))):
            flop_lead_by_board[bk]['lead'] += 1
            flop_lead_by_board[bk]['lead_ids'].append(h.get('id', ''))
    s['flop_lead_by_board'] = {k: {'total': v['total'], 'lead': v['lead'],
                                    'pct': pct(v['lead'], v['total']),
                                    'lead_ids': v['lead_ids'][:20]}
                                for k, v in flop_lead_by_board.items()}
    s['core']['flop_lead_acceptable_boards'] = sorted(k6_acceptable_boards)

    # --- K4: HU SRP C-Bet by Position vs SB Defend ---
    # Denominator: Hero PFR, HU flop, SB defended (villain is SB)
    # Note: we can approximate "villain is SB" by: only 1 villain saw flop AND
    # Hero opened from not-SB AND the only villain is SB. Without explicit villain
    # position tracking, we use: PFR from CO/BTN/MP + 2 players at flop + no BB
    # defending flag. This is an approximation.
    # For cleaner K4 tracking, we track HU SRP c-bets split by Hero position + depth.
    k4_hu_srp = [h for h in hands
                 if h.get('pfr')
                 and h.get('pot_type', 'SRP') == 'SRP'
                 and h.get('players_at_flop', 0) == 2
                 and len(h.get('board', [])) >= 3
                 and h.get('position') in ('MP', 'CO', 'BTN')]
    k4_by_pos_depth = defaultdict(lambda: {'total': 0, 'bet': 0})
    for h in k4_hu_srp:
        pos = h.get('position')
        sb = h.get('stack_bb', 100)
        depth = '60BB+' if sb >= 45 else '30-45BB' if sb >= 25 else '<25BB'
        key = f"{pos}_{depth}"
        k4_by_pos_depth[key]['total'] += 1
        if any(b[0] == 'flop' for b in h.get('hero_bets', [])):
            k4_by_pos_depth[key]['bet'] += 1
    s['k4_srp_cbet_by_pos_depth'] = {k: {'total': v['total'], 'bet': v['bet'],
                                          'pct': pct(v['bet'], v['total'])}
                                      for k, v in k4_by_pos_depth.items()}

    # K4 target lookup for report
    s['k4_targets'] = {
        'MP_60BB+': 70, 'MP_30-45BB': 70, 'MP_<25BB': 75,
        'CO_60BB+': 56, 'CO_30-45BB': 61, 'CO_<25BB': 65,
        'BTN_60BB+': 48, 'BTN_30-45BB': 53, 'BTN_<25BB': 55,
    }

    # --- K2: Gentlemen/Warriors classification for OOP PFR c-bets ---
    # Classify each HU SRP postflop spot by opener-vs-caller position
    # Hero OOP as PFR → opener is Hero, caller is villain
    # Hero IP as caller → caller is Hero, opener is villain
    k2_oop_pfr = [h for h in hands
                  if h.get('pfr') and not h.get('hero_ip')
                  and h.get('pot_type', 'SRP') == 'SRP'
                  and h.get('players_at_flop', 0) == 2
                  and len(h.get('board', [])) >= 3]
    k2_matchup = defaultdict(lambda: {'total': 0, 'bet': 0})
    for h in k2_oop_pfr:
        hp = _position_matchup(h.get('position'), h.get('n_players', 8))
        # Opener = Hero (OOP). Caller = villain from LP.
        # Matchup naming: "OOP_pos vs LP" simplified to Hero's position class
        matchup = 'Warrior' if hp in ('EP', 'MP') else 'Gentleman'  # EP/MP vs LP = Warrior; LP vs LP = Gentleman
        # BLIND-pos hero as PFR is BvB or similar — separate bucket
        if hp == 'BLIND': matchup = 'BvB'
        k2_matchup[matchup]['total'] += 1
        if any(b[0] == 'flop' for b in h.get('hero_bets', [])):
            k2_matchup[matchup]['bet'] += 1
    s['k2_oop_pfr_matchup'] = {k: {'total': v['total'], 'bet': v['bet'],
                                    'pct': pct(v['bet'], v['total'])}
                                for k, v in k2_matchup.items()}

    # === END APPENDIX K METRICS ===

    # === DRILL-DERIVED METRICS (v7.13) ===
    # From 20K-hand aggregate analysis + drill sessions.
    # Order: Aggressor vs Reactor > Draw Overbet Jam > Passive-Passive-Jam
    #        > Triple Barrel Response > Sizing Consistency
    #
    # Uses existing hand fields: hero_bets, facing_bets, check_raises,
    # hero_street_actions (reconstructed below), stack_bb, net_bb, vpip,
    # flop_allin, hand_strength, draw_type, cards, board

    # --- 1. AGGRESSOR vs REACTOR P&L (highest priority) ---
    # Aggressor: Hero bet/raised/check-raised on at least one postflop street
    # Reactor: Hero only called/checked on every postflop street
    agg_react_pool = [h for h in hands
                      if h.get('vpip') and len(h.get('board', [])) >= 3
                      and not h.get('pf_allin', False)]

    def _is_aggressor(h):
        # Any hero bet (spot cbet/barrel/probe/raise) = aggressor
        if h.get('hero_bets'): return True
        if h.get('check_raises'): return True
        return False

    aggressor_hands = [h for h in agg_react_pool if _is_aggressor(h)]
    reactor_hands = [h for h in agg_react_pool if not _is_aggressor(h)]
    agg_net = sum(h.get('net_bb', 0) for h in aggressor_hands)
    react_net = sum(h.get('net_bb', 0) for h in reactor_hands)
    agg_bbph = round(agg_net / len(aggressor_hands), 2) if aggressor_hands else 0
    react_bbph = round(react_net / len(reactor_hands), 2) if reactor_hands else 0
    s['aggressor_vs_reactor'] = {
        'aggressor_n': len(aggressor_hands),
        'aggressor_net_bb': round(agg_net, 1),
        'aggressor_bb_per_hand': agg_bbph,
        'reactor_n': len(reactor_hands),
        'reactor_net_bb': round(react_net, 1),
        'reactor_bb_per_hand': react_bbph,
        'delta_bb_per_hand': round(agg_bbph - react_bbph, 2),
        'target': 'Aggressor BB/hand should be >3x Reactor BB/hand (20K sample: Agg +4.8 vs Reactor -1.2)',
    }
    s['core']['agg_react_delta'] = round(agg_bbph - react_bbph, 2)

    # --- 2. DRAW OVERBET JAM FLAG ---
    # Hero jams >200% pot on flop/turn while holding draw/air with >=15BB effective
    draw_overbet_jams = []
    for h in hands:
        if h.get('stack_bb', 100) < 15: continue
        if not h.get('hero_bets'): continue
        cards = h.get('cards', [])
        for street, size_pct, spot, ippos in h.get('hero_bets', []):
            if street not in ('flop', 'turn'): continue
            if size_pct < 200: continue
            # Must be approximately a jam — check if it's a large overbet
            # (all-in detected via hand being flop_allin or turn_allin)
            board_slice = h.get('board', [])[:3 if street == 'flop' else 4]
            if not board_slice or len(board_slice) < 3: continue
            # Check hand strength at that point
            hs = h.get('hand_strength', 'unknown')
            # Made hand classification
            if is_made_hand(cards, board_slice):
                continue  # Not a draw/air jam
            draw_overbet_jams.append({
                'id': h.get('id'),
                'cards': normalize_hand(cards),
                'pos': h.get('position'),
                'stack_bb': round(h.get('stack_bb', 0), 1),
                'street': street,
                'size_pct': size_pct,
                'spot': spot,
                'net_bb': round(h.get('net_bb', 0), 1),
                'tournament': h.get('tournament', '')[:40],
            })
            break  # one flag per hand max
    s['draw_overbet_jams'] = {
        'count': len(draw_overbet_jams),
        'net_bb': round(sum(d['net_bb'] for d in draw_overbet_jams), 1),
        'hands': draw_overbet_jams,
        'target': 'These hands should use geometric sizing across streets, not single-street jams (<15BB excluded — jam standard at short depth)',
    }

    # --- 3. PASSIVE-PASSIVE-JAM DETECTION ---
    # Flop call + Turn call + River jam/raise
    passive_passive_jams = []
    for h in hands:
        if len(h.get('board', [])) < 5: continue  # needs all 5 cards
        facing = h.get('facing_bets', [])
        # Must have called flop
        flop_call = any(fb[0] == 'flop' and fb[2] == 'call' for fb in facing)
        turn_call = any(fb[0] == 'turn' and fb[2] == 'call' for fb in facing)
        if not (flop_call and turn_call): continue
        # Hero raised/jammed river
        river_raise = any(b[0] == 'river' and b[2] == 'raise' for b in h.get('hero_bets', []))
        # Or: river bet after no bets prior streets (unlikely given call flop/turn but still)
        river_bet_after_calls = any(b[0] == 'river' and b[2] in ('value_bet', 'bluff', 'probe', 'barrel')
                                    for b in h.get('hero_bets', []))
        if not (river_raise or river_bet_after_calls): continue
        # Check it's a big bet (>75% pot) — otherwise it's a block/value bet, not a jam
        river_size = max([b[1] for b in h.get('hero_bets', []) if b[0] == 'river'], default=0)
        if river_size < 75: continue
        won = h.get('won', False)
        passive_passive_jams.append({
            'id': h.get('id'),
            'cards': normalize_hand(h.get('cards', [])),
            'pos': h.get('position'),
            'stack_bb': round(h.get('stack_bb', 0), 1),
            'river_size_pct': river_size,
            'won': won,
            'net_bb': round(h.get('net_bb', 0), 1),
            'tournament': h.get('tournament', '')[:40],
        })
    won_ct = sum(1 for d in passive_passive_jams if d['won'])
    s['passive_passive_jam'] = {
        'count': len(passive_passive_jams),
        'won': won_ct,
        'win_rate': pct(won_ct, len(passive_passive_jams)),
        'net_bb': round(sum(d['net_bb'] for d in passive_passive_jams), 1),
        'hands': passive_passive_jams,
        'note': 'Call flop + Call turn + Jam/Raise river >75% pot. Anti-pattern: lets villain define their range then shove into it.',
    }

    # --- 4. TRIPLE BARREL RESPONSE ---
    # Villain bet on flop, turn, AND river; track Hero's river action
    tb_faced_all = []
    for h in hands:
        if len(h.get('board', [])) < 5: continue
        facing = h.get('facing_bets', [])
        flop_bet = any(fb[0] == 'flop' for fb in facing)
        turn_bet = any(fb[0] == 'turn' for fb in facing)
        river_bet = any(fb[0] == 'river' for fb in facing)
        if not (flop_bet and turn_bet and river_bet): continue
        river_action = next((fb[2] for fb in facing if fb[0] == 'river'), None)
        # Raise = hero raised the river bet
        hero_river_raise = any(b[0] == 'river' and b[2] == 'raise' for b in h.get('hero_bets', []))
        if hero_river_raise: final = 'raise'
        elif river_action == 'call': final = 'call'
        elif river_action == 'fold': final = 'fold'
        else: final = 'other'
        tb_faced_all.append({
            'id': h.get('id'),
            'cards': normalize_hand(h.get('cards', [])),
            'final': final,
            'won': h.get('won', False),
            'net_bb': round(h.get('net_bb', 0), 1),
        })
    tb_called = [t for t in tb_faced_all if t['final'] == 'call']
    tb_folded = [t for t in tb_faced_all if t['final'] == 'fold']
    tb_raised = [t for t in tb_faced_all if t['final'] == 'raise']
    tb_called_won = sum(1 for t in tb_called if t['won'])
    tb_raised_won = sum(1 for t in tb_raised if t['won'])
    s['triple_barrel_response'] = {
        'total': len(tb_faced_all),
        'called': {
            'count': len(tb_called),
            'won': tb_called_won,
            'win_rate': pct(tb_called_won, len(tb_called)),
            'net_bb': round(sum(t['net_bb'] for t in tb_called), 1),
            'avg_bb': round(sum(t['net_bb'] for t in tb_called) / len(tb_called), 2) if tb_called else 0,
            'flag_if_wr_below_45': pct(tb_called_won, len(tb_called)) < 45 and len(tb_called) >= 5,
        },
        'folded': {
            'count': len(tb_folded),
            'net_bb': round(sum(t['net_bb'] for t in tb_folded), 1),
            'note': 'Cost of flop+turn calls before folding river. Often correct per population under-bluffs rivers (Population tends to under-bluff rivers, so folding is often right (J19)).',
        },
        'raised': {
            'count': len(tb_raised),
            'won': tb_raised_won,
            'win_rate': pct(tb_raised_won, len(tb_raised)),
            'net_bb': round(sum(t['net_bb'] for t in tb_raised), 1),
        },
        'target': 'Called-all-3 win rate should be >=45%. Below that = calling too wide after committing 2 streets.',
    }

    # --- 5. SIZING CONSISTENCY SCORE ---
    # For hands where Hero bet on 2+ streets, classify pattern as geometric vs erratic
    # v7.33 Bug #9 fix: exempt two GTO-correct patterns that look erratic:
    # (1) Skipped-street barrel (e.g. cbet flop → check turn → polar river)
    #     The check between bet streets means it's not a "consecutive sizing"
    #     pattern at all — it's delayed-barrel + value-blocker pattern.
    # (2) River card completes a draw Hero had on the flop (FD or SD).
    #     Then the polar river overbet is GTO-aligned for value, not erratic.
    # Example fixed: TM5919499304 A5d on K-J-7tt → cbet 25% (nut FD) → x turn →
    # river 6d completes nut flush → 132% overbet. Both bets correct for context.
    geometric_hands = []
    erratic_hands = []
    small_small_jam_hands = []
    for h in hands:
        bets = [(b[0], b[1]) for b in h.get('hero_bets', []) if b[0] in ('flop', 'turn', 'river')]
        if len(bets) < 2: continue
        # Deduplicate — only first bet per street
        by_street = {}
        for st, sz in bets:
            if st not in by_street:
                by_street[st] = sz
        ordered_streets = [s_ for s_ in ('flop', 'turn', 'river') if s_ in by_street]
        if len(ordered_streets) < 2: continue
        sizes = [by_street[s_] for s_ in ordered_streets]
        # v7.33 Bug #9 — check exception (1): non-consecutive streets
        # If Hero bet flop and bet river but didn't bet turn, the in-between check
        # makes the consecutive-ratio test inappropriate. Skip erratic check.
        bet_streets_set = set(ordered_streets)
        has_skipped_street = (
            ('flop' in bet_streets_set and 'river' in bet_streets_set
             and 'turn' not in bet_streets_set)
            or ('flop' in bet_streets_set and 'turn' in bet_streets_set
                and 'river' in bet_streets_set
                and any(b[0] == 'turn' and b[2] == 'check' for b in h.get('hero_bets',[])))
        )
        # v7.33 Bug #9 — check exception (2): river draw completion
        # If the river card completes a draw Hero had on the flop, a polar river
        # overbet is GTO-aligned for value (Hero now has the nuts/strong hand).
        river_completed_draw = False
        cards = h.get('cards', [])
        board = h.get('board', [])
        if (len(board) == 5 and len(cards) == 2
            and 'river' in by_street and by_street['river'] >= 90):
            # Hero had FD on flop (3 same suit) and river is the 4th of suit?
            hero_suits = [c[1] for c in cards]
            board_suits = [c[1] for c in board]
            for s_ in set(hero_suits):
                if hero_suits.count(s_) == 2 and board_suits[:3].count(s_) == 1:
                    # FD on flop. Check if river completes 4-of-suit (with ≥4 same on board+hero)
                    total_of_suit = board_suits.count(s_) + hero_suits.count(s_)
                    if total_of_suit >= 5 and board_suits[4] == s_:
                        river_completed_draw = True
                        break
            # Could add OESD detection too but FD is the main case.
        # Geometric sizing (pot-as-percentage) grows each street because pot doubles after
        # bet+call. A bet of 60-80% pot every street creates a 1.5-2.5x ratio between
        # consecutive size percentages. Real anti-pattern = *shrinking* sizes (gave up)
        # or jump from small→overbet (punt signal). Accepted ratio band: 0.80-3.00.
        # Below 0.80 = shrinking street (gave up on value/turned bluff). Above 3.00 = erratic jump.
        is_geometric = True
        for i in range(1, len(sizes)):
            prev, cur = sizes[i-1], sizes[i]
            if prev == 0: continue
            ratio = cur / prev
            if not (0.80 <= ratio <= 3.00):
                is_geometric = False
                break
        # Apply v7.33 exceptions: don't flag erratic if either exception triggered
        if not is_geometric and (has_skipped_street or river_completed_draw):
            is_geometric = True
        record = {
            'id': h.get('id'),
            'cards': normalize_hand(h.get('cards', [])),
            'streets': list(zip(ordered_streets, sizes)),
            'net_bb': round(h.get('net_bb', 0), 1),
        }
        if is_geometric:
            geometric_hands.append(record)
        else:
            erratic_hands.append(record)
            # Specific anti-pattern: small -> small -> JAM (each prior <60% and last >=200%)
            if (len(sizes) >= 2 and sizes[-1] >= 200
                and all(sz < 60 for sz in sizes[:-1])):
                small_small_jam_hands.append(record)
    s['sizing_consistency'] = {
        'geometric': len(geometric_hands),
        'erratic': len(erratic_hands),
        'total': len(geometric_hands) + len(erratic_hands),
        'geometric_pct': pct(len(geometric_hands), len(geometric_hands) + len(erratic_hands)),
        'small_small_jam_count': len(small_small_jam_hands),
        'small_small_jam_hands': small_small_jam_hands,
        'erratic_hands': erratic_hands[:15],
        'target': 'Geometric compliance target 70%+. Small→Small→JAM is the specific anti-pattern to eliminate.',
    }

    # === END DRILL-DERIVED METRICS ===

    # --- TABLE SIZE MIX (v7.2) ---
    ts_counts = defaultdict(int)
    for h in hands: ts_counts[h.get('table_size', 8)] += 1
    s['table_size_mix'] = dict(ts_counts)

    # --- SB BvB PREFLOP STRATEGY (v7.2 — J29) ---
    # When it folds to SB in BvB at 25-40 BB depth: limp 80%, raise 10%, fold 10%
    # v7.30 P1-1: filter by stack depth — J29 specifically targets 25-40 BB. Lumping
    # all depths together produces misleading aggregates (deeper stacks have a
    # different framework, sub-25 BB is jam-or-fold).
    sb_bvb_hands_all = [h for h in hands if h['position'] == 'SB' and h.get('first_in')
                        and h.get('n_players', 8) >= 2]
    sb_bvb_hands = [h for h in sb_bvb_hands_all if 25 <= h.get('stack_bb', 0) <= 40]
    sb_bvb_limp = sum(1 for h in sb_bvb_hands if h['vpip'] and not h['pfr'])
    sb_bvb_raise = sum(1 for h in sb_bvb_hands if h['pfr'])
    sb_bvb_fold = sum(1 for h in sb_bvb_hands if not h['vpip'])
    sb_bvb_total = len(sb_bvb_hands)
    s['sb_bvb_preflop'] = {
        'total': sb_bvb_total,
        'limp': sb_bvb_limp, 'limp_pct': pct(sb_bvb_limp, sb_bvb_total),
        'raise': sb_bvb_raise, 'raise_pct': pct(sb_bvb_raise, sb_bvb_total),
        'fold': sb_bvb_fold, 'fold_pct': pct(sb_bvb_fold, sb_bvb_total),
        'target': 'Limp ~80%, Raise ~10%, Fold ~10% at 25-40BB (J29)',
        'depth_bracket': '25-40 BB',
        'all_depths_total': len(sb_bvb_hands_all),  # how many SB-BvB at any depth (for context)
    }

    # --- VPIP-PFR GAP ADJUSTED (exclude SB BvB limps — J29 limp range inflates gap) ---
    sb_bvb_vpip = sb_bvb_limp + sb_bvb_raise  # all BvB vpip hands
    ex_bvb_n = N - sb_bvb_total
    if ex_bvb_n > 0:
        ex_bvb_vpip = vpip_ct - sb_bvb_vpip
        ex_bvb_pfr = pfr_ct - sb_bvb_raise
        s['core']['vpip_pfr_gap_ex_bvb'] = round(pct(ex_bvb_vpip, ex_bvb_n) - pct(ex_bvb_pfr, ex_bvb_n), 1)
    else:
        s['core']['vpip_pfr_gap_ex_bvb'] = s['core']['vpip_pfr_gap']

    # --- BB 3-BET SIZING (v7.2 — J30; refactored v7.25 to use hero_3bet_size_x) ---
    bb_3bet_hands = [h for h in hands if h['position'] == 'BB' and h.get('hero_3bet')]
    bb_3bet_sizes = []
    bb_3bet_size_values = []  # for mean computation
    for h in bb_3bet_hands:
        size_x = h.get('hero_3bet_size_x')
        if size_x is not None:
            bb_3bet_size_values.append(size_x)
        bb_3bet_sizes.append({
            'id': h['id'], 'cards': normalize_hand(h.get('cards', [])),
            'stack_bb': round(h.get('stack_bb', 0)),
            'size_x': size_x,
            'undersized': (size_x is not None and size_x < 4.0),
            'action_summary': h.get('action_summary', '')
        })
    bb_mean_size = round(sum(bb_3bet_size_values) / len(bb_3bet_size_values), 2) if bb_3bet_size_values else None
    bb_undersized_count = sum(1 for h in bb_3bet_sizes if h['undersized'])
    s['bb_3bet_sizing'] = {
        'count': len(bb_3bet_hands),
        'hands': bb_3bet_sizes,
        'mean_size_x': bb_mean_size,
        'undersized_count': bb_undersized_count,
        'target': '5x from BB (J30)',
        'flag_threshold': '<4x = undersized'
    }

    # --- IP 3-BET SIZING by depth (v7.25 — J44) ---
    # Buckets Hero's IP 3-bets by position (CO/BTN/HJ) and stack depth bucket.
    # Targets per Dave (J44):
    #   <25BB:    2.5x the open
    #   25-40BB:  3.0x the open (linear scale)
    #   >40BB:    3.5x the open
    # Flag |actual - target| > 0.5x as deviation.
    IP_POSITIONS = {'CO', 'BTN', 'HJ'}
    DEPTH_TARGETS = [
        ('<25BB',    lambda s: s < 25,                  2.5),
        ('25-40BB',  lambda s: 25 <= s <= 40,            3.0),
        ('40+BB',    lambda s: s > 40,                   3.5),
    ]
    ip_3bet_buckets = {label: {'count': 0, 'sizes': [], 'mean_size_x': None,
                                'target': tgt, 'deviations': [], 'hands': []}
                        for label, _, tgt in DEPTH_TARGETS}
    ip_3bet_total = 0
    ip_3bet_deviation_count = 0
    for h in hands:
        if not h.get('hero_3bet'):
            continue
        if h.get('position') not in IP_POSITIONS:
            continue
        # v7.30 P1-2: skip PF all-ins. At low stacks, the "3-bet" is a jam — not a
        # sizing decision. Including jams produces absurd ratios (e.g. AA BTN 16BB
        # shove → 7.92x; KJs CO 21BB shove → 10.52x) that are flagged as
        # "wide deviations" but aren't sizing leaks at all.
        if h.get('pf_allin'):
            continue
        size_x = h.get('hero_3bet_size_x')
        if size_x is None:
            continue
        stack_bb = h.get('stack_bb', 0)
        # Find depth bucket
        bucket_label = None
        bucket_target = None
        for label, predicate, tgt in DEPTH_TARGETS:
            if predicate(stack_bb):
                bucket_label = label
                bucket_target = tgt
                break
        if bucket_label is None:
            continue
        bkt = ip_3bet_buckets[bucket_label]
        bkt['count'] += 1
        bkt['sizes'].append(size_x)
        ip_3bet_total += 1
        deviation = abs(size_x - bucket_target)
        is_deviation = deviation > 0.5
        hand_record = {
            'id': h['id'], 'cards': normalize_hand(h.get('cards', [])),
            'position': h['position'],
            'stack_bb': round(stack_bb, 1),
            'size_x': size_x,
            'target_x': bucket_target,
            'deviation': round(deviation, 2),
            'flagged': is_deviation,
            'action_summary': h.get('action_summary', '')
        }
        bkt['hands'].append(hand_record)
        if is_deviation:
            ip_3bet_deviation_count += 1
            bkt['deviations'].append(hand_record)
    # Compute mean per bucket
    for label, bkt in ip_3bet_buckets.items():
        if bkt['sizes']:
            bkt['mean_size_x'] = round(sum(bkt['sizes']) / len(bkt['sizes']), 2)
        # Don't dump the raw sizes list to JSON (kept hands list instead)
        del bkt['sizes']
    s['ip_3bet_sizing'] = {
        'total_count': ip_3bet_total,
        'deviation_count': ip_3bet_deviation_count,
        'deviation_rate_pct': round(100 * ip_3bet_deviation_count / ip_3bet_total, 1) if ip_3bet_total else 0,
        'buckets': ip_3bet_buckets,
        'targets': '<25BB: 2.5x | 25-40BB: 3.0x | 40+BB: 3.5x (J44)',
        'flag_threshold': '|actual - target| > 0.5x'
    }

    # --- LINE ANALYSIS (v8) ---
    # B-V10 FEATURE (2026-06-01): collect top-3 best and worst hands per line
    # so the P&L Lines table can link to drill-down hand lists.
    import heapq
    line_stats = defaultdict(lambda: {'count': 0, 'net_bb': 0, 'hands': [],
                                       '_all_hands': []})
    for h in hands:
        line = h.get('line', 'unknown')
        if line in ('fold_preflop', 'unknown'): continue
        line_stats[line]['count'] += 1
        line_stats[line]['net_bb'] += h.get('net_bb', 0)
        line_stats[line]['_all_hands'].append((h.get('net_bb', 0), h['id']))
        if len(line_stats[line]['hands']) < 3:
            line_stats[line]['hands'].append(h['id'])
    # Compute top-3 best and worst per line
    for _ls in line_stats.values():
        _ah = _ls.pop('_all_hands')
        # B-V10: collect top 10 (not 3) so popups have at least 5 examples
        # after the JS filters out hands without appendix cards
        _ls['top3_best'] = [hid for _, hid in heapq.nlargest(10, _ah)]
        _ls['top3_worst'] = [hid for _, hid in heapq.nsmallest(10, _ah)]

    # Top losing lines sorted by total net BB
    sorted_lines = sorted(line_stats.items(), key=lambda x: x[1]['net_bb'])
    top_losing = []
    for line_name, ld in sorted_lines[:15]:
        avg = ld['net_bb'] / ld['count'] if ld['count'] > 0 else 0
        confidence = 'HIGH' if ld['count'] >= 100 else 'MED' if ld['count'] >= 30 else 'LOW'
        top_losing.append({
            'line': line_name, 'count': ld['count'], 'net_bb': round(ld['net_bb'], 1),
            'avg_bb': round(avg, 2), 'confidence': confidence, 'example_ids': ld['hands'],
            'top3_best': ld.get('top3_best', []),
            'top3_worst': ld.get('top3_worst', []),
        })
    s['top_losing_lines'] = top_losing

    # Top winning lines
    top_winning = []
    for line_name, ld in sorted_lines[-10:]:
        avg = ld['net_bb'] / ld['count'] if ld['count'] > 0 else 0
        top_winning.append({
            'line': line_name, 'count': ld['count'], 'net_bb': round(ld['net_bb'], 1),
            'avg_bb': round(avg, 2),
            'top3_best': ld.get('top3_best', []),
            'top3_worst': ld.get('top3_worst', []),
        })
    s['top_winning_lines'] = list(reversed(top_winning))

    # Line summary stats
    s['line_summary'] = {
        'unique_lines': len(line_stats),
        'vpip_hands_with_lines': sum(ld['count'] for ld in line_stats.values()),
    }

    # --- PREFLOP DEVIATION LOG (v7.2 — full range check) ---
    pf_devs = check_preflop_deviations(hands, ranges or {})
    s['preflop_deviations'] = pf_devs
    # B150 (Ron 2026-05-23): stash the actual chart contents for every chart a
    # deviation references, so the report can SHOW the correct range beside
    # each "Wide …" / "Missed …" flag. Only referenced charts are stored, so
    # the session payload stays small (157 charts loaded → typically ~10-20
    # actually referenced). The renderer cannot re-load these reliably itself
    # (gem_ranges.load_ranges yields different chart names), so the chart that
    # actually produced the flag must travel with the deviation.
    _dev_chart_names = {d.get('chart') for d in pf_devs if d.get('chart')}
    s['_dev_charts'] = {cn: sorted((ranges or {}).get(cn, []))
                        for cn in _dev_chart_names if cn in (ranges or {})}
    # v7.39 — B32: surface the chart sanity report so the renderer can show
    # which charts were augmented and warn the user. Pulled from the analyzer's
    # module-level singleton populated in __main__.
    s['range_sanity_report'] = dict(_RANGE_SANITY_REPORT) if _RANGE_SANITY_REPORT else {}
    # ============================================================
    # AMIT COACHING RULES (June 2, 2026)
    # ============================================================
    _coaching_flags = []

    # RULE 1: MW pot sizing too small — Hero c-bets <50% pot in multiway
    # with a strong hand. "They're going to pay bigger bets, bloat the pot."
    for h in hands:
        if not h.get('multiway_flop') or not h.get('pfr'):
            continue
        for _st, _sz, _spot, _ip in (h.get('hero_bets') or []):
            if _spot == 'cbet' and _st == 'flop' and _sz and _sz < 50:
                # Check if Hero had a strong hand (top pair+)
                _cards = h.get('cards', [])
                _board = h.get('board', [])
                if _cards and _board and len(_board) >= 3:
                    try:
                        cat = classify_hand_for_betting(_cards, _board[:3], 'flop', sizing_pct=_sz)
                        if cat == 'value':
                            _coaching_flags.append({
                                'id': h.get('id'), 'rule': 'MW_SMALL_SIZING',
                                'detail': f'MW c-bet {_sz:.0f}% pot with value hand — '
                                          f'consider bigger sizing to bloat pot',
                            })
                    except Exception:
                        pass

    # RULE 2: Flop cbet size → turn barrel correlation
    # Track: big flop cbet (>66%) → did Hero barrel turn? vs small (<40%)
    _big_cbet_barrel = {'big_cbet': 0, 'big_barrel': 0,
                        'small_cbet': 0, 'small_barrel': 0}
    for h in hands:
        if not h.get('pfr'):
            continue
        _bets = h.get('hero_bets') or []
        _flop_sz = None
        _turn_bet = False
        for _st, _sz, _spot, _ip in _bets:
            if _st == 'flop' and _spot == 'cbet':
                _flop_sz = _sz
            if _st == 'turn' and _spot in ('cbet', 'bet'):
                _turn_bet = True
        if _flop_sz is not None:
            if _flop_sz >= 66:
                _big_cbet_barrel['big_cbet'] += 1
                if _turn_bet:
                    _big_cbet_barrel['big_barrel'] += 1
            elif _flop_sz <= 40:
                _big_cbet_barrel['small_cbet'] += 1
                if _turn_bet:
                    _big_cbet_barrel['small_barrel'] += 1
    s['coaching_cbet_barrel_correlation'] = _big_cbet_barrel

    # RULE 3: Check-call OOP when should bet (fold equity + low XR freq)
    # Flag: Hero check-called OOP on flop when Hero had a playable hand
    # and the population XR frequency is low (<10%)
    for h in hands:
        _hsa = h.get('hero_street_actions', {}) or {}
        if _hsa.get('flop') == 'check_call' and not h.get('hero_ip', True):
            # OOP check-call — potential "should have bet" spot
            _net = h.get('net_bb', 0)
            if _net < -5:  # lost meaningful chips
                _coaching_flags.append({
                    'id': h.get('id'), 'rule': 'OOP_CHECK_CALL_SHOULD_BET',
                    'detail': 'OOP check-call on flop — consider betting for '
                              'fold equity (population XR freq is low)',
                })

    # RULE 4: Cheap tourney sizing — <$100 BI, increase value bet sizes
    # Track: average c-bet sizing in <$100 vs $100+ buy-in tournaments
    _cheap_sizing = {'cheap_bets': [], 'expensive_bets': []}
    for h in hands:
        _bi = 100  # default
        _tname = h.get('tournament', '')
        # Extract buy-in from tournament name (rough heuristic)
        import re as _re_bi
        _bi_m = _re_bi.search(r'(\d+\.?\d*)\s*(?:$|Bounty|Hold|NLH)', _tname)
        if _bi_m:
            try:
                _bi = float(_bi_m.group(1))
            except ValueError:
                pass
        for _st, _sz, _spot, _ip in (h.get('hero_bets') or []):
            if _spot == 'cbet' and _sz:
                if _bi < 100:
                    _cheap_sizing['cheap_bets'].append(_sz)
                else:
                    _cheap_sizing['expensive_bets'].append(_sz)
    _cheap_avg = (sum(_cheap_sizing['cheap_bets']) / len(_cheap_sizing['cheap_bets'])
                  if _cheap_sizing['cheap_bets'] else 0)
    _exp_avg = (sum(_cheap_sizing['expensive_bets']) / len(_cheap_sizing['expensive_bets'])
                if _cheap_sizing['expensive_bets'] else 0)
    s['coaching_sizing_by_buyin'] = {
        'cheap_avg_sizing': round(_cheap_avg, 1),
        'expensive_avg_sizing': round(_exp_avg, 1),
        'cheap_n': len(_cheap_sizing['cheap_bets']),
        'expensive_n': len(_cheap_sizing['expensive_bets']),
    }
    if _cheap_avg and _cheap_avg < 50 and len(_cheap_sizing['cheap_bets']) >= 5:
        _coaching_flags.append({
            'id': '', 'rule': 'CHEAP_TOURNEY_SMALL_SIZING',
            'detail': f'Avg c-bet sizing {_cheap_avg:.0f}% in <$100 buy-ins — '
                      f'consider larger (villains are inelastic)',
        })

    # RULE 5: BvB deep stack bottom-range opens (>40BB)
    for h in hands:
        if (h.get('position') == 'SB'
                and h.get('opener_position') in (None, '', 'SB')
                and h.get('first_in')
                and h.get('pfr')
                and (h.get('stack_bb') or 0) > 40
                and h.get('n_players', 8) <= 3):  # BvB or 3-handed
            _hs = normalize_hand(h.get('cards', []))
            if not _hs:
                continue
            # Bottom range: offsuit non-broadway, non-ace, non-pair
            _r0 = _hs[0]; _r1 = _hs[1] if len(_hs) > 1 else '?'
            _is_suited = len(_hs) == 3 and _hs[2] == 's'
            _is_pair = len(_hs) == 2
            _BROADWAY = 'AKQJT'
            if (not _is_pair and not _is_suited
                    and _r0 not in _BROADWAY and _r1 not in _BROADWAY
                    and _r0 != 'A'):
                _coaching_flags.append({
                    'id': h.get('id'), 'rule': 'BVB_DEEP_RAGGED_OPEN',
                    'detail': f'Opened {_hs} BvB at {h.get("stack_bb",0):.0f}BB deep '
                              f'— bottom range ragged hand, consider folding',
                })

    s['coaching_flags'] = _coaching_flags
    if _coaching_flags:
        print(f"  Coaching flags: {len(_coaching_flags)} "
              f"({', '.join(set(f['rule'] for f in _coaching_flags))})")

    # ============================================================
    # BUG-U: MISSED BLUFF-RAISE DETECTOR
    # ============================================================
    # Flags spots where Hero CALLED with zero/low SDV when a bluff-raise
    # was available. The analysis typically only evaluates call/fold, but
    # when Hero has no SDV, the bluff-raise line (fold equity) should be
    # considered as the primary alternative.
    #
    # Criteria:
    #   - Hero called a bet on turn or river (not preflop, not flop)
    #   - Hero's hand strength is weak (high_card, no pair, busted draw)
    #   - Hero lost (net_bb < 0) — winning with air = got lucky
    #   - Hero was NOT all-in (has chips to raise)
    #   - Not multiway (bluff-raising into 3+ players is rarely correct)
    _missed_bluff_raises = []
    for h in hands:
        if h.get('net_bb', 0) >= 0:
            continue  # only flag losing calls
        if h.get('players_at_flop', 2) > 2:
            continue  # multiway — bluff-raising too risky
        if h.get('pf_allin') or h.get('flop_allin'):
            continue  # all-in — no raise option
        _hs = h.get('hand_strength', '')
        if _hs not in ('high_card', 'unknown', ''):
            continue  # has a made hand — not zero SDV
        # Check if Hero called on turn or river
        _called_turn = h.get('called_villain_bet_turn')
        _called_river = h.get('called_villain_bet_river')
        if not _called_turn and not _called_river:
            continue
        _street = 'river' if _called_river else 'turn'
        # Estimate: did Hero have zero SDV? Check if any draw existed
        _draw = h.get('draw_type', 'none') or 'none'
        _busted_draw = _street == 'river' and _draw != 'none' and _hs == 'high_card'
        _pure_air = _hs == 'high_card' and _draw == 'none'
        if not _busted_draw and not _pure_air:
            continue
        # This is a missed bluff-raise candidate
        _cards = normalize_hand(h.get('cards', []))
        _pos = h.get('position', '?')
        _stack = h.get('stack_bb', 0)
        _net = h.get('net_bb', 0)
        _desc = ('busted draw → bluff-raise was the exploit line'
                 if _busted_draw else
                 'pure air — no SDV, consider bluff-raising for fold equity')
        _missed_bluff_raises.append({
            'id': h.get('id', ''),
            'cards': _cards,
            'position': _pos,
            'stack_bb': round(_stack),
            'street': _street,
            'hand_strength': _hs,
            'draw_type': _draw,
            'net_bb': round(_net, 1),
            'note': f'{_cards} {_pos} {_street}: {_desc}',
        })
    _missed_bluff_raises.sort(key=lambda x: x['net_bb'])  # worst first
    s['missed_bluff_raises'] = _missed_bluff_raises[:15]
    if _missed_bluff_raises:
        print(f"  Missed bluff-raises: {len(_missed_bluff_raises)} spots "
              f"where Hero called with zero SDV (consider raising)")

    # v7.39 — MDA v7.5 overlay. Augments existing deviations with population-
    # exploit annotations and computes session-wide aligned/missed exploit
    # lists. Non-blocking: failures leave the existing deviations intact.
    try:
        import gem_mda_overlay as _mda
        _hands_by_id = {h.get('id'): h for h in hands if h.get('id')}
        _mda.annotate_deviations(pf_devs, _hands_by_id)
        s['mda_exploits'] = _mda.find_aligned_and_missed_exploits(hands)
    except Exception as _e:
        s['mda_exploits'] = {'aligned': [], 'missed': [],
                              'error': f'{type(_e).__name__}: {_e}'}
    # Summary by type
    # B-V10: collect hand IDs alongside card strings for hand-list popups
    dev_summary = defaultdict(lambda: {'count': 0, 'clear': 0, 'marginal': 0,
                                        'hands': [], 'hand_ids': []})
    for d in pf_devs:
        dt = d['type']
        dev_summary[dt]['count'] += 1
        if d.get('confidence') == 'CLEAR': dev_summary[dt]['clear'] += 1
        else: dev_summary[dt]['marginal'] += 1
        if len(dev_summary[dt]['hands']) < 5:
            dev_summary[dt]['hands'].append(d['cards'])
        dev_summary[dt]['hand_ids'].append(d.get('id', ''))
    s['deviation_summary'] = {k: dict(v) for k, v in dev_summary.items()}

    # --- v7.10: Promote CVJ/Iso-Jam deviations to mistakes (they're EV errors, not just deviations) ---
    cvj_iso_types = {'Wide CVJ (Call Villain Jam)', 'Wide Iso-Jam',
                     'Wide CVJ — re-jam over jam (covers)'}  # B176
    for d in pf_devs:
        if d['type'] in cvj_iso_types:
            mistakes.append({'id': d['id'], 'cards': d['cards'], 'pos': d['pos'],
                             'stack_bb': d['stack_bb'], 'format': d['format'],
                             'tournament': d.get('tournament','')[:45],
                             'type': d['type'], 'confidence': d.get('confidence','CLEAR'),
                             'action_summary': d.get('action_summary',''),
                             # B150: carry the correct iso-jam range through
                             # so the report shows it beside the flag.
                             'iso_range': d.get('iso_range'),
                             'jammer': d.get('jammer'), 'jammer_bb': d.get('jammer_bb'),
                             'note': d.get('note','')})
    # Recompute mistake counts after CVJ/Iso additions
    s['mistakes'] = mistakes
    # B257: inclusive filter — only confidence='CLEAR' counts as confirmed.
    clear_mistakes = [m for m in mistakes if m.get('confidence') == 'CLEAR']
    s['mistakes_per_100'] = round(len(clear_mistakes)/N*100, 2) if N else 0
    s['marginal_mistakes'] = [m for m in mistakes if m.get('confidence') == 'MARGINAL']
    s['marginal_per_100'] = round(len(s['marginal_mistakes'])/N*100, 2) if N else 0

    # --- PUNT CLASSIFIER (v7.13) ---
    # A punt is a RECKLESS/ILLOGICAL BIG mistake — chips in badly on a decision
    # evaluable as -EV before the result. Not results-oriented.
    # Gates:
    #   G1 — Magnitude: committed >=20BB OR >=30% eff stack
    #   G2 — Decision-not-output: matches a pattern Hero should know to avoid
    #   G3 — Pattern: P1..P6 below
    # Promoted FROM existing mistakes/deviations; removed from mistakes list
    # so the same hand isn't double-counted.
    dev_types_by_id = defaultdict(set)
    for d in s.get('preflop_deviations', []):
        dev_types_by_id[d['id']].add(d.get('type'))
    draw_jam_ids = {j['id'] for j in s.get('draw_overbet_jams', {}).get('hands', [])}
    small_small_jam_ids = {j['id'] for j in s.get('small_small_jam', {}).get('hands', [])}
    hand_by_id = {h['id']: h for h in hands}

    def _mk_punt(h, pattern, reason):
        return {
            'id': h['id'],
            'cards': normalize_hand(h.get('cards', [])),
            'pos': h.get('position'),
            'stack_bb': round(h.get('stack_bb', 0)),
            'eff_stack_bb': round(h.get('eff_stack_bb', h.get('stack_bb', 0))),
            'committed_bb': round(h.get('hero_committed_bb', 0), 1),
            'net_bb': round(h.get('net_bb', 0), 1),
            'tournament': h.get('tournament', '')[:45],
            'date': h.get('date'),
            'phase': h.get('tournament_phase'),
            'type': f'Punt ({pattern})',
            'pattern': pattern,
            'reason': reason,
            'confidence': 'CLEAR',
            'action_summary': h.get('action_summary', ''),
        }

    def _magnitude_ok(h):
        committed = h.get('hero_committed_bb', 0) or 0
        eff = h.get('eff_stack_bb', h.get('stack_bb', 0)) or 0
        return committed >= max(20, 0.30 * eff)

    punts = []
    punted_ids = set()
    for h in hands:
        hid = h.get('id')
        if hid in punted_ids: continue
        if not _magnitude_ok(h): continue
        eff = h.get('eff_stack_bb', h.get('stack_bb', 0)) or 0
        # Sanity floor: hands with eff<5BB are all-in already; committed-bb anomalies
        # can produce noise. Skip.
        if eff < 5: continue
        dts = dev_types_by_id.get(hid, set())

        # P1 — Dominated preflop stack-off (Wide CVJ / Wide Iso-Jam)
        # Exclusion: eff_stack < 13BB is push/fold territory; chart thresholds
        # don't apply there. Any-two-cards jams at short stacks are correct.
        if eff >= 13:
            # B176: a re-jam-covers is a CVJ (call decision) - same
            # P1-CVJ severity as a wide flat call of the jam.
            if ('Wide CVJ (Call Villain Jam)' in dts
                    or 'Wide CVJ — re-jam over jam (covers)' in dts):
                punts.append(_mk_punt(h, 'P1-CVJ',
                    'Called a jam with a hand outside CVJ threshold (should-know rule)'))
                punted_ids.add(hid); continue
            if 'Wide Iso-Jam' in dts:
                punts.append(_mk_punt(h, 'P1-IsoJam',
                    'Jammed over a jam with a hand outside Iso-Jam threshold (should-know rule)'))
                punted_ids.add(hid); continue

        # P2 — Light 4-bet spew: Wide 3-Bet AND preflop reached 4-bet+ AND eff >=30BB
        if 'Wide 3-Bet' in dts and eff >= 30 and h.get('pf_raise_count', 0) >= 4:
            punts.append(_mk_punt(h, 'P2-LightFourBet',
                '3-bet outside range then got it in on a 4-bet+ (deep, no plan)'))
            punted_ids.add(hid); continue

        # P3 — Deep OOP flat spew: Wide Call-Rejam at >=50BB eff
        if 'Wide Call-Rejam' in dts and eff >= 50:
            punts.append(_mk_punt(h, 'P3-DeepFlatSpew',
                'Flatted a 3-bet/raise OOP at >=50BB outside range, then stacked off'))
            punted_ids.add(hid); continue

        # P4 — Draw overbet jam at >=30BB effective (already flagged; this is the deep subset)
        # v7.31 Patch 6: SPR > 4 floor. At SPR <= 3 OOP, no geometric line is
        # feasible — every non-jam bet commits, so the overshove can be the
        # +EV play given range advantage + FE. Exception #13.
        if hid in draw_jam_ids and eff >= 30 and detector_prereq_satisfied('p4_drawjamdeep', h):
            punts.append(_mk_punt(h, 'P4-DrawJamDeep',
                'Overbet-jammed a draw at >=30BB eff AND SPR>4 — use geometric sizing, not single-street jam'))
            punted_ids.add(hid); continue

        # P5 — Small->Small->JAM river >=150% pot (a subset of small_small_jam)
        if hid in small_small_jam_ids:
            river_sizes = [b[1] for b in h.get('hero_bets', []) if b[0] == 'river']
            if river_sizes and max(river_sizes) >= 150:
                punts.append(_mk_punt(h, 'P5-SmallSmallJam',
                    'Sized small twice then jammed >=150% river — reckless pattern'))
                punted_ids.add(hid); continue

        # P6 — Pure bluff river overbet >=125% pot (no SDV, no pair with board)
        #
        # B44 (v7.51, Ron 2026-05-18): exception for capped-range exploit jams.
        # When Hero faces a tiny donk-lead on the river (<=20% pot), villain's
        # range is mechanically capped (the line is "I want a cheap showdown" —
        # virtually never strong hands that would value-bet for protection).
        # Raising/jamming over the donk is a textbook exploit, not a reckless
        # bluff. The detector's "pure bluff overbet" pattern is correctly
        # identifying the SIZING (125%+ pot) and the NO-VALUE-IN-HAND criterion,
        # but missing the CONTEXT (capped lead) that flips it from punt to
        # +EV exploit. Surfaced on TM5965565380 (AJo BTN exploit jam over a
        # 1BB donk lead on K-T-3 board; Hero blocked top of value range with
        # A and Js; villain folded — clean +28.5BB result was reclassified as
        # punt by P6).
        #
        # Skip P6 when Hero raised on river AND the villain's lead that Hero
        # raised was <=20% pot. Uses 'hero_raise_villain_lead_pct' field
        # populated by the parser when Hero raises a villain bet.
        if h.get('river_action') == 'bluff':
            river_sizes = [b[1] for b in h.get('hero_bets', []) if b[0] == 'river']
            if river_sizes and max(river_sizes) >= 125:
                # B44 capped-donk-lead exception
                villain_lead_river = (h.get('hero_raise_villain_lead_pct', {}) or {}).get('river')
                if villain_lead_river is not None and villain_lead_river <= 20:
                    # capped-range exploit — skip P6 flag
                    pass
                else:
                    punts.append(_mk_punt(h, 'P6-BluffOverbet',
                        'Pure-bluff river overbet >=125% pot — reckless without blockers/equity'))
                    punted_ids.add(hid); continue

    # Remove promoted hands from mistakes (avoid double-count)
    mistakes_after_promotion = [m for m in mistakes if m['id'] not in punted_ids]
    s['mistakes'] = mistakes_after_promotion
    # B257: inclusive filter — only confidence='CLEAR' counts as confirmed.
    clear_mistakes = [m for m in mistakes_after_promotion if m.get('confidence') == 'CLEAR']
    s['mistakes_per_100'] = round(len(clear_mistakes)/N*100, 2) if N else 0
    s['marginal_mistakes'] = [m for m in mistakes_after_promotion if m.get('confidence') == 'MARGINAL']
    s['marginal_per_100'] = round(len(s['marginal_mistakes'])/N*100, 2) if N else 0

    # Punt stats
    s['punts'] = {
        'count': len(punts),
        'per_100': round(len(punts)/N*100, 2) if N else 0,
        'per_1000': round(len(punts)/N*1000, 2) if N else 0,
        'by_pattern': dict(Counter(p['pattern'] for p in punts)),
        'total_net_bb': round(sum(p['net_bb'] for p in punts), 1),
        'total_committed_bb': round(sum(p['committed_bb'] for p in punts), 1),
        'hands': punts,
    }

    # --- v7.10: <8BB push/fold missed as separate stat ---
    push_misses = [m for m in mistakes if 'Push <8BB' in m.get('type','') or 'Reshove <8BB' in m.get('type','')]
    s['push_fold_lt8bb_misses'] = len(push_misses)
    s['push_fold_lt8bb_clear'] = sum(1 for m in push_misses if m.get('confidence') == 'CLEAR')

    # --- POSITIONAL P&L (v7.11) ---
    pos_pnl = {}
    for pos_name in ['UTG','UTG+1','MP','HJ','CO','BTN','SB','BB']:
        ph = [h for h in hands if h['position'] == pos_name]
        if not ph: continue
        total_bb = sum(h.get('net_bb', 0) for h in ph)
        n_hands = len(ph)
        vpip_h = [h for h in ph if h.get('vpip')]
        vpip_bb = sum(h.get('net_bb', 0) for h in vpip_h)
        pos_pnl[pos_name] = {
            'hands': n_hands,
            'net_bb': round(total_bb, 1),
            'bb_per_hand': round(total_bb / n_hands, 2) if n_hands else 0,
            'bb_per_100': round(total_bb / n_hands * 100, 1) if n_hands else 0,
            'vpip_hands': len(vpip_h),
            'vpip_net_bb': round(vpip_bb, 1),
            'vpip_bb_per_hand': round(vpip_bb / len(vpip_h), 2) if vpip_h else 0,
        }
    s['positional_pnl'] = pos_pnl

    # =========================================================================
    # v7.27 — FACING-ACTION DEFENSE + DONK + BARREL + AFq + SPLIT METRICS
    # =========================================================================
    # All rates are computed as: numerator / opportunity_count.
    # Each metric carries its own denominator (n) for confidence assessment.
    # Section 'facing_action' bundles them; key fields also lifted to 'core'
    # so the report and CSV can reference them directly.
    facing = {}

    def _rate(num, den):
        return round(100.0 * num / den, 1) if den > 0 else 0.0

    # ----- Hero as caller facing villain c-bet -----
    cbet_opps = sum(1 for h in hands if h.get('faced_villain_cbet_flop'))
    fold_to_cbet = sum(1 for h in hands if h.get('fold_to_villain_cbet_flop'))
    call_cbet   = sum(1 for h in hands if h.get('called_villain_cbet_flop'))
    raise_cbet_ip = sum(1 for h in hands if h.get('raised_villain_cbet_flop_ip'))
    xr_cbet     = sum(1 for h in hands if h.get('xr_villain_cbet_flop'))
    # v7.34 IP/OOP subsets (Jasper exploit set: float-flop = call IP; xr = raise OOP)
    cbet_opps_ip  = sum(1 for h in hands if h.get('faced_villain_cbet_flop') and h.get('hero_ip'))
    cbet_opps_oop = sum(1 for h in hands if h.get('faced_villain_cbet_flop') and not h.get('hero_ip'))
    call_cbet_ip  = sum(1 for h in hands if h.get('called_villain_cbet_flop') and h.get('hero_ip'))
    call_cbet_oop = sum(1 for h in hands if h.get('called_villain_cbet_flop') and not h.get('hero_ip'))
    facing['vs_cbet'] = {
        'opps': cbet_opps,
        'fold': fold_to_cbet, 'fold_pct': _rate(fold_to_cbet, cbet_opps),
        'call': call_cbet, 'call_pct': _rate(call_cbet, cbet_opps),
        'raise_ip': raise_cbet_ip, 'raise_ip_pct': _rate(raise_cbet_ip, cbet_opps),
        'xr': xr_cbet, 'xr_pct': _rate(xr_cbet, cbet_opps),
        # v7.34 IP/OOP split for float-flop and OOP raise (xr) exploit metrics
        'opps_ip': cbet_opps_ip, 'opps_oop': cbet_opps_oop,
        'call_ip': call_cbet_ip, 'call_ip_pct': _rate(call_cbet_ip, cbet_opps_ip),
        'call_oop': call_cbet_oop, 'call_oop_pct': _rate(call_cbet_oop, cbet_opps_oop),
        # raise_ip is already restricted to IP hands by parser flag (raised_villain_cbet_flop_ip);
        # its denominator should be IP-only opps for a clean rate. Add aliased rate alongside.
        'raise_ip_pct_of_ip': _rate(raise_cbet_ip, cbet_opps_ip),
        'xr_pct_of_oop': _rate(xr_cbet, cbet_opps_oop),
    }
    # v7.43 (Ron 2026-05-09): Raise CBet OOP across ALL pot types (not just SRP).
    # Previous xr_pct_of_oop only counted SRP cbet check-raises because
    # faced_villain_cbet_flop is set only in SRPs. 3-bet pot and 4-bet pot
    # cbet check-raises were missed entirely (this session: 2 check-raises in
    # 3BPs counted as 0 in raise_cbet_oop_pct). Add unified metric covering
    # SRP + 3BP + 4BP.
    cbet_opps_oop_all = sum(1 for h in hands
                            if (h.get('faced_villain_cbet_flop') or
                                h.get('faced_villain_cbet_flop_3bp') or
                                h.get('faced_villain_cbet_flop_4bp'))
                            and not h.get('hero_ip'))
    xr_cbet_all = sum(1 for h in hands
                      if h.get('hero_check_raise_flop')
                      and not h.get('hero_ip')
                      and (h.get('faced_villain_cbet_flop') or
                           h.get('faced_villain_cbet_flop_3bp') or
                           h.get('faced_villain_cbet_flop_4bp')))
    facing['vs_cbet']['xr_all_pots_oop'] = xr_cbet_all
    facing['vs_cbet']['opps_oop_all_pots'] = cbet_opps_oop_all
    facing['vs_cbet']['xr_pct_of_oop_all_pots'] = _rate(xr_cbet_all, cbet_opps_oop_all)

    # ----- Hero c-bet, faced XR/raise -----
    xr_opps = sum(1 for h in hands if h.get('faced_xr_after_cbet'))
    fold_to_xr  = sum(1 for h in hands if h.get('folded_to_xr_after_cbet'))
    call_xr     = sum(1 for h in hands if h.get('called_xr_after_cbet'))
    reraise_xr  = sum(1 for h in hands if h.get('reraised_xr_after_cbet'))
    facing['xr_after_cbet'] = {
        'opps': xr_opps,
        'fold': fold_to_xr, 'fold_pct': _rate(fold_to_xr, xr_opps),
        'call': call_xr, 'call_pct': _rate(call_xr, xr_opps),
        'reraise': reraise_xr, 'reraise_pct': _rate(reraise_xr, xr_opps),
    }

    # ----- Donk profile (Hero as caller OOP leading) -----
    donk_opps = sum(1 for h in hands if (not h.get('pfr')) and (not h.get('hero_ip'))
                    and h.get('vpip') and len(h.get('board') or []) >= 3)
    donk_flop = sum(1 for h in hands if h.get('hero_donked_flop'))
    # FEAT-D: collect donk hand IDs
    _donk_flop_ids = [h.get('id','') for h in hands if h.get('hero_donked_flop') and h.get('id')]
    _donk_turn_ids = [h.get('id','') for h in hands if h.get('hero_donked_turn') and h.get('id')]
    donk_turn_opps = sum(1 for h in hands if (not h.get('pfr')) and (not h.get('hero_ip'))
                         and h.get('vpip') and len(h.get('board') or []) >= 4)
    donk_turn = sum(1 for h in hands if h.get('hero_donked_turn'))
    facing['donk_lead'] = {
        'flop_opps': donk_opps, 'flop_donks': donk_flop,
        'flop_pct': _rate(donk_flop, donk_opps),
        'flop_donk_ids': _donk_flop_ids[:20],
        'turn_opps': donk_turn_opps, 'turn_donks': donk_turn,
        'turn_pct': _rate(donk_turn, donk_turn_opps),
        'turn_donk_ids': _donk_turn_ids[:20],
    }

    # ----- Hero as PFR facing donk -----
    faced_donk_opps = sum(1 for h in hands if h.get('faced_donk_flop'))
    fold_to_donk  = sum(1 for h in hands if h.get('folded_to_donk_flop'))
    call_donk     = sum(1 for h in hands if h.get('called_donk_flop'))
    raise_donk    = sum(1 for h in hands if h.get('raised_donk_flop'))
    facing['vs_donk'] = {
        'opps': faced_donk_opps,
        'fold': fold_to_donk, 'fold_pct': _rate(fold_to_donk, faced_donk_opps),
        'call': call_donk, 'call_pct': _rate(call_donk, faced_donk_opps),
        'raise': raise_donk, 'raise_pct': _rate(raise_donk, faced_donk_opps),
    }

    # ----- Hero double / triple barrel rates -----
    cbet_flop_count = sum(1 for h in hands if h.get('pfr')
                          and (h.get('hero_street_actions') or {}).get('flop') == 'cbet')
    double_barrel = sum(1 for h in hands if h.get('double_barreled'))
    triple_barrel = sum(1 for h in hands if h.get('triple_barreled'))
    # POPUP IDs: collect hand IDs for barrel/probe/bet-fold/value/bluff drill-down
    _barrel_ids = {
        'double_barrel_ids': [h['id'] for h in hands if h.get('double_barreled') and h.get('id')],
        'missed_barrel_ids': [h['id'] for h in hands if h.get('pfr')
                              and (h.get('hero_street_actions') or {}).get('flop') == 'cbet'
                              and not h.get('double_barreled') and len(h.get('board', [])) >= 4
                              and h.get('id')],
        'triple_barrel_ids': [h['id'] for h in hands if h.get('triple_barreled') and h.get('id')],
        'missed_triple_ids': [h['id'] for h in hands if h.get('double_barreled')
                              and not h.get('triple_barreled') and len(h.get('board', [])) >= 5
                              and h.get('id')],
        'probe_turn_ids': [h['id'] for h in hands if h.get('probe_turn') and h.get('id')],
        # v8.19.0 Chapter D: popup ID lists share the same street legal-opportunity gate as their counters.
        'missed_probe_ids': [h['id'] for h in hands if h.get('missed_probe') and h.get('id')
                             and is_legal_postflop_opportunity(h, 'turn')],
        'missed_river_value_ids': [h['id'] for h in hands if h.get('missed_river_value') and h.get('id')
                                   and is_legal_postflop_opportunity(h, 'river')],
        'bet_fold_flop_ids': [h['id'] for h in hands if h.get('folded_to_xr_after_cbet') and h.get('id')],
        'bet_fold_turn_ids': [h['id'] for h in hands if h.get('fold_to_villain_bet_turn')
                              and h.get('hero_street_actions', {}).get('turn') in ('bet', 'cbet', 'barrel')
                              and h.get('id')],
        'missed_squeeze_ids': [h['id'] for h in hands if h.get('squeeze_opp')
                               and not h.get('is_squeeze') and h.get('id')],
    }

    # ================================================================
    # TEACHING EXAMPLE FILTERING (v8.4.6 + v8.5.0 action-frequency)
    # Separate metric denominators from teachable examples.
    # Uses SQF_*_HF (>=70% frequency) charts for high-confidence gating,
    # falling back to binary SQUEEZE_* charts when SQF data unavailable.
    # ================================================================
    def _depth_key(stack):
        if stack <= 35:
            return '30BB'
        return '50BB'

    _POS_MAP = {'MP': 'LJ', 'UTG+2': 'LJ'}

    def _squeeze_caller_pos(h):
        """Extract the cold-caller's position from pf_sequence."""
        opener = h.get('opener_position', '')
        saw_raise = False
        for item in (h.get('pf_sequence') or []):
            if '(H)' in item:
                break
            parts = item.split(':', 1)
            if len(parts) < 2:
                continue
            pos_part, action = parts[0], parts[1]
            if action == 'raises':
                saw_raise = True
            elif action == 'calls' and saw_raise:
                return pos_part
        return ''

    def _gate_squeeze_opportunity(h):
        return (h.get('squeeze_opp')
                and not h.get('is_squeeze')
                and h.get('hero_faced_raise')
                and not h.get('pf_allin')
                and h.get('id'))

    _sqf_diag = {'no_cards': 0, 'no_chart': 0, 'not_in_range': 0,
                  'clear': 0, 'mixed': 0, 'keys_tried': set(), 'keys_hit': set(),
                  'sample_misses': []}

    def _gate_squeeze_range(h):
        """Hand must be in squeeze range. Returns ('clear'|'mixed'|False)."""
        try:
            from gem_ranges import load_ranges, normalize_hand_class
            cards = normalize_hand_class(''.join(h.get('cards', [])))
            if not cards:
                _sqf_diag['no_cards'] += 1
                return False
            hero = h.get('position', '')
            opener = _POS_MAP.get(h.get('opener_position', ''), h.get('opener_position', ''))
            caller = _POS_MAP.get(_squeeze_caller_pos(h), _squeeze_caller_pos(h))
            stack = h.get('eff_stack_bb') or h.get('stack_bb') or 30
            dk = _depth_key(stack)
            all_ranges = load_ranges()

            hf_keys = [f'SQF_{dk}_{hero}_vs{opener}open_{caller}call_HF']
            base_keys = [f'SQF_{dk}_{hero}_vs{opener}open_{caller}call']
            if caller == 'BTN' or not caller:
                hf_keys.append(f'SQF_{dk}_{hero}_vs{opener}open_BTNcall_HF')
                base_keys.append(f'SQF_{dk}_{hero}_vs{opener}open_BTNcall')
            old_keys = [f'SQUEEZE_{dk}_vs{opener}open_{caller}call',
                        f'SQUEEZE_{dk}_vs{opener}open_BTNcall']

            all_keys = hf_keys + base_keys + old_keys
            for k in all_keys:
                _sqf_diag['keys_tried'].add(k)

            for key in hf_keys:
                rng = all_ranges.get(key)
                if rng:
                    _sqf_diag['keys_hit'].add(key)
                    if cards in rng:
                        _sqf_diag['clear'] += 1
                        return 'clear'
            for key in base_keys:
                rng = all_ranges.get(key)
                if rng:
                    _sqf_diag['keys_hit'].add(key)
                    if cards in rng:
                        _sqf_diag['mixed'] += 1
                        return 'mixed'
            for key in old_keys:
                rng = all_ranges.get(key)
                if rng:
                    _sqf_diag['keys_hit'].add(key)
                    if cards in rng:
                        _sqf_diag['mixed'] += 1
                        return 'mixed'

            _sqf_diag['not_in_range'] += 1
            if len(_sqf_diag['sample_misses']) < 5:
                _sqf_diag['sample_misses'].append(
                    f"{cards} {hero} vs{opener}+{caller} {dk} keys={[k for k in all_keys if all_ranges.get(k)]}")
            return False
        except Exception as _e:
            if len(_sqf_diag['sample_misses']) < 5:
                _sqf_diag['sample_misses'].append(f"EXCEPTION: {_e}")
            return 'clear'

    def _gate_squeeze_clarity(h):
        stack = h.get('eff_stack_bb') or h.get('stack_bb') or 30
        if stack < 8 or stack > 100:
            return False
        return True

    def _rank_teaching(h):
        score = 50
        cards = ''.join(h.get('cards', []))
        if any(c in cards for c in ['A', 'K', 'Q']):
            score += 10
        stack = h.get('eff_stack_bb') or h.get('stack_bb') or 0
        if 20 <= stack <= 60:
            score += 15
        elif stack < 12 or stack > 100:
            score -= 15
        if h.get('first_in'):
            score += 5
        return score

    _sq_all = [h for h in hands if _gate_squeeze_opportunity(h)]
    _sq_qualified = []
    _sq_mixed = []
    for h in _sq_all:
        rng_result = _gate_squeeze_range(h)
        if rng_result == 'clear' and _gate_squeeze_clarity(h):
            _sq_qualified.append(h)
        elif rng_result == 'mixed' and _gate_squeeze_clarity(h):
            _sq_mixed.append(h)
    _sq_qualified.sort(key=lambda h: -_rank_teaching(h))

    _sq_rejected = [{'id': h.get('id'), 'reasons': [
        r for r in [
            'not_in_squeeze_range' if not _gate_squeeze_range(h) else None,
            'mixed_frequency' if _gate_squeeze_range(h) == 'mixed' else None,
            'extreme_stack' if not _gate_squeeze_clarity(h) else None,
        ] if r
    ]} for h in _sq_all if h not in _sq_qualified]

    s['teaching_examples'] = {
        'missed_squeeze': {
            'opportunity_ids': [h['id'] for h in _sq_all],
            'teaching_example_ids': [h['id'] for h in _sq_qualified[:20]],
            'review_candidate_ids': [h['id'] for h in _sq_mixed[:20]],
            'total_opps': len(_sq_all),
            'qualified_n': len(_sq_qualified),
            'mixed_n': len(_sq_mixed),
            'coverage_pct': round(len(_sq_qualified) / max(len(_sq_all), 1) * 100, 1),
            'rejection_sample': _sq_rejected[:10],
        },
    }
    print(f"  Teaching examples: missed_squeeze {len(_sq_qualified)} clear + "
          f"{len(_sq_mixed)} mixed / {len(_sq_all)} opps "
          f"({s['teaching_examples']['missed_squeeze']['coverage_pct']}%)")
    if _sqf_diag['keys_tried']:
        _kt = len(_sqf_diag['keys_tried'])
        _kh = len(_sqf_diag['keys_hit'])
        print(f"    SQF diag: {_kt} keys tried, {_kh} resolved to charts, "
              f"no_cards={_sqf_diag['no_cards']}, not_in_range={_sqf_diag['not_in_range']}")
        if _sqf_diag['sample_misses']:
            for _sm in _sqf_diag['sample_misses']:
                print(f"    SQF miss: {_sm}")
        if not _sqf_diag['keys_hit']:
            try:
                from gem_ranges import load_ranges as _lr_diag
                _rd = _lr_diag()
                _sqf_keys = [k for k in _rd if k.startswith('SQF_') or k.startswith('SQUEEZE_')]
                print(f"    gem_ranges has {len(_rd)} charts total, {len(_sqf_keys)} SQF/SQUEEZE: {_sqf_keys[:8]}")
            except Exception:
                print(f"    gem_ranges.load_ranges() failed or empty")

    # ================================================================
    # TEACHING EXAMPLES: MISSED 3-BET (uses 3BF_*_HF charts)
    # ================================================================
    def _gate_3bet_range(h):
        """Returns 'clear'/'mixed'/False for missed 3-bet hands."""
        try:
            from gem_ranges import load_ranges as _lr_3b, normalize_hand_class as _nhc_3b
            cards = _nhc_3b(''.join(h.get('cards', [])))
            if not cards:
                return False
            hero = h.get('position', '')
            opener = h.get('opener_position', '')
            stack = h.get('eff_stack_bb') or h.get('stack_bb') or 30
            dk = '20BB' if stack <= 25 else ('30BB' if stack <= 40 else '50BB')
            all_r = _lr_3b()
            # Try 3BF_HF first (high-frequency = clear teaching example)
            hf_key = f'3BF_{dk}_{hero}vs{opener}_HF'
            hf_rng = all_r.get(hf_key, {})
            if hf_rng and cards in hf_rng:
                return 'clear'
            # Try 3BF base (>=50% = mixed)
            base_key = f'3BF_{dk}_{hero}vs{opener}'
            base_rng = all_r.get(base_key, {})
            if base_rng and cards in base_rng:
                return 'mixed'
            # Fallback to old 3BET charts (binary)
            old_key = f'3BET_{dk}_{hero}vs{opener}'
            old_rng = all_r.get(old_key, {})
            if old_rng and cards in old_rng:
                return 'mixed'
            return False
        except Exception:
            return 'clear'

    _3b_all = [h for h in hands
               if h.get('hero_faced_raise') and not h.get('hero_3bet')
               and not h.get('pf_allin') and not h.get('first_in')
               and h.get('pf_raise_count', 0) == 1
               and h.get('position') not in ('UTG', 'UTG+1')
               and (h.get('eff_stack_bb') or h.get('stack_bb') or 0) >= 12
               and h.get('id') and h.get('cards')]
    _3b_qualified = []
    _3b_mixed = []
    for h in _3b_all:
        rng = _gate_3bet_range(h)
        if rng == 'clear' and _gate_squeeze_clarity(h):
            _3b_qualified.append(h)
        elif rng == 'mixed' and _gate_squeeze_clarity(h):
            _3b_mixed.append(h)
    _3b_qualified.sort(key=lambda h: -_rank_teaching(h))

    s['teaching_examples']['missed_3bet'] = {
        'opportunity_ids': [h['id'] for h in _3b_all],
        'teaching_example_ids': [h['id'] for h in _3b_qualified[:20]],
        'review_candidate_ids': [h['id'] for h in _3b_mixed[:20]],
        'total_opps': len(_3b_all),
        'qualified_n': len(_3b_qualified),
        'mixed_n': len(_3b_mixed),
        'coverage_pct': round(len(_3b_qualified) / max(len(_3b_all), 1) * 100, 1),
    }
    print(f"  Teaching examples: missed_3bet {len(_3b_qualified)} clear + "
          f"{len(_3b_mixed)} mixed / {len(_3b_all)} opps "
          f"({s['teaching_examples']['missed_3bet']['coverage_pct']}%)")

    # Legacy compatibility: merge flat lists into _barrel_ids before final assign
    _barrel_ids.update({
        'missed_cr_flop_ids': [h['id'] for h in hands
                               if h.get('faced_villain_cbet_flop') and not h.get('hero_ip')
                               and h.get('called_villain_cbet_flop') and not h.get('xr_villain_cbet_flop')
                               and h.get('hand_strength', '') in ('two_pair', 'trips', 'straight', 'flush', 'full_house')
                               and (h.get('players_at_flop') or 2) <= 2  # HU only — multiway flat-to-trap is standard
                               and not h.get('hero_check_raise_turn')  # didn't CR a later street
                               and not h.get('hero_check_raise_river')
                               and not h.get('raised_villain_bet_turn')
                               and not h.get('raised_villain_bet_river')
                               and h.get('id')],
        'cbet_3bp_ids': [h['id'] for h in hands if h.get('cbet_flop_3bp') and h.get('id')],
        # v8.12.4 (QA item 14): a check-raise / flop jam by the PFR is not a
        # MISSED c-bet either — require a genuinely passive flop action.
        'missed_cbet_3bp_ids': [h['id'] for h in hands if h.get('hero_3bet')
                                and h.get('pot_type') == '3BP' and is_legal_cbet_opportunity(h)
                                and not h.get('cbet_flop_3bp') and not h.get('cbet_flop_srp')
                                and (h.get('hero_street_actions', {}) or {}).get('flop')
                                    not in ('jam', 'xr', 'xr-ai', 'raise', 'bet', 'bet-call',
                                            'bet-fold', 'bet-callAI')
                                and h.get('id')],
        'missed_bluff_river_ids': [h['id'] for h in hands
                                   if h.get('river_action') in ('check_sdv', 'check_giveup')
                                   and h.get('hand_strength') == 'high_card'
                                   and h.get('id')],
    })
    for _bk in _barrel_ids:
        _barrel_ids[_bk] = _barrel_ids[_bk][:20]
    s['popup_hand_ids'] = _barrel_ids

    facing['barrels'] = {
        'cbet_count': cbet_flop_count,
        'double_barrel': double_barrel,
        'double_barrel_pct': _rate(double_barrel, cbet_flop_count),
        'triple_barrel': triple_barrel,
        'triple_barrel_pct': _rate(triple_barrel, cbet_flop_count),
    }

    # ----- Hero faced double/turn barrel as caller -----
    turn_barrel_opps = sum(1 for h in hands if h.get('faced_turn_barrel'))
    fold_to_tb = sum(1 for h in hands if h.get('folded_to_turn_barrel'))
    call_tb    = sum(1 for h in hands if h.get('called_turn_barrel'))
    facing['vs_turn_barrel'] = {
        'opps': turn_barrel_opps,
        'fold': fold_to_tb, 'fold_pct': _rate(fold_to_tb, turn_barrel_opps),
        'call': call_tb, 'call_pct': _rate(call_tb, turn_barrel_opps),
    }

    # ----- Bet-Fold / Bet-Call (Hero bet then villain raised) -----
    for st in ('flop', 'turn', 'river'):
        opp = sum(1 for h in hands if h.get(f'bet_then_faced_raise_{st}'))
        bf  = sum(1 for h in hands if h.get(f'bet_fold_{st}'))
        bc  = sum(1 for h in hands if h.get(f'bet_call_{st}'))
        facing[f'bet_fold_{st}'] = {
            'opps': opp,
            'fold': bf, 'fold_pct': _rate(bf, opp),
            'call': bc, 'call_pct': _rate(bc, opp),
        }

    # ----- Cold call rates (overall + by Hero position) -----
    cc_opps = sum(1 for h in hands if h.get('vpip') and h.get('hero_faced_raise')
                  and not h.get('villain_jammed'))
    cold_calls = sum(1 for h in hands if h.get('cold_called'))
    cc_3bet    = sum(1 for h in hands if h.get('cold_called_3bet'))
    facing['cold_call'] = {
        'opps': cc_opps,
        'cc': cold_calls, 'cc_pct': _rate(cold_calls, cc_opps),
        'cc_3bet': cc_3bet, 'cc_3bet_pct': _rate(cc_3bet, cc_opps),
    }

    # v7.31 Patch 1: split Cold Call into separate stats with distinct targets.
    # The lumped Cold_Call stat mixed BB defense (target ~55-65% vs steal) with
    # non-blind cold-calls (target 5-15%), producing a number that doesn't map
    # to any real target. Reported as 67.2% on this session — auto-leak deriver
    # mistakenly flagged it 🔴 when the underlying BB defense was 🟢 in target.
    #
    # Replacement stats:
    #   Cold_Call_NB              — non-blind cold calls only (UTG-BTN)
    #   BB_Defense_vs_Steal       — call/3-bet rate vs CO/BTN/SB open
    #   BB_Defense_vs_NonSteal    — call/3-bet rate vs UTG-HJ open
    #   SB_Defense_vs_LP          — SB defense vs CO/BTN open
    LATE_POSITIONS = {'CO', 'BTN', 'SB'}
    EARLY_MID_POSITIONS = {'UTG', 'UTG+1', 'MP', 'HJ'}

    # Non-blind cold call (excludes blinds defending)
    # v7.43 (Ron 2026-05-09): denom no longer requires vpip=True. Old denom
    # was self-fulfilling — only counted hands where Hero ENTERED the pot,
    # so the rate became "of times Hero VPIP'd vs an open, what % were
    # cold-calls" (essentially 1 - 3-bet rate). Correct definition: of times
    # Hero faced an open from non-blinds, what % did Hero cold-call (calls
    # vs raises vs folds). This session: was 26/58=44.8% (buggy), now
    # 26/338=7.7% (in target 5-15%).
    nb_cc_opps = sum(1 for h in hands if h.get('hero_faced_raise')
                     and not h.get('villain_jammed')
                     and h.get('position') not in ('SB', 'BB'))
    nb_cc = sum(1 for h in hands if h.get('cold_called')
                and h.get('position') not in ('SB', 'BB'))
    facing['cold_call_nb'] = {
        'opps': nb_cc_opps, 'cc': nb_cc, 'cc_pct': _rate(nb_cc, nb_cc_opps),
        'target': '5-15% (mostly fold or 3-bet from non-blinds)',
    }

    # BB defense vs steal (CO/BTN/SB open) — defend = call OR 3-bet
    bb_steal_opps = sum(1 for h in hands if h.get('position') == 'BB'
                        and h.get('faced_steal_bb'))
    bb_steal_call = sum(1 for h in hands if h.get('position') == 'BB'
                        and h.get('faced_steal_bb') and h.get('called_steal_bb'))
    bb_steal_3bet = sum(1 for h in hands if h.get('position') == 'BB'
                        and h.get('faced_steal_bb') and h.get('hero_3bet'))
    bb_steal_defend = bb_steal_call + bb_steal_3bet
    _bb_steal_fold_ids = [h['id'] for h in hands if h.get('position') == 'BB'
                          and h.get('faced_steal_bb') and not h.get('vpip') and h.get('id')]
    # BB missed-defend: range-gated using BB_DEF_vs*pct charts
    _bb_steal_folds = [h for h in hands if h.get('position') == 'BB'
                        and h.get('faced_steal_bb') and not h.get('vpip') and h.get('id')]
    _bb_missed_gated = []
    # Derive opener open% from OPEN chart widths
    _opener_pct_defaults = {'UTG': 15, 'UTG+1': 20, 'MP': 25, 'HJ': 30,
                             'CO': 35, 'BTN': 45, 'SB': 50}
    _opener_pct_map = dict(_opener_pct_defaults)
    for _op_pos in _opener_pct_defaults:
        _op_ws = [round(len(rv) / 169 * 100) for rk, rv in (ranges or {}).items()
                  if rk.startswith('OPEN_') and rk.endswith(f'_{_op_pos}')]
        if _op_ws:
            _opener_pct_map[_op_pos] = round(sum(_op_ws) / len(_op_ws))
    for h in _bb_steal_folds:
        try:
            _hs = normalize_hand(h.get('cards', []))
            if not _hs:
                continue
            _op = h.get('opener_position', '')
            _op_pct = _opener_pct_map.get(_op, 30)
            _pct_options = [15, 20, 25, 30, 35, 40, 45, 50]
            _closest = min(_pct_options, key=lambda x: abs(x - _op_pct))
            _def_key = f'BB_DEF_vs{_closest}pct'
            _def_rng = (ranges or {}).get(_def_key, set())
            if _def_rng and _hs in _def_rng:
                _bb_missed_gated.append({
                    'id': h['id'], 'cards': _hs, 'opener': _op,
                    'stack_bb': round(h.get('eff_stack_bb') or h.get('stack_bb') or 0),
                    'chart': _def_key,
                    'correct_action': 'defend',
                    'range_note': f'{_hs} is in BB defend range vs {_op} open ({_def_key})',
                })
        except Exception:
            pass
    facing['bb_defense_vs_steal'] = {
        'opps': bb_steal_opps, 'defend': bb_steal_defend,
        'defend_pct': _rate(bb_steal_defend, bb_steal_opps),
        'call': bb_steal_call, 'call_pct': _rate(bb_steal_call, bb_steal_opps),
        'three_bet': bb_steal_3bet, 'three_bet_pct': _rate(bb_steal_3bet, bb_steal_opps),
        'target': '55-65% defend rate (combined call + 3-bet)',
        'missed_defend_ids': _bb_steal_fold_ids[:20],
        'missed_defend_gated': _bb_missed_gated[:20],
    }

    # BB defense vs non-steal (UTG-HJ open) — tighter target
    bb_nons_opps = sum(1 for h in hands if h.get('position') == 'BB'
                       and h.get('hero_faced_raise')
                       and not h.get('faced_steal_bb')
                       and not h.get('villain_jammed'))
    bb_nons_call = sum(1 for h in hands if h.get('position') == 'BB'
                       and h.get('hero_faced_raise')
                       and not h.get('faced_steal_bb')
                       and h.get('vpip')
                       and h.get('cold_called'))
    bb_nons_3bet = sum(1 for h in hands if h.get('position') == 'BB'
                       and h.get('hero_faced_raise')
                       and not h.get('faced_steal_bb')
                       and h.get('hero_3bet'))
    bb_nons_defend = bb_nons_call + bb_nons_3bet
    facing['bb_defense_vs_nonsteal'] = {
        'opps': bb_nons_opps, 'defend': bb_nons_defend,
        'defend_pct': _rate(bb_nons_defend, bb_nons_opps),
        'target': '30-45% defend rate vs UTG-HJ open',
    }

    # SB defense vs LP (CO/BTN open)
    sb_lp_opps = sum(1 for h in hands if h.get('position') == 'SB'
                     and h.get('hero_faced_raise')
                     and h.get('opener_position') in LATE_POSITIONS - {'SB'}
                     and not h.get('villain_jammed'))
    sb_lp_call = sum(1 for h in hands if h.get('position') == 'SB'
                     and h.get('hero_faced_raise')
                     and h.get('opener_position') in LATE_POSITIONS - {'SB'}
                     and h.get('cold_called'))
    sb_lp_3bet = sum(1 for h in hands if h.get('position') == 'SB'
                     and h.get('hero_faced_raise')
                     and h.get('opener_position') in LATE_POSITIONS - {'SB'}
                     and h.get('hero_3bet'))
    sb_lp_defend = sb_lp_call + sb_lp_3bet
    # B1 (Aviel handoff 2026-05-25): collect the FOLDED SB-vs-LP spots so V.3
    # can list them — Ron wants to audit which folds were wrong, not just see
    # the aggregate rate.
    sb_lp_folded = [
        {'id': h.get('id'),
         'cards': ''.join(h.get('cards', []) or []),
         'opener_position': h.get('opener_position', '?'),
         'stack_bb': round(h.get('stack_bb', 0) or 0),
         'tournament': (h.get('tournament', '') or '')[:45],
         'date': h.get('date', '')}
        for h in hands
        if h.get('position') == 'SB'
        and h.get('hero_faced_raise')
        and h.get('opener_position') in LATE_POSITIONS - {'SB'}
        and not h.get('villain_jammed')
        and not h.get('cold_called')
        and not h.get('hero_3bet')
    ]
    # SB missed-defend: range-gated using SBD_* charts
    _sb_lp_folds = [h for h in hands if h.get('position') == 'SB'
                     and h.get('hero_faced_raise')
                     and h.get('opener_position') in LATE_POSITIONS - {'SB'}
                     and not h.get('villain_jammed')
                     and not h.get('vpip') and h.get('id')]
    _sb_lp_fold_ids = [h['id'] for h in _sb_lp_folds]
    _sb_missed_gated = []
    for h in _sb_lp_folds:
        try:
            _hs = normalize_hand(h.get('cards', []))
            if not _hs:
                continue
            _op = h.get('opener_position', '')
            _stk = h.get('eff_stack_bb') or h.get('stack_bb') or 30
            _dk = '20BB' if _stk <= 25 else ('35BB' if _stk <= 42 else '50BB')
            # Check if hand is in the total defend range
            _def_key = f'SBD_{_dk}_vs{_op}'
            _def_rng = (ranges or {}).get(_def_key, set())
            if _def_rng and _hs in _def_rng:
                # Determine if it was a call or 3-bet hand
                _call_key = f'SBD_{_dk}_vs{_op}_CALL'
                _3bet_key = f'SBD_{_dk}_vs{_op}_3BET'
                _in_call = _hs in (ranges or {}).get(_call_key, set())
                _in_3bet = _hs in (ranges or {}).get(_3bet_key, set())
                _action = '3-bet' if _in_3bet else ('call' if _in_call else 'defend')
                _sb_missed_gated.append({
                    'id': h['id'], 'cards': _hs, 'opener': _op,
                    'stack_bb': round(_stk), 'chart': _def_key,
                    'correct_action': _action,
                    'range_note': f'{_hs} is a {_action} vs {_op} open at {_dk} ({_def_key})',
                })
        except Exception:
            pass
    facing['sb_defense_vs_lp'] = {
        'opps': sb_lp_opps, 'defend': sb_lp_defend,
        'defend_pct': _rate(sb_lp_defend, sb_lp_opps),
        'target': '30-40% defend rate vs CO/BTN open',
        'folded_hands': sb_lp_folded,
        'missed_defend_ids': _sb_lp_fold_ids[:20],
        'missed_defend_gated': _sb_missed_gated[:20],
    }

    cc_by_pos = {}
    for pos in ('UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB'):
        pos_opps = sum(1 for h in hands if h.get('position') == pos
                       and h.get('hero_faced_raise')
                       and not h.get('villain_jammed'))
        pos_cc = sum(1 for h in hands if h.get('position') == pos and h.get('cold_called'))
        if pos_opps > 0:
            cc_by_pos[pos] = {'opps': pos_opps, 'cc': pos_cc, 'pct': _rate(pos_cc, pos_opps)}
    facing['cold_call_by_pos'] = cc_by_pos

    # ----- 4-bet / 5-bet split -----
    # v7.31.1: denominator FIX. Old `fb_opps` counted "Hero faced any raise
    # and didn't fold" — that's the cold-call denom. Real 4-bet opportunity
    # is "Hero opened (was PFR) then faced a 3-bet" — only spot where Hero
    # has a 4-bet decision. Old denom inflated denom ~30% on this session.
    fb_opps_legacy = sum(1 for h in hands if h.get('hero_faced_raise') and h.get('vpip'))
    # Real opps: Hero was the original opener AND there's been at least 2 raises preflop.
    fb_opps = sum(1 for h in hands
                  if h.get('pfr') and h.get('pf_raise_count', 0) >= 2)
    hero_4bet = sum(1 for h in hands if h.get('hero_4bet_only'))
    hero_5bet = sum(1 for h in hands if h.get('hero_5bet_plus'))
    fold_to_4b_count = sum(1 for h in hands if h.get('fold_to_4bet'))
    fold_to_5b_count = sum(1 for h in hands if h.get('faced_5bet') and not h.get('vpip'))
    faced_5b_opps = sum(1 for h in hands if h.get('faced_5bet'))
    # v7.33 Bug #7 fix: separate denominators for 4-bet and 5-bet decisions.
    # Old hero_5bet_pct used fb_opps (Hero opened + faced 3-bet) which is the
    # 4-bet decision space, not the 5-bet decision space. Real 5-bet decision
    # requires Hero to have 4-bet AND faced a 5-bet.
    opps_to_5bet = sum(1 for h in hands
                        if h.get('hero_4bet_only') and h.get('faced_5bet'))
    hero_5bet_when_faced_5bet = sum(1 for h in hands
                                     if h.get('hero_4bet_only') and h.get('faced_5bet')
                                     and h.get('hero_5bet_plus'))
    # Cold 4-bet jam = Hero's first PF action is a 5-bet+ jam (no Hero 4-bet
    # preceded). Typically squeeze-jam from BB facing open + 3-bet.
    cold_4bet_jam_count = sum(1 for h in hands
                                if h.get('hero_5bet_plus') and not h.get('hero_4bet_only'))
    facing['four_five_bet'] = {
        'opps_to_4bet': fb_opps,
        'opps_to_4bet_legacy': fb_opps_legacy,  # kept for back-compat; deprecated
        'hero_4bet': hero_4bet, 'hero_4bet_pct': _rate(hero_4bet, fb_opps),
        # v7.33 Bug #7: legacy hero_5bet_pct deprecated (wrong denom). Kept as
        # _legacy alias only for back-compat. Use hero_5bet_when_faced_5bet_pct.
        'hero_5bet': hero_5bet,
        'hero_5bet_legacy_pct': _rate(hero_5bet, fb_opps),  # WRONG denom — deprecated
        'opps_to_5bet': opps_to_5bet,  # Hero 4-bet AND faced 5-bet
        'hero_5bet_when_faced_5bet': hero_5bet_when_faced_5bet,
        'hero_5bet_when_faced_5bet_pct': _rate(hero_5bet_when_faced_5bet, opps_to_5bet),
        'cold_4bet_jam_count': cold_4bet_jam_count,  # squeeze-jams from BB etc.
        'faced_5bet': faced_5b_opps,
        'fold_to_5bet': fold_to_5b_count,
        'fold_to_5bet_pct': _rate(fold_to_5b_count, faced_5b_opps),
        'fold_to_4bet': fold_to_4b_count,
    }
    # Surface real n at the top level for the report renderer (sample-size tag)
    s['hero_4bet_real_opps'] = fb_opps

    # ----- Re-steal & Fold-to-Steal -----
    bb_steal_opps = sum(1 for h in hands if h.get('faced_steal_bb'))
    fold_to_steal = sum(1 for h in hands if h.get('fold_to_steal_bb'))
    restole = sum(1 for h in hands if h.get('restole'))
    restole_opps = sum(1 for h in hands
                       if h.get('position') in ('SB', 'BB')
                       and h.get('opener_position') in ('CO', 'BTN', 'SB', 'HJ'))
    facing['steals'] = {
        'bb_face_opps': bb_steal_opps,
        'fold_to_steal': fold_to_steal,
        'fold_to_steal_pct': _rate(fold_to_steal, bb_steal_opps),
        'restole': restole, 'restole_opps': restole_opps,
        'restole_pct': _rate(restole, restole_opps),
    }

    # ----- Squeeze defense -----
    sq_opps = sum(1 for h in hands if h.get('faced_squeeze'))
    fold_to_sq = sum(1 for h in hands if h.get('folded_to_squeeze'))
    facing['squeeze_defense'] = {
        'opps': sq_opps,
        'fold': fold_to_sq, 'fold_pct': _rate(fold_to_sq, sq_opps),
    }

    # ----- Sub-15BB call jam -----
    lt15_call_opps = sum(1 for h in hands if h.get('villain_jammed')
                         and (h.get('eff_stack_bb') or 0) <= 15)
    lt15_call = sum(1 for h in hands if h.get('lt15bb_call_jam'))
    facing['lt15bb_call_jam'] = {
        'opps': lt15_call_opps,
        'calls': lt15_call,
        'pct': _rate(lt15_call, lt15_call_opps),
    }

    # ----- AFq (Aggression Frequency = (b+r) / (b+r+c+x+f)) -----
    # Counted across postflop street actions in hero_street_actions.
    aggressive_codes = {'bet', 'raise', 'cbet', 'jam', 'xr', 'xr-ai'}
    passive_codes    = {'call', 'xc', 'check', 'x', 'fold', 'xf', 'callAI', 'xc-ai'}
    agg_count = 0; pas_count = 0
    for h in hands:
        for act in (h.get('hero_street_actions') or {}).values():
            if act in aggressive_codes:
                agg_count += 1
            elif act in passive_codes:
                pas_count += 1
    afq = _rate(agg_count, agg_count + pas_count)
    s['core']['afq'] = afq
    facing['afq'] = {'aggressive': agg_count, 'passive': pas_count, 'pct': afq}

    # ----- EV bb/100 (eai_ev_adjusted-derived) -----
    # F10 (Ron 2026-05-14): bug fix — read of s['eai_ev_adjusted'] previously
    # happened BEFORE that key is populated (line ~4996 below), so pf_delta/
    # post_delta/avg_pot_proxy were always 0 → EV_bb/100 always equaled
    # actual_bb/100. Compute the EAI EV adjustment INLINE here from s['eai']
    # (which IS populated by line ~1572), then the downstream block at line
    # ~4996 just re-uses these same numbers.
    def _eai_expected_local(eai_subsection, expected_rates):
        exp_wins = 0.0; total_ct = 0; actual_wins = 0
        for bucket, rate in expected_rates.items():
            d = eai_subsection.get(bucket, {})
            ct = d.get('count', 0); won = d.get('won', 0)
            exp_wins += ct * rate; actual_wins += won; total_ct += ct
        return {
            'expected_wins': round(exp_wins, 1),
            'actual_wins': actual_wins,
            'total_spots': total_ct,
            'delta_wins': round(actual_wins - exp_wins, 1),
            'expected_win_pct': round(exp_wins / total_ct * 100, 1) if total_ct else 0,
            'actual_win_pct': round(actual_wins / total_ct * 100, 1) if total_ct else 0,
        }
    _eai_data_early = s.get('eai', {})
    # C5 fix (Ron 2026-05-14): textbook baselines (preflop 80/55/20, postflop
    # 85/50/25) were miscalibrated for Ron's pool — created systematic ~5 BB/100
    # offset in EV_gap. Replaced with empirical rates derived from 57 sessions
    # × 1,963 EAI showdowns. Preflop ahead/flip/behind were 12.9pp/6.1pp/+9.4pp
    # off textbook; postflop ahead was accurate, behind 7.9pp off. Empirical
    # rates centered at sum-of-deltas ≈ 0 across the calibration dataset.
    _PF_BASE  = {'ahead': 0.671, 'flip': 0.489, 'behind': 0.294}
    _POST_BASE = {'ahead': 0.847, 'flip': 0.50,  'behind': 0.171}  # flip kept at textbook (zero empirical samples)
    _pf_exp_early = _eai_expected_local(_eai_data_early.get('preflop', {}), _PF_BASE)
    _post_exp_early = _eai_expected_local(_eai_data_early.get('postflop', {}), _POST_BASE)
    _eai_hands_list_early = _eai_data_early.get('hands', [])
    _avg_pot_early = 0
    if _eai_hands_list_early:
        _pot_sizes = []
        for _h_summary in _eai_hands_list_early:
            _hid = _h_summary.get('id') if isinstance(_h_summary, dict) else None
            if _hid:
                _full = next((h for h in hands if h['id'] == _hid), None)
                if _full:
                    _pot_sizes.append(_full.get('stack_bb', 20))
        _avg_pot_early = round(sum(_pot_sizes) / len(_pot_sizes), 1) if _pot_sizes else 0
    pf_delta = _pf_exp_early['delta_wins']
    post_delta = _post_exp_early['delta_wins']
    avg_pot_proxy = _avg_pot_early
    # Stash for the later block (line ~4996) to reuse instead of recomputing.
    s['_eai_ev_adjusted_precompute'] = {
        'preflop': _pf_exp_early, 'postflop': _post_exp_early,
        'avg_eai_pot_bb': _avg_pot_early,
    }
    # v7.33 Bug #2 fix: actual_bb_per_100 was reading positional_pnl.OVERALL
    # which doesn't exist — always returned 0, so ev_bb_per_100 was always wrong.
    # Compute directly from hand totals (same logic as Bug #1 fix below).
    try:
        _total_net_bb = sum(h.get('net_bb', 0) for h in hands)
        actual_bb_per_100 = round(_total_net_bb / N * 100, 2) if N else 0.0
    except (TypeError, ValueError):
        actual_bb_per_100 = 0.0
    # EV bb/100 = actual minus the bb attributable to running over/under EV in all-ins
    ev_adjustment_bb = -1 * (pf_delta + post_delta) * avg_pot_proxy
    if N > 0:
        ev_bb_per_100 = round(actual_bb_per_100 + (ev_adjustment_bb / N * 100), 2)
    else:
        ev_bb_per_100 = 0.0
    s['core']['ev_bb_per_100'] = ev_bb_per_100

    # v7.33 Bug #1 fix: surface bb_per_100 into core dict directly from hand
    # net_bb totals. Was None previously because finalize step never set it on
    # core; reports had to compute manually. positional_pnl has per-position
    # rows but no OVERALL aggregate, so compute fresh here.
    s['core']['bb_per_100'] = actual_bb_per_100 if N else None

    # ----- Lift key v7.27 metrics into core for easy report/CSV access -----
    s['core']['fold_to_cbet_pct'] = facing['vs_cbet']['fold_pct']
    s['core']['call_cbet_pct'] = facing['vs_cbet']['call_pct']
    s['core']['raise_cbet_ip_pct'] = facing['vs_cbet']['raise_ip_pct']
    # v7.34 Exploit metrics (Jasper-5): IP/OOP cbet response decomposition
    # call_cbet_ip_pct  = Float Flop rate (Hero IP, called villain flop cbet)
    # raise_cbet_oop_pct = OOP check-raise rate vs villain cbet (xr_pct/of_oop denom)
    s['core']['call_cbet_ip_pct'] = facing['vs_cbet']['call_ip_pct']
    s['core']['call_cbet_ip_n'] = facing['vs_cbet']['opps_ip']
    # v7.43 (Ron 2026-05-09): point raise_cbet_oop_pct to cr_frequency.flop_pct.
    # The previous metric used vs_cbet.xr_pct_of_oop which only counted SRP
    # check-raises (because the parser sets faced_villain_cbet_flop only in
    # SRPs; 3BP/4BP cbet-faced flags are unreliable). cr_frequency.flop_pct
    # counts ALL flop check-raises across all pot types — and check-raise is
    # OOP-only by definition (Hero checked, villain bet, Hero raised), so
    # it's a clean Raise-CBet-OOP measurement.
    cr_freq = s.get('cr_frequency', {})
    s['core']['raise_cbet_oop_pct'] = cr_freq.get('flop_pct', 0)
    s['core']['raise_cbet_oop_n'] = cr_freq.get('flop_opp', 0)
    # Keep SRP-only as a separate field for back-compat / drill-down
    s['core']['raise_cbet_oop_srp_pct'] = facing['vs_cbet']['xr_pct_of_oop']
    s['core']['raise_cbet_oop_srp_n'] = facing['vs_cbet']['opps_oop']
    s['core']['fold_to_xr_pct'] = facing['xr_after_cbet']['fold_pct']
    s['core']['donk_flop_pct'] = facing['donk_lead']['flop_pct']
    s['core']['donk_turn_pct'] = facing['donk_lead']['turn_pct']
    s['core']['fold_to_donk_pct'] = facing['vs_donk']['fold_pct']
    s['core']['raise_donk_pct'] = facing['vs_donk']['raise_pct']
    s['core']['double_barrel_pct'] = facing['barrels']['double_barrel_pct']
    s['core']['triple_barrel_pct'] = facing['barrels']['triple_barrel_pct']
    s['core']['fold_to_double_barrel_pct'] = facing['vs_turn_barrel']['fold_pct']
    s['core']['cold_call_pct'] = facing['cold_call']['cc_pct']
    # v7.31 Patch 1: separately-targeted Cold Call replacements
    s['core']['cold_call_nb_pct'] = facing['cold_call_nb']['cc_pct']
    s['core']['bb_defense_vs_steal_pct'] = facing['bb_defense_vs_steal']['defend_pct']
    s['core']['bb_defense_vs_nonsteal_pct'] = facing['bb_defense_vs_nonsteal']['defend_pct']
    s['core']['sb_defense_vs_lp_pct'] = facing['sb_defense_vs_lp']['defend_pct']
    s['core']['hero_4bet_pct'] = facing['four_five_bet']['hero_4bet_pct']
    # v7.33 Bug #7: hero_5bet_pct now points to the legacy (wrong-denom) value
    # for back-compat with old session_history rows. New code should use
    # hero_5bet_when_faced_5bet_pct. Reports should NOT cite hero_5bet_pct;
    # cite hero_5bet_when_faced_5bet_pct + cold_4bet_jam_count separately.
    s['core']['hero_5bet_pct'] = facing['four_five_bet']['hero_5bet_legacy_pct']  # DEPRECATED
    s['core']['hero_5bet_when_faced_5bet_pct'] = facing['four_five_bet']['hero_5bet_when_faced_5bet_pct']
    s['core']['hero_5bet_when_faced_5bet_n'] = facing['four_five_bet']['opps_to_5bet']
    s['core']['cold_4bet_jam_count'] = facing['four_five_bet']['cold_4bet_jam_count']
    s['core']['fold_to_steal_bb_pct'] = facing['steals']['fold_to_steal_pct']
    s['core']['restole_pct'] = facing['steals']['restole_pct']
    s['core']['fold_to_squeeze_pct'] = facing['squeeze_defense']['fold_pct']
    s['core']['lt15bb_call_jam_pct'] = facing['lt15bb_call_jam']['pct']

    s['facing_action'] = facing
    # =========================================================================
    # END v7.27 BLOCK
    # =========================================================================

    # =========================================================================
    # v7.28 — preflop matrix completion + per-street c-bet/XR/bet-raise
    #         + showdown branches + river efficiency
    # =========================================================================
    f28 = {}

    def _r(num, den):
        return round(100.0 * num / den, 1) if den > 0 else 0.0

    def _avg(values):
        return round(sum(values) / len(values), 2) if values else 0.0

    # ----- VPIP/PFR ratio + True PFR -----
    pfr_pct = s['core'].get('pfr', 0)
    vpip_pct = s['core'].get('vpip', 0) or 0.0001  # avoid div0
    s['core']['vpip_pfr_ratio'] = round(pfr_pct / vpip_pct, 3) if vpip_pct else 0.0
    true_opps = sum(1 for h in hands if h.get('true_pfr_opportunity'))
    true_pfr  = sum(1 for h in hands if h.get('true_pfr_action'))
    s['core']['true_pfr_pct'] = _r(true_pfr, true_opps)
    f28['true_pfr'] = {'opps': true_opps, 'pfr': true_pfr,
                       'pct': s['core']['true_pfr_pct']}

    # ----- All-In Preflop % -----
    pf_ai = sum(1 for h in hands if h.get('pf_allin_flag'))
    s['core']['pf_allin_pct'] = _r(pf_ai, N)
    f28['pf_allin'] = {'count': pf_ai, 'pct': s['core']['pf_allin_pct']}

    # ----- 3-bet IP/OOP split -----
    threebet_ip_opps  = sum(1 for h in hands if h.get('hero_faced_raise') and h.get('hero_ip'))
    threebet_oop_opps = sum(1 for h in hands if h.get('hero_faced_raise') and not h.get('hero_ip'))
    threebet_ip  = sum(1 for h in hands if h.get('hero_3bet_ip'))
    threebet_oop = sum(1 for h in hands if h.get('hero_3bet_oop'))
    f28['threebet_split'] = {
        'ip': {'opps': threebet_ip_opps, 'count': threebet_ip,
               'pct': _r(threebet_ip, threebet_ip_opps)},
        'oop': {'opps': threebet_oop_opps, 'count': threebet_oop,
                'pct': _r(threebet_oop, threebet_oop_opps)},
    }
    s['core']['threebet_ip_pct'] = f28['threebet_split']['ip']['pct']
    s['core']['threebet_oop_pct'] = f28['threebet_split']['oop']['pct']

    # ----- Fold to 3-bet IP/OOP -----
    # B8 fix (v7.46): opps require Hero RAISED preflop (pfr=True). Old code
    # used first_in which includes limps — Hero limping then facing a raise
    # is NOT a 3-bet situation. Caused count>0 with opps=0 mismatches.
    f3b_ip_opps  = sum(1 for h in hands if h.get('hero_faced_raise')
                       and h.get('first_in') and h.get('pfr')
                       and h.get('hero_ip')
                       and h.get('pf_raise_count', 0) >= 2)
    f3b_oop_opps = sum(1 for h in hands if h.get('hero_faced_raise')
                       and h.get('first_in') and h.get('pfr')
                       and not h.get('hero_ip')
                       and h.get('pf_raise_count', 0) >= 2)
    # Counts likewise restricted to hands where Hero pfr'd
    f3b_ip  = sum(1 for h in hands if h.get('fold_to_3bet_ip') and h.get('pfr'))
    f3b_oop = sum(1 for h in hands if h.get('fold_to_3bet_oop') and h.get('pfr'))
    f28['fold_to_3bet_split'] = {
        'ip': {'opps': f3b_ip_opps, 'count': f3b_ip, 'pct': _r(f3b_ip, f3b_ip_opps)},
        'oop': {'opps': f3b_oop_opps, 'count': f3b_oop, 'pct': _r(f3b_oop, f3b_oop_opps)},
    }
    s['core']['fold_to_3bet_ip_pct'] = f28['fold_to_3bet_split']['ip']['pct']
    s['core']['fold_to_3bet_oop_pct'] = f28['fold_to_3bet_split']['oop']['pct']

    # ----- Call 3-bet (Hero opener) -----
    call3b_opps  = sum(1 for h in hands if h.get('first_in') and h.get('pfr')
                       and h.get('hero_faced_raise') and h.get('pf_raise_count', 0) >= 2)
    call3b       = sum(1 for h in hands if h.get('hero_called_3bet'))
    call3b_ip    = sum(1 for h in hands if h.get('hero_called_3bet_ip'))
    call3b_oop   = sum(1 for h in hands if h.get('hero_called_3bet_oop'))
    f28['call_3bet'] = {
        'opps': call3b_opps,
        'total': call3b, 'total_pct': _r(call3b, call3b_opps),
        'ip': call3b_ip, 'ip_pct': _r(call3b_ip, threebet_ip_opps),
        'oop': call3b_oop, 'oop_pct': _r(call3b_oop, threebet_oop_opps),
    }
    s['core']['call_3bet_pct'] = f28['call_3bet']['total_pct']

    # ----- Call 4-bet / Call 5-bet -----
    call4b_opps = sum(1 for h in hands if h.get('hero_3bet') and h.get('pf_raise_count', 0) >= 3)
    call4b      = sum(1 for h in hands if h.get('hero_called_4bet'))
    call5b_opps = sum(1 for h in hands if h.get('hero_4bet_only')
                      and h.get('pf_raise_count', 0) >= 4)
    call5b      = sum(1 for h in hands if h.get('hero_called_5bet'))
    f28['call_4bet'] = {'opps': call4b_opps, 'count': call4b, 'pct': _r(call4b, call4b_opps)}
    f28['call_5bet'] = {'opps': call5b_opps, 'count': call5b, 'pct': _r(call5b, call5b_opps)}
    s['core']['call_4bet_pct'] = f28['call_4bet']['pct']
    s['core']['call_5bet_pct'] = f28['call_5bet']['pct']

    # ----- Squeeze response -----
    sq_opps = sum(1 for h in hands if h.get('faced_squeeze'))
    sq_call = sum(1 for h in hands if h.get('called_squeeze'))
    sq_raise = sum(1 for h in hands if h.get('raised_squeeze'))
    f28['squeeze_response'] = {
        'opps': sq_opps,
        'call': sq_call, 'call_pct': _r(sq_call, sq_opps),
        'raise': sq_raise, 'raise_pct': _r(sq_raise, sq_opps),
    }
    s['core']['call_squeeze_pct'] = f28['squeeze_response']['call_pct']
    s['core']['raise_squeeze_pct'] = f28['squeeze_response']['raise_pct']

    # ----- Steal & blind combat splits -----
    bb_steal_opps = sum(1 for h in hands if h.get('faced_steal_bb'))
    call_steal_bb = sum(1 for h in hands if h.get('called_steal_bb'))
    fold_bb_sb = sum(1 for h in hands if h.get('fold_bb_to_sb_steal'))
    fold_bb_sb_opps = sum(1 for h in hands if h.get('position') == 'BB'
                          and h.get('opener_position') == 'SB'
                          and not h.get('villain_jammed'))
    fold_sb_btn = sum(1 for h in hands if h.get('fold_sb_to_btn_steal'))
    fold_sb_btn_opps = sum(1 for h in hands if h.get('position') == 'SB'
                           and h.get('opener_position') == 'BTN'
                           and not h.get('villain_jammed'))
    sb_def = sum(1 for h in hands if h.get('sb_defended_vs_steal'))
    sb_def_opps = sum(1 for h in hands if h.get('position') == 'SB'
                      and h.get('opener_position') in ('CO', 'BTN', 'HJ')
                      and not h.get('villain_jammed'))
    bb_3b_btn = sum(1 for h in hands if h.get('bb_3bet_vs_btn'))
    bb_3b_btn_opps = sum(1 for h in hands if h.get('position') == 'BB'
                         and h.get('opener_position') == 'BTN'
                         and not h.get('villain_jammed'))
    bb_3b_sb = sum(1 for h in hands if h.get('bb_3bet_vs_sb'))
    bb_3b_sb_opps = sum(1 for h in hands if h.get('position') == 'BB'
                        and h.get('opener_position') == 'SB'
                        and not h.get('villain_jammed'))
    fold_to_bb_3b = sum(1 for h in hands if h.get('hero_folded_to_bb_3bet'))
    bb_3b_face_opps = sum(1 for h in hands if h.get('hero_stole_faced_bb_3bet'))
    f28['steal_blind_combat'] = {
        'call_steal_bb': call_steal_bb, 'call_steal_bb_pct': _r(call_steal_bb, bb_steal_opps),
        'fold_bb_to_sb': fold_bb_sb, 'fold_bb_to_sb_opps': fold_bb_sb_opps,
        'fold_bb_to_sb_pct': _r(fold_bb_sb, fold_bb_sb_opps),
        'fold_sb_to_btn': fold_sb_btn, 'fold_sb_to_btn_opps': fold_sb_btn_opps,
        'fold_sb_to_btn_pct': _r(fold_sb_btn, fold_sb_btn_opps),
        'sb_defend': sb_def, 'sb_defend_opps': sb_def_opps,
        'sb_defend_pct': _r(sb_def, sb_def_opps),
        'bb_3bet_vs_btn': bb_3b_btn, 'bb_3bet_vs_btn_opps': bb_3b_btn_opps,
        'bb_3bet_vs_btn_pct': _r(bb_3b_btn, bb_3b_btn_opps),
        'bb_3bet_vs_sb': bb_3b_sb, 'bb_3bet_vs_sb_opps': bb_3b_sb_opps,
        'bb_3bet_vs_sb_pct': _r(bb_3b_sb, bb_3b_sb_opps),
        'fold_to_bb_3bet': fold_to_bb_3b, 'fold_to_bb_3bet_opps': bb_3b_face_opps,
        'fold_to_bb_3bet_pct': _r(fold_to_bb_3b, bb_3b_face_opps),
    }
    s['core']['call_steal_bb_pct'] = f28['steal_blind_combat']['call_steal_bb_pct']
    s['core']['fold_bb_to_sb_pct'] = f28['steal_blind_combat']['fold_bb_to_sb_pct']
    s['core']['fold_sb_to_btn_pct'] = f28['steal_blind_combat']['fold_sb_to_btn_pct']
    s['core']['sb_defend_pct'] = f28['steal_blind_combat']['sb_defend_pct']
    s['core']['bb_3bet_vs_btn_pct'] = f28['steal_blind_combat']['bb_3bet_vs_btn_pct']
    s['core']['bb_3bet_vs_sb_pct'] = f28['steal_blind_combat']['bb_3bet_vs_sb_pct']
    s['core']['fold_to_bb_3bet_pct'] = f28['steal_blind_combat']['fold_to_bb_3bet_pct']

    # ----- C-Bet response by street: Turn / River (extends v7.27 flop) -----
    turn_face_opps = sum(1 for h in hands if h.get('faced_villain_bet_turn'))
    turn_fold = sum(1 for h in hands if h.get('fold_to_villain_bet_turn'))
    turn_call = sum(1 for h in hands if h.get('called_villain_bet_turn'))
    turn_raise = sum(1 for h in hands if h.get('raised_villain_bet_turn'))
    river_face_opps = sum(1 for h in hands if h.get('faced_villain_bet_river'))
    river_fold = sum(1 for h in hands if h.get('fold_to_villain_bet_river'))
    river_call = sum(1 for h in hands if h.get('called_villain_bet_river'))
    river_raise = sum(1 for h in hands if h.get('raised_villain_bet_river'))
    f28['vs_villain_bet_by_street'] = {
        'turn': {'opps': turn_face_opps, 'fold': turn_fold,
                 'fold_pct': _r(turn_fold, turn_face_opps),
                 'call': turn_call, 'call_pct': _r(turn_call, turn_face_opps),
                 'raise': turn_raise, 'raise_pct': _r(turn_raise, turn_face_opps)},
        'river': {'opps': river_face_opps, 'fold': river_fold,
                  'fold_pct': _r(river_fold, river_face_opps),
                  'call': river_call, 'call_pct': _r(river_call, river_face_opps),
                  'raise': river_raise, 'raise_pct': _r(river_raise, river_face_opps)},
    }
    s['core']['fold_to_villain_bet_turn_pct'] = f28['vs_villain_bet_by_street']['turn']['fold_pct']
    s['core']['fold_to_villain_bet_river_pct'] = f28['vs_villain_bet_by_street']['river']['fold_pct']

    # ----- C-Bet by pot type -----
    # v8.19.0 Chapter D (PHF-004): same legal-opportunity gate as the texture counters so the
    # 3BP/4BP c-bet denominators never count impossible spots (terminal all-in / flop-jammed / no chips).
    cbet_3bp_opps = sum(1 for h in hands if h.get('pfr')
                        and h.get('pot_type') == '3BP'
                        and is_legal_cbet_opportunity(h))
    cbet_3bp = sum(1 for h in hands if h.get('cbet_flop_3bp'))
    # B31 fix (v7.46): cbet_4bp_opps requires Hero is the LAST preflop raiser
    # (i.e., Hero 4-bet), not just any PFR in a 4BP. Old denominator counted
    # hands where Hero 3-bet and got 4-bet by villain — Hero is NOT the
    # aggressor postflop in that case, so cbet attribution to Hero is wrong.
    # Use pf_raise_count: in a 4BP, raises=4. Hero is last raiser iff
    # Hero's last action was a raise AND pf_raise_count==4.
    cbet_4bp_opps = sum(1 for h in hands if h.get('pfr')
                        and h.get('pot_type') == '4BP'
                        and h.get('pf_raise_count', 0) == 4
                        and (h.get('pf_action') == 'raise' or
                             h.get('hero_last_pf_action') == 'raise')
                        and is_legal_cbet_opportunity(h))
    cbet_4bp = sum(1 for h in hands if h.get('cbet_flop_4bp'))
    f3bp_opps = sum(1 for h in hands if h.get('faced_villain_cbet_flop_3bp'))
    f3bp_fold = sum(1 for h in hands if h.get('fold_to_cbet_flop_3bp'))
    f4bp_opps = sum(1 for h in hands if h.get('faced_villain_cbet_flop_4bp'))
    f4bp_fold = sum(1 for h in hands if h.get('fold_to_cbet_flop_4bp'))
    # B247 (Ron review 2026-05-26): collect the per-hand id lists behind the
    # 3BP/4BP c-bet counts so VII can link to up-to-3 cbet / no-cbet example
    # hands per row. A "no-cbet" hand = Hero was PFR in the pot type with a
    # flop seen but did NOT continuation-bet (checked).
    def _cbet_lists(pot_t, cbet_flag, last_raiser_gate):
        cbet_ids, nocbet_ids = [], []
        for h in hands:
            if not (h.get('pfr') and h.get('pot_type') == pot_t
                    and is_legal_cbet_opportunity(h)):    # v8.19.0 Chapter D gate (popup ids)
                continue
            if last_raiser_gate and not (
                    h.get('pf_raise_count', 0) == 4
                    and (h.get('pf_action') == 'raise'
                         or h.get('hero_last_pf_action') == 'raise')):
                continue
            (cbet_ids if h.get(cbet_flag) else nocbet_ids).append(h['id'])
        return cbet_ids, nocbet_ids
    _cb3_ids, _ncb3_ids = _cbet_lists('3BP', 'cbet_flop_3bp', False)
    _cb4_ids, _ncb4_ids = _cbet_lists('4BP', 'cbet_flop_4bp', True)
    f28['cbet_by_pot_type'] = {
        '3BP': {'opps': cbet_3bp_opps, 'cbets': cbet_3bp, 'pct': _r(cbet_3bp, cbet_3bp_opps),
                'face_opps': f3bp_opps, 'face_fold': f3bp_fold,
                'fold_pct': _r(f3bp_fold, f3bp_opps),
                'cbet_hands': _cb3_ids, 'nocbet_hands': _ncb3_ids},
        '4BP': {'opps': cbet_4bp_opps, 'cbets': cbet_4bp, 'pct': _r(cbet_4bp, cbet_4bp_opps),
                'face_opps': f4bp_opps, 'face_fold': f4bp_fold,
                'fold_pct': _r(f4bp_fold, f4bp_opps),
                'cbet_hands': _cb4_ids, 'nocbet_hands': _ncb4_ids},
    }
    s['core']['cbet_3bp_pct'] = f28['cbet_by_pot_type']['3BP']['pct']
    s['core']['cbet_3bp_n'] = cbet_3bp
    s['core']['cbet_3bp_opps'] = cbet_3bp_opps
    s['core']['cbet_4bp_pct'] = f28['cbet_by_pot_type']['4BP']['pct']
    s['core']['cbet_4bp_n'] = cbet_4bp
    s['core']['cbet_4bp_opps'] = cbet_4bp_opps
    s['core']['fold_to_cbet_3bp_pct'] = f28['cbet_by_pot_type']['3BP']['fold_pct']
    s['core']['fold_to_cbet_3bp_n'] = f3bp_fold
    s['core']['fold_to_cbet_3bp_opps'] = f3bp_opps
    s['core']['fold_to_cbet_4bp_pct'] = f28['cbet_by_pot_type']['4BP']['fold_pct']
    s['core']['fold_to_cbet_4bp_n'] = f4bp_fold
    s['core']['fold_to_cbet_4bp_opps'] = f4bp_opps

    # ----- Multiway c-bet -----
    # v8.19.0 Chapter D: gate the multiway c-bet denominator too (was pfr+multiway_flop only — no
    # board / all-in validation, so a flop-jammed or no-chips-behind multiway pot wrongly counted).
    mw_cbet_opps = sum(1 for h in hands if h.get('pfr') and h.get('multiway_flop')
                       and is_legal_cbet_opportunity(h))
    mw_cbet = sum(1 for h in hands if h.get('cbet_flop_mw'))
    mw_face_opps = sum(1 for h in hands if h.get('faced_mw_cbet_flop'))
    mw_fold = sum(1 for h in hands if h.get('fold_to_mw_cbet'))
    f28['multiway_cbet'] = {
        'opps': mw_cbet_opps, 'cbets': mw_cbet, 'pct': _r(mw_cbet, mw_cbet_opps),
        'face_opps': mw_face_opps, 'fold': mw_fold,
        'fold_pct': _r(mw_fold, mw_face_opps),
    }
    s['core']['mw_cbet_pct'] = f28['multiway_cbet']['pct']
    s['core']['fold_to_mw_cbet_pct'] = f28['multiway_cbet']['fold_pct']

    # ----- Delayed C-Bet Turn rate -----
    # v8.19.0 Chapter D: turn-street legal-opportunity gate (board>=4 + no terminal/flop all-in + chips).
    dct_opps = sum(1 for h in hands if h.get('pfr')
                   and (h.get('hero_street_actions') or {}).get('flop') in ('x', 'xc', 'xf')
                   and is_legal_postflop_opportunity(h, 'turn'))
    dct = sum(1 for h in hands if h.get('delayed_cbet_turn'))
    f28['delayed_cbet_turn'] = {'opps': dct_opps, 'count': dct, 'pct': _r(dct, dct_opps)}
    s['core']['delayed_cbet_turn_pct'] = f28['delayed_cbet_turn']['pct']

    # ----- Probe Turn rate -----
    probe_turn_opps = sum(1 for h in hands
                          if (not h.get('pfr')) and h.get('vpip')
                          and h.get('hero_ip')
                          and (h.get('players_at_flop') or 0) == 2
                          and (h.get('hero_street_actions') or {}).get('flop') in ('x', None)
                          and not h.get('villain_bet_flop_first')
                          # v8.19.0 Chapter D: turn legal-opportunity gate (board>=4 + no terminal/
                          # flop all-in + chips behind) so the probe denominator excludes runouts.
                          and is_legal_postflop_opportunity(h, 'turn'))
    probe_turn = sum(1 for h in hands if h.get('probe_turn'))
    f28['probe_turn'] = {'opps': probe_turn_opps, 'count': probe_turn,
                         'pct': _r(probe_turn, probe_turn_opps)}
    s['core']['probe_turn_pct'] = f28['probe_turn']['pct']

    # ----- Check-Raise responses (general, not just after cbet) per street -----
    xr_responses = {}
    for st in ('flop', 'turn', 'river'):
        opps = sum(1 for h in hands if h.get(f'faced_xr_{st}'))
        fold = sum(1 for h in hands if h.get(f'fold_to_xr_{st}'))
        call = sum(1 for h in hands if h.get(f'call_xr_{st}'))
        rr   = sum(1 for h in hands if h.get(f'reraise_xr_{st}'))
        xr_responses[st] = {
            'opps': opps,
            'fold': fold, 'fold_pct': _r(fold, opps),
            'call': call, 'call_pct': _r(call, opps),
            'reraise': rr, 'reraise_pct': _r(rr, opps),
        }
    f28['xr_response_by_street'] = xr_responses

    # ----- Hero check-raise rate per street -----
    cr_by_st = {}
    for st in ('flop', 'turn', 'river'):
        # opportunity to xr = Hero checked AND villain bet
        opps = sum(1 for h in hands
                   if (h.get('hero_action_flags') or {}).get(st, {}).get('check')
                   and len([f for f in (h.get('facing_bets') or [])
                            if f and f[0] == st]) > 0)
        cr = sum(1 for h in hands if h.get(f'hero_check_raise_{st}'))
        cr_by_st[st] = {'opps': opps, 'count': cr, 'pct': _r(cr, opps)}
    f28['check_raise_by_street'] = cr_by_st

    # ----- Bet-Raise per street (completes bet-fold/bet-call/bet-raise triangle) -----
    br_by_st = {}
    for st in ('flop', 'turn', 'river'):
        opps = sum(1 for h in hands if h.get(f'bet_then_faced_raise_{st}'))
        br = sum(1 for h in hands if h.get(f'bet_raise_{st}'))
        br_by_st[st] = {'opps': opps, 'count': br, 'pct': _r(br, opps)}
    f28['bet_raise_by_street'] = br_by_st

    # ----- Showdown branch metrics -----
    cbet_flop_count_28 = sum(1 for h in hands
                             if h.get('pfr')
                             and (h.get('hero_street_actions') or {}).get('flop') == 'cbet')
    cbet_flop_sd = sum(1 for h in hands if h.get('cbet_flop_then_sd'))
    called_flop_cbet_count = sum(1 for h in hands if h.get('called_villain_cbet_flop'))
    called_flop_cbet_sd = sum(1 for h in hands if h.get('called_flop_cbet_then_sd'))
    # B253: include bet-then-call/fold composites — Hero DID bet the turn.
    cbet_turn_count = sum(1 for h in hands
                          if h.get('pfr')
                          and (h.get('hero_street_actions') or {}).get('turn') in (
                              'bet', 'jam', 'bet-call', 'bet-fold', 'bet-callAI'))
    cbet_turn_sd = sum(1 for h in hands if h.get('cbet_turn_then_sd'))
    called_river_count = sum(1 for h in hands if h.get('called_river'))
    called_river_won_sd = sum(1 for h in hands if h.get('called_river_then_won_sd'))
    raised_river_count = sum(1 for h in hands if h.get('raised_river'))
    raised_river_won_sd = sum(1 for h in hands if h.get('raised_river_then_won_sd'))
    f28['showdown_branches'] = {
        'wtsd_after_flop_cbet': {
            'opps': cbet_flop_count_28, 'sd': cbet_flop_sd,
            'pct': _r(cbet_flop_sd, cbet_flop_count_28),
        },
        'wtsd_after_calling_flop_cbet': {
            'opps': called_flop_cbet_count, 'sd': called_flop_cbet_sd,
            'pct': _r(called_flop_cbet_sd, called_flop_cbet_count),
        },
        'wtsd_after_turn_cbet': {
            'opps': cbet_turn_count, 'sd': cbet_turn_sd,
            'pct': _r(cbet_turn_sd, cbet_turn_count),
        },
        'wsd_after_calling_river': {
            'opps': called_river_count, 'won': called_river_won_sd,
            'pct': _r(called_river_won_sd, called_river_count),
        },
        'wsd_after_raising_river': {
            'opps': raised_river_count, 'won': raised_river_won_sd,
            'pct': _r(raised_river_won_sd, raised_river_count),
        },
    }
    s['core']['wtsd_after_flop_cbet_pct'] = f28['showdown_branches']['wtsd_after_flop_cbet']['pct']
    s['core']['wsd_after_calling_river_pct'] = f28['showdown_branches']['wsd_after_calling_river']['pct']

    # ----- River efficiency (avg net_bb by river action class) -----
    call_nets = [h.get('net_bb', 0) for h in hands
                 if h.get('river_action_class') == 'call'
                 and h.get('net_bb') is not None]
    bet_nets = [h.get('net_bb', 0) for h in hands
                if h.get('river_action_class') == 'bet'
                and h.get('net_bb') is not None]
    raise_nets = [h.get('net_bb', 0) for h in hands
                  if h.get('river_action_class') == 'raise'
                  and h.get('net_bb') is not None]
    f28['river_efficiency'] = {
        'call_n': len(call_nets), 'call_avg_bb': _avg(call_nets),
        'call_total_bb': round(sum(call_nets), 1) if call_nets else 0.0,
        'bet_n': len(bet_nets), 'bet_avg_bb': _avg(bet_nets),
        'bet_total_bb': round(sum(bet_nets), 1) if bet_nets else 0.0,
        'raise_n': len(raise_nets), 'raise_avg_bb': _avg(raise_nets),
        'raise_total_bb': round(sum(raise_nets), 1) if raise_nets else 0.0,
    }
    s['core']['rce_avg_bb'] = f28['river_efficiency']['call_avg_bb']
    s['core']['river_bet_avg_bb'] = f28['river_efficiency']['bet_avg_bb']
    s['core']['river_raise_avg_bb'] = f28['river_efficiency']['raise_avg_bb']

    s['facing_action_v728'] = f28
    # =========================================================================
    # END v7.28 BLOCK
    # =========================================================================

    # --- CSV ROW (ready to append to session_history) ---
    ep_rate = s['threebet_by_opener'].get('EP', {}).get('rate', '')
    lp_rate = s['threebet_by_opener'].get('LP', {}).get('rate', '')
    non_sat_mistakes = sum(1 for m in mistakes if not m.get('is_satellite'))
    top_leak_parts = []
    # PRIMARY METRICS FIRST
    # v7.22: use non-blind gap (target applies to non-blind; raw inflated by BB defense)
    if s['core']['vpip_pfr_gap_nonblind'] > 4.0:
        top_leak_parts.append(f"VPIP-PFR Gap {s['core']['vpip_pfr_gap_nonblind']}% non-blind (raw {s['core']['vpip_pfr_gap']}%)")
    if s['core']['non_sd_win'] < 25: top_leak_parts.append(f"Non-SD Win {s['core']['non_sd_win']}%")
    if s['core']['sd_aggressor_pct'] < 40: top_leak_parts.append(f"SD Aggr {s['core']['sd_aggressor_pct']}%")
    # SECONDARY
    # v7.22: guard by n — don't flag leaks on tiny samples
    if s['cbet'].get('hu_ip_opp', 0) >= 10 and s['cbet']['hu_ip_pct'] < 60:
        top_leak_parts.append('HU CBet IP')
    # v7.22 fix: SB Steal threshold corrected. open_pct at SB measures
    # pot-entry rate (limp+raise, J29). Per J29 full-ring target is
    # 85-95% (limp 80 + raise 10 = 90% pot entry).
    # v7.46 B39 fix: lowered leak threshold from <75 to <60. J29's REAL
    # lower bound is ~70% — top 70% of SB range limped/raised, bottom 30%
    # folded as junk. Old <75 threshold over-fired on sessions where Hero
    # correctly folded worse hands. Now: only flag as leak when SB pot-entry
    # is genuinely below the J29 fold-junk threshold (<60%).
    sb_fi = s['positions'].get('SB',{}).get('fi', 0)
    sb_open_pct = s['positions'].get('SB',{}).get('open_pct', 100)
    sb_clear_violations = 0
    if sb_fi:
        sb_devs = [d for d in s.get('preflop_deviations', [])
                    if d.get('pos') == 'SB' and d.get('type') == 'Missed Open'
                    and d.get('confidence') == 'CLEAR']
        sb_clear_violations = len(sb_devs)
    sb_leak_promoted = (
        (sb_fi >= 30 and sb_open_pct < 60) or
        sb_clear_violations >= 3
    )
    if sb_leak_promoted:
        top_leak_parts.append('SB Pot-Entry')
    # v7.43 (Ron 2026-05-09): apply CI-overlap promotion to BTN/CO Open
    # leaks (same pattern as HU C-Bet B39). Old logic flagged any time raw
    # open% < target floor, ignoring sample size. Now: only promote if CI
    # upper bound is BELOW target floor (statistically too tight). For tighter
    # play (open% < target floor), upper bound matters; for looser play
    # (over target ceiling), lower bound matters. These are tight-side leaks.
    import math as _m
    def _ci_upper(x, n, z=1.645):
        if not n: return 0.0
        p = x / n
        denom = 1 + z*z/n
        center = (p + z*z/(2*n)) / denom
        spread = z * _m.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
        return min(1.0, center + spread) * 100
    btn_pos = s['positions'].get('BTN', {})
    btn_fi = btn_pos.get('fi', 0)
    btn_open_pct = btn_pos.get('open_pct', 100)
    if btn_fi >= 10:
        btn_opens = btn_pos.get('opens', round(btn_open_pct * btn_fi / 100))
        ci_up = _ci_upper(btn_opens, btn_fi)
        if ci_up < 45:
            top_leak_parts.append('BTN Open')
    co_pos = s['positions'].get('CO', {})
    co_fi = co_pos.get('fi', 0)
    co_open_pct = co_pos.get('open_pct', 100)
    if co_fi >= 10:
        co_opens = co_pos.get('opens', round(co_open_pct * co_fi / 100))
        ci_up = _ci_upper(co_opens, co_fi)
        if ci_up < 25:
            top_leak_parts.append('CO Open')
    top_leak = ' + '.join(top_leak_parts[:3]) if top_leak_parts else 'None'

    csv_row = {
        'Date': s['volume']['date'],
        'Batch_ID': 'GG' + s['volume']['date'].replace('-',''),
        'Hands': N,
        # v7.33 Bug #1 fix: was '' placeholder; now sourced from core.
        'BB_per_100': s['core'].get('bb_per_100', ''),
        'VPIP': s['core']['vpip'],
        'PFR': s['core']['pfr'],
        'ThreeBet': pct(sum(d.get('3bets',0) for d in s['threebet_by_opener'].values()),
                        sum(d.get('opps',0) for d in s['threebet_by_opener'].values())),
        # ATS (v7.22 fix): scope is CO+BTN only (SB excluded because J29
        # limp-80% pulls raise-rate below target artificially). Raw kept
        # for backward compat.
        'ATS': s['core']['ats'],
        'ATS_Raw': s['core']['ats_raw'],
        'BTN_Open': s['positions'].get('BTN',{}).get('open_pct', ''),
        'CO_Open': s['positions'].get('CO',{}).get('open_pct', ''),
        'SB_Steal': s['positions'].get('SB',{}).get('open_pct', ''),
        'AF': s['core']['af'],
        'WTSD_Vol': s['showdown']['wtsd'],
        'WSD_Vol': s['showdown']['wsd'],
        # Flop C-Bet HU (v7.22 fix): split IP vs OOP. The 60-70% target
        # applies to HU IP specifically (per Quick Ref). HU OOP is "low
        # frequency by design". Blending them artificially deflates the
        # metric. Both reported; blended kept as Flop_CBet_HU_Raw.
        'Flop_CBet_HU': s['cbet']['hu_ip_pct'],
        'Flop_CBet_HU_OOP': s['cbet']['hu_oop_pct'],
        'Flop_CBet_HU_Raw': s['cbet']['hu_pct'],
        'Flop_CBet_MW': s['cbet']['mw_pct'],
        'Turn_CBet': s['cbet']['turn_pct'],
        'River_CBet': s['cbet']['river_pct'],
        # Flop Probe (v7.22 fix revision): previous metric was incoherent —
        # "probe" has a narrow poker meaning (Hero non-PFR, HU, IP, PFR
        # checked flop, Hero bets). True opps are rare (often 0/session).
        # A rate over a narrow denominator is noise.
        #
        # Replaced with integer count from the existing parser-level
        # `missed_probe` detector (which flags the specific mistake:
        # Hero in true probe spot with made hand or strong draw, checked
        # behind). This is a leak-count, not a frequency.
        #
        # The historical "Flop_Probe rate" column is deprecated — CSV
        # now carries Missed_Probe_Count for trend tracking.
        'Missed_Probe_Count': s.get('missed_probes', {}).get('count', 0),
        'Flop_Probe': '',  # deprecated, kept for CSV column stability
        'LT12BB_Errors': s['core']['lt12bb_errors'],
        'Punts_per_100': s.get('punts', {}).get('per_100', 0.0),
        'Mistakes_per_100': s['mistakes_per_100'],
        'RedLine_BB100': '',
        'Pure_Bluff_Pct': s['bluff_profile']['pure_pct'],
        'Semi_Bluff_Pct': s['bluff_profile']['semi_pct'],
        'Value_Bet_Pct': s['bluff_profile']['value_pct'],
        'ThreeBet_vs_EP': ep_rate,
        'ThreeBet_vs_LP': lp_rate,
        'Premiums_Pct': s['card_quality']['premiums_pct'],
        'Top_Leak': top_leak,
        # VPIP-PFR Gap: v7.22 fix — use non-blind version in CSV to match
        # the <4% target (which is defined for non-blind play). Raw
        # all-hands gap inflated by BB defense (legitimate defense,
        # not flatting). Raw gap kept in core for backward compat.
        'VPIP_PFR_Gap': s['core']['vpip_pfr_gap_nonblind'],
        'VPIP_PFR_Gap_Raw': s['core']['vpip_pfr_gap'],
        'WWSF': s['core']['wwsf'],
        'Non_SD_Win': s['core']['non_sd_win'],
        'SD_Aggressor': s['core']['sd_aggressor_pct'],
        'Caller_IP_Flop_Agg': s['core']['caller_ip_flop_agg'],
        'IP_Stab_Rate': s['core'].get('ip_stab_rate', ''),
        'Flop_Lead_Rate': s['core'].get('flop_lead_rate', ''),
        'Float_Turn_Attack': s['core'].get('float_turn_attack_rate', ''),
        'Agg_React_Delta': s['core'].get('agg_react_delta', ''),
        'Draw_Overbet_Jams': s.get('draw_overbet_jams', {}).get('count', 0),
        'Passive_Passive_Jam': s.get('passive_passive_jam', {}).get('count', 0),
        'Triple_Barrel_Called_WR': s.get('triple_barrel_response', {}).get('called', {}).get('win_rate', ''),
        'Sizing_Geo_Pct': s.get('sizing_consistency', {}).get('geometric_pct', ''),
        'Small_Small_Jam_Ct': s.get('sizing_consistency', {}).get('small_small_jam_count', 0),
        'CR_Flop_Pct': s.get('cr_frequency', {}).get('flop_pct', ''),
        'CR_Total_Pct': s.get('cr_frequency', {}).get('total_pct', ''),
        'ThreeBet_BTN': s.get('threebet_by_hero_pos', {}).get('BTN', {}).get('rate', ''),
        # v7.27 NEW columns (appended at end for CSV stability)
        'AFq': s['core'].get('afq', ''),
        'EV_bb_per_100': s['core'].get('ev_bb_per_100', ''),
        'Fold_to_CBet': s['core'].get('fold_to_cbet_pct', ''),
        'Call_CBet': s['core'].get('call_cbet_pct', ''),
        'Raise_CBet_IP': s['core'].get('raise_cbet_ip_pct', ''),
        'Fold_to_XR_after_CBet': s['core'].get('fold_to_xr_pct', ''),
        'Donk_Flop': s['core'].get('donk_flop_pct', ''),
        'Donk_Turn': s['core'].get('donk_turn_pct', ''),
        'Fold_to_Donk': s['core'].get('fold_to_donk_pct', ''),
        'Raise_Donk': s['core'].get('raise_donk_pct', ''),
        'Double_Barrel': s['core'].get('double_barrel_pct', ''),
        'Triple_Barrel': s['core'].get('triple_barrel_pct', ''),
        'Fold_to_Double_Barrel': s['core'].get('fold_to_double_barrel_pct', ''),
        'Cold_Call': s['core'].get('cold_call_pct', ''),
        # v7.31 Patch 1: split-target Cold Call replacements. Cold_Call kept
        # for backward compat with historic CSVs but the split stats below
        # are the ones to compare against targets going forward.
        'Cold_Call_NB': s['core'].get('cold_call_nb_pct', ''),
        'BB_Defense_vs_Steal': s['core'].get('bb_defense_vs_steal_pct', ''),
        'BB_Defense_vs_NonSteal': s['core'].get('bb_defense_vs_nonsteal_pct', ''),
        'SB_Defense_vs_LP': s['core'].get('sb_defense_vs_lp_pct', ''),
        'Hero_4Bet': s['core'].get('hero_4bet_pct', ''),
        'Hero_5Bet': s['core'].get('hero_5bet_when_faced_5bet_pct', ''),
        'Fold_to_Steal_BB': s['core'].get('fold_to_steal_bb_pct', ''),
        'ReSteal': s['core'].get('restole_pct', ''),
        'Fold_to_Squeeze': s['core'].get('fold_to_squeeze_pct', ''),
        'LT15BB_Call_Jam': s['core'].get('lt15bb_call_jam_pct', ''),
        # v7.28 NEW columns (appended at end for CSV stability)
        'VPIP_PFR_Ratio': s['core'].get('vpip_pfr_ratio', ''),
        'True_PFR': s['core'].get('true_pfr_pct', ''),
        'PF_AllIn_Pct': s['core'].get('pf_allin_pct', ''),
        'ThreeBet_IP': s['core'].get('threebet_ip_pct', ''),
        'ThreeBet_OOP': s['core'].get('threebet_oop_pct', ''),
        'Fold_to_3Bet_IP': s['core'].get('fold_to_3bet_ip_pct', ''),
        'Fold_to_3Bet_OOP': s['core'].get('fold_to_3bet_oop_pct', ''),
        'Call_3Bet': s['core'].get('call_3bet_pct', ''),
        'Call_4Bet': s['core'].get('call_4bet_pct', ''),
        'Call_5Bet': s['core'].get('call_5bet_pct', ''),
        'Call_Squeeze': s['core'].get('call_squeeze_pct', ''),
        'Raise_Squeeze': s['core'].get('raise_squeeze_pct', ''),
        'Call_Steal_BB': s['core'].get('call_steal_bb_pct', ''),
        'Fold_BB_to_SB': s['core'].get('fold_bb_to_sb_pct', ''),
        'Fold_SB_to_BTN': s['core'].get('fold_sb_to_btn_pct', ''),
        'SB_Defend': s['core'].get('sb_defend_pct', ''),
        'BB_3Bet_vs_BTN': s['core'].get('bb_3bet_vs_btn_pct', ''),
        'BB_3Bet_vs_SB': s['core'].get('bb_3bet_vs_sb_pct', ''),
        'Fold_to_BB_3Bet': s['core'].get('fold_to_bb_3bet_pct', ''),
        'Fold_to_CBet_Turn': s['core'].get('fold_to_villain_bet_turn_pct', ''),
        'Fold_to_CBet_River': s['core'].get('fold_to_villain_bet_river_pct', ''),
        'CBet_3BP': s['core'].get('cbet_3bp_pct', ''),
        'CBet_4BP': s['core'].get('cbet_4bp_pct', ''),
        'Fold_to_CBet_3BP': s['core'].get('fold_to_cbet_3bp_pct', ''),
        'Fold_to_CBet_4BP': s['core'].get('fold_to_cbet_4bp_pct', ''),
        'MW_CBet': s['core'].get('mw_cbet_pct', ''),
        'Fold_to_MW_CBet': s['core'].get('fold_to_mw_cbet_pct', ''),
        'Delayed_CBet_Turn': s['core'].get('delayed_cbet_turn_pct', ''),
        'Probe_Turn': s['core'].get('probe_turn_pct', ''),
        'WTSD_after_Flop_CBet': s['core'].get('wtsd_after_flop_cbet_pct', ''),
        'WSD_after_Calling_River': s['core'].get('wsd_after_calling_river_pct', ''),
        'RCE_avg_bb': s['core'].get('rce_avg_bb', ''),
        'River_Bet_Avg_bb': s['core'].get('river_bet_avg_bb', ''),
        'River_Raise_Avg_bb': s['core'].get('river_raise_avg_bb', ''),
        # v7.34 NEW columns — Exploit metrics (Jasper-5).
        # Population-derived exploit angles. Strict append-only for CSV stability.
        # Phase 1: lifted IP/OOP cbet response decomposition.
        'Call_CBet_IP': s['core'].get('call_cbet_ip_pct', ''),       # = Float Flop %
        'Raise_CBet_OOP': s['core'].get('raise_cbet_oop_pct', ''),   # = check-raise rate vs cbet OOP
        # Phase 2: BB iso vs SB limp (BB exploit when SB limps after fold-around)
        'BB_Iso_SB_Limp': s['core'].get('bb_iso_sb_limp_pct', ''),   # iso% over SB limp from BB
        # Phase 3: fold-to-cbet by sizing bucket (small ≤40%, medium 40–70%, large >70%)
        # Action target: defend wider vs small, fold tighter vs large.
        'F2_Flop_CBet_Small':  (s['core'].get('fold_to_cbet_by_size') or {}).get('small', {}).get('pct', ''),
        'F2_Flop_CBet_Medium': (s['core'].get('fold_to_cbet_by_size') or {}).get('medium', {}).get('pct', ''),
        'F2_Flop_CBet_Large':  (s['core'].get('fold_to_cbet_by_size') or {}).get('large', {}).get('pct', ''),
        'F2_Turn_CBet_Small':  (s['core'].get('fold_to_turn_cbet_by_size') or {}).get('small', {}).get('pct', ''),
        'F2_Turn_CBet_Medium': (s['core'].get('fold_to_turn_cbet_by_size') or {}).get('medium', {}).get('pct', ''),
        'F2_Turn_CBet_Large':  (s['core'].get('fold_to_turn_cbet_by_size') or {}).get('large', {}).get('pct', ''),
        # Skill-index family (Ron 2026-05-16). Computed from THIS session's
        # tournaments at finish-percentile level. Mean_Logit is the raw stat;
        # FinScore_Pct / AvgPos_Pct / Skill_Index / Skill_Index_Handicap are
        # derived. Backfilled for historical rows by build_session_history_*.
        # Per-day numbers are noisy (day-to-day SD ≈ 86 ELO) — for skill
        # trajectory analysis use trailing windows in gem_meta_analysis.
        'Mean_Logit':            '',  # populated below
        'FinScore_Pct':          '',
        'AvgPos_Pct':            '',
        'Skill_Index':           '',
        'Skill_Index_Handicap':  '',
    }
    s['csv_row'] = csv_row

    # Populate skill_index columns from per-tournament data for THIS session.
    # Computed at session-day granularity (vs the trailing-window context that
    # session_skill_context provides). High noise but useful for trajectory.
    try:
        from gem_summary_parser import _compute_skill_index_for_rows
        import csv as _csv
        # Look up THIS session's tournaments from the per-tournament CSV.
        # CWD takes precedence over /mnt/project/ because the project file
        # is read-only and may lag the local working copy after appends.
        _date = s['volume'].get('date')
        # RUN-LOCAL ISOLATION (Aviel rerun): CWD only. Aviel has no
        # per-tournament financial CSV, so the Skill Index columns stay blank
        # rather than borrowing Ron's /mnt/project/ financial rows.
        per_t_paths = ['session_financials_per_tournament.csv']
        _per_t = None
        for _p in per_t_paths:
            try:
                with open(_p) as _f:
                    _per_t = [r for r in _csv.DictReader(_f) if r.get('date') == _date]
                if _per_t:  # only break if we found rows for this date
                    break
            except FileNotFoundError:
                continue
        if _per_t:
            _si = _compute_skill_index_for_rows(_per_t)
            if _si:
                csv_row['Mean_Logit']           = round(_si['mean_logit'], 3)
                csv_row['FinScore_Pct']         = _si['fin_score']
                csv_row['AvgPos_Pct']           = _si['avg_pos']
                csv_row['Skill_Index']          = _si['skill_index']
                csv_row['Skill_Index_Handicap'] = _si['handicap']
    except Exception:
        pass  # non-fatal — columns just stay empty

    # ============================================================
    # v7.14: PHASE-SLICED STATS + INTRA-SESSION ARC + EAI EV-ADJ
    # ============================================================

    # --- (A) STATS BY TOURNAMENT PHASE ---
    # Aggregate stats by phase so phase-specific leaks aren't diluted by
    # volume. Bubble/FT phases have fewer hands but the leaks there are
    # often ICM-critical.
    def _compute_phase_slice(phase_hands):
        n = len(phase_hands)
        if n == 0: return None
        vpip_c = sum(1 for h in phase_hands if h.get('vpip'))
        pfr_c = sum(1 for h in phase_hands if h.get('pfr'))
        # 3-bet opportunities: hero faced a raise as non-opener, pf_raise_count==1
        b3_opp = sum(1 for h in phase_hands if h.get('hero_faced_raise') and h.get('pf_raise_count',0)==1 and not h.get('first_in'))
        b3_ct = sum(1 for h in phase_hands if h.get('hero_3bet'))
        # F2-3B: Hero opened and faced a 3-bet
        ftb_opp = sum(1 for h in phase_hands if h.get('pfr') and h.get('pf_raise_count',0)>=2 and not h.get('hero_3bet'))
        ftb_ct = sum(1 for h in phase_hands if h.get('fold_to_3bet'))
        # Mistakes in phase — Bug fix (Ron 2026-05-30): was != 'MARGINAL'
        # which includes CLEAR + MED + unset. Headline uses == 'CLEAR' only
        # (line 4410). Align so phase-slice / tilt-detection uses the same
        # denominator as the headline mistakes_per_100.
        mistake_ids = {m['id'] for m in s.get('mistakes', []) if (m.get('confidence', '') or '').upper() == 'CLEAR'}
        mistake_c = sum(1 for h in phase_hands if h['id'] in mistake_ids)
        # Saw flop
        saw_flop = sum(1 for h in phase_hands if len(h.get('board', [])) >= 3 and h.get('vpip'))
        # WWSF (won when saw flop)
        won_saw_flop = sum(1 for h in phase_hands if len(h.get('board', [])) >= 3 and h.get('vpip') and h.get('won'))
        # Net BB + Win rate
        net_bb = round(sum(h.get('net_bb', 0) for h in phase_hands), 1)
        bb_per_100 = round(net_bb / n * 100, 2) if n else 0
        # Cbet flop: PFR, saw flop, not pf allin
        cbet_opp = sum(1 for h in phase_hands if h.get('pfr') and len(h.get('board',[]))>=3 and not h.get('pf_allin'))
        cbet_ct = sum(1 for h in phase_hands if h.get('pfr') and any(b[2]=='cbet' and b[0]=='flop' for b in h.get('hero_bets',[])))
        return {
            'n_hands': n,
            'vpip': pct(vpip_c, n),
            'pfr': pct(pfr_c, n),
            'three_bet': pct(b3_ct, b3_opp),
            'three_bet_opps': b3_opp,
            'fold_to_3bet': pct(ftb_ct, ftb_opp),
            'cbet_flop': pct(cbet_ct, cbet_opp),
            'wwsf': pct(won_saw_flop, saw_flop),
            'saw_flop': saw_flop,
            'mistakes': mistake_c,
            'mistakes_per_100': round(mistake_c / n * 100, 2) if n else 0,
            'net_bb': net_bb,
            'bb_per_100': bb_per_100,
        }

    phase_groups = defaultdict(list)
    for h in hands:
        phase_groups[h.get('tournament_phase', 'unknown')].append(h)
    s['stats_by_phase'] = {
        phase: _compute_phase_slice(ph_hands)
        for phase, ph_hands in phase_groups.items()
        if _compute_phase_slice(ph_hands) is not None
    }
    # Overall benchmarks for comparison (so report can flag phase deviations)
    s['stats_by_phase']['_overall'] = {
        'vpip': s['core']['vpip'],
        'pfr': s['core']['pfr'],
        'mistakes_per_100': s['mistakes_per_100'],
        'bb_per_100': round(sum(h.get('net_bb',0) for h in hands)/N*100, 2) if N else 0,
    }

    # --- (B) INTRA-SESSION ARC (tilt / fatigue detection) ---
    # Split session into 4 quartiles by hand order (or by time if available).
    # A mistake rate that doubles from Q1→Q4 is a tilt signal.
    # Using hand index is robust; hand_time can vary widely (multi-table).
    if N >= 20:  # need reasonable volume to quartile meaningfully
        quartile_size = N // 4
        # B179 (Ron 2026-05-25): sort by (hand_ts_date, hand_time) - the
        # in-file timestamp's TRUE calendar date + time. `date` is stored as
        # the constant filename-derived session date (v7.36 Bug #2 fix), so
        # a (date, hand_time) sort degenerated to hand_time only and post-
        # midnight hands (00:xx) wrapped ahead of the 20:xx evening hands
        # (the "00:00:02 -> 20:28" bug). GG hand-ids are NOT globally
        # monotonic in time (id blocks are per-tournament, ranges overlap),
        # so they cannot order the session either. hand_ts_date is the only
        # field that is per-hand-correct and chronological.
        chrono_hands = sorted(hands, key=lambda h: (
            h.get('hand_ts_date') or h.get('date') or '',
            h.get('hand_time') or ''))
        quartiles = []
        # Bug fix (Ron 2026-05-30): align with headline CLEAR-only filter
        mistake_ids_all = {m['id'] for m in s.get('mistakes', []) if (m.get('confidence', '') or '').upper() == 'CLEAR'}
        # B177 (Ron 2026-05-25): per-quartile cEV. BB/100 does NOT aggregate
        # across an MTT session (a stack built cheap then busted expensive
        # reads BB-positive on a chip loss) - the whole report's spine is
        # cEV for exactly that reason, so the arc must carry it too. Per
        # quartile: Sigma over resolved hands of net_chips / tournament start.
        _arc_starts = {}
        try:
            from gem_cev import compute_cev_per_stack
            _arc_ptc = compute_cev_per_stack(hands)
            _arc_starts = {tid: d['starting_chips']
                           for tid, d in (_arc_ptc.get('per_tournament', {}) or {}).items()
                           if isinstance(d, dict) and d.get('starting_chips')}
        except Exception:
            _arc_starts = {}

        def _q_cev(q_hands):
            """(cev_sum, n_resolved) for a quartile - chips/start spine unit."""
            cs, nr = 0.0, 0
            for hh in q_hands:
                tid = hh.get('tournament_id') or hh.get('tournament')
                start = _arc_starts.get(tid)
                if not start:
                    continue
                cs += ((hh.get('net_bb') or 0) * (hh.get('bb_blind') or 0)) / start
                nr += 1
            return cs, nr
        for q in range(4):
            start = q * quartile_size
            end = (q+1) * quartile_size if q < 3 else N
            q_hands = chrono_hands[start:end]
            q_n = len(q_hands)
            if q_n == 0: continue
            q_mistakes = sum(1 for h in q_hands if h['id'] in mistake_ids_all)
            q_vpip = sum(1 for h in q_hands if h.get('vpip'))
            q_net = round(sum(h.get('net_bb', 0) for h in q_hands), 1)
            _q_cev_sum, _q_cev_nres = _q_cev(q_hands)
            quartiles.append({
                'quartile': q + 1,
                'n_hands': q_n,
                'mistakes': q_mistakes,
                'mistakes_per_100': round(q_mistakes / q_n * 100, 2),
                'vpip': pct(q_vpip, q_n),
                'net_bb': q_net,
                'bb_per_100': round(q_net / q_n * 100, 2),
                # B177: cEV spine - % of starting stack, summable across MTTs.
                'cev_per_stack': round(_q_cev_sum, 4),
                'cev_n_resolved': _q_cev_nres,
                'cev_per_100': (round(_q_cev_sum / _q_cev_nres * 100, 2)
                                if _q_cev_nres else None),
                'first_hand_id': q_hands[0]['id'] if q_hands else '',
                'last_hand_id': q_hands[-1]['id'] if q_hands else '',
                'first_time': q_hands[0].get('hand_time', ''),
                'last_time': q_hands[-1].get('hand_time', ''),
            })
        # Tilt flag: Q4 mistakes/100 is >=2x Q1 with n>=20 per quartile
        tilt_flag = False
        tilt_note = ''
        if len(quartiles) == 4 and all(q['n_hands'] >= 20 for q in quartiles):
            q1_rate = quartiles[0]['mistakes_per_100']
            q4_rate = quartiles[3]['mistakes_per_100']
            if q4_rate >= 2 * max(q1_rate, 0.5):  # guard against div by zero
                tilt_flag = True
                tilt_note = f"Q4 mistakes/100 ({q4_rate}) is {round(q4_rate/max(q1_rate,0.1),1)}x Q1 ({q1_rate}) — possible tilt/fatigue window"
        s['intra_session_arc'] = {
            'quartiles': quartiles,
            'tilt_flag': tilt_flag,
            'tilt_note': tilt_note,
        }
    else:
        s['intra_session_arc'] = {'quartiles': [], 'tilt_flag': False, 'tilt_note': 'insufficient volume'}

    # --- (B2) BLIND-SPOT AUDIT (B178) — random sample of un-flagged hands ---
    s['blindspot_audit'] = _compute_blindspot_audit(hands, s)

    # --- (C) EAI EV-ADJUSTED P&L ---
    # F10 (Ron 2026-05-14): values precomputed at line ~4180 (so the earlier
    # EV bb/100 block can use them). Reuse here to avoid double-work.
    # Expected rates from GEM_Quick_Reference v7.14:
    #   Preflop: ahead 80%, flip 55%, behind 20%
    #   Postflop: ahead 85%, flip 50%, behind 25%
    _pre = s.get('_eai_ev_adjusted_precompute')
    if _pre:
        pf_exp = _pre['preflop']
        post_exp = _pre['postflop']
        avg_eai_pot_bb = _pre['avg_eai_pot_bb']
    else:
        # Fallback path (shouldn't fire post-F10, kept for safety)
        def _eai_expected(eai_subsection, expected_rates):
            """eai_subsection = {'ahead': {count, won, pct}, ...}"""
            exp_wins = 0.0
            total_ct = 0
            actual_wins = 0
            for bucket, rate in expected_rates.items():
                d = eai_subsection.get(bucket, {})
                ct = d.get('count', 0)
                won = d.get('won', 0)
                exp_wins += ct * rate
                actual_wins += won
                total_ct += ct
            return {
                'expected_wins': round(exp_wins, 1),
                'actual_wins': actual_wins,
                'total_spots': total_ct,
                'delta_wins': round(actual_wins - exp_wins, 1),
                'expected_win_pct': round(exp_wins / total_ct * 100, 1) if total_ct else 0,
                'actual_win_pct': round(actual_wins / total_ct * 100, 1) if total_ct else 0,
            }
        eai_data = s.get('eai', {})
        # C5 fix: empirical baselines (see early block at line ~4203 for derivation)
        pf_exp = _eai_expected(eai_data.get('preflop', {}), {'ahead': 0.671, 'flip': 0.489, 'behind': 0.294})
        post_exp = _eai_expected(eai_data.get('postflop', {}), {'ahead': 0.847, 'flip': 0.50, 'behind': 0.171})
        eai_hands_list = eai_data.get('hands', [])
        avg_eai_pot_bb = 0
        if eai_hands_list:
            pot_sizes = []
            for h_summary in eai_hands_list:
                hid = h_summary.get('id') if isinstance(h_summary, dict) else None
                if hid:
                    full = next((h for h in hands if h['id'] == hid), None)
                    if full:
                        pot_sizes.append(full.get('stack_bb', 20))
            avg_eai_pot_bb = round(sum(pot_sizes) / len(pot_sizes), 1) if pot_sizes else 0
    s['eai_ev_adjusted'] = {
        'preflop': pf_exp,
        'postflop': post_exp,
        'avg_eai_pot_bb': avg_eai_pot_bb,
        'approx_bb_variance_pf': round(pf_exp['delta_wins'] * avg_eai_pot_bb, 1) if avg_eai_pot_bb else 0,
        'approx_bb_variance_post': round(post_exp['delta_wins'] * avg_eai_pot_bb, 1) if avg_eai_pot_bb else 0,
        'note': 'approx_bb_variance uses avg stack as pot proxy; directional only, not precise EV',
        # v8.12.8 (handover Issue 2): equity-method stamp — 'phevaluator'
        # only when every all-in bucket came from computed equity; the
        # renderer marks True EV approximate otherwise.
        'equity_method': ('phevaluator'
                          if (_HAS_EAI_EQUITY and
                              not s.get('eai', {}).get('heuristic_fallback_n', 0))
                          else ('mixed' if _HAS_EAI_EQUITY else 'heuristic')),
        'heuristic_fallback_n': s.get('eai', {}).get('heuristic_fallback_n', 0),
    }

    # =====================================================================
    # v7.30 QUALITY LAYER — pre-flight + learning log + version stamp
    # =====================================================================
    # Runs at the END of analyze_session so it sees the final stats. The
    # report layer should consult s['quality'] before promoting findings:
    #   - sections in s['quality']['unreliable_sections'] get ❌ marker
    #   - thin-denominator findings get ⚪ marker
    #   - learning entries get appended to gem_pipeline_learnings.csv
    # =====================================================================
    try:
        if ranges is None:
            ranges = {}
        preflight = run_preflight(s, hands, ranges, targets=targets)
        # Plausibility-gate the deviations and mistakes lists for confidence labels
        gated_findings = []
        for d in s.get('preflop_deviations', []):
            # Mark ❌ if a section is known unreliable
            unreliable = ('preflop_deviations' in ' '.join(preflight.get('unreliable_sections', [])))
            finding = {
                'rule_code': d.get('type'),
                'denominator': None,  # individual deviations don't have aggregate denom
                'unreliable': unreliable,
                'requires_context': d.get('confidence') == 'MARGINAL',
            }
            gate = plausibility_gate(finding, hands)
            d['quality_label'] = gate['confidence']
            gated_findings.append({**d, 'confidence': gate['confidence']})
        for m in s.get('mistakes', []):
            finding = {
                'rule_code': m.get('type'),
                'denominator': None,
                'requires_context': m.get('confidence') == 'MARGINAL',
            }
            gate = plausibility_gate(finding, hands)
            m['quality_label'] = gate['confidence']
            gated_findings.append({**m, 'confidence': gate['confidence']})

        learnings = end_of_run_learning(preflight, gated_findings, s)
        s['quality'] = {
            'preflight': preflight,
            'learnings': learnings,
            'version': 'v7.32',
            'note': ('All ✅ checks passed.' if preflight.get('all_ok')
                     else f'⚠️ {len(preflight.get("unreliable_sections", []))} section(s) marked ❌ unreliable.'),
        }
    except Exception as e:
        # Quality layer failure should NEVER block the analyzer. Capture and continue.
        s['quality'] = {'error': f'quality layer failed: {e}', 'version': 'v7.32'}

    # ============================================================
    # v7.32 NEW STATS + DETECTORS (per-position cbet, squeeze, RFI,
    # 4-bet-when-facing-3bet, SB limp decomposition, aggregate-mask)
    # Reads from `targets` dict loaded by load_targets(). Stores results
    # under s['core'][...] (per-position dicts) and appends deviation
    # records to s['preflop_deviations'] using detector_<...> rule codes.
    # ============================================================
    POSITIONS_NB = ('UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB')
    MIN_N_BY_POS = 10  # n-floor for per-position deviation flagging

    # ---- C1: Turn cbet by Hero position ----
    # Numerator: PFR + cbet flop + saw turn (HU, no x/r) + bet/jam turn
    # Denominator: PFR + cbet flop + saw turn HU (i.e., cbet got called, not raised)
    # We count `double_barreled` for numerator (parser-derived).
    # Denominator: PFR + cbet flop + len(board)>=4 + not faced_xr_after_cbet
    turn_cbet_by_pos = {}
    for p in POSITIONS_NB:
        ph = [h for h in hands if h.get('position') == p]
        opps = [h for h in ph if h.get('pfr')
                and (h.get('hero_street_actions') or {}).get('flop') == 'cbet'
                and len(h.get('board') or []) >= 4
                and not h.get('faced_xr_after_cbet')]
        bets = [h for h in opps if h.get('double_barreled')]
        n_opp = len(opps)
        if n_opp == 0:
            turn_cbet_by_pos[p] = {'opps': 0, 'count': 0, 'pct': 0}
        else:
            turn_cbet_by_pos[p] = {'opps': n_opp, 'count': len(bets),
                                    'pct': round(len(bets) / n_opp * 100, 1)}
    s['core']['turn_cbet_by_pos'] = turn_cbet_by_pos

    # ---- C2: River cbet by Hero position ----
    # Num: triple_barreled (PFR + cbet flop + bet turn + bet river)
    # Denom: PFR + cbet flop + bet turn + saw river HU + not faced raise on turn
    river_cbet_by_pos = {}
    for p in POSITIONS_NB:
        ph = [h for h in hands if h.get('position') == p]
        # Approx: double_barreled + saw river + not faced raise on turn (no
        # parser bool for "turn raise after Hero barrel" in current schema —
        # use absence of bet_then_faced_raise_turn as proxy).
        opps = [h for h in ph if h.get('double_barreled')
                and len(h.get('board') or []) >= 5
                and not h.get('bet_then_faced_raise_turn')]
        bets = [h for h in opps if h.get('triple_barreled')]
        n_opp = len(opps)
        if n_opp == 0:
            river_cbet_by_pos[p] = {'opps': 0, 'count': 0, 'pct': 0}
        else:
            river_cbet_by_pos[p] = {'opps': n_opp, 'count': len(bets),
                                     'pct': round(len(bets) / n_opp * 100, 1)}
    s['core']['river_cbet_by_pos'] = river_cbet_by_pos

    # ---- C3: Fold to flop cbet by Hero position ----
    # Num: faced_villain_cbet_flop + folded
    # Denom: faced_villain_cbet_flop
    f2cb_by_pos = {}
    for p in POSITIONS_NB:
        ph = [h for h in hands if h.get('position') == p]
        opps = [h for h in ph if h.get('faced_villain_cbet_flop')]
        folds = [h for h in opps if h.get('fold_to_villain_cbet_flop')]
        n_opp = len(opps)
        if n_opp == 0:
            f2cb_by_pos[p] = {'opps': 0, 'count': 0, 'pct': 0}
        else:
            f2cb_by_pos[p] = {'opps': n_opp, 'count': len(folds),
                              'pct': round(len(folds) / n_opp * 100, 1)}
    s['core']['fold_to_cbet_by_pos'] = f2cb_by_pos

    # ---- v7.34: Fold-to-cbet by SIZING BUCKET (Jasper exploits #1 + #3) ----
    # Population under-thinks sizing → fold rate vs small barrels is
    # systematically too high (cheap to call, attack with floats), and fold
    # rate vs large barrels too low (population polarizes correctly here, so
    # sticky calls bleed). Buckets:
    #   small  ≤ 40% pot  — block-bet / range cbet, defend wide
    #   medium 40–70% pot — merged middle-strength zone (M20)
    #   large  > 70% pot  — polarized; population is more value-heavy here
    # Source: facing_bets entry [(street, %pot, hero_action), ...] from parser.
    def _sz_bucket(pct_pot):
        if pct_pot is None: return None
        if pct_pot <= 40: return 'small'
        if pct_pot <= 70: return 'medium'
        return 'large'

    def _empty_size_buckets():
        return {b: {'opps': 0, 'folds': 0, 'pct': 0} for b in ('small', 'medium', 'large')}

    # Flop fold-to-cbet by sizing bucket
    f2cb_by_size = _empty_size_buckets()
    for h in hands:
        if not h.get('faced_villain_cbet_flop'): continue
        flop_facing = [f for f in (h.get('facing_bets') or []) if f and f[0] == 'flop']
        if not flop_facing: continue  # Hero raised → no facing_bets entry; not a fold/call decision
        bucket = _sz_bucket(flop_facing[0][1])
        if bucket is None: continue
        f2cb_by_size[bucket]['opps'] += 1
        # FEAT-D: collect fold/call IDs per sizing bucket
        if h.get('fold_to_villain_cbet_flop'):
            f2cb_by_size[bucket]['folds'] += 1
            f2cb_by_size[bucket].setdefault('fold_ids', []).append(h.get('id', ''))
        else:
            f2cb_by_size[bucket].setdefault('call_ids', []).append(h.get('id', ''))
    for b, v in f2cb_by_size.items():
        v['pct'] = round(v['folds'] / v['opps'] * 100, 1) if v['opps'] else 0
        for _ik in ('fold_ids', 'call_ids'):
            if _ik in v:
                v[_ik] = v[_ik][:20]
    s['core']['fold_to_cbet_by_size'] = f2cb_by_size

    # Turn fold-to-cbet (double barrel) by sizing bucket
    f2tb_by_size = _empty_size_buckets()
    for h in hands:
        if not h.get('faced_turn_barrel'): continue
        turn_facing = [f for f in (h.get('facing_bets') or []) if f and f[0] == 'turn']
        if not turn_facing: continue
        bucket = _sz_bucket(turn_facing[0][1])
        if bucket is None: continue
        f2tb_by_size[bucket]['opps'] += 1
        if h.get('folded_to_turn_barrel'):
            f2tb_by_size[bucket]['folds'] += 1
    for b, v in f2tb_by_size.items():
        v['pct'] = round(v['folds'] / v['opps'] * 100, 1) if v['opps'] else 0
    s['core']['fold_to_turn_cbet_by_size'] = f2tb_by_size

    # ---- C4: 4-bet rate when facing 3-bet (alias for clarity + per-pos) ----
    # The aggregate is already correctly computed at facing['four_five_bet']
    # (fixed in v7.31.1); add explicit aliases and per-position decomposition.
    s['core']['hero_4bet_when_facing_3bet_pct'] = facing['four_five_bet']['hero_4bet_pct']
    s['core']['hero_4bet_when_facing_3bet_n'] = facing['four_five_bet']['opps_to_4bet']
    h4b_by_pos = {}
    for p in POSITIONS_NB:
        ph = [h for h in hands if h.get('position') == p]
        opps = [h for h in ph if h.get('pfr') and h.get('pf_raise_count', 0) >= 2]
        fours = [h for h in opps if h.get('hero_4bet_only')]
        n_opp = len(opps)
        if n_opp == 0:
            h4b_by_pos[p] = {'opps': 0, 'count': 0, 'pct': 0}
        else:
            h4b_by_pos[p] = {'opps': n_opp, 'count': len(fours),
                             'pct': round(len(fours) / n_opp * 100, 1)}
    s['core']['hero_4bet_by_pos'] = h4b_by_pos

    # ---- C5: SB limp/call/raise/fold decomposition ----
    # Build off SB pot-entry: first_in + position SB. Already tracked in
    # pos_data['SB']: opens (raise+limp), raises, limps, missed.
    sb_data = s.get('positions', {}).get('SB', {})
    sb_fi = sb_data.get('fi', 0)
    sb_raises = sb_data.get('raises', 0)
    sb_limps = sb_data.get('limps', 0)
    sb_missed = sb_data.get('missed', 0)
    # After SB limps: BB raised → Hero limp/call vs limp/raise vs limp/fold
    sb_limp_then_raised_opps = 0
    sb_limp_call = 0
    sb_limp_raise = 0
    sb_limp_fold = 0
    for h in hands:
        if h.get('position') != 'SB': continue
        if not (h.get('first_in') and h.get('vpip') and not h.get('pfr')):
            continue  # not a SB limp
        # Did BB raise? Look at hero_faced_raise + pf_raise_count >= 1
        if not h.get('hero_faced_raise'):
            continue
        sb_limp_then_raised_opps += 1
        pa = h.get('pf_action', '')
        if pa == 'fold': sb_limp_fold += 1
        elif pa in ('3bet', '4bet+', 'jam'): sb_limp_raise += 1
        elif pa in ('call',): sb_limp_call += 1
    s['core']['sb_fi_n'] = sb_fi
    s['core']['sb_raise_first_pct'] = round(sb_raises / sb_fi * 100, 1) if sb_fi else 0
    s['core']['sb_limp_open_pct'] = round(sb_limps / sb_fi * 100, 1) if sb_fi else 0
    s['core']['sb_fold_first_pct'] = round(sb_missed / sb_fi * 100, 1) if sb_fi else 0
    s['core']['sb_limp_then_raised_n'] = sb_limp_then_raised_opps
    if sb_limp_then_raised_opps:
        s['core']['sb_limp_call_pct'] = round(sb_limp_call / sb_limp_then_raised_opps * 100, 1)
        s['core']['sb_limp_raise_pct'] = round(sb_limp_raise / sb_limp_then_raised_opps * 100, 1)
        s['core']['sb_limp_fold_pct'] = round(sb_limp_fold / sb_limp_then_raised_opps * 100, 1)
    else:
        s['core']['sb_limp_call_pct'] = 0
        s['core']['sb_limp_raise_pct'] = 0
        s['core']['sb_limp_fold_pct'] = 0

    # ---- v7.34: BB iso vs SB limp (Jasper exploit #2) ----
    # Hero is BB, SB limped after everyone folded, Hero raised (iso) or
    # checked. Population-exploit metric: GG MTT pool 3-bets too rarely
    # → iso prints high frequency. Limp ranges are weak so equity
    # realization vs iso is poor for SB.
    bb_sb_limp_opps = 0
    bb_sb_limp_iso  = 0
    bb_sb_limp_check = 0
    for h in hands:
        if not h.get('bb_faced_sb_limp'): continue
        bb_sb_limp_opps += 1
        if h.get('bb_iso_sb_limp'): bb_sb_limp_iso += 1
        elif h.get('bb_checked_sb_limp'): bb_sb_limp_check += 1
    s['core']['bb_iso_sb_limp_n'] = bb_sb_limp_opps
    if bb_sb_limp_opps:
        s['core']['bb_iso_sb_limp_pct'] = round(bb_sb_limp_iso / bb_sb_limp_opps * 100, 1)
        s['core']['bb_check_sb_limp_pct'] = round(bb_sb_limp_check / bb_sb_limp_opps * 100, 1)
    else:
        s['core']['bb_iso_sb_limp_pct'] = 0
        s['core']['bb_check_sb_limp_pct'] = 0

    # ---- v7.34 LATE-STAGE CSV PATCH ----
    # The csv_row dict was constructed earlier (line ~3873) before these
    # exploit-metric core fields were populated. Patch them in now so the
    # CSV columns reflect actual values instead of '' defaults.
    # Strict append-only ordering is preserved; we're only updating values.
    if 'csv_row' in s:
        s['csv_row']['BB_Iso_SB_Limp']      = s['core'].get('bb_iso_sb_limp_pct', '')
        f2cb_sz = s['core'].get('fold_to_cbet_by_size') or {}
        f2tb_sz = s['core'].get('fold_to_turn_cbet_by_size') or {}
        s['csv_row']['F2_Flop_CBet_Small']  = f2cb_sz.get('small', {}).get('pct', '')
        s['csv_row']['F2_Flop_CBet_Medium'] = f2cb_sz.get('medium', {}).get('pct', '')
        s['csv_row']['F2_Flop_CBet_Large']  = f2cb_sz.get('large', {}).get('pct', '')
        s['csv_row']['F2_Turn_CBet_Small']  = f2tb_sz.get('small', {}).get('pct', '')
        s['csv_row']['F2_Turn_CBet_Medium'] = f2tb_sz.get('medium', {}).get('pct', '')
        s['csv_row']['F2_Turn_CBet_Large']  = f2tb_sz.get('large', {}).get('pct', '')

    # ---- C7: Squeeze rate by Hero position ----
    # Num: is_squeeze (parser-derived; Hero 3-bet w/ caller in front)
    # Denom: squeeze_opp (parser-derived; opener + caller before Hero's first PF action)
    sq_by_pos = {}
    for p in POSITIONS_NB:
        ph = [h for h in hands if h.get('position') == p]
        opps = [h for h in ph if h.get('squeeze_opp')]
        sqs = [h for h in opps if h.get('is_squeeze')]
        n_opp = len(opps)
        if n_opp == 0:
            sq_by_pos[p] = {'opps': 0, 'count': 0, 'pct': 0}
        else:
            sq_by_pos[p] = {'opps': n_opp, 'count': len(sqs),
                            'pct': round(len(sqs) / n_opp * 100, 1)}
    s['core']['squeeze_pct_by_pos'] = sq_by_pos

    # ---- C1/C2/C3/C6/C7 + C10: deviation detectors ----
    # Records appended to s['preflop_deviations'] (which already collects PF dev
    # records from check_preflop_deviations). We also accumulate a parallel
    # postflop deviation list at s['postflop_deviations_v732'] keyed by detector.
    pf_devs = s.setdefault('preflop_deviations', [])
    post_devs = s.setdefault('postflop_deviations_v732', [])
    aggregate_masking = []  # C10

    def _band_check(pct_val, lo, hi, n, min_n=MIN_N_BY_POS):
        """Return ('clear'|'marginal'|'in_band'|'low_n', delta_pp).
        delta_pp = signed distance from nearest band edge (0 if in-band)."""
        if n < min_n: return ('low_n', 0)
        if lo <= pct_val <= hi: return ('in_band', 0)
        if pct_val < lo:
            d = lo - pct_val
            return ('clear', -d) if d > (hi - lo) * 0.6 else ('marginal', -d)
        d = pct_val - hi
        return ('clear', d) if d > (hi - lo) * 0.6 else ('marginal', d)

    # C1: Turn cbet
    for p in POSITIONS_NB:
        d = turn_cbet_by_pos[p]
        if d['opps'] == 0: continue
        tgt = targets.get(f'TURN_CBET_TARGET_{p}')
        if not tgt: continue
        verdict, delta = _band_check(d['pct'], tgt[0], tgt[1], d['opps'])
        if verdict in ('clear', 'marginal'):
            post_devs.append({
                'rule': 'detector_turn_cbet_by_pos',
                'pos': p, 'pct': d['pct'], 'n': d['opps'],
                'target': f'{tgt[0]:.0f}-{tgt[1]:.0f}',
                'delta_pp': round(delta, 1), 'confidence': verdict.upper(),
            })

    # C2: River cbet
    for p in POSITIONS_NB:
        d = river_cbet_by_pos[p]
        if d['opps'] == 0: continue
        tgt = targets.get(f'RIVER_CBET_TARGET_{p}')
        if not tgt: continue
        verdict, delta = _band_check(d['pct'], tgt[0], tgt[1], d['opps'])
        if verdict in ('clear', 'marginal'):
            post_devs.append({
                'rule': 'detector_river_cbet_by_pos',
                'pos': p, 'pct': d['pct'], 'n': d['opps'],
                'target': f'{tgt[0]:.0f}-{tgt[1]:.0f}',
                'delta_pp': round(delta, 1), 'confidence': verdict.upper(),
            })

    # C3: Fold to flop cbet
    f2cb_devs_by_pos = []
    for p in POSITIONS_NB:
        d = f2cb_by_pos[p]
        if d['opps'] == 0: continue
        tgt = targets.get(f'F2CB_TARGET_{p}')
        if not tgt: continue
        verdict, delta = _band_check(d['pct'], tgt[0], tgt[1], d['opps'])
        if verdict in ('clear', 'marginal'):
            rec = {
                'rule': 'detector_fold_to_cbet_by_pos',
                'pos': p, 'pct': d['pct'], 'n': d['opps'],
                'target': f'{tgt[0]:.0f}-{tgt[1]:.0f}',
                'delta_pp': round(delta, 1), 'confidence': verdict.upper(),
            }
            post_devs.append(rec)
            f2cb_devs_by_pos.append(rec)

    # C6: RFI by position
    for p in ('UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB'):
        pos_d = s.get('positions', {}).get(p)
        if not pos_d: continue
        tgt = targets.get(f'RFI_TARGET_{p}')
        if not tgt: continue
        if p == 'SB':
            # SB target is on RAISE-only frequency per Dave's J29
            fi = pos_d.get('fi', 0)
            raises = pos_d.get('raises', 0)
            pct_val = round(raises / fi * 100, 1) if fi else 0
            n = fi
        else:
            pct_val = pos_d.get('open_pct', 0)
            n = pos_d.get('fi', 0)
        verdict, delta = _band_check(pct_val, tgt[0], tgt[1], n, min_n=15)
        if verdict in ('clear', 'marginal'):
            pf_devs.append({
                'type': 'rfi_deviation',
                'rule': 'detector_rfi_by_pos',
                'pos': p, 'pct': pct_val, 'n': n,
                'target': f'{tgt[0]:.0f}-{tgt[1]:.0f}',
                'delta_pp': round(delta, 1), 'confidence': verdict.upper(),
                'note': ('SB raise-frequent per J29' if p == 'SB' else 'depth-mixed; tighten <40bb'),
            })

    # C7: Squeeze by position
    for p in POSITIONS_NB:
        d = sq_by_pos[p]
        if d['opps'] == 0: continue
        tgt = targets.get(f'SQUEEZE_TARGET_{p}')
        if not tgt: continue
        verdict, delta = _band_check(d['pct'], tgt[0], tgt[1], d['opps'])
        if verdict in ('clear', 'marginal'):
            pf_devs.append({
                'type': 'squeeze_deviation',
                'rule': 'detector_squeeze_by_pos',
                'pos': p, 'pct': d['pct'], 'n': d['opps'],
                'target': f'{tgt[0]:.0f}-{tgt[1]:.0f}',
                'delta_pp': round(delta, 1), 'confidence': verdict.upper(),
            })

    # ---- C10: Aggregate-masking detector ----
    # When aggregate is 🟢 in-target but ≥3 positions are 🔴 out-of-target
    # for the same metric, emit a high-priority finding. This caught the
    # silent-failure pattern from the external report cross-check.
    def _aggregate_masks(metric_name, agg_pct, agg_lo, agg_hi, agg_n,
                        per_pos_devs, total_pos_evaluated):
        if agg_n < 30: return None  # too small to evaluate aggregate
        if not (agg_lo <= agg_pct <= agg_hi): return None  # aggregate not in-target
        out_of_band = [r for r in per_pos_devs
                       if r.get('confidence') in ('CLEAR', 'MARGINAL')]
        if len(out_of_band) >= 3 and total_pos_evaluated >= 5:
            return {
                'metric': metric_name,
                'aggregate_pct': agg_pct,
                'aggregate_target': f'{agg_lo:.0f}-{agg_hi:.0f}',
                'aggregate_n': agg_n,
                'positions_out_of_band': [r['pos'] for r in out_of_band],
                'n_positions_out': len(out_of_band),
                'message': (f'{metric_name} aggregate {agg_pct}% is in-target '
                           f'but {len(out_of_band)} positions are out-of-band. '
                           f'Per-position picture is hidden by the headline.'),
            }
        return None

    # Run aggregate-masking on Fold to Cbet (the canonical example)
    f2cb_agg = s['core'].get('fold_to_cbet_pct', 0) or 0
    f2cb_agg_n = facing['vs_cbet'].get('opps', 0)
    n_pos_with_data = sum(1 for p in POSITIONS_NB if f2cb_by_pos[p]['opps'] >= MIN_N_BY_POS)
    am = _aggregate_masks('fold_to_cbet', f2cb_agg, 50, 60, f2cb_agg_n,
                           f2cb_devs_by_pos, n_pos_with_data)
    if am: aggregate_masking.append(am)

    # Run aggregate-masking on Turn Cbet (use vague aggregate target 50-60%)
    # Compute aggregate turn cbet from already-computed per-pos data.
    tc_total_opps = sum(d['opps'] for d in turn_cbet_by_pos.values())
    tc_total_bets = sum(d['count'] for d in turn_cbet_by_pos.values())
    tc_agg_pct = round(tc_total_bets / tc_total_opps * 100, 1) if tc_total_opps else 0
    tc_devs = [r for r in post_devs if r['rule'] == 'detector_turn_cbet_by_pos']
    n_tc_pos = sum(1 for p in POSITIONS_NB if turn_cbet_by_pos[p]['opps'] >= MIN_N_BY_POS)
    am = _aggregate_masks('turn_cbet', tc_agg_pct, 47, 57, tc_total_opps,
                           tc_devs, n_tc_pos)
    if am: aggregate_masking.append(am)

    s['aggregate_masking'] = aggregate_masking

    # v7.41 — MDA v9 frequency-test pass. Runs LAST so it sees the fully
    # populated csv_row, facing_action, and texture_gto_findings.
    try:
        import gem_mda_overlay as _mda_freq
        s['mda_frequency_signals'] = _mda_freq.find_frequency_signals(s)
    except Exception as _e:
        s['mda_frequency_signals'] = []
        s['mda_frequency_signals_error'] = f'{type(_e).__name__}: {_e}'

    # ---- BATCH 1 (#3): ANALYZER-OWNED primary_villain ----
    # Override the parser's basic opener/jammer heuristic using decision_points.
    # Key decision = last significant Hero action (last non-fold DP, or last DP).
    # The primary_villain is whoever Hero was facing at the key decision.
    for h in hands:
        dps = h.get('decision_points') or []
        if not dps:
            continue
        # Find key decision: prefer last non-fold DP, fall back to last DP
        key_dp = None
        for dp in reversed(dps):
            if dp.get('hero_action') != 'folds':
                key_dp = dp
                break
        if not key_dp:
            key_dp = dps[-1]
        # Mark it as key
        key_dp['is_key_decision'] = True
        h['key_decision_id'] = key_dp['id']
        # Set primary_villain from key decision's facing villain
        vname = key_dp.get('facing_villain_name')
        if vname:
            vdata = (h.get('villains') or {}).get(vname, {})
            h['primary_villain'] = {
                'name': vname,
                'position': vdata.get('position', key_dp.get('facing_villain_snapshot', {}).get('position', '?')),
                'stack_bb': vdata.get('stack_bb', key_dp.get('facing_villain_snapshot', {}).get('stack_bb', 0)),
                'role': key_dp.get('facing_villain_role', 'unknown'),
                'archetype': vdata.get('archetype', ''),
                'archetype_label': vdata.get('archetype_label', ''),
                'shown_cards': vdata.get('shown_cards', []),
            }
        # else: keep parser's primary_villain as fallback

    # ---- BATCH 6 (R12): POST-FOLD WHAT-IF ----
    # For showdown hands where Hero folded and villain cards are known,
    # compute hypothetical equity. Limited to educational context.
    _what_if = []
    for h in hands:
        if h.get('vpip') or not h.get('went_to_sd'):
            continue  # Hero played or no showdown
        # Hero folded preflop — check if we can see villain cards + board
        hero_cards = h.get('cards', [])
        board = h.get('board', [])
        if len(hero_cards) < 2 or len(board) < 3:
            continue
        # Check if any villain showed cards
        _shown_villains = []
        for vn, vd in (h.get('villains') or {}).items():
            if isinstance(vd, dict) and vd.get('shown_cards'):
                _shown_villains.append(vd['shown_cards'])
        if not _shown_villains:
            continue
        # Compute Hero's hypothetical equity vs shown villain on the full board
        try:
            if _HAS_EAI_EQUITY:
                _eq_r = gem_eai_equity.equity(
                    hero_cards, _shown_villains, board[:5])
                if _eq_r and _eq_r.get('hero_equity') is not None:
                    _eq = _eq_r['hero_equity']
                    _eq_pct = _eq * 100 if _eq <= 1.5 else _eq
                    if _eq_pct > 70:  # Hero would have won convincingly
                        _what_if.append({
                            'id': h.get('id', ''),
                            'hero_cards': ''.join(hero_cards),
                            'equity_pct': round(_eq_pct, 0),
                            'board': ' '.join(board),
                            'position': h.get('position', '?'),
                            'note': f"Folded {h.get('position','?')} with "
                                    f"{''.join(hero_cards)} — would have had "
                                    f"{_eq_pct:.0f}% equity on {' '.join(board[:3])}",
                        })
        except Exception:
            pass
    s['what_if_folds'] = _what_if[:10]
    if _what_if:
        print(f"  What-if folds: {len(_what_if)} hands where Hero folded "
              f"but would have had >70% equity")

    # ---- BATCH 6 (R3): PREFLOP FOLD ANALYSIS ----
    # Compute fold% by position and flag positions where Hero folds too much.
    _fold_by_pos = defaultdict(lambda: {'total': 0, 'folds': 0, 'fold_ids': []})
    for h in hands:
        pos = h.get('position', '?')
        if h.get('disconnected'):
            continue
        _fold_by_pos[pos]['total'] += 1
        if not h.get('vpip'):
            _is_bb_walk = (pos == 'BB'
                           and h.get('pf_action') == 'check'
                           and not h.get('opener_position'))
            if _is_bb_walk:
                _fold_by_pos[pos]['total'] -= 1
                continue
            _fold_by_pos[pos]['folds'] += 1
            if h.get('id') and h.get('first_in'):
                # v8.5.8: range-gate fold_ids — only include folds of hands
                # that are INSIDE the position's open range (in-range folds =
                # real evidence of over-folding; trash folds are correct).
                _of_cards = h.get('cards', [])
                _of_hs = normalize_hand(_of_cards) if len(_of_cards) >= 2 else ''
                _of_in_range = False
                if _of_hs and ranges:
                    _of_n = h.get('n_players', 8)
                    _of_chart_pos = _open_chart_pos(pos, _of_n) if pos not in ('SB', 'BB') else pos
                    _of_stk = h.get('eff_stack_bb') or h.get('stack_bb') or 30
                    _of_tier = _depth_tier_open(_of_stk)
                    _of_key = f'{_of_tier}_{_of_chart_pos}'
                    _of_chart = ranges.get(_of_key, set())
                    if _of_chart and _of_hs in _of_chart:
                        _of_in_range = True
                        _fold_by_pos[pos].setdefault('fold_range_notes', {})[h['id']] = (
                            f'{_of_hs} is inside {_of_key} — should open')
                if _of_in_range:
                    _fold_by_pos[pos]['fold_ids'].append(h['id'])
    # Expected open/defend rates by position — derived from OPEN chart widths
    # when available, falling back to hardcoded defaults.
    _expected_vpip_defaults = {
        'UTG': 12, 'UTG+1': 14, 'MP': 16, 'HJ': 20,
        'CO': 28, 'BTN': 42, 'SB': 35, 'BB': 55,
    }
    _expected_vpip = dict(_expected_vpip_defaults)
    if ranges:
        for _vp_pos in ('UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN'):
            # Average across available depth tiers for this position
            _vp_widths = []
            for _rk, _rv in ranges.items():
                if _rk.startswith('OPEN_') and _rk.endswith(f'_{_vp_pos}'):
                    _vp_widths.append(round(len(_rv) / 169 * 100, 1))
            if _vp_widths:
                _expected_vpip[_vp_pos] = round(sum(_vp_widths) / len(_vp_widths))
        # SB: use SBD total defend charts if available, else OPEN_SB_RAISE
        _sb_widths = []
        for _rk, _rv in ranges.items():
            if _rk.startswith('SBD_') and _rk.endswith('_vsBTN') and '_CALL' not in _rk and '_3BET' not in _rk and '_HF' not in _rk:
                _sb_widths.append(round(len(_rv) / 169 * 100, 1))
        if _sb_widths:
            _expected_vpip['SB'] = round(sum(_sb_widths) / len(_sb_widths))
        # BB: use BB_DEF charts averaged
        _bb_widths = []
        for _rk, _rv in ranges.items():
            if _rk.startswith('BB_DEF_vs') and 'pct' in _rk:
                _bb_widths.append(round(len(_rv) / 169 * 100, 1))
        if _bb_widths:
            _expected_vpip['BB'] = round(sum(_bb_widths) / len(_bb_widths))
    _overfold_flags = []
    for pos, data in _fold_by_pos.items():
        if data['total'] < 10:
            continue
        fold_pct = 100 * data['folds'] / data['total']
        expected_fold = 100 - _expected_vpip.get(pos, 25)
        if fold_pct > expected_fold + 10:  # folding >10pp more than expected
            _overfold_flags.append({
                'position': pos,
                'fold_pct': round(fold_pct, 1),
                'expected_fold_pct': round(expected_fold, 1),
                'excess_pp': round(fold_pct - expected_fold, 1),
                'sample': data['total'],
                'fold_ids': data['fold_ids'][:20],
                'fold_range_notes': data.get('fold_range_notes', {}),
            })
    _overfold_flags.sort(key=lambda x: -x['excess_pp'])
    s['overfold_by_position'] = _overfold_flags
    if _overfold_flags:
        print(f"  Overfold detection: {len(_overfold_flags)} positions fold "
              f">{10}pp above expected")

    # ---- BATCH 5 (0I): DETECTOR CALIBRATION DATA ----
    # Compute per-detector precision from analyst overrides (if analyst file present).
    # Persists across sessions via session_history.
    _ac_cal = rd_local.get('analyst_commentary', {}) if 'rd_local' in dir() else {}
    if not _ac_cal:
        _ac_cal = {}  # no analyst file → no calibration data this session
    _detector_cal = {}
    for m in s.get('mistakes', []):
        dtype = m.get('type', 'unknown')
        _detector_cal.setdefault(dtype, {'flagged': 0, 'confirmed': 0, 'cleared': 0})
        _detector_cal[dtype]['flagged'] += 1
        # Check if analyst cleared this hand
        hid = m.get('id', '')
        if hid in _ac_cal:
            v = _ac_cal[hid]
            if isinstance(v, dict):
                verdict = v.get('verdict', '')
                if verdict.startswith(('III.0', 'III.3', 'III.4', 'III.5', 'I.7')):
                    _detector_cal[dtype]['cleared'] += 1
                elif verdict.startswith(('III.1', 'III.2')):
                    _detector_cal[dtype]['confirmed'] += 1
    # Compute precision per detector
    for dtype, data in _detector_cal.items():
        total_reviewed = data['confirmed'] + data['cleared']
        data['precision'] = (round(data['confirmed'] / total_reviewed, 2)
                             if total_reviewed > 0 else None)
        data['status'] = ('reliable' if data['precision'] and data['precision'] >= 0.6
                          else 'noisy' if data['precision'] and data['precision'] < 0.4
                          else 'unknown')
    s['detector_calibration'] = _detector_cal

    # ---- BATCH 5 (R4): TILT / EMOTIONAL CASCADE DETECTION ----
    # Rolling 20-hand window: detect spikes in mistake density after big losses.
    _sorted_hands = sorted(hands, key=lambda h: h.get('id', ''))
    _mistake_ids_tilt = {m.get('id') for m in s.get('mistakes', [])}
    _window = 20
    _tilt_cascades = []
    for i in range(len(_sorted_hands) - _window):
        _chunk = _sorted_hands[i:i+_window]
        _n_mistakes = sum(1 for h in _chunk if h.get('id') in _mistake_ids_tilt)
        if _n_mistakes >= 4:  # 4+ mistakes in 20 hands = spike
            # Check if there was a big loss in the 5 hands before this window
            _prior = _sorted_hands[max(0, i-5):i]
            _big_loss = any(h.get('net_bb', 0) < -20 for h in _prior)
            if _big_loss:
                _trigger_hand = next((h for h in _prior if h.get('net_bb', 0) < -20), None)
                _tilt_cascades.append({
                    'window_start_id': _chunk[0].get('id', ''),
                    'trigger_id': _trigger_hand.get('id', '') if _trigger_hand else '',
                    'trigger_loss_bb': round(_trigger_hand.get('net_bb', 0), 1) if _trigger_hand else 0,
                    'mistakes_in_window': _n_mistakes,
                    'window_net_bb': round(sum(h.get('net_bb', 0) for h in _chunk), 1),
                })
    # Deduplicate overlapping windows
    _seen_triggers = set()
    _unique_cascades = []
    for tc in _tilt_cascades:
        if tc['trigger_id'] not in _seen_triggers:
            _seen_triggers.add(tc['trigger_id'])
            _unique_cascades.append(tc)
    s['tilt_cascades'] = _unique_cascades[:5]
    if _unique_cascades:
        print(f"  Tilt cascades: {len(_unique_cascades)} detected "
              f"(mistake spikes after big losses)")

    # ---- BATCH 5 (R11): STACK TRAJECTORY PER TOURNAMENT ----
    # Track stack_bb series by hand order per tournament.
    _stack_trajectories = {}
    _by_tourney_traj = defaultdict(list)
    for h in _sorted_hands:
        tid = h.get('tournament_id') or h.get('tournament', '')
        if tid and h.get('stack_bb'):
            _by_tourney_traj[tid].append({
                'id': h.get('id', ''),
                'stack_bb': round(h.get('stack_bb', 0), 1),
                'net_bb': round(h.get('net_bb', 0), 1),
            })
    for tid, entries in _by_tourney_traj.items():
        if len(entries) < 10:
            continue
        stacks = [e['stack_bb'] for e in entries]
        _peak = max(stacks)
        _valley = min(stacks)
        _peak_idx = stacks.index(_peak)
        _valley_idx = stacks.index(_valley)
        _stack_trajectories[tid] = {
            'n_hands': len(entries),
            'start_bb': stacks[0],
            'end_bb': stacks[-1],
            'peak_bb': _peak,
            'peak_hand': entries[_peak_idx]['id'],
            'valley_bb': _valley,
            'valley_hand': entries[_valley_idx]['id'],
            'biggest_gain_id': max(entries, key=lambda e: e['net_bb'])['id'],
            'biggest_loss_id': min(entries, key=lambda e: e['net_bb'])['id'],
        }
    s['stack_trajectories'] = _stack_trajectories

    # ---- BATCH 5 (ACE-4): ICM/BOUNTY RED-FLAG APPROXIMATION ----
    # Rough flags per hand — not full ICM math, just practical warnings.
    from gem_bounty import bounty_collectibility as _bounty_collectibility
    from gem_decision_snapshot import (bounty_coverage as _ds_bounty_coverage,
                                       bounty_coverage_by_opponent as _ds_cover_by_opp,
                                       bounty_aggregate as _ds_bounty_agg,
                                       hero_in_allin_confrontation as _ds_confront)
    for h in hands:
        _phase = h.get('tournament_phase', '')
        _fmt = h.get('format', '')
        _stack = h.get('stack_bb', 0) or 0
        _avg_stack = 50  # rough approximation (would need tournament-level data)
        # v8.14.1 rev-3 (Blocker 2): canonical bounty collectibility — ONE source
        # of truth shared with the coaching "bounty not collectible" card, so the
        # "bounty covers villain" flag below can never contradict it (the 73559949
        # bug). The old `_stack > (jammer_stack_bb or eff_stack_bb or 0)` FABRICATED
        # "covers": jammer_stack_bb is 0 on complex all-ins (4-bet pots), so it fell
        # back to eff_stack_bb — which is the SHORTEST table villain, NOT the all-in
        # opponent (73559949: Hero 52.7BB read "covers" off a 12.9BB shorty while a
        # 66BB villain actually covered Hero). We now trust ONLY jammer_stack_bb —
        # the one field that reliably names the all-in opponent — and return
        # 'unknown' (never a fabricated cover) when it is absent. Unknown is safe:
        # it asserts neither collectible nor not-collectible, so it can never
        # contradict the PKO audit's own cover classification.
        _is_bnt = (_fmt == 'BOUNTY' or (h.get('bounty_value_bb', 0) or 0) > 0)
        # v8.17.1 Iteration 1 (bounty cover — ONE source of truth): derive
        # collectibility from the live CONTESTING opponents at the decision, which
        # works whether Hero jammed, CALLED a jam, jammed-and-got-called, or it was
        # multiway. jammer_stack_bb only names a villain who jammed BEFORE Hero, so
        # it was 0 (-> false 'unknown') for all of those, leaving 24 hands saying
        # "cover/collectibility unresolved" when coverage was plainly knowable. We
        # gate on Hero actually being all-in; if the contesting set is unresolvable
        # we fall back to the legacy jammer read (which never fabricates a cover).
        if _is_bnt and _ds_confront(h):
            # v8.17.1 Iter-1 rev: per-opponent coverage over the REALIZED contest,
            # with a typed aggregate that supports 'mixed' (Hero covers some all-in
            # opponents but not others) — never collapsed to not_collectible. Stamp
            # the per-opponent detail + aggregate alongside the scalar.
            h['bounty_coverage_by_opponent'] = _ds_cover_by_opp(h)
            h['bounty_aggregate'] = _ds_bounty_agg(h)
            _collect = _ds_bounty_coverage(h)
            if _collect == 'unknown':
                _opp_stk = h.get('jammer_stack_bb')
                _collect = _bounty_collectibility(
                    _stack, [_opp_stk] if _opp_stk else [],
                    h.get('bounty_value_bb', 0), is_bounty=True)
        else:
            _opp_stk = h.get('jammer_stack_bb')
            _collect = _bounty_collectibility(
                _stack, [_opp_stk] if _opp_stk else [],
                h.get('bounty_value_bb', 0), is_bounty=_is_bnt)
        # h['bounty_collectible'] is the REALIZED collectibility (describes the played
        # hand). It MUST NOT drive decision-time teaching/pricing/verdicts/trust strips/
        # coaching — those consume h['decision_bounty_context'] (REV4 B2).
        h['realized_bounty_collectible'] = _collect
        h['bounty_collectible'] = _collect
        # REV3/REV4 B2: route the canonical FUTURE-BLIND decision-time bounty context
        # onto the hand the report renders (default = the reviewed all-in confrontation)
        # PLUS an action-indexed map for hands with several Hero actions, so every
        # decision-time consumer reads the SAME canonical object at the SAME index — never
        # an independently reconstructed bounty truth.
        _dbc_default = None
        if _is_bnt:
            from gem_decision_snapshot import (build_decision_bounty_context as _ds_dbc,
                                               resolve_decision_ref as _ds_ref)
            _dbc_default = _ds_dbc(h)
            h['decision_bounty_context'] = _dbc_default
            _ledger = h.get('action_ledger') or []
            _hero_nm = h.get('hero', 'Hero')
            _by_idx = {}
            for _ai, _a in enumerate(_ledger):
                if _a.get('player') == _hero_nm and _a.get('action') != 'posts':
                    _by_idx[_ai] = _ds_dbc(h, _ai)
            h['decision_bounty_context_by_action_index'] = _by_idx
        # REV6 B2: stamp the ONE canonical reviewed-decision reference (ledger-inferred,
        # future-blind) onto EVERY hand so the visible capsule / pot-odds / bounty trust
        # strip route through the SAME graded action — independent of which render path
        # (full / --quick / analyst-rerender) runs. The worklist later OVERWRITES this with
        # the candidate-kind-authoritative ref where it has one (full path renders after).
        try:
            from gem_decision_snapshot import build_reviewed_decision_ref as _ds_rdr
            h['reviewed_decision_ref'] = _ds_rdr(h)
        except Exception:
            pass
        # decision-time bounty flag (teaching: "bounty may justify wider call") comes from
        # the canonical context AT THE REVIEWED ACTION INDEX (REV7 A5) — never the hand-level
        # default (a first-in open whose LATER all-in covers a villain must NOT show the flag,
        # 84074364/83765091). Hero covers an ELIGIBLE villain (all/mixed) at the reviewed
        # action, with a real committed bounty opportunity there.
        _dbc_agg = (_dbc_default or {}).get('coverage_aggregate')
        _rdref_icm = h.get('reviewed_decision_ref') or {}
        _rev_bapp_icm = _rdref_icm.get('bounty_applicability')
        _rev_bagg_icm = _rdref_icm.get('bounty_aggregate')
        _rev_kind_icm = _rdref_icm.get('hero_action_kind')
        _icm = {
            'near_bubble': _phase in ('bubble', 'ft_bubble'),
            'final_table': _phase in ('final_table', 'ft_zone'),
            'satellite': _fmt == 'SATELLITE',
            # REV7 A5: cover at the REVIEWED action (an eligible committed bounty there)
            'bounty_covers_villain': bool(_rev_bagg_icm in ('all', 'mixed')
                                          and _rev_bapp_icm in ('exact_committed', 'exact_and_potential')),
            'hero_covered': (_stack or 0) < (h.get('jammer_stack_bb') or 0) if h.get('jammer_stack_bb') else False,
            'stack_utility': ('low' if _stack < 15 else 'high' if _stack > 80 else 'medium'),
            'icm_flag': None,
        }
        # Generate flags
        if _icm['satellite'] and _icm['stack_utility'] != 'low':
            _icm['icm_flag'] = 'Satellite — stop gambling if in qualifying position'
        elif _icm['near_bubble'] and _stack > _avg_stack * 1.5:
            _icm['icm_flag'] = 'Near bubble with big stack — ICM says fold wider than chipEV'
        elif _icm['near_bubble'] and _stack < _avg_stack * 0.5:
            _icm['icm_flag'] = 'Near bubble short — ICM pressure high, pick spots carefully'
        elif _icm['bounty_covers_villain'] and _rev_kind_icm in (
                'call_vs_jam', 'call_off', 'open_shove', 'rejam_over_live_raise',
                'overjam_with_side_pot'):
            # REV13 D: the bounty flag must name the SELECTED action, never restate a literal
            # re-jam / open-shove as a "call" (83915520 / 84990829). For a re-jam/overjam the
            # bounty widens the CONTINUE threshold before the re-jam; for a shove it widens the
            # shove range; only a genuine call gets "wider call".
            if _rev_kind_icm in ('rejam_over_live_raise', 'overjam_with_side_pot'):
                _icm['icm_flag'] = 'Bounty covers villain — bounty may widen the continue threshold before the re-jam'
            elif _rev_kind_icm == 'open_shove':
                _icm['icm_flag'] = 'Bounty covers villain — bounty may widen the open-shove range'
            else:
                _icm['icm_flag'] = 'Bounty covers villain — bounty may justify wider call'
        h['icm_context'] = _icm

    # ---- BATCH 4 (R5): SIZING-TELL DETECTION ----
    # Correlate Hero's bet sizing (% pot) with hand strength at showdown.
    # If value bets average significantly larger than bluffs, it's a tell.
    _sizing_by_strength = {'value': [], 'bluff': [], 'other': []}
    for h in hands:
        if not h.get('went_to_sd'):
            continue
        for a in (h.get('action_ledger') or []):
            if (a.get('player') == h.get('hero')
                    and a.get('action') in ('bets', 'raises')
                    and a.get('street') in ('flop', 'turn', 'river')):
                amt = a.get('amount_bb', 0)
                if amt <= 0:
                    continue
                # Classify by river action or hand strength
                ra = h.get('river_action', '')
                if ra == 'value_bet' or h.get('hand_strength', '') in (
                        'two_pair', 'trips', 'straight', 'flush', 'full_house', 'quads'):
                    _sizing_by_strength['value'].append(amt)
                elif ra in ('bluff', 'check_giveup') or h.get('hand_strength') == 'high_card':
                    _sizing_by_strength['bluff'].append(amt)
                else:
                    _sizing_by_strength['other'].append(amt)
    _val_avg = (sum(_sizing_by_strength['value']) / len(_sizing_by_strength['value'])
                if _sizing_by_strength['value'] else 0)
    _blf_avg = (sum(_sizing_by_strength['bluff']) / len(_sizing_by_strength['bluff'])
                if _sizing_by_strength['bluff'] else 0)
    _tell_gap = abs(_val_avg - _blf_avg)
    s['sizing_tell'] = {
        'value_avg_bb': round(_val_avg, 1),
        'bluff_avg_bb': round(_blf_avg, 1),
        'value_n': len(_sizing_by_strength['value']),
        'bluff_n': len(_sizing_by_strength['bluff']),
        'gap_bb': round(_tell_gap, 1),
        'is_tell': _tell_gap > 2.0 and min(len(_sizing_by_strength['value']),
                                             len(_sizing_by_strength['bluff'])) >= 5,
        'note': (f"Value bets avg {_val_avg:.1f}BB, bluffs avg {_blf_avg:.1f}BB "
                 f"(gap {_tell_gap:.1f}BB)" if _tell_gap > 2.0 else ''),
    }

    # ---- BATCH 4 (R2): LUCKY MISTAKE DETECTOR ----
    # Flag hands where Hero WON but was a significant underdog at the key decision.
    # These are "positive variance masking mistakes" — won despite -EV play.
    _lucky_mistakes = []
    for h in hands:
        if not h.get('won'):
            continue
        hid = h.get('id', '')
        # Check EAI equity — was Hero an underdog?
        _eai_h_lm = {e.get('id', ''): e for e in s.get('eai', {}).get('hands', [])}
        _e = _eai_h_lm.get(hid)
        if _e and _e.get('hero_equity') is not None:
            eq = _e['hero_equity']
            eq_pct = eq * 100 if eq <= 1.5 else eq
            # BUG-R: multiway-aware threshold. In a 3-way pot, 32% is near
            # fair share (33%), not "behind." Only flag if equity is
            # significantly below fair share (fair_share - 10pp).
            _n_ai_lm = _e.get('n_allin', 2) or 2
            _fair_lm = 100.0 / _n_ai_lm
            _threshold_lm = max(_fair_lm - 10, 20)  # never below 20%
            if eq_pct < _threshold_lm and h.get('net_bb', 0) > 5:
                _lucky_mistakes.append({
                    'id': hid, 'equity_pct': round(eq_pct, 0),
                    'net_bb': round(h.get('net_bb', 0), 1),
                    'cards': ''.join(h.get('cards', [])),
                    'position': h.get('position', '?'),
                })
    s['lucky_mistakes'] = _lucky_mistakes[:20]
    if _lucky_mistakes:
        print(f"  Lucky mistakes: {len(_lucky_mistakes)} hands won despite "
              f"<35% equity (positive variance masking errors)")

    # ---- BATCH 2 (#1): UNIVERSAL analysis_confidence ----
    # Every hand gets a confidence assessment based on what data is available.
    # This is the single schema for confirmed/candidate/noise tagging.
    for h in hands:
        _ac = {'confidence': 'LOW', 'reason_source': '', 'needs_review': True,
               'risk_flags': [], 'review_tier': 'unreviewed'}
        hid = h.get('id', '')
        _is_mistake = hid in {m.get('id') for m in s.get('mistakes', [])}
        _is_punt = hid in {p.get('id') for p in s.get('punts', {}).get('hands', [])}
        _has_eai = hid in {e.get('id', '') for e in s.get('eai', {}).get('hands', [])}
        _is_disconnected = h.get('disconnected', False)

        if _is_disconnected:
            _ac = {'confidence': 'SKIP', 'reason_source': 'disconnected',
                   'needs_review': False, 'risk_flags': ['disconnected'],
                   'review_tier': 'out_of_scope'}
        elif _is_punt:
            _ac = {'confidence': 'HIGH', 'reason_source': 'detector_punt',
                   'needs_review': True, 'risk_flags': [],
                   'review_tier': 'auto_preflop'}
        elif _is_mistake:
            _m = next((m for m in s.get('mistakes', []) if m.get('id') == hid), {})
            _conf = (_m.get('confidence', '') or '').upper()
            _ac['confidence'] = _conf if _conf in ('CLEAR', 'HIGH', 'MEDIUM') else 'MEDIUM'
            _ac['reason_source'] = f"detector_{_m.get('type', 'unknown')}"
            _ac['needs_review'] = _conf != 'CLEAR'
            _ac['review_tier'] = 'auto_preflop' if _conf == 'CLEAR' else 'candidate'
        elif _has_eai:
            _ac = {'confidence': 'MEDIUM', 'reason_source': 'eai_equity',
                   'needs_review': False, 'risk_flags': [],
                   'review_tier': 'auto_equity'}

        # Add risk flags based on hand characteristics
        if h.get('players_at_flop', 0) > 2:
            _ac['risk_flags'].append('multiway')
        if h.get('game_type', 'NLH') != 'NLH':
            _ac['risk_flags'].append('non_nlh_quarantined')
        if h.get('format') == 'BOUNTY' and not h.get('bounty_value_bb'):
            _ac['risk_flags'].append('bounty_context_missing')
        if h.get('tournament_phase') in ('bubble', 'ft_bubble'):
            _ac['risk_flags'].append('icm_not_computed')

        h['analysis_confidence'] = _ac

    # ---- BATCH 1 (#7): GAME-TYPE GATING ----
    # Remove non-NLH hands from mistake/punt stats so Hold'em detectors
    # don't corrupt non-Hold'em hands. The hands stay in the parsed set
    # (for volume counts) but are excluded from strategic analysis.
    # RC3 P0-1: compute from ALL hands (not the already-NLH-filtered `hands`, which would be empty) and
    # stamp on `s` so it is SERIALIZED into gem_stats.json and survives into report_data / --quick.
    # Every completeness + coverage owner reads this set to exclude unsupported non-NLH hands.
    _non_nlh_ids = {h.get('id') for h in all_hands if h.get('game_type', 'NLH') != 'NLH'}
    s['_non_nlh_ids'] = sorted(_non_nlh_ids)
    if _non_nlh_ids:
        _pre_m = len(s.get('mistakes', []))
        _filter_non_nlh_from_candidate_buckets(s, _non_nlh_ids)
        _post_m = len(s.get('mistakes', []))
        if _pre_m != _post_m:
            print(f"  Game-type gate: removed {_pre_m - _post_m} non-NLH "
                  f"hands from mistakes ({len(_non_nlh_ids)} non-NLH total)")

    # ---- BATCH 1: ANALYZER QA GATE ----
    try:
        from gem_qa_gate import run_analyzer_qa, print_qa_summary
        _aqa = run_analyzer_qa(s, hands)
        print_qa_summary('Analyzer', _aqa)
    except Exception as _qa_err:
        print(f"  ⚠️  Analyzer QA gate error: {_qa_err}")

    # ---- BATCH 1 (#5): EARLY CANDIDATE SNAPSHOT ----
    # Write a preliminary candidate set NOW, inside analyze_session(),
    # so it exists even if the __main__ block's enriched build fails or
    # the process is killed. The enriched build in __main__ will overwrite.
    s['_early_candidates_written'] = False
    try:
        _ec_hands_by_id = {h.get('id'): h for h in hands}
        _ec_path = f'/tmp/_early_candidates_{s["volume"]["date_range"]}.json'
        _ec = {
            'session_date': s['volume']['date'],
            'date_compact': s['volume']['date_range'],
            'early_snapshot': True,
            'mistakes': [{'id': m.get('id'), 'type': m.get('type'),
                          'confidence': m.get('confidence', '')}
                         for m in s.get('mistakes', [])],
            'punts': [{'id': p.get('id')} for p in s.get('punts', {}).get('hands', [])],
            'note': 'Preliminary — written before enriched build. '
                    'Full candidate file supersedes this.',
        }
        import json as _json_ec
        with open(_ec_path, 'w') as _ecf:
            _json_ec.dump(_ec, _ecf, indent=2, default=str)
        s['_early_candidates_written'] = True
        s['_early_candidates_path'] = _ec_path
    except Exception:
        pass

    return s
# ============================================================
# 4. SANITY CHECKS — gate before report
# ============================================================

def sanity_check(s, hands, prev_csv=None):
    alerts = []; N = s['volume']['hands']

    # 1. VPIP >= PFR
    if s['core']['pfr'] > s['core']['vpip']:
        alerts.append(f"FAIL: PFR ({s['core']['pfr']}) > VPIP ({s['core']['vpip']})")
    print(f"  OK: VPIP ({s['core']['vpip']}) >= PFR ({s['core']['pfr']})")

    # 2. Position distribution
    for p, d in s['positions'].items():
        p_pct = d['hands']/N*100
        if p_pct < 3 or p_pct > 25:
            alerts.append(f"WARN: {p} has {d['hands']} hands ({p_pct:.0f}%)")
    print(f"  OK: Position distribution checked")

    # 3. Open arithmetic
    for p in ['BTN', 'CO', 'SB']:
        if p not in s['positions']: continue
        d = s['positions'][p]
        if d['fi'] > 0 and d['opens'] + d['missed'] != d['fi']:
            alerts.append(f"FAIL: {p} opens({d['opens']}) + missed({d['missed']}) != FI({d['fi']})")
        else:
            if p == 'SB' and d.get('limps', 0) > 0:
                print(f"  OK: {p} open arithmetic: {d['raises']} raises + {d['limps']} limps + {d['missed']} folds = {d['fi']} FI")
            else:
                print(f"  OK: {p} open arithmetic: {d['opens']} + {d['missed']} = {d['fi']} FI")

    # 4. WTSD
    wtsd = s['showdown']['wtsd']
    if wtsd > 50: alerts.append(f"FAIL: WTSD {wtsd}% > 50%")
    elif wtsd < 10 and s['showdown']['saw_flop_vol'] > 50: alerts.append(f"WARN: WTSD {wtsd}% < 10%")
    else: print(f"  OK: WTSD {wtsd}%")

    # 5. River semi-bluff
    rsb = s['river_audit'].get('semi_bluff', 0)
    if rsb > 0: alerts.append(f"FAIL: {rsb} river semi-bluffs")
    else: print(f"  OK: River semi-bluff = 0")

    # 6. Premium rate
    pp = s['card_quality']['premiums_pct']
    if pp < 1.0 or pp > 10.0: alerts.append(f"WARN: Premium rate {pp}%")
    else: print(f"  OK: Premium rate {pp}%")

    # 7. Cross-session drift
    if prev_csv and os.path.exists(prev_csv):
        with open(prev_csv) as f:
            rows = list(csv.DictReader(f))
        if rows:
            prev = rows[-1]
            drift_map = {'BTN_Open': s['positions'].get('BTN',{}).get('open_pct',0),
                         'CO_Open': s['positions'].get('CO',{}).get('open_pct',0),
                         'SB_Steal': s['positions'].get('SB',{}).get('open_pct',0),
                         'Flop_CBet_HU': s['cbet']['hu_pct']}
            print(f"\n  Cross-session drift (vs {prev.get('Date','?')}):")
            for col, cur in drift_map.items():
                pv = prev.get(col, '')
                if pv:
                    try:
                        delta = cur - float(pv)
                        if abs(delta) > 20: alerts.append(f"DRIFT: {col} {delta:+.1f} pts ({pv}→{cur}%)")
                        else: print(f"    {col}: {delta:+.1f} pts")
                    except ValueError: pass

    if alerts:
        print(f"\n  {'!'*50}")
        print(f"  {len(alerts)} ALERT(S):")
        for a in alerts: print(f"    ⚠ {a}")
        print(f"  {'!'*50}")
    else:
        print(f"\n  ALL CHECKS PASSED ✓")
    return alerts




# ============================================================
# 5. MAIN — parse, analyze, check, output
# ============================================================

def _dates_contiguous(dates):
    """True if the sorted ISO date strings form a gap-free run (COR-005 SessionCoverage.contiguous)."""
    import datetime as _dt
    try:
        ds = [_dt.date.fromisoformat(d) for d in dates if d]
    except Exception:
        return False
    ds.sort()
    return all((ds[i + 1] - ds[i]).days == 1 for i in range(len(ds) - 1))


def build_date_coverage(hands, session_dir):
    """v8.16.1 Bug-1: session date-scope transparency. Reports the date span of
    the loaded session so a multi-date upload can never be silently narrowed to
    one day (the prior smoke ran only 2026-06-14 although the source zip also
    held 2026-06-13). Scans the HH .txt files and game_summaries/ in
    `session_dir` (grouped by the GG filename date YYYYMMDD) and the parsed
    `hands` (grouped by per-hand timestamp date — note GG names a file by the
    tournament-START date, so late hands can carry the next day's timestamp).

    NO filtering is applied here: every .txt found is parsed, so included == total
    and `excluded_dates` is empty unless an explicit date filter is requested
    upstream (none exists today). Returns a dict (stamped into report_data) plus a
    printable `summary_lines` list. Pure aside from os.listdir on session_dir."""
    import os as _os, re as _re
    from collections import Counter as _Counter
    _gg = _re.compile(r'GG(\d{8})')

    def _scan(folder):
        by_date = _Counter(); total = 0
        try:
            entries = _os.listdir(folder)
        except OSError:
            return by_date, total
        for f in entries:
            if f.startswith('.') or not f.lower().endswith('.txt'):
                continue
            m = _gg.search(f)
            if m:
                d = m.group(1)
                d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            else:
                d = 'unknown'
            by_date[d] += 1; total += 1
        return by_date, total

    hh_by_date, hh_total = _scan(session_dir)
    sum_by_date, sum_total = _scan(_os.path.join(session_dir, 'game_summaries'))
    hands_by_date = _Counter(h.get('date', '') for h in (hands or []) if h.get('date'))
    file_dates = sorted(d for d in (set(hh_by_date) | set(sum_by_date)) if d != 'unknown')
    included_dates = sorted(set(file_dates) | set(hands_by_date))
    cov = {
        'included_dates': included_dates,
        'excluded_dates': [],
        'filtered': False,
        'filter_reason': 'none — all dates in the session directory were included',
        'hh_files_total': hh_total, 'hh_files_included': hh_total,
        'summary_files_total': sum_total, 'summary_files_included': sum_total,
        'hh_files_by_date': dict(hh_by_date),
        'summary_files_by_date': dict(sum_by_date),
        'hands_by_date': dict(hands_by_date),
        'n_hands': sum(hands_by_date.values()),
    }
    lines = [
        "Session date coverage (no silent date filtering):",
        f"  included dates ({len(included_dates)}): {', '.join(included_dates) or '—'}",
        "  excluded dates: none — all dates included by default",
        f"  HH files included/total: {hh_total}/{hh_total} (by date: {dict(hh_by_date)})",
        f"  summary files included/total: {sum_total}/{sum_total} (by date: {dict(sum_by_date)})",
        f"  hands by date: {dict(hands_by_date)}",
        f"  filter reason: {cov['filter_reason']}",
    ]
    if len(included_dates) > 1:
        lines.append(f"  MULTI-DATE session: {len(included_dates)} dates present — "
                     "all included (no silent date filter).")
    cov['summary_lines'] = lines
    return cov


if __name__ == '__main__':
    # v7.36: support --section <Roman[,Roman,...]> for partial render.
    # Strip flag args before falling back to positional SESSION_DIR / SESSION_NAME
    # parsing so the legacy positional interface still works.
    _argv = list(sys.argv[1:])
    _section_filter = None
    if '--section' in _argv:
        _i = _argv.index('--section')
        if _i + 1 < len(_argv):
            _section_filter = [t.strip().upper() for t in _argv[_i+1].split(',')]
            del _argv[_i:_i+2]
    # Fix B (v7.99.26): --analyst-file <path> explicit analyst commentary path
    _analyst_file_override = None
    if '--analyst-file' in _argv:
        _i = _argv.index('--analyst-file')
        if _i + 1 < len(_argv):
            _analyst_file_override = _argv[_i + 1]
            del _argv[_i:_i+2]
    # Fix A (v7.99.26): --require-analyst hard-fails if analyst coverage is incomplete
    _require_analyst = False
    if '--require-analyst' in _argv:
        _argv.remove('--require-analyst')
        _require_analyst = True
    # Ron 2026-05-31: --player <name> for multi-player support.
    # Threads into report title, all output filenames, and auto-isolation.
    _player_name = None
    if '--player' in _argv:
        _i = _argv.index('--player')
        if _i + 1 < len(_argv):
            _player_name = _argv[_i + 1].strip()
            del _argv[_i:_i+2]
    # EFFICIENCY #4: --quick mode for incremental re-render.
    _quick_mode = False
    if '--quick' in _argv:
        _argv.remove('--quick')
        _quick_mode = True
    # v8.12.10: quick render now validates by default; opt out explicitly.
    global _NO_VALIDATE_RENDER
    _NO_VALIDATE_RENDER = False
    if '--no-validate-render' in _argv:
        _argv.remove('--no-validate-render')
        _NO_VALIDATE_RENDER = True
    # H3: --reanalyze mode — skip parse, redo analyze + render.
    _reanalyze_mode = False
    if '--reanalyze' in _argv:
        _argv.remove('--reanalyze')
        _reanalyze_mode = True
    # SPEC #5: --render-only mode — load all cached data, attach analyst
    # file, refresh discipline tier, render. NO hash check on analyst file.
    _render_only_mode = False
    if '--render-only' in _argv:
        _argv.remove('--render-only')
        _render_only_mode = True
    # v8.9.0-prep: --analyst-villain-file <path> for LLM analyst villain review
    # This is the reviewed worksheet, NOT the prose analyst commentary.
    # GOVERNANCE: must NOT be in HH input directory; renderer must not create facts.
    _analyst_villain_file = None
    if '--analyst-villain-file' in _argv:
        _i = _argv.index('--analyst-villain-file')
        if _i + 1 < len(_argv):
            _analyst_villain_file = _argv[_i + 1]
            del _argv[_i:_i+2]
    # v8.9.0-prep: --max-villain-candidates N (default 40)
    _max_villain_candidates = 40
    if '--max-villain-candidates' in _argv:
        _i = _argv.index('--max-villain-candidates')
        if _i + 1 < len(_argv):
            try:
                _max_villain_candidates = int(_argv[_i + 1])
            except ValueError:
                pass
            del _argv[_i:_i+2]
    # v8.12.0 P0: measurement-only coverage audit. Flag absent = this code
    # path untouched (functional-identity contract: no report changes).
    # v8.12.2 R4: lazy hand cards are DEFAULT ON (browser-QA'd). Opt out
    # with --no-lazy-hand-details; --lazy-hand-details kept for symmetry.
    if '--lazy-hand-details' in _argv:
        _argv.remove('--lazy-hand-details')
        import os as _lz_os
        _lz_os.environ['GEM_LAZY_HANDS'] = '1'
    if '--no-lazy-hand-details' in _argv:
        _argv.remove('--no-lazy-hand-details')
        import os as _lz_os2
        _lz_os2.environ['GEM_LAZY_HANDS'] = '0'
    if '--coverage-audit' in _argv:
        _argv.remove('--coverage-audit')
        import os as _ca_os
        _ca_os.environ['GEM_COVERAGE_AUDIT'] = '1'
    _resume_from_cache = False
    _cache_date_override = None
    if '--resume-from-cache' in _argv:
        _i = _argv.index('--resume-from-cache')
        _argv.remove('--resume-from-cache')
        _resume_from_cache = True
        if _i < len(_argv) and not _argv[_i].startswith('--') and _i < len(_argv):
            _cache_date_override = _argv.pop(_i)
    _profile_mode = False
    if '--profile' in _argv:
        _argv.remove('--profile')
        _profile_mode = True
    SESSION_DIR = _argv[0] if len(_argv) > 0 else '/home/claude/poker_session/'
    SESSION_NAME = _argv[1] if len(_argv) > 1 else 'session'

    # BUG-A fix: define _pname_file/_pname_display BEFORE any branch
    # that uses them (quick mode, cache keys, filenames all need these).
    _pname_file = (_player_name or 'Knockman').replace(' ', '_')
    _pname_display = _player_name or 'Knockman'

    try:
        from gem_report_draft.draft import VERSION as _PIPELINE_VER
    except Exception:
        _PIPELINE_VER = '?'
    print(f"GEM {_PIPELINE_VER} (parser v7.2) — {SESSION_DIR}")
    if _quick_mode:
        print("  ⚡ QUICK MODE — skipping parse+analyze, re-rendering from cached data")
    print("=" * 60)

    # Phase 4.6 D: wall-clock timing
    import time as _time

    # ---- EFFICIENCY #4: QUICK RE-RENDER MODE ----
    if _quick_mode:
        # _pname_file/_pname_display already defined above
        # v8.4.0: use session-slug cache paths (matching parse/analyze path)
        _q_slug = os.path.basename(os.path.normpath(SESSION_DIR)).replace(' ', '_')[:30] if SESSION_DIR else ''
        _q_suffix = f'_{_q_slug}' if _q_slug else ''
        _rd_path = f'/home/claude/gem_report_data_{_pname_file}.json'
        _hands_path = f'/home/claude/gem_hands_{_pname_file}{_q_suffix}.json'
        if not os.path.exists(_hands_path):
            _hands_path = f'/home/claude/gem_hands_{_pname_file}.json'
        _stats_path = '/home/claude/gem_stats.json'
        _missing = [p for p in [_rd_path, _hands_path, _stats_path]
                    if not os.path.exists(p)]
        if _missing:
            print(f"ERROR: --quick requires cached data. Missing: {_missing}")
            print(f"Run a full pipeline first, then use --quick for re-renders.")
            sys.exit(1)
        # Guard: verify cached data matches the requested session_dir
        import hashlib as _hl_q
        _hh_q = sorted(
            os.path.join(SESSION_DIR, f) for f in os.listdir(SESSION_DIR)
            if f.lower().endswith('.txt') and not f.startswith('.')
        ) if os.path.isdir(SESSION_DIR) else []
        _hash_q = _hl_q.md5()
        for _hf_q in _hh_q:
            try: _hash_q.update(open(_hf_q, 'rb').read())
            except Exception: pass
        # v8.12.8 QA2: the parse-cache WRITER keys the marker by player AND
        # session-dir slug (.gem_hh_hash_<player>_<slug>) — this reader used
        # the suffix-less path, so it always compared against a STALE global
        # marker and --quick false-aborted right after a successful full run
        # on the same dir. Mirror the writer's key, fall back to legacy.
        _slug_q = (os.path.basename(os.path.normpath(SESSION_DIR))
                   .replace(' ', '_')[:30] if SESSION_DIR else '')
        _hp_q = (f'/home/claude/.gem_hh_hash_{_pname_file}'
                 + (f'_{_slug_q}' if _slug_q else ''))
        if not os.path.exists(_hp_q):
            _hp_q = f'/home/claude/.gem_hh_hash_{_pname_file}'
        _ch_q = open(_hp_q).read().strip() if os.path.exists(_hp_q) else ''
        if _ch_q and _hash_q.hexdigest() != _ch_q:
            print(f"  ⚠️  --quick: cached data is from a DIFFERENT session "
                  f"(hash mismatch). Stored={_ch_q[:12]}… Recomputed={_hash_q.hexdigest()[:12]}… "
                  f"Run a full pipeline on this session first.")
            sys.exit(1)
        _t0 = _time.perf_counter()
        with open(_hands_path, encoding='utf-8') as f:
            hands = json.load(f)
        with open(_rd_path, encoding='utf-8') as f:
            report_data = json.load(f)
        with open(_stats_path, encoding='utf-8') as f:
            stats = json.load(f)
        # B142: cross-file session fingerprint check
        _fp_stats = stats.get('_session_fingerprint', {})
        _fp_rd = report_data.get('_session_fingerprint', {})
        if _fp_stats and _fp_rd:
            _fp_match = (_fp_stats.get('n_hands') == _fp_rd.get('n_hands')
                         and _fp_stats.get('first_hand_id') == _fp_rd.get('first_hand_id')
                         and _fp_stats.get('date_range') == _fp_rd.get('date_range'))
            if not _fp_match:
                print(f"  ERROR: --quick session fingerprint MISMATCH!")
                print(f"    stats:       n={_fp_stats.get('n_hands')} date={_fp_stats.get('date_range')} "
                      f"first={_fp_stats.get('first_hand_id', '')[:10]}")
                print(f"    report_data: n={_fp_rd.get('n_hands')} date={_fp_rd.get('date_range')} "
                      f"first={_fp_rd.get('first_hand_id', '')[:10]}")
                print(f"  Cached intermediates are from different sessions. "
                      f"Run a full pipeline first.")
                sys.exit(1)
        # Also verify hands count matches
        if _fp_stats and _fp_stats.get('n_hands') and len(hands) != _fp_stats['n_hands']:
            print(f"  WARNING: hands file has {len(hands)} hands but stats "
                  f"fingerprint says {_fp_stats['n_hands']}. Data may be stale.")
        # v8.12.4 (QA item 30): cache-vs-CURRENT-DIR check. The cross-file
        # check above only proves the cached trio is internally consistent —
        # a stale cache from another session is consistent with itself and
        # sailed through, rendering wrong data. Compare the fingerprint's
        # hh_hash against the hash of the session dir we just computed and
        # HARD-ABORT on mismatch (override: GEM_QUICK_ALLOW_STALE=1).
        _fp_hh = _fp_stats.get('hh_hash', '')
        if _fp_hh and _hh_q and _fp_hh != _hash_q.hexdigest():
            if os.environ.get('GEM_QUICK_ALLOW_STALE') == '1':
                print(f"  ⚠️  --quick: cache hh_hash does not match this session "
                      f"dir — PROCEEDING because GEM_QUICK_ALLOW_STALE=1.")
            else:
                print(f"  ERROR: --quick cache is from a DIFFERENT session.")
                print(f"    cache hh_hash: {_fp_hh[:12]}…  current dir: "
                      f"{_hash_q.hexdigest()[:12]}…")
                print(f"    (cache: n={_fp_stats.get('n_hands')} "
                      f"date={_fp_stats.get('date_range')})")
                print(f"  Run the full pipeline on this session first, or set "
                      f"GEM_QUICK_ALLOW_STALE=1 to override deliberately.")
                sys.exit(1)

        # Print cache info so stale data is immediately visible
        _cache_date = stats.get('volume', {}).get('date_range', '?')
        print(f"Loaded cached data in {_time.perf_counter()-_t0:.1f}s "
              f"({len(hands)} hands, player={_pname_display}, date={_cache_date})")

        # Re-resolve analyst file (this is what changed)
        _date_range = stats.get('volume', {}).get('date_range', '')
        from gem_report_data import _resolve_analyst_file
        sa_path, _sa_log = _resolve_analyst_file(_date_range, _analyst_file_override)
        if sa_path:
            with open(sa_path) as f:
                session_analysis = json.load(f)
            report_data['analyst_commentary'] = session_analysis
            print(f"  Analyst file: {sa_path} ({len(session_analysis)} entries)")
        else:
            print(f"  No analyst file found for {_date_range}")

        # BUG FIX: --quick must re-run _refresh_discipline_tier after loading
        # analyst file. Without this, stat strip carries stale pre-analyst
        # punt/mistake counts. Cheap operation (~10ms on cached data).
        from gem_report_data import (_refresh_discipline_tier,
                                      compute_report_completeness)
        _refresh_discipline_tier(report_data, stats, hands)
        print(f"  discipline_tier refreshed (punts={report_data.get('discipline_tier',{}).get('canonical_punts_count','?')}, "
              f"mistakes={report_data.get('discipline_tier',{}).get('canonical_mistakes_count','?')})")
        # v8.12.10: completeness from cached candidate need-set (candidates
        # are not re-derived in --quick; the full/resume run stamped them).
        _rc_q = compute_report_completeness(report_data, candidates=None)

        # ---- Gate B4: in analyst/release mode, VALIDATE EVERY BINDING *before* rendering or writing any
        # report file (owner blocker #2-#4/#6). Require the sealed packet AND analyst output; recompute and
        # compare the packet hash, the immutable build identity, the canonical input hashes, and the cache
        # identity derived from the ACTUAL loaded cache; validate the analyst JSON with the REAL cache_ok;
        # require complete required coverage. Any failure exits non-zero with NO report written -- never a
        # silent full-run fallback. (GEM_ANALYST_MODE=0 keeps the legacy non-analyst quick re-render.)
        _q_analyst_mode = os.environ.get('GEM_ANALYST_MODE', '1') != '0'
        if _q_analyst_mode:
            import gem_analyst_packet as _apq
            import gem_build_identity as _bidq
            from gem_input_manifest import canonical_input_hashes as _cihq
            _ap_out_q = '/mnt/user-data/outputs' if os.path.isdir('/mnt/user-data/outputs') else '/home/claude'
            _pkt_path_q = os.path.join(_ap_out_q, f'analyst_packet_{_pname_file}.json')
            _ao_path_q = os.path.join(_ap_out_q, f'analyst_packet_{_pname_file}_analyst_output.json')

            def _quick_fail(_msg):
                print(f"  ❌ --quick FAIL CLOSED (no report written): {_msg}")
                sys.exit(1)
            if not os.path.exists(_pkt_path_q):
                _quick_fail(f"sealed packet missing -- run: python gem_analyzer.py {SESSION_DIR}")
            if not os.path.exists(_ao_path_q):
                _quick_fail(f"analyst output missing ({os.path.basename(_ao_path_q)}) -- review the packet "
                            "and save the analyst JSON there")
            try:
                with open(_pkt_path_q, encoding='utf-8') as _pf:
                    _pkt_q = json.load(_pf)
            except Exception as _pe:
                _quick_fail(f"sealed packet is malformed JSON ({_pe}) -- re-run the full pipeline")
            try:
                with open(_ao_path_q, encoding='utf-8') as _af:
                    _ao_q = json.load(_af)
            except Exception as _ae:
                _quick_fail(f"analyst output is malformed JSON ({_ae}) -- fix the analyst JSON and re-run --quick")
            if not isinstance(_ao_q, dict) or not isinstance(_ao_q.get('verdicts'), list):
                _quick_fail("analyst output has no 'verdicts' array -- fix the analyst JSON and re-run --quick")
            _m_q = _pkt_q.get('manifest', {})
            if _apq.recompute_packet_hash(_pkt_q) != _m_q.get('packet_hash'):
                _quick_fail("sealed packet hash mismatch -- the packet was modified; re-run the full pipeline")
            _idy_now = _bidq.build_identity()
            _idy_pkt = _m_q.get('build_identity') or {}
            if _idy_pkt.get('build_id') and _idy_pkt.get('build_id') != _idy_now.get('build_id'):
                _quick_fail(f"build identity mismatch (packet {_idy_pkt.get('build_id')} vs runtime "
                            f"{_idy_now.get('build_id')}) -- rebuild/re-run the full pipeline")
            _inhash_now = _cihq(SESSION_DIR)
            if _m_q.get('input_hashes') and _inhash_now != _m_q.get('input_hashes'):
                _quick_fail("input files changed since the packet was sealed -- re-run the full pipeline")
            _cache_now = _apq.cache_identity_from_disk(_rd_path, _hands_path, _idy_now, _inhash_now)
            _cache_ok = (_cache_now == _m_q.get('cache_identity'))
            if not _cache_ok:
                _quick_fail("deterministic cache does not match the packet cache identity (stale cache) -- "
                            "re-run the full pipeline")
            _val_q = _apq.validate_analyst_output(_pkt_q, _ao_q, cache_ok=_cache_ok)
            if not _val_q.get('valid'):
                _quick_fail(f"analyst output invalid: {_val_q.get('errors')} -- fix the JSON and re-run --quick")
            if (_val_q.get('required_coverage') or 0) < 1.0:
                _quick_fail(f"incomplete required-decision coverage ({_val_q.get('required_coverage')}) -- "
                            "review every required decision")
            globals()['_QUICK_VALIDATED'] = {'packet_hash': _m_q.get('packet_hash'),
                                             'coverage': _val_q.get('required_coverage'), 'cache_ok': _cache_ok}
            print(f"  ✓ --quick pre-render validation PASSED (packet+analyst+cache+identity bound; "
                  f"coverage {_val_q.get('required_coverage')})")
            # ---- QA-BLOCK-001: CONSUME the validated analyst output. Merge its verdicts into the canonical
            # hand-keyed analyst_commentary, then recompute the analyst-dependent owners (completeness +
            # final-truth) BEFORE render, so the final report is analyst-integrated: the AUTO_ONLY banner
            # disappears, the reviewed count + verdict totals reconcile exactly with the JSON, and each
            # analyst verdict OVERRIDES any stale automatic nomination (final-truth analyst override).
            _commentary_q, _onepass_q = _apq.analyst_commentary_from_output(_pkt_q, _ao_q)
            report_data['analyst_commentary'] = _commentary_q
            report_data['analyst_onepass'] = _onepass_q
            _rc_q = compute_report_completeness(report_data, candidates=None)
            _refresh_discipline_tier(report_data, stats, hands)
            print(f"  ✓ analyst output integrated: state={_rc_q['state']} "
                  f"reviewed_hands={_rc_q['reviewed_hands']} verdicts={_onepass_q['verdict_counts']}")

        # Re-render
        from gem_report_draft import render_both
        date_compact = _date_range
        out_dir = '/mnt/user-data/outputs'
        if not os.path.isdir(out_dir):
            out_dir = '/home/claude'
        _t0 = _time.perf_counter()
        html_str, md_str = render_both(stats, report_data, hands,
                                        sections=_section_filter)
        _t_render = _time.perf_counter() - _t0
        if _section_filter:
            suffix = '_section_' + '_'.join(_section_filter)
            html_path = f"{out_dir}/Pokerbot_{_pname_file}_{date_compact}{suffix}.html"
            md_path = html_path.replace('.html', '.md')
        else:
            _tag_q = 'AUTO_ONLY' if _rc_q.get('state') == 'AUTO_ONLY' else ''
            html_path = _versioned_path(out_dir, 'Pokerbot', date_compact, 'html', _pname_file, tag=_tag_q)
            md_path = html_path.replace('.html', '.md')
        # B-V10 (2026-06-01): surrogate guard — match the full-path guard
        # (B4.4) so quick mode doesn't crash on emoji surrogates.
        _sq = [i for i, c in enumerate(html_str) if 0xD800 <= ord(c) <= 0xDFFF]
        if _sq:
            print(f"\n  ⚠️  SURROGATE GUARD (quick): {len(_sq)} lone surrogate(s) "
                  f"— replacing with '?'")
            html_str = ''.join('?' if 0xD800 <= ord(c) <= 0xDFFF else c
                               for c in html_str)
            md_str = ''.join('?' if 0xD800 <= ord(c) <= 0xDFFF else c
                             for c in md_str)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_str)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_str)
        print(f"\n⚡ Quick re-render in {_t_render:.1f}s")
        print(f"  HTML: {html_path} ({os.path.getsize(html_path)//1024}KB)")
        print(f"  MD:   {md_path}")
        # ---- Gate 2.2: PROVE this quick render did zero forbidden work + validate packet binding ----
        # This branch loaded cached data and rendered; it NEVER reached parse/reference/analyze/detector/
        # worklist/packet (all gated behind `if not _quick_mode`, after this sys.exit). The stage meter
        # proves it; a non-zero forbidden count is a release-blocking bug and fails closed. When the sealed
        # packet + analyst output are present, their binding is validated (fail-closed) before delivery.
        try:
            import gem_stage_meter as _sm_q
            _fcounts = _sm_q.forbidden_quick_counts()
            _ap_out_q = '/mnt/user-data/outputs' if os.path.isdir('/mnt/user-data/outputs') else '/home/claude'
            _pkt_path_q = os.path.join(_ap_out_q, f'analyst_packet_{_pname_file}.json')
            _ao_path_q = os.path.join(_ap_out_q, f'analyst_packet_{_pname_file}_analyst_output.json')
            _bind_q = {'packet_present': os.path.exists(_pkt_path_q),
                       'analyst_output_present': os.path.exists(_ao_path_q)}
            if os.path.exists(_pkt_path_q):
                import gem_analyst_packet as _apq
                with open(_pkt_path_q, encoding='utf-8') as _pf:
                    _pkt_q = json.load(_pf)
                _recomputed = _apq.recompute_packet_hash(_pkt_q)   # binds inputs/runtime/cache/contents
                _bind_q['packet_hash_matches'] = (_recomputed == (_pkt_q.get('manifest') or {}).get('packet_hash'))
                if not _bind_q['packet_hash_matches']:
                    print("  ERROR: --quick packet hash mismatch — the sealed packet was modified since the "
                          "full run. Re-run: python gem_analyzer.py <SESSION_DIR>")
                    sys.exit(1)
                if os.path.exists(_ao_path_q):
                    with open(_ao_path_q, encoding='utf-8') as _af:
                        _ao_q = json.load(_af)
                    _val_q = _apq.validate_analyst_output(_pkt_q, _ao_q, cache_ok=True)
                    _bind_q['analyst_output_valid'] = bool(_val_q.get('valid'))
                    if not _val_q.get('valid'):
                        print(f"  ERROR: --quick analyst output failed validation: {_val_q.get('errors')}. "
                              "Fix the analyst JSON, then re-run --quick.")
                        sys.exit(1)
            _tele_q = {'mode': 'quick', 'forbidden_quick_counts': _fcounts,
                       'zero_forbidden_quick_work': _sm_q.quick_is_clean(),
                       'all_stage_counts': _sm_q.snapshot(), 'binding': _bind_q}
            with open(os.path.join(_ap_out_q, f'analyst_packet_{_pname_file}_quick_stage_telemetry.json'),
                      'w', encoding='utf-8') as _tf:
                json.dump(_tele_q, _tf, indent=2, default=str)
            if not _sm_q.quick_is_clean():
                print(f"  ERROR: --quick performed FORBIDDEN work {_fcounts} — release-blocking. Aborting.")
                sys.exit(1)
            print(f"  ✓ quick stage telemetry: zero forbidden work {_fcounts} | binding={_bind_q}")
        except SystemExit:
            raise
        except Exception as _qse:
            print(f"  ⚠ quick stage telemetry skipped: {_qse}")
        _print_completeness(_rc_q, where='quick')
        # v8.12.10 (pipeline-learnings Fix 5): --quick used to SKIP all
        # validation, but the final delivered report usually comes from a
        # quick re-render — exactly where the #sec-7-4 broken anchor slipped
        # through. Run a lightweight render check by default unless the
        # operator opts out with --no-validate-render.
        if not globals().get('_NO_VALIDATE_RENDER'):
            _qv = _quick_validate_render(html_str, report_data)
            if _qv:
                print(f"\n  ⚠️  Quick render validation: {len(_qv)} issue(s)")
                for _qi in _qv[:12]:
                    print(f"     - {_qi}")
            else:
                print("\n  ✅ Quick render validation passed "
                      "(anchors + globals + financial/analyst trust).")
        # v8.14.1 consistency-fix (Blocker 1): a quick analyst re-render must
        # refresh the run manifest + run log so they AGREE with the report it just
        # produced. Previously they were left as the prior full AUTO_ONLY pass, so
        # an analyst-rendered report shipped with manifest analyst_status=AUTO_ONLY
        # and stale AUTO_ONLY output paths. Patch the existing manifest (preserving
        # input_files / n_hands / version from the full pass) and rewrite the log.
        if not _section_filter:
            try:
                _qm_path = (f'/home/claude/_run_manifest_'
                            f'{_pname_file}_{date_compact}.json')
                _qman = {}
                if os.path.exists(_qm_path):
                    try:
                        with open(_qm_path, encoding='utf-8') as _qmf:
                            _qman = json.load(_qmf)
                    except Exception:
                        _qman = {}
                _qman.setdefault('player', _pname_display)
                _qman.setdefault(
                    'version',
                    __import__('gem_version',
                               fromlist=['RUNTIME_VERSION']).RUNTIME_VERSION)
                _qman['analyst_status'] = _rc_q.get('state')
                _qman['analyst_hand_entries'] = _rc_q.get('reviewed_hands')
                _qman['candidate_hands_awaiting'] = _rc_q.get('awaiting_candidates')
                _qman['analyst_coverage_line'] = _rc_q.get('coverage_line')
                _qman['outputs'] = {'html': html_path, 'md': md_path}
                _qman['rerendered_quick'] = True
                _qcf = _qman.get('cli_flags') or {}
                _qcf.update({'quick_mode': True,
                             'analyst_file': _analyst_file_override})
                _qman['cli_flags'] = _qcf
                _qtm = _qman.get('timing') or {}
                _qtm['quick_render_s'] = round(_t_render, 1)
                _qman['timing'] = _qtm
                with open(_qm_path, 'w', encoding='utf-8') as _qmf:
                    json.dump(_qman, _qmf, indent=2, ensure_ascii=False)
                print(f"  Run manifest updated (quick re-render): {_qm_path}")
                # v8.14.1 P0-1: the quick analyst re-render must ALSO persist the
                # final-state report_data so the packaged gem_report_data_<player>.json
                # AGREES with the manifest/log/report. Previously only the full
                # AUTO_ONLY pass wrote it, so the packaged data shipped with
                # state=AUTO_ONLY / reviewed=0 / analyst_commentary={} while the
                # report claimed ANALYST_COMPLETE. report_data already carries
                # analyst_commentary (applied at load) + report_completeness (_rc_q);
                # recompute only gto_export_analyst_count honestly from the persisted
                # GTO id-set. No poker facts are derived here.
                try:
                    report_data['report_completeness'] = _rc_q
                    _ac_q = report_data.get('analyst_commentary') or {}
                    _gto_ids_q = set(report_data.get('_gto_written_ids') or [])
                    if _gto_ids_q:
                        _ana_ids_q = {hid for hid, cmt in _ac_q.items()
                                      if isinstance(cmt, dict) and str(hid).startswith('TM')
                                      and str(cmt.get('verdict', '')).startswith(
                                          ('I.7', 'III.1', 'III.4', 'III.5'))}
                        report_data['gto_export_analyst_count'] = len(_ana_ids_q & _gto_ids_q)
                    _rd_qpath = f'/home/claude/gem_report_data_{_pname_file}.json'
                    with open(_rd_qpath, 'w', encoding='utf-8') as _rdqf:
                        json.dump(report_data, _rdqf, indent=2,
                                  default=str, ensure_ascii=False)
                    print(f"  Report data updated (quick re-render): {_rd_qpath}")
                except Exception as _rdqe:
                    print(f"  Quick report_data update skipped: {_rdqe}")
                _ql_path = (f'/home/claude/_run_log_'
                            f'{_pname_file}_{date_compact}.txt')
                with open(_ql_path, 'w', encoding='utf-8') as _qlf:
                    _qlf.write(f"GEM run log — {_qman.get('player', '')} "
                               f"{_qman.get('timestamp', '')}\n")
                    _qlf.write(f"runtime version : {_qman.get('version', '')}\n")
                    _qlf.write(f"report format   : "
                               f"{_qman.get('report_format_version', '')}\n")
                    _qlf.write(f"hands / tourneys: {_qman.get('n_hands', '?')} / "
                               f"{_qman.get('n_tournaments', '?')}\n")
                    _qlf.write(f"analyst status  : {_qman.get('analyst_status', '')} "
                               f"(quick analyst re-render)\n")
                    _qlf.write(f"analyst entries : "
                               f"{_qman.get('analyst_hand_entries', '?')} reviewed · "
                               f"{_qman.get('candidate_hands_awaiting', '?')} "
                               f"candidate(s) awaiting\n")
                    _qlf.write(f"coverage        : "
                               f"{_qman.get('analyst_coverage_line', '')}\n")
                    _qlf.write(f"game summaries  : "
                               f"{_qman.get('game_summaries_found', '')}\n")
                    _qlf.write(f"outputs         : {_qman.get('outputs', {})}\n")
                    _qlf.write(f"input files     : {_qman.get('input_files', [])}\n")
                    _qlf.write("\nNote: regenerated by a quick analyst re-render; "
                               "manifest + log reflect the analyst report shipped, "
                               "not the prior AUTO_ONLY pass.\n")
                print(f"  Run log updated (quick re-render): {_ql_path}")
            except Exception as _qme:
                print(f"  Quick manifest/log update skipped: {_qme}")
        sys.exit(0)

    # ---- SPEC #5: RENDER-ONLY MODE ----
    if _render_only_mode:
        # v8.3.0: use session-slug cache paths (matching parse/analyze path)
        _ro_slug = os.path.basename(os.path.normpath(SESSION_DIR)).replace(' ', '_')[:30] if SESSION_DIR else ''
        _ro_suffix = f'_{_ro_slug}' if _ro_slug else ''
        _rd_path = f'/home/claude/gem_report_data_{_pname_file}.json'
        _hands_path = f'/home/claude/gem_hands_{_pname_file}{_ro_suffix}.json'
        # Fallback: try without suffix (old cache format)
        if not os.path.exists(_hands_path):
            _hands_path = f'/home/claude/gem_hands_{_pname_file}.json'
        _stats_path = '/home/claude/gem_stats.json'
        _missing = [p for p in [_rd_path, _hands_path, _stats_path]
                    if not os.path.exists(p)]
        if _missing:
            print(f"ERROR: --render-only requires cached data. Missing: {_missing}")
            sys.exit(1)
        print(f"  🔄 RENDER-ONLY — loading cached data, attaching analyst file")
        _t0 = _time.perf_counter()
        with open(_hands_path, encoding='utf-8') as f:
            hands = json.load(f)
        with open(_rd_path, encoding='utf-8') as f:
            report_data = json.load(f)
        with open(_stats_path, encoding='utf-8') as f:
            stats = json.load(f)
        print(f"  Loaded: {len(hands)} hands, "
              f"{len(report_data.get('appendix_hand_ids_all',[]))} appendix IDs")
        # Batch 1: Extract decision points on cached hands (if not already present)
        if hands and 'decision_points' not in hands[0]:
            from gem_dp_extractor import extract_decision_points
            extract_decision_points(hands)
            _dp_c = sum(len(h.get('decision_points', [])) for h in hands)
            print(f"  Decision points: {_dp_c} DPs extracted on cached hands")
        # Attach analyst commentary (NO hash check — this is the whole point)
        _af = _analyst_file_override  # B-V11: was _analyst_file_path (undefined)
        if not _af:
            _date_range = stats.get('volume', {}).get('date_range', '')
            _af_candidates = [
                f'/home/claude/session_analysis_{_pname_file}_{_date_range}.json',
                f'/home/claude/work/session_analysis_{_pname_file}_{_date_range}.json',
                f'/home/claude/session_analysis_{_date_range}.json',
            ]
            _af = next((p for p in _af_candidates if os.path.exists(p)), None)
        if _af and os.path.exists(_af):
            with open(_af) as f:
                report_data['analyst_commentary'] = json.load(f)
            print(f"  Analyst file: {_af} ({len(report_data['analyst_commentary'])} entries)")
        else:
            report_data['analyst_commentary'] = {}
            print(f"  No analyst file found")
        # Refresh discipline tier after analyst is loaded
        from gem_report_data import _refresh_discipline_tier
        _refresh_discipline_tier(report_data, stats, hands)
        # Render
        from gem_report_draft import render_both
        _date_range = stats.get('volume', {}).get('date_range', '')
        out_dir = '/mnt/user-data/outputs'
        if not os.path.isdir(out_dir):
            out_dir = '/home/claude'
        # B-V11: _section_filter already parsed at line 7276. Removed bogus
        # recompute from undefined _section variable.
        html_str, md_str = render_both(stats, report_data, hands,
                                        sections=_section_filter)
        # Surrogate guard
        _sq = [i for i, c in enumerate(html_str) if 0xD800 <= ord(c) <= 0xDFFF]
        if _sq:
            print(f"  ⚠️  SURROGATE GUARD: {len(_sq)} surrogates — replacing")
            html_str = ''.join('?' if 0xD800 <= ord(c) <= 0xDFFF else c for c in html_str)
            md_str = ''.join('?' if 0xD800 <= ord(c) <= 0xDFFF else c for c in md_str)
        html_path = _versioned_path(out_dir, 'Pokerbot', _date_range, 'html', _pname_file)
        md_path = html_path.replace('.html', '.md')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_str)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_str)
        _t_render = _time.perf_counter() - _t0
        print(f"\n🔄 Render-only in {_t_render:.1f}s")
        print(f"  HTML: {html_path} ({os.path.getsize(html_path)//1024}KB)")
        print(f"  MD:   {md_path}")
        sys.exit(0)

    # ---- RESUME-FROM-CACHE MODE ----
    # Load cached intermediates → build candidates/worksheet → load analyst → render.
    # Skips parse + analyze entirely. For crash recovery after analysis completes.
    if _resume_from_cache:
        print("  🔁 RESUME-FROM-CACHE — loading cached data, building candidates + worksheet")
        _t_pipeline_start = _time.perf_counter()

        def _log_profile(stage_name):
            if not _profile_mode:
                return
            try:
                import resource
                rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            except Exception:
                try:
                    import psutil
                    rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
                except Exception:
                    rss_mb = None
            elapsed = _time.perf_counter() - _t_pipeline_start
            rss_str = f"{rss_mb:.0f}MB" if rss_mb else "n/a"
            print(f"  [PROFILE] {stage_name}: {elapsed:.1f}s elapsed, peak RSS {rss_str}")

        _rc_slug = os.path.basename(os.path.normpath(SESSION_DIR)).replace(' ', '_')[:30] if SESSION_DIR else ''
        _rc_suffix = f'_{_rc_slug}' if _rc_slug else ''
        _rd_path = f'/home/claude/gem_report_data_{_pname_file}.json'
        _hands_path = f'/home/claude/gem_hands_{_pname_file}{_rc_suffix}.json'
        if not os.path.exists(_hands_path):
            _hands_path = f'/home/claude/gem_hands_{_pname_file}.json'
        _stats_path = '/home/claude/gem_stats.json'
        _required = [_rd_path, _hands_path, _stats_path]
        _missing = [p for p in _required if not os.path.exists(p)]
        if _missing:
            print(f"ERROR: --resume-from-cache requires cached data. Missing:")
            for _mp in _missing:
                print(f"    {_mp}")
            print(f"Run a full pipeline first.")
            sys.exit(1)
        _t0 = _time.perf_counter()
        with open(_hands_path, encoding='utf-8') as f:
            hands = json.load(f)
        with open(_rd_path, encoding='utf-8') as f:
            report_data = json.load(f)
        with open(_stats_path, encoding='utf-8') as f:
            stats = json.load(f)
        # B142: session fingerprint validation — all three files must match
        _fp_stats = stats.get('_session_fingerprint', {})
        _fp_rd = report_data.get('_session_fingerprint', {})
        if _fp_stats and _fp_rd:
            _fp_match = (_fp_stats.get('n_hands') == _fp_rd.get('n_hands')
                         and _fp_stats.get('first_hand_id') == _fp_rd.get('first_hand_id')
                         and _fp_stats.get('date_range') == _fp_rd.get('date_range'))
            if not _fp_match:
                print(f"ERROR: session fingerprint MISMATCH between cached files!")
                print(f"  stats:       n={_fp_stats.get('n_hands')} "
                      f"date={_fp_stats.get('date_range')} "
                      f"first={str(_fp_stats.get('first_hand_id', ''))[:10]}")
                print(f"  report_data: n={_fp_rd.get('n_hands')} "
                      f"date={_fp_rd.get('date_range')} "
                      f"first={str(_fp_rd.get('first_hand_id', ''))[:10]}")
                print(f"Cached files are from different sessions. "
                      f"Run a full pipeline first.")
                sys.exit(1)
        if _fp_stats and _fp_stats.get('n_hands') and len(hands) != _fp_stats['n_hands']:
            print(f"  WARNING: hands file has {len(hands)} but fingerprint "
                  f"says {_fp_stats['n_hands']}. Data may be stale.")
        _cache_date = stats.get('volume', {}).get('date_range', '?')
        print(f"Loaded cached data in {_time.perf_counter()-_t0:.1f}s "
              f"({len(hands)} hands, player={_pname_display}, date={_cache_date})")
        for _lp in _required:
            _lmt = os.path.getmtime(_lp)
            import datetime as _dt_rc
            _lts = _dt_rc.datetime.fromtimestamp(_lmt).strftime('%Y-%m-%d %H:%M:%S')
            print(f"    {os.path.basename(_lp)}: {_lts}")
        _log_profile('cache_load')
        # Load ranges (for reshove/push chart gating in coverage builder)
        ranges = None
        try:
            from gem_ranges import load_ranges
            ranges = load_ranges()
        except Exception:
            pass
        # Build candidates + worksheet
        from gem_coverage_builder import build_and_write as _build_coverage
        _coverage_timing = {
            'parse_s': 0, 'analyze_s': 0,
            'pipeline_start': _t_pipeline_start,
        }
        candidates = _build_coverage(
            stats, hands, report_data, _pname_file, SESSION_DIR,
            ranges=ranges, timing=_coverage_timing)
        _log_profile('coverage_builder')
        # Load analyst commentary
        _date_range = stats['volume']['date_range']
        from gem_report_data import _resolve_analyst_file, _refresh_discipline_tier
        sa_path, _sa_log = _resolve_analyst_file(_date_range, _analyst_file_override)
        if sa_path:
            with open(sa_path) as f:
                report_data['analyst_commentary'] = json.load(f)
            print(f"  Analyst file: {sa_path} ({len(report_data['analyst_commentary'])} entries)")
        else:
            report_data['analyst_commentary'] = {}
            print(f"  No analyst file found")
        _refresh_discipline_tier(report_data, stats, hands)
        # PLO quarantine
        _non_nlh_ids_main = {h.get('id') for h in hands
                             if h.get('game_type', 'NLH') != 'NLH'}
        if _non_nlh_ids_main:
            _filter_non_nlh_from_candidate_buckets(candidates, _non_nlh_ids_main)
        # Coverage gate (simplified — warn only, no --require-analyst in resume mode)
        _ac = report_data.get('analyst_commentary', {}) or {}
        _auto_res = set(report_data.get('auto_resolved_ids', []))
        _need_v = set()
        for _bk in ('bust_audit', 'coolers', 'mistakes', 'punts',
                     'iii4_screening', 'read_dependent_screening'):
            for _c in candidates.get(_bk, []):
                _cid = _c.get('id')
                if _cid and _cid not in _auto_res:
                    _need_v.add(_cid)
        _uncov = sorted(_need_v - set(_ac.keys()))
        if _uncov:
            print(f"  ⚠ {len(_uncov)} of {len(_need_v)} flagged hands uncovered")
        else:
            print(f"  ✓ Coverage: {len(_need_v)} flagged hands covered")
        # Coaching cards (must run before render so window.coachingCards is serialized)
        from gem_coaching_cards import build_coaching_cards as _build_cc_resume
        report_data['coaching_cards'] = _build_cc_resume(
            hands, stats, report_data, ranges=ranges)
        _n_cc_r = sum(len(v) for v in report_data['coaching_cards'].values())
        if _n_cc_r:
            print(f"  Coaching cards: {_n_cc_r} cards for "
                  f"{len(report_data['coaching_cards'])} hands")
        _log_profile('coaching_cards')
        # v8.12.10: completeness from live candidates (resume path)
        from gem_report_data import compute_report_completeness as _crc_rsm
        _rc_rsm = _crc_rsm(report_data, candidates=candidates)
        # Re-dump report_data with new keys
        with open(_rd_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, default=str, ensure_ascii=False)
        # Render
        from gem_report_draft import render_both
        out_dir = '/mnt/user-data/outputs'
        os.makedirs(out_dir, exist_ok=True)
        date_compact = stats['volume']['date_range']
        _t0 = _time.perf_counter()
        html_str, md_str = render_both(stats, report_data, hands,
                                        sections=_section_filter)
        _t_render = _time.perf_counter() - _t0
        _log_profile('render')
        if _section_filter:
            suffix = '_section_' + '_'.join(_section_filter)
            html_path = f"{out_dir}/Pokerbot_{_pname_file}_{date_compact}{suffix}.html"
            md_path = html_path.replace('.html', '.md')
        else:
            _tag_rsm = 'AUTO_ONLY' if _rc_rsm.get('state') == 'AUTO_ONLY' else ''
            html_path = _versioned_path(out_dir, 'Pokerbot', date_compact, 'html', _pname_file, tag=_tag_rsm)
            md_path = html_path.replace('.html', '.md')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_str)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_str)
        _t_total = _time.perf_counter() - _t_pipeline_start
        print(f"\n🔁 Resume-from-cache complete in {_t_total:.1f}s "
              f"(coverage {_t_total - _t_render:.1f}s + render {_t_render:.1f}s)")
        print(f"  HTML: {html_path} ({os.path.getsize(html_path)//1024}KB)")
        print(f"  MD:   {md_path}")
        _print_completeness(_rc_rsm, where='resume')
        if not globals().get('_NO_VALIDATE_RENDER'):
            _qv_r = _quick_validate_render(html_str, report_data)
            if _qv_r:
                print(f"\n  ⚠️  Render validation: {len(_qv_r)} issue(s)")
                for _qi in _qv_r[:12]:
                    print(f"     - {_qi}")
            else:
                print("\n  ✅ Render validation passed.")
        sys.exit(0)

    _t_pipeline_start = _time.perf_counter()

    def _log_profile(stage_name):
        if not _profile_mode:
            return
        try:
            import resource
            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except Exception:
            try:
                import psutil
                rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            except Exception:
                rss_mb = None
        elapsed = _time.perf_counter() - _t_pipeline_start
        rss_str = f"{rss_mb:.0f}MB" if rss_mb else "n/a"
        print(f"  [PROFILE] {stage_name}: {elapsed:.1f}s elapsed, peak RSS {rss_str}")

    # ---- EFFICIENCY #7: CACHE PARSED HANDS ----
    # Hash HH input files. If unchanged from last run, load cached gem_hands
    # instead of re-parsing. Saves ~5-15s on re-runs (analyst iteration).
    import hashlib as _hashlib
    # Include session dir basename in cache key to prevent stale-cache cross-session pollution
    _session_slug = os.path.basename(os.path.normpath(SESSION_DIR)).replace(' ', '_')[:30] if SESSION_DIR else ''
    _cache_suffix = f'_{_session_slug}' if _session_slug else ''
    _cache_path = f'/home/claude/gem_hands_{_pname_file}{_cache_suffix}.json'
    _hash_path = f'/home/claude/.gem_hh_hash_{_pname_file}{_cache_suffix}'
    _hh_files = sorted(
        os.path.join(SESSION_DIR, f) for f in os.listdir(SESSION_DIR)
        if f.lower().endswith('.txt') and not f.startswith('.')
    ) if os.path.isdir(SESSION_DIR) else []
    _hh_hash = _hashlib.md5()
    for _hf in _hh_files:
        try:
            _hh_hash.update(open(_hf, 'rb').read())
        except Exception:
            pass
    _current_hash = _hh_hash.hexdigest()
    _cached_hash = ''
    if os.path.exists(_hash_path):
        try:
            _cached_hash = open(_hash_path).read().strip()
        except Exception:
            pass
    _use_cache = (_cached_hash == _current_hash and os.path.exists(_cache_path)
                  and _current_hash != '')

    # Step 0: Cache schema version check — force reparse if schema is outdated
    if _use_cache:
        try:
            from gem_parser import PARSER_SCHEMA_VERSION as _REQUIRED_SCHEMA
            import json as _json_schema
            with open(_cache_path, encoding='utf-8') as _sf:
                _first_hand = _json_schema.loads('[' + _sf.read(5000).split('},')[0] + '}]')[0]
            _cached_schema = _first_hand.get('schema_version', 1)
            if _cached_schema < _REQUIRED_SCHEMA:
                print(f"  ⚠️  Cache schema v{_cached_schema} < required v{_REQUIRED_SCHEMA} — forcing reparse")
                _use_cache = False
        except Exception:
            pass  # if we can't check, proceed with cache

    # ---- EFFICIENCY #8: AUTO-DETECT PLATFORM ----
    # If HH files contain CoinPoker XML (<HandHistory>), auto-convert to GG
    # text format before parsing. No manual coinpoker_to_gg.py step needed.
    _coinpoker_detected = False
    for _hf in _hh_files[:3]:  # check first 3 files
        try:
            _sample = open(_hf, encoding='utf-8-sig', errors='replace').read(500)
            if '<HandHistory>' in _sample or '<?xml' in _sample:
                _coinpoker_detected = True
                break
        except Exception:
            pass
    if _coinpoker_detected:
        print(f"\n  🔄 CoinPoker XML detected — auto-converting to GG format...")
        try:
            import coinpoker_to_gg as _cp
            _gg_blocks = []
            _cp_errs = 0
            for _hf in _hh_files:
                try:
                    _raw = open(_hf, encoding='utf-8-sig').read()
                    for _xml_hand in _cp.parse_hands(_raw):
                        try:
                            _gg_blocks.append(_cp.transform_hand(_xml_hand))
                        except Exception:
                            _cp_errs += 1
                except Exception:
                    _cp_errs += 1
            _gg_out = os.path.join(SESSION_DIR, f'_converted_gg_{_pname_file}.txt')
            with open(_gg_out, 'w', encoding='utf-8') as _gf:
                _gf.write('\n\n\n'.join(_gg_blocks) + '\n')
            print(f"  Converted {len(_gg_blocks)} hands ({_cp_errs} errors) → {_gg_out}")
            # Update hash to include converted output
            _hh_hash.update(open(_gg_out, 'rb').read())
            _current_hash = _hh_hash.hexdigest()
        except ImportError:
            print("  ⚠️  coinpoker_to_gg.py not found — cannot auto-convert")
        except Exception as _cp_e:
            print(f"  ⚠️  CoinPoker conversion failed: {_cp_e}")

    _tour_cache_path = f'/home/claude/gem_tournaments_{_pname_file}{_cache_suffix}.json'
    # --reanalyze: force cache load for hands (skip parse) but re-run analyze
    if _reanalyze_mode and os.path.exists(_cache_path):
        _use_cache = True
        print(f"  🔄 --reanalyze: loading cached hands, will re-run analysis")
    if _use_cache:
        print(f"  ♻️  HH files unchanged — loading cached hands from {_cache_path}")
        _t0 = _time.perf_counter()
        with open(_cache_path, encoding='utf-8') as _cf:
            hands = json.load(_cf)
        # BUG-C/D: load persisted tournaments dict (lossless), or rebuild
        # from hands (lossy on files/bullet count) as fallback.
        if os.path.exists(_tour_cache_path):
            with open(_tour_cache_path, encoding='utf-8') as _tf:
                tournaments = json.load(_tf)
            # Convert files list back to set
            for _tk, _tv in tournaments.items():
                if isinstance(_tv, dict) and isinstance(_tv.get('files'), list):
                    _tv['files'] = set(_tv['files'])
        else:
            # Fallback: rebuild from hands (lossy — no per-hand filename)
            from collections import defaultdict
            tournaments = {}
            for h in hands:
                tname = h.get('tournament', 'Unknown')
                tkey = h.get('tournament_id') or tname
                if tkey not in tournaments:
                    tournaments[tkey] = {
                        'tid': h.get('tournament_id'),
                        'name': tname, 'hands': [], 'files': set(),
                        'format': h.get('format', 'BOUNTY'),
                        'buyin': h.get('buyin', 0),
                    }
                tournaments[tkey]['hands'].append(h.get('id', ''))
        n_files = len(_hh_files)
        errors = 0
        _t_parse = _time.perf_counter() - _t0
        print(f"Loaded: {len(hands)} cached hands, "
              f"{len(tournaments)} tournaments in {_t_parse:.1f}s")
        _log_profile('parse (cache hit)')
    else:
        # Parse
        _t0 = _time.perf_counter()
        _stage_meter.tick('parse')          # forbidden in --quick (Gate 2.2)
        hands, tournaments, n_files, errors = parse_session(SESSION_DIR)
        _t_parse = _time.perf_counter() - _t0
        print(f"Parsed: {len(hands)} hands, {len(tournaments)} tournaments, "
              f"{n_files} files, {errors} errors")
        # v8.16.1 Bug-1: loud session date-scope report (no silent date filter).
        _date_coverage = build_date_coverage(hands, SESSION_DIR)
        for _dc_ln in _date_coverage['summary_lines']:
            print(_dc_ln)
        _log_profile('parse')
        # Save hash for next run
        try:
            with open(_hash_path, 'w') as _hf:
                _hf.write(_current_hash)
        except Exception:
            pass
    if not hands: print("ERROR: No hands parsed!"); sys.exit(1)

    # ---- H2: POST-PARSE SANITY CHECK ----
    # Catch garbage-in early before the analyzer spends 150s on bad data.
    _sanity_issues = []
    # Check hero identified
    _hero_names = set(h.get('hero', '') for h in hands[:50])
    if not any(_hero_names):
        _sanity_issues.append("No hero name identified in any hand")
    # Check for duplicate hand IDs
    _hand_ids_check = [h.get('id', '') for h in hands]
    _dupes = len(_hand_ids_check) - len(set(_hand_ids_check))
    if _dupes:
        _sanity_issues.append(f"{_dupes} duplicate hand IDs")
    # Check stacks are sane (not all zero)
    _zero_stacks = sum(1 for h in hands[:100] if (h.get('stack_bb') or 0) <= 0)
    if _zero_stacks > len(hands[:100]) * 0.5:
        _sanity_issues.append(f"{_zero_stacks}/100 hands have zero/negative stack")
    # Check blinds parsed
    _zero_blinds = sum(1 for h in hands[:100] if not h.get('bb_blind'))
    if _zero_blinds > len(hands[:100]) * 0.5:
        _sanity_issues.append(f"{_zero_blinds}/100 hands have no blind level")
    # Batch 2 (R8): Hand-gap detection per tournament
    from collections import defaultdict as _ddict_gap
    _by_tourney = _ddict_gap(list)
    for h in hands:
        tid = h.get('tournament_id') or h.get('tournament', '')
        if tid and h.get('id'):
            _by_tourney[tid].append(h['id'])
    _gap_count = 0
    for tid, hids in _by_tourney.items():
        # GG hand IDs are TM + 10 digits — extract numeric part
        nums = sorted(int(hid[2:]) for hid in hids if hid.startswith('TM') and hid[2:].isdigit())
        if len(nums) >= 2:
            for i in range(1, len(nums)):
                gap = nums[i] - nums[i-1]
                if 2 <= gap <= 20:  # small gaps (1-20 missing hands)
                    _gap_count += gap - 1
        if _gap_count > 50:
            break  # don't over-report
    if _gap_count:
        _sanity_issues.append(f"~{_gap_count} possible missing hands (ID gaps)")
    if _sanity_issues:
        print(f"\n  ⚠️  POST-PARSE SANITY CHECK — {len(_sanity_issues)} issue(s):")
        for _si in _sanity_issues:
            print(f"    ⚠️  {_si}")
        print(f"  Continuing with caution — results may be unreliable.")
    else:
        print(f"  ✅ Post-parse sanity check passed ({len(hands)} hands, "
              f"hero={list(_hero_names)[0] if _hero_names else '?'})")

    # ---- BATCH 1 STAGE 2: DECISION POINT EXTRACTION ----
    # Runs immediately after parsing, BEFORE detectors. Creates
    # hand['decision_points'] on every hand so detectors can attach flags
    # to decision_point IDs.
    _t0_dp = _time.perf_counter()
    from gem_dp_extractor import extract_decision_points
    extract_decision_points(hands)
    _t_dp = _time.perf_counter() - _t0_dp
    _dp_count = sum(len(h.get('decision_points', [])) for h in hands)
    _dp_hands = sum(1 for h in hands if h.get('decision_points'))
    print(f"  Decision points: {_dp_count} DPs across {_dp_hands} hands "
          f"({_t_dp:.2f}s)")

    # ---- BATCH 1: PARSER QA GATE ----
    try:
        from gem_qa_gate import run_parser_qa, print_qa_summary
        _pqa = run_parser_qa(hands)
        print_qa_summary('Parser', _pqa)
    except Exception as _qa_err:
        print(f"  ⚠️  Parser QA gate error: {_qa_err}")

    # Load ranges
    # Path resolution order (v7.32): prefer ranges file co-located with the
    # analyzer module so in-development edits to Poker_Ranges_Text.txt take
    # precedence over the read-only /mnt/project/ snapshot. Falls back to
    # /mnt/project/ when running against a release copy without local edits.
    _here = os.path.dirname(os.path.abspath(__file__)) or '.'
    range_paths = [os.path.join(_here, 'Poker_Ranges_Text.txt'),
                   '/mnt/project/Poker_Ranges_Text.txt', 'Poker_Ranges_Text.txt',
                   os.path.join(SESSION_DIR, 'Poker_Ranges_Text.txt')]
    ranges = {}
    targets = {}
    for rp in range_paths:
        if os.path.exists(rp):
            _stage_meter.tick('reference')   # forbidden in --quick (external chart/range load)
            ranges = load_ranges(rp)
            targets = load_targets(rp)  # v7.32: parallel target-band loader
            if ranges: print(f"Loaded {len(ranges)} range charts from {rp}"); break
    if not ranges: print("WARNING: No range file found — skipping preflop deviation analysis")
    if targets: print(f"Loaded {len(targets)} target frequency bands from ranges file")

    # v7.39 — B32 mitigation: chart sanity check + augmentation. Affected
    # charts get patched with missing anchor hands so detectors don't fail
    # silently; the report flags the augmentation per-deviation. v7.39
    # extension: also reports OCR-noise pattern clusters (4o-column,
    # 2o-column) without stripping them.
    if ranges:
        ranges, _sanity_report = sanity_check_ranges(ranges)
        globals()['_RANGE_SANITY_REPORT'] = _sanity_report
        if _sanity_report:
            print(f"\n⚠️  Chart sanity (B32): {len(_sanity_report)} chart(s) flagged:")
            for chart_name, info in sorted(_sanity_report.items()):
                missing = info.get('missing_before') or []
                noise = info.get('ocr_noise_patterns') or []
                bits = []
                if missing:
                    preview = ', '.join(missing[:6]) + (f' …+{len(missing)-6} more'
                                                        if len(missing) > 6 else '')
                    bits.append(f"+{info['augmented_count']} hands [{preview}]")
                if noise:
                    bits.append(f"OCR-noise: {', '.join(noise)}")
                print(f"  - {chart_name} ({info.get('family','?')}): {' | '.join(bits)}")

    # Analyze
    _t0 = _time.perf_counter()
    _stage_meter.tick('analyze')        # forbidden in --quick (evaluators + analyst grading run here)
    stats = analyze_session(hands, tournaments, n_files, errors, ranges, targets=targets)
    _t_analyze = _time.perf_counter() - _t0
    _log_profile('analyze')

    # Sanity check (gate)
    print(f"\n{'='*60}\nSANITY CHECKS\n{'='*60}")
    # B27: stale hardcoded paths replaced with glob discovery (same as below).
    import glob as _glob_sc
    _sc_candidates = []
    # RUN-LOCAL ISOLATION (Aviel rerun): restricted to CWD so Aviel's session
    # is not sanity-compared against Ron's /mnt/project/ session_history.
    for _d in (os.getcwd(),):
        for _p in _glob_sc.glob(os.path.join(_d, 'session_history*.csv')):
            if os.path.exists(_p):
                _sc_candidates.append(_p)
    prev_csv = max(_sc_candidates, key=os.path.getmtime) if _sc_candidates else None
    alerts = sanity_check(stats, hands, prev_csv)

    # Print summary
    print(f"\n{'='*60}\nSESSION SUMMARY\n{'='*60}")
    print(f"Date: {stats['volume']['date']}")
    print(f"\n  === PRIMARY METRICS ===")
    print(f"  VPIP-PFR Gap: {stats['core']['vpip_pfr_gap']}% (ex-BvB: {stats['core']['vpip_pfr_gap_ex_bvb']}%) (target <4%)")
    print(f"  WWSF: {stats['core']['wwsf']}% ({stats['core']['wwsf_ct']}/{stats['core']['wwsf_total']}) (target 42-48%)")
    print(f"  Non-SD Win: {stats['core']['non_sd_win']}% ({stats['core']['non_sd_ct']}/{stats['core']['wwsf_total']}) (target 25-35%)")
    print(f"  SD Aggressor: {stats['core']['sd_aggressor_pct']}% ({stats['core']['sd_aggressor']}/{stats['core']['sd_total']}) (target >40%)")
    print(f"  Caller IP Flop Agg: {stats['core']['caller_ip_flop_agg']}% ({stats['core']['caller_ip_flop_n']} hands, {stats['core'].get('caller_ip_delayed_cbet',0)} delayed cbets, {stats['core'].get('caller_ip_truly_passive',0)} truly passive) (target 30-40%)")
    # K3/K1/K6 — Appendix K metrics (v7.13)
    print(f"  IP Stab Rate (K3): {stats['core'].get('ip_stab_rate',0)}% ({stats['core'].get('ip_stab_bet_n',0)}/{stats['core'].get('ip_stab_n',0)}) (target 40-60%)")
    print(f"  IP Caller x/r (K1): {stats['core'].get('ip_caller_xr_rate',0)}% ({stats['core'].get('ip_caller_xr_bet_n',0)}/{stats['core'].get('ip_caller_xr_n',0)}) | MW: {stats['core'].get('ip_caller_xr_mw_rate',0)}% (MW target 0-5%)")
    print(f"  Flop Lead Rate (K6): {stats['core'].get('flop_lead_rate',0)}% ({stats['core'].get('flop_lead_bet_n',0)}/{stats['core'].get('flop_lead_n',0)}) (baseline ~2-5%, higher OK on low_paired/low_straight)")
    print(f"  Float→Turn Attack: {stats['core'].get('float_turn_attack_rate',0)}% ({stats['core'].get('float_turn_attack_n',0)}h) (target >50%)")
    # v7.13 drill-derived metrics
    ar = stats.get('aggressor_vs_reactor', {})
    if ar and (ar.get('aggressor_n', 0) + ar.get('reactor_n', 0)) >= 10:
        print(f"  *** Aggressor vs Reactor Δ: {ar.get('delta_bb_per_hand',0):+.2f} BB/h | Agg {ar.get('aggressor_bb_per_hand',0):+.2f} ({ar.get('aggressor_n',0)}h) vs React {ar.get('reactor_bb_per_hand',0):+.2f} ({ar.get('reactor_n',0)}h) | target Agg > 3x React ***")
    doj = stats.get('draw_overbet_jams', {})
    if doj and doj.get('count', 0) > 0:
        print(f"  Draw Overbet Jams: {doj['count']}h {doj['net_bb']:+.1f}BB (habitual, not tilt — use geometric sizing)")
    ppj = stats.get('passive_passive_jam', {})
    if ppj and ppj.get('count', 0) > 0:
        print(f"  Passive-Passive-Jam: {ppj['count']}h, won {ppj['won']} ({ppj['win_rate']}%), {ppj['net_bb']:+.1f}BB")
    tb = stats.get('triple_barrel_response', {})
    if tb and tb.get('total', 0) > 0:
        print(f"  Triple Barrel Faced: {tb['total']} (called {tb['called']['count']}@{tb['called']['win_rate']}%wr | folded {tb['folded']['count']} | raised {tb['raised']['count']})")
    sc = stats.get('sizing_consistency', {})
    if sc and sc.get('total', 0) > 0:
        print(f"  Sizing Consistency: {sc['geometric_pct']}% geometric ({sc['geometric']}/{sc['total']}) | Small→Small→JAM: {sc['small_small_jam_count']} (target 0)")
    print(f"  === END PRIMARY ===\n")
    print(f"VPIP {stats['core']['vpip']}% | PFR {stats['core']['pfr']}% | ATS {stats['core']['ats']}% | AF {stats['core']['af']}")
    print(f"BTN {stats['positions'].get('BTN',{}).get('open_pct',0)}% | CO {stats['positions'].get('CO',{}).get('open_pct',0)}% | SB {stats['positions'].get('SB',{}).get('open_pct',0)}%")
    print(f"HU CB {stats['cbet']['hu_pct']}% (IP {stats['cbet']['hu_ip_pct']}% OOP {stats['cbet']['hu_oop_pct']}%) | MW CB {stats['cbet']['mw_pct']}% | Turn CB {stats['cbet']['turn_pct']}%")
    print(f"WTSD {stats['showdown']['wtsd']}% | WSD {stats['showdown']['wsd']}%")
    print(f"F2-3B {stats['core']['ftb']}% ({stats['core']['ftb_ct']}/{stats['core']['ftb_opps']})")
    print(f"3B vs EP {stats['threebet_by_opener'].get('EP',{}).get('rate',0)}% | vs LP {stats['threebet_by_opener'].get('LP',{}).get('rate',0)}%")
    print(f"Premiums {stats['card_quality']['premiums_pct']}% | Card Cold: {stats['card_quality']['card_cold']}")
    print(f"EAI: {stats['eai']['total']} showdowns")
    pf = stats['eai']['preflop']
    post = stats['eai']['postflop']
    if pf['count'] > 0:
        print(f"  Preflop ({pf['count']}): Ahead {pf['ahead']['won']}/{pf['ahead']['count']} ({pf['ahead']['pct']}%) | Flip {pf['flip']['won']}/{pf['flip']['count']} ({pf['flip']['pct']}%) | Behind {pf['behind']['won']}/{pf['behind']['count']} ({pf['behind']['pct']}%)")
    if post['count'] > 0:
        print(f"  Postflop ({post['count']}): Ahead {post['ahead']['won']}/{post['ahead']['count']} ({post['ahead']['pct']}%) | Behind {post['behind']['won']}/{post['behind']['count']} ({post['behind']['pct']}%)")
    for street in ['flop', 'turn', 'river']:
        bs = stats['eai'].get('by_street', {}).get(street)
        if bs and bs['count'] > 0:
            print(f"    {street.capitalize()} ({bs['count']}): ahead {bs['ahead']['won']}/{bs['ahead']['count']} | behind {bs['behind']['won']}/{bs['behind']['count']}")
    print(f"Coolers: {stats['coolers']['count']} ({stats['coolers']['rate']}/100)")
    print(f"Punts: {stats.get('punts',{}).get('count',0)} ({stats.get('punts',{}).get('per_100',0)}/100) | Mistakes: {len(stats['mistakes'])} ({stats['mistakes_per_100']}/100)")
    print(f"Check-Raises: {stats['core']['check_raises']} | One-and-Done: {stats['core']['one_and_done']}")
    cr = stats.get('cr_frequency', {})
    if cr:
        print(f"CR Frequency: Flop {cr['flop_pct']}% ({cr['flop_cr']}/{cr['flop_opp']}) | Turn {cr['turn_pct']}% | River {cr['river_pct']}% | Total {cr['total_pct']}% [target: flop 6-8%, total 8-12%]")
    tbh = stats.get('threebet_by_hero_pos', {})
    if tbh:
        tbh_str = ' | '.join(f"{p} {d['rate']}%" for p in ['BTN','SB','BB','CO','HJ'] if p in tbh for d in [tbh[p]])
        print(f"3-Bet by Hero Pos: {tbh_str}")
    print(f"Missed River Value: {stats['missed_river_value']['count']} | Missed Probes: {stats['missed_probes']['count']}")
    print(f"SPR dist: {stats['spr_distribution']}")
    if stats['hand_strength_dist']:
        print(f"SD hand strength: {stats['hand_strength_dist']}")

    # Table size mix (v7.2)
    print(f"Table sizes: {stats.get('table_size_mix', {})}")

    # SB BvB preflop (v7.2 — J29)
    sbv = stats.get('sb_bvb_preflop', {})
    if sbv.get('total', 0) > 0:
        print(f"SB BvB Preflop: limp {sbv['limp_pct']}% raise {sbv['raise_pct']}% fold {sbv['fold_pct']}% (n={sbv['total']}) [target: limp ~80%, raise ~10%, fold ~10%]")

    # BB 3-bet sizing (v7.2 — J30)
    bb3 = stats.get('bb_3bet_sizing', {})
    if bb3.get('count', 0) > 0:
        print(f"BB 3-bets: {bb3['count']} hands [target sizing: 5x from BB]")

    # Aggression tables (key IP caller spots)
    at = stats.get('aggression_tables', {})
    for key in ['Caller_Flop_IP', 'Caller_Turn_IP', 'PFR_Flop_IP', 'PFR_Turn_IP']:
        if key not in at: continue
        print(f"\n  {key}:")
        for cat in ['made_hand','nut_fd','fd','oesd+bdfd','oesd','gutshot+bdfd','gutshot','bdfd','overcards','none']:
            d = at[key].get(cat)
            if not d or d['total']==0: continue
            print(f"    {cat:>16} {d['total']:4d} hands  {d['bet']:3d} bet  {d['pct']:5.1f}%")

    # LINE ANALYSIS (v8)
    if stats.get('top_losing_lines'):
        print(f"\n  === TOP LOSING LINES ===")
        print(f"  {'Line':>55} {'#':>4} {'Net BB':>8} {'BB/h':>7} {'Conf':>5}")
        for ll in stats['top_losing_lines'][:10]:
            print(f"  {ll['line']:>55} {ll['count']:4d} {ll['net_bb']:+8.1f} {ll['avg_bb']:+7.2f} {ll['confidence']:>5}")
        print(f"  === TOP WINNING LINES ===")
        for wl in stats.get('top_winning_lines', [])[:5]:
            print(f"  {wl['line']:>55} {wl['count']:4d} {wl['net_bb']:+8.1f} {wl['avg_bb']:+7.2f}")
        print(f"  Unique lines: {stats['line_summary']['unique_lines']} | VPIP hands tracked: {stats['line_summary']['vpip_hands_with_lines']}")

    # Mistakes detail
    if stats['mistakes']:
        print(f"\nMISTAKES:")
        for m in stats['mistakes']:
            sat = ' [SAT-ICM]' if m.get('is_satellite') else ''
            extra = f" | Board: {m.get('board','')}" if 'board' in m else ''
            summary = f" | {m.get('action_summary','')}" if m.get('action_summary') else ''
            print(f"  {m['id']} | {m['cards']:5s} | {m['pos']:3s} | {m['stack_bb']}BB | {m['type']}{sat}{extra}{summary}")

    # Missed river value
    if stats['missed_river_value']['hands']:
        print(f"\nMISSED RIVER VALUE ({stats['missed_river_value']['count']}):")
        for m in stats['missed_river_value']['hands'][:10]:
            summary = f" | {m.get('action_summary','')}" if m.get('action_summary') else ''
            print(f"  {m['id']} | {m['cards']:5s} | {m['pos']:3s} | {m['hand_strength']} | Bet {m['streets_bet']} streets | {m['board']}{summary}")

    # Missed probes
    if stats['missed_probes']['hands']:
        print(f"\nMISSED PROBES ({stats['missed_probes']['count']}):")
        for m in stats['missed_probes']['hands'][:10]:
            print(f"  {m['id']} | {m['cards']:5s} | {m['pos']:3s} | {m['hand_strength']} | Draw: {m['draw_type']} | {m['board']}")

    # F2-3B flags
    bad_ftb = [f for f in stats['fold_to_3bet_details'] if f.get('is_pair_lt50')]
    if bad_ftb:
        print(f"\nF2-3B PUNT CANDIDATES (pairs <50BB — Dave J11):")
        for f in bad_ftb:
            print(f"  {f['id']} | {f['cards']} | {f['pos']} | {f['stack_bb']}BB")

    # Preflop deviations (v7.2)
    dev_sum = stats.get('deviation_summary', {})
    if dev_sum:
        print(f"\nPREFLOP DEVIATIONS ({len(stats.get('preflop_deviations', []))} total):")
        print(f"  {'Type':<25} {'Total':>5} {'Clear':>5} {'Marginal':>8}  Common Hands")
        for dt in ['Missed Open', 'Wide Open', 'Missed Defend/3-Bet', 'Wide 3-Bet',
                    'Missed Rejam', 'Missed Call-Rejam', 'Wide Call-Rejam',
                    'Missed BB Defend', 'Wide BB Defend', 'Wide BvB Iso (vs limp)']:
            d = dev_sum.get(dt)
            if not d: continue
            hands_str = ', '.join(d['hands'][:5])
            print(f"  {dt:<25} {d['count']:5d} {d['clear']:5d} {d['marginal']:8d}  {hands_str}")

    # Ron 2026-05-31: player-scoped filenames for multi-player support.
    # Pattern: Pokerbot_{NAME}_{YYYYMMDD}_V{N}.html
    # NAME defaults to 'Knockman'. V{N} auto-increments if file exists.
    _pname_file = (_player_name or 'Knockman').replace(' ', '_')
    _pname_display = _player_name or 'Knockman'

    # B142: session fingerprint — embedded in all cached intermediates so
    # --quick can detect cross-session mismatches.
    _hand_ids_sorted = sorted(h.get('id', '') for h in hands if h.get('id'))
    _session_fingerprint = {
        'player': _pname_file,
        'n_hands': len(hands),
        'first_hand_id': _hand_ids_sorted[0] if _hand_ids_sorted else '',
        'last_hand_id': _hand_ids_sorted[-1] if _hand_ids_sorted else '',
        'date_range': stats.get('volume', {}).get('date_range', ''),
    }
    # v8.12.4 (QA item 30): bind the fingerprint to the HH DIRECTORY hash.
    # The cross-file check only proved the cached trio was internally
    # consistent — a stale-but-consistent cache from another session passed
    # and rendered wrong data. With hh_hash inside the fingerprint, --quick
    # can compare cache vs the CURRENT session dir and hard-abort.
    try:
        import hashlib as _hl_fp
        _fp_files = sorted(
            os.path.join(SESSION_DIR, f) for f in os.listdir(SESSION_DIR)
            if f.lower().endswith('.txt') and not f.startswith('.')
        ) if os.path.isdir(SESSION_DIR) else []
        _fp_hash = _hl_fp.md5()
        for _fp_f in _fp_files:
            try:
                _fp_hash.update(open(_fp_f, 'rb').read())
            except Exception:
                pass
        _session_fingerprint['hh_hash'] = _fp_hash.hexdigest()
    except Exception:
        pass
    stats['_session_fingerprint'] = _session_fingerprint

    # Save stats JSON
    out_path = f'/home/claude/gem_stats.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nStats saved: {out_path} ({os.path.getsize(out_path)//1024}KB)")

    # Save hands JSON (without raw_text to save space)
    hands_path = f'/home/claude/gem_hands_{_pname_file}{_cache_suffix}.json'
    with open(hands_path, 'w', encoding='utf-8') as f:
        # A2a: preserve raw_text in cache (EAI needs it on cache hits).
        # After A2b (structured action ledger), raw_text becomes optional.
        json.dump([{k: v for k, v in h.items()} for h in hands], f, default=str, ensure_ascii=False)
    print(f"Hands saved: {hands_path} ({os.path.getsize(hands_path)//1024}KB)")
    # BUG-D: write unscoped alias so tests/tools reading gem_hands.json still work
    _canonical_hands = '/home/claude/gem_hands.json'
    try:
        import shutil
        shutil.copy2(hands_path, _canonical_hands)
    except Exception:
        pass
    # BUG-D: persist tournaments dict for cache round-trip (files set → list)
    try:
        _tour_save = {}
        for _tk, _tv in tournaments.items():
            _td = dict(_tv)
            if isinstance(_td.get('files'), set):
                _td['files'] = sorted(_td['files'])
            _tour_save[_tk] = _td
        with open(_tour_cache_path, 'w', encoding='utf-8') as f:
            json.dump(_tour_save, f, indent=2, default=str, ensure_ascii=False)
    except Exception:
        pass

    # v7.14: Lean hands JSON — drops verbose fields (~35% smaller).
    # Use for bulk scanning / aggregate analysis. Full gem_hands.json
    # remains source of truth for hand-by-hand narration (clinical
    # examples, action replays). Same fields + same IDs, so a lookup
    # back to the full file is always safe.
    LEAN_DROP_FIELDS = {'raw_text', 'pf_sequence', 'action_summary',
                        'hero_street_actions', 'line_actions', 'stacks_behind'}
    hands_lean_path = f'/home/claude/gem_hands_lean.json'
    with open(hands_lean_path, 'w', encoding='utf-8') as f:
        json.dump([{k: v for k, v in h.items() if k not in LEAN_DROP_FIELDS} for h in hands], f, default=str, ensure_ascii=False)
    lean_sz = os.path.getsize(hands_lean_path)
    full_sz = os.path.getsize(hands_path)
    saved_pct = round((1 - lean_sz/full_sz) * 100, 1) if full_sz else 0
    print(f"Hands (lean) saved: {hands_lean_path} ({lean_sz//1024}KB, -{saved_pct}% vs full)")
    _log_profile('cache_write')

    # Auto-generate CSV row
    cr = stats['csv_row']
    csv_header = ','.join(cr.keys())
    csv_values = ','.join(str(v) for v in cr.values())
    print(f"\n{'='*60}\nCSV ROW (append to session_history)\n{'='*60}")
    print(f"Header: {csv_header}")
    print(f"Values: {csv_values}")

    # Run log row (append to gem_run_log.csv)
    dev_count = len(stats.get('preflop_deviations', []))
    clear_devs = sum(1 for d in stats.get('preflop_deviations', []) if d.get('confidence') == 'CLEAR')
    run_log = f"{stats['volume']['date']},{cr['Batch_ID']},{stats['volume']['hands']},{len(tournaments)},{n_files},~{stats['volume']['hands']//2}K,{errors},,v7.2 parser. {dev_count} preflop deviations ({clear_devs} clear). {len(stats['mistakes'])} mistakes. {stats['coolers']['count']} coolers."
    print(f"\nRUN LOG ROW (append to gem_run_log.csv):")
    print(run_log)

    # --- AUTO-GENERATE REPORT DATA (v7.12) ---
    # B27 fix: discover most-recent session_history*.csv via glob, follow D35
    # local-first pattern. Was hardcoded to session_history_20260409.csv
    # (long-stale) and session_history.csv (never existed) — leak persistence
    # tracker silently saw "no prior data" every run.
    import glob as _glob
    def _find_latest_history():
        candidates = []
        # RUN-LOCAL ISOLATION (Aviel rerun): restricted to CWD so Aviel's
        # report trend/leak-persistence sections are not built against Ron's
        # /mnt/project/ session_history. Aviel has no GEM history -> these
        # sections render standalone, which is correct.
        for d in (os.getcwd(),):
            for p in _glob.glob(os.path.join(d, 'session_history*.csv')):
                if os.path.exists(p):
                    candidates.append(p)
        if not candidates:
            return None
        # Prefer most-recently modified file across all dirs.
        return max(candidates, key=os.path.getmtime)
    session_hist = _find_latest_history()
    if session_hist:
        print(f"  [B27] session history: {session_hist}")
    # ---- OPPONENT PROFILER: per-villain archetype classification ----
    _t0_profiler = _time.perf_counter()
    try:
        from gem_opponent_profiler import (profile_opponents, tag_hands_with_archetypes,
                                           find_misplays_vs_archetype)
        _opp_profiles = profile_opponents(hands, hero_name=_pname_display)
        tag_hands_with_archetypes(hands, _opp_profiles)
        _misplays = find_misplays_vs_archetype(hands, _opp_profiles)
        # Store on stats for renderer access
        stats['opponent_profiles'] = {k: {kk: (sorted(vv) if isinstance(vv, set) else vv)
                                          for kk, vv in v.items()
                                          if kk != 'example_hand_ids'}
                                      for k, v in _opp_profiles.items()
                                      if v.get('archetype') != 'UNKNOWN'}
        stats['archetype_misplays'] = _misplays
        # Tag misplayed hands so the XIV renderer shows exploit advice
        _hands_by_id_mp = {h.get('id'): h for h in hands}
        for _mp in _misplays:
            _mph = _hands_by_id_mp.get(_mp.get('hand_id'))
            if _mph:
                _mph['archetype_misplay'] = {
                    'misplay_type': _mp.get('misplay_type', ''),
                    'what_to_do': _mp.get('what_to_do', ''),
                    'archetype_label': _mp.get('archetype_label', ''),
                }
        _arch_counts = {}
        for _v in _opp_profiles.values():
            a = _v.get('archetype', 'UNKNOWN')
            _arch_counts[a] = _arch_counts.get(a, 0) + 1
        # v8.7.0: Opponent Intelligence — neutral alias pool + per-player keys
        from gem_villain_intel import build_villain_intel, villain_key_for_hand
        _villain_intel = build_villain_intel(hands, _pname_display, _opp_profiles)
        stats['villain_intel'] = _villain_intel
        _alias_map = _villain_intel.get('villain_aliases', {})

        # Build legacy villain_identity_map for backward compat (renderers still read it)
        _villain_map = {}
        for _vk, _va in _alias_map.items():
            _villain_map[_vk] = {
                'villain_code': _va.get('v_number', ''),
                'alias': _va.get('alias', ''),
                'archetype': _va.get('archetype_label', _va.get('archetype', '')),
                'n_hands': _va.get('n_hands', 0),
                'confidence': ('very_low' if _va.get('n_hands', 0) < 5 else
                               'medium_low' if _va.get('n_hands', 0) < 10 else
                               'medium' if _va.get('n_hands', 0) < 20 else
                               'medium_high' if _va.get('n_hands', 0) < 50 else 'high'),
            }
        # Also index by old-style key (tournament[:30]|position) so existing
        # renderer lookups via primary_villain_hash still find entries.
        for h in hands:
            _pvk = villain_key_for_hand(h)
            _pvh = h.get('primary_villain_hash', '')
            if _pvk and _pvk in _villain_map and _pvh and _pvh not in _villain_map:
                _villain_map[_pvh] = _villain_map[_pvk]
        stats['villain_identity_map'] = _villain_map

        # PR3: index evidence atoms by hand for per-hand tagging
        _atoms_by_hand = _villain_intel.get('atoms_by_hand', {})
        # PR4: index exploit opportunities by hand
        _exploits_by_hand = _villain_intel.get('exploits_by_hand', {})

        # Tag each hand with villain identity — new key + legacy compat
        for h in hands:
            _pvk = villain_key_for_hand(h)
            h['primary_villain_key'] = _pvk
            # PR3: populate evidence atoms and badges from detectors
            _hand_atoms = _atoms_by_hand.get(h.get('id', ''), [])
            h['villain_evidence_atoms'] = _hand_atoms
            h['villain_badges'] = _hand_atoms  # badges are the same atoms for grid rendering
            # PR4: populate exploit opportunities
            _hand_exploits = _exploits_by_hand.get(h.get('id', ''), [])
            h['exploit_opportunities'] = _hand_exploits
            # Set villain_identity from new alias map
            if _pvk and _pvk in _alias_map:
                _va = _alias_map[_pvk]
                h['villain_identity'] = {
                    'code': _va.get('v_number', ''),
                    'alias': _va.get('alias', ''),
                    'archetype': _va.get('archetype_label', _va.get('archetype', '')),
                    'confidence': ('very_low' if _va.get('n_hands', 0) < 5 else
                                   'medium_low' if _va.get('n_hands', 0) < 10 else
                                   'medium' if _va.get('n_hands', 0) < 20 else
                                   'medium_high' if _va.get('n_hands', 0) < 50 else 'high'),
                    'n_hands': _va.get('n_hands', 0),
                    'villain_key': _pvk,
                }
            else:
                # Fallback: try old-style primary_villain_hash
                _pvh = h.get('primary_villain_hash', '')
                if _pvh and _pvh in _villain_map:
                    _vi = _villain_map[_pvh]
                    h['villain_identity'] = {
                        'code': _vi['villain_code'],
                        'alias': _vi['alias'],
                        'archetype': _vi['archetype'],
                        'confidence': _vi['confidence'],
                        'n_hands': _vi['n_hands'],
                    }

        print(f"\nOpponent profiling: {len(_opp_profiles)} villains tracked, "
              f"{len(_misplays)} archetype misplays found, "
              f"{len(_alias_map)} villain identities assigned (neutral aliases)")
        print(f"  Archetypes: {_arch_counts}")
        # v8.7.0: Opponent Intelligence QA summary
        _vi_atoms = _villain_intel.get('evidence_atoms', [])
        _vi_exploits = _villain_intel.get('exploit_opportunities', [])
        _vi_reads = _villain_intel.get('read_states', {})
        if _vi_atoms or _vi_exploits:
            from collections import Counter as _Ctr
            _by_sig = _Ctr(a.get('signal', '?') for a in _vi_atoms)
            _hero_f = sum(1 for a in _vi_atoms if not a.get('hero_involved', True))
            print(f"\n  Opponent Intel QA:")
            print(f"    Evidence atoms: {len(_vi_atoms)}")
            for _sig, _n in _by_sig.most_common():
                print(f"      {_sig}: {_n}")
            print(f"    hero_involved=false: {_hero_f}")
            if _vi_exploits:
                # v8.8.3: use exploit_detector field instead of fragile text matching
                _by_exp = _Ctr(_e.get('exploit_detector', 'unknown') for _e in _vi_exploits)
                print(f"    Exploit opportunities: {len(_vi_exploits)}")
                for _et, _n in _by_exp.most_common():
                    print(f"      {_et}: {_n}")
                # v8.8.3: exploit_read_label distribution
                _by_label = _Ctr(_e.get('exploit_read_label', '❓ Unknown') for _e in _vi_exploits)
                print(f"    Exploit read labels:")
                for _rl, _n in _by_label.most_common():
                    print(f"      {_rl}: {_n}")
                # v8.8.3: read_source distribution (monitor archetype fallback)
                _by_src = _Ctr(_e.get('read_source', 'unknown') for _e in _vi_exploits)
                print(f"    Exploit read sources:")
                for _rs, _n in _by_src.most_common():
                    print(f"      {_rs}: {_n}")
                _arch_missed = sum(1 for _e in _vi_exploits
                                   if _e.get('read_source') == 'profiler_archetype'
                                   and _e.get('auto_verdict') == 'missed_exploit')
                if _arch_missed > len(_vi_exploits) * 0.5:
                    print(f"    *** WARNING: {_arch_missed}/{len(_vi_exploits)} missed exploits "
                          f"rely on profiler_archetype — read evidence may be thin ***")
            else:
                print(f"    Exploit opportunities: 0")
            if _vi_reads:
                _by_read = _Ctr(rs.get('primary_read', '?') for rs in _vi_reads.values())
                print(f"    Read states: {len(_vi_reads)}")
                for _r, _n in _by_read.most_common():
                    print(f"      {_r}: {_n}")
            _atom_counts = _Ctr(a.get('villain_key', '') for a in _vi_atoms)
            _top5_vk = _atom_counts.most_common(5)
            if _top5_vk:
                print(f"    Top villains by evidence:")
                for _vk, _na in _top5_vk:
                    _vm = _alias_map.get(_vk) or _villain_intel.get('villain_aliases', {}).get(_vk, {})
                    _vname = _vm.get('alias', _vk.split('|')[1][:8] if '|' in _vk else '?')
                    _vcode = _vm.get('v_number', _vm.get('villain_code', '?'))
                    print(f"      {_vname:10s} ({_vcode:4s}): {_na} atoms")
            # REGRESSION GUARD: Hero-identity invariants
            _hero_actual = set(h.get('hero', '') for h in hands if h.get('hero'))
            _hero_as_villain = sum(1 for a in _vi_atoms
                                  if any(hn in a.get('villain_key', '') for hn in _hero_actual))
            print(f"    Hero-as-villain atoms: {_hero_as_villain}")
            if _hero_as_villain > 0:
                print(f"    *** REGRESSION: Hero appears as villain in {_hero_as_villain} atoms ***")
            if _hero_f == 0 and len(_vi_atoms) > 20:
                print(f"    *** WARNING: hero_involved=false is 0 with {len(_vi_atoms)} atoms — "
                      f"possible hero-name mismatch ***")
        # Re-save hands cache with archetype tags (profiler runs after initial save)
        try:
            with open(hands_path, 'w', encoding='utf-8') as f:
                json.dump([{k: v for k, v in h.items()} for h in hands], f, default=str, ensure_ascii=False)
            print(f"  Hands cache updated with archetype tags")
        except Exception:
            pass
    except Exception as _opp_e:
        print(f"  Opponent profiling skipped: {type(_opp_e).__name__}: {_opp_e}")
        stats['opponent_profiles'] = {}
        stats['archetype_misplays'] = []
    _t_profiler = _time.perf_counter() - _t0_profiler
    _log_profile('profiler + villain_intel')

    # BUG-2 fix: define variables needed by analyst villain worksheet
    _ws_out_dir = '/mnt/user-data/outputs'
    if not os.path.isdir(_ws_out_dir):
        _ws_out_dir = os.path.dirname(os.path.abspath(__file__))
    _ws_date_raw = stats.get('volume', {}).get('date_range', 'unknown')
    _ws_date_compact = re.sub(r'[^A-Za-z0-9_-]+', '_', str(_ws_date_raw)).strip('_') or 'unknown'

    # v8.9.0-prep: generate analyst villain worksheet (deterministic, no LLM call)
    try:
        from gem_analyst_villain import (
            build_opponent_adjustment_candidates, write_worksheet)
        _vi_ws = stats.get('villain_intel', {})
        if _vi_ws:
            _ws_candidates = build_opponent_adjustment_candidates(
                _vi_ws, hands, stats,
                max_candidates=_max_villain_candidates)
            if _ws_candidates:
                _ws_path = write_worksheet(
                    _ws_candidates, _ws_date_compact, _pname_file, _ws_out_dir)
                print(f"\n  Analyst villain worksheet: {_ws_path} "
                      f"({len(_ws_candidates)} candidates)")
            else:
                print(f"\n  Analyst villain worksheet: 0 candidates (no worksheet written)")
    except Exception as _ws_e:
        print(f"  Analyst villain worksheet skipped: {type(_ws_e).__name__}: {_ws_e}")

    # v8.7.5 FIX: Re-save stats after villain_intel is populated.
    # The initial stats save (line ~8478) happens BEFORE the profiler/villain_intel
    # section, so villain_intel is missing from the cached JSON. On --render-only,
    # the renderer reads stats from JSON and gets no villain_intel → empty
    # window.villainIntel → all opponent popups/Matrix break.
    try:
        # Convert sets to lists for JSON serialization
        _vi_for_json = stats.get('villain_intel', {})
        if _vi_for_json:
            for _vk, _va in _vi_for_json.get('villain_aliases', {}).items():
                if isinstance(_va.get('positions_seen'), set):
                    _va['positions_seen'] = sorted(_va['positions_seen'])
                if isinstance(_va.get('evidence_hand_ids'), set):
                    _va['evidence_hand_ids'] = list(_va['evidence_hand_ids'])
        _stats_path_resave = '/home/claude/gem_stats.json'
        with open(_stats_path_resave, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, default=str, ensure_ascii=False)
    except Exception as _re:
        print(f"  Warning: stats re-save failed: {_re}")

    # Fix B (v7.99.26): set the module-level override BEFORE generate_report_data()
    # so internal _maybe_load_analyst_commentary calls use the same resolved path.
    import gem_report_data as _grd
    _grd._ANALYST_FILE_OVERRIDE = _analyst_file_override
    report_data = generate_report_data(stats, hands, SESSION_DIR, session_hist,
                                       player_name=_pname_display)
    report_data['_session_fingerprint'] = _session_fingerprint
    # v8.16.1 Bug-1: persist the date-coverage transparency record (printed at
    # parse time) into report_data + the run log so the scope is auditable.
    try:
        report_data['date_coverage'] = _date_coverage
    except NameError:
        pass
    rd_path = f'/home/claude/gem_report_data_{_pname_file}.json'
    with open(rd_path, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nReport data saved: {rd_path} ({os.path.getsize(rd_path)//1024}KB)")
    if report_data.get('gto_export_path'):
        print(f"GTO export saved: {report_data['gto_export_path']}")
    print(f"Avg buy-in: ${report_data['avg_buyin']} ({report_data['total_invested']} total)")
    if report_data.get('trend_sparklines'):
        print(f"\nTREND SPARKLINES:")
        for metric, sp in report_data['trend_sparklines'].items():
            print(f"  {metric}: {sp['trend_str']}")
    print(f"\nHero classification: {report_data['hero_classification']['emoji']} {report_data['hero_classification']['label']}")
    print(f"Mistake EV impact: {report_data['total_mistake_ev']:+.1f}BB")
    lp = report_data.get('leak_persistence', {})
    if lp.get('tracker'):
        print(f"\nLEAK PERSISTENCE:")
        for lt in lp['tracker']:
            print(f"  {lt['status']:15s} {lt['leak']:25s} {lt['note']}")
        s = lp.get('summary', {})
        print(f"  --- {s.get('new',0)} new, {s.get('recurring',0)} recurring, {s.get('returned',0)} returned, {s.get('resolved',0)} resolved")

    # --- AUTO-GENERATE REPORT (v7.36 — D21 HTML primary + MD secondary) ---
    # Per Quick Reference D21:
    #   /mnt/user-data/outputs/Pokerbot_Report_YYYYMMDD.html  (primary)
    #   /mnt/user-data/outputs/Pokerbot_Report_YYYYMMDD.md    (secondary)
    # Earlier versions only emitted MD to /home/claude/ — silent doc-vs-code
    # drift caught in the v7.35→v7.36 review.

    # ---- ANALYST CANDIDATES + WORKSHEET (extracted to gem_coverage_builder) ----
    from gem_coverage_builder import build_and_write as _build_coverage
    _coverage_timing = {
        'parse_s': round(_t_parse, 1),
        'analyze_s': round(_t_analyze, 1),
        'profiler_s': round(_t_profiler, 1) if '_t_profiler' in dir() else None,
        'verdicts_s': None,
        'render_s': None,
        'pipeline_start': _t_pipeline_start,
    }
    _stage_meter.tick('detector')       # forbidden in --quick (Gate 2.2): candidate/detector sweep
    candidates = _build_coverage(
        stats, hands, report_data, _pname_file, SESSION_DIR,
        ranges=ranges, timing=_coverage_timing)
    _log_profile('coverage_builder')


    # ---- LOAD SESSION ANALYSIS (if present) ----
    # Analyst step produces session_analysis_<date>.json. Renderer reads it
    # via report_data['analyst_commentary']. If file missing, sections that
    # depend on commentary degrade cleanly (e.g., "no III.4 entries this run").
    # Fix B (v7.99.26): search-order resolution replaces single hardcoded path.
    _date_range = stats['volume']['date_range']
    sa_path, _sa_log = _resolve_analyst_file(_date_range, _analyst_file_override)
    print(f"\n{'='*60}\nANALYST FILE RESOLUTION\n{'='*60}")
    print(f"  Looking for: session_analysis_{_date_range}.json")
    for _l in _sa_log:
        print(_l)
    if sa_path:
        with open(sa_path) as f:
            session_analysis = json.load(f)
        report_data['analyst_commentary'] = session_analysis
        n_cmts = len(session_analysis)
        print(f"  Loaded: {sa_path} ({n_cmts} per-hand entries)")
        # B237 (Ron review 2026-05-26): auto-tag III.3-cleared hands that were
        # all-in coin-flips Hero LOST with outcome='lost_flip' so they render
        # as "🪙 Lost coin-flip" instead of a generic clear.
        # B240 (Ron review 2026-05-26, greenlit): extended to a full
        # equity-driven classification using the gem_eai_equity numbers —
        # 🦁 Dominating, 🪙 Coin-flip (won), 🥇 Field favourite (multiway),
        # 🤢 Suckout (favourite lost). An explicit analyst `outcome` always
        # wins; only cleared/justified hands with no outcome set are tagged.
        # B251 (Ron review 2026-05-27): gate widened from III.3-only to
        # III.3 + III.5. A lost coin-flip call-off is routinely graded III.5
        # Justified (justified variance), not III.3 — those were silently
        # skipped, so flip losses like QQ-vs-AK / AK-vs-QQ rendered as a
        # bare verdict with no 🪙 outcome label. The outcome label is
        # orthogonal to clear-vs-justified; both verdict classes qualify.
        _eai_by_id = {h.get('id'): h for h in
                      (stats.get('eai', {}).get('hands', []) or [])}
        _n_tagged = 0
        for _hid, _eh in _eai_by_id.items():
            _c = session_analysis.get(_hid)
            if not (isinstance(_c, dict)
                    # Item 13: widen to III.0/I.7 + existing III.3/III.5 —
                    # all cleared/justified/GTO-standard/cooler verdicts
                    # qualify for equity-driven outcome sub-labels.
                    and str(_c.get('verdict', '')).startswith(
                        ('III.0', 'III.3', 'III.5', 'I.7'))
                    and not _c.get('outcome')):
                continue
            _e = _eh.get('hero_equity')
            _won = _eh.get('won')
            _cat = _eh.get('category')
            _n = _eh.get('n_allin') or 2
            _fav = _eh.get('is_favorite', False)
            _oc = None
            if _won is True and _e is not None:
                if _e >= 0.62 or (_cat == 'ahead' and _n >= 3 and _e >= 0.52):
                    _oc = 'dominating'
                elif _n >= 3 and _fav and _e < 0.52:
                    _oc = 'multiway_fav'
                elif 0.42 <= _e <= 0.60:
                    _oc = 'coin_flip'
            elif _won is False and _e is not None:
                # Item 13: extend lost-side auto-tagger so that lost
                # all-ins carry sub-labels (lost_flip, semi_bluff_cooler,
                # top_of_range) in addition to suckout. Ron's review:
                # "not a cooler, it's a lost coin flip" — needs 🪙.
                if _fav and _e >= 0.60:
                    _oc = 'suckout'
                elif _cat == 'flip' or (0.42 <= _e <= 0.60):
                    _oc = 'lost_flip'
                elif _e >= 0.62:
                    # Hero was dominating (>62%) and still lost — extreme
                    # suckout but sub-labelled 'top_of_range' for taxonomy.
                    _oc = 'top_of_range'
                elif _e < 0.42 and _fav is False:
                    # Hero was behind and lost — normal, but if the analyst
                    # marked it cleared/justified it was a semi-bluff spot.
                    _oc = 'semi_bluff_cooler'
            if _oc:
                _c['outcome'] = _oc
                _n_tagged += 1
        if _n_tagged:
            print(f"  auto-tagged {_n_tagged} cleared all-in(s) with an "
                  f"equity outcome label (🦁/🪙/🥇/🤢/🥶)")
    else:
        report_data['analyst_commentary'] = {}
        print(f"  Analyst commentary: none — no session_analysis file found.\n"
              f"  Sections requiring commentary will render as ⚪ awaiting analyst.")

    # B-AVIEL BUG-5 (2026-06-01): refresh discipline_tier now that
    # analyst_commentary is definitively bound to rd. This ensures the stat
    # strip's punts/mistakes count matches the body sections (both use the
    # same analyst-cleared set). Without this, a pre-render with no analyst
    # file shows detector-raw punts in the strip while body shows 0.
    from gem_report_data import _refresh_discipline_tier
    _refresh_discipline_tier(report_data, stats, hands)

    # ---- v8.9.8 P2-C: PLO quarantine pass on __main__ candidate buckets ----
    # analyze_session() strips mistakes/punts, but bust_audit/iii4_screening/
    # read_dependent_screening/bestplay_screening are built in __main__
    # and can contain PLO hands. Strip them before coverage gate.
    _non_nlh_ids_main = {h.get('id') for h in hands
                         if h.get('game_type', 'NLH') != 'NLH'}
    if _non_nlh_ids_main:
        _filter_non_nlh_from_candidate_buckets(candidates, _non_nlh_ids_main)
    # v8.12.6 (Chat session 2026-06-11): this wrote to `s`, which does not
    # exist in __main__ scope (it's analyze_session's local) — NameError
    # crashed every fresh `python gem_analyzer.py` run right after the
    # candidate build. The variable here is `stats`.
    stats['_non_nlh_ids'] = _non_nlh_ids_main

    # ---- FIX A (v7.99.26): ANALYST COVERAGE GATE ----
    # After candidates are built and analyst_commentary is loaded (or {}),
    # compute which flagged hand IDs lack verdicts. Soft gate by default
    # (warn + continue); --require-analyst makes it a hard fail.
    _ac = report_data.get('analyst_commentary', {}) or {}
    _ac_ids = set(_ac.keys())
    # Hands needing verdicts: bust audit + detector punts + blind-spot sample
    # v8.4.0 B-6 FIX: coverage gate must use the SAME hand set as the worksheet.
    # Previously only checked bust_audit + punts + blindspot, missing hands that
    # the worksheet includes (coolers, mistakes, iii4, read-dep, bestplay).
    _auto_res = set(report_data.get('auto_resolved_ids', []))
    # v8.19.0 RC3 (P2-1): the coverage gate and the completeness owner consume ONE canonical
    # required-review population (gem_report_data.canonical_required_review_ids), so the "Full
    # coverage" message below provably implies compute_report_completeness has NO unreviewed
    # required hand. SUPPRESS-noise candidates stay IN the set (a suggested SUPPRESS is the
    # auto-classifier's hint, not an analyst waiver); the blindspot-audit sample is a SEPARATE
    # coverage signal (reported just after), never folded into the required-review identity.
    from gem_report_data import canonical_required_review_ids as _canon_rri
    _need_verdict_ids = _canon_rri(candidates, _auto_res, _non_nlh_ids_main)['need']
    # v8.9.8 P2-C: production-safe PLO quarantine invariant — the canonical owner already excludes
    # non-NLH, so this stays as a fail-loud guard that the shared set never carries a PLO leak.
    _plo_leak = _need_verdict_ids & _non_nlh_ids_main
    if _plo_leak:
        import logging
        logging.error("PLO quarantine leak: %s — removing from verdict surface", _plo_leak)
        _need_verdict_ids -= _plo_leak
    _uncovered = sorted(_need_verdict_ids - _ac_ids)
    _covered = _need_verdict_ids & _ac_ids
    print(f"\n{'='*60}\nANALYST COVERAGE CHECK\n{'='*60}")
    if _auto_res:
        print(f"  Chart-match auto-resolved: {len(_auto_res)} "
              f"(excluded from coverage requirement)")
    if not _need_verdict_ids:
        print("  No hands require analyst verdicts this session.")
    elif not _uncovered:
        print(f"  ✓ Full coverage: {len(_covered)}/{len(_need_verdict_ids)} "
              f"flagged hands have analyst verdicts.")
    else:
        _status = "HARD FAIL" if _require_analyst else "WARNING"
        print(f"  ⚠ {_status}: {len(_uncovered)} of {len(_need_verdict_ids)} "
              f"flagged hands have NO analyst verdict.")
        print(f"  Covered: {len(_covered)}  |  Uncovered: {len(_uncovered)}")
        print(f"  Expected file: session_analysis_{_date_range}.json"
              f"  {'(FOUND: ' + sa_path + ')' if sa_path else '(NOT FOUND)'}")
        # B256: Print uncovered IDs WITH hand context (cards/pos/stack/line)
        # so each failed gate is actionable in one pass.
        _show = _uncovered[:50]
        _hbi = {h.get('id'): h for h in hands}
        print(f"  Uncovered IDs ({len(_uncovered)} total):")
        for _uid in _show:
            _h = _hbi.get(_uid)
            if _h:
                _cards = ' '.join(_h.get('cards', []) or [])
                _pos = _h.get('position', '?')
                _sbb = round(_h.get('stack_bb', 0))
                _net = round(_h.get('net_bb', 0), 1)
                _src = 'blindspot' if _uid in {
                    (_sh.get('id') or '') for _sh in
                    (stats.get('blindspot_audit', {}).get('sampled', []) or [])
                } else 'bust/punt'
                print(f"    {_uid}  {_cards:10s}  {_pos:4s}  "
                      f"{_sbb:3d}BB  {_net:+.1f}BB  [{_src}]")
            else:
                print(f"    {_uid}")
        if len(_uncovered) > 50:
            print(f"    … and {len(_uncovered) - 50} more")
        if _require_analyst:
            print(f"\n  ABORTING — --require-analyst is set. Provide the "
                  f"analyst file via --analyst-file <path> or remove "
                  f"--require-analyst to continue with ⚪ stubs.")
            sys.exit(2)
        else:
            print(f"\n  Continuing with ⚪ awaiting-analyst stubs. To fail "
                  f"on incomplete coverage, re-run with --require-analyst.")

    # v8.19.0 RC3 (P2-1): blindspot-audit coverage is a SEPARATE signal from the canonical
    # required-review set above — so "Full coverage" means exactly "every shared required-review
    # candidate is graded" == the completeness owner has no unreviewed required hand. Report it
    # on its own line; an unreviewed blindspot sample is informational, never a coverage failure.
    _bs = stats.get('blindspot_audit', {})
    _bs_ids = {(_sh.get('id') or '') for _sh in (_bs.get('sampled', []) or [])} if isinstance(_bs, dict) else set()
    _bs_ids.discard('')
    if _bs_ids:
        _bs_uncov = sorted(_bs_ids - _ac_ids)
        print(f"  Blindspot audit: {len(_bs_ids) - len(_bs_uncov)}/{len(_bs_ids)} sampled hands reviewed"
              + (f" ({len(_bs_uncov)} unreviewed — informational, not a coverage requirement)."
                 if _bs_uncov else "."))

    # v8.7.9 FIX (GAP 3): check metric-flagged leaks have analyst judgment
    _promoted = (report_data.get('leak_persistence', {}) or {}).get('current_leaks', []) or []
    if _promoted:
        _synth = (report_data.get('analyst_commentary', {}) or {}).get('__synthesis__', {}) or {}
        _leak_cmts = _synth.get('leaks', {}) if isinstance(_synth, dict) else {}
        _unjudged = [n for n in _promoted
                     if not (((_leak_cmts.get(n) or {}).get('real_or_noise') or '').strip())]
        if _unjudged:
            _lk_status = "HARD FAIL" if _require_analyst else "WARNING"
            print(f"  ⚠ {_lk_status}: {len(_unjudged)} metric-flagged leak(s) "
                  f"have NO analyst judgment: {_unjudged}")
            if _require_analyst:
                print(f"  Add __synthesis__.leaks entries keyed by exact leak name "
                      f"with real_or_noise field (real/mixed/noise).")
        else:
            print(f"  ✓ All {len(_promoted)} metric-flagged leaks have analyst judgment.")

    # v7.60: QUANTIFY the read-dependent bucket. The river call/fold solver
    # prices each read-dependent call's chip-EV vs FOLD at the population
    # baseline — replacing the "impact under review" placeholder with a real
    # number. Covers analyst-verdicted III.4 hands + screener-flagged calls.
    # Turn (or earlier) bluff-catches are not river-solvable and are reported
    # separately rather than silently dropped.
    report_data['read_dependent_quant'] = {}
    try:
        from gem_solver_integration import (quantify_read_dependent_calls,
                                            _SOLVER_AVAILABLE as _SA_Q)
        if _SA_Q:
            _sa = report_data.get('analyst_commentary', {}) or {}
            _rd_ids = [hid for hid, c in _sa.items()
                       if isinstance(c, dict)
                       and str(c.get('verdict', '')).startswith('III.4')]
            _rd_ids += [c['id'] for c in
                        candidates.get('read_dependent_screening', [])
                        if c.get('id')]
            if _rd_ids:
                report_data['read_dependent_quant'] = \
                    quantify_read_dependent_calls(
                        _rd_ids, hands, SESSION_DIR,
                        '/home/claude/solver_runs',
                        stats['volume']['date_range'])
                _nq = sum(1 for v in report_data['read_dependent_quant'].values()
                          if v.get('solvable'))
                print(f"Read-dependent quantified: {_nq}/"
                      f"{len(report_data['read_dependent_quant'])} river-solvable")
    except Exception as _q_e:
        print(f"  read-dependent quantification skipped: "
              f"{type(_q_e).__name__}: {_q_e}")

    # v7.62 (Ron 2026-05-21): RESIDUAL DECOMPOSITION — break the implied-true-EV
    # residual into named skill-leak buckets. Computed HERE (not in
    # generate_report_data) because it needs read_dependent_quant, which is
    # only appended above. The rows EXPLAIN the residual; they do not extend
    # the top ledger's subtraction chain. read-dependent is solver-real; MDA
    # missed/aligned are model-expected (generic per-rec EV, like card
    # quality); MDA-missed is deduped against the counted Mistake-EV ids.
    report_data['residual_decomposition'] = {}
    try:
        _ra = report_data.get('results_attribution', {}) or {}
        _n = _ra.get('n_hands', 0) or 1
        _resid_p100 = _ra.get('implied_true_ev_extended_per_100', 0.0)

        _rdq = report_data.get('read_dependent_quant', {}) or {}
        _rd_cost_bb = 0.0
        _rd_n = 0
        for _q in _rdq.values():
            if (_q.get('solvable') and _q.get('verdict_pop') == 'FOLD'
                    and _q.get('ev_call_pop_bb') is not None):
                _rd_cost_bb += _q['ev_call_pop_bb']
                _rd_n += 1
        # capture (hand_id, bb_cost) for the read-dependent cEV conversion
        _rd_events = [(_hid, _q['ev_call_pop_bb'])
                      for _hid, _q in _rdq.items()
                      if (_q.get('solvable') and _q.get('verdict_pop') == 'FOLD'
                          and _q.get('ev_call_pop_bb') is not None)]

        _mda = stats.get('mda_exploits', {}) or {}
        _counted = set(_ra.get('non_tail_mistake_ids', []) or [])

        def _missed_cost(e):
            ev = e.get('ev_bb') or 0
            return ev if e.get('counter_rec') else -ev

        def _aligned_credit(e):
            ev = e.get('ev_bb') or 0
            return -ev if e.get('counter_rec') else ev

        _missed = _mda.get('missed', []) or []
        _aligned = _mda.get('aligned', []) or []
        _missed_kept = [e for e in _missed if e.get('hand_id') not in _counted]
        _missed_deduped_n = len(_missed) - len(_missed_kept)
        _mda_missed_bb = sum(_missed_cost(e) for e in _missed_kept)
        _mda_aligned_bb = sum(_aligned_credit(e) for e in _aligned)

        def _p100(bb):
            return round(100.0 * bb / _n, 3)

        _rd_p = _p100(_rd_cost_bb)
        _mm_p = _p100(_mda_missed_bb)
        _ma_p = _p100(_mda_aligned_bb)
        _unattr_p = round(_resid_p100 - _rd_p - _mm_p - _ma_p, 3)

        # --- cEV for the decomposition rows (% starting stack / 100) ---
        # v7.63 (Ron 2026-05-21): each row's cEV = sum(bb_cost x that hand's
        # big blind) / that hand's TOURNAMENT starting stack — per-tournament
        # denominator, NOT the session mean (the session-mean form inflated
        # late-game events; see the _mistake_cev / B142 note). The implied
        # true EV cEV is the chip-conserving spine: it comes straight from
        # results_attribution (surface cEV − the 4 variance layers), so the
        # residual decomposition reconciles with financial direction.
        _cev_starts = report_data.get('cev_starts', {}) or {}
        _tid_by_id = {h.get('id'): (h.get('tournament_id') or h.get('tournament'))
                      for h in hands}
        _bb_by_id = {h.get('id'): (h.get('bb_blind') or 0) for h in hands}
        _n_res = ((report_data.get('cev_session', {}) or {})
                  .get('n_hands_resolved') or _n)

        def _cev_p100(events):
            """events: list of (hand_id, bb_cost). -> cEV % stack / 100.
            Per-event chips/start clamped to [-3,3] starting stacks — same
            bound as _mistake_cev — so one extreme late-game-blind hand
            cannot dominate a residual row."""
            if not _cev_starts:
                return None
            tot = 0.0
            for hid, bb in events:
                start_t = _cev_starts.get(_tid_by_id.get(hid))
                blind = _bb_by_id.get(hid, 0)
                if start_t and blind:
                    tot += max(-3.0, min((bb * blind) / start_t, 3.0))
            return round(100.0 * tot / _n_res, 3)

        _rd_cev = _cev_p100(_rd_events)
        _mm_cev = _cev_p100([(e.get('hand_id'), _missed_cost(e))
                             for e in _missed_kept])
        _ma_cev = _cev_p100([(e.get('hand_id'), _aligned_credit(e))
                             for e in _aligned])
        # implied-true-EV cEV = the chip-conserving spine from the cEV ledger.
        _itev_cev = _ra.get('implied_true_ev_cev_per_100')
        _unattr_cev = None
        if (_itev_cev is not None and _rd_cev is not None
                and _mm_cev is not None and _ma_cev is not None):
            _unattr_cev = round(_itev_cev - _rd_cev - _mm_cev - _ma_cev, 3)

        report_data['residual_decomposition'] = {
            'available': True,
            'residual_per_100': round(_resid_p100, 2),
            'read_dependent': {'per_100': _rd_p, 'cev_per_100': _rd_cev,
                               'total_bb': round(_rd_cost_bb, 1),
                               'n_calls': _rd_n, 'basis': 'solver-real'},
            'mda_missed': {'per_100': _mm_p, 'cev_per_100': _mm_cev,
                           'total_bb': round(_mda_missed_bb, 1),
                           'n_events': len(_missed_kept),
                           'n_deduped': _missed_deduped_n,
                           'basis': 'model-expected'},
            'mda_aligned': {'per_100': _ma_p, 'cev_per_100': _ma_cev,
                            'total_bb': round(_mda_aligned_bb, 1),
                            'n_events': len(_aligned),
                            'basis': 'model-expected'},
            'unattributed': {'per_100': _unattr_p, 'cev_per_100': _unattr_cev,
                             'basis': 'balance — un-named leak cost'},
        }
        # BUG-2 (Ron 2026-05-30): flag low-confidence decompositions where
        # unattributed dominates the residual. The 4 variance layers are
        # already in the top ledger (surface → True EV subtraction chain);
        # this section decomposes the POST-variance skill residual. When
        # read_dependent + MDA explain <50% of it, flag it so the renderer
        # can add a caveat rather than presenting a clean-looking table.
        _explained_p = abs(_rd_p) + abs(_mm_p) + abs(_ma_p)
        _resid_abs = abs(_resid_p100) if _resid_p100 else 1.0
        _low_conf = (_resid_abs > 1.0 and
                     _explained_p / _resid_abs < 0.5)
        report_data['residual_decomposition']['low_confidence'] = _low_conf
        if _low_conf:
            report_data['residual_decomposition']['low_confidence_reason'] = (
                f"Explained {_explained_p:.1f} of {_resid_abs:.1f} bb/100 residual "
                f"({100*_explained_p/_resid_abs:.0f}%) — "
                f"most of the skill residual is unattributed")
        _ucev = (f"{_unattr_cev:+.3f}" if _unattr_cev is not None else "n/a")
        print(f"Residual decomposition (cEV/100, spine): read-dep "
              f"{_rd_cev if _rd_cev is not None else 'n/a'}, "
              f"MDA-missed {_mm_cev if _mm_cev is not None else 'n/a'}, "
              f"MDA-aligned {_ma_cev if _ma_cev is not None else 'n/a'}, "
              f"unattributed {_ucev} stacks | BB/100 lens: unattributed "
              f"{_unattr_p:+.2f}")
    except Exception as _rd_e:
        report_data['residual_decomposition'] = {
            'available': False, 'reason': f'{type(_rd_e).__name__}: {_rd_e}'}
        print(f"  residual decomposition skipped: "
              f"{type(_rd_e).__name__}: {_rd_e}")

    # v7.64 (Ron 2026-05-21): depth-segmented win-rate. Decision-quality BB/100
    # cut by effective stack depth (4-tier: <=8 / 8-25 / 25-40 / >40 BB) with
    # an ICM-pressure split and a tournament cluster-bootstrap CI. Separate
    # from the cEV ledger — decision quality, not result attribution.
    try:
        from gem_depth_segments import compute_depth_segments
        report_data['depth_segments'] = compute_depth_segments(hands)
        _ds = report_data['depth_segments']
        if _ds.get('available'):
            print(f"Depth segments: {_ds['n_hands']} hands / "
                  f"{_ds['n_tournaments']} tournaments across "
                  f"{len(_ds['buckets'])} depth buckets")
    except Exception as _ds_e:
        report_data['depth_segments'] = {
            'available': False, 'reason': f'{type(_ds_e).__name__}: {_ds_e}'}
        print(f"  depth segments skipped: {type(_ds_e).__name__}: {_ds_e}")

    # v8.12.10: stamp report completeness (full path — candidates live) so
    # the TL;DR banner + filename + CLI reflect analyst coverage, AND the
    # need-set persists into the cached rd below for later --quick renders.
    from gem_report_data import compute_report_completeness as _crc_full
    _rc_full = _crc_full(report_data, candidates=candidates)

    # v8.12.11 (Slice E): emit the analyst worklist — a prioritized triage
    # queue (proposals, not verdicts) for the LLM analyst pass. Write-only
    # artifact; does NOT affect the report. Never fatal.
    try:
        from gem_analyst_worklist import build_analyst_worklist
        _stage_meter.tick('worklist')   # forbidden in --quick (Gate 2.2)
        _wl_dc = stats.get('volume', {}).get('date_range', 'session')
        _wl = build_analyst_worklist(candidates, stats, report_data, hands,
                                     _wl_dc,
                                     runtime=report_data.get('renderer_version')
                                     or __import__('gem_version', fromlist=['RUNTIME_VERSION']).RUNTIME_VERSION)
        _wl_dir = '/mnt/user-data/outputs' if os.path.isdir(
            '/mnt/user-data/outputs') else '/home/claude'
        _wl_path = f"{_wl_dir}/analyst_worklist_{_wl_dc}.json"
        with open(_wl_path, 'w', encoding='utf-8') as _wf:
            json.dump(_wl, _wf, indent=2, ensure_ascii=False)
        _wc = _wl['generated_counts']
        print(f"\n  Analyst worklist: {_wl_path}")
        print(f"    must_review={_wc['must_review']} "
              f"review_if_time={_wc['review_if_time']} "
              f"auto_clear={_wc['auto_clear']} "
              f"aggregate_only={_wc['aggregate_only']} "
              f"drill_candidate={_wc['drill_candidate']}")
    except Exception as _wl_e:
        print(f"  Analyst worklist skipped: {type(_wl_e).__name__}: {_wl_e}")

    # B141 (Ron 2026-05-21): the rd_path dump above happens BEFORE the
    # read-dependent screen/quant keys are added — so gem_report_data.json
    # on disk was missing read_dependent_quant / read_dependent_screen
    # (and anything else appended after the first dump). The renderer was
    # unaffected (it uses the in-memory dict) but any post-hoc consumer of
    # the JSON saw stale data. Re-dump here so the file matches memory.
    with open(rd_path, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, default=str, ensure_ascii=False)

    out_dir = '/mnt/user-data/outputs'
    os.makedirs(out_dir, exist_ok=True)
    date_compact = stats['volume']['date_range']

    # ---- SCHEMA VALIDATION (v7.36) ----
    # Run before render to catch shape mismatches between analyzer/report_data
    # and renderer expectations. This is the guardrail Bug #3 needed: had it
    # existed, the IX leak_persistence shape mismatch would have surfaced
    # immediately rather than silently emitting "0 new | 0 recurring".
    print(f"\n{'='*60}\nSCHEMA VALIDATION\n{'='*60}")
    schema_ok, schema_issues = validate_pipeline_outputs(stats, report_data, strict=False)
    if schema_ok:
        print("  ALL SCHEMA CHECKS PASSED ✓")
    else:
        print(f"  ⚠ {len(schema_issues)} SCHEMA ISSUE(S) — render will continue but "
              f"affected sections may render empty:")
        for iss in schema_issues:
            print(f"    - {iss}")
    # v8.9.0-prep: load analyst villain review if provided
    if _analyst_villain_file:
        try:
            from gem_analyst_villain import load_analyst_villain_review
            _avr = load_analyst_villain_review(
                _analyst_villain_file,
                expected_session_date=date_compact)
            _avr_debug = _avr.get('debug', {})
            _n_valid = _avr_debug.get('total', 0) - _avr_debug.get('invalid', 0)
            print(f"\n  Analyst villain review loaded: {_n_valid} valid "
                  f"({_avr_debug.get('confirmed', 0)} confirmed, "
                  f"{_avr_debug.get('rejected', 0)} rejected, "
                  f"{_avr_debug.get('borderline', 0)} borderline, "
                  f"{_avr_debug.get('upgraded', 0)} upgraded)")
            report_data['analyst_villain_review'] = _avr
        except Exception as _avr_e:
            print(f"  Analyst villain review load failed: "
                  f"{type(_avr_e).__name__}: {_avr_e}")

    from gem_coaching_cards import build_coaching_cards as _build_cc
    report_data['coaching_cards'] = _build_cc(hands, stats, report_data, ranges=ranges)
    _n_cc = sum(len(v) for v in report_data['coaching_cards'].values())
    if _n_cc:
        print(f"  Coaching cards: {_n_cc} cards for "
              f"{len(report_data['coaching_cards'])} hands")
    # REV9 C2/C3: the report_data JSON was dumped BEFORE coaching_cards were built, so the
    # persisted file lacked them (consumer-ownership evidence read 0). Re-dump now so the
    # coaching-card ownership (reviewed_action_index) is in the file post-hoc consumers read.
    try:
        with open(rd_path, 'w', encoding='utf-8') as _ccf:
            json.dump(report_data, _ccf, indent=2, default=str, ensure_ascii=False)
    except Exception:
        pass

    _t0 = _time.perf_counter()
    # Perf fix (Ron 2026-05-30): render_both() builds the Doc ONCE and
    # renders both formats from it — was calling _build() twice before.
    html_str, md_str = render_both(stats, report_data, hands, sections=_section_filter)
    _t_render = _time.perf_counter() - _t0
    _log_profile('render')
    # Ron 2026-05-31: versioned, player-scoped report filenames.
    # Pattern: Pokerbot_{NAME}_{YYYYMMDD}_V{N}.html
    if _section_filter:
        suffix = '_section_' + '_'.join(_section_filter)
        html_path = f"{out_dir}/Pokerbot_{_pname_file}_{date_compact}{suffix}.html"
        md_path = f"{out_dir}/Pokerbot_{_pname_file}_{date_compact}{suffix}.md"
    else:
        _tag_full = 'AUTO_ONLY' if _rc_full.get('state') == 'AUTO_ONLY' else ''
        html_path = _versioned_path(out_dir, 'Pokerbot', date_compact, 'html', _pname_file, tag=_tag_full)
        md_path = html_path.replace('.html', '.md')
    # B4.4: pre-write surrogate guard — catch lone surrogates before they
    # crash the UTF-8 write (cost a full 250s run when BUG-B hit).
    _surr_positions = [i for i, c in enumerate(html_str)
                       if 0xD800 <= ord(c) <= 0xDFFF]
    if _surr_positions:
        print(f"\n  ⚠️  SURROGATE GUARD: {len(_surr_positions)} lone surrogate(s) "
              f"at positions {_surr_positions[:5]} — replacing with '?'")
        html_str = ''.join('?' if 0xD800 <= ord(c) <= 0xDFFF else c
                           for c in html_str)
        md_str = ''.join('?' if 0xD800 <= ord(c) <= 0xDFFF else c
                         for c in md_str)
    with open(html_path, 'w', encoding='utf-8') as f: f.write(html_str)
    with open(md_path, 'w', encoding='utf-8') as f: f.write(md_str)
    _html_kb = os.path.getsize(html_path) // 1024
    print(f"\nReport (HTML, primary): {html_path} ({_html_kb}KB)")
    print(f"Report (MD,  secondary): {md_path}  ({os.path.getsize(md_path)//1024}KB)")
    # v8.20 final RC: the canonical FULL run emits the ONE sealed analyst packet (every required decision
    # hydrated with every fact + pre-completed calculation) bound to real input hashes + current commit +
    # content-derived cache id. Emitted AFTER render so the canonical required-review population
    # (_candidate_need_ids, stamped by compute_report_completeness) is present. --quick later validates
    # that binding and renders from cache. Best-effort -- never breaks the run.
    # In analyst/release mode (default ON; GEM_ANALYST_MODE=0 disables) any packet / identity / semantic-
    # audit failure FAILS CLOSED with a non-zero exit -- never a silent warning. The packaged Chat workflow
    # runs analyst mode by default. Identity comes from the embedded git-independent build id; input hashes
    # from the canonical recursive manifest; cache identity from the ACTUAL cache artifacts.
    _analyst_mode = os.environ.get('GEM_ANALYST_MODE', '1') != '0'
    try:
        import gem_analyst_packet as _ap_emit
        import gem_build_identity as _ap_bid
        from gem_input_manifest import canonical_input_hashes as _ap_cih
        _ap_out = '/mnt/user-data/outputs' if os.path.isdir('/mnt/user-data/outputs') else '/home/claude'
        _ap_idy = _ap_bid.build_identity()
        _ap_inhash = _ap_cih(SESSION_DIR)
        # Compute the cache identity from the ON-DISK cache artifacts (the exact files --quick reloads), so a
        # fresh full->quick always matches and any later cache mutation is detected (owner blocker #6).
        _q_slug_e = os.path.basename(os.path.normpath(SESSION_DIR)).replace(' ', '_')[:30] if SESSION_DIR else ''
        _rd_cache_e = f'/home/claude/gem_report_data_{_pname_file}.json'
        _hands_cache_e = f'/home/claude/gem_hands_{_pname_file}' + (f'_{_q_slug_e}' if _q_slug_e else '') + '.json'
        if not os.path.exists(_hands_cache_e):
            _hands_cache_e = f'/home/claude/gem_hands_{_pname_file}.json'
        _ap_cache = _ap_emit.cache_identity_from_disk(_rd_cache_e, _hands_cache_e, _ap_idy, _ap_inhash)
        _ap_pkt = _ap_emit.build_packet(
            hands, report_data, session_id=str(_pname_file),
            runtime_version=str(_ap_idy.get('runtime_base') or ''),
            runtime_commit=str(_ap_idy.get('source_commit_short') or ''),
            input_hashes=_ap_inhash, cache_identity=_ap_cache, build_identity=_ap_idy, optional_cap=8)
        _ap_base = os.path.join(_ap_out, f'analyst_packet_{_pname_file}')
        _ap_sa = _ap_emit.semantic_audit(_ap_pkt)            # owner Gate 1 + no-calc semantic audit
        for _ap_fn, _ap_obj in (('.json', _ap_pkt),
                                ('_manifest.json', _ap_pkt['manifest']),
                                ('_semantic_audit.json', _ap_sa),
                                ('_completeness.json', _ap_emit.decision_completeness(_ap_pkt)),
                                ('_coverage.json', _ap_emit.build_coverage_reconciliation(report_data, _ap_pkt)),
                                ('_oracle.json', _ap_emit.build_oracle(report_data, _ap_pkt))):
            with open(_ap_base + _ap_fn, 'w', encoding='utf-8') as _apf:
                json.dump(_ap_obj, _apf, indent=2, ensure_ascii=False, default=str)
        with open(os.path.join(_ap_out, f'analyst_cache_identity_{_pname_file}.txt'), 'w', encoding='utf-8') as _apf:
            _apf.write(_ap_cache)
        # FAIL CLOSED: a non-atomic / calculation-requiring packet is a release blocker.
        if not (_ap_sa['zero_silently_incomplete'] and _ap_sa['zero_future_information_leaks']
                and _ap_sa['zero_analyst_calculations_required']):
            raise RuntimeError('analyst packet NOT atomic/no-calc-safe: failing=%d future_leaks=%d '
                               'analyst_calc_required=%d -- see %s_semantic_audit.json'
                               % (_ap_sa['failing'], _ap_sa['future_information_leaks'],
                                  _ap_sa['analyst_calculation_required_count'], _ap_base))
        print(f"  ✓ Sealed atomic analyst packet ({_ap_idy['build_id']}): {_ap_base}.json "
              f"(required={_ap_pkt['manifest']['required_count']} optional={_ap_pkt['manifest']['optional_count']} "
              f"hash={_ap_pkt['manifest']['packet_hash'][:12]} semantic_failing={_ap_sa['failing']} "
              f"future_leaks={_ap_sa['future_information_leaks']} zero_calc={_ap_sa['zero_analyst_calculations_required']})")
        print(f"    1) review every required decision once -> save analyst JSON at {_ap_base}_analyst_output.json")
        print(f"    2) python gem_analyzer.py {SESSION_DIR} --quick   (validates binding + renders from cache)")
    except Exception as _ape:
        if _analyst_mode:
            print(f"  ❌ ANALYST-MODE FAIL CLOSED: analyst packet emission failed: {_ape}")
            sys.exit(1)
        print(f"  ⚠ analyst packet emission skipped (non-analyst mode): {_ape}")

    # v8.19.0 Chapter I: explicit input manifest + reproducibility (additive; a failure here
    # never blocks the report). Deterministic given the inputs/config; `generated_at` carries the
    # session fingerprint (not a wall-clock) so the manifest reproduces byte-for-byte.
    try:
        from gem_input_manifest import build_input_manifest as _bim
        # Use the CANONICAL tournament model events (performance.hands / finish / net) so the
        # manifest coverage agrees with the Results section — not the raw per_tournament dicts.
        try:
            import gem_tournament_model as _TMmf
            _im_tours = _TMmf.build_tournament_model(report_data).get('events', []) or []
        except Exception:
            _im_tours = ((report_data.get('usd_overlay', {}) or {}).get('per_tournament', [])
                         or report_data.get('tournaments') or [])
        _rc_state = ((report_data.get('report_completeness') or {}).get('state') or 'AUTO_ONLY')
        try:
            from gem_parser import PARSER_SCHEMA_VERSION as _psv
        except Exception:
            _psv = None
        _im = _bim(SESSION_DIR, hands, _im_tours, stats,
                   analysis_mode=_rc_state,
                   config={'parser_schema_version': _psv,
                           'runtime_version': __import__('gem_version',
                                                         fromlist=['RUNTIME_VERSION']).RUNTIME_VERSION},
                   cache_state=('cached' if globals().get('_USED_CACHE') else 'fresh'),
                   generated_at=(stats.get('_session_fingerprint', {}) or {}).get('hh_hash'))
        _im_path = html_path.replace('.html', '_input_manifest.json')
        with open(_im_path, 'w', encoding='utf-8') as _imf:
            json.dump(_im, _imf, indent=2, default=str, ensure_ascii=False)
        report_data['input_manifest'] = _im
        _cov = _im['coverage']
        print(f"Input manifest: {_im_path}  ({_im['files_discovered']} files, "
              f"{_im['parsed_hands']['count']} hands, {_cov['events_discovered']} events: "
              f"{_cov['hh_backed_events']} HH-backed / {_cov['summary_only_events']} summary-only / "
              f"{_cov['financially_resolved_events']} resolved)")
    except Exception as _ime:
        print(f"  (input manifest skipped: {_ime})")

    # Auto-zip large HTML files (Ron 2026-05-30): browser preview can fail
    # on files >1MB. Wrap both HTML + MD in a zip so the preview doesn't
    # attempt to load the raw file.
    _ZIP_THRESHOLD_KB = 1024  # 1 MB
    if _html_kb >= _ZIP_THRESHOLD_KB:
        import zipfile as _zipfile
        zip_path = html_path.replace('.html', '.zip')
        with _zipfile.ZipFile(zip_path, 'w', _zipfile.ZIP_DEFLATED) as zf:
            zf.write(html_path, os.path.basename(html_path))
            zf.write(md_path, os.path.basename(md_path))
        _zip_kb = os.path.getsize(zip_path) // 1024
        print(f"  ⚠ HTML > 1MB — zipped to prevent browser preview hang:")
        print(f"  ZIP: {zip_path} ({_zip_kb}KB)")
    # Also keep a workspace copy in /home/claude/ for in-pipeline tooling.
    workspace_md = f"/home/claude/GEM_Report_{_pname_file}_{date_compact}.md"
    try:
        with open(workspace_md, 'w', encoding='utf-8') as f: f.write(md_str)
    except OSError:
        pass  # non-fatal if /home/claude doesn't exist (e.g. Windows)

    # Phase 4.6 C: GTOW manifest — build from real session data when requested.
    # Gated by GEM_GTOW_MANIFEST env var (set by gem_run.py --gtow-manifest).
    if os.environ.get('GEM_GTOW_MANIFEST', '').lower() in ('1', 'true', 'yes'):
        try:
            import gem_gtow
            app_det_map = report_data.get('appendix_hand_details') or {}
            pairs = []
            for h in hands:
                hid = h.get('id', '')
                det = app_det_map.get(hid, {})
                pairs.append((h, det))
            manifest = gem_gtow.build_manifest(pairs, rd=report_data)
            manifest_path = f"{out_dir}/_gtow_manifest.json"
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            n_ready = sum(1 for r in manifest if r['link_status'] == 'ready')
            n_partial = sum(1 for r in manifest if r['link_status'] == 'partial')
            n_unavail = sum(1 for r in manifest if r['link_status'] == 'unavailable')
            print(f"\nGTOW manifest: {manifest_path} ({len(manifest)} hands: "
                  f"{n_ready} ready, {n_partial} partial, {n_unavail} unavailable)")
        except Exception as _gtow_e:
            print(f"\n  GTOW manifest skipped: {type(_gtow_e).__name__}: {_gtow_e}")

    # Phase 4.6 D: timing summary
    _t_total = _time.perf_counter() - _t_pipeline_start
    print(f"\n{'='*60}\nTIMING SUMMARY\n{'='*60}")
    print(f"  Parse:      {_t_parse:6.1f}s")
    print(f"  Analyze:    {_t_analyze:6.1f}s")
    try:
        print(f"  Profiler:   {_t_profiler:6.1f}s")
    except NameError:
        pass
    try:
        print(f"  Verdicts:   {_t_verdict:6.1f}s")
    except NameError:
        pass
    print(f"  Render:     {_t_render:6.1f}s")
    print(f"  Total:      {_t_total:6.1f}s")
    # v8.12.10: completeness state at the very end so the operator's last
    # line of output answers "is this a final analyst report?"
    try:
        _print_completeness(_rc_full, where='full')
    except NameError:
        pass

    # ---- H1: RUN MANIFEST ----
    # Self-describing record for reproducibility. Captures code version,
    # input files, config, timing, and output paths in one JSON.
    try:
        import hashlib as _hl_m
        _manifest = {
            # v8.14.1 hotfix (#5 metadata consistency): manifest reports the
            # RUNTIME/release version (single source of truth, gem_version), not
            # the pinned report-FORMAT version. Format version kept as its own
            # field so both are visible and unambiguous.
            'version': report_data.get('renderer_version') or
                       __import__('gem_version', fromlist=['RUNTIME_VERSION']).RUNTIME_VERSION,
            'report_format_version':
                       __import__('gem_report_draft.draft', fromlist=['VERSION']).VERSION,
            'timestamp': str(stats.get('volume', {}).get('date', '')),
            'session_dir': SESSION_DIR,
            'player': _pname_display,
            'input_files': sorted(os.path.basename(f) for f in _hh_files) if '_hh_files' in dir() else [],
            # v8.12.8 QA2: read the session-suffixed marker (the writer keys
            # by player+slug); the suffix-less path was a stale global file.
            'input_hash': (lambda _ip: open(_ip).read().strip()
                           if os.path.exists(_ip) else '')(
                '/home/claude/.gem_hh_hash_%s_%s' % (
                    _pname_file,
                    os.path.basename(os.path.normpath(SESSION_DIR))
                    .replace(' ', '_')[:30])
                if SESSION_DIR else
                f'/home/claude/.gem_hh_hash_{_pname_file}'),
            'n_hands': len(hands),
            'n_tournaments': len(tournaments),
            'cli_flags': {
                'section_filter': _section_filter,
                'analyst_file': _analyst_file_override,
                'require_analyst': _require_analyst,
                'quick_mode': _quick_mode,
                'player': _player_name,
            },
            'timing': {
                'parse_s': round(_t_parse, 1),
                'analyze_s': round(_t_analyze, 1),
                'profiler_s': round(_t_profiler, 1) if '_t_profiler' in dir() else None,
                'verdicts_s': round(_t_verdict, 1) if '_t_verdict' in dir() else None,
                'render_s': round(_t_render, 1),
                'total_s': round(_t_total, 1),
            },
            'outputs': {
                'html': html_path,
                'md': md_path,
            },
            # v8.12.10 (pipeline trust contract): completeness + summary
            # availability in the manifest so handoffs are unambiguous.
            'analyst_status': _rc_full.get('state'),
            'analyst_hand_entries': _rc_full.get('reviewed_hands'),
            'candidate_hands_awaiting': _rc_full.get('awaiting_candidates'),
            'game_summaries_found': (
                (report_data.get('usd_overlay') or {}).get('status')
                != 'no_summaries_found'),
        }
        _manifest_path = f'/home/claude/_run_manifest_{_pname_file}_{date_compact}.json'
        with open(_manifest_path, 'w', encoding='utf-8') as _mf:
            json.dump(_manifest, _mf, indent=2, ensure_ascii=False)
        print(f"\n  Run manifest: {_manifest_path}")
        # v8.14.1 hotfix (#7): write a human-readable run log alongside the
        # outputs so the outputs package carries it (first real hotfix run).
        _runlog_path = f'/home/claude/_run_log_{_pname_file}_{date_compact}.txt'
        try:
            _ml = _manifest
            with open(_runlog_path, 'w', encoding='utf-8') as _lf:
                _lf.write(f"GEM run log — {_ml.get('player', '')} "
                          f"{_ml.get('timestamp', '')}\n")
                _lf.write(f"runtime version : {_ml.get('version', '')}\n")
                _lf.write(f"report format   : {_ml.get('report_format_version', '')}\n")
                _lf.write(f"hands / tourneys: {_ml.get('n_hands', '?')} / "
                          f"{_ml.get('n_tournaments', '?')}\n")
                _lf.write(f"analyst status  : {_ml.get('analyst_status', '')}\n")
                _lf.write(f"game summaries  : {_ml.get('game_summaries_found', '')}\n")
                _lf.write(f"timing (s)      : {_ml.get('timing', {})}\n")
                _lf.write(f"outputs         : {_ml.get('outputs', {})}\n")
                _lf.write(f"input files     : {_ml.get('input_files', [])}\n")
                _lf.write("\nNote: console stderr carries any phevaluator/EAI "
                          "degradation or report-lint warnings for this run.\n")
            print(f"  Run log: {_runlog_path}")
        except Exception as _le:
            print(f"  Run log skipped: {_le}")
    except Exception as _me:
        print(f"  Run manifest skipped: {_me}")

    # ---- POST-RENDER VALIDATION + HANDOVER PROMPT ----
    # Auto-run validation checks on the generated report and print a
    # structured handover request so the analyst surfaces bugs/friction
    # without being asked.
    print(f"\n{'='*60}")
    print("POST-RENDER VALIDATION")
    print(f"{'='*60}")
    _val_issues = []
    try:
        _html_content = open(html_path, encoding='utf-8').read()
        # Check 1: escaped hand-list-triggers
        _n_escaped = _html_content.count('&lt;a class=&quot;hand-list-trigger')
        _n_live = _html_content.count('<a class="hand-list-trigger"')
        if _n_escaped > 0:
            _val_issues.append(f"❌ {_n_escaped} escaped hand-list-trigger tags (should be 0)")
        else:
            print(f"  ✅ Hand-list triggers: {_n_live} live, 0 escaped")
        # Check 2: AWAITING ANALYST leak (v8.14.3 Issue 2 — state-aware). A
        # visible "awaiting analyst" label is a HARD error only when the report
        # claims ANALYST_COMPLETE; in AUTO_ONLY/ANALYST_PARTIAL it is expected
        # and informational (flagging it there was a false positive).
        _n_await = _html_content.lower().count('awaiting analyst')
        _state_full = (_rc_full or {}).get('state')
        if _n_await > 0 and _state_full == 'ANALYST_COMPLETE':
            _val_issues.append(f"❌ {_n_await} 'AWAITING ANALYST' occurrences in an "
                               f"ANALYST_COMPLETE report (Issue 2)")
        elif _n_await > 0:
            print(f"  ℹ️  {_n_await} 'awaiting analyst' label(s) "
                  f"(expected for {_state_full or 'non-complete'})")
        else:
            print(f"  ✅ No 'AWAITING ANALYST' leaks")
        # Check 3: player name leak (non-Ron)
        if _pname_display.lower() != 'knockman':
            _n_knock = _html_content.lower().count('knockman')
            if _n_knock > 0:
                _val_issues.append(f"❌ {_n_knock} 'Knockman' occurrences (should be 0 for {_pname_display})")
            else:
                print(f"  ✅ No 'Knockman' leaks (player: {_pname_display})")
        # Check 4: broken anchors
        import re as _re_val
        _hrefs = set(_re_val.findall(r'href=["\']#([^"\']+)["\']', _html_content))
        _ids = set(_re_val.findall(r'id=["\']([^"\']+)["\']', _html_content))
        _ids |= set(_re_val.findall(r'name=["\']([^"\']+)["\']', _html_content))
        # Exclude JS template patterns (sec-app-hand- built at runtime)
        _broken = sorted(h for h in _hrefs if h not in _ids
                         and 'sec-app-hand-' not in h
                         and not h.startswith('report-search'))
        if _broken:
            _val_issues.append(f"⚠️  {len(_broken)} broken anchor links: {_broken[:5]}")
        else:
            print(f"  ✅ All {len(_hrefs)} anchor links resolve")
        # Check 5: stat cards count (prefix match — cards can have modifiers
        # like stat-pos/stat-neg: class="stat-card stat-pos")
        _n_stat = (_html_content.count('class="stat-card') +
                   _html_content.count("class='stat-card"))
        if _n_stat != 12:
            _val_issues.append(f"⚠️  {_n_stat} stat cards (expected 12)")
        else:
            print(f"  ✅ 12 stat cards in top bar")
        # Check 6: draw profile in hand grids (match both quote styles)
        # v8.12.4 (QA item 20): with lazy hands ON the grid annotations live
        # INSIDE the deflate payload — a raw-text count reports 0 and reads
        # as a wiring break. Decode the lazyHands payload and count there too.
        _lazy_html_v = ''
        try:
            import zlib as _zlib_v, base64 as _b64_v
            for _pm in _re_val.finditer(
                    r'["\']([A-Za-z0-9+/=]{200000,})["\']', _html_content):
                _pd = _zlib_v.decompress(
                    _b64_v.b64decode(_pm.group(1)), -15).decode('utf-8', 'replace')
                if '<article' in _pd[:300]:
                    _lazy_html_v = _pd
                    break
        except Exception:
            pass
        _n_dp = (_html_content.count('class="draw-profile"') +
                 _html_content.count("class='draw-profile'") +
                 _lazy_html_v.count('class="draw-profile"') +
                 _lazy_html_v.count("class='draw-profile'"))
        _dp_src = ' (incl. lazy payload)' if _lazy_html_v else ''
        print(f"  ℹ️  {_n_dp} draw-profile annotations in hand grids{_dp_src}")
        # Check 7: buy-in column
        _n_bi_zero = _html_content.count('| $0 |')
        if _n_bi_zero > 2:
            _val_issues.append(f"⚠️  {_n_bi_zero} '$0' buy-in cells (check ₮→$ conversion)")
        # Check 8: POPUP COVERAGE — every hand ID in a hand-list-trigger
        # must have a matching sec-app-hand-{id} anchor so clicking through
        # shows the actual hand detail.
        # Check actual hand-ref links (href="#sec-app-hand-X") vs appendix anchors.
        # This is more precise than checking data-hids (which are summary triggers
        # that may intentionally not have appendix entries).
        _hand_ref_targets = set(_re_val.findall(
            r'href=["\']#sec-app-hand-([^"\']+)["\']', _html_content))
        _app_anchors = set(_re_val.findall(
            r'id=["\']sec-app-hand-([^"\']+)["\']', _html_content))
        # v8.12.4 (QA item 19): anchors materialized from the lazy payload
        # count as resolvable — scan the decoded payload too.
        if _lazy_html_v:
            _app_anchors |= set(_re_val.findall(
                r'id=["\']sec-app-hand-([^"\']+)["\']', _lazy_html_v))
            _app_anchors |= set(_re_val.findall(
                r"data-hand-id=['\"]([^'\"]+)['\"]", _lazy_html_v))
        _orphan_refs = _hand_ref_targets - _app_anchors
        if _orphan_refs:
            _val_issues.append(
                f"⚠️  {len(_orphan_refs)} hand-ref links have no appendix "
                f"entry: {sorted(_orphan_refs)[:5]}")
        else:
            print(f"  ✅ All {len(_hand_ref_targets)} hand-ref links resolve "
                  f"to appendix entries ({len(_app_anchors)} total)")
        # Check 9 (v8.14.3 Issue 1): financial one-source-of-truth — the
        # top-level cost/ABI must equal the parsed USD overlay totals.
        _ov_v = report_data.get('usd_overlay') or {}
        _ovt_v = _ov_v.get('totals') or {}
        if _ov_v.get('status') == 'parsed' and _ovt_v.get('total_cost') and _ovt_v.get('n_bullets'):
            _exp_inv_v = round(float(_ovt_v['total_cost']), 2)
            _exp_abi_v = round(float(_ovt_v['total_cost']) / float(_ovt_v['n_bullets']), 2)
            if abs(round(float(report_data.get('total_invested') or 0), 2) - _exp_inv_v) > 0.01:
                _val_issues.append(f"❌ financial: top-level total_invested "
                                   f"{report_data.get('total_invested')} != overlay "
                                   f"total_cost {_exp_inv_v} (Issue 1)")
            elif abs(round(float(report_data.get('avg_buyin') or 0), 2) - _exp_abi_v) > 0.01:
                _val_issues.append(f"❌ financial: top-level avg_buyin "
                                   f"{report_data.get('avg_buyin')} != overlay "
                                   f"cost/bullets {_exp_abi_v} (Issue 1)")
            else:
                print(f"  ✅ Financial one-source-of-truth: cost=${_exp_inv_v} "
                      f"ABI=${_exp_abi_v} (overlay = top-level)")
        # Check 10 (v8.14.3 Issue 3): analyst-critical hands (III.1/III.2 or
        # significant/critical loss) must not be budget_trimmed, and the
        # decoded lazy payload must carry their full detail.
        _ac_v = report_data.get('analyst_commentary') or {}
        _crit_v = set()
        for _hid_v, _cmt_v in _ac_v.items():
            if str(_hid_v).startswith('__') or not isinstance(_cmt_v, dict):
                continue
            _vd_v = str(_cmt_v.get('verdict', '') or '')
            if _vd_v.startswith('III.1') or _vd_v.startswith('III.2'):
                _crit_v.add(str(_hid_v)[-8:])
        for _src_v in ('_significant_loss_ids', '_critical_need_ids'):
            for _x_v in (report_data.get(_src_v) or []):
                _crit_v.add(str(_x_v)[-8:])
        _crit_v = {s for s in _crit_v if s and s.isdigit()}
        if _crit_v:
            _trim_v = {m[-8:] for m in _re_val.findall(
                r"data-hand-id=['\"]([\w-]+)['\"]\s+data-availability=['\"]budget_trimmed['\"]",
                _html_content)}
            _bad_trim_v = sorted(_crit_v & _trim_v)
            if _bad_trim_v:
                _val_issues.append(f"❌ {len(_bad_trim_v)} analyst-critical hand(s) "
                                   f"rendered budget_trimmed: {_bad_trim_v[:8]} (Issue 3)")
            # decoded payload: critical hand must not be a stub
            _stub_v = 'trimmed for report size'
            _stub_hits = set()
            for _cm_v in _re_val.finditer(
                    r"data-hand-id=['\"]([\w-]+)['\"][^>]*>(?:(?!</article>).)*?"
                    + _re_val.escape(_stub_v), _lazy_html_v, _re_val.DOTALL):
                _stub_hits.add(_cm_v.group(1)[-8:])
            _bad_stub_v = sorted(_crit_v & _stub_hits)
            if _bad_stub_v:
                _val_issues.append(f"❌ {len(_bad_stub_v)} analyst-critical hand(s) "
                                   f"stub-only in decoded payload: {_bad_stub_v[:8]} (Issue 3)")
            if not _bad_trim_v and not _bad_stub_v:
                print(f"  ✅ {len(_crit_v)} analyst-critical hand(s) carry full "
                      f"detail (none budget_trimmed)")
        # Check 11 (v8.14.3 Issue 3): no full+trimmed DUPLICATE — a hand must
        # not appear both as a budget_trimmed shell stub and a full lazy card.
        _trim_all_v = {m[-8:] for m in _re_val.findall(
            r"data-hand-id=['\"]([\w-]+)['\"]\s+data-availability=['\"]budget_trimmed['\"]",
            _html_content)}
        if _trim_all_v and _lazy_html_v:
            # v8.16.2 Phase B: count only FULL cards in the lazy payload. Full
            # cards carry `data-hand-id=X data-format=...`; budget-trimmed stubs
            # are themselves pb-lazy (their inner HTML is in the same payload) but
            # carry data-availability='budget_trimmed' and NO data-format. The old
            # bare `data-hand-id` regex matched the stubs too, so it flagged every
            # stub as "also a full card" (a false positive on large sessions). The
            # --quick mirror already excludes stubs via _decode_lazy_cards; this
            # aligns the full-pipeline check to the same TRUE invariant.
            _full_suf_v = {m[-8:] for m in _re_val.findall(
                r"data-hand-id=['\"]([\w-]+)['\"]\s+data-format=", _lazy_html_v)}
            _dup_v = sorted(_trim_all_v & _full_suf_v)
            if _dup_v:
                _val_issues.append(f"❌ {len(_dup_v)} hand(s) rendered BOTH a "
                                   f"budget_trimmed stub and a full card: {_dup_v[:8]} (Issue 3)")
        # Check 12 (v8.14.4): no raw chart IDs (PUSH_/CALLJAM_/REJAM_/OPEN_/JAM_)
        # in user-facing prose — rendered shell visible text, decoded lazy cards,
        # and analyst-commentary prose. Machine-only uses (data-chart-id, JS keys)
        # are stripped by the helper, so only visible prose is flagged.
        try:
            from gem_chart_labels import find_raw_chart_ids_in_user_text as _frci_v
            _raw_v = set(_frci_v(_html_content, is_html=True))
            if _lazy_html_v:
                _raw_v.update(_frci_v(_lazy_html_v, is_html=True))
            def _collect_strs_v(o, acc):
                if isinstance(o, str): acc.append(o)
                elif isinstance(o, dict):
                    for _vv in o.values(): _collect_strs_v(_vv, acc)
                elif isinstance(o, (list, tuple)):
                    for _vv in o: _collect_strs_v(_vv, acc)
            _acs_v = []
            _collect_strs_v(report_data.get('analyst_commentary') or {}, _acs_v)
            _raw_v.update(_frci_v('\n'.join(_acs_v), is_html=False))
            if _raw_v:
                _val_issues.append(f"❌ {len(_raw_v)} raw chart ID(s) in user-facing "
                                   f"text (humanize before render): {sorted(_raw_v)[:8]} (v8.14.4)")
            else:
                print(f"  ✅ No raw chart IDs in user-facing prose")
        except Exception:
            pass
        # Check 13 (v8.14.4): cash+ticket return-basis disclosure present when the
        # parsed overlay carries ticket value (mirrors _quick_validate_render 2b).
        _ovv = report_data.get('usd_overlay') or {}
        _ovtv = _ovv.get('totals') or {}
        if _ovv.get('status') == 'parsed' and float(_ovtv.get('total_ticket_value') or 0) > 0:
            _tlc = _html_content.lower()
            if not ('cash + ticket' in _tlc or ('ticket value' in _tlc and 'cash' in _tlc)):
                _val_issues.append("❌ total_ticket_value > 0 but no visible cash + "
                                   "ticket return-basis disclosure (v8.14.4)")
            else:
                print(f"  ✅ Cash + ticket return-basis disclosed (ticket value > 0)")
        # Check 14 (v8.16.4 Obj-5): every Mistake/Punt-class hand-level verdict
        # must be substantiated by a visible explanation. The live render already
        # downgrades an auto Mistake with no action-level marker to Review
        # (_review_downgrade via auto_verdict_needs_review); this validator is the
        # secondary net and CALLS the gem_review_trust.verdict_validation_issue
        # contract directly. On AUTO_ONLY reports analyst_commentary is empty, so
        # this is a no-op there.
        try:
            from gem_review_trust import verdict_validation_issue as _vvi14
            _ac14 = report_data.get('analyst_commentary') or {}
            _v14 = []
            for _hid14, _c14 in _ac14.items():
                if not isinstance(_c14, dict):
                    continue
                _vd14 = str(_c14.get('verdict', '') or '')
                _low14 = _vd14.lower()
                if _vd14.startswith('III.2') or 'mistake' in _low14:
                    _lab14 = 'Mistake'
                elif _vd14.startswith('III.1') or 'punt' in _low14:
                    _lab14 = 'Punt'
                else:
                    continue
                _has14 = bool((_c14.get('argument') or '').strip())
                _iss14 = _vvi14(_lab14, has_bound_action_marker=_has14,
                                has_explanation=_has14)
                if _iss14:
                    _v14.append(f"⚠️  {str(_hid14)[-8:]} {_lab14}: {_iss14}")
            if _v14:
                _val_issues.extend(_v14)
            else:
                print(f"  ✅ All Mistake/Punt verdicts substantiated (v8.16.4 Obj-5)")
        except Exception:
            pass
        # Check 15 (v8.17.1 P5(2,3)): marker/commentary parity + scored all-in
        # completeness BUILD GATES. Built from STRUCTURED decision/evidence atoms
        # (analyst_commentary verdict+argument, villain_intel atoms, the
        # classify_preflop_allin kind + the rendered pot-odds fields + the render's
        # stamped _allin_register) — never from text proximity. A build FAILs (❌) on
        # an orphan / wrong-player / wrong-action marker, or a scored all-in that
        # rendered neither complete math nor an explicit no_clear_lesson.
        try:
            from gem_review_trust import (marker_parity_issues as _mpi15,
                                          classify_preflop_allin as _cpa15,
                                          allin_rendered_fields as _arf15,
                                          allin_completeness_issue as _aci15)
            _ac15 = report_data.get('analyst_commentary') or {}
            _atoms_by_hand15 = ((report_data.get('villain_intel') or {})
                                .get('atoms_by_hand') or {})
            _pob15 = report_data.get('pot_odds_by_hand') or {}
            _mk_issues, _ai_issues = [], []
            for _h15 in (hands or []):
                _hid15 = _h15.get('id') or ''
                if not _hid15:
                    continue
                _hs15 = _hid15[-8:] if len(_hid15) > 8 else _hid15
                # --- marker/commentary parity (structured identities only) ---
                _markers, _notes, _ve, _atoms = [], set(), set(), {}
                _c15 = _ac15.get(_hid15) or _ac15.get(_hs15) or {}
                if isinstance(_c15, dict):
                    _vd15 = str(_c15.get('verdict', '') or '').lower()
                    if (_vd15.startswith('iii.2') or _vd15.startswith('iii.1')
                            or 'mistake' in _vd15 or 'punt' in _vd15):
                        _markers.append({'kind': 'mistake', 'ref': _hid15})
                        if (_c15.get('argument') or '').strip():
                            _notes.add(_hid15)
                for _atom in (_atoms_by_hand15.get(_hid15)
                              or _atoms_by_hand15.get(_hs15) or []):
                    if not isinstance(_atom, dict):
                        continue
                    _aref = '%s:%s:%s' % (_hs15, _atom.get('signal', ''),
                                          _atom.get('street', ''))
                    _ve.add(_aref)
                    _atoms[_aref] = {'player': _atom.get('villain_position'),
                                     'street': _atom.get('street'),
                                     'action_index': _atom.get('action_index')}
                    _markers.append({'kind': 'villain_evidence', 'ref': _aref,
                                     'player': _atom.get('villain_position'),
                                     'street': _atom.get('street'),
                                     'action_index': _atom.get('action_index')})
                for _miss in _mpi15(_markers, _notes, _ve, atoms=_atoms):
                    _mk_issues.append("❌ %s marker parity: %s" % (_hs15, _miss))
                # --- scored all-in completeness (only hands the render processed) ---
                if _h15.get('pf_allin') and _h15.get('_allin_register'):
                    _k15 = _cpa15(_h15)[0]
                    if _k15 not in ('not_allin', 'unknown'):
                        _po15 = _pob15.get(_hid15) or _pob15.get(_hs15)
                        _ci15 = _aci15(_k15, _arf15(_po15, _h15, _k15),
                                       register=_h15.get('_allin_register'))
                        if _ci15:
                            _ai_issues.append("❌ %s all-in completeness: %s"
                                              % (_hs15, _ci15))
            if _mk_issues:
                _val_issues.extend(_mk_issues)
            else:
                print("  ✅ Marker/commentary parity clean (v8.17.1 P5)")
            if _ai_issues:
                _val_issues.extend(_ai_issues)
            else:
                print("  ✅ All scored all-ins complete or no_clear_lesson (v8.17.1 P5)")
        except Exception:
            pass
    except Exception as _val_e:
        print(f"  ⚠️  Validation skipped: {_val_e}")

    if _val_issues:
        print(f"\n  {'='*50}")
        print(f"  ISSUES FOUND ({len(_val_issues)}):")
        for _vi in _val_issues:
            print(f"    {_vi}")
    else:
        print(f"\n  ✅ All validation checks passed")

    # Handover prompt — reminds the analyst to surface bugs/friction
    print(f"\n{'='*60}")
    print("ANALYST HANDOVER REMINDER")
    print(f"{'='*60}")
    print("""
  Before delivering this report, please write a brief handover covering:

  1. BUGS: anything that rendered wrong, showed incorrect data, or looked off.
     For each: symptom, section, severity, and how to reproduce.
  2. PIPELINE FRICTION: any step that was slow, confusing, or needed a
     manual workaround. What would have saved time?
  3. DATA QUALITY: any automated classification (draw profile, archetype,
     verdict pre-fill, pot odds) that was wrong. What it said vs what it
     should have said.
  4. MISSING FEATURES: things you did manually that should be automated.
  5. TEMPLATE QUALITY: did pre-filled verdicts help? What % confirmed vs
     overridden? Were draw profiles and villain archetypes useful?

  Format as markdown. Include file names and line numbers where possible.
  This handover goes directly to Claude Code for the next improvement cycle.
""")
