#!/usr/bin/env python3
"""
gem_squares_report.py — v7.26

Markdown report for gem_squares.json snapshot + gem_squares_history.json.

Output sections:
  1. Aggregated Story (TLDR narrative — top of report)
  2. Top-20 Squares by Study Score
  3. Watch List (regime-flagged)
  4. Split / Merge Proposals
  5. Trajectory (when history available)

Usage:
  python3 gem_squares_report.py
  python3 gem_squares_report.py --squares gem_squares.json --output report.md
"""

import os
import sys
import json
import argparse
from datetime import datetime


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def fmt_pct(x, decimals=1):
    if x is None:
        return "—"
    return f"{x:.{decimals}f}%"


def fmt_bb(x, decimals=2):
    if x is None:
        return "—"
    sign = "+" if x > 0 else ""
    return f"{sign}{x:.{decimals}f}bb"


def aggregated_story(snapshot, history):
    """
    Narrative TLDR. The point: Ron wants to know the story, not read tables.
    """
    squares = snapshot.get("squares", [])
    total_hands = snapshot.get("total_hands", 0)
    if not squares:
        return "_(no squares; check input data)_"

    # Top 5 study targets
    top_5 = squares[:5]

    # Total estimated leak across all losing squares
    losing_squares = [s for s in squares if s["net_bb_mean"] < 0]
    total_loss_bb = sum(s["net_bb_mean"] * s["n_total"] for s in losing_squares)

    # Regime breakdown
    regressing = [s for s in squares if s["regime_flag"] == "regressing"]
    improving = [s for s in squares if s["regime_flag"] == "improving"]

    # Splits / merges
    split_n = sum(1 for s in squares if s["split_candidate"])
    merge_n = sum(1 for s in squares if s["merge_candidate"])

    # Pot-weighted leak concentration
    top_5_score = sum(s["study_score"] for s in top_5)
    total_score = sum(s["study_score"] for s in squares) or 1.0
    concentration_pct = top_5_score / total_score * 100

    # Build story
    lines = []
    lines.append(f"**{total_hands:,} hands** across **{len(squares)} active squares**.")
    lines.append("")

    if top_5:
        top_target = top_5[0]
        lines.append(
            f"**Top study target:** `{top_target['square_id']}` — "
            f"{top_target['n_total']:,} hands, "
            f"{fmt_bb(top_target['net_bb_mean'])}/hand, "
            f"{fmt_pct(top_target['freq_pct'])} of volume. "
            f"Total leak ≈ {top_target['net_bb_mean'] * top_target['n_total']:.0f}bb."
        )

    lines.append(
        f"**Top-5 squares concentrate {concentration_pct:.0f}% of total study score** — "
        f""
        + ("highly concentrated leak profile, focus there." if concentration_pct > 60
           else "leak is distributed; broader study allocation warranted.")
    )

    if losing_squares:
        lines.append(
            f"**{len(losing_squares)} losing squares** account for "
            f"~{abs(total_loss_bb):,.0f}bb of realized loss "
            f"(unadjusted for hand-strength composition — see caveat below)."
        )

    if regressing:
        names = ", ".join(f"`{s['square_id']}`" for s in regressing[:3])
        more = f" + {len(regressing) - 3} more" if len(regressing) > 3 else ""
        lines.append(
            f"**Regressing (recent worse than long-term):** {names}{more} — "
            f"closed leaks reopening or new spots emerging in last 30d."
        )

    if improving:
        names = ", ".join(f"`{s['square_id']}`" for s in improving[:3])
        more = f" + {len(improving) - 3} more" if len(improving) > 3 else ""
        lines.append(
            f"**Improving:** {names}{more} — recent EWMA above long-term mean. "
            f"Study from prior cycles likely paying off."
        )

    if split_n or merge_n:
        lines.append(
            f"**Granularity:** {split_n} split candidates "
            f"(high within-square variance + sample), "
            f"{merge_n} merge candidates (low n + similar to neighbor). "
            f"Approve before next cycle."
        )

    if history and len(history) >= 2:
        prev = history[-2]
        cur = history[-1]
        delta_score_top = (
            (cur["summaries"][0]["study_score"] if cur["summaries"] else 0)
            - (prev["summaries"][0]["study_score"] if prev["summaries"] else 0)
        )
        if abs(delta_score_top) > 0.01:
            direction = "down" if delta_score_top < 0 else "up"
            lines.append(
                f"**Trajectory:** top-square study score moved {direction} "
                f"({delta_score_top:+.2f}) since prior snapshot."
            )

    lines.append("")
    lines.append(
        "_Caveat: net_bb is realized result, biased by hand-strength composition. "
        "Cross-square comparison should account for this. v7.26 limitation; "
        "v7.27 candidate is hand-strength-normalized leak score._"
    )

    return "\n".join(lines)


def top_squares_table(snapshot, n=20):
    squares = snapshot.get("squares", [])[:n]
    if not squares:
        return "_(empty)_"
    lines = []
    lines.append("| # | Square | Kind | n | Freq% | Avg pot | Net bb/hand | Study score | Regime |")
    lines.append("|---|--------|------|---|-------|---------|-------------|-------------|--------|")
    for i, s in enumerate(squares, 1):
        flag_emoji = {
            "improving": "🟢",
            "regressing": "🔴",
            "stable": "⚪",
            "insufficient": "⚫",
        }.get(s["regime_flag"], "⚫")
        lines.append(
            f"| {i} | `{s['square_id']}` | {s['kind']} | {s['n_total']:,} | "
            f"{s['freq_pct']:.2f} | {s['avg_pot_bb']:.1f}bb | "
            f"{fmt_bb(s['net_bb_mean'])} | {s['study_score']:.2f} | "
            f"{flag_emoji} {s['regime_flag']} |"
        )
    return "\n".join(lines)


def watch_list(snapshot):
    squares = snapshot.get("squares", [])
    flagged = [s for s in squares if s["regime_flag"] in ("regressing", "improving")]
    if not flagged:
        return "_(no squares flagged for regime change)_"
    lines = []
    lines.append("| Square | Regime | n | Long-term net | EWMA recent | Δz |")
    lines.append("|--------|--------|---|---------------|-------------|----|")
    flagged.sort(key=lambda s: abs(s.get("delta_z") or 0), reverse=True)
    for s in flagged[:15]:
        emoji = "🔴" if s["regime_flag"] == "regressing" else "🟢"
        lines.append(
            f"| `{s['square_id']}` | {emoji} {s['regime_flag']} | {s['n_total']:,} | "
            f"{fmt_bb(s['net_bb_mean'])} | {fmt_bb(s['ewma_recent'])} | "
            f"{s['delta_z']:.2f} |"
        )
    return "\n".join(lines)


def split_merge_section(snapshot):
    squares = snapshot.get("squares", [])
    splits = [s for s in squares if s["split_candidate"]]
    merges = [s for s in squares if s["merge_candidate"]]
    out = []
    if splits:
        out.append("**Split candidates** (high within-square variance + n ≥ 200):\n")
        for s in splits[:10]:
            out.append(
                f"- `{s['square_id']}` — n={s['n_total']:,}, "
                f"variance={s['net_bb_variance']:.1f}, "
                f"σ={s['net_bb_stddev']:.2f}bb. "
                f"Likely hiding heterogeneous sub-spots."
            )
    if merges:
        out.append("\n**Merge candidates** (n < 50 + profile matches neighbor):\n")
        for s in merges[:10]:
            out.append(
                f"- `{s['square_id']}` — n={s['n_total']}, "
                f"net={fmt_bb(s['net_bb_mean'])}. "
                f"Sample too small; consider folding into nearest neighbor."
            )
    if not out:
        return "_(no proposals)_"
    return "\n".join(out)


def trajectory_section(history):
    if not history or len(history) < 2:
        return "_(history insufficient — need ≥ 2 snapshots)_"
    out = []
    out.append(f"**{len(history)} snapshots** stored.")
    out.append("")
    # Compare last 2 snapshots — top movers
    prev = {s["square_id"]: s for s in history[-2]["summaries"]}
    cur = {s["square_id"]: s for s in history[-1]["summaries"]}
    deltas = []
    for sid, s in cur.items():
        if sid in prev:
            d = s["study_score"] - prev[sid]["study_score"]
            if abs(d) > 0.01:
                deltas.append((sid, d, prev[sid]["study_score"], s["study_score"]))
    deltas.sort(key=lambda x: abs(x[1]), reverse=True)
    if deltas:
        out.append(f"**Top movers vs prior snapshot ({history[-2]['generated_at'][:10]} → {history[-1]['generated_at'][:10]}):**\n")
        for sid, d, before, after in deltas[:10]:
            arrow = "↑" if d > 0 else "↓"
            out.append(f"- `{sid}` {arrow} {d:+.2f} ({before:.2f} → {after:.2f})")
    return "\n".join(out)


def generate_report(snapshot, history):
    generated = snapshot.get("generated_at", "")
    total_hands = snapshot.get("total_hands", 0)
    n_squares = snapshot.get("n_squares", 0)

    sections = []
    sections.append(f"# GEM Squares Report — v{snapshot.get('version', '7.26')}")
    sections.append(f"_Generated {generated} | {total_hands:,} hands | {n_squares} squares_\n")

    sections.append("## TLDR — Aggregated Story\n")
    sections.append(aggregated_story(snapshot, history))
    sections.append("")

    sections.append("## Top 20 Squares by Study Score\n")
    sections.append(top_squares_table(snapshot, n=20))
    sections.append("")

    sections.append("## Watch List — Regime Changes\n")
    sections.append(watch_list(snapshot))
    sections.append("")

    sections.append("## Granularity Proposals\n")
    sections.append(split_merge_section(snapshot))
    sections.append("")

    sections.append("## Trajectory\n")
    sections.append(trajectory_section(history))
    sections.append("")

    sections.append("---")
    sections.append("_Generated by gem_squares_report.py v7.26._")

    return "\n".join(sections)


def main():
    ap = argparse.ArgumentParser(description="GEM v7.26 squares report generator")
    ap.add_argument("--squares", default="gem_squares.json", help="Snapshot input")
    ap.add_argument("--history", default="gem_squares_history.json", help="History input")
    ap.add_argument("--output", default="gem_squares_report.md", help="Markdown output")
    args = ap.parse_args()

    snapshot = load_json(args.squares, default={})
    if not snapshot:
        sys.stderr.write(f"[gem_squares_report] could not load {args.squares}\n")
        sys.exit(1)
    history = load_json(args.history, default=[])

    report = generate_report(snapshot, history)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)
    sys.stderr.write(f"[gem_squares_report] wrote {args.output}\n")


if __name__ == "__main__":
    main()
