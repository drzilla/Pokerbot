#!/usr/bin/env python3
"""
gem_aggression_solver_pass.py — v1.0 (Ron 2026-05-12, B66)

For each IN_SCOPE river missed-aggression candidate from gem_aggression_detector,
attempt a solver-level confirmation using gem_solver's value_bet mode.

WHY:
  v7.47's aggression detector uses 5 heuristic gates. The solver is the
  ground-truth EV check for river HU spots. If solver says EV(check) > EV(bet),
  the heuristic flag was wrong — demote to "AMBIGUOUS_BY_SOLVER".

LIMITATIONS:
  - River HU only (gem_solver scope).
  - Reconstructs pot from raw HH; if HH parsing fails, skip with HEURISTIC_ONLY.
  - Villain range constructed via gem_ranges heuristic — coarse, but better
    than nothing for confirmation purposes.
  - "Check" EV = 0 (assumes checked through = pot is awarded by showdown,
    Hero's equity vs villain's checked-back range). A check-call-bet would
    need separate handling; for the missed-aggression case Hero checked
    and the line ended, so the comparison is bet vs no-action.

PUBLIC API:
    run_solver_pass(aggression_block, hands, hh_dir, out_dir) -> {
        confirmed: [hand_ids whose heuristic verdict matched solver],
        denied:    [hand_ids whose solver said check is +EV vs bet],
        skipped:   [{hand_id, reason} for ineligible/failed],
    }
"""

import os
import sys
import json
import traceback


def run_solver_pass(aggression_block, hands, hh_dir, out_dir):
    """For each MISSED river candidate, run solver to confirm.

    Returns dict with confirmed/denied/skipped lists. The augmentation is
    written back into the candidate dict (mutates aggression_block in place).
    """
    result = {'confirmed': [], 'denied': [], 'skipped': [], 'errors': []}

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from gem_solver_integration import is_solver_eligible, analyze_hand
    except Exception as e:
        result['errors'].append(f'solver_import_failed: {type(e).__name__}: {e}')
        return result

    # Build raw HH lookup for the candidate IDs we'll be checking
    missed = aggression_block.get('missed_aggression', []) or []
    river_candidates = [c for c in missed if c.get('street_of_interest') == 'river']
    if not river_candidates:
        return result

    hands_by_id = {h.get('id'): h for h in hands if isinstance(h, dict)}
    candidate_ids = [c['hand_id'] for c in river_candidates if c.get('hand_id')]

    # Pull raw HH via the existing helper
    try:
        from gem_report_data import _extract_raw_hh
        raw_hh_map = _extract_raw_hh(candidate_ids, hh_dir)
    except Exception as e:
        result['errors'].append(f'raw_hh_extraction_failed: {type(e).__name__}: {e}')
        raw_hh_map = {}

    os.makedirs(out_dir, exist_ok=True)

    for cand in river_candidates:
        hid = cand.get('hand_id')
        if not hid:
            result['skipped'].append({'hand_id': '?', 'reason': 'no_hand_id'})
            continue
        h = hands_by_id.get(hid)
        if not h:
            result['skipped'].append({'hand_id': hid, 'reason': 'hand_not_found'})
            continue

        # The detector's solver_status field tells us if this was IN_SCOPE.
        # But gem_solver_integration.is_solver_eligible relies on
        # `hand.get('river_action')`. For checked-river spots (the missed-aggression
        # case), river_action is typically NOT in the eligible set ('call',
        # 'fold_to_bet', 'value_bet', 'bluff'). So we synthesize a value_bet
        # check: did Hero have a profitable bet vs his checked-river range?
        raw_hh = raw_hh_map.get(hid)
        if not raw_hh:
            result['skipped'].append({'hand_id': hid, 'reason': 'no_raw_hh'})
            cand['solver_verdict'] = 'SKIPPED (no raw HH)'
            continue

        # Construct a synthetic "what if Hero had bet" record for the solver.
        # Use a 60%-pot bet as the test sizing (typical thin-value sizing on
        # river when checked-to). Higher sizings can be tested in follow-up.
        synthetic = dict(h)
        synthetic['river_action'] = 'value_bet'
        # Compute synthetic bet — 60% pot of pre-river pot (will be reconstructed
        # by reconstruct_river_context). Use a placeholder that the solver
        # interpretation will override.
        try:
            from gem_solver_integration import reconstruct_river_context
            ctx = reconstruct_river_context(raw_hh, hero_name='Hero')
            if ctx is None or ctx.get('pot_before_river_action_bb', 0) <= 0:
                result['skipped'].append({'hand_id': hid, 'reason': 'pot_reconstruction_failed'})
                cand['solver_verdict'] = 'SKIPPED (pot reconstruction failed)'
                continue
            pot_pre = ctx['pot_before_river_action_bb']
            # If Hero already had a check action and villain checked back,
            # pot_before_river_action is the pre-river pot. Use 60% of that
            # as our test sizing.
            synthetic_bet = round(0.6 * pot_pre, 2)
        except Exception as e:
            result['skipped'].append({'hand_id': hid, 'reason': f'reconstruct_error: {type(e).__name__}'})
            cand['solver_verdict'] = f'SKIPPED (reconstruct: {type(e).__name__})'
            continue

        # B224 (Ron review 2026-05-25): the synthetic-bet side channel was
        # never wired up — analyze_hand's value_bet branch read Hero's ACTUAL
        # river bet (0 when checked) and bailed `no_hero_bet`, so every
        # candidate skipped. analyze_hand now accepts synthetic_river_bet_pct:
        # when Hero checked the river it builds a hypothetical bet of that %
        # of the reconstructed pot and runs the full value-bet solve through
        # the existing (tested) villain-range construction. 60% pot = the
        # IV.6 test sizing.
        try:
            aug = analyze_hand(synthetic, raw_hh, out_dir, session_tag='agg_pass',
                               synthetic_river_bet_pct=60)
        except Exception as e:
            result['errors'].append(f'{hid}: {type(e).__name__}: {e}')
            result['skipped'].append({'hand_id': hid, 'reason': f'analyze_hand_error: {type(e).__name__}'})
            cand['solver_verdict'] = f'ERROR ({type(e).__name__})'
            continue

        if aug is None or not aug.get('solver_applied'):
            reason = aug.get('reason', 'not_applicable') if isinstance(aug, dict) else 'no_result'
            result['skipped'].append({'hand_id': hid, 'reason': reason})
            cand['solver_verdict'] = f'SKIPPED ({reason})'
            continue

        # Interpret solver output. analyze_hand returns dict with EV info.
        ev_bet = aug.get('ev_bet_bb', None)
        ev_check = aug.get('ev_check_bb', 0.0)
        delta = (ev_bet - ev_check) if (ev_bet is not None) else None

        if delta is None:
            result['skipped'].append({'hand_id': hid, 'reason': 'ev_unavailable'})
            cand['solver_verdict'] = 'SKIPPED (EV unavailable)'
            continue

        cand['solver_ev_bet'] = round(ev_bet, 2) if ev_bet is not None else None
        cand['solver_ev_check'] = round(ev_check, 2)
        cand['solver_ev_delta'] = round(delta, 2)
        cand['solver_test_bet_pct'] = 60  # what we tested
        # Apply 0.2 BB noise threshold (project convention)
        if delta >= 0.2:
            cand['solver_verdict'] = f'CONFIRMED (Δ={delta:+.2f}BB, bet > check)'
            result['confirmed'].append(hid)
        elif delta <= -0.2:
            cand['solver_verdict'] = f'DENIED (Δ={delta:+.2f}BB, check > bet — heuristic was wrong)'
            result['denied'].append(hid)
        else:
            cand['solver_verdict'] = f'NEUTRAL (Δ={delta:+.2f}BB, < noise threshold 0.2)'
            result['skipped'].append({'hand_id': hid, 'reason': 'below_noise_threshold'})

    return result


# ============================================================
# DRILL CLUSTERING (B67 v7.48)
# ============================================================
# Group missed-aggression candidates by leak class. The clustering surface
# is AF breakdown's below-target slices: e.g., river_ip_pfr AF=0.20 →
# all MISSED_AGGRESSION candidates with street=river, pos=ip, role=pfr.
# Each cluster becomes one drill pack with focused tactical questions.

def cluster_for_drills(aggression_block, af_breakdown):
    """Return drill clusters keyed by (street, pos, role) leak class.

    Each cluster: {
        'slice_key': str,
        'slice_af': float,
        'slice_target': str,
        'slice_gap': float,
        'spots': [aggression candidates that match this slice],
        'drill_question': str (focused tactical question per cluster),
    }
    """
    if not aggression_block or 'error' in (aggression_block or {}):
        return []
    if not af_breakdown or 'error' in (af_breakdown or {}):
        return []

    missed = aggression_block.get('missed_aggression', []) or []
    if not missed:
        return []

    # Find below-target slices from AF breakdown (with n>=5)
    cross = af_breakdown.get('cross', {}) or {}
    below = []
    for key, slc in cross.items():
        if (slc.get('status') == '🟡' and slc.get('n', 0) >= 5
                and 'passive' in slc.get('note', '')):
            af = slc.get('af')
            if af is None: continue
            try:
                lo = float(slc.get('target_band', '0-0').split('-')[0])
                gap = lo - af
                below.append((key, slc, gap))
            except Exception:
                continue
    below.sort(key=lambda x: -x[2])  # biggest gap first

    clusters = []
    for slice_key, slc, gap in below:
        # Parse slice key: e.g., "river_ip_pfr" -> (street, pos, role)
        parts = slice_key.split('_')
        if len(parts) != 3: continue
        street, pos, role = parts
        # Find missed-aggression candidates that match
        matching = []
        for c in missed:
            if c.get('street_of_interest') != street: continue
            # Match position by looking at hsa + position info on the candidate
            # We don't have a direct pos/role field on aggression candidates,
            # but we have hand fields elsewhere — for now, just match by street.
            # Position match will be approximate.
            matching.append(c)
        if not matching:
            continue
        clusters.append({
            'slice_key': slice_key,
            'slice_af': slc.get('af'),
            'slice_af_display': slc.get('af_display'),
            'slice_target': slc.get('target_band'),
            'slice_gap': round(gap, 2),
            'slice_n': slc.get('n', 0),
            'spots': matching[:5],  # top 5 per cluster
            'spot_count': len(matching),
            'drill_question': _drill_question_for_slice(slice_key),
        })
    return clusters


def _drill_question_for_slice(slice_key):
    """Return a focused tactical question for the given leak class.

    Keep the question SPECIFIC — generic "review line" questions don't drill.
    """
    questions = {
        'river_ip_pfr':   "On the river, you're IP as PFR and villain has checked to you. "
                          "What's the value-bet threshold (hand strength minimum) given "
                          "villain's checked-river-IP-call range? Name three Hero holdings "
                          "that should bet for thin value and three that should check back.",
        'river_oop_pfr':  "On the river, you're OOP as PFR with the betting lead. What's "
                          "your three-streets-of-value cutoff? What sizing maximizes EV "
                          "against villain's flatted-to-river range?",
        'turn_ip_pfr':    "You c-bet flop IP, villain called. Villain checks turn. What's "
                          "the 2nd-barrel value threshold? Name the turn cards that improve "
                          "villain's range (giving up) vs. yours (continuing).",
        'turn_oop_pfr':   "You c-bet flop OOP, villain called. Turn brings a brick (no draw "
                          "completes). What's the double-barrel range? Which sizings extract "
                          "best from villain's flatted-flop range?",
        'flop_ip_pfr':    "You raised preflop, villain called. Which flop textures get a "
                          "high-frequency cbet IP vs. which get a checked-back range? Name "
                          "three c-bet skip boards.",
        'flop_oop_pfr':   "You raised preflop, villain called IP. Which flop textures get "
                          "donked vs. checked? Name three OOP donk-lead boards vs. three "
                          "check-call boards.",
        'flop_ip_caller': "You called preflop, villain c-bet flop IP into you. When do you "
                          "float-raise (small sizing) vs. just float-call vs. fold? "
                          "Name two raise-now boards vs. two call-now boards.",
        'turn_ip_caller': "You called flop IP, villain checks turn. What's your stab-in-the-"
                          "dark frequency? Name three turn cards that demand a probe bet.",
    }
    return questions.get(slice_key, f"Review the {slice_key} decision class — your "
                                     f"frequency is below target, identify whether the "
                                     f"leak is value or bluff side.")


if __name__ == '__main__':
    print("gem_aggression_solver_pass.py — solver confirmation pass module")
    print("Usage: imported by gem_report_data.py during pipeline run")
