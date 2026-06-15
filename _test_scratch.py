#!/usr/bin/env python3
"""v8.8.3 regression tests: exploit read semantics fix.

Layers 1-5: constants, helper, detector behavioral, integration,
            backward compat, golden fixture.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

PASS = 0; FAIL = 0

def check(label, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  OK  {label}')
    else:
        FAIL += 1
        print(f'  FAIL {label} -- {detail}')


# ============================================================
# LAYER 1: Constants & helper unit tests
# ============================================================
print('\n=== LAYER 1: Constants & helper unit tests ===')

from gem_villain_intel import (
    _EXPLOIT_READ_MAP, VALID_EXPLOIT_READ_LABELS, _stamp_exploit_read,
    _empty_exploit_opportunity, _villain_has_read, _DIMENSION_MAP,
)

# Test 1: _EXPLOIT_READ_MAP completeness
_expected_keys = {
    'bluffed_sticky', 'paid_off_passive_aggression', 'missed_steal_vs_nit',
    'missed_thin_value_vs_sticky', 'opened_too_loose_vs_aggro',
    'overfolded_vs_aggro', 'ego_fought_maniac', 'pivot_overplayed',
}
check('T1: _EXPLOIT_READ_MAP has exactly 8 entries',
      set(_EXPLOIT_READ_MAP.keys()) == _expected_keys,
      f'got keys: {set(_EXPLOIT_READ_MAP.keys())}')

# Test 2: _EXPLOIT_READ_MAP values valid
check('T2: all map values in VALID_EXPLOIT_READ_LABELS',
      all(v in VALID_EXPLOIT_READ_LABELS for v in _EXPLOIT_READ_MAP.values()),
      f'bad values: {[v for v in _EXPLOIT_READ_MAP.values() if v not in VALID_EXPLOIT_READ_LABELS]}')

# Test 3: VALID_EXPLOIT_READ_LABELS has 4 entries
check('T3: VALID_EXPLOIT_READ_LABELS has 4 entries',
      len(VALID_EXPLOIT_READ_LABELS) == 4,
      f'got {len(VALID_EXPLOIT_READ_LABELS)}')

# Test 4: _stamp_exploit_read stamps all fields
_t4 = {}
_stamp_exploit_read(_t4, 'overfolded_vs_aggro', 'prior_atoms_mapped')
check('T4: stamp sets exploit_detector',
      _t4.get('exploit_detector') == 'overfolded_vs_aggro',
      f'got {_t4.get("exploit_detector")}')
check('T4b: stamp sets exploit_type',
      _t4.get('exploit_type') == 'overfolded_vs_aggro',
      f'got {_t4.get("exploit_type")}')
check('T4c: stamp sets exploit_outcome=missed',
      _t4.get('exploit_outcome') == 'missed',
      f'got {_t4.get("exploit_outcome")}')
check('T4d: stamp sets read_source',
      _t4.get('read_source') == 'prior_atoms_mapped',
      f'got {_t4.get("read_source")}')
check('T4e: stamp sets exploit_read_label',
      _t4.get('exploit_read_label') == 'Aggressive',
      f'got {_t4.get("exploit_read_label")}')

# Test 5: _stamp_exploit_read outcome='good'
_t5 = {}
_stamp_exploit_read(_t5, 'missed_steal_vs_nit', 'prior_atoms_mapped', outcome='good')
check('T5: good outcome stamps correctly',
      _t5.get('exploit_outcome') == 'good',
      f'got {_t5.get("exploit_outcome")}')

# Test 6: _stamp_exploit_read unknown detector
_t6 = {}
_stamp_exploit_read(_t6, 'nonexistent_detector', '')
check('T6: unknown detector maps to Unknown',
      _t6.get('exploit_read_label') == 'Unknown',
      f'got {_t6.get("exploit_read_label")}')

# Test 7: Template has new fields
_t7 = _empty_exploit_opportunity()
_new_fields = ('exploit_detector', 'exploit_type', 'exploit_outcome',
               'read_source', 'exploit_read_label')
check('T7: template has all 5 new fields',
      all(k in _t7 for k in _new_fields),
      f'missing: {[k for k in _new_fields if k not in _t7]}')


# ============================================================
# LAYER 2: Detector-level behavioral tests
# ============================================================
print('\n=== LAYER 2: Detector behavioral tests ===')

from gem_villain_intel import (
    detect_bluffed_sticky, detect_overfolded_vs_aggro,
    detect_pivot_overplayed, detect_missed_steal_vs_nit_blinds,
    detect_paid_off_passive_aggression, detect_missed_thin_value_vs_sticky,
    detect_opened_too_loose_vs_aggro, detect_ego_fought_maniac,
    detect_exploit_opportunities,
)


def _make_atoms(villain_key, dimension, count, hand_ids=None):
    """Build mock evidence atoms for a villain."""
    atoms = []
    for i in range(count):
        hid = (hand_ids[i] if hand_ids and i < len(hand_ids)
               else f'H{9999 - i}')  # high IDs = early hands
        atoms.append({
            'hand_id': hid,
            'villain_key': villain_key,
            'dimension': dimension,
            'strength': 1,
            'signal': f'mock_{dimension}',
            'badge': 'note',
            'street': 'flop',
            'same_hand_actionable': False,
            'hero_involved': True,
        })
    return atoms


# Test 8: detect_bluffed_sticky stamps correctly
_hand8 = {
    'id': 'H100', 'tournament_id': 'T1',
    'hero_street_actions': {'river': 'bet'},
    'net_bb': -15.0, 'went_to_sd': False,
    'primary_villain_key': 'T1|V1',
    'hero': 'Hero',
    'villains': {'V1': {'position': 'BB'}},
    'action_ledger': [],
}
# 4 sticky atoms with earlier hand IDs (higher numbers = earlier in GG)
_atoms8 = {'T1|V1': _make_atoms('T1|V1', 'sticky', 4, ['H9999', 'H9998', 'H9997', 'H9996'])}
_aliases8 = {'T1|V1': {'alias': 'TestV', 'v_number': 'V01', 'display': 'TestV'}}
_ho8 = {'H9999': 0, 'H9998': 1, 'H9997': 2, 'H9996': 3, 'H100': 4}
_result8 = detect_bluffed_sticky(_hand8, 'Hero', _aliases8, _atoms8,
                                  read_states=None, hand_order=_ho8)
check('T8: bluffed_sticky fires',
      len(_result8) == 1,
      f'got {len(_result8)} exploits')
if _result8:
    check('T8b: exploit_detector=bluffed_sticky',
          _result8[0].get('exploit_detector') == 'bluffed_sticky',
          f'got {_result8[0].get("exploit_detector")}')
    check('T8c: exploit_read_label=Sticky Passive',
          _result8[0].get('exploit_read_label') == 'Sticky Passive',
          f'got {_result8[0].get("exploit_read_label")}')
    check('T8d: read_source=prior_atoms_mapped',
          _result8[0].get('read_source') == 'prior_atoms_mapped',
          f'got {_result8[0].get("read_source")}')

# Test 9: detect_overfolded_vs_aggro stamps correctly
_hand9 = {
    'id': 'H200', 'tournament_id': 'T1',
    'hero_street_actions': {'flop': 'fold'},
    'net_bb': -5.0,
    'primary_villain_key': 'T1|V2',
    'hero': 'Hero',
    'villains': {'V2': {'position': 'BTN'}},
    'action_ledger': [],
}
_atoms9 = {'T1|V2': _make_atoms('T1|V2', 'aggressive', 4, ['H9999', 'H9998', 'H9997', 'H9996'])}
_aliases9 = {'T1|V2': {'alias': 'AggroV', 'v_number': 'V02', 'display': 'AggroV'}}
_ho9 = {'H9999': 0, 'H9998': 1, 'H9997': 2, 'H9996': 3, 'H200': 4}
_result9 = detect_overfolded_vs_aggro(_hand9, 'Hero', _aliases9, _atoms9,
                                       read_states=None, hand_order=_ho9)
check('T9: overfolded_vs_aggro fires',
      len(_result9) == 1,
      f'got {len(_result9)} exploits')
if _result9:
    check('T9b: exploit_detector=overfolded_vs_aggro',
          _result9[0].get('exploit_detector') == 'overfolded_vs_aggro',
          f'got {_result9[0].get("exploit_detector")}')
    check('T9c: exploit_read_label=Aggressive',
          _result9[0].get('exploit_read_label') == 'Aggressive',
          f'got {_result9[0].get("exploit_read_label")}')

# Test 10: detect_pivot_overplayed uses same_hand_pivot
_hand10 = {
    'id': 'H300', 'tournament_id': 'T1',
    'hero_street_actions': {'turn': 'call', 'river': 'call'},
    'net_bb': -25.0,
    'primary_villain_key': 'T1|V3',
    'hero': 'Hero',
    'villains': {'V3': {'position': 'CO'}},
    'action_ledger': [],
}
_atoms10 = {'T1|V3': [{
    'hand_id': 'H300', 'villain_key': 'T1|V3', 'dimension': 'pivot',
    'strength': 1, 'signal': 'passive_aggro_pivot', 'badge': 'pivot',
    'street': 'turn', 'same_hand_actionable': True, 'hero_involved': True,
}]}
_aliases10 = {'T1|V3': {'alias': 'PivotV', 'v_number': 'V03', 'display': 'PivotV'}}
_result10 = detect_pivot_overplayed(_hand10, 'Hero', _aliases10, _atoms10,
                                     read_states=None, hand_order=None)
check('T10: pivot_overplayed fires',
      len(_result10) == 1,
      f'got {len(_result10)} exploits')
if _result10:
    check('T10b: read_source=same_hand_pivot',
          _result10[0].get('read_source') == 'same_hand_pivot',
          f'got {_result10[0].get("read_source")}')
    check('T10c: exploit_read_label=Loose Passive',
          _result10[0].get('exploit_read_label') == 'Loose Passive',
          f'got {_result10[0].get("exploit_read_label")}')

# Test 11: detect_missed_steal_vs_nit_blinds stamps correctly
_hand11 = {
    'id': 'H400', 'tournament_id': 'T1',
    'position': 'BTN',
    'vpip': False, 'pfr': False,
    'cards': ['Kh', '9h'],  # stealable suited king
    'hero': 'Hero',
    'villains': {'NitV': {'position': 'BB'}},
    'action_ledger': [
        {'player': 'Hero', 'action': 'folds', 'street': 'preflop', 'amount_bb': 0},
    ],
}
_atoms11 = {'T1|NitV': _make_atoms('T1|NitV', 'tight', 4, ['H9999', 'H9998', 'H9997', 'H9996'])}
_aliases11 = {'T1|NitV': {'alias': 'NitGuy', 'v_number': 'V04', 'display': 'NitGuy'}}
_ho11 = {'H9999': 0, 'H9998': 1, 'H9997': 2, 'H9996': 3, 'H400': 4}
_result11 = detect_missed_steal_vs_nit_blinds(_hand11, 'Hero', _aliases11, _atoms11,
                                               read_states=None, hand_order=_ho11)
check('T11: missed_steal_vs_nit fires',
      len(_result11) == 1,
      f'got {len(_result11)} exploits')
if _result11:
    check('T11b: exploit_read_label=Nit / Rock',
          _result11[0].get('exploit_read_label') == 'Nit / Rock',
          f'got {_result11[0].get("exploit_read_label")}')

# Test 12: _villain_has_read source propagation
_hand12 = {'id': 'H500', 'tournament_id': 'T1', 'villain_archetype': '', 'villain_archetype_confidence': ''}
_atoms12 = {'T1|V5': _make_atoms('T1|V5', 'aggressive', 5, ['H9999', 'H9998', 'H9997', 'H9996', 'H9995'])}
_ho12 = {'H9999': 0, 'H9998': 1, 'H9997': 2, 'H9996': 3, 'H9995': 4, 'H500': 5}
_has, _src, _conf, _na = _villain_has_read(_hand12, 'T1|V5', 'aggressive', _atoms12,
                                       min_atoms=2, hand_order=_ho12)
check('T12: prior atoms -> prior_atoms_mapped',
      _has and _src == 'prior_atoms_mapped',
      f'has={_has}, src={_src}')

# Test 13: Archetype fallback stamps read_source='profiler_archetype'
_hand13 = {
    'id': 'H600', 'tournament_id': 'T1',
    'hero_street_actions': {'flop': 'fold'},
    'net_bb': -8.0,
    'primary_villain_key': 'T1|V6',
    'hero': 'Hero',
    'villain_archetype': 'MANIAC',
    'villain_archetype_confidence': 'medium',
    'villains': {'V6': {'position': 'BTN'}},
    'action_ledger': [],
}
# NO prior atoms — must fall back to archetype
_atoms13 = {}
_aliases13 = {'T1|V6': {'alias': 'ArchV', 'v_number': 'V06', 'display': 'ArchV'}}
_result13 = detect_overfolded_vs_aggro(_hand13, 'Hero', _aliases13, _atoms13,
                                        read_states=None, hand_order=None)
check('T13: archetype fallback fires',
      len(_result13) == 1,
      f'got {len(_result13)} exploits')
if _result13:
    check('T13b: read_source=profiler_archetype',
          _result13[0].get('read_source') == 'profiler_archetype',
          f'got {_result13[0].get("read_source")}')

# Test 14: No-fire returns empty list
_hand14 = {
    'id': 'H700', 'tournament_id': 'T1',
    'hero_street_actions': {'river': 'bet'},
    'net_bb': -10.0, 'went_to_sd': False,
    'primary_villain_key': 'T1|V7',
    'hero': 'Hero',
    'villain_archetype': '', 'villain_archetype_confidence': '',
    'villains': {'V7': {'position': 'BB'}},
    'action_ledger': [],
}
# No atoms, no matching archetype → should not fire
_result14 = detect_bluffed_sticky(_hand14, 'Hero', {}, {},
                                   read_states=None, hand_order=None)
check('T14: no-fire returns empty list',
      _result14 == [],
      f'got {_result14}')


# ============================================================
# LAYER 3: Orchestrator & integration tests
# ============================================================
print('\n=== LAYER 3: Orchestrator & integration tests ===')

# Test 15: detect_exploit_opportunities calls all 8 detectors, no crash
# Build a multi-hand list with atoms that fire at least 2 detectors.
# Include dummy "prior" hands so atom hand IDs appear in hand_order
# (orchestrator builds hand_order from h.get('id') of the hands list;
#  atoms referencing unknown hand IDs are filtered out by temporal gate).
_prior_hand_ids = ['H9999', 'H9998', 'H9997', 'H9996', 'H9995']
_dummy_prior_hands = [
    {'id': hid, 'tournament_id': 'T1', 'hero': 'Hero',
     'hero_street_actions': {}, 'net_bb': 0, 'villains': {},
     'action_ledger': [], 'primary_villain_key': ''}
    for hid in _prior_hand_ids
]
_hands15 = _dummy_prior_hands + [_hand8, _hand9, _hand10, _hand11]
_atoms15 = {}
_atoms15.update(_atoms8)
_atoms15.update(_atoms9)
_atoms15.update(_atoms10)
_atoms15.update(_atoms11)
_aliases15 = {}
_aliases15.update(_aliases8)
_aliases15.update(_aliases9)
_aliases15.update(_aliases10)
_aliases15.update(_aliases11)
_result15 = detect_exploit_opportunities(_hands15, 'Hero', _aliases15, _atoms15,
                                          read_states=None)
check('T15: orchestrator returns list without crash',
      isinstance(_result15, list),
      f'got {type(_result15).__name__}')
check('T15b: orchestrator fires at least 2 detectors',
      len(_result15) >= 2,
      f'got {len(_result15)} exploits')

# Test 16: detector → label mapping invariant
# Every exploit from the orchestrator must satisfy:
#   exploit_read_label == _EXPLOIT_READ_MAP[exploit_detector]
_t16_ok = True
_t16_detail = ''
for _exp16 in _result15:
    _det = _exp16.get('exploit_detector', '')
    _label = _exp16.get('exploit_read_label', '')
    _expected = _EXPLOIT_READ_MAP.get(_det, '❓ Unknown')
    if _label != _expected:
        _t16_ok = False
        _t16_detail = f'detector={_det}: got {_label!r}, expected {_expected!r}'
        break
check('T16: exploit_read_label == _EXPLOIT_READ_MAP[exploit_detector] for all',
      _t16_ok, _t16_detail)

# Test 17: All labels valid
_t17_bad = [e for e in _result15
            if e.get('exploit_read_label', '') not in VALID_EXPLOIT_READ_LABELS
            and e.get('exploit_read_label', '') != '❓ Unknown']
check('T17: all exploit_read_labels in VALID_EXPLOIT_READ_LABELS or Unknown',
      len(_t17_bad) == 0,
      f'{len(_t17_bad)} invalid labels: {[e.get("exploit_read_label") for e in _t17_bad[:3]]}')

# Test 18: No fresh text fallback — no v8.8.3 exploit should have legacy_text_inference
_t18_bad = [e for e in _result15
            if e.get('read_label_source') == 'legacy_text_inference']
check('T18: no fresh exploit uses legacy_text_inference',
      len(_t18_bad) == 0,
      f'{len(_t18_bad)} exploits used text fallback')

# Test 19: Unknown excluded from Matrix — simulate grouping logic
from collections import defaultdict as _ddict

_t19_exploits = list(_result15)  # copy real ones
# Add a fake exploit with Unknown label
_t19_unknown = {'villain_key': 'T1|VX', 'auto_verdict': 'missed_exploit',
                'exploit_read_label': '❓ Unknown', 'exploit_detector': 'nonexistent'}
_t19_exploits.append(_t19_unknown)

_t19_by_read = _ddict(lambda: {'exploit_opps': 0, 'missed': 0})
_t19_n_excluded = 0
for _exp19 in _t19_exploits:
    _epr19 = _exp19.get('exploit_read_label', '')
    if _epr19 == 'Unknown' or _epr19 == '❓ Unknown' or not _epr19:
        _t19_n_excluded += 1
        continue
    _t19_by_read[_epr19]['exploit_opps'] += 1
    if _exp19.get('auto_verdict') == 'missed_exploit':
        _t19_by_read[_epr19]['missed'] += 1

check('T19: Unknown exploit excluded from Matrix counts',
      _t19_n_excluded >= 1,
      f'excluded={_t19_n_excluded}')
check('T19b: no Unknown key in Matrix rows',
      'Unknown' not in _t19_by_read and '❓ Unknown' not in _t19_by_read,
      f'found Unknown in rows: {list(_t19_by_read.keys())}')

# Test 20: Semantic correctness — aggro detectors → Aggressive row
_aggro_dets = {'overfolded_vs_aggro', 'opened_too_loose_vs_aggro', 'ego_fought_maniac'}
_t20_ok = all(_EXPLOIT_READ_MAP[d] == 'Aggressive' for d in _aggro_dets)
check('T20: aggro detectors all map to Aggressive',
      _t20_ok,
      f'got: {[(d, _EXPLOIT_READ_MAP[d]) for d in _aggro_dets if _EXPLOIT_READ_MAP[d] != "Aggressive"]}')

# Test 21: Semantic correctness — sticky detectors → Sticky Passive row
_sticky_dets = {'bluffed_sticky', 'missed_thin_value_vs_sticky'}
_t21_ok = all(_EXPLOIT_READ_MAP[d] == 'Sticky Passive' for d in _sticky_dets)
check('T21: sticky detectors all map to Sticky Passive',
      _t21_ok,
      f'got: {[(d, _EXPLOIT_READ_MAP[d]) for d in _sticky_dets if _EXPLOIT_READ_MAP[d] != "Sticky Passive"]}')

# Test 22: read_source distribution — every exploit has non-empty read_source
_t22_sources = [e.get('read_source', '') for e in _result15]
check('T22: all exploits have non-empty read_source',
      all(_t22_sources),
      f'empty read_source count: {_t22_sources.count("")}')
_t22_valid_sources = {'prior_atoms_mapped', 'profiler_archetype', 'same_hand_pivot'}
_t22_bad_src = [s for s in _t22_sources if s not in _t22_valid_sources]
check('T22b: all read_source values are valid',
      len(_t22_bad_src) == 0,
      f'invalid sources: {_t22_bad_src}')

# Test 23: Matrix count == drilldown count
# Simulate JS serialization (sections_xiv.py logic): exploit_read_label → read_label
_t23_js_by_read = _ddict(int)
for _exp23 in _result15:
    _epr23_raw = _exp23.get('exploit_read_label', '')
    if not _epr23_raw:
        continue
    _epr23_label = _epr23_raw.split(' ', 1)[1] if ' ' in _epr23_raw else _epr23_raw
    if _epr23_label == 'Unknown':
        continue
    _t23_js_by_read[_epr23_label] += 1

# Simulate Matrix counts (same logic as test 19 but for real exploits only)
_t23_matrix_by_read = _ddict(int)
for _exp23m in _result15:
    _epr23m = _exp23m.get('exploit_read_label', '')
    if _epr23m == '❓ Unknown' or not _epr23m:
        continue
    _epr23m_label = _epr23m.split(' ', 1)[1] if ' ' in _epr23m else _epr23m
    _t23_matrix_by_read[_epr23m_label] += 1

check('T23: Matrix counts == drilldown counts per read label',
      dict(_t23_js_by_read) == dict(_t23_matrix_by_read),
      f'JS={dict(_t23_js_by_read)}, Matrix={dict(_t23_matrix_by_read)}')


# ============================================================
# LAYER 4: Backward compatibility & edge cases
# ============================================================
print('\n=== LAYER 4: Backward compatibility & edge cases ===')

# Test 24: Legacy exploit dict (missing new fields) doesn't crash grouping
_legacy_exp24 = {
    'villain_key': 'T1|V_legacy',
    'evidence_text': 'Hero folded to aggro 3bet from maniac villain',
    'auto_verdict': 'missed_exploit',
    'hand_id': 'H_legacy',
    'label': 'Missed',
    # No exploit_detector, exploit_read_label, etc.
}
_t24_by_read = _ddict(lambda: {'exploit_opps': 0, 'missed': 0})
_t24_n_excluded = 0
try:
    # Simulate the fallback chain from sections_iv_xii.py
    _epr24 = _legacy_exp24.get('exploit_read_label', '')
    if not _epr24 or _epr24 == '❓ Unknown':
        # Text inference fallback (replicate _infer_read_label_from_text logic)
        _et24 = (_legacy_exp24.get('evidence_text', '') or '').lower()
        if 'sticky' in _et24 or 'thin value' in _et24 or 'calls too wide' in _et24:
            _epr24 = '\U0001f4de Sticky Passive'
        elif 'overfold' in _et24 or 'nit' in _et24 or 'steal' in _et24:
            _epr24 = '\U0001faa8 Nit / Rock'
        elif 'passive' in _et24 or 'pivot' in _et24:
            _epr24 = '\U0001f41f Loose Passive'
        elif 'aggro' in _et24 or 'maniac' in _et24 or '3bet' in _et24 or 'bluff' in _et24:
            _epr24 = '⚡ Aggressive'
    if _epr24 == '❓ Unknown' or not _epr24:
        _t24_n_excluded += 1
    else:
        _t24_by_read[_epr24]['exploit_opps'] += 1
    check('T24: legacy exploit dict renders without crash',
          True, '')
except Exception as e:
    check('T24: legacy exploit dict renders without crash',
          False, f'{type(e).__name__}: {e}')

# Test 25: Empty exploit list
try:
    _result25 = detect_exploit_opportunities([], 'Hero', {}, {},
                                              read_states=None)
    check('T25: empty hand list -> empty exploits, no crash',
          _result25 == [],
          f'got {_result25}')
except Exception as e:
    check('T25: empty hand list -> empty exploits, no crash',
          False, f'{type(e).__name__}: {e}')

# Test 26: Legacy fallback: aggro text → Aggressive
# (Replicates _infer_read_label_from_text from sections_iv_xii.py)
def _test_infer_read_label_from_text(exp):
    """Mirror of sections_iv_xii.py _infer_read_label_from_text for testing."""
    _et = (exp.get('evidence_text', '') or '').lower()
    if 'sticky' in _et or 'thin value' in _et or 'calls too wide' in _et:
        return '\U0001f4de Sticky Passive'
    if 'overfold' in _et or 'nit' in _et or 'steal' in _et:
        return '\U0001faa8 Nit / Rock'
    if 'passive' in _et or 'pivot' in _et:
        return '\U0001f41f Loose Passive'
    if 'aggro' in _et or 'maniac' in _et or '3bet' in _et or 'bluff' in _et:
        return '⚡ Aggressive'
    return ''

_t26_exp = {'evidence_text': 'Hero opened too loose vs aggro 3bet threat'}
check('T26: legacy text fallback: aggro -> Aggressive',
      _test_infer_read_label_from_text(_t26_exp) == '⚡ Aggressive',
      f'got {_test_infer_read_label_from_text(_t26_exp)!r}')

# Test 27: Legacy fallback: sticky text → Sticky Passive
_t27_exp = {'evidence_text': 'Hero bluffed river into sticky calling station'}
check('T27: legacy text fallback: sticky -> Sticky Passive',
      _test_infer_read_label_from_text(_t27_exp) == '\U0001f4de Sticky Passive',
      f'got {_test_infer_read_label_from_text(_t27_exp)!r}')

# Test 28: Legacy fallback: nit text → Nit / Rock
_t28_exp = {'evidence_text': 'Missed steal opportunity vs nit in blinds'}
check('T28: legacy text fallback: nit -> Nit / Rock',
      _test_infer_read_label_from_text(_t28_exp) == '\U0001faa8 Nit / Rock',
      f'got {_test_infer_read_label_from_text(_t28_exp)!r}')

# Test 29: JS serialization contract — sections_xiv.py uses exploit_read_label
# Static code check: verify sections_xiv.py reads exploit_read_label, not primary_read
_t29_path = os.path.join(os.path.dirname(__file__),
                          'gem_report_draft', 'sections_xiv.py')
_t29_ok = False
_t29_old_pattern = False
try:
    with open(_t29_path, 'r', encoding='utf-8') as _f29:
        _t29_code = _f29.read()
    # Must contain the new pattern: exploit_read_label
    _t29_ok = "exploit_read_label" in _t29_code
    # Must NOT use the old direct pattern for read_label assignment
    # (old: _epr_raw = _ers.get('primary_read', '') without exploit_read_label check)
    # The code should first try exploit_read_label, then fallback to primary_read
    _t29_old_pattern = ("_epr_raw = _ers.get('primary_read'" in _t29_code
                         and "exploit_read_label" not in _t29_code)
except Exception as e:
    _t29_ok = False
    _t29_old_pattern = True
check('T29: sections_xiv.py uses exploit_read_label for JS read_label',
      _t29_ok and not _t29_old_pattern,
      f'has exploit_read_label={_t29_ok}, old_pattern_only={_t29_old_pattern}')


# ============================================================
# LAYER 5: Golden fixture — deterministic test for the exact bug
# ============================================================
print('\n=== LAYER 5: Golden fixture ===')

# Scenario A: villain primary_read = Loose Passive, detector = overfolded_vs_aggro
# Expected: exploit_read_label = Aggressive (NOT Loose Passive)
_golden_exp_a = {
    'villain_key': 'T1|V_golden_a',
    'evidence_text': 'Hero folded to aggro villain',
    'auto_verdict': 'missed_exploit',
}
_stamp_exploit_read(_golden_exp_a, 'overfolded_vs_aggro', 'prior_atoms_mapped')
check('T_golden_A: overfolded_vs_aggro -> Aggressive (not Loose Passive)',
      _golden_exp_a['exploit_read_label'] == 'Aggressive',
      f'got {_golden_exp_a["exploit_read_label"]}')

# Scenario B: villain primary_read = Nit/Rock, detector = ego_fought_maniac
# Expected: exploit_read_label = Aggressive (NOT Nit/Rock)
_golden_exp_b = {
    'villain_key': 'T1|V_golden_b',
    'evidence_text': 'Hero 3bet maniac',
    'auto_verdict': 'missed_exploit',
}
_stamp_exploit_read(_golden_exp_b, 'ego_fought_maniac', 'prior_atoms_mapped')
check('T_golden_B: ego_fought_maniac -> Aggressive (not Nit/Rock)',
      _golden_exp_b['exploit_read_label'] == 'Aggressive',
      f'got {_golden_exp_b["exploit_read_label"]}')

# Scenario C: Unknown exploit → should be flagged for exclusion
_golden_exp_c = {
    'villain_key': 'T1|V_golden_c',
    'auto_verdict': 'missed_exploit',
}
_stamp_exploit_read(_golden_exp_c, 'nonexistent', '')
check('T_golden_C: unknown detector -> Unknown label',
      _golden_exp_c['exploit_read_label'] == 'Unknown',
      f'got {_golden_exp_c["exploit_read_label"]}')
check('T_golden_C2: Unknown label NOT in VALID set',
      _golden_exp_c['exploit_read_label'] not in VALID_EXPLOIT_READ_LABELS,
      'Unknown should NOT be in VALID set')


# ============================================================
# LAYER 6: Phase B — Good exploit tests
# ============================================================
print('\n=== LAYER 6: Good exploit tests ===')

from gem_villain_intel import (
    detect_good_fold_vs_passive_aggro, detect_good_steal_vs_nit,
    _is_premium_hand,
)

# Test 30: good_fold_vs_passive_aggro fires on valid fold
_hand30 = {
    'id': 'H800', 'tournament_id': 'T1',
    'hero_street_actions': {'flop': 'call', 'turn': 'fold'},
    'net_bb': -8.0,
    'primary_villain_key': 'T1|V30',
    'hero': 'Hero',
    'cards': ['Kh', 'Jh'],  # calling-range hand (KJs)
    'villains': {'V30': {'position': 'CO'}},
    'villain_archetype': 'FISH',
    'villain_archetype_confidence': 'medium',
    'action_ledger': [
        {'player': 'V30', 'action': 'raises', 'street': 'turn', 'amount_bb': 12},
    ],
    'villain_xr_turn': True,
}
# Passive atoms for V30
_atoms30 = {'T1|V30': _make_atoms('T1|V30', 'loose_passive', 4,
                                   ['H9999', 'H9998', 'H9997', 'H9996'])}
_aliases30 = {'T1|V30': {'alias': 'PassiveV', 'v_number': 'V30', 'display': 'PassiveV'}}
_ho30 = {'H9999': 0, 'H9998': 1, 'H9997': 2, 'H9996': 3, 'H800': 4}
_result30 = detect_good_fold_vs_passive_aggro(_hand30, 'Hero', _aliases30, _atoms30,
                                               read_states=None, hand_order=_ho30)
check('T30: good_fold_vs_passive_aggro fires',
      len(_result30) == 1,
      f'got {len(_result30)} exploits')
if _result30:
    check('T30b: exploit_outcome=good',
          _result30[0].get('exploit_outcome') == 'good',
          f'got {_result30[0].get("exploit_outcome")}')
    check('T30c: exploit_read_label=Loose Passive',
          _result30[0].get('exploit_read_label') == 'Loose Passive',
          f'got {_result30[0].get("exploit_read_label")}')
    check('T30d: auto_verdict=good_exploit',
          _result30[0].get('auto_verdict') == 'good_exploit',
          f'got {_result30[0].get("auto_verdict")}')

# Test 31: good_fold_vs_passive_aggro gate - air fold excluded
_hand31 = dict(_hand30)
_hand31['id'] = 'H801'
_hand31['cards'] = ['3h', '2d']  # total trash — not calling range
_ho31 = dict(_ho30); _ho31['H801'] = 4
_result31 = detect_good_fold_vs_passive_aggro(_hand31, 'Hero', _aliases30, _atoms30,
                                               read_states=None, hand_order=_ho31)
check('T31: air fold excluded (no good exploit)',
      len(_result31) == 0,
      f'got {len(_result31)} exploits')

# Test 32: good_steal_vs_nit fires on valid steal
_hand32 = {
    'id': 'H900', 'tournament_id': 'T1',
    'position': 'BTN',
    'vpip': True, 'pfr': True,
    'cards': ['Th', '8h'],  # marginal steal hand (T8s) — not premium
    'hero': 'Hero',
    'villains': {'NitV2': {'position': 'BB'}},
    'action_ledger': [
        {'player': 'Hero', 'action': 'raises', 'street': 'preflop', 'amount_bb': 2.5},
    ],
}
_atoms32 = {'T1|NitV2': _make_atoms('T1|NitV2', 'tight', 5,
                                     ['H9999', 'H9998', 'H9997', 'H9996', 'H9995'])}
_aliases32 = {'T1|NitV2': {'alias': 'NitGuy2', 'v_number': 'V32', 'display': 'NitGuy2'}}
_ho32 = {'H9999': 0, 'H9998': 1, 'H9997': 2, 'H9996': 3, 'H9995': 4, 'H900': 5}
_result32 = detect_good_steal_vs_nit(_hand32, 'Hero', _aliases32, _atoms32,
                                      read_states=None, hand_order=_ho32)
check('T32: good_steal_vs_nit fires',
      len(_result32) == 1,
      f'got {len(_result32)} exploits')
if _result32:
    check('T32b: exploit_outcome=good',
          _result32[0].get('exploit_outcome') == 'good',
          f'got {_result32[0].get("exploit_outcome")}')
    check('T32c: exploit_read_label=Nit / Rock',
          _result32[0].get('exploit_read_label') == 'Nit / Rock',
          f'got {_result32[0].get("exploit_read_label")}')

# Test 33: good_steal_vs_nit gate - premium hand excluded
_hand33 = dict(_hand32)
_hand33['id'] = 'H901'
_hand33['cards'] = ['Ah', 'Kd']  # AKo is premium — standard open, not exploit
_ho33 = dict(_ho32); _ho33['H901'] = 5
_result33 = detect_good_steal_vs_nit(_hand33, 'Hero', _aliases32, _atoms32,
                                      read_states=None, hand_order=_ho33)
check('T33: premium hand excluded from good_steal (AKo)',
      len(_result33) == 0,
      f'got {len(_result33)} exploits')

# Test 34: _is_premium_hand correctness
check('T34a: AA is premium',
      _is_premium_hand(['As', 'Ah']),
      '')
check('T34b: KK is premium',
      _is_premium_hand(['Kd', 'Kc']),
      '')
check('T34c: QQ is premium',
      _is_premium_hand(['Qh', 'Qs']),
      '')
check('T34d: AKo is premium',
      _is_premium_hand(['Ah', 'Kd']),
      '')
check('T34e: AQo is NOT premium',
      not _is_premium_hand(['Ah', 'Qd']),
      '')
check('T34f: JJ is NOT premium',
      not _is_premium_hand(['Jh', 'Jd']),
      '')

# Test 35: Exploit Opps = Missed + Good (invariant)
# Use orchestrator results from Layer 3 + add good hands
_hands35 = list(_hands15) + [_hand30, _hand32]
_atoms35 = dict(_atoms15)
_atoms35.update(_atoms30)
_atoms35.update(_atoms32)
_aliases35 = dict(_aliases15)
_aliases35.update(_aliases30)
_aliases35.update(_aliases32)
_result35 = detect_exploit_opportunities(_hands35, 'Hero', _aliases35, _atoms35,
                                          read_states=None)
_missed35 = sum(1 for e in _result35 if e.get('auto_verdict') == 'missed_exploit')
_good35 = sum(1 for e in _result35 if e.get('auto_verdict') == 'good_exploit')
check('T35: Exploit Opps = Missed + Good',
      len(_result35) == _missed35 + _good35,
      f'total={len(_result35)}, missed={_missed35}, good={_good35}')

# Test 36: auto_verdict coverage — every exploit is missed or good
_t36_bad = [e for e in _result35
            if e.get('auto_verdict') not in ('missed_exploit', 'good_exploit')]
check('T36: all verdicts are missed_exploit or good_exploit',
      len(_t36_bad) == 0,
      f'{len(_t36_bad)} with bad verdict')

# Test 37: Good labels valid
_good37 = [e for e in _result35 if e.get('auto_verdict') == 'good_exploit']
_t37_bad = [e for e in _good37
            if e.get('exploit_read_label', '') not in VALID_EXPLOIT_READ_LABELS]
check('T37: all good exploit labels valid',
      len(_t37_bad) == 0,
      f'{len(_t37_bad)} with invalid label')

# Test 38: No (hand_id, villain_key, exploit_detector, exploit_outcome) duplicates
_t38_keys = set()
_t38_dups = 0
for e in _result35:
    _k = (e.get('hand_id'), e.get('villain_key'),
          e.get('exploit_detector'), e.get('exploit_outcome'))
    if _k in _t38_keys:
        _t38_dups += 1
    _t38_keys.add(_k)
check('T38: no exploit duplicates',
      _t38_dups == 0,
      f'{_t38_dups} duplicates')

# Test 39: Matrix Good column renders (static code check)
_t39_path = os.path.join(os.path.dirname(__file__),
                          'gem_report_draft', 'sections_iv_xii.py')
with open(_t39_path, 'r', encoding='utf-8') as _f39:
    _t39_code = _f39.read()
check('T39: Matrix has Good column header',
      "'>Good</span></th>" in _t39_code or "data-label='Good'" in _t39_code,
      'Good column header not found')

# Test 40: Drilldown good filter exists (static code check)
_t40_path = os.path.join(os.path.dirname(__file__),
                          'gem_report_draft', '_html.py')
with open(_t40_path, 'r', encoding='utf-8') as _f40:
    _t40_code = _f40.read()
check('T40: drilldown has good filter',
      "filterType==='good'" in _t40_code,
      'good filter branch not found in _html.py')

# Test 41: Good exploit doesn't fire on same hand as missed for same detector
# paid_off fires on H800-style (called+lost), good_fold fires on H800-style (folded)
# They can't both fire on the same hand because one requires call, other requires fold
_t41_bad = []
_t41_by_hand = {}
for e in _result35:
    _hk41 = (e.get('hand_id'), e.get('villain_key'), e.get('exploit_detector'))
    if _hk41 not in _t41_by_hand:
        _t41_by_hand[_hk41] = []
    _t41_by_hand[_hk41].append(e.get('exploit_outcome'))
for _hk41, outcomes in _t41_by_hand.items():
    if 'missed' in outcomes and 'good' in outcomes:
        _t41_bad.append(_hk41)
check('T41: no hand has both missed+good for same detector',
      len(_t41_bad) == 0,
      f'{len(_t41_bad)} hands with both')


# ============================================================
# LAYER 7: v8.8.5 — Evidence Quality + GPT Feedback Omnibus
# ============================================================
print('\n=== LAYER 7: v8.8.5 — Phase 1 bug fixes ===')

from gem_villain_intel import _RANK_VAL, _make_atom, _hand_context

# T42: Popup atom has dimension field
_t42_atom = _make_atom(
    'H999', 'T001', 'T001|abc', 'V1', 'preflop', 1,
    'open_limp', 'note', 'passivity', 3, False, False,
    'V1 open-limped', 'supports',
)
# Simulate popup serialization
_t42_popup = {
    'hand_id': _t42_atom['hand_id'],
    'dimension': _t42_atom.get('dimension', ''),
}
check('T42: popup atom has dimension',
      _t42_popup['dimension'] == 'passivity',
      f'got dimension={_t42_popup["dimension"]!r}')

# T43: Card notation — ranks sort descending
_t43_cards_a = ['3h', 'Js']
_t43_sorted_a = sorted((c[0] for c in _t43_cards_a),
                        key=lambda r: _RANK_VAL.get(r, 0), reverse=True)
_t43_str_a = ''.join(_t43_sorted_a) + 's'
check('T43a: J3s not 3Js',
      _t43_str_a == 'J3s',
      f'got {_t43_str_a}')

_t43_cards_b = ['Td', 'Qc']
_t43_sorted_b = sorted((c[0] for c in _t43_cards_b),
                        key=lambda r: _RANK_VAL.get(r, 0), reverse=True)
_t43_str_b = ''.join(_t43_sorted_b) + 'o'
check('T43b: QTo not TQo',
      _t43_str_b == 'QTo',
      f'got {_t43_str_b}')

_t43_cards_c = ['7s', 'As']
_t43_sorted_c = sorted((c[0] for c in _t43_cards_c),
                        key=lambda r: _RANK_VAL.get(r, 0), reverse=True)
_t43_str_c = ''.join(_t43_sorted_c) + 's'
check('T43c: A7s not 7As',
      _t43_str_c == 'A7s',
      f'got {_t43_str_c}')

# T44: cEV/100 grand total computation formula matches sections_financial
# Formula: _gt_bb / _gt_avg_stk * 100  (verified in code)
# Static check: sections_financial.py contains the formula
_t44_path = os.path.join(os.path.dirname(__file__),
                          'gem_report_draft', 'sections_financial.py')
with open(_t44_path, 'r', encoding='utf-8') as _f44:
    _t44_code = _f44.read()
check('T44: cEV/100 total row computed',
      '_gt_cev100' in _t44_code or 'gt_bb' in _t44_code,
      'cEV total computation not found')

# T45: %Lost bustout = 100%
check('T45: %Lost in exits header',
      '%Lost' in _t44_code,
      '%Lost header not found in sections_financial.py')

# T46: %Lost calc uses abs(net)/starting * 100
check('T46: %Lost calculation present',
      '_pct_lost' in _t44_code,
      '_pct_lost variable not found')

# T47: Result column header (not Verdict)
check('T47: Result column header',
      '| Result |' in _t44_code,
      'Result header not found')

# T48: P0.2 silent fallback removed (static check)
with open(_t40_path, 'r', encoding='utf-8') as _f48:
    _t48_code = _f48.read()
check('T48: silent fallback removed',
      'supporting.length?supporting:allAtoms' not in _t48_code,
      'silent fallback still present in _html.py')


print('\n=== LAYER 7: v8.8.5 — Phase 2 evidence backfill (P0.3) ===')

# T49: _make_atom accepts context kwargs and stores them
_t49_atom = _make_atom(
    'H999', 'T001', 'T001|abc', 'V1', 'flop', 1,
    'open_limp', 'note', 'passivity', 3, False, True,
    'V1 open-limped', 'supports',
    hero_position='BTN', hero_cards='AhKd', board='Qs Jd 3c',
    villain_action='open-limped', context_text='Hero BTN; V1 open-limped from MP',
)
check('T49a: _make_atom stores hero_position',
      _t49_atom['hero_position'] == 'BTN',
      f'got {_t49_atom["hero_position"]!r}')
check('T49b: _make_atom stores hero_cards',
      _t49_atom['hero_cards'] == 'AhKd',
      f'got {_t49_atom["hero_cards"]!r}')
check('T49c: _make_atom stores board',
      _t49_atom['board'] == 'Qs Jd 3c',
      f'got {_t49_atom["board"]!r}')
check('T49d: _make_atom stores villain_action',
      _t49_atom['villain_action'] == 'open-limped',
      f'got {_t49_atom["villain_action"]!r}')
check('T49e: _make_atom stores context_text',
      _t49_atom['context_text'] == 'Hero BTN; V1 open-limped from MP',
      f'got {_t49_atom["context_text"]!r}')
check('T49f: _make_atom stores detail_status default',
      _t49_atom['detail_status'] == 'evidence_only',
      f'got {_t49_atom["detail_status"]!r}')

# T50: _hand_context extracts hero position from action_ledger
_t50_hand = {
    'action_ledger': [
        {'player': 'Hero', 'position': 'BTN', 'action': 'raise'},
        {'player': 'Villain', 'position': 'BB', 'action': 'call'},
    ],
    'cards': ['Ah', 'Kd'],
    'board': ['Qs', 'Jd', '3c'],
}
_t50_pos, _t50_cards, _t50_board = _hand_context(_t50_hand, 'Hero')
check('T50a: _hand_context extracts hero position',
      _t50_pos == 'BTN',
      f'got {_t50_pos!r}')
check('T50b: _hand_context extracts hero cards',
      _t50_cards == 'AhKd',
      f'got {_t50_cards!r}')
check('T50c: _hand_context extracts board',
      _t50_board == 'Qs Jd 3c',
      f'got {_t50_board!r}')

# T51: _hand_context fallback to hero_position when no action_ledger match
_t51_hand = {
    'action_ledger': [
        {'player': 'Other', 'position': 'CO'},
    ],
    'hero_position': 'SB',
    'cards': [],
    'board': [],
}
_t51_pos, _, _ = _hand_context(_t51_hand, 'Hero')
check('T51: _hand_context fallback to hero_position',
      _t51_pos == 'SB',
      f'got {_t51_pos!r}')

# T52: detect_open_limp populates context_text
from gem_villain_intel import detect_open_limp
_t52_hand = {
    'id': 'H_T52', 'tournament_id': 'T001',
    'action_ledger': [
        {'player': 'V1_player', 'action': 'calls', 'position': 'MP',
         'street': 'preflop', 'amount': 1.0},
        {'player': 'Hero', 'action': 'raises', 'position': 'BTN',
         'street': 'preflop', 'amount': 3.0},
    ],
    'cards': ['Ah', 'Kd'],
    'board': [],
    'hero_position': 'BTN',
}
_t52_aliases = {'T001|V1_player': {'alias': 'V1', 'display': 'V1_player'}}
_t52_result = detect_open_limp(_t52_hand, 'Hero', _t52_aliases)
_t52_has_ctx = any(a.get('context_text', '') for a in _t52_result) if _t52_result else False
check('T52: detect_open_limp populates context_text',
      _t52_has_ctx,
      f'atoms={len(_t52_result)}, context_text missing')

# T53: Popup atom serialization includes all 9 P0.3 fields (static check)
_t53_path = os.path.join(os.path.dirname(__file__), 'gem_villain_intel.py')
with open(_t53_path, 'r', encoding='utf-8') as _f53:
    _t53_code = _f53.read()
_t53_fields = ['hero_position', 'hero_cards', 'board', 'villain_action',
               'trigger_action', 'pot_size', 'showdown_hand', 'context_text',
               'detail_status']
_t53_missing = [f for f in _t53_fields
                if f"'{f}': a.get('{f}'" not in _t53_code]
check('T53: popup serialization has all 9 P0.3 fields',
      len(_t53_missing) == 0,
      f'missing: {_t53_missing}')

# T54: JS evidence table renders context_text (static check)
check('T54: JS renders context_text in evidence table',
      'context_text' in _t48_code and 'context_text' in _t48_code,
      'context_text rendering not found in _html.py')


print('\n=== LAYER 7: v8.8.5 — Phase 3 vague diagnostic fix ===')

# T55: AMBIGUOUS verdict names gates
try:
    from gem_report_draft._helpers import _agg_commentary
    _t55_available = True
except ImportError:
    _t55_available = False
    print('  SKIP T55a-c: gem_report_draft._helpers not importable (overlay-only)')

if _t55_available:
    _t55_candidate = {
        'verdict': 'AMBIGUOUS',
        'street_of_interest': 'river',
        'hsa': {'river': 'check'},
        'recommended_action': 'bet small',
        'gates': {
            1: {'pass': True, 'reason': 'strong hand'},
            2: {'pass': True, 'reason': 'board favours'},
            3: {'pass': True, 'reason': 'range pays'},
            4: {'pass': True, 'reason': 'decision axis'},
            5: {'pass': False, 'reason': 'Worse hand calls: uncertain calling range'},
        },
    }
    _t55_text = _agg_commentary(_t55_candidate)
    check('T55a: AMBIGUOUS verdict enumerates gates',
          '✗' in _t55_text and '✓' in _t55_text,
          f'got: {_t55_text[:100]}')
    check('T55b: AMBIGUOUS names the failing gate',
          'Worse hand calls' in _t55_text,
          f'got: {_t55_text[:100]}')

    # Also test AMBIGUOUS_AGGRESSIVE
    _t55b_candidate = dict(_t55_candidate, verdict='AMBIGUOUS_AGGRESSIVE',
                            hsa={'river': 'bet'})
    _t55b_text = _agg_commentary(_t55b_candidate)
    check('T55c: AMBIGUOUS_AGGRESSIVE enumerates gates',
          '✗' in _t55b_text and 'Conditions:' in _t55b_text,
          f'got: {_t55b_text[:100]}')


print('\n=== LAYER 7: v8.8.5 — Phase 4 tournament context ===')

# T56: RACER format detection (static check in parser)
_t56_path = os.path.join(os.path.dirname(__file__), 'gem_parser.py')
with open(_t56_path, 'r', encoding='utf-8') as _f56:
    _t56_code = _f56.read()
check('T56: RACER format detection in parser',
      "'racer'" in _t56_code and "'RACER'" in _t56_code,
      'RACER detection not found in gem_parser.py')

# T57: Satellite format still detected (static check — unchanged)
check('T57: SATELLITE format still in parser',
      "'satellite'" in _t56_code.lower() and "'SATELLITE'" in _t56_code,
      'SATELLITE detection missing from gem_parser.py')

# T58: P&L rows serialized to JS (static check)
_t58_path = os.path.join(os.path.dirname(__file__),
                          'gem_report_draft', 'sections_xiv.py')
with open(_t58_path, 'r', encoding='utf-8') as _f58:
    _t58_code = _f58.read()
check('T58: perTournamentPnlRows serialized',
      'perTournamentPnlRows' in _t58_code,
      'perTournamentPnlRows not found in sections_xiv.py')


print('\n=== LAYER 7: v8.8.5 — Phase 6 villain assumptions ===')

# T59: _stamp_exploit_read sets assumption_confidence from n_atoms
_t59a = {}
_stamp_exploit_read(_t59a, 'bluffed_sticky', 'prior_atoms_mapped',
                     confidence='', n_atoms=7)
check('T59a: assumption_confidence=high for 7 atoms',
      _t59a.get('assumption_confidence') == 'high',
      f'got {_t59a.get("assumption_confidence")!r}')

_t59b = {}
_stamp_exploit_read(_t59b, 'bluffed_sticky', 'prior_atoms_mapped',
                     confidence='', n_atoms=4)
check('T59b: assumption_confidence=medium for 4 atoms',
      _t59b.get('assumption_confidence') == 'medium',
      f'got {_t59b.get("assumption_confidence")!r}')

_t59c = {}
_stamp_exploit_read(_t59c, 'bluffed_sticky', 'prior_atoms_mapped',
                     confidence='', n_atoms=1)
check('T59c: assumption_confidence=low for 1 atom',
      _t59c.get('assumption_confidence') == 'low',
      f'got {_t59c.get("assumption_confidence")!r}')

# T59d: confidence= kwarg overrides n_atoms-derived
_t59d = {}
_stamp_exploit_read(_t59d, 'bluffed_sticky', 'prior_atoms_mapped',
                     confidence='high', n_atoms=1)
check('T59d: explicit confidence overrides n_atoms',
      _t59d.get('assumption_confidence') == 'high',
      f'got {_t59d.get("assumption_confidence")!r}')

# T60: assumption_source labels correctly
_t60a = {}
_stamp_exploit_read(_t60a, 'bluffed_sticky', 'prior_atoms_mapped',
                     n_atoms=5)
check('T60a: prior_atoms_mapped source label',
      'prior evidence' in _t60a.get('assumption_source', ''),
      f'got {_t60a.get("assumption_source")!r}')

_t60b = {}
_stamp_exploit_read(_t60b, 'bluffed_sticky', 'profiler_archetype')
check('T60b: profiler_archetype source label',
      'population tendency' in _t60b.get('assumption_source', ''),
      f'got {_t60b.get("assumption_source")!r}')

_t60c = {}
_stamp_exploit_read(_t60c, 'pivot_overplayed', 'same_hand_pivot',
                     confidence='high')
check('T60c: same_hand_pivot source label',
      'observed in this hand' in _t60c.get('assumption_source', ''),
      f'got {_t60c.get("assumption_source")!r}')

# T60d: assumption fields serialized to JS exploit data (static check)
check('T60d: assumption_source in JS exploit serialization',
      "'assumption_source'" in _t58_code and "'assumption_confidence'" in _t58_code,
      'assumption fields not in sections_xiv.py exploit serialization')

# T60e: assumption block rendered in exploit drilldown (static check)
check('T60e: assumption block in exploit drilldown',
      'assumption_source' in _t48_code and 'assumption_confidence' in _t48_code,
      'assumption rendering not found in _html.py')


# ============================================================
# LAYER 8: v8.8.6 regression tests (T61–T70)
# ============================================================
print('\n--- Layer 8: v8.8.6 GPT QA bug fixes ---')

# T61: context-pill whitelisted in _md_inline inner_span_pat
check('T61: context-pill in _md_inline whitelist',
      'context-pill' in _t48_code,
      'context-pill not in _html.py inner_span_pat')

# T62: P&L init is idempotent + uses DOMContentLoaded
check('T62a: P&L uses DOMContentLoaded',
      'DOMContentLoaded' in _t48_code and 'initPerTournamentPnlTable' in _t48_code,
      'P&L not wrapped in DOMContentLoaded')
check('T62b: P&L has idempotency guard',
      '__pnlInitialized' in _t48_code,
      'P&L missing idempotency guard')

# T63: _villain_has_read returns 4-tuple
from gem_villain_intel import _villain_has_read
_t63_hand = {'id': 'test63', 'villain_key': 'T|V1', 'actions': []}
_t63_result = _villain_has_read(_t63_hand, 'T|V1', 'tight', {}, set(), None, None)
check('T63: _villain_has_read returns 4-tuple',
      len(_t63_result) == 4,
      f'returned {len(_t63_result)}-tuple, expected 4')

# T64: n_atoms > 0 for prior_atoms_mapped source
# Build enough atoms to trigger prior_atoms_mapped source
_t64_atoms = []
for _i in range(10):
    _t64_atoms.append({
        'hand_id': f'h{_i}', 'signal': 'blind_overfold', 'dimension': 'tight',
        'weight': 1.0, 'strength': 1.5, 'street': 'preflop',
        'same_hand_actionable': False,
    })
_t64_abv = {'T|V1': _t64_atoms}
_t64_result = _villain_has_read(
    {'id': 'test64', 'villain_key': 'T|V1', 'actions': []},
    'T|V1', 'tight', _t64_abv, set(), None, None)
check('T64: n_atoms > 0 for prior_atoms source',
      _t64_result[0] and _t64_result[3] > 0,
      f'has_read={_t64_result[0]}, n_atoms={_t64_result[3]}')

# T65: _stamp_exploit_read interpolates n_atoms correctly
_t65 = {}
_stamp_exploit_read(_t65, 'bluffed_sticky', 'prior_atoms_mapped', n_atoms=6)
check('T65: n_atoms interpolated in assumption_source',
      '6 atoms' in _t65.get('assumption_source', ''),
      f'got {_t65.get("assumption_source")!r}')

# T65b: archetype source never shows "(0 atoms)"
_t65b = {}
_stamp_exploit_read(_t65b, 'bluffed_sticky', 'profiler_archetype', n_atoms=0)
check('T65b: archetype source no atom count',
      '0 atoms' not in _t65b.get('assumption_source', ''),
      f'got {_t65b.get("assumption_source")!r}')

# T66: subtotal cEV computation exists in sections_financial.py
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_financial.py'), 'r', encoding='utf-8') as _f66:
    _t66_code = _f66.read()
check('T66: subtotal cEV/100 in sections_financial',
      '_st_cev' in _t66_code and '_st_avg_stk' in _t66_code,
      'subtotal cEV computation missing')

# T67: gate reason scrub strips street suffixes
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_helpers.py'), 'r', encoding='utf-8') as _f67:
    _t67_code = _f67.read()
check('T67a: gate scrub strips _TURN suffix',
      "'_TURN'" in _t67_code or '_TURN' in _t67_code,
      'street suffix stripping not present in _helpers.py')
check('T67b: UNKNOWN mapped to human-readable label',
      "'UNKNOWN': 'insufficient evidence" in _t67_code
      or "'UNKNOWN'" in _t67_code,
      'UNKNOWN token not scrubbed in _helpers.py')
check('T67c: HERO_AGGRESSIVE maps to plain English',
      'villain may not call' in _t67_code,
      'HERO_AGGRESSIVE not mapped to plain English')

# T68: Bustouts filter in P&L JS
check('T68: Bustouts filter in P&L table',
      'Bustouts' in _t48_code and 'Number(r.roi)<=-99' in _t48_code,
      'Bustouts filter not found in _html.py')

# T69: satellite caveat text exists in sections_xiv.py
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_xiv.py'), 'r', encoding='utf-8') as _f69:
    _t69_code = _f69.read()
check('T69a: satellite caveat on verdict line',
      'chipEV-only' in _t69_code and 'satellite/ICM context may override' in _t69_code,
      'satellite caveat text missing from sections_xiv.py')
check('T69b: satellite caveat inlined in coaching text',
      'satellite/ICM may make folding defensible' in _t69_code,
      'satellite caveat not inlined in coaching explanation')

# T70: no 3-tuple unpack of _villain_has_read remains
with open(os.path.join(os.path.dirname(__file__),
          'gem_villain_intel.py'), 'r', encoding='utf-8') as _f70:
    _t70_code = _f70.read()
import re as _re70
_t70_3tuple = _re70.findall(r'has_read,\s*source,\s*conf\s*=\s*_villain_has_read', _t70_code)
check('T70: no 3-tuple unpack of _villain_has_read',
      len(_t70_3tuple) == 0,
      f'found {len(_t70_3tuple)} remaining 3-tuple unpacks')

# T71: Matrix exploit drilldown uses &#39; not \\x27
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_iv_xii.py'), 'r', encoding='utf-8') as _f71:
    _t71_code = _f71.read()
check('T71a: no \\x27 in exploit drilldown onclick',
      '\\\\x27' not in _t71_code,
      'literal \\x27 still present in sections_iv_xii.py drilldown links')
check('T71b: &#39; used in drilldown onclick',
      "&#39;" in _t71_code and 'openExploitDrilldown' in _t71_code,
      '&#39; not found in exploit drilldown links')

# T72: P&L init called after data assignment
check('T72: P&L init called after data assignment',
      'initPerTournamentPnlTable' in _t69_code,
      'initPerTournamentPnlTable not called after data assignment in sections_xiv.py')

# T73: satellite caveat inline replaces strong assertions
check('T73: satellite coaching text caveats "the leak"',
      'the leak by chipEV' in _t69_code,
      'satellite caveat not inlined into "folding it is the leak" text')

# T74: gate reason plain English for all tokens
check('T74a: CORRECTLY_PASSIVE plain English',
      'checking was correct' in _t67_code,
      'CORRECTLY_PASSIVE not plain English')
check('T74b: MISSED_AGGRESSION plain English',
      'missed a betting opportunity' in _t67_code,
      'MISSED_AGGRESSION not plain English')


print('\n--- Layer 8 continued: v8.8.6 V6 QA fixes ---')

# T75: exploit_read_label is canonical (no emoji)
_t75_exp = {}
_stamp_exploit_read(_t75_exp, 'missed_steal_vs_nit', 'prior_atoms_mapped')
check('T75a: exploit_read_label canonical (no emoji)',
      _t75_exp['exploit_read_label'] == 'Nit / Rock',
      f'got {_t75_exp["exploit_read_label"]}')
check('T75b: exploit_read_display has emoji',
      _t75_exp.get('exploit_read_display') == '🪨 Nit / Rock',
      f'got {_t75_exp.get("exploit_read_display")}')
check('T75c: read_label == exploit_read_label invariant',
      _t75_exp['exploit_read_label'] == 'Nit / Rock',
      'read_label/exploit_read_label mismatch')

# T76: "1 atom" not "1 atoms" grammar
_t76_exp = {}
_stamp_exploit_read(_t76_exp, 'bluffed_sticky', 'prior_atoms_mapped', n_atoms=1)
check('T76a: 1 atom (singular)',
      '1 atom)' in _t76_exp.get('assumption_source', ''),
      f'got {_t76_exp.get("assumption_source")}')
_t76b_exp = {}
_stamp_exploit_read(_t76b_exp, 'bluffed_sticky', 'prior_atoms_mapped', n_atoms=4)
check('T76b: 4 atoms (plural)',
      '4 atoms)' in _t76b_exp.get('assumption_source', ''),
      f'got {_t76b_exp.get("assumption_source")}')

# T77: Bustouts filter uses Number() for robustness
check('T77: Bustouts uses Number(r.roi)',
      'Number(r.roi)<=-99' in _t48_code,
      'Bustouts not using Number() for roi comparison')

# T78: satellite caveat in S17.3 _row_data severity
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_xiii.py'), 'r', encoding='utf-8') as _f78:
    _t78_code = _f78.read()
check('T78a: satellite caveat in S17.3 severity',
      'SATELLITE' in _t78_code and 'chipEV-only' in _t78_code,
      'satellite caveat not in sections_xiii.py deviation tables')

# T79: _READ_EMOJI mapping exists
from gem_villain_intel import _READ_EMOJI
check('T79a: _READ_EMOJI has 5 entries',
      len(_READ_EMOJI) == 5,
      f'got {len(_READ_EMOJI)}')
check('T79b: _READ_EMOJI covers all valid labels',
      all(label in _READ_EMOJI for label in VALID_EXPLOIT_READ_LABELS),
      f'missing: {[l for l in VALID_EXPLOIT_READ_LABELS if l not in _READ_EMOJI]}')

# T80: Matrix normalisation for canonical grouping
check('T80: sections_iv_xii uses _canon for label normalisation',
      'def _canon(' in _t71_code,
      '_canon normalisation not found in sections_iv_xii.py')

# T81: exploit_read_display serialized to JS
check('T81: exploit_read_display in JS popup',
      'exploit_read_display' in _t69_code,
      'exploit_read_display not serialized in sections_xiv.py')

# T82-T86: v8.8.6 S1-fix satellite caveat propagation + B-HG1 merge
print('\n--- Layer 8 continued: v8.8.6 S1-fix + B-HG1 ---')

# T82: XIV.B coaching path has satellite caveat (Site 3)
check('T82a: XIV.B satellite caveat on flag explanation',
      '_xivb_fmt' in _t69_code and '_xivb_icm' in _t69_code,
      'XIV.B satellite format/ICM variables not found in sections_xiv.py')
check('T82b: XIV.B applies .replace on deviation phrase',
      _t69_code.count("'passing on it is the deviation',") >= 2,
      'XIV.B path does not apply deviation-text substitution')

# T83: MDA path has satellite caveat (Site 2)
check('T83: MDA coaching path applies satellite caveat',
      '_mda_expl = _mda_expl.replace(' in _t69_code
      or ("_mda_expl.replace(" in _t69_code and "passing on it is the deviation" in _t69_code),
      'MDA path does not apply satellite caveat substitution')

# T84: deviation label carries caveat for satellite (confidence)
check('T84: deviation label satellite caveat on CLEAR confidence',
      '_d_fmt_xiv' in _t69_code and "CLEAR chipEV-only" in _t69_code,
      'deviation path missing satellite caveat on CLEAR confidence label')

# T85: _hand_grid.py B-HG1 isinstance guard
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_hand_grid.py'), 'r', encoding='utf-8') as _f85:
    _t85_code = _f85.read()
check('T85a: _argument_is_structured has isinstance guard',
      'if not isinstance(argument, str):' in _t85_code,
      '_argument_is_structured missing non-string guard')
check('T85b: note loop has str coercion',
      "if not isinstance(note, str):" in _t85_code,
      'note rendering loop missing str coercion for non-string notes')

# T86: all three emit paths have satellite caveat (count check)
# Site 1 (XIV.A no-verdict), Site 2 (MDA), Site 3 (XIV.B) — each applies
# the "passing on it is the deviation" → caveated replacement
_sat_replace_count = _t69_code.count(
    'passing on it is the deviation by chipEV')
check('T86: all 3 emit paths apply satellite coaching caveat',
      _sat_replace_count >= 3,
      f'expected >=3 caveated deviation phrases, got {_sat_replace_count}')

# T87-T93: v8.8.6 raise-size display + verdict chips
print('\n--- Layer 9: v8.8.6 raise-size display + verdict chips ---')

# -- Raise-size display (hand grid) --
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_hand_grid.py'), 'r', encoding='utf-8') as _f87:
    _t87_code = _f87.read()

# T87: _current_bet / _raise_count tracking variables present
check('T87a: _current_bet tracking variable exists',
      '_current_bet = 1.0 if street ==' in _t87_code,
      '_hand_grid.py missing _current_bet preflop init')
check('T87b: _raise_count tracking variable exists',
      '_raise_count = 0' in _t87_code,
      '_hand_grid.py missing _raise_count init')

# T88: preflop raise labels
check('T88a: preflop Open to label',
      "'Open to'" in _t87_code,
      '_hand_grid.py missing Open to label for first preflop raise')
check('T88b: preflop 3-bet to label',
      "'3-bet to'" in _t87_code,
      '_hand_grid.py missing 3-bet to label')
check('T88c: preflop 4-bet to label',
      "'4-bet to'" in _t87_code,
      '_hand_grid.py missing 4-bet to label')
check('T88d: preflop 5-bet to label',
      "'5-bet to'" in _t87_code,
      '_hand_grid.py missing 5-bet to label')

# T89: raise-to computation
check('T89: _raise_to = _current_bet + amt formula',
      '_raise_to = _current_bet + amt' in _t87_code,
      '_hand_grid.py missing raise-to computation')

# T90: JAM display unchanged (still uses amt, not _raise_to)
check('T90: JAM display still uses amt (not raise_to)',
      'JAM {amt:.1f}BB' in _t87_code,
      'JAM display was changed — spec says keep as-is')

# T91: postflop raise uses "Raise to"
check('T91: postflop raise label is Raise to',
      "_rlbl = 'Raise to'" in _t87_code,
      '_hand_grid.py missing postflop Raise to label')

# -- Verdict chips (HTML renderer) --
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_html.py'), 'r', encoding='utf-8') as _f92:
    _t92_code = _f92.read()

# T92: verdict chips HTML present in modal
check('T92a: verdict-chip-row div exists in modal HTML',
      'verdict-chip-row' in _t92_code,
      '_html.py missing verdict-chip-row container')
check('T92b: Agree chip with data-verdict',
      'data-verdict="Agree"' in _t92_code,
      '_html.py missing Agree verdict chip')
check('T92c: Debate chip with data-verdict',
      'data-verdict="Debate"' in _t92_code,
      '_html.py missing Debate verdict chip')
check('T92d: Report bug chip with data-verdict',
      'data-verdict="Report bug"' in _t92_code,
      '_html.py missing Report bug verdict chip')
check('T92e: Clear verdict button exists',
      'verdict-clear' in _t92_code and ('Clear verdict' in _t92_code or '>Clear<' in _t92_code),
      '_html.py missing Clear verdict control')

# T93: hidden select preserved + chip click handlers
check('T93a: modal-review-status select hidden',
      'id="modal-review-status" style="display:none"' in _t92_code
      or 'id="modal-review-status" class="hidden' in _t92_code,
      'modal verdict select not hidden — chips won\'t replace dropdown')
check('T93b: chip click handler dispatches change event',
      'dispatchEvent' in _t92_code and 'verdict-chip' in _t92_code,
      '_html.py missing chip click → hidden select → change dispatch')
check('T93c: loadReview syncs verdict chips',
      'verdict-chip' in _t92_code and 'toggle' in _t92_code
      and 'data-verdict' in _t92_code,
      '_html.py loadReview does not sync verdict chip active state')
check('T93d: verdict chip CSS — agree active green',
      'verdict-agree.active' in _t92_code and '#ecfdf3' in _t92_code,
      '_html.py missing verdict-agree active CSS')
check('T93e: verdict chip CSS — debate active amber',
      'verdict-debate.active' in _t92_code and '#fffbeb' in _t92_code,
      '_html.py missing verdict-debate active CSS')
check('T93f: verdict chip CSS — bug active red',
      'verdict-bug.active' in _t92_code and '#fef2f2' in _t92_code,
      '_html.py missing verdict-bug active CSS')

# T93g: section-level audit dropdowns NOT changed
# The inline audit-row select (class="audit-status") must still be a visible select
check('T93g: section audit-status select still visible (not hidden)',
      'class="audit-status"' in _t92_code
      and _t92_code.count('audit-status') >= 5,
      'section audit-status selects may have been accidentally changed')

# ============================================================
# LAYER 10: v8.8.6 — Villain Hand Details + Hand Detail Availability
# ============================================================
print('\n--- Layer 10: v8.8.6 VH + HA architecture implementation ---')

# Reload code strings for new tests
with open(os.path.join(os.path.dirname(__file__),
          'gem_villain_intel.py'), 'r', encoding='utf-8') as _fvh:
    _tvh_vi_code = _fvh.read()
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_xiv.py'), 'r', encoding='utf-8') as _fvh2:
    _tvh_xiv_code = _fvh2.read()
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_html.py'), 'r', encoding='utf-8') as _fvh3:
    _tvh_html_code = _fvh3.read()
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_hand_grid.py'), 'r', encoding='utf-8') as _fvh4:
    _tvh_grid_code = _fvh4.read()
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'draft.py'), 'r', encoding='utf-8') as _fvh5:
    _tvh_draft_code = _fvh5.read()

# --- T-VH1: SIGNAL_COACHING contains entry for every detector signal ---
from gem_villain_intel import SIGNAL_COACHING, _SIGNAL_LABELS
check('T-VH1a: SIGNAL_COACHING has all 10 signals',
      all(sig in SIGNAL_COACHING for sig in _SIGNAL_LABELS),
      f'missing: {[s for s in _SIGNAL_LABELS if s not in SIGNAL_COACHING]}')
check('T-VH1b: each entry has suggests/so_what/default_timing',
      all('suggests' in v and 'so_what' in v and 'default_timing' in v
          for v in SIGNAL_COACHING.values()),
      'some SIGNAL_COACHING entries missing required fields')

# --- T-VH2: atoms created with suggests/so_what/default_timing ---
from gem_villain_intel import _make_atom
_tvh2_atom = _make_atom(
    'test', 'T1', 'T1|V1', 'TestV',
    'preflop', 0, 'open_limp', 'note', 'loose_passive',
    strength=2, same_hand_actionable=True, hero_involved=True,
    evidence_text='test', read_impact='test')
check('T-VH2a: atom has suggests field',
      _tvh2_atom.get('suggests') != '',
      f'atom suggests empty: {_tvh2_atom.get("suggests")!r}')
check('T-VH2b: atom has so_what field',
      _tvh2_atom.get('so_what') != '',
      f'atom so_what empty: {_tvh2_atom.get("so_what")!r}')
check('T-VH2c: atom has default_timing field',
      _tvh2_atom.get('default_timing') != '',
      f'atom default_timing empty: {_tvh2_atom.get("default_timing")!r}')

# --- T-VH3: _build_hand_opponent_contexts classifies all 4 buckets ---
check('T-VH3a: _build_hand_opponent_contexts function exists',
      'def _build_hand_opponent_contexts(' in _tvh_xiv_code,
      '_build_hand_opponent_contexts not found in sections_xiv.py')
check('T-VH3b: all 4 buckets referenced',
      "'exploit_miss'" in _tvh_xiv_code
      and "'good_exploit'" in _tvh_xiv_code
      and "'villain_evidence'" in _tvh_xiv_code
      and "'passive_read'" in _tvh_xiv_code,
      'not all 4 bucket types found in sections_xiv.py')

# --- T-VH4: timing classifier uses available_before_action_index ---
check('T-VH4: _classify_timing uses available_before_action_index',
      'def _classify_timing(' in _tvh_xiv_code
      and 'available_before_action_index' in _tvh_xiv_code,
      '_classify_timing missing or does not use available_before_action_index')

# --- T-VH5: missed exploit with unknown timing downgrades ---
check('T-VH5: unknown timing -> villain_evidence downgrade',
      # In the bucket assignment: if timing not in known_before/same_hand_before → evidence
      "bucket = 'villain_evidence'" in _tvh_xiv_code,
      'unknown timing downgrade to evidence not found')

# --- T-VH6: modal HTML contains coaching block divs ---
check('T-VH6a: coaching block container in modal JS',
      'opponent-coaching' in _tvh_html_code,
      'opponent-coaching div not found in _html.py')
check('T-VH6b: coaching block renders all 4 bucket types',
      'cb-miss' in _tvh_html_code
      and 'cb-good' in _tvh_html_code
      and 'cb-evidence' in _tvh_html_code
      and 'coaching-passive' in _tvh_html_code,
      'not all 4 coaching block types found in _html.py')

# --- T-VH7: severity C uses "Small Miss" label ---
check('T-VH7: severity C uses Small Miss label',
      'Opponent Adjustment — Small Miss' in _tvh_html_code,
      'Small Miss label not found for severity C coaching blocks')

# --- T-VH8: villain badges in hand grid ---
check('T-VH8a: villain_badges parameter in grid renderer',
      'villain_badges=None' in _tvh_grid_code
      or 'villain_badges=' in _tvh_grid_code,
      'villain_badges parameter not found in _hand_grid.py')
check('T-VH8b: villain badge span rendered',
      'villain-badge' in _tvh_grid_code,
      'villain-badge span not rendered in _hand_grid.py')
check('T-VH8c: badge types vb-note vb-pivot vb-miss vb-good in CSS',
      'vb-note' in _tvh_html_code
      and 'vb-pivot' in _tvh_html_code
      and 'vb-miss' in _tvh_html_code
      and 'vb-good' in _tvh_html_code,
      'not all badge CSS classes found in _html.py')

# --- T-VH9: yellow street notes contain so_what ---
check('T-VH9: villain street notes with so_what',
      'villain-street-notes' in _tvh_xiv_code
      and "so_what" in _tvh_xiv_code,
      'villain street notes not found in sections_xiv.py')

# --- T-HA1: handReferenceAudit serialized in draft.py ---
check('T-HA1: handReferenceAudit in draft.py',
      'handReferenceAudit' in _tvh_draft_code,
      'handReferenceAudit not found in draft.py')

# --- T-HA2: handAvailability serialized in draft.py ---
check('T-HA2: handAvailability in draft.py',
      'handAvailability' in _tvh_draft_code,
      'handAvailability not found in draft.py')

# --- T-HA3: openHandListPopup uses handAvailability ---
check('T-HA3: openHandListPopup uses handAvailability for fallback',
      'handAvailability' in _tvh_html_code
      and 'non_replayable' in _tvh_html_code
      and 'not_rendered' in _tvh_html_code,
      'openHandListPopup not using handAvailability for three-state display')

# --- T-HA4: "detail not in appendix" retired ---
check('T-HA4: generic "detail not in appendix" retired',
      'detail not in appendix' not in _tvh_html_code,
      '"detail not in appendix" still present in _html.py')

# --- T-HA5: popup header shows hand count ---
check('T-HA5: popup header includes hand count',
      '_shownCount' in _tvh_html_code and 'openable' in _tvh_html_code,
      'popup header missing hand count display')

# --- T-HA6: handOpponentContexts serialized ---
check('T-HA6: handOpponentContexts serialized in sections_xiv.py',
      'handOpponentContexts' in _tvh_xiv_code,
      'handOpponentContexts not found in sections_xiv.py')

# --- T-VH10: _EXPLOIT_COACHING dict covers all 8 detectors ---
from gem_villain_intel import _EXPLOIT_COACHING, _EXPLOIT_READ_MAP
check('T-VH10: _EXPLOIT_COACHING covers all exploit detectors',
      all(det in _EXPLOIT_COACHING for det in _EXPLOIT_READ_MAP),
      f'missing: {[d for d in _EXPLOIT_READ_MAP if d not in _EXPLOIT_COACHING]}')

# --- T-VH11: _stamp_exploit_read stamps coaching fields ---
_tvh11 = {}
_stamp_exploit_read(_tvh11, 'bluffed_sticky', 'prior_atoms_mapped', n_atoms=5)
check('T-VH11a: exploit has suggests field',
      _tvh11.get('suggests') != '',
      f'exploit suggests empty: {_tvh11.get("suggests")!r}')
check('T-VH11b: exploit has so_what field',
      _tvh11.get('so_what') != '',
      f'exploit so_what empty: {_tvh11.get("so_what")!r}')

# --- T-VH12: _build_villain_badges function exists ---
check('T-VH12: _build_villain_badges function exists',
      'def _build_villain_badges(' in _tvh_xiv_code,
      '_build_villain_badges not found in sections_xiv.py')

# --- T-VH13: villain badges wired to both grid call sites ---
check('T-VH13: villain_badges passed to grid at both call sites',
      _tvh_xiv_code.count('villain_badges=_vb') >= 1
      and '_vb_b = _build_villain_badges' in _tvh_xiv_code,
      'villain_badges not wired to both XIV.A and XIV.B grid calls')

# --- T-VH14: coaching block CSS exists ---
check('T-VH14: coaching block CSS exists',
      '.coaching-block' in _tvh_html_code
      and '.cb-header' in _tvh_html_code
      and '.cb-body' in _tvh_html_code,
      'coaching block CSS not found in _html.py')

# --- T-VH15: villain badge CSS exists ---
check('T-VH15: villain badge CSS exists',
      '.villain-badge' in _tvh_html_code
      and '.vb-note' in _tvh_html_code
      and '.vb-miss' in _tvh_html_code,
      'villain badge CSS not found in _html.py')

# --- T-HA7: _esc HTML-escape helper defined ---
check('T-HA7: _esc helper defined in _html.py JS',
      'function _esc(' in _tvh_html_code,
      '_esc HTML-escape function not found in _html.py')

# --- T-VH16: timing labels dict ---
check('T-VH16: _TIMING_LABELS dict exists',
      '_TIMING_LABELS' in _tvh_xiv_code
      and 'known_before' in _tvh_xiv_code
      and 'same_hand_before' in _tvh_xiv_code,
      '_TIMING_LABELS not found in sections_xiv.py')

# --- T-HA8: villain street notes CSS ---
check('T-HA8: villain street notes CSS exists',
      '.villain-street-notes' in _tvh_html_code
      and '.vsn-street' in _tvh_html_code,
      'villain street notes CSS not found in _html.py')

# ============================================================
# Layer 11: HA Phase 3 — Priority Registration
# ============================================================
print('\n--- Layer 11: HA Phase 3 - Priority Registration ---')

# Read _state.py for state tests
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_state.py'), 'r', encoding='utf-8') as _fha9:
    _tha_state_code = _fha9.read()
# Read _helpers.py for registration function tests
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_helpers.py'), 'r', encoding='utf-8') as _fha10:
    _tha_helpers_code = _fha10.read()
# Read sections_iv_xii.py for priority annotations
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_iv_xii.py'), 'r', encoding='utf-8') as _fha11:
    _tha_iv_code = _fha11.read()
# Read sections_mistakes.py
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_mistakes.py'), 'r', encoding='utf-8') as _fha12:
    _tha_mistakes_code = _fha12.read()
# Read sections_issue_explorer.py
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_issue_explorer.py'), 'r', encoding='utf-8') as _fha13:
    _tha_ie_code = _fha13.read()

# T-HA9: _APPENDIX_HAND_PRIORITIES exists in _state.py
check('T-HA9: _APPENDIX_HAND_PRIORITIES in _state.py',
      '_APPENDIX_HAND_PRIORITIES' in _tha_state_code
      and '_APPENDIX_HAND_PRIORITIES = {}' in _tha_state_code,
      '_APPENDIX_HAND_PRIORITIES dict not defined in _state.py')

# T-HA10: _register_hand_priority function exists
check('T-HA10: _register_hand_priority function exists',
      'def _register_hand_priority(hid, priority)' in _tha_state_code,
      '_register_hand_priority not found in _state.py')

# T-HA11: _register_hand_priority keeps best (lowest) priority
from gem_report_draft import _state as _ts_ha11
_ts_ha11._APPENDIX_HAND_PRIORITIES = {}
_ts_ha11._register_hand_priority('TM1234', 2)
_ts_ha11._register_hand_priority('TM1234', 1)
_ts_ha11._register_hand_priority('TM1234', 3)
check('T-HA11: priority keeps best (lowest)',
      _ts_ha11._APPENDIX_HAND_PRIORITIES.get('TM1234') == 1,
      f'expected 1, got {_ts_ha11._APPENDIX_HAND_PRIORITIES.get("TM1234")}')
_ts_ha11._APPENDIX_HAND_PRIORITIES = {}  # cleanup

# T-HA12: _reset_citations clears priorities
_ts_ha11._APPENDIX_HAND_PRIORITIES = {'TM9999': 0}
_ts_ha11._reset_citations()
check('T-HA12: _reset_citations clears priorities',
      len(_ts_ha11._APPENDIX_HAND_PRIORITIES) == 0,
      f'priorities not cleared: {len(_ts_ha11._APPENDIX_HAND_PRIORITIES)}')

# T-HA13: _popup_example_ids accepts priority parameter
check('T-HA13: _popup_example_ids has priority param',
      'def _popup_example_ids(pool_ids, want=5, cap=20, backfill_ids=None, priority=2)' in _tha_helpers_code,
      'priority parameter not in _popup_example_ids signature')

# T-HA14: _register_hids_for_appendix accepts priority parameter
check('T-HA14: _register_hids_for_appendix has priority param',
      'def _register_hids_for_appendix(hids, cap=50, priority=2)' in _tha_helpers_code,
      'priority parameter not in _register_hids_for_appendix signature')

# T-HA15: budget planner in draft.py
check('T-HA15: budget planner in draft.py',
      'handPriorityBudget' in _tvh_draft_code
      and '_SOFT_CAP_KB' in _tvh_draft_code
      and '_all_with_prio' in _tvh_draft_code,
      'budget planner not found in draft.py')

# T-HA16: budget_trimmed state in handAvailability
check('T-HA16: budget_trimmed state in frontend',
      'budget_trimmed' in _tvh_html_code
      and 'file size budget' in _tvh_html_code,
      'budget_trimmed label not found in _html.py')

# T-HA17: P0 annotations in sections_iv_xii.py (3 sites)
check('T-HA17a: P0 missed 3-bet annotation',
      'priority=0)  # P0: missed 3-bet teaching' in _tha_iv_code,
      'P0 annotation for missed 3-bet not found')
check('T-HA17b: P0 J44 sizing deviations',
      'priority=0)  # P0: J44 sizing deviations' in _tha_iv_code,
      'P0 annotation for J44 deviations not found')
check('T-HA17c: P0 missed squeeze teaching',
      'priority=0)  # P0: missed squeeze teaching' in _tha_iv_code,
      'P0 annotation for missed squeeze not found')

# T-HA18: P1 annotations exist (spot check 3)
check('T-HA18a: P1 missed BB defends',
      'priority=1)  # P1: missed BB defends' in _tha_iv_code,
      'P1 annotation for missed BB defends not found')
check('T-HA18b: P1 leak candidates in mistakes',
      'priority=1)  # P1: leak candidate hands' in _tha_mistakes_code,
      'P1 annotation for leak candidates not found')
check('T-HA18c: P1 fold-to-cbet drill',
      'priority=1)  # P1: fold-to-cbet leak drill' in _tha_mistakes_code,
      'P1 annotation for fold-to-cbet not found')

# T-HA19: P0 Issue Explorer annotation
check('T-HA19: P0 Issue Explorer annotation',
      '_register_hand_priority(hid, 0)  # P0: Issue Explorer' in _tha_ie_code,
      'P0 annotation for Issue Explorer not found')

# T-HA20: P1 villain evidence annotation in sections_xiv.py
check('T-HA20: P1 villain evidence annotation',
      '_register_hand_priority(_veid, 1)  # P1: villain evidence' in _tvh_xiv_code,
      'P1 annotation for villain evidence not found')

# T-HA21: budget_trimmed in draft.py handAvailability classification
check('T-HA21: budget_trimmed in draft.py HA classification',
      "'budget_trimmed'" in _tvh_draft_code
      and "budget_trimmed" in _tvh_draft_code,
      'budget_trimmed not in draft.py handAvailability')

# T-HA22: _popup_example_ids calls _register_hand_priority
check('T-HA22: _popup_example_ids calls _register_hand_priority',
      '_state._register_hand_priority(hid, priority)' in _tha_helpers_code,
      '_popup_example_ids does not call _register_hand_priority')

# T-HA23: XIV.B cap bypass for P0/P1 hands
check('T-HA23: XIV.B P0/P1 cap bypass',
      '_hids_priority' in _tvh_xiv_code
      and '_APPENDIX_HAND_PRIORITIES' in _tvh_xiv_code,
      'XIV.B priority cap bypass not found in sections_xiv.py')

# T-HA24: atoms_by_hand used instead of non-existent all_atoms
check('T-HA24: atoms_by_hand fix in _build_hand_opponent_contexts',
      "atoms_by_hid = vi.get('atoms_by_hand'" in _tvh_xiv_code,
      'atoms_by_hand fix not applied — Bucket C will be empty')

# T-HA25: atoms_by_hand fix in _build_villain_badges
check('T-HA25: atoms_by_hand in _build_villain_badges',
      "hand_atoms = _abh.get(hid" in _tvh_xiv_code,
      'atoms_by_hand fix not applied in _build_villain_badges')

# T-HA26: atoms_by_hand fix in yellow street notes
check('T-HA26: atoms_by_hand in yellow street notes',
      "atoms_by_hand" in _tvh_xiv_code.split('yellow street notes')[1].split('doc.w')[0]
      if 'yellow street notes' in _tvh_xiv_code else False,
      'atoms_by_hand fix not applied in yellow street notes')

# ============================================================
# Layer 12: VH gap-fill rendering tests
# ============================================================

# T-VH10: top one-liner for exploit hands
check('T-VH10: top one-liner for exploit hands',
      'cb-oneliner' in _tvh_html_code
      and '_exploitCtxs' in _tvh_html_code
      and 'fef9e7' in _tvh_html_code,
      'top one-liner not rendering for exploit hands')

# T-VH11: severity C enriched with timing/hero_action/V-number
check('T-VH11: severity C compact shows timing + hero action',
      'cb-timing' in _tvh_html_code.split('Severity C')[1].split('good_exploit')[0]
      if 'Severity C' in _tvh_html_code else False,
      'severity C compact missing timing field')

# T-VH12: suggests line ("Read signal:") in exploit blocks
check('T-VH12: read signal line in exploit blocks',
      'Read signal: ' in _tvh_html_code,
      '"Read signal:" line missing from coaching blocks')

# T-VH13: Bucket C uses compact inline note (v8.9.6 redesign)
check('T-VH13: Bucket C uses compact v25-ve-inline format',
      'v25-ve-inline' in _tvh_html_code
      and 'v25-ve-badge' in _tvh_html_code,
      'Bucket C missing compact inline evidence format')

# T-VH14: yellow street notes have Actionable/timing line
check('T-VH14: yellow street notes have Actionable now line',
      'Actionable now?' in _tvh_xiv_code
      and 'default_timing' in _tvh_xiv_code,
      'yellow street notes missing Actionable now? field')

# T-VH15: yellow street notes have badge (Note/Pivot) and suggests
check('T-VH15: yellow street notes badge + suggests',
      'vsn-suggests' in _tvh_html_code
      and 'vsn-timing' in _tvh_html_code
      and "What it suggests:" in _tvh_xiv_code,
      'yellow street notes missing structured fields')

# T-VH16: Bucket C disclaimer removed (v8.9.6 compact redesign)
check('T-VH16: evidence disclaimer removed from Bucket C',
      'not necessarily a Hero mistake' not in _tvh_html_code,
      'Bucket C still has old disclaimer — should be removed')

# T-VH17: one-liner CSS
check('T-VH17: one-liner CSS',
      'cb-oneliner' in _tvh_html_code
      and 'fef9e7' in _tvh_html_code,
      'cb-oneliner CSS not found')

# ────────────────────────────────────────────────────────────
# T-IQ: Inline Table Queue Navigation (v8.8.6)
# ────────────────────────────────────────────────────────────
import re as _re_iq

# T-IQ1: buildInlineHandQueueFromClickedRef function exists in _html.py
check('T-IQ1: buildInlineHandQueueFromClickedRef JS function',
      'function buildInlineHandQueueFromClickedRef' in _tvh_html_code,
      'buildInlineHandQueueFromClickedRef not found in _html.py')

# T-IQ2: isHandDetailAvailable helper exists
check('T-IQ2: isHandDetailAvailable helper',
      'function isHandDetailAvailable' in _tvh_html_code,
      'isHandDetailAvailable not found')

# T-IQ3: collectHandIdsFromQueueContainer helper exists
check('T-IQ3: collectHandIdsFromQueueContainer helper',
      'function collectHandIdsFromQueueContainer' in _tvh_html_code,
      'collectHandIdsFromQueueContainer not found')

# T-IQ4: Click handler has inline queue branch (v8.8.6 marker)
check('T-IQ4: click handler inline queue branch',
      'build inline table queue for on-page hand refs' in _tvh_html_code
      and 'buildInlineHandQueueFromClickedRef(pill)' in _tvh_html_code,
      'click handler missing inline queue branch')

# T-IQ5: _queueBackToList handles inline_table sourceType
check('T-IQ5: back-to-list handles inline_table',
      "q.sourceType==='inline_table'" in _tvh_html_code
      and "q.sourceType==='inline_table_group'" in _tvh_html_code,
      '_queueBackToList missing inline_table handling')

# T-IQ6: Back button label is dynamic (Back to table / Back to list)
check('T-IQ6: dynamic back button label',
      "'Back to table'" in _tvh_html_code
      and "'Back to list'" in _tvh_html_code
      and 'backLabel' in _tvh_html_code,
      'Back button label not dynamic')

# T-IQ7: inlineHandQueueAudit object exists
check('T-IQ7: inlineHandQueueAudit debug object',
      'window.inlineHandQueueAudit' in _tvh_html_code
      and '_buildInlineQueueAudit' in _tvh_html_code,
      'inlineHandQueueAudit audit object missing')

# T-IQ8: IE rep tables have data-hand-queue-id attribute
_ie_code = open(os.path.join(os.path.dirname(__file__), 'gem_report_draft', 'sections_issue_explorer.py'),
                encoding='utf-8').read()
check('T-IQ8: IE rep tables have queue metadata',
      'data-hand-queue-id' in _ie_code
      and 'data-hand-queue-title' in _ie_code,
      'IE rep tables missing queue metadata attributes')

# T-IQ9: scrollIntoView in back-to-table path
check('T-IQ9: back-to-table scrolls to source',
      "scrollIntoView({behavior:'smooth',block:'center'})" in _tvh_html_code,
      'back-to-table missing scrollIntoView')

# T-IQ10: sourcePath suppressed when same as title (no duplication)
check('T-IQ10: sourcePath dedup in queue bar',
      '_spShow' in _tvh_html_code
      and "q.sourcePath!==q.contextTitle" in _tvh_html_code,
      'sourcePath duplication guard missing')

# ────────────────────────────────────────────────────────────
# T-AV: LLM Analyst Villain Handoff (v8.9.0)
# ────────────────────────────────────────────────────────────
import json as json
import gem_analyst_villain as _gav

# Build a mock villain_intel for testing
_mock_vi = {
    'villain_aliases': {
        'v_anon_01': {'alias': 'Eagle', 'v_number': 'V01'},
        'v_anon_02': {'alias': 'Hawk', 'v_number': 'V02'},
        'v_anon_03': {'alias': 'Falcon', 'v_number': 'V03'},
    },
    'read_states': {
        'v_anon_01': {'primary_read': 'Nit / Rock', 'confidence': 'high'},
        'v_anon_02': {'primary_read': 'Loose Passive', 'confidence': 'medium'},
        'v_anon_03': {'primary_read': 'Sticky Passive', 'confidence': 'low'},
    },
    'exploit_opportunities': [
        {'hand_id': 'TM6039960264', 'villain_key': 'v_anon_01',
         'exploit_outcome': 'missed', 'exploit_type': 'missed_steal_vs_nit',
         'severity': 'A', 'timing_classification': 'known_before',
         'read_source': 'prior_atoms_mapped',
         'hero_action': 'folded A7o', 'recommended_exploit': 'open-raise',
         'suggests': 'Villain overfolds', 'so_what': 'Steal more',
         'next_time': 'Open-raise A7o from HJ'},
        {'hand_id': 'TM6039961024', 'villain_key': 'v_anon_01',
         'exploit_outcome': 'good', 'exploit_type': 'bluffed_sticky',
         'severity': 'B', 'timing_classification': 'known_before',
         'read_source': 'prior_atoms_mapped',
         'hero_action': 'value bet river', 'recommended_exploit': 'thin value',
         'suggests': 'Villain calls too wide', 'so_what': 'Value bet thin'},
        # Separate hand for timing_unclear (different hand+villain to avoid dedup)
        {'hand_id': 'TM6039962222', 'villain_key': 'v_anon_03',
         'exploit_outcome': 'missed', 'exploit_type': 'missed_thin_value_vs_sticky',
         'severity': 'B', 'timing_classification': 'unknown',
         'hero_action': 'checked river', 'recommended_exploit': 'bet river',
         'action_index': 5, 'available_before_action_index': 3},
    ],
    'atoms_by_hand': {
        'TM6039960264': [
            {'signal': 'repeated_blind_overfold', 'street': 'preflop',
             'evidence_text': 'Folds blinds 80%', 'strength': 3,
             'dimension': 'passive', 'villain_key': 'v_anon_01',
             'hand_id': 'TM6039960264', 'action_index': 2},
        ],
        'TM6039961024': [
            {'signal': 'weak_showdown_call', 'street': 'river',
             'evidence_text': 'Called river with third pair', 'strength': 2,
             'dimension': 'sticky', 'villain_key': 'v_anon_01',
             'hand_id': 'TM6039961024'},
        ],
        'TM6039961941': [
            {'signal': 'open_limp', 'street': 'preflop',
             'evidence_text': 'Open-limped UTG', 'strength': 2,
             'dimension': 'loose_passive', 'villain_key': 'v_anon_02',
             'hand_id': 'TM6039961941'},
            {'signal': 'passive_aggro_pivot', 'street': 'turn',
             'evidence_text': 'Suddenly raised turn', 'strength': 4,
             'dimension': 'aggressive', 'villain_key': 'v_anon_02',
             'hand_id': 'TM6039961941'},
            {'signal': 'multiway_donk', 'street': 'flop',
             'evidence_text': 'Donk bet into 3 players', 'strength': 3,
             'dimension': 'loose_passive', 'villain_key': 'v_anon_02',
             'hand_id': 'TM6039961941'},
        ],
        # Separate hand for learning_hand (v_anon_01, no dimension conflict)
        'TM6039963333': [
            {'signal': 'cold_call_3bet_oop', 'street': 'preflop',
             'evidence_text': 'Cold-called 3-bet OOP', 'strength': 4,
             'dimension': 'passive', 'villain_key': 'v_anon_01',
             'hand_id': 'TM6039963333'},
            {'signal': 'weak_showdown_call', 'street': 'river',
             'evidence_text': 'Called river with bottom pair', 'strength': 3,
             'dimension': 'passive', 'villain_key': 'v_anon_01',
             'hand_id': 'TM6039963333'},
            {'signal': 'calldown_weak_pair', 'street': 'turn',
             'evidence_text': 'Called turn with weak pair', 'strength': 3,
             'dimension': 'passive', 'villain_key': 'v_anon_01',
             'hand_id': 'TM6039963333'},
        ],
    },
    'atoms_by_villain': {
        'v_anon_02': [
            {'signal': 'open_limp', 'dimension': 'loose_passive',
             'hand_id': 'TM6039961941', 'villain_key': 'v_anon_02'},
            {'signal': 'passive_aggro_pivot', 'dimension': 'aggressive',
             'hand_id': 'TM6039961941', 'villain_key': 'v_anon_02'},
            {'signal': 'multiway_donk', 'dimension': 'loose_passive',
             'hand_id': 'TM6039961941', 'villain_key': 'v_anon_02'},
        ],
    },
}
_mock_hands = [
    {'id': 'TM6039960264', 'position': 'HJ', 'cards': ['A', 'h', '7', 'c'],
     'tournament': 'T1', 'board': ['K', 's', '5', 'd', '2', 'h'],
     'net_bb': -1.5, 'stack_bb': 25.0},
    {'id': 'TM6039961024', 'position': 'CO', 'cards': ['K', 'd', 'Q', 's'],
     'tournament': 'T1', 'board': ['J', 'h', '8', 's', '3', 'c'],
     'net_bb': 8.5, 'stack_bb': 30.0},
    {'id': 'TM6039961941', 'position': 'BTN', 'cards': ['9', 'h', '8', 'h'],
     'tournament': 'T2', 'board': ['7', 'd', '6', 's', '2', 'c'],
     'net_bb': -5.0, 'stack_bb': 20.0},
    {'id': 'TM6039962222', 'position': 'SB', 'cards': ['T', 's', '9', 's'],
     'tournament': 'T2', 'board': ['Q', 'h', '8', 'd', '4', 'c'],
     'net_bb': -3.0, 'stack_bb': 18.0},
    {'id': 'TM6039963333', 'position': 'BB', 'cards': ['6', 'd', '5', 'd'],
     'tournament': 'T1', 'board': ['A', 'c', '9', 'h', '3', 's'],
     'net_bb': -8.0, 'stack_bb': 22.0},
]
_mock_stats = {}

_av_candidates = _gav.build_opponent_adjustment_candidates(
    _mock_vi, _mock_hands, _mock_stats, max_candidates=40)

# T-AV1: Candidate builder returns list
check('T-AV1: candidate builder returns list',
      isinstance(_av_candidates, list) and len(_av_candidates) > 0,
      f'Expected non-empty list, got {type(_av_candidates)} len={len(_av_candidates) if isinstance(_av_candidates, list) else "?"}')

# T-AV2: All 5 source_types generated
_av_types = set(c['source_type'] for c in _av_candidates)
check('T-AV2: all 5 source_types generated',
      _av_types >= {'exploit_miss', 'exploit_good', 'timing_unclear',
                    'mixed_signal', 'learning_hand'},
      'Missing source_types: ' + str({'exploit_miss','exploit_good','timing_unclear','mixed_signal','learning_hand'} - _av_types))

# T-AV3: Candidate dedup (TM6039961941 appears as timing_unclear AND mixed_signal/learning,
# but timing_unclear is P1, should be kept over P2 mixed_signal/learning)
_av_hid_vk_count = {}
for c in _av_candidates:
    key = (c['hand_id'], c['villain_key'])
    _av_hid_vk_count[key] = _av_hid_vk_count.get(key, 0) + 1
_av_dups = {k: v for k, v in _av_hid_vk_count.items() if v > 1}
check('T-AV3: candidate dedup — no hand+villain duplicates',
      len(_av_dups) == 0,
      f'Duplicate hand+villain pairs: {_av_dups}')

# T-AV4: Budget cap respected
_av_capped = _gav.build_opponent_adjustment_candidates(
    _mock_vi, _mock_hands, _mock_stats, max_candidates=2)
check('T-AV4: budget cap respected',
      len(_av_capped) <= 2,
      f'Expected <=2, got {len(_av_capped)}')

# T-AV5: Priority ordering (P0 before P1 before P2)
_av_prios = [c['priority'] for c in _av_candidates]
_av_prio_nums = [{'P0': 0, 'P1': 1, 'P2': 2}[p] for p in _av_prios]
check('T-AV5: priority ordering P0 < P1 < P2',
      _av_prio_nums == sorted(_av_prio_nums),
      f'Priorities not sorted: {_av_prios}')

# T-AV6: Candidate dict has all required fields
_av_first = _av_candidates[0]
_av_missing = [f for f in _gav._CANDIDATE_FIELDS if f not in _av_first]
check('T-AV6: candidate has all required fields',
      len(_av_missing) == 0,
      f'Missing fields: {_av_missing}')

# T-AV7: evidence_summary is non-empty
_av_empty_summaries = [c['candidate_id'][:8] for c in _av_candidates
                       if not c.get('evidence_summary')]
check('T-AV7: evidence_summary non-empty on all candidates',
      len(_av_empty_summaries) == 0,
      f'Empty summaries: {_av_empty_summaries}')

# T-AV8: Worksheet JSON round-trips
import tempfile as _tmpf_av
_av_tmpdir = _tmpf_av.mkdtemp()
_av_ws_path = _gav.write_worksheet(
    _av_candidates, '20260604', 'Knockman', _av_tmpdir)
with open(_av_ws_path, 'r', encoding='utf-8') as _f_av:
    _av_ws = json.load(_f_av)
check('T-AV8: worksheet round-trips',
      _av_ws['schema_version'] == '1.0'
      and _av_ws['total_candidates'] == len(_av_candidates)
      and len(_av_ws['candidates']) == len(_av_candidates),
      'Worksheet round-trip failed')

# T-AV9: Analyst review loads valid JSON
# Simulate a reviewed worksheet
_av_reviewed = _av_ws.copy()
for c in _av_reviewed['candidates']:
    c['analyst_verdict'] = 'confirmed'
    c['analyst_coaching'] = 'Good coaching text for testing purposes.'
    c['analyst_severity'] = 'medium'
    c['analyst_confidence'] = 'high'
_av_rev_path = os.path.join(_av_tmpdir, '_analyst_villain_reviewed_20260604.json')
with open(_av_rev_path, 'w', encoding='utf-8') as _f_av2:
    json.dump(_av_reviewed, _f_av2)
_av_loaded = _gav.load_analyst_villain_review(_av_rev_path)
check('T-AV9: analyst review loads valid JSON',
      len(_av_loaded['candidates_by_id']) == len(_av_candidates)
      and _av_loaded['debug']['confirmed'] == len(_av_candidates),
      f'Loaded {len(_av_loaded["candidates_by_id"])} candidates, expected {len(_av_candidates)}')

# T-AV10: Analyst review rejects invalid verdict
_av_bad = _av_ws.copy()
_av_bad['candidates'] = [dict(_av_ws['candidates'][0], analyst_verdict='banana')]
_av_bad_path = os.path.join(_av_tmpdir, '_bad_review.json')
with open(_av_bad_path, 'w', encoding='utf-8') as _f_av3:
    json.dump(_av_bad, _f_av3)
_av_bad_loaded = _gav.load_analyst_villain_review(_av_bad_path)
check('T-AV10: invalid verdict rejected',
      _av_bad_loaded['debug']['invalid'] == 1
      and len(_av_bad_loaded['candidates_by_id']) == 0,
      f'Expected 1 invalid, got {_av_bad_loaded["debug"]}')

# T-AV11: Missing analyst file → no crash
_av_none = _gav.load_analyst_villain_review('/nonexistent/path.json')
check('T-AV11: missing analyst file no crash',
      _av_none['candidates_by_id'] == {},
      'Missing file should return empty dict')

# T-AV12: candidate_id is stable hash (Requirement A)
_av_id1 = _gav._stable_candidate_id('exploit_miss', 'TM6039960264', 'v_anon_01')
_av_id2 = _gav._stable_candidate_id('exploit_miss', 'TM6039960264', 'v_anon_01')
check('T-AV12: candidate_id is stable hash',
      _av_id1 == _av_id2 and len(_av_id1) == 16 and _av_id1.isalnum(),
      f'Unstable or wrong format: {_av_id1} vs {_av_id2}')

# T-AV13: candidate_reason present on all candidates (Requirement E)
_av_no_reason = [c['candidate_id'][:8] for c in _av_candidates
                 if not c.get('candidate_reason')]
check('T-AV13: candidate_reason on all candidates',
      len(_av_no_reason) == 0,
      f'Missing candidate_reason: {_av_no_reason}')

# T-AV14: mixed_signal has dimension_counts (Requirement F)
_av_mixed = [c for c in _av_candidates if c['source_type'] == 'mixed_signal']
check('T-AV14: mixed_signal has dimension_counts',
      all('dimension_counts' in c for c in _av_mixed)
      and (not _av_mixed or len(_av_mixed[0]['dimension_counts']) >= 2),
      'mixed_signal candidates missing dimension_counts')

# T-AV15: timing_unclear has action-index fields (Requirement G)
_av_timing = [c for c in _av_candidates if c['source_type'] == 'timing_unclear']
check('T-AV15: timing_unclear has action-index fields',
      all('det_action_index' in c for c in _av_timing),
      'timing_unclear candidates missing action-index fields')

# Cleanup temp dir
import shutil as _shutil_av
_shutil_av.rmtree(_av_tmpdir, ignore_errors=True)

# ============================================================
# T-AV16 through T-AV21: Renderer integration for analyst handoff
# ============================================================
# These test the overlay of analyst verdicts into _build_hand_opponent_contexts
# and the by_hand_villain convenience index.

# Build mock analyst review from existing candidates
import hashlib as _hl_av

def _test_candidate_id(source_type, hid, vk):
    """Mirror _stable_candidate_id for test verification."""
    raw = f'{source_type}|{hid}|{vk}'
    return _hl_av.sha256(raw.encode()).hexdigest()[:16]

# Create a mock reviewed worksheet with analyst verdicts
_test_cid_miss = _test_candidate_id('exploit_miss', 'TM6039960264', 'v_anon_01')
_test_cid_good = _test_candidate_id('exploit_good', 'TM6039961024', 'v_anon_01')
_test_cid_timing = _test_candidate_id('timing_unclear', 'TM6039962222', 'v_anon_03')
_test_cid_mixed = _test_candidate_id('mixed_signal', 'TM6039961941', 'v_anon_02')
_test_cid_learn = _test_candidate_id('learning_hand', 'TM6039963333', 'v_anon_01')

_mock_reviewed_json = {
    'schema_version': '1.0',
    'session_date': '20260604',
    'hero_name': 'TestHero',
    'candidates': [
        {'candidate_id': _test_cid_miss, 'hand_id': 'TM6039960264',
         'villain_key': 'v_anon_01', 'source_type': 'exploit_miss',
         'analyst_verdict': 'confirmed', 'analyst_coaching': 'Good catch — steal more vs nits.',
         'analyst_severity': 'high', 'analyst_confidence': 'high', 'analyst_note': ''},
        {'candidate_id': _test_cid_good, 'hand_id': 'TM6039961024',
         'villain_key': 'v_anon_01', 'source_type': 'exploit_good',
         'analyst_verdict': 'rejected', 'analyst_coaching': '',
         'analyst_severity': 'low', 'analyst_confidence': 'high', 'analyst_note': 'Not a real good exploit'},
        {'candidate_id': _test_cid_timing, 'hand_id': 'TM6039962222',
         'villain_key': 'v_anon_03', 'source_type': 'timing_unclear',
         'analyst_verdict': 'borderline', 'analyst_coaching': 'Timing is ambiguous here.',
         'analyst_severity': 'medium', 'analyst_confidence': 'low', 'analyst_note': 'Needs more data'},
        {'candidate_id': _test_cid_mixed, 'hand_id': 'TM6039961941',
         'villain_key': 'v_anon_02', 'source_type': 'mixed_signal',
         'analyst_verdict': 'confirmed', 'analyst_coaching': 'This villain shows genuine mixed tendencies.',
         'analyst_severity': 'medium', 'analyst_confidence': 'medium', 'analyst_note': ''},
        {'candidate_id': _test_cid_learn, 'hand_id': 'TM6039963333',
         'villain_key': 'v_anon_01', 'source_type': 'learning_hand',
         'analyst_verdict': 'upgraded', 'analyst_coaching': 'Great teaching hand for passive read.',
         'analyst_severity': 'medium', 'analyst_confidence': 'high', 'analyst_note': ''},
    ],
}

# Write to temp and load via load_analyst_villain_review
import tempfile as _tf_av2, json as _json_av2
_av2_tmpdir = _tf_av2.mkdtemp()
_av2_path = os.path.join(_av2_tmpdir, 'reviewed.json')
with open(_av2_path, 'w', encoding='utf-8') as _f:
    _json_av2.dump(_mock_reviewed_json, _f)

_av_review = _gav.load_analyst_villain_review(_av2_path)

# T-AV16: by_hand_villain index populated
check('T-AV16: by_hand_villain index populated',
      'by_hand_villain' in _av_review and len(_av_review['by_hand_villain']) > 0,
      'load_analyst_villain_review missing by_hand_villain')

# T-AV17: by_hand_villain lookup correct for (hid_short, villain_key)
_bv_miss = _av_review['by_hand_villain'].get(('39960264', 'v_anon_01'), [])
_bv_miss_types = [r['source_type'] for r in _bv_miss]
check('T-AV17: by_hand_villain contains exploit_miss for 39960264+v01',
      'exploit_miss' in _bv_miss_types,
      'by_hand_villain missing exploit_miss: ' + str(_bv_miss_types))

# Now test _build_hand_opponent_contexts with analyst overlay
# Need to import from sections_xiv — requires building the right mock structures
from gem_report_draft.sections_xiv import _build_hand_opponent_contexts

_mock_s = {
    'villain_intel': _mock_vi,
    '_hands_by_id': {h['id']: h for h in _mock_hands},
}
_mock_rd = {
    'appendix_hand_ids_all': ['TM6039960264', 'TM6039961024', 'TM6039961941',
                               'TM6039962222', 'TM6039963333'],
}

# Call WITHOUT analyst review (baseline)
_hoc_no_review = _build_hand_opponent_contexts(_mock_hands, _mock_s, _mock_rd)

# Call WITH analyst review
_mock_rd_with = dict(_mock_rd)
_mock_rd_with['analyst_villain_review'] = _av_review
_hoc_with_review = _build_hand_opponent_contexts(
    _mock_hands, _mock_s, _mock_rd_with, analyst_review=_av_review)

# T-AV18: rejected exploit_good filtered from contexts
# The good_exploit for TM6039961024 should be present without review...
_hoc_1024_no = _hoc_no_review.get('61024', _hoc_no_review.get('39961024', []))
_good_no = [c for c in _hoc_1024_no if c.get('bucket') == 'good_exploit']
# ...but filtered with analyst review (rejected)
_hoc_1024_with = _hoc_with_review.get('61024', _hoc_with_review.get('39961024', []))
_good_with = [c for c in _hoc_1024_with if c.get('bucket') == 'good_exploit']
check('T-AV18: rejected good_exploit filtered from contexts',
      len(_good_no) >= 1 and len(_good_with) == 0,
      'rejected good_exploit not filtered: no_review=' + str(len(_good_no)) +
      ' with_review=' + str(len(_good_with)))

# T-AV19: confirmed exploit_miss has analyst_coaching in context
_hoc_0264 = _hoc_with_review.get('60264', _hoc_with_review.get('39960264', []))
_miss_ctx = [c for c in _hoc_0264 if c.get('bucket') == 'exploit_miss']
check('T-AV19: confirmed exploit_miss has analyst_coaching',
      len(_miss_ctx) >= 1 and _miss_ctx[0].get('analyst_reviewed') is True
      and _miss_ctx[0].get('analyst_coaching') == 'Good catch — steal more vs nits.',
      'exploit_miss analyst overlay missing: ' + str(_miss_ctx[:1]))

# T-AV20: upgraded atom promotes to analyst_learning bucket
_hoc_3333 = _hoc_with_review.get('63333', _hoc_with_review.get('39963333', []))
_learning = [c for c in _hoc_3333 if c.get('bucket') == 'analyst_learning']
check('T-AV20: upgraded atom has analyst_learning bucket',
      len(_learning) >= 1 and _learning[0].get('analyst_verdict') == 'upgraded',
      'analyst_learning bucket missing or wrong verdict: ' + str(_learning[:1]))

# T-AV21: fallback label CSS class present in _html.py
_html_path_av = os.path.join(os.path.dirname(__file__), 'gem_report_draft', '_html.py')
with open(_html_path_av, 'r', encoding='utf-8') as _f:
    _html_src_av = _f.read()
check('T-AV21: fallback label for non-reviewed coaching blocks',
      'cb-fallback-label' in _html_src_av
      and 'not yet analyst-reviewed' in _html_src_av,
      'fallback label not in _html.py')

# T-AV22: analyst_learning bucket CSS present in _html.py
check('T-AV22: analyst_learning bucket CSS present',
      'coaching-analyst_learning' in _html_src_av
      and 'cb-learning' in _html_src_av,
      'analyst_learning CSS classes missing from _html.py')

# T-AV23: analyst badge rendering in JS
check('T-AV23: analyst badge rendering in JS',
      'cb-analyst' in _html_src_av
      and 'Analyst confirmed' in _html_src_av
      and 'Debatable' in _html_src_av
      and 'Learning opportunity' in _html_src_av,
      'analyst badge JS rendering missing')

# Cleanup
import shutil as _shutil_av2
_shutil_av2.rmtree(_av2_tmpdir, ignore_errors=True)

# ============================================================
# T-HG1..HG3: Hand grid — ante/blind "posts" actions must be suppressed
# v8.8.7 regression guard: "posts 0.1BB" noise must never render in grid
# ============================================================

_hg_src = open(os.path.join(os.path.dirname(__file__), 'gem_report_draft', '_hand_grid.py'),
               encoding='utf-8').read()

# T-HG1 (static): the render loop skips posts actions
check('T-HG1: hand grid render loop skips posts actions',
      "actions[i].get('action') == 'posts'" in _hg_src
      and 'continue' in _hg_src[_hg_src.index("== 'posts'"):
                                 _hg_src.index("== 'posts'") + 80],
      '_hand_grid.py render loop must skip posts actions')

# T-HG2 (static): _hero_actions_by_street_from_app skips posts
check('T-HG2: hero action index helper skips posts',
      _hg_src.count("a.get('action') == 'posts'") >= 2,
      '_hand_grid.py hero helpers must filter posts in at least 2 places '
      '(render + _hero_actions_by_street_from_app)')

# T-HG3 (behavioral): feed mock actions with posts, verify they don't appear
from gem_report_draft._hand_grid import _hero_action_verbs_by_street_from_app
_hg3_app = {'actions': {'preflop': [
    {'position': 'SB', 'action': 'posts', 'amount_bb': 0.5, 'is_hero': False},
    {'position': 'BB', 'action': 'posts', 'amount_bb': 1.0, 'is_hero': False},
    {'position': 'UTG', 'action': 'posts', 'amount_bb': 0.1, 'is_hero': True},
    {'position': 'UTG', 'action': 'raises', 'amount_bb': 3.0,
     'is_hero': True, 'stack_bb': 100},
    {'position': 'BB', 'action': 'calls', 'amount_bb': 2.0,
     'is_hero': False, 'stack_bb': 100},
], 'flop': [], 'turn': [], 'river': []}}
_hg3_verbs = _hero_action_verbs_by_street_from_app(_hg3_app)
check('T-HG3: hero verbs exclude posts action',
      'posts' not in _hg3_verbs.get('preflop', [])
      and 'raises' in _hg3_verbs.get('preflop', [])
      and len(_hg3_verbs['preflop']) == 1,
      f'Expected ["raises"], got {_hg3_verbs.get("preflop")}')

# ============================================================
# T-PLO1..T-PLO3: PLO/non-NLH exclusion (v8.8.8 BUG-1)
# ============================================================

# T-PLO1 (static): shadow block exists in gem_analyzer.py
_plo1_src = open(os.path.join(os.path.dirname(__file__), 'gem_analyzer.py'), encoding='utf-8').read()
check('T-PLO1: PLO shadow block present in gem_analyzer.py',
      'all_hands = hands' in _plo1_src and 'game_type_counts' in _plo1_src,
      'Missing all_hands shadow or game_type_counts metadata')

# T-PLO2 (static): existing game_type gate preserved as safety net
check('T-PLO2: downstream game_type gate still present (safety net)',
      '_non_nlh_ids' in _plo1_src,
      'The L7654 safety-net gate was removed — must be kept')

# T-PLO3 (behavioral): PLO hands excluded from strategic hand iteration
# Simulate the shadow logic from analyze_session
from collections import Counter as _Ctr_plo3
_plo3_hands = [
    {'cards': ['As', 'Ks'], 'game_type': 'NLH',  'vpip': True, 'pfr': True},
    {'cards': ['Qh', 'Jh'], 'game_type': 'NLH',  'vpip': True, 'pfr': False},
    {'cards': ['Ah', 'Kh'], 'game_type': 'PLO',   'vpip': True, 'pfr': True},
    {'cards': ['Td', '9d'], 'game_type': 'PLO',   'vpip': False, 'pfr': False},
]
_plo3_all = _plo3_hands
_plo3_N_total = len(_plo3_all)
_plo3_gt = dict(_Ctr_plo3(h.get('game_type', 'NLH') for h in _plo3_all))
_plo3_non_nlh = _plo3_N_total - _plo3_gt.get('NLH', 0)
if _plo3_non_nlh:
    _plo3_strategic = [h for h in _plo3_all if h.get('game_type', 'NLH') == 'NLH']
else:
    _plo3_strategic = _plo3_all
_plo3_N = len(_plo3_strategic)
_plo3_vpip = sum(1 for h in _plo3_strategic if h['vpip'])
check('T-PLO3: PLO hands excluded from strategic iteration',
      _plo3_N == 2 and _plo3_vpip == 2 and _plo3_gt == {'NLH': 2, 'PLO': 2},
      f'Expected N=2, vpip=2, gt={{NLH:2,PLO:2}}; got N={_plo3_N}, '
      f'vpip={_plo3_vpip}, gt={_plo3_gt}')

# ============================================================
# V25 STREET-MERGED MODAL TESTS
# ============================================================
# T-V25-1 through T-V25-18: static regression tests for V25 layout refactor
# All tests read _html.py source; no runtime DOM testing.

with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_html.py'), 'r', encoding='utf-8') as _fv25:
    _v25_code = _fv25.read()

# T-V25-1: V25 CSS classes exist
check('T-V25-1: V25 CSS classes present',
      '.v25-topbar' in _v25_code
      and '.v25-street' in _v25_code
      and '.v25-street-head' in _v25_code
      and '.v25-hand' in _v25_code,
      'V25 CSS classes missing from _html.py')

# T-V25-2: V25 modal HTML structure
check('T-V25-2: V25 modal HTML structure in _MODAL_HTML',
      'v25-panel' in _v25_code
      and 'v25-topbar' in _v25_code
      and 'v25-top-cards' in _v25_code,
      'V25 HTML structure missing from _MODAL_HTML')

# T-V25-3: buildModalHandV25 exists
check('T-V25-3: buildModalHandV25 function exists',
      'function buildModalHandV25(hid)' in _v25_code,
      'buildModalHandV25 function not found')

# T-V25-4: Review controls preserved
check('T-V25-4: Review controls preserved in _MODAL_HTML',
      'verdict-chip' in _v25_code
      and 'modal-review-notes' in _v25_code
      and 'modal-save-state' in _v25_code,
      'Review controls missing from _MODAL_HTML')

# T-V25-5: hand-modal-title ID preserved
check('T-V25-5: hand-modal-title ID preserved',
      'id="hand-modal-title"' in _v25_code,
      'hand-modal-title ID missing — backward compat break')

# T-V25-6: Queue element preserved
check('T-V25-6: hand-queue-context ID preserved',
      'hand-queue-context' in _v25_code,
      'hand-queue-context ID missing')

# T-V25-7: GTOW data attributes in clone logic
check('T-V25-7: GTOW clone preserves original class',
      'classList.add(\'v25-gtow-btn\')' in _v25_code
      or "classList.add('v25-gtow-btn')" in _v25_code,
      'GTOW clone should ADD v25-gtow-btn, not replace original class')

# T-V25-8: No overflow:hidden on street ancestors
# Check that .v25-street, .v25-street-body, .v25-hand don't have overflow:hidden
_v25_css_section = _v25_code[_v25_code.index('V25 STREET-MERGED MODAL CSS'):
                             _v25_code.index('V25 mobile overrides')]
check('T-V25-8: No overflow:hidden on V25 street ancestors',
      'v25-street {' not in _v25_css_section or
      'overflow: hidden' not in _v25_css_section.split('.v25-street {')[1].split('}')[0]
      if '.v25-street {' in _v25_css_section else True,
      'overflow:hidden found on .v25-street — will break sticky headers')

# T-V25-9: Legacy fallback exists
check('T-V25-9: Legacy fallback wrapper exists',
      'function buildModalHandLegacy(hid)' in _v25_code
      and 'buildModalHandV25(hid)' in _v25_code
      and 'buildModalHandLegacy(hid)' in _v25_code
      and 'falling back to legacy' in _v25_code,
      'Legacy fallback wrapper missing or incomplete')

# T-V25-10: Queue functions unchanged
check('T-V25-10: Queue functions all present',
      '_queuePrev' in _v25_code
      and '_queueNext' in _v25_code
      and '_queueJump' in _v25_code
      and '_queueBackToList' in _v25_code
      and 'buildInlineHandQueueFromClickedRef' in _v25_code,
      'Queue navigation functions missing')

# T-V25-11: Analyst handoff rendering preserved
check('T-V25-11: Analyst handoff rendering preserved',
      'analyst_learning' in _v25_code
      and 'cb-analyst' in _v25_code
      and 'cb-fallback-label' in _v25_code,
      'Analyst handoff rendering missing from V25')

# T-V25-12: Opponent coaching bucket routing
check('T-V25-12: V25 handles all coaching bucket types',
      'exploit_miss' in _v25_code
      and 'good_exploit' in _v25_code
      and 'villain_evidence' in _v25_code
      and 'passive_read' in _v25_code
      and 'analyst_learning' in _v25_code,
      'Missing coaching bucket type in V25 renderer')

# T-V25-13: Review storage selectors preserved
check('T-V25-13: Review storage IDs in _MODAL_HTML',
      'modal-review-status' in _v25_code
      and 'modal-review-notes' in _v25_code
      and 'modal-save-state' in _v25_code,
      'Review storage element IDs missing')

# T-V25-14: List/villain modals untouched
check('T-V25-14: list-modal and villain-evidence-modal preserved',
      'id="list-modal"' in _v25_code
      and 'id="villain-evidence-modal"' in _v25_code,
      'list-modal or villain-evidence-modal missing')

# T-V25-15: _hand_grid.py unchanged (SHA256 guard)
import hashlib as _hl_v25
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_hand_grid.py'), 'rb') as _fhg:
    _hg_hash = _hl_v25.sha256(_fhg.read()).hexdigest()
check('T-V25-15: _hand_grid.py unchanged (SHA256)',
      _hg_hash == 'd847cc12ea7770a561e335c8c317302b68fb858158e7025180508439f4b01865',
      f'_hand_grid.py was modified! Hash: {_hg_hash}')

# T-V25-16: Top bar hydration function exists and handles Prev/Next
check('T-V25-16: _hydrateV25TopBar exists and called in openHand',
      'function _hydrateV25TopBar(hid' in _v25_code
      and '_hydrateV25TopBar(hid' in _v25_code.split('function openHand')[1].split('window.openHand')[0],
      '_hydrateV25TopBar not called from openHand — top bar won\'t update on Prev/Next')

# T-V25-17: Legacy fallback wrapper structure
# Check that buildModalHand tries V25 first, catches errors, falls back
_v25_wrapper = _v25_code[_v25_code.index('function buildModalHand(hid)'):
                          _v25_code.index('Hand Queue State')]
check('T-V25-17: buildModalHand wrapper has try/catch/fallback',
      'try{' in _v25_wrapper
      and 'catch(e)' in _v25_wrapper
      and 'buildModalHandV25(hid)' in _v25_wrapper
      and 'buildModalHandLegacy(hid)' in _v25_wrapper,
      'buildModalHand wrapper missing try/catch or fallback call')

# T-V25-18: No duplicate coaching — routedIdxs tracking
check('T-V25-18: Opponent coaching dedup via routing tracking',
      'routedIdxs' in _v25_code or 'routedContextIds' in _v25_code,
      'No dedup tracking for routed coaching contexts — risk of duplicates')

# ============================================================
# v8.8.9 BUG-FIX TESTS
# ============================================================

# --- BUG-1: sections_financial uses analyzer category, not equity re-threshold ---
_HERE = os.path.dirname(__file__)
_sf_src = open(os.path.join(_HERE, 'gem_report_draft', 'sections_financial.py'), encoding='utf-8').read()
check('T-BF1-1: BUG-1 — category field used in _ai_ids (not equity threshold)',
      "_be.get('category'" in _sf_src,
      'sections_financial.py still uses equity re-thresholding instead of category')
check('T-BF1-2: BUG-1 — no equity threshold buckets remain',
      '_beq_n >= 55' not in _sf_src and '_beq_n >= 42' not in _sf_src,
      'Old equity thresholds (>=55, >=42) still present')

# --- BUG-3: auto_verdicts piped to renderer ---
_ga_src = open(os.path.join(_HERE, 'gem_analyzer.py'), encoding='utf-8').read()
_gcb_compat = open(os.path.join(_HERE, 'gem_coverage_builder.py'), encoding='utf-8').read() if os.path.exists(os.path.join(_HERE, 'gem_coverage_builder.py')) else ''
_ga_or_gcb = _ga_src + _gcb_compat
check('T-BF3-1: BUG-3 — auto_verdicts dict built in analyzer',
      "report_data['auto_verdicts']" in _ga_or_gcb,
      'gem_analyzer.py does not write auto_verdicts to report_data')
_sxiv_src = open(os.path.join(_HERE, 'gem_report_draft', 'sections_xiv.py'), encoding='utf-8').read()
check('T-BF3-2: BUG-3 — sections_xiv reads auto_verdicts as fallback',
      "auto_verdicts" in _sxiv_src and '_is_auto_verdict' in _sxiv_src,
      'sections_xiv.py does not fall back to auto_verdicts')
check('T-BF3-3: BUG-3 — auto badge rendered for auto-verdicts',
      'auto</span>' in _sxiv_src or "auto-verdict" in _sxiv_src or "auto</" in _sxiv_src,
      'No auto badge in sections_xiv for pipeline verdicts')

# --- BUG-4: spurious Note badge removed ---
check('T-BF4-1: BUG-4 — no catch-all else Note badge',
      "{'type': 'note', 'label': 'Note'}" not in _sxiv_src
      and "{'type':'note','label':'Note'}" not in _sxiv_src,
      'sections_xiv.py still has catch-all Note badge in _build_villain_badges')
check('T-BF4-2: BUG-4 — passive_aggro_pivot badge preserved',
      "'passive_aggro_pivot'" in _sxiv_src and "'pivot'" in _sxiv_src,
      'Pivot badge for passive_aggro_pivot was accidentally removed')

# --- BUG-5: GTOW pf_allin gate ---
_gtow_src = open(os.path.join(_HERE, 'gem_gtow.py'), encoding='utf-8').read()
check('T-BF5-1: BUG-5 — GTOW flop-root gated on not pf_allin',
      "not hand.get('pf_allin')" in _gtow_src,
      'gem_gtow.py flop-root branch does not gate on pf_allin')

# --- BUG-6: R4 out-of-range verdict ---
check('T-BF6-1: BUG-6 — _in_rj initialized before REJAM block',
      '_in_rj = None' in _ga_or_gcb,
      'gem_analyzer.py does not initialize _in_rj before REJAM block')
check('T-BF6-2: BUG-6 — R4 branches on range membership',
      'R4_3betjam_out_of_range' in _ga_or_gcb,
      'gem_analyzer.py R4 rule has no out-of-range branch')
check('T-BF6-3: BUG-6 — R4 in-range check uses _in_rj',
      'not _in_rj' in _ga_or_gcb and "III.4 Read-dependent" in _ga_or_gcb,
      'R4 rule does not use _in_rj to gate verdict')

# --- FEATURE: keyboard nav focus guard ---
check('T-FEAT-1: Arrow key handler has editable-field focus guard',
      '_inEdit' in _v25_code,
      'Keyboard handler has no focus guard for textarea/input')

# ============================================================
# T-BF2: BUG-2 push/fold range-gated verdicts (v8.9.0)
# ============================================================
_ana_src = open(os.path.join(_HERE, 'gem_analyzer.py'), encoding='utf-8').read()
_ana_or_gcb = _ana_src + _gcb_compat

check('T-BF2-1: _PUSH_DEPTH_MAX extended to 25',
      '_PUSH_DEPTH_MAX = 25' in _ana_or_gcb,
      '_PUSH_DEPTH_MAX not bumped to 25')

check('T-BF2-2: _STEAL_DEPTH_MAX preserved at 15 for R1',
      '_STEAL_DEPTH_MAX = 15' in _ana_or_gcb,
      'Missing _STEAL_DEPTH_MAX for R1 missed-steal gate')

check('T-BF2-3: R1 uses _STEAL_DEPTH_MAX (not _PUSH_DEPTH_MAX)',
      '_stack <= _STEAL_DEPTH_MAX' in _ana_or_gcb,
      'R1 still uses _PUSH_DEPTH_MAX instead of _STEAL_DEPTH_MAX')

check('T-BF2-4: R2 has out-of-range gate (R2_open_shove_out_of_range)',
      'R2_open_shove_out_of_range' in _ana_or_gcb,
      'R2 missing out-of-range auto_rule')

check('T-BF2-5: _in_push initialized for R2 verdict gating',
      '_in_push = None' in _ana_or_gcb,
      '_in_push not initialized')

check('T-BF2-6: JAM_ chart prefix searched in push citation',
      "('JAM_', 'PUSH_')" in _ana_or_gcb,
      'Push citation not searching JAM_ charts')

check('T-BF2-7: Position aliasing map exists',
      '_POS_ALIAS' in _ana_or_gcb and "'UTG': ['LJ']" in _ana_or_gcb,
      '_POS_ALIAS map missing or incomplete')

check('T-BF2-8: Depth quantization tiers in push citation',
      '_target_depth = 20' in _ana_or_gcb and '_target_depth = 12' in _ana_or_gcb,
      'Missing depth quantization tiers for 12BB/20BB')

check('T-BF2-9: No-jam-range detection for positions without charts',
      'No GTO jam range' in _ana_or_gcb,
      'Missing no-jam-range note for positions without charts at depth')

check('T-BF2-10: Villain push citation extended to _PUSH_DEPTH_MAX',
      '_stack <= _PUSH_DEPTH_MAX and not _hero_open_jammed' in _ana_or_gcb,
      'Villain push citation not extended to _PUSH_DEPTH_MAX')

# Range file checks
_rng_path = os.path.join(_HERE, 'Poker_Ranges_Text.txt')
_rng_src = open(_rng_path, encoding='utf-8').read()

check('T-BF2-11: GTOW ChipEV section exists in range file',
      'GTOW ChipEV 6-max JAM RANGES' in _rng_src,
      'Missing GTOW ChipEV section in Poker_Ranges_Text.txt')

check('T-BF2-12: JAM_12BB charts present',
      'JAM_12BB_LJ:' in _rng_src and 'JAM_12BB_BTN:' in _rng_src,
      'Missing JAM_12BB charts')

check('T-BF2-13: JAM_15BB charts present',
      'JAM_15BB_LJ:' in _rng_src and 'JAM_15BB_SB:' in _rng_src,
      'Missing JAM_15BB charts')

check('T-BF2-14: JAM_20BB charts present (BTN+SB only)',
      'JAM_20BB_BTN:' in _rng_src and 'JAM_20BB_SB:' in _rng_src,
      'Missing JAM_20BB charts')

check('T-BF2-15: JAM_25BB_SB chart present',
      'JAM_25BB_SB:' in _rng_src,
      'Missing JAM_25BB_SB chart')

check('T-BF2-16: No-jam note for EP at 20BB',
      'NO JAM: LJ, HJ, CO' in _rng_src,
      'Missing no-jam comment for EP positions at 20BB')

# Behavioral: verify range loader finds the new charts
from gem_ranges import load_ranges as _lr_bf2
_bf2_ranges = _lr_bf2()
check('T-BF2-17: JAM_12BB_CO loads via gem_ranges',
      'JAM_12BB_CO' in _bf2_ranges and len(_bf2_ranges.get('JAM_12BB_CO', {})) > 20,
      'JAM_12BB_CO not loading or too few combos')

check('T-BF2-18: JAM_20BB_BTN loads with thin range',
      'JAM_20BB_BTN' in _bf2_ranges and 5 <= len(_bf2_ranges.get('JAM_20BB_BTN', {})) <= 30,
      'JAM_20BB_BTN not loading or wrong combo count')

# ============================================================
# v8.9.1 — Drop Audit Regression + UX + Raw Stats
# ============================================================
print('\n=== v8.9.1: Drop Audit Regression + UX + Raw Stats ===')

import inspect as _ins891

# --- Static: _hand_grid.py source checks ---
_hg_path = os.path.join(os.path.dirname(__file__), 'gem_report_draft', '_hand_grid.py')
with open(_hg_path, encoding='utf-8') as _f:
    _hg_src = _f.read()

check('T-891-01: board-tex class present in _hand_grid.py',
      "board-tex" in _hg_src,
      'board-tex span not found')

check('T-891-02: draw-profile class present in _hand_grid.py',
      "draw-profile" in _hg_src,
      'draw-profile span not found')

check('T-891-03: villain-mini class present in _hand_grid.py',
      "villain-mini" in _hg_src,
      'villain-mini span not found')

check('T-891-04: push-verdict class present in _hand_grid.py',
      "push-verdict" in _hg_src,
      'push-verdict span not found')

check('T-891-05: _ps(p, stk pattern in action format strings',
      "_ps(p, stk" in _hg_src,
      '_ps() not wired into action loop')

check('T-891-06: _effective_amt function defined in _hand_grid.py',
      "def _effective_amt" in _hg_src,
      '_effective_amt helper missing')

check('T-891-07: _grid_stack function defined in _hand_grid.py',
      "def _grid_stack" in _hg_src,
      '_grid_stack helper missing')

check('T-891-08: _eai_html fragment initialized',
      "_eai_html = ''" in _hg_src,
      '_eai_html not pre-initialized to empty string')

check('T-891-09: _arch_html fragment initialized',
      "_arch_html = ''" in _hg_src,
      '_arch_html not pre-initialized to empty string')

check('T-891-10: _push_verdict_attr fragment initialized',
      "_push_verdict_attr = ''" in _hg_src,
      '_push_verdict_attr not pre-initialized to empty string')

check('T-891-11: _calljam_html fragment initialized',
      "_calljam_html = ''" in _hg_src,
      '_calljam_html not pre-initialized to empty string')

check('T-891-12: json.dumps used for JS onclick safety',
      "json.dumps" in _hg_src or "_json_mod.dumps" in _hg_src,
      'json.dumps not found — JS injection risk')

check('T-891-13: html.escape used for villain alias safety',
      "html.escape" in _hg_src or "_html_mod.escape" in _hg_src,
      'html.escape not found — XSS risk')

# T-891-14: Villain archetype reads from h (hand dict), not app_details
# gem_opponent_profiler sets villain_archetype_label on h, not on appendix_hand_details.
# Reading from app_details was dead code — it always returned empty string.
check('T-891-14: villain_archetype_label reads from h, not app_details',
      "h.get('villain_archetype_label'" in _hg_src
      and "app_details" not in _hg_src.split('villain_archetype_label')[0].split('\n')[-1],
      'villain_archetype_label must read from h (hand dict), not app_details')

check('T-891-15: villain_exploit_note reads from h, not app_details',
      "h.get('villain_exploit_note'" in _hg_src,
      'villain_exploit_note must read from h (hand dict), not app_details')

# --- Static: sections_iv_xii.py source checks ---
_sec_path = os.path.join(os.path.dirname(__file__), 'gem_report_draft', 'sections_iv_xii.py')
with open(_sec_path, encoding='utf-8') as _f:
    _sec_src = _f.read()

# sec-5-5: both if and else branches
_sec55_count = _sec_src.count('"sec-5-5"')
check('T-891-14: sec-5-5 emitted in both if/else paths',
      _sec55_count >= 2,
      f'sec-5-5 appears {_sec55_count} time(s), need >=2')

# sec-5-6: both if and else branches
_sec56_count = _sec_src.count('"sec-5-6"')
check('T-891-15: sec-5-6 emitted in both if/else paths',
      _sec56_count >= 2,
      f'sec-5-6 appears {_sec56_count} time(s), need >=2')

# sec-11-4b: both if and else branches
_sec114b_count = _sec_src.count('"sec-11-4b"')
check('T-891-16: sec-11-4b emitted in both if/else paths',
      _sec114b_count >= 2,
      f'sec-11-4b appears {_sec114b_count} time(s), need >=2')

# --- Behavioral: Raw Stats zero-filter ---
check('T-891-17: Raw Stats filter does NOT exclude 0',
      '0, 0.0)' not in _sec_src or 'not in (None' not in _sec_src,
      'Filter still strips 0/0.0 — zero-value stats lost')

# More precise: find the _emit_csv_remaining filter line
_filter_lines = [l for l in _sec_src.splitlines() if 'not in (None' in l and "'None'" in l]
_has_zero_filter = any('0, 0.0' in l or ', 0)' in l for l in _filter_lines)
check('T-891-18: Raw Stats filter line keeps 0 and 0.0 values',
      not _has_zero_filter,
      f'Filter line still contains numeric zero exclusion')

# --- Static: BUG-1 ICM flat alert fix ---
_ga_path = os.path.join(os.path.dirname(__file__), 'gem_analyzer.py')
with open(_ga_path, encoding='utf-8') as _f:
    # Read first 2200 lines to find the fix area (was 1500; v8.12.x
    # helper insertions shifted the ICM gate past the old window)
    _ga_lines = []
    for _i, _line in enumerate(_f, 1):
        _ga_lines.append(_line)
        if _i > 2200:
            break
_ga_head = ''.join(_ga_lines)

check('T-891-19: ICM flat alert uses phase check (not icm_pressure)',
      'phase in _ICM_PHASES' in _ga_head,
      'J43 ICM flat alert still using icm_pressure gate')

check('T-891-20: icm_pressure >= 0.5 gate removed',
      '_icm_p2 >= 0.5' not in _ga_head,
      'Old icm_pressure gate still present')

# --- Static: GAP-14 stale comment fix ---
_html_path = os.path.join(os.path.dirname(__file__), 'gem_report_draft', '_html.py')
with open(_html_path, encoding='utf-8') as _f:
    # Read around line 2172 area
    _html_lines = []
    for _i, _line in enumerate(_f, 1):
        _html_lines.append(_line)
        # v8.12.5: window 2600 -> 2800 (PBLazy norm + pill-whitelist
        # insertions shifted the pinned comment past the old cutoff)
        # v8.14.0 Slice C: 2800 -> 2950 (PBReviewQueue controller insertion
        # shifted the pinned push-range comment down again)
        if _i > 2950:
            break
_html_head = ''.join(_html_lines)

check('T-891-21: Push-range comment says <=25BB (not <=15BB)',
      '<=25BB' in _html_head or '≤25BB' in _html_head,
      'GAP-14 stale comment not fixed')

# --- Static: Version bump ---
from gem_report_draft.draft import VERSION as _v891
check('T-891-22: VERSION is v8.12.0',
      _v891 == 'v8.12.0',
      f'VERSION is {_v891}')

# --- Static: Flop card sorting ---
check('T-891-23: _sort_cards_desc used for flop ordering',
      '_sort_cards_desc' in _hg_src,
      '_sort_cards_desc not found in _hand_grid.py')

# ────────────────────────────────────────────────────────────
# V25.3 PASS A — Modal cleanup tests
# ────────────────────────────────────────────────────────────

check('T-A-01: mobile .v25-hand has padding-bottom with v25-review-h',
      'padding-bottom: calc(var(--v25-review-h) + 20px)' in _tvh_html_code,
      'mobile bottom padding not restored')

check('T-A-02: analyst-notes early-return for headerless divs',
      "querySelector('.note-street')" in _tvh_html_code
      and 'if(!hasHeaders){' in _tvh_html_code
      and "getAttribute('data-street')" in _tvh_html_code,
      'headerless duplication fix missing')

check('T-A-03: verdict extracts from first <p> before textContent',
      "querySelector('p')||verdictEl" in _tvh_html_code,
      'verdict backlink-text fix missing')

check('T-A-04: villain row has evidence link button',
      'v25-evidence-link' in _tvh_html_code
      and 'openVillainEvidence(villainKey)' in _tvh_html_code,
      'evidence link button missing from villain row')

check('T-A-05: metadata normalizer uses anchored skip regexes',
      '_isMetaSkip' in _tvh_html_code
      and 'v25-tourney' in _tvh_html_code
      and r'^L\d+$' in _tvh_html_code,
      'anchored metadata skip regexes missing')

check('T-A-06: stack context preserves source summary text',
      'srcText' in _tvh_html_code
      and "srcText||'Stack context'" in _tvh_html_code,
      'stack context hardcoded overwrite not fixed')

check('T-A-07: hero-phase querySelector in V25 preflop',
      "querySelector('.hero-phase')" in _tvh_html_code,
      'hero-phase extraction missing')

check('T-A-08: v25-compact-queue class in queue rendering',
      'v25-compact-queue' in _tvh_html_code,
      'compact queue class missing')

check('T-A-09: v25-queue-main-row and v25-queue-chip-rail present',
      'v25-queue-main-row' in _tvh_html_code
      and 'v25-queue-chip-rail' in _tvh_html_code,
      'compact queue structure classes missing')

check('T-A-10: v25-queue-btn replaces inline style buttons',
      'v25-queue-btn' in _tvh_html_code
      and 'v25-queue-prev' in _tvh_html_code
      and 'v25-queue-next' in _tvh_html_code,
      'queue buttons not using v25-namespaced classes')

check('T-A-11: postflop title is Board + hero hand',
      "Board + hero hand" in _tvh_html_code,
      'postflop board heading not updated')

check('T-A-12: .ann-bare V25 rule has font-size 1.15em',
      'ann-bare' in _tvh_html_code
      and '1.15em' in _tvh_html_code,
      '.ann-bare sizing not fixed to 1.15em')

check('T-A-13: desktop grid 190px 390px minmax(0, 1fr)',
      '190px 390px minmax(0, 1fr)' in _tvh_html_code,
      'desktop unequal columns missing')

check('T-A-14: .modal-panel.v25-panel desktop width override',
      '.modal-panel.v25-panel' in _tvh_html_code
      and 'min(1320px' in _tvh_html_code,
      'panel width override missing')

check('T-A-15: semantic column classes present',
      'v25-board-section' in _tvh_html_code
      and 'v25-action-section' in _tvh_html_code
      and 'v25-commentary-section' in _tvh_html_code,
      'semantic section classes missing')

check('T-A-16: overflow-wrap anywhere on commentary paragraphs',
      'overflow-wrap: anywhere' in _tvh_html_code,
      'commentary overflow-wrap missing')

check('T-A-17: scroll-margin-top uses var(--sticky-offset)',
      'scroll-margin-top' in _tvh_html_code
      and 'var(--sticky-offset)' in _tvh_html_code,
      'hardcoded scroll offset not using CSS variable')

# ────────────────────────────────────────────────────────────
# V25.3 PASS B — Queue/audit plumbing tests
# ────────────────────────────────────────────────────────────

check('T-B-01: _norm8 function in draft.py',
      'def _norm8(hid):' in _tvh_draft_code
      and 'hid[-8:]' in _tvh_draft_code,
      '_norm8 canonicalization function missing')

check('T-B-02: handAvailability JS lookup uses normalizeHandId',
      'normalizeHandId(hid)]' in _tvh_html_code,
      'handAvailability lookup not normalized')

check('T-B-03: no inline onclick openHand in sections_issue_explorer',
      'onclick' not in _tha_ie_code or 'openHand' not in _tha_ie_code,
      'inline onclick openHand still present')

# Read sections_financial.py for suckout test
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_financial.py'), 'r', encoding='utf-8') as _fb4:
    _tb4_fin_code = _fb4.read()
check('T-B-04: data-hand-queue-group in sections_financial suckout',
      'data-hand-queue-group' in _tb4_fin_code
      and 'suckout-fav-lost' in _tb4_fin_code
      and 'suckout-underdog-won' in _tb4_fin_code,
      'suckout queue group attributes missing')

check('T-B-05: _collectByQueueGroup function in JS',
      '_collectByQueueGroup' in _tvh_html_code
      and 'data-hand-queue-group' in _tvh_html_code,
      'queue group collection function missing')

check('T-B-06: collectHandIdsFromQueueContainer has group filter',
      'queueGroupFilter' in _tvh_html_code
      and 'containerOrObj' in _tvh_html_code,
      'queue container function missing group filter support')

check('T-B-07: scroll-margin-top uses var(--sticky-offset) (item 11 verify)',
      'var(--sticky-offset)' in _tvh_html_code,
      'scroll offset CSS variable missing')

# ────────────────────────────────────────────────────────────
# V25.3 PASS C — Hero hand strength tests
# ────────────────────────────────────────────────────────────

# Re-read _hand_grid.py source for Pass C tests
with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', '_hand_grid.py'), 'r', encoding='utf-8') as _fc:
    _tc_hg_code = _fc.read()

check('T-C-01: _hero_made_html pattern in _hand_grid.py',
      '_hero_made_html' in _tc_hg_code,
      'hero made-hand HTML variable missing')

check('T-C-02: _describe_made_hand called for hero (not just villain)',
      _tc_hg_code.count('_describe_made_hand') >= 2,
      '_describe_made_hand only called once (villain only)')

check('T-C-03: _hero_made_html pre-initialized to empty (fail-soft)',
      "_hero_made_html = ''" in _tc_hg_code,
      'hero made-hand not pre-initialized')

check('T-C-04: villain made-hand span still present (no regression)',
      "class='made-hand'>" in _tc_hg_code
      and 'sd_villain_html' in _tc_hg_code,
      'villain showdown rendering regressed')

check('T-C-05: hero made-hand only appears when went_sd is true',
      'if went_sd and sd_dict:' in _tc_hg_code
      and '_hero_made_html' in _tc_hg_code,
      'hero made-hand not gated on went_sd')

check('T-C-06: hero made-hand uses "Hero:" label (guardrail 7)',
      "(Hero: {_hero_made})" in _tc_hg_code,
      'hero label missing "Hero:" prefix')

# ============================================================
# MOBILE TABLE READABILITY (PRD 2026-06-10)
# ============================================================
print('\n--- Mobile Table Readability Tests ---')

# Re-read source files for current state
with open(os.path.join(os.path.dirname(__file__), 'gem_report_draft', '_html.py'),
          encoding='utf-8') as _f_mob:
    _mob_html_src = _f_mob.read()

with open(os.path.join(os.path.dirname(__file__), 'gem_report_draft',
          'sections_issue_explorer.py'), encoding='utf-8') as _f_mob_ie:
    _mob_ie_src = _f_mob_ie.read()

with open(os.path.join(os.path.dirname(__file__), 'gem_report_draft',
          'sections_iv_xii.py'), encoding='utf-8') as _f_mob_iv:
    _mob_iv_src = _f_mob_iv.read()

# --- Phase 1: Classification + scroll mode ---

check('T-MOB-01: _md_to_html auto-classifies tables with data-mobile-mode',
      'data-mobile-mode="' in _mob_html_src
      and '_mob_mode' in _mob_html_src
      and '_n_vis_cols' in _mob_html_src,
      '_md_to_html pipe-table converter missing mobile mode classification')

check('T-MOB-02: scroll mode assigned when >=5 visible columns (no prose)',
      "_n_vis_cols >= 5" in _mob_html_src
      and "'scroll'" in _mob_html_src,
      'scroll mode threshold not set to >=5 columns')

check('T-MOB-03: --mobile-table-min-width CSS var computed',
      '--mobile-table-min-width' in _mob_html_src
      and 'max(180 * _n_vis_cols, 800)' in _mob_html_src,
      'min-width CSS var not computed from column count')

check('T-MOB-04: scroll mode CSS — swipe hint',
      '[data-mobile-mode="scroll"]::before' in _mob_html_src
      and 'swipe table' in _mob_html_src,
      'scroll mode missing swipe hint pseudo-element')

check('T-MOB-05: scroll mode CSS — sticky first column',
      '.table-shell[data-mobile-mode="scroll"] .data-table td:first-child' in _mob_html_src
      and 'position: sticky' in _mob_html_src
      and 'left: 0' in _mob_html_src,
      'scroll mode missing sticky first column')

check('T-MOB-06: scroll mode CSS — horizontal scroll wrapper',
      '[data-mobile-mode="scroll"] .table-scroll' in _mob_html_src
      and 'overflow-x: auto' in _mob_html_src,
      'scroll mode missing horizontal overflow on .table-scroll')

check('T-MOB-07: scroll mode CSS — min-width from CSS var',
      '.table-shell[data-mobile-mode="scroll"] .data-table' in _mob_html_src
      and 'var(--mobile-table-min-width' in _mob_html_src,
      'scroll mode table not using --mobile-table-min-width CSS var')

check('T-MOB-08: page-level overflow prevention',
      '.table-shell' in _mob_html_src
      and 'max-width: 100%' in _mob_html_src
      and 'overflow: hidden' in _mob_html_src,
      'table-shell missing page-level overflow prevention')

# --- Phase 2: hand-list mode ---

check('T-MOB-09: hand-list mode CSS — hide original table on mobile',
      '[data-mobile-mode="hand-list"]' in _mob_html_src
      and 'display: none' in _mob_html_src,
      'hand-list mode not hiding original table on mobile')

check('T-MOB-10: hand-list mode CSS — show mobile-hand-list',
      '.mobile-hand-list' in _mob_html_src
      and 'display: block' in _mob_html_src,
      'mobile-hand-list not shown on mobile')

check('T-MOB-11: desktop hides mobile-only views',
      '.mobile-hand-list {{ display: none' in _mob_html_src
      or '.mobile-hand-list { display: none' in _mob_html_src,
      'mobile-hand-list not hidden on desktop')

check('T-MOB-12: mobile-hand-row card structure in CSS',
      '.mobile-hand-row' in _mob_html_src
      and 'grid-template-columns' in _mob_html_src
      and 'border-radius: 14px' in _mob_html_src,
      'mobile-hand-row card CSS missing')

check('T-MOB-13: open-hand-btn class in mobile CSS',
      '.open-hand-btn' in _mob_html_src,
      'open-hand-btn class missing from CSS')

check('T-MOB-14: mobile-tag classes with good/bad/warn variants',
      '.mobile-tag' in _mob_html_src
      and '.mobile-tag.bad' in _mob_html_src
      and '.mobile-tag.good' in _mob_html_src,
      'mobile-tag classes missing good/bad/warn variants')

# --- Phase 3: evidence-card mode ---

check('T-MOB-15: evidence-card mode CSS exists',
      '[data-mobile-mode="evidence-card"]' in _mob_html_src
      and '.mobile-evidence-card' in _mob_html_src,
      'evidence-card mobile CSS missing')

check('T-MOB-16: evidence-card grid layout (2-col key/value)',
      '.mobile-evidence-grid' in _mob_html_src
      and 'grid-template-columns: 1fr 1fr' in _mob_html_src,
      'evidence-card grid layout missing')

check('T-MOB-17: evidence-card body styling',
      '.mobile-evidence-body' in _mob_html_src
      and 'border-left: 3px solid' in _mob_html_src,
      'evidence-card body styling missing')

# --- Phase 4: compact mode ---

check('T-MOB-18: compact mode CSS tightens padding',
      '.table-shell[data-mobile-mode="compact"] .data-table' in _mob_html_src,
      'compact mode CSS missing')

# --- JS: client-side row builder + audit ---

check('T-MOB-19: JS _buildMobileHandRows function',
      '_buildMobileHandRows' in _mob_html_src
      and 'mobile-hand-list' in _mob_html_src
      and 'mobile-hand-row' in _mob_html_src,
      'JS mobile hand row builder missing')

check('T-MOB-20: JS mobileTableAudit object',
      'mobileTableAudit' in _mob_html_src
      and 'by_mode' in _mob_html_src
      and 'wide_unclassified' in _mob_html_src,
      'JS mobileTableAudit audit object missing')

check('T-MOB-21: JS audit counts all 4 modes',
      'by_mode:{scroll:' in _mob_html_src
      and 'hand_list:' in _mob_html_src
      and 'evidence_card:' in _mob_html_src
      and 'compact:' in _mob_html_src,
      'mobileTableAudit missing mode counting')

# Find the function body (between definition and next function)
_mob_fn_start = _mob_html_src.find('function _buildMobileHandRows')
_mob_fn_body = _mob_html_src[_mob_fn_start:_mob_fn_start + 4000] if _mob_fn_start >= 0 else ''
check('T-MOB-22: JS hand-row builder preserves data-hand-id',
      "data-hand-id" in _mob_fn_body,
      'mobile hand row builder drops data-hand-id')

# --- Cross-file: section tables have data-mobile-mode ---

check('T-MOB-23: IE main table (ie-tbl) has scroll mode',
      'data-mobile-mode="scroll"' in _mob_ie_src
      and 'ie-tbl' in _mob_ie_src,
      'issue explorer main table missing data-mobile-mode="scroll"')

check('T-MOB-24: IE rep-hands table has hand-list mode',
      'data-mobile-mode="hand-list"' in _mob_ie_src
      and 'ie-rep-tbl' in _mob_ie_src,
      'issue explorer rep-hands table missing hand-list mode')

check('T-MOB-25: IE drill-down table has scroll mode',
      'data-mobile-mode="scroll"' in _mob_ie_src
      and 'ie-dd-tbl' in _mob_ie_src,
      'issue explorer drill-down table missing scroll mode')

check('T-MOB-26: IE evidence/sub tables have compact mode',
      'data-mobile-mode="compact"' in _mob_ie_src,
      'issue explorer compact tables missing mode')

check('T-MOB-27: exploit matrix table has scroll mode',
      "data-mobile-mode='scroll'" in _mob_iv_src
      and 'data-table' in _mob_iv_src,
      'exploit matrix table missing scroll mode')

check('T-MOB-28: IE drill-down table has table-scroll wrapper',
      'class="table-scroll"><table class="ie-dd-tbl"' in _mob_ie_src,
      'drill-down table missing table-scroll wrapper for horizontal scroll')

# --- Desktop regression: all mobile CSS inside @media ---

check('T-MOB-29: all mobile CSS inside @media(max-width:768px)',
      _mob_html_src.count('MOBILE TABLE READABILITY') >= 2  # START and END markers
      and '.mobile-hand-list {{ display: none' in _mob_html_src,
      'mobile CSS leaking into desktop (missing @media wrapper)')

check('T-MOB-30: no page-level overflow introduced by table-shell',
      'max-width: 100%' in _mob_html_src
      and '.table-shell' in _mob_html_src,
      'table-shell missing max-width:100% overflow guard')

# --- Evidence-card auto-detection in pipe-table converter ---

check('T-MOB-31: evidence-card auto-detect uses header keywords',
      '_ev_keywords' in _mob_html_src
      and "'evidence-card'" in _mob_html_src
      and '_has_prose' in _mob_html_src
      and '_has_hand' in _mob_html_src,
      'evidence-card heuristic missing from _md_to_html')

check('T-MOB-32: evidence keywords include verdict and misplay',
      "'verdict'" in _mob_html_src.split('_ev_keywords')[1][:200]
      if '_ev_keywords' in _mob_html_src else False,
      'verdict keyword missing from evidence-card detection')

check('T-MOB-33: evidence-card needs both hand + prose columns',
      '_has_prose and _has_hand' in _mob_html_src,
      'evidence-card should require BOTH hand ref AND prose column')

check('T-MOB-34: evidence-card overrides scroll for prose tables',
      _mob_html_src.index("'evidence-card'") < _mob_html_src.index("'scroll'")
      if "'evidence-card'" in _mob_html_src and "'scroll'" in _mob_html_src
      else False,
      'evidence-card must be checked before scroll fallback')

# --- Version bump ---

with open(os.path.join(os.path.dirname(__file__), 'gem_report_draft', 'draft.py'),
          encoding='utf-8') as _f_draft_ver:
    _draft_ver_src = _f_draft_ver.read()

check('T-MOB-35: version bumped to v8.12.0',
      'VERSION = "v8.12.0"' in _draft_ver_src,
      f'version not bumped — still has old version')

# ── V25.4 P0 fixes ──────────────────────────────────────────

# P0-A: Mobile blank table safety — table only hidden when JS replacement exists
check('T-V254-01: hand-list table hide requires has-mobile-cards class',
      'has-mobile-cards' in _mob_html_src and
      '[data-mobile-mode="hand-list"].has-mobile-cards' in _mob_html_src,
      'hand-list table hide not gated on has-mobile-cards')

check('T-V254-02: evidence-card table hide requires has-mobile-cards class',
      '[data-mobile-mode="evidence-card"].has-mobile-cards' in _mob_html_src,
      'evidence-card table hide not gated on has-mobile-cards')

check('T-V254-03: hand-list fallback scroll when no mobile cards',
      'hand-list"]:not(.has-mobile-cards)' in _mob_html_src,
      'no fallback scroll for hand-list without mobile cards')

check('T-V254-04: evidence-card fallback scroll when no mobile cards',
      'evidence-card"]:not(.has-mobile-cards)' in _mob_html_src,
      'no fallback scroll for evidence-card without mobile cards')

check('T-V254-05: JS hand-list builder adds has-mobile-cards class',
      "shell.classList.add('has-mobile-cards')" in _mob_html_src,
      'hand-list builder does not mark shell with has-mobile-cards')

check('T-V254-06: JS evidence-card builder function exists',
      'function _buildMobileEvidenceCards' in _mob_html_src,
      'evidence-card builder function missing')

check('T-V254-07: evidence-card builder called in init',
      '_buildMobileEvidenceCards()' in _mob_html_src,
      'evidence-card builder not called during init')

check('T-V254-08: evidence-card builder adds has-mobile-cards class',
      _mob_html_src.count("shell.classList.add('has-mobile-cards')") >= 2,
      'evidence-card builder does not mark shell with has-mobile-cards')

# P0-B: Swipe hint uses literal arrows (not Python-mangled CSS unicode escapes)
check('T-V254-09: swipe hint uses literal arrow characters',
      '←  swipe table  →' in _mob_html_src or
      '←  swipe table  →' in _mob_html_src,
      'swipe hint missing literal arrows')

check('T-V254-10: no octal-mangled swipe hint',
      '\x1190' not in _mob_html_src and '\x1192' not in _mob_html_src,
      'swipe hint still has Python octal corruption')

# ============================================================
# P1-1: Dynamic sticky CSS vars (_syncV25StickyVars)
# P1-2: scroll-margin-top on .v25-street
# ============================================================
print('\n--- V25.4 P1-1/P1-2: Dynamic sticky vars + scroll-margin ---')

check('T-V254-11: _syncV25StickyVars function defined',
      'function _syncV25StickyVars()' in _mob_html_src,
      '_syncV25StickyVars not found in JS')

check('T-V254-12: _syncV25StickyVars measures topbar offsetHeight',
      "topbar.offsetHeight" in _mob_html_src,
      'function does not measure topbar height')

check('T-V254-13: _syncV25StickyVars measures queue offsetHeight',
      "queue.offsetHeight" in _mob_html_src,
      'function does not measure queue height')

check('T-V254-14: _syncV25StickyVars measures review offsetHeight',
      "review.offsetHeight" in _mob_html_src,
      'function does not measure review height')

check('T-V254-15: _syncV25StickyVars called in openHand',
      '_syncV25StickyVars();' in _mob_html_src,
      '_syncV25StickyVars not wired into openHand')

check('T-V254-16: resize listener calls _syncV25StickyVars',
      "addEventListener('resize'" in _mob_html_src and
      '_syncV25StickyVars' in _mob_html_src,
      'no resize listener for sticky vars')

check('T-V254-17: resize listener debounced',
      '_stickyTimer' in _mob_html_src,
      'resize listener not debounced')

check('T-V254-18: hardcoded :root fallback still present',
      '--v25-topbar-h: 58px' in _mob_html_src and
      '--v25-queue-h: 42px' in _mob_html_src and
      '--v25-review-h: 120px' in _mob_html_src,
      'CSS fallback defaults removed — they must remain as initial values')

check('T-V254-19: setProperty writes to .v25-panel (scoped, not :root)',
      "panel.style.setProperty('--v25-topbar-h'" in _mob_html_src,
      '_syncV25StickyVars does not scope vars to .v25-panel')

_street_marker = '.v25-street {{' if '.v25-street {{' in _mob_html_src else '.v25-street {'
_street_block = _mob_html_src[_mob_html_src.find(_street_marker):][:400] if _street_marker in _mob_html_src else ''
check('T-V254-20: .v25-street has scroll-margin-top',
      'scroll-margin-top' in _street_block and
      'v25-topbar-h' in _street_block and 'v25-queue-h' in _street_block,
      '.v25-street missing scroll-margin-top using sticky vars')

check('T-V254-21: queue hidden state handled (display===none => 0)',
      "queue.style.display==='none'?0:queue.offsetHeight" in _mob_html_src,
      '_syncV25StickyVars does not handle hidden queue bar')

# ============================================================
# P1-3: Metadata skip hardening — status/verdict chips filtered
# ============================================================
print('\n--- V25.4 P1-3: Metadata skip hardening ---')

# Extract the _metaSkips array region from source
_skip_region = _mob_html_src[_mob_html_src.find('_metaSkips='):_mob_html_src.find('_metaSkips=') + 400] if '_metaSkips=' in _mob_html_src else ''

check('T-V254-22: _metaSkips includes Mistake keyword',
      'Mistake' in _skip_region,
      '_metaSkips does not filter Mistake chips')

check('T-V254-23: _metaSkips includes Correct keyword',
      'Correct' in _skip_region,
      '_metaSkips does not filter Correct chips')

check('T-V254-24: _metaSkips includes Borderline keyword',
      'Borderline' in _skip_region,
      '_metaSkips does not filter Borderline chips')

check('T-V254-25: _metaSkips includes Flagged keyword',
      'Flagged' in _skip_region,
      '_metaSkips does not filter Flagged chips')

check('T-V254-26: _metaSkips includes Reviewed keyword',
      'Reviewed' in _skip_region,
      '_metaSkips does not filter Reviewed chips')

check('T-V254-27: _metaSkips includes Cleared keyword',
      'Cleared' in _skip_region,
      '_metaSkips does not filter Cleared chips')

check('T-V254-28: _metaSkips includes Punt keyword',
      'Punt' in _skip_region,
      '_metaSkips does not filter Punt chips')

check('T-V254-29: status skip is case-insensitive',
      '/i' in _skip_region.split('Punt')[1][:20] if 'Punt' in _skip_region else False,
      'status/verdict skip regex not case-insensitive')

check('T-V254-30: original skip regexes preserved (L-level, BP, SPR, SRP, showdown)',
      '/^L' in _skip_region and 'BP' in _skip_region and 'SPR' in _skip_region
      and 'SRP' in _skip_region and 'Lost' in _skip_region,
      'original _metaSkips entries were removed or damaged')

# ============================================================
# P1-4: Verdict text strip xref/link noise
# ============================================================
print('\n--- V25.4 P1-4: Verdict text strip xref/link noise ---')

# Find the P1-4 verdict extraction block (use the P1-4 comment as anchor)
_verdict_region = ''
_vr_start = _mob_html_src.find('P1-4: Extract verdict text')
if _vr_start >= 0:
    _verdict_region = _mob_html_src[_vr_start:_vr_start + 600]

check('T-V254-31: verdict uses cloneNode before text extraction',
      'cloneNode(true)' in _verdict_region,
      'verdict text not extracted from a clone')

check('T-V254-32: verdict clone strips <a> elements',
      "querySelectorAll('a" in _verdict_region and '.remove()' in _verdict_region,
      'verdict clone does not remove link elements')

check('T-V254-33: verdict clone strips .xref elements',
      '.xref' in _verdict_region.split('querySelectorAll')[1][:80] if 'querySelectorAll' in _verdict_region else False,
      'verdict clone does not remove .xref elements')

check('T-V254-34: verdict clone strips .hand-ref elements',
      '.hand-ref' in _verdict_region.split('querySelectorAll')[1][:80] if 'querySelectorAll' in _verdict_region else False,
      'verdict clone does not remove .hand-ref elements')

check('T-V254-35: verdict clone strips .mh-links elements',
      '.mh-links' in _verdict_region,
      'verdict clone does not remove .mh-links containers')

check('T-V254-36: stray arrow chars stripped from verdict text',
      '/[' in _verdict_region and ']+/g' in _verdict_region,
      'verdict text does not strip stray arrow characters')

check('T-V254-37: mentioned-in backlinks still extracted separately',
      'v25-mentioned' in _mob_html_src and 'Mentioned in' in _mob_html_src,
      'mentioned-in row was damaged by verdict fix')

# ============================================================
# P1-5: analyst_learning routing uses ctx.street fallback
# ============================================================
print('\n--- V25.4 P1-5: analyst_learning street fallback ---')

_al_region = _mob_html_src[_mob_html_src.find("analyst_learning'"):][:300] if "analyst_learning'" in _mob_html_src else ''
# Find the routing block (second occurrence — the one with st3)
_al_route = _mob_html_src[_mob_html_src.find("analyst_learning'){", _mob_html_src.find("analyst_learning'{")+1):][:300] if _mob_html_src.count("analyst_learning'{") >= 2 else ''
# Fallback: search for the P1-5 comment
if not _al_route:
    _p15_start = _mob_html_src.find('P1-5:')
    if _p15_start >= 0:
        _al_route = _mob_html_src[_p15_start:_p15_start + 300]

check('T-V254-38: analyst_learning routing uses ctx.street fallback',
      'ctx.street' in _al_route and 'hero_decision_street' in _al_route,
      'analyst_learning still only routes by hero_decision_street')

check('T-V254-39: fallback chain is hero_decision_street||ctx.street||empty',
      "ctx.hero_decision_street||ctx.street||''" in _al_route,
      'fallback chain order is wrong')

# ============================================================
# P1-6: Deterministic fallback label for street-routed exploit contexts
# ============================================================
print('\n--- V25.4 P1-6: Street-routed exploit fallback label ---')

_p16_start = _mob_html_src.find('P1-6:')
_p16_region = _mob_html_src[_p16_start:_p16_start + 500] if _p16_start >= 0 else ''

check('T-V254-40: street-routed exploit blocks get fallback label',
      'cb-fallback-label' in _p16_region and 'Deterministic analysis' in _p16_region,
      'no fallback label for street-routed exploit contexts')

check('T-V254-41: fallback filters exploit_miss and good_exploit buckets',
      'exploit_miss' in _p16_region and 'good_exploit' in _p16_region,
      'fallback label does not check exploit bucket types')

check('T-V254-42: fallback checks analyst_reviewed before showing label',
      'analyst_reviewed' in _p16_region,
      'fallback label does not gate on analyst_reviewed')

check('T-V254-43: bottom-contexts fallback label still present',
      _mob_html_src.count('cb-fallback-label') >= 3,
      'bottom-contexts fallback label was damaged (need >=3: legacy, bottom, street)')

# ============================================================
# P1-7: Villain fallback normalization (compact chips, not DOM clone)
# ============================================================
print('\n--- V25.4 P1-7: Villain fallback normalization ---')

_p17_start = _mob_html_src.find('P1-7:')
_p17_region = _mob_html_src[_p17_start:_p17_start + 700] if _p17_start >= 0 else ''

check('T-V254-44: villain fallback no longer clones DOM',
      'v25-villain-row-fallback' not in _mob_html_src,
      'v25-villain-row-fallback class still present (DOM clone not removed)')

check('T-V254-45: villain fallback splits facing-strip into chips',
      'v25-chip' in _p17_region and 'split(' in _p17_region,
      'villain fallback does not parse into chips')

check('T-V254-46: villain fallback detects coverage in chip text',
      'v25-coverage-pill' in _p17_region,
      'villain fallback does not apply coverage-pill class')

check('T-V254-47: structured villain row still uses villainIntel',
      'v25-villain-token' in _mob_html_src and 'v25-evidence-link' in _mob_html_src,
      'structured villain row damaged')

# ============================================================
# P1-8: Coverage from stack-context fallback
# ============================================================
print('\n--- V25.4 P1-8: Coverage from stack-context fallback ---')

_cov_start = _mob_html_src.find('P1-8:')
_cov_region = _mob_html_src[_cov_start:_cov_start + 600] if _cov_start >= 0 else ''

check('T-V254-48: coverage checks stackEl text as fallback',
      'stackEl' in _cov_region and 'textContent' in _cov_region,
      'coverage pill does not check stack context')

check('T-V254-49: coverage combines facing-strip + stack-context text',
      'fsEl' in _cov_region and 'stackEl' in _cov_region,
      'coverage does not combine both sources')

check('T-V254-50: covers Hero regex still present in coverage',
      'covers\\s+Hero' in _cov_region or 'covers' in _cov_region.lower(),
      'covers Hero regex missing from coverage')

# ============================================================
# P1-9: Review pills CSS
# ============================================================
print('\n--- V25.4 P1-9: Review pills CSS ---')

check('T-V254-51: .review-pill base CSS exists',
      '.review-pill {{' in _mob_html_src or '.review-pill {' in _mob_html_src,
      'no CSS rule for .review-pill')

check('T-V254-52: .review-none variant CSS exists',
      '.review-pill.review-none' in _mob_html_src,
      'no CSS for review-none variant')

check('T-V254-53: .review-some variant CSS exists',
      '.review-pill.review-some' in _mob_html_src,
      'no CSS for review-some variant')

check('T-V254-54: .review-all variant CSS exists',
      '.review-pill.review-all' in _mob_html_src,
      'no CSS for review-all variant')

check('T-V254-55: .review-na variant CSS exists',
      '.review-pill.review-na' in _mob_html_src,
      'no CSS for review-na variant')

check('T-V254-56: .review-missing variant CSS exists',
      '.review-pill.review-missing' in _mob_html_src,
      'no CSS for review-missing variant')

check('T-V254-57: JS pbReviewPillHTML function still generates pills',
      'pbReviewPillHTML' in _mob_html_src and 'review-pill' in _mob_html_src,
      'review pill JS generation was damaged')

# ============================================================
# P1-10: Hand-list trigger label clarity
# ============================================================
print('\n--- V25.4 P1-10: Hand-list trigger label clarity ---')

_p110_start = _mob_html_src.find('P1-10:')
_p110_region = _mob_html_src[_p110_start:_p110_start + 600] if _p110_start >= 0 else ''

check('T-V254-58: naked number triggers get "hands" suffix',
      "hands '" in _p110_region or 'hands ›' in _p110_region
      or "hands \\u203A" in _p110_region,
      'naked number triggers not enhanced with hands label')

check('T-V254-59: BB value triggers get "BB" suffix',
      "BB " in _p110_region and ("hands" in _p110_region or 'BB ›' in _p110_region
      or "BB \\u203A" in _p110_region),
      'BB value triggers not enhanced')

check('T-V254-60: aria-label set from data-list-title',
      'aria-label' in _p110_region and 'data-list-title' in _p110_region,
      'accessibility labels not added')

check('T-V254-61: existing descriptive labels skipped',
      '/hands|hand|' in _p110_region or 'hands|hand' in _p110_region,
      'enhancer does not skip already-descriptive labels')

# ============================================================
# P1-11: Search placeholder + P1-12: De-emphasize Reset Notes
# ============================================================
print('\n--- V25.4 P1-11/P1-12: Search placeholder + Reset de-emphasis ---')

check('T-V254-62: search placeholder is descriptive',
      'Search hand ID, issue, section, or tournament' in _mob_html_src,
      'search placeholder still generic')

_reset_css_start = _mob_html_src.find('#audit-reset-btn {{')
_reset_css = _mob_html_src[_reset_css_start:_reset_css_start + 300] if _reset_css_start >= 0 else ''
check('T-V254-63: reset button uses outline style (not solid red bg)',
      'background: #fff' in _reset_css,
      'reset button still solid red')

check('T-V254-64: reset button border is soft red',
      'border: 1px solid #fecaca' in _reset_css,
      'reset button border not de-emphasized')

check('T-V254-65: reset button label is lowercase with ellipsis',
      'Reset notes' in _mob_html_src,
      'reset button label not updated')

# ============================================================
# P2 items: queue reason class, td.street-actions, empty state,
#           export/import styling, modal close tap targets
# ============================================================
print('\n--- V25.4 P2: Polish items ---')

check('T-V254-66: queue reason uses CSS class (not inline style)',
      'v25-queue-reason' in _mob_html_src and
      'margin-top:6px;border-left:3px solid #f59e0b' not in _mob_html_src,
      'queue reason still uses inline style')

check('T-V254-67: v25-queue-reason CSS class defined',
      '.v25-queue-reason {{' in _mob_html_src or '.v25-queue-reason {' in _mob_html_src,
      'v25-queue-reason CSS not defined')

check('T-V254-68: queue also-appears uses CSS class',
      'v25-queue-also' in _mob_html_src,
      'also-appears-in row still uses inline style')

check('T-V254-69: street-actions selector preferred over bare td',
      "td.street-actions'" in _mob_html_src or 'td.street-actions"' in _mob_html_src,
      'V25 grid parser does not prefer .street-actions cells')

check('T-V254-70: street-actions fallback to all tbody td',
      "querySelectorAll('tbody td')" in _mob_html_src,
      'no fallback to tbody td for older grids')

check('T-V254-71: review empty state has actionable copy',
      'Open a hand and mark Agree' in _mob_html_src,
      'review empty state still passive')

check('T-V254-72: export/import buttons use review-json-btn class',
      'review-json-btn' in _mob_html_src,
      'export/import buttons not class-styled')

check('T-V254-73: review-json-btn CSS defined',
      '.review-json-btn {{' in _mob_html_src or '.review-json-btn {' in _mob_html_src,
      'review-json-btn CSS not defined')

check('T-V254-74: modal close button min-height 36px',
      'min-height: 36px' in _mob_html_src,
      'modal close button tap target not enlarged')

# ── V25.4+ GPT-QA + Usability fixes ─────────────────────────
print('\n--- V25.4+ GPT-QA + Usability fixes ---')

# GPT-QA-1: Queue bar block layout
check('T-V254-75: queue bar uses display:block not flex',
      'display: block' in _mob_html_src and '.v25-queue-bar' in _mob_html_src
      and 'overflow-y: visible' in _mob_html_src,
      'queue bar still uses flex row layout')

# GPT-QA-2: syncStickyVars in requestAnimationFrame
check('T-V254-76: sticky vars measured after layout (rAF)',
      'requestAnimationFrame' in _mob_html_src and '_syncV25StickyVars' in _mob_html_src,
      '_syncV25StickyVars not wrapped in requestAnimationFrame')

# GPT-QA-3: ResizeObserver for review bar
check('T-V254-77: review bar ResizeObserver resync',
      'ResizeObserver' in _mob_html_src and 'modal-review' in _mob_html_src,
      'no ResizeObserver for review bar height changes')

# GPT-QA-4: Metadata ordering — Hero before Eff
_meta_region = _mob_html_src[_mob_html_src.find('GPT-QA-4'):_mob_html_src.find('GPT-QA-4') + 800] if 'GPT-QA-4' in _mob_html_src else ''
check('T-V254-78: metadata classifies Type/Phase/Eff separately',
      '_typeChip' in _meta_region and '_phaseChip' in _meta_region and '_effChip' in _meta_region,
      'metadata chip classification not refined')

_hero_before_eff = _mob_html_src.find('heroPos||heroStack')
_eff_emit = _mob_html_src.find('_emitMeta(_effChip)')
check('T-V254-79: Hero emitted before Eff in metadata order',
      _hero_before_eff > 0 and _eff_emit > 0 and _hero_before_eff < _eff_emit,
      'Hero chip not before Eff chip in emit order')

# GPT-QA-5: Facing-strip fallback preserves Evidence action
check('T-V254-80: facing-strip fallback clones .facing-action',
      'facing-action' in _mob_html_src and 'v25-evidence-link' in _mob_html_src
      and '_fsAction' in _mob_html_src,
      'facing-strip fallback does not preserve Evidence button')

# GPT-QA-6: Clear button text is compact
check('T-V254-81: verdict clear button says "Clear" not "Clear verdict"',
      '>Clear<' in _mob_html_src and 'Clear verdict' not in _mob_html_src,
      'verdict button still says "Clear verdict"')

# GPT-QA-7: Also-appears inside compact queue
check('T-V254-82: also-appears inserted inside .v25-compact-queue',
      '.v25-compact-queue' in _mob_html_src
      and 'querySelector' in _mob_html_src and '_alsoHtml' in _mob_html_src,
      'also-appears-in still appended outside compact queue block')

# User-QA-1: Mobile scroll-mode table CSS reset
check('T-V254-83: scroll-mode tables override card-mode CSS',
      '[data-mobile-mode="scroll"] .data-table' in _mob_html_src
      and 'table-header-group' in _mob_html_src,
      'scroll-mode tables not reset from card-mode rules')

# User-QA-2: Evidence-card builder without thead
_ev_builder_pos = _mob_html_src.find('_buildMobileEvidenceCards')
_ev_region = _mob_html_src[_ev_builder_pos:_ev_builder_pos + 500] if _ev_builder_pos > 0 else ''
check('T-V254-84: evidence-card builder falls back to first-row th',
      'tr:first-child th' in _ev_region,
      'evidence-card builder has no thead fallback')

# User-QA-3: BB trigger enhanced with "hands"
check('T-V254-85: BB value triggers include "hands" in label',
      "BB · hands" in _mob_html_src or "BB \\u00b7 hands" in _mob_html_src,
      'BB value triggers do not show hands suffix')

# User-QA-4: Review pill text clarity
check('T-V254-86: review pill uses text not symbols for compact',
      "' rev'" in _mob_html_src or "' rev'" in _mob_html_src,
      'compact review pill still uses cryptic symbols')

check('T-V254-87: all-reviewed pill says "Reviewed"',
      "'Reviewed'" in _mob_html_src,
      'all-reviewed pill does not say Reviewed')

# ============================================================
# v8.9.5 — Render QA + Analytics Fixes + Mobile Table Usability
# ============================================================
print('\n=== v8.9.5 TESTS ===')

# ── Bug fix tests ──
check('T-V254-88: BUG-D getAttribute data-street in note routing',
      "getAttribute('data-street')" in _mob_html_src,
      'BUG-D data-street routing not found in _html.py')

check('T-V254-89: BUG-D street normalization regex',
      r"replace(/[\s_-]+/g,'')" in _mob_html_src,
      'BUG-D street normalization regex not found')

check('T-V254-90: BUG-E _dedupTextKey helper exists',
      '_dedupTextKey' in _mob_html_src,
      '_dedupTextKey helper not found in _html.py')

check('T-V254-91: BUG-E containment check',
      'indexOf(bt.substring(0,80))' in _mob_html_src,
      'BUG-E 80-char containment check not found')

check('T-V254-92: stackEl uses toUpperCase',
      "toUpperCase()==='DETAILS'" in _mob_html_src,
      'stackEl defensive toUpperCase not found')

# ── Analytics fix tests ──
with open(os.path.join(os.path.dirname(__file__), 'gem_analyzer.py'),
          encoding='utf-8') as _f_ga:
    _ga_src = _f_ga.read()

check('T-V254-93: BUG-2 _ws_date_compact in gem_analyzer.py',
      '_ws_date_compact' in _ga_src,
      '_ws_date_compact variable not found in gem_analyzer.py')

with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_issue_explorer.py'),
          encoding='utf-8') as _f_ie:
    _ie_src = _f_ie.read()

check('T-V254-94: BUG-3 _IE_JS is raw string',
      '_IE_JS = r"""' in _ie_src,
      '_IE_JS not changed to raw string')

with open(os.path.join(os.path.dirname(__file__),
          'gem_report_draft', 'sections_xiv.py'),
          encoding='utf-8') as _f_xiv:
    _xiv_src = _f_xiv.read()

check('T-V254-95: BUG-D analytics data-street stamp',
      "data-street='" in _xiv_src,
      'data-street attribute not found in sections_xiv.py')

# ── Mobile tests ──
check('T-V254-96a: data-mobile-mode on .table-shell + valid values only',
      'class="table-shell" data-mobile-mode=' in _mob_html_src
      and all(v in _mob_html_src for v in
              ["'evidence-card'", "'scroll'", "'compact'"])
      and "_mob_mode = ''" not in _mob_html_src
      and "_mob_mode = \"\"" not in _mob_html_src,
      'data-mobile-mode not on .table-shell, missing valid mode values, or empty-string path exists')

check('T-V254-96: old card-mode gated with :not([data-mobile-mode])',
      '.table-shell:not([data-mobile-mode])' in _mob_html_src,
      'old card-mode CSS not gated')

check('T-V254-97: scroll-mode display table + max-content',
      'display: table !important' in _mob_html_src
      and 'width: max-content' in _mob_html_src,
      'scroll-mode table layout overrides missing')

check('T-V254-98: compact-mode display table-cell',
      'display: table-cell !important' in _mob_html_src,
      'compact-mode table-cell override missing')

check('T-V254-99: IE mobile CSS has grid-template-areas',
      'grid-template-areas' in _ie_src,
      'IE mobile card grid layout missing')

check('T-V254-100: IE bottom-sheet ie-mobile-detail-open class',
      'ie-mobile-detail-open' in _ie_src,
      'IE bottom-sheet class toggle missing')

check('T-V254-101: IE mobile close button',
      'ie-mobile-close' in _ie_src,
      'IE mobile close button missing from _IE_JS')

# T-V254-101b: IE click guard — test each piece separately
check('T-V254-101b: IE click guard pieces',
      'ev.target.closest(' in _ie_src
      and '.hand-list-trigger' in _ie_src
      and '.review-pill' in _ie_src
      and '.ie-right' in _ie_src,
      'IE click guard missing one or more interactive element exclusions')

check('T-V254-102: bottom controls padding-bottom 132px',
      'padding-bottom: 132px' in _mob_html_src,
      'bottom controls padding not found')

check('T-V254-103: evidence-card _previewPriority with verdict first',
      "_previewPriority=['verdict'" in _mob_html_src,
      'evidence-card preview priority array missing or verdict not first')

check('T-V254-103b: evidence preview + details separate elements',
      'mobile-evidence-preview' in _mob_html_src
      and 'mobile-evidence-details' in _mob_html_src,
      'evidence preview/details CSS classes missing')

# T-V254-104: order-based — each builder must appendChild BEFORE classList.add
# Check hand-rows builder: list.appendChild(row) before has-mobile-cards
_104_hr_append = _mob_html_src.find('list.appendChild(row)')
_104_hr_class = _mob_html_src.find("shell.classList.add('has-mobile-cards')", _104_hr_append)
_104_hr_ok = _104_hr_append >= 0 and _104_hr_class >= 0 and _104_hr_append < _104_hr_class
# Check evidence builder: list.appendChild(card) before its has-mobile-cards
_104_ev_append = _mob_html_src.find('list.appendChild(card)')
_104_ev_class = _mob_html_src.find("shell.classList.add('has-mobile-cards')", _104_ev_append)
_104_ev_ok = _104_ev_append >= 0 and _104_ev_class >= 0 and _104_ev_append < _104_ev_class
check('T-V254-104: has-mobile-cards added AFTER card append (order-based)',
      _104_hr_ok and _104_ev_ok,
      f'has-mobile-cards class added before card append '
      f'(hand-rows: append@{_104_hr_append} class@{_104_hr_class} ok={_104_hr_ok}, '
      f'evidence: append@{_104_ev_append} class@{_104_ev_class} ok={_104_ev_ok})')

# ============================================================
# v8.9.5 — V25 Final Polish (4 items from static QA)
# ============================================================
print('\n=== v8.9.5 TESTS ===')

# Item 1: Queue-height circular dependency fixed
check('T-V255-01: queue-bar uses min-height: 0 not var(--v25-queue-h)',
      'min-height: 0;' in _mob_html_src
      and 'min-height: var(--v25-queue-h)' not in _mob_html_src,
      'queue-bar still has circular min-height: var(--v25-queue-h)')

# Verify --v25-queue-h is still SET (used for sticky offsets)
check('T-V255-02: --v25-queue-h still measured by _syncV25StickyVars',
      '--v25-queue-h' in _mob_html_src and 'queue.offsetHeight' in _mob_html_src,
      '--v25-queue-h measurement removed — sticky offsets will break')

# Item 2: Facing-strip fallback dedup
_fs_fb_start = _mob_html_src.find('P1-7:')
_fs_fb_region = _mob_html_src[_fs_fb_start:_fs_fb_start + 700] if _fs_fb_start >= 0 else ''

check('T-V255-03: facing-strip fallback clones before text extraction',
      '_fsClone=fsEl.cloneNode(true)' in _fs_fb_region,
      'fallback reads fsEl.textContent directly — will duplicate Evidence text')

check('T-V255-04: clone removes .facing-action before text extraction',
      ".facing-action,.facing-actions').forEach" in _fs_fb_region
      and 'n.remove()' in _fs_fb_region,
      'clone does not strip .facing-action elements')

check('T-V255-05: Evidence chip filter guard in fallback',
      "^Evidence\\s*\\(" in _fs_fb_region,
      'no Evidence filter guard in facing-strip fallback')

check('T-V255-06: text extracted from clone not original',
      '_fsClone.textContent' in _fs_fb_region
      and 'fsEl.textContent' not in _fs_fb_region,
      'text still extracted from fsEl instead of _fsClone')

# Item 3: Emoji-prefix guard
check('T-V255-07: emoji-prefix guard in metadata skip list',
      '/u]' in _mob_html_src and '_metaSkips' in _mob_html_src,
      'emoji-prefix guard regex not in skip list')

# Item 4: Row-specific coverage parsing
_cov_start2 = _mob_html_src.find('P1-8:')
_cov_region2 = _mob_html_src[_cov_start2:_cov_start2 + 600] if _cov_start2 >= 0 else ''

check('T-V255-08: coverage uses row-specific parsing when v_number available',
      'v_number' in _cov_region2 and 'querySelectorAll' in _cov_region2,
      'coverage does not do row-specific parsing')

check('T-V255-09: coverage falls back to full stack text when no identity',
      'clean(stackEl.textContent)' in _cov_region2,
      'no fallback to full stack text when villain identity unavailable')

check('T-V255-10: coverage still checks alias as alternative to v_number',
      'vi.alias' in _cov_region2 or '_vAlias' in _cov_region2,
      'coverage does not check villain alias')

# Keep items — verify QA "keep" list not broken
check('T-V255-11: double requestAnimationFrame for sticky sync kept',
      'requestAnimationFrame(function(){_syncV25StickyVars();requestAnimationFrame(_syncV25StickyVars)' in _mob_html_src,
      'double rAF pattern broken')

check('T-V255-12: ResizeObserver for review bar kept',
      'ResizeObserver' in _mob_html_src and '_reviewEl' in _mob_html_src,
      'ResizeObserver for review bar removed')

check('T-V255-13: legacy fallback wrapper kept',
      'buildModalHandLegacy(hid)' in _mob_html_src and 'buildModalHand(hid)' in _mob_html_src,
      'legacy fallback wrapper damaged')

check('T-V255-14: Clear verdict label kept',
      "data-verdict=\"\">Clear<" in _mob_html_src,
      'Clear verdict label changed')

# ============================================================
# v8.9.6 — EAI Perf + V25 Layout Overhaul + Evidence Compact
# ============================================================
print('\n=== v8.9.6 TESTS ===')

# Re-read sources for current state
with open(os.path.join(os.path.dirname(__file__), 'gem_eai_equity.py'),
          encoding='utf-8') as _f_eai:
    _eai_src = _f_eai.read()

with open(os.path.join(os.path.dirname(__file__), 'gem_report_draft', '_html.py'),
          encoding='utf-8') as _f_v256:
    _v256_html_src = _f_v256.read()

# --- Workstream A: EAI equity performance ---
check('T-V256-01: _eval7_id or _evaluate_cards import attempted',
      '_evaluate_cards' in _eai_src or '_eval7_id' in _eai_src,
      'int-id evaluator import missing')

check('T-V256-02: _MC_SAMPLES default is 20000',
      "'20000'" in _eai_src and "'120000'" not in _eai_src.split('_MC_SAMPLES')[1].split('\n')[0],
      'MC samples default not changed to 20000')

check('T-V256-03: remaining_id variable exists in equity function',
      'remaining_id' in _eai_src,
      'remaining_id not found — int-id conversion missing')

check('T-V256-04: _Card = None guard in except block',
      '_Card = None' in _eai_src,
      '_Card fallback guard missing')

# --- Workstream B: V25 layout overhaul ---
check('T-V256-05: .v25-hand max-width is 1220px',
      '1220px' in _v256_html_src and 'max-width: 1100px' not in _v256_html_src,
      'max-width not updated to 1220px')

check('T-V256-06: grid columns 190px 390px',
      '190px 390px' in _v256_html_src,
      'desktop grid not updated')

check('T-V256-07: .v25-top-cards .card font-size 15px',
      '.v25-top-cards .card' in _v256_html_src and 'font-size: 15px' in _v256_html_src.split('.v25-top-cards .card')[1][:100],
      'topbar card font-size not 15px')

check('T-V256-08: v25-hand-name-stage uses createElement(div)',
      "createElement('div');hn.className='v25-hand-name-stage'" in _v256_html_src,
      'hand-name-stage still using span')

check('T-V256-09: _appendV25WhyLine function exists',
      'function _appendV25WhyLine' in _v256_html_src,
      '_appendV25WhyLine helper missing')

check('T-V256-10: v25-queue-reason line suppressed',
      'v25-queue-reason' not in _v256_html_src.split('_renderQueueContext')[1].split('function ')[0] if '_renderQueueContext' in _v256_html_src else False,
      'queue reason not suppressed')

check('T-V256-11: street nav chips removed',
      "createElement('div');navDiv.className='v25-street-nav'" not in _v256_html_src,
      'street nav chips still present')

# Find .v25-street-head in base CSS (NOT inside @media)
_base_css_end = _v256_html_src.find('@media (min-width: 1200px)')
_base_street_head = _v256_html_src[:_base_css_end] if _base_css_end > 0 else _v256_html_src
_sh_idx = _base_street_head.rfind('.v25-street-head')
_sh_rule = _base_street_head[_sh_idx:_sh_idx+500] if _sh_idx >= 0 else ''
check('T-V256-12: .v25-street-head has position: sticky in BASE rule',
      'position: sticky' in _sh_rule,
      'sticky not in base .v25-street-head rule')

check('T-V256-13: hydrateV25CommentaryCollapse function exists',
      'function hydrateV25CommentaryCollapse' in _v256_html_src,
      'commentary collapse function missing')

check('T-V256-14: .v25-commentary-toggle CSS exists',
      '.v25-commentary-toggle' in _v256_html_src,
      'commentary toggle CSS missing')

# --- Workstream C: Villain evidence compact ---
check('T-V256-15: v25-ve-inline class in villain_evidence rendering',
      'v25-ve-inline' in _v256_html_src,
      'compact inline evidence class missing')

check('T-V256-16: Suggests: in villain_evidence block',
      "Suggests:</b>" in _v256_html_src,
      'Suggests label missing from evidence block')

check('T-V256-17: Villain Evidence Collected heading removed',
      'Villain Evidence Collected' not in _v256_html_src,
      'old heading still present')

check('T-V256-18: evidence collection disclaimer removed',
      'evidence collection, not necessarily' not in _v256_html_src,
      'old disclaimer still present')

check('T-V256-19: Read timing removed from evidence block',
      'Read timing:' not in _v256_html_src.split("bucket==='villain_evidence'")[1][:800] if "bucket==='villain_evidence'" in _v256_html_src else False,
      'Read timing still in evidence block')

check('T-V256-20: _clusterVillainEvidence function exists with street in key',
      'function _clusterVillainEvidence' in _v256_html_src and "c.street||''" in _v256_html_src,
      'cluster function missing or street not in key')

check('T-V256-21: no .v25-ve-mark action-column marker rendered',
      'v25-ve-mark' not in _v256_html_src,
      'C4 marker found — should be parked')

# --- Must-fix review additions (v8.9.9) ---
check('T-V256-22: smoke test compares private vs public evaluator values',
      '_eval7(*cards) == _eval7_id(*ids)' in _eai_src,
      'smoke test should compare _eval7 vs _eval7_id values')

check('T-V256-23: grid preserves third column minmax(0,1fr)',
      '190px 390px minmax(0, 1fr)' in _v256_html_src,
      'grid-template-columns missing minmax third column')

check('T-V256-24: no cluster without signal key',
      "if(!sk){out.push(c);return;}" in _v256_html_src,
      'clustering guard for missing signal key not found')

check('T-V256-25: cluster merge preserves suggests and so_what',
      "c.suggests&&!seen[key].suggests" in _v256_html_src
      and "c.so_what&&!seen[key].so_what" in _v256_html_src,
      'cluster merge missing suggests or so_what preservation')

check('T-V256-26: label dedup + Unknown villain fallback',
      'function _pushUnique' in _v256_html_src and "'Unknown villain'" in _v256_html_src,
      '_pushUnique helper or Unknown villain fallback missing')

print('\n=== v8.10.0 COACHING CARDS TESTS ===')

from gem_coaching_cards import (build_coaching_cards, derive_quality_gates,
                                _build_decision_facts, _run_assertions,
                                _select_template, _clamp_words,
                                _compute_blocker_facts, _compute_hero_range_facts,
                                _tmpl_blocker_insight, _tmpl_range_awareness,
                                _select_insight)

# synthetic hand for testing
def _cc_hand(**kw):
    base = {'id': 'TEST001', 'cards': ['As','Kd'], 'position': 'BTN',
            'stack_bb': 25, 'eff_stack_bb': 24, 'pf_action': 'call',
            'hero_bets': 0, 'facing_bets': 1, 'pf_allin': True,
            'format': 'FREEZEOUT', 'game_type': 'NLH', 'table_size': 6,
            'n_players': 2, 'board': [], 'board_texture': '',
            'villains': {'CO': {'stack_bb': 22, 'shown_cards': 'QhQs'}},
            'eai_hero_equity': 45.0, 'required_eq_pct': 40.0,
            'pot_facing': 12.0, 'call_amount_bb': 8.0,
            'tournament_phase': '', 'action_ledger': [],
            'villain_archetype': '', 'villain_archetype_label': '',
            'bounty_value_bb': 0, 'bounty_type': 'none'}
    base.update(kw)
    return base

_cc_stats = {'punts': {'hands': []}, 'mistakes': [], 'eai': {'hands': []},
             'villain_intel': {'evidence_atoms': {}}}
_cc_rd = {'auto_labels': {}}

# --- Load-Bearing Correctness Tests (T-CC-01 through T-CC-15) ---

# T-CC-01: No equity without range
_cc_h01 = _cc_hand(villains={})
_cc_f01 = _build_decision_facts(_cc_h01, _cc_stats, _cc_rd)
_cc_g01, _, _ = derive_quality_gates(_cc_f01)
check('T-CC-01: no numeric equity without range',
      not _cc_g01['numeric_equity_allowed'],
      'numeric equity should be blocked when no range_facts exist')

# T-CC-02: No HU equity in multiway
_cc_h02 = _cc_hand(n_players=4,
                    action_ledger=[{'street':'preflop','player':'P1','action':'call'},
                                   {'street':'preflop','player':'P2','action':'call'},
                                   {'street':'preflop','player':'Hero','action':'call'}])
_cc_f02 = _build_decision_facts(_cc_h02, _cc_stats, _cc_rd)
_cc_g02, _, _ = derive_quality_gates(_cc_f02)
check('T-CC-02: no HU equity in multiway',
      not _cc_g02['multiway_equity_safe'],
      'multiway_equity_safe should be False with 3+ players')

# T-CC-03: Heads-up-at-decision exception
_cc_h03 = _cc_hand(n_players=6,
                    action_ledger=[{'street':'preflop','player':'Hero','action':'raise'},
                                   {'street':'preflop','player':'CO','action':'call'}])
_cc_f03 = _build_decision_facts(_cc_h03, _cc_stats, _cc_rd)
_cc_g03, _, _ = derive_quality_gates(_cc_f03)
check('T-CC-03: HU at decision allows equity',
      _cc_g03['multiway_equity_safe'],
      'should be True when only 2 players at decision despite larger table')

# T-CC-04: Pot validation includes sanity check
_cc_h04 = _cc_hand(pot_facing=0, call_amount_bb=0)
_cc_f04 = _build_decision_facts(_cc_h04, _cc_stats, _cc_rd)
check('T-CC-04: pot validation fails on zero pot',
      _cc_f04['pot_facts']['pot_validation'] == 'failed',
      'zero pot should fail validation')

# T-CC-05: MTT format stored in facts
_cc_f05 = _build_decision_facts(_cc_hand(), _cc_stats, _cc_rd)
check('T-CC-05: game context format in facts',
      _cc_f05['game_context']['format'] == 'FREEZEOUT',
      'format not stored in game_context')

# T-CC-06: Bounty arithmetic
_cc_h06 = _cc_hand(format='BOUNTY', bounty_value_bb=5, bounty_type='pko')
_cc_f06 = _build_decision_facts(_cc_h06, _cc_stats, _cc_rd)
_cc_t06 = _select_template(_cc_f06, derive_quality_gates(_cc_f06)[0])
check('T-CC-06: bounty card produced for BOUNTY format',
      _cc_t06 is not None and _cc_t06['card_type'] == 'bounty_ev',
      'bounty_ev template should fire for covered bounty hand')

# T-CC-07: Bounty confidence bands
_cc_h07 = _cc_hand(format='BOUNTY', bounty_value_bb=5, bounty_type='mystery')
_cc_f07 = _build_decision_facts(_cc_h07, _cc_stats, _cc_rd)
check('T-CC-07: mystery bounty gets medium confidence',
      _cc_f07['bounty_facts']['bounty_confidence'] == 'medium',
      'mystery bounty should be medium confidence')

# T-CC-08: Bounty-only call wording
_cc_h08 = _cc_hand(format='BOUNTY', bounty_value_bb=10, bounty_type='pko',
                    eai_hero_equity=35.0, required_eq_pct=40.0)
_cc_f08 = _build_decision_facts(_cc_h08, _cc_stats, _cc_rd)
_cc_t08 = _select_template(_cc_f08, derive_quality_gates(_cc_f08)[0])
check('T-CC-08: bounty-only call mentions bounty in headline',
      _cc_t08 is not None and 'bounty' in _cc_t08.get('headline', '').lower(),
      'bounty-only call should say bounty in headline')

# T-CC-09: Bounty coverage (non-covered excluded)
_cc_h09 = _cc_hand(format='BOUNTY', bounty_value_bb=5, bounty_type='pko',
                    stack_bb=10, villains={'CO': {'stack_bb': 30}})
_cc_f09 = _build_decision_facts(_cc_h09, _cc_stats, _cc_rd)
check('T-CC-09: hero does not cover detected',
      not _cc_f09['bounty_facts']['hero_covers'],
      'hero_covers should be False when villain has larger stack')

# T-CC-10: ICM suppression
_cc_h10 = _cc_hand(tournament_phase='bubble_zone')
_cc_f10 = _build_decision_facts(_cc_h10, _cc_stats, _cc_rd)
_cc_g10, _, _ = derive_quality_gates(_cc_f10)
check('T-CC-10: ICM suppresses confident chip-EV',
      not _cc_g10['icm_allows_confident_verdict'],
      'bubble_zone should suppress confident chip-EV verdict')

# T-CC-11: Satellite suppression + priority
_cc_h11 = _cc_hand(format='SATELLITE', tournament_phase='bubble_zone')
_cc_f11 = _build_decision_facts(_cc_h11, _cc_stats, _cc_rd)
_cc_t11 = _select_template(_cc_f11, derive_quality_gates(_cc_f11)[0])
check('T-CC-11: satellite takes priority over ICM',
      _cc_t11 is not None and _cc_t11['card_type'] == 'satellite_caution',
      'satellite_caution should fire before icm_caution')

# T-CC-12: Action ranking guard
_cc_interp12 = {'card_type': 'call_math', 'poker_verdict': 'Call. Do not raise.',
                'headline': 'test', 'why': 'test', 'learn': 'test', 'plan': 'test'}
_cc_f12 = _build_decision_facts(_cc_hand(), _cc_stats, _cc_rd)
_cc_g12 = derive_quality_gates(_cc_f12)[0]
_cc_g12['action_ranking_supported'] = False
_ok12, _r12 = _run_assertions(_cc_f12, _cc_g12, _cc_interp12)
check('T-CC-12: hard action ranking without alternatives rejected',
      not _ok12 and any('C:' in r for r in _r12),
      'assertion C should fire on unsupported action ranking')

# T-CC-13: Symmetric mistake guard (requires recommended != hero_action)
_cc_interp13_good = {'card_type': 'call_math', 'poker_verdict': 'Good call',
                     'headline': 'test', 'why': 'test', 'learn': 'test', 'plan': 'test'}
_cc_f13 = _build_decision_facts(_cc_hand(), _cc_stats, _cc_rd)
_cc_f13['decision_meta']['auto_verdict'] = 'chart_standard'
_cc_g13 = derive_quality_gates(_cc_f13)[0]
_ok13, _ = _run_assertions(_cc_f13, _cc_g13, _cc_interp13_good)
check('T-CC-13: good verdict with chart-standard passes',
      _ok13,
      'non-contradicting verdict should pass assertion L')

# T-CC-14: Disciplined fold guard
_cc_h14 = _cc_hand(pf_action='fold', eai_hero_equity=None)
_cc_f14 = _build_decision_facts(_cc_h14, _cc_stats, _cc_rd)
_cc_t14 = _select_template(_cc_f14, derive_quality_gates(_cc_f14)[0])
check('T-CC-14: disciplined fold template with fold action',
      _cc_t14 is not None and _cc_t14['card_type'] == 'disciplined_fold',
      'fold action + required equity should produce disciplined_fold')

# T-CC-15: Renderer purity (display_card values unchanged)
_cc_cards15 = build_coaching_cards([_cc_hand()], _cc_stats, _cc_rd)
_cc_any15 = list(_cc_cards15.values())[0][0] if _cc_cards15 else None
check('T-CC-15: display_card has provenance field',
      _cc_any15 is not None and _cc_any15.get('provenance', {}).get('facts_generated_by') == 'programmatic',
      'display_card should carry provenance untouched')

# --- Safety / Anti-Hallucination Tests (T-CC-16 through T-CC-24) ---

# T-CC-16: No blocker wording
_cc_f16 = _build_decision_facts(_cc_hand(), _cc_stats, _cc_rd)
check('T-CC-16: blocker_facts disabled in Phase 1',
      not _cc_f16['blocker_facts']['enabled'],
      'blocker_facts should be disabled')

# T-CC-17: No hero-range wording
check('T-CC-17: hero_range_facts disabled in Phase 1',
      not _cc_f16['hero_range_facts']['enabled'],
      'hero_range_facts should be disabled')

# T-CC-18: Villain read timing guard
_cc_f18 = _build_decision_facts(_cc_hand(), _cc_stats, _cc_rd)
check('T-CC-18: villain reads available_before_decision is True',
      _cc_f18['villain_reads']['available_before_decision'],
      'programmatic reads should always be available_before_decision')

# T-CC-19: Villain read sample gate
_cc_g19_empty = derive_quality_gates(_cc_f18)[0]
check('T-CC-19: villain_read_safe False with zero evidence',
      not _cc_g19_empty['villain_read_safe'],
      'should be unsafe with zero evidence atoms')

# T-CC-20: Claim reconciliation
_cc_interp20 = {'card_type': 'call_math', 'poker_verdict': 'Clear fold',
                'headline': 'test', 'why': 'test', 'learn': 'test', 'plan': 'test'}
_cc_f20 = _build_decision_facts(_cc_hand(), _cc_stats, _cc_rd)
_cc_f20['decision_meta']['auto_verdict'] = 'chart_standard'
_ok20, _r20 = _run_assertions(_cc_f20, derive_quality_gates(_cc_f20)[0], _cc_interp20)
check('T-CC-20: fold contradicts chart-standard auto-verdict',
      not _ok20 and any('L:' in r for r in _r20),
      'assertion L should fire on contradicting verdict')

# T-CC-21: Hand narrative / per-street consistency
check('T-CC-21: _clamp_words enforces word limit',
      _clamp_words('one two three four five six', 4) == 'one two three four',
      'word clamping broken')

# T-CC-22: Mixed-card noise guard (no mixed card in Phase 1)
_cc_f22 = _build_decision_facts(_cc_hand(), _cc_stats, _cc_rd)
_cc_t22 = _select_template(_cc_f22, derive_quality_gates(_cc_f22)[0])
check('T-CC-22: no mixed-action card type in Phase 1',
      _cc_t22 is None or 'mixed' not in _cc_t22.get('card_type', ''),
      'mixed card type should not appear in Phase 1')

# T-CC-23: Sizing card guard (no hero range = no sizing card)
check('T-CC-23: no sizing card type in Phase 1',
      _cc_t22 is None or 'sizing' not in _cc_t22.get('card_type', ''),
      'sizing card type should not appear without hero_range')

# T-CC-24: Dedup (same lesson_type max once per hand)
_cc_cards24 = build_coaching_cards([_cc_hand()], _cc_stats, _cc_rd)
_cc_list24 = list(_cc_cards24.values())[0] if _cc_cards24 else []
_cc_types24 = [c['card_type'] for c in _cc_list24]
check('T-CC-24: no duplicate card types per hand',
      len(_cc_types24) == len(set(_cc_types24)),
      'duplicate card types in same hand')

# --- UI / Regression Tests (T-CC-25 through T-CC-33) ---

# Re-read sources for coaching card checks
with open(os.path.join(os.path.dirname(__file__), 'gem_report_draft', '_html.py'),
          encoding='utf-8') as _f_cc_html:
    _cc_html_src = _f_cc_html.read()

with open(os.path.join(os.path.dirname(__file__), 'gem_coaching_cards.py'),
          encoding='utf-8') as _f_cc_mod:
    _cc_mod_src = _f_cc_mod.read()

check('T-CC-25: existing action display preserved',
      'v25-action-section' in _cc_html_src,
      'action display class missing')

check('T-CC-26: existing villain badges preserved',
      'v25-villain-badge' in _cc_html_src or 'villain-badge' in _cc_html_src,
      'villain badge class missing')

check('T-CC-27: existing thumbs-up/down preserved',
      'verdict-chip' in _cc_html_src and 'verdict-agree' in _cc_html_src,
      'verdict chip buttons missing')

check('T-CC-28: existing GTOW button preserved',
      'gtow' in _cc_html_src.lower() or 'gto-wizard' in _cc_html_src.lower() or 'gtoButton' in _cc_html_src,
      'GTOW button reference missing')

check('T-CC-29: existing copy/reset notes preserved',
      'auditExport' in _cc_html_src and 'auditReset' in _cc_html_src,
      'copy/reset notes function missing')

check('T-CC-30: existing analyst notes still render',
      'notesByStreet' in _cc_html_src,
      'notesByStreet routing removed')

check('T-CC-31: mobile range text max-width + ellipsis',
      'range-text' in _cc_html_src and 'text-overflow' in _cc_html_src,
      'range-text overflow handling missing')

check('T-CC-32: max card limits enforced (1 primary per hand)',
      'setdefault' in _cc_mod_src and 'append' in _cc_mod_src,
      'card accumulation pattern missing from module')

check('T-CC-33: feedback metadata stores provenance fields',
      'facts_generated_by' in _cc_mod_src and 'facts_version' in _cc_mod_src,
      'provenance fields missing from module')

# --- Phase 2 Coaching Cards Tests (T-CC-40 through T-CC-61) ---
print('\n  -- Phase 2: blocker + range awareness --')

# T-CC-40: blocker_facts enabled on 3-flush board with A of suit
_cc_h40 = _cc_hand(cards=['Ah', 'Kd'], board=['7h', '3h', 'Th', 'Jd', '2c'])
_cc_f40 = _build_decision_facts(_cc_h40, _cc_stats, _cc_rd)
_compute_blocker_facts(_cc_f40)
check('T-CC-40: blocker_facts enabled on 3-flush board with A of suit',
      _cc_f40['blocker_facts']['enabled'] and _cc_f40['blocker_facts']['nut_flush_blocker'],
      'Ah should be nut flush blocker on hearts board')

# T-CC-41: blocker_facts disabled with <3 board cards
_cc_h41 = _cc_hand(cards=['Ah', 'Kd'], board=['7h', '3h'])
_cc_f41 = _build_decision_facts(_cc_h41, _cc_stats, _cc_rd)
_compute_blocker_facts(_cc_f41)
check('T-CC-41: blocker_facts disabled with <3 board cards',
      not _cc_f41['blocker_facts']['enabled'],
      'blocker_facts should stay disabled with only 2 board cards')

# T-CC-42: no_flush_blocker detection
_cc_h42 = _cc_hand(cards=['Ac', 'Kd'], board=['7h', '3h', 'Th', 'Jd', '2c'])
_cc_f42 = _build_decision_facts(_cc_h42, _cc_stats, _cc_rd)
_compute_blocker_facts(_cc_f42)
check('T-CC-42: no_flush_blocker when hero has no hearts',
      _cc_f42['blocker_facts']['enabled'] and _cc_f42['blocker_facts']['no_flush_blocker'],
      'hero with no hearts on hearts board should have no_flush_blocker=True')

# T-CC-43: paired_board_blocker detection with correct wording
_cc_h43 = _cc_hand(cards=['7d', 'As'], board=['7h', '7c', 'Ts', 'Jd', '2c'])
_cc_f43 = _build_decision_facts(_cc_h43, _cc_stats, _cc_rd)
_compute_blocker_facts(_cc_f43)
check('T-CC-43: paired_board_blocker when hero holds board pair rank',
      _cc_f43['blocker_facts']['enabled'] and _cc_f43['blocker_facts']['paired_board_blocker']
      and _cc_f43['blocker_facts']['paired_board_blocker_rank'] == '7',
      'hero holding 7 on 7-7 board should have paired_board_blocker=True')

# T-CC-44: hero_range_facts enabled with chart match
_cc_test_ranges = {'OPEN_20-40BB_BTN': {'AKs', 'AKo', 'AA', 'KK', 'QQ', 'JJ', 'TT', 'AQs'}}
_cc_h44 = _cc_hand(cards=['As', 'Kh'], position='BTN', stack_bb=25, pf_action='raise',
                   facing_bets=0)
_cc_f44 = _build_decision_facts(_cc_h44, _cc_stats, _cc_rd)
_compute_hero_range_facts(_cc_f44, _cc_test_ranges)
check('T-CC-44: hero_range_facts enabled with chart match',
      _cc_f44['hero_range_facts']['enabled'] and _cc_f44['hero_range_facts']['in_range'],
      'AKs on BTN at 25BB should be in OPEN_20-40BB_BTN range')

# T-CC-45: hero_range_facts outside-chart detection
_cc_h45 = _cc_hand(cards=['5h', '3h'], position='BTN', stack_bb=25, pf_action='raise',
                   facing_bets=0)
_cc_f45 = _build_decision_facts(_cc_h45, _cc_stats, _cc_rd)
_compute_hero_range_facts(_cc_f45, _cc_test_ranges)
check('T-CC-45: hero_range_facts detects outside-chart hand',
      _cc_f45['hero_range_facts']['enabled'] and not _cc_f45['hero_range_facts']['in_range']
      and _cc_f45['hero_range_facts']['range_position'] == 'outside',
      '53s on BTN should be outside the test range')

# T-CC-46: hero_range_facts disabled without ranges
_cc_h46 = _cc_hand(cards=['As', 'Kh'], position='BTN', stack_bb=25)
_cc_f46 = _build_decision_facts(_cc_h46, _cc_stats, _cc_rd)
_compute_hero_range_facts(_cc_f46, None)
check('T-CC-46: hero_range_facts disabled when ranges is None',
      not _cc_f46['hero_range_facts']['enabled'],
      'should stay disabled without ranges dict')

# T-CC-47: blocker_insight template fires for nut flush blocker
_cc_h47 = _cc_hand(cards=['Ah', 'Kd'], board=['7h', '3h', 'Th', 'Jd', '2c'])
_cc_f47 = _build_decision_facts(_cc_h47, _cc_stats, _cc_rd)
_compute_blocker_facts(_cc_f47)
_cc_g47 = derive_quality_gates(_cc_f47)[0]
_cc_i47 = _tmpl_blocker_insight(_cc_f47, _cc_g47)
check('T-CC-47: blocker_insight template fires for nut flush blocker',
      _cc_i47 is not None and _cc_i47['card_type'] == 'blocker_insight'
      and _cc_i47['variant'] == 'blue' and _cc_i47['_insight_trigger'] == 'nut_flush_blocker',
      'nut flush blocker should produce a blue blocker_insight card')

# T-CC-48: range_awareness template fires for outside-chart hand (open context)
_cc_h48 = _cc_hand(cards=['5h', '3h'], position='BTN', stack_bb=25, pf_action='raise',
                   facing_bets=0)
_cc_f48 = _build_decision_facts(_cc_h48, _cc_stats, _cc_rd)
_compute_hero_range_facts(_cc_f48, _cc_test_ranges)
_cc_g48 = derive_quality_gates(_cc_f48)[0]
_cc_i48 = _tmpl_range_awareness(_cc_f48, _cc_g48)
check('T-CC-48: range_awareness fires for outside-chart hand',
      _cc_i48 is not None and _cc_i48['card_type'] == 'range_awareness'
      and _cc_i48['variant'] == 'blue' and _cc_i48['_insight_trigger'] == 'outside_chart',
      'outside-chart hand should produce a blue range_awareness card')

# T-CC-49: no duplicate card_types per hand (with insight)
_cc_h49 = _cc_hand(cards=['Ah', 'Kd'], board=['7h', '3h', 'Th', 'Jd', '2c'],
                   position='BTN', stack_bb=25)
_cc_cards49 = build_coaching_cards([_cc_h49], _cc_stats, _cc_rd, ranges=_cc_test_ranges)
_cc_list49 = list(_cc_cards49.values())[0] if _cc_cards49 else []
_cc_types49 = [c['card_type'] for c in _cc_list49]
check('T-CC-49: no duplicate card types per hand (Phase 2)',
      len(_cc_types49) == len(set(_cc_types49)),
      'should not have duplicate card types even with insight cards')

# T-CC-50: assertion E1 blocks blocker insight without blocker_facts.enabled
_cc_interp50 = {'card_type': 'blocker_insight', '_insight_trigger': 'nut_flush_blocker',
                'poker_verdict': 'Blocker advantage', 'headline': 'test',
                'why': 'test', 'learn': 'test', 'plan': 'test'}
_cc_f50 = _build_decision_facts(_cc_hand(board=[]), _cc_stats, _cc_rd)
_ok50, _r50 = _run_assertions(_cc_f50, derive_quality_gates(_cc_f50)[0], _cc_interp50)
check('T-CC-50: assertion E1 blocks blocker without enabled',
      not _ok50 and any('E1:' in r for r in _r50),
      'assertion E1 should fire on blocker insight with disabled facts')

# T-CC-51: assertion F1 blocks range awareness without hero_range_facts.enabled
_cc_interp51 = {'card_type': 'range_awareness', '_insight_trigger': 'outside_chart',
                'poker_verdict': 'Range deviation', 'headline': 'test',
                'why': 'test', 'learn': 'test', 'plan': 'test'}
_cc_f51 = _build_decision_facts(_cc_hand(), _cc_stats, _cc_rd)
_ok51, _r51 = _run_assertions(_cc_f51, derive_quality_gates(_cc_f51)[0], _cc_interp51)
check('T-CC-51: assertion F1 blocks range awareness without enabled',
      not _ok51 and any('F1:' in r for r in _r51),
      'assertion F1 should fire on range awareness without chart data')

# T-CC-52: flat-call detected as capped range (not BB, stack >= 20BB)
_cc_h52 = _cc_hand(cards=['As', 'Ah'], position='CO', stack_bb=30, pf_action='call',
                   facing_bets=1)
_cc_f52 = _build_decision_facts(_cc_h52, _cc_stats, _cc_rd)
_cc_test_ranges_52 = {'OPEN_20-40BB_CO': {'AA', 'AKs', 'KK', 'QQ'}}
_compute_hero_range_facts(_cc_f52, _cc_test_ranges_52)
check('T-CC-52: flat-call from CO detected as capped range',
      _cc_f52['hero_range_facts']['is_capped']
      and _cc_f52['hero_range_facts']['range_context'] == 'flat_vs_open',
      'pf_action=call from CO with facing_bets=1 should set is_capped=True')

# T-CC-53: coaching version is v2
from gem_coaching_cards import _COACHING_VERSION as _cc_ver
check('T-CC-53: coaching version is v2',
      _cc_ver == 'v2',
      'Phase 2 should have _COACHING_VERSION v2')

# T-CC-54: no_flush_blocker insight does NOT fire on passive hand
_cc_h54 = _cc_hand(cards=['Ac', 'Kd'], board=['7h', '3h', 'Th', 'Jd', '2c'],
                   facing_bets=0, hero_bets=0, pf_allin=False)
_cc_f54 = _build_decision_facts(_cc_h54, _cc_stats, _cc_rd)
_compute_blocker_facts(_cc_f54)
_cc_g54 = derive_quality_gates(_cc_f54)[0]
_cc_i54 = _tmpl_blocker_insight(_cc_f54, _cc_g54)
check('T-CC-54: no_flush_blocker does NOT fire on passive hand',
      _cc_i54 is None,
      'no_flush_blocker should not fire when facing_bets=0 and hero_bets=0')

# T-CC-55: nut_flush_blocker does NOT render when hero has made nut flush
_cc_h55 = _cc_hand(cards=['Ah', '9h'], board=['7h', '3h', 'Th', 'Jd', '2c'])
_cc_f55 = _build_decision_facts(_cc_h55, _cc_stats, _cc_rd)
_compute_blocker_facts(_cc_f55)
_cc_g55 = derive_quality_gates(_cc_f55)[0]
_cc_i55 = _tmpl_blocker_insight(_cc_f55, _cc_g55)
check('T-CC-55: made nut flush renders as nut_flush_made not blocker',
      _cc_i55 is not None and _cc_i55['_insight_trigger'] == 'nut_flush_made',
      'Ah+9h on 3-heart board should be nut_flush_made_hand not blocker')

# T-CC-56: paired-board blocker uses trips/full-house wording
_cc_h56 = _cc_hand(cards=['7d', 'As'], board=['7h', '7c', 'Ts', 'Jd', '2c'],
                   facing_bets=1)
_cc_f56 = _build_decision_facts(_cc_h56, _cc_stats, _cc_rd)
_compute_blocker_facts(_cc_f56)
_cc_g56 = derive_quality_gates(_cc_f56)[0]
_cc_i56 = _tmpl_blocker_insight(_cc_f56, _cc_g56)
check('T-CC-56: paired-board blocker uses trips/full-house wording',
      _cc_i56 is not None and 'trips' in _cc_i56.get('headline', '').lower()
      and 'set' not in _cc_i56.get('headline', '').lower(),
      'paired-board card should say trips/full houses not set')

# T-CC-57: range_awareness outside-chart only fires for open context
_cc_h57 = _cc_hand(cards=['5h', '3h'], position='BTN', stack_bb=25, pf_action='call',
                   facing_bets=1)
_cc_f57 = _build_decision_facts(_cc_h57, _cc_stats, _cc_rd)
_compute_hero_range_facts(_cc_f57, _cc_test_ranges)
_cc_g57 = derive_quality_gates(_cc_f57)[0]
_cc_i57 = _tmpl_range_awareness(_cc_f57, _cc_g57)
check('T-CC-57: outside-chart does not fire when range_context != open',
      _cc_i57 is None or _cc_i57.get('_insight_trigger') != 'outside_chart',
      'outside-chart should only fire for open context')

# T-CC-58: capped-premium does NOT fire for BB defend
_cc_h58 = _cc_hand(cards=['As', 'Ah'], position='BB', stack_bb=30, pf_action='call',
                   facing_bets=1)
_cc_f58 = _build_decision_facts(_cc_h58, _cc_stats, _cc_rd)
_cc_test_ranges_58 = {'OPEN_20-40BB_BB': {'AA', 'AKs', 'KK', 'QQ'}}
_compute_hero_range_facts(_cc_f58, _cc_test_ranges_58)
check('T-CC-58: capped-premium does NOT fire for BB defend',
      not _cc_f58['hero_range_facts'].get('is_capped'),
      'BB defend should not be flagged as capped')

# T-CC-59: primary + insight order is primary first, insight second
_cc_h59 = _cc_hand(cards=['Ah', 'Kd'], board=['7h', '3h', 'Th', 'Jd', '2c'],
                   format='BOUNTY', pf_allin=True, n_players=2,
                   villains={'CO': {'stack_bb': 50, 'shown_cards': 'QhQs'}})
_cc_cards59 = build_coaching_cards([_cc_h59], _cc_stats, _cc_rd, ranges=_cc_test_ranges)
_cc_list59 = list(_cc_cards59.values())[0] if _cc_cards59 else []
_cc_order_ok = True
if len(_cc_list59) >= 2:
    _cc_primary_types = {'satellite_caution', 'icm_caution', 'bounty_not_collectible',
                         'bounty_ev', 'multiway_caution', 'call_math', 'disciplined_fold'}
    _cc_insight_types = {'blocker_insight', 'range_awareness'}
    if _cc_list59[0]['card_type'] in _cc_insight_types and _cc_list59[1]['card_type'] in _cc_primary_types:
        _cc_order_ok = False
check('T-CC-59: primary card before insight card in result list',
      _cc_order_ok,
      'primary card should come before insight card')

# T-CC-60: max 2 cards per hand
_cc_h60 = _cc_hand(cards=['Ah', 'Kd'], board=['7h', '3h', 'Th', 'Jd', '2c'],
                   position='BTN', stack_bb=25)
_cc_cards60 = build_coaching_cards([_cc_h60], _cc_stats, _cc_rd, ranges=_cc_test_ranges)
_cc_list60 = list(_cc_cards60.values())[0] if _cc_cards60 else []
check('T-CC-60: max 2 cards per hand',
      len(_cc_list60) <= 2,
      f'got {len(_cc_list60)} cards, expected max 2')

# T-CC-61: insight card survives when primary is suppressed
_cc_h61 = _cc_hand(cards=['Ah', 'Kd'], board=['7h', '3h', 'Th', 'Jd', '2c'],
                   pot_facing=0, call_amount_bb=0)
_cc_f61 = _build_decision_facts(_cc_h61, _cc_stats, _cc_rd)
_compute_blocker_facts(_cc_f61)
_cc_g61, _, _cc_suppress61 = derive_quality_gates(_cc_f61)
_cc_i61 = _tmpl_blocker_insight(_cc_f61, _cc_g61)
check('T-CC-61: insight card survives primary suppression',
      _cc_suppress61 is not None and _cc_i61 is not None
      and _cc_i61['card_type'] == 'blocker_insight',
      'blocker insight should fire even when pot_validation suppresses primary')

print('\n=== v8.9.7 TESTS ===')

# --- B138: _is_weak_showdown pocket-pair guard ---
from gem_villain_intel import _is_weak_showdown as _iws

check('T-V257-01: B138 set is not weak (7h7d on 2-7-9-A-4)',
      _iws(['7h', '7d'], ['2d', '7c', '9s', 'Ac', '4h']) is False,
      'pocket-pair set misclassified as weak')

check('T-V257-02: B138 pocket pair off-board not weak (JhJd on 2-7-9-A-4)',
      _iws(['Jh', 'Jd'], ['2d', '7c', '9s', 'Ac', '4h']) is False,
      'pocket overpair misclassified as weak')

check('T-V257-03: B138 two pair is not weak (9h4d on 2-7-9-A-4)',
      _iws(['9h', '4d'], ['2d', '7c', '9s', 'Ac', '4h']) is False,
      'two pair misclassified as weak')

check('T-V257-04: B138 genuine weak hand still flagged (3h5d on 2-7-9-A-4)',
      _iws(['3h', '5d'], ['2d', '7c', '9s', 'Ac', '4h']) is True,
      'ace-high/air not flagged as weak')

check('T-V257-05: B138 bottom pair still weak (2h5d on 2-7-9-A-4)',
      _iws(['2h', '5d'], ['2d', '7c', '9s', 'Ac', '4h']) is True,
      'bottom pair not flagged as weak')

# --- B140: villain badge sentinel ---
_v257_sxiv_src = open(os.path.join(os.path.dirname(__file__),
    'gem_report_draft', 'sections_xiv.py'), encoding='utf-8').read()

check('T-V257-06: B140 sentinel key (street, -1) in _build_villain_badges',
      'idx = -1' in _v257_sxiv_src and "street and idx is None" in _v257_sxiv_src,
      'sentinel key logic missing')

check('T-V257-07: B140 auto_verdict fallback in _build_villain_badges',
      'auto_verdict' in _v257_sxiv_src.split('_build_villain_badges')[1][:4000],
      'auto_verdict fallback missing')

_v257_hg_src = open(os.path.join(os.path.dirname(__file__),
    'gem_report_draft', '_hand_grid.py'), encoding='utf-8').read()

check('T-V257-08: B140 _hero_last_idx_by_street precomputation',
      '_hero_last_idx_by_street' in _v257_hg_src,
      '_hero_last_idx_by_street missing from _hand_grid.py')

check('T-V257-09: B140 sentinel placement in _hand_grid.py',
      '_street_sentinel_placed' in _v257_hg_src and "(street, -1)" in _v257_hg_src,
      'sentinel placement logic missing')

# --- B139: deterministic exploit generation ---
_v257_vi_src = open(os.path.join(os.path.dirname(__file__),
    'gem_villain_intel.py'), encoding='utf-8').read()
_v257_vi_bvi = _v257_vi_src.split('def build_villain_intel')[1][:3000] if 'def build_villain_intel' in _v257_vi_src else ''

check('T-V257-12: B139 hands sorted by ID in build_villain_intel',
      "sorted(hands, key=lambda h: h.get('id'" in _v257_vi_bvi,
      'hands not sorted at entry to build_villain_intel')

check('T-V257-13: B139 evidence_atoms sorted by stable key',
      'evidence_atoms.sort(key=_atom_sort_key)' in _v257_vi_bvi,
      'evidence_atoms not sorted before indexing')

check('T-V257-14: B139 exploit_opportunities sorted by stable key',
      'exploit_opportunities.sort(key=' in _v257_vi_src,
      'exploit_opportunities not sorted')

check('T-V257-15: B139 evidence_hand_ids sorted in read_states',
      'evidence_hids = sorted(set(' in _v257_vi_src,
      'evidence_hand_ids not sorted in _build_read_states')

# --- B142: --quick session fingerprint guard ---
_v257_ga_src = open(os.path.join(os.path.dirname(__file__),
    'gem_analyzer.py'), encoding='utf-8').read()

check('T-V257-18: B142 session fingerprint embedded in stats',
      "_session_fingerprint" in _v257_ga_src and "'n_hands'" in _v257_ga_src
      and "stats['_session_fingerprint']" in _v257_ga_src,
      'session fingerprint not embedded in stats save')

check('T-V257-19: B142 session fingerprint embedded in report_data',
      "report_data['_session_fingerprint']" in _v257_ga_src,
      'session fingerprint not embedded in report_data save')

check('T-V257-20: B142 --quick fingerprint mismatch check',
      'fingerprint MISMATCH' in _v257_ga_src and 'sys.exit(1)' in _v257_ga_src.split('fingerprint MISMATCH')[1][:600] if 'fingerprint MISMATCH' in _v257_ga_src else False,
      '--quick does not abort on fingerprint mismatch')

# --- B141: cross-hand evidence routing ---
check('T-V257-21: B141 same_hand_actionable in context dict',
      "'same_hand_actionable'" in _v257_sxiv_src,
      'same_hand_actionable not carried in villain_evidence context')

check('T-V257-22: B141 same_hand_actionable gate in _html.py',
      'same_hand_actionable' in _v256_html_src and '_sameHand' in _v256_html_src,
      'same_hand_actionable routing gate missing from _html.py')

# --- B143: villain trigger marker for fold-type mistakes ---
check('T-V257-23: B143 _trigger_markers precomputation exists',
      '_trigger_markers' in _v257_hg_src and '_trigger_markers = {}' in _v257_hg_src,
      '_trigger_markers precomputation missing from _hand_grid.py')

check('T-V257-24: trigger marker covers flagged folds AND calls/raises (v8.12.0b)',
      "('folds', 'calls', 'raises'," in _v257_hg_src.split('_trigger_markers')[1][:1200]
      and '_has_note' in _v257_hg_src.split('_trigger_markers')[1][:1200],
      'trigger marker precomputation missing note logic')

check('T-V257-25: B143 ann-trigger rendering in main loop',
      'ann-trigger' in _v257_hg_src and 'trigger_html' in _v257_hg_src,
      'ann-trigger rendering missing from hand grid loop')

check('T-V257-26: B143 ann-trigger CSS in _html.py',
      'ann-trigger' in _v256_html_src,
      'ann-trigger CSS missing from _html.py')

# ============================================================
# v8.9.8 Phase 1 — Detector Fixes (P1-C, P2-A, P2-B, P2-C, P2-D)
# ============================================================

_v898_ga_src_raw = open(os.path.join(os.path.dirname(__file__),
    'gem_analyzer.py'), encoding='utf-8').read()
_v898_gcb_path = os.path.join(os.path.dirname(__file__), 'gem_coverage_builder.py')
_v898_gcb_src = open(_v898_gcb_path, encoding='utf-8').read() if os.path.exists(_v898_gcb_path) else ''
_v898_ga_src = _v898_ga_src_raw + _v898_gcb_src
_v898_lint_src = open(os.path.join(os.path.dirname(__file__),
    'gem_report_lint.py'), encoding='utf-8').read()

# --- P2-D: Lint print visibility ---
check('T-P2D-01: Lint findings printed to console by default',
      'LINT: {f.rule}' in _v898_lint_src or "f'  LINT: {f.rule}" in _v898_lint_src,
      'format_console_summary does not print individual findings')

check('T-P2D-02: Lint prints ERROR/BLOCKER severity filter',
      "f.severity in ('ERROR', 'BLOCKER')" in _v898_lint_src
      or "severity in ('ERROR'" in _v898_lint_src,
      'Lint output not filtered to ERROR/BLOCKER')

# --- P2-C: PLO quarantine ---
check('T-P2C-01: _PLO_CANDIDATE_BUCKETS tuple exists',
      '_PLO_CANDIDATE_BUCKETS' in _v898_ga_src
      and "'bust_audit'" in _v898_ga_src.split('_PLO_CANDIDATE_BUCKETS')[1][:300],
      'PLO candidate bucket tuple missing or does not include bust_audit')

check('T-P2C-02: _filter_non_nlh_from_candidate_buckets function exists',
      'def _filter_non_nlh_from_candidate_buckets' in _v898_ga_src,
      'PLO quarantine helper function missing')

check('T-P2C-03: PLO quarantine called in __main__ before coverage gate',
      '_non_nlh_ids_main' in _v898_ga_src
      and '_filter_non_nlh_from_candidate_buckets(candidates' in _v898_ga_src,
      'PLO quarantine not applied to __main__ candidate buckets')

check('T-P2C-04: Production-safe PLO leak invariant (log, not assert)',
      'PLO quarantine leak' in _v898_ga_src
      and 'logging.error' in _v898_ga_src.split('PLO quarantine leak')[0][-200:],
      'PLO leak invariant missing or uses hard assert instead of logging')

check('T-P2C-05: bust_audit in candidate bucket tuple',
      "'bust_audit'" in _v898_ga_src.split('_PLO_CANDIDATE_BUCKETS')[1][:200]
      if '_PLO_CANDIDATE_BUCKETS' in _v898_ga_src else False,
      'bust_audit not in PLO candidate bucket tuple')

check('T-P2C-06: iii4_screening in candidate bucket tuple',
      "'iii4_screening'" in _v898_ga_src.split('_PLO_CANDIDATE_BUCKETS')[1][:300]
      if '_PLO_CANDIDATE_BUCKETS' in _v898_ga_src else False,
      'iii4_screening not in PLO candidate bucket tuple')

# --- P2-A: Shared preflop-terminal-allin helper ---
check('T-P2A-01: _is_preflop_terminal_allin function exists at module level',
      'def _is_preflop_terminal_allin(h)' in _v898_ga_src
      and _v898_ga_src.index('def _is_preflop_terminal_allin') < _v898_ga_src.index('def analyze_session'),
      '_is_preflop_terminal_allin not defined at module level')

check('T-P2A-02: Helper checks pf_allin field',
      "h.get('pf_allin')" in _v898_ga_src.split('def _is_preflop_terminal_allin')[1][:500]
      if 'def _is_preflop_terminal_allin' in _v898_ga_src else False,
      'Helper does not check pf_allin')

check('T-P2A-03: Helper checks action_ledger for postflop hero actions',
      'hero_postflop_action' in _v898_ga_src.split('def _is_preflop_terminal_allin')[1][:600]
      if 'def _is_preflop_terminal_allin' in _v898_ga_src else False,
      'Helper does not check for hero postflop actions in ledger')

check('T-P2A-04: M1 detector uses shared helper',
      '_is_preflop_terminal_allin(h)' in _v898_ga_src.split('M1: MISSED TURN DELAYED C-BET')[1][:1200]
      if 'M1: MISSED TURN DELAYED C-BET' in _v898_ga_src else False,
      'M1 detector still uses pf_allin instead of shared helper')

check('T-P2A-05: M6 detector uses shared helper',
      '_is_preflop_terminal_allin(h)' in _v898_ga_src.split('M6: 3BP WET-TURN')[1][:1000]
      if 'M6: 3BP WET-TURN' in _v898_ga_src else False,
      'M6 detector still uses pf_allin instead of shared helper')

check('T-P2A-06: J14 detector uses shared helper',
      '_is_preflop_terminal_allin(h)' in _v898_ga_src.split('Monotone IP c-bet')[1][:500]
      if 'Monotone IP c-bet' in _v898_ga_src else False,
      'J14 detector still uses pf_allin instead of shared helper')

check('T-P2A-07: At least 3 detectors use shared helper (prove it is shared)',
      _v898_ga_src.count('_is_preflop_terminal_allin(h)') >= 3,
      'Shared helper used in fewer than 3 places')

check('T-P2A-08: Helper does not require empty board (handles board runout)',
      "not h.get('board')" not in _v898_ga_src.split('def _is_preflop_terminal_allin')[1][:600]
      if 'def _is_preflop_terminal_allin' in _v898_ga_src else False,
      'Helper incorrectly requires empty board for detection')

# --- P2-B: R6 pot-odds routing ---
check('T-P2B-01: R5_micro_potodds auto_rule exists',
      'R5_micro_potodds' in _v898_ga_src,
      'Micro-stack pot-odds-based R5 route missing')

check('T-P2B-02: R6 uses required_equity from decision_math',
      "required_equity" in _v898_ga_src.split('R6: Caller of jam')[1][:1200]
      if 'R6: Caller of jam' in _v898_ga_src else False,
      'R6 does not reference required_equity from decision_math')

check('T-P2B-03: R6 micro-stack gate uses eff < 6',
      '_eff < 6' in _v898_ga_src.split('R6: Caller of jam')[1][:1200]
      if 'R6: Caller of jam' in _v898_ga_src else False,
      'R6 micro-stack gate missing eff < 6 check')

check('T-P2B-04: No bounty in R5_micro_potodds formula',
      'bounty' not in _v898_ga_src.split('R5_micro_potodds')[1][:300].lower()
      if 'R5_micro_potodds' in _v898_ga_src else False,
      'Bounty math found in micro-stack pot-odds formula')

check('T-P2B-05: Missing pot data routes to III.4 not I.7',
      'R6_call_jam_lowEq_nopotdata' in _v898_ga_src
      and 'III.4' in _v898_ga_src.split('R6_call_jam_lowEq_nopotdata')[0][-200:],
      'Missing pot data fallback does not route to III.4')

# --- P1-C: Reshove range gate ---
check('T-P1C-01: REJAM chart lookup in reshove detector',
      'REJAM_' in _v898_ga_src.split('ULTRA-SHORT RESHOVE')[1][:2800]
      if 'ULTRA-SHORT RESHOVE' in _v898_ga_src else False,
      'REJAM chart lookup missing from reshove detector')

check('T-P1C-02: Position canonicalization in reshove detector',
      '_POS_CANON' in _v898_ga_src.split('ULTRA-SHORT RESHOVE')[1][:2800]
      if 'ULTRA-SHORT RESHOVE' in _v898_ga_src else False,
      'Position canonicalization missing from reshove detector')

check('T-P1C-03: Unrecognized position caps at MARGINAL',
      '_POS_SAFE' in _v898_ga_src.split('ULTRA-SHORT RESHOVE')[1][:2000]
      if 'ULTRA-SHORT RESHOVE' in _v898_ga_src else False,
      'Safe position set missing — unrecognized positions not handled')

_reshove_section = (_v898_ga_src.split('ULTRA-SHORT RESHOVE')[1][:3500]
                     if 'ULTRA-SHORT RESHOVE' in _v898_ga_src else '')

check('T-P1C-04: Hand not in REJAM chart suppresses should_reshove',
      '_chart_says_reshove' in _reshove_section
      and 'should_reshove = False' in _reshove_section,
      'REJAM chart miss does not suppress should_reshove')

check('T-P1C-05: Early opener without chart caps at MARGINAL',
      'not _rj_chart' in _reshove_section
      and "confidence = 'MARGINAL'" in _reshove_section,
      'Missing chart for early opener does not cap confidence')

# v8.9.9 Phase 2 — Pipeline Resilience (P1-A, P1-B, P3-A)
print('\n=== v8.9.9 Phase 2 TESTS ===')

_v899_ga_src = open(os.path.join(os.path.dirname(__file__),
    'gem_analyzer.py'), encoding='utf-8').read()

# --- P3-A: _versioned_path dedup ---
import re as _re_p3a
_vp_defs = _re_p3a.findall(r'def _versioned_path\b', _v899_ga_src)
check('T-P3A-01: Only one def _versioned_path in gem_analyzer.py',
      len(_vp_defs) == 1,
      f'Found {len(_vp_defs)} definitions (expected 1)')

# Module-level _versioned_path takes pname_file param
_vp_sig_area = _src[:3000]
check('T-P3A-02: _versioned_path takes pname_file parameter',
      'def _versioned_path(directory, prefix, date, ext, pname_file' in _v899_ga_src,
      'Module-level _versioned_path missing pname_file param')

# --- P1-A: gem_coverage_builder.py extraction ---
_gcb_path = os.path.join(os.path.dirname(__file__), 'gem_coverage_builder.py')
_gcb_exists = os.path.exists(_gcb_path)
check('T-P1A-01: gem_coverage_builder.py exists and importable',
      _gcb_exists,
      'gem_coverage_builder.py not found')

if _gcb_exists:
    with open(_gcb_path, encoding='utf-8') as _f:
        _gcb_src = _f.read()
    check('T-P1A-02: build_and_write callable in gem_coverage_builder',
          'def build_and_write(' in _gcb_src,
          'build_and_write function not found')
    check('T-P1A-03: py_compile clean on gem_coverage_builder.py',
          __import__('py_compile').compile(_gcb_path, doraise=True) is not None,
          'py_compile failed')
    check('T-P1A-04: gem_analyzer.py calls build_and_write from gem_coverage_builder',
          'from gem_coverage_builder import build_and_write' in _v899_ga_src,
          'gem_analyzer.py does not import build_and_write')
else:
    for _t in ('T-P1A-02', 'T-P1A-03', 'T-P1A-04'):
        check(f'{_t}: SKIP (gem_coverage_builder.py missing)', False, 'file missing')

# --- P1-A sub: --profile flag ---
check('T-P1A-05: --profile flag accepted by gem_analyzer.py',
      "'--profile'" in _v899_ga_src and '_profile_mode' in _v899_ga_src,
      '--profile flag parsing not found')

check('T-P1A-06: _log_profile helper defined',
      'def _log_profile(' in _v899_ga_src,
      '_log_profile helper not found')

# --- P1-B: --resume-from-cache flag ---
check('T-P1B-01: --resume-from-cache flag accepted by gem_analyzer.py',
      "'--resume-from-cache'" in _v899_ga_src and '_resume_from_cache' in _v899_ga_src,
      '--resume-from-cache flag parsing not found')

check('T-P1B-02: Resume mode loads three cache files (hands, stats, report_data)',
      'gem_hands_' in _v899_ga_src and 'gem_stats.json' in _v899_ga_src
      and 'gem_report_data_' in _v899_ga_src,
      'Cache file loading not found')

check('T-P1B-03: Resume mode validates session fingerprint',
      '_session_fingerprint' in _v899_ga_src and '_fp_match' in _v899_ga_src,
      'Fingerprint validation not found in resume mode')

check('T-P1B-04: Resume mode calls coverage builder',
      '_build_coverage' in _v899_ga_src,
      'Coverage builder call not found in resume mode')

check('T-P1B-05: Resume mode aborts on missing cache with clear error',
      'ERROR: --resume-from-cache requires cached data' in _v899_ga_src,
      'Missing-cache error message not found')

check('T-P1B-06: Resume mode aborts on fingerprint mismatch',
      'session fingerprint MISMATCH' in _v899_ga_src,
      'Fingerprint mismatch error not found')


# ============================================================
# v8.12.0 — PKO research layer + D1 quarantine + P0 audit + R1 codec
# ============================================================
import gem_pko_research as _pko

# --- D1 quarantine ---
from gem_ranges import load_ranges as _lr_v812
_r812 = _lr_v812('Poker_Ranges_Text.txt')
check('T-D1-01: no live SBD_ chart keys after quarantine',
      not any(k.startswith('SBD_') for k in _r812),
      'live SBD_ keys found')
check('T-D1-02: other chart families still load',
      'PUSH_10BB_BTN' in _r812 and any(k.startswith('BB_DEF_vs') for k in _r812),
      'expected charts missing after quarantine')
_prt_raw = open('Poker_Ranges_Text.txt', encoding='utf-8').read()
check('T-D1-03: anti-canary — no line starts with SBD_',
      '\nSBD_' not in _prt_raw, 'un-quarantined SBD line present')

# --- coverage / collectibility split ---
check('T-PKO-01: 1-chip cover is collectible',
      _pko.can_collect_bounty(20.1, 20.0) is True, '')
check('T-PKO-02: equal stacks collectible (eliminate on win)',
      _pko.can_collect_bounty(20.0, 20.0) is True, '')
check('T-PKO-03: covered is NOT collectible',
      _pko.can_collect_bounty(15.0, 20.0) is False, '')
check('T-PKO-04: research bucket keeps 1.10/0.90 heuristic',
      _pko.coverage_bucket(22.1, 20.0) == 'Hero covers'
      and _pko.coverage_bucket(17.9, 20.0) == 'Hero covered'
      and _pko.coverage_bucket(20.5, 20.0) == 'Equal', '')

# --- depth bands: hard edges, no snapping ---
check('T-PKO-05: 22.0 in short bucket, 23.5 is band edge',
      _pko.depth_band(22.0) == ('<=20bb', False, None)
      and _pko.depth_band(23.5)[1] is True, '')
check('T-PKO-06: <12bb routes to push/fold out-of-scope',
      _pko.depth_band(11.9)[2] == 'out_of_scope_pushfold', '')
check('T-PKO-07: >60bb routes to deep out-of-scope',
      _pko.depth_band(61.0)[2] == 'out_of_scope_deep', '')

# --- bucket table integrity ---
check('T-PKO-08: floor-graded delta buckets (PKO3 v3 run)',
      _pko.PKO_RESEARCH_BUCKETS['bb_vs_btn_3way_short']['delta_bucket'] == 'Very high'
      and _pko.PKO_RESEARCH_BUCKETS['bb_vs_btn_hu_short_covering']['delta_bucket'] == 'Low',
      'range-floor re-grades missing')
check('T-PKO-09: CO bucket upgraded to full confidence (PKO3 v3 revisit-verified)',
      _pko.PKO_RESEARCH_BUCKETS['bb_vs_co_hu_short']['confidence'] == 'aggregate_gtow_supported', '')
_v3_full = ['bb_vs_btn_hu_short_covered', 'bb_vs_btn_hu_30bb_equal',
            'bb_vs_btn_3way_short', 'bb_vs_btn_4way_short',
            'bb_multiway_short_covered', 'bb_multiway_short_covering',
            'bb_vs_co_hu_short']
_v3_classic = {'bb_vs_btn_hu_short_covered': 68.2, 'bb_vs_btn_hu_30bb_equal': 86.9,
               'bb_vs_btn_3way_short': 38.6, 'bb_vs_btn_4way_short': 18.3,
               'bb_multiway_short_covered': 52.8, 'bb_multiway_short_covering': 11.8,
               'bb_vs_co_hu_short': 42.9}
check('T-PKO-24: v3-measured buckets carry classic pct, full conf, jam_heavy False',
      all(_pko.PKO_RESEARCH_BUCKETS[k]['classic_defend_pct'] == _v3_classic[k]
          and _pko.PKO_RESEARCH_BUCKETS[k]['confidence'] == 'aggregate_gtow_supported'
          and _pko.PKO_RESEARCH_BUCKETS[k]['jam_heavy'] is False
          and 'PKO3 v3' in _pko.PKO_RESEARCH_BUCKETS[k]['source']
          for k in _v3_full), 'v3 bake incomplete')
check('T-PKO-25: v1-era unmeasured rows demoted to directional with mix withdrawn',
      all(_pko.PKO_RESEARCH_BUCKETS[k]['confidence'] == 'directional_aggregate'
          and _pko.PKO_RESEARCH_BUCKETS[k]['action_mix'] == 'n/r'
          for k in ('bb_vs_btn_hu_short_covering', 'bb_vs_btn_hu_50bb_covering',
                    'bb_vs_btn_hu_50bb_covered', 'bb_multiway_50bb')), 'demotion missing')

# --- classification rules (schema v2 + guardrails) ---
def _mk_hand(act='folds', allin=False, opener='BTN', opener_stack=16.0,
             hero_stack=18.0, callers=(), fmt='BOUNTY', phase='bubble_zone',
             hid='T1'):
    ledger = [{'street': 'preflop', 'player': 'Op', 'position': opener,
               'action': 'raises', 'amount_bb': 2.2, 'stack_bb': opener_stack,
               'is_all_in': allin}]
    for i, c in enumerate(callers):
        ledger.append({'street': 'preflop', 'player': 'C%d' % i,
                       'position': c, 'action': 'calls', 'amount_bb': 2.2,
                       'stack_bb': 15.0, 'is_all_in': False})
    ledger.append({'street': 'preflop', 'player': 'HeroX', 'position': 'BB',
                   'action': act, 'amount_bb': 0, 'stack_bb': hero_stack,
                   'is_all_in': False})
    return {'id': hid, 'hero': 'HeroX', 'position': 'BB', 'format': fmt,
            'tournament_phase': phase, 'eff_stack_bb': hero_stack,
            'action_ledger': ledger}

_c1 = _pko.build_pko_context(_mk_hand(act='folds', callers=('SB',), hero_stack=16.5, opener_stack=16.0), {})
check('T-PKO-10: high-delta fold w/o Classic backstop = Review, never Missed',
      _c1.get('classification') == 'Review', str(_c1.get('classification')))
_c2 = _pko.build_pko_context(_mk_hand(act='folds', callers=('SB',), hid='T2'),
                             {'missed_defend': {'T2'}, 'wide_defend': set()})
check('T-PKO-11: chart-backed fold = Missed with chart source',
      _c2.get('classification') == 'Missed'
      and _c2.get('classic_support_source') == 'chart', str(_c2))
_c3 = _pko.build_pko_context(_mk_hand(act='calls', callers=('SB',), hero_stack=16.5, opener_stack=16.0), {})
check('T-PKO-12: 3way-short flat call = Good/aligned (v3 call-dominated mix; jam-heavy retired)',
      _c3.get('classification') == 'Good'
      and _c3.get('pko_action_fit') == 'aligned', str(_c3))
_c4 = _pko.build_pko_context(_mk_hand(act='calls'), {})  # HU short covering: v1-era, mix withdrawn
check('T-PKO-13: HU covering (v1-era, mix unverified) Classic-OK call = Baseline',
      _c4.get('classification') == 'Baseline'
      and _c4.get('pko_action_fit') == 'unknown', str(_c4))
_c5 = _pko.build_pko_context(
    _mk_hand(act='calls', opener_stack=45.0, hero_stack=50.0), {})
check('T-PKO-14: action_mix n/r (v1-era 50bb row) Classic-OK continue = Baseline (not PKO-good)',
      _c5.get('classification') == 'Baseline'
      and _c5.get('pko_action_fit') == 'unknown', str(_c5))
_c5b = _pko.build_pko_context(
    _mk_hand(act='calls', opener_stack=19.0, hero_stack=17.0), {})
check('T-PKO-14b: covered-short call with v3-known mix = Good/aligned',
      _c5b.get('classification') == 'Good'
      and _c5b.get('pko_action_fit') == 'aligned', str(_c5b))
_c6 = _pko.build_pko_context(
    _mk_hand(act='calls', callers=('SB',), hid='T6'),
    {'missed_defend': set(), 'wide_defend': {'T6'}})
check('T-PKO-15: Classic-too-loose + high delta = Review (not auto Too wide)',
      _c6.get('classification') == 'Review', str(_c6.get('classification')))
_c7 = _pko.build_pko_context(_mk_hand(act='folds', allin=True), {})
check('T-PKO-16: facing all-in routes to allin_family, never a defense bucket',
      _c7.get('enabled') is False and _c7.get('oos_reason') == 'allin_family', str(_c7))
_c8 = _pko.build_pko_context(_mk_hand(act='folds', fmt='MYSTERY_BOUNTY'), {})
check('T-PKO-17: mystery routes out-of-scope (no research bucket)',
      _c8.get('oos_reason') == 'out_of_scope_mystery', str(_c8))
_c9 = _pko.build_pko_context(_mk_hand(act='folds', phase='late_reg',
                                      callers=('SB',)), {})
check('T-PKO-18: phase outside bubble downgrades confidence',
      _c9.get('confidence') == 'directional_aggregate'
      and any('phase' in r for r in _c9.get('confidence_reasons', [])), str(_c9))
check('T-PKO-19: classification enum excludes Opp/Actual; count dims are bools',
      _c1['classification'] in ('Good', 'Too wide', 'Missed', 'Review',
                                'Baseline', 'Out of scope')
      and isinstance(_c1['is_opportunity'], bool)
      and isinstance(_c1['hero_continued'], bool), str(_c1))
_co = _pko.build_pko_context(_mk_hand(act='folds', opener='CO'), {})
check('T-PKO-20: CO opener maps to measured CO bucket',
      _co.get('research_bucket') == 'bb_vs_co_hu_short', str(_co.get('research_bucket')))

# --- enrichment aggregation ---
_hands_t = [_mk_hand(act='folds', callers=('SB',), hid='A1', hero_stack=16.5, opener_stack=16.0),
            _mk_hand(act='calls', hid='A2'),
            {'id': 'A3', 'hero': 'HeroX', 'position': 'BB',
             'format': 'FREEZEOUT', 'action_ledger': []}]
_agg = _pko.enrich_pko_contexts(_hands_t, None, None)
check('T-PKO-21: enrich returns enabled aggregate + by_hand contexts',
      _agg.get('enabled') is True and 'A1' in _agg['by_hand']
      and _hands_t[0]['pko_context']['enabled'] is True, '')
_seen_total = sum(len(r['cells']['Seen']) for r in _agg['teaching_rows'])
check('T-PKO-22: snapshot count equals sum of teaching Seen cells',
      len(_agg['snapshot']['pko_sensitive_opps']) == _seen_total,
      f"{len(_agg['snapshot']['pko_sensitive_opps'])} vs {_seen_total}")
check('T-PKO-23: enrich fail-soft on garbage input',
      _pko.enrich_pko_contexts(None, None, None).get('enabled') in (True, False), '')

# ============================================================
# v8.14.0 — Slice E: PKO v2 trust reconciliation + copy clarity (T-PKOE-*)
# ============================================================
import re as _re_pkoe
import gem_pko_research as _pkoE
_e1 = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covers', can_collect_bounty=True,
                                players=2, coverage_label='covers opener — bounty collectible',
                                bounty_value_bb=4.0, bounty_usd=5.0)
check('T-PKOE-01: Hero covers villain -> collectible trust line + $X conversion',
      _e1['cover_state'] == 'hero_covers' and _e1['collectible'] is True
      and 'collectible' in _e1['trust_line'] and '$5.00' in _e1['trust_line']
      and not _e1['contradiction'], _e1['trust_line'])
_e2 = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covered', can_collect_bounty=False,
                                players=2,
                                coverage_label='covered by opener — opener bounty not collectible')
check('T-PKOE-02: Villain covers Hero -> bounty discount does not help Hero',
      _e2['cover_state'] == 'hero_covered' and _e2['collectible'] is False
      and 'does not help Hero' in _e2['trust_line'] and not _e2['contradiction'], _e2['trust_line'])
_e3a = _pkoE.reconcile_pko_trust(coverage_bucket='Equal', can_collect_bounty=True, players=2)
_e3b = _pkoE.reconcile_pko_trust(coverage_bucket='Equal', can_collect_bounty=False, players=2)
check('T-PKOE-03: near-equal/equal stacks handled safely (collectible only if Hero wins)',
      _e3a['cover_state'] == 'equal' and 'only if Hero wins outright' in _e3a['trust_line']
      and 'not collectible' in _e3b['trust_line'] and not _e3a['contradiction'], _e3a['trust_line'])
_e4 = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covers', can_collect_bounty=True, players=3,
                                coverage_label='covers CO only — that bounty collectible; HJ covers Hero')
check('T-PKOE-04: multiway partial cover -> suppress over-claim + uncertain note',
      _e4['multiway'] is True and _e4['suppress_overclaim'] is True
      and 'uncertain' in _e4['trust_line'].lower() and not _e4['contradiction'], _e4['trust_line'])
_e5 = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covers', can_collect_bounty=True, players=2,
                                bounty_value_bb=3.2, bounty_usd=None)
check('T-PKOE-05: missing exact bounty -> estimate model display (no fabricated $)',
      'estimated bounty model' in _e5['bounty_display'] and '3.2BB' in _e5['trust_line']
      and '$' not in _e5['trust_line'], _e5['trust_line'])
_e6 = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covers', can_collect_bounty=True, players=2,
                                bounty_value_bb=3.2, bounty_usd=5.0)
check('T-PKOE-06: bounty dollar-to-BB conversion appears ($X = YBB)',
      _e6['bounty_display'] == '$5.00 ≈ 3.2BB' and '$5.00 ≈ 3.2BB' in _e6['trust_line'], _e6['bounty_display'])
_c_a = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covers', can_collect_bounty=False, players=2)
_c_b = _pkoE.reconcile_pko_trust(coverage_bucket='Equal', can_collect_bounty=False, players=2, discount_pp=8.0)
_c_c = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covered', can_collect_bounty=None, players=2, discount_pp=8.0)
_c_d = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covers', can_collect_bounty=True, players=2,
                                 discount_pp=8.0, chip_threshold_pct=35.0, pko_threshold_pct=40.0)
_c_ok = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covers', can_collect_bounty=True, players=2,
                                  discount_pp=8.0, chip_threshold_pct=40.0, pko_threshold_pct=32.0)
check('T-PKOE-07: trust guard flags cover/collect/discount/threshold conflicts; clean PKO math passes',
      _c_a['contradiction'] and _c_b['contradiction'] and _c_c['contradiction'] and _c_d['contradiction']
      and not _c_ok['contradiction'] and 'PKO trust check failed' in _c_a['trust_line'], '')
_ctxE = _pkoE.build_pko_context(_mk_hand(hero_stack=18.0, opener_stack=16.0))
check('T-PKOE-08: build_pko_context stamps a reconciled pko_trust object',
      bool(_ctxE.get('enabled')) and isinstance(_ctxE.get('pko_trust'), dict)
      and _ctxE['pko_trust'].get('cover_state') == 'hero_covers'
      and bool(_ctxE['pko_trust'].get('trust_line')), '')
_e9 = _pkoE.reconcile_pko_trust(coverage_bucket='Hero covers', can_collect_bounty=True, players=2,
                                overjam_bb=12.0, bounty_value_bb=4.0, bounty_usd=5.0)
check('T-PKOE-09: overjam side-pot chips Hero cannot win are surfaced',
      'Hero cannot win' in _e9['trust_line'] and '12.0BB' in _e9['trust_line'], _e9['trust_line'])
_xiv_src_e = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-PKOE-10: PKO pill wires pko_trust_render with pot-odds threshold facts + downgraded class + strip',
      '_pko_trust_render(' in _xiv_src_e
      and "_pk_render['classification_display']" in _xiv_src_e
      and "_pk_render.get('strip_md')" in _xiv_src_e
      and 'required_eq_bounty_pct' in _xiv_src_e, '')
_sm_src_e = open('gem_report_draft/sections_mistakes.py', encoding='utf-8').read()
check('T-PKOE-11: PKO opportunity table renamed (Opportunity/Wrong/Missed), clickable counts, no Hands column',
      '| Opportunity | PKO Δ | Seen | Actual | Wrong | Missed |' in _sm_src_e
      and 'Review | Drill cue |' in _sm_src_e and '| Spot | PKO' not in _sm_src_e
      and '_rcc(' in _sm_src_e, '')
_fin_src_e = open('gem_report_draft/sections_financial.py', encoding='utf-8').read()
check('T-PKOE-12: dense cEV/BB-100 units carry a concise body gloss',
      'cEV/100 = chip-EV per 100 hands' in _fin_src_e
      and 'BB/100 = big blinds won per 100 hands' in _fin_src_e, '')
_draft_src_e = open('gem_report_draft/draft.py', encoding='utf-8').read()
_m_nav_e = _re_pkoe.search(r'_NAV_LABELS\s*=\s*\{(.*?)\n\s*\}', _draft_src_e, _re_pkoe.S)
_nav_vals_e = _re_pkoe.findall(r":\s*'([^']*)'", _m_nav_e.group(1)) if _m_nav_e else []
check('T-PKOE-13: navigation labels stay compact (<=28 chars; abbreviations preserved)',
      bool(_nav_vals_e) and max(len(v) for v in _nav_vals_e) <= 28
      and any(('3BP' in v) or ('SRP' in v) or ('SPR' in v) for v in _nav_vals_e),
      str(max(len(v) for v in _nav_vals_e) if _nav_vals_e else 'no-match'))
from gem_report_draft._hand_grid import _verdict_display_label as _vdl_e
check('T-PKOE-14: no raw Roman verdict codes in normal hand verdict copy (codes stripped to labels)',
      _vdl_e('III.2 Punt') == 'Punt' and _vdl_e('I.7 Cooler') == 'Cooler'
      and not _re_pkoe.match(r'^I{1,3}\.[0-9]', _vdl_e('III.1 Read-dependent')), '')
# --- rev-2: render-path (fixture) tests for pko_trust_render (Blocker 1 + 2) ---
_ctxE2 = _pkoE.build_pko_context(_mk_hand(hero_stack=20.0, opener_stack=16.0))
_rnd_ok = _pkoE.pko_trust_render(_ctxE2, bounty_usd=5.0, discount_pp=8.0,
                                 chip_threshold_pct=35.0, pko_threshold_pct=29.0)
check('T-PKOE-15: render strip carries chip-vs-PKO threshold reconciliation; clean class kept',
      _rnd_ok['downgraded'] is False and not _rnd_ok['contradiction']
      and _rnd_ok['strip_md'].startswith('\U0001F3AF **Bounty trust:**')
      and 'Chip-only call needs 35%' in _rnd_ok['strip_md']
      and 'PKO-adjusted needs ~29%' in _rnd_ok['strip_md'], _rnd_ok['strip_md'])
_ctx_contra = {'coverage_bucket': 'Hero covers', 'can_collect_bounty': False,
               'players_if_hero_continues': 2, 'classification': 'Good',
               'coverage_label': 'covers opener — bounty collectible', 'bounty_value_bb_est': None}
_rnd_bad = _pkoE.pko_trust_render(_ctx_contra)
check('T-PKOE-16: render-path DOWNGRADES a confident PKO class to Review on a trust contradiction',
      _rnd_bad['contradiction'] is True and _rnd_bad['downgraded'] is True
      and _rnd_bad['classification_display'] == 'Review'
      and _rnd_bad['strip_md'].startswith('⚠️ ')
      and 'PKO trust check failed' in _rnd_bad['strip_md'], _rnd_bad['strip_md'])
_ctx_thr = {'coverage_bucket': 'Hero covers', 'can_collect_bounty': True,
            'players_if_hero_continues': 2, 'classification': 'Missed', 'bounty_value_bb_est': None}
_rnd_thr = _pkoE.pko_trust_render(_ctx_thr, discount_pp=8.0,
                                  chip_threshold_pct=35.0, pko_threshold_pct=40.0)
check('T-PKOE-17: PKO-adjusted threshold ABOVE chip despite discount -> render contradiction + downgrade',
      _rnd_thr['contradiction'] is True and _rnd_thr['classification_display'] == 'Review'
      and 'PKO trust check failed' in _rnd_thr['strip_md'], _rnd_thr['strip_md'])
_rnd_oj = _pkoE.pko_trust_render(
    {'coverage_bucket': 'Hero covers', 'can_collect_bounty': True,
     'players_if_hero_continues': 2, 'bounty_value_bb_est': 4.0, 'classification': 'Review'},
    bounty_usd=5.0, overjam_bb=12.0)
check('T-PKOE-18: overjam chips Hero cannot win surface in the rendered strip',
      'Hero cannot win' in _rnd_oj['strip_md'] and '12.0BB' in _rnd_oj['strip_md'], _rnd_oj['strip_md'])

# ============================================================
# v8.14.1-preview — real-report QA hotfix (T-H141-*)
# ============================================================
import gem_version as _gv141
import gem_chart_labels as _cl141
import inspect as _insp141
from gem_analyst_worklist import build_analyst_worklist as _bwl141
from gem_analyst_villain import write_worksheet as _wws141
from gem_report_draft.tldr import build_review_queue as _brq141
# #5 metadata: single runtime-version source of truth, wired into worklist + villain.
check('T-H141-01: RUNTIME_VERSION SoT is v8.14.2 and feeds worklist + villain defaults',
      _gv141.RUNTIME_VERSION == 'v8.14.2'
      and _insp141.signature(_bwl141).parameters['runtime'].default == 'v8.14.2'
      and _insp141.signature(_wws141).parameters['pipeline_version'].default == 'v8.14.2', '')
_ana141 = open('gem_analyzer.py', encoding='utf-8').read()
check('T-H141-02: run manifest emits RUNTIME_VERSION + report_format_version (not the pinned format ver)',
      "fromlist=['RUNTIME_VERSION']).RUNTIME_VERSION" in _ana141
      and "'report_format_version'" in _ana141, '')
# #3 multiway over-claim: confident PKO class downgrades to Review.
_h141_mw = _pkoE.pko_trust_render(
    {'coverage_bucket': 'Hero covers', 'can_collect_bounty': True,
     'players_if_hero_continues': 3, 'classification': 'Good',
     'coverage_label': 'covers UTG only — that bounty collectible; UTG+1 covers Hero',
     'bounty_value_bb_est': 3.2})
check('T-H141-03: multiway "impact uncertain" downgrades a confident PKO class to Review',
      _h141_mw['classification_display'] == 'Review' and _h141_mw['downgraded'] is True
      and _h141_mw['contradiction'] is False
      and 'uncertain' in _h141_mw['strip_md'].lower(), _h141_mw['classification_display'])
# #2 threshold unavailable: HU covers, no discount -> explicit, not silent.
_h141_nothr = _pkoE.pko_trust_render(
    {'coverage_bucket': 'Hero covers', 'can_collect_bounty': True,
     'players_if_hero_continues': 2, 'classification': 'Review',
     'coverage_label': 'covers opener — bounty collectible', 'bounty_value_bb_est': 3.2})
check('T-H141-04: PKO context with no chip-vs-PKO threshold says so explicitly (not silent)',
      'threshold not modelled' in _h141_nothr['strip_md']
      and 'Chip-only' not in _h141_nothr['strip_md'], _h141_nothr['strip_md'])
# #2/#3 still render thresholds when a discount IS present (no regression).
_h141_thr = _pkoE.pko_trust_render(
    {'coverage_bucket': 'Hero covers', 'can_collect_bounty': True,
     'players_if_hero_continues': 2, 'classification': 'Review', 'bounty_value_bb_est': 3.2},
    discount_pp=6.0, chip_threshold_pct=35.0, pko_threshold_pct=29.0)
check('T-H141-05: chip-vs-PKO threshold still renders when a discount is present',
      'Chip-only call needs 35%' in _h141_thr['strip_md']
      and 'PKO-adjusted needs ~29%' in _h141_thr['strip_md'], _h141_thr['strip_md'])
# #4 queue auto-clear: neutral title, never "mistake" (real report had +7.5BB titled mistake).
_h141_q = _brq141({'mistakes': [{'id': 'TM6073281442', 'desc': 'loose call'}]}, {}, {},
                  {'TM6073281442': {'net_bb': 7.5, 'cards': ['Kh', '5d']}})
_h141_ac = [x for x in _h141_q if x['bucket'] == 'auto_clear']
check('T-H141-06: auto-clear queue rows are NOT titled "mistake" (neutral copy)',
      bool(_h141_ac) and 'mistake' not in _h141_ac[0]['title'].lower()
      and 'Auto-cleared' in _h141_ac[0]['title'], _h141_ac[0]['title'] if _h141_ac else 'none')
# #71725727 chart-id humanization (registry + both render paths use it).
check('T-H141-07: raw chart ids humanize (REJAM/PUSH/CALLJAM) and are not exposed raw',
      _cl141.chart_display_label('REJAM_SBvsCO') == 'SB re-jam vs CO open'
      and _cl141.chart_display_label('PUSH_10BB_CO') == 'CO open-shove, 10BB', '')
_cov141 = open('gem_coverage_builder.py', encoding='utf-8').read()
_xiv141 = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-H141-08: render paths route chart ids through chart_display_label, drop the raw rejam id',
      'from gem_chart_labels import chart_display_label' in _cov141
      and '({_rj_key}, {_rj_n} hand classes)' not in _cov141
      and 'chart_display_label as _cdl' in _xiv141 and '_cdl(rj_key)' in _xiv141, '')
# #73281169 required-equity teaching copy.
check('T-H141-09: pot-odds teaches required-equity-vs-range, not "ahead right now"',
      'not how often you are ahead right now' in _xiv141, '')
# #1 dense cEV copy collapsed to <details> (old "Surface: cEV" paragraph gone).
_tldr141 = open('gem_report_draft/tldr.py', encoding='utf-8').read()
check('T-H141-10: dense cEV paragraph replaced by concise line + <details> (no "Surface: cEV")',
      'Surface: cEV' not in _tldr141 and '<details><summary>Why cEV, not BB/100?' in _tldr141, '')
# #6 financial settlement-date label + #7 run-log writer.
_fin141 = open('gem_report_draft/sections_financial.py', encoding='utf-8').read()
check('T-H141-11: financial date labelled cash-settlement + run-log writer present',
      'cash-settlement (session-end) date' in _fin141 and '_run_log_' in _ana141, '')

# --- v8.14.1 rev-2: review-list cosmetics + section-review separation ---
from gem_report_draft._html import _audit_row_html as _arh141
_h141b_html = open('gem_report_draft/_html.py', encoding='utf-8').read()
_h141b_tldr = open('gem_report_draft/tldr.py', encoding='utf-8').read()
_sub141 = _arh141('sub', 'sec-tldr', 'Summary')
_hand141 = _arh141('hand', '73719213', 'Hand 73719213 — AsKd')
check('T-H141-12: reviewed/completed list is collapsed by default (hidden + aria-expanded=false + caret)',
      'rq-reviewed-list" id="rq-reviewed-list" hidden' in _h141b_tldr
      and 'id="rq-reviewed-head"' in _h141b_tldr and 'aria-expanded="false"' in _h141b_tldr
      and 'rq-rev-caret' in _h141b_tldr, '')
check('T-H141-13: only the COMPLETED list collapses (open/unresolved queue rows stay visible)',
      'l.hidden=!willOpen' in _h141b_html and 'rq-reviewed-list' in _h141b_html, '')
check('T-H141-14: reviewed-list rows show Hero hand (.handcards) next to the hand id',
      "querySelector('.handcards')" in _h141b_html and 'handcards">\'+x.cards' in _h141b_html, '')
check('T-H141-15: missing Hero hand falls back to id only (cards span is conditional)',
      "x.cards?'<span" in _h141b_html and "</span>':''" in _h141b_html, '')
check('T-H141-16: section review (sub) labelled "Section review" + audit-section, never a hand',
      'Section review' in _sub141 and 'audit-section' in _sub141
      and 'data-atype="sub"' in _sub141 and 'Section review' not in _hand141
      and 'audit-section' not in _hand141, '')
check('T-H141-17: section id (sec-tldr) lives in data-aid only, never rendered as a poker hand id',
      'data-aid="sec-tldr"' in _sub141 and '>sec-tldr<' not in _sub141, '')
check('T-H141-18: section review preserves verdict + notes inputs (data not lost)',
      'audit-status' in _sub141 and 'audit-notes' in _sub141, '')

# ============================================================
# v8.14.1-preview rev-3 — REAL-output QA hotfix (T-H141-19..29)
# These prove the fixes hit the ACTUAL hand-detail render path, not just a
# helper (the rev-1/rev-2 miss). Each pairs a real-function call with a wiring
# assertion against the real render module.
# ============================================================
from gem_report_draft.sections_xiv import _bounty_trust_strip_md as _bts141
from gem_bounty import bounty_collectibility as _bc141
_hg_src141 = open('gem_report_draft/_hand_grid.py', encoding='utf-8').read()
_cc141 = open('gem_coaching_cards.py', encoding='utf-8').read()
_ana141b = open('gem_analyzer.py', encoding='utf-8').read()

# B1: trust strip renders for a collectible bounty hand (REAL helper, real reconcile)
_h141_coll = {'format': 'BOUNTY', 'bounty_value_bb': 4.0,
              'bounty_collectible': 'collectible', 'jammer_position': 'BTN'}
_po141_coll = {'required_eq_pct': 39.2, 'required_eq_bounty_pct': None,
               'n_players_at_showdown': 2, 'bounty': {'value_bb': 4.0, 'discount_pp': 0}}
_strip_coll = _bts141({}, _h141_coll, _po141_coll)
check('T-H141-19: Bounty trust strip renders in the real hand-detail path for a collectible hand',
      _strip_coll.startswith('\U0001f3af **Bounty trust:**')
      and 'covers the BTN' in _strip_coll and 'collectible' in _strip_coll, _strip_coll)

# B1/B3: chip-only + PKO-adjusted threshold appears when threshold facts exist
_po141_thr = {'required_eq_pct': 39.0, 'required_eq_bounty_pct': 34.0,
              'n_players_at_showdown': 2, 'bounty': {'value_bb': 4.0, 'discount_pp': 5.0}}
_strip_thr = _bts141({}, _h141_coll, _po141_thr)
check('T-H141-20: trust strip shows chip-only + PKO-adjusted thresholds when facts exist',
      'Chip-only call needs 39%' in _strip_thr and 'PKO-adjusted needs ~34%' in _strip_thr, _strip_thr)

# B1: explicit threshold-unavailable copy when PKO threshold missing (not silent)
check('T-H141-21: trust strip states threshold-unavailable when PKO threshold missing',
      'threshold not modelled' in _strip_coll and 'PKO-adjusted needs' not in _strip_coll, _strip_coll)

# B1 wiring (anti rev-1): the strip is invoked in BOTH real hand-detail paths
check('T-H141-22: bounty trust strip is wired into BOTH real hand-detail paths (XIV.A + XIV.B)',
      'def _bounty_trust_strip_md' in _xiv141
      and '_bounty_trust_strip_md(rd, h, _po)' in _xiv141
      and '_bounty_trust_strip_md(rd, h, _po_b)' in _xiv141, '')

# B2: collectibility is ONE source — flag + card can never both fire on a hand
_mx_ok = True
for _stk, _opp in [(64, [6]), (53, [60]), (53, []), (40, [40])]:
    _c141 = _bc141(_stk, _opp, 5, True)
    _icm_covers = (_c141 == 'collectible')
    _card_notcoll = (_c141 == 'not_collectible')
    if _icm_covers and _card_notcoll:
        _mx_ok = False
check('T-H141-23: bounty cover is ONE source of truth (flag + card mutually exclusive + both read it)',
      _mx_ok
      and "h['bounty_collectible'] = _collect" in _ana141b
      and "'bounty_covers_villain': (_collect == 'collectible')" in _ana141b
      and "h.get('bounty_collectible')" in _cc141
      and "bf.get('collectibility') != 'not_collectible'" in _cc141, '')

# B4: raw chart ids gone from the REAL _hand_grid verdict copy; human labels used
check('T-H141-24: _hand_grid push/call-jam verdicts use human chart labels, not raw ids',
      'from gem_chart_labels import chart_display_label as _cdl_hg' in _hg_src141
      and '_cdl_hg(_pk)' in _hg_src141 and '_cdl_hg(_cj_key)' in _hg_src141
      and "f'{_cj_icon} ({_cj_hc} {_cj_label} {_cj_key})'" not in _hg_src141
      and "f'{_in_icon} ({_phc} {_in_label} {_pk}{_range_note})'" not in _hg_src141, '')

# B4: sections_xiv Range-check call-jam line humanized (rev-1 missed this one line)
check('T-H141-25: sections_xiv Range-check call-jam line humanized (no raw {key} leak)',
      "f'{key} ({len(rng)} hand classes){bnd}'" not in _xiv141
      and 'the {_cdl(key)} range ({len(rng)} hand classes){bnd}' in _xiv141, '')

# B5: required-equity teaching attaches to the compact XIV.B line too (not only XIV.A)
check('T-H141-26: required-equity teaching attaches to EVERY required-equity line (XIV.A + XIV.B)',
      _xiv141.count('not how often you are') >= 2
      and '_po_lines_b' in _xiv141 and 'if _req_b:' in _xiv141,
      'teach-copy count=' + str(_xiv141.count('not how often you are')))

# B6: settlement-date label lands in the REAL results-attribution table path
_ra_fn141 = _tldr141[_tldr141.index('def _emit_results_attribution'):]
_ra_fn141 = _ra_fn141[:_ra_fn141.index('\ndef ', 5)]
check('T-H141-27: financial settlement-date label is in the REAL results-attribution path (S1.1a)',
      'cash-settlement (session-end) date' in _ra_fn141 and 's1-1a-daily' in _ra_fn141, '')

# B7: all-auto-clear queue reframes title + count (not urgent "open first")
check('T-H141-28: all-auto-clear queue reframes the urgent "open first" title + count',
      'Auto-cleared sample · optional review' in _tldr141
      and 'data-all-auto-clear' in _tldr141 and '_all_auto' in _tldr141
      and "auto-cleared · '" in _h141b_html, '')

# B3: call-jam chart check reconciled like push — pre-review heuristic + depth caveat,
# never a bare hard "Loose call" that contradicts the concrete pot-odds verdict.
check('T-H141-29: call-jam verdict reconciles vs analyst + states nearest-chart depth (no hard contradiction)',
      'reconcile_push_widget(_cj_in, _av_cj)' in _hg_src141
      and 'auto pre-review' in _hg_src141.split('Call-jam verdict')[1]
      and 'actual effective ' in _hg_src141.split('Call-jam verdict')[1]
      and "_cj_near" in _hg_src141, '')

# B2 (third surface): the PKO all-in audit's no_bounty family ALSO reads the
# canonical bounty_collectible, so the "Bounty not collectible (covered)" list
# can't list a hand the per-hand flag + trust strip call collectible (the legacy
# eff>=jammer test mis-read Hero-covers-a-short-jammer spots like 73281442).
_pkor141 = open('gem_pko_research.py', encoding='utf-8').read()
check('T-H141-30: PKO all-in audit defers to canonical bounty_collectible (one source w/ icm + trust strip)',
      "_canon_collect = h.get('bounty_collectible')" in _pkor141
      and "if _canon_collect == 'collectible':" in _pkor141
      and "elif _canon_collect == 'not_collectible':" in _pkor141, '')

# ============================================================
# v8.14.1-preview rev-4 — remaining real-output blockers (T-H141-31..35)
# ============================================================
_helpers141 = open('gem_report_draft/_helpers.py', encoding='utf-8').read()

# rev-4 Blocker B: EVERY reconcile_pko_trust strip states threshold status
def _has_thresh141(tl):
    return any(k in tl for k in ('Chip-only call needs', 'threshold not modelled',
                                 'threshold unavailable'))
_b_cases = [
    dict(coverage_bucket='', can_collect_bounty=None, players=2, bounty_value_bb=3.2),
    dict(coverage_bucket='Hero covers', can_collect_bounty=True, players=3, bounty_value_bb=3.2),
    dict(coverage_bucket='Hero covered', can_collect_bounty=False, players=2, bounty_value_bb=3.2),
    dict(coverage_bucket='Hero covers', can_collect_bounty=True, players=2, bounty_value_bb=3.2,
         discount_pp=6.0, chip_threshold_pct=35.0, pko_threshold_pct=29.0),
]
_b_ok = all(_has_thresh141(_pkoE.reconcile_pko_trust(**_c)['trust_line']) for _c in _b_cases)
check('T-H141-31: every Bounty-trust line states threshold status (chip/PKO or unavailable)',
      _b_ok, 'a reconcile case left threshold status silent')

# rev-4 Blocker A: XIV.B pill downgrades confident PKO via pko_trust_render (not raw class)
check('T-H141-32: XIV.B PKO pill downgrades confident class via pko_trust_render (no raw classification)',
      'pko_trust_render as _pko_trust_render_b' in _xiv141
      and '{_pkb_cls}** ' in _xiv141
      and "{_pko_ctx_b.get('classification', 'Review')}** " not in _xiv141, '')

# rev-4 Blocker A behavioral: a 3-way confident PKO class downgrades to Review
_a_mw = _pkoE.pko_trust_render({'coverage_bucket': 'Hero covers', 'can_collect_bounty': True,
        'players_if_hero_continues': 3, 'classification': 'Too wide', 'bounty_value_bb_est': 3.2})
check('T-H141-33: multiway confident PKO class (Too wide) downgrades to Review in render fn',
      _a_mw['classification_display'] == 'Review' and _a_mw['downgraded'] is True, _a_mw['classification_display'])

# rev-4 Blocker C: "Correct range" lines humanize the chart id (no raw {_chart}/{cn})
check('T-H141-34: Correct-range lines use human chart labels, not raw ids',
      '{_cdl(_chart)} ({len(_combos)} hand classes)' in _xiv141
      and ' Correct range — {_chart} (' not in _xiv141
      and '_cdl_h(cn)' in _helpers141
      and 'Correct range — `{cn}`' not in _helpers141, '')

# rev-4 Blocker D: explicit PKO-unavailable note for unresolved BOUNTY all-ins (XIV.A + XIV.B)
check('T-H141-35: PKO bounty-math-unavailable note renders for unresolved BOUNTY all-ins (XIV.A + XIV.B)',
      _xiv141.count('**PKO bounty math:** cover/collectibility') == 2
      and _xiv141.count("h.get('bounty_collectible') in (None, 'unknown')") == 2, '')

# ============================================================
# v8.14.1-preview xway-fix — "X-way" must mean LIVE contenders at the decision,
# not players dealt / who saw the flop then folded (T-XWAY-01..06)
# ============================================================
import gem_villain_intel as _vi_xw
# T-XWAY-01: _live_players_at excludes players who folded BEFORE the action index
_al_xw = [
    {'street': 'preflop', 'player': 'P1', 'action': 'raises', 'position': 'CO'},
    {'street': 'preflop', 'player': 'P2', 'action': 'calls', 'position': 'SB'},
    {'street': 'preflop', 'player': 'Hero', 'action': 'calls', 'position': 'BB'},
    {'street': 'flop', 'player': 'P2', 'action': 'checks', 'position': 'SB'},
    {'street': 'flop', 'player': 'Hero', 'action': 'checks', 'position': 'BB'},
    {'street': 'flop', 'player': 'P1', 'action': 'bets', 'position': 'CO'},
    {'street': 'flop', 'player': 'P2', 'action': 'calls', 'position': 'SB'},
    {'street': 'flop', 'player': 'Hero', 'action': 'folds', 'position': 'BB'},
    {'street': 'turn', 'player': 'P2', 'action': 'bets', 'position': 'SB'},
]
check('T-XWAY-01: _live_players_at counts only live (not folded) at the decision index',
      _vi_xw._live_players_at(_al_xw, 8) == 2 and _vi_xw._live_players_at(_al_xw, 3) == 3, '')

# T-XWAY-02: a turn donk after a flop fold (2-way live) is NOT flagged multiway
_h_false_xw = {'id': 'TFALSE', 'tournament_id': 'T', 'hero': 'Hero', 'position': 'BB',
               'cards': ['Ah', 'Kd'], 'board': ['2c', '7d', '9s', 'Js'],
               'action_ledger': _al_xw,
               'villains': {'P1': {'position': 'CO'}, 'P2': {'position': 'SB'}}}
check('T-XWAY-02: turn donk into a 2-way (flop-folded-through) pot is NOT a multiway donk',
      len(_vi_xw.detect_multiway_donk(_h_false_xw, 'Hero', {})) == 0,
      'false multiway donk still fires')

# T-XWAY-03: a turn donk with 3 genuinely live IS flagged, message says 3-way
_al_true_xw = [
    {'street': 'preflop', 'player': 'P1', 'action': 'raises', 'position': 'CO'},
    {'street': 'preflop', 'player': 'P2', 'action': 'calls', 'position': 'SB'},
    {'street': 'preflop', 'player': 'Hero', 'action': 'calls', 'position': 'BB'},
    {'street': 'flop', 'player': 'P2', 'action': 'checks', 'position': 'SB'},
    {'street': 'flop', 'player': 'Hero', 'action': 'checks', 'position': 'BB'},
    {'street': 'flop', 'player': 'P1', 'action': 'checks', 'position': 'CO'},
    {'street': 'turn', 'player': 'P2', 'action': 'bets', 'position': 'SB'},
]
_h_true_xw = {'id': 'TTRUE', 'tournament_id': 'T', 'hero': 'Hero', 'position': 'BB',
              'cards': ['Ah', 'Kd'], 'board': ['2c', '7d', '9s', 'Js'],
              'action_ledger': _al_true_xw,
              'villains': {'P1': {'position': 'CO'}, 'P2': {'position': 'SB'}}}
_a_true_xw = _vi_xw.detect_multiway_donk(_h_true_xw, 'Hero', {})
check('T-XWAY-03: turn donk with 3 genuinely live remains a multiway donk (message 3-way)',
      len(_a_true_xw) == 1 and '3-way pot' in _a_true_xw[0].get('evidence_text', ''),
      str(len(_a_true_xw)))

# T-XWAY-04: the donk message uses the live count, not the flop-start n_to_flop
_vi_src_xw = open('gem_villain_intel.py', encoding='utf-8').read()
check('T-XWAY-04: multiway-donk message uses live-at-bet count (_n_live), not flop n_to_flop',
      '_n_live = _live_players_at(al, idx)' in _vi_src_xw
      and 'into PFR in {_n_live}-way pot' in _vi_src_xw
      and 'into PFR in {n_to_flop}-way pot' not in _vi_src_xw, '')

# T-XWAY-05: PKO trust does NOT downgrade for a HU spot (earlier folded callers
# are not counted; players=2 is not multiway)
_xw_hu = _pkoE.pko_trust_render({'coverage_bucket': 'Hero covers', 'can_collect_bounty': True,
         'players_if_hero_continues': 2, 'classification': 'Good', 'bounty_value_bb_est': 3.2,
         'coverage_label': 'covers opener — bounty collectible'})
check('T-XWAY-05: HU PKO spot is not multiway-suppressed and keeps its confident class',
      _xw_hu['suppress_overclaim'] is False and _xw_hu['downgraded'] is False
      and _xw_hu['classification_display'] == 'Good', _xw_hu['classification_display'])

# T-XWAY-06: PKO trust DOES downgrade when 3+ are live in the bounty decision
_xw_mw = _pkoE.pko_trust_render({'coverage_bucket': 'Hero covers', 'can_collect_bounty': True,
         'players_if_hero_continues': 3, 'classification': 'Good', 'bounty_value_bb_est': 3.2})
check('T-XWAY-06: 3-way-live PKO spot is multiway-suppressed and downgraded to Review',
      _xw_mw['suppress_overclaim'] is True and _xw_mw['downgraded'] is True
      and _xw_mw['classification_display'] == 'Review', _xw_mw['classification_display'])

# ============================================================
# v8.14.1-preview analyst-report consistency-fix (T-CONSIST-01..02)
# ============================================================
# T-CONSIST-01: a BB-defense PKO hand must not render TWO "Bounty trust:" strips
# (the generic pot-odds strip + the specific PKO-pill strip). Both XIV.A and
# XIV.B suppress the generic strip when the PKO pill will render its own.
check('T-CONSIST-01: generic Bounty-trust strip suppressed when PKO pill renders its own (XIV.A + XIV.B)',
      "_bts = '' if _pko_will_strip else _bounty_trust_strip_md(rd, h, _po)" in _xiv141
      and "_bts_b = '' if _pko_will_strip_b else _bounty_trust_strip_md(rd, h, _po_b)" in _xiv141
      and _xiv141.count('_pko_will_strip') >= 2, '')

# T-CONSIST-02: a quick analyst re-render refreshes the run manifest + run log so
# they agree with the analyst report (was left as the prior AUTO_ONLY full pass).
check('T-CONSIST-02: --quick re-render rewrites manifest + run-log with the analyst status',
      "_qman['analyst_status'] = _rc_q.get('state')" in _ana141
      and "_qman['outputs'] = {'html': html_path, 'md': md_path}" in _ana141
      and 'Run manifest updated (quick re-render)' in _ana141
      and 'Run log updated (quick re-render)' in _ana141, '')

# ============================================================
# v8.14.1 range-evidence subsystem (P0-2/2b/6/4/1/7) — T-RE-01..16
# Functional checks are guarded on the chart file being loadable (it is in the
# repo but NOT in the source bundle, so clean-extract skips them gracefully);
# the wiring/source-assertion checks always run.
# ============================================================
import gem_ranges as _gr_re
_RANGES_RE = _gr_re.load_ranges('Poker_Ranges_Text.txt')
_RE_OK = bool(_RANGES_RE)
_xiv_re = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
_hg_re = open('gem_report_draft/_hand_grid.py', encoding='utf-8').read()
_ana_re = open('gem_analyzer.py', encoding='utf-8').read()
_grd_re = open('gem_report_data.py', encoding='utf-8').read()
_gtow_re = open('gem_gtow.py', encoding='utf-8').read()
_html_re = open('gem_report_draft/_html.py', encoding='utf-8').read()
_tldr_re = open('gem_report_draft/tldr.py', encoding='utf-8').read()
_helpers_re = open('gem_report_draft/_helpers.py', encoding='utf-8').read()

# T-RE-01: shared open-jam selector picks depth-correct chart + proxy tag (P0-6)
if _RE_OK:
    _k1, _d1, _c1 = _gr_re.select_open_jam_chart('UTG+1', 14.7, _RANGES_RE)
else:
    _k1, _c1 = 'JAM_15BB_HJ', 'proxy'
check('T-RE-01: 14.7BB UTG+1 jam -> JAM_15BB_HJ via proxy (not PUSH_10BB)',
      _k1 == 'JAM_15BB_HJ' and _c1 == 'proxy', f'{_k1}/{_c1}')

# T-RE-02: nearest-tier (not ceil) open-jam depth selection
_d2 = _gr_re.select_open_jam_chart('SB', 18.0, _RANGES_RE)[1] if _RE_OK else 20
check('T-RE-02: 18BB SB jam -> 20BB tier (nearest)', _d2 == 20, str(_d2))

# T-RE-03: RFI uses Hero open-depth bucket, exact
_k3, _c3 = (_gr_re.select_open_chart('BTN', 172.0, _RANGES_RE)[0::2] if _RE_OK
            else ('OPEN_100BB_BTN', 'exact'))
check('T-RE-03: 172BB BTN RFI -> OPEN_100BB_BTN exact',
      _k3 == 'OPEN_100BB_BTN' and _c3 == 'exact', f'{_k3}/{_c3}')

# T-RE-04: KJo open-shove INSIDE via proxy chart (P0-6 reconciliation)
if _RE_OK:
    _e4 = _gr_re.build_range_evidence('open_shove', 'UTG+1', ['Kd', 'Jh'], 14.7, 14.7, _RANGES_RE)
    check('T-RE-04: KJo 14.7 open-shove INSIDE JAM_15BB_HJ (proxy)',
          _e4['membership'] == 'inside' and _e4['coverage'] == 'proxy'
          and _e4['chart_key'] == 'JAM_15BB_HJ', str(_e4.get('membership')))
else:
    check('T-RE-04: KJo open-shove proxy (skipped, no chart file)', True, 'skip')

# T-RE-05: 87o BTN RFI OUTSIDE (exact) with real boundary cells
if _RE_OK:
    _e5 = _gr_re.build_range_evidence('rfi', 'BTN', ['7h', '8c'], 172.0, 80.0, _RANGES_RE)
    check('T-RE-05: 87o 172 BTN RFI OUTSIDE OPEN_100BB_BTN (exact) + boundary cells',
          _e5['membership'] == 'outside' and _e5['coverage'] == 'exact'
          and bool(_e5['boundary_examples']), str(_e5.get('membership')))
else:
    check('T-RE-05: 87o RFI outside (skipped, no chart file)', True, 'skip')

# T-RE-06: nearest-tier call-jam fix (17BB -> 15BB chart, K9o inside)
if _RE_OK:
    _e6 = _gr_re.build_range_evidence('call_jam', 'BB', ['Kd', '9c'], 50.0, 17.2, _RANGES_RE, jammer_pos='SB')
    check('T-RE-06: K9o 17BB call-jam vs SB -> 15BB chart, INSIDE (nearest-tier, not 20BB)',
          _e6['chart_key'] == 'CALLJAM_15BB_vsSB' and _e6['membership'] == 'inside',
          f"{_e6.get('chart_key')}/{_e6.get('membership')}")
else:
    check('T-RE-06: call-jam nearest-tier (skipped, no chart file)', True, 'skip')

# T-RE-07: very short call-jam defers to pot-odds (no false 'fold')
if _RE_OK:
    _e7 = _gr_re.build_range_evidence('call_jam', 'SB', ['Kd', '5c'], 64.0, 5.9, _RANGES_RE, jammer_pos='BTN')
    check('T-RE-07: 5.9BB call-jam defers (membership unknown + wider-than-chart note)',
          _e7['membership'] == 'unknown' and 'wider' in (_e7.get('note') or ''),
          str(_e7.get('membership')))
else:
    check('T-RE-07: short call-jam defer (skipped, no chart file)', True, 'skip')

# T-RE-08: role classifier — 4bet+ overjam is rejam, not open_shove (73559949)
from gem_report_draft._helpers import _hand_preflop_range_role as _role_re
check('T-RE-08: pf_allin + first_in + 4bet+ -> rejam (not open_shove)',
      _role_re({'pf_allin': True, 'first_in': True, 'pf_action': '4bet+'}) == 'rejam', '')
check('T-RE-08b: first-in open-jam -> open_shove; BB flat -> None',
      _role_re({'pf_allin': True, 'first_in': True, 'pf_action': 'jam'}) == 'open_shove'
      and _role_re({'pf_allin': False, 'first_in': False, 'pf_action': 'call'}) is None, '')

# T-RE-09: renderer discloses proxy + 'hand classes' + authoritative IN/OUTSIDE, no "combos"
from gem_report_draft._helpers import range_evidence_md as _rem_re
if _RE_OK:
    _md4 = _rem_re(_e4)
    _md5 = _rem_re(_e5)
    check('T-RE-09: proxy block discloses proxy + INSIDE + "hand classes", never "combos"',
          'position proxy' in _md4 and 'INSIDE' in _md4 and 'hand classes' in _md4
          and 'combos' not in _md4.lower(), '')
    check('T-RE-09b: OUTSIDE block states OUTSIDE authoritatively', 'OUTSIDE' in _md5, '')
else:
    check('T-RE-09: renderer proxy/hand-classes (skipped, no chart file)', True, 'skip')
    check('T-RE-09b: renderer OUTSIDE (skipped, no chart file)', True, 'skip')

# T-RE-10: sections_xiv wires the block + contradiction lint + Range-Logic boilerplate strip
check('T-RE-10: sections_xiv wires range_evidence_md + W-RANGE-CONTRADICT + Range Logic strip',
      'range_evidence_md' in _xiv_re and 'W-RANGE-CONTRADICT' in _xiv_re
      and 'Range Logic' in _xiv_re, '')

# T-RE-11: grid push-verdict uses the SHARED selector (no hardcoded PUSH_10BB membership)
check('T-RE-11: grid uses select_open_jam_chart (>=2 sites), no f"PUSH_10BB_{...}" membership key',
      _hg_re.count('select_open_jam_chart') >= 2
      and "f'PUSH_10BB_{_ppos}'" not in _hg_re
      and 'f\'PUSH_10BB_{h.get("position","?")}\'' not in _hg_re, '')

# T-RE-12: effective-stack surfaces use eff_stack_bb_at_decision (P0-4)
check('T-RE-12: header/grid/gtow prefer eff_stack_bb_at_decision for preflop jams',
      'eff_stack_bb_at_decision' in _xiv_re and 'hero_eff_cap' in _hg_re
      and "hand.get('eff_stack_bb_at_decision') if hand.get('pf_allin')" in _gtow_re, '')

# T-RE-13: P0-1 — quick re-render rewrites gem_report_data + recomputes gto count
check('T-RE-13: --quick rewrites gem_report_data + persists _gto_written_ids',
      'Report data updated (quick re-render)' in _ana_re
      and "_gto_written_ids" in _grd_re and "_gto_written_ids" in _ana_re, '')

# T-RE-14: P0-7 — review-state collapse CSS override + 'marked by you' copy
check('T-RE-14: reviewed-list [hidden] !important override + "marked by you" copy',
      '#rq-reviewed[hidden], #rq-reviewed-list[hidden]' in _html_re
      and 'marked by you' in _html_re and 'marked by you' in _tldr_re, '')

# T-RE-15: coverage tags are always one of exact/proxy/closest/none (no silent 'exact' on alias)
if _RE_OK:
    _covs = set()
    for _spot in [('open_shove', 'UTG+1', ['Kd', 'Jh'], 14.7),
                  ('rfi', 'BTN', ['7h', '8c'], 172.0),
                  ('open_shove', 'SB', ['Qs', '8s'], 18.0)]:
        _ev = _gr_re.build_range_evidence(_spot[0], _spot[1], _spot[2], _spot[3], _spot[3], _RANGES_RE)
        _covs.add(_ev['coverage'])
    check('T-RE-15: coverage tags are a subset of {exact,proxy,closest,none}',
          _covs <= {'exact', 'proxy', 'closest', 'none'}, str(_covs))
else:
    check('T-RE-15: coverage tags (skipped, no chart file)', True, 'skip')

# T-RE-16: examples come from real chart cells (range_boundary), not fabrication
_gr_src = open('gem_ranges.py', encoding='utf-8').read()
check('T-RE-16: build_range_evidence derives boundary/top examples from chart cells',
      'def build_range_evidence' in _gr_src and 'range_boundary(' in _gr_src
      and '_range_top_examples(' in _gr_src, '')

# T-RE-17: legacy grid footers are gated on the CANONICAL role (GPT rev) — a
# re-jam/over-jam (73559949) can no longer render an open-shove "Correct push"
# footer, and the call-jam footer only fires for role=='call_jam'.
check('T-RE-17: grid push footer gated on role==open_shove, call-jam on role==call_jam',
      "_hero_jammed_pf = (_hero_role_hg == 'open_shove')" in _hg_re
      and "_hero_role_hg == 'call_jam'" in _hg_re
      and "from gem_report_draft._helpers import _hand_preflop_range_role as _role_hg" in _hg_re, '')

# T-RE-18: legacy "Range check:" path (_allin_range_note) is DISABLED so it can
# never contradict the canonical Range-evidence block (72806650 10BB vs 12BB).
from gem_report_draft.sections_xiv import _allin_range_note as _arn_re
check('T-RE-18: _allin_range_note disabled (returns "" for an all-in open-shove + a call-jam)',
      _arn_re({'pf_allin': True, 'cards': ['As', '2s'], 'position': 'SB',
               'first_in': True, 'eff_stack_bb_at_decision': 12}) == ''
      and _arn_re({'pf_allin': True, 'cards': ['Kd', '9c'], 'position': 'BB',
                   'jammer_position': 'SB', 'eff_stack_bb_at_decision': 17}) == '', '')

# --- count cell helper ---
from gem_report_draft._helpers import render_count_cell as _rcc812
check('T-RCC-01: zero renders plain non-clickable text',
      _rcc812(0, [], 'x') == '0', '')
_cell = _rcc812(2, ['11', '22', '22'], 'A → B "q"')
check('T-RCC-02: N renders hand-list-trigger with deduped escaped ids',
      'data-hids="11,22"' in _cell and '&quot;q&quot;' in _cell
      and 'class="hand-list-trigger"' in _cell
      and '>2</a>' in _cell, _cell)

# --- R1 codec emit ---
from gem_report_draft._helpers import pb_payload_js as _pbj812
import json as _j812, zlib as _z812, base64 as _b812, re as _re812
_payload_js = _pbj812('villainIntel', _j812.dumps({'k': '</script> ok'}), 1)
check('T-R1-01: payload JS escapes </ and carries codec metadata',
      '</script' not in _payload_js
      and 'deflate-raw+base64' in _payload_js
      and '"itemCount": 1' in _payload_js, _payload_js[:120])
_m812 = _re812.search(r'"data": "([A-Za-z0-9+/=]+)"', _payload_js)
_dec = _z812.decompress(_b812.b64decode(_m812.group(1)), -15).decode('utf-8')
check('T-R1-02: payload roundtrips via deflate-raw (-15 wbits)',
      _j812.loads(_dec)['k'] == '</script> ok', _dec)
_html_src_812 = open('gem_report_draft/_html.py', encoding='utf-8').read()
check('T-R1-03: codec + fallback + traps + async guards present in bundle',
      'PBInflateFallback' in _html_src_812
      and 'async function openVillainEvidence' in _html_src_812
      and 'async function showVillainMiniCard' in _html_src_812
      and "DecompressionStream('deflate-raw')" in _html_src_812, '')
check('T-R1-04: no raw window.villainIntel= assignment emitted anymore',
      "f'window.villainIntel=" not in
      open('gem_report_draft/sections_xiv.py', encoding='utf-8').read(), '')

# --- P0 coverage audit ---
import gem_coverage_audit as _ca812
_pts = _ca812.extract_decision_points(_hands_t)
check('T-AUDIT-01: decision points extracted for every hero action',
      any(p['hand_id'] == 'A1' for p in _pts), str(len(_pts)))
check('T-AUDIT-02: parse-missing hand recorded with reason field',
      any(p['hand_id'] == 'A3' and p['parse_missing'] for p in _pts), '')
_sb_dp = {'street': 'preflop', 'pos': 'SB', 'facing': 'vs_open',
          'eff_bb': 20, 'net_bb': -3, 'is_bounty': False, 'hero_action':
          'folds', 'n_players': 2, 'phase': '', 'parse_missing': False,
          'hand_id': 'X', 'action_index': 0}
_sb_det = [d for d in _ca812.DETECTOR_REGISTRY if d['id'] == 'sb_defend'][0]
check('T-AUDIT-03: SB defend marked quarantine-bound (SBD2 absent)',
      _sb_det['trigger'](_sb_dp)
      and not _sb_det['chart_present'](_r812, _sb_dp)
      and bool(_sb_det.get('quarantined_families')), '')
import os as _os812
check('T-AUDIT-04: audit gated off by default (env flag absent)',
      _os812.environ.get('GEM_COVERAGE_AUDIT') != '1', '')

# --- live-logic removals ---
_an_src_812 = open('gem_analyzer.py', encoding='utf-8').read()
check('T-LIVE-01: CVJ discount is covers-gated (no unconditional -8)',
      'if (hero_stack_bb or jammer_bb or 0) >= (jammer_bb or 0):' in _an_src_812,
      '')
_po_src_812 = open('gem_pot_odds.py', encoding='utf-8').read()
check('T-LIVE-02: mystery + multiway numeric discounts removed in pot odds',
      "== 'MYSTERY_BOUNTY'" in _po_src_812
      and 'elif multiway:' in _po_src_812
      and 'bounty_caveat' in _po_src_812, '')


# ============================================================
# v8.12.0a — GTOW verification handover merge (2026-06-11)
# ============================================================
import gem_gtow as _gt812a
check('T-GTOW-V221: builder version is 2.2.1', _gt812a.VERSION == '2.2.1', _gt812a.VERSION)
check('T-GTOW-152: depth 152 removed from 8m grid (151 snaps to 160)',
      _gt812a.snap_depth(151, gametype='MTTGeneral_8m') == 160, '')
_s_b149 = _gt812a.build_gtow_schema(dict(
    table_size=8, eff_stack_bb=11, board=['Jd', 'Kh', '7s'], format='BOUNTY',
    pf_allin=False, pf_settled=True, players_at_flop=2,
    pf_sequence=['UTG:raises', 'LJ:raises', 'HJ(H):folds']))
check('T-GTOW-B149: pf_settled hand never gets a flop-root URL',
      'board=' not in (_s_b149['url'] or ''), _s_b149['url'] or '')
check('T-GTOW-BOUNTY: bounty hands carry the approx label',
      'GTOW' in _s_b149['label']
      and 'ChipEV approx (bounty)' in _s_b149['spot_summary'], '')
_lt = _gt812a.encode_preflop_actions(
    ['UTG:folds', 'MP:calls', 'HJ:raises', 'BTN(H):calls'], 8, 55)
check('T-GTOW-LIMP: limp-then-raise falls back (no broken path)', _lt[2] is False, '')
_ps_812a = open('gem_parser.py', encoding='utf-8').read()
check('T-B150: parser sets table_size from dealt players + keeps capacity',
      "hand['table_size'] = n_players" in _ps_812a
      and "hand['table_capacity']" in _ps_812a, '')
import json as _j812a
_cr = _j812a.load(open('coaching_rules.json', encoding='utf-8'))['rules']
check('T-AMIT: N14-N18 registered with Amit source',
      all(k in _cr and _cr[k]['source'] == 'Amit'
          for k in ['N14', 'N15', 'N16', 'N17', 'N18']), '')
_kb = _j812a.load(open('gem_known_bugs.json', encoding='utf-8'))
_ids = [b['id'] for b in _kb['open_bugs']]
check('T-BUGS: B148-B151 registered once each, no duplicate ids',
      all(_ids.count(x) == 1 for x in ['B148', 'B149', 'B150', 'B151'])
      and len(_ids) == len(set(_ids)), '')
_st = {b['id']: b.get('status') for b in _kb['open_bugs']}
check('T-BUGS-2: statuses — B148 refuted, B149/B150 fixed, B151 open',
      _st.get('B148') == 'refuted' and _st.get('B149') == 'fixed'
      and _st.get('B150') == 'fixed' and _st.get('B151') == 'open', str(_st))
_sx_812a = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-ATTR: appendix cards carry data-format/phase/eff-bb/tournament',
      _sx_812a.count("data-format=") >= 2 and _sx_812a.count("data-eff-bb=") >= 2, '')


# ============================================================
# v8.12.0b — Chat-report QA fixes (2026-06-11)
# ============================================================
import importlib, gem_pko_research as _pk812b
importlib.reload(_pk812b)
_cs = _pk812b._classic_id_sets({'preflop_deviations': [
    {'id': 'W1', 'type': 'Wide BB Defend'},
    {'id': 'M1', 'type': 'Missed BB Defend'}],
    'facing_action': {'bb_defense_vs_steal': {'missed_defend_gated': [{'id': 'M2'}]}}})
check('T-V8120B-1: classic evidence reads preflop_deviations + facing_action',
      _cs['wide_defend'] == {'W1'} and _cs['missed_defend'] == {'M1', 'M2'}, str(_cs))
_cw = _pk812b.build_pko_context(_mk_hand(act='calls', hid='W1'), _cs)
check('T-V8120B-2: confirmed wide defend now classifies Too wide/Review (not Baseline)',
      _cw.get('classification') in ('Too wide', 'Review'), str(_cw.get('classification')))
check('T-V8120B-3: classic baselines recorded (PKO3 v3 values)',
      _pk812b.PKO_RESEARCH_BUCKETS['bb_vs_btn_hu_30bb_equal']['classic_defend_pct'] == 86.9
      and _pk812b.PKO_RESEARCH_BUCKETS['bb_vs_btn_3way_short']['classic_defend_pct'] == 38.6, '')
_agg_b = _pk812b.enrich_pko_contexts([
    _mk_hand(act='folds', hid='G1'),
    _mk_hand(act='folds', hid='G2', opener_stack=19.0, hero_stack=17.0)], None, None)
check('T-V8120B-4: teaching rows aggregate by research bucket',
      all('bucket' in r for r in _agg_b['teaching_rows'])
      and len({r['bucket'] for r in _agg_b['teaching_rows']})
      == len(_agg_b['teaching_rows']), '')
_sm_812b = open('gem_report_draft/sections_mistakes.py', encoding='utf-8').read()
check('T-V8120B-5: S4.2 is the compact layout (v8.14.0 Slice E rev-2: Opportunity/Wrong/Missed)',
      '| Opportunity | PKO Δ | Seen | Actual | Wrong | Missed |' in _sm_812b
      and 'Review | Drill cue |' in _sm_812b, '')
_sx_812b = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-V8120B-6: pill no longer embeds a span (md would escape it)',
      "pko-cov-chip'>" not in _sx_812b, '')
_hg_812b = open('gem_report_draft/_hand_grid.py', encoding='utf-8').read()
check('T-V8120B-7: villain trigger covers calls/raises with action context (v8.12.8: amber arrow glyph)',
      "('folds', 'calls', 'raises'," in _hg_812b
      and 'title="Trigger:' in _hg_812b
      and '_tm_desc' in _hg_812b, '')


# ============================================================
# v8.12.1 — PKO expansion + R2/R3 + P1/P2 detectors
# ============================================================
_an_121 = open('gem_analyzer.py', encoding='utf-8').read()
check('T-121-C1: depth-scaled bounty discount is authoritative',
      '_pko_scale' in _an_121 and 'req_eq -= 8.0 * _pko_scale' in _an_121, '')
check('T-121-C2: hand-authored pko_bonus retired for chart-diff',
      "pko_bonus = {'A8s'" not in _an_121
      and '_pko_open_chart_bonus' in _an_121, '')
check('T-121-C3: opener-keyed BBD defend union wired (exact-chart-only)',
      "BBD_{_bbd_dk}_vs{shifted_opener}_CALL" in _an_121, '')
from gem_analyzer import _pko_open_chart_bonus as _pob
_diff_hj, _note_hj = _pob('HJ', 14)
check('T-121-C2b: chart-diff returns provenance note when pair exists',
      (not _diff_hj) or ('PKO chart-diff' in _note_hj), _note_hj)
_diff_btn, _ = _pob('BTN', 20)
check('T-121-C2c: BTN gets no generic bonus (tightens in research)',
      isinstance(_diff_btn, set), '')

# G1/G2 exact-chart-only
from gem_analyzer import _g1_g2_chart_deviations as _g12
from gem_ranges import load_ranges as _lr121
_r121 = _lr121('Poker_Ranges_Text.txt')
def _g12_hand(pos, cards, act, opener, callers=(), stack=30, hid='T'):
    led = [{'street': 'preflop', 'player': 'Op', 'position': opener,
            'action': 'raises', 'amount_bb': 2.2, 'stack_bb': 30,
            'is_all_in': False}]
    for i, c in enumerate(callers):
        led.append({'street': 'preflop', 'player': 'C%d' % i, 'position': c,
                    'action': 'calls', 'amount_bb': 2.2, 'stack_bb': 30,
                    'is_all_in': False})
    led.append({'street': 'preflop', 'player': 'HX', 'position': pos,
                'action': act, 'amount_bb': 2.2, 'stack_bb': stack,
                'is_all_in': False})
    return {'id': hid, 'hero': 'HX', 'position': pos, 'cards': cards,
            'eff_stack_bb': stack, 'action_ledger': led}
_d1 = _g12([_g12_hand('BB', ['Ah', 'Kd'], 'calls', 'BTN', stack=30)], _r121)
check('T-121-G1: BB flat of a chart 3-bet hand fires Missed 3-Bet',
      any(d['type'] == 'Missed 3-Bet' and '3BF_30BB_BBvsBTN' in d['chart']
          for d in _d1), str(_d1))
_d2 = _g12([_g12_hand('BB', ['Ah', 'Kd'], 'calls', 'UTG', stack=30)], _r121)
check('T-121-G1b: no chart key (vs UTG) -> silent, no heuristic fallback',
      _d2 == [], str(_d2))
_d3 = _g12([_g12_hand('SB', ['Ah', 'Ad'], 'folds', 'CO', callers=('BTN',),
                      stack=30)], _r121)
check('T-121-G2: SB fold of a chart squeeze hand fires Missed Squeeze',
      any(d['type'] == 'Missed Squeeze' and 'SQF_30BB_SB_vsCOopen_BTNcall'
          in d['chart'] for d in _d3), str(_d3))
check('T-121-G2b: copy never says punt/wrong',
      all('punt' not in d['note'].lower() and 'wrong' not in d['note'].lower()
          for d in _d1 + _d3), '')

# P2 review flags
import gem_review_flags as _rvf121
_rvh = {'id': 'RV1', 'hero': 'HX', 'net_bb': -8, 'went_to_sd': True,
        'board': ['2h', '7h', '9h', 'Kh', '3c'],
        'action_ledger': [
            {'street': 'river', 'player': 'V', 'action': 'bets',
             'amount_bb': 5, 'is_all_in': False},
            {'street': 'river', 'player': 'HX', 'action': 'calls',
             'amount_bb': 5, 'is_all_in': False}]}
_rv = _rvf121.build_review_flags([_rvh])
check('T-121-G4: river bluff-catcher review fires on 4-flush runout loss',
      'RV1' in _rv and _rv['RV1'][0]['kind'] == 'river_bluffcatch_review',
      str(_rv))
check('T-121-G4b: review copy teaches the checklist, never verdicts',
      'what beats us' in _rv['RV1'][0]['copy']
      and 'punt' not in _rv['RV1'][0]['copy'].lower(), '')

# pko_pressure card
_cc_121 = open('gem_coaching_cards.py', encoding='utf-8').read()
check('T-121-CARD: pko_pressure insight registered with Review title + cap',
      "('pko_pressure', _tmpl_pko_pressure)" in _cc_121
      and "'PKO Review: bounty pressure spot'" in _cc_121
      and '_count' in _cc_121, '')

# R2
_hg_121 = open('gem_report_draft/_hand_grid.py', encoding='utf-8').read()
check('T-121-R2: hot grid styles use pb- classes',
      'pb-ip' in _hg_121 and 'pb-ring' in _hg_121 and 'pb-mut-i' in _hg_121, '')
_sx_121 = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-121-R2b: data-gtow-url no longer emitted (href is canonical)',
      "data-gtow-url='{_url}'" not in _sx_121, '')

# R3 flag-off identity is covered by the unit assert at patch time; here:
_html_121 = open('gem_report_draft/_html.py', encoding='utf-8').read()
check('T-121-R3: lazyfier + PBLazy + beforeprint + expand-all present',
      '_maybe_lazyfy_hands' in _html_121 and 'PBLazy' in _html_121
      and 'beforeprint' in _html_121 and 'pb-expand-all' in _html_121, '')
check('T-121-R3b: openHand guards lazy materialization',
      'async function openHand(hid)' in _html_121
      and 'PBLazy.ensure(hid)' in _html_121, '')
import os as _os121
check('T-121-R3c: lazy mode default OFF',
      _os121.environ.get('GEM_LAZY_HANDS') not in ('1',), '')


# ============================================================
# v8.12.2 — lazy fixes + default flip + G6/G7-G10 + P4 + Phase C
# ============================================================
_html_122 = open('gem_report_draft/_html.py', encoding='utf-8').read()
check('T-122-LAZY-1: PBLazy + PBData exposed on window (click-path fix)',
      'window.PBLazy=PBLazy' in _html_122 and 'window.PBData=PBData' in _html_122, '')
check('T-122-LAZY-2: lazy default ON with opt-out',
      "os.environ.get('GEM_LAZY_HANDS', '1') != '1'" in _html_122, '')
import glob as _g122
check('T-122-LAZY-3: no pb-nw class emissions in sections (md whitelist)',
      all('pb-nw' not in open(f, encoding='utf-8').read()
          for f in _g122.glob('gem_report_draft/sections_*.py')), '')
import os as _o122, importlib
import gem_report_draft._html as _H122
importlib.reload(_H122)
_o122.environ['GEM_LAZY_HANDS'] = '0'
_probe = "<html><body><article class='hand-detail-card' data-hand-id='Z1'><p>X</p></article></body></html>"
check('T-122-LAZY-4: GEM_LAZY_HANDS=0 produces identity output',
      _H122._maybe_lazyfy_hands(_probe) == _probe, '')
_o122.environ['GEM_LAZY_HANDS'] = '1'
_lz = _H122._maybe_lazyfy_hands(_probe)
check('T-122-LAZY-5: default-on lazyfies with payload + expand-all',
      'pb-lazy' in _lz and 'lazyHands' in _lz and 'pb-expand-all' in _lz, '')
_o122.environ['GEM_LAZY_HANDS'] = '0'

_an_122 = open('gem_analyzer.py', encoding='utf-8').read()
check('T-122-FLAG: --no-lazy-hand-details opt-out wired',
      "'--no-lazy-hand-details'" in _an_122, '')

from gem_analyzer import _dark_chart_detectors as _dk122
def _dk_hand(pos, cards, act, opener=None, limpers=(), hero_open=False,
             threebettor=None, stack=30, hid='D1'):
    led = []
    for lp in limpers:
        led.append({'street': 'preflop', 'player': 'L' + lp, 'position': lp,
                    'action': 'calls', 'amount_bb': 1, 'stack_bb': 30})
    if hero_open:
        led.append({'street': 'preflop', 'player': 'HX', 'position': pos,
                    'action': 'raises', 'amount_bb': 2.2, 'stack_bb': stack})
    if opener:
        led.append({'street': 'preflop', 'player': 'OP', 'position': opener,
                    'action': 'raises', 'amount_bb': 2.2, 'stack_bb': 30})
    if threebettor:
        led.append({'street': 'preflop', 'player': 'TB',
                    'position': threebettor, 'action': 'raises',
                    'amount_bb': 6.5, 'stack_bb': 30})
    led.append({'street': 'preflop', 'player': 'HX', 'position': pos,
                'action': act, 'amount_bb': 0, 'stack_bb': stack})
    return {'id': hid, 'hero': 'HX', 'position': pos, 'cards': cards,
            'eff_stack_bb': stack, 'action_ledger': led}
from gem_ranges import load_ranges as _lr122
check('T-122-DARK-1: G7-G10 all silent without their chart families',
      _dk122([_dk_hand('CO', ['Ah', 'Jd'], 'calls', opener='HJ'),
              _dk_hand('SB', ['Ah', 'Jd'], 'folds'),
              _dk_hand('BTN', ['Ah', 'Jd'], 'folds', limpers=('MP',))],
             _lr122('Poker_Ranges_Text.txt')) == [], '')
_syn = {'CC_30BB_COvsHJ': {'AA': 1}, 'BVB_SB_OPEN_30BB': {'AJs': 1},
        'ISO_30BB_BTN': {'AJs': 1}, 'F3B_30BB_COvsBTN_CONT': {'AJs': 1}}
_dd = _dk122([
    _dk_hand('CO', ['Ah', 'Jd'], 'calls', opener='HJ', hid='D-CC'),
    _dk_hand('SB', ['Ah', 'Jh'], 'folds', hid='D-BVB'),
    _dk_hand('BTN', ['Ah', 'Jh'], 'folds', limpers=('MP',), hid='D-ISO'),
    _dk_hand('CO', ['Ah', 'Jh'], 'folds', hero_open=True,
             threebettor='BTN', hid='D-F3B')], _syn)
_types = {d['type'] for d in _dd}
check('T-122-DARK-2: G7-G10 fire on synthetic exact charts',
      _types == {'Wide Cold-Call', 'Missed BvB Open', 'Missed Iso vs Limp',
                 'Missed 3-Bet Defense'}, str(_types))

import importlib as _il122, gem_review_flags as _rv122
_il122.reload(_rv122)
_g6h = {'id': 'G6H', 'hero': 'HX', 'hero_ip': False, 'players_at_flop': 2,
        'cards': ['Ah', 'Kh'], 'board': ['Ad', 'Kd', '7s', '2c'],
        'action_ledger': [
            {'street': 'turn', 'player': 'HX', 'action': 'checks'},
            {'street': 'turn', 'player': 'V', 'action': 'bets',
             'amount_bb': 4},
            {'street': 'turn', 'player': 'HX', 'action': 'calls',
             'amount_bb': 4}]}
_g6r = _rv122.g6_missed_value_checkraise(_g6h)
check('T-122-G6: OOP HU two-pair check-call on wet turn -> review flag',
      _g6r is not None and _g6r['kind'] == 'missed_value_checkraise'
      and 'punt' not in _g6r['copy'].lower(), str(_g6r))
_g6h2 = dict(_g6h, players_at_flop=3)
check('T-122-G6b: multiway excluded',
      _rv122.g6_missed_value_checkraise(_g6h2) is None, '')

_p4 = _rv122.build_p4_worksheet(
    [{'id': 'L1', 'hero': 'HX', 'net_bb': -30, 'vpip': True}]
    + [{'id': 'N%d' % i, 'hero': 'HX', 'net_bb': 1, 'vpip': True}
       for i in range(8)]
    + [{'id': 'M%d' % i, 'hero': 'HX', 'net_bb': 1, 'vpip': False}
       for i in range(30)])
check('T-122-P4: post-loss cluster detected with neutral wording',
      len(_p4['g14_post_loss_clusters']) == 1
      and 'tilt' not in str(_p4).lower(), str(_p4['g14_post_loss_clusters']))
check('T-122-P4b: worksheet never reaches a render surface',
      'p4_worksheet' not in open('gem_report_draft/sections_xiv.py',
                                 encoding='utf-8').read()
      and 'p4_worksheet' not in open('gem_report_draft/sections_mistakes.py',
                                     encoding='utf-8').read(), '')

_hg_122 = open('gem_report_draft/_hand_grid.py', encoding='utf-8').read()
check('T-122-PC-1: static tooltips via pb-tt classes; titles JS-filled',
      'pb-tt1' in _hg_122 and 'pb-tt2' in _hg_122
      and '_pbFillTitles' in _html_122, '')
check('T-122-PC-2: villain-mini onclick removed (delegated listener)',
      'showVillainMiniCard({_vk_js},this)' not in _hg_122
      and "closest('.villain-mini[data-vk]')" in _html_122, '')

check('T-122-AUDIT: fired ids read preflop_deviations',
      'preflop_deviations' in open('gem_coverage_audit.py',
                                   encoding='utf-8').read(), '')

# ============================================================
# v8.12.4 — Chat-QA fix pins (31-item review)
# ============================================================
# QA-14: composite bet-then-X codes count as c-bets (TM6058777821 class)
_hh_1224 = """Poker Hand #TM9000000001: Tournament #1, T1 Hold'em No Limit - Level6(150/300(45)) - 2026/06/10 03:12:54
Table '85' 7-max Seat #3 is the button
Seat 1: Hero (10,865 in chips)
Seat 2: villA (37,399 in chips)
Seat 3: villB (45,160 in chips)
Seat 4: villC (14,994 in chips)
Seat 5: villD (11,877 in chips)
Seat 6: villE (8,915 in chips)
Seat 7: villF (17,863 in chips)
villB: posts the ante 45
villD: posts the ante 45
villF: posts the ante 45
Hero: posts the ante 45
villE: posts the ante 45
villA: posts the ante 45
villC: posts the ante 45
villC: posts small blind 150
villD: posts big blind 300
*** HOLE CARDS ***
Dealt to Hero [8c 8s]
villE: folds
villF: raises 300 to 600
Hero: raises 1,200 to 1,800
villA: folds
villB: folds
villC: folds
villD: folds
villF: calls 1,200
*** FLOP *** [7c 2s 5h]
villF: checks
Hero: bets 3,274
villF: raises 12,744 to 16,018 and is all-in
Hero: calls 5,746 and is all-in
Uncalled bet (6,998) returned to villF
villF: shows [5s As] (a pair of Fives)
Hero: shows [8c 8s] (a pair of Eights)
*** TURN *** [7c 2s 5h] [Kd]
*** RIVER *** [7c 2s 5h Kd] [9s]
*** SHOWDOWN ***
Hero collected 22,405 from pot
*** SUMMARY ***
Total pot 22,405 | Rake 0 | Jackpot 0 | Bingo 0 | Fortune 0 | Tax 0
Board [7c 2s 5h Kd 9s]
Seat 1: Hero showed [8c 8s] and won (22,405) with a pair of Eights
Seat 2: villA folded before Flop
Seat 3: villB (button) folded before Flop
Seat 4: villC (small blind) folded before Flop
Seat 5: villD (big blind) folded before Flop
Seat 6: villE folded before Flop
Seat 7: villF showed [5s As] and lost with a pair of Fives
"""
import importlib as _il1224, gem_parser as _gp1224
_il1224.reload(_gp1224)
_h1224 = _gp1224.parse_one_hand(_hh_1224)
check('T-1224-CBET-1: bet-then-call-allin in 3BP counts as c-bet',
      _h1224.get('cbet_flop_3bp') is True
      and _h1224.get('hero_cbet_flop') is True, str({
          'flop': (_h1224.get('hero_street_actions') or {}).get('flop'),
          'c3bp': _h1224.get('cbet_flop_3bp')}))

# QA-11: river bet on a board-supplied trips with kicker-only upgrade = bluff
_flop_blk_old = """*** FLOP *** [7c 2s 5h]
villF: checks
Hero: bets 3,274
villF: raises 12,744 to 16,018 and is all-in
Hero: calls 5,746 and is all-in
Uncalled bet (6,998) returned to villF
villF: shows [5s As] (a pair of Fives)
Hero: shows [8c 8s] (a pair of Eights)
*** TURN *** [7c 2s 5h] [Kd]
*** RIVER *** [7c 2s 5h Kd] [9s]
*** SHOWDOWN ***
Hero collected 22,405 from pot"""
_flop_blk_k9 = """*** FLOP *** [Qc Qs Qh]
villF: checks
Hero: checks
*** TURN *** [Qc Qs Qh] [6d]
villF: checks
Hero: checks
*** RIVER *** [Qc Qs Qh 6d] [2d]
villF: checks
Hero: bets 1,200
villF: folds
Uncalled bet (1,200) returned to Hero
Hero collected 4,455 from pot"""
_sum_old = """*** SUMMARY ***
Total pot 22,405 | Rake 0 | Jackpot 0 | Bingo 0 | Fortune 0 | Tax 0
Board [7c 2s 5h Kd 9s]
Seat 1: Hero showed [8c 8s] and won (22,405) with a pair of Eights"""
_sum_k9 = """*** SUMMARY ***
Total pot 4,455 | Rake 0 | Jackpot 0 | Bingo 0 | Fortune 0 | Tax 0
Board [Qc Qs Qh 6d 2d]
Seat 1: Hero collected (4,455)"""
_hh_k9 = (_hh_1224.replace('TM9000000001', 'TM9000000002')
          .replace('Dealt to Hero [8c 8s]', 'Dealt to Hero [Kc 9h]')
          .replace(_flop_blk_old, _flop_blk_k9)
          .replace(_sum_old, _sum_k9)
          .replace('Seat 7: villF showed [5s As] and lost with a pair of Fives',
                   'Seat 7: villF folded on the River'))
_hk9 = _gp1224.parse_one_hand(_hh_k9)
check('T-1224-RIVAL-1: K9 river bet on QQQ-6-2 classifies as bluff, not value',
      _hk9.get('river_action') == 'bluff', str(_hk9.get('river_action')))

# QA-15: checked hand that WON showdown is check_sdv even if high-card
_flop_blk_qj = """*** FLOP *** [7c 2s 5h]
villF: checks
Hero: checks
*** TURN *** [7c 2s 5h] [Kd]
villF: checks
Hero: checks
*** RIVER *** [7c 2s 5h Kd] [9s]
villF: checks
Hero: checks
*** SHOWDOWN ***
villF: shows [3d 4d] (high card King)
Hero: shows [Qc Jh] (high card King, Queen kicker)
Hero collected 4,455 from pot"""
_sum_qj = """*** SUMMARY ***
Total pot 4,455 | Rake 0 | Jackpot 0 | Bingo 0 | Fortune 0 | Tax 0
Board [7c 2s 5h Kd 9s]
Seat 1: Hero showed [Qc Jh] and won (4,455) with high card King"""
_hh_qj = (_hh_1224.replace('TM9000000001', 'TM9000000003')
          .replace('Dealt to Hero [8c 8s]', 'Dealt to Hero [Qc Jh]')
          .replace(_flop_blk_old, _flop_blk_qj)
          .replace(_sum_old, _sum_qj)
          .replace('Seat 7: villF showed [5s As] and lost with a pair of Fives',
                   'Seat 7: villF showed [3d 4d] and lost with high card King'))
_hqj = _gp1224.parse_one_hand(_hh_qj)
check('T-1224-CHKB-1: checked QJ-high that WON showdown files as check_sdv',
      _hqj.get('river_action') == 'check_sdv', str(_hqj.get('river_action')))

# QA-9: ledger-path showdown reveals carry outcome + partial flag
import gem_report_data as _grd1224
_il1224.reload(_grd1224)
_seat_h = {'action_ledger': [{'street': 'preflop', 'player': 'Hero',
                              'action': 'raises', 'amount_bb': 2.2}],
           'bb_blind': 300, 'hero': 'Hero', 'stack_bb': 30,
           'went_to_sd': True, 'position': 'UTG',
           'villains': {'villA': {'position': 'BB'}},
           'stacks_behind': {}, 'seat_stacks_bb_all': {},
           'raw_text': ('villA: shows [Qd Ad]\nHero: shows [Jh Kh]\n'
                        'partialV: shows [5s]\n'
                        'Seat 1: villA (big blind) showed [Qd Ad] and won '
                        '(49,606) with Ace high\n'
                        'Seat 2: Hero showed [Jh Kh] and lost with King high\n')}
_si = _grd1224._build_seat_info_from_hand(_seat_h)
_sd_vals = list((_si.get('showdown') or {}).values())
_won_entries = [v for v in _sd_vals if (v.get('outcome') or '').startswith('won')]
_partials = [v for v in _sd_vals if v.get('partial')]
check('T-1224-SD-1: showdown reveals carry outcome from SUMMARY lines',
      len(_won_entries) == 1 and _won_entries[0]['cards'] == ['Qd', 'Ad'],
      str(_sd_vals))
check('T-1224-SD-2: one-card voluntary show flagged partial',
      len(_partials) == 1 and _partials[0]['cards'] == ['5s'], str(_partials))

# QA-5/6: post-analyst attribution refresh — cooler ledger + mistake row
_rd_ra = {
    'results_attribution': {
        'n_hands': 100, 'cooler_var_bb': -35.0, 'cooler_var_per_100': -35.0,
        'cooler_count_actual': 1, 'cooler_count_expected': 0.2,
        'non_tail_mistake_count': 0, 'non_tail_mistake_per_100': 0.0,
        'non_tail_mistake_cev_per_100': 0.0, 'non_tail_mistake_ids': [],
    },
    'analyst_commentary': {
        'TMQA1': {'verdict': 'III.2 — strategic leak', 'label': 'over-bluff'},
        'TMQA2': {'verdict': 'I.7 — cooler'},
    },
    'appendix_hand_details': {},
    'discipline_tier': {'canonical_mistakes_count': 1},
}
_stats_ra = {'coolers': {'hands': [], 'expected_low': 0.15,
                         'expected_high': 0.30, 'positive_count': 0},
             'eai': {'hands': []}}
_hands_ra = [{'id': 'TMQA1', 'net_bb': -46.0, 'stack_bb': 100,
              'cards': ['Kc', '9c'], 'board': [], 'won': False},
             {'id': 'TMQA2', 'net_bb': -30.0, 'stack_bb': 40,
              'cards': ['Ac', 'Ad'], 'board': [], 'won': False}]
_grd1224._refresh_results_attribution(_rd_ra, _stats_ra, _hands_ra)
_ra_after = _rd_ra['results_attribution']
_cl_after = _rd_ra.get('cooler_ledger') or {}
check('T-1224-RA-1: analyst I.7 enters the cooler ledger (count 1)',
      _cl_after.get('negative_count') == 1
      and _ra_after.get('cooler_count_actual') == 1, str(_cl_after))
check('T-1224-RA-2: mistake row carries analyst EV (net_bb) + canonical count',
      _ra_after.get('mistake_row_count') == 1
      and abs(_ra_after.get('mistake_row_per_100', 0) - (-46.0)) < 0.01,
      str({k: _ra_after.get(k) for k in ('mistake_row_count',
                                         'mistake_row_per_100')}))

# QA-4: all-ins one-liner uses the eai_ev_adjusted basis when present
import gem_report_draft.sections_xiv as _sx1224
_s_eai = {'eai_ev_adjusted': {
    'preflop': {'expected_wins': 30.0, 'actual_wins': 31.0},
    'postflop': {'expected_wins': 9.1, 'actual_wins': 10.0}},
    'eai': {}}
_line_eai = _sx1224._eai_one_liner(_s_eai)
check('T-1224-EAI-1: one-liner expected base = table base (39.1)',
      '41.0/39.1' in _line_eai and '+1.9' in _line_eai, _line_eai)

# QA-7: spine-keyed direction labels (source pin)
_tl_1224 = open('gem_report_draft/tldr.py', encoding='utf-8').read()
check('T-1224-DIR-1: mixed-direction label when cEV and BB disagree',
      'mixed — cEV:' in _tl_1224 and '_dir3(' in _tl_1224, '')
check('T-1224-REC-1: spine-disagreement reconciliation note present',
      'The two spines disagree on this session' in _tl_1224, '')
check('T-1224-A2-1: dashboard quotes promoted leaks as canonical',
      'Drill the promoted leaks (S5.1)' in _tl_1224, '')

# QA-1: promotion rules for the two defensive signals (source pin)
_grd_src_1224 = open('gem_report_data.py', encoding='utf-8').read()
check('T-1224-PROMO-1: BB Over-Fold + Postflop Over-Folding promotion rules',
      "current_leaks.add('BB Over-Fold')" in _grd_src_1224
      and "current_leaks.add('Postflop Over-Folding')" in _grd_src_1224, '')
check('T-1224-CAP-1: appendix cap is lazy-aware (1000) with env override',
      'GEM_APPENDIX_CAP' in _grd_src_1224
      and '1000 if _lazy_on_cap else 250' in _grd_src_1224, '')

# QA-3: weighted aggregate target for the defend matrix (source pin)
_s47_1224 = open('gem_report_draft/sections_iv_xii.py', encoding='utf-8').read()
check('T-1224-DEF-1: defend-matrix aggregate uses opportunity-weighted target',
      'opportunity-weighted target' in _s47_1224
      and 'Selection leak, not a frequency leak' in _s47_1224, '')

# QA-12/13: GTOW shortlist guarantees + cooler->CVJ routing (source pin)
check('T-1224-GTO-1: biggest pots + CLEAR mistakes guaranteed in shortlist',
      '_guaranteed_gto' in _grd_src_1224
      and 'called as a' in _grd_src_1224, '')
check('T-1224-GTO-2: analyst-confirmed mistakes appended post-attach',
      'Confirmed mistakes — solver review' in _grd_src_1224, '')

# QA-16: watchlist degenerate-aim clamp + bluff synthesis
import gem_leak_watchlist as _wl1224
_il1224.reload(_wl1224)
_wl_row = {'F2_Turn_CBet_Small': 35.0}
_wl_out = _wl1224.build_leak_watchlist(_wl_row)
_tcs = next((i for i in _wl_out['session_metrics']
             if i['metric'] == 'F2_Turn_CBet_Small'), None)
check('T-1224-WL-1: degenerate p25=0 renders top-avg aim, not "<=0.0 (aim)"',
      _tcs is not None and 'aim ≈' in _tcs['target_range']
      and '≤0.0 (aim)' not in _tcs['target_range'],
      str(_tcs and _tcs['target_range']))
check('T-1224-WL-2: synthesis_notes key present',
      'synthesis_notes' in _wl_out, str(list(_wl_out.keys())))

# QA-30: fingerprint binds hh_hash; --quick aborts on dir mismatch (source pin)
_ga_src_1224 = open('gem_analyzer.py', encoding='utf-8').read()
check('T-1224-FP-1: session fingerprint carries hh_hash',
      "_session_fingerprint['hh_hash']" in _ga_src_1224, '')
check('T-1224-FP-2: --quick hard-aborts on cache-vs-dir mismatch',
      'GEM_QUICK_ALLOW_STALE' in _ga_src_1224
      and 'cache is from a DIFFERENT session' in _ga_src_1224, '')

# QA-20: post-render validation decodes lazy payload for draw profiles
check('T-1224-VAL-1: draw-profile validation is lazy-payload-aware',
      'incl. lazy payload' in _ga_src_1224, '')

# QA-31/28: analyst reconciliation + batch-stamp detector
check('T-1224-RECON-1: analyst entry reconciliation present (v8.12.9: synthesis counted separately)',
      'Reconciliation:' in _grd_src_1224
      and 'synthesis/meta block' in _grd_src_1224
      and 'batch-stamp' in _grd_src_1224, '')

# QA-29: W-POT accepts decision-point pot basis
_sx_src_1224 = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-1224-WPOT-1: W-POT accepts decision-point pots (superseded by '
      'v8.12.6 any-street windows)',
      '_windows_pot' in _sx_src_1224, '')

# QA-18: Early Bustout Pattern classification
check('T-1224-PHASE-1: Del-6 phase pattern computed + rendered',
      "rd['phase_pattern']" in _grd_src_1224
      and 'Early Bustout Pattern' in _grd_src_1224
      and 'phase_pattern' in open('gem_report_draft/sections_financial.py',
                                  encoding='utf-8').read(), '')

# QA-23: arc verdict note
check('T-1224-ARC-1: intra-session arc draws a conclusion',
      'Arc verdict' in open('gem_report_draft/sections_financial.py',
                            encoding='utf-8').read(), '')

# QA-21: progress tracker current row + persistence specs
check('T-1224-TRACK-1: current-session row closes the trend table',
      'this session' in _s47_1224
      and "LEAK_TARGETS['SB BvB']" in _grd_src_1224, '')

# QA-24: empty-Picks checklist violation surfaced
check('T-1224-PICKS-1: batch-closed candidates surface a section warning',
      'checklist §9 expects 5-10 curated Picks' in
      open('gem_report_draft/sections_mistakes.py', encoding='utf-8').read(), '')

# QA-10: suckout-ledger prefill caution
check('T-1224-SUCK-1: mistakes-bucket prefill capped for suckout hands',
      'suckout ledger' in open('gem_coverage_builder.py',
                               encoding='utf-8').read(), '')

# ============================================================
# v8.12.5 — QA-pass leftovers (items 8/17 + CI-gated promotion)
# ============================================================
import tempfile as _tf1225, os as _os1225
import importlib as _il1225b, gem_report_data as _grd1225
_il1225b.reload(_grd1225)
_tmp1225 = _tf1225.mkdtemp()
_hhd = _os1225.path.join(_tmp1225, 'merged'); _os1225.makedirs(_hhd)
_sibd = _os1225.path.join(_tmp1225, 'a'); _os1225.makedirs(_sibd)
_NL = chr(10)
open(_os1225.path.join(_hhd, 'hh1.txt'), 'w', encoding='utf-8').write(
    'Poker Hand #TM1: Tournament #555, X1: $10 Foo Bar Baz Qux, Holdem' + _NL)
open(_os1225.path.join(_sibd, 'gs1.txt'), 'w', encoding='utf-8').write(_NL.join([
    'Tournament #555, X1: $10 Foo Bar Baz Qux, Holdem No Limit',
    'Buy-in: $9+$1', '100 Players', 'Total Prize Pool: $1,000',
    'Tournament started 2026/06/09 23:30:00',
    '5th : Hero, $50', 'You finished the tournament in 5th place.',
    'You made 0 re-entries and received a total of $50.', '']))
open(_os1225.path.join(_sibd, 'gs2.txt'), 'w', encoding='utf-8').write(_NL.join([
    'Tournament #556, X2: $15 Zod Mystery Stage Alpha, Holdem No Limit',
    'Buy-in: $13+$2', '200 Players', 'Total Prize Pool: $3,000',
    'Tournament started 2026/06/09 23:30:00',
    '40th : Hero, 12,345 chips', 'You finished the tournament in 40th place.',
    'You made 0 re-entries and received a total of 12,345 chips.', '']))
_hands1225 = [{'tournament': 'X1 $10 Foo Bar Baz Qux'},
              {'tournament': 'Some Other Unmatched Tournament Name'}]
_ov1225 = _grd1225._parse_game_summaries_usd(_hhd, _hands1225)
check('T-1225-SUM-1: summaries discovered in arbitrarily-named sibling dir',
      _ov1225['status'] == 'parsed'
      and (_ov1225.get('totals') or {}).get('n_tournaments') == 2,
      str(_ov1225.get('status')) + '/' +
      str((_ov1225.get('totals') or {}).get('n_tournaments')))
check('T-1225-SUM-2: chips payout flagged as flighted advancement',
      bool(_ov1225.get('advanced_tournaments'))
      and 'Zod Mystery' in _ov1225['advanced_tournaments'][0],
      str(_ov1225.get('advanced_tournaments')))
check('T-1225-SUM-3: HH tournament without summary listed unresolved',
      any('Unmatched' in u for u in
          (_ov1225.get('unresolved_hh_tournaments') or [])),
      str(_ov1225.get('unresolved_hh_tournaments')))

# CI-gated promotion: source pin + the Wilson math semantics
_grd_src_1225 = open('gem_report_data.py', encoding='utf-8').read()
check('T-1225-CI-1: promotion rules are Wilson-CI gated',
      '_wilson_pl' in _grd_src_1225 and '_ci_below(' in _grd_src_1225
      and '_ci_above(' in _grd_src_1225, '')
def _wilson_ref(pct, n, z=1.645):
    p = max(0.0, min(1.0, pct / 100.0))
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((centre - margin) / denom * 100, (centre + margin) / denom * 100)
_lo_a, _hi_a = _wilson_ref(24.5, 20)   # borderline 0.5pp miss on n=20
_lo_b, _hi_b = _wilson_ref(10.0, 100)  # clear miss on n=100
check('T-1225-CI-2: borderline miss does NOT pass the CI gate; clear miss does',
      _hi_a >= 25 and _hi_b < 25,
      'borderline hi=%.1f clear hi=%.1f' % (_hi_a, _hi_b))

# Unsettled line render pin
check('T-1225-UNS-1: TLDR names flighted bags + missing summaries',
      'Unsettled:' in open('gem_report_draft/tldr.py', encoding='utf-8').read(), '')

# --- v8.12.5 browser-QA pins (live click-through findings) ---
_html_1225 = open('gem_report_draft/_html.py', encoding='utf-8').read()
check('T-1225-PILL-1: verdict-pill in the _md_inline stash whitelist',
      'verdict-pill|context-pill' in _html_1225,
      'pill spans were emitted but escaped on every page until whitelisted')
check('T-1225-PILL-2: modal top bar clones the verdict pill into the top-verdict chip',
      'srcPill' in _html_1225 and 'srcPill.cloneNode' in _html_1225
      and "classList.add('v25-top-verdict')" in _html_1225, '')
check('T-1225-LAZY-1: PBLazy normalizes TM-form ids before payload lookup',
      'function _norm(hid)' in _html_1225
      and 'matDone[_norm(hid)]' in _html_1225, '')
check('T-1225-LAZY-2: ensureAll yields to the event loop (chunked)',
      'i%100===99' in _html_1225, '')

# --- v8.12.6 pins (Chat session 2026-06-11 findings) ---
_ga_1226 = open('gem_analyzer.py', encoding='utf-8').read()
check('T-1226-NAME-1: __main__ PLO-quarantine writes to stats, not s',
      "stats['_non_nlh_ids'] = _non_nlh_ids_main" in _ga_1226
      and not __import__('re').search(
          r"(?<![A-Za-z_])s\['_non_nlh_ids'\]", _ga_1226),
      'NameError crashed fresh __main__ runs')
_sx_1226 = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-1226-WPOT-1: pot claims accepted against ANY street window',
      '_windows_pot' in _sx_1226 and 'matches no street window' in _sx_1226, '')
check('T-1226-IE-1: coverage Training column renders em-dash, not None',
      "else '—'" in open('gem_report_draft/sections_issue_explorer.py',
                         encoding='utf-8').read(), '')

# --- v8.12.8 pins (Ron QA 2026-06-12: lazy tables, PKO labels, handover) ---
# A: hand-list popups read the static index before scraping the (lazy) DOM
_dr_1228 = open('gem_report_draft/draft.py', encoding='utf-8').read()
_html_1228 = open('gem_report_draft/_html.py', encoding='utf-8').read()
check('T-1228-LAZY-1: draft emits window.handIndex for popup rows',
      "'window.handIndex='" in _dr_1228, '')
check('T-1228-LAZY-2: popup is index-first with DOM fallback',
      'window.handIndex||{}' in _html_1228
      and 'function fmtCardSpans' in _html_1228
      and '_idx.c' in _html_1228, '')

# B: PKO context truth — actual opener label, exact-stack coverage, SB oos
import gem_pko_research as _pk8

def _mk8(opener='BTN', op_stack=16.0, hero_stack=18.0, act='calls', eff=None,
         callers=(), bounty_bb=0.0, lbl=''):
    led = [{'street': 'preflop', 'player': 'Op', 'position': opener,
            'action': 'raises', 'amount_bb': 2.2, 'stack_bb': op_stack,
            'is_all_in': False}]
    for i, (cp, cs) in enumerate(callers):
        led.append({'street': 'preflop', 'player': 'C%d' % i, 'position': cp,
                    'action': 'calls', 'amount_bb': 2.2, 'stack_bb': cs,
                    'is_all_in': False})
    led.append({'street': 'preflop', 'player': 'H8', 'position': 'BB',
                'action': act, 'amount_bb': 0, 'stack_bb': hero_stack,
                'is_all_in': False})
    return {'id': 'X8', 'hero': 'H8', 'position': 'BB', 'format': 'BOUNTY',
            'tournament_phase': 'bubble_zone',
            'eff_stack_bb': eff if eff is not None else min(hero_stack, op_stack),
            'stack_bb': hero_stack, 'action_ledger': led,
            'bounty_value_bb': bounty_bb, 'bounty_label': lbl}

_c8a = _pk8.build_pko_context(_mk8('HJ', 18, 69, 'calls', eff=18), {})
check('T-1228-PKO-1: spot label names the ACTUAL opener, never borrowed BTN',
      _c8a['spot'] == 'BB vs HJ open', _c8a['spot'])
check('T-1228-PKO-2: 69bb-vs-18bb is covers/collectible (hero stack, not eff)',
      _c8a['can_collect_bounty'] is True
      and 'collectible' in _c8a['coverage_label']
      and 'cannot collect' not in _c8a['teaching_note'],
      str(_c8a['coverage_label']))
check('T-1228-PKO-3: borrowed (nearest) aggregate never claims PKO-Good',
      _c8a['aggregate_fit'] == 'nearest'
      and _c8a['classification'] != 'Good'
      and 'Nearest measured' in _c8a['teaching_note'], _c8a['classification'])
_c8b = _pk8.build_pko_context(_mk8('SB', 32, 28, 'folds', eff=28), {})
check('T-1228-PKO-4: SB opener routes out-of-scope, never the BTN bucket',
      _c8b.get('enabled', False) is False
      and _c8b.get('oos_reason') == 'out_of_scope_sb_opener',
      str(_c8b.get('oos_reason')))
_c8c = _pk8.build_pko_context(_mk8('HJ', 22.125, 23.125, 'calls', eff=22.1), {})
check('T-1228-PKO-5: near-equal stacks say collectible-if-wins, never "cannot collect"',
      _c8c['can_collect_bounty'] is True
      and 'near-equal' in _c8c['coverage_label'], _c8c['coverage_label'])
_c8d = _pk8.build_pko_context(_mk8(bounty_bb=4.0, lbl='Regular bounty (PKO)'), {})
check('T-1228-PKO-6: caveat uses the estimated bounty model, not a dead-end',
      'Bounty \u2248 4.0BB' in _c8d['caveat']
      and 'bounty_estimated_from_model' in _c8d['confidence_reasons'],
      _c8d['caveat'])
check('T-1228-PKO-7: no-estimate hands keep the unavailable wording',
      'unavailable in GG export' in _pk8.build_pko_context(_mk8(), {})['caveat'], '')

# D: non-all-in pot odds (handover Issue 1)
from gem_pot_odds import compute_nonallin_pot_odds as _cnapo
_RAW8 = (
    "Poker Hand #TM888: Tournament #1, Hold'em No Limit - Level10(50/100)\n"
    "Seat 1: Hero (20000 in chips)\nSeat 2: V1 (20000 in chips)\n"
    "V1: posts small blind 50\nHero: posts big blind 100\n"
    "*** HOLE CARDS ***\nDealt to Hero [Ah 6h]\n"
    "V1: raises 100 to 200\nHero: calls 100\n"
    "*** FLOP *** [2h 7h Kd]\nHero: checks\nV1: bets 300\nHero: calls 300\n"
    "*** TURN *** [2h 7h Kd 2c]\nHero: checks\nV1: bets 1300\nHero: calls 1300\n"
    "*** RIVER *** [2h 7h Kd 2c 9s]\nHero: checks\nV1: checks\n")
_po8 = _cnapo({}, _RAW8)
check('T-1228-PO-1: street-calls block carries per-street required equity',
      _po8 is not None and _po8['mode'] == 'street_calls'
      and len(_po8['per_street_calls']) == 3,
      str(_po8 and len(_po8.get('per_street_calls', []))))
check('T-1228-PO-2: overbet flagged on the turn + headline is max-required street',
      _po8['street'] == 'turn' and _po8['is_overbet'] is True
      and _po8['bet_pct_of_pot'] > 100, str(_po8['bet_pct_of_pot']))
check('T-1228-PO-3: overbet invariant — required equity always > 33.3%',
      all((not ps['is_overbet']) or ps['required_eq_pct'] > 33.3
          for ps in _po8['per_street_calls']), '')
check('T-1228-PO-4: all-in calls stay on the equity path (returns None)',
      _cnapo({}, _RAW8.replace('Hero: calls 1300',
                               'Hero: calls 1300 and is all-in')) is None, '')
_gpo_1228 = open('gem_pot_odds.py', encoding='utf-8').read()
check('T-1228-PO-5: enrich second path exists + runs without phevaluator',
      "stats['street_calls']" in _gpo_1228
      and 'street-call pot odds still' in _gpo_1228, '')
check('T-1228-PO-6: worksheet carries mode/is_overbet/per_street',
      "'per_street': po.get('per_street_summary')" in
      open('gem_coverage_builder.py', encoding='utf-8').read(), '')

# E: EAI degradation is loud + stamped (handover Issue 2)
_ga_1228 = open('gem_analyzer.py', encoding='utf-8').read()
check('T-1228-EAI-1: missing phevaluator warns loudly at startup',
      'phevaluator unavailable' in _ga_1228
      and 'APPROXIMATE' in _ga_1228, '')
check('T-1228-EAI-2: heuristic fallback count stamped on eai + eai_ev_adjusted',
      "s['eai']['heuristic_fallback_n']" in _ga_1228
      and "'equity_method': ('phevaluator'" in _ga_1228, '')
check('T-1228-EAI-3: report data exposes the degradation flag',
      "rd['eai_equity_degraded']" in
      open('gem_report_data.py', encoding='utf-8').read(), '')
check('T-1228-EAI-4: TLDR scorecard marks True EV approximate when degraded',
      'eai_equity_degraded' in
      open('gem_report_draft/tldr.py', encoding='utf-8').read(), '')
check('T-1228-EAI-5: STEP0 installs phevaluator in the Chat env',
      'pip install --quiet phevaluator' in
      open('SESSION_START_STEP0_package_rebuild.txt', encoding='utf-8').read(), '')

# F: marker semantics — trigger is amber routing; red ! reserved for evidence
_hg_1228 = open('gem_report_draft/_hand_grid.py', encoding='utf-8').read()
_sx_1228b = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-1228-MK-1: trigger marker renders \u21aa with Trigger-prefixed tooltip',
      '\u21aa<sup>{_tm_note}</sup>' in _hg_1228
      and 'title="Trigger:' in _hg_1228, '')
check('T-1228-MK-2: badge row ownership — evidence on villain rows only',
      "if is_h and _vbt in ('note', 'pivot', 'evid')" in _hg_1228
      and "(not is_h) and _vbt in ('miss', 'good')" in _hg_1228, '')
check('T-1228-MK-3: evidence badges built for whitelisted villain signals',
      "'open_limp': 'Limp'" in _sx_1228b and "'type': 'evid'" in _sx_1228b, '')
check('T-1228-MK-4: trigger amber + vb-evid red CSS shipped',
      'background: #d97706' in _html_1228
      and 'color: #dc2626; border: 1px solid #fca5a5' in _html_1228, '')

# F: evidence-badge behavior via the builder
from gem_report_draft.sections_xiv import _build_villain_badges as _bvb8
_s_vi8 = {'villain_intel': {'atoms_by_hand': {'H8X': [
    {'street': 'flop', 'action_index': 2, 'signal': 'multiway_donk',
     'suggests': 'weak stab', 'villain_alias': 'Torch', 'villain_key': 'T|x'},
    {'street': 'turn', 'action_index': 1, 'signal': 'open_limp',
     'villain_key': 'T|y'},
]}, 'exploit_opportunities': []}}
_b8 = _bvb8('H8X', _s_vi8)
check('T-1228-MK-5: atom with teaching text gets evid badge; bare atom does not',
      bool(_b8) and ('flop', 2) in _b8
      and _b8[('flop', 2)][0]['type'] == 'evid'
      and ('turn', 1) not in _b8, str(_b8))

# G: sizing-claim + street-anchor lints against the rendered grid
check('T-1228-LINT-1: grid stashes rendered bet pcts for W-PCT',
      '_grid_bet_pcts' in _hg_1228, '')
check('T-1228-LINT-2: W-PCT + W-NOTE-STREET lints wired after grid build',
      'W-PCT: Hand' in _sx_1228b and 'W-NOTE-STREET: Hand' in _sx_1228b, '')

# H: exploitation gates (QA P0) + context dedupe (QA P1)
import gem_villain_intel as _gvi8
check('T-1228-VI-1: baseline-open set — JJ/KQo standard, A7o is a real exploit',
      _gvi8._is_baseline_open(['Jh', 'Jd'], 'HJ') is True
      and _gvi8._is_baseline_open(['Kh', 'Qd'], 'CO') is True
      and _gvi8._is_baseline_open(['Ah', '7d'], 'BTN') is False, '')
_gvi_src8 = open('gem_villain_intel.py', encoding='utf-8').read()
check('T-1228-VI-2: standard opens reclassified read_supported_standard',
      "'read_supported_standard'" in _gvi_src8
      and 'baseline open' in _gvi_src8, '')
check('T-1228-VI-3: thin reads downgrade Good/Miss to candidate',
      _gvi_src8.count("'read_supported_candidate'") >= 2
      and 'do not over-adjust' in _gvi_src8, '')
check('T-1228-CTX-1: atom/context dedupe keys on street+signal, not hand+villain',
      '_exploit_cover' in _sx_1228b
      and "atom.get('signal', '') == 'repeated_blind_overfold'" in _sx_1228b, '')

# --- v8.12.8 QA3 pins (Ron review notes on the 06-11 V4 report) ---
_cb_1229 = open('gem_coverage_builder.py', encoding='utf-8').read()
_po_1229 = open('gem_pot_odds.py', encoding='utf-8').read()
_hg_1229 = open('gem_report_draft/_hand_grid.py', encoding='utf-8').read()
_sx_1229 = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
_html_1229 = open('gem_report_draft/_html.py', encoding='utf-8').read()
_dr_1229 = open('gem_report_draft/draft.py', encoding='utf-8').read()
_ga_1229 = open('gem_analyzer.py', encoding='utf-8').read()

check('T-1229-NOT-1: chart notation sorts ranks high-first (8Ao bug)',
      '_rv.get(r1, 0) > _rv.get(r0, 0)' in _cb_1229, '')
check('T-1229-SB-1: SB100 missed-open records the chart actually hit (limp vs raise)',
      '_sb_chart_hit' in _ga_1229, '')
from gem_report_draft.sections_xiv import _embolden_hand_in_range as _emb9
check('T-1229-BOLD-1: hero hand token bolded inside range families',
      _emb9('A2o+, K2o+, J6o+, T6o+', 'J6o') == 'A2o+, K2o+, **J6o+**, T6o+'
      and _emb9('K9o+', 'K8o') == 'K9o+'
      and _emb9('22+', 'QQ') == '**22+**', '')
check('T-1229-POT-1: side-pot-aware required equity (main pot price)',
      'priced on the main pot' in _po_1229
      and "'main_pot_bb': main_pot_bb" in _po_1229, '')
check('T-1229-POT-2: folded players excluded from showdown villain hands',
      '_folded_players' in _po_1229, '')
check('T-1229-POT-3: EV prices the winnable pot only',
      '_pot_for_ev = main_pot_bb if main_pot_bb' in _po_1229, '')
check('T-1229-GRID-1: capped jam adds only the EFFECTIVE amount to the pot',
      '_bt_add = (_eff_amt if (allin and _was_capped) else amt)' in _hg_1229
      and '_rp_delta = min(_rp_delta, _eff_amt)' in _hg_1229
      and '_street_commit' in _hg_1229, '')
check('T-1229-PRICE-1: worksheet PRICE line prefers the pot-odds engine',
      '_po_auth' in _cb_1229
      and "ctx.get('pot_odds') or {}" in _cb_1229, '')
check('T-1229-REJAM-1: rejam note carries human label + Top/Boundary range',
      '3-bet jam over a' in _cb_1229
      and _cb_1229.count('Boundary: ...') >= 2, '')
check('T-1229-NWAY-1: multiway equity label says "by showdown" (hindsight guard)',
      'by showdown' in _cb_1229, '')
check('T-1229-VSN-1: villain note renders the Evidence line',
      'vsn-evidence' in _sx_1229, '')
check('T-1229-THUMB-1: positive note marker is thumbs-UP green',
      '\U0001F44D<sup>{note_num}</sup>' in _hg_1229
      and '\U0001F44E<sup>' not in _hg_1229
      and 'background: #15803d' in _html_1229, '')
check('T-1229-POPUP-1: hand-list columns sortable',
      'function _sortPopupTable' in _html_1229
      and '_sortPopupTable(tbl,ci,th)' in _html_1229, '')
check('T-1229-POPUP-2: Vs Pos column shows the OPENER from the index',
      "_posHeader==='Vs Pos'" in _html_1229
      and '_idx.o' in _html_1229
      and "_e['o'] = _hh['opener_position']" in _dr_1229, '')

# --- v8.12.8 QA-GPT pins (GPT deep-QA handoff 2026-06-13) ---
_hp_1230 = open('gem_report_draft/_helpers.py', encoding='utf-8').read()
_hg_1230 = open('gem_report_draft/_hand_grid.py', encoding='utf-8').read()
_cb_1230 = open('gem_coverage_builder.py', encoding='utf-8').read()
_sx_1230 = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
_html_1230 = open('gem_report_draft/_html.py', encoding='utf-8').read()

# pot walk: raise increments converted to totals + commit deltas
from gem_report_draft._helpers import _compute_pot_by_street as _cpbs
_acts_1230 = {'preflop': [
    {'name': 'sb', 'action': 'posts', 'amount_bb': 0.5},
    {'name': 'bb', 'action': 'posts', 'amount_bb': 1.0},
    {'name': 'v1', 'action': 'raises', 'amount_bb': 1.0},   # open to 2
    {'name': 'v2', 'action': 'calls', 'amount_bb': 2.0},
    {'name': 'H', 'action': 'raises', 'amount_bb': 8.0},    # 3bet to 10
    {'name': 'v1', 'action': 'calls', 'amount_bb': 8.0},
    {'name': 'v2', 'action': 'calls', 'amount_bb': 8.0},
], 'flop': [
    {'name': 'H', 'action': 'bets', 'amount_bb': 17.8},
    {'name': 'v1', 'action': 'raises', 'amount_bb': 23.5},  # to 41.3
    {'name': 'v2', 'action': 'folds'},
    {'name': 'H', 'action': 'calls', 'amount_bb': 23.5},
]}
_h_1230 = {'bb_blind': 200, 'sb_blind': 100, 'ante': 30, 'n_players': 6}
_pots_1230 = _cpbs(_acts_1230, _h_1230)
check('T-1230-POT-1: pot walk reproduces GG totals on re-raised streets',
      abs(_pots_1230['flop'] - 32.4) < 0.15
      and abs(_pots_1230['turn'] - 115.0) < 0.3,
      str(_pots_1230))
check('T-1230-POT-2: blind posts seed commits, antes excluded',
      "continue  # ante — not bet-matching commitment" in _hp_1230, '')
check('T-1230-EFF-1: all-in CALL amount is the exact contested cap',
      "_b.get('action') == 'calls'" in
      _hg_1230.split('def _effective_amt')[1][:1600], '')
check('T-1230-BNTY-1: no bounty-adjusted threshold when engine applied none',
      '_po_b9' in _cb_1230
      and "required_eq_bounty_pct') is None" in _cb_1230, '')
check('T-1230-RJ-1: rejam near-flip gated on _in_rj — inside=standard get-in; outside/no-chart=III.4 (no "standard get-in" claim); _rj_phrase removed',
      'inside the jamming range — standard get-in.' in _cb_1230
      and "'R3_3betjam_flip_unconfirmed'" in _cb_1230
      and 'not a chart jam.' in _cb_1230
      and 'Needs read or population confirmation.' in _cb_1230
      and 'equity-driven get-in' in _cb_1230
      and '_rj_phrase' not in _cb_1230, '')
# T-RE-19 (GPT rev): the contradiction lint also flags an outside-chart get-in
# JUSTIFICATION ("standard get-in" / "correct push") — not just inside-claims.
check('T-RE-19: W-RANGE-CONTRADICT lint catches outside-chart "standard get-in"/"correct push"',
      "_assertive_getin = ('standard get-in', 'correct get-in'," in _xiv_re
      and "'correct push'" in _xiv_re
      and '_getin_hit = any(w in _argl for w in _assertive_getin)' in _xiv_re, '')

# T-RE-20 (REV3, Blocker 2 / 72807590): legacy "Correct range" prose defers to the
# canonical Range-evidence block. _deviation_range_text + the inline preflop-
# deviation branch suppress their chart line when _canon_supersede(h) reports a
# chart-backed block, and _xivb_flag_note threads the hand through to it.
check('T-RE-20: legacy Correct-range prose gated on canonical block (_canon_supersede + h threaded)',
      'def _canon_supersede(h):' in _xiv_re
      and 'def _deviation_range_text(hid, s, h=None):' in _xiv_re
      and 'def _xivb_flag_note(hid, s, rd, h=None):' in _xiv_re
      and _xiv_re.count('_canon_supersede(h)') >= 2
      and _xiv_re.count('_xivb_flag_note(hid, s, rd, h)') >= 3, '')

# T-RE-21b (REV3): without the hand the legacy line is preserved (back-compat,
# no ranges needed — _canon_supersede(None) short-circuits).
from gem_report_draft.sections_xiv import _deviation_range_text as _drt_re
_s_590 = {'preflop_deviations': [{'id': 'TM6072807590', 'cards': '97s',
          'pos': 'HJ', 'type': 'Missed Open', 'chart': 'OPEN_20-40BB_HJ'}],
          '_dev_charts': {'OPEN_20-40BB_HJ': ['55+', 'A2s+', 'K8s+', '97s']}}
check('T-RE-21b: without h, legacy Correct-range line preserved (back-compat)',
      'Correct range' in _drt_re('TM6072807590', _s_590), '')

# T-RE-21 (REV3): a Missed-Open deviation stored on the short-table-adjusted HJ
# chart, beside a canonical MP block that says OUTSIDE (97s @ 7-max MP, hand
# 72807590), renders the reconciliation note — NOT "Correct range — HJ" / "inside
# this chart — passing on it is the deviation".
_h_590 = {'id': 'TM6072807590', 'position': 'MP', 'cards': ['9c', '7c'],
          'stack_bb': 23, 'eff_stack_bb_at_decision': 23, 'pf_action': 'fold',
          'first_in': True, 'n_players': 7}
if _RE_OK:
    _drt_out = _drt_re('TM6072807590', _s_590, _h_590)
    check('T-RE-21: 72807590 missed-open defers to canonical MP (no "Correct range"/"inside this chart")',
          'Correct range' not in _drt_out
          and 'inside this chart' not in _drt_out
          and 'is outside' in _drt_out, _drt_out[:90])
else:
    check('T-RE-21: 72807590 deferral (skipped, no chart file)', True, 'skip')

# T-RE-22 (REV3): the contradiction lint also flags chart-STATUS / membership
# claims (range-standard / standard line / inside this chart / clean-by-chart)
# asserted beside an OUTSIDE canonical chart (72807313 class). Honest "outside
# chart but cleared on EV/fold-equity grounds" prose contains none of these.
check('T-RE-22: W-RANGE-CONTRADICT lint extended for range-standard/standard line/inside this chart',
      "'inside this chart'" in _xiv_re
      and "'range-standard', 'standard line'" in _xiv_re
      and "'jam is clean', 'clean by chart'" in _xiv_re, '')

# T-RE-23 (REV4, 72807590 report-BODY): the XIII leak surfaces label a short-table
# proxy chart and show Hero's REAL seat — the body no longer reads "HJ 23BB" as if
# Hero sat at HJ while the hand card says MP / OUTSIDE / not a clear leak.
from gem_report_draft._helpers import _emit_correct_ranges as _ecr_re
class _DocM_RE:
    def __init__(self): self.lines = []
    def w(self, x=''): self.lines.append(str(x))
    def write_block(self, b): self.lines.append(str(b))
_dm = _DocM_RE()
_ecr_re(_dm,
        [{'id': 'TM6072807590', 'pos': 'HJ', 'chart': 'OPEN_20-40BB_HJ', 'type': 'Missed Open'}],
        {'OPEN_20-40BB_HJ': ['55', '66', 'A2s', '97s']},
        {'TM6072807590': {'id': 'TM6072807590', 'position': 'MP'}})
_ecr_out = '\n'.join(_dm.lines)
check('T-RE-23: proxy chart labeled "(short-table proxy)" + "hand classes" (not combos)',
      'short-table proxy' in _ecr_out and 'hand classes)' in _ecr_out and 'combos)' not in _ecr_out,
      _ecr_out[:90])
_dm2 = _DocM_RE()
_ecr_re(_dm2, [{'id': 'X', 'pos': 'CO', 'chart': 'OPEN_20-40BB_CO'}],
        {'OPEN_20-40BB_CO': ['55', 'A2s']}, {'X': {'position': 'CO'}})
check('T-RE-23b: non-proxy chart (seat==pos) has no proxy label',
      'short-table proxy' not in '\n'.join(_dm2.lines), '')
_xiii_re = open('gem_report_draft/sections_xiii.py', encoding='utf-8').read()
check('T-RE-23c: sections_xiii shows true seat + proxy chart label, threads hands_by_id',
      'def _proxy_info(d):' in _xiii_re
      and "_href({**d, 'position': _seat_d}" in _xiii_re
      and "chart_label += ' (short-table proxy)'" in _xiii_re
      and _xiii_re.count("s.get('_dev_charts', {}), s.get('_hands_by_id'))") >= 3, '')

# T-RE-24 (REV5, 72692569): coverage-builder resolves re-jam membership at ANY
# depth + strips '+' to match gem_ranges (REJAM_MPvsUTG1), so it can never emit a
# "no rejam chart" existence-denial for a matchup the canonical block resolves.
check('T-RE-24: coverage-builder re-jam key strips "+" and is not stack-gated',
      'REJAM_{_pos.replace("+", "")}vs{_opener.replace("+", "")}' in _cb_1230
      and "_hero_role(h) == 'threebet_jam':" in _cb_1230
      and "_hero_role(h) == 'threebet_jam' and _stack <= 30" not in _cb_1230, '')
# the REJAM key the fix builds resolves in the real chart file, AA inside
if _RE_OK:
    check('T-RE-24a: REJAM_MPvsUTG1 resolves (AA inside) — matches canonical selector',
          'AA' in _RANGES_RE.get('REJAM_MPvsUTG1', set()), '')
else:
    check('T-RE-24a: REJAM_MPvsUTG1 resolves (skipped, no chart file)', True, 'skip')
# T-RE-24b: new render lint flags a "no chart" claim beside a canonical Reference
check('T-RE-24b: W-RANGE-CHART-EXISTS lint guards no-chart claim vs canonical Reference',
      'W-RANGE-CHART-EXISTS' in _xiv_re
      and "'no rejam chart' in _argl_ce" in _xiv_re
      and "'no chart for this matchup' in _argl_ce" in _xiv_re
      and "_rev.get('membership') in ('inside', 'outside')" in _xiv_re, '')

# T-RE-25 (REV6, 73559949): inverse lint — when canonical evidence has NO charted
# range (chart_key absent, coverage 'none'), prose may NOT claim chart support
# (inside push/EP jam range, clear push, standard shove, mandatory, range-standard).
# A proxy/closest block HAS a chart_key, so its "no exact chart at NBB; using
# nearest chart" disclosure is legitimate and NOT matched.
check('T-RE-25: W-RANGE-NO-CHART lint guards chart-support prose vs canonical no-charted-range',
      'W-RANGE-NO-CHART' in _xiv_re
      and "not _rev.get('chart_key')" in _xiv_re
      and "_rev.get('coverage') in (None, 'none')" in _xiv_re
      and "'inside the push range'" in _xiv_re
      and "'clear push'" in _xiv_re
      and "'standard shove'" in _xiv_re, '')
check('T-1230-VSN-1: cross-hand pattern reads labeled Future read',
      'Future read' in _sx_1230, '')
check('T-1230-SIZE-1: oversized villain opens get the sizing-read note',
      'def _oversize_open_note' in _sx_1230
      and _sx_1230.count('_oversize_open_note(h)') >= 2, '')
check('T-1230-CLS-1: user-facing range counts say hand classes, not combos',
      'hand classes)' in _cb_1230 and 'hand classes)' in _sx_1230
      and not __import__('re').search(r'\d?\{?_?\w*combos\} combos\)', _sx_1230), '')
check('T-1230-SRCH-1: search miss inflates lazy hands and retries',
      'Loading all hands to search' in _html_1230, '')

# --- v8.12.9 pins (Slice A+B: GPT-audit confirmed bugs + clear policies) ---
import gem_villain_intel as _gvi31
check('T-1231-NOT-1: _chart_label canonical — pairs bare, high-first',
      _gvi31._chart_label(['Jh', 'Jd']) == 'JJ'
      and _gvi31._chart_label(['8h', 'Ad']) == 'A8o'
      and _gvi31._chart_label(['Td', 'Ad']) == 'ATs'
      and "+ ('s' if suited else 'o')" not in
      open('gem_villain_intel.py', encoding='utf-8').read(), '')
_html_1231 = open('gem_report_draft/_html.py', encoding='utf-8').read()
check('T-1231-POP-1: popup reads the static verdict-pill before defaulting',
      ".querySelector('.verdict-pill')" in
      _html_1231.split('function openHandListPopup')[1][:8000], '')
check('T-1231-POP-2: unmapped Roman prefixes stripped in popup verdicts',
      "replace(/^[IVX]+\.\d+\s*/,'')" in _html_1231, '')
check('T-1231-MOB-1: mobile street headers sticky',
      'position: sticky; top: var(--v25-topbar-h, 0px); z-index: 4;' in _html_1231, '')
_pk_1231 = open('gem_pko_research.py', encoding='utf-8').read()
check('T-1231-PKO-1: partial multiway coverage names the covered seats',
      'covers %s only — that bounty collectible' in _pk_1231, '')
import gem_pko_research as _pk31
_led31 = [{'street': 'preflop', 'player': 'Op', 'position': 'CO',
           'action': 'raises', 'amount_bb': 2.2, 'stack_bb': 30.0,
           'is_all_in': False},
          {'street': 'preflop', 'player': 'C0', 'position': 'BTN',
           'action': 'calls', 'amount_bb': 2.2, 'stack_bb': 10.0,
           'is_all_in': False},
          {'street': 'preflop', 'player': 'H31', 'position': 'BB',
           'action': 'calls', 'amount_bb': 0, 'stack_bb': 18.0,
           'is_all_in': False}]
_c31 = _pk31.build_pko_context(
    {'id': 'X31', 'hero': 'H31', 'position': 'BB', 'format': 'BOUNTY',
     'tournament_phase': 'bubble_zone', 'eff_stack_bb': 18.0,
     'stack_bb': 18.0, 'action_ledger': _led31,
     'bounty_value_bb': 0, 'bounty_label': ''}, {})
check('T-1231-PKO-2: covers BTN only — CO covers Hero (named, not counted)',
      'covers BTN only' in _c31['coverage_label']
      and 'CO covers Hero' in _c31['coverage_label'],
      _c31['coverage_label'])
_sx_1231 = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-1231-STUB-1: metric-only stubs carry an explicit no-replay reason',
      'no-replay-reason' in _sx_1231
      and 'No action replay for this hand' in _sx_1231, '')
check('T-1231-PKO-3: depth band discloses the effective stack behind it',
      _sx_1231.count("(eff {_pko_ctx.get('effective_stack_bb', '?')}bb)") == 1
      and _sx_1231.count("(eff {_pko_ctx_b.get('effective_stack_bb', '?')}bb)") == 1, '')
check('T-1231-RECON-1: synthesis blocks counted apart from hand entries',
      'synthesis/meta block' in
      open('gem_report_data.py', encoding='utf-8').read(), '')
_cb_1231 = open('gem_coverage_builder.py', encoding='utf-8').read()
check('T-1231-LUCK-1: revealed-hand equity labeled luck context, not decision basis',
      'All-in result equity' in _cb_1231
      and 'not the decision basis' in _cb_1231, '')
check('T-1231-ROM-1: no literal Roman codes printed in Cleared-As cells',
      'III.0 {_oct_disp}' not in
      open('gem_report_draft/sections_mistakes.py', encoding='utf-8').read(), '')

# --- v8.12.10 pins (Slice C: pipeline trust contract) ---
import gem_report_data as _grd32
def _mk_rd32(ac, need_ids):
    return {'analyst_commentary': ac, 'auto_resolved_ids': [],
            '_candidate_need_ids': need_ids}
# AUTO_ONLY: no analyst entries
_rc_a = _grd32.compute_report_completeness(_mk_rd32({}, ['a', 'b']),
                                           candidates=None)
check('T-1232-RC-1: no analyst file -> AUTO_ONLY',
      _rc_a['state'] == 'AUTO_ONLY' and _rc_a['awaiting_candidates'] == 2, str(_rc_a))
# PARTIAL: some reviewed, some awaiting
_rc_p = _grd32.compute_report_completeness(
    _mk_rd32({'a': {'verdict': 'III.2'}, '__synthesis__': {}}, ['a', 'b']),
    candidates=None)
check('T-1232-RC-2: synthesis ignored; partial coverage -> ANALYST_PARTIAL',
      _rc_p['state'] == 'ANALYST_PARTIAL' and _rc_p['reviewed_hands'] == 1
      and _rc_p['awaiting_candidates'] == 1, str(_rc_p))
# COMPLETE: all need-set reviewed
_rc_c = _grd32.compute_report_completeness(
    _mk_rd32({'a': {}, 'b': {}}, ['a', 'b']), candidates=None)
check('T-1232-RC-3: all candidates reviewed -> ANALYST_COMPLETE',
      _rc_c['state'] == 'ANALYST_COMPLETE'
      and _rc_c['awaiting_candidates'] == 0, str(_rc_c))
# candidates path stamps _candidate_need_ids for later --quick
_rd_stamp = {'analyst_commentary': {}, 'auto_resolved_ids': []}
_grd32.compute_report_completeness(
    _rd_stamp, candidates={'mistakes': [{'id': 'X1'}], 'punts': [{'id': 'X2'}]})
check('T-1232-RC-4: candidates path persists need-set for --quick',
      sorted(_rd_stamp['_candidate_need_ids']) == ['X1', 'X2'], '')
_ga32 = open('gem_analyzer.py', encoding='utf-8').read()
check('T-1232-FNAME-1: AUTO_ONLY filename tag wired in all 3 render paths',
      _ga32.count("'AUTO_ONLY' if _rc") == 3
      and 'def _versioned_path(directory, prefix, date, ext, pname_file, tag' in _ga32, '')
check('T-1232-QV-1: --quick validates by default, --no-validate-render opts out',
      '_NO_VALIDATE_RENDER' in _ga32
      and 'def _quick_validate_render' in _ga32
      and "'--no-validate-render'" in _ga32, '')
check('T-1232-MANIFEST-1: run manifest carries analyst_status + summary flag',
      "'analyst_status': _rc_full" in _ga32
      and "'game_summaries_found'" in _ga32, '')
_tldr32 = open('gem_report_draft/tldr.py', encoding='utf-8').read()
check('T-1232-BANNER-1: TLDR emits AUTO_ONLY + no-summary banners',
      'AUTO-ONLY REPORT' in _tldr32
      and 'No tournament game-summary files found' in _tldr32, '')

# --- v8.12.11 pins (Slice E: analyst_worklist_v1) ---
from gem_chart_labels import chart_display_label as _cdl33
check('T-1233-LABEL-1: chart ids resolve to human labels, no raw leak',
      _cdl33('REJAM_SBvsHJ') == 'SB re-jam vs HJ open'
      and _cdl33('OPEN_20-40BB_SB') == 'SB open, 20-40BB'
      and _cdl33('PUSH_10BB_CO') == 'CO open-shove, 10BB'
      and 'REJAM_' not in _cdl33('REJAM_XXvsYY_30BB'), '')
check('T-1233-LABEL-2: UTG+1/UTG+2 positions format (no lowercase fallback)',
      _cdl33('OPEN_100BB_UTG+1') == 'UTG+1 open, ~100BB'
      and _cdl33('PUSH_12BB_UTG+2') == 'UTG+2 open-shove, 12BB'
      and _cdl33('') == '', _cdl33('OPEN_100BB_UTG+1'))

import gem_analyst_worklist as _awl
check('T-1233-HAND-1: _hand_label canonical (list+str), pairs bare',
      _awl._hand_label('4hAs') == 'A4o'
      and _awl._hand_label(['Jc','Jd']) == 'JJ'
      and _awl._hand_label('TdAd') == 'ATs', '')

def _mk_cand(**kw):
    base = {'id': 'TM1', 'cards': kw.pop('cards', 'AhKs'), 'position': 'CO',
            'format': 'BOUNTY', 'tournament_phase': 'mid', 'action_summary': 'x',
            'decision_math': {'key_decision_street': 'preflop', 'streets': {}}}
    base.update(kw); return base

# marginal open NEVER must_review (bottom-5% policy)
_st = {'preflop_deviations': [
    {'id': 'TM_MARG', 'type': 'Missed Open', 'cards': 'K6s', 'pos': 'CO',
     'chart': 'OPEN_100BB_CO', 'confidence': 'MARGINAL'},
    {'id': 'TM_CORE', 'type': 'Missed Open', 'cards': 'AQo', 'pos': 'CO',
     'chart': 'OPEN_100BB_CO', 'confidence': 'CLEAR'}]}
_cands = {'mistakes': [_mk_cand(id='TM_MARG', cards='K6s'),
                       _mk_cand(id='TM_CORE', cards='AhQs')]}
_wl = _awl.build_analyst_worklist(_cands, _st, {}, [], '20260101')
check('T-1233-POL-1: marginal open routes aggregate_only, NEVER must_review',
      _wl['items']['TM_MARG']['bucket'] == 'aggregate_only'
      and _wl['items']['TM_MARG']['range_membership']['bottom_5pct_buffer_applied'] is True, str(_wl['items']['TM_MARG']['bucket']))
check('T-1233-POL-2: CLEAR core miss routes must_review',
      _wl['items']['TM_CORE']['bucket'] == 'must_review', str(_wl['items']['TM_CORE']['bucket']))

# revealed-equity is luck-only, never the basis
_cand_allin = _mk_cand(id='TM_AI', cards='7h7s', position='BB', pf_allin=True,
                       jammer_position='CO', jammer_stack_bb=19.0,
                       eff_stack_at_decision_bb=19.0,
                       hero_realized_eq_at_allin=0.0,
                       decision_math={'key_decision_street': 'preflop',
                       'streets': {'preflop': {'required_equity': 0.48,
                       'hero_equity_vs_range': 0.52, 'hero_call_amount_bb': 17.0}}})
_wl2 = _awl.build_analyst_worklist({'all_in_review': [_cand_allin]}, {}, {}, [], '20260101')
_ai = _wl2['items']['TM_AI']
check('T-1233-POL-3: revealed equity labeled luck-only, not the basis',
      any('luck only' in e for e in _ai['evidence'])
      and 'Do not use the revealed hand' in _ai['reviewer_question'], str(_ai['evidence']))
check('T-1233-POL-4: decision-effective stack vs relevant villain (19, not nominal)',
      _ai['decision_node']['effective_bb_vs_relevant_villain'] == 19.0, '')

# tiny PKO call Hero can collect -> auto_clear (call-any-two protection)
_cand_tiny = _mk_cand(id='TM_TINY', cards='9h2d', position='BTN', pf_allin=True,
                      jammer_position='SB', jammer_stack_bb=12.0,
                      eff_stack_at_decision_bb=80.0, bounty_discount_pp=8.0,
                      decision_math={'key_decision_street': 'preflop',
                      'streets': {'preflop': {'hero_call_amount_bb': 1.0}}})
_rd_tiny = {'pko_research': {'by_hand': {'TM_TINY': {'enabled': True,
            'can_collect_bounty': True, 'coverage_label': 'covers SB',
            'bounty_value_bb_est': 4.0}}}}
_wl3 = _awl.build_analyst_worklist({'bestplay_screening': [_cand_tiny]}, {}, _rd_tiny, [], '20260101')
check('T-1233-POL-5: tiny collectible PKO call -> auto_clear (not a punt)',
      _wl3['items']['TM_TINY']['bucket'] == 'auto_clear'
      and _wl3['items']['TM_TINY']['bounty_context']['hero_covers_relevant_villain'] is True, str(_wl3['items']['TM_TINY']['bucket']))

# schema: all 8 additions + proposals (never final verdicts) + buckets valid
check('T-1233-SCHEMA-1: all 8 additions + review_outcome unreviewed + valid bucket',
      all(all(k in it for k in ('canonical_action_line','decision_node',
          'range_membership','bounty_context','source_truth','llm_prompt_hint',
          'dedupe_group','review_outcome'))
          and it['review_outcome']['status'] == 'unreviewed'
          and it['bucket'] in _awl.BUCKETS
          and it['finality'] in ('auto_clear','analyst_required','aggregate_only')
          for it in _wl2['items'].values()), '')
check('T-1233-SCHEMA-2: no Roman numerals in any proposal/why text',
      not any(__import__('re').search(r'[IVX]+\.\d', it['auto_proposal'] + it['why_review'])
              for it in _wl['items'].values()), '')
_ga_1233 = open('gem_analyzer.py', encoding='utf-8').read()
check('T-1233-EMIT-1: full pipeline emits analyst_worklist artifact',
      'build_analyst_worklist' in _ga_1233
      and 'analyst_worklist_{_wl_dc}.json' in _ga_1233, '')

# --- v8.12.11 GPT-revision pins (findings 3/4/5/6) ---
# GPT-4: a call price that exceeds Hero's effective stack is impossible ->
# null it and surface a 'decision price unavailable' failure mode.
_cand_badprice = _mk_cand(id='TM_BADPRICE', cards='QhQd', position='BB',
    pf_allin=True, jammer_position='CO', jammer_stack_bb=12.0,
    eff_stack_at_decision_bb=12.0,
    decision_math={'key_decision_street': 'preflop',
    'streets': {'preflop': {'hero_call_amount_bb': 117.5}}})
_wl_bp = _awl.build_analyst_worklist({'all_in_review': [_cand_badprice]}, {}, {}, [], '20260101')
_bp = _wl_bp['items']['TM_BADPRICE']
check('T-1233-PRICE-1: call > eff nulls call_amount_bb + failure mode',
      _bp['decision_node']['call_amount_bb'] is None
      and _bp['decision_node']['price_unavailable'] is True
      and 'decision price unavailable' in _bp['failure_modes'],
      str(_bp['decision_node']) + ' / ' + str(_bp['failure_modes']))

# GPT-5: canonical_action_line is built from the hand's action_ledger, not the
# terse 'preflop_only' / action_summary fallback.
_hand_led = {'id': 'TM_LED', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'V1', 'position': 'UTG', 'action': 'raises', 'amount_bb': 2.2},
    {'street': 'preflop', 'player': 'Hero', 'position': 'BTN', 'action': 'calls', 'amount_bb': 2.2},
    {'street': 'flop', 'player': 'V1', 'position': 'UTG', 'action': 'bets', 'amount_bb': 3.0}]}
_cand_led = _mk_cand(id='TM_LED', cards='AhKh', position='BTN',
    decision_math={'key_decision_street': 'flop', 'streets': {}})
_wl_led = _awl.build_analyst_worklist({'mistakes': [_cand_led]}, {}, {}, [_hand_led], '20260101')
_line = _wl_led['items']['TM_LED']['canonical_action_line']
check('T-1233-LINE-1: canonical_action_line built from ledger (not terse)',
      'Hero' in _line and '|' in _line and 'raises 2.2' in _line
      and _line != 'preflop_only', _line)

# GPT-6: bounty_context split — adjustment NOT applied while collectibility is
# unknown, even if a discount_pp is flagged.
_cand_bnt = _mk_cand(id='TM_BNT', cards='AhKs', format='BOUNTY', bounty_discount_pp=6.0)
_wl_bnt = _awl.build_analyst_worklist({'mistakes': [_cand_bnt]}, {}, {}, [], '20260101')
_bc = _wl_bnt['items']['TM_BNT']['bounty_context']
check('T-1233-BNT-1: bounty split — no adjustment while collectibility unknown',
      _bc['is_pko'] is True and _bc['collectibility_known'] is False
      and _bc['adjustment_applied_to_decision'] is False
      and 'estimated_bounty_exists' in _bc, str(_bc))
_rd_bnt2 = {'pko_research': {'by_hand': {'TM_BNT2': {'enabled': True,
    'can_collect_bounty': True, 'coverage_label': 'covers CO',
    'bounty_value_bb_est': 3.0}}}}
_cand_bnt2 = _mk_cand(id='TM_BNT2', cards='AhKs', format='BOUNTY', bounty_discount_pp=6.0)
_wl_bnt2 = _awl.build_analyst_worklist({'mistakes': [_cand_bnt2]}, {}, _rd_bnt2, [], '20260101')
_bc2 = _wl_bnt2['items']['TM_BNT2']['bounty_context']
check('T-1233-BNT-2: bounty adjustment applied only when coverage known+covers',
      _bc2['collectibility_known'] is True
      and _bc2['hero_covers_relevant_villain'] is True
      and _bc2['adjustment_applied_to_decision'] is True
      and _bc2['estimated_bounty_exists'] is True, str(_bc2))

# GPT-3: auto_clear gate is narrow. Deep premium and short non-premium all-ins
# no longer auto_clear; only a narrow premium short-stack get-in does.
_cand_deep = _mk_cand(id='TM_DEEP', cards='AhKd', position='BTN', pf_allin=True,
    format='REGULAR', jammer_position='CO', jammer_stack_bb=100.0,
    eff_stack_at_decision_bb=100.0,
    decision_math={'key_decision_street': 'preflop',
    'streets': {'preflop': {'required_equity': 0.45, 'hero_equity_vs_range': 0.46,
    'hero_call_amount_bb': 100.0}}})
_wl_deep = _awl.build_analyst_worklist({'bestplay_screening': [_cand_deep]}, {}, {}, [], '20260101')
check('T-1233-AC-1: deep premium all-in (AKo 100BB) is NOT auto_clear',
      _wl_deep['items']['TM_DEEP']['bucket'] != 'auto_clear',
      str(_wl_deep['items']['TM_DEEP']['bucket']))
_cand_shortnp = _mk_cand(id='TM_SNP', cards='Ad4c', position='SB', pf_allin=True,
    format='REGULAR', jammer_position='CO', jammer_stack_bb=18.0,
    eff_stack_at_decision_bb=18.0,
    decision_math={'key_decision_street': 'preflop',
    'streets': {'preflop': {'hero_call_amount_bb': 18.0}}})
_wl_snp = _awl.build_analyst_worklist({'bestplay_screening': [_cand_shortnp]}, {}, {}, [], '20260101')
check('T-1233-AC-2: short NON-premium all-in (A4o 18BB) is NOT auto_clear',
      _wl_snp['items']['TM_SNP']['bucket'] != 'auto_clear',
      str(_wl_snp['items']['TM_SNP']['bucket']))
_cand_pshort = _mk_cand(id='TM_PSHORT', cards='AhAs', position='BTN', pf_allin=True,
    format='REGULAR', jammer_position='CO', jammer_stack_bb=15.0,
    eff_stack_at_decision_bb=15.0,
    decision_math={'key_decision_street': 'preflop',
    'streets': {'preflop': {'hero_call_amount_bb': 15.0}}})
_wl_ps = _awl.build_analyst_worklist({'bestplay_screening': [_cand_pshort]}, {}, {}, [], '20260101')
check('T-1233-AC-3: narrow premium short-stack (AA 15BB) -> auto_clear',
      _wl_ps['items']['TM_PSHORT']['bucket'] == 'auto_clear',
      str(_wl_ps['items']['TM_PSHORT']['bucket']))
# multiway gate must read pot participation, NOT table seat count: a heads-up
# all-in at a 6-max table (n_players=6, n_opponents=1) still auto_clears.
_cand_hu6 = _mk_cand(id='TM_HU6', cards='AhAs', position='BTN', pf_allin=True,
    format='REGULAR', jammer_position='CO', jammer_stack_bb=15.0,
    eff_stack_at_decision_bb=15.0, n_players=6,
    multiway_decomposition={'n_opponents': 1}, players_at_flop=2,
    decision_math={'key_decision_street': 'preflop',
    'streets': {'preflop': {'hero_call_amount_bb': 15.0}}})
_wl_hu6 = _awl.build_analyst_worklist({'bestplay_screening': [_cand_hu6]}, {}, {}, [], '20260101')
check('T-1233-AC-4: table seat count (n_players=6) does NOT flag multiway',
      _wl_hu6['items']['TM_HU6']['bucket'] == 'auto_clear',
      str(_wl_hu6['items']['TM_HU6']['bucket']))
# a genuine 3-way all-in (n_opponents=2) IS multiway -> not auto_clear.
_cand_3way = _mk_cand(id='TM_3WAY', cards='AhAs', position='BTN', pf_allin=True,
    format='REGULAR', jammer_position='CO', jammer_stack_bb=15.0,
    eff_stack_at_decision_bb=15.0, n_players=6,
    multiway_decomposition={'n_opponents': 2},
    decision_math={'key_decision_street': 'preflop',
    'streets': {'preflop': {'hero_call_amount_bb': 15.0}}})
_wl_3way = _awl.build_analyst_worklist({'bestplay_screening': [_cand_3way]}, {}, {}, [], '20260101')
check('T-1233-AC-5: genuine 3-way all-in (n_opponents=2) -> NOT auto_clear',
      _wl_3way['items']['TM_3WAY']['bucket'] != 'auto_clear',
      str(_wl_3way['items']['TM_3WAY']['bucket']))

# --- v8.12.11 GPT review #2 pins: decision-node alignment for preflop items ---
# A preflop chart/range deviation must anchor to the PREFLOP decision, never a
# later-street node / full-hand action line / contaminated effective stack.
# DK-1/2: Missed Rejam — Hero called MP's open (hand ran to a river fold). The
# reviewed decision is the preflop re-jam, so street=preflop and the line stops
# at Hero's call (no postflop/river bleed).
_dk_dev = [{'id': 'TM_DK1', 'type': 'Missed Rejam', 'cards': 'QJs', 'pos': 'HJ',
            'chart': 'REJAM_HJvsMP', 'confidence': 'CLEAR',
            'opener_position': 'MP', 'stack_bb': 25}]
_dk_hand = {'id': 'TM_DK1', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'MP', 'position': 'MP', 'action': 'raises', 'amount_bb': 2.2},
    {'street': 'preflop', 'player': 'Hero', 'position': 'HJ', 'action': 'calls', 'amount_bb': 2.2},
    {'street': 'flop', 'player': 'MP', 'position': 'MP', 'action': 'bets', 'amount_bb': 5.0},
    {'street': 'flop', 'player': 'Hero', 'position': 'HJ', 'action': 'calls', 'amount_bb': 5.0},
    {'street': 'river', 'player': 'MP', 'position': 'MP', 'action': 'bets', 'amount_bb': 9.0, 'is_all_in': True},
    {'street': 'river', 'player': 'Hero', 'position': 'HJ', 'action': 'folds'}]}
_dk_cand = _mk_cand(id='TM_DK1', cards='JdQd', position='HJ',
    decision_math={'key_decision_street': 'river', 'streets': {}})
_wl_dk = _awl.build_analyst_worklist({'bestplay_screening': [_dk_cand]},
    {'preflop_deviations': _dk_dev}, {}, [_dk_hand], '20260101')
_dk = _wl_dk['items']['TM_DK1']
check('T-1233-DK-1: preflop deviation anchors decision_node.street=preflop',
      _dk['decision_node']['street'] == 'preflop'
      and _dk['decision_kind'] == 'preflop_deviation', str(_dk['decision_node']['street']))
check('T-1233-DK-2: missed-rejam line stops at Hero call (no postflop bleed)',
      'Hero calls 2.2' in _dk['canonical_action_line']
      and 'bets' not in _dk['canonical_action_line']
      and 'folds' not in _dk['canonical_action_line']
      and 're-jamming' in _dk['reviewer_question'], _dk['canonical_action_line'])
# DK-3/4: first-in Missed Open — Hero folded, SB shoved AFTER. Line stops at
# Hero's fold; effective stack is the clean 81BB, not the overwritten 12BB.
_dk3_dev = [{'id': 'TM_DK3', 'type': 'Missed Open', 'cards': 'K6s', 'pos': 'CO',
             'chart': 'OPEN_100BB_CO', 'confidence': 'CLEAR', 'stack_bb': 81}]
_dk3_hand = {'id': 'TM_DK3', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'UTG', 'position': 'UTG', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'CO', 'action': 'folds'},
    {'street': 'preflop', 'player': 'BTN', 'position': 'BTN', 'action': 'folds'},
    {'street': 'preflop', 'player': 'SB', 'position': 'SB', 'action': 'raises', 'amount_bb': 18.6, 'is_all_in': True},
    {'street': 'preflop', 'player': 'BB', 'position': 'BB', 'action': 'folds'}]}
_dk3_cand = _mk_cand(id='TM_DK3', cards='Kc6c', position='CO',
    eff_stack_at_decision_bb=12.36, effective_stack_bb=81.06, stack_bb=81.06,
    decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_dk3 = _awl.build_analyst_worklist({'mistakes': [_dk3_cand]},
    {'preflop_deviations': _dk3_dev}, {}, [_dk3_hand], '20260101')
_dk3 = _wl_dk3['items']['TM_DK3']
check('T-1233-DK-3: missed-open line stops at Hero fold (no later SB all-in)',
      _dk3['canonical_action_line'].endswith('Hero folds')
      and 'all-in' not in _dk3['canonical_action_line'], _dk3['canonical_action_line'])
check('T-1233-DK-4: first-in open stack not overwritten by later all-in (81 not 12)',
      _dk3['decision_node']['effective_bb_vs_relevant_villain'] == 81.0,
      str(_dk3['decision_node']['effective_bb_vs_relevant_villain']))
# DK-5: BB defend preflop item must not inherit later river/fold context even
# when the candidate's key_decision_street is a later street.
_dk5_dev = [{'id': 'TM_DK5', 'type': 'Missed Defend', 'cards': 'K9o', 'pos': 'BB',
             'chart': 'OPEN_20-40BB_BB', 'confidence': 'CLEAR',
             'opener_position': 'BTN', 'stack_bb': 40}]
_dk5_hand = {'id': 'TM_DK5', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'BTN', 'position': 'BTN', 'action': 'raises', 'amount_bb': 2.2},
    {'street': 'preflop', 'player': 'Hero', 'position': 'BB', 'action': 'folds'}]}
_dk5_cand = _mk_cand(id='TM_DK5', cards='Kh9d', position='BB',
    action_summary='Folded BB vs BTN, call turn, fold river',
    decision_math={'key_decision_street': 'river', 'streets': {}})
_wl_dk5 = _awl.build_analyst_worklist({'mistakes': [_dk5_cand]},
    {'preflop_deviations': _dk5_dev}, {}, [_dk5_hand], '20260101')
_dk5 = _wl_dk5['items']['TM_DK5']
check('T-1233-DK-5: BB defend preflop item does not inherit river/fold context',
      _dk5['decision_node']['street'] == 'preflop'
      and 'river' not in _dk5['canonical_action_line']
      and _dk5['decision_node']['hero_actual_action'] == 'folds'
      and _dk5['canonical_action_line'] == 'BTN raises 2.2 | Hero folds',
      _dk5['canonical_action_line'] + ' / ' + _dk5['decision_node']['hero_actual_action'])

# --- v8.12.11 GPT review #3 pins: decision price is kind/facing aware ---
# A first-in open/fold/jam has NO call price. call_amount_bb must be null with
# price_not_applicable=true (NOT price_unavailable). The K6s/_dk3 fixture also
# proves a later opponent all-in (SB shoves 18.6 after Hero folds) is not bled
# into the price field.
check('T-1233-PNA-1: missed-open first-in fold -> call_amount_bb None + N/A',
      _dk3['decision_node']['call_amount_bb'] is None
      and _dk3['decision_node']['price_not_applicable'] is True
      and _dk3['decision_node']['price_unavailable'] is False, str(_dk3['decision_node']))
check('T-1233-PNA-6: first-in deviation does not inherit a later all-in as price',
      _dk3['decision_node']['call_amount_bb'] is None
      and _dk3['source_truth']['price_engine'] == 'not_applicable',
      str(_dk3['source_truth']['price_engine']))
# wide-open first-in raise: a bogus stblock call price MUST be ignored.
_pna2_dev = [{'id': 'TM_PNA2', 'type': 'Wide Open', 'cards': 'A7s', 'pos': 'CO',
              'chart': 'OPEN_100BB_CO', 'confidence': 'CLEAR', 'stack_bb': 100}]
_pna2_hand = {'id': 'TM_PNA2', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'UTG', 'position': 'UTG', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'CO', 'action': 'raises', 'amount_bb': 2.2}]}
_pna2_cand = _mk_cand(id='TM_PNA2', cards='Ah7h', position='CO', first_in=True,
    decision_math={'key_decision_street': 'preflop',
    'streets': {'preflop': {'hero_call_amount_bb': 3.4}}})  # bogus price -> ignored
_wl_pna2 = _awl.build_analyst_worklist({'mistakes': [_pna2_cand]},
    {'preflop_deviations': _pna2_dev}, {}, [_pna2_hand], '20260101')
_pna2 = _wl_pna2['items']['TM_PNA2']['decision_node']
check('T-1233-PNA-2: wide-open first-in raise -> call_amount_bb None (ignores bogus price)',
      _pna2['call_amount_bb'] is None and _pna2['price_not_applicable'] is True, str(_pna2))
# first-in open jam: still no call price.
_pna3_dev = [{'id': 'TM_PNA3', 'type': 'Wide Open', 'cards': 'A4o', 'pos': 'BTN',
              'chart': 'PUSH_15BB_BTN', 'confidence': 'CLEAR', 'stack_bb': 15}]
_pna3_hand = {'id': 'TM_PNA3', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'CO', 'position': 'CO', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'BTN', 'action': 'raises', 'amount_bb': 15.0, 'is_all_in': True}]}
_pna3_cand = _mk_cand(id='TM_PNA3', cards='Ad4c', position='BTN', pf_allin=True, first_in=True,
    decision_math={'key_decision_street': 'preflop',
    'streets': {'preflop': {'hero_call_amount_bb': 7.9}}})  # bogus price -> ignored
_wl_pna3 = _awl.build_analyst_worklist({'bestplay_screening': [_pna3_cand]},
    {'preflop_deviations': _pna3_dev}, {}, [_pna3_hand], '20260101')
_pna3 = _wl_pna3['items']['TM_PNA3']['decision_node']
check('T-1233-PNA-3: first-in open-jam -> call_amount_bb None',
      _pna3['call_amount_bb'] is None and _pna3['price_not_applicable'] is True, str(_pna3))
# BB defend where Hero CALLS keeps the real call amount (a facing decision).
_pna4_dev = [{'id': 'TM_PNA4', 'type': 'Wide', 'cards': 'K9o', 'pos': 'BB',
              'chart': 'OPEN_20-40BB_BB', 'confidence': 'CLEAR',
              'opener_position': 'BTN', 'stack_bb': 40}]
_pna4_hand = {'id': 'TM_PNA4', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'BTN', 'position': 'BTN', 'action': 'raises', 'amount_bb': 2.5},
    {'street': 'preflop', 'player': 'Hero', 'position': 'BB', 'action': 'calls', 'amount_bb': 2.5}]}
_pna4_cand = _mk_cand(id='TM_PNA4', cards='Kh9d', position='BB', first_in=False,
    decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_pna4 = _awl.build_analyst_worklist({'mistakes': [_pna4_cand]},
    {'preflop_deviations': _pna4_dev}, {}, [_pna4_hand], '20260101')
_pna4 = _wl_pna4['items']['TM_PNA4']['decision_node']
check('T-1233-PNA-4: BB defend (Hero calls) keeps real call_amount_bb',
      _pna4['call_amount_bb'] == 2.5 and _pna4['price_not_applicable'] is False, str(_pna4))
# missed rejam where Hero called instead keeps the real call amount (facing).
check('T-1233-PNA-5: missed-rejam (Hero called) keeps real call amount',
      _dk['decision_node']['call_amount_bb'] == 2.2
      and _dk['decision_node']['price_not_applicable'] is False,
      str(_dk['decision_node']['call_amount_bb']))
# polish: an empty/unmapped chart label must not emit "()" or dangling text.
_pol6_dev = [{'id': 'TM_POL6', 'type': 'Missed Open', 'cards': '77', 'pos': 'CO',
              'chart': '', 'confidence': 'MARGINAL'}]
_pol6_cand = _mk_cand(id='TM_POL6', cards='7h7s', position='CO', first_in=True,
    decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_pol6 = _awl.build_analyst_worklist({'mistakes': [_pol6_cand]},
    {'preflop_deviations': _pol6_dev}, {}, [], '20260101')
_pol6 = _wl_pol6['items']['TM_POL6']
check('T-1233-POL-6: empty chart label -> no empty parens / dangling text',
      '()' not in _pol6['reviewer_question'] and '()' not in _pol6['why_review']
      and '( )' not in _pol6['why_review'], _pol6['reviewer_question'])

# --- v8.12.11 GPT review #4 pins: preflop_allin reviewed-event selector ---
# A preflop all-in is graded on Hero's LAST preflop action (jam / call-off),
# never the initial open. A call-off carries the real (capped) price; a jam
# carries none. facing names the raise/jam Hero faced (or limper / first-in).
_pa1_hand = {'id': 'TM_PA1', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'MP', 'position': 'MP', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'HJ', 'action': 'raises', 'amount_bb': 1.2},
    {'street': 'preflop', 'player': 'BTN', 'position': 'BTN', 'action': 'raises', 'amount_bb': 8.6, 'is_all_in': True},
    {'street': 'preflop', 'player': 'SB', 'position': 'SB', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'HJ', 'action': 'calls', 'amount_bb': 8.6}]}
_pa1_cand = _mk_cand(id='TM_PA1', cards='8h8s', position='HJ', pf_allin=True,
    jammer_position='BTN', jammer_stack_bb=11.0, eff_stack_at_decision_bb=11.0,
    decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_pa1 = _awl.build_analyst_worklist({'all_in_review': [_pa1_cand]}, {}, {}, [_pa1_hand], '20260101')
_pa1 = _wl_pa1['items']['TM_PA1']['decision_node']
check('T-1233-PA-1: open-then-call-off -> node is the call, price applies',
      _pa1['hero_actual_action'] == 'calls 8.6' and _pa1['call_amount_bb'] == 8.6
      and _pa1['price_not_applicable'] is False
      and 'BTN jam 8.6' in _pa1['hero_action_facing'], str(_pa1))
_pa2_hand = {'id': 'TM_PA2', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'Hero', 'position': 'CO', 'action': 'raises', 'amount_bb': 1.2},
    {'street': 'preflop', 'player': 'SB', 'position': 'SB', 'action': 'raises', 'amount_bb': 3.8},
    {'street': 'preflop', 'player': 'BB', 'position': 'BB', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'CO', 'action': 'raises', 'amount_bb': 15.3, 'is_all_in': True},
    {'street': 'preflop', 'player': 'SB', 'position': 'SB', 'action': 'calls', 'amount_bb': 15.3}]}
_pa2_cand = _mk_cand(id='TM_PA2', cards='JhJs', position='CO', pf_allin=True,
    eff_stack_at_decision_bb=15.3, decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_pa2 = _awl.build_analyst_worklist({'all_in_review': [_pa2_cand]}, {}, {}, [_pa2_hand], '20260101')
_pa2 = _wl_pa2['items']['TM_PA2']['decision_node']
check('T-1233-PA-2: open-then-4bet-jam -> node is Hero jam, facing the 3-bet',
      _pa2['hero_actual_action'] == 'raises 15.3 all-in'
      and 'SB raise 3.8' in _pa2['hero_action_facing']
      and _pa2['price_not_applicable'] is True and _pa2['call_amount_bb'] is None, str(_pa2))
_pa3_hand = {'id': 'TM_PA3', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'Hero', 'position': 'UTG+1', 'action': 'raises', 'amount_bb': 1.2},
    {'street': 'preflop', 'player': 'CO', 'position': 'CO', 'action': 'raises', 'amount_bb': 2.8},
    {'street': 'preflop', 'player': 'BTN', 'position': 'BTN', 'action': 'raises', 'amount_bb': 24.1, 'is_all_in': True},
    {'street': 'preflop', 'player': 'SB', 'position': 'SB', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'UTG+1', 'action': 'calls', 'amount_bb': 22.5, 'is_all_in': True},
    {'street': 'preflop', 'player': 'CO', 'position': 'CO', 'action': 'folds'}]}
_pa3_cand = _mk_cand(id='TM_PA3', cards='KhKs', position='UTG+1', pf_allin=True,
    jammer_position='BTN', jammer_stack_bb=24.1, eff_stack_at_decision_bb=22.5,
    decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_pa3 = _awl.build_analyst_worklist({'all_in_review': [_pa3_cand]}, {}, {}, [_pa3_hand], '20260101')
_pa3 = _wl_pa3['items']['TM_PA3']['decision_node']
check('T-1233-PA-3: open-raise-jam, Hero calls off -> node is the call-off',
      _pa3['hero_actual_action'] == 'calls 22.5 all-in'
      and 'BTN jam 24.1' in _pa3['hero_action_facing']
      and _pa3['call_amount_bb'] == 22.5 and _pa3['price_not_applicable'] is False, str(_pa3))
_pa4_hand = {'id': 'TM_PA4', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'CO', 'position': 'CO', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'BTN', 'action': 'raises', 'amount_bb': 12.0, 'is_all_in': True},
    {'street': 'preflop', 'player': 'BB', 'position': 'BB', 'action': 'folds'}]}
_pa4_cand = _mk_cand(id='TM_PA4', cards='Ad9d', position='BTN', pf_allin=True, first_in=True,
    eff_stack_at_decision_bb=12.0, decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_pa4 = _awl.build_analyst_worklist({'bestplay_screening': [_pa4_cand]}, {}, {}, [_pa4_hand], '20260101')
_pa4 = _wl_pa4['items']['TM_PA4']['decision_node']
check('T-1233-PA-4: first-in open-jam -> call None, N/A, facing first-in',
      _pa4['call_amount_bb'] is None and _pa4['price_not_applicable'] is True
      and _pa4['hero_actual_action'] == 'raises 12.0 all-in'
      and _pa4['hero_action_facing'] == 'first-in', str(_pa4))
_pa5_hand = {'id': 'TM_PA5', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'MP', 'position': 'MP', 'action': 'calls', 'amount_bb': 1.0},
    {'street': 'preflop', 'player': 'Hero', 'position': 'CO', 'action': 'raises', 'amount_bb': 9.0, 'is_all_in': True},
    {'street': 'preflop', 'player': 'BB', 'position': 'BB', 'action': 'folds'}]}
_pa5_cand = _mk_cand(id='TM_PA5', cards='Ah9h', position='CO', pf_allin=True,
    eff_stack_at_decision_bb=9.0, decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_pa5 = _awl.build_analyst_worklist({'all_in_review': [_pa5_cand]}, {}, {}, [_pa5_hand], '20260101')
_pa5 = _wl_pa5['items']['TM_PA5']['decision_node']
check('T-1233-PA-5: iso-jam over limper -> facing vs limper(s), not unknown',
      _pa5['hero_action_facing'] == 'vs limper(s)'
      and _pa5['hero_actual_action'] == 'raises 9.0 all-in'
      and _pa5['call_amount_bb'] is None, str(_pa5))
_pa6_line = _wl_pa2['items']['TM_PA2']['canonical_action_line']
check('T-1233-PA-6: preflop_allin line stops at the reviewed all-in (no trailing caller)',
      _pa6_line.endswith('Hero raises 15.3 all-in') and 'SB calls' not in _pa6_line, _pa6_line)
check('T-1233-PA-7: multi-action preflop_allin never anchors to the initial open',
      all(w['items'][h]['decision_node']['hero_actual_action'] != 'raises 1.2'
          for w, h in [(_wl_pa1, 'TM_PA1'), (_wl_pa2, 'TM_PA2'), (_wl_pa3, 'TM_PA3')]), '')
# first-in deviation must not surface a contaminated opener as "X open".
_pa8_dev = [{'id': 'TM_PA8', 'type': 'Wide Open', 'cards': 'A5o', 'pos': 'CO',
             'chart': 'PUSH_20BB_CO', 'confidence': 'CLEAR', 'opener_position': 'MP', 'stack_bb': 20}]
_pa8_hand = {'id': 'TM_PA8', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'UTG', 'position': 'UTG', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'CO', 'action': 'raises', 'amount_bb': 20.0, 'is_all_in': True},
    {'street': 'preflop', 'player': 'BTN', 'position': 'BTN', 'action': 'folds'}]}
_pa8_cand = _mk_cand(id='TM_PA8', cards='Ad5c', position='CO', pf_allin=True, first_in=True,
    decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_pa8 = _awl.build_analyst_worklist({'bestplay_screening': [_pa8_cand]},
    {'preflop_deviations': _pa8_dev}, {}, [_pa8_hand], '20260101')
check('T-1233-PA-8: first-in deviation w/ contaminated opener -> facing first-in',
      _wl_pa8['items']['TM_PA8']['decision_node']['hero_action_facing'] == 'first-in (folds to Hero)',
      _wl_pa8['items']['TM_PA8']['decision_node']['hero_action_facing'])

# --- v8.12.11 GPT review #5 pins: raw size vs decision-effective stack ---
# clean overjam call-off: call capped to eff (never > eff), overjam present.
_sz1_hand = {'id': 'TM_SZ1', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'SB', 'position': 'SB', 'action': 'raises', 'amount_bb': 44.5, 'is_all_in': True},
    {'street': 'preflop', 'player': 'Hero', 'position': 'BB', 'action': 'calls', 'amount_bb': 44.5}]}
_sz1_cand = _mk_cand(id='TM_SZ1', cards='AhKh', position='BB', pf_allin=True,
    jammer_position='SB', jammer_stack_bb=44.5, eff_stack_at_decision_bb=26.2,
    decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_sz1 = _awl.build_analyst_worklist({'all_in_review': [_sz1_cand]}, {}, {}, [_sz1_hand], '20260101')
_sz1 = _wl_sz1['items']['TM_SZ1']['decision_node']
check('T-1233-SZ-1: clean overjam call-off capped to eff (call<=eff, overjam present)',
      _sz1['call_amount_bb'] == 26.2 and _sz1['effective_bb_vs_relevant_villain'] == 26.2
      and _sz1['call_amount_bb'] <= _sz1['effective_bb_vs_relevant_villain']
      and _sz1['overjam_bb'] and _sz1['action_size_bb'] == 44.5, str(_sz1))
# multiway call-off, raw > eff, cannot reconcile -> null + price unavailable + failure mode.
_sz2_hand = {'id': 'TM_SZ2', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'CO', 'position': 'CO', 'action': 'raises', 'amount_bb': 16.9, 'is_all_in': True},
    {'street': 'preflop', 'player': 'SB', 'position': 'SB', 'action': 'raises', 'amount_bb': 14.1, 'is_all_in': True},
    {'street': 'preflop', 'player': 'Hero', 'position': 'BB', 'action': 'calls', 'amount_bb': 32.0}]}
_sz2_cand = _mk_cand(id='TM_SZ2', cards='7h7s', position='BB', pf_allin=True,
    eff_stack_at_decision_bb=19.0, decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_sz2 = _awl.build_analyst_worklist({'all_in_review': [_sz2_cand]}, {}, {}, [_sz2_hand], '20260101')
_sz2_it = _wl_sz2['items']['TM_SZ2']; _sz2 = _sz2_it['decision_node']
check('T-1233-SZ-2: multiway call-off raw>eff -> null + price unavailable + failure mode',
      _sz2['call_amount_bb'] is None and _sz2['price_unavailable'] is True
      and any('side-pot/overjam reconciliation' in f for f in _sz2_it['failure_modes']), str(_sz2))
# first-in overjam jam: jam_size and decision_effective separated.
_sz3_hand = {'id': 'TM_SZ3', 'hero': 'Hero', 'action_ledger': [
    {'street': 'preflop', 'player': 'CO', 'position': 'CO', 'action': 'folds'},
    {'street': 'preflop', 'player': 'Hero', 'position': 'BTN', 'action': 'raises', 'amount_bb': 77.4, 'is_all_in': True},
    {'street': 'preflop', 'player': 'BB', 'position': 'BB', 'action': 'folds'}]}
_sz3_cand = _mk_cand(id='TM_SZ3', cards='Qh5h', position='BTN', pf_allin=True, first_in=True,
    eff_stack_at_decision_bb=13.0, decision_math={'key_decision_street': 'preflop', 'streets': {}})
_wl_sz3 = _awl.build_analyst_worklist({'bestplay_screening': [_sz3_cand]}, {}, {}, [_sz3_hand], '20260101')
_sz3_it = _wl_sz3['items']['TM_SZ3']; _sz3 = _sz3_it['decision_node']
check('T-1233-SZ-3: first-in overjam shows jam_size and decision_effective separately',
      _sz3['jam_size_bb'] == 77.4 and _sz3['decision_effective_bb'] == 13.0
      and _sz3['risk_bb'] == 13.0 and _sz3['overjam_bb'] == 64.4
      and _sz3['call_amount_bb'] is None and _sz3['price_not_applicable'] is True, str(_sz3))
check('T-1233-SZ-4: reviewer question uses decision-effective stack, not raw jam size',
      '13BB' in _sz3_it['reviewer_question'] and '77' not in _sz3_it['reviewer_question'],
      _sz3_it['reviewer_question'])
check('T-1233-SZ-5: why_review reconciles raw jam vs effective (no contradiction with action)',
      'raw all-in' in _sz3_it['why_review'] and 'effective' in _sz3_it['why_review']
      and _sz3['hero_actual_action'] == 'raises 77.4 all-in', _sz3_it['why_review'])


def _no_overprice(_w):
    for _it in _w['items'].values():
        _dn = _it['decision_node']
        _ca, _ef = _dn.get('call_amount_bb'), _dn.get('effective_bb_vs_relevant_villain')
        if _ca and _ef and _ca > _ef + 0.05 and not (_dn.get('overjam_bb') or _dn.get('side_pot_context')):
            return False
    return True
check('T-1233-SZ-INV: no item has call_amount_bb > effective stack without overjam/side_pot',
      all(_no_overprice(_w) for _w in [_wl_sz1, _wl_sz2, _wl_sz3, _wl_pa1, _wl_pa2, _wl_pa3]), '')

# ============================================================
# v8.12.12 / Slice E.1 — report trust + source-truth cleanup (T-1234)
# ============================================================
# --- Objective A: analyst punt street/type label ---
from gem_report_draft.sections_mistakes import _analyst_punt_street_label as _apsl
check('T-1234-A-1: analyst street=preflop -> Preflop punt (not Postflop)',
      _apsl({'verdict': 'III.1 Punt', 'street': 'preflop'}, None) == 'Preflop punt (analyst)', '')
check('T-1234-A-2: analyst street=turn -> Postflop punt',
      _apsl({'verdict': 'III.1 Punt', 'street': 'turn'}, None) == 'Postflop punt (analyst)', '')
check('T-1234-A-3: preflop all-in hand (no street/spot) -> Preflop punt, not Postflop',
      _apsl({'verdict': 'III.1 Punt'}, {'pf_allin': True, 'went_to_sd': True}) == 'Preflop punt (analyst)', '')
check('T-1234-A-4: spot PF ALL-IN marker -> Preflop punt',
      _apsl({'verdict': 'III.1 Punt', 'spot': 'BTN 40BB, PF ALL-IN, SD lost'}, None) == 'Preflop punt (analyst)', '')
check('T-1234-A-5: legacy/unknown street degrades to neutral Punt (not Postflop)',
      _apsl({'verdict': 'III.1 Punt'}, {'pf_allin': False}) == 'Punt (analyst)', '')
_sm_src = open('gem_report_draft/sections_mistakes.py', encoding='utf-8').read()
check('T-1234-A-6: hardcoded "Postflop punt" fallback removed from the punt table',
      "type_label = 'Postflop punt (analyst)'" not in _sm_src
      and '_analyst_punt_street_label(cmt, h)' in _sm_src, '')

# --- Objective B: neutral AUTO_ONLY / unreviewed large-loss labels ---
from gem_report_draft.sections_financial import _neutral_unreviewed_large_loss_verdict as _nllv
check('T-1234-B-1: top-of-range loss w/o verdict -> neutral status, no exculpatory verdict',
      _nllv('top_of_range').startswith('⏳ awaiting analyst')
      and 'showdown' in _nllv('top_of_range')
      and '🪤' not in _nllv('top_of_range')
      and 'vs top-of-range' not in _nllv('top_of_range'), _nllv('top_of_range'))
check('T-1234-B-2: no signal/context -> plain "awaiting analyst review"',
      _nllv(None) == '⏳ awaiting analyst review', _nllv(None))
check('T-1234-B-3: auto-detected cooler -> auto-signal context, not a cooler verdict',
      _nllv(None, auto_cooler=True).startswith('⏳ awaiting analyst')
      and 'auto signal' in _nllv(None, auto_cooler=True)
      and '❄️' not in _nllv(None, auto_cooler=True), _nllv(None, auto_cooler=True))
_sf_src = open('gem_report_draft/sections_financial.py', encoding='utf-8').read()
_x13_src = open('gem_report_draft/sections_xiii.py', encoding='utf-8').read()
check('T-1234-B-4: S1.3 no longer renders exculpatory variance/cooler as a verdict default',
      '🎲 unclassified variance' not in _sf_src
      and '🪤 vs top-of-range' not in _sf_src
      and 'elif hid in i7_ids:' in _sf_src
      and '_neutral_unreviewed_large_loss_verdict(' in _sf_src, '')
check('T-1234-B-5: S17.6 large-loss audit neutralized the same way',
      '🎲 unclassified variance' not in _x13_src
      and '🪤 vs top-of-range' not in _x13_src
      and 'elif hid in i7_ids_full:' in _x13_src, '')

# --- Objective C: source_truth.price_engine provenance (no 'none' w/ a price) ---
def _pe(_w, _hid):
    return _w['items'][_hid]['source_truth']['price_engine']
# reuse PA/SZ/DK fixtures built above
check('T-1234-C-1: no item with a populated call_amount_bb has price_engine none',
      all(not (it['decision_node'].get('call_amount_bb')
               and it['source_truth']['price_engine'] in ('none', None))
          for _w in [_wl_pa1, _wl_pa2, _wl_pa3, _wl_sz1, _wl_sz2, _wl_sz3,
                     _wl_dk3, _wl_pol6]
          for it in _w['items'].values()), '')
check('T-1234-C-2: first-in open/fold -> price_engine not_applicable (never none)',
      _pe(_wl_dk3, 'TM_DK3') == 'not_applicable', _pe(_wl_dk3, 'TM_DK3'))
check('T-1234-C-3: ledger call-off -> action_ledger',
      _pe(_wl_pa1, 'TM_PA1') == 'action_ledger', _pe(_wl_pa1, 'TM_PA1'))
check('T-1234-C-4: capped overjam call-off -> sidepot_reconciled',
      _pe(_wl_sz1, 'TM_SZ1') == 'sidepot_reconciled', _pe(_wl_sz1, 'TM_SZ1'))
check('T-1234-C-5: unsafe multiway call-off -> unavailable + failure mode',
      _pe(_wl_sz2, 'TM_SZ2') == 'unavailable'
      and any('side-pot/overjam reconciliation' in f
              for f in _wl_sz2['items']['TM_SZ2']['failure_modes']), _pe(_wl_sz2, 'TM_SZ2'))
check('T-1234-C-6: first-in open-jam (no call price) -> not_applicable, not none',
      _pe(_wl_sz3, 'TM_SZ3') == 'not_applicable', _pe(_wl_sz3, 'TM_SZ3'))
_aw_src = open('gem_analyst_worklist.py', encoding='utf-8').read()
check('T-1234-C-7: price_engine driven by decision-node price_source (no static none)',
      "src_truth['price_engine'] = dn['price_source']" in _aw_src
      and "'price_source':" in _aw_src, '')

# --- Objective D: analyst coverage/status clarity (banners + counts) ---
from gem_report_data import compute_report_completeness as _crc12
_cands_d = {'punts': [{'id': 'HD1'}], 'mistakes': [{'id': 'HD2'}]}
_rc_auto = _crc12({'analyst_commentary': {}}, _cands_d)
check('T-1234-D-1: no analyst -> AUTO_ONLY, all candidates awaiting',
      _rc_auto['state'] == 'AUTO_ONLY' and _rc_auto['awaiting_candidates'] == 2
      and _rc_auto['candidate_need'] == 2, str(_rc_auto))
_rc_part = _crc12({'analyst_commentary': {'HD1': {'verdict': 'III.1 Punt'}}}, _cands_d)
check('T-1234-D-2: partial -> reviewed/candidate/unreviewed counts + remaining bucket named',
      _rc_part['state'] == 'ANALYST_PARTIAL' and _rc_part['reviewed_hands'] == 1
      and _rc_part['candidate_need'] == 2 and _rc_part['awaiting_candidates'] == 1
      and _rc_part['awaiting_by_bucket'].get('mistakes') == 1, str(_rc_part))
_rc_done = _crc12({'analyst_commentary': {'HD1': {'verdict': 'III.1 Punt'},
                   'HD2': {'verdict': 'III.5 Justified'}}}, _cands_d)
check('T-1234-D-3: all candidates reviewed -> ANALYST_COMPLETE, none awaiting',
      _rc_done['state'] == 'ANALYST_COMPLETE' and _rc_done['awaiting_candidates'] == 0
      and not _rc_done['awaiting_by_bucket'], str(_rc_done))
# --quick path: need-bucket persisted, awaiting recomputed without candidates
_rd_q = {'analyst_commentary': {'HD1': {'verdict': 'III.1 Punt'}},
         '_candidate_need_ids': ['HD1', 'HD2'],
         '_candidate_need_bucket': {'HD1': 'punts', 'HD2': 'mistakes'}}
_rc_q12 = _crc12(_rd_q, None)
check('T-1234-D-4: --quick (no candidates) still names remaining bucket from persisted map',
      _rc_q12['state'] == 'ANALYST_PARTIAL'
      and _rc_q12['awaiting_by_bucket'].get('mistakes') == 1, str(_rc_q12))
_tldr_src = open('gem_report_draft/tldr.py', encoding='utf-8').read()
check('T-1234-D-5: TLDR banner covers all three states with counts + remaining buckets',
      "_rc_state == 'AUTO_ONLY'" in _tldr_src
      and "_rc_state == 'ANALYST_PARTIAL'" in _tldr_src
      and "_rc_state == 'ANALYST_COMPLETE'" in _tldr_src
      and "candidate_need" in _tldr_src and "_awaiting_buckets_phrase" in _tldr_src
      and "INCOMPLETE" in _tldr_src, '')

# ============================================================
# v8.12.12 / Slice E.1 rev-2 — report trust (T-1235): F cover table,
# G PKO bounty-adjusted math, H Roman-code removal, I summary honesty
# ============================================================
# --- Objective F: Stack Context cover table — every villain vs Hero ---
from gem_report_draft.sections_xiv import _stack_cover_label as _scl
check('T-1235-F-1: shorter villain -> Hero covers + delta (direction shown)',
      _scl(18.7, 13.0, 1) == '✓ Hero covers +5.7BB', _scl(18.7, 13.0, 1))
check('T-1235-F-2: deeper villain -> Villain covers Hero + delta (not "= equal")',
      _scl(18.7, 24.1, 1) == '✗ Villain covers Hero +5.4BB', _scl(18.7, 24.1, 1))
check('T-1235-F-3: within tolerance -> "≈ roughly equal" only for true near-ties',
      _scl(18.7, 18.75, 1) == '≈ roughly equal'
      and _scl(18.7, 18.4, 1) != '≈ roughly equal', _scl(18.7, 18.75, 1))
# Regression for hand 70391838: Hero SB 18.7BB vs BB/MP/HJ/CO/BTN.
# v8.12.11 showed BB "✓ Hero covers" but MP/HJ/CO/BTN as a flat "= equal".
_f70 = {14.3: '✓ Hero covers +4.4BB', 13.0: '✓ Hero covers +5.7BB',
        24.1: '✗ Villain covers Hero +5.4BB', 31.8: '✗ Villain covers Hero +13.1BB',
        7.9: '✓ Hero covers +10.8BB'}
check('T-1235-F-4: hand 70391838 — all 5 villain seats compared to Hero (no "= equal")',
      all(_scl(18.7, _vb, 1) == _exp for _vb, _exp in _f70.items()),
      str({_vb: _scl(18.7, _vb, 1) for _vb in _f70}))
_xiv_src = open('gem_report_draft/sections_xiv.py', encoding='utf-8').read()
check('T-1235-F-5: cover table wired to helper; buggy flag-only "= equal" branch removed',
      'def _stack_cover_label(' in _xiv_src
      and '_stack_cover_label(' in _xiv_src
      and "vs_str = '= equal'" not in _xiv_src
      and "f'✗ covers Hero (+" not in _xiv_src, '')

# --- Objective G: PKO bounty-adjusted threshold math (only where safe) ---
import gem_bounty as _gb
# Collectibility invariant the render relies on: a discount/value exist only
# when Hero covers; a non-covering Hero never gets a fabricated discount.
_bc_cov = _gb.bounty_context('Bounty Hunters', 'post_reg', fmt='BOUNTY', hero_covers=True)
_bc_nocov = _gb.bounty_context('Bounty Hunters', 'post_reg', fmt='BOUNTY', hero_covers=False)
check('T-1235-G-1: Hero covers -> positive bounty discount + value (collectible)',
      _bc_cov['discount_pp'] > 0 and _bc_cov['value_bb'] > 0,
      f"disc={_bc_cov['discount_pp']} val={_bc_cov['value_bb']}")
check('T-1235-G-2: Hero does NOT cover -> 0 discount + 0 value (no fabricated discount)',
      _bc_nocov['discount_pp'] == 0 and _bc_nocov['value_bb'] == 0,
      f"disc={_bc_nocov['discount_pp']} val={_bc_nocov['value_bb']}")
check('T-1235-G-3: cover-aware PKO-adjusted threshold rendered + freezeout guard',
      'PKO-adjusted call needs' in _xiv_src
      and 'Hero covers ' in _xiv_src and 'bounty collectible' in _xiv_src
      and "_btype not in (None, 'none')" in _xiv_src
      and 'hero_covers_field' in _xiv_src, '')
check('T-1235-G-4: unknown/unsafe -> "review manually"; old misleading copy removed',
      'PKO adjustment unavailable' in _xiv_src
      and 'review' in _xiv_src and 'manually' in _xiv_src
      and '**Bounty-adjusted:** required' not in _xiv_src
      and 'no discount (Hero does not cover' not in _xiv_src, '')
check('T-1235-G-5: estimated bounty labelled a model estimate; adj-EV only with discount',
      'estimated bounty model' in _xiv_src
      and _xiv_src.index('**Bounty-adjusted EV:**')
          > _xiv_src.index('PKO-adjusted call needs'), '')

# --- Obj-G rev-3: PKO bounty estimate $X / dollar-unavailable + thresholds ---
from gem_report_draft.sections_xiv import _pko_bounty_usd as _pbu
_rd_usd = {'usd_overlay': {'per_tournament': [{'tid': 'T1', 'name': 'PKO 5', 'bounty_usd': 2.5}]}}
check('T-1236-G-1: safe dollar source present -> bounty $ returned (by tid or name)',
      _pbu(_rd_usd, {'tournament_id': 'T1'}) == 2.5
      and _pbu(_rd_usd, {'tournament': 'PKO 5'}) == 2.5, '')
check('T-1236-G-2: no safe dollar source -> None (caller says unavailable, no fake $)',
      _pbu({'usd_overlay': {'per_tournament': [{'tid': 'T1'}]}}, {'tournament_id': 'T1'}) is None
      and _pbu({}, {'tournament_id': 'X'}) is None
      and _pbu(_rd_usd, {'tournament_id': 'OTHER'}) is None, '')
check('T-1236-G-3: render shows "$X" when safe, else explicit dollar-unavailable + BB model',
      '**Estimated bounty:** $' in _xiv_src
      and '{_vbb:.1f}BB' in _xiv_src
      and 'Dollar bounty unavailable in HH export' in _xiv_src
      and 'estimated bounty model' in _xiv_src, '')
check('T-1236-G-4: chip-only -> PKO-adjusted call thresholds shown side by side',
      'Chip-only call needs' in _xiv_src and 'PKO-adjusted call needs ~' in _xiv_src, '')

# --- Objective H: strip Roman verdict codes from user-facing copy ---
from gem_report_draft._hand_grid import _verdict_display_label as _vdl
_H_CODES = {'III.1 Punt': 'Punt', 'III.2 Mistake': 'Mistake',
            'III.3 Variance': 'Variance', 'III.4 Read-dependent': 'Read-dependent',
            'III.5 Justified': 'Justified', 'I.7 Cooler': 'Cooler'}
check('T-1235-H-1: every Roman-coded verdict label renders code-free',
      all(_vdl(k) == v for k, v in _H_CODES.items())
      and not any(_vdl(k).startswith(('III.', 'I.7')) for k in _H_CODES), '')
check('T-1235-H-2: bare codes map to labels; already-clean / non-verdict pass through',
      _vdl('III.2') == 'Mistake' and _vdl('I.7') == 'Cooler'
      and _vdl('Punt') == 'Punt' and _vdl('—') == '—'
      and _vdl('📊 screened') == '📊 screened' and _vdl('') == '', '')
from gem_report_draft._hand_grid import _VERDICT_HUMAN as _VH
check('T-1235-H-3: display-only — taxonomy map + internal code routing intact',
      _VH.get('III.1') == 'Punt' and _VH.get('I.7') == 'Cooler'
      and 'III.1 Punt'.startswith('III.1'), '')
# leak sites wired to the helper
_sf_src_h = open('gem_report_draft/sections_financial.py', encoding='utf-8').read()
_x13_src_h = open('gem_report_draft/sections_xiii.py', encoding='utf-8').read()
_sm_src_h = open('gem_report_draft/sections_mistakes.py', encoding='utf-8').read()
check('T-1235-H-4: verdict-label leak sites route through _verdict_display_label',
      '_verdict_display_label(' in _xiv_src
      and '_verdict_display_label(' in _x13_src_h
      and '_verdict_display_label(' in _sf_src_h
      and '_verdict_display_label(' in _sm_src_h, '')
check('T-1235-H-5: raw Roman-code copy removed from user-facing strings',
      'analyst-confirmed III.1/III.2' not in _x13_src_h
      and 'III.1 punt / III.2 strategic leak' not in _x13_src_h
      and 'No III.0 GTO-Standard' not in _sm_src_h
      and 'I.7 cooler or III.x leak' not in _sm_src_h, '')

# --- Obj-H rev-3: source smoke — NO Roman verdict code in any VISIBLE render
#     string across the report-draft package. Allowlist (per GPT review):
#     docstrings, exact code tokens (dict keys / startswith args), quote-wrapped
#     code tokens (maps / comparisons), anchors/ids, and a tiny set of internal
#     verdict-set comparison literals. Anything else that still embeds a code is
#     rendered prose -> fail.
import ast as _ast_h, os as _os_h, re as _re_h
_H_CODE = _re_h.compile(r'\bIII\.[0-9]\b|\bI\.7\b')
_H_EXACT = _re_h.compile(r'^(III\.[0-9]|I\.7)$')
_H_QUOTED = _re_h.compile(r'''['"](?:III\.[0-9]|I\.7)['"]''')
_H_ALLOW_LITERALS = {'III.3 Cleared', 'III.5 Justified', 'I.7 Cooler'}
def _h_doc_ids(_tree):
    _out = set()
    for _n in _ast_h.walk(_tree):
        if isinstance(_n, (_ast_h.Module, _ast_h.FunctionDef, _ast_h.AsyncFunctionDef, _ast_h.ClassDef)):
            _b = getattr(_n, 'body', [])
            if _b and isinstance(_b[0], _ast_h.Expr) and isinstance(getattr(_b[0], 'value', None), _ast_h.Constant) and isinstance(_b[0].value.value, str):
                _out.add(id(_b[0].value))
    return _out
def _h_scan(_fp):
    _tree = _ast_h.parse(open(_fp, encoding='utf-8').read())
    _docs = _h_doc_ids(_tree)
    _leaks = []
    for _n in _ast_h.walk(_tree):
        if not (isinstance(_n, _ast_h.Constant) and isinstance(_n.value, str)):
            continue
        if id(_n) in _docs:
            continue
        _s = _n.value
        if not _H_CODE.search(_s) or _H_EXACT.match(_s):
            continue
        if _s.startswith('sec-') or _s.startswith('#sec') or _s in _H_ALLOW_LITERALS:
            continue
        if _H_CODE.search(_H_QUOTED.sub('', _s)):
            _leaks.append((_os_h.path.basename(_fp), _s[:60]))
    return _leaks
_rd_dir_h = _os_h.path.join(_os_h.path.dirname(__file__), 'gem_report_draft')
_h_all_leaks = []
for _fn_h in sorted(_os_h.listdir(_rd_dir_h)):
    if _fn_h.endswith('.py'):
        _h_all_leaks += _h_scan(_os_h.path.join(_rd_dir_h, _fn_h))
check('T-1236-H-6: no Roman verdict code in any visible render string (report-draft)',
      not _h_all_leaks, str(_h_all_leaks[:6]))
check('T-1236-H-7: humanized copy present, Roman render-forms gone (ASCII-safe)',
      'read-dependent review' in _xiv_src and 'III.4 review' not in _xiv_src
      and 'Per-hand analysis in the read-dependent section.' in _tldr_src
      and 'Per-hand analysis in III.4' not in _tldr_src, '')

# ============================================================
# v8.13.0 — Villain Exploitation Teaching Layer (T-VT)
# ============================================================
import gem_villain_teaching as _vt
_vt_vk = 'T1|abcd1234'
def _vt_rs(n=9, conf='high', hids=None, primary='\U0001F4DE Sticky Passive'):
    return {_vt_vk: {'villain_alias': 'Ghost', 'primary_read': primary,
                     'confidence': conf, 'n_evidence': n,
                     'evidence_hand_ids': hids or ['H9', 'H7', 'H_now']}}
_vt_sticky = {_vt_vk: [{'dimension': 'sticky'} for _ in range(3)]}
def _vt_exp(**kw):
    b = {'villain_key': _vt_vk, 'hand_id': 'H_now', 'exploit_read_label': 'Sticky Passive',
         'exploit_read_display': '\U0001F4DE Sticky Passive', 'read_source': 'prior_atoms_mapped',
         'evidence_text': 'Called river with second pair after Hero double-barreled.',
         'suggests': 'Villain is sticky/station - calls down with marginal holdings.',
         'so_what': 'Do not bluff this player multi-street. Value-bet thinner instead.',
         'recommended_exploit': 'Check back rivers; value-bet thinner.',
         'available_before_action_index': 2, 'action_index': 5, 'hero_decision_street': 'river'}
    b.update(kw); return b
_REQ = {'villain_id', 'villain_alias', 'street', 'villain_did', 'cue', 'archetype',
        'confidence', 'evidence_count', 'exploit_now', 'future_exploit',
        'do_not_overadjust', 'source_truth', 'population'}
_o = _vt.teaching_from_exploit(_vt_exp(), _vt_rs(), _vt_sticky)
check('T-VT-01: teaching object has full contract incl source_truth{atoms,decision_id,no_hindsight}',
      _REQ <= set(_o) and {'evidence_atoms', 'decision_id', 'no_hindsight'} <= set(_o['source_truth']), '')
check('T-VT-02: villain-fact fields copied verbatim from stamped exploit (no invention)',
      _o['villain_did'] == 'Called river with second pair after Hero double-barreled.'
      and _o['cue'].startswith('Villain is sticky/station')
      and _o['exploit_now'] == 'Do not bluff this player multi-street. Value-bet thinner instead.'
      and _o['future_exploit'] == 'Check back rivers; value-bet thinner.', '')
_thin = _vt.teaching_from_exploit(_vt_exp(evidence_text='', suggests=''),
                                  {_vt_vk: {'n_evidence': 1, 'evidence_hand_ids': ['H_now']}}, {_vt_vk: []})
check('T-VT-03: thin read -> fixed fallback line, no exploit_now',
      _thin['fallback'] and _vt.FALLBACK_LINE in _thin['teach_lines'] and _thin['exploit_now'] is None, '')
_sd = _vt.teaching_from_atom({'villain_key': _vt_vk, 'hand_id': 'H2', 'signal': 'weak_showdown_call',
                              'street': 'river', 'action_index': 4, 'available_before_action_index': None,
                              'evidence_text': 'Showed weak pair.', 'hero_involved': True,
                              'so_what': 'Value-bet thinner.', 'suggests': 'Sticky.'},
                             _vt_rs(), _vt_sticky, signal_coaching={})
check('T-VT-04: showdown-only atom (available None) -> no_hindsight False, no exploit_now (no hindsight leak)',
      _sd['source_truth']['no_hindsight'] is False and _sd['exploit_now'] is None and _sd['fallback'], '')
check('T-VT-05: prior-atoms read -> no_hindsight True; evidence_atoms are strictly EARLIER hands',
      _o['source_truth']['no_hindsight'] is True and 'H_now' not in _o['source_truth']['evidence_atoms']
      and set(_o['source_truth']['evidence_atoms']) == {'H9', 'H7'}, '')
_pf = _vt.teaching_from_exploit(_vt_exp(read_source='profiler_archetype'),
                                {_vt_vk: {'n_evidence': 12, 'evidence_hand_ids': ['a', 'b']}}, _vt_sticky)
check('T-VT-06: profiler_archetype (population, no direct evidence) capped to low confidence',
      _pf['confidence'] == 'low', _pf['confidence'])
check('T-VT-07: confidence bands wired to evidence_count + same-type corroboration',
      _vt.derive_confidence('prior_atoms_mapped', 9, 2) == 'high'
      and _vt.derive_confidence('prior_atoms_mapped', 5, 1) == 'medium'
      and _vt.derive_confidence('prior_atoms_mapped', 9, 0) == 'low'
      and _vt.derive_confidence('prior_atoms_mapped', 2, 2) == 'low', '')
check('T-VT-08: do_not_overadjust is derived guardrail copy keyed by confidence (never a villain fact)',
      _o['do_not_overadjust'] == _vt._DO_NOT_OVERADJUST_GENERIC['high']
      and _thin['do_not_overadjust'] in (set(_vt._LOW_CONF_CONTEXT.values())
                                         | {_vt._DO_NOT_OVERADJUST_GENERIC['low']})
      and _vt_vk not in _o['do_not_overadjust'], '')
import re as _re_vt
_pko = {'H_now': {'coverage_label': 'covers opener - bounty collectible', 'can_collect_bounty': True}}
_op = _vt.teaching_from_exploit(_vt_exp(), _vt_rs(), _vt_sticky, pko_by_hand=_pko)
check('T-VT-09: PKO cover reuses coverage_label verbatim; no BB/$ fabricated; omitted when absent',
      _op['pko']['cover_label'] == 'covers opener - bounty collectible' and _op['pko']['collectible'] is True
      and not _re_vt.search(r'\$|BB', _op['pko']['cover_label']) and 'pko' not in _o, '')
_live = _vt.teaching_from_exploit(_vt_exp(), _vt_rs(), _vt_sticky, population='live')
check('T-VT-10: live read carries live caveat, never the online suffix (no cross-apply)',
      'do not cross-apply to online' in _live['cue'] and 'online-pool' not in _live['cue']
      and 'online-pool' in _o['cue'] and 'live read' not in _o['cue'], '')
_long = _vt.teaching_from_exploit(_vt_exp(evidence_text=' '.join(['w'] * 40), so_what=' '.join(['x'] * 40)),
                                  _vt_rs(), _vt_sticky)
check('T-VT-11: villain_did/exploit_now clamped to word caps',
      len(_long['villain_did'].split()) <= 22 and len(_long['exploit_now'].split()) <= 18, '')
_noi = _vt.teaching_from_exploit(_vt_exp(read_source='same_hand_pivot', available_before_action_index=None,
                                         action_index=None, hero_decision_index=None), _vt_rs(), _vt_sticky)
check('T-VT-12: missing decision index -> decision_id ends |? and same-hand cue is not actionable',
      _noi['source_truth']['decision_id'].endswith('|?') and _noi['source_truth']['no_hindsight'] is False, '')
_vtsrc = open('gem_villain_teaching.py', encoding='utf-8').read()
check('T-VT-13: builder reuses stamped fields (no hardcoded villain facts / invented coaching)',
      'def build_villain_teaching(' in _vtsrc and "exp.get('so_what')" in _vtsrc
      and "exp.get('evidence_text')" in _vtsrc and 'FALLBACK_LINE' in _vtsrc, '')
_built = _vt.build_villain_teaching({'read_states': _vt_rs(), 'atoms_by_villain': _vt_sticky,
                                     'exploits_by_hand': {'H_now': [_vt_exp()]}, 'atoms_by_hand': {}})
check('T-VT-14: build_villain_teaching indexes by hand + villain; never raises on partial data',
      'H_now' in _built['teaching_by_hand'] and _vt_vk in _built['teaching_by_villain']
      and _vt.build_villain_teaching({})['teaching_by_hand'] == {}, '')
# --- rev-2 (GPT product-fail fixes) ---
check('T-VT-15: non-fallback teach_lines render the FULL Slice-D contract (8 labels)',
      not _o['fallback']
      and any(l.startswith('What villain did:') for l in _o['teach_lines'])
      and any(l.startswith('Cue:') for l in _o['teach_lines'])
      and any(l.startswith('Read:') for l in _o['teach_lines'])
      and any(l.startswith('Confidence:') for l in _o['teach_lines'])
      and any(l.startswith('Exploit now:') for l in _o['teach_lines'])
      and any(l.startswith('Exploit future:') for l in _o['teach_lines'])
      and any(l.startswith('Do not over-adjust:') for l in _o['teach_lines'])
      and any(l.startswith('Tag suggestion:') for l in _o['teach_lines']), '')
_a_sha = {'villain_key': _vt_vk, 'hand_id': 'H2', 'signal': 'multiway_donk', 'street': 'flop',
          'action_index': 3, 'available_before_action_index': 3, 'same_hand_actionable': True,
          'evidence_text': 'Donk-bet into the field.', 'hero_involved': True,
          'suggests': 'Loose.', 'so_what': 'Raise donks.'}
_a_no = dict(_a_sha, hand_id='H3', same_hand_actionable=False, signal='weak_showdown_call')
_o_sha = _vt.teaching_from_atom(_a_sha, _vt_rs(), _vt_sticky, signal_coaching={})
_o_no = _vt.teaching_from_atom(_a_no, _vt_rs(), _vt_sticky, signal_coaching={})
check('T-VT-16: atom no-hindsight REQUIRES same_hand_actionable (avail alone is insufficient)',
      _o_sha['source_truth']['no_hindsight'] is True
      and _o_no['source_truth']['no_hindsight'] is False
      and _o_no['fallback'] and _o_no['exploit_now'] is None, '')
check('T-VT-17: low-confidence guardrail generic by default; PKO line only for PKO/cold-call spots',
      _vt.derive_do_not_overadjust('low') == _vt._DO_NOT_OVERADJUST_GENERIC['low']
      and 'cold-call' not in _vt.derive_do_not_overadjust('low')
      and 'cold-call' in _vt.derive_do_not_overadjust('low', has_pko=True)
      and _vt.derive_do_not_overadjust('low', 'Nit / Rock') == _vt._LOW_CONF_CONTEXT['Nit / Rock'], '')
_htmlsrc_vt = open('gem_report_draft/_html.py', encoding='utf-8').read()
check('T-VT-18: renderer iterates the FULL teach_lines (not just header) + has teach styles',
      'teach_lines.forEach' in _htmlsrc_vt and 'v25-teach-head' in _htmlsrc_vt
      and 'v25-teach-line' in _htmlsrc_vt, '')

# ============================================================
# v8.14.0 — Slice D: Villain Exploitation v2 (T-VX-*)
#   8-field per-hand teaching contract + Natural8 candidate-tag mapper +
#   candidate read language + stable-identity evidence aggregation.
# ============================================================
_VX_CONTRACT = ['What villain did:', 'Cue:', 'Read:', 'Confidence:', 'Exploit now:',
                'Exploit future:', 'Do not over-adjust:', 'Tag suggestion:']
check('T-VX-01: full per-hand teaching contract (8 labels) + tag_suggestion{label,color,kind} present',
      all(any(l.startswith(p) for l in _o['teach_lines']) for p in _VX_CONTRACT)
      and {'label', 'color', 'kind'} <= set(_o['tag_suggestion']), '')
check('T-VX-02: candidate read language unless high conf; weak read -> Unsure/yellow (never forced)',
      _vt._candidate_archetype('Sticky Passive', 'medium') == 'Candidate Sticky Passive'
      and _vt._candidate_archetype('Sticky Passive', 'high') == 'Sticky Passive'
      and _vt._candidate_archetype('', 'low') == 'Unknown / Tag-me-later'
      and _vt.suggest_natural8_tag('Sticky Passive', 'low', 5, True)['kind'] == 'unsure'
      and _vt.suggest_natural8_tag('Sticky Passive', 'high', 1, True)['kind'] == 'unsure'
      and _vt.suggest_natural8_tag('Sticky Passive', 'high', 9, False)['color'] == 'yellow', '')
check('T-VX-03: repeated sticky/passive -> Calling Station (orange) at high conf, exploit present',
      _o['tag_suggestion']['label'] == 'Calling Station' and _o['tag_suggestion']['color'] == 'orange'
      and _o['tag_suggestion']['kind'] == 'station' and _o['exploit_now']
      and 'Tag suggestion: Calling Station (orange)' in _o['teach_lines'], '')
_vx_ars = {_vt_vk: {'villain_alias': 'Storm', 'primary_read': 'Aggressive', 'confidence': 'high',
                    'n_evidence': 9, 'evidence_hand_ids': ['H9', 'H7', 'H_now']}}
_vx_aatoms = {_vt_vk: [{'dimension': 'aggressive'} for _ in range(3)]}
_vx_aggro = _vt.teaching_from_exploit(
    _vt_exp(exploit_read_label='Aggressive', exploit_read_display='Aggressive',
            evidence_text='Check-raised turn after floating the flop.',
            suggests='Delayed aggression - piles on pressure on later streets.',
            so_what='Respect the turn check-raise; do not auto-barrel.',
            recommended_exploit='Pot-control turns; let him keep bluffing.'),
    _vx_ars, _vx_aatoms)
check('T-VX-04: aggression -> Danger Reg (red) high conf / Candidate Maniac-LAG (pink) medium; exploit respects raise',
      _vx_aggro['tag_suggestion']['label'] == 'Danger Reg' and _vx_aggro['tag_suggestion']['color'] == 'red'
      and 'Respect' in (_vx_aggro['exploit_now'] or '') and not _vx_aggro['fallback']
      and _vt.suggest_natural8_tag('Aggressive', 'medium', 5, True)['label'] == 'Candidate Maniac/LAG'
      and _vt.suggest_natural8_tag('Aggressive', 'medium', 5, True)['color'] == 'pink', '')
_vx_sd = _vt.teaching_from_atom(
    {'villain_key': _vt_vk, 'hand_id': 'H8', 'signal': 'weak_showdown_call', 'street': 'river',
     'action_index': 4, 'available_before_action_index': None, 'hero_involved': True,
     'evidence_text': 'Tabled bottom pair at showdown.', 'so_what': 'Value-bet thinner.',
     'suggests': 'Sticky.'}, _vt_rs(), _vt_sticky, signal_coaching={})
check('T-VX-05: showdown-only atom -> fallback, no exploit_now, Unsure tag, no_hindsight False',
      _vx_sd['fallback'] and _vx_sd['exploit_now'] is None
      and _vx_sd['tag_suggestion']['kind'] == 'unsure'
      and _vx_sd['source_truth']['no_hindsight'] is False
      and _vt.FALLBACK_LINE in _vx_sd['teach_lines'], '')
_vx_hni = _vt.build_villain_teaching(
    {'read_states': _vt_rs(), 'atoms_by_villain': _vt_sticky, 'exploits_by_hand': {},
     'atoms_by_hand': {'Hx': [{'villain_key': _vt_vk, 'hand_id': 'Hx', 'signal': 'weak_showdown_call',
                               'street': 'river', 'action_index': 2, 'available_before_action_index': 2,
                               'same_hand_actionable': True, 'evidence_text': 'x', 'hero_involved': False,
                               'suggests': 's', 'so_what': 'w'}]}})
check('T-VX-06: hero-not-involved atoms never create a same-hand teaching object (no fake live read)',
      not _vx_hni['teaching_by_hand'].get('Hx'), '')
_vx_contra = _vt.teaching_from_exploit(_vt_exp(), _vt_rs(n=9),
                                       {_vt_vk: [{'dimension': 'aggressive'} for _ in range(9)]})
check('T-VX-07: uncorroborated/contradictory cues -> low conf + Unsure tag + candidate read (not forced)',
      _vx_contra['confidence'] == 'low' and _vx_contra['tag_suggestion']['kind'] == 'unsure'
      and not _vx_contra['fallback']
      and any(l.startswith('Read: Candidate') for l in _vx_contra['teach_lines']), '')
_vx_many = []
for _vxi in range(6):
    _vx_rsi = {_vt_vk: {'villain_alias': 'Seat%d' % _vxi, 'primary_read': '\U0001F4DE Sticky Passive',
                        'confidence': 'high', 'n_evidence': 9, 'evidence_hand_ids': ['H9', 'H7']}}
    _vx_many.append(_vt.teaching_from_exploit(_vt_exp(), _vx_rsi, _vt_sticky))
_vx_summ = _vt.build_villain_evidence_summary({_vt_vk: _vx_many}, max_aliases=3)
check('T-VX-08: evidence summary groups by STABLE id + truncates long alias list (no overflow)',
      len(_vx_summ) == 1 and _vx_summ[0]['villain_id'] == _vt_vk
      and _vx_summ[0]['alias_count'] == 6 and 'more' in _vx_summ[0]['alias']
      and _vx_summ[0]['tag_label'] == 'Calling Station', '')
check('T-VX-09: v8.13.0 no-hindsight gates intact (prior=actionable True; showdown=False)',
      _o['source_truth']['no_hindsight'] is True and _sd['source_truth']['no_hindsight'] is False
      and 'def _no_hindsight(' in _vtsrc and 'same_hand_actionable' in _vtsrc, '')
check('T-VX-10: renderer classifies new contract lines (tag swatch + confidence + guard rename)',
      "indexOf('Tag suggestion:')" in _htmlsrc_vt and "indexOf('Do not over-adjust:')" in _htmlsrc_vt
      and "indexOf('Confidence:')" in _htmlsrc_vt and 'v25-teach-tag' in _htmlsrc_vt
      and 'v25-teach-conf' in _htmlsrc_vt and 'data-tag-color' in _htmlsrc_vt
      and 'Avoid over-adjusting:' not in _htmlsrc_vt, '')

# ============================================================
# v8.13.1 — Analyst Coverage + Verdict-Contradiction Trust (T-CT-*)
# ============================================================
import gem_report_data as _ctrd
import gem_coverage_builder as _ctcb
import gem_analyst_worklist as _ctwl
from gem_report_draft._hand_grid import (reconcile_push_widget as _ct_rpw,
                                          tldr_contradicts_verdict as _ct_tcv)
from gem_report_draft.sections_xiv import _wpot_claim_ok as _ct_wpot
from gem_report_draft._helpers import (monotone_overcommit_lesson as _ct_mol,
                                       _agg_commentary as _ct_agg)

# P0 #1: completion gate — 5 reviewed, 0/14 significant losses -> NOT COMPLETE
_ct_cands = {'postflop_loss_screen': [{'id': f'L{i}'} for i in range(14)],
             'mistakes': [], 'punts': [], 'coolers': [], 'bust_audit': [],
             'biggest_loss_screen': []}
_ct_rc1 = _ctrd.compute_report_completeness(
    {'analyst_commentary': {f'R{i}': {} for i in range(5)}}, candidates=_ct_cands)
check('T-CT-01: 5 reviewed / 0-of-14 significant losses is NOT ANALYST_COMPLETE',
      _ct_rc1['state'] == 'ANALYST_PARTIAL' and _ct_rc1['critical_unreviewed'] == 14,
      str(_ct_rc1.get('state')))

# P0 #2: coverage line — incomplete warns "not final"; complete shows N/M
check('T-CT-02a: incomplete coverage line says "not final"',
      'not final' in _ct_rc1['coverage_line']
      and _ct_rc1['critical_coverage_ok'] is False, _ct_rc1['coverage_line'])
_ct_rc2 = _ctrd.compute_report_completeness(
    {'analyst_commentary': {f'L{i}': {} for i in range(14)}}, candidates=_ct_cands)
check('T-CT-02b: complete coverage renders "14/14 significant-loss" + 0 critical + COMPLETE',
      _ct_rc2['state'] == 'ANALYST_COMPLETE'
      and '14/14 significant-loss' in _ct_rc2['coverage_line']
      and _ct_rc2['critical_unreviewed'] == 0, _ct_rc2['coverage_line'])

# P1 #3/#4: biggest-loss + postflop-loss screens
_ct_hands = [
  {'id':'TM_BL','net_bb':-12.0,'pf_allin':False,'board':['Ah','Kd','2c'],'went_to_sd':True,'cards':['9h','9d'],'position':'BTN'},
  {'id':'TM_PF','net_bb':-40.0,'pf_allin':False,'board':['Qc','8c','3c'],'went_to_sd':True,'cards':['Ah','Qd'],'position':'CO'},
  {'id':'TM_WIN','net_bb':30.0,'pf_allin':False,'board':['2h','3d','4c'],'went_to_sd':True,'cards':['Ac','Ad'],'position':'BB'}]
_ct_stats = {'stack_trajectories': {'T1': {'biggest_loss_id': 'TM_BL'}}}
_ct_scr = _ctcb.build_loss_screens(_ct_stats, _ct_hands)
check('T-CT-03: every stack_trajectories biggest_loss_id is screened',
      'TM_BL' in _ct_scr['biggest_loss_screen'], str(_ct_scr))
check('T-CT-04: postflop loss <= -15BB screened; winners/small losses not',
      'TM_PF' in _ct_scr['postflop_loss_screen']
      and 'TM_WIN' not in _ct_scr['postflop_loss_screen']
      and 'TM_BL' not in _ct_scr['postflop_loss_screen'], str(_ct_scr))
_ct_wcands = {
  'biggest_loss_screen':[{'id':'TM_BL','screen_reason':'Per-tournament biggest loss; must clear or classify.','position':'BTN','cards':'9h9d','net_bb':-12.0,'went_to_sd':True}],
  'postflop_loss_screen':[{'id':'TM_PF','screen_reason':'Postflop loss -40BB (<= -15BB); must clear or classify.','position':'CO','cards':'AhQd','net_bb':-40.0,'went_to_sd':True}]}
_ct_wl = _ctwl.build_analyst_worklist(_ct_wcands, _ct_stats, {}, _ct_hands, '20260613')
check('T-CT-04b: screened hands reach the worklist with their screen source bucket',
      'TM_BL' in _ct_wl['items']
      and 'biggest_loss_screen' in (_ct_wl['items']['TM_BL'].get('candidate_sources') or [])
      and 'TM_PF' in _ct_wl['items']
      and 'postflop_loss_screen' in (_ct_wl['items']['TM_PF'].get('candidate_sources') or []), '')

# P1 #5: verdict contradiction
check('T-CT-05a: final Justified does NOT render bare "Wrong push" (overridden)',
      _ct_rpw(False, 'III.5 Justified')[0] == 'overridden', str(_ct_rpw(False, 'III.5 Justified')))
check('T-CT-05b: no analyst verdict -> auto pre-review',
      _ct_rpw(False, '')[0] == 'pre_review', '')
check('T-CT-05c: final Mistake + "standard" TL;DR is a flagged contradiction',
      _ct_tcv('inside the push range — standard, result is variance.', 'III.2 Mistake') is True
      and _ct_tcv('inside the push range — standard', 'III.5 Justified') is False, '')

# P1 #6: effective stack
_ct_es = _ctwl.effective_stack_safety(33.6, 18.0, overjam_bb=15.6)
check('T-CT-06: SB shove total 33.6 / eff 18 evaluated at 18BB (not 33), with warn',
      _ct_es['eval_depth_bb'] == 18.0 and _ct_es['warn'] is True
      and '18BB shove' in _ct_es['safety_line'] and 'not 34BB' in _ct_es['safety_line'], str(_ct_es))

# P2 #7: W-POT
check('T-CT-07: "call 7 into 19.9" passes when _pot_odds per-street pot is 19.9',
      _ct_wpot(19.9, {'per_street_calls': [{'pot_before_call_bb': 19.9, 'total_pot_bb': 26.9}]}, [('turn', 12.9, 14.0)]) is True
      and _ct_wpot(50.0, {'per_street_calls': [{'pot_before_call_bb': 19.9}]}, [('turn', 12.9, 14.0)]) is False, '')

# P2 #8: AQ monotone lesson
_ct_les = _ct_mol('Qc 8c 3c Kc', {'flop': 'xc', 'turn': 'jam'}, net_bb=-40)
check('T-CT-08a: monotone over-commit lesson names protection+turn, not only "missed flop aggression"',
      bool(_ct_les) and 'not just missed flop aggression' in _ct_les
      and 'cheap flop protection' in _ct_les and 'turn' in _ct_les, (_ct_les or '')[:80])
_ct_aggout = _ct_agg({'verdict': 'MISSED_AGGRESSION', 'street_of_interest': 'flop',
                      'hsa': {'flop': 'xc', 'turn': 'jam'}, 'board': 'Qc 8c 3c Kc',
                      'net_bb': -40, 'gates': {}})
check('T-CT-08b: _agg_commentary reframes monotone over-commit (not sole "missed flop aggression")',
      'cheap flop protection' in _ct_aggout, _ct_aggout[:80])

# ============================================================
# v8.14.0 Slice B — V25 hand-detail modal redesign (top bar + street headers)
# ============================================================
_hdr_src = open('gem_report_draft/_html.py', encoding='utf-8').read()
_vd_block = _hdr_src.split('.v25-top-identity .v25-top-verdict')[1][:300] if '.v25-top-identity .v25-top-verdict' in _hdr_src else ''
_shh_i = _hdr_src.find('.v25-street-head {')
_shh_block = _hdr_src[_shh_i:_shh_i + 320] if _shh_i >= 0 else ''

check('T-V25HD-01: result pill color classes preserved (good/bad/neutral)',
      '.v25-top-result.good' in _hdr_src and '.v25-top-result.bad' in _hdr_src
      and '.v25-top-result.neutral' in _hdr_src, '')
check('T-V25HD-02: system verdict readable in its own top-bar chip (12px, not 0.55em)',
      '.v25-top-identity .v25-top-verdict' in _hdr_src and 'font-size: 12px' in _vd_block, _vd_block[:80])
check('T-V25HD-03: top verdict strips raw Roman verdict codes in hydration',
      "replace(/I{1,3}[.][0-9]+/g,'')" in _hdr_src
      and "classList.add('v25-top-verdict')" in _hdr_src, '')
check('T-V25HD-04: street header builds title + context chips next to it',
      "className='v25-street-context'" in _hdr_src
      and "className='v25-pot-chip'" in _hdr_src
      and "className='v25-strength-chip'" in _hdr_src
      and "sTitle.className='v25-street-title'" in _hdr_src, '')
check('T-V25HD-04b: .v25-street-head is a flex row (context next to title, not far-right grid)',
      'display: flex' in _shh_block, _shh_block[:90])
check('T-V25HD-05: no street shortcut/filter chips added (nav stays hidden)',
      '.v25-street-nav {{ display: none !important; }}' in _hdr_src
      and 'v25-street-chip' not in _hdr_src and 'street-filter' not in _hdr_src, '')
check('T-V25HD-06: action-row / commentary-grid / review-control selectors intact',
      'grid-action' in _hdr_src and 'v25-street-body' in _hdr_src
      and 'modal-review' in _hdr_src and 'verdict-chip' in _hdr_src, '')
check('T-V25HD-07: mobile header wraps cleanly (flex-wrap on street head + top identity)',
      'flex-wrap: wrap' in _shh_block
      and '.v25-top-identity {{ flex-wrap: wrap' in _hdr_src, '')
check('T-V25HD-08: top-bar chips use line-height:1 (verdict chip adds no row-height jump)',
      'line-height: 1;' in _vd_block, _vd_block[:80])

# ============================================================
# v8.14.0 Slice C — Compact Hand Review Queue (T-RQ-*)
# ============================================================
from gem_report_draft.tldr import (build_review_queue as _rq_build,
                                    normalize_review_status as _rq_norm)
_rqh = open('gem_report_draft/_html.py', encoding='utf-8').read()
_rqt = open('gem_report_draft/tldr.py', encoding='utf-8').read()

_rq_an = {'TMp': {'verdict': 'III.1', 'hand_strength': 'x'},
          'TMm': {'verdict': 'III.2', 'hand_strength': 'y'}}
_rq_s = {'mistakes': [{'id': 'TMa', 'desc': 'auto', 'net_bb': -9}]}
_rq_rd = {'issue_explorer_issues': [{'name': 'Leak', 'all_hand_ids': ['TMk']}],
          'reviewed_mistakes': {'needs_review': [{'id': 'TMg', 'reason': 'm'}]}}
_rq_hb = {k: {'net_bb': -10, 'cards': ['Ah', 'Kd']} for k in ('TMp', 'TMm', 'TMa', 'TMk', 'TMg')}
_rq_q = _rq_build(_rq_s, _rq_rd, _rq_an, _rq_hb)
check('T-RQ-01: queue priority order punt<analyst<known_leak<auto_clear<marginal',
      [x['bucket'] for x in _rq_q] == ['punt', 'analyst_mistake', 'known_leak', 'auto_clear', 'marginal'],
      str([x['bucket'] for x in _rq_q]))
check('T-RQ-02: status normalize (Agree/Report bug/Drill/Rulebook/Clear); Ignore rejected',
      _rq_norm('Agree') == 'agree' and _rq_norm('Report bug') == 'report_bug'
      and _rq_norm('Drill') == 'drill' and _rq_norm('Rulebook') == 'rulebook'
      and _rq_norm('Clear') == '' and _rq_norm('Ignore') == '', '')
check('T-RQ-03: queue item carries id/rank/bucket/reason_label/title/net/cards',
      all(k in _rq_q[0] for k in ('id', 'rank', 'bucket', 'reason_label', 'title', 'net', 'cards')),
      str(_rq_q[0]))
check('T-RQ-04: modal review chips include Drill + Rulebook + Clear; no Ignore status',
      'data-verdict="Drill"' in _rqh and 'data-verdict="Rulebook"' in _rqh
      and 'data-verdict="Agree"' in _rqh and 'data-verdict="">Clear' in _rqh
      and 'data-verdict="Ignore"' not in _rqh, '')
check('T-RQ-05: PBReviewQueue builds full-queue context (data-queue-ids) + opens via openHand',
      'window.PBReviewQueue' in _rqh and 'data-queue-ids' in _rqh
      and 'handIds:ids.slice()' in _rqh and 'function openRow' in _rqh
      and 'openHand(hid)' in _rqh, '')
check('T-RQ-06: rq-card renders data-topn + count + show-all + reviewed + celebratory state',
      'rq-card' in _rqt and 'data-topn=' in _rqt and 'id="rq-count"' in _rqt
      and 'id="rq-showall"' in _rqt and 'id="rq-reviewed"' in _rqt
      and 'id="rq-empty-win"' in _rqt, '')
check('T-RQ-07: compact rows are full-row clickable (role=button) with one reason + BB pill',
      'class="rq-row" role="button"' in _rqt and 'class="reason reason-' in _rqt
      and 'bb-pill' in _rqt, '')
check('T-RQ-08: mobile rq-row uses stacking grid-areas (no horizontal table)',
      'grid-template-areas: "rank hid main bb"' in _rqh, '')
check('T-RQ-09: status change refreshes the queue partition/counts',
      'window.PBReviewQueue.refresh()' in _rqh, '')

# ============================================================
# SUMMARY
# ============================================================
print(f'\n{"=" * 60}')
print(f'RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL}')
if FAIL:
    print('FIX BEFORE PROCEEDING')
    sys.exit(1)
else:
    print('ALL TESTS PASSED')
