"""v7.30 regression test: every non-empty csv_row metric must be rendered in the report.

If this test fails, it means a new csv_row key was added to gem_analyzer.py
but the corresponding Del 8 category in gem_report_draft.py wasn't updated.
Either add the key to a category or to the Uncategorized fallback gracefully.

Run as: python3 test_csv_row_complete.py
"""
import sys, os, glob, re
sys.path.insert(0, '/mnt/project')

import gem_parser, gem_analyzer
from gem_report_data import generate_report_data
from gem_report_draft import generate_report_draft

# Use the May 3-4 session as the test fixture
all_hands = []
tournaments = {}
n_files = 0
hh_dir = '/home/claude/session/'
if not os.path.isdir(hh_dir):
    print(f"⚠️ Skipping test_csv_row_complete: no session dir at {hh_dir}")
    sys.exit(0)
for fp in glob.glob(hh_dir + '*.txt'):
    n_files += 1
    fname = os.path.basename(fp)
    with open(fp) as f: content = f.read()
    fmt = 'BOUNTY' if 'bounty' in fp.lower() else 'FREEZEOUT'
    for chunk in re.split(r'(?=Poker Hand #TM)', content):
        if not chunk.strip(): continue
        try:
            h = gem_parser.parse_one_hand(chunk, fname)
            if h:
                all_hands.append(h)
                tid_m = re.search(r'Tournament #(\d+)', chunk)
                tid = tid_m.group(1) if tid_m else h.get('tournament','')
                if tid not in tournaments:
                    tournaments[tid] = {'name': h.get('tournament',''), 'format': h['format'], 'hands': [], 'buyin': h.get('buyin',0)}
                tournaments[tid]['hands'].append(h)
        except: pass

ranges = gem_analyzer.load_ranges('/mnt/project/Poker_Ranges_Text.txt')
stats = gem_analyzer.analyze_session(all_hands, tournaments, n_files, 0, ranges=ranges)
report_data = generate_report_data(stats, all_hands, hh_dir)
report_md = generate_report_draft(stats, all_hands, report_data)

# Test: every non-empty csv_row key value should appear in the report MD
csv_row = stats.get('csv_row', {})
failures = []
warnings = []
for key, val in csv_row.items():
    if val in ('', None):
        continue
    # Check the KEY name appears (in the Del 8 reference table)
    pretty = key.replace('_', ' ')
    if pretty not in report_md and key not in report_md:
        failures.append(f"  '{key}' (value={val}) — neither '{pretty}' nor '{key}' appears in report")

# Also: report must contain the Del 8 anchor
if '## Del 8: Complete Stat Reference' not in report_md:
    failures.append("Del 8: Complete Stat Reference section missing from report")

# Specific Ron-flagged metrics MUST appear in Del 2B (not just Del 8 appendix)
del_2b_start = report_md.find('## Del 2B: Core Stats')
del_2b_end = report_md.find('## ', del_2b_start + 5) if del_2b_start > 0 else -1
del_2b_section = report_md[del_2b_start:del_2b_end] if del_2b_start > 0 else ''
RON_REQUIRED_IN_DEL_2B = ['AF', 'ATS', '3-Bet', 'Cold Call', 'True PFR', 'WTSD', 'WSD']
for required in RON_REQUIRED_IN_DEL_2B:
    if required not in del_2b_section:
        failures.append(f"Ron-required metric '{required}' missing from Del 2B headline section")

if failures:
    print("❌ FAILURES:")
    for f in failures:
        print(f)
    print(f"\nTotal failures: {len(failures)}")
    sys.exit(1)
else:
    print(f"✅ ALL CSV_ROW METRICS SURFACED IN REPORT")
    print(f"   {len(csv_row)} csv_row keys, {sum(1 for v in csv_row.values() if v not in ('', None))} non-empty")
    print(f"   Del 8: Complete Stat Reference present")
    print(f"   Del 2B contains all Ron-required metrics: {', '.join(RON_REQUIRED_IN_DEL_2B)}")
