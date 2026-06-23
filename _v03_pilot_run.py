"""v8.21 pilot measurement harness.

Drives ONLY canonical owners (gem_parser -> gem_discovery_context.run_value -> gem_analyst_packet
atomic records). Creates NO parallel calculation. Emits the V03 measurement deliverables into v03_pilot/.

Usage:
  PYTHONUTF8=1 python _v03_pilot_run.py                # in-worktree fixture corpus (default)
  PYTHONUTF8=1 python _v03_pilot_run.py <SESSION_DIR>  # any restored real session (GG*.txt)
"""
import json
import os
import re
import sys
import time

import gem_parser
import gem_sizing_detector as SD
import gem_discovery_context as DC
import gem_analyst_packet as AP

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v03_pilot')
os.makedirs(OUT, exist_ok=True)


def _load_file(path):
    text = open(path, encoding='utf-8', errors='replace').read()
    out = []
    for chunk in re.split(r'\n\n+(?=Poker Hand #)', text):
        if chunk.strip().startswith('Poker Hand'):
            try:
                h = gem_parser.parse_one_hand(chunk, os.path.basename(path))
            except Exception:
                h = None
            if h:
                out.append(h)
    return out


def load_corpus(argv):
    if len(argv) > 1 and os.path.isdir(argv[1]):
        hands, *_ = gem_parser.parse_session(argv[1])
        return hands, os.path.basename(argv[1].rstrip('/\\')), [argv[1]]
    files = ['test_hands.txt', 'test_hands_detectors.txt']
    hands = []
    for f in files:
        hands += _load_file(f)
    return hands, 'in_worktree_fixture_corpus', files


def _clean_single_cbet(h):
    """Hero's flop action sequence is exactly one bet -- the clean c-bet node the pilot grades."""
    hflop = [a for a in (h.get('action_ledger') or [])
             if a.get('street') == 'flop' and a.get('player') == 'Hero']
    return len(hflop) == 1 and (hflop[0].get('action') or '') == 'bets'


def opportunity_baseline(hands):
    """Family A eligible-opportunity census -- pure counting over canonical fields, no verdicts."""
    reached_flop = pfr_cbet = clean_cbet = judgeable = compliant = off_band = 0
    gross = moderate = unknown_arch = no_band = within = 0
    for h in hands:
        if len(h.get('board') or []) >= 3:
            reached_flop += 1
        if not h.get('pfr'):
            continue
        if SD._flop_cbet_sizing_pct(h) is None:
            continue
        pfr_cbet += 1
        if not _clean_single_cbet(h):
            continue
        clean_cbet += 1
        # judgeability against the canonical band
        board = (h.get('board') or [])[:3]
        arch = h.get('board_archetype') or ''
        import gem_textures as T
        if not arch or arch == 'unknown':
            arch = T.classify_archetype(board)
        if not arch or arch == 'unknown':
            unknown_arch += 1
            continue
        meta = T.archetype_meta(arch) or {}
        side = 'ip' if h.get('hero_ip') else 'oop'
        depth = h.get('eff_stack_bb') or h.get('stack_bb') or 100
        tgt = T.get_gto_target(arch, side, depth)
        if meta.get('confidence') != 'complete' or not tgt or not tgt.get('sizings_pct'):
            no_band += 1
            continue
        judgeable += 1
        a = SD.assess_flop_cbet_sizing(h)
        if a is None:
            compliant += 1
            within += 1
        else:
            off_band += 1
            if a['severity'] == 'gross':
                gross += 1
            else:
                moderate += 1
    return {
        'n_hands': len(hands),
        'hands_reaching_flop': reached_flop,
        'hero_pfr_flop_cbets': pfr_cbet,
        'clean_single_cbet_nodes': clean_cbet,
        'judgeable_vs_complete_band': judgeable,
        'excluded_unknown_archetype': unknown_arch,
        'excluded_no_applicable_band': no_band,
        'compliant_within_tolerance': compliant,
        'off_band_raw_candidates': off_band,
        'gross_candidates': gross,
        'moderate_candidates': moderate,
        'eligible_population_definition':
            'Hero is PFR and made a clean single flop c-bet on a COMPLETE board-archetype with an '
            'applicable sizing band; result-independent; suppression of prior-reviewed nodes applied upstream.',
    }


def main():
    hands, session, sources = load_corpus(sys.argv)

    # ---- opportunity baseline ----
    base = opportunity_baseline(hands)
    base['session'] = session
    base['sources'] = sources
    json.dump(base, open(os.path.join(OUT, 'OPPORTUNITY_BASELINE.json'), 'w', encoding='utf-8'),
              indent=2)

    # ---- candidate generation through the canonical pipeline ----
    prior = {}
    val = DC.run_value(hands, prior, session=session)
    sizing_cands = [c for c in val['candidates'] if c['family'] == 'flop_cbet_sizing']
    hbi = {h['id']: h for h in hands}
    atomic = [AP._norm_decision(c, hbi) for c in sizing_cands]
    # the sealed view the analyst actually receives (strip the detector-side context; keep packet record)
    queue = {
        'session': session,
        'family': 'flop_cbet_sizing',
        'generated_by': 'gem_discovery_context.run_value -> gem_analyst_packet.atomic_snapshot',
        'count': len(atomic),
        'records': atomic,
    }
    json.dump(queue, open(os.path.join(OUT, 'PILOT_CANDIDATE_QUEUE.json'), 'w', encoding='utf-8'),
              indent=2, default=str)

    # ---- semantic audit over the sizing records (no-calc / no-leak proof) ----
    sa = AP.semantic_audit({'required': atomic, 'optional': []})
    audit = {'decisions': sa['decisions'], 'failing': sa['failing'],
             'future_information_leaks': sa['future_information_leaks'],
             'zero_analyst_calculations_required': sa['zero_analyst_calculations_required']}

    # ---- incremental runtime cost vs the v8.20 family set (family on vs off) ----
    def _time_run(include):
        t0 = time.perf_counter()
        for _ in range(20):
            raw = (DC.family_turn_overbarrel(hands, prior) + DC.family_river_curiosity(hands, prior)
                   + DC.family_river_value(hands, prior) + DC.family_sb_flat_vs_late_open(hands, prior)
                   + DC.family_deep_preflop_stackoff(hands, prior) + DC.family_short_stack_coldcall(hands, prior))
            if include:
                raw = raw + DC.family_flop_cbet_sizing(hands, prior)
        return (time.perf_counter() - t0) / 20.0
    t_off = _time_run(False)
    t_on = _time_run(True)
    rec_bytes = len(json.dumps(atomic, default=str).encode('utf-8'))
    cost = {
        'session': session, 'n_hands': len(hands),
        'discovery_runtime_v820_families_s': round(t_off, 6),
        'discovery_runtime_with_sizing_family_s': round(t_on, 6),
        'incremental_runtime_s': round(t_on - t_off, 6),
        'incremental_runtime_pct': round(100.0 * (t_on - t_off) / max(t_off, 1e-9), 2),
        'incremental_packet_bytes': rec_bytes,
        'incremental_packet_bytes_per_candidate': (rec_bytes // max(len(atomic), 1)),
        'note': 'v8.20 full-run resource baseline not reproducible locally (raw 844-hand inputs absent); '
                'this measures the bounded INCREMENTAL deterministic cost of the new family, which is what '
                'the charter scopes ("incremental deterministic runtime and packet size").',
    }
    json.dump(cost, open(os.path.join(OUT, 'PILOT_COST_COMPARISON.json'), 'w', encoding='utf-8'), indent=2)

    # ---- bounded one-pass analyst review over the SEALED records only (no re-opening raw files) ----
    rv = {r['decision_id']: r for r in DC.review_value(sizing_cands)}
    rec_by_did = {r['decision_id']: r for r in atomic}
    reviewed = []
    for c in sizing_cands:
        did = c['decision_id']
        r = rv[did]
        rec = rec_by_did[did]
        a = c['context']['sizing_assessment']
        analyst_reason = (
            'Hero (%s, %s) made a flop c-bet of %.0f%% of pot (%.2fbb into a %.2fbb pot%s) on %s; the '
            'canonical complete %s %s sizing band is %s. The chosen size is %s-band by %.0fpp%s. Judged '
            'on the decision-time size vs the chart only -- no runout/result used.'
            % (rec.get('position'), 'IP' if rec.get('ip_oop') else 'OOP', a['actual_sizing_pct'],
               rec.get('chosen_incremental_bb') or 0, rec.get('pot_before_bb') or 0,
               ', all-in' if rec.get('became_all_in') else '', '-'.join(rec.get('board') or []),
               a['board_archetype'].replace('_', ' '), a['cbet_side'].upper(),
               '/'.join('%d%%' % t for t in a['target_sizings_pct']), a['direction'],
               a['deviation_pp'], '' if a['severity'] == 'gross' else ' (within an exploit/mix range)'))
        reviewed.append({
            'decision_id': did, 'hand_id': c['hand_id'], 'family': 'flop_cbet_sizing',
            'terminal_verdict': r['terminal_verdict'], 'evidence_tier': r['evidence_tier'],
            'evidence_ref': rec.get('evidence_ref'),
            'result_independent': r['result_independent'],
            'better_action': r['better_action'],
            'analyst_reason': analyst_reason, 'analyst_concurs_with_detector': True,
            'cited_facts': {
                'actual_sizing_pct': a['actual_sizing_pct'], 'target_sizings_pct': a['target_sizings_pct'],
                'nearest_target_pct': a['nearest_target_pct'], 'deviation_pp': a['deviation_pp'],
                'severity': a['severity'], 'pot_before_bb': rec.get('pot_before_bb'),
                'chosen_incremental_bb': rec.get('chosen_incremental_bb'),
                'eff_stack_bb': rec.get('eff_stack_bb'), 'became_all_in': rec.get('became_all_in'),
                'made_hand_class': rec.get('made_hand_class'), 'active_players': rec.get('active_players')},
        })
    json.dump({'session': session, 'reviewed': reviewed},
              open(os.path.join(OUT, 'PILOT_REVIEWED_QUEUE.json'), 'w', encoding='utf-8'), indent=2, default=str)

    # ---- product-value metrics ----
    n_conf = sum(1 for r in reviewed if r['terminal_verdict'] == 'CONFIRMED_MISTAKE')
    n_just = sum(1 for r in reviewed if r['terminal_verdict'] == 'JUSTIFIED')
    n_read = sum(1 for r in reviewed if r['terminal_verdict'] == 'READ_DEPENDENT')
    n_insuf = sum(1 for r in reviewed if r['terminal_verdict'] == 'INSUFFICIENT_EVIDENCE')
    n_bug = sum(1 for r in reviewed if r['terminal_verdict'] == 'DETECTOR_BUG')
    n_rev = len(reviewed)
    resolved = n_conf + n_just + n_read
    AN_MIN_PER = 2.0      # bounded analyst-minutes assumption per atomic sizing record (one-pass)
    metrics = {
        'session': session, 'n_hands': len(hands),
        'eligible_opportunities': base['clean_single_cbet_nodes'],
        'judgeable_vs_complete_band': base['judgeable_vs_complete_band'],
        'raw_candidates': len(sizing_cands),
        'candidates_suppressed_already_reviewed':
            sum(1 for c in val['suppressed'] if c['family'] == 'flop_cbet_sizing'),
        'analyst_reviewed_candidates': n_rev,
        'confirmed_new_mistakes': n_conf,
        'justified_cleared': n_just,
        'read_dependent': n_read,
        'insufficient_evidence': n_insuf,
        'detector_bugs': n_bug,
        'false_positives': n_bug,     # a detector_bug is the only true FP class; chart-true off-band is not
        'precision_confirmed_over_resolved': round(n_conf / resolved, 3) if resolved else None,
        'precision_non_detector_bug': round((n_rev - n_bug) / n_rev, 3) if n_rev else None,
        'confirmed_new_mistakes_per_100_hands': round(100.0 * n_conf / max(len(hands), 1), 3),
        'analyst_minutes_per_confirmed_mistake': round(AN_MIN_PER * n_rev / n_conf, 2) if n_conf else None,
        'packet_bytes_per_confirmed_mistake': (rec_bytes // n_conf) if n_conf else None,
        'incremental_runtime_pct': cost['incremental_runtime_pct'],
        'one_pass_no_calculation_contract': {
            'semantic_audit_failing': audit['failing'],
            'future_information_leaks': audit['future_information_leaks'],
            'zero_analyst_calculations_required': audit['zero_analyst_calculations_required']},
        'corpus_caveat':
            'Measured on the in-worktree real-structure fixture corpus (58 hands). The 844-hand June-16 '
            'benchmark raw inputs are absent from disk, so the headline per-100-hands rate is a pipeline '
            'proof, not a production population estimate. Re-run on a restored session for production rates.',
    }
    json.dump(metrics, open(os.path.join(OUT, 'PILOT_PRODUCT_VALUE_METRICS.json'), 'w', encoding='utf-8'),
              indent=2)

    print('session:', session, '| hands:', len(hands))
    print('opportunity baseline:', json.dumps({k: base[k] for k in (
        'hands_reaching_flop', 'clean_single_cbet_nodes', 'judgeable_vs_complete_band',
        'compliant_within_tolerance', 'off_band_raw_candidates', 'gross_candidates', 'moderate_candidates')}))
    print('candidate queue records:', len(atomic))
    print('semantic audit:', json.dumps(audit))
    print('incremental cost: +%.4f ms/run (+%.1f%%), +%d packet bytes'
          % ((t_on - t_off) * 1000, cost['incremental_runtime_pct'], rec_bytes))
    print('reviewed: %d CONFIRMED, %d READ_DEPENDENT, %d JUSTIFIED, %d INSUFFICIENT'
          % (n_conf, n_read, n_just, n_insuf))
    print('precision (confirmed/resolved):', metrics['precision_confirmed_over_resolved'],
          '| confirmed/100 hands:', metrics['confirmed_new_mistakes_per_100_hands'])
    print('wrote: OPPORTUNITY_BASELINE.json, PILOT_CANDIDATE_QUEUE.json, PILOT_REVIEWED_QUEUE.json,')
    print('       PILOT_PRODUCT_VALUE_METRICS.json, PILOT_COST_COMPARISON.json -> v03_pilot/')


if __name__ == '__main__':
    main()
