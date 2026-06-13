#!/usr/bin/env python3
"""
test_pko.py — regression harness for gem_pko (IV.7 Bounty/PKO flip analysis).

Covers: range-token expansion, HU preflop jam-call reconstruction, and the
flip-detection logic (including the Hero-covers gate on the bounty discount).

Run: python3 test_pko.py   ·   exit 0 = pass, 1 = fail.
"""
import sys, os, unittest

HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
for p in ['/home/claude', HERE]:
    if os.path.exists(os.path.join(p, 'gem_pko.py')):
        sys.path.insert(0, p)
        break

import gem_pko


# A synthetic GG-style heads-up preflop jam-call HH. BB = 1000.
# Hero (BB, 60,000) covers the jammer (BTN, 40,000). Folds to BTN who jams
# 40,000 all-in; Hero calls 38,500 all-in. Uncalled 500 returned.
# Total pot = antes(8*100=800) + SB 500 + Hero BB already 1000 + jam matched
# 39,500 + Hero call 38,500 ... constructed so Total pot is explicit below.
_HH_FLIP = """Poker Hand #TM5900000001: Tournament #1, 1-X: $100 Test [Bounty]
Level5(500/1000) - 2026-05-24
  Seat 1: Hero (60000 in chips)
  Seat 2: villain1 (40000 in chips)
  Seat 3: other (50000 in chips)
  Hero: posts the ante 100
  villain1: posts the ante 100
  other: posts the ante 100
  other: posts small blind 500
  Hero: posts big blind 1000
*** HOLE CARDS ***
Dealt to Hero [Kh Qh]
  villain1: raises 39000 to 40000 and is all-in
  other: folds
  Hero: calls 39000 and is all-in
  Uncalled bet (0) returned to villain1
*** FLOP *** [2c 7d 9s]
*** TURN *** [2c 7d 9s] [3h]
*** RIVER *** [2c 7d 9s 3h] [4c]
*** SHOWDOWN ***
villain1: shows [Ad 5d]
Hero: shows [Kh Qh]
*** SUMMARY ***
Total pot 80700 | Rake 0
Seat 1: Hero (big blind) showed [Kh Qh]
Seat 2: villain1 showed [Ad 5d]
"""


class TestExpandPlus(unittest.TestCase):
    def test_pair_plus(self):
        self.assertEqual(gem_pko._expand_plus('TT+'),
                         ['TT', 'JJ', 'QQ', 'KK', 'AA'])

    def test_suited_plus(self):
        self.assertEqual(gem_pko._expand_plus('ATs+'),
                         ['ATs', 'AJs', 'AQs', 'AKs'])

    def test_offsuit_plus(self):
        self.assertEqual(gem_pko._expand_plus('KTo+'),
                         ['KTo', 'KJo', 'KQo'])

    def test_no_plus(self):
        self.assertEqual(gem_pko._expand_plus('QJs'), ['QJs'])


class TestReconstruct(unittest.TestCase):
    def test_hu_jam_call(self):
        ctx = gem_pko.reconstruct_hu_preflop_jam_call(_HH_FLIP)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['jammer_name'], 'villain1')
        # to_call = 39000 / 1000 bb
        self.assertAlmostEqual(ctx['to_call_bb'], 39.0, places=1)
        # pot_before_call = total 80700 - 39000 call = 41700 -> 41.7 bb
        self.assertAlmostEqual(ctx['pot_before_call_bb'], 41.7, places=1)
        # required equity = 39000 / 80700 = 48.3%
        self.assertAlmostEqual(ctx['required_equity'], 48.3, places=1)
        # Hero 60k covers villain 40k
        self.assertTrue(ctx['hero_covers'])

    def test_rejects_non_jam_call(self):
        # A HH with no "Hero: calls ... and is all-in" -> None
        bad = _HH_FLIP.replace('Hero: calls 39000 and is all-in',
                               'Hero: folds')
        self.assertIsNone(gem_pko.reconstruct_hu_preflop_jam_call(bad))


class TestFlipLogic(unittest.TestCase):
    def test_covers_gate(self):
        """When Hero covers, the bounty discount applies; the flip logic
        must be able to produce a flip. When Hero is covered it cannot."""
        hands = [{'id': 'TM5900000001', 'pf_allin': True, 'format': 'BOUNTY',
                  'tournament': 'Test', 'date': '2026-05-24', 'position': 'BB'}]
        res = gem_pko.analyze_pko_flips(hands, {'TM5900000001': _HH_FLIP})
        self.assertEqual(res['evaluated'], 1)
        # KQs equity vs a wide jam range is ~45-47%; required 48.3%.
        # freezeout: likely a fold (eq < 48.3). bounty: 48.3 - 8 = 40.3,
        # eq > 40.3 -> correct. So this should register as a flip (a).
        total_flips = len(res['flips_a']) + len(res['flips_b'])
        self.assertEqual(total_flips, 1)
        self.assertEqual(res['flips_a'][0]['flip'], 'a')
        self.assertEqual(res['flips_a'][0]['role'], 'caller')

    def test_covered_hero_no_flip(self):
        """Hero covered by the jammer -> bounty discount 0 -> cannot flip."""
        hh = _HH_FLIP.replace('Seat 1: Hero (60000 in chips)',
                              'Seat 1: Hero (30000 in chips)')
        # Hero 30k < villain 40k -> Hero is covered.
        hands = [{'id': 'TM5900000001', 'pf_allin': True, 'format': 'BOUNTY',
                  'tournament': 'Test', 'date': '2026-05-24', 'position': 'BB'}]
        res = gem_pko.analyze_pko_flips(hands, {'TM5900000001': hh})
        self.assertEqual(len(res['flips_a']) + len(res['flips_b']), 0)


# A synthetic HU Hero-JAM HH. BB = 1000. villain2 (BB-ish, 25,000) opens;
# Hero (30,000) jams over the open; villain folds. Hero covers.
_HH_HERO_JAM = """Poker Hand #TM5900000002: Tournament #2, 2-X: $100 Test [Bounty]
Level7(500/1000) - 2026-05-24
  Seat 1: Hero (30000 in chips)
  Seat 2: villain2 (25000 in chips)
  Seat 3: other2 (40000 in chips)
  Hero: posts the ante 100
  villain2: posts the ante 100
  other2: posts the ante 100
  other2: posts small blind 500
  Hero: posts big blind 1000
*** HOLE CARDS ***
Dealt to Hero [Ah Ks]
  villain2: raises 1500 to 2500
  Hero: raises 27500 to 30000 and is all-in
  other2: folds
  villain2: folds
  Uncalled bet (5000) returned to Hero
*** SHOWDOWN ***
*** SUMMARY ***
Total pot 29100 | Rake 0
Seat 1: Hero collected (29100)
"""


class TestJammerReconstruct(unittest.TestCase):
    def test_hu_hero_jam(self):
        ctx = gem_pko.reconstruct_hu_preflop_hero_jam(_HH_HERO_JAM)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['villain_name'], 'villain2')
        self.assertFalse(ctx['was_called'])
        self.assertTrue(ctx['hero_covers'])     # Hero 30k covers villain 25k
        # effective contest = min(30k, 25k) / 1000 = 25.0 bb
        self.assertAlmostEqual(ctx['eff_contest_bb'], 25.0, places=1)

    def test_rejects_hero_call(self):
        # _HH_FLIP is a Hero-CALL hand -> jammer reconstruction returns None
        self.assertIsNone(gem_pko.reconstruct_hu_preflop_hero_jam(_HH_FLIP))


class TestJammerEV(unittest.TestCase):
    def test_shove_ev_fold_branch(self):
        """A pure-fold outcome: EV = pot_now (dead money won)."""
        ctx = {'eff_contest_bb': 20.0, 'pot_before_jam_bb': 3.0}
        ev = gem_pko.jammer_shove_ev(ctx, fold_pct=100.0,
                                     hero_equity_pct=0.0, bounty_credit_bb=0.0)
        self.assertAlmostEqual(ev, 3.0, places=2)

    def test_bounty_credit_lifts_ev(self):
        """A positive bounty credit raises the called-branch EV."""
        ctx = {'eff_contest_bb': 20.0, 'pot_before_jam_bb': 3.0}
        ev_no = gem_pko.jammer_shove_ev(ctx, 50.0, 50.0, 0.0)
        ev_bty = gem_pko.jammer_shove_ev(ctx, 50.0, 50.0, 4.0)
        self.assertGreater(ev_bty, ev_no)

    def test_jammer_path_evaluated(self):
        """The jammer hand routes through analyze_pko_flips and is counted."""
        hands = [{'id': 'TM5900000002', 'pf_allin': True, 'format': 'BOUNTY',
                  'tournament': 'Test', 'date': '2026-05-24', 'position': 'BTN'}]
        res = gem_pko.analyze_pko_flips(hands, {'TM5900000002': _HH_HERO_JAM})
        self.assertEqual(res['evaluated_jammer'], 1)
        self.assertEqual(res['evaluated_caller'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
