"""Emit the mistake-discovery pilot artifacts from a run's parsed hands + stats (v8.20 Track 3).

Reproducible: runs gem_discovery_pilot.run_discovery_pilot on the run's own parsed hands/stats and writes
MISTAKE_DISCOVERY_PILOT_METRICS.json + MISTAKE_DISCOVERY_ANALYST_QUEUE.json. Every output is a candidate;
nothing is promoted to a confirmed mistake.

Usage:
    python tools/emit_discovery_pilot.py <gem_hands_*.json> <gem_stats.json|-> <out_dir> [<report_data.json>]

The optional report_data.json supplies prior analyst truth (final_truth.records) so candidates are
reconciled vs prior verdicts and the bounded review can separate incremental from already-adjudicated.
"""
import io
import json
import os
import sys

import gem_discovery_pilot as dp


def main():
    if len(sys.argv) not in (4, 5):
        raise SystemExit(__doc__)
    hands_path, stats_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    hands = json.load(io.open(hands_path, encoding='utf-8'))
    if isinstance(hands, dict):
        hands = list(hands.values())
    stats = {}
    if stats_path and stats_path != '-' and os.path.exists(stats_path):
        stats = json.load(io.open(stats_path, encoding='utf-8'))
    prior_records = {}
    if len(sys.argv) == 5 and os.path.exists(sys.argv[4]):
        rd = json.load(io.open(sys.argv[4], encoding='utf-8'))
        prior_records = (rd.get('final_truth') or {}).get('records', {}) or {}
    res = dp.run_discovery_pilot(hands, stats, prior_records=prior_records)
    os.makedirs(out_dir, exist_ok=True)
    for fn, obj in (('MISTAKE_DISCOVERY_PILOT_METRICS.json', res['metrics']),
                    ('MISTAKE_DISCOVERY_ANALYST_QUEUE.json', res['analyst_queue']),
                    ('MISTAKE_DISCOVERY_REVIEWED_QUEUE.json', res['reviewed'])):
        with io.open(os.path.join(out_dir, fn), 'w', encoding='utf-8', newline='\n') as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
    m = res['metrics']
    t = m['totals']
    print('discovery pilot (n_hands=%d): %d raw candidates, %d aggregate signals'
          % (m['n_hands'], t['raw_candidates'], t['aggregate_signals']))
    for fam in m['families']:
        print('  %-26s gen=%s new=%s suppressed=%s confirmed=%s gross_abs_net_bb=%s'
              % (fam['family'], fam['candidates_generated'], fam['new_unreviewed'],
                 fam['suppressed_already_reviewed_same_node'], fam['confirmed_mistakes'],
                 fam['gross_abs_hand_net_bb_exposed']))
    print('  with_decision_node=%d  suppressed_same_node=%d  new/changed=%d  incremental_reviewed=%d'
          % (t['with_decision_node'], t['suppressed_already_reviewed_same_node'],
             t['new_unreviewed_or_changed_node'], t['incremental_reviewed']))
    print('  INCREMENTAL CONFIRMED MISTAKES=%d  per_100=%s  precision=%s  unsupported_math=%d'
          % (t['incremental_confirmed_mistakes'], t['incremental_confirmed_per_100_hands'],
             t['precision_among_incremental_reviewed'], t['unsupported_exact_math']))


if __name__ == '__main__':
    main()
