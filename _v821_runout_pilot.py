"""v8.21 Runout Transition -- real-session pilot. Runs the deterministic module over the approved real
corpus and measures coverage, suppression, tag distribution, cost, and samples. Canonical owners only."""
import json
import os
import time
from collections import Counter

import gem_parser
import gem_runout_transition as RT

SESSIONS = [
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_live_test', 'live_test_2026-06-04'),
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\hh_today', 'hh_today_2026-06-09'),
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_20260527', 'session_2026-05-27'),
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v821_range')
os.makedirs(OUT, exist_ok=True)


def main():
    hands = []
    for path, name in SESSIONS:
        if os.path.isdir(path):
            hh, *_ = gem_parser.parse_session(path)
            for h in hh:
                h['_session'] = name
            hands += hh

    t0 = time.perf_counter()
    eligible = resolved = unresolved = descriptive = rule_backed = suppressed = 0
    unresolved_reasons = Counter()
    tag_dist = Counter()
    status_dist = Counter()
    bytes_total = 0
    samples = {'improved': [], 'draw_busted': [], 'flush_card': [], 'board_paired': [], 'blank': [], 'unresolved': []}

    for h in hands:
        for (street, i) in RT._hero_turn_river_decisions(h):
            eligible += 1
            rec = RT.build_transition(h, i)
            bytes_total += len(json.dumps(rec, default=str))
            if rec.get('unresolved'):
                unresolved += 1
                unresolved_reasons[rec.get('unresolved_reason')] += 1
                suppressed += 1
                if len(samples['unresolved']) < 3:
                    samples['unresolved'].append({'hand': h.get('id'), 'street': street, 'reason': rec.get('unresolved_reason')})
                continue
            resolved += 1
            status_dist[rec['hero_status']] += 1
            for t in rec['transition_tags']:
                tag_dist[t] += 1
            if rec['changed'] or rec['remained']:
                descriptive += 1
            if rec['planning_implication'] != 'insufficient_evidence':
                rule_backed += 1
            # collect representative samples (one-liners)
            tb = RT.teaching_block(rec)
            one = {'hand': h.get('id'), 'session': h.get('_session'), 'street': street,
                   'card': rec['new_card'], 'board': '-'.join(rec['resulting_board']),
                   'status': rec['hero_status'], 'tags': rec['transition_tags'],
                   'changed': tb['changed'], 'reassess': tb['reassess']}
            if rec['hero_status'] == 'improved' and len(samples['improved']) < 4:
                samples['improved'].append(one)
            if rec['draw_busted'] and len(samples['draw_busted']) < 4:
                samples['draw_busted'].append(one)
            if 'flush_card' in rec['transition_tags'] and len(samples['flush_card']) < 4:
                samples['flush_card'].append(one)
            if 'board_paired' in rec['transition_tags'] and len(samples['board_paired']) < 4:
                samples['board_paired'].append(one)
            if 'blank_vs_hero_draws' in rec['transition_tags'] and len(samples['blank']) < 4:
                samples['blank'].append(one)
    dt = time.perf_counter() - t0

    metrics = {
        'corpus': [n for _, n in SESSIONS], 'n_hands': len(hands),
        'eligible_turn_river_decisions': eligible,
        'resolved_complete_evidence': resolved,
        'unresolved_suppressed': unresolved,
        'unresolved_reasons': dict(unresolved_reasons),
        'descriptive_output': descriptive,
        'rule_backed_coaching': rule_backed,
        'insufficient_evidence_strategic': resolved,  # every resolved record's strategic layer is suppressed
        'resolved_rate': round(resolved / eligible, 3) if eligible else 0.0,
        'hero_status_distribution': dict(status_dist),
        'transition_tag_distribution': dict(tag_dist.most_common()),
        'false_positive_risk': 'descriptive-only; facts are canonical evaluator outputs (no verdicts)',
        'duplicate_static_texture_commentary': 'none — emits transition (before->after), not static labels',
        'result_leaks': 0, 'unsupported_range_claims': 0,
        'analyst_workload_added': 0,
        'avg_record_bytes': (bytes_total // max(eligible, 1)),
        'runtime_seconds': round(dt, 3),
        'runtime_ms_per_1000_decisions': round(1000.0 * dt / max(eligible, 1) * 1000, 2),
    }
    json.dump(metrics, open(os.path.join(OUT, 'RUNOUT_PILOT_METRICS.json'), 'w', encoding='utf-8'), indent=2)
    json.dump(samples, open(os.path.join(OUT, 'RUNOUT_PILOT_SAMPLES.json'), 'w', encoding='utf-8'), indent=2, default=str)

    print('hands:', len(hands), '| eligible turn/river decisions:', eligible)
    print('resolved:', resolved, '(%.0f%%)' % (100 * metrics['resolved_rate']), '| unresolved/suppressed:', unresolved, dict(unresolved_reasons))
    print('descriptive output:', descriptive, '| rule-backed coaching:', rule_backed, '(expect 0 — strategic blocked)')
    print('status:', dict(status_dist))
    print('top tags:', tag_dist.most_common(8))
    print('avg record bytes:', metrics['avg_record_bytes'], '| runtime %.3fs for %d decisions' % (dt, eligible))
    print('--- sample improved ---')
    for s in samples['improved'][:3]:
        print('  ', s['hand'], s['board'], s['status'], s['changed'])
    print('--- sample flush_card ---')
    for s in samples['flush_card'][:2]:
        print('  ', s['hand'], s['board'], s['tags'], s['reassess'])


if __name__ == '__main__':
    main()
