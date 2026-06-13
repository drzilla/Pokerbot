#!/usr/bin/env python3
"""
test_coinpoker.py — Regression tests for CoinPoker XML → GG-text conversion
and isolation-mode hero-name threading.

Covers the three bugs from the Dave/DCB1316 session (2026-05-30):
  1. WSD=100% — transformer mis-emitting "showed" for uncontested wins
  2. Hero-name threading — _parse_hand_seat_info defaulted hero='Hero'
  3. Villain showdown cards — hero mis-tagged as villain

Run: python3 -m pytest test_coinpoker.py -v
"""
import sys, os, re, unittest

HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
sys.path.insert(0, HERE)

import coinpoker_to_gg as cp

# ============================================================
# Minimal CoinPoker XML fixtures
# ============================================================

_XML_UNCONTESTED_WIN = """<?xml version="1.0" encoding="utf-8"?>
<HandHistory>
  <DateOfHandUtc>2026-05-30T02:27:25.124Z</DateOfHandUtc>
  <HandId>9900000001</HandId>
  <DealerButtonPosition>1</DealerButtonPosition>
  <TableName>Test Table</TableName>
  <HeroName>DCB1316</HeroName>
  <GameDescription>
    <PokerFormat>CashGame</PokerFormat><Site>CoinPoker</Site>
    <GameType>NoLimitHoldem</GameType>
    <Limit><SmallBlind>400</SmallBlind><BigBlind>800</BigBlind>
           <IsAnteTable>true</IsAnteTable><Ante>100</Ante></Limit>
    <SeatType MaxPlayers="6" />
    <TableType>Regular</TableType>
    <Tournament><TournamentId>99001</TournamentId>
      <TournamentName>Test Tourney</TournamentName>
      <BuyIn><PrizePoolValue>10</PrizePoolValue><Rake>1</Rake>
             <IsKnockout>false</IsKnockout><KnockoutValue>0</KnockoutValue></BuyIn>
      <Bounty>0</Bounty></Tournament>
  </GameDescription>
  <Players>
    <Player PlayerName="DCB1316" StartingStack="20000" SeatNumber="1" Cards="AhKd" />
    <Player PlayerName="villain1" StartingStack="15000" SeatNumber="3" Cards="" />
    <Player PlayerName="villain2" StartingStack="18000" SeatNumber="5" Cards="" />
  </Players>
  <CommunityCards></CommunityCards>
  <TotalPot>2200</TotalPot>
  <Actions>
    <HandAction PlayerName="DCB1316" HandActionType="ANTE" Amount="-100" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="ANTE" Amount="-100" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain2" HandActionType="ANTE" Amount="-100" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="SMALL_BLIND" Amount="-400" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain2" HandActionType="BIG_BLIND" Amount="-800" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="DCB1316" HandActionType="RAISE" Amount="-2000" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="FOLD" Amount="0" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain2" HandActionType="FOLD" Amount="0" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="DCB1316" HandActionType="UNCALLED_BET" Amount="1200" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="DCB1316" HandActionType="WINS" Amount="2200" Street="Summary" IsAllIn="false" />
  </Actions>
</HandHistory>"""

_XML_SHOWDOWN_HERO_LOSES = """<?xml version="1.0" encoding="utf-8"?>
<HandHistory>
  <DateOfHandUtc>2026-05-30T03:00:00.000Z</DateOfHandUtc>
  <HandId>9900000002</HandId>
  <DealerButtonPosition>1</DealerButtonPosition>
  <TableName>Test Table 2</TableName>
  <HeroName>DCB1316</HeroName>
  <GameDescription>
    <PokerFormat>CashGame</PokerFormat><Site>CoinPoker</Site>
    <GameType>NoLimitHoldem</GameType>
    <Limit><SmallBlind>200</SmallBlind><BigBlind>400</BigBlind>
           <IsAnteTable>true</IsAnteTable><Ante>50</Ante></Limit>
    <SeatType MaxPlayers="6" />
    <TableType>Regular</TableType>
    <Tournament><TournamentId>99002</TournamentId>
      <TournamentName>Test PKO Bounty</TournamentName>
      <BuyIn><PrizePoolValue>10</PrizePoolValue><Rake>1</Rake>
             <IsKnockout>false</IsKnockout><KnockoutValue>0</KnockoutValue></BuyIn>
      <Bounty>0</Bounty></Tournament>
  </GameDescription>
  <Players>
    <Player PlayerName="DCB1316" StartingStack="10000" SeatNumber="1" Cards="QhQd" />
    <Player PlayerName="villain1" StartingStack="12000" SeatNumber="4" Cards="AhAd" />
  </Players>
  <CommunityCards>7s3c2dKh9s</CommunityCards>
  <TotalPot>20200</TotalPot>
  <Actions>
    <HandAction PlayerName="DCB1316" HandActionType="ANTE" Amount="-50" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="ANTE" Amount="-50" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="DCB1316" HandActionType="SMALL_BLIND" Amount="-200" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="BIG_BLIND" Amount="-400" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="DCB1316" HandActionType="RAISE" Amount="-1000" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="RAISE" Amount="-3000" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="DCB1316" HandActionType="CALL" Amount="2000" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="BET" Amount="5000" Street="Flop" IsAllIn="false" />
    <HandAction PlayerName="DCB1316" HandActionType="CALL" Amount="5000" Street="Flop" IsAllIn="true" />
    <HandAction PlayerName="villain1" HandActionType="UNCALLED_BET" Amount="2000" Street="Flop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="WINS" Amount="20200" Street="Summary" IsAllIn="false" />
  </Actions>
</HandHistory>"""

_XML_HERO_FOLDS_VILLAINS_SHOW = """<?xml version="1.0" encoding="utf-8"?>
<HandHistory>
  <DateOfHandUtc>2026-05-30T03:30:00.000Z</DateOfHandUtc>
  <HandId>9900000003</HandId>
  <DealerButtonPosition>2</DealerButtonPosition>
  <TableName>Test Table 3</TableName>
  <HeroName>DCB1316</HeroName>
  <GameDescription>
    <PokerFormat>CashGame</PokerFormat><Site>CoinPoker</Site>
    <GameType>NoLimitHoldem</GameType>
    <Limit><SmallBlind>100</SmallBlind><BigBlind>200</BigBlind>
           <IsAnteTable>false</IsAnteTable><Ante>0</Ante></Limit>
    <SeatType MaxPlayers="6" />
    <TableType>Regular</TableType>
    <Tournament><TournamentId>99003</TournamentId>
      <TournamentName>Test Collision PKO</TournamentName>
      <BuyIn><PrizePoolValue>10</PrizePoolValue><Rake>1</Rake>
             <IsKnockout>false</IsKnockout><KnockoutValue>0</KnockoutValue></BuyIn>
      <Bounty>0</Bounty></Tournament>
  </GameDescription>
  <Players>
    <Player PlayerName="DCB1316" StartingStack="8000" SeatNumber="1" Cards="5h3d" />
    <Player PlayerName="villain1" StartingStack="10000" SeatNumber="2" Cards="AhKd" />
    <Player PlayerName="villain2" StartingStack="9000" SeatNumber="4" Cards="QhQd" />
  </Players>
  <CommunityCards>Ts7c2dAh9s</CommunityCards>
  <TotalPot>18200</TotalPot>
  <Actions>
    <HandAction PlayerName="villain1" HandActionType="SMALL_BLIND" Amount="-100" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="DCB1316" HandActionType="BIG_BLIND" Amount="-200" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain2" HandActionType="RAISE" Amount="-600" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="CALL" Amount="500" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="DCB1316" HandActionType="FOLD" Amount="0" Street="Preflop" IsAllIn="false" />
    <HandAction PlayerName="villain1" HandActionType="RAISE" Amount="-9000" Street="Flop" IsAllIn="true" />
    <HandAction PlayerName="villain2" HandActionType="CALL" Amount="8400" Street="Flop" IsAllIn="true" />
    <HandAction PlayerName="villain1" HandActionType="WINS" Amount="18200" Street="Summary" IsAllIn="false" />
  </Actions>
</HandHistory>"""


class TestCoinPokerConverter(unittest.TestCase):

    def test_uncontested_win_no_showdown(self):
        """Uncontested preflop win → no SHOWDOWN marker, hero 'collected' not 'showed'."""
        gg = cp.transform_hand(_XML_UNCONTESTED_WIN)
        self.assertNotIn('*** SHOWDOWN ***', gg,
            "Uncontested win must NOT have a SHOWDOWN section")
        self.assertNotIn('showed', gg.lower(),
            "Uncontested win must not contain 'showed' (WSD bug)")
        self.assertIn('collected', gg,
            "Winner must have 'collected' line")

    def test_showdown_hero_loses(self):
        """Hero loses all-in showdown → hero 'showed and lost', villain 'showed and won'."""
        gg = cp.transform_hand(_XML_SHOWDOWN_HERO_LOSES)
        self.assertIn('*** SHOWDOWN ***', gg)
        self.assertIn('DCB1316', gg)
        # Hero showed and lost
        self.assertRegex(gg, r'DCB1316 showed \[Qh Qd\] and lost')
        # Villain showed and won
        self.assertRegex(gg, r'villain1 showed \[Ah Ad\] and won')

    def test_hero_folds_villains_show(self):
        """Hero folds, two villains show → hero 'folded', villains 'showed'."""
        gg = cp.transform_hand(_XML_HERO_FOLDS_VILLAINS_SHOW)
        self.assertIn('*** SHOWDOWN ***', gg)
        # Hero folded — must NOT show
        self.assertNotIn('DCB1316 showed', gg,
            "Hero who folded must not appear as 'showed'")
        self.assertIn('DCB1316 folded', gg)
        # Both villains showed
        self.assertIn('villain1 showed', gg)
        self.assertIn('villain2 showed', gg)

    def test_raise_amount_conversion(self):
        """RAISE total → 'raises <inc> to <total>' in GG format."""
        gg = cp.transform_hand(_XML_UNCONTESTED_WIN)
        # Hero raises to 2000 from SB position (committed 0 before RAISE)
        self.assertIn('raises', gg)
        self.assertIn('to 2000', gg)

    def test_bounty_by_name(self):
        """Tournament named 'Collision PKO' → tagged Bounty even if IsKnockout=false."""
        gg = cp.transform_hand(_XML_HERO_FOLDS_VILLAINS_SHOW)
        # "Collision" is in the PKO keyword list
        self.assertIn('Bounty', gg,
            "Collision PKO tournament must be tagged Bounty by name")

    def test_non_bounty_no_tag(self):
        """Regular tournament → no Bounty tag."""
        gg = cp.transform_hand(_XML_UNCONTESTED_WIN)
        self.assertNotIn('Bounty', gg,
            "Non-bounty tournament must not have Bounty tag")

    def test_hand_id_starts_with_tm(self):
        """Hand ID must start with TM for gem_parser to accept it."""
        gg = cp.transform_hand(_XML_UNCONTESTED_WIN)
        self.assertIn('Poker Hand #TM', gg)

    def test_dealt_to_hero(self):
        """Hero cards must appear in 'Dealt to' line."""
        gg = cp.transform_hand(_XML_UNCONTESTED_WIN)
        self.assertIn('Dealt to DCB1316 [Ah Kd]', gg)


class TestHeroNameThreading(unittest.TestCase):
    """Test the §4.1 self-healing hero detection in _parse_hand_seat_info."""

    def test_auto_derive_hero_from_hh(self):
        """With hero_name=None, derive hero from 'Dealt to' line."""
        from gem_report_data import _parse_hand_seat_info
        # Build a minimal GG-text HH with a non-standard hero name
        hh = ("Poker Hand #TM99: Tournament #1, Test Hold'em No Limit "
              "- Level1(100/200(25)) - 2026/05/30 00:00:00\n"
              "Table '1' 6-max Seat #1 is the button\n"
              "Seat 1: DCB1316 (10000 in chips)\n"
              "Seat 3: villain1 (12000 in chips)\n"
              "DCB1316: posts the ante 25\n"
              "villain1: posts the ante 25\n"
              "villain1: posts big blind 200\n"
              "*** HOLE CARDS ***\n"
              "Dealt to DCB1316 [Qh Qd]\n"
              "DCB1316: raises 300 to 500\n"
              "villain1: calls 300\n"
              "*** FLOP *** [7s 3c 2d]\n"
              "*** SUMMARY ***\n"
              "Total pot 1050 | Rake 0\n"
              "Board [7s 3c 2d]\n")
        result = _parse_hand_seat_info(hh, hero_name=None)
        # Find the hero seat
        hero_seats = [s for s in result['seats'] if s.get('is_hero')]
        assert hero_seats, "Must identify DCB1316 as hero via Dealt-to detection"
        assert hero_seats[0]['name'] == 'DCB1316'

    def test_explicit_hero_name_works(self):
        """Passing hero_name='DCB1316' explicitly also works."""
        from gem_report_data import _parse_hand_seat_info
        hh = ("Poker Hand #TM99: Tournament #1, Test Hold'em No Limit "
              "- Level1(100/200(25)) - 2026/05/30 00:00:00\n"
              "Table '1' 6-max Seat #1 is the button\n"
              "Seat 1: DCB1316 (10000 in chips)\n"
              "Seat 3: villain1 (12000 in chips)\n"
              "DCB1316: posts the ante 25\n"
              "villain1: posts the ante 25\n"
              "villain1: posts big blind 200\n"
              "*** HOLE CARDS ***\n"
              "Dealt to DCB1316 [Qh Qd]\n"
              "*** SUMMARY ***\n"
              "Total pot 500 | Rake 0\n")
        result = _parse_hand_seat_info(hh, hero_name='DCB1316')
        hero_seats = [s for s in result['seats'] if s.get('is_hero')]
        assert hero_seats, "Must identify DCB1316 as hero via explicit name"

    def test_default_hero_for_gg(self):
        """Standard GG hands with hero_name=None → derives 'Hero' from Dealt-to."""
        from gem_report_data import _parse_hand_seat_info
        hh = ("Poker Hand #TM99: Tournament #1, Test Hold'em No Limit "
              "- Level1(100/200(25)) - 2026/05/30 00:00:00\n"
              "Table '1' 6-max Seat #1 is the button\n"
              "Seat 1: Hero (10000 in chips)\n"
              "Seat 3: villain1 (12000 in chips)\n"
              "Hero: posts the ante 25\n"
              "villain1: posts the ante 25\n"
              "villain1: posts big blind 200\n"
              "*** HOLE CARDS ***\n"
              "Dealt to Hero [Ah Kd]\n"
              "*** SUMMARY ***\n"
              "Total pot 500 | Rake 0\n")
        result = _parse_hand_seat_info(hh)  # no hero_name
        hero_seats = [s for s in result['seats'] if s.get('is_hero')]
        assert hero_seats, "GG default path must still work"
        assert hero_seats[0]['name'] == 'Hero'


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
