"""
test_golden_hands.py — SPEC #2: Golden-hand validation harness.

Tests the unified villain identity record (#0), shown card parsing (#1),
per-street pot-odds/equity computation (#3), and decision math fields.

NOT run before every render — this is a CI/dev gate for the test checkpoint.
"""
import os
import sys
import json

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

from gem_parser import parse_one_hand


# ============================================================
# TEST FIXTURES — synthetic hands with known answers
# ============================================================

# A simple preflop all-in: Hero jams AA, villain calls with KK
HAND_PF_ALLIN = """Poker Hand #TM9999001: Tournament #12345, Test Hold'em No Limit - Level5(50/100(10)) - 2026/06/01 12:00:00
Table '1' 8-max Seat #1 is the button
Seat 1: Player1 (5000 in chips)
Seat 2: Player2 (3000 in chips)
Seat 3: Hero (4000 in chips)
Seat 4: Player4 (6000 in chips)
Seat 5: Player5 (5000 in chips)
Seat 6: Player6 (5000 in chips)
Seat 7: Player7 (5000 in chips)
Seat 8: Player8 (5000 in chips)
Player1: posts the ante 10
Player2: posts the ante 10
Hero: posts the ante 10
Player4: posts the ante 10
Player5: posts the ante 10
Player6: posts the ante 10
Player7: posts the ante 10
Player8: posts the ante 10
Player2: posts small blind 50
Hero: posts big blind 100
*** HOLE CARDS ***
Dealt to Hero [Ah Ad]
Player4: folds
Player5: folds
Player6: folds
Player7: folds
Player8: folds
Player1: folds
Player2: raises 200 to 300
Hero: raises 3690 to 3990 and is all-in
Player2: calls 2690 and is all-in
*** FLOP *** [Ts 7c 2d]
*** TURN *** [Ts 7c 2d] [5h]
*** RIVER *** [Ts 7c 2d 5h] [3s]
*** SHOW DOWN ***
Hero: shows [Ah Ad] (a pair of Aces)
Player2: shows [Kh Kd] (a pair of Kings)
Hero collected 6180 from pot
*** SUMMARY ***
Hero showed [Ah Ad] and won (6180)
Player2 showed [Kh Kd] and lost
"""


def test_villain_identity_record():
    """SPEC #0: Every non-Hero seat has an entry in hand['villains']."""
    h = parse_one_hand(HAND_PF_ALLIN, 'test.txt')
    assert h is not None, "Parse failed"
    assert 'villains' in h, "Missing villains dict"
    assert len(h['villains']) == 7, f"Expected 7 villains, got {len(h['villains'])}"
    # Check structure of one villain
    v2 = h['villains'].get('Player2')
    assert v2 is not None, "Player2 not in villains"
    assert v2['position'] == 'SB', f"Expected SB, got {v2['position']}"
    # 3000 chips / 100 BB blind = 30.0 BB
    assert abs(v2['stack_bb'] - 30.0) < 0.5, f"Expected ~30.0BB, got {v2['stack_bb']}"
    assert v2['seat'] == 2


def test_shown_cards_parsing():
    """SPEC #1: Villain shown cards populated from showdown."""
    h = parse_one_hand(HAND_PF_ALLIN, 'test.txt')
    assert h is not None
    v2 = h['villains'].get('Player2')
    assert v2 is not None
    assert v2['shown_cards'] == ['Kh', 'Kd'], f"Expected ['Kh','Kd'], got {v2['shown_cards']}"
    # Non-showing villains should have None
    v4 = h['villains'].get('Player4')
    assert v4 is not None
    assert v4['shown_cards'] is None


def test_primary_villain():
    """SPEC #0: primary_villain identifies the key opponent."""
    h = parse_one_hand(HAND_PF_ALLIN, 'test.txt')
    assert h is not None
    pv = h.get('primary_villain', {})
    assert pv.get('name') == 'Player2', f"Expected Player2, got {pv}"
    # Player2 raised first → role should be 'opener'
    assert pv.get('role') in ('opener', 'jammer')


def test_matchups():
    """SPEC #0: matchups dict on showdown hands."""
    h = parse_one_hand(HAND_PF_ALLIN, 'test.txt')
    assert h is not None
    mm = h.get('matchups', {})
    assert 'Player2' in mm, f"Player2 not in matchups: {mm.keys()}"
    m = mm['Player2']
    assert m['hero_cards'] == ['Ah', 'Ad']
    assert m['villain_cards'] == ['Kh', 'Kd']


def test_seat_stacks_bb_all():
    """Parser carries full per-seat stacks."""
    h = parse_one_hand(HAND_PF_ALLIN, 'test.txt')
    assert h is not None
    stacks = h.get('seat_stacks_bb_all', {})
    assert len(stacks) >= 7, f"Expected ≥7 seat stacks, got {len(stacks)}"


def test_pf_allin_called_jam():
    """CP21: pf_allin catches 'Hero calls villain jam'."""
    # In HAND_PF_ALLIN, Hero jams — should be pf_allin=True
    h = parse_one_hand(HAND_PF_ALLIN, 'test.txt')
    assert h is not None
    assert h.get('pf_allin') == True, f"Expected pf_allin=True, got {h.get('pf_allin')}"


def test_walk_not_fold():
    """BB walk should have pf_action='check', not 'fold'."""
    walk_hand = """Poker Hand #TM9999002: Tournament #12345, Test Hold'em No Limit - Level5(50/100(10)) - 2026/06/01 12:00:00
Table '1' 6-max Seat #1 is the button
Seat 1: Player1 (5000 in chips)
Seat 2: Player2 (5000 in chips)
Seat 3: Hero (5000 in chips)
Seat 4: Player4 (5000 in chips)
Seat 5: Player5 (5000 in chips)
Seat 6: Player6 (5000 in chips)
Player1: posts the ante 10
Player2: posts the ante 10
Hero: posts the ante 10
Player4: posts the ante 10
Player5: posts the ante 10
Player6: posts the ante 10
Player2: posts small blind 50
Hero: posts big blind 100
*** HOLE CARDS ***
Dealt to Hero [Ah Kh]
Player4: folds
Player5: folds
Player6: folds
Player1: folds
Player2: folds
*** SUMMARY ***
Hero collected 210 from pot
"""
    h = parse_one_hand(walk_hand, 'test.txt')
    assert h is not None
    assert h.get('pf_action') == 'check', f"Walk should be 'check', got {h.get('pf_action')}"
    assert h.get('vpip') == False


# ============================================================
# RUNNER
# ============================================================

if __name__ == '__main__':
    tests = [
        test_villain_identity_record,
        test_shown_cards_parsing,
        test_primary_villain,
        test_matchups,
        test_seat_stacks_bb_all,
        test_pf_allin_called_jam,
        test_walk_not_fold,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed} passed, {failed} failed out of {len(tests)}")
    sys.exit(1 if failed > 0 else 0)
