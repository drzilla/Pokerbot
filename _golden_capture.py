"""Capture pre-conversion rendered HTML for the 6 stat-table sections.

Writes _golden_pre.json with line-range extracts for each table, keyed by
a label (T1-T6). Also saves the full rendered HTML for unrestricted diffing.

Usage: python -X utf8 _golden_capture.py
"""
import sys, os, json, re

_HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
sys.path.insert(0, _HERE)

from test_content_parity import _minimal_fixture
from gem_report_draft.draft import _build
from gem_report_draft._html import Doc

s, rd, hands = _minimal_fixture()
doc = _build(s, rd, hands)
html = doc.render_html()
md_lines = doc.lines[:]  # raw markdown lines before HTML wrap

# Save full HTML
with open(os.path.join(_HERE, '_golden_pre_full.html'), 'w', encoding='utf-8') as f:
    f.write(html)

# Extract stat-table regions from markdown lines.
# A stat table starts with Doc.STAT_HEADER and ends at the next blank line.
# Also capture T4/T5 manual headers (old 6-col) and T6 orphan rows.
STAT_HEADER = Doc.STAT_HEADER

tables = {}
i = 0
table_idx = 0
while i < len(md_lines):
    line = md_lines[i]
    # Detect stat table by header (T1, T2, T3 use stat_table_open)
    if line.strip() == STAT_HEADER.strip():
        start = i
        # Collect until blank line
        j = i + 1
        while j < len(md_lines) and md_lines[j].strip():
            j += 1
        table_idx += 1
        tables[f'stat_table_{table_idx}'] = {
            'start': start,
            'end': j,
            'lines': md_lines[start:j],
        }
        i = j
        continue
    # Detect T4/T5 old manual headers
    if '| Metric | Value (n) | CI 90% | Tentative Target | Status | Notes |' in line:
        start = i
        j = i + 1
        while j < len(md_lines) and md_lines[j].strip():
            j += 1
        table_idx += 1
        tables[f'old_header_table_{table_idx}'] = {
            'start': start,
            'end': j,
            'lines': md_lines[start:j],
        }
        i = j
        continue
    # Detect T6 orphan: _stat_row_pct lines starting with "| Caller IP"
    if line.startswith('| Caller IP Aggression'):
        start = i
        j = i + 1
        while j < len(md_lines) and md_lines[j].strip() and md_lines[j].startswith('|'):
            j += 1
        table_idx += 1
        tables[f'orphan_table_{table_idx}'] = {
            'start': start,
            'end': j,
            'lines': md_lines[start:j],
        }
        i = j
        continue
    i += 1

# Save extracts
with open(os.path.join(_HERE, '_golden_pre.json'), 'w', encoding='utf-8') as f:
    json.dump(tables, f, indent=2, ensure_ascii=False)

print(f"Captured {len(tables)} table regions from {len(md_lines)} markdown lines")
for k, v in tables.items():
    print(f"  {k}: lines {v['start']}-{v['end']} ({len(v['lines'])} rows)")
    for row in v['lines'][:3]:
        print(f"    {row[:100]}")
    if len(v['lines']) > 3:
        print(f"    ... ({len(v['lines'])-3} more)")
