#!/usr/bin/env python3
"""
gem_report_diff.py — Compare two GEM report HTMLs and show what changed.

Usage:
    python gem_report_diff.py old.html new.html [--output diff.md]

Extracts key metrics per section (hand counts, rates, verdicts, stat cards)
and outputs a structured diff. Useful for verifying analyst edits landed
or catching regressions between code versions.
"""
import re
import sys
import json


def extract_metrics(html):
    """Extract key metrics from a rendered GEM report HTML."""
    metrics = {}

    # Stat cards
    stat_cards = re.findall(
        r"class=['\"]stat-card[^'\"]*['\"][^>]*>.*?<b>([^<]+)</b>.*?<small>([^<]+)</small>",
        html, re.DOTALL)
    for value, label in stat_cards:
        metrics[f'stat:{label.strip()}'] = value.strip()

    # Section headings with their IDs
    for m in re.finditer(r'id=["\']?(sec-\d+)["\']?[^>]*>.*?<h2[^>]*>(.*?)</h2>', html, re.DOTALL):
        sec_id = m.group(1)
        heading = re.sub(r'<[^>]+>', '', m.group(2)).strip()[:60]
        metrics[f'section:{sec_id}'] = heading

    # Hand-ref count
    n_refs = len(re.findall(r'class=["\']hand-ref["\']', html))
    metrics['hand_refs'] = str(n_refs)

    # Appendix entries
    n_app = len(re.findall(r'id=["\']sec-app-hand-', html))
    metrics['appendix_entries'] = str(n_app)

    # Verdict counts (from rendered text)
    for verdict in ['I.7 Cooler', 'III.1 Punt', 'III.2 Mistake',
                     'III.3 Cleared', 'III.4 Read-dependent',
                     'III.5 Justified', 'III.8 Pick']:
        count = html.count(verdict)
        if count:
            metrics[f'verdict:{verdict}'] = str(count)

    # Draw profile count
    n_dp = html.count("class='draw-profile'") + html.count('class="draw-profile"')
    metrics['draw_profiles'] = str(n_dp)

    # Hand grids
    n_grid = html.count("class='hand-grid'") + html.count('class="hand-grid"')
    metrics['hand_grids'] = str(n_grid)

    # Analyst notes blocks
    n_notes = html.count('analyst-notes')
    metrics['analyst_notes'] = str(n_notes)

    # Collapsed sections
    n_collapsed = len(re.findall(r'<details><summary><h2', html))
    metrics['collapsed_sections'] = str(n_collapsed)

    # Live triggers
    n_triggers = html.count('hand-list-trigger')
    metrics['hand_list_triggers'] = str(n_triggers)

    # Broken anchors
    hrefs = set(re.findall(r'href=["\']#([^"\']+)["\']', html))
    ids = set(re.findall(r'id=["\']([^"\']+)["\']', html))
    broken = [h for h in hrefs if h not in ids
              and 'sec-app-hand-' not in h
              and "'+id+'" not in h]
    metrics['broken_anchors'] = str(len(broken))

    return metrics


def diff_reports(old_html, new_html):
    """Compare two reports and return a structured diff."""
    old = extract_metrics(old_html)
    new = extract_metrics(new_html)

    all_keys = sorted(set(old.keys()) | set(new.keys()))
    changes = []
    added = []
    removed = []

    for k in all_keys:
        ov = old.get(k)
        nv = new.get(k)
        if ov is None:
            added.append((k, nv))
        elif nv is None:
            removed.append((k, ov))
        elif ov != nv:
            changes.append((k, ov, nv))

    return changes, added, removed


def format_diff_md(changes, added, removed):
    """Format the diff as readable markdown."""
    lines = ['# GEM Report Diff', '']

    if not changes and not added and not removed:
        lines.append('**No differences found.**')
        return '\n'.join(lines)

    if changes:
        lines.append(f'## Changed ({len(changes)})')
        lines.append('')
        lines.append('| Metric | Old | New |')
        lines.append('|--------|-----|-----|')
        for k, ov, nv in changes:
            lines.append(f'| {k} | {ov} | {nv} |')
        lines.append('')

    if added:
        lines.append(f'## Added ({len(added)})')
        lines.append('')
        for k, v in added:
            lines.append(f'- **{k}**: {v}')
        lines.append('')

    if removed:
        lines.append(f'## Removed ({len(removed)})')
        lines.append('')
        for k, v in removed:
            lines.append(f'- ~~{k}~~: was {v}')
        lines.append('')

    return '\n'.join(lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: python gem_report_diff.py old.html new.html [--output diff.md]")
        sys.exit(1)

    old_path = sys.argv[1]
    new_path = sys.argv[2]
    output_path = None
    if '--output' in sys.argv:
        idx = sys.argv.index('--output')
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    old_html = open(old_path, encoding='utf-8').read()
    new_html = open(new_path, encoding='utf-8').read()

    changes, added, removed = diff_reports(old_html, new_html)
    md = format_diff_md(changes, added, removed)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(md)
        print(f"Diff written to {output_path}")
    else:
        print(md)

    # Summary
    print(f"\n{len(changes)} changed, {len(added)} added, {len(removed)} removed")


if __name__ == '__main__':
    main()
