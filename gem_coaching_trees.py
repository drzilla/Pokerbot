"""Leak Decision Trees — static correction rules per leak type.

For each promoted leak, provides a step-by-step decision tree that
the player can use at the table to avoid repeating the mistake.

Batch 5 (4B): static decision trees per leak category.
"""

LEAK_DECISION_TREES = {
    'Cold_Call_NB': {
        'title': 'Before calling a raise outside the blinds',
        'steps': [
            'Am I in the BB? → call can be okay (defend range)',
            'Is this a pocket pair with set-mining odds (15× IP / 20× OOP)? → call',
            'Is this a suited connector/broadway with implied odds AND position? → sometimes call',
            'Am I in the SB? → 3-bet or fold (almost never flat)',
            'Otherwise → fold or 3-bet',
        ],
        'memory_rule': 'Outside BB: 3-bet or fold. Flat only with specific reason.',
    },
    'VPIP_PFR_Gap_Raw': {
        'title': 'Reducing the VPIP-PFR gap',
        'steps': [
            'Am I calling when I should be 3-betting? → 3-bet more from blinds',
            'Am I flatting opens from SB? → almost always wrong, 3-bet or fold',
            'Am I cold-calling from MP/CO? → tighten range, 3-bet the top end',
            'Am I limping? → never limp (except SB BvB per J29)',
        ],
        'memory_rule': 'Every call should have a specific reason. Default = raise or fold.',
    },
    'AF': {
        'title': 'Increasing Aggression Factor',
        'steps': [
            'After check-calling flop, did I consider probing turn? → bet more turns',
            'After c-betting flop, did I barrel turn with equity? → barrel more',
            'On river, did I check back value hands? → bet thinner for value',
            'Am I check-calling rivers when I should be check-raising? → add CR to arsenal',
        ],
        'memory_rule': 'When in doubt, bet. Passive play compounds errors.',
    },
    'ATS_Raw': {
        'title': 'Opening more from steal positions',
        'steps': [
            'BTN first-in: open top 40-50% of hands',
            'CO first-in: open top 25-35% of hands',
            'SB first-in: raise or fold (no limp except BvB J29)',
            'Short stack (<15BB): push/fold chart takes over',
            'Deep (>40BB): add more suited connectors and small pairs',
        ],
        'memory_rule': 'Never fold BTN/CO first-in with any Ax, Kx suited, pocket pair.',
    },
    'ThreeBet_OOP': {
        'title': '3-betting more from OOP',
        'steps': [
            'BB vs BTN/SB: 3-bet 10-14% (premiums + suited bluffs)',
            'SB vs CO/BTN: 3-bet 8-12% (mostly for value, some bluffs)',
            'What hands to 3-bet bluff? Suited Ax (A2s-A5s), suited connectors',
            'If villain 4-bets often: tighten 3-bet bluffs, widen value',
        ],
        'memory_rule': 'SB/BB vs LP: 3-bet or fold. Flat only with big pairs occasionally.',
    },
    'CBet_3BP': {
        'title': 'C-betting in 3-bet pots',
        'steps': [
            'Board favors 3-bettor (A-high, K-high)? → c-bet 33-50% pot',
            'Board favors caller (middling connected)? → check more',
            'OOP in 3BP? → c-bet less (25-35% range, mostly for value)',
            'IP in 3BP? → c-bet more (40-50% range)',
            'Stack-to-pot ratio < 2? → often just jam or check-jam',
        ],
        'memory_rule': 'In 3BP: small c-bet on favorable boards, check unfavorable boards.',
    },
    'BB_Iso_SB_Limp': {
        'title': 'Isolating vs SB limp from BB',
        'steps': [
            'SB limps: raise to 3-4BB with top 50-60% of hands',
            'What to raise: any pair, any suited Ax, broadways, connectors 54s+',
            'What to check back: weak offsuit (72o, 83o, 94o)',
            'If SB limp-raises often: tighten iso range, value-heavy',
        ],
        'memory_rule': 'Punish the SB limp. Default = raise. Check only true trash.',
    },
}


def get_decision_tree(leak_code):
    """Return the decision tree for a leak code, or None."""
    return LEAK_DECISION_TREES.get(leak_code)


def get_tree_for_leak_name(leak_name):
    """Match a leak name to a decision tree by fuzzy keyword matching."""
    n = leak_name.lower()
    if 'cold' in n and 'call' in n:
        return LEAK_DECISION_TREES.get('Cold_Call_NB')
    if 'vpip' in n and 'pfr' in n and 'gap' in n:
        return LEAK_DECISION_TREES.get('VPIP_PFR_Gap_Raw')
    if 'aggression' in n and 'factor' in n or n == 'af':
        return LEAK_DECISION_TREES.get('AF')
    if 'ats' in n or 'attempt to steal' in n or 'steal' in n:
        return LEAK_DECISION_TREES.get('ATS_Raw')
    if '3-bet' in n and 'oop' in n or '3bet' in n and 'oop' in n:
        return LEAK_DECISION_TREES.get('ThreeBet_OOP')
    if 'cbet' in n and '3b' in n or 'c-bet' in n and '3b' in n:
        return LEAK_DECISION_TREES.get('CBet_3BP')
    if 'iso' in n and ('sb' in n or 'limp' in n):
        return LEAK_DECISION_TREES.get('BB_Iso_SB_Limp')
    return None
