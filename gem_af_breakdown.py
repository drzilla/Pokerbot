#!/usr/bin/env python3
"""
gem_af_breakdown.py — v1.0 (Ron 2026-05-12)

Decompose session-level AF (Aggression Factor) into actionable slices:
  - by STREET (flop / turn / river)
  - by POSITION (IP / OOP)
  - by ROLE (PFR / Caller)
  - cross-tabulations (e.g., "river AF as PFR IP")

WHY:
  Session-aggregate AF=1.2 (vs typical 2.4) tells you SOMETHING is passive
  but doesn't tell you WHERE. The leak might be:
    - turn AF as PFR IP (cbet-then-check pattern)
    - river AF OOP (failed to value-bet/lead river when checked-to)
    - flop AF as caller IP (no float-raises)
  Each has a different drill prescription.

DEFINITION:
  AF = (bets + raises) / (calls)
  Computed across Hero's postflop actions only (preflop excluded).
  Folds are EXCLUDED from both numerator and denominator (industry-standard).

Public API:
    compute_af_breakdown(hands) -> {
        'session': {...},          # aggregate (matches stats['af'])
        'by_street': {flop, turn, river: {...}},
        'by_position': {ip, oop: {...}},
        'by_role': {pfr, caller: {...}},
        'cross': {street × pos × role grid},
        'flags': [list of below-target slices with explanations],
    }

Each slice has {bets, raises, calls, af, n, ci_low, ci_high, target_band,
status: 🟢|🟡|🔴|⚪}.
"""

from collections import defaultdict


# AF target bands by slice — based on mid-stakes MTT reg expectations.
# These are heuristic; refine with population data over time.
AF_TARGETS = {
    'session':       (1.8, 3.5),
    'flop':          (2.0, 4.0),
    'turn':          (1.5, 3.0),
    'river':         (1.0, 2.5),
    'ip':            (2.0, 4.0),
    'oop':           (1.2, 2.5),
    'pfr':           (2.5, 5.0),
    'caller':        (1.0, 2.5),
    'flop_ip_pfr':   (3.0, 6.0),   # cbet IP = aggressive baseline
    'flop_oop_pfr':  (2.0, 4.0),
    'flop_ip_caller': (1.5, 3.0),  # floats + raises
    'turn_ip_pfr':   (2.0, 4.0),
    'turn_oop_pfr':  (1.5, 3.0),
    'turn_ip_caller': (1.0, 2.5),
    'river_ip_pfr':  (1.5, 3.0),   # triple barrel territory
    'river_oop_pfr': (1.0, 2.5),
    'river_ip_caller': (0.8, 2.0),
}


def _verdict(af, n, target):
    """Return status emoji + label for an AF slice."""
    if n < 5:
        return '⚪', f'thin (n={n})'
    lo, hi = target
    if af < lo:
        gap = lo - af
        return '🟡', f'passive ({gap:.1f} below {lo})'
    if af > hi:
        gap = af - hi
        return '🟡', f'over-aggressive ({gap:.1f} above {hi})'
    return '🟢', 'in band'


def _af(bets, raises, calls):
    """Return AF or None if no calls (undefined)."""
    if calls == 0:
        return float('inf') if (bets + raises) > 0 else None
    return (bets + raises) / calls


def _slice_summary(slice_data, target_key):
    """Build the summary dict for one AF slice."""
    b = slice_data['bets']
    r = slice_data['raises']
    c = slice_data['calls']
    n = b + r + c
    af = _af(b, r, c)
    target = AF_TARGETS.get(target_key)
    if target is None:
        status, note = '⚪', 'no target'
    elif af is None:
        status, note = '⚪', 'no calls (denominator zero)'
    elif af == float('inf'):
        status, note = '⚪', 'no calls (all aggressive)'
    else:
        status, note = _verdict(af, n, target)
    return {
        'bets': b, 'raises': r, 'calls': c, 'n': n,
        'af': af if af not in (None, float('inf')) else None,
        'af_display': '∞' if af == float('inf') else (f'{af:.2f}' if af is not None else '—'),
        'target_band': f'{target[0]:.1f}-{target[1]:.1f}' if target else '—',
        'status': status, 'note': note,
    }


def compute_af_breakdown(hands):
    """Build full AF breakdown from session hands.

    Walks hero_action_flags per street (set by parser) to count
    bets/raises/calls/folds. Slices and cross-tabs derived from those.
    """
    # Containers: street × pos × role → {bets, raises, calls}
    def _zero(): return {'bets': 0, 'raises': 0, 'calls': 0}
    cells = defaultdict(_zero)

    for h in hands:
        if not isinstance(h, dict): continue
        if h.get('hero') != 'Hero': continue
        haf = h.get('hero_action_flags') or {}
        hero_ip = h.get('hero_ip', False)
        pfr = h.get('pfr', False) or h.get('hero_pfr', False)
        pos_label = 'ip' if hero_ip else 'oop'
        role_label = 'pfr' if pfr else 'caller'

        for street in ('flop', 'turn', 'river'):
            sa = haf.get(street, {}) or {}
            # Tally
            if sa.get('bet'):
                cells[(street, pos_label, role_label)]['bets'] += 1
                cells[('session', None, None)]['bets'] += 1
                cells[(street, None, None)]['bets'] += 1
                cells[(None, pos_label, None)]['bets'] += 1
                cells[(None, None, role_label)]['bets'] += 1
            if sa.get('raise'):
                cells[(street, pos_label, role_label)]['raises'] += 1
                cells[('session', None, None)]['raises'] += 1
                cells[(street, None, None)]['raises'] += 1
                cells[(None, pos_label, None)]['raises'] += 1
                cells[(None, None, role_label)]['raises'] += 1
            if sa.get('call'):
                cells[(street, pos_label, role_label)]['calls'] += 1
                cells[('session', None, None)]['calls'] += 1
                cells[(street, None, None)]['calls'] += 1
                cells[(None, pos_label, None)]['calls'] += 1
                cells[(None, None, role_label)]['calls'] += 1

    # Build output structure
    out = {}
    out['session'] = _slice_summary(cells[('session', None, None)], 'session')
    out['by_street'] = {
        st: _slice_summary(cells[(st, None, None)], st)
        for st in ('flop', 'turn', 'river')
    }
    out['by_position'] = {
        pos: _slice_summary(cells[(None, pos, None)], pos)
        for pos in ('ip', 'oop')
    }
    out['by_role'] = {
        role: _slice_summary(cells[(None, None, role)], role)
        for role in ('pfr', 'caller')
    }
    # Cross-tabs: street × pos × role
    cross = {}
    for st in ('flop', 'turn', 'river'):
        for pos in ('ip', 'oop'):
            for role in ('pfr', 'caller'):
                key = f'{st}_{pos}_{role}'
                cross[key] = _slice_summary(cells[(st, pos, role)], key)
    out['cross'] = cross

    # Generate flags: slices significantly below their target band
    flags = []
    # Session-level first
    s = out['session']
    if s['status'] == '🟡' and s['af'] is not None:
        flags.append(f"Session AF {s['af']:.2f} {s['note']} — target {s['target_band']}")
    # By street
    for st_name, st in out['by_street'].items():
        if st['status'] == '🟡' and st['af'] is not None and 'passive' in st['note']:
            flags.append(f"{st_name.upper()} AF {st['af']:.2f} {st['note']} (n={st['n']}) — target {st['target_band']}")
    # By position
    for pos_name, ps in out['by_position'].items():
        if ps['status'] == '🟡' and ps['af'] is not None and 'passive' in ps['note']:
            flags.append(f"{pos_name.upper()} AF {ps['af']:.2f} {ps['note']} (n={ps['n']}) — target {ps['target_band']}")
    # By role
    for role_name, rs in out['by_role'].items():
        if rs['status'] == '🟡' and rs['af'] is not None and 'passive' in rs['note']:
            flags.append(f"As {role_name.upper()}: AF {rs['af']:.2f} {rs['note']} (n={rs['n']}) — target {rs['target_band']}")
    # Cross — only flag the WORST-OFFENDING crosses (don't flood with every cell)
    cross_flags = []
    for key, slc in cross.items():
        if slc['status'] == '🟡' and slc['af'] is not None and 'passive' in slc['note'] and slc['n'] >= 5:
            cross_flags.append((key, slc))
    # Sort by gap-below-target descending (biggest leaks first)
    def _gap(slc):
        if slc['af'] is None: return 0
        lo = float(slc['target_band'].split('-')[0])
        return lo - slc['af']
    cross_flags.sort(key=lambda kv: -_gap(kv[1]))
    for key, slc in cross_flags[:5]:  # top 5 cross-slice leaks
        flags.append(f"  ↳ Cross-slice {key}: AF {slc['af']:.2f} {slc['note']} (n={slc['n']})")

    out['flags'] = flags
    return out


if __name__ == '__main__':
    import json, sys
    if len(sys.argv) < 2:
        print("Usage: python3 gem_af_breakdown.py <gem_hands.json>")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        hands = json.load(f)
    result = compute_af_breakdown(hands)
    print("\n=== SESSION AF ===")
    s = result['session']
    print(f"  {s['status']} {s['af_display']} | target {s['target_band']} | n={s['n']} | {s['note']}")
    print("\n=== BY STREET ===")
    for st, slc in result['by_street'].items():
        print(f"  {st:5s}: {slc['status']} AF {slc['af_display']:<6} | b={slc['bets']} r={slc['raises']} c={slc['calls']} | target {slc['target_band']} | {slc['note']}")
    print("\n=== BY POSITION ===")
    for pos, slc in result['by_position'].items():
        print(f"  {pos:5s}: {slc['status']} AF {slc['af_display']:<6} | b={slc['bets']} r={slc['raises']} c={slc['calls']} | target {slc['target_band']} | {slc['note']}")
    print("\n=== BY ROLE ===")
    for role, slc in result['by_role'].items():
        print(f"  {role:7s}: {slc['status']} AF {slc['af_display']:<6} | b={slc['bets']} r={slc['raises']} c={slc['calls']} | target {slc['target_band']} | {slc['note']}")
    print("\n=== CROSS (street × pos × role) ===")
    for key, slc in result['cross'].items():
        if slc['n'] >= 5:
            print(f"  {key:30s}: {slc['status']} AF {slc['af_display']:<6} | n={slc['n']:3d} | target {slc['target_band']} | {slc['note']}")
    print(f"\n=== FLAGS ({len(result['flags'])}) ===")
    for f in result['flags']:
        print(f"  {f}")
