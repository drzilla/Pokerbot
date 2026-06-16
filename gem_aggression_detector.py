#!/usr/bin/env python3
"""
gem_aggression_detector.py — v1.0 (Ron 2026-05-12)

Multi-gate detector for "missed aggression" spots that replaces the v7.46
heuristic "made_value_hand + called = missed_value" rule. That rule fired
false positives on dry-board IP set-vs-donk-lead (where flat is correct)
and OOP combo-draw spots (where ER demands check-call).

ARCHITECTURE — every candidate must pass FIVE gates:

  Gate 1: HAND STRENGTH    — Hero has a hand that COULD be the aggressor
  Gate 2: BOARD TEXTURE    — texture supports betting/raising for value
  Gate 3: ACTION CONTEXT   — villain's prior action makes raise +EV
  Gate 4: DECISION AXIS    — verify ER vs ED framing (combo draws OOP = ER)
  Gate 5: VS-WHAT-CALLS    — name 2-3 villain holdings that pay the raise

The output is a per-hand record with all 5 gates' verdicts and an overall
recommendation. The OLD heuristic produced binary "missed/not" — the NEW
detector produces a chain of reasoning that the analyst step can audit.

When a candidate fails Gate 2, 3, or 4 with strong signal, it's DEMOTED
from "missed aggression" to "correctly passive" (and surfaced in report
as a positive note rather than a leak).

Public API:
    analyze_postflop_aggression(hand) -> {
        'hand_id': str,
        'verdict': 'MISSED_AGGRESSION' | 'CORRECTLY_PASSIVE' | 'AMBIGUOUS',
        'street_of_interest': 'flop'|'turn'|'river',
        'gates': {1..5: {pass: bool, reason: str}},
        'recommended_action': str,
        'decision_axis': 'ER' | 'ED' | 'mixed',
        'villains_that_pay': [str, str, str],
    }

Solver hook (for river decisions): if gem_solver is available, run a
value-bet EV check at the river node to validate the heuristic.
"""

import sys
from collections import namedtuple

RANK_ORDER = '23456789TJQKA'
RANK_IDX = {r: i for i, r in enumerate(RANK_ORDER)}


# ============================================================
# HAND CLASSIFICATION (reused from chat-scope candidate detector)
# ============================================================

def classify_hand(cards, board):
    """Return dict with class, label, strength_score (0-100), draws."""
    if not cards or not board or len(cards) != 4:
        return {'cls': '?', 'label': '', 'score': 0, 'draws': []}
    c1, c2 = cards[:2], cards[2:4]
    hero_ranks = [c1[0], c2[0]]
    hero_suits = [c1[1], c2[1]]
    board_ranks = [b[0] for b in board]
    board_suits = [b[1] for b in board]
    rank_counts = {r: (hero_ranks + board_ranks).count(r)
                   for r in set(hero_ranks + board_ranks)}

    cls, label, score = '?', '', 0
    pp = hero_ranks[0] == hero_ranks[1]
    board_pairs = [r for r in set(board_ranks) if board_ranks.count(r) >= 2]

    # Quads
    for r in rank_counts:
        if rank_counts[r] == 4 and r in hero_ranks:
            return {'cls': 'quads', 'label': f'quad{r}', 'score': 100, 'draws': []}
    # Flushes
    for s in 'cdhs':
        if hero_suits.count(s) + board_suits.count(s) >= 5 and hero_suits.count(s) >= 1:
            cls, label, score = 'flush', f'{s}flush', 90
            break
    # Straights
    ri = sorted(set(RANK_IDX[r] for r in hero_ranks + board_ranks))
    # Wheel check
    if RANK_IDX['A'] in ri:
        for low in [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8]:
            window = [low + i for i in range(5)]
            if low == -1:
                window = [RANK_IDX['A'], 0, 1, 2, 3]
            if all(w in ri for w in window):
                if any(RANK_IDX[r] in window for r in hero_ranks) and score < 85:
                    cls, label, score = 'straight', 'straight', 85
                    break
    else:
        for low in range(0, 9):
            if all(low + i in ri for i in range(5)):
                if any(RANK_IDX[r] in range(low, low + 5) for r in hero_ranks) and score < 85:
                    cls, label, score = 'straight', 'straight', 85
                    break
    # Sets / FH
    for r in hero_ranks:
        if hero_ranks.count(r) == 2 and rank_counts[r] == 3:
            other = [bp for bp in board_pairs if bp != r]
            if other and score < 95:
                cls, label, score = 'full_house', f'FH', 95
            elif score < 85:
                cls, label, score = 'set', f'set{r}', 85
    # Two-pair / TP / pp / etc
    if score < 70:
        paired = list({hr for hr in hero_ranks if hr in board_ranks and rank_counts[hr] == 2})
        # B64 (v7.48, Ron 2026-05-12): detect board-paired-augments-TP case.
        # If Hero has TP and the BOARD itself is paired (rank with count==2
        # made up entirely of board cards), Hero actually plays TWO PAIR
        # (his pair + the board's pair). Common case: Hero J3 on JT89T —
        # plays JJ+TT two pair, not pair of Jacks with a 3 kicker.
        board_only_pair_rank = None
        for r in set(board_ranks):
            if board_ranks.count(r) == 2 and r not in hero_ranks:
                # Found a rank that's paired purely on the board
                board_only_pair_rank = r
                break
        if pp:
            mp = hero_ranks[0]
            overs = sum(1 for r in board_ranks if RANK_IDX[r] > RANK_IDX[mp])
            if overs == 0:
                cls, label, score = 'overpair', f'OP{mp}', 72
            elif overs == 1:
                cls, label, score = 'underpair_1', f'pp1o({mp})', 50
            else:
                cls, label, score = 'underpair_n', f'pp{overs}o({mp})', 25
        elif len(paired) == 2:
            cls, label, score = 'two_pair', f'2P{paired[0]}{paired[1]}', 78
        elif paired and board_only_pair_rank:
            # B64: Hero has TP AND the board itself is paired → 2P
            # (Hero plays his TP + board's pair). Strength is real 2P but
            # the "second pair" comes from the board, so it's slightly
            # weaker than a normal 2P — set score in between (70 vs 78).
            mp = paired[0]
            kicker = ([r for r in hero_ranks if r != mp][0]
                      if hero_ranks[0] != hero_ranks[1] else mp)
            sb = sorted(set(board_ranks), key=lambda r: RANK_IDX[r], reverse=True)
            # The label notes "(board-paired)" to flag that the second pair
            # plays from the board.
            if mp == sb[0]:
                cls, label, score = 'two_pair', f'2P{mp}{board_only_pair_rank}(board-paired)', 70
            else:
                # Hero has a lower pair, board pair higher than Hero's → Hero's
                # 2P plays but is dominated by anyone holding the higher pair.
                cls, label, score = 'two_pair', f'2P{board_only_pair_rank}{mp}(board-dom)', 55
        elif paired:
            sb = sorted(set(board_ranks), key=lambda r: RANK_IDX[r], reverse=True)
            mp = paired[0]
            kicker = ([r for r in hero_ranks if r != mp][0]
                      if hero_ranks[0] != hero_ranks[1] else mp)
            ki = RANK_IDX[kicker]
            if mp == sb[0]:
                if ki >= 10:
                    cls, label, score = 'top_pair', f'TPGK({kicker})', 62
                elif ki >= 7:
                    cls, label, score = 'top_pair', f'TPMK({kicker})', 47
                else:
                    cls, label, score = 'top_pair', f'TPWK({kicker})', 32
            elif len(sb) >= 2 and mp == sb[1]:
                cls, label, score = 'second_pair', f'2nd({mp})', 38
            else:
                cls, label, score = 'low_pair', f'lo({mp})', 18
        else:
            cls, label, score = 'high_card', '', 5

    # Draws
    draws = []
    for s in 'cdhs':
        cnt = hero_suits.count(s) + board_suits.count(s)
        hero_in = hero_suits.count(s)
        if cnt == 4 and hero_in >= 1:
            draws.append('FD')
            break
    if len(board) < 5:
        dist = sorted(set(RANK_IDX[r] for r in hero_ranks + board_ranks))
        for low in range(0, 9):
            window = set(range(low, low + 5))
            if len(window & set(dist)) == 4 and any(RANK_IDX[r] in window for r in hero_ranks):
                # Check if it's OESD (Hero contributes from inside, 2 ways to complete)
                # vs gutshot (only 1 way). Heuristic: if the 4 present cards form
                # a contiguous block, it's OESD; otherwise gutshot.
                present = sorted(window & set(dist))
                if len(present) == 4 and present[-1] - present[0] == 3:
                    draws.append('OESD')
                else:
                    draws.append('SD')
                break

    return {'cls': cls, 'label': label, 'score': score, 'draws': draws}


# ============================================================
# GATE 2: BOARD TEXTURE
# ============================================================

def board_dynamicism(board):
    """Score 0-100 of how dynamic (likely to change ranges on next street) the board is.

    Higher = wetter = more reason to fast-play value (bet/raise).
    Lower = drier = more reason to slow-play or trap.

    Used as Gate 2 input. Returns dict with score + reasons.
    """
    if not board or len(board) < 3:
        return {'score': 50, 'reasons': ['insufficient board']}

    score = 0
    reasons = []
    suits = [c[1] for c in board]
    ranks = [c[0] for c in board]
    rank_set = set(RANK_IDX[r] for r in ranks)

    # Flush draws on board
    suit_counts = {s: suits.count(s) for s in set(suits)}
    max_suit = max(suit_counts.values())
    if max_suit >= 3:
        # Monotone flop / 3-flush board
        if len(board) == 3:
            score += 40
            reasons.append('monotone flop — wet')
        else:
            score += 30
            reasons.append('3-flush on turn/river — wet')
    elif max_suit == 2:
        score += 15
        reasons.append('flush draw available')

    # Straight density
    sorted_ri = sorted(rank_set)
    # Count gaps in the rank window
    if len(sorted_ri) >= 3:
        spread = sorted_ri[-1] - sorted_ri[0]
        if spread <= 4:
            score += 25
            reasons.append('connected — straight draws live')
        elif spread <= 6:
            score += 10
            reasons.append('semi-connected')

    # Paired board
    if len(set(ranks)) < len(ranks):
        score -= 10  # paired boards typically reduce drawiness
        reasons.append('paired (reduces draws)')

    # Number of broadway cards (more = more equity for hero)
    broadway = sum(1 for r in ranks if RANK_IDX[r] >= 9)  # T, J, Q, K, A
    if broadway >= 2:
        score += 10
        reasons.append('broadway-heavy')

    score = max(0, min(100, score))
    return {'score': score, 'reasons': reasons}


# ============================================================
# GATE 3: ACTION CONTEXT
# ============================================================

def villain_action_context(hsa, hero_ip, pfr, street):
    """Classify the action context Hero faced on the given street.

    Returns dict with 'context' (one of: DONK_LEAD, CBET, BARREL, CHECKBACK,
    DELAYED_CBET, X_C_PASSIVE, X_R, etc.) and 'range_shape' (POLARIZED_VALUE,
    POLARIZED_BLUFF, LINEAR, CAPPED).
    """
    flop_a = hsa.get('flop', '')
    turn_a = hsa.get('turn', '')
    river_a = hsa.get('river', '')

    if street == 'flop':
        # Hero's flop action characterizes what villain did before/after
        if hero_ip and flop_a == 'call':
            # Villain bet first into IP Hero. Donk-lead if Hero is PFR (villain
            # leading into the raiser); standard cbet if Hero is the caller.
            # BUG-3 fix: c-bet range is polarized/strong, not linear — Hero
            # cannot "miss aggression" by calling a villain c-bet.
            if pfr:
                return {'context': 'DONK_LEAD', 'range_shape': 'POLARIZED_VALUE'}
            else:
                return {'context': 'CBET_INTO_HERO', 'range_shape': 'POLARIZED_VALUE'}
        if (not hero_ip) and flop_a == 'xc':
            # Hero OOP check-called. Villain bet → cbet (most common) or
            # donk-lead-if-villain-also-OOP (rare 3-way+).
            # BUG-3 fix: same logic — villain c-bet range is polarized.
            if pfr:
                return {'context': 'VILLAIN_BET_VS_PFR_OOP', 'range_shape': 'POLARIZED_VALUE'}
            else:
                return {'context': 'CBET_INTO_HERO_OOP', 'range_shape': 'POLARIZED_VALUE'}
        if flop_a == 'x' and hero_ip:
            # Hero IP and checked — must mean villain also checked (otherwise hsa would be xc/xf)
            return {'context': 'BOTH_CHECKED', 'range_shape': 'CAPPED'}
        if flop_a == 'x' and not hero_ip:
            # Hero OOP and just "x" → villain checked back
            return {'context': 'VILLAIN_CHECKED_BACK', 'range_shape': 'CAPPED'}
        if flop_a in ('cbet', 'bet'):
            # Hero bet — villain's response captured in turn action
            if 'call' in turn_a or 'xc' in turn_a or turn_a in ('x',):
                return {'context': 'CBET_CALLED', 'range_shape': 'LINEAR'}
            return {'context': 'HERO_AGGRESSIVE', 'range_shape': 'N/A'}

    elif street == 'turn':
        if hero_ip and turn_a == 'call':
            # Hero IP called turn bet. Was villain barreling or donk-leading?
            if 'bet' in flop_a or 'cbet' in flop_a:
                # Hero c-bet flop, villain called, villain donk-led turn = POLARIZED
                return {'context': 'DONK_LEAD_TURN', 'range_shape': 'POLARIZED_VALUE'}
            elif 'call' in flop_a:
                # Hero called villain's flop bet, villain barreled turn = LINEAR-VALUE
                return {'context': 'TURN_BARREL', 'range_shape': 'LINEAR_VALUE_HEAVY'}
            else:
                # Hero checked flop (or x'd through), faced turn bet
                return {'context': 'TURN_LEAD', 'range_shape': 'POLARIZED_VALUE'}
        if (not hero_ip) and turn_a == 'xc':
            # Hero OOP check-called turn — villain barreled
            return {'context': 'TURN_BARREL_OOP', 'range_shape': 'LINEAR_VALUE_HEAVY'}
        if turn_a == 'x' and (flop_a in ('cbet', 'bet')):
            # Hero cbet flop, x'd turn → villain x'd back or hero gave up
            return {'context': 'CBET_FLOP_X_TURN', 'range_shape': 'CAPPED'}
        if turn_a == 'x' and hero_ip:
            return {'context': 'BOTH_CHECKED_TURN', 'range_shape': 'CAPPED'}
        if turn_a == 'x' and not hero_ip:
            return {'context': 'VILLAIN_CHECKED_BACK_TURN', 'range_shape': 'CAPPED'}
        if turn_a in ('bet',):
            return {'context': 'HERO_AGGRESSIVE_TURN', 'range_shape': 'N/A'}

    elif street == 'river':
        if hero_ip and river_a in ('call', 'xc', 'callAI'):
            # Triple barrel into Hero or villain lead river
            return {'context': 'RIVER_BET_INTO_HERO', 'range_shape': 'POLARIZED_VALUE_HEAVY'}
        if (not hero_ip) and river_a == 'xc':
            return {'context': 'RIVER_BARREL_OOP', 'range_shape': 'POLARIZED_VALUE_HEAVY'}
        if river_a == 'x' and turn_a == 'x':
            return {'context': 'GOT_TO_SD_PASSIVE', 'range_shape': 'CAPPED'}
        if river_a == 'x' and hero_ip:
            return {'context': 'VILLAIN_CHECKED_RIVER', 'range_shape': 'CAPPED'}
        if river_a == 'x' and not hero_ip:
            return {'context': 'VILLAIN_CHECKED_BACK_RIVER', 'range_shape': 'CAPPED'}

    return {'context': 'UNKNOWN', 'range_shape': 'UNKNOWN'}


# ============================================================
# GATE 4: DECISION AXIS (ER vs ED vs MIXED)
# ============================================================

def decision_axis(hand_class, draws, hero_ip, board_score):
    """Classify the decision axis for Hero's hand type.

    ER (Equity Realization) — favored by checking/calling to see more streets cheaply
    ED (Equity Denial) — favored by betting/raising to fold out live equity
    MIXED — context-dependent
    """
    # Combo draws OOP → ER (preserve optionality, free river card)
    if not hero_ip and ('FD' in draws or 'OESD' in draws):
        if hand_class in ('high_card', 'low_pair', 'second_pair', 'top_pair'):
            return {'axis': 'ER',
                    'reason': 'OOP with draw equity — leading collapses tree, gives up free realization'}

    # Strong made hands on wet boards IP → ED (charge draws)
    if hero_ip and hand_class in ('set', 'two_pair', 'overpair') and board_score >= 50:
        return {'axis': 'ED',
                'reason': 'Strong made hand on wet board IP — charge draws + protect equity'}

    # Strong made hands on DRY boards → MIXED (slow-play has merit)
    if hand_class in ('set', 'two_pair', 'overpair') and board_score < 30:
        return {'axis': 'MIXED',
                'reason': 'Strong hand on dry board — slow-play and fast-play both have merit'}

    # Bluffcatchers OOP facing barrels → ER (don't raise unless population over-bluffs)
    if not hero_ip and hand_class in ('top_pair', 'overpair') and board_score >= 50:
        return {'axis': 'ER',
                'reason': 'Bluffcatcher OOP on wet board — call to realize SDV, raise only vs over-bluffers'}

    # Top pair good kicker IP with capped villain → ED (thin value)
    if hero_ip and hand_class in ('top_pair', 'overpair'):
        return {'axis': 'ED',
                'reason': 'TP+/overpair IP — bet thin value vs capped/wide ranges'}

    return {'axis': 'MIXED', 'reason': 'No clear axis pressure'}


# ============================================================
# GATE 5: VS-WHAT-CALLS
# ============================================================

def villains_that_pay(hand_class, hand_label, board, street_context):
    """Return a list of villain holdings that would pay a value raise here.

    Heuristic: based on board structure + hand class, name 2-3 specific
    hand classes from villain's continuing range. If the answer is mostly
    "hands that chop or beat us", the raise isn't a value raise.
    """
    payers = []
    if hand_class in ('set', 'full_house', 'quads'):
        # Sets/FH crush most of villain's value-betting range
        payers = ['overpairs (JJ+)', 'two pair', 'top pair good kicker', 'flush draws']
    elif hand_class == 'two_pair':
        payers = ['top pair', 'overpairs', 'flush/straight draws']
    elif hand_class == 'straight':
        payers = ['two pair', 'sets', 'top pair', 'flush draws']
    elif hand_class == 'flush':
        payers = ['two pair', 'sets', 'lower flushes', 'straights']
    elif hand_class == 'overpair':
        payers = ['top pair good kicker', 'second pair', 'flush/straight draws']
    elif hand_class == 'top_pair':
        if 'GK' in hand_label:
            payers = ['second pair', 'third pair', 'random draws', 'weaker TP kickers']
        elif 'MK' in hand_label:
            payers = ['second pair', 'weak kickers', 'random draws']
        else:
            payers = ['second pair', 'busted draws', 'random pair-low-kicker']
    elif hand_class in ('second_pair', 'underpair_1'):
        payers = ['high cards with backdoors', 'gutshots', 'random unpaired']
    else:
        payers = ['(thin — mostly bluff-folds folds)']

    # Refine by board: on draw-heavy boards, value targets shrink for marginal hands
    flush_present = max((board.count(s) for s in 'cdhs' if s in str(board)), default=0)
    return payers[:3]


# ============================================================
# GATE 1 + ORCHESTRATION
# ============================================================

def analyze_postflop_aggression(hand):
    """Main entry — runs all 5 gates on a single hand record.

    Returns None when the hand isn't a passive postflop spot (no analysis needed).
    Returns the candidate dict with full gate audit otherwise.
    """
    if not isinstance(hand, dict): return None
    if hand.get('hero') != 'Hero': return None
    board = hand.get('board') or []
    if len(board) < 3: return None
    cards = ''.join(hand.get('cards', []))
    if len(cards) != 4: return None

    # Skip preflop all-ins — Hero made no postflop decisions
    if hand.get('pf_allin', False) or hand.get('hero_pf_allin', False):
        return None

    # B162 (Ron 2026-05-24): skip hands Hero folded preflop. A preflop fold
    # still leaves Hero's hole cards AND a board (the other players' flop) in
    # the record, and the parser may leave a stray hero_street_actions entry
    # — without this guard the detector scores Hero's folded hole cards
    # against a flop he never saw (TM5991383585: folded QJo UTG, was being
    # flagged as a missed flop c-bet with a fabricated "TPGK on Jd Ts 6s").
    if hand.get('pf_action') == 'fold' or hand.get('line') == 'fold_preflop':
        return None

    hsa = hand.get('hero_street_actions') or {}
    fa = hsa.get('flop', '')
    ta = hsa.get('turn', '')
    ra = hsa.get('river', '')
    if 'fold' in str(fa) or 'fold' in str(ta) or 'fold' in str(ra) or fa == 'xf':
        # Still consider earlier streets where Hero acted before folding
        # but only flag if the missed action was on a street BEFORE the fold
        pass  # don't skip outright — let street selection handle it

    # Skip if Hero never acted postflop at all (e.g., faced all-in preflop, called, ran out)
    if not (fa or ta or ra):
        return None

    hero_ip = hand.get('hero_ip', False)
    pfr = hand.get('pfr', False) or hand.get('hero_pfr', False)
    n_flop = hand.get('n_players_flop', 0) or 2

    # Classify hand at each street
    flop_cls = classify_hand(cards, board[:3])
    turn_cls = classify_hand(cards, board[:4]) if len(board) >= 4 else None
    river_cls = classify_hand(cards, board[:5]) if len(board) >= 5 else None

    # Evaluate EACH passive-action street separately. The leak may be on a
    # later street (e.g., TPGK flop with villain-bet [polarized = no raise]
    # but TPGK turn with villain-checked [capped = lead for value]).
    street_evaluations = []
    for street, cls, act in [
        ('flop', flop_cls, fa),
        ('turn', turn_cls, ta),
        ('river', river_cls, ra),
    ]:
        if not cls or not act: continue
        # v8.16.1 Bug-2a: a call of an ALL-IN bet (callAI) is NOT a
        # missed-aggression spot. Facing an all-in there is no more-aggressive
        # line available — you cannot bet into, or raise, an all-in — so the
        # "should Hero have been more aggressive?" question does not apply.
        # Scoring it produced a category-wrong "correct check — a bet wasn't
        # justified" verdict on a pure call/fold decision (78024888: Hero called
        # a river jam holding the nut flush; there was no bet/check or raise
        # decision to grade). Only x (checked) and xc/call (called a NON-all-in
        # bet, where a RAISE was still available) are missed-aggression-eligible.
        is_passive = act in ('x', 'xc', 'call')
        if not is_passive: continue
        strong_made = cls['score'] >= 60
        strong_combo = 'OESD' in cls['draws'] and 'FD' in cls['draws']
        if not (strong_made or strong_combo): continue
        # Build full gate evaluation for this street
        street_board_full = (board[:3] if street == 'flop'
                             else board[:4] if street == 'turn'
                             else board[:5])
        btx = board_dynamicism(street_board_full)
        actx = villain_action_context(hsa, hero_ip, pfr, street)
        axis = decision_axis(cls['cls'], cls['draws'], hero_ip, btx['score'])
        payers = villains_that_pay(cls['cls'], cls['label'], street_board_full, actx)

        local_gates = {}
        local_gates[1] = {
            'pass': True,  # already filtered
            'reason': f"Hero has {cls['label'] or cls['cls']} (score {cls['score']}, draws={cls['draws']}) — passes threshold",
        }
        # Gate 2
        if cls['cls'] in ('set', 'two_pair') and btx['score'] < 30:
            local_gates[2] = {'pass': False,
                              'reason': f"Board too dry (score {btx['score']}) — slow-play has merit over fast-play"}
        elif cls['cls'] in ('top_pair', 'overpair') and btx['score'] >= 50:
            local_gates[2] = {'pass': True,
                              'reason': f"Wet board (score {btx['score']}) — protect/value: {'; '.join(btx['reasons'])}"}
        else:
            local_gates[2] = {'pass': True,
                              'reason': f"Board score {btx['score']} — neutral: {'; '.join(btx['reasons']) or '—'}"}
        # Gate 3
        if actx['range_shape'] in ('POLARIZED_VALUE', 'POLARIZED_VALUE_HEAVY'):
            local_gates[3] = {'pass': False,
                              'reason': f"Villain showed value via {actx['context']} — raise vs polarized value bloats vs hands that beat us"}
        elif actx['range_shape'] in ('CAPPED', 'LINEAR', 'LINEAR_VALUE_HEAVY'):
            local_gates[3] = {'pass': True,
                              'reason': f"Villain range {actx['range_shape']} via {actx['context']} — raising/leading extracts from worse hands"}
        else:
            local_gates[3] = {'pass': False,
                              'reason': f"Context {actx['context']} unclear — not flagging"}
        # Gate 4
        if axis['axis'] == 'ER':
            local_gates[4] = {'pass': False,
                              'reason': f"AXIS=ER: {axis['reason']} — passive line maximizes EV"}
        elif axis['axis'] == 'ED':
            local_gates[4] = {'pass': True,
                              'reason': f"AXIS=ED: {axis['reason']}"}
        else:
            local_gates[4] = {'pass': True,
                              'reason': f"AXIS=MIXED: {axis['reason']}"}
        # Gate 5
        weak_payers = sum(1 for p in payers if any(w in p.lower()
                          for w in ['second pair', 'third', 'random', 'draws',
                                    'weaker', 'busted', 'thin', 'gutshot', 'high cards']))
        local_gates[5] = {
            'pass': weak_payers >= 1,
            'reason': f"Villain holdings that pay a raise: {', '.join(payers)}",
        }

        pass_count = sum(1 for g in local_gates.values() if g['pass'])
        street_evaluations.append({
            'street': street, 'cls': cls, 'act': act,
            'gates': local_gates, 'pass_count': pass_count,
            'btx': btx, 'actx': actx, 'axis': axis, 'payers': payers,
        })

    if not street_evaluations:
        return None

    # Choose the EARLIEST street where ALL 5 gates pass (true missed-aggression
    # leak — earlier is the inflection point). If no street passes all 5, fall
    # back to the street with the most gates passing (highest signal).
    street_evaluations.sort(key=lambda s: (-s['pass_count'],
                                            ['flop', 'turn', 'river'].index(s['street'])))
    best = street_evaluations[0]
    street = best['street']
    cls = best['cls']
    act = best['act']
    gates = best['gates']
    btx = best['btx']
    actx = best['actx']
    axis = best['axis']
    payers = best['payers']
    pass_count = best['pass_count']

    street_board = (board[:3] if street == 'flop'
                    else board[:4] if street == 'turn'
                    else board[:5])

    # Gates already computed per-street above; just compute overall verdict
    # Overall verdict
    if pass_count == 5:
        verdict = 'MISSED_AGGRESSION'
        recommended = f"Bet/raise {street} for value with {cls['label']}"
    elif pass_count == 4:
        verdict = 'AMBIGUOUS'
        recommended = f"Likely missed aggression on {street} but one gate failed — see notes"
    else:
        verdict = 'CORRECTLY_PASSIVE'
        # Find the failing gate(s) to explain why
        failed_gates = [f"Gate{gn}" for gn, g in gates.items() if not g['pass']]
        recommended = f"Passive line correct on {street} — gates failed: {', '.join(failed_gates)}"

    return {
        'hand_id': hand.get('id'),
        'cards': cards,
        'position': hand.get('position'),
        'eff_bb': round(hand.get('eff_stack_bb', hand.get('stack_bb', 0)), 1),
        'board': ' '.join(street_board),
        'tournament': hand.get('tournament', '')[:40],
        'date': hand.get('date', ''),
        'net_bb': hand.get('net_bb', 0),
        'won': hand.get('won', False),
        'went_sd': hand.get('went_to_sd', False),
        'verdict': verdict,
        'street_of_interest': street,
        'hand_class': cls['label'],
        'hand_score': cls['score'],
        'board_score': btx['score'],
        'action_context': actx['context'],
        'range_shape': actx['range_shape'],
        'decision_axis': axis['axis'],
        'axis_reason': axis['reason'],
        'villains_that_pay': payers,
        'gates': gates,
        'recommended_action': recommended,
        'hsa': {'flop': fa, 'turn': ta, 'river': ra},
        'action_summary': hand.get('action_summary', ''),
        # B61 (v7.47, Ron 2026-05-12): solver-validation status.
        #   IN_SCOPE = river HU spot, eligible for gem_solver value-bet check
        #   OUT_OF_SCOPE = flop/turn spot, heuristic gates are the only validation
        #   HEURISTIC_ONLY = river spot but not HU or other constraint fails
        # Actual solver invocation happens in a separate pass; this field
        # tags which candidates need that confirmation step.
        'solver_status': _solver_status(hand, street),
    }


def analyze_postflop_over_aggression(hand):
    """F4 (v7.49, Ron 2026-05-13): mirror of analyze_postflop_aggression for
    OVER-aggression. Same 5-gate evaluation, but applied to spots where Hero
    bet/raised — if the gates would tell Hero NOT to be aggressive (gate
    failures dominate), the action is flagged as TOO_AGGRESSIVE.

    Returns None when the hand isn't an aggressive-postflop spot. Returns
    candidate dict with full gate audit otherwise.

    Verdict logic (symmetric to passive case):
      - 5/5 gates pass + Hero aggressive  → CORRECTLY_AGGRESSIVE (positive note)
      - 4/5 gates pass + Hero aggressive  → AMBIGUOUS_AGGRESSIVE
      - 3/5 or fewer pass + Hero aggressive → TOO_AGGRESSIVE
    """
    if not isinstance(hand, dict): return None
    if hand.get('hero') != 'Hero': return None
    board = hand.get('board') or []
    if len(board) < 3: return None
    cards = ''.join(hand.get('cards', []))
    if len(cards) != 4: return None

    # Skip preflop all-ins — no postflop decisions to evaluate
    if hand.get('pf_allin', False) or hand.get('hero_pf_allin', False):
        return None

    # B162 (Ron 2026-05-24): skip hands Hero folded preflop — see the
    # matching guard in analyze_postflop_aggression. A preflop fold leaves
    # hole cards + a board in the record but no real postflop action.
    if hand.get('pf_action') == 'fold' or hand.get('line') == 'fold_preflop':
        return None

    hsa = hand.get('hero_street_actions') or {}
    fa = hsa.get('flop', '')
    ta = hsa.get('turn', '')
    ra = hsa.get('river', '')

    if not (fa or ta or ra):
        return None

    hero_ip = hand.get('hero_ip', False)
    pfr = hand.get('pfr', False) or hand.get('hero_pfr', False)

    flop_cls = classify_hand(cards, board[:3])
    turn_cls = classify_hand(cards, board[:4]) if len(board) >= 4 else None
    river_cls = classify_hand(cards, board[:5]) if len(board) >= 5 else None

    # Aggressive action codes: bet, cbet, raise, jam, xr, xr-ai, bAI, rAI
    AGGRESSIVE_ACTS = {'bet', 'cbet', 'raise', 'jam', 'xr', 'xr-ai',
                       'b', 'r', 'bAI', 'rAI'}
    # B253 (split-verdict): bet-then-call composites. The BET portion is
    # aggressive; the call-of-raise is a separate passive decision. When we
    # see these, we evaluate the bet node for over-aggression as normal but
    # skip flagging the call — that's a different mistake class (light-call).
    _SPLIT_ACTS = {'bet-call', 'bet-fold', 'bet-callAI'}

    street_evaluations = []
    for street, cls, act in [
        ('flop', flop_cls, fa),
        ('turn', turn_cls, ta),
        ('river', river_cls, ra),
    ]:
        if not cls or not act:
            continue
        # B253: for split-verdict streets, treat only the BET portion as
        # aggressive. The call/fold of the raise is NOT over-aggression.
        is_split = act in _SPLIT_ACTS
        is_aggressive = act in AGGRESSIVE_ACTS or is_split or (
            isinstance(act, str) and any(a in act for a in ('bet', 'jam', 'raise', 'xr'))
        )
        if not is_aggressive:
            continue
        # Same evaluability filter as passive detector: require some hand strength
        # OR draw — without it, the gates aren't meaningful. We're explicitly
        # looking for "Hero had a hand worth evaluating and bet anyway despite
        # bad context" — naked-air bluffs are a different leak class.
        strong_made = cls['score'] >= 60
        strong_combo = 'OESD' in cls['draws'] and 'FD' in cls['draws']
        medium_made = cls['score'] >= 40  # second pair, weak top pair
        has_any_equity = strong_made or strong_combo or medium_made or len(cls['draws']) > 0
        if not has_any_equity:
            # Naked-air aggressive plays are bluffs — handled by other detectors
            continue

        # B200 (Ron review 2026-05-25): a near-nut made hand can NEVER be
        # "too aggressive" — betting/raising flush-or-better for value is
        # always correct, and the gate machinery (villain-range / worse-hands-
        # pay) is irrelevant when Hero holds a monster. Without this skip the
        # detector flagged the nut flush (93012530) and aces-full (97011964)
        # value jams as TOO_AGGRESSIVE — a severe false positive. Skip the
        # over-aggression evaluation for these strength classes entirely.
        _MONSTER_CLS = {'straight', 'flush', 'full_house', 'quads',
                        'straight_flush', 'full house', 'straight flush'}
        if (cls.get('cls') or '').lower() in _MONSTER_CLS:
            continue

        street_board_full = (board[:3] if street == 'flop'
                             else board[:4] if street == 'turn'
                             else board[:5])
        btx = board_dynamicism(street_board_full)
        actx = villain_action_context(hsa, hero_ip, pfr, street)
        axis = decision_axis(cls['cls'], cls['draws'], hero_ip, btx['score'])
        payers = villains_that_pay(cls['cls'], cls['label'], street_board_full, actx)

        local_gates = {}
        # Gate 1 — evaluability (relaxed for over-aggression: any equity counts)
        local_gates[1] = {
            'pass': has_any_equity,
            'reason': f"Hero has {cls['label'] or cls['cls']} (score {cls['score']}, draws={cls['draws']})",
        }
        # Gate 2 — board texture for aggression
        if cls['cls'] in ('set', 'two_pair') and btx['score'] < 30:
            local_gates[2] = {'pass': False,
                              'reason': f"Board too dry (score {btx['score']}) — fast-play not needed"}
        elif cls['cls'] in ('top_pair', 'overpair') and btx['score'] >= 50:
            local_gates[2] = {'pass': True,
                              'reason': f"Wet board (score {btx['score']}) — aggression for protection"}
        else:
            local_gates[2] = {'pass': True,
                              'reason': f"Board score {btx['score']} — neutral"}
        # Gate 3 — villain's action shape: POLARIZED_VALUE means Hero's aggression
        # walks into villain's value range
        if actx['range_shape'] in ('POLARIZED_VALUE', 'POLARIZED_VALUE_HEAVY'):
            local_gates[3] = {'pass': False,
                              'reason': f"Villain showed value via {actx['context']} — aggression bloats vs hands that beat us"}
        elif actx['range_shape'] in ('CAPPED', 'LINEAR', 'LINEAR_VALUE_HEAVY'):
            local_gates[3] = {'pass': True,
                              'reason': f"Villain range {actx['range_shape']} — aggression extracts value"}
        else:
            local_gates[3] = {'pass': False,
                              'reason': f"Context {actx['context']} unclear — aggression risky"}
        # Gate 4 — decision axis: ER means Hero should NOT bet (equity retention)
        if axis['axis'] == 'ER':
            local_gates[4] = {'pass': False,
                              'reason': f"AXIS=ER: {axis['reason']} — aggression burns equity"}
        elif axis['axis'] == 'ED':
            local_gates[4] = {'pass': True,
                              'reason': f"AXIS=ED: {axis['reason']}"}
        else:
            local_gates[4] = {'pass': True,
                              'reason': f"AXIS=MIXED: {axis['reason']}"}
        # Gate 5 — worse hands pay
        weak_payers = sum(1 for p in payers if any(w in p.lower()
                          for w in ['second pair', 'third', 'random', 'draws',
                                    'weaker', 'busted', 'thin', 'gutshot', 'high cards']))
        local_gates[5] = {
            'pass': weak_payers >= 1,
            'reason': f"Villain holdings that pay aggression: {', '.join(payers) if payers else '—'}",
        }

        pass_count = sum(1 for g in local_gates.values() if g['pass'])
        street_evaluations.append({
            'street': street, 'cls': cls, 'act': act,
            'gates': local_gates, 'pass_count': pass_count,
            'btx': btx, 'actx': actx, 'axis': axis, 'payers': payers,
        })

    if not street_evaluations:
        return None

    # F4 verdict logic: choose the EARLIEST aggressive-action street with the
    # LOWEST gate-pass-count (the worst case — that's where the leak lives).
    # Tie-breaker: earliest street.
    street_evaluations.sort(key=lambda s: (s['pass_count'],
                                            ['flop', 'turn', 'river'].index(s['street'])))
    best = street_evaluations[0]
    pass_count = best['pass_count']
    if pass_count <= 3:
        verdict = 'TOO_AGGRESSIVE'
    elif pass_count == 4:
        verdict = 'AMBIGUOUS_AGGRESSIVE'
    else:
        verdict = 'CORRECTLY_AGGRESSIVE'

    street = best['street']
    cls = best['cls']
    act = best['act']
    gates = best['gates']
    btx = best['btx']
    actx = best['actx']
    axis = best['axis']
    payers = best['payers']

    street_board = (board[:3] if street == 'flop'
                    else board[:4] if street == 'turn'
                    else board[:5])

    failed_gates = [f"Gate{gn}" for gn, g in gates.items() if not g['pass']]
    if verdict == 'TOO_AGGRESSIVE':
        recommended = (f"Aggression on {street} fails {len(failed_gates)}/5 gates "
                       f"({', '.join(failed_gates)}) — consider x/c or smaller bet")
    elif verdict == 'AMBIGUOUS_AGGRESSIVE':
        recommended = (f"Aggression on {street} marginal — one gate failed "
                       f"({', '.join(failed_gates)})")
    else:
        recommended = f"Aggressive line correct on {street} — all gates pass"

    # B253 (split-verdict): include per-node committed amounts and flag
    # that the street has a bet-then-call-raise split. The magnitude
    # attribution for any mistake should use ONLY the offending node's
    # committed amount, not the whole hand's hero_committed_bb.
    _street_nodes = (hand.get('hero_street_nodes') or {}).get(street)
    _split_info = {}
    if _street_nodes and act in _SPLIT_ACTS:
        _split_info = {
            'is_split_verdict': True,
            'bet_node_bb': _street_nodes.get('bet_bb', 0),
            'call_node_bb': _street_nodes.get('call_raise_bb', 0),
            'note': ('Bet and call-of-raise are separate decisions. '
                     'Bet may be justified (range-advantage stab); '
                     'call-of-raise is the potential leak.'),
        }

    return {
        'hand_id': hand.get('id'),
        'cards': cards,
        'position': hand.get('position'),
        'eff_bb': round(hand.get('eff_stack_bb', hand.get('stack_bb', 0)), 1),
        'board': ' '.join(street_board),
        'tournament': hand.get('tournament', '')[:40],
        'date': hand.get('date', ''),
        'net_bb': hand.get('net_bb', 0),
        'won': hand.get('won', False),
        'went_sd': hand.get('went_to_sd', False),
        'verdict': verdict,
        'street_of_interest': street,
        'hand_class': cls['label'],
        'hand_score': cls['score'],
        'board_score': btx['score'],
        'action_context': actx['context'],
        'range_shape': actx['range_shape'],
        'decision_axis': axis['axis'],
        'axis_reason': axis['reason'],
        'villains_that_pay': payers,
        'gates': gates,
        'recommended_action': recommended,
        'hsa': {'flop': fa, 'turn': ta, 'river': ra},
        'action_summary': hand.get('action_summary', ''),
        'pass_count': pass_count,
        **_split_info,
    }


def _solver_status(hand, street):
    """Tag whether this candidate is in scope for solver-level confirmation."""
    if street != 'river':
        return 'OUT_OF_SCOPE'
    # Try to call existing solver integration
    try:
        from gem_solver_integration import is_solver_eligible
        eligible, reason, mode = is_solver_eligible(hand)
        if eligible:
            return f'IN_SCOPE ({mode})'
        return f'HEURISTIC_ONLY ({reason})'
    except Exception:
        return 'HEURISTIC_ONLY (solver_unavailable)'


def analyze_session(hands):
    """Run analyze_postflop_aggression across all session hands.

    Returns:
        missed_aggression: [candidate, ...]
        correctly_passive: [candidate, ...]   (positive notes for report)
        ambiguous: [candidate, ...]
        too_aggressive: [candidate, ...]      (F4 v7.49: over-aggression candidates)
        ambiguous_aggressive: [candidate, ...]
        correctly_aggressive: [candidate, ...] (positive notes for report)
    """
    missed, correct, ambig = [], [], []
    too_agg, ambig_agg, correct_agg = [], [], []
    for h in hands:
        result = analyze_postflop_aggression(h)
        if result is not None:
            if result['verdict'] == 'MISSED_AGGRESSION':
                missed.append(result)
            elif result['verdict'] == 'CORRECTLY_PASSIVE':
                correct.append(result)
            else:
                ambig.append(result)
        # F4 (v7.49): also evaluate aggressive plays for over-aggression
        oa_result = analyze_postflop_over_aggression(h)
        if oa_result is not None:
            if oa_result['verdict'] == 'TOO_AGGRESSIVE':
                too_agg.append(oa_result)
            elif oa_result['verdict'] == 'AMBIGUOUS_AGGRESSIVE':
                ambig_agg.append(oa_result)
            elif oa_result['verdict'] == 'CORRECTLY_AGGRESSIVE':
                correct_agg.append(oa_result)
    # Sort each list by net_bb magnitude (most impactful first)
    missed.sort(key=lambda c: -abs(c.get('net_bb', 0)))
    too_agg.sort(key=lambda c: -abs(c.get('net_bb', 0)))
    return {
        'missed_aggression': missed,
        'correctly_passive': correct,
        'ambiguous': ambig,
        'too_aggressive': too_agg,
        'ambiguous_aggressive': ambig_agg,
        'correctly_aggressive': correct_agg,
    }


# ============================================================
# SOLVER VALIDATION HOOK (Gate 5 augmentation for river spots)
# ============================================================

def solver_validate(candidate, raw_hh_lookup=None):
    """For RIVER missed-aggression candidates, attempt to run gem_solver
    in value_bet mode to confirm/deny the verdict.

    Returns dict with solver_verdict ('CONFIRM' | 'DENY' | 'INCONCLUSIVE')
    and EV-delta info. Falls back gracefully if solver unavailable.

    SCOPE: river HU spots only (gem_solver's scope).
    """
    if candidate.get('street_of_interest') != 'river':
        return {'solver_verdict': 'OUT_OF_SCOPE',
                'note': 'Solver hook supports river HU only'}

    try:
        from gem_solver_integration import is_solvable_hand
    except Exception:
        return {'solver_verdict': 'UNAVAILABLE',
                'note': 'gem_solver_integration import failed'}

    # For now, we just flag that the hand is in scope for solver review
    # The full integration with raw HH + range construction is a follow-up.
    return {'solver_verdict': 'QUEUED',
            'note': 'River HU candidate — eligible for gem_solver value_bet check'}


if __name__ == '__main__':
    # Standalone test mode
    import json
    if len(sys.argv) < 2:
        print("Usage: python3 gem_aggression_detector.py <gem_hands.json>")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        hands = json.load(f)
    result = analyze_session(hands)
    print(f"MISSED_AGGRESSION: {len(result['missed_aggression'])}")
    print(f"CORRECTLY_PASSIVE: {len(result['correctly_passive'])}")
    print(f"AMBIGUOUS:         {len(result['ambiguous'])}")
    print("\n=== Top 10 missed-aggression candidates ===")
    for c in result['missed_aggression'][:10]:
        print(f"\n{c['hand_id'][-8:]} {c['cards']} {c['position']} {c['eff_bb']}BB | {c['street_of_interest']} | net{c['net_bb']:+.1f}")
        print(f"  Verdict: {c['verdict']}")
        print(f"  Hand: {c['hand_class']} (score {c['hand_score']}) on {c['board']}")
        print(f"  Board score: {c['board_score']} | Context: {c['action_context']} ({c['range_shape']})")
        print(f"  Axis: {c['decision_axis']} — {c['axis_reason']}")
        print(f"  Recommended: {c['recommended_action']}")
        for gn in (1,2,3,4,5):
            g = c['gates'][gn]
            print(f"    Gate {gn} [{'PASS' if g['pass'] else 'FAIL'}]: {g['reason']}")
