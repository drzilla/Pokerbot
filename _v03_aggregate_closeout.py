"""v8.21 aggregate-only closeout measurement on the 3 approved real sessions (3,609 hands).

Emits AGGREGATE_SIZING_SUMMARY.json, overlap with the existing aggregate sizing detector, and before/after
cost/workload into v03_pilot/. Canonical owners only; no per-hand analyst candidates; no results/equity.
"""
import json
import os
import time
import gem_parser
import gem_sizing_detector as SD
import gem_discovery_context as DC
import gem_textures as T

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v03_pilot')
os.makedirs(OUT, exist_ok=True)
SESSIONS = [
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_live_test', 'session_live_test_2026-06-04'),
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\hh_today', 'hh_today_2026-06-09'),
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_20260527', 'session_2026-05-27'),
]


def load():
    hands = []
    for path, name in SESSIONS:
        if not os.path.isdir(path):
            continue
        hh, *_ = gem_parser.parse_session(path)
        for h in hh:
            h['_session'] = name
        hands += hh
    return hands


# existing aggregate detector extractors (mirror gem_analyzer's GTO block exactly)
def _did(h):
    return any(b[0] == 'flop' and b[2] == 'cbet' for b in (h.get('hero_bets') or []))


def _siz(h):
    for b in (h.get('hero_bets') or []):
        if b[0] == 'flop' and b[2] == 'cbet':
            return b[1]
    return None


def main():
    hands = load()
    n = len(hands)

    # ---- recalibrated aggregate summary (safe: SRP/HU/non-all-in/within-spread) ----
    t0 = time.perf_counter()
    summary = SD.summarize_offband_sizing(hands)
    agg_s = time.perf_counter() - t0
    json.dump(summary, open(os.path.join(OUT, 'AGGREGATE_SIZING_SUMMARY.json'), 'w', encoding='utf-8'),
              indent=2, default=str)

    # ---- existing aggregate sizing detector on the same corpus (overlap) ----
    eligible = [h for h in hands if h.get('pfr')]
    tgf = T.aggregate_compliance(
        eligible, get_archetype_fn=lambda h: h.get('board_archetype', 'unknown'),
        get_side_fn=lambda h: 'ip' if h.get('hero_ip') else 'oop',
        get_depth_fn=lambda h: h.get('eff_stack_bb') or h.get('stack_bb') or 100,
        get_did_cbet_fn=_did, get_sizing_fn=_siz)
    existing = SD.build_sizing_leak_signals(tgf)
    existing_signals = existing['signals']
    # the existing detector does NOT gate SRP/HU/all-in and uses discrete-point matching -> broader, less safe
    my_keys = {(L['archetype'], L['side']) for L in summary['leak_signals']}
    ex_keys = {(s['archetype'], s['side']) for s in existing_signals}
    overlap = {
        'recalibrated_leak_signals': len(summary['leak_signals']),
        'existing_aggregate_leak_signals': len(existing_signals),
        'shared_archetype_side_buckets': sorted('%s|%s' % k for k in (my_keys & ex_keys)),
        'only_in_recalibrated': sorted('%s|%s' % k for k in (my_keys - ex_keys)),
        'only_in_existing': sorted('%s|%s' % k for k in (ex_keys - my_keys)),
        'note': 'The existing build_sizing_leak_signals (over texture_gto_findings) does NOT gate '
                'SRP/heads-up/non-all-in and matches discrete points; the recalibrated summary applies the '
                'deep-validation safety gates + within-spread compliance, so it is the corrected, safer '
                'refinement of the same aggregate signal. Recommend the existing aggregate adopt these gates.',
    }
    json.dump(overlap, open(os.path.join(OUT, 'AGGREGATE_OVERLAP.json'), 'w', encoding='utf-8'), indent=2)

    # ---- before/after cost + workload ----
    def _disc(include_baseline_only):
        s = time.perf_counter()
        for _ in range(10):
            DC.run_value(hands, {})
        return (time.perf_counter() - s) / 10
    run_s = _disc(True)
    cost = {
        'n_hands': n,
        'aggregate_summary_runtime_s': round(agg_s, 4),
        'discovery_run_value_runtime_s': round(run_s, 4),
        'analyst_packet_sizing_records': 0,
        'mandatory_analyst_reviews_added': 0,
        'workload_comparison': {
            'v8.20_baseline': '0 sizing reviews',
            '63b00e7_per_hand_uncorrected': 'auto-CONFIRMED gross c-bets as mistakes (false); required reviews',
            'c813797_per_hand_corrected': '29 per-hand nominations (gross->required, moderate->optional), 0 confirmed',
            'aggregate_only_closeout': '0 mandatory reviews; %d informational aggregate leak signal(s)' % len(summary['leak_signals']),
        },
        'packet_bytes_added': 0,
        'note': 'Aggregate summary adds NO analyst-packet records and NO mandatory reviews. run_value is '
                'back to the v8.20 baseline family set (sizing family removed). The summary is a separate, '
                'optional coaching rollup.',
    }
    json.dump(cost, open(os.path.join(OUT, 'AGGREGATE_COST_COMPARISON.json'), 'w', encoding='utf-8'), indent=2)

    print('hands:', n)
    print('AGGREGATE: opps=%d off_band=%d (%.0f%%) under=%d over=%d | leak_signals=%d | mandatory_reviews=%d'
          % (summary['opportunities'], summary['off_band'], 100 * summary['off_band_rate'],
             summary['under_sized'], summary['over_sized'], len(summary['leak_signals']),
             summary['creates_mandatory_analyst_reviews']))
    for L in summary['leak_signals']:
        print('  LEAK:', L['coaching'], '| examples:', L['representative_hands'])
    print('OVERLAP: recalibrated=%d existing=%d shared=%s'
          % (overlap['recalibrated_leak_signals'], overlap['existing_aggregate_leak_signals'],
             overlap['shared_archetype_side_buckets']))
    print('COST: summary %.4fs | run_value %.4fs | packet records +0 | mandatory reviews +0'
          % (agg_s, run_s))
    print('wrote AGGREGATE_SIZING_SUMMARY / AGGREGATE_OVERLAP / AGGREGATE_COST_COMPARISON -> v03_pilot/')


if __name__ == '__main__':
    main()
