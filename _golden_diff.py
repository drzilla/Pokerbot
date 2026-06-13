"""Post-conversion golden diff: compare pre vs post rendered markdown lines.

Shows exactly which table regions changed and how.
Usage: python -X utf8 _golden_diff.py
"""
import sys, os, json, difflib

_HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
sys.path.insert(0, _HERE)

from test_content_parity import _minimal_fixture
from gem_report_draft.draft import _build
from gem_report_draft._html import Doc

# Load pre-conversion golden
with open(os.path.join(_HERE, '_golden_pre.json'), 'r', encoding='utf-8') as f:
    pre_tables = json.load(f)

# Build post-conversion
s, rd, hands = _minimal_fixture()
doc = _build(s, rd, hands)
post_lines = doc.lines[:]

# Save full post HTML for manual inspection
html = doc.render_html()
with open(os.path.join(_HERE, '_golden_post_full.html'), 'w', encoding='utf-8') as f:
    f.write(html)

# Extract the same line ranges from post-conversion, PLUS scan for new
# metric_table blocks in the block registry
print("=" * 70)
print("GOLDEN HTML DIFF — pre vs post conversion (B.0-B.4)")
print("=" * 70)

# Full markdown diff — find ALL changed regions
pre_path = os.path.join(_HERE, '_golden_pre_full.html')
if os.path.exists(pre_path):
    with open(pre_path, 'r', encoding='utf-8') as f:
        pre_html = f.read()
    # Character-level summary
    if pre_html == html:
        print("\nFull HTML: BYTE-IDENTICAL (unexpected — T4/T5/T6 should differ)")
    else:
        print(f"\nFull HTML: DIFFERS (pre={len(pre_html)} chars, post={len(html)} chars)")

# Now diff at the markdown-line level for precision
# Re-build pre-conversion lines from saved golden JSON snapshot
# Instead, let's do a line-by-line diff of the rendered markdown
# Load pre-conversion full markdown
pre_build_path = os.path.join(_HERE, '_golden_pre_md.json')
# We didn't save pre-md, so let's work from the HTML tables
# Better: diff the markdown lines by re-reading the pre golden tables
# and comparing against the same line positions in post

print("\n" + "-" * 70)
print("PER-TABLE COMPARISON")
print("-" * 70)

# Map golden pre tables to approximate post locations by scanning for
# the same anchor content
STAT_HEADER = Doc.STAT_HEADER.strip()

# Find all stat-table regions in post
post_tables = {}
i = 0
table_idx = 0
while i < len(post_lines):
    line = post_lines[i]
    if line.strip() == STAT_HEADER:
        start = i
        j = i + 1
        while j < len(post_lines) and post_lines[j].strip():
            j += 1
        table_idx += 1
        post_tables[f'post_stat_{table_idx}'] = {
            'start': start, 'end': j,
            'lines': post_lines[start:j],
        }
        i = j
        continue
    i += 1

# Pre tables: stat_table_1 (T1), stat_table_2 (T2), old_header_table_3 (T4),
#             old_header_table_4 (T5), stat_table_5 (T3), orphan_table_6 (T6)
# Post tables: should have stat tables for T1, T2, T4, T5, T3, T6 all with
#              the canonical 7-col header

# Map by order
pre_keys = sorted(pre_tables.keys())
post_keys = sorted(post_tables.keys())

print(f"\nPre-conversion: {len(pre_keys)} table regions")
for k in pre_keys:
    t = pre_tables[k]
    print(f"  {k}: {len(t['lines'])} lines at {t['start']}-{t['end']}")

print(f"\nPost-conversion: {len(post_keys)} table regions")
for k in post_keys:
    t = post_tables[k]
    print(f"  {k}: {len(t['lines'])} lines at {t['start']}-{t['end']}")

# Now do contextual matching — match by looking at the data rows
# T1: has "VPIP" as first data row
# T2: has "AF" as first data row
# T3: has "HU IP" as first data row
# T4: has "Float Flop" as first data row
# T5: has "BB Iso" as first data row
# T6: has "Caller IP" as first data row

def first_data_keyword(lines):
    """Return first few words of first data row (after header+sep)."""
    for line in lines:
        if line.startswith('|') and '---' not in line and 'Metric' not in line and 'Value' not in line:
            return line.split('|')[1].strip()[:30]
    return '(no data)'

# Print diffs for each pre table against its best post match
label_map = {
    'stat_table_1': 'T1 Pre-Flop KPIs',
    'stat_table_2': 'T2 Post-Flop KPIs',
    'old_header_table_3': 'T4 Group A Float/CR',
    'old_header_table_4': 'T5 Group B BB Iso',
    'stat_table_5': 'T3 C-Bet Split',
    'orphan_table_6': 'T6 Caller IP',
}

# Match post tables by keyword
post_by_keyword = {}
for k, t in post_tables.items():
    kw = first_data_keyword(t['lines'])
    post_by_keyword[kw] = (k, t)

pre_by_keyword = {}
for k, t in pre_tables.items():
    kw = first_data_keyword(t['lines'])
    pre_by_keyword[kw] = (k, t)

# Known keyword matches
matches = [
    ('VPIP', 'T1 Pre-Flop KPIs', False),  # not converted yet
    ('[AF](#sec-11-10)', 'T2 Post-Flop KPIs', False),  # not converted yet
    ('Float Flop (Call CBet IP)', 'T4 Float/CR', True),
    ('BB Iso vs SB Limp', 'T5 BB Iso', True),
    ('HU IP', 'T3 C-Bet Split', True),
    ('Caller IP Aggression (HU)', 'T6 Caller IP', True),
]

for kw_prefix, label, converted in matches:
    print(f"\n{'=' * 60}")
    print(f"TABLE: {label} (converted={converted})")
    print(f"{'=' * 60}")

    # Find pre
    pre_match = None
    for kw, (k, t) in pre_by_keyword.items():
        if kw.startswith(kw_prefix) or kw_prefix in kw:
            pre_match = t
            break

    # Find post
    post_match = None
    for kw, (k, t) in post_by_keyword.items():
        if kw.startswith(kw_prefix) or kw_prefix in kw:
            post_match = t
            break

    if not pre_match:
        print("  PRE: not found!")
        continue
    if not post_match:
        print("  POST: not found!")
        continue

    pre_lines = pre_match['lines']
    post_lines_t = post_match['lines']

    if pre_lines == post_lines_t:
        print("  BYTE-IDENTICAL ✅")
    else:
        print(f"  DIFFERS: pre={len(pre_lines)} lines, post={len(post_lines_t)} lines")
        diff = list(difflib.unified_diff(
            pre_lines, post_lines_t,
            fromfile='PRE', tofile='POST',
            lineterm=''))
        for d in diff:
            print(f"  {d}")

# Block registry check
print(f"\n{'=' * 60}")
print("BLOCK REGISTRY — metric_table blocks")
print(f"{'=' * 60}")
mt_blocks = [e for e in doc._block_registry if e['block']['type'] == 'metric_table']
print(f"Found {len(mt_blocks)} metric_table blocks:")
for e in mt_blocks:
    blk = e['block']
    n_rows = len(blk.get('rows', []))
    n_raw = sum(1 for r in blk.get('rows', []) if isinstance(r, str))
    n_dict = n_rows - n_raw
    print(f"  {blk['id']}: {n_rows} rows ({n_dict} dict + {n_raw} raw), "
          f"lines {e['start_line']}-{e['end_line']}")
