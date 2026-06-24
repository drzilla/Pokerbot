"""v8.21 production-path verification — ONE canonical aggregate sizing implementation.

After the closeout, there is NO per-hand sizing detector. The only sizing surface is the AGGREGATE
build_sizing_leak_signals, fed by gem_analyzer's GTO block (gem_textures.aggregate_compliance) and gated by
gem_sizing_detector.cbet_chart_applies (SRP / heads-up / non-all-in). These tests prove the gate, the
production wiring, and that the per-hand path and the dead duplicate are gone.

Run:  PYTHONUTF8=1 python test_sizing_line_pilot.py    (standalone PASS/FAIL; exit 1 on any failure)
"""
import json
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


def mk(sizing, pot_type='SRP', multiway=False, players=2, allin=False,
       arch='middling_disconnected', ip=True, eff=100.0, hid='X'):
    return {'id': hid, 'pfr': True, 'board_archetype': arch, 'hero_ip': ip, 'eff_stack_bb': eff,
            'pot_type': pot_type, 'multiway_flop': multiway, 'players_at_flop': players,
            'board': ['Jh', '9d', '5c'],
            'hero_bets': [['flop', sizing, 'cbet', 'IP' if ip else 'OOP']],
            'action_ledger': [{'street': 'flop', 'player': 'Hero', 'action': 'bets', 'is_all_in': allin}]}


# ─────────────────────── 1. cbet_chart_applies safety gate ───────────────────────
print('[1] cbet_chart_applies gate (SRP / heads-up / non-all-in)')
check('SRP heads-up non-all-in -> applies', SD.cbet_chart_applies(mk(33)) is True)
check('3-bet pot -> blocked', SD.cbet_chart_applies(mk(33, pot_type='3BP')) is False)
check('4-bet pot -> blocked', SD.cbet_chart_applies(mk(33, pot_type='4BP')) is False)
check('multiway flag -> blocked', SD.cbet_chart_applies(mk(33, multiway=True)) is False)
check('3 players at flop -> blocked', SD.cbet_chart_applies(mk(33, players=3)) is False)
check('all-in c-bet -> blocked', SD.cbet_chart_applies(mk(33, allin=True)) is False)

# ─────────────────────── 2. gate folded into the aggregate path (freq kept, sizing gated) ───────────────────────
print('[2] aggregate_compliance with the production gate')
# mirror gem_analyzer._gto_sizing_pct: None when the chart does not apply
def _siz_gated(h):
    if not SD.cbet_chart_applies(h):
        return None
    for b in h.get('hero_bets', []):
        if b[0] == 'flop' and b[2] == 'cbet':
            return b[1]
    return None
hands = [mk(33, hid='SRP%d' % i) for i in range(9)] + [mk(33, pot_type='3BP', hid='TBP1')]
tgf = gem_textures.aggregate_compliance(
    hands, get_archetype_fn=lambda h: h['board_archetype'],
    get_side_fn=lambda h: 'ip' if h['hero_ip'] else 'oop',
    get_depth_fn=lambda h: h['eff_stack_bb'], get_did_cbet_fn=lambda h: True, get_sizing_fn=_siz_gated)
bucket = tgf['middling_disconnected']['ip']
check('frequency denominator counts ALL 10 c-bets', bucket['n_cbet'] == 10)
check('sizing judged EXCLUDES the 3BP c-bet (9 not 10)', bucket['sizing_judged_n'] == 9)
check('sizing compliance 0% (33% vs [100,125,150])', bucket['sizing_compliance_pct'] == 0.0)

# ─────────────────────── 3. build_sizing_leak_signals: aggregate, no per-hand verdict ───────────────────────
print('[3] build_sizing_leak_signals (aggregate only)')
res = SD.build_sizing_leak_signals(tgf)
sigs = res['signals']
check('one aggregate leak signal fires', len(sigs) == 1)
sig = sigs[0] if sigs else {}
check('signal_type is aggregate_leak', sig.get('signal_type') == 'aggregate_leak')
check('judged count is the gated 9', sig.get('evidence', {}).get('judged_c_bets') == 9)
check('signal does NOT confirm a per-hand mistake',
      'CONFIRMED' not in json.dumps(sig) and 'confirmed_mistake' not in json.dumps(sig).lower())
check('contributing hands are evidence, analyst decides',
      'analyst' in (sig.get('requires_analyst_review') or '').lower())

# ─────────────────────── 4. ONE implementation; dead duplicate removed ───────────────────────
print('[4] single canonical implementation')
check('summarize_offband_sizing removed', not hasattr(SD, 'summarize_offband_sizing'))
check('assess_flop_cbet_sizing removed', not hasattr(SD, 'assess_flop_cbet_sizing'))
check('applicable_band removed', not hasattr(SD, 'applicable_band'))
check('build_sizing_leak_signals kept', hasattr(SD, 'build_sizing_leak_signals'))

# ─────────────────────── 5. production wiring present ───────────────────────
print('[5] production wiring (source checks)')
_cb = open('gem_coverage_builder.py', encoding='utf-8').read()
check('coverage_builder calls build_sizing_leak_signals',
      'build_sizing_leak_signals(stats.get(' in _cb)
check("coverage_builder stamps report_data['sizing_leak_signals']",
      "report_data['sizing_leak_signals']" in _cb)
_an = open('gem_analyzer.py', encoding='utf-8').read()
check('gem_analyzer gates _gto_sizing_pct via cbet_chart_applies',
      'cbet_chart_applies' in _an and 'def _gto_sizing_pct' in _an)
_dr = open('gem_report_draft/draft.py', encoding='utf-8').read()
check('report renders Sizing & Line Patterns from sizing_leak_signals',
      'Sizing & Line Patterns' in _dr and "rd.get('sizing_leak_signals')" in _dr)

# ─────────────────────── 6. no per-hand sizing in discovery / packet ───────────────────────
print('[6] zero per-hand sizing candidates / reviews')
val = DC.run_value(list(hands), {})
check('run_value emits no flop_cbet_sizing candidates',
      not any(c['family'] == 'flop_cbet_sizing' for c in val['candidates']))
rd = {'final_truth': {'records': {}}, 'material_loss_population': {}, '_candidate_need_ids': []}
pkt = AP.build_packet(list(hands), rd, session_id='prod', optional_cap=8)
check('packet has zero sizing decisions',
      not any(d.get('family') == 'flop_cbet_sizing' for d in pkt['required'] + pkt['optional']))
check('no sizing chart excerpt in EVIDENCE', 'chart.flop_cbet_sizing_band' not in AP.EVIDENCE)

print('\nRESULTS: %d passed, %d failed, %d total' % (_passed, _failed, _passed + _failed))
if _failed:
    raise SystemExit(1)
print('ALL PRODUCTION-PATH SIZING TESTS PASSED')
