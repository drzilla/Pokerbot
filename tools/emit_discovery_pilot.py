"""Emit the mistake-discovery pilot artifacts from a run's parsed hands + stats (v8.20 Track 3).

Reproducible: runs gem_discovery_pilot.run_discovery_pilot on the run's own parsed hands/stats and writes
MISTAKE_DISCOVERY_PILOT_METRICS.json + MISTAKE_DISCOVERY_ANALYST_QUEUE.json. Every output is a candidate;
nothing is promoted to a confirmed mistake.

Usage:
    python tools/emit_discovery_pilot.py <gem_hands_*.json> <gem_stats.json|-> <out_dir>
"""
import io
import json
import os
import sys

import gem_discovery_pilot as dp


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    hands_path, stats_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    hands = json.load(io.open(hands_path, encoding='utf-8'))
    if isinstance(hands, dict):
        hands = list(hands.values())
    stats = {}
    if stats_path and stats_path != '-' and os.path.exists(stats_path):
        stats = json.load(io.open(stats_path, encoding='utf-8'))
    res = dp.run_discovery_pilot(hands, stats)
    os.makedirs(out_dir, exist_ok=True)
    with io.open(os.path.join(out_dir, 'MISTAKE_DISCOVERY_PILOT_METRICS.json'),
                 'w', encoding='utf-8', newline='\n') as f:
        json.dump(res['metrics'], f, indent=2, ensure_ascii=False)
    with io.open(os.path.join(out_dir, 'MISTAKE_DISCOVERY_ANALYST_QUEUE.json'),
                 'w', encoding='utf-8', newline='\n') as f:
        json.dump(res['analyst_queue'], f, indent=2, ensure_ascii=False)
    m = res['metrics']
    print('discovery pilot: %d candidates across %d families (n_hands=%d)'
          % (m['totals']['candidates_generated'], len(m['families']), m['n_hands']))
    for fam in m['families']:
        print('  %-26s generated=%s bb_impact=%s'
              % (fam['family'], fam['candidates_generated'], fam['canonical_material_bb_impact']))
    print('  auto_promoted_to_confirmed=%d  unsupported_exact_math=%d  with_decision_node=%d/%d'
          % (m['auto_promoted_to_confirmed'], m['totals']['unsupported_exact_math'],
             m['totals']['with_decision_node'], m['totals']['candidates_generated']))


if __name__ == '__main__':
    main()
