#!/usr/bin/env python3
"""Tests for pocket-pair-on-paired-board two_pair misclassification fix.

Reference: HANDOVER_pocket_pair_two_pair_misclass.md, Section 5.
"""
import pytest
from gem_made_hands import _classify_made_hand


class TestPocketPairOnPairedBoard:
    """Pocket pair + board pair should be overpair/underpair, not two_pair."""

    def test_overpair_aces_on_queen_paired_board(self):
        """TM6043159167 repro: AhAd on 6c 7d Qh Qd 9d → overpair, not two_pair."""
        cls, detail = _classify_made_hand(['Ah', 'Ad'], ['6c', '7d', 'Qh', 'Qd', '9d'])
        assert cls == 'overpair', f"Expected overpair, got {cls}: {detail}"
        assert 'board-paired' in detail

    def test_overpair_kings_on_seven_paired_board(self):
        """KhKd on 7c 7d 2s 4h 9c → overpair."""
        cls, detail = _classify_made_hand(['Kh', 'Kd'], ['7c', '7d', '2s', '4h', '9c'])
        assert cls == 'overpair', f"Expected overpair, got {cls}: {detail}"
        assert 'board-paired' in detail

    def test_underpair_eights_on_king_paired_board(self):
        """8h8d on Kc Ks 4d 2h 9c → underpair (88 < KK)."""
        cls, detail = _classify_made_hand(['8h', '8d'], ['Kc', 'Ks', '4d', '2h', '9c'])
        assert cls == 'underpair', f"Expected underpair, got {cls}: {detail}"
        assert 'board-paired' in detail

    def test_overpair_eights_on_four_paired_board(self):
        """8h8d on 4c 4s 7d 2h 3c → overpair (88 > 7, the highest non-paired rank)."""
        cls, detail = _classify_made_hand(['8h', '8d'], ['4c', '4s', '7d', '2h', '3c'])
        assert cls == 'overpair', f"Expected overpair, got {cls}: {detail}"
        assert 'board-paired' in detail

    def test_underpair_eights_on_four_paired_board_with_nine(self):
        """8h8d on 4c 4s 9d 2h 3c → underpair (88 < 9, the highest non-paired rank)."""
        cls, detail = _classify_made_hand(['8h', '8d'], ['4c', '4s', '9d', '2h', '3c'])
        assert cls == 'underpair', f"Expected underpair, got {cls}: {detail}"
        assert 'board-paired' in detail


class TestGenuineTwoPairUnchanged:
    """Non-pocket-pair hands where both Hero cards pair the board = real two pair."""

    def test_genuine_two_pair_ak_on_ak_board(self):
        """AhKd on As Ks 4d 2h 9c → two_pair (both Hero cards pair the board)."""
        cls, detail = _classify_made_hand(['Ah', 'Kd'], ['As', 'Ks', '4d', '2h', '9c'])
        assert cls == 'two_pair', f"Expected two_pair, got {cls}: {detail}"


class TestInvariant:
    """Regression guard: pocket pair + two_pair label should never co-occur."""

    def test_pocket_pair_never_labels_two_pair(self):
        """Sweep pocket pairs on various paired boards — none should return two_pair."""
        cases = [
            (['Ah', 'Ad'], ['6c', '7d', 'Qh', 'Qd', '9d']),
            (['Kh', 'Kd'], ['7c', '7d', '2s', '4h', '9c']),
            (['8h', '8d'], ['Kc', 'Ks', '4d', '2h', '9c']),
            (['8h', '8d'], ['4c', '4s', '7d', '2h', '3c']),
            (['8h', '8d'], ['4c', '4s', '9d', '2h', '3c']),
            (['Th', 'Td'], ['3c', '3s', '5d', '7h', '2c']),
            (['5h', '5d'], ['Ac', 'As', 'Kd', 'Qh', 'Jc']),
            (['2h', '2d'], ['9c', '9s', '8d', '7h', '6c']),
        ]
        for hero, board in cases:
            cls, detail = _classify_made_hand(hero, board)
            assert cls != 'two_pair', (
                f"Pocket pair {hero} on paired board {board} returned '{cls}': {detail}. "
                f"Pocket pairs should never be labelled two_pair."
            )
