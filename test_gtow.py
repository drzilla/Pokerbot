#!/usr/bin/env python3
"""
test_gtow.py — Unit tests for gem_gtow v2.0 (validated URL builder).

Covers: snap_depth, encode_preflop_actions, encode_board,
        _build_url, build_gtow_schema, build_manifest,
        _get_open_rcode, _get_3bet_rcode, _tier_lookup.
"""

import unittest
from gem_gtow import (
    snap_depth, encode_preflop_actions, encode_board,
    _build_url, build_gtow_schema, build_manifest,
    _get_open_rcode, _get_3bet_rcode, _tier_lookup,
    _pick_stacks, _match_stacks, _variance, _load_stacks_lookup,
    _OPEN_RAISE, _OPEN_TIERS, CHIPEV_GAMETYPES,
    _DEPTH_GRID_8M, _DEPTH_GRIDS,
)


# ============================================================================
# FIXTURES
# ============================================================================

def _make_hand(table_size=8, stack_bb=50, board=None, pf_sequence=None,
               position='BTN', players_at_flop=0, eff_stack_bb=None):
    """Minimal hand record for GTOW testing."""
    return {
        'id': 'TM1234567890123456',
        'table_size': table_size,
        'stack_bb': stack_bb,
        'eff_stack_bb': eff_stack_bb or stack_bb,
        'board': board or [],
        'cards': ['Ac', 'Kc'],
        'position': position,
        'pf_sequence': pf_sequence or [],
        'players_at_flop': players_at_flop,
    }


def _std_pf_sequence_8max():
    """8-max, UTG opens, everyone folds, BB calls."""
    return [
        'UTG(H):raises',
        'UTG+1:folds',
        'MP:folds',
        'HJ:folds',
        'CO:folds',
        'BTN:folds',
        'SB:folds',
        'BB:calls',
    ]


def _std_pf_btn_open_6max():
    """6-max, folds to BTN, BTN opens, SB folds, BB calls."""
    return [
        'UTG:folds',
        'MP:folds',
        'CO:folds',
        'BTN(H):raises',
        'SB:folds',
        'BB:calls',
    ]


# ============================================================================
# TESTS
# ============================================================================

class TestSnapDepth(unittest.TestCase):

    def test_exact_match(self):
        self.assertEqual(snap_depth(50), 50)

    def test_snap_to_nearest(self):
        # 52 is closer to 51 than 54 in the grid
        self.assertEqual(snap_depth(52), 51)

    def test_minimum(self):
        self.assertEqual(snap_depth(0.5), 1)

    def test_maximum(self):
        self.assertEqual(snap_depth(300), 206)

    def test_custom_grid(self):
        self.assertEqual(snap_depth(37, [10, 20, 40, 80]), 40)

    def test_empty_grid_fallback(self):
        self.assertEqual(snap_depth(25.3, []), 25)

    def test_gametype_selects_correct_grid(self):
        """snap_depth with gametype= uses that gametype's grid, not 8m."""
        # 3-max grid has no depth 1 — min is 6. With 8m grid, depth 1 exists.
        self.assertEqual(snap_depth(1, gametype='MTTGeneral_3m'), 6)
        # 8m grid has 206 as max; 9m (MTTGeneralV2) max is 200
        self.assertEqual(snap_depth(300, gametype='MTTGeneralV2'), 200)
        # 7m grid max is 65, 8m grid max is 206
        self.assertEqual(snap_depth(100, gametype='MTTGeneral_7m'), 65)

    def test_gametype_fallback_to_8m(self):
        """Unknown gametype falls back to _DEPTH_GRID_8M."""
        self.assertEqual(snap_depth(206, gametype='MTTUnknown'), 206)

    def test_depth_grids_cover_all_chipev_gametypes(self):
        """Every CHIPEV_GAMETYPES value has a matching _DEPTH_GRIDS entry."""
        for ts, gt in CHIPEV_GAMETYPES.items():
            self.assertIn(gt, _DEPTH_GRIDS,
                          msg=f'table_size={ts} gametype={gt} missing from _DEPTH_GRIDS')

    def test_depth_grids_sorted(self):
        """All depth grids are sorted ascending (snap_depth assumes this)."""
        for gt, grid in _DEPTH_GRIDS.items():
            self.assertEqual(grid, sorted(grid), msg=f'{gt} grid not sorted')

    def test_build_schema_snaps_to_correct_grid(self):
        """build_gtow_schema for a 3-max hand snaps to 3m grid."""
        hand = _make_hand(
            table_size=3, stack_bb=1,
            pf_sequence=['BTN(H):raises', 'SB:folds', 'BB:calls'],
            board=['Ah', '7d', '2s'],
            players_at_flop=2,
        )
        schema = build_gtow_schema(hand)
        # 3m grid min depth is 6 — stack=1 should snap to 6, not 1
        if schema['url']:
            self.assertIn('depth=6.125', schema['url'],
                          msg='3-max hand should snap to 3m grid (min=6)')


class TestGetOpenRcode(unittest.TestCase):

    def test_utg_at_50bb(self):
        self.assertEqual(_get_open_rcode('UTG', 50), 'R2')

    def test_btn_at_60bb(self):
        self.assertEqual(_get_open_rcode('BTN', 60), 'R2.2')

    def test_sb_at_25bb(self):
        self.assertEqual(_get_open_rcode('SB', 25), 'R3')

    def test_utg_at_100bb(self):
        self.assertEqual(_get_open_rcode('UTG', 100), 'R2.1')

    def test_unknown_position(self):
        # 'UTG2' not in 8-max open raise table → None
        self.assertIsNone(_get_open_rcode('UTG2', 50))


class TestGet3betRcode(unittest.TestCase):

    def test_btn_at_25bb(self):
        self.assertEqual(_get_3bet_rcode('BTN', 25), 'R5')

    def test_bb_at_30bb(self):
        self.assertEqual(_get_3bet_rcode('BB', 30), 'R7.5')

    def test_sb_at_20bb(self):
        self.assertEqual(_get_3bet_rcode('SB', 20), 'R5')


class TestTierLookup(unittest.TestCase):

    def test_exact_tier(self):
        result = _tier_lookup(_OPEN_RAISE, _OPEN_TIERS, 50)
        self.assertIn('UTG', result)
        self.assertEqual(result['UTG'], 'R2')

    def test_between_tiers(self):
        # 55 → uses tier 50 (nearest lower)
        result = _tier_lookup(_OPEN_RAISE, _OPEN_TIERS, 55)
        self.assertEqual(result['UTG'], 'R2')

    def test_below_minimum(self):
        # Below 15 → uses 15
        result = _tier_lookup(_OPEN_RAISE, _OPEN_TIERS, 10)
        self.assertIn('UTG', result)


class TestEncodePreflopActions(unittest.TestCase):

    def test_8max_utg_open_bb_call(self):
        pf = _std_pf_sequence_8max()
        tokens, hero_idx, ok = encode_preflop_actions(pf, 8, 50)
        # UTG opens R2, then 5 folds, then BB calls
        self.assertEqual(tokens, 'R2-F-F-F-F-F-F-C')
        self.assertEqual(hero_idx, 0)  # UTG is first
        self.assertTrue(ok)

    def test_6max_btn_open(self):
        pf = _std_pf_btn_open_6max()
        tokens, hero_idx, ok = encode_preflop_actions(pf, 6, 50)
        # 3 folds, BTN opens R2, SB folds, BB calls
        self.assertEqual(tokens, 'F-F-F-R2-F-C')
        self.assertEqual(hero_idx, 3)
        self.assertTrue(ok)

    def test_3bet_sequence(self):
        pf = [
            'UTG:raises',     # open
            'UTG+1:folds',
            'MP:folds',
            'HJ:raises',      # 3bet
            'CO:folds',
            'BTN(H):folds',
            'SB:folds',
            'BB:folds',
        ]
        tokens, hero_idx, ok = encode_preflop_actions(pf, 8, 50)
        # UTG R2, F, F, HJ R6 (3bet code at 50bb), F, F, F, F
        self.assertTrue(ok)
        parts = tokens.split('-')
        self.assertEqual(parts[0], 'R2')   # open
        self.assertEqual(parts[1], 'F')
        self.assertEqual(parts[2], 'F')
        # 3bet by HJ at 50bb
        hj_3bet = _get_3bet_rcode('HJ', 50)
        self.assertEqual(parts[3], hj_3bet)

    def test_4bet_becomes_rai(self):
        pf = [
            'UTG:raises',     # open (1st raise)
            'HJ:raises',      # 3bet (2nd raise)
            'UTG(H):raises',  # 4bet (3rd raise → RAI)
            'HJ:calls',
        ]
        tokens, hero_idx, ok = encode_preflop_actions(pf, 8, 50)
        self.assertTrue(ok)
        parts = tokens.split('-')
        self.assertEqual(parts[2], 'RAI')  # 4bet → RAI
        self.assertEqual(hero_idx, 2)      # hero's first action

    def test_empty_sequence(self):
        tokens, hero_idx, ok = encode_preflop_actions([], 8, 50)
        self.assertEqual(tokens, '')
        self.assertEqual(hero_idx, -1)
        self.assertTrue(ok)

    def test_unknown_rcode_fails(self):
        # Use position not in open raise table (table_size triggers pos mapping)
        pf = ['XXX:raises']  # unknown position → R-code lookup returns None
        tokens, hero_idx, ok = encode_preflop_actions(pf, 8, 50)
        self.assertFalse(ok)
        self.assertEqual(tokens, '')


class TestEncodeBoard(unittest.TestCase):

    def test_flop(self):
        self.assertEqual(encode_board(['Ks', '9c', 'Js']), 'Ks9cJs')

    def test_full_board(self):
        self.assertEqual(
            encode_board(['Td', '5h', '2c', '8s', 'Qd']),
            'Td5h2c8sQd')

    def test_empty(self):
        self.assertEqual(encode_board([]), '')
        self.assertEqual(encode_board(None), '')


class TestBuildUrl(unittest.TestCase):

    def test_basic_structure(self):
        url = _build_url('MTTGeneral_8m', 50,
                         preflop_actions='R2-F-F-F-F-F-F-C',
                         board='Ks9cJs',
                         history_spot=8)
        self.assertTrue(url.startswith('https://app.gtowizard.com/solutions?'))
        self.assertIn('gametype=MTTGeneral_8m', url)
        self.assertIn('depth=50.125', url)
        self.assertIn('board=Ks9cJs', url)
        self.assertIn('history_spot=8', url)
        self.assertIn('preflop_actions=R2-F-F-F-F-F-F-C', url)

    def test_root_url(self):
        url = _build_url('MTTGeneral_8m', 50, history_spot=0)
        self.assertNotIn('preflop_actions=', url)
        self.assertNotIn('board=', url)
        self.assertIn('history_spot=0', url)

    def test_125_suffix(self):
        url = _build_url('MTTGeneral_8m', 25)
        self.assertIn('depth=25.125', url)


class TestBuildGtowSchema(unittest.TestCase):

    def test_flop_root_hu(self):
        """HU postflop hand → flop root link (status=ready)."""
        hand = _make_hand(
            table_size=8, stack_bb=50,
            board=['Ks', '9c', 'Js', '3d'],
            pf_sequence=_std_pf_sequence_8max(),
            players_at_flop=2,
        )
        schema = build_gtow_schema(hand)
        self.assertEqual(schema['status'], 'ready')
        self.assertIn('Ks9cJs', schema['url'])  # flop only (3 cards)
        self.assertIn('preflop_actions=', schema['url'])
        self.assertIn('Flop root', schema['spot_summary'])

    def test_preflop_only_hero_decision(self):
        """Preflop-only hand → hero's decision point."""
        pf = [
            'UTG:folds',
            'UTG+1:folds',
            'MP:folds',
            'HJ:folds',
            'CO(H):raises',
            'BTN:folds',
            'SB:folds',
            'BB:folds',
        ]
        hand = _make_hand(
            table_size=8, stack_bb=25,
            pf_sequence=pf,
            players_at_flop=0,
        )
        schema = build_gtow_schema(hand)
        self.assertEqual(schema['status'], 'ready')
        self.assertIsNotNone(schema['url'])
        # Hero is CO, 4 folds before hero → history_spot = 4
        self.assertIn('history_spot=4', schema['url'])
        self.assertIn('Preflop', schema['spot_summary'])

    def test_4way_postflop_falls_back(self):
        """4-way postflop → partial (preflop root fallback)."""
        hand = _make_hand(
            table_size=8, stack_bb=30,
            board=['Ah', '7d', '2s'],
            pf_sequence=_std_pf_sequence_8max(),
            players_at_flop=4,
        )
        schema = build_gtow_schema(hand)
        self.assertEqual(schema['status'], 'partial')
        self.assertIsNotNone(schema['url'])
        self.assertIn('4-way', schema['spot_summary'])

    def test_3way_postflop_ok(self):
        """3-way postflop → ready (GTOW supports up to 3-way)."""
        hand = _make_hand(
            table_size=8, stack_bb=30,
            board=['Ah', '7d', '2s'],
            pf_sequence=_std_pf_sequence_8max(),
            players_at_flop=3,
        )
        schema = build_gtow_schema(hand)
        self.assertEqual(schema['status'], 'ready')

    def test_no_pf_sequence_unavailable(self):
        """No preflop sequence → unavailable."""
        hand = _make_hand(table_size=8, stack_bb=50)
        schema = build_gtow_schema(hand)
        self.assertEqual(schema['status'], 'unavailable')

    def test_bad_table_size_unavailable(self):
        hand = _make_hand(table_size=1)
        schema = build_gtow_schema(hand)
        self.assertEqual(schema['status'], 'unavailable')

    def test_zero_stack_unavailable(self):
        hand = _make_hand(table_size=8, stack_bb=0)
        schema = build_gtow_schema(hand)
        self.assertEqual(schema['status'], 'unavailable')

    def test_gametype_matches_table_size(self):
        for ts, expected_gt in CHIPEV_GAMETYPES.items():
            hand = _make_hand(
                table_size=ts, stack_bb=50,
                board=['Ah', '7d', '2s'],
                pf_sequence=['BTN(H):raises', 'SB:folds', 'BB:calls'],
                players_at_flop=2,
            )
            schema = build_gtow_schema(hand)
            if schema['url']:
                self.assertIn(f'gametype={expected_gt}', schema['url'],
                              msg=f'table_size={ts}')


class TestBuildManifest(unittest.TestCase):

    def test_manifest_columns(self):
        hand = _make_hand(
            table_size=8, stack_bb=50,
            board=['Ks', '9c', 'Js'],
            pf_sequence=_std_pf_sequence_8max(),
            players_at_flop=2,
        )
        rows = build_manifest([(hand, {})])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn('hand_id', row)
        self.assertIn('status', row)
        self.assertIn('url', row)

    def test_manifest_hand_id_short(self):
        hand = _make_hand(
            table_size=8, stack_bb=50,
            pf_sequence=_std_pf_sequence_8max(),
        )
        rows = build_manifest([(hand, {})])
        # 'TM1234567890123456' → last 8 chars
        self.assertEqual(rows[0]['hand_id'], '90123456')


class TestLeadingFoldPadding(unittest.TestCase):
    """v2.1.1: partial pf_sequences pad leading folds so history_spot
    counts all positions. Critical for non-8-max tables."""

    def test_9max_partial_sequence_padded(self):
        """BTN opens in 9-max but sequence only has 3 entries → 6 F prepended."""
        pf = ['BTN(H):raises', 'SB:folds', 'BB:calls']
        tokens, hero_idx, ok = encode_preflop_actions(pf, 9, 42)
        self.assertTrue(ok)
        parts = tokens.split('-')
        # BTN is index 7 in 9-max (UTG,UTG1,UTG2,LJ,HJ,CO,BTN,SB,BB)
        # → 7 leading folds? No, BTN is position 7 (0-indexed)
        # Wait: _GTOW_POS_ORDER[9] = ['UTG','UTG1','UTG2','LJ','HJ','CO','BTN','SB','BB']
        # BTN is at index 6 → 6 leading folds
        self.assertEqual(len(parts), 9, f'expected 9 tokens (6F + R2 + F + C), got {tokens}')
        self.assertEqual(parts[:6], ['F'] * 6)
        self.assertEqual(hero_idx, 6)

    def test_7max_partial_sequence_padded(self):
        """CO opens in 7-max but UTG/LJ/HJ folds missing → 3 F prepended."""
        pf = ['CO(H):raises', 'BTN:folds', 'SB:folds', 'BB:calls']
        tokens, hero_idx, ok = encode_preflop_actions(pf, 7, 50)
        self.assertTrue(ok)
        parts = tokens.split('-')
        # CO is at index 3 in 7-max (UTG,LJ,HJ,CO,BTN,SB,BB) → 3 leading folds
        self.assertEqual(len(parts), 7, f'expected 7 tokens, got {tokens}')
        self.assertEqual(parts[:3], ['F'] * 3)
        self.assertEqual(hero_idx, 3)

    def test_full_sequence_no_padding(self):
        """Full pf_sequence (UTG first) gets no padding."""
        pf = _std_pf_sequence_8max()  # starts with UTG
        tokens, hero_idx, ok = encode_preflop_actions(pf, 8, 50)
        self.assertTrue(ok)
        parts = tokens.split('-')
        # UTG is index 0 → no padding. 8 entries.
        self.assertEqual(len(parts), 8)
        self.assertEqual(hero_idx, 0)  # UTG(H) → first token

    def test_flop_root_uses_padded_history_spot(self):
        """build_gtow_schema with partial 9-max pf → history_spot=9, not 3."""
        hand = _make_hand(
            table_size=9, stack_bb=42,
            board=['Ah', '7d', '2s'],
            pf_sequence=['BTN(H):raises', 'SB:folds', 'BB:calls'],
            players_at_flop=2,
        )
        schema = build_gtow_schema(hand)
        self.assertEqual(schema['status'], 'ready')
        self.assertIn('history_spot=9', schema['url'],
                      msg='9-max flop root should have history_spot=9')


class TestStacksMatching(unittest.TestCase):
    """Tests for stacks lookup and matching."""

    def test_variance_equal_stacks(self):
        self.assertEqual(_variance([50, 50, 50, 50]), 0.0)

    def test_variance_unequal(self):
        v = _variance([10, 20, 30])
        self.assertGreater(v, 0)

    def test_match_stacks_prefers_equal_without_app_details(self):
        """When no app_details, _match_stacks picks lowest-variance row."""
        rows = [
            [50, 30, 70, 40, 60, 20, 80, 10],  # high variance
            [50, 50, 50, 50, 50, 50, 50, 50],    # equal stacks
            [50, 45, 55, 48, 52, 47, 53, 46],    # low variance
        ]
        chosen = _match_stacks(rows, 8, None)
        self.assertEqual(chosen, [50, 50, 50, 50, 50, 50, 50, 50])

    def test_match_stacks_with_seat_data(self):
        """When app_details has seats, picks closest by distance."""
        rows = [
            [50, 50, 50, 50, 50, 50, 50, 50],    # equal
            [50, 30, 70, 20, 80, 40, 60, 10],     # asymmetric A
            [50, 45, 55, 48, 52, 47, 53, 46],     # close to equal
        ]
        # Provide seats matching asymmetric A closely
        app_details = {
            'seats': [
                {'position': 'UTG', 'stack_bb': 50},
                {'position': 'UTG+1', 'stack_bb': 30},
                {'position': 'MP', 'stack_bb': 70},
                {'position': 'HJ', 'stack_bb': 20},
                {'position': 'CO', 'stack_bb': 80},
                {'position': 'BTN', 'stack_bb': 40},
                {'position': 'SB', 'stack_bb': 60},
                {'position': 'BB', 'stack_bb': 10},
            ],
        }
        chosen = _match_stacks(rows, 8, app_details)
        self.assertEqual(chosen, [50, 30, 70, 20, 80, 40, 60, 10])

    def test_pick_stacks_returns_formatted_string(self):
        """_pick_stacks returns 'd.125-d.125-...' format."""
        stacks = _pick_stacks('MTTGeneral_8m', 50, 8)
        if stacks:  # only runs if _gtow_situations.json exists
            self.assertIn('.125', stacks)
            parts = stacks.split('-')
            self.assertEqual(len(parts), 8)  # 8-max = 8 positions

    def test_pick_stacks_none_without_data(self):
        """Returns None for gametype not in lookup."""
        stacks = _pick_stacks('MTTNonexistent', 50, 8)
        self.assertIsNone(stacks)

    def test_build_url_includes_stacks(self):
        """_build_url includes stacks= when provided."""
        url = _build_url('MTTGeneral_8m', 50,
                         stacks='50.125-45.125-55.125-48.125-52.125-47.125-53.125-46.125')
        self.assertIn('stacks=', url)
        self.assertIn('50.125', url)

    def test_build_url_no_stacks(self):
        """_build_url omits stacks= when None."""
        url = _build_url('MTTGeneral_8m', 50)
        self.assertNotIn('stacks=', url)

    def test_build_schema_includes_stacks_when_available(self):
        """build_gtow_schema URL has stacks= when situations file exists."""
        hand = _make_hand(
            table_size=8, stack_bb=50,
            board=['Ks', '9c', 'Js'],
            pf_sequence=_std_pf_sequence_8max(),
            players_at_flop=2,
        )
        schema = build_gtow_schema(hand)
        if schema['url']:
            # If situations file loaded, stacks= present
            lookup = _load_stacks_lookup()
            if lookup.get('MTTGeneral_8m', {}).get(50):
                self.assertIn('stacks=', schema['url'],
                              msg='stacks should be in URL when situations data exists')

    def test_stacks_lookup_loads(self):
        """_load_stacks_lookup loads data if file exists."""
        import os
        lookup = _load_stacks_lookup()
        situations_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '_gtow_situations.json')
        if os.path.exists(situations_path):
            self.assertIn('MTTGeneral_8m', lookup,
                          msg='8m gametype should be in lookup')
            self.assertGreater(len(lookup['MTTGeneral_8m']), 0)
        # else: graceful — empty dict, no error


if __name__ == '__main__':
    unittest.main()
