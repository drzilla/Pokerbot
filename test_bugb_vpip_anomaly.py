"""Quick check: find profiles where VPIP% > 100 — indicates double-counting."""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

SESSION_DIR = r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_20260527'
from gem_parser import parse_session
from gem_opponent_profiler import profile_opponents

hands, tournaments, n_files, errors = parse_session(SESSION_DIR)
profiles = profile_opponents(hands, hero_name='Hero')

print("Profiles with VPIP > 100%:")
for k, v in sorted(profiles.items(), key=lambda kv: -kv[1].get('vpip',0)/max(kv[1]['hands_seen'],1)):
    n = v['hands_seen']
    vpip = v['vpip']
    pfr = v['pfr']
    if n > 0 and vpip/n > 1.0:
        vpip_pct = vpip/n*100
        pfr_pct = pfr/n*100
        print(f"  {k}: hands={n} vpip={vpip} pfr={pfr} vpip%={vpip_pct:.1f} pfr%={pfr_pct:.1f}")
