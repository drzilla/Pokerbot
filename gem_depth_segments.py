"""gem_depth_segments.py — Depth-segmented win-rate diagnostics (v7.64).

Decision quality BY STACK DEPTH. Standard BB/100 aggregated across a whole MTT
session is poisoned two ways: (1) blind escalation makes net-BB non-additive
across levels — a stack built cheap and lost expensive reads BB-positive on a
chip loss (Bug A); (2) deep-stack early hands flood the hand volume, so the
late game is drowned out of the global rate.

SEGMENTING by effective stack depth fixes both. Within a depth bucket the
stack-in-BB is held roughly constant, so BB/100 is a stable, commensurable
*decision-quality* rate — and BB is the right unit for edge (a 2 BB mistake is
2 BB regardless of the absolute blind level).

This is a DECISION-QUALITY metric and is deliberately SEPARATE from the cEV
Result Attribution ledger (gem_cev.py), which is a RESULT-attribution tool and
genuinely needs chip-conservation. Two metrics, two jobs — not competitors.

Depth scheme (v7.64 canonical, 4-tier), by effective stack at the decision:
    <=8 BB     pure push/fold (Ron's sub-8 rule)
    8-25 BB    reshove / 3-bet-fold band
    25-40 BB   Dave J44 mid stratum
    >40 BB     deep — full postflop tree
The 25 / 40 boundaries match Dave's J44 framework (report Section VII.4) so the
report stays internally consistent; the <=8 tier adds Ron's pure push/fold
stratum. This is a decision-quality stratification and is intentionally
distinct from J44's sizing-specific buckets — different question, different cut.

ICM split: each depth bucket is also reported for high-ICM-pressure spots
(money bubble + final table) vs standard, because the risk premium changes how
a given depth should be played. Driven entirely by the existing hand-level
`tournament_phase` field — no schema change.

Confidence interval: a cluster bootstrap with the TOURNAMENT as the resampling
unit. Hands within a tournament are one connected trajectory (serial
correlation), so they cannot be resampled individually; the tournament is the
independent draw. Bullet-level clustering would be marginally finer, but the
parser does not yet emit a per-bullet id — tournament-level is the correct,
slightly-conservative fallback.

NOT YET DONE (sequenced): all-in-adjusted ("Sklansky") BB/100 per segment.
That requires per-hand all-in equity (the planned phevaluator precision pass);
until then this module reports realized BB/100, which still delivers the core
diagnostic — WHERE, by depth, the leaks are.
"""

import random

# (label, lo_exclusive, hi_inclusive) — effective stack in BB at the decision
DEPTH_BUCKETS = [
    ('<=8BB',   float('-inf'),  8.0),
    ('8-25BB',  8.0,           25.0),
    ('25-40BB', 25.0,          40.0),
    ('>40BB',   40.0,    float('inf')),
]

# tournament_phase values that count as high-ICM pressure
_HIGH_ICM_PHASES = {'bubble_zone', 'ft_zone'}

SCHEME_LABEL = '4-tier: <=8 / 8-25 / 25-40 / >40 BB (Dave J44 boundaries + sub-8)'


def _bucket_of(eff_bb):
    """Assign an effective-stack-in-BB value to its depth bucket label."""
    for label, lo, hi in DEPTH_BUCKETS:
        if lo < eff_bb <= hi:
            return label
    return None


def _eff_bb(h):
    """Effective stack in BB at the decision point. `eff_stack_bb_at_decision`
    is the precise field (depth when Hero actually acted); `eff_stack_bb`
    (start of hand) is the fallback. Returns None if neither is usable."""
    v = h.get('eff_stack_bb_at_decision')
    if v is None or v <= 0:
        v = h.get('eff_stack_bb')
    return v if (v and v > 0) else None


def _icm_band(h):
    """'high' for money-bubble / final-table hands, else 'std'."""
    return 'high' if h.get('tournament_phase') in _HIGH_ICM_PHASES else 'std'


def _rate(net_bb, n):
    """BB/100 — None when the cell is empty."""
    return round(net_bb / n * 100.0, 2) if n else None


def compute_depth_segments(hands, n_boot=2000, seed=20260521):
    """Depth-segmented BB/100 with an ICM-pressure split and a 90% tournament
    cluster-bootstrap CI per bucket. Returns a render-ready dict.

    Single forward pass builds a per-tournament list of (bucket, band, net_bb);
    the aggregate cells and the bootstrap both derive from it.
    """
    # --- one pass: per-tournament list of (bucket, band, net_bb) ---
    by_t = {}
    n_skipped = 0
    for h in hands:
        eff = _eff_bb(h)
        nb = h.get('net_bb')
        if eff is None or nb is None:
            n_skipped += 1
            continue
        b = _bucket_of(eff)
        if b is None:
            n_skipped += 1
            continue
        tid = h.get('tournament_id') or h.get('tournament') or '?'
        by_t.setdefault(tid, []).append((b, _icm_band(h), nb))

    if not by_t:
        return {'available': False, 'reason': 'no_segmentable_hands'}

    # --- aggregate cells: (bucket, band) and (bucket, 'all') ---
    cells = {}
    for recs in by_t.values():
        for b, band, nb in recs:
            for key in ((b, band), (b, 'all')):
                c = cells.setdefault(key, [0.0, 0])
                c[0] += nb
                c[1] += 1
    total_hands = sum(c[1] for k, c in cells.items() if k[1] == 'all')

    # --- cluster bootstrap: resample whole tournaments with replacement ---
    tids = list(by_t)
    boot = {b[0]: [] for b in DEPTH_BUCKETS}
    if len(tids) >= 2 and n_boot > 0:
        rng = random.Random(seed)
        n_t = len(tids)
        for _ in range(n_boot):
            agg = {}
            for _ in range(n_t):
                for b, _band, nb in by_t[tids[rng.randrange(n_t)]]:
                    a = agg.setdefault(b, [0.0, 0])
                    a[0] += nb
                    a[1] += 1
            for b, a in agg.items():
                if a[1]:
                    boot[b].append(a[0] / a[1] * 100.0)

    def _ci90(b):
        xs = sorted(boot.get(b, []))
        if len(xs) < 20:          # too few resamples landed in this bucket
            return None
        lo = xs[int(0.05 * len(xs))]
        hi = xs[min(len(xs) - 1, int(0.95 * len(xs)))]
        return (round(lo, 2), round(hi, 2))

    out = {
        'available': True,
        'scheme': SCHEME_LABEL,
        'n_tournaments': len(tids),
        'n_hands': total_hands,
        'n_skipped': n_skipped,
        'ci_method': 'tournament cluster bootstrap, 90%',
        'allin_adjusted': False,   # realized BB/100; Sklansky pass sequenced
        'buckets': [],
    }
    for label, _lo, _hi in DEPTH_BUCKETS:
        allc = cells.get((label, 'all'), [0.0, 0])
        stdc = cells.get((label, 'std'), [0.0, 0])
        highc = cells.get((label, 'high'), [0.0, 0])
        ci = _ci90(label)
        # a bucket is a reliable signal only when its CI sits clear of 0
        reliable = ci is not None and (ci[0] > 0 or ci[1] < 0)
        out['buckets'].append({
            'depth': label,
            'n_hands': allc[1],
            'pct_volume': (round(100.0 * allc[1] / total_hands, 1)
                           if total_hands else 0.0),
            'bb100': _rate(*allc),
            'bb100_std_icm': _rate(*stdc),
            'bb100_high_icm': _rate(*highc),
            'n_std': stdc[1],
            'n_high': highc[1],
            'ci90': ci,
            'reliable_signal': reliable,
        })
    return out


if __name__ == '__main__':
    import json
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else 'gem_hands.json'
    hands = json.load(open(src))
    ds = compute_depth_segments(hands)
    if not ds.get('available'):
        print('unavailable:', ds.get('reason'))
        raise SystemExit(1)
    print(f"{ds['n_hands']} hands / {ds['n_tournaments']} tournaments  "
          f"({ds['n_skipped']} skipped)")
    print(f"{'depth':9s} {'hands':>6s} {'%vol':>6s} {'BB/100':>8s} "
          f"{'std-ICM':>9s} {'high-ICM':>10s} {'90% CI':>18s}")
    for b in ds['buckets']:
        ci = b['ci90']
        ci_s = f"[{ci[0]:+.1f},{ci[1]:+.1f}]" if ci else "—"
        print(f"{b['depth']:9s} {b['n_hands']:6d} {b['pct_volume']:5.1f}% "
              f"{(b['bb100'] or 0):+8.2f} "
              f"{(b['bb100_std_icm'] if b['bb100_std_icm'] is not None else 0):+9.2f} "
              f"{(b['bb100_high_icm'] if b['bb100_high_icm'] is not None else 0):+10.2f} "
              f"{ci_s:>18s}")
