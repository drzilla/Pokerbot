#!/usr/bin/env python3
"""
gem_solver.py — v0.2

Scope: River HU decisions, three modes:
  Mode 1: call_fold  — Hero facing a bet on the river
  Mode 2: value_bet  — Hero betting river, measure EV of bet vs check
  Mode 3: bluff      — Hero bluffing river, need villain fold-freq for +EV

Method: Exact enumeration of villain's river range.
        True equity + pot-odds EV comparison.

TRANSPARENCY CONTRACT:
  Every run writes full audit bundle to out_dir:
    inputs.json / command.txt / raw_stdout.txt / result.json / caveats.txt
"""
import json, os, sys, itertools, argparse
from datetime import datetime, timezone
from phevaluator import evaluate_cards

RANKS = '23456789TJQKA'
SUITS = 'shdc'

def expand_hand_desc(desc):
    desc = desc.strip()
    if len(desc) == 4 and desc[1] in SUITS and desc[3] in SUITS:
        return [(desc[:2], desc[2:])]
    if len(desc) == 2 and desc[0] == desc[1]:
        r = desc[0]
        cards = [r+s for s in SUITS]
        return list(itertools.combinations(cards, 2))
    if len(desc) == 3:
        r1, r2, kind = desc[0], desc[1], desc[2]
        out = []
        for s1 in SUITS:
            for s2 in SUITS:
                if kind == 's' and s1 != s2: continue
                if kind == 'o' and s1 == s2: continue
                c1, c2 = r1+s1, r2+s2
                if c1 == c2: continue
                out.append((c1, c2))
        return out
    raise ValueError(f"Unparseable: {desc}")

def expand_range(range_spec):
    out = []
    for entry in range_spec:
        for c1, c2 in expand_hand_desc(entry['desc']):
            out.append((c1, c2, entry.get('weight', 1.0), entry['desc']))
    return out

def remove_conflicts(combos, used_cards):
    used = set(used_cards)
    return [(c1,c2,w,d) for c1,c2,w,d in combos if c1 not in used and c2 not in used]


# ============================================================
# PREFLOP EQUITY vs RANGE  (B175, Ron 2026-05-25)
# Combined-loop Monte-Carlo: each iteration samples one villain combo
# (weight-proportional) and one random 5-card runout. The aggregate
# std-error falls as 1/sqrt(n) across the whole range at once, so ~20k
# samples gives ~+/-0.7pp on the range-aggregate equity. Used by the
# CVJ flag to show Hero's equity vs the villain jam range.
# ============================================================
def preflop_equity_vs_range(hero_cards, villain_combos, n_samples=20000,
                            seed=1729):
    """MC preflop equity (%) of a 2-card Hero hand vs a villain RANGE.

    hero_cards: ('Ac','6h')  villain_combos: list of (c1,c2,w,desc) with
    Hero's cards already removed. Returns (equity_pct, n_used) or (None,0)
    if the range is empty.
    """
    import random, bisect
    if not villain_combos or len(hero_cards) != 2:
        return None, 0
    rng = random.Random(seed)
    full = [r + s for r in RANKS for s in SUITS]
    hero = list(hero_cards)
    cum, t = [], 0.0
    for _, _, w, _ in villain_combos:
        t += (w or 1.0)
        cum.append(t)
    if t <= 0:
        return None, 0
    wins = ties = 0.0
    n = 0
    for _ in range(n_samples):
        c1, c2, _, _ = villain_combos[bisect.bisect_left(cum, rng.random() * t)]
        dead = {hero[0], hero[1], c1, c2}
        board = []
        while len(board) < 5:
            card = full[rng.randrange(52)]
            if card in dead:
                continue
            dead.add(card)
            board.append(card)
        hr = evaluate_cards(*hero, *board)
        vr = evaluate_cards(c1, c2, *board)
        if hr < vr:
            wins += 1
        elif hr == vr:
            ties += 1
        n += 1
    if n == 0:
        return None, 0
    return round((wins + 0.5 * ties) / n * 100, 1), n

def river_equity(hero_cards, board, villain_combos, log=None):
    assert len(board) == 5
    hero_rank = evaluate_cards(*hero_cards, *board)
    wins = ties = losses = 0.0
    total = 0.0
    for c1, c2, w, desc in villain_combos:
        v_rank = evaluate_cards(c1, c2, *board)
        if hero_rank < v_rank: outcome='win'; wins += w
        elif hero_rank > v_rank: outcome='loss'; losses += w
        else: outcome='tie'; ties += w
        total += w
        if log is not None:
            log.append({'villain':f'{c1}{c2}','desc':desc,'weight':w,
                        'hero_rank':hero_rank,'villain_rank':v_rank,'outcome':outcome})
    if total == 0: return 0.0, 0, 0, 0, 0
    return (wins + 0.5*ties)/total, total, wins, ties, losses

# ============================================================
# MODE 1: CALL / FOLD
# ============================================================
def solve_call_fold(spec, out_dir):
    hero = spec['hero_cards']
    board = spec['board']
    pot = spec['pot_before_bet']
    bet = spec['bet_facing']
    pot_after_call = pot + 2*bet
    pot_odds = bet / (pot + 2*bet)

    used = set(hero) | set(board)
    value_combos = remove_conflicts(expand_range(spec['villain_value_range']), used)
    bluff_combos = remove_conflicts(expand_range(spec['villain_bluff_range']), used)
    all_combos = value_combos + bluff_combos

    enum_log = []
    eq_all, *_ = river_equity(hero, board, all_combos, log=enum_log)
    eq_value_only, *_ = river_equity(hero, board, value_combos, log=None)

    # B139 (v7.60): EV(call) vs FOLD. When Hero wins he gains the pot that
    # was already in the middle (pot_before + villain's bet = pot + bet) —
    # NOT pot + 2*bet, which double-counts Hero's own call as winnings.
    # The old formula used pot_after_call and was inconsistent with the
    # pot_odds break-even point (it inflated every +EV call by eq*bet).
    pot_won_on_call = pot + bet
    def ev_call(eq): return eq * pot_won_on_call - (1 - eq) * bet
    ev_gto = ev_call(eq_all)
    ev_worst = ev_call(eq_value_only)
    f = spec.get('population_underblff_factor', 0.5)
    eq_pop = eq_all * (1 - f) + eq_value_only * f
    ev_pop = ev_call(eq_pop)

    m14 = 0.02 * (pot + bet)
    def classify(ev):
        if abs(ev) < m14: return 'INDIFFERENT'
        return 'CALL' if ev > 0 else 'FOLD'
    m13_b, m13_w = classify(ev_gto), classify(ev_worst)
    if m13_b=='CALL' and m13_w=='CALL': m13 = 'CALL (robust)'
    elif m13_b=='FOLD' and m13_w=='FOLD': m13 = 'FOLD (robust)'
    elif m13_b=='CALL' and m13_w=='FOLD':
        m13 = 'CALL (asymmetric upside)' if abs(ev_worst) <= 0.3*bet else 'FOLD (stack protection)'
    else: m13 = 'CLOSE — exploit-dependent'

    confidence = '🟢 HIGH' if (len(value_combos)>=6 and len(bluff_combos)>=6) else '🟡 MED'
    if len(all_combos) < 8: confidence = '🔴 LOW (sparse range)'

    fields = {
        'equity_full_pct': round(eq_all*100, 2),
        'equity_value_only_pct': round(eq_value_only*100, 2),
        'equity_pop_pct': round(eq_pop*100, 2),
        'pot_odds_pct': round(pot_odds*100, 2),
        'ev_call_gto': round(ev_gto, 2),
        'ev_call_pop': round(ev_pop, 2),
        'ev_call_worst': round(ev_worst, 2),
        'ev_fold': 0.0,
        'm13_decision': m13,
        'm14_threshold': round(m14, 2),
        'confidence': confidence,
        'value_combo_ct': len(value_combos),
        'bluff_combo_ct': len(bluff_combos),
        'pot_before_bet_bb': round(pot, 2),
        'bet_facing_bb': round(bet, 2),
    }
    _write_bundle(out_dir, spec, 'call_fold', fields, enum_log)
    return _load(out_dir)

# ============================================================
# MODE 2: VALUE BET
# ============================================================
def solve_value_bet(spec, out_dir):
    hero = spec['hero_cards']
    board = spec['board']
    pot = spec['pot_before_bet']
    bet = spec['hero_bet_size_bb']

    used = set(hero) | set(board)
    full_combos = remove_conflicts(expand_range(spec['villain_range']), used)

    if 'villain_call_range_override' in spec:
        call_combos = remove_conflicts(expand_range(spec['villain_call_range_override']), used)
    else:
        THRESH = spec.get('call_rank_threshold', 4800)  # ~top-pair+
        call_combos = [c for c in full_combos if evaluate_cards(c[0], c[1], *board) < THRESH]

    call_w = sum(c[2] for c in call_combos)
    full_w = sum(c[2] for c in full_combos)
    fold_w = full_w - call_w
    fold_freq = fold_w / full_w if full_w > 0 else 0

    enum_log = []
    eq_vs_call, *_ = river_equity(hero, board, call_combos, log=enum_log)
    eq_vs_full, *_ = river_equity(hero, board, full_combos, log=None)

    # EV(bet) = P(fold)*pot + P(call)*[eq*(pot+2bet) - (1-eq)*bet]
    ev_when_called = eq_vs_call * (pot + 2*bet) - (1 - eq_vs_call) * bet
    ev_bet = fold_freq * pot + (1 - fold_freq) * ev_when_called
    ev_check = eq_vs_full * pot   # checkdown — invest 0, realize equity vs full range
    delta = ev_bet - ev_check
    m14 = 0.02 * (pot + bet)
    decision = 'BET' if delta > m14 else ('CHECK' if delta < -m14 else 'INDIFFERENT')

    confidence = '🟢 HIGH' if len(call_combos) >= 6 else '🟡 MED'
    if len(full_combos) < 8: confidence = '🔴 LOW'

    fields = {
        'equity_vs_call_range_pct': round(eq_vs_call*100, 2),
        'equity_vs_full_range_pct': round(eq_vs_full*100, 2),
        'villain_fold_freq_pct': round(fold_freq*100, 2),
        'call_weight': round(call_w, 2),
        'fold_weight': round(fold_w, 2),
        'ev_bet': round(ev_bet, 2),
        'ev_check': round(ev_check, 2),
        'delta_bet_vs_check': round(delta, 2),
        'decision': decision,
        'm14_threshold': round(m14, 2),
        'confidence': confidence,
        'call_combo_ct': len(call_combos),
        'full_combo_ct': len(full_combos),
    }
    _write_bundle(out_dir, spec, 'value_bet', fields, enum_log)
    return _load(out_dir)

# ============================================================
# MODE 3: BLUFF
# ============================================================
def solve_bluff(spec, out_dir):
    hero = spec['hero_cards']
    board = spec['board']
    pot = spec['pot_before_bet']
    bet = spec['hero_bet_size_bb']

    used = set(hero) | set(board)
    full_combos = remove_conflicts(expand_range(spec['villain_range']), used)

    if 'villain_continue_range_override' in spec:
        continue_combos = remove_conflicts(expand_range(spec['villain_continue_range_override']), used)
    else:
        THRESH = spec.get('continue_rank_threshold', 6000)  # pair+
        continue_combos = [c for c in full_combos if evaluate_cards(c[0], c[1], *board) < THRESH]

    cont_w = sum(c[2] for c in continue_combos)
    full_w = sum(c[2] for c in full_combos)
    fold_freq = (full_w - cont_w) / full_w if full_w > 0 else 0
    breakeven = bet / (bet + pot)

    enum_log = []
    eq_called, *_ = river_equity(hero, board, continue_combos, log=enum_log)
    eq_full, *_ = river_equity(hero, board, full_combos, log=None)

    ev_when_called = eq_called * (pot + 2*bet) - (1 - eq_called) * bet
    ev_bluff = fold_freq * pot + (1 - fold_freq) * ev_when_called
    ev_check = eq_full * pot   # realize equity if checked
    delta = ev_bluff - ev_check
    m14 = 0.02 * (pot + bet)
    decision = 'BLUFF' if delta > m14 else ('CHECK' if delta < -m14 else 'INDIFFERENT')

    confidence = '🟢 HIGH' if len(continue_combos) >= 4 else '🟡 MED'
    if len(full_combos) < 8: confidence = '🔴 LOW'

    fields = {
        'breakeven_fold_freq_pct': round(breakeven*100, 2),
        'villain_fold_freq_pct': round(fold_freq*100, 2),
        'equity_when_called_pct': round(eq_called*100, 2),
        'equity_vs_full_if_check_pct': round(eq_full*100, 2),
        'ev_bluff': round(ev_bluff, 2),
        'ev_check': round(ev_check, 2),
        'delta_bluff_vs_check': round(delta, 2),
        'decision': decision,
        'm14_threshold': round(m14, 2),
        'confidence': confidence,
        'continue_combo_ct': len(continue_combos),
        'full_combo_ct': len(full_combos),
    }
    _write_bundle(out_dir, spec, 'bluff', fields, enum_log)
    return _load(out_dir)

# ============================================================
# AUDIT BUNDLE WRITER
# ============================================================
def _write_bundle(out_dir, spec, mode, result_fields, enum_log):
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    with open(os.path.join(out_dir, 'inputs.json'), 'w', encoding='utf-8') as f:
        json.dump({'mode': mode, 'spec': spec, 'timestamp': ts}, f, indent=2)

    with open(os.path.join(out_dir, 'command.txt'), 'w', encoding='utf-8') as f:
        f.write(f"python3 gem_solver.py --spec {spec.get('hand_id','?')}.json --mode {mode}\n")
        f.write(f"# timestamp: {ts}\n# version: gem_solver v0.2\n")

    with open(os.path.join(out_dir, 'raw_stdout.txt'), 'w', encoding='utf-8') as f:
        f.write(f"=== gem_solver v0.2 mode={mode} ===\n")
        f.write(f"Hand: {spec.get('hand_id','?')}\n")
        f.write(f"Hero: {' '.join(spec.get('hero_cards',[]))}\n")
        f.write(f"Board: {' '.join(spec.get('board',[]))}\n\n")
        if enum_log:
            f.write(f"--- ENUMERATION ({len(enum_log)} combos) ---\n")
            f.write(f"{'Combo':8} {'Desc':8} {'Wt':>5} {'H_rank':>7} {'V_rank':>7} {'Result':>6}\n")
            for e in enum_log:
                f.write(f"{e['villain']:8} {e['desc']:8} {e['weight']:>5.2f} "
                        f"{e['hero_rank']:>7} {e['villain_rank']:>7} {e['outcome']:>6}\n")
        f.write(f"\n--- RESULT ---\n")
        for k, v in result_fields.items():
            f.write(f"{k}: {v}\n")

    result = {
        'hand_id': spec.get('hand_id', '?'),
        'mode': mode,
        'version': 'gem_solver v0.2',
        'timestamp': ts,
        'results': result_fields,
    }
    with open(os.path.join(out_dir, 'result.json'), 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)

    with open(os.path.join(out_dir, 'caveats.txt'), 'w', encoding='utf-8') as f:
        f.write(f"=== CAVEATS — mode={mode} ===\n\n")
        f.write("1. RANGE ASSUMPTION. Either user-supplied or heuristic-constructed.\n")
        if 'villain_value_range' in spec:
            f.write(f"   Value: {[e['desc'] for e in spec['villain_value_range'][:20]]}\n")
        if 'villain_bluff_range' in spec:
            f.write(f"   Bluff: {[e['desc'] for e in spec['villain_bluff_range'][:20]]}\n")
        if 'villain_range' in spec:
            f.write(f"   Combined: {[e['desc'] for e in spec['villain_range'][:20]]}"
                    f"{'...' if len(spec['villain_range'])>20 else ''}\n")
        f.write("\n2. SCOPE: river HU, single mode. No earlier-street tree, no sizing sweep, no multiway.\n")
        f.write("3. CHIPEV ONLY — no ICM adjustment.\n")
        f.write("4. HEADS-UP ONLY.\n\n")
        if mode == 'call_fold':
            f.write(f"5. M13: best-case EV {result_fields['ev_call_gto']}BB, "
                    f"worst-case {result_fields['ev_call_worst']}BB → {result_fields['m13_decision']}\n")
        elif mode == 'value_bet':
            f.write(f"5. VALUE BET: fold-freq {result_fields['villain_fold_freq_pct']}%, "
                    f"eq-vs-call {result_fields['equity_vs_call_range_pct']}%, "
                    f"Δ(bet-check) {result_fields['delta_bet_vs_check']}BB\n")
            f.write("   Assumes check = showdown at equity vs full range.\n")
        elif mode == 'bluff':
            f.write(f"5. BLUFF: need {result_fields['breakeven_fold_freq_pct']}% folds, "
                    f"estimate {result_fields['villain_fold_freq_pct']}%, "
                    f"Δ(bluff-check) {result_fields['delta_bluff_vs_check']}BB\n")
        f.write(f"\n6. M14: indifference band {result_fields['m14_threshold']}BB.\n")
        f.write(f"7. CONFIDENCE: {result_fields['confidence']}.\n")
        f.write("8. NOT AUTHORITATIVE FOR RULE UPDATES. Flag for discussion only.\n")

def _load(out_dir):
    with open(os.path.join(out_dir, 'result.json')) as f:
        return json.load(f)

def solve(spec, out_dir):
    mode = spec.get('mode', 'call_fold')
    fn = {'call_fold': solve_call_fold,
          'value_bet': solve_value_bet,
          'bluff':     solve_bluff}.get(mode)
    if fn is None: raise ValueError(f"Unknown mode: {mode}")
    return fn(spec, out_dir)

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--spec', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    with open(args.spec) as f: spec = json.load(f)
    r = solve(spec, args.out)
    print(json.dumps({'hand_id': r['hand_id'], 'mode': r['mode'],
                      'results': r['results']}, indent=2))
