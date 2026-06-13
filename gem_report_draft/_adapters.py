"""Renderer adapter layer — the ONLY way renderer files access
decision_points, primary_villain, and analysis_confidence.

Rule: no renderer file (sections_*.py, tldr.py, _hand_grid.py, _html.py)
should directly call hand.get('decision_points') or hand.get('primary_villain').
All access goes through these helpers, which handle:
  - Legacy hands without decision_points (backward compat)
  - Missing fields (safe defaults)
  - Villain reference resolution
  - math_type-aware display formatting
"""


def get_decision_points(hand):
    """Return decision_points[] or empty list for legacy hands."""
    return hand.get('decision_points') or []


def get_key_decision(hand):
    """Return the key decision_point or None.

    Resolution order:
    1. Match key_decision_id
    2. First dp with is_key_decision=True
    3. First dp (fallback)
    """
    dp = get_decision_points(hand)
    if not dp:
        return None
    kid = hand.get('key_decision_id')
    if kid:
        match = next((d for d in dp if d['id'] == kid), None)
        if match:
            return match
    # Fallback: first marked key
    key = next((d for d in dp if d.get('is_key_decision')), None)
    return key or dp[0]


def get_primary_villain(hand):
    """Return primary villain dict or empty dict.

    Falls back to opener_position for legacy hands without primary_villain.
    """
    pv = hand.get('primary_villain')
    if pv:
        return pv
    # Legacy fallback: resolve from opener_position
    op = hand.get('opener_position')
    if op:
        for name, v in (hand.get('villains') or {}).items():
            if isinstance(v, dict) and v.get('position') == op:
                return {'name': name, **v}
    return {}


def get_villain_full(hand, villain_name):
    """Resolve full villain data from hand['villains'] by name.

    Returns the villain dict or empty dict if not found.
    """
    if not villain_name:
        return {}
    return (hand.get('villains') or {}).get(villain_name, {})


def get_analysis_confidence(hand):
    """Return analysis_confidence dict or safe default."""
    return hand.get('analysis_confidence') or {
        'confidence': 'LOW',
        'risk_flags': ['no_analysis'],
        'needs_review': True,
        'review_tier': 'unreviewed',
    }


def get_math_display(dp):
    """Return display-ready math fields based on math_type.

    Returns dict with 'label', 'detail', 'ev' — ready for rendering.
    Handles all math_types gracefully (never crashes on None fields).
    """
    if not dp:
        return {'label': '', 'detail': '', 'ev': None}

    mt = dp.get('math_type') or 'facing_bet'

    if mt == 'facing_bet':
        req = dp.get('required_equity')
        call = dp.get('hero_call_amount_bb')
        pot = dp.get('pot_facing_hero_bb')
        label = f"need {req*100:.0f}%" if req else ''
        detail = ''
        if call and pot:
            sizing = call / pot if pot else 0
            if sizing < 0.4:
                sz_lbl = 'small'
            elif sizing < 0.8:
                sz_lbl = '~half-pot'
            elif sizing < 1.2:
                sz_lbl = '~pot'
            else:
                sz_lbl = f'{sizing:.1f}x pot'
            detail = f"Call {call:.1f}BB into {pot:.1f}BB pot ({sz_lbl})"
        return {'label': label, 'detail': detail, 'ev': dp.get('ev_call_bb')}

    elif mt == 'hero_bet':
        fe = dp.get('fold_equity_required')
        risk = dp.get('risk_bb')
        reward = dp.get('reward_bb')
        label = f"need {fe*100:.0f}% folds" if fe else ''
        detail = ''
        if risk and reward:
            detail = f"Bet {risk:.1f}BB to win {reward:.1f}BB pot"
        return {'label': label, 'detail': detail, 'ev': dp.get('ev_bet_bb')}

    elif mt == 'hero_raise':
        return {
            'label': f"raise to {dp.get('hero_amount_bb', 0):.1f}BB",
            'detail': '',
            'ev': dp.get('ev_bet_bb'),
        }

    elif mt == 'hero_jam':
        eq = dp.get('equity_when_called')
        risk = dp.get('hero_risk_bb')
        label = f"eq if called: {eq*100:.0f}%" if eq else ''
        detail = f"Jam {risk:.1f}BB" if risk else ''
        return {'label': label, 'detail': detail, 'ev': dp.get('ev_jam_bb')}

    elif mt == 'check_or_bet':
        pref = dp.get('preferred_action', '?')
        ev_bet = dp.get('ev_bet_bb', 0) or 0
        ev_check = dp.get('ev_check_bb', 0) or 0
        label = pref
        detail = f"EV(bet)={ev_bet:+.1f} vs EV(check)={ev_check:+.1f}"
        return {'label': label, 'detail': detail,
                'ev': max(ev_bet, ev_check)}

    elif mt == 'fold_vs_bet':
        return {
            'label': 'fold',
            'detail': dp.get('threshold_explanation') or '',
            'ev': 0,
        }

    return {'label': '', 'detail': '', 'ev': None}


def parse_verdict(verdict_str):
    """Parse a verdict string into structured form.

    Batch 6 (5B): structured verdict parsing. Future code should route
    on verdict_class, not verdict.startswith().

    'III.2 Mistake' → {'class': 'III.2', 'label': 'Mistake', 'category': 'mistake'}
    'I.7 Cooler'    → {'class': 'I.7', 'label': 'Cooler', 'category': 'cooler'}
    'III.3 Cleared'  → {'class': 'III.3', 'label': 'Cleared', 'category': 'cleared'}
    ''               → {'class': '', 'label': '', 'category': 'pending'}
    """
    if not verdict_str:
        return {'class': '', 'label': '', 'category': 'pending'}
    v = verdict_str.strip()
    # Extract the class prefix (e.g., 'III.2', 'I.7')
    import re
    m = re.match(r'(I{1,3}\.\d+)\s*(.*)', v)
    if m:
        cls = m.group(1)
        label = m.group(2).strip()
        # Map to category
        _CAT_MAP = {
            'III.1': 'punt', 'III.2': 'mistake', 'III.3': 'cleared',
            'III.4': 'read_dependent', 'III.5': 'justified',
            'III.8': 'pick', 'I.7': 'cooler', 'III.0': 'cleared',
        }
        cat = _CAT_MAP.get(cls, 'other')
        return {'class': cls, 'label': label, 'category': cat}
    # Non-standard verdict
    vl = v.lower()
    if 'no leak' in vl or 'cleared' in vl:
        return {'class': '', 'label': v, 'category': 'cleared'}
    return {'class': '', 'label': v, 'category': 'other'}


def is_mistake(verdict_str):
    """Check if a verdict is a confirmed mistake (III.1 or III.2)."""
    pv = parse_verdict(verdict_str)
    return pv['category'] in ('punt', 'mistake')


def is_cleared(verdict_str):
    """Check if a verdict clears the hand (III.0, III.3, III.4, III.5, I.7, etc.)."""
    pv = parse_verdict(verdict_str)
    return pv['category'] in ('cleared', 'justified', 'cooler', 'read_dependent', 'pick')


def get_coaching_box(dp):
    """Return structured coaching box fields from a decision_point.

    Returns dict with fields for rendering the mistake box.
    Falls back gracefully when fields are None (Batch 1 won't have these).
    """
    if not dp:
        return {}
    return {
        'correct_action': dp.get('correct_action'),
        'correct_size_bb': dp.get('correct_size_bb'),
        'minimum_continue_hand': dp.get('minimum_continue_hand'),
        'threshold_explanation': dp.get('threshold_explanation'),
        'memory_rule': dp.get('memory_rule'),
        'exception': dp.get('exception'),
        'drill_bucket': dp.get('drill_bucket'),
    }
