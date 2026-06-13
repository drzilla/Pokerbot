"""
gem_textures.py — GTO texture archetype classifier and target lookup.

Single source of truth: gto_texture_archetypes.json
Maps Dave's 16-archetype taxonomy onto the existing parser board_texture buckets.

Public API:
    classify_archetype(board_cards) -> archetype_id (str) or 'unknown'
    get_gto_target(archetype_id, side, eff_stack_bb) -> target dict or None
    archetype_meta(archetype_id) -> full archetype record from JSON
    all_archetypes() -> list of archetype records (for drills/report)
    compute_compliance(hand_cbet_pct, hand_sizing_pct, target) -> dict

Classification priority (most specific first):
    tripleton > monotone > paired_coordinated > paired_dry
    > ace_high_coordinated > ace_high_dry
    > broadway_coordinated > broadway_two_tone
    > high_low_low_two_tone > high_mid_low_two_tone
    > broadway_disconnected
    > middling_connected > middling_disconnected
    > low_two_tone > low_connected > low_ragged
    > unknown

Side: 'ip' or 'oop'.
eff_stack_bb: numeric effective stack in big blinds.

Returns None when:
    - archetype id is unknown
    - target scenarios list is empty (TODO archetype)
    - depth band has no entry covering eff_stack_bb
"""

import json
import os
from pathlib import Path

RANK_VAL = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
    'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14
}

# ----------------------------------------------------------------------
# DATA LOADING
# ----------------------------------------------------------------------

_DATA = None
_BY_ID = None

def _candidate_paths():
    """Where the JSON might live, in order of preference."""
    here = Path(__file__).parent
    return [
        Path('/mnt/project/gto_texture_archetypes.json'),
        here / 'gto_texture_archetypes.json',
        Path.cwd() / 'gto_texture_archetypes.json',
        Path('/home/claude/gto_texture_archetypes.json'),
    ]

def load_data(path=None):
    """Load and cache archetype data. Pass path to override."""
    global _DATA, _BY_ID
    if path is None:
        for p in _candidate_paths():
            if p.exists():
                path = p
                break
    if path is None or not Path(path).exists():
        raise FileNotFoundError(
            "gto_texture_archetypes.json not found in: " +
            ", ".join(str(p) for p in _candidate_paths())
        )
    with open(path) as f:
        _DATA = json.load(f)
    _BY_ID = {a['id']: a for a in _DATA['archetypes']}
    return _DATA

def _ensure_loaded():
    if _DATA is None:
        load_data()

# ----------------------------------------------------------------------
# BOARD ANALYSIS HELPERS
# ----------------------------------------------------------------------

def _flop_features(board_cards):
    """Extract structural features used by the classifier."""
    if not board_cards or len(board_cards) < 3:
        return None
    flop = board_cards[:3]
    try:
        ranks = [RANK_VAL[c[0]] for c in flop]
        suits = [c[1] for c in flop]
    except (KeyError, IndexError):
        return None
    sr = sorted(ranks, reverse=True)  # high to low
    return {
        'ranks': sr,                      # [hi, mid, lo]
        'suits': suits,
        'unique_ranks': len(set(ranks)),
        'unique_suits': len(set(suits)),
        'top': sr[0],
        'mid': sr[1],
        'lo': sr[2],
        'span': sr[0] - sr[2],
        'gap_hi_mid': sr[0] - sr[1],
        'gap_mid_lo': sr[1] - sr[2],
        'broadway_count': sum(1 for r in sr if r >= 10),  # T-A
        'has_ace': sr[0] == 14,
        'is_paired': len(set(ranks)) < 3,
        'is_tripleton': len(set(ranks)) == 1,
        'is_monotone': len(set(suits)) == 1,
        'is_two_tone': len(set(suits)) == 2,
        'is_rainbow': len(set(suits)) == 3,
    }

def _is_connected(f):
    """Connected = max gap ≤ 2 AND span ≤ 4. Used for unpaired boards."""
    return f['span'] <= 4 and max(f['gap_hi_mid'], f['gap_mid_lo']) <= 2

def _is_ace_high_coordinated(f):
    """A-high + at least one of: 2-tone/monotone, broadway in middle, connected pair below A."""
    if not f['has_ace']:
        return False
    if f['unique_suits'] <= 2:  # 2-tone or monotone
        return True
    if f['mid'] >= 10:  # broadway in middle (e.g., A-J-9, A-Q-x)
        return True
    if f['gap_mid_lo'] <= 2 and f['mid'] <= 10:  # connected lower pair (A-7-6)
        return True
    return False

def _is_broadway_coordinated(f):
    """3 broadways OR 2 broadways with connectivity. Rainbow/multi-tone.

    NOTE: 3-broadway 2-tone (like KQJ two-tone) routes to broadway_two_tone,
    not here. See classify_archetype priority.
    """
    if f['has_ace']:
        return False  # ace-high gets its own archetype
    if f['broadway_count'] >= 3:
        return True
    if f['broadway_count'] == 2 and f['top'] >= 11 and f['gap_hi_mid'] <= 2:
        # K-Q-x or Q-J-x where x is connected (K-Q-T, Q-J-9 etc.)
        if f['gap_mid_lo'] <= 3:
            return True
    return False


def _is_broadway_two_tone(f):
    """3 broadways AND 2-tone (e.g. KQJ-2t, KQT-2t, QJT-2t).

    Distinct from broadway_coordinated (which is rainbow) because the
    2-tone version is more dynamic (FD threats) and Dave's strategy is
    different (B66 IP vs B33/B66 rainbow, B25 OOP vs B33/B66 rainbow).
    """
    if f['has_ace']:
        return False
    if not f['is_two_tone']:
        return False
    return f['broadway_count'] >= 3


def _is_high_low_low_two_tone(f):
    """K- or Q-high + two low cards (≤6) + two-tone. Example: K-6-2-2t, K-7-3-2t.

    The 'high-low-low' pattern: one broadway top, big gap to middle, both
    non-top cards are low. Two-tone makes this distinct from broadway_disconnected
    (which is mostly rainbow K-Q-4 / K-7-4 patterns).
    """
    if f['has_ace']:
        return False
    if not f['is_two_tone']:
        return False
    if f['top'] not in (12, 13):  # K or Q top
        return False
    if f['broadway_count'] != 1:  # exactly one broadway (the top)
        return False
    if f['mid'] > 7:  # mid must be low — not a 'mid' card
        return False
    return True


def _is_high_mid_low_two_tone(f):
    """K- or Q-high + middle card (7-T) + low card + two-tone. Example: K-8-3-2t, Q-9-4-2t.

    The 'high-mid-low' pattern with a middle card between the broadway top
    and a low card. Two-tone. Dave's K-8-3 archetype.
    """
    if f['has_ace']:
        return False
    if not f['is_two_tone']:
        return False
    if f['top'] not in (12, 13):  # K or Q top
        return False
    if f['broadway_count'] != 1:
        return False
    # Mid is a non-broadway middle card (7, 8, 9, T but T would make broadway_count=2)
    if f['mid'] < 7 or f['mid'] > 10:
        return False
    return True


def _is_low_two_tone(f):
    """Low board (top ≤ 8) + two-tone. Examples: 5-3-2-2t, 6-4-2-2t, 7-5-3-2t.

    Sibling of low_ragged/low_connected but with FD potential. Dave treats
    this distinctly because of equity-shift potential. More connected than
    low_ragged but two-tone makes it more dynamic.
    """
    if f['has_ace']:
        return False
    if f['top'] > 8:
        return False
    if not f['is_two_tone']:
        return False
    return True


def _is_broadway_disconnected(f):
    """K- or Q-high disconnected boards (rainbow or otherwise).

    Catches K-Q-4 / K-7-4 / Q-3-2 patterns. Strategy pattern is range adv
    to PFR, polarized — bluffs/strong-made big, medium small. Top card is
    K or Q to qualify; J-high would fall to middling.

    Priority note: in v1.2, the two-tone variants (high_low_low_two_tone,
    high_mid_low_two_tone, broadway_two_tone) are checked FIRST in
    classify_archetype, so this predicate sees only the rainbow/non-two-tone
    fallthrough cases.
    """
    if f['has_ace']:
        return False
    if f['top'] not in (12, 13):  # Q or K only
        return False
    # Already-handled cases (broadway_coordinated rainbow)
    if f['broadway_count'] >= 3:
        return False
    if f['broadway_count'] == 2 and f['gap_hi_mid'] <= 2 and f['gap_mid_lo'] <= 3:
        return False  # would be broadway_coordinated
    return True


# ----------------------------------------------------------------------
# CLASSIFIER
# ----------------------------------------------------------------------

def classify_archetype(board_cards):
    """Map a flop to one of 16 GTO archetypes. Returns archetype_id."""
    f = _flop_features(board_cards)
    if f is None:
        return 'unknown'

    # Most specific → most general (v1.2)
    if f['is_tripleton']:
        return 'tripleton'
    if f['is_monotone']:
        return 'monotone'

    if f['is_paired']:
        # Paired Coordinated: paired + 2-tone OR pair-card adjacent to kicker
        # Paired Dry: paired + rainbow + disconnected
        pair_rank = max(set(f['ranks']), key=f['ranks'].count) if f['ranks'].count(f['ranks'][0]) >= 2 else None
        kicker = [r for r in f['ranks'] if f['ranks'].count(r) == 1]
        kicker_rank = kicker[0] if kicker else None
        kicker_pair_gap = abs(pair_rank - kicker_rank) if (pair_rank is not None and kicker_rank is not None) else 99
        if f['is_rainbow'] and kicker_pair_gap >= 4:
            return 'paired_dry'
        return 'paired_coordinated'

    # Unpaired from here
    if f['has_ace']:
        if _is_ace_high_coordinated(f):
            return 'ace_high_coordinated'
        return 'ace_high_dry'

    # No ace, unpaired
    # v1.2: split off two-tone broadway sub-archetypes BEFORE the generic
    # broadway_coordinated/broadway_disconnected catches them
    if _is_broadway_two_tone(f):
        return 'broadway_two_tone'
    if _is_high_low_low_two_tone(f):
        return 'high_low_low_two_tone'
    if _is_high_mid_low_two_tone(f):
        return 'high_mid_low_two_tone'

    if _is_broadway_coordinated(f):
        return 'broadway_coordinated'

    if _is_broadway_disconnected(f):
        return 'broadway_disconnected'

    # Top card determines middling vs low
    if f['top'] in (9, 10, 11):  # 9, T, J
        if _is_connected(f):
            return 'middling_connected'
        return 'middling_disconnected'

    # v1.2: low boards now check two-tone before falling to connected/ragged.
    # low_two_tone catches 5-3-2-2t / 6-4-2-2t style boards which have
    # backdoor straight + FD potential that low_ragged doesn't.
    if f['top'] <= 8:
        if _is_low_two_tone(f):
            return 'low_two_tone'
        if _is_connected(f):
            return 'low_connected'
        return 'low_ragged'

    return 'unknown'

# ----------------------------------------------------------------------
# TARGET LOOKUP
# ----------------------------------------------------------------------

def archetype_meta(archetype_id):
    """Return the full archetype record from JSON, or None."""
    _ensure_loaded()
    return _BY_ID.get(archetype_id)

def all_archetypes():
    """Return all archetype records (for drills, reports)."""
    _ensure_loaded()
    return list(_DATA['archetypes'])

def get_gto_target(archetype_id, side, eff_stack_bb):
    """
    Look up the GTO scenario for this archetype/side/depth.

    Returns dict with keys: freq_pct (list[low,high] or None), sizings_pct (list[int]),
    dual_strategy (bool), notes (str), depth_band (str). Returns None when no
    applicable scenario exists (TODO archetype, missing side, depth out of range).
    """
    meta = archetype_meta(archetype_id)
    if meta is None:
        return None
    side_key = f'{side.lower()}_cbet'
    if side_key not in meta:
        return None
    scenarios = meta[side_key].get('scenarios', [])
    if not scenarios:
        return None
    for sc in scenarios:
        lo = sc.get('depth_min_bb', 0)
        hi = sc.get('depth_max_bb', 999)
        if lo <= eff_stack_bb <= hi:
            return {
                'freq_pct': sc.get('freq_pct'),
                'sizings_pct': sc.get('sizings_pct', []),
                'dual_strategy': sc.get('dual_strategy', False),
                'notes': sc.get('notes', ''),
                'depth_band': f"{lo}-{hi}BB",
                'archetype_id': archetype_id,
                'side': side.lower(),
                'eff_stack_bb': eff_stack_bb,
            }
    return None

# ----------------------------------------------------------------------
# COMPLIANCE / DEVIATION COMPUTATION
# ----------------------------------------------------------------------

def sizing_within_target(actual_pct, target_sizings, tolerance_pct=10):
    """
    Is actual sizing within tolerance of any target sizing?
    tolerance_pct is absolute percentage points (e.g. tolerance 10 means
    if target is 50, actual 40-60 passes).
    """
    if not target_sizings:
        return None  # no target → can't judge
    if actual_pct is None:
        return None
    return any(abs(actual_pct - t) <= tolerance_pct for t in target_sizings)

def freq_within_target(actual_freq_pct, target_freq_pct):
    """
    Is actual c-bet frequency within the target [low, high] range?
    target_freq_pct is [low, high] inclusive, or None (no freq constraint).
    Returns None if can't judge, True/False otherwise.
    """
    if target_freq_pct is None or actual_freq_pct is None:
        return None
    lo, hi = target_freq_pct[0], target_freq_pct[1]
    return lo <= actual_freq_pct <= hi

def compliance_label(within):
    """Map compliance bool/None to a status string for reports."""
    if within is None:
        return 'unjudged'
    return 'compliant' if within else 'deviation'

# ----------------------------------------------------------------------
# AGGREGATION (for analyzer)
# ----------------------------------------------------------------------

def aggregate_compliance(hands, get_archetype_fn=None, get_side_fn=None,
                         get_depth_fn=None, get_did_cbet_fn=None,
                         get_sizing_fn=None):
    """
    Compute per-archetype compliance findings from a list of hand dicts.

    Default extractors expect hand dict with keys:
        'board_archetype' (set by parser, see classify_archetype)
        'cbet_side' ('ip' or 'oop' on the flop as PFR)
        'eff_stack_bb_flop' or fallback 'eff_stack_bb'
        'cbet_flop' (bool — did Hero c-bet the flop)
        'cbet_sizing_pct' (numeric % of pot, or None if checked)

    Returns dict keyed by archetype_id with sub-keys per side:
        {
          'ace_high_dry': {
            'ip': {
              'n_opps': 12, 'n_cbet': 11, 'cbet_pct': 91.7,
              'target_freq_pct': [95,100], 'freq_compliant': False,
              'sizing_hands': [{id, sizing_pct, within}],
              'sizing_compliance_pct': 75.0,
              'depth_bands_seen': ['40-999BB'],
              'verdict': 'deviation' | 'compliant' | 'unjudged',
              'sample_size_label': 'sufficient' | 'thin' | 'small'
            },
            'oop': {...}
          }, ...
        }
    """
    get_archetype_fn = get_archetype_fn or (lambda h: h.get('board_archetype'))
    get_side_fn = get_side_fn or (lambda h: h.get('cbet_side'))
    get_depth_fn = get_depth_fn or (
        lambda h: h.get('eff_stack_bb_flop') or h.get('eff_stack_bb') or 100
    )
    get_did_cbet_fn = get_did_cbet_fn or (lambda h: bool(h.get('cbet_flop')))
    get_sizing_fn = get_sizing_fn or (lambda h: h.get('cbet_sizing_pct'))

    out = {}
    for h in hands:
        arch = get_archetype_fn(h)
        side = get_side_fn(h)
        if not arch or not side or arch == 'unknown':
            continue
        depth = get_depth_fn(h)
        if depth is None:
            continue
        target = get_gto_target(arch, side, depth)
        bucket = out.setdefault(arch, {}).setdefault(side, {
            'n_opps': 0, 'n_cbet': 0,
            'sizing_hands': [],
            'depth_bands_seen': set(),
            'target_seen': None,
            'unjudged_no_target': 0,
            # FEAT-3: collect hand IDs for clickable texture rows
            'cbet_hand_ids': [],      # hands that DID c-bet
            'missed_hand_ids': [],    # hands that did NOT c-bet
        })
        bucket['n_opps'] += 1
        did_cbet = get_did_cbet_fn(h)
        _hid = h.get('id')
        if did_cbet:
            bucket['n_cbet'] += 1
            if _hid:
                bucket['cbet_hand_ids'].append(_hid)
            sizing = get_sizing_fn(h)
            if sizing is not None and target is not None:
                within = sizing_within_target(sizing, target['sizings_pct'])
                bucket['sizing_hands'].append({
                    'id': h.get('id'),
                    'sizing_pct': sizing,
                    'within': within,
                    'depth_band': target['depth_band'],
                })
        else:
            if _hid:
                bucket['missed_hand_ids'].append(_hid)
        if target is not None:
            bucket['depth_bands_seen'].add(target['depth_band'])
            bucket['target_seen'] = target  # last one wins; OK for single-band cases
        else:
            bucket['unjudged_no_target'] += 1

    # Finalize aggregates
    for arch, sides in out.items():
        for side, b in sides.items():
            n_opps = b['n_opps']
            n_cbet = b['n_cbet']
            cbet_pct = (100.0 * n_cbet / n_opps) if n_opps else 0.0
            b['cbet_pct'] = round(cbet_pct, 1)
            b['depth_bands_seen'] = sorted(b['depth_bands_seen'])

            target = b.get('target_seen')
            target_freq = target['freq_pct'] if target else None
            b['target_freq_pct'] = target_freq

            freq_ok = freq_within_target(cbet_pct, target_freq) if target_freq else None
            b['freq_compliant'] = freq_ok

            sizing_judged = [s for s in b['sizing_hands'] if s['within'] is not None]
            sizing_ok = [s for s in sizing_judged if s['within']]
            b['sizing_judged_n'] = len(sizing_judged)
            b['sizing_compliant_n'] = len(sizing_ok)
            b['sizing_compliance_pct'] = (
                round(100.0 * len(sizing_ok) / len(sizing_judged), 1)
                if sizing_judged else None
            )

            # Sample-size label
            if n_opps < 3:
                b['sample_size_label'] = 'small'
            elif n_opps < 8:
                b['sample_size_label'] = 'thin'
            else:
                b['sample_size_label'] = 'sufficient'

            # Verdict
            if target_freq is None and b['sizing_compliance_pct'] is None:
                b['verdict'] = 'unjudged'
            else:
                deviated = (
                    (freq_ok is False) or
                    (b['sizing_compliance_pct'] is not None and b['sizing_compliance_pct'] < 60)
                )
                b['verdict'] = 'deviation' if deviated else 'compliant'

    return out

# ----------------------------------------------------------------------
# CLI / smoke test
# ----------------------------------------------------------------------

if __name__ == '__main__':
    load_data()
    print(f"Loaded {len(_DATA['archetypes'])} archetypes from "
          f"{_DATA['source']}")
    examples = [
        (['Ah','7s','2c'], 'ace_high_dry'),
        (['Ah','Js','9d'], 'ace_high_coordinated'),
        (['Kh','Qd','4c'], 'broadway_disconnected'),
        (['Qh','Jd','Ts'], 'broadway_coordinated'),
        (['9h','8d','7s'], 'middling_connected'),
        (['9h','5d','2c'], 'middling_disconnected'),
        (['6h','5d','4s'], 'low_connected'),
        (['7h','3d','2c'], 'low_ragged'),
        (['Jh','6h','2h'], 'monotone'),
        (['8h','8d','3s'], 'paired_dry'),
        (['9h','9d','8h'], 'paired_coordinated'),
        (['5h','5d','5s'], 'tripleton'),
    ]
    print("\nSmoke test:")
    fail = 0
    for board, expected in examples:
        got = classify_archetype(board)
        # ace_high_dry has Ah-7s-2c so first card needs to be Ah; fix
        ok = '✓' if got == expected else '✗'
        if got != expected:
            fail += 1
        print(f"  {ok} {' '.join(board):12} -> {got:25} (expected {expected})")
    if fail:
        print(f"\n{fail} mismatches")
    else:
        print("\nAll classified.")
