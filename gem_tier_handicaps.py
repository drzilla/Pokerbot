"""gem_tier_handicaps.py — empirical BI-tier handicap calibration.

Calibrates the rating handicap each BI tier should carry (in ELO units) by
exploiting Ron's within-session multi-tier observations. Reference tier is
Mid ($25-50); other tiers are compared to Mid using paired same-day data.

Within-session pairing keeps "underlying skill" approximately constant, so
the observed cross-tier logit difference is treated as a field-strength
signal rather than a skill signal.

Outputs to /mnt/project/tier_handicaps.json by default. Recomputed on every
gem_run.py invocation; caches results between runs so the rating doesn't
move unless the underlying data changes meaningfully.

Public API:
    recompute(per_tournament_csv, output_path) -> handicaps dict
    load(path) -> handicaps dict (or default if missing)
    apply(tier, bullets, handicaps) -> bullet-weighted ELO adjustment
"""

import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


# ── Configuration ───────────────────────────────────────────────────────────

TIERS = [
    ('Micro',   0,   10),
    ('Low',     10,  25),
    ('Mid',     25,  50),
    ('High',    50,  100),
    ('Premium', 100, 1e9),
]
TIER_ORDER = [t[0] for t in TIERS]
REFERENCE_TIER = 'Mid'

# Sample-size thresholds for confidence labels
HIGH_CONF_N = 30
MED_CONF_N = 15
MIN_PAIRINGS = 3  # below this, emit no value (insufficient data to estimate)

# Minimum tournaments per (date, tier) bucket to use that bucket in pairing
MIN_TNYS_PER_TIER_DAY = 2

# ELO scale: 200 ELO points = 1 logit unit. Same as base skill_index scale.
ELO_PER_LOGIT = 200


# ── Core math ───────────────────────────────────────────────────────────────

def tier_of(bi):
    """Return tier label for a buy-in amount."""
    for label, lo, hi in TIERS:
        if lo <= bi < hi:
            return label
    return None


def _load_per_tournament(path):
    """Read per-tournament CSV, return list of dicts with logit pre-computed."""
    rows = []
    with open(path) as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            try:
                bi = float(r['buyin_per_bullet'])
                fp = float(r['finish_pct'])
            except (KeyError, ValueError):
                continue
            if bi <= 0 or not (0 < fp < 1):
                continue
            rows.append({
                'date': r['date'],
                'tier': tier_of(bi),
                'logit': math.log(fp / (1 - fp)),
                'bullets': int(float(r.get('n_bullets', 1))),
            })
    return rows


def _date_tier_means(rows):
    """Aggregate to per-(date, tier) mean logits, dropping buckets with <2 obs."""
    bucket = defaultdict(list)
    for r in rows:
        bucket[(r['date'], r['tier'])].append(r['logit'])
    result = {}
    for k, lst in bucket.items():
        if len(lst) >= MIN_TNYS_PER_TIER_DAY:
            result[k] = statistics.mean(lst)
    return result


def _compute_handicaps(rows):
    """Returns {tier: {value, ci_lo, ci_hi, n, confidence}} dict."""
    date_tier_mean = _date_tier_means(rows)

    # Group by date
    by_date = defaultdict(dict)
    for (d, t), ml in date_tier_mean.items():
        by_date[d][t] = ml

    # Paired diffs: for each session with REFERENCE tier + other tier, compute
    # other - reference logit.
    diffs = {t: [] for t in TIER_ORDER if t != REFERENCE_TIER}
    n_sessions_used = 0
    for d, tier_map in by_date.items():
        if REFERENCE_TIER not in tier_map:
            continue
        if len(tier_map) < 2:
            continue
        ref_logit = tier_map[REFERENCE_TIER]
        used_this_session = False
        for t, ml in tier_map.items():
            if t == REFERENCE_TIER:
                continue
            diffs[t].append(ml - ref_logit)
            used_this_session = True
        if used_this_session:
            n_sessions_used += 1

    # Build output
    handicaps = {REFERENCE_TIER: {
        'value': 0.0, 'ci_lo': 0.0, 'ci_hi': 0.0,
        'n': None, 'confidence': 'reference',
    }}
    for t, ds in diffs.items():
        n = len(ds)
        if n == 0:
            handicaps[t] = {
                'value': 0.0, 'ci_lo': None, 'ci_hi': None,
                'n': 0, 'confidence': 'no_data',
            }
            continue
        # v8.6.3: suppress low-n tiers — 1-2 pairings produce fabricated CI
        if n < MIN_PAIRINGS:
            handicaps[t] = {
                'value': None, 'ci_lo': None, 'ci_hi': None,
                'n': n, 'confidence': 'insufficient_data',
            }
            continue
        mean_d = statistics.mean(ds)
        if n > 1:
            se = statistics.stdev(ds) / math.sqrt(n)
            ci_lo, ci_hi = mean_d - 1.96 * se, mean_d + 1.96 * se
        else:
            ci_lo = ci_hi = mean_d
        conf = ('high' if n >= HIGH_CONF_N
                else 'medium' if n >= MED_CONF_N
                else 'low')
        handicaps[t] = {
            'value': round(mean_d * ELO_PER_LOGIT, 1),
            'ci_lo': round(ci_lo * ELO_PER_LOGIT, 1),
            'ci_hi': round(ci_hi * ELO_PER_LOGIT, 1),
            'n': n,
            'confidence': conf,
        }
    return handicaps, n_sessions_used


# ── Public API ──────────────────────────────────────────────────────────────

DEFAULT_PATH = '/mnt/project/tier_handicaps.json'


def recompute(per_tournament_csv, output_path=None, verbose=True,
              prev_handicaps=None):
    """Recompute handicaps from current per-tournament CSV.

    Writes JSON to output_path (default /mnt/project/tier_handicaps.json).
    If prev_handicaps is provided, also reports any tier whose handicap
    moved by >30 ELO between runs (console warning only).

    Returns the new handicaps dict.
    """
    rows = _load_per_tournament(per_tournament_csv)
    handicaps, n_sessions = _compute_handicaps(rows)

    payload = {
        'computed_at': datetime.now().astimezone().isoformat(),
        'n_sessions_used': n_sessions,
        'n_tournaments_total': len(rows),
        'reference_tier': REFERENCE_TIER,
        'elo_per_logit': ELO_PER_LOGIT,
        'tier_handicap_elo': handicaps,
    }

    out = output_path or DEFAULT_PATH
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w') as f:
        json.dump(payload, f, indent=2)

    if verbose:
        print(f"[handicaps] Recomputed from {len(rows)} tournaments / "
              f"{n_sessions} multi-tier sessions → {out}")
        for t in TIER_ORDER:
            h = handicaps.get(t, {})
            if h.get('confidence') == 'reference':
                print(f"  {t:<10}: 0 (reference)")
            else:
                ci = (f"[{h['ci_lo']:>+5.0f},{h['ci_hi']:>+5.0f}]"
                      if h.get('ci_lo') is not None else 'n/a')
                print(f"  {t:<10}: {h['value']:>+6.1f} ELO  {ci}  "
                      f"n={h['n']:<4} ({h['confidence']})")

    # Drift warning
    if prev_handicaps and verbose:
        for t in TIER_ORDER:
            old = prev_handicaps.get('tier_handicap_elo', {}).get(t, {}).get('value')
            new = handicaps.get(t, {}).get('value')
            if old is not None and new is not None and abs(new - old) > 30:
                print(f"  ⚠ {t} handicap drifted by {new - old:+.1f} ELO "
                      f"({old:.1f} → {new:.1f}) — investigate if unexpected")

    return payload


def load(path=DEFAULT_PATH):
    """Load handicaps from JSON. Returns default (all zeros) if file missing.
    Falls back to /home/claude/tier_handicaps.json if the primary path is missing
    (helpful in test/dev environments)."""
    p = Path(path)
    if not p.exists():
        # Fallback to local dev path
        fallback = Path('/home/claude/tier_handicaps.json')
        if fallback.exists():
            p = fallback
        else:
            return _default_payload()
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return _default_payload()


def _default_payload():
    return {
        'computed_at': None,
        'n_sessions_used': 0,
        'reference_tier': REFERENCE_TIER,
        'elo_per_logit': ELO_PER_LOGIT,
        'tier_handicap_elo': {t: {'value': 0.0, 'confidence': 'no_data', 'n': 0}
                              for t in TIER_ORDER},
    }


def apply_to_bullets(tier_bullets_dict, handicaps_payload):
    """Bullet-weighted average handicap given a {tier: bullets} dict.

    Args:
        tier_bullets_dict: e.g. {'Mid': 51, 'High': 48, 'Premium': 32}
        handicaps_payload: as returned by load()

    Returns:
        (weighted_handicap, low_confidence_flag, warning_string)
    """
    h_map = handicaps_payload.get('tier_handicap_elo', {})
    total_b = sum(tier_bullets_dict.values())
    if total_b == 0:
        return 0.0, False, None

    weighted = 0.0
    low_conf_bullets = 0
    low_conf_tiers = []
    for tier, bullets in tier_bullets_dict.items():
        entry = h_map.get(tier, {})
        weighted += entry.get('value', 0) * bullets
        if entry.get('confidence') == 'low' and bullets > 0:
            low_conf_bullets += bullets
            low_conf_tiers.append(tier)

    weighted /= total_b
    low_conf_pct = low_conf_bullets / total_b * 100
    flag = low_conf_pct > 10
    warning = None
    if flag:
        warning = (f"Handicap is low-confidence for "
                   f"{', '.join(low_conf_tiers)} "
                   f"({low_conf_pct:.0f}% of bullets) — interpret with caution.")
    return weighted, flag, warning


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-tourn', default='/mnt/project/session_financials_per_tournament.csv')
    ap.add_argument('--out', default=DEFAULT_PATH)
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    prev = load(args.out) if Path(args.out).exists() else None
    recompute(args.per_tourn, args.out, verbose=not args.quiet, prev_handicaps=prev)
