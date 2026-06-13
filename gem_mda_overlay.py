#!/usr/bin/env python3
"""
gem_mda_overlay.py — v7.39 (2026-05-09)

Mass-Data-Analysis (v7.5) population-exploit overlay.

Sits alongside existing detection layers in gem_analyzer.py. Sources its
recommendations from the structured MDA_RECOMMENDATIONS list below, which
mirrors the human-readable MDA_v7_5_Reference.txt project file.

Architectural slot
==================
- Priority: SECONDARY (same slot as Jaka K-rules / Amit M-rules).
- Below: Dave J-series (always wins on conflict).
- Below: Ron's session leak data (always wins on conflict).
- Above: Default GTO baseline (when no other rule applies).

How it's used
=============
1. annotate_deviations(deviations, hands_by_id) walks the existing pre-flop
   deviation list (from check_preflop_deviations) and attaches `mda_overlay`
   to any deviation whose hand+spot matches an MDA recommendation. The
   downstream renderer surfaces this as a column in deviation tables.

2. find_aligned_and_missed_exploits(hands) walks the entire hand set looking
   for spots where Hero's action ALIGNED with an MDA recommendation (positive
   case) OR DEVIATED from one in the wrong direction (missed exploit). Output
   fed into Section XIII.7 in the renderer.

The overlay is purely additive — it never SUPPRESSES a flag from another
detector. It only ADDS context (MDA Note column / Section XIII.7).
"""

from __future__ import annotations


# =============================================================================
# COMBO EXPANSION (mirrors gem_analyzer._expand but standalone for testing)
# =============================================================================

_RANKS_HI = 'AKQJT98765432'
_RANK_IDX = {r: i for i, r in enumerate(_RANKS_HI)}


def _expand_token(tok):
    """Expand a single token like 'AKs+', '77+', '66+' to a set of combos."""
    tok = tok.strip()
    if not tok: return set()
    # Pair: '77' / '77+'
    if len(tok) >= 2 and tok[0] == tok[1] and tok[0] in _RANK_IDX:
        if tok.endswith('+'):
            top = _RANK_IDX[tok[0]]
            return {_RANKS_HI[i] * 2 for i in range(top + 1)}
        return {tok[:2]} if len(tok) == 2 else set()
    # Non-pair: XYs / XYo / XYs+ / XYo+
    if len(tok) >= 3 and tok[2] in ('s', 'o'):
        x, y, suit = tok[0], tok[1], tok[2]
        if x not in _RANK_IDX or y not in _RANK_IDX: return set()
        xi, yi = _RANK_IDX[x], _RANK_IDX[y]
        if xi >= yi: return set()
        if tok.endswith('+'):
            # second card spans from y up to (but not including) x
            return {x + _RANKS_HI[i] + suit for i in range(yi, xi, -1) if i > xi}
        if len(tok) == 3:
            return {tok}
    return set()


def _expand_combo_string(combo_str):
    """Expand 'A7s+, 22+, J9o+' (comma-separated) to a flat set of combos."""
    out = set()
    for tok in combo_str.split(','):
        tok = tok.strip()
        if not tok: continue
        out |= _expand_token(tok)
    return out


# =============================================================================
# MDA RECOMMENDATIONS (machine-readable form of MDA_v7_5_Reference.txt)
# =============================================================================
#
# Each entry has:
#   id           — short stable identifier (used in mda_overlay.rec_id)
#   description  — one-liner for renderer columns
#   trigger      — dict of conditions: hero_pos, opener_pos, stack_min,
#                   stack_max, opener_action, jammer_pos, first_in
#   combos       — set of combos this recommendation applies to
#   ev_bb        — EV per event in BB (positive = Hero gain by following rec)
#   confidence   — 'HIGH' | 'MED' | 'LOW'
#   action       — 'raise' | '3bet' | 'jam' | 'fold' | 'rejam'
#   action_hint  — human-readable suggestion for the renderer

MDA_RECOMMENDATIONS = [
    {
        'id': 'MDA-1',
        'description': 'BvB BB iso-raise vs SB limp (30+BB)',
        'trigger': {'hero_pos': 'BB', 'opener_pos': 'SB',
                    'opener_action': 'limp', 'stack_min': 30},
        'combos': _expand_combo_string('66+, A7s+, A9o+, J9s+, J9o+'),
        'ev_bb': 3.1, 'confidence': 'HIGH', 'action': 'raise',
        'action_hint': 'Iso-raise 3.5–5x; ~9% range vs SB limp captures +3.1 BB',
    },
    {
        'id': 'MDA-2a',
        'description': 'BB 3-bet vs MP open (~100BB) — exploit-edge expansion',
        'trigger': {'hero_pos': 'BB', 'opener_pos': 'MP', 'stack_min': 80},
        # v7.40 B33: original combo set was '99+, AQs+, AQo+' which includes
        # QQ/KK/AA/AKs/AKo — those are universal default 3-bets, so flagging
        # alignment with KK is "Hero made the obvious play." Restrict to the
        # exploit-edge subset: 99, TT, JJ, AQs, AQo. These are the hands the
        # MDA framework adds beyond default BB-vs-MP-100BB 3-bet ranges.
        'combos': {'99', 'TT', 'JJ', 'AQs', 'AQo'},
        'ev_bb': 2.0, 'confidence': 'HIGH', 'action': '3bet',
        'action_hint': 'Population under-3-bets vs MP; +2.0 BB threshold range. Exploit-edge combos only (99-JJ, AQs, AQo) — default 3-bet hands (QQ+/AKs/AKo) are filtered out.',
    },
    {
        'id': 'MDA-2b',
        'description': 'BB tighten 3-bet vs SB open',
        'trigger': {'hero_pos': 'BB', 'opener_pos': 'SB',
                    'opener_action': 'raise'},
        'combos': _expand_combo_string('JJ+, AKs+, AKo'),
        'ev_bb': -3.7, 'confidence': 'HIGH', 'action': '3bet',
        'action_hint': 'Population over-3-bets BvB SB-open; tighten to ~2.5%',
    },
    {
        'id': 'MDA-3',
        'description': 'MP 10BB push wider (~34%)',
        'trigger': {'hero_pos': 'MP', 'stack_max': 12, 'first_in': True,
                    # v7.40 B33: skip if Hero's open-raise effectively committed
                    # the stack. At 6-9BB, a 2x open commits Hero anyway, so
                    # "raise → should jam" is a sizing-bucket cosmetic, not an
                    # EV leak. action_summary contains 'ALL-IN' on PF jams.
                    'exclude_action_summary_contains': 'ALL-IN'},
        'combos': _expand_combo_string(
            '22+, A2s+, A2o+, K5s+, K7o+, Q8s+, QTo+, JTs+, JTo+, 65s+, 97s+'),
        'ev_bb': 1.7, 'confidence': 'HIGH', 'action': 'jam',
        'action_hint': 'Population under-jams MP at 10BB; double rate captures +1.7 BB/jam',
    },
    {
        'id': 'MDA-4',
        'description': 'REJAM premium pairs 12-25BB',
        # v7.40 B33 (refined): MDA-4 ref spec requires `hero_action=rejam_or_should` —
        # Hero faced a jam (or pre-jam action that escalated to a jam) and
        # decided rejam/call/fold. Approximation: include the spot when EITHER
        # (a) Hero played passively (call/fold) facing >=2 prior raises, OR
        # (b) the hand ended in a preflop all-in AND Hero is not the first
        # opener (so Hero's role was responder, even if pf_action shows
        # Hero's *first* action as a 3-bet that later got jammed back).
        # The gate is enforced via 'require_rejam_context' below; trigger
        # also enforces stack range + Hero is not the lone opener.
        'trigger': {'stack_min': 12, 'stack_max': 25,
                    'first_in': False,
                    'require_rejam_context': True},
        'combos': _expand_combo_string('TT+'),
        'ev_bb': 9.0, 'ev_bb_range': (5.0, 12.0),
        'confidence': 'HIGH', 'action': 'rejam',
        'action_hint': 'Largest single MDA exploit: rejam premiums vs flat at 12-25BB (EV varies +5 to +12 BB by matchup)',
    },
    {
        'id': 'MDA-5a',
        'description': 'CO vs BTN RJ — fold 66',
        'trigger': {'hero_pos': 'CO', 'jammer_pos': 'BTN', 'stack_max': 25},
        'combos': {'66'},
        'ev_bb': -10.2, 'confidence': 'HIGH', 'action': 'fold',
        'action_hint': 'Pop CALLRJ 66 vs BTN RJ is −10.2 BB; default fold',
    },
    {
        'id': 'MDA-5b',
        'description': 'MP vs CO RJ — fold 77',
        'trigger': {'hero_pos': 'MP', 'jammer_pos': 'CO', 'stack_max': 25},
        'combos': {'77'},
        'ev_bb': -7.0, 'confidence': 'MED', 'action': 'fold',
        'action_hint': 'Pop CALLRJ 77 vs CO RJ is −7.0 BB; default fold',
    },
    {
        'id': 'MDA-5c',
        'description': 'SB vs BB RJ — fold ATo',
        'trigger': {'hero_pos': 'SB', 'jammer_pos': 'BB', 'stack_max': 25},
        'combos': {'ATo'},
        'ev_bb': -6.6, 'confidence': 'HIGH', 'action': 'fold',
        'action_hint': 'Pop CALLRJ ATo BvB RJ is −6.6 BB; default fold',
    },
    {
        'id': 'MDA-5d',
        'description': 'CO vs BB RJ — fold KQo',
        'trigger': {'hero_pos': 'CO', 'jammer_pos': 'BB', 'stack_max': 25},
        'combos': {'KQo'},
        'ev_bb': -4.8, 'confidence': 'HIGH', 'action': 'fold',
        'action_hint': 'Pop CALLRJ KQo CO vs BB RJ is −4.8 BB; default fold',
    },
    # =========================================================================
    # v9 EXPANSION (added 2026-05-09): Recs 6-17 — BB defense × villain × stack,
    # REJAM premium-pair extension at 25-40BB, LP push transition.
    # Source: MTT_Tactical_Recommendations_v9_FINAL.md
    # =========================================================================
    {
        'id': 'MDA-6',
        'description': 'BB 3-bet vs EP open at 40-50BB',
        'trigger': {'hero_pos': 'BB', 'opener_pos': 'UTG',
                    'stack_min': 40, 'stack_max': 50,
                    'min_pf_raise_count': 1, 'first_in': False,
                    'exclude_pf_action_in': {'fold'}},
        # 40bb: TT+, AJs+, AJo+ ; 50bb tightens to JJ+ but we keep one
        # combined combo set — borderline TT vs EP at 50bb is acceptable.
        'combos': _expand_combo_string('TT+, AJs+, AJo+'),
        'ev_bb': 2.5, 'confidence': 'HIGH', 'action': '3bet',
        'action_hint': '+3.50 BB at 40bb / +1.04 BB at 50bb. Pop 3-bets only 3.7-4.4%.',
    },
    {
        'id': 'MDA-7',
        'description': 'BB 3-bet vs LP open at 15-20BB',
        'trigger': {'hero_pos': 'BB', 'opener_pos_in': {'CO', 'BTN'},
                    'stack_min': 15, 'stack_max': 20,
                    'min_pf_raise_count': 1, 'first_in': False},
        'combos': _expand_combo_string('TT+, AJs+, AJo+'),
        'ev_bb': 1.16, 'confidence': 'HIGH', 'action': '3bet',
        'action_hint': 'Sizing 4.5-5x is effectively a jam at this depth. Pop 3-bets only 2.4%.',
    },
    {
        'id': 'MDA-8',
        'description': 'BB 3-bet vs MP open at 25-30BB',
        'trigger': {'hero_pos': 'BB', 'opener_pos': 'MP',
                    'stack_min': 25, 'stack_max': 30,
                    'min_pf_raise_count': 1, 'first_in': False},
        'combos': _expand_combo_string('99+, AJs+, AKo+'),
        'ev_bb': 1.06, 'confidence': 'HIGH', 'action': '3bet',
        'action_hint': 'Mid-stack version of MDA-2a; threshold tightens to 99+ at this depth. Pop 3-bets 3.2%.',
    },
    {
        'id': 'MDA-9',
        'description': 'BB jam vs EP open at 15-20BB',
        'trigger': {'hero_pos': 'BB', 'opener_pos': 'UTG',
                    'stack_min': 15, 'stack_max': 20,
                    'min_pf_raise_count': 1, 'first_in': False},
        'combos': _expand_combo_string('77+, ATs+, ATo+, KQs'),
        'ev_bb': 2.0, 'confidence': 'HIGH', 'action': 'jam',
        'action_hint': '+1.70 BB vs min-raise / +2.62 BB vs 2.5x. Pop jams 7.1-7.3%.',
    },
    {
        'id': 'MDA-10',
        'description': 'BB jam vs MP open at 25-30BB (3x size)',
        'trigger': {'hero_pos': 'BB', 'opener_pos': 'MP',
                    'stack_min': 25, 'stack_max': 30,
                    'min_pf_raise_count': 1, 'first_in': False},
        'combos': _expand_combo_string('77+, AJs+, ATo+, KQo'),
        'ev_bb': 3.62, 'confidence': 'MED', 'action': 'jam',
        'action_hint': 'Larger 3x sizing creates more dead money. Pop jams only 4.5%.',
    },
    {
        'id': 'MDA-11',
        'description': 'BB jam vs LP open at 25-30BB',
        'trigger': {'hero_pos': 'BB', 'opener_pos_in': {'CO', 'BTN'},
                    'stack_min': 25, 'stack_max': 30,
                    'min_pf_raise_count': 1, 'first_in': False},
        'combos': _expand_combo_string('66+, ATs+, AJo+, KQo, KQs, JTs'),
        'ev_bb': 2.10, 'confidence': 'HIGH', 'action': 'jam',
        'action_hint': 'LP opens wider → BB has more dead money + range edge. Threshold drops to 66+.',
    },
    # ----- Counter-recs (TIGHTEN — flag if Hero played LIGHT in these spots) -----
    {
        'id': 'MDA-12',
        'description': 'TIGHTEN BB 3-bet vs SB BvB at 50BB',
        'trigger': {'hero_pos': 'BB', 'opener_pos': 'SB',
                    'opener_action': 'raise',
                    'stack_min': 45, 'stack_max': 55,
                    'min_pf_raise_count': 1},
        # Hero should ONLY 3-bet JJ+/AKs/AKo here. Anything outside this set is the leak.
        # We model this as "the alignment combo is JJ+/AKs/AKo — anything else is a missed
        # tighten (i.e., Hero's action was 3-bet on a weaker combo, which costs EV).
        'combos': _expand_combo_string('JJ+, AKs, AKo'),
        'ev_bb': -2.03, 'confidence': 'MED', 'action': '3bet',
        'action_hint': 'Pop avg = -2.03 BB. Light 3-bets crushed by polarized SB-open value half. Counter-rec: 3-bet ONLY listed combos; flat or fold others.',
        'counter_rec': True,  # Hero "missed" this rec by 3-betting a weaker combo
    },
    {
        'id': 'MDA-13',
        'description': 'TIGHTEN BB 3-bet vs MP open 100BB at 3x size',
        # Distinguishing 3x from min-raise needs sizing-extraction. For now, gate
        # on stack ≥ 90BB and rely on counter-rec semantics; will refine when
        # opener_size_bb is available in stats.
        'trigger': {'hero_pos': 'BB', 'opener_pos': 'MP',
                    'stack_min': 90, 'min_pf_raise_count': 1,
                    'first_in': False,
                    # B33 follow-on: ideally also require opener_size_bb >= 3.0;
                    # parser doesn't expose this yet — log as backlog.
                    'pending_field': 'opener_size_bb'},
        'combos': _expand_combo_string('QQ+, AQs+, AQo+'),
        'ev_bb': -2.30, 'confidence': 'MED', 'action': '3bet',
        'action_hint': 'At 3x+ open size MP range tightens AND BB pays more. Pop avg -2.30 BB. Counter-rec: tighten to listed combos. SIZING-DEPENDENT — needs opener_size_bb to fire precisely.',
        'counter_rec': True,
    },
    {
        'id': 'MDA-14',
        'description': 'TIGHTEN BB 3-bet vs LP open 100BB big-size',
        'trigger': {'hero_pos': 'BB', 'opener_pos_in': {'CO', 'BTN'},
                    'stack_min': 90, 'min_pf_raise_count': 1,
                    'first_in': False,
                    'pending_field': 'opener_size_bb'},
        'combos': _expand_combo_string('TT+'),
        'ev_bb': -6.20, 'confidence': 'MED', 'action': '3bet',
        'action_hint': 'At 3.3x+ LP players have polarized strong+bluff range. Pop avg -6.20 BB. Counter-rec: 3-bet ONLY TT+. SIZING-DEPENDENT.',
        'counter_rec': True,
    },
    # ----- v9 REJAM extension at 25-40BB (parallels MDA-4) -----
    {
        'id': 'MDA-16',
        'description': 'REJAM premium pairs 25-40BB (extends MDA-4)',
        'trigger': {'stack_min': 25, 'stack_max': 40,
                    'first_in': False,
                    'require_rejam_context': True},
        'combos': _expand_combo_string('TT+'),
        'ev_bb': 8.0, 'ev_bb_range': (5.0, 12.0),
        'confidence': 'MED', 'action': 'rejam',
        'action_hint': 'Same exploit as MDA-4 at deeper stack tier. Cells: BB-vs-HJ JJ +11.5 BB, TT +7.9 BB, QQ +7.7 BB.',
    },
    # ----- v9 LP push transition zone (15-20BB mixed jam/raise) -----
    {
        'id': 'MDA-17',
        'description': 'PUSH 15-20BB LP transition (mixed jam/raise)',
        'trigger': {'hero_pos_in': {'CO', 'BTN'},
                    'stack_min': 15, 'stack_max': 20,
                    'first_in': True},
        'combos': _expand_combo_string(
            '22+, A2s+, A2o+, K6s+, K6o+, Q9s+, QJo+, J9s+, JTo+, T8s+, 65s+'),
        'ev_bb': 1.5, 'confidence': 'HIGH', 'action': 'jam',
        'action_hint': 'LP raises 23%, jams 13% (~36% combined). Mixed strategy is correct here; pure-jam at 10BB transitions to mixed at 20BB.',
    },
]


# =============================================================================
# MATCHING
# =============================================================================

def _matches_trigger(rec, hand):
    """Test whether a hand satisfies all conditions in rec['trigger'].

    v7.40 B33: added action-class + commitment gates so MDA recommendations
    can require Hero be in the right action context (responder vs opener,
    pre-jam vs post-jam, etc.) without leaking misfires from generic
    stack/position gates.
    """
    trig = rec.get('trigger', {})
    if 'hero_pos' in trig and hand.get('position') != trig['hero_pos']:
        return False
    # v9 expansion: set-membership gates for multi-position recs.
    if 'hero_pos_in' in trig and hand.get('position') not in trig['hero_pos_in']:
        return False
    if 'opener_pos' in trig and hand.get('opener_position') != trig['opener_pos']:
        return False
    if 'opener_pos_in' in trig and hand.get('opener_position') not in trig['opener_pos_in']:
        return False
    if 'jammer_pos' in trig and hand.get('jammer_position') != trig['jammer_pos']:
        return False
    if 'opener_action' in trig:
        oa = hand.get('opener_action', '')
        if oa != trig['opener_action']:
            return False
    if 'first_in' in trig and bool(hand.get('first_in')) != bool(trig['first_in']):
        return False
    stack = hand.get('stack_bb', 0)
    if 'stack_min' in trig and stack < trig['stack_min']:
        return False
    if 'stack_max' in trig and stack > trig['stack_max']:
        return False
    # v7.40 B33: action-class gates.
    if 'min_pf_raise_count' in trig:
        if (hand.get('pf_raise_count', 0) or 0) < trig['min_pf_raise_count']:
            return False
    if 'exclude_pf_action_in' in trig:
        if hand.get('pf_action', '') in trig['exclude_pf_action_in']:
            return False
    if 'exclude_action_summary_contains' in trig:
        needle = trig['exclude_action_summary_contains']
        summary = hand.get('action_summary', '') or ''
        if needle in summary:
            return False
    # v7.40 B33 (refined): rejam-context gate. Approximates the MDA-4
    # `hero_action=rejam_or_should` requirement when no parser-level
    # `faced_jam` field is available. True if either (a) Hero played
    # passively to ≥2 prior raises, or (b) the hand ended in a preflop
    # all-in (signaling escalation to a jam-likely scenario regardless of
    # Hero's first labeled action).
    if trig.get('require_rejam_context'):
        summary = hand.get('action_summary', '') or ''
        passive_response = (
            (hand.get('pf_action') in ('call', 'fold'))
            and (hand.get('pf_raise_count', 0) or 0) >= 2
        )
        pf_allin = 'ALL-IN' in summary
        if not (passive_response or pf_allin):
            return False
    return True


def find_overlay_for_hand(hand, hand_combo):
    """Return list of MDA recommendations whose trigger + combo match this hand."""
    matches = []
    for rec in MDA_RECOMMENDATIONS:
        if not _matches_trigger(rec, hand):
            continue
        if hand_combo not in rec['combos']:
            continue
        matches.append(rec)
    return matches


def annotate_deviations(deviations, hands_by_id):
    """Walk deviations and attach `mda_overlay` for each one whose
    hand+spot matches an MDA recommendation. Mutates `deviations` in
    place; returns it for chaining."""
    for d in deviations:
        hid = d.get('id')
        h = hands_by_id.get(hid) if hid else None
        if not h:
            continue
        combo = d.get('cards') or h.get('hand_class') or ''
        if not combo:
            continue
        matches = find_overlay_for_hand(h, combo)
        if not matches:
            continue
        # Attach the highest-EV-magnitude match (most informative)
        best = max(matches, key=lambda r: abs(r.get('ev_bb', 0)))
        d['mda_overlay'] = {
            'rec_id': best['id'],
            'description': best['description'],
            'ev_bb': best['ev_bb'],
            'confidence': best['confidence'],
            'action_hint': best['action_hint'],
            'all_matches': [r['id'] for r in matches],
        }
    return deviations


def find_aligned_and_missed_exploits(hands):
    """Walk all hands and find spots where Hero's action ALIGNED with an
    MDA recommendation (positive case) or DEVIATED in the wrong direction
    (missed exploit).

    Returns: {'aligned': [...], 'missed': [...]} where each entry has
    {hand_id, cards, position, stack_bb, mda_rec_id, ev_bb, hero_action,
     mda_action, alignment}. alignment ∈ {'aligned', 'missed'}.
    """
    aligned = []
    missed = []
    for h in hands:
        combo = h.get('hand_class') or h.get('cards_class') or ''
        if not combo and isinstance(h.get('cards'), list) and len(h['cards']) >= 2:
            # Build hand_class on the fly for hands missing the field
            cards = h['cards']
            try:
                r1, s1 = cards[0][0], cards[0][1]
                r2, s2 = cards[1][0], cards[1][1]
                if r1 == r2:
                    combo = r1 + r2
                else:
                    high, low = (r1, r2) if _RANK_IDX.get(r1, 99) < _RANK_IDX.get(r2, 99) else (r2, r1)
                    suit_tag = 's' if s1 == s2 else 'o'
                    combo = high + low + suit_tag
            except Exception:
                continue
        if not combo:
            continue
        for rec in MDA_RECOMMENDATIONS:
            if not _matches_trigger(rec, h):
                continue
            if combo not in rec['combos']:
                continue
            hero_action = _classify_hero_action(h)
            rec_action = rec.get('action')
            base_entry = {
                'hand_id': h.get('id'),
                'cards': combo,
                'position': h.get('position'),
                'stack_bb': h.get('stack_bb'),
                'mda_rec_id': rec['id'],
                'ev_bb': rec.get('ev_bb'),
                # v7.40 B33: carry ev_bb_range when present so renderer can
                # surface uncertainty instead of treating peak as point estimate.
                'ev_bb_range': rec.get('ev_bb_range'),
                # v7.41 v9: carry counter_rec flag so renderer can display
                # alignment with TIGHTEN-style recs as "avoided cost" instead
                # of the negative EV (which is the cost of NOT tightening).
                'counter_rec': bool(rec.get('counter_rec')),
                'pending_field': (rec.get('trigger', {}) or {}).get('pending_field'),
                'hero_action': hero_action,
                'mda_action': rec_action,
            }
            if hero_action == rec_action:
                aligned.append({**base_entry, 'alignment': 'aligned'})
            else:
                missed.append({**base_entry, 'alignment': 'missed'})
    return {'aligned': aligned, 'missed': missed}


def _classify_hero_action(h):
    """Map Hero's preflop action to one of the MDA action labels.

    v7.40 B33 (refined): when the spot ends in a preflop all-in, classify
    Hero's role based on whether they were the aggressor or the caller —
    not based on Hero's *first* labeled action. At 12-25BB stacks, a Hero
    3-bet that commits the stack is functionally equivalent to a rejam
    (MDA-4 framing lumps these together because the EV outcome is the
    same: commit premium pair vs villain's range). Without that, the
    classifier treats Hero's 3-bet-jam as 'missed' even when Hero did
    exactly what MDA-4 recommends.
    """
    summary = h.get('action_summary', '') or ''
    pf_allin = 'ALL-IN' in summary
    if pf_allin:
        if h.get('pfr'):
            # Hero was the aggressor pre — 3-bet jam, 4-bet jam, or rejam
            # over a jam. Treat as 'rejam' for MDA-4 alignment purposes.
            return 'rejam'
        if h.get('vpip'):
            return 'call'  # Hero called a jam
        return 'fold'
    # Legacy path for non-allin hands
    if h.get('hero_jam') or h.get('villain_jammed'):
        if h.get('hero_jam'):
            if h.get('faced_3bet') or h.get('faced_open'):
                return 'rejam'
            return 'jam'
        if h.get('vpip'):
            return 'call'
        return 'fold'
    if h.get('hero_3bet'):
        return '3bet'
    if h.get('pfr'):
        return 'raise'
    if h.get('vpip'):
        return 'call'
    return 'fold'


# =============================================================================
# v9 FREQUENCY TESTS (Recs 20, 21, 24, 25)
# =============================================================================
# These recs aren't per-hand alignments — they test Hero's session-aggregate
# rates against MDA-recommended frequencies. This is the architectural unlock
# Ron flagged: per-hand alignment over default-correct plays generates noise;
# session-frequency tests against population baselines generate signal.
#
# Each test produces one of: ALIGNED (Hero in target band), FLAG (Hero off
# target — actionable), THIN (sample too small for verdict).
# =============================================================================

# Each entry describes a frequency test:
#   id          — MDA rec id
#   description — short label for the report
#   read_fn     — callable(stats) → (rate_pct, n) or None if not applicable
#   target_lo   — lower target band
#   target_hi   — upper target band
#   pop_avg     — what the population does (for context column)
#   ev_hint     — text describing the EV/event
#   n_min       — minimum sample for a verdict (else THIN)
FREQUENCY_RECS = [
    {
        'id': 'MDA-20',
        'description': 'Multi-way c-bet rate — population over-bets MW',
        'metric': 'mw_cbet_pct',
        'target_lo': 25, 'target_hi': 35,
        'pop_avg': '46-60%',
        'ev_hint': '+1.0-2.0 BB/spot (population over-bets MW; tighten to value + high-equity draws)',
        'n_min': 8,
        'direction': 'TIGHTEN',
    },
    {
        'id': 'MDA-21',
        'description': 'HU c-bet on connected/low boards — population under-bets',
        'metric': 'connected_low_cbet_pct',
        'target_lo': 70, 'target_hi': 85,
        'pop_avg': '55-71%',
        'ev_hint': '+0.5-1.0 BB per missed c-bet; range-bet small (1/3 pot)',
        'n_min': 10,
        'direction': 'WIDEN',
    },
    {
        'id': 'MDA-24',
        'description': 'EP/MP HU c-bet on connected at 40-100BB — pop under-bets',
        'metric': 'epmp_connected_cbet_pct',
        'target_lo': 70, 'target_hi': 80,
        'pop_avg': '46-53%',
        'ev_hint': '+0.5-1.0 BB per missed c-bet; cell-level finding (consistent across stacks)',
        'n_min': 8,
        'direction': 'WIDEN',
    },
    {
        'id': 'MDA-25',
        'description': 'LP HU c-bet on connected — pop under-bets',
        'metric': 'lp_connected_cbet_pct',
        'target_lo': 70, 'target_hi': 80,
        'pop_avg': '54-58%',
        'ev_hint': '+0.5-1.0 BB per missed c-bet; range-bet small (1/3 pot)',
        'n_min': 8,
        'direction': 'WIDEN',
    },
    # B34 v7.46 expansion: 4 additional counter-recs derived from Ron's
    # drill framework + Jasper-5 + Hungry Horse rules. MDA-23/26/27/28
    # remain v9-spec-pending (require Dave-source doc cross-ref).
    {
        'id': 'MDA-15',
        'description': 'Caller IP flop aggression — population under-attacks weak boards',
        'metric': 'caller_ip_flop_agg',
        'target_lo': 30, 'target_hi': 40,
        'pop_avg': '15-22%',
        'ev_hint': '+0.5-1.0 BB per attack opportunity; raise/float on low-connected '
                   'boards when PFR cbet shows weakness',
        'n_min': 15,
        'direction': 'WIDEN',
    },
    {
        'id': 'MDA-18',
        'description': 'River fold-to-bet vs polarized — population over-folds',
        'metric': 'river_fold_to_large_bet',
        'target_lo': 50, 'target_hi': 65,
        'pop_avg': '68-78%',
        'ev_hint': '+0.4-0.8 BB per spot; call wider against pool that over-bluffs '
                   'river polarized vs reg checking range. Hungry Horse H7.',
        'n_min': 10,
        'direction': 'TIGHTEN',  # fold less = call more (tighten the fold-rate)
    },
    {
        'id': 'MDA-19',
        'description': 'SB completion vs BB iso — J29 mandates limp-heavy',
        'metric': 'sb_limp_completion_rate',
        'target_lo': 80, 'target_hi': 95,
        'pop_avg': '40-55%',
        'ev_hint': '+0.6-1.2 BB per SB hand; J29 (Dave) prescribes ~80% limp-completion '
                   'vs BB. Pool over-raises and over-folds; both -EV.',
        'n_min': 20,
        'direction': 'WIDEN',  # widen limp-completion frequency
    },
    {
        'id': 'MDA-22',
        'description': 'Turn probe (OOP) on missed-cbet — pop under-probes',
        'metric': 'turn_probe_oop_after_missed_cbet',
        'target_lo': 45, 'target_hi': 60,
        'pop_avg': '20-30%',
        'ev_hint': '+0.5-0.8 BB per missed-cbet spot; OOP turn probe is +EV vs '
                   'PFR check-back range which is heavily weak/showdown-value.',
        'n_min': 10,
        'direction': 'WIDEN',
    },
    # =========================================================================
    # K-series (Jaka) frequency overlays — v7.66.
    # K2/K3/K6 are Jaka POSTFLOP FREQUENCY rules: there is no discrete
    # pre-result error to anchor a per-hand detector on, so they belong here
    # as session-rate vs target-band tests (the XIII.5.0 architecture).
    # Source tag is Jaka; bands are rule-stated (K3/K6) or GTO-derived (K2).
    # =========================================================================
    {
        'id': 'K2',
        'description': 'Jaka K2 — OOP PFR flop c-bet rate (HU): default is CHECK',
        'metric': 'k2_oop_pfr_cbet_pct',
        'target_lo': 30, 'target_hi': 50,
        'pop_avg': 'GTO ~42% (Dave archetypes, 15-texture mean)',
        'ev_hint': 'Jaka K2 "make them fear your checks": OOP as PFR, the default '
                   'is to check — a c-bet rate above the band means no real OOP '
                   'checking range. Band derived from gto_texture_archetypes.json '
                   'oop_cbet freq (unweighted mean of 15 archetypes ~42%). Coarse '
                   'session-wide alarm; per-texture detail lives in XIII.5.',
        'n_min': 12,
        'direction': 'TIGHTEN',
    },
    {
        'id': 'K3',
        'description': 'Jaka K3 — IP caller stab rate when checked to',
        'metric': 'k3_ip_stab_rate',
        'target_lo': 40, 'target_hi': 60,
        'pop_avg': 'passive pool under-stabs (checks back too much)',
        'ev_hint': 'Jaka K3: as the IP caller, stab 40-60% when the PFR checks to '
                   'you — stable across textures. Under-stabbing leaves the PFRs '
                   'weak check-back range uncontested; band is rule-stated.',
        'n_min': 12,
        'direction': 'WIDEN',
    },
    {
        'id': 'K6',
        'description': 'Jaka K6 — flop lead (donk) frequency: leading is RARE',
        'metric': 'k6_flop_lead_rate',
        'target_lo': 0, 'target_hi': 5,
        'pop_avg': '~2.5% GTO baseline',
        'ev_hint': 'Jaka K6: flop leading is rare (~2.5% baseline) and reserved for '
                   'specific spots. A session-wide lead rate above the band means '
                   'Hero is donking too many flops.',
        'n_min': 15,
        'direction': 'TIGHTEN',
    },
]


def _read_metric(stats, metric):
    """Resolve a frequency-test metric to (rate_pct, n) from session stats.

    Returns (None, 0) when the metric isn't computable (missing fields).
    """
    csv = stats.get('csv_row', {}) or {}
    fa_cbpt = (stats.get('facing_action', {}) or {}).get('cbet_by_pot_type', {}) or {}
    tgf = stats.get('texture_gto_findings', {}) or {}

    if metric == 'mw_cbet_pct':
        # Hero's session MW c-bet rate. Source: csv_row.Flop_CBet_MW for the
        # rate; cbet.mw_opp / cbet.mw_bet for the raw counts. (facing_action's
        # cbet_by_pot_type.MW is computed in a different code path that may
        # not populate when MW samples are thin.)
        rate = csv.get('Flop_CBet_MW')
        cb = stats.get('cbet', {}) or {}
        n = cb.get('mw_opp', 0) or 0
        if rate is None or n == 0:
            return (None, 0)
        return (float(rate), int(n))

    # Connected/low aggregates: sum across the listed archetypes (IP only — OOP is
    # caller, not PFR; MDA-21/24/25 specify Hero-as-PFR).
    archetypes = ('low_connected', 'middling_connected', 'low_ragged', 'middling_disconnected')
    if metric == 'connected_low_cbet_pct':
        n_cbet = n_opps = 0
        for arch in archetypes:
            ip = (tgf.get(arch, {}) or {}).get('ip', {}) or {}
            n_cbet += ip.get('n_cbet', 0) or 0
            n_opps += ip.get('n_opps', 0) or 0
        if n_opps == 0:
            return (None, 0)
        return (100.0 * n_cbet / n_opps, n_opps)

    if metric == 'epmp_connected_cbet_pct':
        # Position-specific not available in current texture_gto_findings (no
        # position dimension). Same aggregate as connected_low for now; flag
        # as B33 backlog when position-split is added.
        return _read_metric(stats, 'connected_low_cbet_pct')

    if metric == 'lp_connected_cbet_pct':
        return _read_metric(stats, 'connected_low_cbet_pct')

    # --- K-series (Jaka) frequency metrics, v7.66 ---
    core = stats.get('core', {}) or {}
    cb = stats.get('cbet', {}) or {}

    if metric == 'k2_oop_pfr_cbet_pct':
        # K2 (Jaka): OOP PFR HU flop c-bet rate. Rate + denominator are both
        # already computed in gem_analyzer (s['cbet']['hu_oop_pct'] / 'hu_oop_opp').
        rate = cb.get('hu_oop_pct')
        n = cb.get('hu_oop_opp', 0) or 0
        if rate is None or n == 0:
            return (None, 0)
        return (float(rate), int(n))

    if metric == 'k3_ip_stab_rate':
        # K3 (Jaka): IP caller stab rate when checked to. core.ip_stab_rate /
        # ip_stab_n are set by the existing k3_* analyzer block.
        rate = core.get('ip_stab_rate')
        n = core.get('ip_stab_n', 0) or 0
        if rate is None or n == 0:
            return (None, 0)
        return (float(rate), int(n))

    if metric == 'k6_flop_lead_rate':
        # K6 (Jaka): flop lead (donk) frequency. core.flop_lead_rate /
        # flop_lead_n are set by the existing k6_* analyzer block. A 0.0 rate
        # is a valid reading (Hero never donked) — only n==0 is THIN.
        rate = core.get('flop_lead_rate')
        n = core.get('flop_lead_n', 0) or 0
        if rate is None or n == 0:
            return (None, 0)
        return (float(rate), int(n))

    return (None, 0)


def find_frequency_signals(stats):
    """Run every frequency test against session stats. Return list of dicts:
       {id, description, hero_pct, n, target_lo, target_hi, pop_avg, ev_hint,
        direction, verdict ∈ {'ALIGNED','FLAG','THIN'}}.

    'ALIGNED' — Hero in target band.
    'FLAG'    — Hero outside target; direction tells WIDEN vs TIGHTEN.
    'THIN'    — n < n_min; insufficient sample for verdict.
    """
    out = []
    for rec in FREQUENCY_RECS:
        rate, n = _read_metric(stats, rec['metric'])
        if rate is None:
            entry = {**rec, 'hero_pct': None, 'n': 0, 'verdict': 'THIN',
                     'note': 'Metric not computable — required field missing'}
        elif n < rec['n_min']:
            entry = {**rec, 'hero_pct': rate, 'n': n, 'verdict': 'THIN',
                     'note': f"n={n} < {rec['n_min']} required for verdict"}
        elif rec['target_lo'] <= rate <= rec['target_hi']:
            entry = {**rec, 'hero_pct': rate, 'n': n, 'verdict': 'ALIGNED',
                     'note': 'In target band'}
        else:
            direction_note = (
                'too tight' if rate < rec['target_lo']
                else 'too loose'
            )
            entry = {**rec, 'hero_pct': rate, 'n': n, 'verdict': 'FLAG',
                     'note': f'{direction_note} — {rec["direction"]} per MDA'}
        out.append(entry)
    return out
