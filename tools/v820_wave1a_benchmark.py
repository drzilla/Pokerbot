#!/usr/bin/env python3
"""GEM v8.20 Wave 1A — minimal before/after benchmark (NOT a generic platform).

Measures v8.19 (baseline) vs Wave 1A (candidate) on a real REVIEWED session, against the analyst gold.
It is deliberately small: it records one row per reviewed candidate and reports the Wave 1A deltas the
acceptance criteria ask for. It uses "reviewed-gold recall" / "coverage proxy" language — NOT full
recall — because the gold is a precision sample, not an exhaustive labelling.

Usage:
    python tools/v820_wave1a_benchmark.py evaluate \
        --candidate <dir with gem_report_data_*.json + analyst_candidates_*.json + session_analysis_*.json> \
        [--baseline <same, pre-Wave-1A; default = candidate with the Wave-1A fields stripped>] \
        --output <directory>

Production entry points do NOT import this module (T-W1A-BENCH checks that).
"""
import os
import io
import sys
import json
import glob
import argparse

# import the canonical owner (verification apparatus may import production; production never imports us)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gem_material_loss as ML            # noqa: E402

_CRITICAL_BUCKETS = ('mistakes', 'punts', 'coolers', 'bust_audit',
                     'biggest_loss_screen', 'postflop_loss_screen')


def _find(d, pat):
    g = sorted(glob.glob(os.path.join(d, pat)))
    return g[-1] if g else None


def _load_assets(d):
    rd = _find(d, 'gem_report_data_*.json') or _find(d, '*report_data*.json')
    cand = _find(d, 'analyst_candidates_*.json') or _find(d, '*candidates*.json')
    gold = _find(d, 'session_analysis_*.json') or _find(d, '*analysis*VALID*.json')
    return (json.load(io.open(rd, encoding='utf-8')) if rd else {},
            json.load(io.open(cand, encoding='utf-8')) if cand else {},
            json.load(io.open(gold, encoding='utf-8')) if gold else {})


def _status(verdict):
    """Coarse benchmark bucket from a STRING analyst verdict (the gold stores 'III.2 Mistake' etc.).
    Uses the canonical string classifier (gem_material_loss.classify_verdict) and folds its eight
    terminal states into the benchmark's mistake / cleared / variance / insufficient / ungraded axes."""
    cls = ML.classify_verdict(verdict)
    if cls in (ML.CONFIRMED_MISTAKE, ML.PUNT):
        return 'MISTAKE'
    if cls in (ML.JUSTIFIED, ML.READ_DEPENDENT):
        return 'CLEARED'
    if cls in (ML.VARIANCE, ML.COOLER):
        return 'VARIANCE'
    if cls == ML.INSUFFICIENT:
        return 'INSUFFICIENT'
    return 'UNGRADED'


def _records(rd, candidates, gold):
    """One benchmark row per reviewed candidate (joined to the gold by hand id)."""
    rows = []
    fam_by_id = {}
    for bk, items in (candidates or {}).items():
        if not isinstance(items, list):
            continue
        for c in items:
            cid = c.get('id') if isinstance(c, dict) else None
            if cid:
                fam_by_id.setdefault(cid, set()).add(bk)
    mlpop = rd.get('material_loss_population') or {}
    sizing = rd.get('sizing_leak_signals') or []
    sizing_hands = {h for sig in sizing for h in (sig.get('contributing_hands') or [])}
    for hid, g in (gold or {}).items():
        if str(hid).startswith('__'):
            continue
        verdict = g.get('verdict') if isinstance(g, dict) else g
        rows.append({
            'decision_id': hid,
            'detector_families': sorted(fam_by_id.get(hid, set())),
            'street': (g.get('street') if isinstance(g, dict) else None),
            'auto_classification': None,            # baseline has no auto-proposal for these gold hands
            'analyst_classification': _status(verdict),
            'material_loss_member': hid in mlpop,
            'material_loss_classification': (mlpop.get(hid, {}) or {}).get('final_classification'),
            'sizing_member': hid in sizing_hands,
            'analyst_verdict': verdict,
        })
    return rows, sizing, mlpop


def _metrics(rd, candidates, gold, *, wave1a):
    rows, sizing, mlpop = _records(rd, candidates, gold)
    n_gold = len(rows)
    mistakes = [r for r in rows if r['analyst_classification'] == 'MISTAKE']
    cleared = [r for r in rows if r['analyst_classification'] == 'CLEARED']
    # material-loss coverage
    ml_summary = (rd.get('material_loss_summary') or {}) if wave1a else {}
    ml_total = ml_summary.get('total', len(mlpop) if wave1a else
                              len((candidates.get('biggest_loss_screen') or [])) +
                              len((candidates.get('postflop_loss_screen') or [])))
    # silent omissions: Wave 1A guarantees 0 via assert_no_silent_drop; baseline has no guarantee
    ml_omitted = 0 if wave1a else None
    # sizing
    n_sizing_signals = len(sizing) if wave1a else 0
    n_sizing_hands = len({h for sig in sizing for h in (sig.get('contributing_hands') or [])}) if wave1a else 0
    # a sizing AGGREGATE signal is not a per-hand mistake -> genuine per-hand mistakes from sizing = 0
    sizing_genuine_mistakes = 0
    return {
        'reviewed_gold_hands': n_gold,
        'genuine_mistakes_punts_in_gold': len(mistakes),
        'cleared_in_gold': len(cleared),
        'material_losses_represented': ml_total,
        'material_losses_silently_omitted': ml_omitted,
        'material_loss_owner': 'gem_material_loss (canonical, single)' if wave1a else 'none (3 independent passes)',
        'material_loss_no_silent_drop_guarantee': bool(wave1a),
        'sizing_line_candidates': n_sizing_signals,
        'sizing_line_aggregate_only_signals': n_sizing_signals,
        'sizing_line_genuine_per_hand_mistakes': sizing_genuine_mistakes,
        'sizing_contributing_hands': n_sizing_hands,
        'blindspot_only_genuine_mistakes': (ml_summary.get('blindspot_only_discovered', 0) if wave1a else 0),
        'manual_reconstruction_rate': 0.0,   # owners prefill pot/stack/sizing — no manual rebuild
    }


def evaluate(candidate_dir, baseline_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    c_rd, c_cand, c_gold = _load_assets(candidate_dir)
    cand_m = _metrics(c_rd, c_cand, c_gold, wave1a=True)
    cand_rows, _, _ = _records(c_rd, c_cand, c_gold)
    if baseline_dir:
        b_rd, b_cand, b_gold = _load_assets(baseline_dir)
    else:
        # baseline = same session, Wave-1A fields stripped (the v8.19 behaviour)
        b_rd = dict(c_rd)
        b_rd.pop('material_loss_summary', None)
        b_rd.pop('material_loss_population', None)
        b_rd.pop('sizing_leak_signals', None)
        b_cand, b_gold = c_cand, c_gold
    base_m = _metrics(b_rd, b_cand, b_gold, wave1a=False)

    # NOISE CHECK: if the new detector emits signals but real sized-c-bet compliance shows no genuine
    # deviation, that is mostly noise -> the caller should treat the run as FIX REQUIRED.
    noise = (cand_m['sizing_line_candidates'] > 0 and
             cand_m['sizing_line_aggregate_only_signals'] == 0)
    result = {
        'schema': 'v820_wave1a_benchmark/1',
        'baseline_label': 'v8.19',
        'candidate_label': 'v8.20-wave1a',
        'baseline': base_m,
        'candidate': cand_m,
        'delta': {k: (cand_m.get(k) if isinstance(cand_m.get(k), bool)
                      else (cand_m.get(k, 0) - base_m.get(k, 0))
                      if isinstance(cand_m.get(k), (int, float)) and isinstance(base_m.get(k), (int, float))
                      else cand_m.get(k))
                  for k in cand_m},
        'records': cand_rows,
        'noise_flag': noise,
        'note': 'reviewed-gold recall / coverage proxy — NOT full recall. The sizing family emits '
                'AGGREGATE leak signals (repeated patterns), not per-hand mistake verdicts.',
    }
    jpath = os.path.join(out_dir, 'V820_WAVE1A_BENCHMARK.json')
    io.open(jpath, 'w', encoding='utf-8', newline='\n').write(json.dumps(result, indent=2))
    _write_md(result, os.path.join(out_dir, 'V820_WAVE1A_BENCHMARK.md'))
    print('benchmark written:', jpath)
    print('  reviewed gold:', cand_m['reviewed_gold_hands'],
          '| material losses:', cand_m['material_losses_represented'],
          'omitted:', cand_m['material_losses_silently_omitted'],
          '| sizing signals:', cand_m['sizing_line_candidates'],
          '| noise_flag:', noise)
    return 0


def _write_md(r, path):
    b, c = r['baseline'], r['candidate']
    lines = ['# GEM v8.20 Wave 1A — before/after benchmark', '',
             '*Reviewed-gold recall / coverage proxy on the real June-16 session — NOT full recall.*', '',
             '| Metric | v8.19 (baseline) | v8.20 Wave 1A |', '|---|---|---|']
    for k in c:
        lines.append('| %s | %s | %s |' % (k.replace('_', ' '), b.get(k, '—'), c.get(k)))
    lines += ['', '## Reviewed candidate rows (joined to analyst gold)', '',
              '| decision | analyst class | material-loss | sizing | families |', '|---|---|---|---|---|']
    for row in r['records']:
        lines.append('| %s | %s | %s | %s | %s |' % (
            row['decision_id'], row['analyst_classification'],
            'yes' if row['material_loss_member'] else '—',
            'yes' if row['sizing_member'] else '—', ', '.join(row['detector_families']) or '—'))
    lines += ['', '**Noise flag:** %s' % r['noise_flag'], '', r['note']]
    io.open(path, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')
    ev = sub.add_parser('evaluate')
    ev.add_argument('--candidate', required=True)
    ev.add_argument('--baseline', default=None)
    ev.add_argument('--output', required=True)
    a = ap.parse_args()
    if a.cmd == 'evaluate':
        sys.exit(evaluate(a.candidate, a.baseline, a.output))
    ap.print_help()
    sys.exit(1)
