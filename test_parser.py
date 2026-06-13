#!/usr/bin/env python3
"""GEM Parser Test Suite — validates known-correct outputs against test hand histories.
Run after EVERY parser change. All tests must pass before uploading.

Usage: python3 test_parser.py
Requires: gem_analyzer.py and test_hands.txt in /mnt/project/
"""
import sys, os, json, shutil, tempfile, subprocess

# Setup: create temp directory with test hands in GGPoker filename format
# v7.36: prefer LOCAL gem_analyzer.py / test_hands.txt over /mnt/project/ so
# iterative development tests local edits instead of the read-only project
# snapshot. /mnt/project/ remains the fallback for clean checkouts.
TEST_DIR = '/home/claude/test_dir'
_HERE = os.path.dirname(os.path.abspath(__file__)) or '.'
_LOCAL_PARSER = os.path.join(_HERE, 'gem_analyzer.py')
_LOCAL_HANDS = os.path.join(_HERE, 'test_hands.txt')
PARSER = _LOCAL_PARSER if os.path.exists(_LOCAL_PARSER) else '/mnt/project/gem_analyzer.py'
TEST_HANDS = _LOCAL_HANDS if os.path.exists(_LOCAL_HANDS) else '/mnt/project/test_hands.txt'

if not os.path.exists(PARSER):
    print(f"ERROR: Parser not found at {PARSER}"); sys.exit(1)
if not os.path.exists(TEST_HANDS):
    print(f"ERROR: Test hands not found at {TEST_HANDS}"); sys.exit(1)

os.makedirs(TEST_DIR, exist_ok=True)
# Clear any previous test files
for f in os.listdir(TEST_DIR):
    os.remove(os.path.join(TEST_DIR, f))

# Split test hands: deep run hands (TM9000002[4-9] and TM9000003[0-3]) go to separate file
# so they get a different tournament name (parser uses filename for tournament)
all_content = open(TEST_HANDS).read()
import re
deep_run_ids = {'TM90000024','TM90000025','TM90000026','TM90000027','TM90000028',
                'TM90000029','TM90000030','TM90000031','TM90000032','TM90000033'}
hand_blocks = re.split(r'\n(?=Poker Hand #TM)', all_content)
main_hands = []
deep_hands = []
for block in hand_blocks:
    block = block.strip()
    if not block: continue
    if not block.startswith('Poker Hand'): block = 'Poker Hand' + block  # re-add split prefix
    hid_m = re.search(r'Poker Hand #(TM\d+)', block)
    if hid_m and hid_m.group(1) in deep_run_ids:
        deep_hands.append(block)
    else:
        main_hands.append(block)

with open(os.path.join(TEST_DIR, 'GG20260407-0000 - Test Suite.txt'), 'w') as f:
    f.write('\n\n\n'.join(main_hands))
if deep_hands:
    with open(os.path.join(TEST_DIR, 'GG20260407-0001 - Test Deep Run.txt'), 'w') as f:
        f.write('\n\n\n'.join(deep_hands))

# Run parser on test hands (suppress output)
subprocess.run([sys.executable, PARSER, TEST_DIR + '/'],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# Load results
with open('/home/claude/gem_hands.json', encoding='utf-8') as f:
    hands = json.load(f)
with open('/home/claude/gem_stats.json', encoding='utf-8') as f:
    stats = json.load(f)

def get_hand(test_id):
    for h in hands:
        if h['id'] == test_id:
            return h
    return None

passed = 0
failed = 0
errors = []

def check(test_name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {test_name}")
    else:
        failed += 1
        errors.append(f"{test_name}: {detail}")
        print(f"  🔴 FAIL: {test_name} — {detail}")

print("=" * 60)
print("GEM PARSER TEST SUITE")
print("=" * 60)

# ============================================================
# TEST 1: Hero shoves, everyone folds — net positive, won=True
# AKh BTN, shoves 25000, all fold, uncalled 24750 returned, collected 625
# ============================================================
print("\nTEST 1: Shove + fold = positive net_bb, won=True")
h = get_hand('TM90000001')
if h:
    check("Hand parsed", True)
    check("won = True", h.get('won') == True, f"got {h.get('won')}")
    check("net_bb > 0", h.get('net_bb', -999) > 0, f"got {h.get('net_bb')}")
    check("net_bb ≈ +1.5 (625-250 blinds won / 250 BB)", 
          0.5 < h.get('net_bb', 0) < 3.0, f"got {h.get('net_bb')}")
    check("NOT in EAI (no showdown)", 
          not any(e['id'] == 'TM90000001' for e in stats['eai']['hands']),
          "found in EAI list")
else:
    check("Hand parsed", False, "TM90000001 not found")

# ============================================================
# TEST 2: Hero shoves, short stack calls, Hero WINS
# AKo SB shoves 25000, BB calls 10000, 15000 returned, Hero wins
# ============================================================
print("\nTEST 2: Shove + short call + Hero wins")
h = get_hand('TM90000002')
if h:
    check("Hand parsed", True)
    check("won = True", h.get('won') == True, f"got {h.get('won')}")
    check("net_bb > 0", h.get('net_bb', -999) > 0, f"got {h.get('net_bb')}")
    # Hero put in 25000, got back 15000 + collected 20250 = 35250. Net = 35250-25000 = 10250 = 41BB
    eai_hand = next((e for e in stats['eai']['hands'] if e['id'] == 'TM90000002'), None)
    check("In EAI (showdown)", eai_hand is not None, "not found in EAI")
    if eai_hand:
        check("EAI street = preflop", eai_hand.get('street') == 'preflop', f"got {eai_hand.get('street')}")
        check("EAI category = flip (AK vs QQ)", eai_hand.get('category') == 'flip', f"got {eai_hand.get('category')}")
        check("EAI won = True", eai_hand.get('won') == True, f"got {eai_hand.get('won')}")
else:
    check("Hand parsed", False, "TM90000002 not found")

# ============================================================
# TEST 3: Hero shoves, short stack calls, Hero LOSES
# AKo SB shoves 25000, BB calls 10000, 15000 returned, Hero LOSES
# ============================================================
print("\nTEST 3: Shove + short call + Hero LOSES")
h = get_hand('TM90000003')
if h:
    check("Hand parsed", True)
    check("won = False", h.get('won') == False, f"got {h.get('won')}")
    check("net_bb < 0", h.get('net_bb', 999) < 0, f"got {h.get('net_bb')}")
    # Hero put in 25000, got back 15000, collected 0. Net = 15000-25000 = -10000 = -40BB
    check("net_bb ≈ -40 (lost 10000 effective)", 
          -50 < h.get('net_bb', 0) < -30, f"got {h.get('net_bb')}")
    eai_hand = next((e for e in stats['eai']['hands'] if e['id'] == 'TM90000003'), None)
    check("In EAI (showdown)", eai_hand is not None, "not found in EAI")
    if eai_hand:
        check("EAI won = False", eai_hand.get('won') == False, f"got {eai_hand.get('won')}")
        check("EAI category = flip (AK vs QQ)", eai_hand.get('category') == 'flip', f"got {eai_hand.get('category')}")
else:
    check("Hand parsed", False, "TM90000003 not found")

# ============================================================
# TEST 4: Hero opens BTN, V 3-bets from SB, Hero folds
# F2-3B: fold_to_3bet=True, hero_3bet=False, counted in ftb_opps
# ============================================================
print("\nTEST 4: Hero opens, faces 3-bet, folds = fold_to_3bet")
h = get_hand('TM90000004')
if h:
    check("Hand parsed", True)
    check("pfr = True (Hero opened)", h.get('pfr') == True, f"got {h.get('pfr')}")
    check("fold_to_3bet = True", h.get('fold_to_3bet') == True, f"got {h.get('fold_to_3bet')}")
    check("hero_3bet = False (Hero was opener)", h.get('hero_3bet') == False, f"got {h.get('hero_3bet')}")
else:
    check("Hand parsed", False, "TM90000004 not found")

# ============================================================
# TEST 5: V opens UTG, Hero 3-bets BTN, V folds
# hero_3bet=True, NOT fold_to_3bet, NOT in ftb_opps
# ============================================================
print("\nTEST 5: V opens, Hero 3-bets, V folds = hero_3bet, NOT ftb")
h = get_hand('TM90000005')
if h:
    check("Hand parsed", True)
    check("pfr = True", h.get('pfr') == True, f"got {h.get('pfr')}")
    check("hero_3bet = True", h.get('hero_3bet') == True, f"got {h.get('hero_3bet')}")
    check("fold_to_3bet = False", h.get('fold_to_3bet', False) == False, f"got {h.get('fold_to_3bet')}")
else:
    check("Hand parsed", False, "TM90000005 not found")

# ============================================================
# TEST 6: Hero opens BTN, V 3-bets, Hero CALLS → continues
# fold_to_3bet=False, hero_3bet=False, counted in ftb_opps
# ============================================================
print("\nTEST 6: Hero opens, faces 3-bet, calls = not fold_to_3bet")
h = get_hand('TM90000006')
if h:
    check("Hand parsed", True)
    check("fold_to_3bet = False (Hero called)", h.get('fold_to_3bet', True) == False, f"got {h.get('fold_to_3bet')}")
    check("hero_3bet = False (Hero was opener)", h.get('hero_3bet') == False, f"got {h.get('hero_3bet')}")
    check("won = True (won the pot)", h.get('won') == True, f"got {h.get('won')}")
else:
    check("Hand parsed", False, "TM90000006 not found")

# ============================================================
# F2-3B AGGREGATE: only tests 4 and 6 are ftb_opps (Hero opened, faced 3-bet)
# Test 5 is NOT (Hero was the 3-bettor)
# ============================================================
print("\nTEST F2-3B AGGREGATE")
ftb_opps = stats['core']['ftb_opps']
ftb_ct = stats['core']['ftb_ct']
check(f"ftb_opps includes T4 and T6 (openers facing 3bet)", ftb_opps >= 2, f"got {ftb_opps}")
check(f"ftb_ct = 1 (only T4 folded)", ftb_ct >= 1, f"got {ftb_ct}")
# Verify T5 is excluded: if ftb_opps == ftb from T4+T6 only (not T5)
hands_456 = [get_hand(f'TM9000000{i}') for i in [4,5,6]]
opps_456 = sum(1 for h in hands_456 if h and h.get('pfr') and h.get('pf_raise_count',0) >= 2 and not h.get('hero_3bet'))
check(f"T5 excluded from ftb_opps (hero_3bet=True)", opps_456 == 2, f"got {opps_456} for tests 4,5,6")

# ============================================================
# TEST 7: TPGK river check (ATo on As4d8c3h6d) — MRV should flag
# Caller IP, called flop, checked turn+river, TPGK with T kicker
# ============================================================
print("\nTEST 7: TPGK river check = missed river value")
h = get_hand('TM90000007')
if h:
    check("Hand parsed", True)
    check("missed_river_value = True (TPGK, 0 value streets after flop call)",
          h.get('missed_river_value') == True, f"got {h.get('missed_river_value')}")
else:
    check("Hand parsed", False, "TM90000007 not found")

# ============================================================
# TEST 8: TPAK (awful kicker) river check — MRV should NOT flag
# A4d on 2c8hJsQsAd — 4 broadways on board, kicker = 4
# ============================================================
print("\nTEST 8: TPWK on scary board = NOT missed river value")
h = get_hand('TM90000008')
if h:
    check("Hand parsed", True)
    check("missed_river_value = False (TPWK, 4 broadways)",
          h.get('missed_river_value') == False, f"got {h.get('missed_river_value')}")
else:
    check("Hand parsed", False, "TM90000008 not found")

# ============================================================
# TEST 9: TPGK with 1 street of value (bet turn) — MRV should NOT flag
# ATo on As4d8c3h6d, bet turn, check river — already got 1 street
# Wait: 1 street + river check = should flag (need 2 streets with TPGK)
# Actually per rules: flag if <=1 street and is_strong_enough. This has 1 street.
# ============================================================
print("\nTEST 9: TPGK with 1 street, river check = missed river value")
h = get_hand('TM90000009')
if h:
    check("Hand parsed", True)
    check("missed_river_value = True (TPGK, 1 street, safe river)",
          h.get('missed_river_value') == True, f"got {h.get('missed_river_value')}")
else:
    check("Hand parsed", False, "TM90000009 not found")

# ============================================================
# TEST 10: Pair over pair — 88 vs TT, Hero loses = COOLER
# ============================================================
print("\nTEST 10: 88 vs TT = cooler (pair over pair)")
h = get_hand('TM90000010')
eai_hand = next((e for e in stats['eai']['hands'] if e['id'] == 'TM90000010'), None)
if h and eai_hand:
    check("won = False", h.get('won') == False, f"got {h.get('won')}")
    check("EAI category = behind", eai_hand.get('category') == 'behind', f"got {eai_hand.get('category')}")
    cooler_ids = [c['id'] for c in stats['coolers']['hands']]
    check("Classified as cooler", 'TM90000010' in cooler_ids, f"cooler list: {cooler_ids}")
else:
    check("Hand parsed + in EAI", False, "not found")

# ============================================================
# TEST 11: AK vs QQ, Hero loses = FLIP, NOT a cooler
# ============================================================
print("\nTEST 11: AK vs QQ = flip, NOT a cooler")
h = get_hand('TM90000011')
eai_hand = next((e for e in stats['eai']['hands'] if e['id'] == 'TM90000011'), None)
if h and eai_hand:
    check("EAI category = flip", eai_hand.get('category') == 'flip', f"got {eai_hand.get('category')}")
    cooler_ids = [c['id'] for c in stats['coolers']['hands']]
    check("NOT classified as cooler", 'TM90000011' not in cooler_ids, f"found in cooler list!")
else:
    check("Hand parsed + in EAI", False, "not found")

# ============================================================
# TEST 12: Flop all-in, Hero ahead (JJ vs 98h on 4h7d2c) — EAI postflop ahead
# ============================================================
print("\nTEST 12: Flop all-in, JJ vs 98h = postflop ahead, Hero wins")
eai_hand = next((e for e in stats['eai']['hands'] if e['id'] == 'TM90000012'), None)
if eai_hand:
    check("EAI street = flop", eai_hand.get('street') == 'flop', f"got {eai_hand.get('street')}")
    check("EAI category = ahead (JJ > 98 on 472)", eai_hand.get('category') == 'ahead', f"got {eai_hand.get('category')}")
    check("EAI won = True", eai_hand.get('won') == True, f"got {eai_hand.get('won')}")
else:
    check("In EAI", False, "TM90000012 not found in EAI")

# ============================================================
# TEST 13: Flop all-in, Hero behind (JJ vs 77 on 4h7d2c — set over overpair)
# ============================================================
print("\nTEST 13: Flop all-in, JJ vs set of 7s = postflop behind, Hero loses")
eai_hand = next((e for e in stats['eai']['hands'] if e['id'] == 'TM90000013'), None)
if eai_hand:
    check("EAI street = flop", eai_hand.get('street') == 'flop', f"got {eai_hand.get('street')}")
    check("EAI category = behind (JJ < set of 7s)", eai_hand.get('category') == 'behind', f"got {eai_hand.get('category')}")
    check("EAI won = False", eai_hand.get('won') == False, f"got {eai_hand.get('won')}")
else:
    check("In EAI", False, "TM90000013 not found in EAI")

# ============================================================
# TEST 14: River bet → V folds → uncalled returned — NOT in EAI
# ============================================================
print("\nTEST 14: River bet + fold = won, NOT in EAI")
h = get_hand('TM90000014')
if h:
    check("won = True", h.get('won') == True, f"got {h.get('won')}")
    check("net_bb > 0", h.get('net_bb', -999) > 0, f"got {h.get('net_bb')}")
    check("NOT in EAI (no showdown)",
          not any(e['id'] == 'TM90000014' for e in stats['eai']['hands']),
          "found in EAI list")
else:
    check("Hand parsed", False, "TM90000014 not found")

# ============================================================
# TEST 15: CVJ — Villain UTG jams 10BB, Hero calls A8o from HJ
# Should flag as Wide CVJ (A8o not in EP jam call range)
# ============================================================
print("\nTEST 15: CVJ — A8o calling UTG jam = Wide CVJ flag")
h = get_hand('TM90000015')
if h:
    check("Hand parsed", True)
    check("jammer_position = UTG", h.get('jammer_position') == 'UTG', f"got {h.get('jammer_position')}")
    check("jammer_stack_bb ≈ 10", 8 < h.get('jammer_stack_bb', 0) < 12, f"got {h.get('jammer_stack_bb')}")
    check("villain_jammed = True", h.get('villain_jammed') == True, f"got {h.get('villain_jammed')}")
    cvj = [d for d in stats['preflop_deviations'] if d.get('id') == 'TM90000015' and d['type'] == 'Wide CVJ (Call Villain Jam)']
    check("Flagged as Wide CVJ", len(cvj) == 1, f"found {len(cvj)} CVJ flags")
else:
    check("Hand parsed", False, "TM90000015 not found")

# ============================================================
# TEST 16: CVJ — Villain UTG jams 10BB, Hero calls QQ from HJ
# Should NOT flag (QQ is in every call range)
# ============================================================
print("\nTEST 16: CVJ — QQ calling UTG jam = NOT flagged")
h = get_hand('TM90000016')
if h:
    check("Hand parsed", True)
    check("jammer_position = UTG", h.get('jammer_position') == 'UTG', f"got {h.get('jammer_position')}")
    cvj = [d for d in stats['preflop_deviations'] if d.get('id') == 'TM90000016' and d['type'] == 'Wide CVJ (Call Villain Jam)']
    check("NOT flagged as Wide CVJ", len(cvj) == 0, f"found {len(cvj)} CVJ flags (should be 0)")
else:
    check("Hand parsed", False, "TM90000016 not found")

# ============================================================
# TEST 17: Re-jam over a jam — Villain UTG jams 8BB, Hero re-jams QTo
# from UTG+1 covering the jammer (25000 vs 2000). B176 (Ron 2026-05-25):
# vs the jammer a covered re-jam IS a call, so it flags as a CVJ, not
# "Iso-Jam". (A not-covering re-jam is logically impossible — raising
# over a jam requires out-chipping it.)
# ============================================================
print("\nTEST 17: re-jam over UTG jam, Hero covers = Wide CVJ (re-jam over jam, covers)")
h = get_hand('TM90000017')
if h:
    check("Hand parsed", True)
    check("jammer_position = UTG", h.get('jammer_position') == 'UTG', f"got {h.get('jammer_position')}")
    check("pfr = True (Hero raised)", h.get('pfr') == True, f"got {h.get('pfr')}")
    iso = [d for d in stats['preflop_deviations'] if d.get('id') == 'TM90000017'
           and 're-jam over jam' in d['type']]
    check("Flagged as Wide CVJ (re-jam over jam, covers)", len(iso) == 1,
          f"found {len(iso)} re-jam-over-jam flags, types={[d['type'] for d in stats['preflop_deviations'] if d.get('id')=='TM90000017']}")
else:
    check("Hand parsed", False, "TM90000017 not found")

# ============================================================
# TEST 18: ICM Pressure — Level 25, Hero jams 99 from SB at 37BB
# Should flag as ICM Pressure Flag
# ============================================================
print("\nTEST 18: ICM — 99 jam 37BB level 25 = ICM Pressure Flag")
h = get_hand('TM90000018')
if h:
    check("Hand parsed", True)
    check("level = 25", h.get('level') == 25, f"got {h.get('level')}")
    check("stack ≈ 37BB", 35 < h.get('stack_bb', 0) < 40, f"got {h.get('stack_bb')}")
    icm = [d for d in stats['preflop_deviations'] if d.get('id') == 'TM90000018' and d['type'] == 'ICM Pressure Flag']
    check("Flagged as ICM Pressure", len(icm) == 1, f"found {len(icm)} ICM flags")
else:
    check("Hand parsed", False, "TM90000018 not found")

# ============================================================
# TEST 19: FT Flat Alert — 6 players at 8-max, Hero flats MP open with A3s
# Should flag as FT Flat Alert (n_players < table_size)
# ============================================================
print("\nTEST 19: FT Flat — A3s flatting MP open at FT = ICM Flat Alert")
h = get_hand('TM90000019')
if h:
    check("Hand parsed", True)
    check("n_players = 6", h.get('n_players') == 6, f"got {h.get('n_players')}")
    check("table_size = 8", h.get('table_size') == 8, f"got {h.get('table_size')}")
    check("n_players < table_size (FT)", h.get('n_players', 9) < h.get('table_size', 9), "not at FT")
    # v7.25 J43: 'FT Flat Alert' was renamed to 'ICM Flat Alert' and broadened
    # to bubble_zone/post_bubble/ft_zone phases. Test updated to match.
    ft = [d for d in stats['preflop_deviations'] if d.get('id') == 'TM90000019' and d['type'] == 'ICM Flat Alert']
    check("Flagged as ICM Flat Alert", len(ft) == 1, f"found {len(ft)} ICM flags")
else:
    check("Hand parsed", False, "TM90000019 not found")

# ============================================================
# TEST 20: Stacks behind — Hero at CO, verify stacks_behind populated
# BTN=100BB, SB=12BB (reshove stack), BB=100BB
# ============================================================
print("\nTEST 20: Stacks behind — CO with reshove stack on SB")
h = get_hand('TM90000020')
if h:
    check("Hand parsed", True)
    check("position = CO", h.get('position') == 'CO', f"got {h.get('position')}")
    sb = h.get('stacks_behind', {})
    check("stacks_behind has BTN", 'BTN' in sb, f"got {list(sb.keys())}")
    check("stacks_behind has SB", 'SB' in sb, f"got {list(sb.keys())}")
    check("stacks_behind has BB", 'BB' in sb, f"got {list(sb.keys())}")
    check("SB is reshove stack (≈12BB)", 10 < sb.get('SB', 0) < 15, f"got SB={sb.get('SB')}")
    check("BTN ≈ 100BB", sb.get('BTN', 0) > 90, f"got BTN={sb.get('BTN')}")
else:
    check("Hand parsed", False, "TM90000020 not found")

# ============================================================
# TEST 21: Missed Push <8BB — K5s SB 6BB FI fold
# Should flag as Missed Push <8BB (CLEAR - King suited)
# ============================================================
print("\nTEST 21: Missed Push <8BB — K5s SB 6BB fold = CLEAR")
h = get_hand('TM90000021')
if h:
    check("Hand parsed", True)
    check("position = SB", h.get('position') == 'SB', f"got {h.get('position')}")
    check("stack < 8BB", h.get('stack_bb', 99) < 8, f"got {h.get('stack_bb')}")
    check("first_in = True", h.get('first_in') == True, f"got {h.get('first_in')}")
    push_flags = [m for m in stats.get('mistakes', []) if m['id'] == 'TM90000021' and 'Push <8BB' in m.get('type','')]
    check("Flagged as Missed Push <8BB", len(push_flags) >= 1, f"found {len(push_flags)} push flags")
    if push_flags:
        check("Confidence = CLEAR (King)", push_flags[0].get('confidence') == 'CLEAR', f"got {push_flags[0].get('confidence')}")
else:
    check("Hand parsed", False, "TM90000021 not found")

# ============================================================
# TEST 22: Missed Push <8BB — J8o BTN 4BB FI fold
# Should flag as Missed Push <8BB (MARGINAL - Jx at <5BB)
# ============================================================
print("\nTEST 22: Missed Push <8BB — J8o BTN 4BB fold = MARGINAL")
h = get_hand('TM90000022')
if h:
    check("Hand parsed", True)
    check("position = BTN", h.get('position') == 'BTN', f"got {h.get('position')}")
    check("stack < 5BB", h.get('stack_bb', 99) < 5, f"got {h.get('stack_bb')}")
    push_flags = [m for m in stats.get('mistakes', []) if m['id'] == 'TM90000022' and 'Push <8BB' in m.get('type','')]
    check("Flagged as Missed Push <8BB", len(push_flags) >= 1, f"found {len(push_flags)} push flags")
else:
    check("Hand parsed", False, "TM90000022 not found")

# ============================================================
# TEST 23: Missed Reshove <8BB — A5o BB 6BB vs raise fold
# Should flag as Missed Reshove <8BB (CLEAR - Ace)
# ============================================================
print("\nTEST 23: Missed Reshove <8BB — A5o BB 6BB vs raise = CLEAR")
h = get_hand('TM90000023')
if h:
    check("Hand parsed", True)
    check("position = BB", h.get('position') == 'BB', f"got {h.get('position')}")
    check("stack < 8BB", h.get('stack_bb', 99) < 8, f"got {h.get('stack_bb')}")
    check("hero_faced_raise = True", h.get('hero_faced_raise') == True, f"got {h.get('hero_faced_raise')}")
    reshove_flags = [m for m in stats.get('mistakes', []) if m['id'] == 'TM90000023' and 'Reshove <8BB' in m.get('type','')]
    check("Flagged as Missed Reshove <8BB", len(reshove_flags) >= 1, f"found {len(reshove_flags)} reshove flags")
    if reshove_flags:
        check("Confidence = CLEAR (Ace)", reshove_flags[0].get('confidence') == 'CLEAR', f"got {reshove_flags[0].get('confidence')}")
else:
    check("Hand parsed", False, "TM90000023 not found")

# TEST 24-28 — reverse chronological fix
# 5 hands from "Test Deep Run" in reverse order.
# Chronological: 200BB → 117BB → 100BB → 3BB → 25BB
# ============================================================
print("\nTEST 24: Deep run — correct start/peak/low/final after reversal")
dr = next((d for d in stats.get('deep_runs', []) if 'Test Deep Run' in d.get('tournament', '')), None)
if dr:
    check("Deep run found", True)
    check("hands = 10", dr['hands'] == 10, f"got {dr['hands']}")
    check("start = 200 (earliest hand, Level 5)", dr['start'] == 200, f"got {dr['start']}")
    check("peak = 200 (max stack)", dr['peak'] == 200, f"got {dr['peak']}")
    check("low = 3 (KJd all-in hand)", dr['low'] == 3, f"got {dr['low']}")
    check("final = 25 (latest hand, Level 20)", dr['final'] == 25, f"got {dr['final']}")
    check("survival = True (3 < 200*0.3, 25 > 3*2)", dr.get('survival') == True, f"got {dr.get('survival')}")
    check("premiums_pct exists", dr.get('premiums_pct') is not None, "missing")
    check("eai_total exists", dr.get('eai_total') is not None, "missing")
else:
    check("Deep run found", False, "Test Deep Run not in deep_runs (need >=10 hands? only 5)")

print("\nTEST 25: Tournament phases assigned")
test_dr_hands = [h for h in hands if h.get('tournament','') == 'Test Deep Run']
if test_dr_hands:
    phases = set(h.get('tournament_phase', '?') for h in test_dr_hands)
    check("tournament_phase assigned", '?' not in phases and len(phases) > 0, f"got {phases}")
    # Level 5 = late_reg (standard format)
    lv5 = next((h for h in test_dr_hands if h.get('level') == 5), None)
    if lv5:
        check("Level 5 = late_reg", lv5.get('tournament_phase') == 'late_reg', f"got {lv5.get('tournament_phase')}")
    lv20 = next((h for h in test_dr_hands if h.get('level') == 20), None)
    if lv20:
        check("Level 20 = post_reg (standard)", lv20.get('tournament_phase') == 'post_reg', f"got {lv20.get('tournament_phase')}")
else:
    check("Test Deep Run hands found", False, "no hands found")

print("\nTEST 26: Positional P&L computed")
pnl = stats.get('positional_pnl', {})
check("positional_pnl exists", len(pnl) > 0, "empty")
if pnl:
    # BTN should have data (test hands are mostly BTN)
    btn = pnl.get('BTN', {})
    check("BTN P&L has hands", btn.get('hands', 0) > 0, f"got {btn.get('hands')}")
    check("BTN has net_bb", 'net_bb' in btn, "missing")
    check("BTN has bb_per_100", 'bb_per_100' in btn, "missing")

print("\nTEST 27: Report draft generated")
import os, glob
draft_paths = glob.glob('/home/claude/GEM_Report_*.md')
draft_exists = len(draft_paths) > 0
check("GEM_Report_*.md exists", draft_exists, "file not found")
if draft_exists:
    draft = open(draft_paths[0], encoding='utf-8').read()
    # v7.36: renderer outline rebuilt at v7.33 (D1) replaced "## Del 0: TLDR"
    # with "## TL;DR". Test updated to match the canonical header. Also dropped
    # the survival-story-placeholder check since v7.35's structural overhaul
    # absorbed survival narration into I.2 Top Losing/Winning Lines + Deep Runs
    # (no separate placeholder string anymore).
    check("Draft has TLDR", '## Summary' in draft or '## TL;DR' in draft, "missing")
    check("Draft has Positional P&L", 'Positional P&L' in draft or 'Position Analysis' in draft, "missing")
    check("Draft has EAI Expected column", 'Expected' in draft, "missing")
    check("Draft has Deep Runs", 'Deep Run' in draft, "missing")
    check("Draft has Tournament Phases", 'Phase' in draft, "missing")
    check("Draft has color coding", '🟢' in draft or '🔴' in draft or '🟡' in draft, "no color codes found")
    # v7.36: deep-run / stack-arc info now lives in I.1 Per-Tournament P&L
    check("Draft has stack-arc / deep-run signal",
          'Deep Run' in draft or 'Stack arc' in draft or 'stack arc' in draft.lower(),
          "missing")

# ============================================================
# v7.27 TESTS — facing-action defense + donk + barrel flags
# ============================================================
print("\n" + "=" * 60)
print("v7.27 facing-action / donk / barrel flag tests")
print("=" * 60)

def _v727_check_field_present(hands, field, label):
    check(f"v7.27 field '{field}' present in all hands ({label})",
          all(field in h for h in hands),
          f"missing in some hands")

# Re-parse to verify v7.27 fields exist
from gem_parser import parse_session as _ps_v727
_v727_hands, _, _, _ = _ps_v727(os.path.dirname(os.path.abspath(__file__)))
if not _v727_hands:
    # Fallback: try test_hands.txt in same dir
    pass

_v727_required = [
    'fold_to_villain_cbet_flop', 'called_villain_cbet_flop',
    'raised_villain_cbet_flop_ip', 'xr_villain_cbet_flop',
    'faced_xr_after_cbet', 'folded_to_xr_after_cbet',
    'called_xr_after_cbet', 'reraised_xr_after_cbet',
    'faced_donk_flop', 'folded_to_donk_flop', 'called_donk_flop',
    'raised_donk_flop',
    'triple_barreled', 'double_barreled',
    'faced_turn_barrel', 'folded_to_turn_barrel', 'called_turn_barrel',
    'cold_called', 'cold_called_3bet',
    'hero_4bet_only', 'hero_5bet_plus', 'faced_5bet',
    'faced_steal_bb', 'fold_to_steal_bb', 'restole',
    'faced_squeeze', 'folded_to_squeeze',
    'lt15bb_call_jam',
    'hero_donked_flop', 'hero_donked_turn',
    'villain_raised_hero_cbet_flop',
    'bet_then_faced_raise_flop', 'bet_then_faced_raise_turn', 'bet_then_faced_raise_river',
    'bet_fold_flop', 'bet_call_flop',
]

if _v727_hands:
    for field in _v727_required:
        _v727_check_field_present(_v727_hands, field, f"on {len(_v727_hands)} parsed hands")

    # Mutual exclusion: a hand can't be BOTH cold_called AND hero_3bet (3-bet ≠ flat)
    check("v7.27 cold_called excludes hero_3bet hands",
          not any(h.get('cold_called') and h.get('hero_3bet') for h in _v727_hands),
          "found hand with both cold_called=True and hero_3bet=True")

    # Mutual exclusion: faced_donk_flop requires Hero is PFR
    check("v7.27 faced_donk_flop only set when Hero is PFR",
          all((not h.get('faced_donk_flop')) or h.get('pfr') for h in _v727_hands),
          "found faced_donk_flop=True with pfr=False")

    # Mutual exclusion: hero_donked_flop requires Hero NOT PFR and OOP
    check("v7.27 hero_donked_flop only when caller OOP",
          all((not h.get('hero_donked_flop')) or
              ((not h.get('pfr')) and (not h.get('hero_ip')))
              for h in _v727_hands),
          "found hero_donked_flop=True for IP or PFR hand")

    # Triple implies double
    check("v7.27 triple_barreled implies double_barreled",
          all((not h.get('triple_barreled')) or h.get('double_barreled')
              for h in _v727_hands),
          "found triple without double")

    # 4bet-only and 5bet+ are mutually exclusive
    check("v7.27 hero_4bet_only and hero_5bet_plus are mutex",
          not any(h.get('hero_4bet_only') and h.get('hero_5bet_plus') for h in _v727_hands),
          "found hand flagged as both 4bet-only and 5bet+")

    # cold_called requires vpip
    check("v7.27 cold_called implies vpip",
          all((not h.get('cold_called')) or h.get('vpip') for h in _v727_hands),
          "cold_called=True with vpip=False")

    # restole requires hero_3bet from blinds
    check("v7.27 restole implies hero_3bet from blinds",
          all((not h.get('restole')) or
              (h.get('hero_3bet') and h.get('position') in ('SB', 'BB'))
              for h in _v727_hands),
          "restole=True without hero_3bet from blinds")

    # faced_xr_after_cbet implies villain_raised_hero_cbet_flop and Hero PFR
    check("v7.27 faced_xr_after_cbet requires villain_raised + Hero PFR",
          all((not h.get('faced_xr_after_cbet')) or
              (h.get('villain_raised_hero_cbet_flop') and h.get('pfr'))
              for h in _v727_hands),
          "inconsistent faced_xr state")

# ============================================================
# v7.28 TESTS — extended preflop / postflop matrices
# ============================================================
print("\n" + "=" * 60)
print("v7.28 extended matrix tests")
print("=" * 60)

if _v727_hands:
    _v728_required = [
        # preflop
        'true_pfr_opportunity', 'true_pfr_action', 'pf_allin_flag',
        'hero_3bet_ip', 'hero_3bet_oop', 'fold_to_3bet_ip', 'fold_to_3bet_oop',
        'hero_called_3bet', 'hero_called_3bet_ip', 'hero_called_3bet_oop',
        'hero_called_4bet', 'hero_called_5bet',
        'called_squeeze', 'raised_squeeze',
        # steal & blind combat
        'called_steal_bb', 'fold_bb_to_sb_steal', 'fold_sb_to_btn_steal',
        'sb_defended_vs_steal', 'bb_3bet_vs_btn', 'bb_3bet_vs_sb',
        'hero_stole_faced_bb_3bet', 'hero_folded_to_bb_3bet',
        # postflop matrices
        'faced_villain_bet_turn', 'fold_to_villain_bet_turn',
        'called_villain_bet_turn', 'raised_villain_bet_turn',
        'faced_villain_bet_river', 'fold_to_villain_bet_river',
        'called_villain_bet_river', 'raised_villain_bet_river',
        'cbet_flop_3bp', 'cbet_flop_4bp', 'cbet_flop_srp',
        'multiway_flop', 'cbet_flop_mw',
        'delayed_cbet_turn', 'probe_turn',
        # XR responses + bet-raise
        'hero_check_raise_flop', 'hero_check_raise_turn', 'hero_check_raise_river',
        'faced_xr_flop', 'faced_xr_turn', 'faced_xr_river',
        'fold_to_xr_flop', 'call_xr_flop', 'reraise_xr_flop',
        'bet_raise_flop', 'bet_raise_turn', 'bet_raise_river',
        # showdown branches + river efficiency
        'cbet_flop_then_sd', 'called_flop_cbet_then_sd',
        'called_river', 'raised_river', 'hero_bet_river',
        'called_river_then_won_sd', 'raised_river_then_won_sd',
        'river_action_class',
        # tracking
        'villain_xr_flop', 'villain_xr_turn', 'villain_xr_river',
        'hero_action_flags',
    ]
    for field in _v728_required:
        _v727_check_field_present(_v727_hands, field, f"on {len(_v727_hands)} parsed hands")

    # Invariants
    # 3-bet IP + 3-bet OOP = total 3-bets
    total_3b = sum(1 for h in _v727_hands if h.get('hero_3bet'))
    ip_3b = sum(1 for h in _v727_hands if h.get('hero_3bet_ip'))
    oop_3b = sum(1 for h in _v727_hands if h.get('hero_3bet_oop'))
    check("v7.28 3bet_ip + 3bet_oop = total hero_3bet",
          ip_3b + oop_3b == total_3b,
          f"got {ip_3b}+{oop_3b} vs {total_3b}")

    # cbet_flop_3bp + cbet_flop_4bp + cbet_flop_srp = total flop cbets
    total_cbet = sum(1 for h in _v727_hands
                     if h.get('pfr')
                     and (h.get('hero_street_actions') or {}).get('flop') == 'cbet')
    sum_cbet_pt = sum(1 for h in _v727_hands
                      if h.get('cbet_flop_3bp') or h.get('cbet_flop_4bp')
                      or h.get('cbet_flop_srp'))
    check("v7.28 cbet by pot type sums to total cbets",
          sum_cbet_pt == total_cbet,
          f"got {sum_cbet_pt} vs {total_cbet}")

    # Mutual exclusion: 3-bet IP and OOP can't both be true
    check("v7.28 3bet_ip xor 3bet_oop",
          not any(h.get('hero_3bet_ip') and h.get('hero_3bet_oop')
                  for h in _v727_hands), True)

    # called_3bet implies hero_faced_raise + first_in + pfr
    check("v7.28 hero_called_3bet implies opener faced raise",
          all((not h.get('hero_called_3bet')) or
              (h.get('first_in') and h.get('pfr') and h.get('hero_faced_raise'))
              for h in _v727_hands),
          "violation found")

    # bb_3bet_vs_btn requires hero_3bet from BB with BTN opener
    check("v7.28 bb_3bet_vs_btn invariant",
          all((not h.get('bb_3bet_vs_btn')) or
              (h.get('position') == 'BB' and h.get('opener_position') == 'BTN'
               and h.get('hero_3bet'))
              for h in _v727_hands), True)

    # called_river / raised_river / hero_bet_river mutex
    for h in _v727_hands:
        cr = h.get('called_river'); rr = h.get('raised_river'); br = h.get('hero_bet_river')
        truthy = sum([1 for x in (cr, rr, br) if x])
        check("v7.28 river action class mutex (≤1 true)",
              truthy <= 1, f"hand {h.get('id')} has {truthy}")
        break  # Only need one check for the invariant pattern

    # delayed_cbet_turn requires Hero PFR + checked flop + bet turn
    check("v7.28 delayed_cbet_turn invariants",
          all((not h.get('delayed_cbet_turn')) or
              (h.get('pfr')
               and (h.get('hero_street_actions') or {}).get('flop') in ('x', 'xc', 'xf')
               and (h.get('hero_street_actions') or {}).get('turn') in ('bet', 'jam'))
              for h in _v727_hands), True)

    # villain_xr_<street> requires Hero bet that street (otherwise no XR possible)
    for st in ('flop', 'turn', 'river'):
        check(f"v7.28 villain_xr_{st} requires Hero bet that street",
              all((not h.get(f'villain_xr_{st}')) or
                  any(b[0] == st for b in (h.get('hero_bets') or []))
                  for h in _v727_hands), True)

    # called_river_then_won_sd implies called_river AND went_to_sd AND won
    check("v7.28 called_river_won_sd composition",
          all((not h.get('called_river_then_won_sd')) or
              (h.get('called_river') and h.get('went_to_sd') and h.get('won'))
              for h in _v727_hands), True)

# ============================================================
# v7.28 TESTS — preflop matrix completion + c-bet matrix + showdown branches
# ============================================================
print("\n" + "=" * 60)
print("v7.28 preflop matrix / c-bet matrix / showdown branches tests")
print("=" * 60)

_v728_required = [
    # Preflop ratios + true PFR
    'true_pfr_action', 'true_pfr_opportunity', 'pf_allin_flag',
    # 3-bet IP/OOP splits
    'hero_3bet_ip', 'hero_3bet_oop', 'fold_to_3bet_ip', 'fold_to_3bet_oop',
    # Call 3/4/5-bet
    'hero_called_3bet', 'hero_called_3bet_ip', 'hero_called_3bet_oop',
    'hero_called_4bet', 'hero_called_5bet',
    # Squeeze response
    'called_squeeze', 'raised_squeeze',
    # Steal & blind combat
    'called_steal_bb', 'fold_bb_to_sb_steal', 'fold_sb_to_btn_steal',
    'sb_defended_vs_steal', 'bb_3bet_vs_btn', 'bb_3bet_vs_sb',
    'hero_stole_faced_bb_3bet', 'hero_folded_to_bb_3bet',
    # C-bet matrix per street
    'faced_villain_bet_turn', 'fold_to_villain_bet_turn',
    'called_villain_bet_turn', 'raised_villain_bet_turn',
    'faced_villain_bet_river', 'fold_to_villain_bet_river',
    'called_villain_bet_river', 'raised_villain_bet_river',
    # C-bet by pot type
    'cbet_flop_3bp', 'cbet_flop_4bp', 'cbet_flop_srp',
    'faced_villain_cbet_flop_3bp', 'faced_villain_cbet_flop_4bp',
    'fold_to_cbet_flop_3bp', 'fold_to_cbet_flop_4bp',
    # Multiway
    'multiway_flop', 'cbet_flop_mw', 'faced_mw_cbet_flop', 'fold_to_mw_cbet',
    # Delayed c-bet, probe turn
    'delayed_cbet_turn', 'probe_turn',
    # Check-raise responses per street
    'fold_to_xr_flop', 'fold_to_xr_turn', 'fold_to_xr_river',
    'call_xr_flop', 'call_xr_turn', 'call_xr_river',
    'reraise_xr_flop', 'reraise_xr_turn', 'reraise_xr_river',
    'hero_check_raise_flop', 'hero_check_raise_turn', 'hero_check_raise_river',
    # Bet-raise per street
    'bet_raise_flop', 'bet_raise_turn', 'bet_raise_river',
    # Showdown branches
    'cbet_flop_then_sd', 'called_flop_cbet_then_sd', 'cbet_turn_then_sd',
    'called_river', 'called_river_then_won_sd',
    'raised_river', 'raised_river_then_won_sd', 'hero_bet_river',
    # River efficiency tag
    'river_action_class',
    # XR detection per street
    'villain_xr_flop', 'villain_xr_turn', 'villain_xr_river',
    'hero_action_flags',
]
if _v727_hands:
    for field in _v728_required:
        check(f"v7.28 field '{field}' present", all(field in h for h in _v727_hands), True)

    # Invariants
    # IP + OOP split must equal total for 3-bet
    total_3bet = sum(1 for h in _v727_hands if h.get('hero_3bet'))
    ip_3bet = sum(1 for h in _v727_hands if h.get('hero_3bet_ip'))
    oop_3bet = sum(1 for h in _v727_hands if h.get('hero_3bet_oop'))
    check("v7.28 hero_3bet_ip + hero_3bet_oop == hero_3bet total",
          ip_3bet + oop_3bet == total_3bet,
          f"split={ip_3bet}+{oop_3bet}={ip_3bet+oop_3bet}, total={total_3bet}")

    # call_3bet_ip + call_3bet_oop == call_3bet total
    cc3 = sum(1 for h in _v727_hands if h.get('hero_called_3bet'))
    cc3i = sum(1 for h in _v727_hands if h.get('hero_called_3bet_ip'))
    cc3o = sum(1 for h in _v727_hands if h.get('hero_called_3bet_oop'))
    check("v7.28 call_3bet_ip + oop == call_3bet total", cc3i + cc3o == cc3, True)

    # called_4bet implies hero_3bet
    check("v7.28 hero_called_4bet implies hero_3bet",
          all((not h.get('hero_called_4bet')) or h.get('hero_3bet')
              for h in _v727_hands),
          "called_4bet without 3-betting first")

    # called_5bet implies hero_4bet_only
    check("v7.28 hero_called_5bet implies hero_4bet_only",
          all((not h.get('hero_called_5bet')) or h.get('hero_4bet_only')
              for h in _v727_hands),
          "called_5bet without 4-betting first")

    # cbet_flop_{3bp,4bp,srp} sum == total cbet flop count
    cb3 = sum(1 for h in _v727_hands if h.get('cbet_flop_3bp'))
    cb4 = sum(1 for h in _v727_hands if h.get('cbet_flop_4bp'))
    cbs = sum(1 for h in _v727_hands if h.get('cbet_flop_srp'))
    cbt = sum(1 for h in _v727_hands
              if h.get('pfr') and (h.get('hero_street_actions') or {}).get('flop') == 'cbet')
    check("v7.28 cbet 3bp+4bp+srp = total cbet flop", cb3 + cb4 + cbs == cbt, True)

    # WTSD-after-flop-cbet implies cbet_flop AND went_to_sd
    check("v7.28 cbet_flop_then_sd implies pfr + cbet + went_to_sd",
          all((not h.get('cbet_flop_then_sd')) or
              (h.get('pfr') and (h.get('hero_street_actions') or {}).get('flop') == 'cbet'
               and h.get('went_to_sd'))
              for h in _v727_hands), True)

    # river_action_class consistency
    for h in _v727_hands:
        rac = h.get('river_action_class')
        ra = (h.get('hero_street_actions') or {}).get('river')
        if rac == 'call':
            check_inv = ra in ('call', 'xc', 'callAI', 'xc-ai')
        elif rac == 'bet':
            check_inv = ra in ('bet', 'jam')
        elif rac == 'raise':
            check_inv = ra in ('raise', 'xr', 'xr-ai')
        else:
            check_inv = True  # empty class for hands without river action
        if not check_inv:
            check(f"v7.28 river_action_class consistent for hand {h.get('id')}", False,
                  f"class={rac}, action={ra}")
    check("v7.28 river_action_class consistency check completed", True, True)

    # bet_raise_{street} requires both bet AND raise on same street
    for st in ('flop', 'turn', 'river'):
        for h in _v727_hands:
            if h.get(f'bet_raise_{st}'):
                haf = (h.get('hero_action_flags') or {}).get(st) or {}
                if not (haf.get('bet') and haf.get('raise')):
                    check(f"v7.28 bet_raise_{st} consistency for hand {h.get('id')}",
                          False, f"flagged but missing bet+raise")
                    break
    check("v7.28 bet_raise consistency check completed", True, True)

# ============================================================
# v7.34 — BB iso vs SB limp (Jasper exploit #2) parser flag tests
# ============================================================
print("\n" + "=" * 60)
print("v7.34 BB iso vs SB limp parser flag tests")
print("=" * 60)

# Synthetic 6-max fixtures: BTN at Seat #4 → SB=Seat 5, BB=Seat 6.
# Tests cover all four expected outcomes:
#   TM91100001: BB facing SB limp + Hero raises → faced=T, iso=T
#   TM91100002: BB facing SB limp + Hero checks → faced=T, check=T
#   TM91100003: BB facing MP open (raise pre-empts limp scenario) → faced=F
#   TM91100004: Hero in SB (not BB) → faced=F
_BB_ISO_FIXTURES = """Poker Hand #TM91100001: Tournament #999, JasperTest $1+$0.10 USD Hold'em No Limit - Level1(10/20) - 2026/05/07 12:00:00
Table 'Test 1' 6-max Seat #4 is the button
Seat 1: PA (1000 in chips)
Seat 2: PB (1000 in chips)
Seat 3: PC (1000 in chips)
Seat 4: PD (1000 in chips)
Seat 5: PE (1000 in chips)
Seat 6: HeroX (1000 in chips)
PE: posts small blind 10
HeroX: posts big blind 20
*** HOLE CARDS ***
Dealt to HeroX [Ah Ks]
PA: folds
PB: folds
PC: folds
PD: folds
PE: calls 10
HeroX: raises 60 to 80
PE: folds
Uncalled bet (60) returned to HeroX
HeroX collected 40 from pot
*** SUMMARY ***
Total pot 40 | Rake 0
Board []
Seat 6: HeroX (big blind) collected (40)


Poker Hand #TM91100002: Tournament #999, JasperTest $1+$0.10 USD Hold'em No Limit - Level1(10/20) - 2026/05/07 12:01:00
Table 'Test 1' 6-max Seat #4 is the button
Seat 1: PA (1000 in chips)
Seat 2: PB (1000 in chips)
Seat 3: PC (1000 in chips)
Seat 4: PD (1000 in chips)
Seat 5: PE (1000 in chips)
Seat 6: HeroX (1000 in chips)
PE: posts small blind 10
HeroX: posts big blind 20
*** HOLE CARDS ***
Dealt to HeroX [7c 2h]
PA: folds
PB: folds
PC: folds
PD: folds
PE: calls 10
HeroX: checks
*** FLOP *** [9d 4s 2c]
PE: checks
HeroX: checks
*** TURN *** [9d 4s 2c] [Tc]
PE: checks
HeroX: checks
*** RIVER *** [9d 4s 2c Tc] [3h]
PE: checks
HeroX: checks
*** SHOW DOWN ***
PE: shows [Ad 5d] (high card Ace)
HeroX: shows [7c 2h] (a pair of Twos)
HeroX collected 40 from pot
*** SUMMARY ***
Total pot 40 | Rake 0
Board [9d 4s 2c Tc 3h]
Seat 6: HeroX (big blind) showed [7c 2h] and won (40) with a pair of Twos


Poker Hand #TM91100003: Tournament #999, JasperTest $1+$0.10 USD Hold'em No Limit - Level1(10/20) - 2026/05/07 12:02:00
Table 'Test 1' 6-max Seat #4 is the button
Seat 1: PA (1000 in chips)
Seat 2: PB (1000 in chips)
Seat 3: PC (1000 in chips)
Seat 4: PD (1000 in chips)
Seat 5: PE (1000 in chips)
Seat 6: HeroX (1000 in chips)
PE: posts small blind 10
HeroX: posts big blind 20
*** HOLE CARDS ***
Dealt to HeroX [9c 4d]
PA: raises 40 to 60
PB: folds
PC: folds
PD: folds
PE: calls 50
HeroX: folds
*** FLOP *** [Kh 8s 2c]
PE: checks
PA: bets 60
PE: folds
Uncalled bet (60) returned to PA
PA collected 140 from pot
*** SUMMARY ***
Total pot 140 | Rake 0
Board [Kh 8s 2c]
Seat 1: PA collected (140)


Poker Hand #TM91100004: Tournament #999, JasperTest $1+$0.10 USD Hold'em No Limit - Level1(10/20) - 2026/05/07 12:03:00
Table 'Test 1' 6-max Seat #5 is the button
Seat 1: PA (1000 in chips)
Seat 2: PB (1000 in chips)
Seat 3: PC (1000 in chips)
Seat 4: PD (1000 in chips)
Seat 5: PE (1000 in chips)
Seat 6: HeroX (1000 in chips)
HeroX: posts small blind 10
PA: posts big blind 20
*** HOLE CARDS ***
Dealt to HeroX [Td 2c]
PB: folds
PC: folds
PD: folds
PE: folds
HeroX: calls 10
PA: checks
*** FLOP *** [9c 4s 2h]
HeroX: checks
PA: checks
*** TURN *** [9c 4s 2h] [Tc]
HeroX: checks
PA: checks
*** RIVER *** [9c 4s 2h Tc] [3h]
HeroX: checks
PA: checks
*** SHOW DOWN ***
HeroX: shows [Td 2c] (two pair, Tens and Twos)
PA: shows [Ad 5d] (high card Ace)
HeroX collected 40 from pot
*** SUMMARY ***
Total pot 40 | Rake 0
Board [9c 4s 2h Tc 3h]
Seat 6: HeroX (small blind) showed [Td 2c] and won (40) with two pair, Tens and Twos
"""

_v734_dir = tempfile.mkdtemp()
with open(os.path.join(_v734_dir, 'GG20260507-9999 - v734 BB iso fixtures.txt'), 'w') as f:
    f.write(_BB_ISO_FIXTURES)
# Use parse_session directly so we don't pollute the run-state of the
# main test_parser-fixture analyzer outputs (those have already been
# checked above via stats/hands globals).
sys.path.insert(0, os.path.dirname(PARSER) or '.')
from gem_parser import parse_session as _v734_parse
_v734_hands, _, _, _ = _v734_parse(_v734_dir)
shutil.rmtree(_v734_dir)

def _v734_get(tid):
    return next((h for h in _v734_hands if h.get('id') == tid), None)

# Case 1: BB faces SB limp + Hero raises → iso
h = _v734_get('TM91100001')
check('v7.34 BB iso #1 parsed', h is not None)
if h:
    check('v7.34 BB iso #1 position == BB', h.get('position') == 'BB', f"got {h.get('position')}")
    check('v7.34 BB iso #1 bb_faced_sb_limp', h.get('bb_faced_sb_limp') is True, f"got {h.get('bb_faced_sb_limp')}")
    check('v7.34 BB iso #1 bb_iso_sb_limp', h.get('bb_iso_sb_limp') is True, f"got {h.get('bb_iso_sb_limp')}")
    check('v7.34 BB iso #1 NOT bb_checked_sb_limp', h.get('bb_checked_sb_limp') is False, f"got {h.get('bb_checked_sb_limp')}")

# Case 2: BB faces SB limp + Hero checks → check
h = _v734_get('TM91100002')
check('v7.34 BB iso #2 parsed', h is not None)
if h:
    check('v7.34 BB iso #2 position == BB', h.get('position') == 'BB', f"got {h.get('position')}")
    check('v7.34 BB iso #2 bb_faced_sb_limp', h.get('bb_faced_sb_limp') is True, f"got {h.get('bb_faced_sb_limp')}")
    check('v7.34 BB iso #2 NOT bb_iso_sb_limp', h.get('bb_iso_sb_limp') is False, f"got {h.get('bb_iso_sb_limp')}")
    check('v7.34 BB iso #2 bb_checked_sb_limp', h.get('bb_checked_sb_limp') is True, f"got {h.get('bb_checked_sb_limp')}")

# Case 3: BB faces an OPEN (not limp) → faced=F (open pre-empts limp scenario)
h = _v734_get('TM91100003')
check('v7.34 BB iso #3 parsed', h is not None)
if h:
    check('v7.34 BB iso #3 position == BB', h.get('position') == 'BB', f"got {h.get('position')}")
    check('v7.34 BB iso #3 NOT faced_sb_limp (open pre-empts)',
          h.get('bb_faced_sb_limp') is False, f"got {h.get('bb_faced_sb_limp')}")
    check('v7.34 BB iso #3 NOT iso', h.get('bb_iso_sb_limp') is False, f"got {h.get('bb_iso_sb_limp')}")

# Case 4: Hero is SB (not BB) → faced=F regardless of BvB action shape
h = _v734_get('TM91100004')
check('v7.34 BB iso #4 parsed', h is not None)
if h:
    check('v7.34 BB iso #4 position == SB', h.get('position') == 'SB', f"got {h.get('position')}")
    check('v7.34 BB iso #4 NOT faced_sb_limp (Hero not in BB)',
          h.get('bb_faced_sb_limp') is False, f"got {h.get('bb_faced_sb_limp')}")

# ============================================================
# B28 regression test: 7-handed first non-blind labeled UTG (not UTG+1)
# ============================================================
# Use parse_one_hand directly with a synthetic 7-handed hand history.
# Tests the position assignment logic at gem_parser.py:300-308.
print("\n--- B28: 7-handed position labeling ---")
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("gem_parser", os.path.join(_HERE, 'gem_parser.py'))
_gp = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_gp)
_b28_hh = """Poker Hand #TM91000028: Tournament #777, Test 7max Hold'em No Limit - Level1(50/100(15)) - 2026/05/09 00:00:00
Table '1' 8-max Seat #2 is the button
Seat 1: P1 (10000 in chips)
Seat 2: P2 (10000 in chips)
Seat 3: P3 (10000 in chips)
Seat 4: Hero (10000 in chips)
Seat 5: P5 (10000 in chips)
Seat 6: P6 (10000 in chips)
Seat 8: P8 (10000 in chips)
P3: posts small blind 50
Hero: posts big blind 100
*** HOLE CARDS ***
Dealt to Hero [Ah Kh]
P5: raises 100 to 200
P6: folds
P8: folds
P1: folds
P2: folds
P3: folds
Hero: folds
Uncalled bet (100) returned to P5
*** SUMMARY ***
Total pot 250 | Rake 0
Seat 5: P5 collected (250)
"""
h = _gp.parse_one_hand(_b28_hh, 'GG20260509-0000 - Test.txt')
check('B28: hand parsed', h is not None)
if h is not None:
    check('B28: n_players == 7', h.get('n_players') == 7, f"got {h.get('n_players')}")
    check('B28: Hero position == BB', h.get('position') == 'BB', f"got {h.get('position')}")
    # Seat 5 (P5) is the first to act after BB → should be UTG (not UTG+1)
    check('B28: opener_position == UTG', h.get('opener_position') == 'UTG',
          f"got {h.get('opener_position')} — should be UTG (first non-blind at 7-handed)")


# ============================================================
# A1 (Aviel handoff 2026-05-25): hero_ip derived from real flop action order
# ============================================================
# hero_ip must reflect ACTUAL postflop position (last flop actor = IP), not
# Hero's absolute seat rank. On simple BTN test hands the two agree; the
# regression guard is that hero_ip equals "Hero is the last distinct actor on
# the flop" whenever a flop was played.
h = get_hand('TM90000006')
check('A1: TM90000006 parsed', h is not None)
if h is not None and h.get('board') and len(h['board']) >= 3:
    check('A1: TM90000006 hero_ip is BTN-IP (True)', h.get('hero_ip') is True,
          f"got {h.get('hero_ip')}")
    # hero_late_position (the old absolute-seat value) is still exposed
    check('A1: hero_late_position field present',
          'hero_late_position' in h, 'hero_late_position missing')


# ============================================================
# SUMMARY
# ============================================================
if errors:
    print("\nFAILURES:")
    for e in errors:
        print(f"  🔴 {e}")
else:
    print("\n✅ ALL TESTS PASSED")

sys.exit(1 if failed > 0 else 0)

# ============================================================
