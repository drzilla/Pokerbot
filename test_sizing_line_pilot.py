"""v8.21 AGGREGATE-ONLY closeout — tests for the recalibrated flop c-bet sizing signal.

The per-hand sizing family is REMOVED from the analyst queue; the safe assessment now feeds only the
aggregate coaching-leak summary. Covers: applicability gates, deviation classification, the aggregate
rollup, removal from run_value / build_packet, and the no-mandatory-review / no-confirmed-label contract.

Run:  PYTHONUTF8=1 python test_sizing_line_pilot.py    (standalone PASS/FAIL; exit 1 on any failure)
"""
import gem_parser
import gem_textures
import gem_sizing_detector as SD
import gem_discovery_context as DC
import gem_analyst_packet as AP

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print('  PASS', label)
    else:
        _failed += 1
        print('  FAIL', label)


def mk(pfr=True, sizing=None, arch='ace_high_dry', ip=True, eff=100.0, board=('Ah', '7d', '2c'),
       pot_type='SRP', multiway=False, players_at_flop=2, allin=False):
    hb = [['flop', sizing, 'cbet', 'IP' if ip else 'OOP']] if sizing is not None else []
    led = [{'street': 'flop', 'player': 'Hero', 'action': 'bets', 'is_all_in': allin}] if sizing is not None else []
    return {'pfr': pfr, 'hero_bets': hb, 'board': list(board), 'board_archetype': arch, 'hero_ip': ip,
            'eff_stack_bb': eff, 'pot_type': pot_type, 'multiway_flop': multiway,
            'players_at_flop': players_at_flop, 'action_ledger': led}


_HH = """Poker Hand #%(hid)s: Tournament #888888, SRP Test Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01
Table '1' 8-max Seat #1 is the button
Seat 1: Hero (25000 in chips)
Seat 2: Villain1 (25000 in chips)
Seat 3: Villain2 (25000 in chips)
Villain1: posts small blind 125
Villain2: posts big blind 250
*** HOLE CARDS ***
Dealt to Hero [%(hole)s]
Hero: raises 375 to 625
Villain1: folds
Villain2: calls 375
*** FLOP *** [%(flop)s]
Villain2: checks
Hero: bets %(bet)d
Villain2: folds
Uncalled bet (%(bet)d) returned to Hero
Hero collected 1250 from pot
*** SUMMARY ***
Total pot 1250 | Rake 0
Board [%(flop)s]
Seat 1: Hero (button) collected (1250)"""


def srp_hand(hid, bet, hole='Ah Kd', flop='As 7d 2c'):
    return gem_parser.parse_one_hand(_HH % {'hid': hid, 'hole': hole, 'flop': flop, 'bet': bet}, 'GG - Test.txt')


# ─────────────────────── 1. applicability + deviation gates ───────────────────────
print('[1] applicability gates (applicable_band / assess)')
check('valid SRP HU hand is an opportunity', SD.applicable_band(mk(sizing=75)) is not None)
check('3-bet pot -> not an opportunity', SD.applicable_band(mk(sizing=75, pot_type='3BP')) is None)
check('4-bet pot -> not an opportunity', SD.applicable_band(mk(sizing=75, pot_type='4BP')) is None)
check('multiway -> not an opportunity', SD.applicable_band(mk(sizing=75, multiway=True)) is None)
check('3 players at flop -> not an opportunity', SD.applicable_band(mk(sizing=75, players_at_flop=3)) is None)
check('all-in c-bet -> not an opportunity', SD.applicable_band(mk(sizing=75, allin=True)) is None)
check('not PFR -> not an opportunity', SD.applicable_band(mk(pfr=False, sizing=75)) is None)
check('no flop c-bet -> not an opportunity', SD.applicable_band(mk(sizing=None)) is None)
check('board < 3 -> not an opportunity', SD.applicable_band(mk(sizing=75, board=('Ah', '7d'))) is None)

print('[1b] deviation classification (assess)')
check('gross over (80% vs [25])', (SD.assess_flop_cbet_sizing(mk(sizing=80)) or {}).get('severity') == 'gross')
check('gross under (10% vs [50,66])',
      (SD.assess_flop_cbet_sizing(mk(sizing=10, arch='low_connected', board=('6h', '5d', '4c'))) or {}).get('severity') == 'gross')
check('moderate (40% vs [25])', (SD.assess_flop_cbet_sizing(mk(sizing=40)) or {}).get('severity') == 'moderate')
check('dual band never gross (300% vs [33,85,100])',
      (SD.assess_flop_cbet_sizing(mk(sizing=300, arch='broadway_disconnected', board=('Kd', '9s', '4h'))) or {}).get('severity') == 'moderate')
check('within tolerance -> None', SD.assess_flop_cbet_sizing(mk(sizing=30)) is None)
check('within multi-size spread (75% in [50,100]) -> None',
      SD.assess_flop_cbet_sizing(mk(sizing=75, arch='ace_high_coordinated', board=('Ah', 'Kd', '9s'))) is None)
_om = gem_textures.archetype_meta
gem_textures.archetype_meta = lambda aid: {'confidence': 'partial'}
try:
    check('incomplete chart -> None', SD.applicable_band(mk(sizing=75)) is None)
finally:
    gem_textures.archetype_meta = _om

# ─────────────────────── 2. aggregate summary ───────────────────────
print('[2] aggregate summary')
hands = []
for i in range(6):                                    # 6 gross over-sized ace_high_dry IP c-bets
    hands.append(srp_hand('TM700000%02d' % i, 1030))
for i in range(2):                                    # 2 compliant (~30%) ace_high_dry IP c-bets
    hands.append(srp_hand('TM710000%02d' % i, 412))
hands.append(srp_hand('TM72000001', 1030))            # would be off-band but...
hands[-1]['pot_type'] = '3BP'                         # ...3BP -> excluded from opportunities
s = SD.summarize_offband_sizing(hands)
check('opportunities exclude the 3BP hand (8 not 9)', s['opportunities'] == 8)
check('off_band counts the 6 over-sized', s['off_band'] == 6)
check('over_sized = 6, under_sized = 0', s['over_sized'] == 6 and s['under_sized'] == 0)
check('off_band_rate = 0.75', s['off_band_rate'] == 0.75)
check('by_side[ip] present and counted', s['by_side'].get('ip', {}).get('off') == 6)
check('one actionable leak signal', len(s['leak_signals']) == 1)
L = s['leak_signals'][0] if s['leak_signals'] else {}
check('leak signal is ace_high_dry IP over-sizing',
      L.get('archetype') == 'ace_high_dry' and L.get('side') == 'ip' and L.get('dominant_direction') == 'over')
check('leak signal carries representative EXAMPLE hands', len(L.get('representative_hands', [])) >= 1)
check('zero mandatory analyst reviews', s['creates_mandatory_analyst_reviews'] == 0)
check('labels no confirmed mistakes', s['labels_confirmed_mistakes'] is False)
check('uses no results/equity', s['uses_results_or_equity'] is False)
import json as _json
check('summary carries no result/leak keys',
      not any(k in _json.dumps(s) for k in ('net_bb', 'went_to_sd', 'showdown', '"won"')))

# ─────────────────────── 3. removed from the per-hand analyst pipeline ───────────────────────
print('[3] removed from per-hand required/optional review')
val = DC.run_value(hands, {})
check('run_value emits ZERO flop_cbet_sizing candidates',
      not any(c['family'] == 'flop_cbet_sizing' for c in val['candidates']))
check('flop_cbet_sizing absent from by_family', 'flop_cbet_sizing' not in val['metrics']['by_family'])
rd = {'final_truth': {'records': {}}, 'material_loss_population': {}, '_candidate_need_ids': []}
pkt = AP.build_packet(hands, rd, session_id='closeout', optional_cap=8)
allrecs = pkt['required'] + pkt['optional']
check('packet has ZERO sizing decisions',
      not any(d.get('family') == 'flop_cbet_sizing' for d in allrecs))
check('packet evidence has no sizing chart excerpt', 'chart.flop_cbet_sizing_band' not in pkt['evidence'])

# ─────────────────────── 4. fully reverted pipeline state ───────────────────────
print('[4] discovery + packet pipeline unchanged from baseline')
check('no family_flop_cbet_sizing in discovery module', not hasattr(DC, 'family_flop_cbet_sizing'))
check('EVIDENCE has no flop_cbet_sizing key', 'chart.flop_cbet_sizing_band' not in AP.EVIDENCE)

print('\nRESULTS: %d passed, %d failed, %d total' % (_passed, _failed, _passed + _failed))
if _failed:
    raise SystemExit(1)
print('ALL AGGREGATE-ONLY CLOSEOUT TESTS PASSED')
