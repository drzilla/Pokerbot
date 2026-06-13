#!/usr/bin/env python3
"""
test_bounty.py — regression harness for gem_bounty (bounty estimation).

Covers: format classification from tournament name + parser tag, phase
multipliers, the hero-covers gate, the documented regular/post_reg anchor,
and the discount ceiling.

Run: python3 test_bounty.py   ·   exit 0 = pass, 1 = fail.
"""
import sys, os, unittest

HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
for p in ['/home/claude', HERE]:
    if os.path.exists(os.path.join(p, 'gem_bounty.py')):
        sys.path.insert(0, p)
        break

import gem_bounty


class TestClassify(unittest.TestCase):
    def test_regular(self):
        c = gem_bounty.classify_bounty('215-L 3 Sunday Bounty King', 'BOUNTY')
        self.assertEqual(c['bounty_type'], 'regular')
        self.assertEqual(c['discount_pp'], 8.0)

    def test_big_bounties(self):
        c = gem_bounty.classify_bounty(
            '218-M 30 Sunday Bounty Bonanza [Big Bounties]', 'BOUNTY')
        self.assertEqual(c['bounty_type'], 'big')
        self.assertGreater(c['discount_pp'], 8.0)

    def test_mystery(self):
        c = gem_bounty.classify_bounty(
            '216-L 10 Sunday Showdown [Mystery Bounty]', 'MYSTERY_BOUNTY')
        self.assertEqual(c['bounty_type'], 'mystery')

    def test_freezeout(self):
        c = gem_bounty.classify_bounty('214-L 25 Sunday Main Event', 'FREEZEOUT')
        self.assertEqual(c['bounty_type'], 'none')
        self.assertEqual(c['discount_pp'], 0.0)

    def test_satellite_never_bounty(self):
        # a satellite into a bounty event must not be typed as a bounty
        c = gem_bounty.classify_bounty('Sunday Bounty Satellite', 'SATELLITE')
        self.assertEqual(c['bounty_type'], 'none')

    def test_format_tag_gates_name(self):
        # name says bounty but parser tagged freezeout -> freezeout wins
        c = gem_bounty.classify_bounty('Some Bounty-ish Name', 'FREEZEOUT')
        self.assertEqual(c['bounty_type'], 'none')

    def test_name_only_no_fmt(self):
        c = gem_bounty.classify_bounty('Bounty Hyper Madness', None)
        self.assertEqual(c['bounty_type'], 'regular')


class TestPhase(unittest.TestCase):
    def test_baseline(self):
        self.assertEqual(gem_bounty.phase_weight('post_reg'), 1.00)

    def test_ordering(self):
        # bounty weight rises as stacks shrink toward the final table
        self.assertLess(gem_bounty.phase_weight('late_reg'),
                        gem_bounty.phase_weight('post_reg'))
        self.assertLess(gem_bounty.phase_weight('post_reg'),
                        gem_bounty.phase_weight('bubble_zone'))
        self.assertLess(gem_bounty.phase_weight('bubble_zone'),
                        gem_bounty.phase_weight('ft_zone'))

    def test_unknown_phase_baseline(self):
        self.assertEqual(gem_bounty.phase_weight('nonsense'), 1.00)
        self.assertEqual(gem_bounty.phase_weight(None), 1.00)


class TestDiscount(unittest.TestCase):
    def test_documented_anchor(self):
        # regular bounty at the post_reg baseline == the documented ~8pp
        d = gem_bounty.bounty_discount_pp(
            'Sunday Bounty King', 'post_reg', fmt='BOUNTY', hero_covers=True)
        self.assertEqual(d, 8.0)

    def test_hero_must_cover(self):
        # no cover -> no bounty credit, even in a bounty format
        d = gem_bounty.bounty_discount_pp(
            'Sunday Bounty King', 'ft_zone', fmt='BOUNTY', hero_covers=False)
        self.assertEqual(d, 0.0)

    def test_phase_scales(self):
        early = gem_bounty.bounty_discount_pp(
            'Bounty King', 'late_reg', fmt='BOUNTY')
        late = gem_bounty.bounty_discount_pp(
            'Bounty King', 'ft_zone', fmt='BOUNTY')
        self.assertLess(early, late)

    def test_big_above_regular(self):
        reg = gem_bounty.bounty_discount_pp('Bounty King', 'post_reg', fmt='BOUNTY')
        big = gem_bounty.bounty_discount_pp(
            'Bounty Bonanza [Big Bounties]', 'post_reg', fmt='BOUNTY')
        self.assertGreater(big, reg)

    def test_ceiling(self):
        # no name/phase combination may exceed the hard ceiling
        d = gem_bounty.bounty_discount_pp(
            'Bounty Bonanza [Big Bounties]', 'ft_zone', fmt='BOUNTY')
        self.assertLessEqual(d, 20.0)

    def test_freezeout_zero(self):
        d = gem_bounty.bounty_discount_pp(
            'Sunday Main Event', 'ft_zone', fmt='FREEZEOUT')
        self.assertEqual(d, 0.0)


class TestValueBB(unittest.TestCase):
    def test_regular_anchor(self):
        v = gem_bounty.bounty_value_bb('Bounty King', 'post_reg', fmt='BOUNTY')
        self.assertEqual(v, 4.0)

    def test_no_cover_zero(self):
        v = gem_bounty.bounty_value_bb(
            'Bounty King', 'post_reg', fmt='BOUNTY', hero_covers=False)
        self.assertEqual(v, 0.0)


class TestContext(unittest.TestCase):
    def test_bundle_keys(self):
        ctx = gem_bounty.bounty_context(
            'Bounty Bonanza [Big Bounties]', 'ft_zone', fmt='BOUNTY')
        for k in ('bounty_type', 'label', 'phase', 'phase_weight',
                  'hero_covers', 'discount_pp', 'value_bb', 'basis'):
            self.assertIn(k, ctx)
        self.assertEqual(ctx['bounty_type'], 'big')

    def test_no_cover_zeroes_bundle(self):
        ctx = gem_bounty.bounty_context(
            'Bounty King', 'ft_zone', fmt='BOUNTY', hero_covers=False)
        self.assertEqual(ctx['discount_pp'], 0.0)
        self.assertEqual(ctx['value_bb'], 0.0)


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"\n\u2705 ALL TESTS PASSED \u2014 "
              f"{result.testsRun}/{result.testsRun}")
        sys.exit(0)
    print(f"\n\u274c FAILED \u2014 {len(result.failures)} fail, "
          f"{len(result.errors)} error")
    sys.exit(1)
