#!/usr/bin/env python3
"""
GEM Made Hands Analysis — opportunity-denominated rates for each made-hand class.

For each of the 5 classes (set/trips, flush, straight, two_pair, full_house),
computes:
  - made_n: hands that reached this class at showdown (or earlier if known)
  - opp_n:  hands where Hero's starting cards COULD reach the class AND saw flop
  - rate:   made_n / opp_n
  - expected: rough population baseline rate
  - ci:     Wilson 90% CI on the observed rate
  - verdict: {🟢, 🟡, 🔴, ⚪} after sample-size gate

Opportunity definitions (denominator):
  set:        pocket pairs that saw flop
  flush:      2-suited hands that saw flop AND turn/river produced 2+ same-suit
              cards on board (i.e., a flush draw was live at some point)
  straight:   connectors / 1-gap / 2-gap hands that saw flop
  two_pair:   any non-pp hand that saw flop (FUZZIER — both cards must be live)
  full_house: any hand that saw flop (FUZZIEST — pp can fill via paired board,
              non-pp can fill if board pairs Hero's pair)

Expected rates (rough):
  set:        ~12% (flop set ~11.8% from pp; +turn/river runners ≈ ~12%)
  flush:      ~35% (given live FD on turn → 9 outs to river ≈ 35% completion)
  straight:   ~17% (rough — varies wildly by gap structure)
  two_pair:   ~20% (any 2pair by river from non-pp non-suited-double)
  full_house: ~3%  (rare; sets fill ~30%, two-pair fills ~9%)

All expected rates are MARKED ~ since pool baselines aren't precisely calibrated.
"""

from collections import Counter as _Counter

CARD_RANK_VALUES = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
    'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14
}

# Tunable expected rates (rough; calibration improves as data accumulates)
EXPECTED_RATES = {
    'set':        12.0,
    'flush':      35.0,
    'straight':   17.0,
    'two_pair':   20.0,
    'full_house':  3.0,
}

# Acceptable target bands (±5pp around expected for now; calibrate later)
TARGET_BANDS = {
    'set':        (8.0, 16.0),
    'flush':      (25.0, 45.0),
    'straight':   (10.0, 25.0),
    'two_pair':   (15.0, 28.0),
    'full_house': (1.0, 8.0),
}


def _wilson_ci(x, n, z=1.645):
    """Wilson score CI for proportion. Returns (lo_pct, hi_pct)."""
    if n <= 0:
        return (0.0, 100.0)
    phat = x / n
    denom = 1 + z*z / n
    center = (phat + z*z / (2*n)) / denom
    margin = z * ((phat * (1 - phat) / n + z*z / (4*n*n)) ** 0.5) / denom
    return (max(0.0, (center - margin) * 100),
            min(100.0, (center + margin) * 100))


def _is_pocket_pair(cards):
    """cards = ['Ah','Ad'] etc."""
    return len(cards) == 2 and cards[0][0] == cards[1][0]


def _is_suited(cards):
    return len(cards) == 2 and cards[0][1] == cards[1][1]


def _gap(cards):
    """Return the rank gap between two cards (None if pp)."""
    if _is_pocket_pair(cards):
        return None
    r1 = CARD_RANK_VALUES.get(cards[0][0], 0)
    r2 = CARD_RANK_VALUES.get(cards[1][0], 0)
    return abs(r1 - r2)


def _saw_flop(h):
    """Heuristic: hero saw the flop if there's a board card and Hero VPIP'd."""
    board = h.get('board', [])
    if isinstance(board, list) and len(board) >= 3 and h.get('vpip'):
        return True
    # Fallback to action_summary or pf_settled
    if h.get('players_at_flop', 0) >= 2 and h.get('vpip'):
        return True
    return False


def _had_live_flush_draw(h):
    """Hero held 2 suited AND board had ≥2 cards of that suit by turn."""
    cards = h.get('cards', [])
    board = h.get('board', [])
    if not _is_suited(cards):
        return False
    suit = cards[0][1]
    if not isinstance(board, list) or len(board) < 3:
        return False
    # Count Hero's suit on board (turn = first 4 cards)
    board_to_turn = board[:4] if len(board) >= 4 else board[:3]
    suit_count = sum(1 for c in board_to_turn if len(c) >= 2 and c[1] == suit)
    return suit_count >= 2  # 2 board + 2 hero = 4 → 1 more = flush


def _had_straight_potential(h):
    """Hero held connectors/1-gap/2-gap (gap ≤ 4) and saw flop."""
    cards = h.get('cards', [])
    if _is_pocket_pair(cards):
        return False
    gap = _gap(cards)
    return gap is not None and gap <= 4


def compute(hands):
    """Compute made-hands rates.

    Returns dict keyed by class name with:
      {made: int, opp: int, rate: float, expected: float,
       target: (lo, hi), ci: (lo, hi), verdict: emoji,
       n_label: str (sample-size descriptor),
       texture_dist: dict[archetype_id -> count] (B65 v7.48 — board archetypes
                     where Hero MADE the class; surfaces whether sets/2P/flushes
                     came on dry vs wet boards, which affects EV interpretation)}
    """
    # B65 (v7.48, Ron 2026-05-12): import texture classifier for board archetype
    # distribution per made-hand class. Allows surfacing things like:
    # "Hero made 4 two-pair this session, 3 of them on paired boards (board-paired
    # 2P plays as bluffcatcher, not value)."
    try:
        from gem_textures import classify_archetype as _classify_archetype
    except Exception:
        _classify_archetype = lambda board: 'unknown'

    def _texture_dist(made_hands):
        """Tally flop archetypes across the list of hands that made this class."""
        from collections import Counter
        dist = Counter()
        for h in made_hands:
            board = h.get('board') or []
            if isinstance(board, list) and len(board) >= 3:
                arch = _classify_archetype(board[:3]) or 'unknown'
                dist[arch] += 1
        return dict(dist)

    out = {}

    # === SET / TRIPS ===
    # Opp denom: pocket pairs that saw flop
    pp_saw_flop = [h for h in hands if _is_pocket_pair(h.get('cards', [])) and _saw_flop(h)]
    pp_made_set = [h for h in pp_saw_flop if h.get('hand_strength') in ('trips', 'full_house', 'quads')]
    opp = len(pp_saw_flop)
    made = len(pp_made_set)
    rate = (100.0 * made / opp) if opp else 0.0
    ci = _wilson_ci(made, opp)
    out['set'] = {
        'made': made, 'opp': opp, 'rate': rate,
        'expected': EXPECTED_RATES['set'],
        'target': TARGET_BANDS['set'],
        'ci': ci,
        'opp_label': 'pp that saw flop',
        'verdict': _verdict(rate, opp, TARGET_BANDS['set']),
        'texture_dist': _texture_dist(pp_made_set),
    }

    # === FLUSH ===
    # Opp denom: 2-suited hands with live flush draw on flop/turn
    suited_with_fd = [h for h in hands if _had_live_flush_draw(h)]
    flush_made = [h for h in suited_with_fd if h.get('hand_strength') == 'flush'
                  or h.get('hand_strength') == 'straight_flush'
                  or (h.get('hand_strength') == 'full_house' and False)]  # boat over flush rare and shouldn't count
    opp = len(suited_with_fd)
    made = len(flush_made)
    rate = (100.0 * made / opp) if opp else 0.0
    ci = _wilson_ci(made, opp)
    out['flush'] = {
        'made': made, 'opp': opp, 'rate': rate,
        'expected': EXPECTED_RATES['flush'],
        'target': TARGET_BANDS['flush'],
        'ci': ci,
        'opp_label': 'suited + live FD on flop/turn',
        'verdict': _verdict(rate, opp, TARGET_BANDS['flush']),
        'texture_dist': _texture_dist(flush_made),
    }

    # === STRAIGHT ===
    # Opp denom: gap ≤ 4 (connectors/1-gap/2-gap/3-gap) that saw flop
    straight_potential = [h for h in hands
                          if _had_straight_potential(h) and _saw_flop(h)]
    straight_made = [h for h in straight_potential
                     if h.get('hand_strength') in ('straight', 'straight_flush')]
    opp = len(straight_potential)
    made = len(straight_made)
    rate = (100.0 * made / opp) if opp else 0.0
    ci = _wilson_ci(made, opp)
    out['straight'] = {
        'made': made, 'opp': opp, 'rate': rate,
        'expected': EXPECTED_RATES['straight'],
        'target': TARGET_BANDS['straight'],
        'ci': ci,
        'opp_label': 'gap≤4 hands that saw flop (~)',
        'verdict': _verdict(rate, opp, TARGET_BANDS['straight']),
        'texture_dist': _texture_dist(straight_made),
    }

    # === TWO PAIR === (FUZZIER)
    # Opp denom: any non-pp hand that saw flop
    non_pp_saw_flop = [h for h in hands
                       if not _is_pocket_pair(h.get('cards', [])) and _saw_flop(h)]
    two_pair_made = [h for h in non_pp_saw_flop
                     if h.get('hand_strength') == 'two_pair']
    opp = len(non_pp_saw_flop)
    made = len(two_pair_made)
    rate = (100.0 * made / opp) if opp else 0.0
    ci = _wilson_ci(made, opp)
    out['two_pair'] = {
        'made': made, 'opp': opp, 'rate': rate,
        'expected': EXPECTED_RATES['two_pair'],
        'target': TARGET_BANDS['two_pair'],
        'ci': ci,
        'opp_label': 'non-pp that saw flop (~ fuzzy)',
        'verdict': _verdict(rate, opp, TARGET_BANDS['two_pair']),
        'texture_dist': _texture_dist(two_pair_made),
    }

    # === FULL HOUSE === (FUZZIEST)
    # Opp denom: any hand that saw flop. Most hands don't have a path to boat.
    saw_flop_all = [h for h in hands if _saw_flop(h)]
    boat_made = [h for h in saw_flop_all
                 if h.get('hand_strength') in ('full_house', 'quads')]
    opp = len(saw_flop_all)
    made = len(boat_made)
    rate = (100.0 * made / opp) if opp else 0.0
    ci = _wilson_ci(made, opp)
    out['full_house'] = {
        'made': made, 'opp': opp, 'rate': rate,
        'expected': EXPECTED_RATES['full_house'],
        'target': TARGET_BANDS['full_house'],
        'ci': ci,
        'opp_label': 'all that saw flop (~ very fuzzy)',
        'verdict': _verdict(rate, opp, TARGET_BANDS['full_house']),
        'texture_dist': _texture_dist(boat_made),
    }

    return out


# ====================================================================
# BUG-3 (v7.99.38): STRUCTURED DRAW PROFILE
# ====================================================================
# For every Hero postflop decision, emit a code-derived classification
# of made-hand strength + draw equity so the analyst never has to
# eyeball draw type from the board. Eliminates misclassifications like
# "bare gutshot ~4 outs" when the hand actually has OESD + overcard.

_RANK_NAMES = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',
               10:'T',11:'J',12:'Q',13:'K',14:'A'}

try:
    from phevaluator import evaluate_cards as _evaluate_cards
    _PHEV_OK = True
except Exception:
    _PHEV_OK = False


def _rank_val(card):
    """Card like 'Ah' → rank int (2-14)."""
    return CARD_RANK_VALUES.get(card[0], 0)


def _classify_made_hand(hero_cards, board):
    """Classify the made-hand strength from hero's 2 cards + board (3-5 cards).

    Returns (class_name, detail_str).
    class_name: one of 'straight_flush','quads','full_house','flush','straight',
                'set','two_pair','overpair','top_pair','second_pair',
                'middle_pair','bottom_pair','underpair','high_card'
    detail_str: human-readable description.
    """
    if not _PHEV_OK or len(hero_cards) != 2 or len(board) < 3:
        return 'unknown', 'phevaluator unavailable or insufficient board'

    all_cards = list(hero_cards) + list(board)
    try:
        rank = _evaluate_cards(*all_cards)
    except Exception:
        return 'unknown', 'evaluation failed'

    hero_ranks = sorted([_rank_val(c) for c in hero_cards], reverse=True)
    board_ranks = sorted([_rank_val(c) for c in board], reverse=True)
    hr0, hr1 = hero_ranks  # high, low

    # phevaluator rank thresholds (lower = better)
    if rank < 11:
        return 'straight_flush', 'straight flush'
    if rank < 167:
        return 'quads', 'four of a kind'
    if rank < 322:
        return 'full_house', 'full house'
    if rank < 1600:
        return 'flush', 'flush'
    if rank < 1610:
        return 'straight', 'straight'
    if rank < 2468:
        # trips / set
        if hero_cards[0][0] == hero_cards[1][0]:
            return 'set', f'set of {_RANK_NAMES.get(hr0, "?")}s'
        return 'trips', f'trips (board-paired)'
    if rank < 3326:
        # Pocket pair + board pair scores as two-pair in phevaluator, but
        # functionally it's a one-pair hand (overpair/underpair bluff-catcher).
        # Only non-pocket-pair hands where both Hero cards pair the board
        # are genuine two pair.
        is_pp = hero_cards[0][0] == hero_cards[1][0]
        if is_pp:
            bc = _Counter(board_ranks)
            paired_board = {r for r, n in bc.items() if n >= 2}
            non_paired = [r for r in board_ranks if r not in paired_board]
            ref = max(non_paired) if non_paired else min(paired_board)
            if hr0 > ref:
                return 'overpair', f'overpair ({_RANK_NAMES[hr0]}{_RANK_NAMES[hr0]}, board-paired)'
            return 'underpair', f'underpair ({_RANK_NAMES[hr0]}{_RANK_NAMES[hr0]}, board-paired)'
        return 'two_pair', 'two pair'
    if rank < 6186:
        # One pair — classify which pair and kicker
        is_pp = hero_cards[0][0] == hero_cards[1][0]
        if is_pp:
            if hr0 > board_ranks[0]:
                return 'overpair', f'overpair ({_RANK_NAMES[hr0]}{_RANK_NAMES[hr0]})'
            return 'underpair', f'underpair ({_RANK_NAMES[hr0]}{_RANK_NAMES[hr0]})'
        # One hero card pairs the board
        for r in hero_ranks:
            if r in board_ranks:
                kicker = hr0 if r == hr1 else hr1
                kicker_str = _RANK_NAMES.get(kicker, '?')
                if r == board_ranks[0]:
                    return 'top_pair', f'top pair ({_RANK_NAMES[r]}), {kicker_str} kicker'
                if len(board_ranks) >= 2 and r == board_ranks[1]:
                    return 'second_pair', f'second pair ({_RANK_NAMES[r]}), {kicker_str} kicker'
                if len(board_ranks) >= 3 and r == board_ranks[2]:
                    return 'bottom_pair', f'bottom pair ({_RANK_NAMES[r]}), {kicker_str} kicker'
                return 'middle_pair', f'middle pair ({_RANK_NAMES[r]}), {kicker_str} kicker'
        return 'weak_pair', 'pair (board-paired)'
    return 'high_card', f'{_RANK_NAMES.get(hr0, "?")}-high'


def _find_straight_outs(hero_cards, board):
    """Find ranks that complete a straight for hero.

    Returns (draw_type, out_count, completing_ranks).
    draw_type: 'OESD' | 'gutshot' | 'double_gutshot' | None
    """
    hero_ranks = [_rank_val(c) for c in hero_cards]
    board_ranks = [_rank_val(c) for c in board]
    all_ranks = set(hero_ranks + board_ranks)
    # Ace can be low (1) for wheel
    if 14 in all_ranks:
        all_ranks.add(1)

    completing = set()
    # Check every possible 5-card straight (A-5 through T-A)
    for bottom in range(1, 11):  # 1=A-low, 10=T-A
        straight = set(range(bottom, bottom + 5))
        held = straight & all_ranks
        if len(held) >= 4:
            # Need exactly 1 card to complete
            missing = straight - all_ranks
            if len(missing) == 1:
                needed = missing.pop()
                # Hero must contribute to this straight (at least 1 hero rank in it)
                hero_in = set(hero_ranks) & straight
                if 14 in set(hero_ranks) and 1 in straight:
                    hero_in.add(1)
                if hero_in:
                    # Map rank 1 back to 14 (Ace) for display
                    completing.add(14 if needed == 1 else needed)

    if not completing:
        return None, 0, []

    n_outs = len(completing) * 4  # 4 suits per rank
    # Remove cards already on board or in hero's hand
    known_cards = set(hero_cards) | set(board)
    for c_rank in list(completing):
        for suit in 'cdhs':
            card = _RANK_NAMES.get(c_rank, str(c_rank)) + suit
            if card in known_cards:
                n_outs -= 1

    ranks_list = sorted(completing, reverse=True)
    rank_strs = [_RANK_NAMES.get(r, str(r)) for r in ranks_list]

    if len(completing) >= 3:
        return 'OESD', n_outs, rank_strs  # 3+ completing ranks = open-ended or wrap
    if len(completing) == 2:
        # 2 completing ranks: OESD (both ends open) or double gutshot
        # OESD: the 4 held ranks are consecutive with open ends
        # Double gutshot: 2 separate inside draws
        held_sorted = sorted(all_ranks - {1} if 14 in all_ranks else all_ranks)
        # Check if there are 4 consecutive among held ranks
        for i in range(len(held_sorted) - 3):
            if held_sorted[i+3] - held_sorted[i] == 3:
                # 4 consecutive — check if both ends are the completing ranks
                low_end = held_sorted[i] - 1
                high_end = held_sorted[i+3] + 1
                if (low_end in completing or (low_end == 1 and 14 in completing)) and \
                   (high_end in completing or (high_end == 14 and 14 in completing)):
                    return 'OESD', n_outs, rank_strs
        return 'double_gutshot', n_outs, rank_strs
    # 1 completing rank = gutshot
    return 'gutshot', n_outs, rank_strs


def _find_flush_draw(hero_cards, board):
    """Detect flush draw or backdoor flush draw.

    Returns (draw_type, out_count, suit).
    draw_type: 'flush_draw' | 'backdoor_fd' | None
    """
    hero_suits = [c[1] for c in hero_cards]
    board_suits = [c[1] for c in board]

    for suit in 'cdhs':
        hero_count = hero_suits.count(suit)
        board_count = board_suits.count(suit)
        total = hero_count + board_count

        if hero_count == 0:
            continue  # Hero must contribute to the draw

        if total >= 5:
            # Already made a flush — not a draw
            continue

        if total == 4:
            # Flush draw: 13 - 4 = 9 remaining of this suit, minus known cards
            remaining = 13 - total
            return 'flush_draw', remaining, suit

        if total == 3 and hero_count >= 1 and len(board) <= 3:
            # Backdoor flush draw (only relevant on flop — need 2 runner cards)
            return 'backdoor_fd', 0, suit

    return None, 0, None


def _find_backdoor_straight(hero_cards, board):
    """Detect backdoor straight draw (only on the flop).

    BDSD = hero + board have 3 cards within a 5-rank span, needing 2 runner
    cards to complete. Only relevant on the flop (3-card board).

    Returns True if a backdoor straight draw exists, False otherwise.
    """
    if len(board) != 3:
        return False  # only relevant on the flop
    hero_ranks = [_rank_val(c) for c in hero_cards]
    board_ranks = [_rank_val(c) for c in board]
    all_ranks = set(hero_ranks + board_ranks)
    if 14 in all_ranks:
        all_ranks.add(1)  # wheel

    # Check every 5-card straight: do we have exactly 3 of the 5 ranks,
    # with at least 1 from hero?
    for bottom in range(1, 11):
        straight = set(range(bottom, bottom + 5))
        held = straight & all_ranks
        hero_in = set(hero_ranks) & straight
        if 14 in set(hero_ranks) and 1 in straight:
            hero_in.add(1)
        if len(held) == 3 and hero_in:
            return True
    return False


def _count_overcards(hero_cards, board):
    """Count hero cards ranking above the highest board card.

    Returns (count, overcard_rank_names).
    """
    if not board:
        return 0, []
    top_board = max(_rank_val(c) for c in board)
    overs = [c for c in hero_cards if _rank_val(c) > top_board]
    return len(overs), [_RANK_NAMES.get(_rank_val(c), '?') for c in overs]


def draw_profile(hero_cards, board):
    """Build a structured draw profile for Hero's hand at the current board.

    Args:
        hero_cards: ['Ah', '6d'] — Hero's 2 hole cards
        board: ['7d', '3h', 'Kh'] — 3 (flop), 4 (turn), or 5 (river) cards

    Returns a dict:
        {
            'made_hand': str,            # class name
            'made_hand_detail': str,     # human description
            'straight_draw': str|None,   # 'OESD' | 'gutshot' | 'double_gutshot'
            'straight_outs': int,        # number of straight-completing cards
            'straight_cards': list,      # which ranks complete
            'flush_draw': str|None,      # 'flush_draw' | 'backdoor_fd'
            'flush_outs': int,           # typically 9 for FD
            'flush_suit': str|None,      # suit of the draw
            'overcards': int,            # count above top board card
            'overcard_ranks': list,      # which ranks
            'clean_outs': int,           # estimated unique clean outs
            'summary': str,              # one-line human-readable
        }
    """
    hero_cards = list(hero_cards or [])
    board = list(board or [])
    if len(hero_cards) != 2 or len(board) < 3:
        return {
            'made_hand': 'unknown', 'made_hand_detail': 'insufficient data',
            'straight_draw': None, 'straight_outs': 0, 'straight_cards': [],
            'flush_draw': None, 'flush_outs': 0, 'flush_suit': None,
            'overcards': 0, 'overcard_ranks': [],
            'clean_outs': 0, 'summary': 'insufficient data',
        }

    made_class, made_detail = _classify_made_hand(hero_cards, board)
    # On the river (5 cards), draws are moot — hand is complete
    _is_river = len(board) >= 5
    if _is_river:
        sd_type, sd_outs, sd_cards = None, 0, []
        fd_type, fd_outs, fd_suit = None, 0, None
        has_bdsd = False
    else:
        sd_type, sd_outs, sd_cards = _find_straight_outs(hero_cards, board)
        fd_type, fd_outs, fd_suit = _find_flush_draw(hero_cards, board)
        # BDSD: only when no real straight draw exists and we're on the flop
        has_bdsd = (not sd_type and _find_backdoor_straight(hero_cards, board))
    oc_count, oc_ranks = _count_overcards(hero_cards, board)

    # If hero already has a made straight or better, suppress straight draw
    strong_made = {'straight', 'flush', 'full_house', 'quads', 'straight_flush'}
    if made_class in strong_made:
        sd_type, sd_outs, sd_cards = None, 0, []
        has_bdsd = False
    # If hero already has a flush, suppress flush draw
    if made_class in ('flush', 'straight_flush'):
        fd_type, fd_outs, fd_suit = None, 0, None

    pair_classes = {'overpair', 'underpair', 'top_pair', 'second_pair', 'middle_pair',
                    'bottom_pair', 'weak_pair', 'set', 'trips', 'two_pair',
                    'full_house', 'quads', 'straight_flush'}

    # Estimate clean outs (unique cards that improve the hand)
    if sd_outs > 0 and fd_outs > 0:
        # Overlap: ~2 cards are both straight-completing AND of the flush suit
        overlap = min(len(sd_cards), 2)
        clean_outs = sd_outs + fd_outs - overlap
    else:
        clean_outs = sd_outs + fd_outs

    # Overcards as outs: each overcard that pairs up gives ~3 outs
    # But only if hero doesn't already have a pair
    if made_class not in pair_classes and oc_count > 0:
        clean_outs += oc_count * 3

    # Build summary string — human-readable, no redundancy
    parts = []
    if made_class != 'high_card' and made_class != 'unknown':
        parts.append(made_detail)
    if sd_type:
        parts.append(f'{sd_type}({sd_outs})')
    elif has_bdsd:
        parts.append('BDSD')
    if fd_type == 'flush_draw':
        parts.append(f'FD({fd_outs})')
    elif fd_type == 'backdoor_fd':
        parts.append('BDFD')
    if oc_count > 0 and made_class not in pair_classes:
        parts.append(f'{oc_count} over{"s" if oc_count > 1 else ""}')
    if not parts:
        parts.append(made_detail if made_detail else 'high card')
    # Only show clean outs when there are MULTIPLE draw components
    # whose combined total differs from any single component.
    # Single-draw hands (just OESD or just FD) already state their outs.
    _n_draw_components = sum([
        bool(sd_type), bool(fd_type == 'flush_draw'),
        (oc_count > 0 and made_class not in pair_classes),
    ])
    if clean_outs > 0 and _n_draw_components >= 2:
        parts.append(f'~{clean_outs} outs')

    return {
        'made_hand': made_class,
        'made_hand_detail': made_detail,
        'straight_draw': sd_type,
        'straight_outs': sd_outs,
        'straight_cards': sd_cards,
        'flush_draw': fd_type,
        'flush_outs': fd_outs,
        'flush_suit': fd_suit,
        'overcards': oc_count,
        'overcard_ranks': oc_ranks,
        'clean_outs': clean_outs,
        'summary': ' + '.join(parts),
    }


def _verdict(rate, opp, target):
    """Return verdict emoji with sample-size gate."""
    if opp < 10:
        return '⚪'
    lo, hi = target
    if lo <= rate <= hi:
        return '🟢'
    # Borderline: within 1 std-dev of target band
    spread = hi - lo
    if rate < lo - spread or rate > hi + spread:
        return '🔴'
    return '🟡'
