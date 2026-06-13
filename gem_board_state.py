#!/usr/bin/env python3
"""
gem_board_state.py — Board-centric per-street state analysis.

Pure card logic. No equity engine, no MC, no phevaluator dependency.
Provides deterministic board facts (flush status, paired, straights)
that the analyst feed can use instead of reconstructing from raw cards.

Public API:
    board_state(board, hero_cards=None) -> dict
"""

_RANK_ORDER = '23456789TJQKA'
_RANK_VALUE = {r: i for i, r in enumerate(_RANK_ORDER)}
_SUITS = 'shdc'


def _parse_card(card):
    """Parse 'Ah' -> (rank='A', suit='h', value=12)."""
    if not card or len(card) < 2:
        return None
    rank = card[0].upper()
    suit = card[1].lower()
    value = _RANK_VALUE.get(rank)
    if value is None:
        return None
    return {'rank': rank, 'suit': suit, 'value': value}


def _suit_counts(cards):
    """Count suits on parsed cards."""
    counts = {'h': 0, 's': 0, 'd': 0, 'c': 0}
    for c in cards:
        if c and c['suit'] in counts:
            counts[c['suit']] += 1
    return counts


def _flush_status(suit_counts):
    """Derive flush status from suit counts."""
    mx = max(suit_counts.values())
    if mx >= 5:
        return 'monotone'
    if mx == 4:
        return '4-flush'
    if mx == 3:
        return '3-flush'
    if mx == 2:
        return 'two-tone'
    return 'rainbow'


def _flush_completed_this_street(prev_suit_counts, current_suit_counts):
    """Did this street's card bring a 3rd or 4th of any suit?"""
    for s in _SUITS:
        prev = prev_suit_counts.get(s, 0)
        curr = current_suit_counts.get(s, 0)
        if prev == 2 and curr == 3:
            return True
        if prev == 3 and curr == 4:
            return True
    return False


def _pair_info(cards):
    """Compute paired status and pair ranks from board cards."""
    rank_counts = {}
    for c in cards:
        rank_counts[c['rank']] = rank_counts.get(c['rank'], 0) + 1
    pair_ranks = [r for r, n in rank_counts.items() if n >= 2]
    # Sort by rank value descending
    pair_ranks.sort(key=lambda r: _RANK_VALUE.get(r, 0), reverse=True)
    trips_or_quads = any(n >= 3 for n in rank_counts.values())
    return len(pair_ranks) > 0, pair_ranks, trips_or_quads


def _straight_info(cards):
    """Compute straight status and completing ranks."""
    values = sorted(set(c['value'] for c in cards))
    # Add low-ace (value -1 for wheel)
    if 12 in values:  # Ace
        values = [-1] + values

    # Find best consecutive run length
    best_run = 1
    current_run = 1
    for i in range(1, len(values)):
        if values[i] == values[i-1] + 1:
            current_run += 1
            best_run = max(best_run, current_run)
        elif values[i] != values[i-1]:
            current_run = 1

    # Straight completing ranks: find ranks that would make a 5-card straight
    # using >=3 board cards
    completing = set()
    board_values = set(c['value'] for c in cards)
    if 12 in board_values:
        board_values.add(-1)
    for test_val in range(-1, 13):
        test_set = board_values | {test_val}
        test_sorted = sorted(test_set)
        run = 1
        for i in range(1, len(test_sorted)):
            if test_sorted[i] == test_sorted[i-1] + 1:
                run += 1
                if run >= 5:
                    rank = _RANK_ORDER[test_val] if test_val >= 0 else 'A'
                    if test_val not in board_values or (test_val == -1 and 12 not in set(c['value'] for c in cards)):
                        completing.add(rank)
            else:
                run = 1

    status = 'none'
    if best_run >= 5:
        status = 'completed'
    elif best_run >= 4:
        status = 'open_on_board'
    elif best_run >= 3:
        status = 'gutter_on_board'

    return status, sorted(completing, key=lambda r: _RANK_VALUE.get(r, 0), reverse=True)


def _nut_hand_label(paired, flush_status, straight_status, trips_or_quads):
    """Coarse label for the nut hand category on this board."""
    if trips_or_quads:
        return 'quads'
    if paired and flush_status in ('3-flush', '4-flush', 'monotone'):
        return 'boat_or_flush'
    if paired:
        return 'boat'
    if flush_status in ('3-flush', '4-flush', 'monotone'):
        return 'flush'
    if straight_status == 'completed':
        return 'straight'
    if flush_status == 'two-tone':
        return 'set'
    return 'set'


def _hero_plays_board(board_cards, hero_cards):
    """Check if Hero's best 5-card hand equals the board's best 5.

    Returns True if neither hole card improves the board's best 5.
    Conservative: also checks kicker improvement.
    """
    if not hero_cards or len(hero_cards) < 2 or len(board_cards) < 5:
        return False

    board_parsed = [_parse_card(c) for c in board_cards if c]
    hero_parsed = [_parse_card(c) for c in hero_cards if c]
    if len(board_parsed) < 5 or len(hero_parsed) < 2:
        return False
    if not all(board_parsed) or not all(hero_parsed):
        return False

    board_ranks = set(c['rank'] for c in board_parsed)

    # If either hero card pairs a board rank, Hero doesn't play the board
    for hc in hero_parsed:
        if hc['rank'] in board_ranks:
            return False

    # If either hero card makes a flush (3+ of that suit on board), not playing board
    sc = _suit_counts(board_parsed)
    for hc in hero_parsed:
        if sc.get(hc['suit'], 0) >= 3:
            return False

    # Board's best 5 kicker: the lowest value in the board's top 5
    # (considering pairs/trips take priority, but for simplicity check if
    # either hero card beats the board's weakest card)
    board_values = sorted([c['value'] for c in board_parsed], reverse=True)
    hero_values = [c['value'] for c in hero_parsed]

    # If either hero card is higher than the board's lowest card, Hero improves
    # the kicker → does NOT play the board
    board_min = board_values[-1]  # weakest board card
    if any(hv > board_min for hv in hero_values):
        return False

    # Both hero cards are at or below the board's weakest card → plays the board
    return True


def _board_pair_outranks_hero(board_cards, hero_cards):
    """Check if the board's pair rank > Hero's made-pair rank.

    If Hero has no pair from hole cards (no hole card matches a board card),
    and the board is paired, return True (Hero is at/below board pair value).
    """
    if not hero_cards or len(hero_cards) < 2:
        return False

    board_parsed = [_parse_card(c) for c in board_cards if c]
    hero_parsed = [_parse_card(c) for c in hero_cards if c]
    if not all(board_parsed) or not all(hero_parsed):
        return False

    board_rank_counts = {}
    for c in board_parsed:
        board_rank_counts[c['rank']] = board_rank_counts.get(c['rank'], 0) + 1

    # Board pair ranks
    board_pairs = [r for r, n in board_rank_counts.items() if n >= 2]
    if not board_pairs:
        return False

    highest_board_pair = max(_RANK_VALUE.get(r, 0) for r in board_pairs)

    # Hero's pair: does either hole card match a board card?
    board_ranks = set(c['rank'] for c in board_parsed)
    hero_pair_values = [_RANK_VALUE.get(c['rank'], 0) for c in hero_parsed
                        if c['rank'] in board_ranks]

    if not hero_pair_values:
        # Hero has no pair from hole cards — board pair outranks
        return True

    highest_hero_pair = max(hero_pair_values)
    return highest_board_pair > highest_hero_pair


def board_state(board, hero_cards=None):
    """Per-street, BOARD-CENTRIC facts.

    Args:
        board: list of card strings, e.g. ['5h', 'Qs', '8h', 'Qd', '4s']
        hero_cards: optional list of 2 hero hole cards

    Returns:
        dict keyed by street (flop/turn/river) with board state per street.
        Returns {} if board has <3 cards.
    """
    if not isinstance(board, list) or len(board) < 3:
        return {}

    parsed = [_parse_card(c) for c in board]
    if not all(parsed[:3]):
        return {}

    result = {}
    prev_suit_counts = {'h': 0, 's': 0, 'd': 0, 'c': 0}
    prev_nut = None

    streets = [
        ('flop', parsed[:3], board[:3]),
        ('turn', parsed[:4], board[:4]),
        ('river', parsed[:5], board[:5]),
    ]

    for street_name, street_parsed, street_cards_raw in streets:
        if not all(street_parsed):
            break

        sc = _suit_counts(street_parsed)
        fs = _flush_status(sc)
        fc = _flush_completed_this_street(prev_suit_counts, sc) if street_name != 'flop' else False
        one_card_flush = fs in ('3-flush', '4-flush')
        paired, pair_ranks, trips_quads = _pair_info(street_parsed)
        ss, completing = _straight_info(street_parsed)

        # Check if straight completed THIS street
        if street_name != 'flop':
            prev_ss, _ = _straight_info(street_parsed[:-1])
            if ss == 'completed' and prev_ss != 'completed':
                ss = 'completed_this_street'

        nut = _nut_hand_label(paired, fs, ss, trips_quads)
        nut_changed = prev_nut is not None and nut != prev_nut

        entry = {
            'cards': street_cards_raw,
            'suit_counts': sc,
            'flush_status': fs,
            'flush_completed_this_street': fc,
            'one_card_flush_possible': one_card_flush,
            'paired': paired,
            'pair_ranks': pair_ranks,
            'trips_or_quads_on_board': trips_quads,
            'straight_status': ss if ss != 'completed_this_street' else 'completed_this_street',
            'straight_completing_ranks': completing,
            'nut_hand_now': nut,
            'nut_changed_from_prev_street': nut_changed,
        }

        # Hero-aware fields
        if hero_cards and isinstance(hero_cards, list) and len(hero_cards) == 2:
            entry['hero_plays_board'] = _hero_plays_board(street_cards_raw, hero_cards)
            entry['board_pair_outranks_hero_pair'] = _board_pair_outranks_hero(
                street_cards_raw, hero_cards)
        else:
            entry['hero_plays_board'] = None
            entry['board_pair_outranks_hero_pair'] = None

        result[street_name] = entry
        prev_suit_counts = sc
        prev_nut = nut

    return result
