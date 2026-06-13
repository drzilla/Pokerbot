"""Decision Point Extractor — Stage 2 of the GEM pipeline.

Runs IMMEDIATELY after parsing, BEFORE detectors.  Creates
hand['decision_points'] on every hand by scanning the action_ledger for
Hero strategic choices.

A decision_point is any Hero action that involves a strategic choice:
  - call, raise, bet, jam, check (when facing no bet = check-back or check-call later)
  - fold (only when facing a bet — preflop fold first-in is NOT a decision point)

A preflop fold with no prior VPIP is NOT a decision point (no choice was made).
A hand where Hero posts blinds and folds to a raise IS a decision point
(fold_vs_bet).

Each DP gets identity, position, board, and opponent-snapshot fields populated.
Math and coaching fields are left as None — filled later by the Auto-Coach
Engine (Stage 8) for candidate hands only.

Ownership: this module owns hand['decision_points'].
           The analyzer owns hand['primary_villain'] and hand['key_decision_id'].
"""


# ---------------------------------------------------------------------------
# Action classification map: (action, context) -> action_class
# ---------------------------------------------------------------------------
def _classify_action(action, street, hand, action_idx, ledger, is_all_in):
    """Classify a Hero action into a semantic action_class.

    Returns one of: open, cold_call, 3bet, 4bet, 5bet, defend, squeeze,
    cbet, barrel, check_raise, probe, donk, value_bet, bluff, jam,
    fold_vs_bet, check_back, call_bet, raise_bet.
    """
    # Preflop classifications
    if street == 'preflop':
        if action == 'raises':
            # Count raises before this one
            prior_raises = sum(1 for e in ledger[:action_idx]
                               if e['street'] == 'preflop'
                               and e['action'] == 'raises')
            if prior_raises == 0:
                return 'open'
            elif prior_raises == 1:
                # Was Hero's first action a call? If so, this is a squeeze or cold-4bet
                hero_prior = [e for e in ledger[:action_idx]
                              if e['street'] == 'preflop' and e['player'] == hand.get('hero')]
                if any(e['action'] == 'calls' for e in hero_prior):
                    return 'squeeze'  # or cold-4bet; simplified for now
                return '3bet'
            elif prior_raises == 2:
                return '4bet'
            else:
                return '5bet'
        elif action == 'calls':
            # Was there a raise before? If so, what kind of call?
            prior_raises = sum(1 for e in ledger[:action_idx]
                               if e['street'] == 'preflop'
                               and e['action'] == 'raises')
            if prior_raises == 0:
                return 'call_bet'  # calling a limp or blind
            elif prior_raises == 1:
                # Hero calling an open — cold call or defend?
                pos = hand.get('position', '')
                if pos in ('BB', 'SB'):
                    return 'defend'
                return 'cold_call'
            elif prior_raises == 2:
                return 'call_bet'  # calling a 3-bet
            else:
                return 'call_bet'  # calling 4bet+
        elif action == 'folds':
            return 'fold_vs_bet'
        elif action == 'checks':
            return 'check_back'  # BB checks to see flop

    # Postflop classifications
    else:
        if action == 'bets':
            # Is Hero the PFR? If so, is this a c-bet?
            is_pfr = hand.get('pfr', False)
            prior_hero_bets_this_street = sum(
                1 for e in ledger[:action_idx]
                if e['street'] == street and e['player'] == hand.get('hero')
                and e['action'] in ('bets', 'raises'))

            if is_pfr and prior_hero_bets_this_street == 0:
                if street == 'flop':
                    return 'cbet'
                elif street == 'turn' and hand.get('hero_cbet_flop'):
                    return 'barrel'
                elif street == 'river' and hand.get('double_barreled'):
                    return 'barrel'
                else:
                    return 'probe'  # PFR didn't cbet earlier street, now betting
            elif not is_pfr:
                # Non-PFR betting — donk or probe
                # Check if a bet was already made this street by someone else
                prior_bets = [e for e in ledger[:action_idx]
                              if e['street'] == street and e['action'] in ('bets', 'raises')]
                if not prior_bets:
                    return 'donk' if street == 'flop' else 'probe'
                return 'raise_bet'
            return 'value_bet'  # generic

        elif action == 'raises':
            # Check if Hero checked first (check-raise)
            hero_checked = any(
                e['player'] == hand.get('hero') and e['action'] == 'checks'
                for e in ledger[:action_idx] if e['street'] == street)
            if hero_checked:
                return 'check_raise'
            return 'raise_bet'

        elif action == 'calls':
            return 'call_bet'

        elif action == 'checks':
            return 'check_back'

        elif action == 'folds':
            return 'fold_vs_bet'

    if is_all_in:
        return 'jam'

    return action  # fallback


# ---------------------------------------------------------------------------
# Position-relative computation
# ---------------------------------------------------------------------------
def _position_relative(hand, street, action_idx, ledger):
    """Determine Hero's position relative to the action on this street.

    Returns: 'ip', 'oop', 'middle', or 'multiway_unclear'.
    """
    if street == 'preflop':
        # Preflop position is based on seat position relative to button
        return 'ip' if hand.get('hero_ip') else 'oop'

    # Postflop: who acts after Hero on this street?
    hero_name = hand.get('hero', '')
    street_actions = [e for e in ledger if e['street'] == street]
    active_players = []
    seen = set()
    for e in street_actions:
        if e['player'] not in seen and e['action'] != 'folds':
            active_players.append(e['player'])
            seen.add(e['player'])

    if len(active_players) <= 2:
        # HU: Hero IP if they act last
        if active_players and active_players[-1] == hero_name:
            return 'ip'
        return 'oop'

    # Multiway: count players acting after Hero
    hero_pos_in_order = next(
        (i for i, p in enumerate(active_players) if p == hero_name), -1)
    if hero_pos_in_order < 0:
        return 'multiway_unclear'
    players_after = len(active_players) - hero_pos_in_order - 1
    if players_after == 0:
        return 'ip'
    elif players_after >= 2:
        return 'middle'
    else:
        return 'oop'


def _players_left_to_act(hand, street, action_idx, ledger):
    """Count players who haven't acted yet after Hero's action."""
    hero_name = hand.get('hero', '')
    street_actions = [e for e in ledger if e['street'] == street]
    # Players still in the hand (haven't folded) who act after action_idx
    active_after = set()
    for e in street_actions[action_idx + 1:]:
        if e['action'] != 'folds' and e['player'] != hero_name:
            active_after.add(e['player'])
    return len(active_after)


# ---------------------------------------------------------------------------
# Facing villain identification
# ---------------------------------------------------------------------------
def _find_facing_villain(hand, street, action_idx, ledger, hero_action):
    """Identify who Hero is facing at this decision point.

    Returns (villain_name, villain_role, snapshot_dict) or (None, None, {}).
    """
    hero_name = hand.get('hero', '')

    if hero_action == 'folds' or hero_action in ('calls', 'raises'):
        # Hero is responding to someone's bet/raise — find the last aggressor
        for i in range(action_idx - 1, -1, -1):
            e = ledger[i]
            if e['street'] != street:
                break
            if e['player'] != hero_name and e['action'] in ('bets', 'raises'):
                role = 'raiser' if e['action'] == 'raises' else 'bettor'
                # Check if it was a jam
                if e.get('is_all_in'):
                    role = 'jammer'
                name = e['player']
                pos = e.get('position', '?')
                stk = e.get('stack_bb', 0) or (hand.get('seat_stacks_bb_all') or {}).get(pos, 0)
                return name, role, {'position': pos, 'stack_bb': stk}

    elif hero_action in ('bets', 'checks'):
        # Hero is initiating or checking — "facing" the field or last raiser
        # For preflop opens, facing_villain is the BB (or next to act)
        if street == 'preflop':
            # Find the opener if Hero is responding to one
            for i in range(action_idx - 1, -1, -1):
                e = ledger[i]
                if e['player'] != hero_name and e['action'] == 'raises':
                    name = e['player']
                    pos = e.get('position', '?')
                    stk = (hand.get('seat_stacks_bb_all') or {}).get(pos, 0)
                    return name, 'opener', {'position': pos, 'stack_bb': stk}
        return None, None, {}

    return None, None, {}


# ---------------------------------------------------------------------------
# Board context at a given street
# ---------------------------------------------------------------------------
def _board_at_street(hand, street):
    """Return board cards visible at this street."""
    board = hand.get('board') or []
    if street == 'preflop':
        return []
    elif street == 'flop':
        return board[:3]
    elif street == 'turn':
        return board[:4]
    elif street == 'river':
        return board[:5]
    return board


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------
def extract_decision_points(hands):
    """Stage 2: Extract decision_points[] for every hand.

    Mutates each hand dict in place (adds 'decision_points' key).
    Returns the hands list for chaining.

    Decision points are created for every Hero strategic action.
    Identity, position, board, and opponent-snapshot fields are populated.
    Math and coaching fields are left as None.
    """
    for hand in hands:
        ledger = hand.get('action_ledger') or []
        hero_name = hand.get('hero', '')
        board = hand.get('board') or []
        dps = []

        for idx, entry in enumerate(ledger):
            if entry.get('player') != hero_name:
                continue
            action = entry.get('action', '')

            # Skip non-strategic actions
            if action == 'posts':
                continue  # posting blinds/antes is not a decision

            # Skip preflop fold first-in (no strategic choice — Hero just folded)
            if action == 'folds' and entry.get('street') == 'preflop':
                # Was there a raise before Hero? If not, this is a first-in fold = no choice
                prior_raises = sum(1 for e in ledger[:idx]
                                   if e['street'] == 'preflop'
                                   and e['action'] == 'raises')
                if prior_raises == 0:
                    # BB walking or SB completing then folding — not a strategic fold
                    continue
                # There WAS a raise → this is a fold-vs-bet decision (e.g., fold to open)
                # Only include if Hero could have acted (had cards dealt)
                pass

            street = entry.get('street', 'preflop')
            is_allin = entry.get('is_all_in', False)

            # Classify the action
            action_class = _classify_action(
                action, street, hand, idx, ledger, is_allin)

            # Override with jam if all-in
            hero_action = action
            if is_allin and action in ('raises', 'bets', 'calls'):
                if action in ('raises', 'bets'):
                    hero_action = 'jam'
                    if action_class not in ('jam',):
                        action_class = 'jam'

            # Position context
            pos_rel = _position_relative(hand, street, idx, ledger)
            plta = _players_left_to_act(hand, street, idx, ledger)

            # Facing villain
            vname, vrole, vsnap = _find_facing_villain(
                hand, street, idx, ledger, action)

            # Board context
            board_at = _board_at_street(hand, street)

            # Effective stack at this decision
            eff_stack = (hand.get('eff_stack_bb_at_decision')
                         or hand.get('eff_stack_bb')
                         or hand.get('stack_bb')
                         or 0)

            # SPR (postflop only)
            spr = hand.get('spr') if street != 'preflop' else None

            # Players in hand at this street
            street_players = len(set(
                e['player'] for e in ledger
                if e['street'] == street and e['action'] != 'folds'))

            # Build the DP id: hand_id + street + action + sequence
            seq = sum(1 for d in dps if d['street'] == street) + 1
            dp_id = f"{hand.get('id', '?')}_{street}_{action}_{seq:03d}"

            dp = {
                # Identity (set here)
                'id': dp_id,
                'hand_id': hand.get('id', '?'),
                'street': street,
                'action_index': idx,
                'is_key_decision': False,  # analyzer sets the real one

                # Hero action
                'hero_action': hero_action,
                'hero_amount_bb': entry.get('amount_bb', 0),
                'hero_action_class': action_class,

                # Position context
                'hero_position': hand.get('position', '?'),
                'position_relative': pos_rel,
                'players_left_to_act': plta,
                'hero_is_pfr': hand.get('pfr', False),
                'hero_is_last_aggressor': False,  # computed below
                'last_aggressor': None,
                'eff_stack_bb': eff_stack,
                'spr': spr,
                'players_in_hand': street_players,

                # Opponent context (reference-based)
                'facing_villain_name': vname,
                'facing_villain_role': vrole,
                'facing_villain_snapshot': vsnap,

                # Board context
                'board': list(board_at),
                'board_texture': hand.get('board_texture') if street != 'preflop' else None,
                'board_archetype': hand.get('board_archetype') if street != 'preflop' else None,
                'draw_profile': None,  # filled by draw_profile computation if available

                # ===== MATH (None — filled by Auto-Coach, Stage 8) =====
                'math_type': None,
                'pot_before_villain_bet_bb': None,
                'villain_bet_bb': None,
                'pot_facing_hero_bb': None,
                'hero_call_amount_bb': None,
                'final_pot_if_call_bb': None,
                'required_equity': None,
                'hero_equity_vs_range': None,
                'equity_source': None,
                'ev_call_bb': None,
                'risk_bb': None,
                'reward_bb': None,
                'fold_equity_required': None,
                'estimated_fold_equity': None,
                'ev_bet_bb': None,
                'hero_risk_bb': None,
                'pot_before_jam_bb': None,
                'equity_when_called': None,
                'ev_jam_bb': None,
                'ev_check_bb': None,
                'preferred_action': None,

                # ===== COACHING (None — filled by Auto-Coach) =====
                'correct_action': None,
                'correct_size_bb': None,
                'minimum_continue_hand': None,
                'threshold_explanation': None,
                'memory_rule': None,
                'exception': None,
                'drill_bucket': None,

                # ===== LEAK LINKAGE (None — filled by Detectors) =====
                'leak_code': None,
                'detector_name': None,
                'detector_confidence': None,

                # ===== CLASSIFICATION (None — filled by Detectors + Prefill) =====
                'is_mistake': None,
                'mistake_type': None,
                'ev_lost_bb': None,

                # ===== ROOT MISTAKE (None — filled by Auto-Coach) =====
                'is_root_mistake': None,
                'downstream_of': None,

                # ===== CONFIDENCE (None — filled by Detectors) =====
                'confidence': None,
                'risk_flags': [],
                'needs_review': None,

                # ===== CONTEXT (None — filled by Auto-Coach) =====
                'population_note': None,
                'villain_specific_note': None,
                'icm_context': None,
            }

            # Compute last_aggressor
            for i in range(idx - 1, -1, -1):
                e = ledger[i]
                if e['street'] != street:
                    break
                if e['action'] in ('bets', 'raises'):
                    dp['last_aggressor'] = e['player']
                    dp['hero_is_last_aggressor'] = (e['player'] == hero_name)
                    break

            dps.append(dp)

        hand['decision_points'] = dps

    return hands


# ---------------------------------------------------------------------------
# Utility: look up a DP by ID across all hands
# ---------------------------------------------------------------------------
def get_dp_by_id(hands, dp_id):
    """Find a decision_point by its ID across a list of hands."""
    for h in hands:
        for dp in h.get('decision_points', []):
            if dp['id'] == dp_id:
                return dp
    return None
