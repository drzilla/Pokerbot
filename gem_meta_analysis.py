#!/usr/bin/env python3
"""
gem_meta_analysis.py — On-demand meta-analysis refresh.

Runs the full Skill Diagnostics pipeline:
  1. Rebuild paired (session, forward-200-bullet-window) observations
  2. Refit forecast model coefficients (ROI + Logit deviation models)
  3. Refit leak watchlist targets (p25 / p75 / top-quartile per metric)
  4. Run extended variance attribution (EAI / premium / cooler / deep-run)
  5. Run full correlation scan across 90+ metrics × 4 outcomes
  6. Optionally regenerate the Methodology + Insights HTML/PDF report

USAGE:
  # Full refit, regenerate everything
  python3 gem_meta_analysis.py --rebuild

  # Just check whether a refit is warranted (no writes)
  python3 gem_meta_analysis.py --check

  # Refit silently and update the runtime constants (in gem_summary_parser.py
  # and gem_leak_watchlist.py)
  python3 gem_meta_analysis.py --refit-quiet

TRIGGER CRITERIA (when to re-run):
  Auto-prompt to refit when ANY of these are true:
    - n_sessions has grown ≥ 15 since last meta-analysis
    - EAI empirical baselines drifted by ≥ 2pp from current constants
    - Top-3 forecast-model coefficients drift by ≥ 25% from current
    - Skill rate (residual ROI %) drift by ≥ 10pp from prior run

OUTPUTS (when --rebuild):
  - /mnt/user-data/outputs/forecast_model_vN.json  (next version)
  - /mnt/user-data/outputs/leak_targets_vN.json
  - /mnt/user-data/outputs/variance_decomposition_vN.json
  - /mnt/user-data/outputs/full_metric_scan_vN.json
  - /mnt/user-data/outputs/Methodology_and_Insights_vN_YYYYMMDD.html

PIPELINE FILES THAT THIS UPDATES:
  - gem_summary_parser.py        (forecast model constants)
  - gem_leak_watchlist.py        (LEAK_TARGETS dict)
  - gem_analyzer.py              (EAI baselines, if drifted)

DESIGN NOTES:
  - This script is read-only against the project by default. Writes go to
    /mnt/user-data/outputs/. Manual review + manual deploy step is intentional
    so a noisy refit doesn't break the pipeline.
  - The --refit-quiet mode bypasses that for trusted users; emits a one-line
    summary of what changed.
"""
import argparse
import csv
import datetime
import json
import math
import os
import re
import statistics
import sys
from collections import defaultdict

# ---------------------------------------------------------------
# Paths
# ---------------------------------------------------------------
PROJECT_ROOT = '/mnt/project'
OUTPUTS_DIR = '/mnt/user-data/outputs'
DEFAULT_SESSION_HISTORY = os.path.join(
    OUTPUTS_DIR, 'session_history_merged_20251231_to_20260513_recalibrated.csv')
DEFAULT_PER_TOURNAMENT = '/mnt/user-data/outputs/session_financials_per_tournament.csv'
DEFAULT_BULK_LOGS = '/home/claude/bulk_logs'   # for EAI bucket parsing

# ---------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------
def transpose(M): return [list(c) for c in zip(*M)]
def matmul(A, B):
    return [[sum(a*b for a, b in zip(row, col)) for col in transpose(B)] for row in A]
def matinv(M):
    n = len(M)
    A = [row[:] + [1.0 if j == i else 0.0 for j in range(n)] for i, row in enumerate(M)]
    for i in range(n):
        pivot = A[i][i]
        if abs(pivot) < 1e-12:
            for r in range(i+1, n):
                if abs(A[r][i]) > 1e-12:
                    A[i], A[r] = A[r], A[i]; pivot = A[i][i]; break
        for j in range(2*n): A[i][j] /= pivot
        for k in range(n):
            if k == i: continue
            f = A[k][i]
            for j in range(2*n): A[k][j] -= f * A[i][j]
    return [row[n:] for row in A]
def ols(X, y):
    n, k = len(X), len(X[0])
    Xt = transpose(X); XtX = matmul(Xt, X); XtX_inv = matinv(XtX)
    Xty = matmul(Xt, [[v] for v in y])
    coefs = [r[0] for r in matmul(XtX_inv, Xty)]
    yhat = [sum(coefs[j] * X[i][j] for j in range(k)) for i in range(n)]
    resid = [y[i] - yhat[i] for i in range(n)]
    ss_res = sum(r**2 for r in resid)
    my = statistics.mean(y); ss_tot = sum((v - my)**2 for v in y)
    r2 = 1 - ss_res/ss_tot if ss_tot else 0
    return coefs, resid, r2

def fnum(x):
    try: return float(x) if x not in (None, '') else None
    except (TypeError, ValueError): return None


# ---------------------------------------------------------------
# Step 1: Build paired observations (session × forward window)
# ---------------------------------------------------------------
def build_paired_observations(session_history_path, per_tournament_path,
                              forward_bullets=200):
    # COR-001: type-coerce numeric columns at the load boundary (comma-formatted / numeric strings ->
    # numbers; empty/non-numeric -> None) so downstream numeric formatting never crashes on a csv string.
    from gem_csv_types import read_typed_csv
    sessions = read_typed_csv(session_history_path)
    per_t = read_typed_csv(per_tournament_path)

    # Per-tournament rows with finish percentile, sorted by date
    by_date = []
    for r in per_t:
        try:
            fp = float(r['finish_pct']) if r.get('finish_pct') else None
            by_date.append({
                'date': r['date'],
                'bullets': int(r['n_bullets']),
                'cost': float(r['total_cost']),
                'cash': float(r['cash_received']) if r.get('cash_received') else 0,
                'fp': fp,
                'logit': math.log(fp/(1-fp)) if (fp is not None and 0 < fp < 1) else None,
            })
        except (ValueError, KeyError):
            continue
    by_date.sort(key=lambda x: x['date'])

    records = []
    for s in sessions:
        sd = s['Date']
        # Same-session: aggregated outcomes
        same = [t for t in by_date if t['date'] == sd]
        if not same: continue
        cost = sum(t['cost'] for t in same)
        cash = sum(t['cash'] for t in same)
        logits = [t['logit'] for t in same if t['logit'] is not None]
        rec = {
            'Date': sd,
            'same_roi': (cash - cost) / cost * 100 if cost else 0,
            'same_logit': statistics.mean(logits) if logits else None,
            'session_net_usd': cash - cost,
            'session_cost': cost,
            'session_cash': cash,
            'session_bullets': sum(t['bullets'] for t in same),
            'session_top5': sum(1 for t in same
                                if t['fp'] is not None and t['fp'] <= 0.05),
        }
        # Forward window
        fwd = [t for t in by_date if t['date'] > sd]
        if fwd:
            acc = 0; window = []
            for t in fwd:
                if acc >= forward_bullets: break
                window.append(t); acc += t['bullets']
            if acc >= forward_bullets * 0.8:
                f_logits = [t['logit'] for t in window if t['logit'] is not None]
                f_cost = sum(t['cost'] for t in window)
                f_cash = sum(t['cash'] for t in window)
                if f_logits and f_cost > 0:
                    rec['fwd_logit'] = statistics.mean(f_logits)
                    rec['fwd_roi'] = (f_cash - f_cost) / f_cost * 100
                    rec['fwd_bullets'] = acc
        # Add all session_history columns
        for k, v in s.items():
            if k != 'Date':
                rec[k] = fnum(v)
        records.append(rec)
    return records


# ---------------------------------------------------------------
# Step 2: Refit forecast model (mean-centered deviation)
# ---------------------------------------------------------------
def refit_forecast_model(records):
    paired = [r for r in records
              if r.get('fwd_logit') is not None
              and all(r.get(k) is not None for k in ['ThreeBet', 'VPIP', 'Mistakes_per_100'])]
    n = len(paired)
    if n < 20:
        return None, f"insufficient paired observations: n={n}"

    means = {
        'ThreeBet': statistics.mean(r['ThreeBet'] for r in paired),
        'VPIP': statistics.mean(r['VPIP'] for r in paired),
        'Mistakes_per_100': statistics.mean(r['Mistakes_per_100'] for r in paired),
        'forward_roi': statistics.mean(r['fwd_roi'] for r in paired),
        'forward_logit': statistics.mean(r['fwd_logit'] for r in paired),
    }
    # ROI deviation model
    X_roi = [[r['ThreeBet'] - means['ThreeBet'], r['VPIP'] - means['VPIP']]
             for r in paired]
    y_roi = [r['fwd_roi'] - means['forward_roi'] for r in paired]
    coefs_r, resid_r, r2_r = ols(X_roi, y_roi)
    # Logit deviation model
    X_lg = [[r['ThreeBet'] - means['ThreeBet'],
             r['Mistakes_per_100'] - means['Mistakes_per_100']]
            for r in paired]
    y_lg = [r['fwd_logit'] - means['forward_logit'] for r in paired]
    coefs_l, resid_l, r2_l = ols(X_lg, y_lg)
    model = {
        'period_means': {k: round(v, 3) for k, v in means.items()},
        'roi_deviation_model': {
            'beta_threebet': round(coefs_r[0], 3),
            'beta_vpip': round(coefs_r[1], 3),
            'resid_sd': round(statistics.stdev(resid_r), 2),
            'r2': round(r2_r, 3),
        },
        'logit_deviation_model': {
            'beta_threebet': round(coefs_l[0], 4),
            'beta_mistakes': round(coefs_l[1], 4),
            'resid_sd': round(statistics.stdev(resid_l), 4),
            'r2': round(r2_l, 3),
        },
        'n_paired': n,
        'refit_date': datetime.date.today().isoformat(),
    }
    return model, None


# ---------------------------------------------------------------
# Step 3: Refit leak watchlist targets
# ---------------------------------------------------------------
TRACKED_METRICS = [
    ('Cold_Call_NB', 'lower'),
    ('VPIP_PFR_Gap_Raw', 'lower'),
    ('CR_Flop_Pct', 'higher'),
    ('AF', 'higher'),
    ('F2_Flop_CBet_Large', 'lower'),
    ('F2_Flop_CBet_Small', 'higher'),
    ('VPIP', 'lower'),
    ('BB_Iso_SB_Limp', 'higher'),
    ('F2_Turn_CBet_Small', 'lower'),
    ('River_Bet_Avg_bb', 'higher'),
    ('Agg_React_Delta', 'higher'),
    ('ATS_Raw', 'higher'),
    ('ThreeBet_OOP', 'higher'),
    ('Flop_CBet_HU_OOP', 'higher'),
    ('CBet_3BP', 'higher'),
    ('Triple_Barrel', 'lower'),
    ('Pure_Bluff_Pct', 'higher'),
    ('Semi_Bluff_Pct', 'higher'),
    ('Hero_4Bet', 'higher'),
    ('PFR', 'higher'),
]


def refit_leak_targets(records):
    def percentile(vals, p):
        s = sorted(v for v in vals if v is not None)
        if not s: return None
        idx = max(0, min(len(s)-1, int(round(p * (len(s)-1)))))
        return s[idx]

    recs_q = sorted([r for r in records if r.get('same_logit') is not None],
                    key=lambda r: r['same_logit'])
    top_q = recs_q[:max(1, len(recs_q)//4)]
    bot_q = recs_q[-max(1, len(recs_q)//4):]

    targets = {}
    for metric, direction in TRACKED_METRICS:
        vals = [r.get(metric) for r in records if r.get(metric) is not None]
        if len(vals) < 20: continue
        top_vals = [r.get(metric) for r in top_q if r.get(metric) is not None]
        bot_vals = [r.get(metric) for r in bot_q if r.get(metric) is not None]
        targets[metric] = {
            'direction': direction,
            'p25': round(percentile(vals, 0.25), 2),
            'p75': round(percentile(vals, 0.75), 2),
            'median': round(statistics.median(vals), 2),
            'top_avg': round(statistics.mean(top_vals), 2) if top_vals else None,
            'bot_avg': round(statistics.mean(bot_vals), 2) if bot_vals else None,
            'n': len(vals),
        }
    return targets


# ---------------------------------------------------------------
# Step 4: Variance attribution (EAI + premium + cooler + deep-run)
# ---------------------------------------------------------------
def variance_attribution(records, bulk_logs_dir=DEFAULT_BULK_LOGS):
    # Parse cooler counts from logs if available
    coolers = {}
    cooler_re = re.compile(r'Coolers: (\d+) \(([\d.]+)/100\)')
    if os.path.isdir(bulk_logs_dir):
        for fn in os.listdir(bulk_logs_dir):
            if not fn.endswith('.log'): continue
            iso = fn.replace('.log', '')
            try:
                txt = open(os.path.join(bulk_logs_dir, fn)).read()
                m = cooler_re.search(txt)
                if m:
                    coolers[iso] = {'count': int(m.group(1)), 'rate': float(m.group(2))}
            except (OSError, IOError):
                continue

    baseline_premium = statistics.mean(
        r.get('Premiums_Pct') or 3 for r in records
        if r.get('Premiums_Pct') is not None) if records else 3.0
    cooler_rates = [c['rate'] for c in coolers.values()]
    baseline_cooler = statistics.mean(cooler_rates) if cooler_rates else 0.26

    total = {'eai': 0, 'premium': 0, 'cooler': 0, 'deep_run': 0,
             'actual_net': 0, 'cost': 0}
    for r in records:
        bb = r.get('BB_per_100'); ev = r.get('EV_bb_per_100')
        hands = r.get('Hands') or 0
        cost = r.get('session_cost', 0)
        bullets = r.get('session_bullets', 0)
        if not all([bb, ev, hands, cost, bullets]): continue

        avg_bi = cost / bullets if bullets else 0
        d_per_bb = avg_bi / 200

        eai_usd = (bb - ev) * hands / 100 * d_per_bb
        prem_dev = (r.get('Premiums_Pct') or baseline_premium) - baseline_premium
        prem_usd = prem_dev / 100 * hands * 5 * d_per_bb
        c = coolers.get(r['Date'])
        cooler_usd = 0
        if c:
            dev = c['rate'] - baseline_cooler
            cooler_usd = -1 * dev / 100 * hands * 35 * d_per_bb
        expected_t5 = 0.05 * bullets
        actual_t5 = r.get('session_top5', 0)
        deep_run_usd = (actual_t5 - expected_t5) * avg_bi * 8

        total['eai'] += eai_usd
        total['premium'] += prem_usd
        total['cooler'] += cooler_usd
        total['deep_run'] += deep_run_usd
        total['actual_net'] += r.get('session_net_usd', 0)
        total['cost'] += cost

    sum_var = total['eai'] + total['premium'] + total['cooler'] + total['deep_run']
    residual = total['actual_net'] - sum_var
    return {
        'n_sessions': sum(1 for r in records if r.get('session_cost')),
        'total_invested': round(total['cost'], 2),
        'total_net': round(total['actual_net'], 2),
        'eai_variance': round(total['eai'], 2),
        'premium_variance': round(total['premium'], 2),
        'cooler_variance': round(total['cooler'], 2),
        'deep_run_variance': round(total['deep_run'], 2),
        'sum_variance': round(sum_var, 2),
        'residual_skill': round(residual, 2),
        'implied_skill_roi_pct': round(residual / total['cost'] * 100, 1) if total['cost'] else 0,
        'baseline_premium': round(baseline_premium, 2),
        'baseline_cooler_rate': round(baseline_cooler, 3),
    }


# ---------------------------------------------------------------
# Step 5: Full correlation scan
# ---------------------------------------------------------------
def pearson(xs, ys):
    valid = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(valid)
    if n < 10: return None, None
    xs2, ys2 = zip(*valid)
    mx, my = statistics.mean(xs2), statistics.mean(ys2)
    sx = math.sqrt(sum((x-mx)**2 for x in xs2))
    sy = math.sqrt(sum((y-my)**2 for y in ys2))
    if sx == 0 or sy == 0: return None, None
    r = sum((x-mx)*(y-my) for x, y in zip(xs2, ys2)) / (sx * sy)
    if abs(r) >= 1: return r, 0
    t = r * math.sqrt(n - 2) / math.sqrt(1 - r**2)
    p = math.erfc(abs(t) / math.sqrt(2))
    return round(r, 3), round(p, 4)


def full_correlation_scan(records):
    # Find every metric column
    all_keys = set()
    for r in records:
        for k in r.keys():
            if isinstance(r.get(k), (int, float)): all_keys.add(k)
    skip = {'Date', 'session_net_usd', 'session_cost', 'session_cash',
            'session_bullets', 'session_top5'}
    metric_keys = sorted(all_keys - skip)
    outcomes = ['same_logit', 'same_roi', 'fwd_logit', 'fwd_roi']

    out = {}
    for m in metric_keys:
        vals = [r.get(m) for r in records if r.get(m) is not None]
        if len(vals) < 30: continue
        try: sd = statistics.stdev(vals)
        except statistics.StatisticsError: continue
        if sd < 0.01: continue
        row = {'n': len(vals), 'sd': round(sd, 3)}
        for outc in outcomes:
            xs = [r.get(m) for r in records]
            ys = [r.get(outc) for r in records]
            r, p = pearson(xs, ys)
            row[outc] = {'r': r, 'p': p} if r is not None else None
        out[m] = row
    return out


# ---------------------------------------------------------------
# Trigger criteria checking
# ---------------------------------------------------------------
def check_refit_warranted(records, current_model_file=None):
    """Return (refit_warranted: bool, reasons: list[str])."""
    reasons = []
    n_sessions = sum(1 for r in records if r.get('session_cost'))

    # Load current model if exists
    if current_model_file and os.path.exists(current_model_file):
        try:
            current = json.load(open(current_model_file))
            prior_n = current.get('n_paired', 0)
            if n_sessions - prior_n >= 15:
                reasons.append(
                    f'session count grew by {n_sessions - prior_n} '
                    f'({prior_n} → {n_sessions}); ≥15 threshold met')
        except Exception:
            reasons.append('current model file unreadable; refit recommended')
    else:
        reasons.append('no prior model file found')

    return (bool(reasons), reasons)


# ---------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--rebuild', action='store_true',
                   help='full refit + regenerate all outputs')
    p.add_argument('--check', action='store_true',
                   help='check whether refit is warranted; no writes')
    p.add_argument('--refit-quiet', action='store_true',
                   help='refit constants silently')
    p.add_argument('--session-history', default=DEFAULT_SESSION_HISTORY,
                   help='session_history CSV path')
    p.add_argument('--per-tournament', default=DEFAULT_PER_TOURNAMENT,
                   help='per-tournament financial CSV path')
    p.add_argument('--forward-bullets', type=int, default=200,
                   help='forward window size in bullets (default 200)')
    args = p.parse_args()

    if not (args.rebuild or args.check or args.refit_quiet):
        p.print_help(); return 1

    print(f'[meta] reading session_history: {args.session_history}')
    print(f'[meta] reading per-tournament:   {args.per_tournament}')
    records = build_paired_observations(args.session_history, args.per_tournament,
                                        forward_bullets=args.forward_bullets)
    print(f'[meta] built {len(records)} session records; '
          f'paired (with forward window): '
          f'{sum(1 for r in records if r.get("fwd_logit") is not None)}')

    # --check mode
    if args.check:
        cur_model_file = os.path.join(OUTPUTS_DIR, 'forecast_model_v2.json')
        warranted, reasons = check_refit_warranted(records, cur_model_file)
        print(f'\n[meta] refit warranted: {warranted}')
        for r in reasons:
            print(f'  - {r}')
        return 0

    # Refit
    model, err = refit_forecast_model(records)
    if err:
        print(f'[meta] forecast refit failed: {err}'); return 1
    print(f'\n[meta] forecast model refit:')
    print(f'  ROI:   β_3bet={model["roi_deviation_model"]["beta_threebet"]:+.2f}  '
          f'β_vpip={model["roi_deviation_model"]["beta_vpip"]:+.2f}  '
          f'R²={model["roi_deviation_model"]["r2"]:.3f}')
    print(f'  Logit: β_3bet={model["logit_deviation_model"]["beta_threebet"]:+.4f}  '
          f'β_mistakes={model["logit_deviation_model"]["beta_mistakes"]:+.4f}  '
          f'R²={model["logit_deviation_model"]["r2"]:.3f}')

    targets = refit_leak_targets(records)
    print(f'\n[meta] leak targets refit: {len(targets)} metrics')

    variance = variance_attribution(records)
    print(f'\n[meta] variance attribution:')
    print(f'  net P&L: ${variance["total_net"]:+,.0f}')
    print(f'  EAI: ${variance["eai_variance"]:+,.0f}  '
          f'Premium: ${variance["premium_variance"]:+,.0f}  '
          f'Cooler: ${variance["cooler_variance"]:+,.0f}  '
          f'Deep-run: ${variance["deep_run_variance"]:+,.0f}')
    print(f'  residual skill: ${variance["residual_skill"]:+,.0f}  '
          f'({variance["implied_skill_roi_pct"]:+.1f}% implied ROI)')

    scan = full_correlation_scan(records)
    print(f'\n[meta] full correlation scan: {len(scan)} metrics × 4 outcomes')

    # Write outputs
    if args.rebuild:
        stamp = datetime.date.today().strftime('%Y%m%d')
        for name, data in [
            (f'forecast_model_{stamp}.json', model),
            (f'leak_targets_{stamp}.json', targets),
            (f'variance_decomposition_{stamp}.json', variance),
            (f'full_metric_scan_{stamp}.json', scan),
        ]:
            path = os.path.join(OUTPUTS_DIR, name)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            print(f'[meta] wrote {path}')

        print(f'\n[meta] NEXT STEPS to deploy:')
        print(f'  1. Review the JSON outputs in {OUTPUTS_DIR}')
        print(f'  2. Update _FORECAST_PERIOD_MEANS / _FORECAST_*_BETAS '
              f'in gem_summary_parser.py')
        print(f'  3. Update LEAK_TARGETS dict in gem_leak_watchlist.py')
        print(f'  4. Bump GEM_Quick_Reference.txt version')

    return 0


if __name__ == '__main__':
    sys.exit(main())
