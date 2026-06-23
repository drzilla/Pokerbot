"""v8.21 pilot — targeted contract tests for the per-hand flop c-bet SIZING detector (Family A).

Run:  PYTHONUTF8=1 python test_sizing_line_pilot.py
Standalone PASS/FAIL harness (repo convention). Exit 1 on any failure.

Covers: deviation severity classification; fail-closed on every missing canonical input; the graded node
is the c-bet; the candidate flows through the canonical packet pipeline (run_value -> _norm_decision ->
atomic_snapshot) with a clean semantic audit and a no-leak result; build_packet routing (gross -> required,
moderate -> optional); and validate_analyst_output accepts a packet-bound verdict yet rejects unbound
evidence / fact references.
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


def mk(pfr=True, sizing=None, arch='ace_high_dry', ip=True, eff=100.0, board=('Ah', '7d', '2c')):
    """Minimal hand dict carrying ONLY the canonical fields assess_flop_cbet_sizing consumes."""
    hb = [['flop', sizing, 'cbet', 'IP' if ip else 'OOP']] if sizing is not None else []
    return {'pfr': pfr, 'hero_bets': hb, 'board': list(board),
            'board_archetype': arch, 'hero_ip': ip, 'eff_stack_bb': eff}


def load(path):
    text = open(path, encoding='utf-8', errors='replace').read()
    out = []
    for chunk in re.split(r'\n\n+(?=Poker Hand #)', text):
        if chunk.strip().startswith('Poker Hand'):
            h = gem_parser.parse_one_hand(chunk, 'GG20260407-000000 - Test.txt')
            if h:
                out.append(h)
    return out


# ─────────────────────────── 1. assess_flop_cbet_sizing severity ───────────────────────────
print('[1] severity classification')
# ace_high_dry IP @100bb -> band [25] (single-target, complete)
a = SD.assess_flop_cbet_sizing(mk(sizing=80, arch='ace_high_dry', ip=True, eff=100))
check('gross over (80% vs [25])', a and a['severity'] == 'gross' and a['direction'] == 'over')
# low_connected IP -> band [50,66] (single-strategy, complete); 10% is <=0.5*50 and >=25pp off
a = SD.assess_flop_cbet_sizing(mk(sizing=10, arch='low_connected', ip=True, eff=100,
                                  board=('6h', '5d', '4c')))
check('gross under (10% vs [50,66])', a and a['severity'] == 'gross' and a['direction'] == 'under')
# moderate: 40% vs [25] -> 15pp off, not >=2x, not <=0.5x
a = SD.assess_flop_cbet_sizing(mk(sizing=40, arch='ace_high_dry', ip=True, eff=100))
check('moderate (40% vs [25])', a and a['severity'] == 'moderate')
# dual-strategy band is NEVER graded gross (broadway_disconnected IP [33,85,100] dual)
a = SD.assess_flop_cbet_sizing(mk(sizing=300, arch='broadway_disconnected', ip=True, eff=100,
                                  board=('Kd', '9s', '4h')))
check('dual-strategy never gross (300% vs [33,85,100])', a and a['severity'] == 'moderate')

# ─────────────────────────── 2. fail-closed on missing canonical input ───────────────────────────
print('[2] fail-closed conditions (return None)')
check('within tolerance -> None', SD.assess_flop_cbet_sizing(mk(sizing=30, arch='ace_high_dry')) is None)
check('not PFR -> None', SD.assess_flop_cbet_sizing(mk(pfr=False, sizing=80)) is None)
check('no flop c-bet -> None', SD.assess_flop_cbet_sizing(mk(sizing=None)) is None)
check('board < 3 cards -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, board=('Ah', '7d'))) is None)

# unknown archetype -> None (force the canonical classifier to 'unknown')
_orig_classify = gem_textures.classify_archetype
gem_textures.classify_archetype = lambda b: 'unknown'
try:
    check('unknown archetype -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, arch='unknown')) is None)
finally:
    gem_textures.classify_archetype = _orig_classify

# non-complete chart -> None (force confidence != complete)
_orig_meta = gem_textures.archetype_meta
gem_textures.archetype_meta = lambda aid: {'confidence': 'partial'}
try:
    check('incomplete chart -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, arch='ace_high_dry')) is None)
finally:
    gem_textures.archetype_meta = _orig_meta

# empty band -> None (force get_gto_target to a no-target band)
_orig_tgt = gem_textures.get_gto_target
gem_textures.get_gto_target = lambda a, s, d: {'sizings_pct': [], 'depth_band': '0-999BB'}
try:
    check('no sanctioned band -> None', SD.assess_flop_cbet_sizing(mk(sizing=80, arch='ace_high_dry')) is None)
finally:
    gem_textures.get_gto_target = _orig_tgt

# ─────────────────────────── 3. family on real fixtures ───────────────────────────
print('[3] family_flop_cbet_sizing on fixture hands')
hands = load('test_hands.txt') + load('test_hands_detectors.txt')
fam = DC.family_flop_cbet_sizing(hands, {})
by_id = {c['hand_id']: c for c in fam}
check('two fixture candidates', len(fam) == 2)
check('gross candidate TM91000015 present', 'TM91000015' in by_id
      and by_id['TM91000015']['context']['sizing_assessment']['severity'] == 'gross')
check('moderate candidate TM90000006 present', 'TM90000006' in by_id
      and by_id['TM90000006']['context']['sizing_assessment']['severity'] == 'moderate')
check('compliant c-bet TM91000003 NOT flagged', 'TM91000003' not in by_id)
# the graded node is the flop c-bet itself
hbi = {h['id']: h for h in hands}
ok = True
for c in fam:
    ai = int(c['decision_id'].rsplit(':', 1)[-1])
    led = hbi[c['hand_id']]['action_ledger'][ai]
    ok = ok and led.get('player') == 'Hero' and led.get('street') == 'flop' and led.get('action') == 'bets'
check('decision_id action_index == the flop c-bet', ok)

# review verdicts
rev = {r['decision_id']: r for r in DC.review_value(fam)}
check('gross -> CONFIRMED_MISTAKE',
      rev[by_id['TM91000015']['decision_id']]['terminal_verdict'] == 'CONFIRMED_MISTAKE')
check('moderate -> READ_DEPENDENT',
      rev[by_id['TM90000006']['decision_id']]['terminal_verdict'] == 'READ_DEPENDENT')

# ─────────────────────────── 4. run_value integration ───────────────────────────
print('[4] run_value integration')
val = DC.run_value(hands, {}, session='pilot_test')
check('family present in by_family', 'flop_cbet_sizing' in val['metrics']['by_family'])
check('exactly one confirmed sizing mistake',
      val['metrics']['by_family']['flop_cbet_sizing']['confirmed_mistakes'] == 1)
check('confirmed set carries the gross decision',
      any(r['family'] == 'flop_cbet_sizing' for r in val['confirmed']))

# ─────────────────────────── 5. atomic record + semantic audit (no leak / no calc) ───────────────────────────
print('[5] atomic record + semantic audit')
recs = [AP._norm_decision(c, hbi) for c in fam]
r_gross = next(r for r in recs if r['hand_id'] == 'TM91000015')
check('atomic record canonically resolved', r_gross.get('canonical_resolved') is True)
check('evidence_ref bound to the chart', r_gross.get('evidence_ref') == 'chart.flop_cbet_sizing_band')
check('evidence_tier CHART_BACKED', r_gross.get('evidence_tier') == 'CHART_BACKED')
check('sizing_assessment fact present', isinstance(r_gross.get('sizing_assessment'), dict))
check('no net_bb / result leak in record',
      not any(k in r_gross for k in ('net_bb', 'won', 'went_to_sd', 'showdown', 'prior_verdict')))
sa = AP.semantic_audit({'required': recs, 'optional': []})
check('semantic audit: 0 failing', sa['failing'] == 0)
check('semantic audit: 0 future-information leaks', sa['future_information_leaks'] == 0)
check('semantic audit: zero analyst calculations required', sa['zero_analyst_calculations_required'] is True)

# ─────────────────────────── 6. build_packet routing ───────────────────────────
print('[6] build_packet routing (gross -> required, moderate -> optional)')
rd = {'final_truth': {'records': {}}, 'material_loss_population': {}, '_candidate_need_ids': []}
pkt = AP.build_packet(hands, rd, session_id='pilot', optional_cap=8)
req_hands = {d['hand_id'] for d in pkt['required']}
opt_hands = {d['hand_id'] for d in pkt['optional']}
check('gross hand in REQUIRED', 'TM91000015' in req_hands)
check('moderate hand in OPTIONAL', 'TM90000006' in opt_hands)
check('chart evidence excerpt included in packet', 'chart.flop_cbet_sizing_band' in pkt['evidence'])
check('packet semantic audit clean', AP.semantic_audit(pkt)['failing'] == 0)

# ─────────────────────────── 7. validate_analyst_output binding ───────────────────────────
print('[7] validate_analyst_output (one-pass / no-calc contract)')
m = pkt['manifest']
gross_did = next(d['decision_id'] for d in pkt['required'] if d['hand_id'] == 'TM91000015')
# one verdict per required decision (the gross sizing one cites only packet facts), keyed by id so no dup.
verdicts = []
for d in pkt['required']:
    if d['decision_id'] == gross_did:
        verdicts.append({'decision_id': gross_did, 'verdict': 'CONFIRMED_MISTAKE',
                         'reason': 'c-bet size off the canonical band', 'better_action': 'size toward 85%',
                         'evidence_refs': ['chart.flop_cbet_sizing_band'], 'fact_refs': ['sizing_assessment']})
    else:
        verdicts.append({'decision_id': d['decision_id'], 'verdict': 'JUSTIFIED', 'reason': 'r'})
good = {'session_id': m['session_id'], 'packet_hash': m['packet_hash'], 'verdicts': verdicts}
res = AP.validate_analyst_output(pkt, good, cache_ok=True)
check('valid analyst output accepted', res['valid'] is True and res['required_coverage'] == 1.0)

bad_ev = {'session_id': m['session_id'], 'packet_hash': m['packet_hash'],
          'verdicts': [{'decision_id': d['decision_id'], 'verdict': 'JUSTIFIED', 'reason': 'r'}
                       for d in pkt['required']]}
bad_ev['verdicts'][0] = {'decision_id': gross_did, 'verdict': 'CONFIRMED_MISTAKE', 'reason': 'r',
                         'evidence_refs': ['external_solver_run']}     # not a packet evidence key
check('unbound evidence_ref rejected', AP.validate_analyst_output(pkt, bad_ev, cache_ok=True)['valid'] is False)

bad_fact = {'session_id': m['session_id'], 'packet_hash': m['packet_hash'],
            'verdicts': [{'decision_id': d['decision_id'], 'verdict': 'JUSTIFIED', 'reason': 'r'}
                         for d in pkt['required']]}
bad_fact['verdicts'][0] = {'decision_id': gross_did, 'verdict': 'CONFIRMED_MISTAKE', 'reason': 'r',
                           'fact_refs': ['net_bb']}                    # a result fact not in the record
check('unbound fact_ref (net_bb) rejected', AP.validate_analyst_output(pkt, bad_fact, cache_ok=True)['valid'] is False)

# ─────────────────────────── summary ───────────────────────────
print('\nRESULTS: %d passed, %d failed, %d total' % (_passed, _failed, _passed + _failed))
if _failed:
    raise SystemExit(1)
print('ALL SIZING-LINE PILOT TESTS PASSED')
