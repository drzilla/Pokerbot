#!/usr/bin/env python3
"""GEM Schema Drift Checker — compares analyzer output files against
gem_schema.json and warns when fields drift.

gem_schema.json is the human-readable field dictionary used as the
source of truth for:
  - gem_hands.json       (top-level: list of hand dicts; schema docs each field)
  - gem_stats.json       (top-level: dict; schema lists each section key)
  - gem_report_data.json (top-level: dict; schema lists each section key)

This script compares each output file's actual keys against what the
schema documents and flags:
  🟡 EXTRA      — field present in output but NOT documented in schema
                 (probably a new field you added — update the schema)
  🔴 MISSING    — field documented in schema but NOT emitted by analyzer
                 (probably a regression — restore the field or remove
                  the schema entry)
  🟢 OK         — field name appears in both

Exit code: 0 if no MISSING entries (extras are informational).
Usage:   python3 validate_schema.py [/path/to/output/dir]
         (defaults to /home/claude/ which is where the analyzer writes)

Run after every analyzer change. Complements test_detectors.py:
  - test_detectors.py: checks detector RULE behavior (which hands flag)
  - validate_schema.py: checks output STRUCTURE (which fields exist)
"""
import sys, os, json

OUTPUT_DIR = sys.argv[1] if len(sys.argv) > 1 else '/home/claude'
SCHEMA_PATH = '/mnt/project/gem_schema.json'
if not os.path.exists(SCHEMA_PATH):
    SCHEMA_PATH = os.path.join(os.path.dirname(__file__) or '.', 'gem_schema.json')

if not os.path.exists(SCHEMA_PATH):
    print(f"ERROR: gem_schema.json not found (tried /mnt/project/ and local)")
    sys.exit(2)

schema = json.load(open(SCHEMA_PATH))

# ============================================================
# EXPECTED SETS — extracted from schema
# ============================================================
expected_hand_fields   = set(schema.get('gem_hands_json', {}).get('fields', {}).keys())
expected_stats_keys    = set(schema.get('gem_stats_json', {}).get('top_level_keys', {}).keys())
expected_rd_keys       = set(schema.get('gem_report_data_json', {}).get('top_level_keys', {}).keys())

# ============================================================
# ACTUAL SETS — loaded from output files
# ============================================================
def load_actual(filename, get_keys):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return None, f"file not found at {path}"
    try:
        data = json.load(open(path))
        return get_keys(data), None
    except Exception as e:
        return None, str(e)

actual_hand_fields, err_h = load_actual('gem_hands.json',
    lambda d: set(d[0].keys()) if isinstance(d, list) and d else set())
actual_stats_keys, err_s = load_actual('gem_stats.json',
    lambda d: set(d.keys()) if isinstance(d, dict) else set())
actual_rd_keys, err_r = load_actual('gem_report_data.json',
    lambda d: set(d.keys()) if isinstance(d, dict) else set())

# ============================================================
# COMPARE + REPORT
# ============================================================
print("=" * 64)
print(f"GEM SCHEMA DRIFT CHECKER")
print(f"Schema: {SCHEMA_PATH}  (v{schema.get('_meta',{}).get('version','?')})")
print(f"Output: {OUTPUT_DIR}")
print("=" * 64)

total_missing = 0
total_extra = 0

def compare(label, expected, actual, err):
    global total_missing, total_extra
    print(f"\n[{label}]")
    if err:
        print(f"  ⚠️  SKIP: {err}")
        return
    # Filter out schema meta keys
    expected = {k for k in expected if not k.startswith('_')}
    actual = {k for k in actual if not k.startswith('_')}
    missing = expected - actual
    extra = actual - expected
    ok = expected & actual

    print(f"  schema: {len(expected)} fields | output: {len(actual)} fields | matching: {len(ok)}")

    if missing:
        print(f"  🔴 MISSING from output ({len(missing)}) — schema documents but analyzer isn't emitting:")
        for k in sorted(missing):
            desc = ''
            # Look up description if available
            src = schema.get(_section_for(label), {})
            entry = src.get('fields', src.get('top_level_keys', {})).get(k, {})
            if isinstance(entry, dict):
                desc = entry.get('description', '')[:60]
            elif isinstance(entry, str):
                desc = entry[:60]
            print(f"      {k}" + (f"  — {desc}" if desc else ''))
        total_missing += len(missing)
    if extra:
        print(f"  🟡 EXTRA in output ({len(extra)}) — new fields; update schema:")
        for k in sorted(extra):
            print(f"      {k}")
        total_extra += len(extra)
    if not missing and not extra:
        print(f"  ✅ IN SYNC")

def _section_for(label):
    return {'gem_hands.json': 'gem_hands_json',
            'gem_stats.json': 'gem_stats_json',
            'gem_report_data.json': 'gem_report_data_json'}[label]

compare('gem_hands.json',       expected_hand_fields, actual_hand_fields or set(), err_h)
compare('gem_stats.json',       expected_stats_keys,  actual_stats_keys  or set(), err_s)
compare('gem_report_data.json', expected_rd_keys,     actual_rd_keys     or set(), err_r)

# ============================================================
# SUMMARY
# ============================================================
print()
print("=" * 64)
if total_missing == 0 and total_extra == 0:
    print("✅ SCHEMA IN SYNC across all output files")
    sys.exit(0)
elif total_missing == 0:
    print(f"🟡 OK — {total_extra} EXTRA field(s). Schema needs updating to document new fields.")
    print("   (Not a failure: analyzer is emitting more than the schema knows about.)")
    sys.exit(0)
else:
    print(f"🔴 DRIFT — {total_missing} MISSING, {total_extra} EXTRA")
    print("   MISSING fields = likely regression in analyzer. Investigate.")
    sys.exit(1)
