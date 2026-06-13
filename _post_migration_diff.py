"""Post-migration diff: compare pre/post _stat_row output snapshots."""
import sys, json, re
sys.path.insert(0, '.')

# Force reimport
for mod_name in list(sys.modules.keys()):
    if 'gem_report_draft' in mod_name:
        del sys.modules[mod_name]

from gem_report_draft._helpers import _stat_row, _stat_row_pct

results = []
def snap(label, fn, *args, **kwargs):
    results.append({'label': label, 'output': fn(*args, **kwargs)})

# Exact same calls as pre-migration snapshot
snap('T1:PFR', _stat_row_pct, 'PFR', 25.0, 200, 14, 20, 'PF raise rate', link_to='sec-8-2')
snap('T1:3Bet', _stat_row_pct, '3-Bet', 8.5, 120, 6, 9, 'PF re-raise rate', link_to='sec-8-3', aim='>=9.6 aim')
snap('T1:Squeeze', _stat_row, 'Squeeze %', 5, 80, 5, 13, 'squeeze vs LP open+call', link_to='sec-8-4')
snap('T1:ColdCall', _stat_row, 'Cold Call (non-blind)', 15, 200, 5, 15, 'CC pre rake', link_to='sec-8-5')
snap('T1:ATS', _stat_row, 'ATS', 80, 200, 35, 45, 'attempt to steal', link_to='sec-8-6')
snap('T1:BBDef', _stat_row, 'BB Def vs Steal', 30, 50, 55, 65, 'BB defend %', link_to='sec-8-8')
snap('T1:SBDef', _stat_row, 'SB Def vs LP (J29)', 12, 40, 30, 40, 'SB def vs LP open')
snap('T1:4Bet', _stat_row_pct, 'Hero 4-Bet', 7.0, 60, 5, 12, '4bet pre', link_to='sec-8-7')
snap('T1:5Bet', _stat_row_pct, 'Hero 5-Bet', 20.0, 15, 15, 25, '5bet proper')
snap('T2:CRFlop', _stat_row, 'Check-Raise Flop', 6, 100, 6, 8, 'flop x/r', link_to='sec-11-7', aim='>=7.2 aim')
snap('T2:CRTotal', _stat_row, 'Check-Raise Total', 10, 100, 8, 12, 'all streets x/r', link_to='sec-11-7')
snap('T2:FoldCBet', _stat_row, 'Fold to CBet', 25, 50, 50, 60, 'facing flop cbet', link_to='sec-11-1')
snap('T2:WTSD', _stat_row_pct, 'WTSD (vol)', 28.5, 200, 25, 32, 'went to SD')
snap('T2:WSD', _stat_row, 'WSD (vol)', 30, 55, 50, 58, 'won at SD')
snap('T2:WWSF', _stat_row, 'WWSF', 45, 100, 42, 48, 'won-when-saw-flop')
snap('T2:NSD', _stat_row, 'Non-SD Win', 15, 50, 25, 35, 'won w/o showdown')
snap('T2:SDAgg', _stat_row, 'SD Aggressor', 8, 15, 40, 100, "aggressor's SD won %")
snap('T2:Semi', _stat_row, 'Semi-Bluff %', 10, 50, 15, 30, 'semi-bluffs as % of bet decisions', link_to='sec-7-2')
snap('T2:Pure', _stat_row, 'Pure Bluff %', 5, 50, 10, 20, 'pure bluffs as % of bet decisions', link_to='sec-7-2')
snap('T3:HUIP', _stat_row, 'HU IP', 40, 60, 60, 75, 'in-position, heads-up SRP cbet')
snap('T3:HUOOP', _stat_row, 'HU OOP', 20, 60, 35, 55, 'out-of-position SRP cbet')
snap('T3:MW', _stat_row, 'MW (multiway)', 15, 50, 30, 45, '3+ players to flop')
snap('T3:Turn', _stat_row, 'Turn (double-barrel)', 25, 45, 50, 65, 'after flop cbet, turn bet')
snap('T3:River', _stat_row, 'River (triple-barrel)', 10, 30, 35, 55, 'after turn cbet, river bet')
snap('T4:Float', _stat_row, 'Float Flop (Call CBet IP)', 20, 50, 35, 50, 'J#5: float vs over-cbetters')
snap('T4:RaiseCR', _stat_row, 'Raise CBet OOP (CR)', 5, 50, 8, 15, 'J#4 OOP half')
snap('T5:BBIso', _stat_row, 'BB Iso vs SB Limp', 35, 50, 65, 85, 'J#2: punish weak SB limp range')
snap('T6:CallerHU', _stat_row_pct, 'Caller IP Aggression (HU)', 35.0, 100, 30, 40, 'raise + bet vs villain check')
snap('T6:CallerMW', _stat_row_pct, 'Caller IP Aggression (MW)', 25.0, 80, 20, 30, 'multiway version')
snap('EDGE:n0', _stat_row, 'TestZero', 0, 0, 10, 20, 'n=0 case')
snap('EDGE:small_n', _stat_row, 'TestSmall', 1, 5, 10, 20, 'n<n_min case')
snap('EDGE:pct_n0', _stat_row_pct, 'TestPctZero', 0.0, 0, 10, 20, 'pct n=0')

# Load pre-migration
with open('_pre_migration_snapshot.json', 'r', encoding='utf-8') as f:
    pre = json.load(f)

_ci_span = re.compile(r'<span class="ci-tip" title="[^"]+">ⓘ</span>')

print('=== BEFORE/AFTER DIFF — behavioral equivalence check ===\n')
all_ok = True
for old, new in zip(pre, results):
    assert old['label'] == new['label']
    label = old['label']
    o_cells = [c.strip() for c in old['output'].split('|')[1:-1]]
    n_cells = [c.strip() for c in new['output'].split('|')[1:-1]]

    # Metric name: old col 0, new col 0
    if o_cells[0] != n_cells[0]:
        print(f'  {label}: METRIC NAME CHANGED: {o_cells[0]!r} -> {n_cells[0]!r}')
        all_ok = False

    # Status emoji: old col 4, new col 1
    if o_cells[4] != n_cells[1]:
        print(f'  {label}: STATUS CHANGED: {o_cells[4]!r} -> {n_cells[1]!r}')
        all_ok = False

    # Value/rate: old col 1 ('rate% (n=N)' or 'n=0'), new col 2 ('rate% <span>' or dash)
    old_val = o_cells[1]
    new_val_clean = _ci_span.sub('', n_cells[2]).strip()
    if 'n=0' in old_val:
        if new_val_clean != '—':
            print(f'  {label}: n=0 VALUE MISMATCH: new={new_val_clean!r}')
            all_ok = False
    else:
        old_rate = old_val.split('(')[0].strip()
        if old_rate != new_val_clean:
            print(f'  {label}: RATE CHANGED: {old_rate!r} -> {new_val_clean!r}')
            all_ok = False

    # CI: old col 2, new embedded in tooltip on col 2
    old_ci = o_cells[2]
    ci_match = re.search(r'title="CI 90%: ([^"]+)"', n_cells[2])
    new_ci = ci_match.group(1) if ci_match else '—'
    if old_ci != '—' and new_ci == '—':
        print(f'  {label}: CI DROPPED: was {old_ci!r}')
        all_ok = False
    elif old_ci != '—' and old_ci != new_ci:
        print(f'  {label}: CI CHANGED: {old_ci!r} -> {new_ci!r}')
        all_ok = False

    # Target: old col 3, new col 3
    if o_cells[3] != n_cells[3]:
        print(f'  {label}: TARGET CHANGED: {o_cells[3]!r} -> {n_cells[3]!r}')
        all_ok = False

    # Notes: old col 5, new col 6
    if o_cells[5] != n_cells[6]:
        print(f'  {label}: NOTES CHANGED: {o_cells[5]!r} -> {n_cells[6]!r}')
        all_ok = False

    # Sample: old embedded in Value 'n=N', new col 5
    if 'n=0' not in old_val:
        n_match = re.search(r'\(n=(\d+)\)', old_val)
        if n_match:
            old_n = f'n={n_match.group(1)}'
            if old_n != n_cells[5]:
                print(f'  {label}: SAMPLE CHANGED: {old_n!r} -> {n_cells[5]!r}')
                all_ok = False

if all_ok:
    print('All 32 snapshots: metric name, status emoji, rate, CI, target, sample, notes preserved')
    print('Column reorder + CI-to-tooltip + Delta addition confirmed behavior-equivalent')
else:
    print('\nBehavioral equivalence BROKEN')
    sys.exit(1)

# Also print a few example rows for visual inspection
print('\n=== SAMPLE POST-MIGRATION ROWS ===\n')
for r in results[:5]:
    print(f'  {r["label"]:20s} {r["output"]}')
print(f'  {"...":20s}')
for r in results[-3:]:
    print(f'  {r["label"]:20s} {r["output"]}')
