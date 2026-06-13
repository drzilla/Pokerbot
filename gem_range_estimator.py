"""Range Estimator — estimate villain's range from position + action sequence.

This module provides HEURISTIC range estimates for non-showdown hands.
Used by the Auto-Coach Engine to compute approximate hero_equity_vs_range
when exact equity (from shown cards) is unavailable.

The estimates are POPULATION-LEVEL defaults, not solver-derived.
Every estimate carries a confidence flag ('low' / 'medium') and a
risk_flag 'unknown_villain_range'.

Batch 4 (R1 foundation): range estimation framework.
Full equity computation against estimated ranges is Batch 5+.
"""

# Population-level opening ranges by position (% of hands)
# These are approximate frequencies for low-mid stakes online MTTs.
OPEN_FREQ = {
    'UTG': 12, 'UTG+1': 14, 'MP': 16, 'HJ': 20,
    'CO': 28, 'BTN': 42, 'SB': 35, 'BB': 100,  # BB defends, not opens
}

# Population-level 3-bet ranges by position vs opener position (% of hands)
THREEBET_FREQ = {
    ('BB', 'BTN'): 10, ('BB', 'CO'): 8, ('BB', 'SB'): 12,
    ('SB', 'BTN'): 8, ('SB', 'CO'): 6,
    ('BTN', 'CO'): 7, ('BTN', 'HJ'): 5,
    ('CO', 'HJ'): 5, ('CO', 'MP'): 4,
}

# Population-level c-bet frequencies by board texture
CBET_FREQ = {
    'dry_ahigh': 70, 'dry_khigh': 65, 'dry_low': 55,
    'paired_board': 60, 'monotone': 35,
    'connected_mid': 30, 'connected_high': 40,
    'wet_draw_heavy': 40, 'unknown': 50,
}


def estimate_villain_range(villain_position, action_sequence, street='preflop',
                            board_texture=None, pot_type='SRP'):
    """Estimate villain's range width (as % of hands) from their action.

    Returns dict with:
      range_pct: estimated % of hands in villain's range
      description: human-readable range description
      confidence: 'low' or 'medium'
      risk_flags: list of risk flags
    """
    result = {
        'range_pct': 50.0,
        'description': 'unknown range',
        'confidence': 'low',
        'risk_flags': ['unknown_villain_range'],
    }

    vpos = villain_position or '?'

    # Preflop: estimate from position
    if street == 'preflop':
        if 'open' in action_sequence.lower() or 'raise' in action_sequence.lower():
            freq = OPEN_FREQ.get(vpos, 25)
            result['range_pct'] = freq
            result['description'] = f'{vpos} open (~{freq}% of hands)'
            result['confidence'] = 'medium' if vpos in OPEN_FREQ else 'low'
        elif '3bet' in action_sequence.lower() or '3-bet' in action_sequence.lower():
            result['range_pct'] = 8
            result['description'] = f'{vpos} 3-bet (~8% of hands)'
            result['confidence'] = 'low'
        elif '4bet' in action_sequence.lower():
            result['range_pct'] = 3
            result['description'] = f'{vpos} 4-bet (~3% of hands)'
            result['confidence'] = 'low'
        elif 'jam' in action_sequence.lower() or 'all-in' in action_sequence.lower():
            result['range_pct'] = 5
            result['description'] = f'{vpos} jam (~5% of hands)'
            result['confidence'] = 'low'

    # Postflop: narrow from preflop range + board texture
    else:
        base_pct = OPEN_FREQ.get(vpos, 25)
        tex = board_texture or 'unknown'

        if 'bet' in action_sequence.lower():
            # Villain bet — range narrows to ~60% of their preflop range
            narrowed = base_pct * 0.6
            result['range_pct'] = round(narrowed, 1)
            result['description'] = (f'{vpos} bet on {tex.replace("_", " ")} '
                                      f'(~{narrowed:.0f}% of starting hands)')
        elif 'raise' in action_sequence.lower():
            narrowed = base_pct * 0.3
            result['range_pct'] = round(narrowed, 1)
            result['description'] = f'{vpos} raise (~{narrowed:.0f}% — strong range)'
            result['confidence'] = 'low'
        elif 'check' in action_sequence.lower():
            result['range_pct'] = round(base_pct * 0.8, 1)
            result['description'] = f'{vpos} checked (~{base_pct * 0.8:.0f}% — capped range)'

    return result
