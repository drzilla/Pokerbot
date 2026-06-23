"""v8.21 pilot — contract + ADVERSARIAL tests for the per-hand flop c-bet SIZING detector (Family A),
post deep-audit corrections (SRP-only / HU-only / non-all-in chart applicability; detector NOMINATES,
analyst owns the terminal verdict).

Run:  PYTHONUTF8=1 python test_sizing_line_pilot.py    (standalone PASS/FAIL; exit 1 on any failure)
"""
import re
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
    """Minimal hand carrying only the canonical fields assess_flop_cbet_sizing consumes."""
    hb = [['flop', sizing, 'cbet', 'IP' if ip else 'OOP']] if sizing is not None else []
    led = []
    if sizing is not None:
        led = [{'street': 'flop', 'player': 'Hero', 'action': 'bets', 'is_all_in': allin}]
    return {'pfr': pfr, 'hero_bets': hb, 'board': list(board), 'board_archetype': arch, 'hero_ip': ip,
            'eff_stack_bb': eff, 'pot_type': pot_type, 'multiway_flop': multiway,
            'players_at_flop': players_at_flop, 'action_ledger': led}


_HH_TMPL = """Poker Hand #%(hid)s: Tournament #888888, SRP Test Hold'em No Limit - Level5(125/250(0)) - 2026/04/07 00:00:01
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
    """A real-ledger HU single-raised-pot IP c-bet hand (flop pot = 1375 chips = 5.5bb)."""
    return gem_parser.parse_one_hand(_HH_TMPL % {'hid': hid, 'hole': hole, 'flop': flop, 'bet': bet},
                                     'GG20260407 - Test.txt')


def load(path):
    text = open(path, encoding='utf-8', errors='replace').read()
    out = []
    for chunk in re.split(r'\n\n+(?=Poker Hand #)', text):
        if chunk.strip().startswith('Poker Hand'):
            h = gem_parser.parse_one_hand(chunk, 'GG20260407-000000 - Test.txt')
            if h:
                out.append(h)
    return out


# ─────────────────────────── 1. severity classification (SRP) ───────────────────────────
print('[1] severity classification')
a = SD.assess_flop_cbet_sizing(mk(sizing=80, arch='ace_high_dry', ip=True))
check('gross over (80% vs [25])', a and a['severity'] == 'gross' and a['direction'] == 'over')
a = SD.assess_flop_cbet_sizing(mk(sizing=10, arch='low_connected', ip=True, board=('6h', '5d', '4c')))
check('gross under (10% vs [50,66])', a and a['severity'] == 'gross' and a['direction'] == 'under')
a = SD.assess_flop_cbet_sizing(mk(sizing=40, arch='ace_high_dry', ip=True))
check('moderate (40% vs [25])', a and a['severity'] == 'moderate')
a = SD.assess_flop_cbet_sizing(mk(sizing=300, arch='broadway_disconnected', ip=True, board=('Kd', '9s', '4h')))
check('dual-strategy never gross (300% vs [33,85,100])', a and a['severity'] == 'moderate')
a = SD.assess_flop_cbet_sizing(mk(sizing=300, arch='middling_disconnected', ip=False, board=('Js', '7h', '5c')))
check('OOP side judged (300% vs [85])', a and a['cbet_side'] == 'oop' and a['severity'] == 'gross')

# ─────────────────────────── 2. fail-closed: chart applicability (deep-audit fixes) ───────────────────────────
print('[2] chart-applicability fail-closed (SRP / HU / non-all-in)')
check('3-bet pot -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, pot_type='3BP')) is None)
check('4-bet pot -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, pot_type='4BP')) is None)
check('multiway flop (flag) -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, multiway=True)) is None)
check('multiway flop (3 players) -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, players_at_flop=3)) is None)
check('all-in c-bet -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, allin=True)) is None)

# ─────────────────────────── 3. fail-closed: missing canonical input ───────────────────────────
print('[3] fail-closed on missing canonical input')
check('within tolerance -> None', SD.assess_flop_cbet_sizing(mk(sizing=30)) is None)
check('not PFR -> None', SD.assess_flop_cbet_sizing(mk(pfr=False, sizing=80)) is None)
check('no flop c-bet -> None', SD.assess_flop_cbet_sizing(mk(sizing=None)) is None)
check('board < 3 -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, board=('Ah', '7d'))) is None)
_oc = gem_textures.classify_archetype
gem_textures.classify_archetype = lambda b: 'unknown'
try:
    check('unknown archetype -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, arch='unknown')) is None)
finally:
    gem_textures.classify_archetype = _oc
_om = gem_textures.archetype_meta
gem_textures.archetype_meta = lambda aid: {'confidence': 'partial'}
try:
    check('incomplete chart -> None', SD.assess_flop_cbet_sizing(mk(sizing=80)) is None)
finally:
    gem_textures.archetype_meta = _om
_ot = gem_textures.get_gto_target
gem_textures.get_gto_target = lambda a, s, d: {'sizings_pct': [], 'depth_band': '0-999BB'}
try:
    check('no sanctioned band -> None', SD.assess_flop_cbet_sizing(mk(sizing=80)) is None)
finally:
    gem_textures.get_gto_target = _ot

# ─────────────────────────── 4. real-ledger pipeline (synthetic SRP hands) ───────────────────────────
print('[4] pipeline on real-ledger SRP hands')
h_gross = srp_hand('TM99000001', 1030)   # ~74.9% vs [25]  -> gross
h_within = srp_hand('TM99000002', 412)   # ~30.0% vs [25]  -> within tolerance
h_mod = srp_hand('TM99000003', 600)      # ~43.6% vs [25]  -> moderate
fam = DC.family_flop_cbet_sizing([h_gross, h_within, h_mod], {})
ids = {c['hand_id']: c for c in fam}
check('gross + moderate fire, within cleared', set(ids) == {'TM99000001', 'TM99000003'})
check('gross severity correct', ids['TM99000001']['context']['sizing_assessment']['severity'] == 'gross')
# decision_id action index == the flop c-bet
hbi = {h['id']: h for h in [h_gross, h_within, h_mod]}
ok = True
for c in fam:
    ai = int(c['decision_id'].rsplit(':', 1)[-1])
    led = hbi[c['hand_id']]['action_ledger'][ai]
    ok = ok and led.get('player') == 'Hero' and led.get('street') == 'flop' and led.get('action') == 'bets'
check('decision_id == the flop c-bet node', ok)

# ─────────────────────────── 5. terminal-verdict ownership (detector does NOT auto-confirm) ───────────────────────────
print('[5] terminal-verdict ownership')
rev = {r['decision_id']: r for r in DC.review_value(fam)}
check('gross -> READ_DEPENDENT (NOT confirmed by detector)',
      rev[ids['TM99000001']['decision_id']]['terminal_verdict'] == 'READ_DEPENDENT')
val = DC.run_value([h_gross, h_within, h_mod], {})
check('run_value confirms ZERO sizing mistakes', len(val['confirmed']) == 0)
check('family present in by_family', 'flop_cbet_sizing' in val['metrics']['by_family'])

# ─────────────────────────── 6. atomic record + semantic audit (no leak / no calc) ───────────────────────────
print('[6] atomic record + semantic audit')
recs = [AP._norm_decision(c, hbi) for c in fam]
rg = next(r for r in recs if r['hand_id'] == 'TM99000001')
check('atomic record resolved', rg.get('canonical_resolved') is True)
check('hero_action is a scalar bet', rg.get('hero_action') == 'bet')
check('evidence_ref bound to chart', rg.get('evidence_ref') == 'chart.flop_cbet_sizing_band')
check('sizing_assessment fact present', isinstance(rg.get('sizing_assessment'), dict))
check('no result/future leak', not any(k in rg for k in ('net_bb', 'won', 'went_to_sd', 'showdown', 'prior_verdict')))
sa = AP.semantic_audit({'required': recs, 'optional': []})
check('semantic audit 0 failing', sa['failing'] == 0)
check('semantic audit 0 leaks', sa['future_information_leaks'] == 0)
check('semantic audit zero analyst calc', sa['zero_analyst_calculations_required'] is True)

# ─────────────────────────── 7. build_packet routing (gross required NOT confirmed; moderate optional) ───────────────────────────
print('[7] build_packet routing')
rd = {'final_truth': {'records': {}}, 'material_loss_population': {}, '_candidate_need_ids': []}
pkt = AP.build_packet([h_gross, h_within, h_mod], rd, session_id='pilot', optional_cap=8)
req = {d['hand_id'] for d in pkt['required']}
opt = {d['hand_id'] for d in pkt['optional']}
check('gross nomination in REQUIRED', 'TM99000001' in req)
check('moderate nomination in OPTIONAL', 'TM99000003' in opt)
check('chart evidence excerpt in packet', 'chart.flop_cbet_sizing_band' in pkt['evidence'])
check('packet semantic audit clean', AP.semantic_audit(pkt)['failing'] == 0)

# ─────────────────────────── 8. dedup / duplicate nomination ───────────────────────────
print('[8] dedup')
val_dup = DC.run_value([h_gross, h_gross], {})   # same hand twice
check('duplicate (hand,street,family) collapses to one',
      sum(1 for c in val_dup['candidates'] if c['family'] == 'flop_cbet_sizing') == 1)

# ─────────────────────────── 9. analyst OWNS the verdict (validate_analyst_output) ───────────────────────────
print('[9] validate_analyst_output (analyst confirms; binding enforced)')
m = pkt['manifest']
gross_did = next(d['decision_id'] for d in pkt['required'] if d['hand_id'] == 'TM99000001')
verdicts = []
for d in pkt['required']:
    if d['decision_id'] == gross_did:
        verdicts.append({'decision_id': gross_did, 'verdict': 'CONFIRMED_MISTAKE',
                         'reason': 'c-bet 75% vs the 25% band', 'better_action': 'size toward 25%',
                         'evidence_refs': ['chart.flop_cbet_sizing_band'], 'fact_refs': ['sizing_assessment']})
    else:
        verdicts.append({'decision_id': d['decision_id'], 'verdict': 'JUSTIFIED', 'reason': 'r'})
good = {'session_id': m['session_id'], 'packet_hash': m['packet_hash'], 'verdicts': verdicts}
res = AP.validate_analyst_output(pkt, good, cache_ok=True)
check('analyst CONFIRMED accepted (analyst owns verdict)', res['valid'] is True and res['required_coverage'] == 1.0)
bad = dict(good); bad_v = [dict(v) for v in verdicts]
bad_v[0] = {'decision_id': gross_did, 'verdict': 'CONFIRMED_MISTAKE', 'reason': 'r', 'fact_refs': ['net_bb']}
bad = {'session_id': m['session_id'], 'packet_hash': m['packet_hash'], 'verdicts': bad_v}
check('unbound fact_ref (net_bb) rejected', AP.validate_analyst_output(pkt, bad, cache_ok=True)['valid'] is False)

# ─────────────────────────── 10. mutation: unsafe records fail closed ───────────────────────────
print('[10] mutation / fail-closed')
# a deep 3BP fixture hand must NOT be nominated even though it is an off-band c-bet
check('fixture 3-bet pots produce ZERO candidates',
      len(DC.family_flop_cbet_sizing(load('test_hands.txt') + load('test_hands_detectors.txt'), {})) == 0)
# a hand with no resolvable Hero decision fails closed (unresolved), never fabricates operands
bad_rec = AP.atomic_snapshot({'id': 'TMWALK', 'cards': ['Ah', 'Kd'], 'action_ledger': []},
                             'flop', 0, 'flop_cbet_sizing')
check('no canonical Hero decision -> unresolved (fail closed)', bad_rec.get('unresolved') is True
      and bad_rec.get('canonical_resolved') is False)

# ─────────────────────────── summary ───────────────────────────
print('\nRESULTS: %d passed, %d failed, %d total' % (_passed, _failed, _passed + _failed))
if _failed:
    raise SystemExit(1)
print('ALL SIZING-LINE PILOT TESTS PASSED')
