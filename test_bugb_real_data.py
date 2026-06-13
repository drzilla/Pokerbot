#!/usr/bin/env python3
"""BUG-B Test D — real-data QA summary.

Parses actual HH, runs profiler, prints full QA summary for acceptance.
"""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

SESSION_DIR = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\ron\AppData\Local\Temp\gem_session_20260528'

print(f"BUG-B Real-Data QA")
print(f"Session dir: {SESSION_DIR}")
print("=" * 60)

# ---- Parse ----
from gem_parser import parse_session
hands, tournaments, n_files, errors = parse_session(SESSION_DIR)
print(f"Parsed: {len(hands)} hands, {len(tournaments)} tournaments")
if not hands:
    print("ERROR: No hands parsed!")
    sys.exit(1)

# ---- Run profiler ----
from gem_opponent_profiler import profile_opponents, tag_hands_with_archetypes, find_misplays_vs_archetype

profiles = profile_opponents(hands, hero_name='Hero')

# ---- Test A: Identity correctness ----
print("\n" + "=" * 60)
print("TEST A: Identity Correctness")
print("=" * 60)

pos_labels = {'BTN', 'SB', 'BB', 'CO', 'HJ', 'MP', 'UTG', 'UTG+1', 'LJ', 'UNK', '?'}
bad_keys = [k for k in profiles if k.split('|', 1)[-1] in pos_labels]
hero_keys = [k for k in profiles if '|Hero' in k]

print(f"  Total profiles: {len(profiles)}")
print(f"  Position-keyed profiles (BAD): {len(bad_keys)}")
if bad_keys:
    print(f"    Examples: {bad_keys[:5]}")
print(f"  Hero profiles (BAD): {len(hero_keys)}")
if hero_keys:
    print(f"    Examples: {hero_keys[:5]}")

# Check cross-position merging: same player in multiple positions should be one key
from collections import Counter
player_names = [k.split('|', 1)[-1] for k in profiles]
name_counts = Counter(player_names)
dupes = {n: c for n, c in name_counts.items() if c > 1}
# Dupes are ok if they're from different tournaments
print(f"  Players appearing in multiple tournaments: {len(dupes)}")

identity_pass = len(bad_keys) == 0 and len(hero_keys) == 0
print(f"\n  Identity result: {'[PASS]' if identity_pass else '[FAIL]'}")

# ---- Test B: Stat correctness ----
print("\n" + "=" * 60)
print("TEST B: Stat Correctness")
print("=" * 60)

vpip_eq_pfr = 0
vpip_gt_pfr = 0
pfr_gt_vpip = 0
total_with_15 = 0

for k, v in profiles.items():
    n = v.get('hands_seen', 0)
    if n < 15:
        continue
    total_with_15 += 1
    vpip = v.get('vpip', 0)
    pfr = v.get('pfr', 0)
    if vpip == pfr:
        vpip_eq_pfr += 1
    elif vpip > pfr:
        vpip_gt_pfr += 1
    else:
        pfr_gt_vpip += 1

print(f"  Profiles with 15+ hands: {total_with_15}")
print(f"  VPIP == PFR: {vpip_eq_pfr}")
print(f"  VPIP > PFR:  {vpip_gt_pfr}")
print(f"  PFR > VPIP:  {pfr_gt_vpip} (should be 0 or near-0)")

# Including all profiles
all_eq = sum(1 for v in profiles.values() if v['vpip'] == v['pfr'])
all_gt = sum(1 for v in profiles.values() if v['vpip'] > v['pfr'])
print(f"\n  All profiles ({len(profiles)} total):")
print(f"    VPIP == PFR: {all_eq}")
print(f"    VPIP > PFR:  {all_gt}")
print(f"    PFR > VPIP:  {sum(1 for v in profiles.values() if v['pfr'] > v['vpip'])}")

# Key check: is VPIP==PFR for ALL villains? (the original bug)
all_eq_flag = all(v['vpip'] == v['pfr'] for v in profiles.values())
print(f"\n  VPIP==PFR for ALL villains: {all_eq_flag}")
stat_pass = not all_eq_flag and pfr_gt_vpip == 0
print(f"  Stat result: {'[PASS]' if stat_pass else '[FAIL]'}")

# ---- Test D: QA Summary ----
print("\n" + "=" * 60)
print("TEST D: QA Summary")
print("=" * 60)

print(f"  Number of opponent profiles: {len(profiles)}")
print(f"  Number of unique villain keys: {len(set(profiles.keys()))}")

# Top 10 by hands
top = sorted(profiles.items(), key=lambda kv: -kv[1]['hands_seen'])[:10]
print(f"\n  Top 10 profiles by hands:")
print(f"  {'Key':<40} {'Hands':>6} {'Positions':<15} {'VPIP':>6} {'PFR':>6} {'Limp':>6} {'AF':>6} {'Arch':<20}")
print(f"  {'-'*40} {'-'*6} {'-'*15} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*20}")
for k, v in top:
    n = v['hands_seen']
    pos_list = v.get('positions_seen', set())
    if isinstance(pos_list, list):
        pos = ','.join(sorted(pos_list))
    else:
        pos = ','.join(sorted(pos_list))
    vpip_pct = (v['vpip'] / n * 100) if n else 0
    pfr_pct = (v['pfr'] / n * 100) if n else 0
    limp_pct = (v['limp'] / n * 100) if n else 0
    # AF = (bets+raises) / (bets+raises+calls+checks) if denom > 0
    agg = v.get('postflop_bets', 0) + v.get('postflop_raises', 0)
    passive = v.get('postflop_calls', 0) + v.get('postflop_checks', 0)
    af = (agg / passive) if passive > 0 else 0
    arch = v.get('archetype', '?')
    print(f"  {k:<40} {n:>6} {pos:<15} {vpip_pct:>5.1f}% {pfr_pct:>5.1f}% {limp_pct:>5.1f}% {af:>5.2f} {arch:<20}")

# VPIP/PFR distribution summary (all profiles)
print(f"\n  VPIP/PFR distribution (all {len(profiles)} profiles):")
vpip_pcts = []
pfr_pcts = []
for v in profiles.values():
    n = v['hands_seen']
    if n > 0:
        vpip_pcts.append(v['vpip'] / n * 100)
        pfr_pcts.append(v['pfr'] / n * 100)

if vpip_pcts:
    vpip_pcts.sort()
    pfr_pcts.sort()
    print(f"    VPIP: min={vpip_pcts[0]:.1f}% median={vpip_pcts[len(vpip_pcts)//2]:.1f}% max={vpip_pcts[-1]:.1f}% mean={sum(vpip_pcts)/len(vpip_pcts):.1f}%")
    print(f"    PFR:  min={pfr_pcts[0]:.1f}% median={pfr_pcts[len(pfr_pcts)//2]:.1f}% max={pfr_pcts[-1]:.1f}% mean={sum(pfr_pcts)/len(pfr_pcts):.1f}%")

# Archetype distribution
archetypes = Counter(v.get('archetype', '?') for v in profiles.values())
print(f"\n  Archetype distribution:")
for arch, cnt in archetypes.most_common():
    print(f"    {arch:<25} {cnt:>4}")

# ---- Test C: Regression — tag and misplays ----
print("\n" + "=" * 60)
print("TEST C: Regression (tag + misplays)")
print("=" * 60)

try:
    tag_hands_with_archetypes(hands, profiles)
    tagged = sum(1 for h in hands if h.get('primary_villain_hash'))
    print(f"  Hands tagged with archetypes: {tagged} / {len(hands)}")

    # Check tagged keys are player-based, not position-based
    bad_tags = 0
    for h in hands:
        pvh = h.get('primary_villain_hash', '')
        if pvh and pvh.split('|', 1)[-1] in pos_labels:
            bad_tags += 1
    print(f"  Position-keyed tags (BAD): {bad_tags}")

    misplays = find_misplays_vs_archetype(hands, profiles)
    print(f"  Misplays found: {len(misplays)}")

    regression_pass = bad_tags == 0
    print(f"\n  Regression result: {'[PASS]' if regression_pass else '[FAIL]'}")
except Exception as e:
    print(f"  CRASH: {e}")
    import traceback
    traceback.print_exc()
    regression_pass = False

# ---- Overall ----
print("\n" + "=" * 60)
print("OVERALL RESULTS")
print("=" * 60)
all_pass = identity_pass and stat_pass and regression_pass
print(f"  Test A (Identity):   {'[PASS]' if identity_pass else '[FAIL]'}")
print(f"  Test B (Stats):      {'[PASS]' if stat_pass else '[FAIL]'}")
print(f"  Test C (Regression): {'[PASS]' if regression_pass else '[FAIL]'}")
print(f"\n  Overall: {'[PASS] All acceptance criteria met' if all_pass else '[FAIL] Fix needed'}")
