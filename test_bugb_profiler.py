#!/usr/bin/env python3
"""BUG-B profiler fix — acceptance tests.

Tests identity correctness, stat correctness, and prints before/after QA summary.
"""
import pytest
from gem_opponent_profiler import profile_opponents, tag_hands_with_archetypes, find_misplays_vs_archetype


# ============================================================
# Test helpers — build synthetic hands
# ============================================================

def _make_hand(tid='288240370', hid='TM6040001', hero='Hero',
               villains=None, opener_position='', action_ledger=None,
               went_to_sd=False, pf_raise_count=0, stacks_behind=None):
    """Build a minimal hand dict for profiler tests."""
    h = {
        'id': hid,
        'tournament_id': tid,
        'tournament': f'Tournament #{tid}'[:30],
        'hero': hero,
        'villains': villains or {},
        'opener_position': opener_position,
        'action_ledger': action_ledger or [],
        'went_to_sd': went_to_sd,
        'pf_raise_count': pf_raise_count,
        'stacks_behind': stacks_behind or {},
        'hero_street_actions': {},
    }
    return h


def _make_villain(name, position, stack_bb=50):
    return {name: {'name': name, 'seat': 1, 'position': position, 'stack_bb': stack_bb, 'shown_cards': None}}


def _pf_action(player, action, street='preflop', amount_bb=0):
    return {'street': street, 'player': player, 'position': '?', 'action': action,
            'amount_bb': amount_bb, 'is_all_in': False}


# ============================================================
# A. Identity correctness
# ============================================================

class TestIdentityCorrectness:

    def test_same_villain_multiple_positions_gets_one_profile(self):
        """Same player_hash in different positions = single profile."""
        hands = [
            _make_hand(hid='TM1', villains=_make_villain('abc123', 'BTN'),
                       action_ledger=[_pf_action('abc123', 'raises')],
                       opener_position='BTN'),
            _make_hand(hid='TM2', villains=_make_villain('abc123', 'CO'),
                       action_ledger=[_pf_action('abc123', 'raises')],
                       opener_position='CO'),
            _make_hand(hid='TM3', villains=_make_villain('abc123', 'SB'),
                       action_ledger=[_pf_action('abc123', 'calls')],
                       opener_position=''),
        ]
        profiles = profile_opponents(hands, hero_name='Hero')
        # Should be exactly one key: tid|abc123
        abc_keys = [k for k in profiles if 'abc123' in k]
        assert len(abc_keys) == 1, f"Expected 1 profile for abc123, got {len(abc_keys)}: {abc_keys}"
        p = profiles[abc_keys[0]]
        assert p['hands_seen'] == 3
        assert 'BTN' in p['positions_seen']
        assert 'CO' in p['positions_seen']
        assert 'SB' in p['positions_seen']

    def test_different_villains_same_position_separate_profiles(self):
        """Two different players who both sat BTN = two separate profiles."""
        hands = [
            _make_hand(hid='TM1', villains=_make_villain('player_a', 'BTN'),
                       action_ledger=[_pf_action('player_a', 'raises')],
                       opener_position='BTN'),
            _make_hand(hid='TM2', villains=_make_villain('player_b', 'BTN'),
                       action_ledger=[_pf_action('player_b', 'calls')],
                       opener_position=''),
        ]
        profiles = profile_opponents(hands, hero_name='Hero')
        a_keys = [k for k in profiles if 'player_a' in k]
        b_keys = [k for k in profiles if 'player_b' in k]
        assert len(a_keys) == 1
        assert len(b_keys) == 1
        assert a_keys[0] != b_keys[0]

    def test_different_villains_same_seat_separate_profiles(self):
        """Different players in seat 3 across hands = separate profiles."""
        v1 = {'p1': {'name': 'p1', 'seat': 3, 'position': 'CO', 'stack_bb': 50, 'shown_cards': None}}
        v2 = {'p2': {'name': 'p2', 'seat': 3, 'position': 'CO', 'stack_bb': 40, 'shown_cards': None}}
        hands = [
            _make_hand(hid='TM1', villains=v1),
            _make_hand(hid='TM2', villains=v2),
        ]
        profiles = profile_opponents(hands, hero_name='Hero')
        p1_keys = [k for k in profiles if 'p1' in k]
        p2_keys = [k for k in profiles if 'p2' in k]
        assert len(p1_keys) == 1
        assert len(p2_keys) == 1

    def test_hero_never_included_as_villain(self):
        """Hero should never appear in profiles."""
        v = {'Hero': {'name': 'Hero', 'seat': 1, 'position': 'BTN', 'stack_bb': 50, 'shown_cards': None},
             'villain1': {'name': 'villain1', 'seat': 2, 'position': 'SB', 'stack_bb': 50, 'shown_cards': None}}
        # Hero appears in villains dict (shouldn't happen in practice, but defensive)
        hands = [_make_hand(hid='TM1', villains=v, hero='Hero',
                            action_ledger=[_pf_action('Hero', 'raises'), _pf_action('villain1', 'calls')])]
        profiles = profile_opponents(hands, hero_name='Hero')
        for k in profiles:
            assert '|Hero' not in k, f"Hero found in profile key: {k}"

    def test_no_position_keyed_profiles(self):
        """No profile key should be tournament|BTN or tournament|SB etc."""
        position_labels = {'BTN', 'SB', 'BB', 'CO', 'HJ', 'MP', 'UTG', 'UTG+1', 'LJ', 'UNK', '?'}
        hands = [
            _make_hand(hid='TM1',
                       villains={**_make_villain('abc', 'BTN'), **_make_villain('def', 'SB')},
                       action_ledger=[_pf_action('abc', 'raises')],
                       opener_position='BTN'),
        ]
        profiles = profile_opponents(hands, hero_name='Hero')
        for k in profiles:
            parts = k.split('|', 1)
            if len(parts) == 2:
                assert parts[1] not in position_labels, \
                    f"Profile key {k} uses position label '{parts[1]}' instead of player hash"


# ============================================================
# B. Stat correctness
# ============================================================

class TestStatCorrectness:

    def test_vpip_counts_calls_not_just_raises(self):
        """VPIP should increment on calls AND raises."""
        hands = []
        for i in range(20):
            if i < 10:
                # Villain raises (VPIP + PFR)
                ledger = [_pf_action('v1', 'raises')]
                opener = 'BTN'
            else:
                # Villain calls (VPIP only)
                ledger = [_pf_action('v1', 'calls')]
                opener = ''
            hands.append(_make_hand(
                hid=f'TM{i}', villains=_make_villain('v1', 'BTN'),
                action_ledger=ledger, opener_position=opener))
        profiles = profile_opponents(hands, hero_name='Hero')
        v1_key = [k for k in profiles if 'v1' in k][0]
        p = profiles[v1_key]
        assert p['vpip'] == 20, f"VPIP should be 20, got {p['vpip']}"
        assert p['pfr'] == 10, f"PFR should be 10, got {p['pfr']}"
        assert p['vpip'] > p['pfr'], "VPIP must be > PFR when villain also calls"

    def test_vpip_not_equal_pfr_for_caller(self):
        """A villain who only calls should have VPIP > 0 and PFR == 0."""
        hands = [_make_hand(hid=f'TM{i}', villains=_make_villain('caller', 'CO'),
                            action_ledger=[_pf_action('caller', 'calls')])
                 for i in range(20)]
        profiles = profile_opponents(hands, hero_name='Hero')
        k = [k for k in profiles if 'caller' in k][0]
        p = profiles[k]
        assert p['vpip'] == 20
        assert p['pfr'] == 0
        assert p['vpip'] > p['pfr']

    def test_vpip_equals_pfr_only_for_pure_raiser(self):
        """VPIP == PFR is only correct when villain ONLY raises, never calls."""
        hands = [_make_hand(hid=f'TM{i}', villains=_make_villain('raiser', 'BTN'),
                            action_ledger=[_pf_action('raiser', 'raises')],
                            opener_position='BTN')
                 for i in range(20)]
        profiles = profile_opponents(hands, hero_name='Hero')
        k = [k for k in profiles if 'raiser' in k][0]
        p = profiles[k]
        # This IS a legitimate VPIP==PFR case
        assert p['vpip'] == p['pfr'] == 20

    def test_limp_counted_as_vpip_not_pfr(self):
        """A limper (calls pre, no raise) should have VPIP but not PFR."""
        hands = [_make_hand(hid=f'TM{i}', villains=_make_villain('limper', 'HJ'),
                            action_ledger=[_pf_action('limper', 'calls')])
                 for i in range(20)]
        profiles = profile_opponents(hands, hero_name='Hero')
        k = [k for k in profiles if 'limper' in k][0]
        p = profiles[k]
        assert p['vpip'] == 20
        assert p['pfr'] == 0
        assert p['limp'] == 20

    def test_postflop_actions_populate(self):
        """Postflop bets/calls/folds from ledger should populate stats."""
        ledger = [
            _pf_action('v1', 'raises'),
            {'street': 'flop', 'player': 'v1', 'position': 'BTN', 'action': 'bets', 'amount_bb': 3, 'is_all_in': False},
            {'street': 'turn', 'player': 'v1', 'position': 'BTN', 'action': 'bets', 'amount_bb': 6, 'is_all_in': False},
            {'street': 'river', 'player': 'v1', 'position': 'BTN', 'action': 'checks', 'amount_bb': 0, 'is_all_in': False},
        ]
        hands = [_make_hand(hid='TM1', villains=_make_villain('v1', 'BTN'),
                            action_ledger=ledger, opener_position='BTN')]
        profiles = profile_opponents(hands, hero_name='Hero')
        k = [k for k in profiles if 'v1' in k][0]
        p = profiles[k]
        assert p['postflop_bets'] == 2
        assert p['postflop_checks'] == 1

    def test_hands_count_plausible(self):
        """Hand count should match exactly how many hands the villain appeared in."""
        villains = {**_make_villain('frequent', 'BTN'), **_make_villain('rare', 'SB')}
        hands = [_make_hand(hid=f'TM{i}', villains=villains) for i in range(30)]
        # Add 10 more hands where only 'frequent' appears
        hands += [_make_hand(hid=f'TM{30+i}', villains=_make_villain('frequent', 'CO'))
                  for i in range(10)]
        profiles = profile_opponents(hands, hero_name='Hero')
        freq_k = [k for k in profiles if 'frequent' in k][0]
        rare_k = [k for k in profiles if 'rare' in k][0]
        assert profiles[freq_k]['hands_seen'] == 40
        assert profiles[rare_k]['hands_seen'] == 30


# ============================================================
# C. Regression — tag_hands and misplays still work
# ============================================================

class TestRegression:

    def test_tag_hands_uses_new_keys(self):
        """tag_hands_with_archetypes should set primary_villain_hash to tid|player."""
        # Build enough hands for classification (15+)
        hands = [_make_hand(hid=f'TM{i}',
                            villains=_make_villain('aggro_player', 'BTN'),
                            action_ledger=[_pf_action('aggro_player', 'raises')],
                            opener_position='BTN',
                            pf_raise_count=1)
                 for i in range(20)]
        profiles = profile_opponents(hands, hero_name='Hero')
        tag_hands_with_archetypes(hands, profiles)
        # Check that primary_villain_hash uses the new key format
        tagged = [h for h in hands if h.get('primary_villain_hash')]
        assert len(tagged) > 0, "No hands were tagged"
        for h in tagged:
            pvh = h['primary_villain_hash']
            assert '|aggro_player' in pvh, f"Expected tid|player_hash format, got: {pvh}"
            parts = pvh.split('|', 1)
            assert parts[1] not in {'BTN', 'SB', 'BB', 'CO', 'HJ', 'MP'}, \
                f"primary_villain_hash uses position label: {pvh}"

    def test_misplays_still_return(self):
        """find_misplays_vs_archetype should still work after re-keying."""
        # Build 20 hands of a calling station
        hands = []
        for i in range(20):
            ledger = [_pf_action('station', 'calls')]
            postflop = [
                {'street': 'flop', 'player': 'station', 'position': 'CO',
                 'action': 'calls', 'amount_bb': 3, 'is_all_in': False},
                {'street': 'turn', 'player': 'station', 'position': 'CO',
                 'action': 'calls', 'amount_bb': 6, 'is_all_in': False},
            ]
            hands.append(_make_hand(
                hid=f'TM{i}', villains=_make_villain('station', 'CO'),
                action_ledger=ledger + postflop, went_to_sd=True))
        profiles = profile_opponents(hands, hero_name='Hero')
        tag_hands_with_archetypes(hands, profiles)
        misplays = find_misplays_vs_archetype(hands, profiles)
        # We don't require specific misplays, just that the function doesn't crash
        assert isinstance(misplays, list)


# ============================================================
# D. QA Summary (run manually with -s flag)
# ============================================================

def test_qa_summary_synthetic():
    """Print QA summary from synthetic data to verify format."""
    hands = []
    # Build diverse villain pool
    villains_spec = [
        ('tight_raiser', 15, 'raises', None),
        ('loose_caller', 25, 'calls', None),
        ('mixed_player', 20, None, None),  # alternates
    ]
    for vname, n, action, _ in villains_spec:
        for i in range(n):
            if action:
                ledger = [_pf_action(vname, action)]
            elif i % 3 == 0:
                ledger = [_pf_action(vname, 'raises')]
            elif i % 3 == 1:
                ledger = [_pf_action(vname, 'calls')]
            else:
                ledger = []  # folded pre
            hands.append(_make_hand(
                hid=f'TM_{vname}_{i}',
                villains=_make_villain(vname, 'BTN'),
                action_ledger=ledger,
                opener_position='BTN' if ledger and ledger[0]['action'] == 'raises' else '',
                went_to_sd=(i % 4 == 0)))

    profiles = profile_opponents(hands, hero_name='Hero')

    # Print summary
    print("\n" + "=" * 60)
    print("BUG-B FIX QA SUMMARY (synthetic)")
    print("=" * 60)
    print(f"  Profiles: {len(profiles)}")
    unique_keys = set(profiles.keys())
    print(f"  Unique keys: {len(unique_keys)}")

    # VPIP/PFR distribution
    vpip_eq_pfr = 0
    vpip_gt_pfr = 0
    pfr_gt_vpip = 0
    for k, v in profiles.items():
        vpip = v.get('vpip', 0)
        pfr = v.get('pfr', 0)
        if vpip == pfr:
            vpip_eq_pfr += 1
        elif vpip > pfr:
            vpip_gt_pfr += 1
        else:
            pfr_gt_vpip += 1

    print(f"  VPIP == PFR: {vpip_eq_pfr}")
    print(f"  VPIP > PFR:  {vpip_gt_pfr}")
    print(f"  PFR > VPIP:  {pfr_gt_vpip} (should be 0)")

    # Top profiles
    top = sorted(profiles.items(), key=lambda kv: -kv[1]['hands_seen'])[:10]
    print(f"\n  Top {len(top)} profiles by hands:")
    print(f"  {'Key':<30} {'Hands':>6} {'Positions':<15} {'VPIP':>5} {'PFR':>5} {'AF':>5} {'Arch':<15}")
    for k, v in top:
        pos = ','.join(sorted(v.get('positions_seen', set())))
        vpip_pct = v.get('vpip_pct', 0)
        pfr_pct = v.get('pfr_pct', 0)
        af = v.get('af', 0)
        arch = v.get('archetype', '?')
        print(f"  {k:<30} {v['hands_seen']:>6} {pos:<15} {vpip_pct:>5.1f} {pfr_pct:>5.1f} {af:>5.1f} {arch:<15}")

    # Verify no position-keyed profiles
    pos_labels = {'BTN', 'SB', 'BB', 'CO', 'HJ', 'MP', 'UTG', 'UTG+1', 'LJ', 'UNK', '?'}
    bad_keys = [k for k in profiles if k.split('|', 1)[-1] in pos_labels]
    assert not bad_keys, f"Position-keyed profiles found: {bad_keys}"
    assert pfr_gt_vpip == 0, f"PFR > VPIP found in {pfr_gt_vpip} profiles"
    print("\n  [PASS] All checks passed")
