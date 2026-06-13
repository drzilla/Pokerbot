"""
gem_summary_parser.py — Tournament summary file parser.

Parses GG tournament summary files (NOT hand-history files — these are the
short result-only summaries) into a structured dict with financial data.

Source files look like:

    Tournament #283300927, $138 Tuesday Classic, Hold'em No Limit
    Buy-in: $138+$12
    1456 Players
    Total Prize Pool: $200,000
    Tournament started 2026/05/13 01:05:00
    185th : Hero, $392.55
    You finished the tournament in 185th place.
    You received a total of $392.55.

Or with re-entries:

    Buy-in: $42+$8+$50
    [...]
    You finished the tournament in 81th place.
    You made 1 re-entries and received a total of $351.25.

Or Day 2 advancement (no final cash yet):

    [...] You have advanced to Day2 with 25,732 chips.

# BUG HISTORY — DO NOT REGRESS

  v1.0 (2026-05-13, Ron 2026-05-13): initial module. Replaces ad-hoc
       regex parsing that had a critical bug: stripped thousands-place
       digits from cash values, turning $8,580.10 into $8.0. This caused
       a -$15K reported P/L when the actual figure was +$15K (off by
       $30K from clamping FIVE winning tournaments to single-digit cash).

  KEY ROBUSTNESS RULES — all enforced by tests:
    1. Cash regex MUST handle commas in dollar values (e.g. $8,580.10).
    2. Buy-in regex MUST handle 1/2/3 components ($X, $X+$Y, $X+$Y+$Z).
    3. Day2-advancement files MUST return status='pending', not 0 cash.
    4. Satellites MUST be flagged (tickets ≠ cash for P/L accounting).
    5. Filename date is the SESSION date (Ron's local date); the
       "Tournament started" timestamp can be the next UTC day.

Public API:
    parse_summary_file(path) -> dict | None
    parse_summary_dir(dir_path) -> list[dict]
    aggregate_by_date(rows) -> dict {date_iso: aggregated_dict}
    is_satellite(tournament_name) -> bool

Usage from CLI / pipeline:
    python3 gem_summary_parser.py /path/to/summaries/  # prints daily CSV
"""

import os
import re
import csv
import sys
from collections import defaultdict


# Regexes — anchored to be robust against the v1.0 bugs we shipped
RE_FILENAME = re.compile(
    r'GG(\d{8})\s*-\s*Tournament\s*#(\d+)\s*-\s*(.+)\.txt$'
)
# Buy-in: $X+$Y+$Z — each component allows commas (e.g. $1,050) and decimals.
# NOTE: the comma-allowance was the v1.0 bug fix. Tests enforce that
# $1,050.50 parses as 1050.50, not 1.0.
RE_BUYIN = re.compile(
    r'Buy-in:\s*\$([0-9,]+(?:\.[0-9]+)?)'
    r'(?:\+\$([0-9,]+(?:\.[0-9]+)?))?'
    r'(?:\+\$([0-9,]+(?:\.[0-9]+)?))?'
)
# Cash received — commas allowed (was the bug)
RE_CASH = re.compile(
    r'received a total of \$([0-9,]+(?:\.[0-9]+)?)'
)
# Re-entries
RE_REENTRIES = re.compile(r'made (\d+) re-entries')
# Finish place
RE_PLACE = re.compile(r'finished the tournament in (\d+)')
# Total players in field (e.g. "1516 Players") — Ron 2026-05-13:
# needed for Top1%/Top5% deep-run rate metrics
RE_PLAYERS = re.compile(r'^(\d+)\s+Players\s*$', re.MULTILINE)
# Day2 advancement marker — these tournaments don't have final cash yet
RE_DAY2 = re.compile(r'advanced to Day2', re.IGNORECASE)
# Chip-stack final (no cash, just chips reported — for tournaments where the
# summary closes without ITM)
RE_CHIPS_FINAL = re.compile(r'received a total of (\d+) chips', re.IGNORECASE)

# Tokens that mark a tournament as satellite (tickets ≠ cash)
_SAT_TOKENS = [
    'satellite', ' sat ', ' sat to', 'mega to', 'phase ', 'phase-h',
    'sat-', '-sat', ' seats', ' tickets',
]


def is_satellite(tournament_name):
    """True if the tournament name indicates a satellite (ticket prize).

    Satellite prizes are tournament tickets with face value but no cash
    payout. They should be excluded from cash P/L aggregation and tracked
    in a separate column.
    """
    if not tournament_name:
        return False
    n = tournament_name.lower()
    return any(tok in n for tok in _SAT_TOKENS)


def _money(s):
    """Convert a money string (possibly with commas) to float. Handles None."""
    if s is None:
        return 0.0
    return float(s.replace(',', ''))


def _format_tags(name):
    """Infer format tags from tournament name (Bounty, Turbo, Hyper, etc)."""
    tags = []
    n = name.lower()
    if is_satellite(name):
        tags.append('Sat')
    if 'bounty' in n:
        tags.append('Bounty')
    if 'mystery' in n:
        tags.append('Mystery')
    if 'turbo' in n:
        tags.append('Turbo')
    if 'hyper' in n:
        tags.append('Hyper')
    if '7-max' in n or '7max' in n:
        tags.append('7max')
    if '5-max' in n or '5max' in n:
        tags.append('5max')
    if 'deepstack' in n or 'deep stack' in n:
        tags.append('Deepstack')
    if 'ggmaster' in n:
        tags.append('GGM')
    if 'sop-sc' in n or 'wsop-sc' in n:
        tags.append('SOP-SC')
    if not any(t in tags for t in ('Bounty', 'Mystery', 'Sat')):
        tags.append('FZ')  # Freezeout
    return '|'.join(tags)


def parse_summary_file(path):
    """Parse a single tournament summary file.

    DATE CONVENTION (Ron 2026-05-21, decision B): the 'date' field is the
    GGPoker FILENAME date = GG's server date. This is NOT BKK local time —
    an evening BKK session can land partly on the next server date. This is
    a DELIBERATE choice: the entire session_financials history (2974+ rows
    back to 2025-06) was built filename-dated, and a consistent file beats a
    correct-but-seamed one. Do NOT "fix" this to BKK without converting the
    whole history — that would split the file across two conventions.

    Returns a dict with these keys:
        date              ISO date string (YYYY-MM-DD) — filename date
        tournament_id     numeric string (e.g. '283300927')
        tournament_name   e.g. '98-M 150 Tuesday Classic'
        format            pipe-separated tags (e.g. 'Bounty|Turbo')
        buyin_breakdown   raw string (e.g. '$42+$8+$50')
        buyin_per_bullet  float — total cost per single entry
        n_bullets         int — 1 + n_reentries
        total_cost        float — buyin_per_bullet × n_bullets
        cash_received     float — cash + bounty + ticket face value
        net               float — cash_received - total_cost
        finish_place      int or None
        is_satellite      bool — True if name matches satellite tokens
        status            'settled' | 'pending' | 'no_data'
                            pending = Day2 advancement, no final cash yet
                            no_data = neither cash line nor advancement line

    Returns None if filename doesn't match expected pattern or file unreadable.
    """
    fn = os.path.basename(path)
    m_fn = RE_FILENAME.match(fn)
    if not m_fn:
        return None
    date_raw, tourn_id, name = m_fn.group(1), m_fn.group(2), m_fn.group(3).strip()
    date_iso = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"

    try:
        text = open(path, errors='ignore').read()
    except (OSError, IOError):
        return None

    # Parse buy-in (required field)
    m_bi = RE_BUYIN.search(text)
    if not m_bi:
        return None
    buyin_parts = [_money(g) for g in m_bi.groups() if g]
    cost_per_bullet = sum(buyin_parts)
    buyin_str = '+'.join(f'${p}' for p in buyin_parts) if buyin_parts else '$0'

    # Re-entries
    m_re = RE_REENTRIES.search(text)
    n_bullets = 1 + (int(m_re.group(1)) if m_re else 0)

    # Cash received — three possibilities:
    #   1. Normal cash line ("received a total of $X.XX")
    #   2. Day2 advancement (no cash line, will be in later summary)
    #   3. Neither (chip count only, no cash) — treat as 0
    m_cash = RE_CASH.search(text)
    is_day2 = bool(RE_DAY2.search(text))
    m_chips = RE_CHIPS_FINAL.search(text)

    if m_cash:
        received = _money(m_cash.group(1))
        status = 'settled'
    elif is_day2:
        received = 0.0
        status = 'pending'  # Day 2 advancement — final cash TBD in later file
    elif m_chips:
        # "received a total of N chips" → busted with 0 cash
        received = 0.0
        status = 'settled'
    else:
        received = 0.0
        status = 'no_data'

    # Finish place
    m_p = RE_PLACE.search(text)
    place = int(m_p.group(1)) if m_p else None

    # Total players in field (Ron 2026-05-13)
    m_pl = RE_PLAYERS.search(text)
    total_players = int(m_pl.group(1)) if m_pl else None

    total_cost = cost_per_bullet * n_bullets
    net = received - total_cost
    sat = is_satellite(name)

    # Deep-run flags (Ron 2026-05-13/14)
    # All tournaments — including satellites — count toward FT/Top% per Ron's
    # convention: "a ticket is worth money, a bullet is worth real money."
    # Field-size limitation noted (sat 67 players vs MTT 20K means same Top%
    # doesn't mean same skill demonstration), used as directional metric.
    # - made_ft: finished within last 9. Standard MTT FT convention.
    # - top1/top5: percentile finish in the field. Requires total_players.
    made_ft = (place is not None and place <= 9)
    top1_pct = (place is not None and total_players is not None
                and place / total_players <= 0.01)
    top5_pct = (place is not None and total_players is not None
                and place / total_players <= 0.05)

    # Finish percentile — primary north-star skill metric (Ron 2026-05-14).
    # Lower is better. Per-tier stratified rolling average tracks real skill
    # progression with ~10x less variance than ITM rate at the same sample size.
    # See compute_tier_avgf_rolling() for the trajectory analysis.
    finish_pct = (place / total_players) if (place is not None and total_players) else None

    return {
        'date': date_iso,
        'tournament_id': tourn_id,
        'tournament_name': name,
        'format': _format_tags(name),
        'buyin_breakdown': buyin_str,
        'buyin_per_bullet': round(cost_per_bullet, 2),
        'n_bullets': n_bullets,
        'total_cost': round(total_cost, 2),
        'cash_received': round(received, 2),
        'net': round(net, 2),
        'finish_place': place,
        'total_players': total_players,
        'finish_pct': round(finish_pct, 4) if finish_pct is not None else None,
        'made_ft': made_ft,
        'top5_pct': top5_pct,
        'top1_pct': top1_pct,
        'is_satellite': sat,
        # B144 (Ron 2026-05-23): 3-component buy-in ($prize+$fee+$bounty) =
        # bounty/PKO tournament. cash_received then includes KO money, so ITM
        # must be placement-based, not cash-based — see compute_aggregate().
        'is_bounty': len(buyin_parts) >= 3,
        'status': status,
    }


def parse_summary_dir(dir_path, dedupe=True):
    """Parse all .txt files in a directory.

    If dedupe is True (default), drops duplicates on (date, tournament_id).
    Useful when the same tournament appears in multiple zip uploads.
    """
    rows = []
    seen = set()
    for f in sorted(os.listdir(dir_path)):
        if not f.endswith('.txt'):
            continue
        path = os.path.join(dir_path, f)
        row = parse_summary_file(path)
        if not row:
            continue
        if dedupe:
            key = (row['date'], row['tournament_id'])
            if key in seen:
                continue
            seen.add(key)
        rows.append(row)
    rows.sort(key=lambda r: (r['date'], r['tournament_id']))
    return rows


def aggregate_by_date(rows):
    """Aggregate parsed rows into per-date dicts.

    Returns dict keyed by ISO date.

    Convention (Ron 2026-05-14, v3):
      Tournaments + Bullets + Total_Cost + Total_Cash + ITM_Count + Winning_Count
      + FT_Count + Top5_Count + Top1_Count include EVERYTHING (cash tournaments
      AND satellites). Rationale per Ron: "a ticket is worth money, a bullet is
      worth real money" — sat ticket value counts as cash, sat reaching ITM
      counts as ITM. Sat_* columns remain as an informational subset.

    Per-date dict contains:
        tournaments, bullets,                  [all entries]
        total_cost, total_cash, net, roi_pct,  [all entries]
        itm_count, itm_pct_per_bullet,         [cash >= buyin]
        winning_count, winning_pct_per_bullet, [net > 0]
        ft_count, ft_pct_per_bullet,           [finish_place <= 9]
        top5_count, top5_pct_per_bullet,       [cash + sat — needs total_players]
        top1_count, top1_pct_per_bullet,       [cash + sat — needs total_players]
        top_eligible_bullets,                  [bullets w/ total_players]
        avg_buyin,
        sat_tournaments, sat_cost, sat_ticket_value, sat_seats_won,
        pending_count

    Definitions:
        itm_count       = entries where cash_received >= buyin_per_bullet.
                          Bounty-only payouts (cash > 0 but < buyin) excluded.
                          For sats: ticket value >= buyin counts (Ron 2026-05-14).
        winning_count   = entries where net > 0 (cash > total_cost).
        ft_count        = entries where finish_place <= 9.
        top5_count      = entries where finish_place / total_players <= 0.05.
        top1_count      = entries where finish_place / total_players <= 0.01.

    Percentages are PER-BULLET (denominator = Bullets played).
    Top1/Top5 use a separate eligible-bullets denominator since some summaries
    lack total_players data (older format).

    KNOWN LIMITATION (Ron 2026-05-14): Top% across varying field sizes (67-player
    satellite vs 20K-player main event) isn't a strict skill-equivalence metric.
    Used as directional indicator. For format-specific analysis, filter on the
    per-tournament CSV.
    """
    agg = defaultdict(lambda: {
        'tournaments': 0, 'bullets': 0,
        'top_eligible_bullets': 0,
        'avgf_sum': 0.0, 'avgf_count': 0,  # for AvgF aggregate (north-star skill metric)
        'total_cost': 0.0, 'total_cash': 0.0,
        'itm_count': 0, 'winning_count': 0,
        'ft_count': 0, 'top5_count': 0, 'top1_count': 0,
        'sat_tournaments': 0, 'sat_cost': 0.0,
        'sat_ticket_value': 0.0, 'sat_seats_won': 0,
        'pending_count': 0,
    })
    for r in rows:
        d = r['date']
        a = agg[d]
        if r['status'] == 'pending':
            a['pending_count'] += 1
            # Don't count pending tournaments toward cost — they'll get
            # picked up when the Day 2 summary lands.
            continue

        # All entries (cash + sat) count toward main totals.
        a['tournaments'] += 1
        a['bullets'] += r['n_bullets']
        a['total_cost'] += r['total_cost']
        a['total_cash'] += r['cash_received']

        # ITM (B144): bounty tournaments — cash includes KO money, so a deep
        # bust reads "cash >= buyin" while finishing out of the paid places.
        # Use placement (~top 15%) for bounty events; cash for non-bounty;
        # ticket value for satellites. Falls back to cash if place unknown.
        _itm = False
        if r.get('is_bounty') and r.get('finish_place') and r.get('total_players'):
            import math as _math
            _paid = _math.ceil(r['total_players'] * 0.15)
            _itm = (r['finish_place'] <= _paid) and (r['cash_received'] > 0)
        elif r['buyin_per_bullet'] > 0 and r['cash_received'] >= r['buyin_per_bullet']:
            _itm = True
        if _itm:
            a['itm_count'] += 1
        if r['net'] > 0:
            a['winning_count'] += 1
        # Deep-run flags — all tournaments count (sats included per Ron 2026-05-14)
        if r.get('made_ft'):
            a['ft_count'] += 1
        if r.get('total_players') is not None:
            a['top_eligible_bullets'] += r['n_bullets']
            if r.get('top5_pct'):
                a['top5_count'] += 1
            if r.get('top1_pct'):
                a['top1_count'] += 1
        # Avg finish % — primary north-star skill metric (Ron 2026-05-14).
        # Per-tournament contribution: each tournament with valid finish_pct
        # contributes one value. Aggregate computed as sum/count.
        if r.get('finish_pct') is not None:
            a['avgf_sum'] += r['finish_pct']
            a['avgf_count'] += 1

        # Sat-specific informational subset (does not subtract from main totals)
        if r['is_satellite']:
            a['sat_tournaments'] += 1
            a['sat_cost'] += r['total_cost']
            a['sat_ticket_value'] += r['cash_received']
            if r['cash_received'] > 0:
                a['sat_seats_won'] += 1

    # Compute derived fields — all per-BULLET
    out = {}
    for d, a in agg.items():
        net = a['total_cash'] - a['total_cost']
        roi = (net / a['total_cost'] * 100) if a['total_cost'] else 0.0
        # Per-bullet rates
        itm_pct = (a['itm_count'] / a['bullets'] * 100) if a['bullets'] else 0.0
        win_pct = (a['winning_count'] / a['bullets'] * 100) if a['bullets'] else 0.0
        ft_pct = (a['ft_count'] / a['bullets'] * 100) if a['bullets'] else 0.0
        top5_pct = ((a['top5_count'] / a['top_eligible_bullets'] * 100)
                    if a['top_eligible_bullets'] else None)
        top1_pct = ((a['top1_count'] / a['top_eligible_bullets'] * 100)
                    if a['top_eligible_bullets'] else None)
        avg_bi = (a['total_cost'] / a['bullets']) if a['bullets'] else 0.0
        # Avg finish percentile — primary skill metric. Stored as fraction (0-1)
        # for downstream rolling computation; renderer converts to % at display.
        avgf = (a['avgf_sum'] / a['avgf_count']) if a['avgf_count'] else None
        out[d] = {
            **a,
            'net': round(net, 2),
            'roi_pct': round(roi, 1),
            'itm_pct_per_bullet': round(itm_pct, 1),
            'winning_pct_per_bullet': round(win_pct, 1),
            'ft_pct_per_bullet': round(ft_pct, 2),
            'top5_pct_per_bullet': round(top5_pct, 2) if top5_pct is not None else None,
            'top1_pct_per_bullet': round(top1_pct, 2) if top1_pct is not None else None,
            'avgf_pct': round(avgf * 100, 2) if avgf is not None else None,
            'avg_buyin': round(avg_bi, 2),
            'total_cost': round(a['total_cost'], 2),
            'total_cash': round(a['total_cash'], 2),
            'sat_cost': round(a['sat_cost'], 2),
            'sat_ticket_value': round(a['sat_ticket_value'], 2),
        }
    return out


def compare_rates(count_a, n_a, count_b, n_b, label_a='A', label_b='B'):
    """Two-proportion z-test for comparing rates between two groups.

    Use this whenever making a comparative claim like "X month was better
    than Y" on rates like ITM/B, FT/B, Top5/B. Returns a dict with the
    confidence level and a pre-formatted summary string.

    Per Ron 2026-05-14: comparative claims must include explicit confidence.
    Never label a period "stumbled", "best", "weak" qualitatively without
    backing statistics, given high MTT variance.

    Args:
        count_a: numerator for group A (e.g. ITM_Count in April)
        n_a:     denominator for group A (e.g. Bullets in April)
        count_b: numerator for group B
        n_b:     denominator for group B
        label_a, label_b: optional labels for the summary string

    Returns dict with keys:
        rate_a, rate_b           — observed rates (as fractions)
        diff_pp                  — pp difference (a - b)
        z                        — z-statistic
        p_value                  — two-tailed p-value
        confidence               — 1 - p_value (range 0-1)
        adequate_sample          — bool: True if both groups n>=150 AND |diff|>=2pp
        summary                  — human-readable line
        verdict                  — one of 'significant', 'directional', 'inconclusive'
    """
    import math

    if n_a <= 0 or n_b <= 0:
        return {'verdict': 'inconclusive', 'summary': 'no data', 'confidence': 0.0,
                'rate_a': 0.0, 'rate_b': 0.0, 'diff_pp': 0.0, 'z': 0.0,
                'p_value': 1.0, 'adequate_sample': False}

    rate_a = count_a / n_a
    rate_b = count_b / n_b
    diff = rate_a - rate_b
    pooled = (count_a + count_b) / (n_a + n_b)
    # Edge case: pooled rate at 0 or 1 → zero variance, can't compute z
    if pooled <= 0 or pooled >= 1:
        return {'verdict': 'inconclusive', 'summary': 'degenerate case',
                'confidence': 0.0, 'rate_a': rate_a, 'rate_b': rate_b,
                'diff_pp': diff*100, 'z': 0.0, 'p_value': 1.0,
                'adequate_sample': False}
    se = math.sqrt(pooled * (1 - pooled) * (1/n_a + 1/n_b))
    z = diff / se if se > 0 else 0.0
    # Two-tailed p-value from z (using normal CDF approximation)
    # Approximation: erf-based, accurate to ~5 decimal places
    p_value = math.erfc(abs(z) / math.sqrt(2))
    confidence = 1.0 - p_value
    adequate = (n_a >= 150 and n_b >= 150 and abs(diff) >= 0.02)

    direction = '>' if diff > 0 else '<' if diff < 0 else '='
    if p_value < 0.05:
        verdict = 'significant'
    elif p_value < 0.20:
        verdict = 'directional'
    else:
        verdict = 'inconclusive'

    summary = (f"{label_a} {rate_a*100:.1f}% {direction} {label_b} {rate_b*100:.1f}% "
               f"(diff {diff*100:+.1f}pp, n={n_a}+{n_b}, conf {confidence*100:.0f}%, "
               f"p={p_value:.3f})")

    return {
        'rate_a': rate_a, 'rate_b': rate_b, 'diff_pp': diff*100,
        'z': z, 'p_value': p_value, 'confidence': confidence,
        'adequate_sample': adequate,
        'summary': summary, 'verdict': verdict,
    }


# Standard BI tiers for stratified skill tracking (Ron 2026-05-14).
# Adjust if Ron's BI distribution shifts substantially upward over time.
DEFAULT_BI_TIERS = [
    ('Micro',   0,   10),
    ('Low',     10,  25),
    ('Mid',     25,  50),
    ('High',    50,  100),
    ('Premium', 100, 100000),
]


def compute_tier_avgf_rolling(per_tournament_rows, window_months=3,
                               bi_tiers=None, min_n=30):
    """Compute rolling per-BI-tier AvgF trajectory — the primary skill metric.

    Ron 2026-05-14 insight: aggregate AvgF can appear flat while every tier
    individually improves, because mixing into harder tiers (higher BI) raises
    the per-tier baseline. Tier-stratified tracking is the correct view.

    Args:
        per_tournament_rows: list of dicts as emitted by parse_summary_file()
                              (must have 'date', 'finish_pct', 'buyin_per_bullet')
        window_months: rolling window size (default 3 months)
        bi_tiers: list of (label, low, high) tuples. Default = DEFAULT_BI_TIERS.
        min_n: minimum sample to surface a tier in a window (default 30)

    Returns:
        List of {window, tier, n, avgf_pct, avg_bi} dicts, one per
        (rolling-window-end, tier) pair where n >= min_n.

    Usage:
        from gem_summary_parser import compute_tier_avgf_rolling
        trajectories = compute_tier_avgf_rolling(per_tournament_rows)
        for t in trajectories:
            if t['tier'] == 'Mid':
                print(f"{t['window']}: AvgF {t['avgf_pct']:.1f}% (n={t['n']})")
    """
    if bi_tiers is None:
        bi_tiers = DEFAULT_BI_TIERS

    def fnum(x):
        try: return float(x)
        except (TypeError, ValueError): return None

    # Normalize input rows — accept either dict-from-parser (numeric)
    # or dict-from-csv (string) form.
    norm = []
    for r in per_tournament_rows:
        bi = fnum(r.get('buyin_per_bullet'))
        fp = fnum(r.get('finish_pct'))
        if bi is None or fp is None: continue
        if not r.get('date'): continue
        # B137 (Ron 2026-05-20): CSV finish_pct is percent-scaled (>1);
        # parser-dict finish_pct is already a fraction. Normalize to fraction.
        if fp > 1:
            fp = fp / 100.0
        norm.append({'date': r['date'], 'buyin': bi, 'fp': fp})

    if not norm:
        return []

    # Bucket by month
    by_month = defaultdict(list)
    for r in norm:
        by_month[r['date'][:7]].append(r)
    months = sorted(by_month.keys())
    if len(months) < window_months:
        return []

    results = []
    # Rolling windows: month_i to month_i + window_months - 1
    for i in range(len(months) - window_months + 1):
        window = months[i:i + window_months]
        window_label = f"{window[0]} -> {window[-1]}"
        rows_in_window = [r for m in window for r in by_month[m]]

        for tier_label, lo, hi in bi_tiers:
            tier_rows = [r for r in rows_in_window if lo <= r['buyin'] < hi]
            n = len(tier_rows)
            if n < min_n:
                continue
            avgf = sum(r['fp'] for r in tier_rows) / n
            avg_bi = sum(r['buyin'] for r in tier_rows) / n
            results.append({
                'window': window_label,
                'window_start': window[0],
                'window_end': window[-1],
                'tier': tier_label,
                'tier_low': lo, 'tier_high': hi,
                'n': n,
                'avgf_pct': round(avgf * 100, 2),
                'avg_bi': round(avg_bi, 2),
            })
    return results


def session_skill_context(per_tournament_rows, session_date,
                           session_avg_bi=None, window_bullets=500,
                           bi_tiers=None):
    """Return current-skill-context for a session, for use as a sidebar line
    in the per-session report (Ron 2026-05-14, build #2).

    Looks at the BI tier matching the session's avg BI, walks backward from
    session_date accumulating `window_bullets` worth of prior tournaments at
    that tier, and returns the trailing-window logit + AvgF with normal-approx
    95% CI on the mean.

    Critically, this is BACKWARD-looking from the session date — it includes
    the session itself only if no prior data exists at that tier, otherwise
    it's the "where I stood entering today" anchor. Per Ron's note that
    AvgF is useless at the daily-session sample size, this is meant as
    context orientation, not a session-specific measurement.

    Args:
        per_tournament_rows: dicts as emitted by parse_summary_file()
                             OR rows read from per-tournament CSV (string vals OK)
        session_date: ISO date of the session (string 'YYYY-MM-DD')
        session_avg_bi: avg BI for the session in USD. If None, will be
                        inferred from same-date rows in per_tournament_rows.
        window_bullets: target trailing-window size in bullets (default 500).
                        Will be relaxed if insufficient data — see returned `n`.
        bi_tiers: tier definitions. Defaults to DEFAULT_BI_TIERS.

    Returns dict (or None if insufficient data) with:
        tier_label, tier_low, tier_high  - matched BI band
        session_avg_bi                    - inferred or passed value
        n_tnys, n_bullets                 - trailing window sample
        window_start, window_end          - ISO dates of window edges
        logit                             - mean logit(finish_pct), 3 dp
        logit_ci_low, logit_ci_high       - 95% CI on logit
        avgf_pct                          - implied AvgF% (inverse-logit of mean)
        ranking_tier                      - 'Recreational' | 'Learning' | 'Breakeven' |
                                            'Winning regular' | 'Mid-stakes pro' |
                                            'High-stakes pro' | 'Top global'
        verdict_line                      - one-liner suitable for direct rendering
        confidence_note                   - caveat string ('low n', 'sufficient', etc.)
    """
    import math
    import statistics

    if bi_tiers is None:
        bi_tiers = DEFAULT_BI_TIERS

    def fnum(x):
        try: return float(x)
        except (TypeError, ValueError): return None
    def fi(x):
        try: return int(x)
        except (TypeError, ValueError): return None

    # Normalize input rows
    norm = []
    for r in per_tournament_rows:
        bi = fnum(r.get('buyin_per_bullet'))
        fp = fnum(r.get('finish_pct'))
        bullets = fi(r.get('n_bullets')) or 1
        date_iso = r.get('date')
        if bi is None or date_iso is None: continue
        if bi <= 0: continue
        # B137 (Ron 2026-05-20): normalize percent-scaled CSV finish_pct.
        if fp is not None and fp > 1:
            fp = fp / 100.0
        norm.append({
            'date': date_iso, 'buyin': bi, 'bullets': bullets,
            'fp': fp,
            'logit': math.log(fp/(1-fp)) if (fp is not None and 0 < fp < 1) else None,
        })
    if not norm:
        return None

    # Infer session avg BI if not provided
    if session_avg_bi is None:
        same_day = [r for r in norm if r['date'] == session_date]
        if not same_day: return None
        total_cost_proxy = sum(r['buyin'] * r['bullets'] for r in same_day)
        total_bullets = sum(r['bullets'] for r in same_day)
        session_avg_bi = total_cost_proxy / total_bullets if total_bullets else 0

    # Match BI tier
    tier_label = tier_low = tier_high = None
    for label, lo, hi in bi_tiers:
        if lo <= session_avg_bi < hi:
            tier_label, tier_low, tier_high = label, lo, hi
            break
    if tier_label is None:
        return None

    # Walk back from session_date through prior tournaments at this tier.
    # Prefer strictly-prior data; fall back to including session_date if needed.
    tier_rows_prior = sorted(
        [r for r in norm if tier_low <= r['buyin'] < tier_high and r['date'] < session_date],
        key=lambda r: r['date']
    )
    if not tier_rows_prior:
        tier_rows_prior = sorted(
            [r for r in norm if tier_low <= r['buyin'] < tier_high and r['date'] <= session_date],
            key=lambda r: r['date']
        )
    if not tier_rows_prior:
        return None

    # Accumulate bullets backward until window is filled
    acc_bullets = 0
    acc_tnys = 0
    win_rows = []
    for r in reversed(tier_rows_prior):
        if acc_bullets >= window_bullets:
            break
        win_rows.append(r)
        acc_bullets += r['bullets']
        acc_tnys += 1
    win_rows.reverse()

    # Need at least 30 tnys with valid logit for any signal
    logit_vals = [r['logit'] for r in win_rows if r['logit'] is not None]
    if len(logit_vals) < 30:
        return None

    mean_logit = statistics.mean(logit_vals)
    if len(logit_vals) > 1:
        sd = statistics.stdev(logit_vals)
        se = sd / math.sqrt(len(logit_vals))
        ci_low = mean_logit - 1.96 * se
        ci_high = mean_logit + 1.96 * se
    else:
        ci_low = ci_high = mean_logit

    avgf = 1 / (1 + math.exp(-mean_logit))
    avgf_pct = avgf * 100

    # ── New metrics (Ron 2026-05-16, skill_index introduction) ──
    # Three derived measures with clear, non-misleading names:
    #   FinScore = inverse_logit(mean_logit) × 100, expressed as %.
    #              Tail-aware central tendency in odds space (= old avgf_pct).
    #   AvgPos   = arithmetic mean of finish_pct × 100. The truly intuitive
    #              "where do I usually finish?" number. Differs from FinScore
    #              because mean and inv-logit don't commute.
    #   skill_index = ELO-style rating = 1500 + 200×(-mean_logit) + tier_handicap.
    #              Cross-tier comparable, intuitive scale.
    # All three share the same underlying mean_logit (the raw stat); they
    # differ only in how they're presented.
    fin_score = avgf_pct                              # alias for clarity
    avg_pos = (sum(r['fp'] for r in win_rows if r.get('fp') is not None)
               / sum(1 for r in win_rows if r.get('fp') is not None) * 100
               if win_rows else None)
    base_skill_index = 1500 + 200 * (-mean_logit)
    si_ci_low_base = 1500 + 200 * (-ci_high)          # note flip: low logit→high SI
    si_ci_high_base = 1500 + 200 * (-ci_low)

    # Apply tier handicap (the trailing window is single-tier by construction,
    # so handicap is just the tier's value)
    try:
        from gem_tier_handicaps import load as _load_handicaps
        _hp = _load_handicaps()
        _h = _hp.get('tier_handicap_elo', {}).get(tier_label, {}).get('value', 0.0)
        if _h is None:
            _h = 0.0  # v8.6.3: insufficient_data tier -> no handicap (safe default)
    except Exception:
        _h = 0.0
    skill_index = round(base_skill_index + _h)
    skill_index_ci_low = round(si_ci_low_base + _h)
    skill_index_ci_high = round(si_ci_high_base + _h)
    # ── End new metrics ──

    # Ranking band — calibrated to typical online MTT pools (Ron 2026-05-14)
    if avgf_pct >= 48: ranking = 'Recreational / losing'
    elif avgf_pct >= 42: ranking = 'Learning grinder'
    elif avgf_pct >= 38: ranking = 'Breakeven regular'
    elif avgf_pct >= 34: ranking = 'Winning regular'
    elif avgf_pct >= 30: ranking = 'Mid-stakes pro'
    elif avgf_pct >= 26: ranking = 'High-stakes pro'
    else: ranking = 'Top global tier'

    confidence_note = (
        'sufficient sample' if len(logit_vals) >= 100
        else 'modest sample' if len(logit_vals) >= 50
        else 'low sample — directional only'
    )

    verdict_line = (
        f"Entering today at {tier_label} BI band (~${session_avg_bi:.0f} avg) · "
        f"skill_index {skill_index} [CI {skill_index_ci_low}–{skill_index_ci_high}] · "
        f"FinScore {fin_score:.1f}%"
        + (f" · AvgPos {avg_pos:.1f}%" if avg_pos is not None else "")
        + f" · n={len(logit_vals)} tnys / {acc_bullets} bullets · "
        f"ranking: {ranking}"
    )

    return {
        'tier_label': tier_label, 'tier_low': tier_low, 'tier_high': tier_high,
        'session_avg_bi': round(session_avg_bi, 2),
        'n_tnys': acc_tnys, 'n_bullets': acc_bullets,
        'n_with_logit': len(logit_vals),
        'window_start': win_rows[0]['date'] if win_rows else None,
        'window_end': win_rows[-1]['date'] if win_rows else None,
        'logit': round(mean_logit, 3),
        'logit_ci_low': round(ci_low, 3),
        'logit_ci_high': round(ci_high, 3),
        # NEW fields:
        'fin_score': round(fin_score, 2),
        'avg_pos': round(avg_pos, 2) if avg_pos is not None else None,
        'skill_index': skill_index,
        'skill_index_ci_low': skill_index_ci_low,
        'skill_index_ci_high': skill_index_ci_high,
        'tier_handicap_applied': round(_h, 1),
        # LEGACY aliases (preserved for callers reading old field name):
        'avgf_pct': round(avgf_pct, 2),
        'ranking_tier': ranking,
        'ranking_band': ranking,                      # new alias
        'confidence_note': confidence_note,
        'verdict_line': verdict_line,
    }


def _compute_skill_index_for_rows(rows):
    """Helper: compute skill_index (with handicaps) for an arbitrary list of
    per-tournament rows. Returns dict or None if too few observations."""
    import math, statistics
    logits = []
    tier_bullets = {}
    fps = []
    n_t = 0
    n_b = 0
    for r in rows:
        try:
            bi = float(r.get('buyin_per_bullet', 0))
            fp = float(r.get('finish_pct', 0))
        except (TypeError, ValueError):
            continue
        # B137 (Ron 2026-05-20): finish_pct in session_financials_per_tournament
        # .csv is stored PERCENT-scaled (0.57 .. 79.98), but the logit math
        # needs a fraction in (0,1). The old `0 < fp < 1` guard silently
        # dropped every row with finish_pct >= 1% — i.e. all but the deepest
        # runs — corrupting EVERY skill-index window (anchor/responsive/today).
        # Normalize: any value > 1 is a percentage.
        if fp > 1:
            fp = fp / 100.0
        if bi <= 0 or not (0 < fp < 1):
            continue
        # Determine tier
        if bi < 10: tier = 'Micro'
        elif bi < 25: tier = 'Low'
        elif bi < 50: tier = 'Mid'
        elif bi < 100: tier = 'High'
        else: tier = 'Premium'
        try: bullets = int(float(r.get('n_bullets', 1)))
        except: bullets = 1
        logits.append(math.log(fp / (1 - fp)))
        fps.append(fp)
        tier_bullets[tier] = tier_bullets.get(tier, 0) + bullets
        n_t += 1
        n_b += bullets
    if n_t < 1:
        return None
    mean_logit = statistics.mean(logits)
    if len(logits) > 1:
        se = statistics.stdev(logits) / math.sqrt(len(logits))
        ci_low_l, ci_high_l = mean_logit - 1.96 * se, mean_logit + 1.96 * se
    else:
        ci_low_l = ci_high_l = mean_logit
    base = 1500 + 200 * (-mean_logit)
    base_ci_low = 1500 + 200 * (-ci_high_l)
    base_ci_high = 1500 + 200 * (-ci_low_l)

    try:
        from gem_tier_handicaps import load as _load_h, apply_to_bullets
        _hp = _load_h()
        handicap, low_conf, warn = apply_to_bullets(tier_bullets, _hp)
    except Exception:
        handicap, low_conf, warn = 0.0, False, None

    return {
        'n_t': n_t, 'n_b': n_b,
        'mean_logit': round(mean_logit, 3),
        'fin_score': round(1 / (1 + math.exp(-mean_logit)) * 100, 2),
        'avg_pos': round(sum(fps) / len(fps) * 100, 2) if fps else None,
        'base_skill_index': round(base),
        'handicap': round(handicap, 1),
        'skill_index': round(base + handicap),
        'skill_index_ci_low': round(base_ci_low + handicap),
        'skill_index_ci_high': round(base_ci_high + handicap),
        'tier_bullets': tier_bullets,
        'low_conf_handicap': low_conf,
        'handicap_warning': warn,
    }


def session_movement_summary(per_tournament_rows, session_date,
                             anchor_window_bullets=500,
                             responsive_window_tnys=100,
                             today_rows=None):
    """Return movement diagnostics for a session vs. historical baselines.

    Computes skill_index for four reference windows:
      1. Long-term anchor (default 500 bullets trailing, ending at session date)
      2. Responsive (default 100 tournaments trailing — sized to detect
         ~200 ELO swings; 95% CI ±60 ELO based on logit σ≈1.5)
      3. Today (the session itself — high variance, flagged as such)
      4. Per-tier breakdown for today (rendered in the report tier table)

    Args:
        per_tournament_rows: list of dicts with date/buyin_per_bullet/
                             finish_pct/n_bullets fields. Used for the
                             trailing windows.
        session_date: ISO 'YYYY-MM-DD' string. Used as the anchor cutoff
                      AND as the default selector for "today's tournaments"
                      (if today_rows is None).
        anchor_window_bullets: trailing window size in bullets for anchor
        responsive_window_tnys: trailing window size in tournaments for fast view
        today_rows: optional explicit list of per-tournament rows that
                    constitute "today's session." Use when the session
                    date convention differs from the per-tournament CSV
                    date convention (e.g., Bangkok local vs GG filename).
                    If None, falls back to filtering by session_date.

    Returns dict with anchor / responsive / today blocks + per-tier breakdown
    for today, plus pre-formatted verdict_lines for direct rendering.
    Returns None on insufficient data.
    """
    if not per_tournament_rows:
        return None

    def _to_date_key(r): return r.get('date', '')

    sorted_rows = sorted(per_tournament_rows, key=_to_date_key)

    # Anchor: walk back from session_date, accumulating bullets
    anchor_rows = []
    acc_b = 0
    for r in reversed(sorted_rows):
        if r.get('date', '') > session_date:
            continue
        if acc_b >= anchor_window_bullets:
            break
        anchor_rows.append(r)
        try: acc_b += int(float(r.get('n_bullets', 1)))
        except: acc_b += 1
    anchor_rows.reverse()

    # Responsive: trailing N tournaments
    responsive_rows = []
    for r in reversed(sorted_rows):
        if r.get('date', '') > session_date:
            continue
        if len(responsive_rows) >= responsive_window_tnys:
            break
        responsive_rows.append(r)
    responsive_rows.reverse()

    # Today: use explicit rows if provided, else filter by session_date
    if today_rows is not None:
        today_rs = today_rows
    else:
        today_rs = [r for r in sorted_rows if r.get('date', '') == session_date]

    anchor = _compute_skill_index_for_rows(anchor_rows)
    responsive = _compute_skill_index_for_rows(responsive_rows)
    today = _compute_skill_index_for_rows(today_rs)

    # Per-tier breakdown for today
    today_per_tier = {}
    if today and today_rs:
        for tier in ['Micro', 'Low', 'Mid', 'High', 'Premium']:
            def _in_tier(r, t):
                try: bi = float(r.get('buyin_per_bullet', 0))
                except: return False
                if t == 'Micro': return 0 <= bi < 10
                if t == 'Low':   return 10 <= bi < 25
                if t == 'Mid':   return 25 <= bi < 50
                if t == 'High':  return 50 <= bi < 100
                if t == 'Premium': return bi >= 100
                return False
            tier_rs = [r for r in today_rs if _in_tier(r, tier)]
            if tier_rs:
                today_per_tier[tier] = _compute_skill_index_for_rows(tier_rs)

    # Movement deltas
    deltas = {}
    if anchor and today:
        deltas['today_vs_anchor'] = today['skill_index'] - anchor['skill_index']
    if responsive and today:
        deltas['today_vs_responsive'] = today['skill_index'] - responsive['skill_index']
    if anchor and responsive:
        deltas['responsive_vs_anchor'] = responsive['skill_index'] - anchor['skill_index']

    # Confidence flag for today's number
    today_low_n = (today is not None) and (today.get('n_b', 0) < 10)

    return {
        'anchor': anchor,
        'responsive': responsive,
        'today': today,
        'today_per_tier': today_per_tier,
        'deltas': deltas,
        'today_low_sample': today_low_n,
        'anchor_window_bullets_target': anchor_window_bullets,
        'responsive_window_tnys_target': responsive_window_tnys,
    }


# Forward-outcome forecast models (Ron 2026-05-14, v7.49.10).
# Fitted on 44 paired (session, forward 200-bullet outcome) observations from
# triangulation v2. Uses mean-centered deviations to give "above/below average
# for the period" predictions rather than absolute ROI extrapolations.
_FORECAST_PERIOD_MEANS = {
    'ThreeBet': 9.42,         # %
    'VPIP': 22.26,            # %
    'Mistakes_per_100': 0.420,
    'forward_roi': 60.3,      # %ROI
    'forward_logit': -0.841,
}
_FORECAST_ROI_BETAS = {        # %ROI deviation per pp deviation
    'three_bet': 9.25,
    'vpip': 28.92,
}
_FORECAST_LOGIT_BETAS = {
    'three_bet': -0.0552,
    'mistakes_per_100': 0.1651,
}
_FORECAST_ROI_RESID_SD = 62.5     # %ROI
_FORECAST_LOGIT_RESID_SD = 0.107


def session_roi_forecast(session_date, three_bet, vpip, mistakes_per_100):
    """Forecast forward 200-bullet ROI + logit from current session metrics.

    Returns predictions framed as deviations from the recent-period mean,
    so the output is "above/below typical" rather than absolute extrapolations.

    Args:
        session_date: ISO date 'YYYY-MM-DD' (unused in deviation model;
                      retained for API compatibility)
        three_bet: current session ThreeBet %
        vpip: current session VPIP %
        mistakes_per_100: current session mistakes/100

    Returns dict with predicted_roi, predicted_logit, plus 80%/95% PIs and
    a verdict_line for direct rendering. Returns None on invalid inputs.
    """
    import math
    if any(v is None for v in [three_bet, vpip, mistakes_per_100]):
        return None

    M = _FORECAST_PERIOD_MEANS
    # ROI prediction: mean + deviation contribution
    d3bet = three_bet - M['ThreeBet']
    dvpip = vpip - M['VPIP']
    dmist = mistakes_per_100 - M['Mistakes_per_100']
    roi_dev = (_FORECAST_ROI_BETAS['three_bet'] * d3bet
               + _FORECAST_ROI_BETAS['vpip'] * dvpip)
    roi_pred = M['forward_roi'] + roi_dev
    # 80% PI ≈ ±1.28 sd, 95% PI ≈ ±1.96 sd
    roi_pi80 = (roi_pred - 1.28 * _FORECAST_ROI_RESID_SD,
                roi_pred + 1.28 * _FORECAST_ROI_RESID_SD)
    roi_pi95 = (roi_pred - 1.96 * _FORECAST_ROI_RESID_SD,
                roi_pred + 1.96 * _FORECAST_ROI_RESID_SD)

    # Logit prediction
    logit_dev = (_FORECAST_LOGIT_BETAS['three_bet'] * d3bet
                 + _FORECAST_LOGIT_BETAS['mistakes_per_100'] * dmist)
    logit_pred = M['forward_logit'] + logit_dev
    logit_pi80 = (logit_pred - 1.28 * _FORECAST_LOGIT_RESID_SD,
                  logit_pred + 1.28 * _FORECAST_LOGIT_RESID_SD)
    avgf_pred = 1 / (1 + math.exp(-logit_pred)) * 100

    # Verdict: deviation framing
    direction = 'above' if roi_dev > 5 else ('below' if roi_dev < -5 else 'near')
    verdict_line = (
        f"Forward outlook (200-bullet, model R²≈0.45): predicted ROI "
        f"{roi_pred:+.0f}% ({direction} period avg {M['forward_roi']:+.0f}%); "
        f"predicted AvgF {avgf_pred:.1f}% · 80% PI [{roi_pi80[0]:+.0f}%, "
        f"{roi_pi80[1]:+.0f}%]"
    )

    return {
        'predicted_roi': round(roi_pred, 1),
        'roi_pi80_low': round(roi_pi80[0], 1),
        'roi_pi80_high': round(roi_pi80[1], 1),
        'roi_pi95_low': round(roi_pi95[0], 1),
        'roi_pi95_high': round(roi_pi95[1], 1),
        'predicted_logit': round(logit_pred, 3),
        'logit_pi80_low': round(logit_pi80[0], 3),
        'logit_pi80_high': round(logit_pi80[1], 3),
        'predicted_avgf_pct': round(avgf_pred, 2),
        'period_mean_roi': M['forward_roi'],
        'period_mean_logit': M['forward_logit'],
        'roi_dev_from_mean': round(roi_dev, 1),
        'verdict_line': verdict_line,
        'caveat': '80% PI ~±80%ROI; model is directional, not precise dollar forecast',
    }


def write_per_tournament_csv(rows, path):
    """Write per-tournament CSV. Mirrors the structure used in
    session_financials_per_tournament.csv."""
    if not rows:
        return
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_daily_csv(by_date, path):
    """Write daily CSV. Mirrors session_financials.csv.

    Schema v3 (Ron 2026-05-14):
      ITM/Winning/FT/Top5/Top1 percentages are PER-BULLET rates.
      AvgF_Pct is the north-star skill metric (lower=better, per-tournament
      finish position / field size, averaged across tournaments that day).
      Per-tier rolling AvgF is reconstructed from the per-tournament CSV via
      compute_tier_avgf_rolling().

      Satellites included in main totals per Ron convention. Sat_* columns
      remain as informational subset.
    """
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow([
            'Date', 'Tournaments', 'Bullets', 'Total_Cost_USD', 'Total_Cash_USD',
            'Net_USD', 'ROI_Pct',
            'ITM_Count', 'ITM_Pct_per_Bullet',
            'Winning_Count', 'Winning_Pct_per_Bullet',
            'FT_Count', 'FT_Pct_per_Bullet',
            'Top5_Count', 'Top5_Pct_per_Bullet',
            'Top1_Count', 'Top1_Pct_per_Bullet',
            'AvgF_Pct',
            'Avg_Buyin_USD',
            'Sat_Tournaments', 'Sat_Cost_USD', 'Sat_Ticket_Value_USD',
            'Sat_Seats_Won', 'Pending_Count', 'Notes'
        ])
        for d in sorted(by_date.keys()):
            r = by_date[d]
            top5_str = f"{r['top5_pct_per_bullet']:.2f}" if r['top5_pct_per_bullet'] is not None else ''
            top1_str = f"{r['top1_pct_per_bullet']:.2f}" if r['top1_pct_per_bullet'] is not None else ''
            avgf_str = f"{r['avgf_pct']:.2f}" if r['avgf_pct'] is not None else ''
            w.writerow([
                d, r['tournaments'], r['bullets'],
                f"{r['total_cost']:.2f}", f"{r['total_cash']:.2f}",
                f"{r['net']:+.2f}", f"{r['roi_pct']:+.1f}",
                r['itm_count'], f"{r['itm_pct_per_bullet']:.1f}",
                r['winning_count'], f"{r['winning_pct_per_bullet']:.1f}",
                r['ft_count'], f"{r['ft_pct_per_bullet']:.2f}",
                r['top5_count'], top5_str,
                r['top1_count'], top1_str,
                avgf_str,
                f"{r['avg_buyin']:.2f}",
                r['sat_tournaments'], f"{r['sat_cost']:.2f}",
                f"{r['sat_ticket_value']:.2f}", r['sat_seats_won'],
                r['pending_count'], ''
            ])


def cli_main(argv):
    """python3 gem_summary_parser.py <dir> [--out-per-tourn FILE] [--out-daily FILE]"""
    if len(argv) < 2:
        print("Usage: gem_summary_parser.py <summary_dir> "
              "[--out-per-tourn FILE] [--out-daily FILE]")
        return 1
    dir_path = argv[1]
    if not os.path.isdir(dir_path):
        print(f"Error: {dir_path} not a directory")
        return 1
    per_path = '/home/claude/session_financials_per_tournament.csv'
    daily_path = '/home/claude/session_financials.csv'
    i = 2
    while i < len(argv):
        if argv[i] == '--out-per-tourn' and i + 1 < len(argv):
            per_path = argv[i+1]; i += 2
        elif argv[i] == '--out-daily' and i + 1 < len(argv):
            daily_path = argv[i+1]; i += 2
        else:
            i += 1
    rows = parse_summary_dir(dir_path)
    print(f"Parsed {len(rows)} tournaments from {dir_path}")
    by_date = aggregate_by_date(rows)
    write_per_tournament_csv(rows, per_path)
    write_daily_csv(by_date, daily_path)
    print(f"Wrote {per_path}")
    print(f"Wrote {daily_path}")
    # Aggregate stats
    total_cost = sum(d['total_cost'] for d in by_date.values())
    total_cash = sum(d['total_cash'] for d in by_date.values())
    net = total_cash - total_cost
    print(f"\nAggregate (cash tournaments only):")
    print(f"  Cost: ${total_cost:,.2f}")
    print(f"  Cash: ${total_cash:,.2f}")
    print(f"  Net:  {'+' if net>=0 else ''}${net:,.2f}")
    return 0


if __name__ == '__main__':
    sys.exit(cli_main(sys.argv))
