"""
Windows runner for the full GEM pipeline.
Patches output paths for Windows compatibility, then runs gem_analyzer.py's
main logic inline (parse -> analyze -> report_data -> render HTML).
"""
import sys, os, json, time

# Fix Windows console encoding — allow emoji/Unicode in print output
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Ensure we're running from the GEM source directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

SESSION_DIR = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\ron\AppData\Local\Temp\gem_session_20260528'
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop')

print(f"GEM Pipeline Runner (Windows)")
print(f"Session dir: {SESSION_DIR}")
print(f"Output dir:  {OUT_DIR}")
print("=" * 60)

# ---- Parse ----
t0 = time.perf_counter()
from gem_parser import parse_session
hands, tournaments, n_files, errors = parse_session(SESSION_DIR)
t_parse = time.perf_counter() - t0
print(f"\nParsed: {len(hands)} hands, {len(tournaments)} tournaments, {n_files} files, {errors} errors ({t_parse:.1f}s)")
if not hands:
    print("ERROR: No hands parsed!")
    sys.exit(1)

# ---- Load ranges ----
from gem_analyzer import load_ranges, load_targets, sanity_check_ranges
_here = os.path.dirname(os.path.abspath(__file__)) or '.'
range_paths = [os.path.join(_here, 'Poker_Ranges_Text.txt'),
               os.path.join(SESSION_DIR, 'Poker_Ranges_Text.txt')]
ranges = {}
targets = {}
for rp in range_paths:
    if os.path.exists(rp):
        ranges = load_ranges(rp)
        targets = load_targets(rp)
        if ranges:
            print(f"Loaded {len(ranges)} range charts from {rp}")
            break
if not ranges:
    print("WARNING: No range file found -- skipping preflop deviation analysis")
if targets:
    print(f"Loaded {len(targets)} target frequency bands from ranges file")

# Sanity check ranges
if ranges:
    ranges, _sanity_report = sanity_check_ranges(ranges)
    if _sanity_report:
        print(f"\n[!] Chart sanity (B32): {len(_sanity_report)} chart(s) flagged")

# ---- Analyze ----
t0 = time.perf_counter()
from gem_analyzer import analyze_session
stats = analyze_session(hands, tournaments, n_files, errors, ranges, targets=targets)
t_analyze = time.perf_counter() - t0
print(f"\nAnalyzed in {t_analyze:.1f}s")
print(f"Date: {stats['volume']['date']}")
print(f"VPIP {stats['core']['vpip']}% | PFR {stats['core']['pfr']}% | ATS {stats['core']['ats']}%")
print(f"BB/100: {stats.get('csv_row', {}).get('BB_per_100', '?')}")
print(f"Punts: {stats.get('punts', {}).get('count', 0)} | Mistakes: {len(stats.get('mistakes', []))}")
print(f"Coolers: {stats.get('coolers', {}).get('count', 0)}")

# ---- Opponent Profiler ----
t0_prof = time.perf_counter()
try:
    from gem_opponent_profiler import (profile_opponents, tag_hands_with_archetypes,
                                       find_misplays_vs_archetype)
    _pname = 'Knockman'  # default hero name
    _opp_profiles = profile_opponents(hands, hero_name=_pname)
    tag_hands_with_archetypes(hands, _opp_profiles)
    _misplays = find_misplays_vs_archetype(hands, _opp_profiles)
    # Store on stats for renderer
    stats['opponent_profiles'] = {k: {kk: (sorted(vv) if isinstance(vv, set) else vv)
                                      for kk, vv in v.items()
                                      if kk != 'example_hand_ids'}
                                  for k, v in _opp_profiles.items()
                                  if v.get('archetype') != 'UNKNOWN'}
    stats['archetype_misplays'] = _misplays
    # Villain Intel (detectors)
    from gem_villain_intel import build_villain_intel, villain_key_for_hand
    _villain_intel = build_villain_intel(hands, _pname, _opp_profiles)
    stats['villain_intel'] = _villain_intel
    _alias_map = _villain_intel.get('villain_aliases', {})
    # Tag hands with villain identity
    _atoms_by_hand = _villain_intel.get('atoms_by_hand', {})
    _exploits_by_hand = _villain_intel.get('exploits_by_hand', {})
    for h in hands:
        _pvk = villain_key_for_hand(h)
        h['primary_villain_key'] = _pvk
        h['villain_evidence_atoms'] = _atoms_by_hand.get(h.get('id', ''), [])
        h['villain_badges'] = h['villain_evidence_atoms']
        h['exploit_opportunities'] = _exploits_by_hand.get(h.get('id', ''), [])
        if _pvk and _pvk in _alias_map:
            _va = _alias_map[_pvk]
            h['villain_identity'] = {
                'code': _va.get('v_number', ''),
                'alias': _va.get('alias', ''),
                'archetype': _va.get('archetype_label', _va.get('archetype', '')),
                'confidence': ('very_low' if _va.get('n_hands', 0) < 5 else
                               'medium_low' if _va.get('n_hands', 0) < 10 else
                               'medium' if _va.get('n_hands', 0) < 20 else
                               'medium_high' if _va.get('n_hands', 0) < 50 else 'high'),
                'n_hands': _va.get('n_hands', 0),
                'villain_key': _pvk,
            }
    t_prof = time.perf_counter() - t0_prof
    print(f"\nOpponent profiling: {len(_opp_profiles)} villains, {len(stats['opponent_profiles'])} classified, "
          f"{len(_misplays)} misplays ({t_prof:.1f}s)")
    # v8.8.3: profiler QA block
    _hero_names = set(h.get('hero', '') for h in hands if h.get('hero'))
    _pos_keyed = sum(1 for k in _opp_profiles if '|' not in k)
    _hero_profiles = sum(1 for k, v in _opp_profiles.items()
                         if any(hn in k for hn in _hero_names))
    print(f"  Profiler QA: {len(_opp_profiles)} profiles, "
          f"position-keyed={_pos_keyed} (expect 0), "
          f"hero-profiles={_hero_profiles} (expect 0)")
    _vpips = [v.get('vpip', 0) for v in _opp_profiles.values() if v.get('n_hands', 0) >= 5]
    _pfrs = [v.get('pfr', 0) for v in _opp_profiles.values() if v.get('n_hands', 0) >= 5]
    if _vpips:
        print(f"  VPIP range: {min(_vpips):.0f}%-{max(_vpips):.0f}% "
              f"(mean {sum(_vpips)/len(_vpips):.0f}%)")
    if _pfrs:
        print(f"  PFR range: {min(_pfrs):.0f}%-{max(_pfrs):.0f}% "
              f"(mean {sum(_pfrs)/len(_pfrs):.0f}%)")
    _eq_count = sum(1 for v, p in zip(_vpips, _pfrs) if abs(v - p) < 0.5)
    _pfr_gt = sum(1 for v, p in zip(_vpips, _pfrs) if p > v + 0.5)
    if _eq_count:
        print(f"  VPIP==PFR: {_eq_count}")
    if _pfr_gt:
        print(f"  *** WARNING: PFR>VPIP for {_pfr_gt} villains (expect 0) ***")
except Exception as e:
    print(f"\nOpponent profiling skipped: {type(e).__name__}: {e}")
    stats['opponent_profiles'] = {}
    stats['archetype_misplays'] = []

# ---- Generate report data ----
t0 = time.perf_counter()
from gem_analyzer import generate_report_data
import gem_report_data as _grd
_grd._ANALYST_FILE_OVERRIDE = None  # No analyst file
report_data = generate_report_data(stats, hands, SESSION_DIR, session_history_path=None)
t_rd = time.perf_counter() - t0
print(f"\nReport data generated in {t_rd:.1f}s")
print(f"Avg buy-in: ${report_data.get('avg_buyin', '?')} ({report_data.get('total_invested', '?')} total)")
print(f"Hero classification: {report_data.get('hero_classification', {}).get('emoji', '')} {report_data.get('hero_classification', {}).get('label', '?')}")

# ---- Schema validation ----
from gem_analyzer import validate_pipeline_outputs
schema_ok, schema_issues = validate_pipeline_outputs(stats, report_data, strict=False)
if schema_ok:
    print("\n[OK] ALL SCHEMA CHECKS PASSED")
else:
    print(f"\n[!] {len(schema_issues)} SCHEMA ISSUE(S):")
    for iss in schema_issues:
        print(f"  - {iss}")

# ---- Render HTML ----
t0 = time.perf_counter()
from gem_report_draft.draft import render_html
html_str = render_html(stats, report_data, hands)
t_render = time.perf_counter() - t0

date_compact = stats['volume']['date_range']
html_path = os.path.join(OUT_DIR, f'Pokerbot_Report_{date_compact}.html')
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html_str)

print(f"\nReport rendered in {t_render:.1f}s")
print(f"HTML: {html_path} ({os.path.getsize(html_path) // 1024}KB)")

# ---- Save stats JSON (for reference) ----
stats_path = os.path.join(OUT_DIR, f'gem_stats_{date_compact}.json')
with open(stats_path, 'w', encoding='utf-8') as f:
    json.dump(stats, f, indent=2, default=str, ensure_ascii=False)
print(f"Stats: {stats_path} ({os.path.getsize(stats_path) // 1024}KB)")

t_total = time.perf_counter() - (t0 - t_render)  # approximate
print(f"\n{'='*60}")
print(f"DONE -- open {html_path} in Chrome to verify.")
