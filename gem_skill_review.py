#!/usr/bin/env python3
"""
gem_skill_review.py — Quarterly skill review generator (Ron 2026-05-14, build #1).

Standalone script that reads session_financials_per_tournament.csv and produces
a shareable HTML doc tracking per-BI-tier AvgF/logit progression over time.

Output: Skill_Review_YYYYMMDD.html — drop-in shareable, dark-mode aware, charts
inlined via Chart.js.

Usage:
    python3 gem_skill_review.py \
        --per-tourn /mnt/project/session_financials_per_tournament.csv \
        --out /mnt/user-data/outputs/Skill_Review_20260514.html

    # Or with defaults (looks for per-tournament CSV in cwd / /mnt/project/)
    python3 gem_skill_review.py

The script is intentionally a separate file from gem_run.py — quarterly cadence,
not per-session. Per Ron 2026-05-14 plan: "run quarterly or whenever you've
added ~500+ bullets since last review."

Sections produced:
    1. Headline stats — lifetime, last-quarter, current
    2. Per-tier rolling AvgF dashboard (the primary skill signal)
    3. First-half vs second-half within-tier improvement (confidence-backed)
    4. Aggregate trajectory chart (logit + avg BI dual-axis)
    5. Ranking placement (where do you sit in the MTT tier framework)
    6. What to track next quarter
"""
from __future__ import annotations
import argparse
import csv
import math
import statistics
import sys
import os
from collections import defaultdict
from datetime import date as _date_t

# Allow running from either /home/claude or /mnt/project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from gem_summary_parser import (
        compute_tier_avgf_rolling,
        DEFAULT_BI_TIERS,
        compare_rates,
    )
except ImportError:
    sys.path.insert(0, '/mnt/project')
    from gem_summary_parser import (
        compute_tier_avgf_rolling,
        DEFAULT_BI_TIERS,
        compare_rates,
    )


# ---------------------------------------------------------------------------
# RANKING BANDS — calibrated to online MTT pools (Ron 2026-05-14)
# ---------------------------------------------------------------------------
RANKING_BANDS = [
    ('Recreational / losing', 48, 55, 'Plays largely randomly, donates over time'),
    ('Learning grinder',      42, 48, 'Some fundamentals, significant leaks'),
    ('Breakeven regular',     38, 42, 'Solid basics, well-matched stakes'),
    ('Winning regular',       34, 38, 'Real edge across formats and field sizes'),
    ('Mid-stakes pro',        30, 34, 'Sustained ROI at mid buy-ins'),
    ('High-stakes pro',       26, 30, 'Elite reads, GTO compliance'),
    ('Top global tier',        0, 26, 'Single-digit-percent of all MTT players'),
]


def classify_ranking(avgf_pct: float) -> str:
    """Return ranking band label for a given avg-finish-percentile."""
    for label, lo, hi, _desc in RANKING_BANDS:
        if lo <= avgf_pct < hi:
            return label
    return 'Recreational / losing' if avgf_pct >= 48 else 'Top global tier'


# ---------------------------------------------------------------------------
# DATA LOADING + STATS
# ---------------------------------------------------------------------------
def fnum(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def fi(x):
    try: return int(x)
    except (TypeError, ValueError): return None


def load_per_tournament(path: str) -> list[dict]:
    """Load per-tournament rows from CSV. Returns list of normalized dicts."""
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append(r)
    norm = []
    for r in rows:
        bi = fnum(r.get('buyin_per_bullet'))
        fp = fnum(r.get('finish_pct'))
        bullets = fi(r.get('n_bullets')) or 1
        cost = fnum(r.get('total_cost')) or 0
        cash = fnum(r.get('cash_received'))
        if cash is None: continue
        if not r.get('date'): continue
        if bi is None or bi <= 0: continue
        # Logit only valid in open interval (0, 1)
        logit = (math.log(fp/(1-fp))
                 if (fp is not None and 0 < fp < 1) else None)
        norm.append({
            'date': r['date'], 'buyin_per_bullet': bi,
            'n_bullets': bullets, 'total_cost': cost,
            'cash_received': cash,
            'finish_pct': fp, 'logit': logit,
        })
    norm.sort(key=lambda r: r['date'])
    return norm


def headline_stats(rows: list[dict]) -> dict:
    """Compute lifetime / last-quarter / current-window stats."""
    if not rows: return {}
    cost = sum(r['total_cost'] for r in rows)
    cash = sum(r['cash_received'] for r in rows)
    bullets = sum(r['n_bullets'] for r in rows)
    fps = [r['finish_pct'] for r in rows if r['finish_pct'] is not None]
    logits = [r['logit'] for r in rows if r['logit'] is not None]
    avgf_life = statistics.mean(fps) * 100 if fps else 0
    logit_life = statistics.mean(logits) if logits else 0
    # Last 3 months from latest date
    latest = rows[-1]['date']
    cutoff_y = int(latest[:4]); cutoff_m = int(latest[5:7]) - 2
    while cutoff_m <= 0: cutoff_m += 12; cutoff_y -= 1
    cutoff = f'{cutoff_y:04d}-{cutoff_m:02d}-01'
    recent = [r for r in rows if r['date'] >= cutoff]
    recent_fps = [r['finish_pct'] for r in recent if r['finish_pct'] is not None]
    recent_logits = [r['logit'] for r in recent if r['logit'] is not None]
    avgf_q = statistics.mean(recent_fps) * 100 if recent_fps else 0
    logit_q = statistics.mean(recent_logits) if recent_logits else 0
    cost_q = sum(r['total_cost'] for r in recent)
    cash_q = sum(r['cash_received'] for r in recent)
    bullets_q = sum(r['n_bullets'] for r in recent)
    avg_bi_q = cost_q / bullets_q if bullets_q else 0
    return {
        'lifetime': {
            'tnys': len(rows), 'bullets': bullets,
            'cost': cost, 'cash': cash, 'net': cash - cost,
            'roi_pct': (cash - cost) / cost * 100 if cost else 0,
            'avgf_pct': round(avgf_life, 2),
            'logit': round(logit_life, 3),
            'ranking': classify_ranking(avgf_life),
            'avg_bi': cost / bullets if bullets else 0,
        },
        'recent_quarter': {
            'tnys': len(recent), 'bullets': bullets_q,
            'cost': cost_q, 'cash': cash_q, 'net': cash_q - cost_q,
            'roi_pct': (cash_q - cost_q) / cost_q * 100 if cost_q else 0,
            'avgf_pct': round(avgf_q, 2),
            'logit': round(logit_q, 3),
            'ranking': classify_ranking(avgf_q),
            'avg_bi': avg_bi_q,
            'window_start': cutoff, 'window_end': latest,
        },
    }


def within_tier_improvement(rows: list[dict]) -> list[dict]:
    """For each tier with sufficient sample, compute 1st-half vs 2nd-half
    AvgF and confidence via Welch t-test approximation."""
    out = []
    for tier_label, lo, hi in DEFAULT_BI_TIERS:
        tier_rows = [r for r in rows if lo <= r['buyin_per_bullet'] < hi]
        n = len(tier_rows)
        if n < 100:
            out.append({
                'tier': tier_label, 'tier_low': lo, 'tier_high': hi,
                'n': n, 'verdict': 'insufficient sample',
            })
            continue
        mid = n // 2
        a = tier_rows[:mid]; b = tier_rows[mid:]
        a_fp = [r['finish_pct'] for r in a if r['finish_pct'] is not None]
        b_fp = [r['finish_pct'] for r in b if r['finish_pct'] is not None]
        if len(a_fp) < 30 or len(b_fp) < 30:
            out.append({
                'tier': tier_label, 'tier_low': lo, 'tier_high': hi,
                'n': n, 'verdict': 'insufficient logit sample',
            })
            continue
        m_a = statistics.mean(a_fp); m_b = statistics.mean(b_fp)
        v_a = statistics.variance(a_fp); v_b = statistics.variance(b_fp)
        se = math.sqrt(v_a / len(a_fp) + v_b / len(b_fp))
        t = (m_a - m_b) / se if se > 0 else 0
        p = math.erfc(abs(t) / math.sqrt(2))
        conf = 1 - p
        if p < 0.05: verdict = 'significant'
        elif p < 0.20: verdict = 'directional'
        else: verdict = 'inconclusive'
        diff_pp = (m_b - m_a) * 100
        out.append({
            'tier': tier_label, 'tier_low': lo, 'tier_high': hi,
            'n': n,
            'first_half_pct': round(m_a * 100, 2),
            'second_half_pct': round(m_b * 100, 2),
            'diff_pp': round(diff_pp, 2),
            't': round(t, 3), 'p': round(p, 4),
            'confidence': round(conf * 100, 1),
            'verdict': verdict,
            'direction': 'improved' if diff_pp < 0 else 'regressed' if diff_pp > 0 else 'flat',
        })
    return out


def rolling_trajectory(rows: list[dict], window_months=3, min_n=30) -> list[dict]:
    """Aggregate AvgF + Avg BI over rolling N-month windows (not tier-stratified).
    For the aggregate trajectory chart."""
    by_month = defaultdict(list)
    for r in rows:
        by_month[r['date'][:7]].append(r)
    months = sorted(by_month.keys())
    out = []
    for i in range(len(months) - window_months + 1):
        w = months[i:i + window_months]
        rs = [r for m in w for r in by_month[m]]
        fps = [r['finish_pct'] for r in rs if r['finish_pct'] is not None]
        if len(fps) < min_n: continue
        bis = [r['buyin_per_bullet'] for r in rs]
        cost = sum(r['total_cost'] for r in rs)
        cash = sum(r['cash_received'] for r in rs)
        out.append({
            'window': f"{w[0]} → {w[-1]}",
            'avgf_pct': round(statistics.mean(fps) * 100, 2),
            'avg_bi': round(statistics.mean(bis), 2),
            'n': len(fps),
            'roi_pct': round((cash - cost) / cost * 100, 1) if cost else 0,
        })
    return out


# ---------------------------------------------------------------------------
# HTML RENDERER
# ---------------------------------------------------------------------------
def _chartjs_inline_path() -> str | None:
    """Locate chart.umd.js for inline embed (offline-portable HTML).
    Returns path or None if not found."""
    candidates = [
        '/home/claude/doc/chart.umd.js',
        '/home/claude/doc/node_modules/chart.js/dist/chart.umd.min.js',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chart.umd.js'),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def render_html(rows: list[dict], headline: dict, tier_table: list[dict],
                rolling: list[dict], tier_dashboard: list[dict],
                run_date: str) -> str:
    """Compose the standalone HTML doc."""
    # Pivot tier_dashboard for chart: by tier
    by_tier_traj = defaultdict(list)
    for t in tier_dashboard:
        by_tier_traj[t['tier']].append(t)
    tier_chart_data = {}
    tier_order = [t[0] for t in DEFAULT_BI_TIERS]
    for tier in tier_order:
        pts = by_tier_traj.get(tier, [])
        tier_chart_data[tier] = [
            {'window': p['window'], 'avgf': p['avgf_pct'], 'n': p['n'],
             'avg_bi': p['avg_bi']}
            for p in pts
        ]

    # Aggregate rolling trajectory (logit dual-axis BI)
    roll_labels = [r['window'].split(' → ')[1] for r in rolling]
    roll_avgf = [r['avgf_pct'] for r in rolling]
    roll_bi = [r['avg_bi'] for r in rolling]
    roll_roi = [r['roi_pct'] for r in rolling]

    # Inline Chart.js if available; fall back to CDN
    chart_inline = ''
    cjs_path = _chartjs_inline_path()
    if cjs_path:
        with open(cjs_path) as f:
            chart_inline = f'<script>\n{f.read()}\n</script>'
    else:
        chart_inline = '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>'

    # Build within-tier-improvement table rows
    tier_table_rows = []
    for t in tier_table:
        if t['verdict'].startswith('insufficient'):
            tier_table_rows.append(
                f'<tr><td class="label">{t["tier"]} (${t["tier_low"]}-${t["tier_high"]})</td>'
                f'<td class="r">{t["n"]}</td>'
                f'<td class="r" colspan="4" style="color: var(--ink-mute);">{t["verdict"]}</td></tr>'
            )
            continue
        ver_class = 'sig' if t['verdict'] == 'significant' else ('dir' if t['verdict'] == 'directional' else 'no')
        direction_arrow = '↓' if t['direction'] == 'improved' else ('↑' if t['direction'] == 'regressed' else '→')
        tier_table_rows.append(
            f'<tr><td class="label">{t["tier"]} (${t["tier_low"]}-${t["tier_high"]})</td>'
            f'<td class="r">{t["n"]}</td>'
            f'<td class="r">{t["first_half_pct"]}%</td>'
            f'<td class="r"><strong>{t["second_half_pct"]}%</strong></td>'
            f'<td class="r">{direction_arrow} {abs(t["diff_pp"]):.1f}pp</td>'
            f'<td><span class="verdict {ver_class}">{t["confidence"]:.0f}% · {t["verdict"]}</span></td></tr>'
        )

    # Build ranking band table
    ranking_rows = []
    lifetime_ranking = headline['lifetime']['ranking']
    recent_ranking = headline['recent_quarter']['ranking']
    for label, lo, hi, desc in RANKING_BANDS:
        cls = 'winner' if label == recent_ranking else ''
        marker = ' ← you' if label == recent_ranking else ''
        ranking_rows.append(
            f'<tr class="{cls}"><td class="label">{label}{marker}</td>'
            f'<td class="r">{lo}-{hi}%</td><td>{desc}</td></tr>'
        )

    # Tier dashboard table (rolling per-tier)
    # Get all distinct windows
    all_windows = sorted({p['window'] for tier_pts in tier_chart_data.values() for p in tier_pts})
    dash_header = '<tr><th>3-mo window</th>' + ''.join(f'<th class="r">{t}</th>' for t in tier_order) + '</tr>'
    dash_rows = []
    for w in all_windows:
        cells = [f'<td class="label">{w}</td>']
        for tier in tier_order:
            pt = next((p for p in tier_chart_data[tier] if p['window'] == w), None)
            if pt:
                cells.append(f'<td class="r">{pt["avgf"]}% <span class="n">n={pt["n"]}</span></td>')
            else:
                cells.append('<td class="r">—</td>')
        dash_rows.append('<tr>' + ''.join(cells) + '</tr>')

    # Compose
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Quarterly Skill Review — Knockman · {run_date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Inconsolata:wght@400;500&family=Manrope:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #FAF6EE;
    --bg-card: #F1E9D8;
    --ink: #1B1714;
    --ink-soft: #4A433C;
    --ink-mute: #7A7065;
    --rule: #C9BFA8;
    --accent: #8B2635;
    --positive: #2D5F3F;
    --warn: #A35100;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #1A1614;
      --bg-card: #221E1A;
      --ink: #F1ECE0;
      --ink-soft: #C5BCAB;
      --ink-mute: #8A8074;
      --rule: #3D3630;
      --accent: #D67881;
      --positive: #7FBE96;
      --warn: #E4A45A;
    }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    background: var(--bg); color: var(--ink);
    font-family: 'Manrope', system-ui, sans-serif;
    font-size: 16px; line-height: 1.65;
    -webkit-font-smoothing: antialiased;
  }}
  .page {{ max-width: 780px; margin: 0 auto; padding: 3.5rem 2rem 5rem; }}
  .eyebrow {{
    font-family: 'Inconsolata', monospace; font-size: 12px;
    letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); margin-bottom: 1rem;
  }}
  h1 {{
    font-family: 'Fraunces', serif; font-weight: 400;
    font-size: clamp(32px, 5vw, 48px); line-height: 1.05;
    letter-spacing: -0.02em; margin-bottom: 0.75rem;
  }}
  h1 em {{ font-style: italic; color: var(--accent); }}
  .deck {{
    font-family: 'Fraunces', serif; font-size: 19px; font-weight: 300;
    line-height: 1.5; color: var(--ink-soft); margin-bottom: 2rem;
    max-width: 580px;
  }}
  .byline {{
    font-family: 'Inconsolata', monospace; font-size: 12px;
    color: var(--ink-mute); letter-spacing: 0.06em;
    padding-bottom: 2rem; border-bottom: 1px solid var(--rule);
    margin-bottom: 3rem;
  }}
  section {{ margin: 3rem 0; }}
  h2 {{
    font-family: 'Fraunces', serif; font-weight: 500;
    font-size: 26px; line-height: 1.15; letter-spacing: -0.01em;
    margin-bottom: 1rem;
  }}
  h2 .num {{
    font-family: 'Inconsolata', monospace; font-size: 13px;
    color: var(--accent); font-weight: 500; letter-spacing: 0.06em;
    display: block; margin-bottom: 0.4rem;
  }}
  h3 {{
    font-family: 'Manrope', sans-serif; font-weight: 600;
    font-size: 15px; margin: 1.25rem 0 0.5rem;
  }}
  p {{ margin-bottom: 1rem; color: var(--ink-soft); }}
  strong {{ font-weight: 600; color: var(--ink); }}
  table {{ width: 100%; border-collapse: collapse; margin: 1.25rem 0; font-size: 14px; }}
  th {{
    text-align: left; font-family: 'Inconsolata', monospace;
    font-weight: 500; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--ink-mute);
    padding: 8px 12px 8px 0; border-bottom: 1px solid var(--rule);
    white-space: nowrap;
  }}
  th.r {{ text-align: right; padding: 8px 0 8px 12px; }}
  td {{
    padding: 9px 12px 9px 0; border-bottom: 1px solid var(--rule);
    color: var(--ink-soft); vertical-align: top;
  }}
  td.r {{ text-align: right; padding: 9px 0 9px 12px; font-variant-numeric: tabular-nums; }}
  td.label {{ color: var(--ink); font-weight: 500; }}
  td .n {{ font-size: 11px; color: var(--ink-mute); font-family: 'Inconsolata', monospace; }}
  .winner td {{ color: var(--ink); font-weight: 500; }}
  .winner td:first-child {{ position: relative; padding-left: 14px; }}
  .winner td:first-child::before {{
    content: ''; position: absolute; left: 0; top: 50%;
    transform: translateY(-50%); width: 4px; height: 4px;
    border-radius: 50%; background: var(--accent);
  }}
  .stat-row {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 0;
    margin: 1.5rem 0; border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule); padding: 1.5rem 0;
  }}
  .stat {{ padding: 0 1rem; border-right: 1px solid var(--rule); }}
  .stat:last-child {{ border-right: none; }}
  .stat:first-child {{ padding-left: 0; }}
  .stat-label {{
    font-family: 'Inconsolata', monospace; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--ink-mute); margin-bottom: 0.4rem;
  }}
  .stat-value {{
    font-family: 'Fraunces', serif; font-weight: 400;
    font-size: 30px; line-height: 1.1; color: var(--ink);
    font-variant-numeric: tabular-nums;
  }}
  .stat-value.acc {{ color: var(--accent); }}
  .stat-sub {{ font-size: 12px; color: var(--ink-mute); margin-top: 0.3rem; }}
  .chart-wrap {{
    background: var(--bg-card); border-radius: 4px;
    padding: 1.5rem 1.5rem 1rem; margin: 1.25rem 0;
  }}
  .chart-title {{ font-family: 'Manrope', sans-serif; font-weight: 600; font-size: 14px; margin-bottom: 0.25rem; }}
  .chart-sub {{ font-size: 12px; color: var(--ink-mute); margin-bottom: 1rem; }}
  .chart-legend {{ display: flex; gap: 1.25rem; margin-bottom: 0.5rem; font-size: 12px; color: var(--ink-soft); flex-wrap: wrap; }}
  .chart-legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
  .chart-legend .sw {{ width: 10px; height: 10px; border-radius: 1px; display: inline-block; }}
  .chart-canvas {{ position: relative; width: 100%; height: 280px; }}
  .verdict {{
    display: inline-block; padding: 2px 8px; border-radius: 3px;
    font-family: 'Inconsolata', monospace; font-size: 11px;
    font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase;
  }}
  .verdict.sig {{ background: var(--positive); color: var(--bg); }}
  .verdict.dir {{ background: var(--warn); color: var(--bg); }}
  .verdict.no {{ background: var(--rule); color: var(--ink-mute); }}
  footer {{
    margin-top: 3rem; padding-top: 1.5rem;
    border-top: 1px solid var(--rule);
    font-family: 'Inconsolata', monospace; font-size: 12px;
    color: var(--ink-mute); line-height: 1.7;
  }}
  @media print {{
    body {{ background: white; color: black; }}
    .page {{ padding: 1.5cm; max-width: none; }}
    .chart-wrap {{ break-inside: avoid; background: #F8F6F2; }}
    section, table {{ break-inside: avoid; }}
    h2 {{ break-after: avoid; }}
  }}
  @media (max-width: 600px) {{
    .page {{ padding: 2rem 1.25rem; }}
    .stat-row {{ grid-template-columns: 1fr; }}
    .stat {{ border-right: none; border-bottom: 1px solid var(--rule); padding: 0.75rem 0; }}
    .stat:last-child {{ border-bottom: none; }}
    table {{ font-size: 13px; }}
  }}
</style>
</head>
<body>
<div class="page">

  <div class="eyebrow">Quarterly Skill Review · {run_date}</div>
  <h1>Where the skill <em>actually</em> sits.</h1>
  <p class="deck">An honest, statistically-grounded snapshot of MTT skill progression — independent of variance, independent of dollar swings.</p>
  <div class="byline">Dataset: {headline['lifetime']['tnys']:,} tournaments · {headline['lifetime']['bullets']:,} bullets · ${headline['lifetime']['cost']:,.0f} invested · lifetime ROI {headline['lifetime']['roi_pct']:+.1f}%</div>

  <!-- Headline -->
  <section>
    <h2><span class="num">01 · Snapshot</span>Right now, by the numbers.</h2>
    <div class="stat-row">
      <div class="stat">
        <div class="stat-label">Current ranking</div>
        <div class="stat-value acc">{headline['recent_quarter']['ranking']}</div>
        <div class="stat-sub">last 3 months · AvgF {headline['recent_quarter']['avgf_pct']:.1f}%</div>
      </div>
      <div class="stat">
        <div class="stat-label">Avg buy-in (current)</div>
        <div class="stat-value">${headline['recent_quarter']['avg_bi']:.0f}</div>
        <div class="stat-sub">lifetime avg ${headline['lifetime']['avg_bi']:.0f}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Recent-quarter ROI</div>
        <div class="stat-value">{headline['recent_quarter']['roi_pct']:+.0f}%</div>
        <div class="stat-sub">lifetime ROI {headline['lifetime']['roi_pct']:+.1f}%</div>
      </div>
    </div>
  </section>

  <!-- Within-tier improvement -->
  <section>
    <h2><span class="num">02 · Per-tier progression</span>Where you actually got better.</h2>
    <p>Aggregate AvgF can hide real improvement when you simultaneously move into harder pools (Simpson's paradox). The honest view is stratified by buy-in tier — each tier compared first-half-of-history vs second-half, with confidence levels via Welch's t-test.</p>
    <table>
      <thead><tr>
        <th>BI tier</th>
        <th class="r">n</th>
        <th class="r">1st half</th>
        <th class="r">2nd half</th>
        <th class="r">Δ AvgF</th>
        <th>Verdict</th>
      </tr></thead>
      <tbody>{''.join(tier_table_rows)}</tbody>
    </table>
  </section>

  <!-- Rolling tier dashboard -->
  <section>
    <h2><span class="num">03 · The dashboard</span>Per-tier rolling AvgF (3-month windows).</h2>
    <p>Each cell = mean finish percentile across all tournaments in that BI tier × 3-month window (min n=30 to render). Lower = better. Drift downward in a tier's column = real skill improvement at that stake level.</p>
    <table style="font-size: 13px;">
      <thead>{dash_header}</thead>
      <tbody>{''.join(dash_rows)}</tbody>
    </table>
  </section>

  <!-- Aggregate trajectory chart -->
  <section>
    <h2><span class="num">04 · Aggregate trajectory</span>Twelve months in one picture.</h2>
    <div class="chart-wrap">
      <div class="chart-title">Rolling AvgF + avg buy-in</div>
      <div class="chart-sub">3-month windows. AvgF declining while BI rises = improving skill at progressively harder stakes.</div>
      <div class="chart-legend">
        <span><span class="sw" style="background: var(--accent);"></span>AvgF % (left axis, lower=better)</span>
        <span><span class="sw" style="background: #5C8AB4;"></span>Avg buy-in $ (right axis)</span>
      </div>
      <div class="chart-canvas">
        <canvas id="trendChart" role="img" aria-label="Trailing AvgF and average buy-in over time">Rolling AvgF and avg BI trajectory across the dataset window.</canvas>
      </div>
    </div>
  </section>

  <!-- Ranking framework -->
  <section>
    <h2><span class="num">05 · The framework</span>Calibration to typical MTT players.</h2>
    <table>
      <thead><tr><th>Tier</th><th class="r">AvgF range</th><th>Description</th></tr></thead>
      <tbody>{''.join(ranking_rows)}</tbody>
    </table>
  </section>

  <!-- Methodology footer -->
  <footer>
    <p><strong>Methodology.</strong> Avg finish percentile = (finish_place / total_players) averaged over tournaments. Per-tier comparisons use Welch's t-test (continuous-distribution version, robust to unequal variance). Confidence = 1 − p. Verdicts: significant p&lt;0.05, directional p&lt;0.20, otherwise inconclusive. Buy-in tiers: Micro &lt;$10, Low $10-25, Mid $25-50, High $50-100, Premium $100+. Satellites included in main aggregate per author convention (a ticket has dollar value).</p>
    <p><strong>Limitations.</strong> Field-size invariance is a property of percentile metrics — meaning a 36% finish in a 67-player satellite counts the same as a 36% in a 20K-player main event. AvgF doesn't predict next-period ROI; it tracks the skill component independently of variance. With this dataset's tournament volume, even significant findings should be retested as the sample grows.</p>
    <p>Run {run_date} · open to peer review.</p>
  </footer>

</div>

{chart_inline}
<script>
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const accent = dark ? '#D67881' : '#8B2635';
  const blue = dark ? '#9DBADD' : '#5C8AB4';
  const inkMute = dark ? '#8A8074' : '#7A7065';
  const rule = dark ? '#3D3630' : '#C9BFA8';

  new Chart(document.getElementById('trendChart'), {{
    type: 'line',
    data: {{
      labels: {roll_labels!r},
      datasets: [
        {{
          label: 'AvgF %', data: {roll_avgf!r},
          borderColor: accent, backgroundColor: accent,
          borderWidth: 2, pointRadius: 3.5, pointBackgroundColor: accent,
          tension: 0.25, yAxisID: 'y',
        }},
        {{
          label: 'Avg BI $', data: {roll_bi!r},
          borderColor: blue, backgroundColor: blue,
          borderWidth: 2, borderDash: [5, 4],
          pointRadius: 3.5, pointBackgroundColor: blue,
          tension: 0.25, yAxisID: 'y1',
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        y: {{ position: 'left',
              ticks: {{ font: {{ family: 'Inconsolata', size: 11 }}, color: accent,
                       callback: v => v + '%' }},
              grid: {{ color: rule, drawBorder: false }} }},
        y1: {{ position: 'right',
               ticks: {{ font: {{ family: 'Inconsolata', size: 11 }}, color: blue,
                        callback: v => '$' + v }},
               grid: {{ display: false }} }},
        x: {{ ticks: {{ font: {{ family: 'Inconsolata', size: 10 }}, color: inkMute,
                       maxRotation: 0, autoSkip: false }},
              grid: {{ display: false }} }}
      }}
    }}
  }});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description='Generate quarterly skill review HTML.')
    ap.add_argument('--per-tourn', default=None,
                    help='Path to session_financials_per_tournament.csv. '
                         'Defaults: ./session_financials_per_tournament.csv, '
                         'then /mnt/project/session_financials_per_tournament.csv.')
    ap.add_argument('--out', default=None,
                    help='Output HTML path. Defaults: '
                         '/mnt/user-data/outputs/Skill_Review_YYYYMMDD.html')
    args = ap.parse_args()

    # Locate per-tournament CSV
    if args.per_tourn:
        per_tourn = args.per_tourn
    else:
        for p in ['session_financials_per_tournament.csv',
                  '/mnt/project/session_financials_per_tournament.csv']:
            if os.path.exists(p):
                per_tourn = p; break
        else:
            print('ERROR: per-tournament CSV not found. Specify --per-tourn.',
                  file=sys.stderr)
            sys.exit(1)

    print(f'Loading per-tournament data from {per_tourn}...')
    rows = load_per_tournament(per_tourn)
    print(f'  {len(rows)} tournaments loaded')

    print('Computing headline stats...')
    headline = headline_stats(rows)
    print(f'  Lifetime AvgF: {headline["lifetime"]["avgf_pct"]:.2f}% ({headline["lifetime"]["ranking"]})')
    print(f'  Recent quarter AvgF: {headline["recent_quarter"]["avgf_pct"]:.2f}% ({headline["recent_quarter"]["ranking"]})')

    print('Within-tier improvement tests...')
    tier_table = within_tier_improvement(rows)
    for t in tier_table:
        if t['verdict'].startswith('insufficient'):
            print(f'  {t["tier"]:<10} n={t["n"]:>4} — {t["verdict"]}')
        else:
            print(f'  {t["tier"]:<10} n={t["n"]:>4} {t["first_half_pct"]:>5.1f}% → '
                  f'{t["second_half_pct"]:>5.1f}% (conf {t["confidence"]:.0f}%, {t["verdict"]})')

    print('Aggregate rolling trajectory...')
    rolling = rolling_trajectory(rows, window_months=3, min_n=30)
    print(f'  {len(rolling)} rolling windows')

    print('Per-tier dashboard (rolling)...')
    # Re-use compute_tier_avgf_rolling from gem_summary_parser to keep one
    # source of truth for the tier-rolling logic.
    tier_dashboard = compute_tier_avgf_rolling(
        [{'date': r['date'], 'finish_pct': r['finish_pct'],
          'buyin_per_bullet': r['buyin_per_bullet']}
         for r in rows],
        window_months=3, min_n=30,
    )
    print(f'  {len(tier_dashboard)} (window, tier) entries')

    # Output
    run_date = _date_t.today().isoformat()
    out_path = args.out or f'/mnt/user-data/outputs/Skill_Review_{run_date.replace("-", "")}.html'
    print(f'Rendering HTML to {out_path}...')
    html = render_html(rows, headline, tier_table, rolling, tier_dashboard, run_date)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Done. {len(html):,} bytes.')


if __name__ == '__main__':
    main()
