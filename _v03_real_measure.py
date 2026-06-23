"""v8.21 deep-validation: REAL-session measurement of the corrected sizing detector.

Parses the approved real raw sessions with the canonical gem_parser (v8.21 runtime), runs the corrected
detector through gem_discovery_context, and emits provenance + opportunity baseline + nomination queue +
overlap into v03_pilot/. NO parallel calculation; fixtures are excluded by construction (real GG only).
"""
import json
import os
import hashlib
import time
import gem_parser
import gem_sizing_detector as SD
import gem_discovery_context as DC
import gem_analyst_packet as AP
import gem_textures as T

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v03_pilot')
os.makedirs(OUT, exist_ok=True)

SESSIONS = [
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_live_test', 'session_live_test_2026-06-04'),
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\hh_today', 'hh_today_2026-06-09'),
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_20260527', 'session_2026-05-27'),
]

POSTFLOP_LOSS_BB = -15.0   # gem_coverage_builder.POSTFLOP_LOSS_SCREEN_BB (material-loss proxy)


def _sha256_dir_txt(d):
    h = hashlib.sha256()
    files = sorted(f for f in os.listdir(d) if f.lower().endswith('.txt'))
    per = []
    for f in files:
        p = os.path.join(d, f)
        try:
            b = open(p, 'rb').read()
        except Exception:
            continue
        fh = hashlib.sha256(b).hexdigest()
        h.update(fh.encode())
        per.append({'file': f, 'sha256': fh, 'bytes': len(b)})
    return h.hexdigest(), per


def assess_population(hands):
    """Eligible-opportunity census with the corrected gates; pure counting, no verdicts."""
    c = dict(reached_flop=0, pfr_cbet=0, clean_single=0, excl_non_srp=0, excl_multiway=0,
             excl_all_in=0, excl_unknown_arch=0, excl_no_band=0, judgeable=0, compliant=0,
             off_band=0, gross=0, moderate=0)
    for h in hands:
        if len(h.get('board') or []) >= 3:
            c['reached_flop'] += 1
        if not h.get('pfr') or SD._flop_cbet_sizing_pct(h) is None:
            continue
        c['pfr_cbet'] += 1
        hflop = [a for a in (h.get('action_ledger') or [])
                 if a.get('street') == 'flop' and a.get('player') == 'Hero']
        if len(hflop) != 1 or (hflop[0].get('action') or '') != 'bets':
            continue
        c['clean_single'] += 1
        applies, why = SD._chart_applies(h)
        if not applies:
            c['excl_' + {'pot_type_not_srp': 'non_srp', 'multiway_flop': 'multiway',
                         'all_in_cbet': 'all_in'}[why]] += 1
            continue
        board = (h.get('board') or [])[:3]
        arch = h.get('board_archetype') or ''
        if not arch or arch == 'unknown':
            arch = T.classify_archetype(board)
        if not arch or arch == 'unknown':
            c['excl_unknown_arch'] += 1
            continue
        meta = T.archetype_meta(arch) or {}
        side = 'ip' if h.get('hero_ip') else 'oop'
        depth = h.get('eff_stack_bb') or h.get('stack_bb') or 100
        tgt = T.get_gto_target(arch, side, depth)
        if meta.get('confidence') != 'complete' or not tgt or not tgt.get('sizings_pct'):
            c['excl_no_band'] += 1
            continue
        c['judgeable'] += 1
        a = SD.assess_flop_cbet_sizing(h)
        if a is None:
            c['compliant'] += 1
        else:
            c['off_band'] += 1
            c['gross' if a['severity'] == 'gross' else 'moderate'] += 1
    return c


def main():
    provenance = {'runtime': {'parser_schema_version': gem_parser.PARSER_SCHEMA_VERSION,
                              'detector': 'gem_sizing_detector.assess_flop_cbet_sizing (corrected: SRP/HU/non-all-in)',
                              'measured_at_commit_parent': '63b00e7'},
                  'sessions': []}
    all_hands = []
    per_session = []
    t0 = time.perf_counter()
    for path, name in SESSIONS:
        if not os.path.isdir(path):
            provenance['sessions'].append({'name': name, 'path': path, 'status': 'MISSING'})
            continue
        hands, tours, nfiles, errs = gem_parser.parse_session(path)
        dh, per = _sha256_dir_txt(path)
        provenance['sessions'].append({
            'name': name, 'path': path, 'status': 'OK', 'files': nfiles, 'hands': len(hands),
            'tournaments': len(tours), 'parse_errors': errs, 'inputs_sha256': dh, 'input_files': per})
        for h in hands:
            h['_session'] = name
        all_hands += hands
        per_session.append((name, hands))
    parse_s = time.perf_counter() - t0
    json.dump(provenance, open(os.path.join(OUT, 'REAL_CORPUS_PROVENANCE.json'), 'w', encoding='utf-8'),
              indent=2)

    # opportunity baseline (combined + per session)
    base = {'combined': assess_population(all_hands),
            'per_session': {name: assess_population(h) for name, h in per_session},
            'n_hands_total': len(all_hands)}
    json.dump(base, open(os.path.join(OUT, 'REAL_OPPORTUNITY_BASELINE.json'), 'w', encoding='utf-8'), indent=2)

    # nominations through the canonical pipeline
    t1 = time.perf_counter()
    val = DC.run_value(all_hands, {}, session='real_combined')
    run_s = time.perf_counter() - t1
    sizing = [c for c in val['candidates'] if c['family'] == 'flop_cbet_sizing']
    other_hand_ids = {c['hand_id'] for c in val['candidates'] if c['family'] != 'flop_cbet_sizing'}
    hbi = {h['id']: h for h in all_hands}
    loss_ids = {h['id'] for h in all_hands if isinstance(h.get('net_bb'), (int, float))
                and h['net_bb'] <= POSTFLOP_LOSS_BB}

    queue = []
    for c in sizing:
        rec = AP._norm_decision(c, hbi)
        a = c['context']['sizing_assessment']
        h = hbi[c['hand_id']]
        queue.append({
            'decision_id': rec['decision_id'], 'hand_id': c['hand_id'],
            'session': h.get('_session'), 'severity': a['severity'],
            'board': rec.get('board'), 'archetype': a['board_archetype'], 'side': a['cbet_side'],
            'made_hand_class': rec.get('made_hand_class'), 'position': rec.get('position'),
            'eff_stack_bb': rec.get('eff_stack_bb'), 'pot_before_bb': rec.get('pot_before_bb'),
            'chosen_incremental_bb': rec.get('chosen_incremental_bb'),
            'actual_sizing_pct': a['actual_sizing_pct'], 'target_sizings_pct': a['target_sizings_pct'],
            'deviation_pp': a['deviation_pp'], 'direction': a['direction'],
            'overlap_other_family': c['hand_id'] in other_hand_ids,
            'overlap_material_loss': c['hand_id'] in loss_ids,
            'atomic_record': rec,
        })
    json.dump({'session': 'real_combined', 'count': len(queue), 'records': queue},
              open(os.path.join(OUT, 'REAL_CANDIDATE_QUEUE.json'), 'w', encoding='utf-8'),
              indent=2, default=str)

    # semantic audit over the real records
    recs = [q['atomic_record'] for q in queue]
    sa = AP.semantic_audit({'required': recs, 'optional': []}) if recs else {
        'failing': 0, 'future_information_leaks': 0, 'zero_analyst_calculations_required': True}

    print('REAL CORPUS:', len(all_hands), 'hands across', len([s for s in provenance['sessions'] if s.get('status') == 'OK']), 'sessions; parse %.1fs' % parse_s)
    print('opportunity (combined):', json.dumps(base['combined']))
    print('sizing nominations:', len(sizing), '| gross:', sum(1 for q in queue if q['severity'] == 'gross'),
          '| moderate:', sum(1 for q in queue if q['severity'] == 'moderate'))
    print('overlap other-family:', sum(1 for q in queue if q['overlap_other_family']),
          '| overlap material-loss:', sum(1 for q in queue if q['overlap_material_loss']))
    print('semantic audit: failing=%s leaks=%s zero_calc=%s' % (sa['failing'], sa['future_information_leaks'], sa['zero_analyst_calculations_required']))
    print('run_value over %d hands: %.3fs' % (len(all_hands), run_s))
    print('wrote REAL_CORPUS_PROVENANCE / REAL_OPPORTUNITY_BASELINE / REAL_CANDIDATE_QUEUE -> v03_pilot/')
    # compact nomination preview for the analyst pass
    for q in queue:
        print('  >>', q['hand_id'], q['session'], '|', '-'.join(q['board']), q['archetype'], q['side'],
              '| %.0f%% vs %s (%s %.0fpp %s) | made=%s pot=%.1f bet=%.1f eff=%.1f | ovl_other=%s ovl_loss=%s'
              % (q['actual_sizing_pct'], q['target_sizings_pct'], q['direction'], q['deviation_pp'],
                 q['severity'], q['made_hand_class'], q['pot_before_bb'] or 0, q['chosen_incremental_bb'] or 0,
                 q['eff_stack_bb'] or 0, q['overlap_other_family'], q['overlap_material_loss']))


if __name__ == '__main__':
    main()
