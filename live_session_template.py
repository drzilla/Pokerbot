"""
Template: Live session → GG hand history conversion.

Usage:
    1. Copy this file: cp live_session_template.py live_session_<YYYYMMDD>.py
    2. Edit tournament constants and HANDS list.
    3. Run: python3 live_session_<YYYYMMDD>.py
    4. Output goes to /home/claude/Claude_GEM_2_GTOWizard_<DATE>_V1.txt
    5. Ship to /mnt/user-data/outputs/ and present_files.

See Live_Session_Guide.md for DSL reference and lessons learned.
"""
from live_to_gg import build_hand

# ============================================================
# Tournament constants — edit per session
# ============================================================
# Use unique 9-digit IDs for each tournament so GTO Wizard groups correctly.
TOURNEY_A_TID = '900000001'
TOURNEY_A_BUY = '$1 Live <Tournament Name>'

# Add more if multiple tournaments in this session:
# TOURNEY_B_TID = '900000002'
# TOURNEY_B_BUY = '$1 Live <Other Name>'

OUTPUT_FILENAME = 'Claude_GEM_2_GTOWizard_YYYYMMDD_V1.txt'

# ============================================================
# Hands — one spec dict per hand
# ============================================================
HANDS = []
def H(spec): HANDS.append(spec)

# ---------------------- EXAMPLE 1: BvB after folds-to-Hero ----------------------
# Source note: "Folds to me in the SB i limp K9o, BB raises to 1.5k, I call.
#              Flop KJ9, I check, he bets 400, I CR to 2k, he calls.
#              Turn T, I check, he bet 8k, I fold."
H({
    'hand_id':'LV0000000001','tourney_id':TOURNEY_A_TID,'buyin':TOURNEY_A_BUY,
    'level':5,'sb':200,'bb':400,'ante':0,
    'dt':'2026/01/01 12:00:00','table':'T1',
    'n':9,'btn':'BU','day_id':'01a',
    'hero':('SB',41000,'Kc 9d'),
    'villain_default_chips':30000,
    'villains':{'BB':42000},
    'actions':[
        'FOLDS_TO_HERO SB',
        'SB: limp','BB: raise 1500','SB: call',
        'F Kh Js 9c',
        'SB: check','BB: bet 400','SB: raise 2000','BB: call',
        'T Td',
        'SB: check','BB: bet 8000','SB: fold',
    ],
})

# ---------------------- EXAMPLE 2: Multiway with showdown ----------------------
# Source note: "Open 1.2k MP with A8s, BU SB BB call. Flop A82r, all check, MP bets 1.5k,
#              all call. Turn 9r, MP bets 4k, BU calls, others fold. River 7,
#              MP bets 9k, BU calls. MP wins with two pair."
# Demonstrates: explicit pf actions, multiway flop, showdown WIN tag.
H({
    'hand_id':'LV0000000002','tourney_id':TOURNEY_A_TID,'buyin':TOURNEY_A_BUY,
    'level':6,'sb':300,'bb':600,'ante':100,
    'dt':'2026/01/01 12:30:00','table':'T1',
    'n':9,'btn':'BU','day_id':'01b',
    'hero':('MP',45000,'As 8s'),
    'villain_default_chips':35000,
    'actions':[
        'UTG: fold','UTG1: fold',
        'MP: raise 1200','LJ: fold','HJ: fold','CO: fold',
        'BU: call','SB: call','BB: call',
        'F Ah 8c 2d','SB: check','BB: check','MP: bet 1500',
        'BU: call','SB: call','BB: call',
        'T 9d','SB: check','BB: check','MP: bet 4000',
        'BU: call','SB: fold','BB: fold',
        'R 7c','MP: bet 9000','BU: call',
        'SHOW MP As 8s two-pair-Aces-and-Eights',
        'SHOW BU Kh Qh high-card',
        'WIN MP',
    ],
})

# ---------------------- EXAMPLE 3: Preflop all-in cooler (skip-by-default) ----------------------
# Most preflop-only hands should be SKIPPED unless Ron asks for completeness.
# Pure jam-fold or jam-call-cooler hands have no postflop GTO content.
# Include only if the source note says "include all" or if it's analytically interesting.

# ---------------------- (Add more hand specs here) ----------------------
# H({...})
# H({...})

# ============================================================
# Render
# ============================================================
if __name__ == '__main__':
    import os, traceback
    out, failed = [], []
    for spec in HANDS:
        try:
            out.append(build_hand(spec))
        except Exception as e:
            failed.append((spec.get('hand_id','?'), str(e), traceback.format_exc()))
    out_path = f'/home/claude/{OUTPUT_FILENAME}'
    with open(out_path, 'w') as f:
        f.write(''.join(out))
    print(f"Wrote {out_path}")
    print(f"Successful: {len(out)}, Failed: {len(failed)}")
    for fid, err, tb in failed:
        print(f"\n  {fid}: {err}\n{tb}")
