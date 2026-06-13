#!/usr/bin/env python3
"""
gem_solver_integration.py — v0.1

Bridge between GEM's parsed hand data and gem_solver.
Given a parsed hand + raw HH, determine if it's a solvable river
decision, reconstruct the context, call the solver, return the
augmentation for inclusion in the mistake EV table.

Design principles:
  - AUGMENT, not replace. Heuristic EV stays in place; solver result
    is an ADDITIONAL field per mistake.
  - FAIL SILENTLY on non-applicable hands — return None. No crashes.
  - EVERY solver invocation writes its audit bundle. Failures leave
    breadcrumb files so Ron can debug.
  - CHIPEV ONLY. Solver results on ICM spots get a 🟡 tag and
    explicit warning in the augmentation record.
"""
import os, re, json, sys, traceback

# Make local imports work when invoked from gem_report_data.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from gem_solver import solve as solver_solve
    from gem_ranges import construct_villain_river_range
    _SOLVER_AVAILABLE = True
    _IMPORT_ERROR = None
except Exception as e:
    _SOLVER_AVAILABLE = False
    _IMPORT_ERROR = str(e)


# ============================================================
# HAND ELIGIBILITY DETECTION
# ============================================================
def is_solver_eligible(hand):
    """
    Return (eligible, reason, mode) tuple.
    Eligible = HU river decision where solver can produce meaningful output.
    """
    if not _SOLVER_AVAILABLE:
        return False, f'solver_unavailable: {_IMPORT_ERROR}', None

    # Must reach river
    board = hand.get('board', [])
    if len(board) != 5:
        return False, 'not_river', None

    # Must be HU on the river. n_players is seats at table (not useful).
    # Rely on multiway flag from parser. If not set, assume HU (conservative).
    if hand.get('multiway') is True:
        return False, 'multiway', None

    # Must have hero cards
    if len(hand.get('cards', [])) != 2:
        return False, 'no_hero_cards', None

    # Determine river action mode
    river_action = hand.get('river_action')
    if river_action in ('call', 'fold_to_bet'):
        return True, 'river_call_fold', 'call_fold'
    if river_action == 'value_bet':
        return True, 'river_value_bet', 'value_bet'
    if river_action == 'bluff':
        return True, 'river_bluff', 'bluff'

    return False, f'river_action={river_action!r}_not_solvable', None


# ============================================================
# RECONSTRUCT POT AND BET SIZES FROM RAW HH
# ============================================================
def reconstruct_river_context(raw_hh, hero_name='Hero'):
    """
    Parse the raw HH to get pot-before-river-action and river bet size
    in BB. Returns dict or None if parse fails.

    This is separate from gem_parser to avoid coupling — we reparse
    just the pot trajectory.
    """
    if not raw_hh: return None
    # B138 (v7.60): GG hand histories use comma thousands separators
    # ("raises 550 to 1,050", "Total pot 18,280"). Every numeric regex below
    # uses (\d+), which silently stops at the comma — "18,280" parsed as 18.
    # This corrupted every pot reconstruction for 4-digit+ amounts (i.e. most
    # hands past the early levels), feeding the solver garbage pots. Strip
    # commas once up front; no regex in this function depends on a comma.
    raw_hh = raw_hh.replace(',', '')
    # Get BB from level line
    bb_m = re.search(r'Level\d+\((\d+)/(\d+)', raw_hh)
    if not bb_m: return None
    bb = float(bb_m.group(2))

    # Get ante if present
    ante_m = re.search(r'/(\d+)\(', raw_hh)
    ante = float(ante_m.group(1)) if ante_m else 0

    # Find street boundaries
    flop_idx = raw_hh.find('*** FLOP ***')
    turn_idx = raw_hh.find('*** TURN ***')
    river_idx = raw_hh.find('*** RIVER ***')
    showdown_idx = raw_hh.find('*** SHOWDOWN ***')
    summary_idx = raw_hh.find('*** SUMMARY ***')
    river_end = showdown_idx if showdown_idx > 0 else (summary_idx if summary_idx > 0 else len(raw_hh))
    if river_idx < 0: return None

    # Compute pot going into river by summing all contributions pre-river
    pre_river = raw_hh[:river_idx]
    river_section = raw_hh[river_idx:river_end]

    # Sum pot contributions pre-river
    pot_pre_river = 0.0
    for line in pre_river.split('\n'):
        # blinds + antes
        m = re.search(r'posts (?:small blind|big blind|ante|big blind ante) (\d+)', line)
        if m: pot_pre_river += float(m.group(1)); continue
        # regular actions (calls / bets / raises to X)
        m_raise = re.search(r':\s+(?:raises|bets)\s+\d+(?:\s+to\s+(\d+))?', line)
        # Actually simpler: look for "calls N" and "bets N" and "raises X to Y"
        m = re.search(r':\s+calls\s+(\d+)', line)
        if m: pot_pre_river += float(m.group(1)); continue
        m = re.search(r':\s+bets\s+(\d+)', line)
        if m: pot_pre_river += float(m.group(1)); continue
        m = re.search(r':\s+raises\s+\d+\s+to\s+(\d+)', line)
        if m:
            # "raises X to Y" means additional contribution = Y - what they already had in.
            # We can't easily track per-player contribution cleanly here; approximate by
            # counting the "to Y" as the new total this street and adjusting.
            # For a rough pot estimate this overcounts. Use a safer approach:
            pass

    # Fallback: use the total pot from summary line
    total_pot_m = re.search(r'Total pot (\d+)', raw_hh)
    if total_pot_m:
        total_pot = float(total_pot_m.group(1))
    else:
        total_pot = None

    # Parse river action to find villain bet (if any) and hero bet (if any)
    villain_bet = 0.0
    hero_bet = 0.0
    river_lines = river_section.split('\n')
    # Track order: first actor on river
    events = []
    for line in river_lines:
        m = re.match(r'(\S+):\s+(folds|checks|calls|bets|raises)\s*(.*)', line)
        if not m: continue
        player, action, rest = m.group(1), m.group(2), m.group(3)
        amt_m = re.search(r'(\d+)', rest)
        amt = float(amt_m.group(1)) if amt_m else 0
        events.append((player, action, amt))

    # Identify villain bet facing hero (for call_fold mode)
    for i, (p, a, amt) in enumerate(events):
        if p != hero_name and a in ('bets', 'raises'):
            villain_bet = amt
            break
    # Identify hero bet (for value_bet/bluff modes)
    for p, a, amt in events:
        if p == hero_name and a in ('bets', 'raises'):
            hero_bet = amt
            break

    # If raw sum under-counted, fallback: use total_pot back-derived.
    # Simplest: for call/fold, pot_before_bet ≈ total_pot - (villain_bet + hero_call_amount)
    # If hero called: total_pot = pot_pre_river + villain_bet + hero_call (= villain_bet)
    # So pot_pre_river = total_pot - 2*villain_bet
    hero_called = any(p == hero_name and a == 'calls' for p, a, _ in events)

    if total_pot and villain_bet > 0 and hero_called:
        pot_before_river_bet = total_pot - 2 * villain_bet
    elif total_pot and villain_bet > 0 and not hero_called:
        pot_before_river_bet = total_pot - villain_bet
    elif total_pot and hero_bet > 0:
        # Hero led river. pot_pre_river + hero_bet (+ villain response)
        villain_called = any(p != hero_name and a == 'calls' for p, a, _ in events)
        if villain_called: pot_before_river_bet = total_pot - 2 * hero_bet
        else: pot_before_river_bet = total_pot - hero_bet
    elif total_pot and villain_bet == 0 and hero_bet == 0:
        # B224 (Ron review 2026-05-25): the river checked through — no chips
        # went in on the river, so the summary "Total pot" IS the pot at the
        # river decision. This is the reliable path for missed-aggression
        # (Hero-checked) candidates; the pot_pre_river raw sum below undercounts
        # because it cannot cleanly attribute "raises X to Y" contributions.
        pot_before_river_bet = total_pot
    else:
        pot_before_river_bet = pot_pre_river  # best-effort fallback

    return {
        'bb': bb,
        'ante': ante,
        'pot_before_river_action_bb': round(pot_before_river_bet / bb, 2),
        'villain_river_bet_bb': round(villain_bet / bb, 2),
        'hero_river_bet_bb': round(hero_bet / bb, 2),
        'raw_total_pot': total_pot,
        'river_events': events,
    }


# ============================================================
# MAIN ENTRY POINT: ANALYZE ONE HAND
# ============================================================
def analyze_hand(hand, raw_hh, out_dir_base, session_tag='unknown', derive_line=False,
                 synthetic_river_bet_pct=None):
    """
    Given a single parsed hand and its raw HH, run the solver if applicable.
    Returns augmentation dict (for inclusion in mistake EV records), or None.

    out_dir_base: base directory for audit bundles (e.g., /home/claude/solver_runs/)
    derive_line:  when True (call_fold mode), the villain-range action sequence
                  is derived from hand['hero_street_actions'] so a check-call
                  line constructs a villain BETTING range rather than the
                  legacy hero-aggressor assumption. Used by the read-dependent
                  screener. Default False keeps the mistakes path unchanged.
    synthetic_river_bet_pct:
                  B224 (Ron review 2026-05-25). value_bet mode normally reads
                  Hero's ACTUAL river bet — which is 0 when Hero checked, so
                  the IV.6 Solver Confirmation Pass (which tests Hero-CHECKED
                  river spots) skipped every hand as `no_hero_bet`. When this
                  is set (e.g. 60) and Hero did not bet the river, a synthetic
                  bet of that % of the pot is used so solve_value_bet can
                  actually evaluate "should Hero have bet?". The result is
                  flagged synthetic_bet=True. Does not affect any hand where
                  Hero genuinely bet.
    """
    eligible, reason, mode = is_solver_eligible(hand)
    if not eligible:
        return None

    try:
        ctx = reconstruct_river_context(raw_hh, hero_name='Hero')
        if ctx is None or ctx['pot_before_river_action_bb'] <= 0:
            return {
                'hand_id': hand.get('id'),
                'solver_applied': False,
                'reason': 'pot_reconstruction_failed',
            }

        # Build base spec
        hand_id = hand.get('id', 'UNKNOWN')
        spec = {
            'hand_id': hand_id,
            'mode': mode,
            'hero_cards': list(hand.get('cards', [])),
            'board': list(hand.get('board', [])),
        }

        # Per-mode fields
        if mode == 'call_fold':
            spec['pot_before_bet'] = ctx['pot_before_river_action_bb']
            spec['bet_facing'] = ctx['villain_river_bet_bb']
            if spec['bet_facing'] <= 0:
                return {'hand_id': hand_id, 'solver_applied': False, 'reason': 'no_villain_bet_to_face'}
            # Construct villain range
            lead_pct = (spec['bet_facing'] / spec['pot_before_bet'] * 100) if spec['pot_before_bet'] else 75
            if derive_line:
                # Read the real hero line so a check-call-down constructs a
                # villain BETTING range, not the legacy hero-aggressor range.
                cf_seq = _derive_call_fold_sequence(hand, lead_pct)
            else:
                cf_seq = [
                    {'street':'flop','hero':'bet','villain':'call','hero_size_pct':33},
                    {'street':'turn','hero':'bet','villain':'call','hero_size_pct':55},
                    {'street':'river','hero':'check','villain':'bet','villain_size_pct':lead_pct},
                ]
            rr = construct_villain_river_range(
                villain_position='BB',  # best-guess; real version would read from hand
                hero_position=hand.get('position', 'BTN'),
                hero_open_size_pct=22,
                stack_depth_bb=hand.get('eff_stack_bb', 40),
                hero_cards=spec['hero_cards'],
                board=spec['board'],
                action_sequence=cf_seq,
            )
            spec['villain_value_range'] = rr['value_range']
            spec['villain_bluff_range'] = rr['bluff_range']
            spec['population_underblff_factor'] = 0.5
        elif mode == 'value_bet':
            spec['pot_before_bet'] = ctx['pot_before_river_action_bb']
            spec['hero_bet_size_bb'] = ctx['hero_river_bet_bb']
            _synthetic_bet = False
            if spec['hero_bet_size_bb'] <= 0:
                # B224: Hero checked the river. If a synthetic test size was
                # supplied (IV.6 Solver Confirmation Pass), evaluate the
                # hypothetical bet instead of skipping as `no_hero_bet`.
                if synthetic_river_bet_pct and spec['pot_before_bet'] > 0:
                    spec['hero_bet_size_bb'] = round(
                        spec['pot_before_bet'] * synthetic_river_bet_pct / 100.0, 2)
                    _synthetic_bet = True
                else:
                    return {'hand_id': hand_id, 'solver_applied': False,
                            'reason': 'no_hero_bet'}
            rr = construct_villain_river_range(
                villain_position='BB',
                hero_position=hand.get('position', 'BTN'),
                hero_open_size_pct=22,
                stack_depth_bb=hand.get('eff_stack_bb', 40),
                hero_cards=spec['hero_cards'],
                board=spec['board'],
                action_sequence=[
                    {'street':'flop','hero':'bet','villain':'call','hero_size_pct':33},
                    {'street':'turn','hero':'bet','villain':'call','hero_size_pct':55},
                    {'street':'river','hero':'bet','villain':'?','villain_size_pct':0},
                ],
            )
            # For value_bet mode, combine value+bluff into single range
            combined = rr['value_range'] + rr['bluff_range']
            spec['villain_range'] = combined
        elif mode == 'bluff':
            spec['pot_before_bet'] = ctx['pot_before_river_action_bb']
            spec['hero_bet_size_bb'] = ctx['hero_river_bet_bb']
            if spec['hero_bet_size_bb'] <= 0:
                return {'hand_id': hand_id, 'solver_applied': False, 'reason': 'no_hero_bet'}
            rr = construct_villain_river_range(
                villain_position='BB',
                hero_position=hand.get('position', 'BTN'),
                hero_open_size_pct=22,
                stack_depth_bb=hand.get('eff_stack_bb', 40),
                hero_cards=spec['hero_cards'],
                board=spec['board'],
                action_sequence=[
                    {'street':'flop','hero':'bet','villain':'call','hero_size_pct':33},
                    {'street':'turn','hero':'bet','villain':'call','hero_size_pct':55},
                    {'street':'river','hero':'bet','villain':'?','villain_size_pct':0},
                ],
            )
            spec['villain_range'] = rr['value_range'] + rr['bluff_range']

        # Store the range construction audit alongside solver audit
        out_dir = os.path.join(out_dir_base, session_tag, hand_id)
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, 'range_audit.json'), 'w', encoding='utf-8') as f:
            json.dump(rr, f, indent=2)

        # Run solver
        result = solver_solve(spec, out_dir)

        # Extract headline EV for augmentation
        r = result['results']
        _ev_bet_bb = _ev_check_bb = None
        if mode == 'call_fold':
            solver_ev = r['ev_call_pop']    # use population-adjusted as default
            headline = f"EV(call)={r['ev_call_pop']:+.2f} | {r['m13_decision']}"
        elif mode == 'value_bet':
            solver_ev = r['delta_bet_vs_check']
            headline = f"Δ(bet-check)={r['delta_bet_vs_check']:+.2f} | {r['decision']}"
            # B224: surface bet/check EV so the IV.6 Solver Confirmation Pass
            # can read them directly (it expects ev_bet_bb / ev_check_bb).
            _ev_bet_bb = r.get('ev_bet')
            _ev_check_bb = r.get('ev_check')
        elif mode == 'bluff':
            solver_ev = r['delta_bluff_vs_check']
            headline = f"Δ(bluff-check)={r['delta_bluff_vs_check']:+.2f} | {r['decision']}"
        else:
            solver_ev = 0
            headline = '?'

        return {
            'hand_id': hand_id,
            'solver_applied': True,
            'mode': mode,
            'solver_ev_bb': round(solver_ev, 2),
            'ev_bet_bb': round(_ev_bet_bb, 2) if _ev_bet_bb is not None else None,
            'ev_check_bb': round(_ev_check_bb, 2) if _ev_check_bb is not None else None,
            'synthetic_bet': (_synthetic_bet if mode == 'value_bet' else False),
            'headline': headline,
            'confidence': r.get('confidence', '?'),
            'audit_path': out_dir,
            'ranges_auto_constructed': True,
            'range_source_key': rr.get('starting_range_key'),
            # v7.60: full result fields surfaced so the read-dependent
            # screener can recompute EV across a population under-bluff band.
            # B224: value_bet also surfaces result_fields now.
            'result_fields': r if mode in ('call_fold', 'value_bet') else None,
        }

    except Exception as e:
        # Write breadcrumb and return failure augmentation
        tb = traceback.format_exc()
        err_dir = os.path.join(out_dir_base, session_tag, hand.get('id', 'UNKNOWN') + '_ERROR')
        os.makedirs(err_dir, exist_ok=True)
        with open(os.path.join(err_dir, 'error.txt'), 'w', encoding='utf-8') as f:
            f.write(f"{e}\n\n{tb}")
        return {
            'hand_id': hand.get('id'),
            'solver_applied': False,
            'reason': f'exception: {type(e).__name__}: {e}',
            'error_path': err_dir,
        }


# ============================================================
# BATCH PROCESSING (called from gem_report_data.py)
# ============================================================
def run_on_mistakes(mistakes, hands, raw_hh_map, out_dir_base, session_tag,
                    heuristic_ev_map=None):
    """
    Iterate over mistakes, run solver on each eligible hand.
    Returns dict: {hand_id: augmentation_dict}

    mistakes: list from stats['mistakes']
    hands: list of all parsed hands (to look up by id)
    raw_hh_map: dict {hand_id: raw_hh_text}
    heuristic_ev_map: optional dict {hand_id: heuristic_ev_bb} — used for
        cross-session history/drift monitoring. If None, heuristic EV
        recorded as 0 in history CSV.
    """
    if not _SOLVER_AVAILABLE:
        return {}
    hands_by_id = {h['id']: h for h in hands if 'id' in h}
    heur_map = heuristic_ev_map or {}
    mistake_type_by_id = {m.get('id'): m.get('type', '') for m in mistakes if m.get('id')}
    out = {}
    history_rows = []
    n_attempted = n_applied = n_failed = 0
    for m in mistakes:
        hid = m.get('id')
        if not hid or hid in out: continue
        hand = hands_by_id.get(hid)
        if not hand: continue
        raw_hh = raw_hh_map.get(hid, '')
        n_attempted += 1
        aug = analyze_hand(hand, raw_hh, out_dir_base, session_tag)
        if aug is None:
            continue
        out[hid] = aug
        if aug.get('solver_applied'):
            n_applied += 1
            # Append history row for drift monitoring
            try:
                from gem_solver_history import make_row
                # Determine if result was within M14 indifference band
                within_m14 = False
                try:
                    res_path = os.path.join(aug.get('audit_path', ''), 'result.json')
                    if os.path.exists(res_path):
                        with open(res_path) as f:
                            rfields = json.load(f).get('results', {})
                        within_m14 = bool(rfields.get('m14_gto_indifferent')
                                          or rfields.get('m14_pop_indifferent')
                                          or (abs(aug.get('solver_ev_bb', 0))
                                              < rfields.get('m14_threshold', 0.5)))
                except Exception:
                    pass
                row = make_row(
                    session_tag=session_tag,
                    hand_id=hid,
                    mode=aug.get('mode', ''),
                    mistake_type=mistake_type_by_id.get(hid, ''),
                    confidence=aug.get('confidence', ''),
                    heuristic_ev=heur_map.get(hid, 0),
                    solver_ev=aug.get('solver_ev_bb', 0),
                    audit_path=aug.get('audit_path', ''),
                    range_source_key=aug.get('range_source_key', ''),
                    within_m14=within_m14,
                )
                history_rows.append(row)
            except Exception:
                pass  # history append must never break the pipeline
        else:
            n_failed += 1
    # Persist history rows (read /mnt/project/, write /home/claude/)
    if history_rows:
        try:
            from gem_solver_history import append_rows
            append_rows(history_rows)
        except Exception:
            pass
    # Write summary log
    os.makedirs(os.path.join(out_dir_base, session_tag), exist_ok=True)
    with open(os.path.join(out_dir_base, session_tag, '_SUMMARY.txt'), 'w', encoding='utf-8') as f:
        f.write(f"gem_solver integration run — session {session_tag}\n")
        f.write(f"mistakes scanned: {len(mistakes)}\n")
        f.write(f"river-eligible (attempted): {n_attempted}\n")
        f.write(f"solver applied: {n_applied}\n")
        f.write(f"failed / not-applicable: {n_failed}\n")
        f.write(f"history rows appended: {len(history_rows)}\n")
        for hid, a in out.items():
            f.write(f"  {hid}: {a.get('headline', a.get('reason','?'))}\n")
    return out


# ============================================================
# READ-DEPENDENT CALL SCREENER (v7.60 — result-independent)
# ============================================================
# Surfaces HU river bluff-catch calls whose CALL/FOLD verdict flips
# between a GTO-balanced villain range and a population under-bluffed
# range (or sits in the indifference band). Result-INDEPENDENT: scans
# won and lost hands alike — the previously-invisible winning read-
# dependent calls are the ones that silently reinforce a -EV habit.
#
# This is a SCREENER, not a verdicting detector: it only surfaces
# candidates into the analyst feed. The analyst step still assigns the
# III.x verdict per hand. (Consistent with the v7 instruction that
# read-dependent patterns must not be auto-classified by detectors.)

def _derive_call_fold_sequence(hand, lead_pct):
    """Map hand['hero_street_actions'] to a villain-range action_sequence
    for construct_villain_river_range. A check-call street -> villain bet;
    a hero bet/cbet street -> villain call. Falls back to check/check on
    unknown. River is always hero-check / villain-bet (call_fold mode)."""
    hsa = hand.get('hero_street_actions') or {}
    seq = []
    for street, default_size in (('flop', 33), ('turn', 55)):
        v = str(hsa.get(street, '')).lower()
        if 'cbet' in v or v.startswith('bet') or 'jam' in v or 'lead' in v:
            seq.append({'street': street, 'hero': 'bet', 'villain': 'call',
                        'hero_size_pct': default_size})
        elif 'xc' in v or 'call' in v:
            seq.append({'street': street, 'hero': 'check', 'villain': 'bet',
                        'villain_size_pct': default_size})
        else:  # 'x' check-through, or unknown
            seq.append({'street': street, 'hero': 'check', 'villain': 'check'})
    seq.append({'street': 'river', 'hero': 'check', 'villain': 'bet',
                'villain_size_pct': lead_pct})
    return seq


def _extract_raw_hh_local(hand_ids, hh_dir):
    """Self-contained raw-HH extractor (avoids a gem_report_data import)."""
    found = {}
    if not hh_dir or not os.path.isdir(hh_dir):
        return found
    want = set(hand_ids)
    for fn in os.listdir(hh_dir):
        fp = os.path.join(hh_dir, fn)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            continue
        for hid in list(want):
            if hid in content:
                m = re.search(rf'(Poker Hand #{re.escape(hid)}:.*?)(?=Poker Hand #|\Z)',
                              content, re.DOTALL)
                if m:
                    found[hid] = m.group(1).strip()
                    want.discard(hid)
        if not want:
            break
    return found


def _classify_call_ev(ev, m14):
    """CALL / FOLD / INDIFF given an EV and the M14 indifference half-band."""
    if abs(ev) <= m14:
        return 'INDIFF'
    return 'CALL' if ev > 0 else 'FOLD'


def _solve_call_population_ev(hand, raw_hh, out_dir_base, session_tag,
                              factors=(0.25, 0.50, 0.75)):
    """Run the river call/fold solver on one hand and return its EV vs a
    GTO-balanced villain range and across a population under-bluff band.

    Returns a dict. solvable=False when the hand is not a river call/fold
    the solver can price (e.g. a turn bluff-catch — the river solver cannot
    price an earlier-street decision). The population-baseline point estimate
    is the EV at the mid band factor (default 0.50)."""
    if not _SOLVER_AVAILABLE:
        return {'solvable': False, 'reason': 'solver_unavailable'}
    try:
        aug = analyze_hand(hand, raw_hh, out_dir_base, session_tag,
                           derive_line=True)
    except Exception as e:
        return {'solvable': False, 'reason': f'exception: {type(e).__name__}'}
    if not aug or not aug.get('solver_applied') or aug.get('mode') != 'call_fold':
        return {'solvable': False,
                'reason': (aug or {}).get('reason', 'not_river_call_fold')}
    r = aug.get('result_fields') or {}
    pot = r.get('pot_before_bet_bb', 0) or 0
    bet = r.get('bet_facing_bb', 0) or 0
    m14 = r.get('m14_threshold', 0) or 0
    if pot <= 0 or bet <= 0:
        return {'solvable': False, 'reason': 'pot_reconstruction_failed'}

    eq_full = (r.get('equity_full_pct', 0) or 0) / 100.0   # GTO-balanced range
    eq_val = (r.get('equity_value_only_pct', 0) or 0) / 100.0  # all-value range
    # B139: EV(call) wins the pot already in the middle (pot + villain bet),
    # not pot + 2*bet — Hero's own call is not part of his winnings.
    pot_won = pot + bet

    def _ev(eq):
        return eq * pot_won - (1 - eq) * bet

    ev_gto = _ev(eq_full)
    band = []
    for f in factors:
        eq_f = eq_full * (1 - f) + eq_val * f
        ev_f = _ev(eq_f)
        band.append({'underbluff_factor': round(f, 2),
                     'ev_call_bb': round(ev_f, 2),
                     'verdict': _classify_call_ev(ev_f, m14)})
    mid = band[len(band) // 2]   # population-baseline point estimate
    return {
        'solvable': True,
        'ev_call_gto_bb': round(ev_gto, 2),
        'verdict_gto': _classify_call_ev(ev_gto, m14),
        'ev_call_pop_bb': mid['ev_call_bb'],
        'verdict_pop': mid['verdict'],
        'pop_factor': mid['underbluff_factor'],
        'underbluff_band': band,
        'm14_threshold': m14,
        'sizing_pct': round((bet / pot) * 100, 1),
        'equity_full_pct': r.get('equity_full_pct', 0),
        'equity_value_only_pct': r.get('equity_value_only_pct', 0),
        'pot_odds_pct': r.get('pot_odds_pct', 0),
        'value_combo_ct': r.get('value_combo_ct', 0),
        'bluff_combo_ct': r.get('bluff_combo_ct', 0),
        'solver_confidence': r.get('confidence', '?'),
        'audit_path': aug.get('audit_path', ''),
    }


def screen_read_dependent_calls(hands, hh_dir, out_dir_base,
                                session_tag='unknown', exclude_ids=None,
                                underbluff_band=(0.25, 0.50, 0.75),
                                polar_sizing_min=0.70, cap=12):
    """
    Scan ALL hands for HU river bluff-catch calls whose verdict is
    read-dependent. A call is read-dependent when its CALL/FOLD verdict
    is NOT robust across the plausible population under-bluff band:
    either it hard-flips (CALL under a balanced range, FOLD under an
    under-bluffed range) or equilibrium itself lands in the indifference
    band (so the population read decides).

    Returns a list of {'id': hand_id, 'screen': {...}} dicts, sorted
    closest-to-indifference first, capped at `cap`. The caller (analyzer)
    wraps each with the standard hand-context block.
    """
    if not _SOLVER_AVAILABLE:
        return []
    exclude_ids = set(exclude_ids or [])

    targets = [h for h in hands
               if h.get('river_action') == 'call'
               and h.get('id')
               and h.get('id') not in exclude_ids
               and h.get('multiway') is not True
               and len(h.get('board', [])) == 5
               and len(h.get('cards', [])) == 2]
    if not targets:
        return []

    raw_hh_map = _extract_raw_hh_local([h['id'] for h in targets], hh_dir)
    screen_tag = f'{session_tag}_rdscreen'
    out = []

    for h in targets:
        hid = h['id']
        raw_hh = raw_hh_map.get(hid, '')
        if not raw_hh:
            continue
        ev = _solve_call_population_ev(h, raw_hh, out_dir_base, screen_tag,
                                       factors=underbluff_band)
        if not ev.get('solvable'):
            continue

        # Polar-sizing gate — read-dependence lives in big bets.
        if ev['sizing_pct'] / 100.0 < polar_sizing_min:
            continue

        v_gto = ev['verdict_gto']
        band = ev['underbluff_band']
        m14 = ev['m14_threshold']
        verdict_set = {v_gto} | {b['verdict'] for b in band}
        hard_flip = ('CALL' in verdict_set and 'FOLD' in verdict_set)
        indiff = ('INDIFF' in verdict_set)
        if not (hard_flip or indiff):
            continue  # robust CALL or robust FOLD — not read-dependent

        flip_f = next((b['underbluff_factor'] for b in band
                       if b['verdict'] == 'FOLD'), None)
        severity = 'hard-flip' if hard_flip else 'indifference-band'
        ev_gto = ev['ev_call_gto_bb']
        if hard_flip and flip_f is not None:
            axis = (f"GTO-balanced range -> {v_gto} ({ev_gto:+.2f} BB); pool "
                    f"under-bluffs (factor >= {flip_f:.2f}) -> FOLD. Verdict "
                    f"hinges on villain's river bluff frequency.")
        else:
            axis = (f"Equilibrium ~indifferent (EV {ev_gto:+.2f} BB, within "
                    f"+/-{m14:.2f} M14 band) — the population read decides "
                    f"call vs fold.")

        net = h.get('net_bb', 0) or 0
        out.append({
            'id': hid,
            'screen': {
                'verdict_gto': v_gto,
                'ev_call_gto_bb': ev_gto,
                'ev_call_pop_bb': ev['ev_call_pop_bb'],
                'pop_factor': ev['pop_factor'],
                'underbluff_band': band,
                'flip_severity': severity,
                'decision_axis': axis,
                'sizing_pct': ev['sizing_pct'],
                'equity_full_pct': ev['equity_full_pct'],
                'equity_value_only_pct': ev['equity_value_only_pct'],
                'pot_odds_pct': ev['pot_odds_pct'],
                'value_combo_ct': ev['value_combo_ct'],
                'bluff_combo_ct': ev['bluff_combo_ct'],
                'solver_confidence': ev['solver_confidence'],
                'result_net_bb': round(net, 1),
                'won': net > 0,
                'audit_path': ev['audit_path'],
            },
        })

    # Closest-to-indifference first — the most genuinely read-dependent.
    out.sort(key=lambda c: abs(c['screen']['ev_call_gto_bb']))
    return out[:cap]


def quantify_read_dependent_calls(hand_ids, hands, hh_dir, out_dir_base,
                                  session_tag='unknown'):
    """
    Quantify a known set of read-dependent calls (analyst-verdicted III.4
    hands + screener-flagged hands). For each river call/fold the solver
    prices the call's chip-EV vs FOLD at a GTO-balanced range and at the
    population baseline (mid under-bluff factor).

    This is the EV of the *decision*, not the hand's net result — a
    read-dependent call inside a 60BB bust still only risks the river
    bet. Turn (or earlier) bluff-catches return solvable=False: the river
    solver cannot price an earlier-street decision.

    Returns {hand_id: {solvable, ev_call_pop_bb, ev_call_gto_bb, ...}}.
    """
    if not _SOLVER_AVAILABLE:
        return {}
    hands_by_id = {h.get('id'): h for h in hands if h.get('id')}
    want = [hid for hid in dict.fromkeys(hand_ids) if hid in hands_by_id]
    if not want:
        return {}
    raw = _extract_raw_hh_local(want, hh_dir)
    quant_tag = f'{session_tag}_rdquant'
    out = {}
    for hid in want:
        out[hid] = _solve_call_population_ev(
            hands_by_id[hid], raw.get(hid, ''), out_dir_base, quant_tag)
    return out


if __name__ == '__main__':
    print('gem_solver_integration v0.1 loaded.')
    print(f'  solver available: {_SOLVER_AVAILABLE}')
    if not _SOLVER_AVAILABLE:
        print(f'  import error: {_IMPORT_ERROR}')
