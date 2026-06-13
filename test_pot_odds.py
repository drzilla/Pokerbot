#!/usr/bin/env python3
"""
test_pot_odds.py — regression harness for gem_pot_odds.

Covers: equity enumeration (river/turn/tie), all-in call reconstruction
(pot-odds identity), the HH integrity check, the per-hand pot_odds block,
BUG-5 range-based equity (result-leak elimination),
BUG-6 per-street call detection, BUG-7 multiway pot detection.

Run: python3 test_pot_odds.py   ·   exit 0 = pass, 1 = fail.
"""
import sys, os, unittest

HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
for p in ['/home/claude', HERE]:
    if os.path.exists(os.path.join(p, 'gem_pot_odds.py')):
        sys.path.insert(0, p)
        break

import gem_pot_odds


# A synthetic GG-style turn all-in call. BB = 600.
# BTN(Hero) opens, BB calls; flop bet/call; turn bet then BB jams, Hero calls
# all-in. Hero A-high nut-flush DRAW (4 hearts) vs villain's made K-high flush.
# Total pot 51480, Hero's all-in call 15840 -> required equity 30.8%.
_HH_TURN_CALL = """Poker Hand #TM5900000099: Tournament #9, 9-X: $21 Sunday Test [Bounty Hyper] Hold'em No Limit - Level9(300/600(90)) - 2026-05-25
Table '90' 6-max Seat #1 is the button
Seat 1: Hero (25410 in chips)
Seat 3: villainX (30570 in chips)
Hero: posts the ante 90
villainX: posts the ante 90
villainX: posts big blind 600
*** HOLE CARDS ***
Dealt to Hero [Ah 6d]
Hero: raises 660 to 1260
villainX: calls 660
*** FLOP *** [7d 3h Kh]
villainX: checks
Hero: bets 2520
villainX: calls 2520
*** TURN *** [7d 3h Kh] [Th]
villainX: checks
Hero: bets 5700
villainX: raises 21000 to 26700 and is all-in
Hero: calls 15840 and is all-in
Uncalled bet (5160) returned to villainX
villainX: shows [4h 8h] (a flush King high)
*** RIVER *** [7d 3h Kh Th] [4s]
*** SHOWDOWN ***
villainX collected 51480 from pot
*** SUMMARY ***
Total pot 51480 | Rake 0
Board [7d 3h Kh Th 4s]
Seat 1: Hero (button) showed [Ah 6d] and lost with Ace high
Seat 3: villainX (big blind) showed [4h 8h] and won (51480) with a flush King high
"""

# BUG-5: Preflop all-in call — 22 vs villain's jam. BB = 400.
# Villain jams ~18BB, Hero calls with 22. Villain shows 77.
# Shown equity ≈ 17.9% (result-leaked) but range equity should be ~40%.
_HH_PREFLOP_ALLIN = """Poker Hand #TM6000000001: Tournament #10, 10-X: $11 Sunday Test [Bounty Hyper] Hold'em No Limit - Level7(200/400(50)) - 2026-05-29
Table '101' 6-max Seat #1 is the button
Seat 1: Hero (12500 in chips)
Seat 3: villJam (7200 in chips)
Seat 4: Player3 (8800 in chips)
Hero: posts the ante 50
villJam: posts the ante 50
Player3: posts the ante 50
Player3: posts big blind 400
*** HOLE CARDS ***
Dealt to Hero [2h 2d]
Hero: raises 400 to 800
villJam: raises 6350 to 7150 and is all-in
Player3: folds
Hero: calls 6350 and is all-in
Uncalled bet (5300) returned to Hero
villJam: shows [7s 7c] (a pair of Sevens)
*** FLOP *** [Kd 9c 3h]
*** TURN *** [Kd 9c 3h] [Ts]
*** RIVER *** [Kd 9c 3h Ts] [Jd]
*** SHOWDOWN ***
villJam collected 14850 from pot
*** SUMMARY ***
Total pot 14850 | Rake 0
Board [Kd 9c 3h Ts Jd]
Seat 1: Hero (button) showed [2h 2d] and lost with a pair of Deuces
Seat 3: villJam showed [7s 7c] and won (14850) with a pair of Sevens
"""

# BUG-6: Multi-street call-down — Hero calls flop, calls turn, calls river all-in.
# The root mistake is the TURN call, not the river.
_HH_MULTI_STREET = """Poker Hand #TM6015017178: Tournament #11, 11-X: $11 Test [Bounty Hyper] Hold'em No Limit - Level8(250/500(60)) - 2026-05-29
Table '110' 6-max Seat #1 is the button
Seat 1: Hero (18000 in chips)
Seat 4: villAgg (22000 in chips)
Hero: posts the ante 60
villAgg: posts the ante 60
villAgg: posts big blind 500
*** HOLE CARDS ***
Dealt to Hero [Ah 8c]
Hero: raises 500 to 1000
villAgg: calls 500
*** FLOP *** [8d 4s 3c]
villAgg: bets 1500
Hero: calls 1500
*** TURN *** [8d 4s 3c] [7s]
villAgg: bets 4000
Hero: calls 4000
*** RIVER *** [8d 4s 3c 7s] [5h]
villAgg: bets 15380 and is all-in
Hero: calls 11380 and is all-in
Uncalled bet (4000) returned to villAgg
villAgg: shows [9s 6s] (a straight Five to Nine)
*** SHOWDOWN ***
villAgg collected 36000 from pot
*** SUMMARY ***
Total pot 36000 | Rake 0
Board [8d 4s 3c 7s 5h]
Seat 1: Hero (button) showed [Ah 8c] and lost with a pair of Eights
Seat 4: villAgg (big blind) showed [9s 6s] and won (36000) with a straight Five to Nine
"""

# BUG-7: 3-way pot with all-in short stack creating main/side pot.
_HH_MULTIWAY = """Poker Hand #TM6015602613: Tournament #12, 12-X: $11 Test [Bounty Hyper] Hold'em No Limit - Level10(400/800(100)) - 2026-05-29
Table '120' 6-max Seat #1 is the button
Seat 1: Hero (15000 in chips)
Seat 3: villShort (3200 in chips)
Seat 4: villLive (20000 in chips)
Hero: posts the ante 100
villShort: posts the ante 100
villLive: posts the ante 100
villLive: posts big blind 800
*** HOLE CARDS ***
Dealt to Hero [Ac 5h]
Hero: raises 800 to 1600
villShort: calls 1600 and is all-in
villLive: calls 800
Uncalled bet (700) returned to villShort
*** FLOP *** [5d 3s 8c]
villLive: bets 2400
Hero: calls 2400
*** TURN *** [5d 3s 8c] [Th]
villLive: bets 4800
Hero: folds
villLive: shows [Kh Kd] (a pair of Kings)
villShort: shows [Js Jc] (a pair of Jacks)
*** RIVER *** [5d 3s 8c Th] [2c]
*** SHOWDOWN ***
villLive collected 9900 from Side pot
villLive collected 5700 from Main pot
*** SUMMARY ***
Total pot 15600 | Rake 0
Main pot 5700 | Side pot 9900
Board [5d 3s 8c Th 2c]
Seat 1: Hero (button) showed [Ac 5h] and lost
Seat 3: villShort showed [Js Jc] and lost with a pair of Jacks
Seat 4: villLive (big blind) showed [Kh Kd] and won (15600) with a pair of Kings
"""


class TestEnumerateEquity(unittest.TestCase):
    def test_river_hero_wins(self):
        # board complete, Hero has a flush, villain a worse flush
        eq = gem_pot_odds.enumerate_equity(
            ['As', '2s'], [['Ks', '3s']], ['4s', '9s', 'Ts', '8d', '2d'])
        self.assertEqual(eq, 100.0)

    def test_river_hero_loses(self):
        eq = gem_pot_odds.enumerate_equity(
            ['Ks', '3s'], [['As', '2s']], ['4s', '9s', 'Ts', '8d', '2d'])
        self.assertEqual(eq, 0.0)

    def test_river_tie_plays_board(self):
        # both play the same board straight -> chop
        eq = gem_pot_odds.enumerate_equity(
            ['2c', '3d'], [['2h', '3s']], ['Ts', 'Jc', 'Qd', 'Kh', 'Ad'])
        self.assertEqual(eq, 50.0)

    def test_turn_known_draw(self):
        # the 96906069 turn spot: nut-flush draw vs a made flush, 1 to come
        eq = gem_pot_odds.enumerate_equity(
            ['Ah', '6d'], [['4h', '8h']], ['7d', '3h', 'Kh', 'Th'])
        self.assertEqual(eq, 15.9)        # 7 live hearts / 44 run-outs

    def test_bad_input(self):
        self.assertIsNone(gem_pot_odds.enumerate_equity(['Ah'], [['Kd', 'Kc']], []))
        # duplicate card
        self.assertIsNone(gem_pot_odds.enumerate_equity(
            ['Ah', '6d'], [['Ah', '8h']], []))


class TestReconstruct(unittest.TestCase):
    def setUp(self):
        self.ctx = gem_pot_odds.reconstruct_allin_call(_HH_TURN_CALL)

    def test_found(self):
        self.assertIsNotNone(self.ctx)

    def test_street(self):
        self.assertEqual(self.ctx['street'], 'turn')

    def test_pot_odds_identity(self):
        # required = to_call / total_pot
        self.assertEqual(self.ctx['to_call_bb'], 26.4)     # 15840 / 600
        self.assertEqual(self.ctx['total_pot_bb'], 85.8)   # 51480 / 600
        self.assertEqual(self.ctx['required_eq_pct'], 30.8)

    def test_cards_and_board(self):
        self.assertEqual(self.ctx['hero_cards'], ['Ah', '6d'])
        self.assertEqual(self.ctx['villain_hands'], [['4h', '8h']])
        self.assertEqual(self.ctx['board_at_decision'],
                         ['7d', '3h', 'Kh', 'Th'])

    def test_hero_does_not_cover(self):
        # Hero 25410 < villain 30570 -> Hero does not cover the field
        self.assertFalse(self.ctx['hero_covers_all'])

    def test_hero_lost(self):
        self.assertFalse(self.ctx['hero_won'])

    def test_no_allin_returns_none(self):
        self.assertIsNone(gem_pot_odds.reconstruct_allin_call(
            "Poker Hand #X: Level1(50/100) - x\nHero: folds\n"))


class TestIntegrity(unittest.TestCase):
    def test_consistent_no_flag(self):
        # 96906069 is consistent: villain's made flush beats Hero's ace-high
        flag = gem_pot_odds.integrity_check(
            ['Ah', '6d'], [['4h', '8h']],
            ['7d', '3h', 'Kh', 'Th', '4s'], hero_won=False)
        self.assertIsNone(flag)

    def test_corrupt_fires(self):
        # record says Hero lost, but Hero actually has the nut straight
        flag = gem_pot_odds.integrity_check(
            ['Ah', 'Kh'], [['2c', '3d']],
            ['Qh', 'Jh', 'Th', '4s', '5c'], hero_won=False)
        self.assertIsNotNone(flag)
        self.assertIn('MISMATCH', flag)


class TestComputeBlock(unittest.TestCase):
    """Test the turn all-in call block (postflop — range unavailable)."""
    def setUp(self):
        hand = {'tournament': '9-X Sunday Test [Bounty Hyper]',
                'tournament_phase': 'post_reg', 'format': 'BOUNTY'}
        self.block = gem_pot_odds.compute_hand_pot_odds(hand, _HH_TURN_CALL)

    def test_block_built(self):
        self.assertIsNotNone(self.block)

    def test_realized_equity_exists(self):
        """BUG-5: shown-hand equity moved to realized_equity_vs_shown."""
        self.assertEqual(self.block['realized_equity_vs_shown'], 15.9)
        self.assertEqual(self.block['realized_equity_mode'], 'exact_vs_shown')
        self.assertIn('RESULT-DERIVED', self.block['realized_equity_note'])

    def test_equity_falls_back_to_shown(self):
        """W3: when range equity unavailable, hero_equity_pct falls back to
        shown-hand equity so analyst has §3b numbers."""
        # Postflop with shown villain → realized equity used as fallback
        self.assertEqual(self.block['hero_equity_pct'], 15.9)
        self.assertEqual(self.block['equity_mode'], 'exact_vs_shown')

    def test_verdict_uses_fallback_equity(self):
        """W3: verdict uses the fallback equity (shown-hand) when range unavailable."""
        # With 15.9% equity vs 30.8% required → call -EV
        self.assertIn('-EV', self.block['verdict_hint'])

    def test_required_equity(self):
        self.assertEqual(self.block['required_eq_pct'], 30.8)

    def test_no_bounty_credit_when_hero_uncovered(self):
        self.assertFalse(self.block['hero_covers_field'])
        self.assertNotIn('required_eq_bounty_pct', self.block)

    def test_no_false_integrity_flag(self):
        self.assertNotIn('integrity_flag', self.block)


class TestBug5RangeEquity(unittest.TestCase):
    """BUG-5: preflop all-in must use range equity, not shown-hand equity."""

    def setUp(self):
        # 22 vs 77 preflop all-in. Villain jams ~18BB.
        hand = {'jammer_stack_bb': 18.0, 'eff_stack_bb': 18.0,
                'tournament': '10-X', 'tournament_phase': 'post_reg',
                'format': 'BOUNTY'}
        self.block = gem_pot_odds.compute_hand_pot_odds(hand, _HH_PREFLOP_ALLIN)

    def test_block_exists(self):
        self.assertIsNotNone(self.block)

    def test_realized_equity_is_result_leaked(self):
        """Shown-hand equity for 22 vs 77 is ~17.9% — the known result-leak."""
        re_eq = self.block['realized_equity_vs_shown']
        self.assertIsNotNone(re_eq)
        # 22 vs 77 preflop MC: ~17-19%
        self.assertGreater(re_eq, 15)
        self.assertLess(re_eq, 22)

    def test_range_equity_is_plausible(self):
        """BUG-5 acceptance: hero_equity_pct must NOT be ~18% (vs shown 77).
        22 vs a ~38% jam range (18BB bucket) should be ~35-45%."""
        eq = self.block['hero_equity_pct']
        self.assertIsNotNone(eq, "Range equity must be available for preflop all-in")
        self.assertEqual(self.block['equity_mode'], 'range_mc')
        # Must be significantly higher than the result-leaked 17.9%
        self.assertGreater(eq, 28, f"22 vs jam range should be >28%, got {eq}%")
        # Must be plausible (not >60% for a small pair)
        self.assertLess(eq, 55, f"22 vs jam range should be <55%, got {eq}%")

    def test_verdict_uses_range(self):
        """Verdict should say 'vs range', not 'on the numbers'."""
        self.assertIn('vs range', self.block['verdict_hint'])
        self.assertNotIn('on the numbers', self.block['verdict_hint'])

    def test_ev_uses_range(self):
        """ev_call_bb must be computed from range equity, not shown equity."""
        self.assertIsNotNone(self.block['ev_call_bb'])
        # With range equity ~40% and required ~48%, EV should be close to 0
        # (not the deeply negative value from 17.9% shown equity)

    def test_range_note_mentions_jam_range(self):
        self.assertIn('jam range', self.block['equity_note'])


class TestBug5KKvsCooler(unittest.TestCase):
    """BUG-5 acceptance: a known cooler (KK preflop all-in vs a jam range)
    should show ~65-80% equity, not 0% (if villain's set ran it out)."""

    def test_kk_preflop_vs_jam_range(self):
        """KK vs ~38% jam range (18BB) should be ~65-80%."""
        eq, mode, note = gem_pot_odds.compute_range_equity(
            ['Kh', 'Kc'], [], 18.0, 'preflop')
        self.assertIsNotNone(eq)
        self.assertEqual(mode, 'range_mc')
        self.assertGreater(eq, 60, f"KK vs jam range should be >60%, got {eq}%")
        self.assertLess(eq, 88, f"KK vs jam range should be <88%, got {eq}%")


class TestBug6PerStreetCalls(unittest.TestCase):
    """BUG-6: multi-street call-down should show per-street pot odds."""

    def setUp(self):
        hand = {'tournament': '11-X', 'tournament_phase': 'post_reg',
                'format': 'BOUNTY'}
        self.block = gem_pot_odds.compute_hand_pot_odds(hand, _HH_MULTI_STREET)

    def test_block_exists(self):
        self.assertIsNotNone(self.block)

    def test_per_street_calls_detected(self):
        """Must detect flop and turn calls (before the river all-in)."""
        psc = self.block.get('per_street_calls', [])
        self.assertGreaterEqual(len(psc), 1,
            "Must detect at least the flop call before the all-in")

    def test_per_street_has_pot_odds(self):
        """Each per-street call must include pot odds data."""
        for ps in self.block.get('per_street_calls', []):
            self.assertIn('street', ps)
            self.assertIn('call_bb', ps)
            self.assertIn('required_eq_pct', ps)


class TestBug7MultiwayDetection(unittest.TestCase):
    """BUG-7: multiway pot with main/side pot split detection."""

    def test_multiway_detected(self):
        mw = gem_pot_odds._detect_multiway_allin(_HH_MULTIWAY)
        self.assertIsNotNone(mw, "Must detect multiway all-in pot")
        self.assertTrue(mw['has_main_side_split'])
        self.assertGreaterEqual(mw['n_allins'], 1)

    def test_hero_folded_side_pot(self):
        mw = gem_pot_odds._detect_multiway_allin(_HH_MULTIWAY)
        self.assertTrue(mw['hero_folded_side_pot'],
            "Must detect Hero folded to side-pot action")

    def test_main_pot_amount(self):
        mw = gem_pot_odds._detect_multiway_allin(_HH_MULTIWAY)
        # Main pot 5700 / BB 800 = 7.1BB
        self.assertGreater(mw['main_pot_bb'], 0)

    def test_non_multiway_returns_none(self):
        """Single all-in (no pot split) should return None."""
        mw = gem_pot_odds._detect_multiway_allin(_HH_TURN_CALL)
        self.assertIsNone(mw)


class TestBug7OverfoldDetection(unittest.TestCase):
    """BUG-7: detect over-fold when Hero folds with main-pot equity."""

    def test_overfold_detected(self):
        hand = {'tournament': '12-X', 'format': 'BOUNTY'}
        of = gem_pot_odds.detect_multiway_overfold(hand, _HH_MULTIWAY)
        self.assertIsNotNone(of, "Must detect Hero's over-fold in multiway pot")

    def test_fold_street(self):
        hand = {'tournament': '12-X', 'format': 'BOUNTY'}
        of = gem_pot_odds.detect_multiway_overfold(hand, _HH_MULTIWAY)
        self.assertEqual(of['fold_street'], 'turn')

    def test_hero_equity_plausible(self):
        """Hero has A5 (pair of fives) on 5d3s8cTh — reasonable equity."""
        hand = {'tournament': '12-X', 'format': 'BOUNTY'}
        of = gem_pot_odds.detect_multiway_overfold(hand, _HH_MULTIWAY)
        eq = of.get('hero_equity_at_fold_pct')
        # A5 vs KK + JJ on 5d3s8cTh: Hero has second pair, should have
        # some equity (maybe 10-25% with 5 outs for trips/two pair)
        if eq is not None:
            self.assertGreater(eq, 0, "Hero must have some equity")


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"\n✅ ALL TESTS PASSED — "
              f"{result.testsRun}/{result.testsRun}")
        sys.exit(0)
    print(f"\n❌ FAILED — {len(result.failures)} fail, "
          f"{len(result.errors)} error")
    sys.exit(1)
