#!/usr/bin/env python3
"""
gem_villain_intel.py — Opponent Intelligence data contract and alias engine.

PR 1: Identity + alias + data contract.
- 108 neutral villain aliases (deterministic stable_hash assignment)
- Villain key: tournament_id|player_hash (per-player, not per-seat)
- Full data contract for evidence atoms, line stories, read states,
  exploit opportunities, and queue context metadata
- build_villain_intel() orchestrator that assigns aliases and returns
  the intel container with empty/default fields for future PRs

Public API:
    build_villain_intel(hands, hero_name, profiles) -> dict
    stable_alias(villain_key) -> str
"""
import hashlib
from collections import defaultdict


# ============================================================
# NAME POOL — 108 neutral, short, memorable names (spec §4)
# ============================================================

NAME_POOL = [
    'Ace', 'Anchor', 'Anvil', 'Archer', 'Atlas', 'Axel',
    'Badger', 'Bandit', 'Beacon', 'Benny', 'Bishop', 'Blade',
    'Blizzard', 'Bolt', 'Bravo', 'Brick', 'Bruno', 'Bull',
    'Cactus', 'Captain', 'Chase', 'Cipher', 'Cobra', 'Comet',
    'Copper', 'Coyote', 'Crow', 'Dash', 'Delta', 'Dex',
    'Diesel', 'Doctor', 'Domino', 'Dragon', 'Duke', 'Echo',
    'Falcon', 'Fang', 'Finn', 'Flint', 'Fox', 'Frost',
    'Ghost', 'Glitch', 'Golem', 'Gravel', 'Hammer', 'Hawk',
    'Hunter', 'Iceman', 'Jax', 'Joker', 'Judge', 'Kai',
    'Knight', 'Kraken', 'Laser', 'Leo', 'Lightning', 'Lucky',
    'Maverick', 'Merlin', 'Meteor', 'Milo', 'Moose', 'Mustang',
    'Nomad',
    'Nova', 'Onyx', 'Oracle', 'Ozzy', 'Panther', 'Phantom',
    'Pilot', 'Pixel', 'Professor', 'Radar', 'Ranger', 'Raven',
    'Recon', 'Rex', 'Rocket', 'Rocco', 'Rogue', 'Scout',
    'Shadow', 'Sheriff', 'Shield', 'Sonic', 'Spark', 'Specter',
    'Spike', 'Storm', 'Striker', 'Tank', 'Theo', 'Tiger',
    'Titan', 'Torch', 'Tracker', 'Turbo', 'Viper', 'Vortex',
    'Warden', 'Wizard', 'Wolf', 'Zane', 'Zephyr',
]

# Overflow pool for collision resolution (spec §4 optional names)
_OVERFLOW_POOL = [
    'Arrow', 'Boulder', 'Canyon', 'Cloud', 'Compass', 'Cougar',
    'Cricket', 'Cyclone', 'Druid', 'Eagle', 'Ember', 'Gator',
    'Glacier', 'Griffin', 'Hydra', 'Iggy', 'Jaguar', 'Lancer',
    'Mage', 'Magnet', 'Mantis', 'Mirror', 'Needle', 'Ogre',
    'Orbit', 'Phoenix', 'Piston', 'Python', 'Quinn', 'Raccoon',
    'Rhino', 'Rico', 'Sailor', 'Scorpion', 'Smoke', 'Sniper',
    'Sphinx', 'Switch', 'Tango', 'Thunder', 'Toby', 'Tornado',
    'Trader', 'Turbine', 'Valkyrie', 'Walt', 'Warlock', 'Wave',
    'Wrench', 'Wyvern',
]


# ============================================================
# BADGE TAXONOMY (spec §5)
# ============================================================

# Card rank ordering for standard poker notation (high card first)
_RANK_VAL = {r: i for i, r in enumerate('23456789TJQKA')}

BADGES = {
    'note':  {'emoji': '❗', 'label': 'Note',  'description': 'Villain did something worth noticing'},
    'pivot': {'emoji': '⚠',  'label': 'Pivot', 'description': 'Line changed — affects strategy now'},
    'miss':  {'emoji': '❌', 'label': 'Miss',  'description': 'Hero failed to adjust to read'},
    'good':  {'emoji': '✅', 'label': 'Good',  'description': 'Hero adjusted correctly'},
}


# ============================================================
# STABLE ALIAS ASSIGNMENT
# ============================================================

def _stable_hash(key):
    """Deterministic integer hash from villain key string.

    Uses MD5 for cross-platform stability (not for security).
    Same key → same integer every time, on every machine.
    """
    return int(hashlib.md5(key.encode('utf-8')).hexdigest(), 16)


def stable_alias(villain_key):
    """Return a neutral alias for this villain key.

    Deterministic: same villain_key always returns the same name.
    Does NOT handle collisions — call assign_aliases() for that.
    """
    idx = _stable_hash(villain_key) % len(NAME_POOL)
    return NAME_POOL[idx]


# ============================================================
# VILLAIN KEY BUILDER
# ============================================================

def build_villain_keys(hands):
    """Scan all hands and build the villain_key → metadata mapping.

    Args:
        hands: list of parsed hand dicts

    Returns:
        dict keyed by villain_key (tournament_id|player_hash):
        {
            'player_hash': str,        # raw GG hash (e.g., '3dcb37e4')
            'tournament_id': str,      # numeric tournament ID
            'positions_seen': set,     # {BTN, SB, BB, ...}
            'hand_ids': list,          # hand IDs where this villain appeared
            'n_hands': int,
        }
    """
    vkeys = {}
    for h in hands:
        tid = h.get('tournament_id') or ''
        if not tid:
            continue
        for vname, vinfo in (h.get('villains') or {}).items():
            vkey = f"{tid}|{vname}"
            if vkey not in vkeys:
                vkeys[vkey] = {
                    'player_hash': vname,
                    'tournament_id': tid,
                    'positions_seen': set(),
                    'hand_ids': [],
                    'n_hands': 0,
                }
            vkeys[vkey]['positions_seen'].add(vinfo.get('position', '?'))
            vkeys[vkey]['hand_ids'].append(h.get('id', ''))
            vkeys[vkey]['n_hands'] += 1
    return vkeys


def assign_aliases(villain_keys_meta):
    """Assign stable aliases and V-numbers to all villain keys.

    V-numbers are assigned in descending order of hand volume:
    V01 = most frequently seen villain, V02 = next, etc.

    Handles alias collisions: if two villain_keys hash to the same
    NAME_POOL entry, the second gets an overflow name.

    Args:
        villain_keys_meta: dict from build_villain_keys()

    Returns:
        dict keyed by villain_key:
        {
            'alias': str,              # 'Ghost'
            'v_number': str,           # 'V01'
            'display': str,            # 'Ghost · V01'
            'villain_key': str,        # '288240360|3dcb37e4'
            'player_hash': str,
            'tournament_id': str,
            'n_hands': int,
            'positions_seen': list,
        }
    """
    # Sort by hand count descending for V-number assignment
    sorted_keys = sorted(
        villain_keys_meta.items(),
        key=lambda kv: -kv[1]['n_hands']
    )

    used_aliases = set()
    overflow_idx = 0
    result = {}

    for v_idx, (vkey, meta) in enumerate(sorted_keys, start=1):
        # Try primary alias from stable hash
        alias = stable_alias(vkey)

        if alias in used_aliases:
            # Collision: try offset variants in NAME_POOL first
            base_hash = _stable_hash(vkey)
            resolved = False
            for offset in range(1, len(NAME_POOL)):
                candidate = NAME_POOL[(base_hash + offset) % len(NAME_POOL)]
                if candidate not in used_aliases:
                    alias = candidate
                    resolved = True
                    break

            if not resolved:
                # Exhaust overflow pool
                while overflow_idx < len(_OVERFLOW_POOL):
                    candidate = _OVERFLOW_POOL[overflow_idx]
                    overflow_idx += 1
                    if candidate not in used_aliases:
                        alias = candidate
                        resolved = True
                        break
                if not resolved:
                    # Last resort: alias + V-number
                    alias = f"V{v_idx:02d}"

        used_aliases.add(alias)
        v_number = f"V{v_idx:02d}"

        result[vkey] = {
            'alias': alias,
            'v_number': v_number,
            'display': alias if alias == v_number else f"{alias} · {v_number}",
            'villain_key': vkey,
            'player_hash': meta['player_hash'],
            'tournament_id': meta['tournament_id'],
            'n_hands': meta['n_hands'],
            'positions_seen': sorted(meta['positions_seen']),
        }

    return result


# ============================================================
# DATA CONTRACT — empty/default structures for future PRs
# ============================================================

def _empty_evidence_atom():
    """Template for an evidence atom (spec §13.1).

    Fields:
        type: always 'evidence_atom'
        hand_id: hand where this evidence occurred
        tournament_id: tournament context
        villain_key: tournament_id|player_hash
        villain_alias: display alias (e.g., 'Ghost · V49')
        street: preflop/flop/turn/river
        action_index: chronological position in hand's action_ledger
        signal: detector code (e.g., 'limp_call', 'weak_showdown_call')
        label: display label ('❗ Note', '⚠ Pivot', '❌ Miss', '✅ Good')
        badge: code ('note', 'pivot', 'miss', 'good')
        dimension: behavioral dimension impacted (e.g., 'loose_passive')
        strength: signal weight 1-5
        same_hand_actionable: can influence later Hero decisions this hand
        available_before_action_index: action_index up to which this was known
        hero_involved: Hero was in hand at this street
        evidence_text: human-readable description
        read_impact: dimensional impact string (e.g., 'Sticky +3')
    """
    return {
        'type': 'evidence_atom',
        'hand_id': '',
        'tournament_id': '',
        'villain_key': '',
        'villain_alias': '',
        'street': '',
        'action_index': 0,
        'signal': '',
        'label': '',
        'badge': '',
        'dimension': '',
        'strength': 0,
        'same_hand_actionable': False,
        'available_before_action_index': None,
        'hero_involved': False,
        'evidence_text': '',
        'read_impact': '',
    }


def _empty_line_story():
    """Template for a line story (spec §13.2).

    Aggregates multiple evidence atoms from the same hand into a
    multi-street narrative with interpretation and adjustment advice.
    """
    return {
        'type': 'line_story',
        'hand_id': '',
        'villain_key': '',
        'label': '',
        'badge': '',
        'sequence': [],
        'interpretation': '',
        'recommended_adjustment': '',
        'confidence': 'low',
    }


def _empty_read_state():
    """Template for a villain read state (spec §13.3).

    Accumulated across all evidence hands for one villain.
    """
    return {
        'villain_key': '',
        'villain_alias': '',
        'primary_read': '',
        'confidence': 'low',
        'dimensions': {
            'loose': 0, 'passive': 0, 'sticky': 0,
            'aggressive': 0, 'competence': 0,
        },
        'exceptions': [],
        'evidence_hand_ids': [],
        'n_evidence': 0,
        'n_hero_involved': 0,
        'n_showdowns': 0,
    }


def _empty_exploit_opportunity():
    """Template for an exploit opportunity (spec §13.4).

    Represents a Hero decision point where villain read should
    have influenced the action.
    """
    return {
        'type': 'exploit_opportunity',
        'hand_id': '',
        'villain_key': '',
        'villain_read_before_decision': '',
        'hero_decision_street': '',
        'hero_action': '',
        'recommended_exploit': '',
        'auto_verdict': '',
        'label': '',
        'badge': '',
        'severity': 'C',
        'read_confidence': 'low',
        'exploit_confidence': 'low',
        'needs_llm_review': False,
        # v8.8.3: exploit read semantics — stamp at detection time
        'exploit_detector': '',
        'exploit_type': '',
        'exploit_outcome': '',
        'read_source': '',
        'exploit_read_label': '',
    }


def _empty_queue_context():
    """Template for queue context metadata (spec §9).

    Hooks for future queue navigation UI. Defined now so the
    data model supports it from the start.
    """
    return {
        'source_type': '',       # 'villain_evidence' | 'issue' | 'opponent_adjustment'
        'source_label': '',
        'hand_ids': [],
        'current_index': 0,
        'back_target': '',
    }


# ============================================================
# PR3: MVP EVIDENCE DETECTORS (spec §14.1, first 5)
# ============================================================

_BLIND_POSITIONS = {'SB', 'BB'}

_SIGNAL_LABELS = {
    'open_limp': 'Open Limp',
    'limp_call': 'Limp-Call',
    'weak_showdown_call': 'Weak Showdown Call',
    'passive_aggro_pivot': 'Passive → Aggro Pivot',
    'repeated_blind_overfold': 'Repeated Blind Overfold',
    'multiway_donk': 'Multiway Donk',
    'weird_minbet': 'Weird Min-Bet',
    'cold_call_3bet_oop': 'Cold-Call 3-Bet OOP',
    'river_bluff_shown': 'River Bluff Shown',
    'calldown_weak_pair': 'Call-Down Weak Pair',
}

# v8.8.6: Coaching map — what each signal means and what Hero should do.
# Canonical data contract; renderer only handles display/formatting.
SIGNAL_COACHING = {
    'open_limp': {
        'suggests': 'Loose-passive tendency; weaker/passive preflop range.',
        'so_what': 'Isolate wider for value, especially in position. Do not assume fold equity postflop.',
        'default_timing': 'Actionable if Hero acts after the limp.',
    },
    'limp_call': {
        'suggests': 'Loose-passive tendency confirmed; wide calling range preflop.',
        'so_what': 'Iso-raise wider for value; expect frequent postflop calls with weak holdings.',
        'default_timing': 'Actionable if Hero acts after the limp-call.',
    },
    'weak_showdown_call': {
        'suggests': 'Sticky/station tendency; calls down with marginal holdings.',
        'so_what': 'Value-bet thinner; do not bluff multi-street. Expect calls with weak pairs.',
        'default_timing': 'Actionable in future hands or later streets.',
    },
    'passive_aggro_pivot': {
        'suggests': 'Normally passive player suddenly aggressive; likely strong or tilting.',
        'so_what': 'Respect sudden aggression from this player — fold marginal hands, do not hero-call.',
        'default_timing': 'Actionable immediately in the same hand.',
    },
    'repeated_blind_overfold': {
        'suggests': 'Tight/nitty tendency in the blinds; folds too often to steals.',
        'so_what': 'Steal wider when this player is in the blinds.',
        'default_timing': 'Actionable when this player is in the blinds.',
    },
    'multiway_donk': {
        'suggests': 'Loose-passive tendency; donk-bets into the field with weak/draw hands.',
        'so_what': 'Raise donk-bets for value with strong hands; call with position and draws.',
        'default_timing': 'Actionable on the street where the donk-bet occurs.',
    },
    'weird_minbet': {
        'suggests': 'Loose-passive tendency; uses minimum bets with weak or draw hands.',
        'so_what': 'Raise min-bets with value hands; the sizing signals weakness.',
        'default_timing': 'Actionable on the street where the min-bet occurs.',
    },
    'cold_call_3bet_oop': {
        'suggests': 'Loose-passive tendency; flatting 3-bets OOP with a wide, likely capped range.',
        'so_what': 'Apply pressure postflop — this range is wide and OOP. C-bet aggressively.',
        'default_timing': 'Actionable on the flop and later streets.',
    },
    'river_bluff_shown': {
        'suggests': 'Aggressive tendency confirmed; capable of multi-street bluffs.',
        'so_what': 'Call down lighter against this player; do not over-fold to river aggression.',
        'default_timing': 'Actionable in future hands.',
    },
    'calldown_weak_pair': {
        'suggests': 'Very sticky; will call multiple streets with weak pairs or worse.',
        'so_what': 'Value-bet relentlessly; never bluff multi-street against this player.',
        'default_timing': 'Actionable in future hands or later streets.',
    },
}

def _signal_to_label(signal):
    """Convert signal code to human-readable label."""
    return _SIGNAL_LABELS.get(signal, signal.replace('_', ' ').title() if signal else '')


def _resolve_hero(hand, hero_name):
    """Return the actual hero player name from the hand's action_ledger.

    The analyzer may pass a display name like 'Knockman' but the parser
    stores 'Hero' in the action_ledger. Always prefer hand['hero'].
    """
    return hand.get('hero', '') or hero_name


def _hero_active_at(action_ledger, hero_name, street, action_index):
    """Return True if Hero had NOT folded before this action.

    Scans the action_ledger for a Hero fold action. If Hero folded
    on an earlier street, or earlier on the same street, hero_involved=False.
    """
    street_order = {'preflop': 0, 'flop': 1, 'turn': 2, 'river': 3, 'showdown': 4}
    target_street_n = street_order.get(street, 0)

    for a in action_ledger:
        if a.get('player') != hero_name:
            continue
        if a.get('action') == 'folds':
            fold_street_n = street_order.get(a.get('street', ''), 0)
            if fold_street_n < target_street_n:
                return False  # Hero folded on earlier street
            if fold_street_n == target_street_n:
                return False
    return True


def _is_pfr(action_ledger, player_name):
    """Return True if this player was the preflop raiser (PFR/opener)."""
    for a in action_ledger:
        if a.get('street') != 'preflop':
            break
        if a.get('action') == 'posts':
            continue
        if a.get('action') in ('raises', 'bets') and a.get('player') == player_name:
            return True
        if a.get('action') in ('raises', 'bets'):
            return False  # someone else raised first
    return False


def _hand_context(hand, hero_name):
    """Extract common context fields from a hand dict for atom enrichment.

    Returns (hero_position, hero_cards, board) — all strings, empty when
    unavailable.  hero_cards joins the raw card list ("3hJs" etc.) so the
    caller can decide whether to expose it (only when hero_involved).
    """
    _hpos = ''
    for a in (hand.get('action_ledger') or []):
        if a.get('player') == hero_name and a.get('position'):
            _hpos = a['position']
            break
    _hpos = _hpos or hand.get('hero_position', '')
    _hcards = ''.join(hand.get('cards') or [])
    _board = ' '.join(hand.get('board') or [])
    return _hpos, _hcards, _board


def _make_atom(hand_id, tournament_id, villain_key, villain_alias,
               street, action_index, signal, badge, dimension,
               strength, same_hand_actionable, hero_involved,
               evidence_text, read_impact, available_before=None,
               *, hero_position='', hero_cards='', board='',
               villain_action='', trigger_action='', pot_size='',
               showdown_hand='', context_text='',
               detail_status='evidence_only'):
    """Convenience constructor for an evidence atom."""
    return {
        'type': 'evidence_atom',
        'hand_id': hand_id,
        'tournament_id': tournament_id,
        'villain_key': villain_key,
        'villain_alias': villain_alias,
        'villain_position': '',  # set by caller
        'street': street,
        'action_index': action_index,
        'signal': signal,
        'label': f"{BADGES[badge]['emoji']} {BADGES[badge]['label']}",
        'badge': badge,
        'dimension': dimension,
        'strength': strength,
        'same_hand_actionable': same_hand_actionable,
        'available_before_action_index': available_before,
        'hero_involved': hero_involved,
        'evidence_text': evidence_text,
        'read_impact': read_impact,
        # P0.3 context fields (v8.8.5)
        'hero_position': hero_position,
        'hero_cards': hero_cards,
        'board': board,
        'villain_action': villain_action,
        'trigger_action': trigger_action,
        'pot_size': pot_size,
        'showdown_hand': showdown_hand,
        'context_text': context_text,
        'detail_status': detail_status,
        # v8.8.6: coaching fields from SIGNAL_COACHING
        'suggests': SIGNAL_COACHING.get(signal, {}).get('suggests', ''),
        'so_what': SIGNAL_COACHING.get(signal, {}).get('so_what', ''),
        'default_timing': SIGNAL_COACHING.get(signal, {}).get('default_timing', ''),
    }


def detect_open_limp(hand, hero_name, aliases):
    """Detect: villain limps (calls BB) as first voluntary action from non-blind position.

    Signal: open_limp | Badge: note | Dimension: loose_passive
    """
    atoms = []
    al = hand.get('action_ledger') or []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    _hpos, _hcards, _ = _hand_context(hand, hero_name)
    # Find first voluntary action per player (skip posts/folds)
    pf = [a for a in al if a['street'] == 'preflop' and a['action'] != 'posts']
    first_raise_seen = False
    for idx, a in enumerate(pf):
        if a['action'] == 'folds':
            continue
        if a['action'] in ('raises', 'bets'):
            first_raise_seen = True
            break
        if (a['action'] == 'calls'
                and a['position'] not in _BLIND_POSITIONS
                and a['player'] != hero_name
                and not first_raise_seen):
            vk = f"{tid}|{a['player']}"
            va = aliases.get(vk, {})
            _valias = va.get('alias', a['player'][:8])
            hero_in = _hero_active_at(al, hero_name, 'preflop', idx)
            atom = _make_atom(
                hid, tid, vk, va.get('display', ''),
                'preflop', idx, 'open_limp', 'note', 'loose_passive',
                strength=2, same_hand_actionable=True,
                hero_involved=hero_in,
                evidence_text=f"{_valias} open-limped from {a['position']}.",
                read_impact='Loose-passive +2',
                available_before=idx + 1,
                hero_position=_hpos,
                villain_action='open-limped',
                context_text=f"Hero {_hpos}; {_valias} open-limped from {a['position']}.",
            )
            atom['villain_position'] = a['position']
            atoms.append(atom)
            # Don't break — keep scanning for additional limpers
    return atoms


def detect_limp_call(hand, hero_name, aliases):
    """Detect: villain limps then calls a raise (limp-call pattern).

    Signal: limp_call | Badge: note | Dimension: loose_passive
    """
    atoms = []
    al = hand.get('action_ledger') or []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    _hpos, _hcards, _ = _hand_context(hand, hero_name)
    pf = [a for a in al if a['street'] == 'preflop' and a['action'] != 'posts']

    # Track limpers: players who called before any raise
    limpers = {}  # player -> action_index
    raise_seen = False
    for idx, a in enumerate(pf):
        if a['action'] == 'folds':
            continue
        if a['action'] in ('raises', 'bets'):
            raise_seen = True
            continue
        if (a['action'] == 'calls'
                and a['player'] != hero_name
                and a['position'] not in _BLIND_POSITIONS):
            if not raise_seen:
                # This is a limp
                limpers[a['player']] = idx
            elif a['player'] in limpers:
                # This is a limp-CALL (limped, then called the raise)
                vk = f"{tid}|{a['player']}"
                va = aliases.get(vk, {})
                _valias = va.get('alias', a['player'][:8])
                hero_in = _hero_active_at(al, hero_name, 'preflop', idx)
                _amt = a.get('amount_bb', 0) or 0
                atom = _make_atom(
                    hid, tid, vk, va.get('display', ''),
                    'preflop', idx, 'limp_call', 'note', 'loose_passive',
                    strength=3, same_hand_actionable=True,
                    hero_involved=hero_in,
                    evidence_text=(f"{_valias} limp-called from "
                                   f"{a['position']} ({_amt:.1f}BB)."),
                    read_impact='Loose-passive +3',
                    available_before=idx + 1,
                    hero_position=_hpos,
                    villain_action=f"limp-called {_amt:.1f}BB",
                    context_text=f"Hero {_hpos}; {_valias} limp-called {_amt:.1f}BB from {a['position']}.",
                )
                atom['villain_position'] = a['position']
                atoms.append(atom)
    return atoms


def detect_weak_showdown_call(hand, hero_name, aliases):
    """Detect: villain called river/turn and showed weak hand at showdown.

    Weak = bottom pair, third pair, ace-high, or worse on a
    board where better is easily possible.

    Signal: weak_showdown_call | Badge: note | Dimension: sticky
    """
    atoms = []
    if not hand.get('went_to_sd'):
        return atoms

    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    al = hand.get('action_ledger') or []
    board = hand.get('board') or []
    _hpos, _hcards, _board_str = _hand_context(hand, hero_name)

    for vname, vinfo in (hand.get('villains') or {}).items():
        vcards = vinfo.get('shown_cards')
        if not vcards or vname == hero_name:
            continue

        # Check if villain called on river (or turn if no river)
        villain_called_late = False
        call_street = ''
        call_idx = 0
        for idx, a in enumerate(al):
            if a['player'] == vname and a['action'] == 'calls' and a['street'] in ('river', 'turn'):
                villain_called_late = True
                call_street = a['street']
                call_idx = idx

        if not villain_called_late:
            continue

        # Assess hand strength — simple heuristic
        # If villain's made hand is weak (pair or worse, no improvement from board)
        made = hand.get('matchups', {}).get(vname, {})
        # Use the villain's hand strength from the hand data if available
        # Fallback: check if villain cards don't pair the board well
        is_weak = _is_weak_showdown(vcards, board)
        if not is_weak:
            continue

        vk = f"{tid}|{vname}"
        va = aliases.get(vk, {})
        _valias = va.get('alias', vname[:8])
        cards_str = ' '.join(vcards) if isinstance(vcards, list) else str(vcards)
        hero_in = _hero_active_at(al, hero_name, call_street, call_idx)
        atom = _make_atom(
            hid, tid, vk, va.get('display', ''),
            call_street, call_idx, 'weak_showdown_call', 'note', 'sticky',
            strength=3, same_hand_actionable=False,
            hero_involved=hero_in,
            evidence_text=(f"{_valias} called {call_street} and showed "
                           f"{cards_str} (weak holding)."),
            read_impact='Sticky +3',
            hero_position=_hpos,
            hero_cards=_hcards if hero_in else '',
            board=_board_str,
            villain_action=f"called {call_street}",
            showdown_hand=cards_str,
            context_text=(f"Hero {_hpos}{(' ' + _hcards) if hero_in and _hcards else ''}; "
                          f"board {_board_str}; {_valias} called and showed {cards_str} (weak)."),
        )
        atom['villain_position'] = vinfo.get('position', '?')
        atoms.append(atom)

    return atoms


def _is_weak_showdown(villain_cards, board):
    """Heuristic: is this a weak showdown holding?

    Returns True if villain likely has bottom/third pair or worse.
    Conservative — only flags clearly weak hands.
    """
    if not villain_cards or not board or len(board) < 3:
        return False

    try:
        # Extract ranks
        rank_order = '23456789TJQKA'
        v_ranks = [c[0] for c in villain_cards if len(c) >= 2]
        b_ranks = [c[0] for c in board if len(c) >= 2]

        if not v_ranks or not b_ranks:
            return False

        # B138: pocket pair that hits the board = SET — never weak
        if len(v_ranks) == 2 and v_ranks[0] == v_ranks[1]:
            return False

        # Two pair: each hole card matches a different board rank
        v_matching = [r for r in v_ranks if r in b_ranks]
        if len(v_matching) == 2 and v_matching[0] != v_matching[1]:
            return False

        # Check for pair: does either villain card match a board card?
        v_pairs = [r for r in v_ranks if r in b_ranks]
        if not v_pairs:
            # No pair at all — ace-high or worse = weak
            return True

        # Has a pair — check if it's bottom/third pair
        board_rank_values = sorted([rank_order.index(r) for r in b_ranks if r in rank_order],
                                   reverse=True)
        pair_value = max(rank_order.index(r) for r in v_pairs if r in rank_order)

        if len(board_rank_values) >= 3:
            # Bottom pair = pairs the lowest board card
            # Third pair = pairs the third-highest board card
            unique_board = sorted(set(board_rank_values), reverse=True)
            if len(unique_board) >= 3 and pair_value <= unique_board[2]:
                return True  # Third pair or worse
            if len(unique_board) >= 2 and pair_value < unique_board[1]:
                return True  # Below second pair
    except (IndexError, ValueError):
        pass

    return False


def detect_passive_aggro_pivot(hand, hero_name, aliases):
    """Detect: villain checked/called on early streets then raised/bet big on later street.

    Signal: passive_aggro_pivot | Badge: pivot | Dimension: pivot
    """
    atoms = []
    al = hand.get('action_ledger') or []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    _hpos, _hcards, _board_str = _hand_context(hand, hero_name)

    streets = ['flop', 'turn', 'river']
    # Track per-villain: their actions by street
    villain_actions = {}  # player -> {street: [actions]}
    for idx, a in enumerate(al):
        if a['player'] == hero_name or a['street'] == 'preflop':
            continue
        if a['action'] == 'posts':
            continue
        villain_actions.setdefault(a['player'], {}).setdefault(a['street'], []).append(
            (idx, a['action'], a['amount_bb']))

    for vname, street_acts in villain_actions.items():
        if vname == hero_name:
            continue
        # §14 FP guard: skip PFR/opener — their check-back then bet is a
        # normal delayed c-bet, not a passive→aggro pivot.
        if _is_pfr(al, vname):
            continue
        # Need at least 2 streets of action
        acted_streets = [s for s in streets if s in street_acts]
        if len(acted_streets) < 2:
            continue

        # Check pattern: passive on early street(s), then aggressive on later
        # CALIBRATION FIX: for BB/SB, only flag check-RAISE as pivot (not check→bet,
        # which is standard blind play). For non-blind positions, any bet qualifies.
        vinfo_pos = (hand.get('villains') or {}).get(vname, {}).get('position', '')
        is_blind = vinfo_pos in _BLIND_POSITIONS
        passive_streets = []
        aggro_street = None
        aggro_idx = 0

        for s in acted_streets:
            acts = street_acts[s]
            has_passive = any(a in ('checks', 'calls') for _, a, _ in acts)
            if is_blind:
                # BB/SB: only a RAISE counts as aggression pivot (bet is normal)
                has_aggro = any(a == 'raises' for _, a, _ in acts)
            else:
                has_aggro = any(a in ('raises', 'bets') for _, a, _ in acts)

            if has_passive and not has_aggro:
                passive_streets.append(s)
            elif has_aggro and passive_streets:
                # Found the pivot!
                if is_blind:
                    aggro_idx = max(idx for idx, a, _ in acts if a == 'raises')
                else:
                    aggro_idx = max(idx for idx, a, _ in acts if a in ('raises', 'bets'))
                aggro_street = s
                break

        if not aggro_street or not passive_streets:
            continue

        vk = f"{tid}|{vname}"
        va = aliases.get(vk, {})
        _valias = va.get('alias', vname[:8])
        passive_str = '/'.join(passive_streets)
        vinfo = (hand.get('villains') or {}).get(vname, {})
        hero_in = _hero_active_at(al, hero_name, aggro_street, aggro_idx)
        atom = _make_atom(
            hid, tid, vk, va.get('display', ''),
            aggro_street, aggro_idx, 'passive_aggro_pivot', 'pivot', 'pivot',
            strength=4, same_hand_actionable=True,
            hero_involved=hero_in,
            evidence_text=(f"{_valias} was passive on {passive_str}, "
                           f"then raised/bet on {aggro_street}. Value-heavy line."),
            read_impact='Passive→Aggro pivot',
            available_before=aggro_idx + 1,
            hero_position=_hpos,
            hero_cards=_hcards if hero_in else '',
            villain_action=f"passive→raised {aggro_street}",
            context_text=(f"Hero {_hpos}; {_valias} was passive on {passive_str}, "
                          f"then raised/bet on {aggro_street}."),
        )
        atom['villain_position'] = vinfo.get('position', '?')
        atoms.append(atom)

    return atoms


def detect_repeated_blind_overfold(hands, hero_name, aliases):
    """Detect: villain folded from BB/SB ≥4 times consecutively.

    Cross-hand detector — needs the full hand list.
    Signal: repeated_blind_overfold | Badge: note | Dimension: tight

    Returns atoms tagged on the 4th+ consecutive fold hand.
    """
    atoms = []
    # Track consecutive blind folds per villain per blind position
    # Key: (villain_key, blind_pos) → list of (hand_id, fold_bool)
    streaks = {}  # vk -> {SB: [hand_ids...], BB: [hand_ids...]}

    for h in hands:
        tid = h.get('tournament_id', '')
        hid = h.get('id', '')
        al = h.get('action_ledger') or []

        for vname, vinfo in (h.get('villains') or {}).items():
            pos = vinfo.get('position', '')
            if pos not in _BLIND_POSITIONS:
                continue
            vk = f"{tid}|{vname}"

            # Did this villain fold from this blind?
            pf = [a for a in al
                  if a['street'] == 'preflop'
                  and a['action'] != 'posts'
                  and a['player'] == vname]
            folded = bool(pf and pf[0]['action'] == 'folds')

            streak_key = (vk, pos)
            if streak_key not in streaks:
                streaks[streak_key] = []

            if folded:
                streaks[streak_key].append(hid)
            else:
                streaks[streak_key] = []  # reset on non-fold

            # Emit atom when streak reaches 4+
            streak_len = len(streaks[streak_key])
            # CALIBRATION: raised from 4 to 6 — folding BB 4x is normal with junk
            if streak_len >= 6 and folded:
                va = aliases.get(vk, {})
                _valias = va.get('alias', vname[:8])
                _hn_ovf = _resolve_hero(h, hero_name)
                _hpos_ovf, _, _ = _hand_context(h, _hn_ovf)
                hero_in = _hero_active_at(al, _hn_ovf, 'preflop', 0)
                atom = _make_atom(
                    hid, tid, vk, va.get('display', ''),
                    'preflop', 0, 'repeated_blind_overfold', 'note', 'tight',
                    strength=2, same_hand_actionable=False,
                    hero_involved=hero_in,
                    evidence_text=(f"{_valias} folded {pos} "
                                   f"{streak_len} times in a row. Exploitable with steals."),
                    read_impact='Tight +2 (blind overfold)',
                    hero_position=_hpos_ovf,
                    villain_action=f"folded {pos}",
                    context_text=(f"Hero {_hpos_ovf}; {_valias} folded {pos} "
                                  f"{streak_len}x in a row."),
                )
                atom['villain_position'] = pos
                atoms.append(atom)

    return atoms


def _live_players_at(al, upto_idx):
    """v8.14.1 xway-fix: distinct dealt players who have NOT folded by action
    index `upto_idx` — the live, still-contesting field at that decision point.

    This is the ONLY correct "N-way" basis per the product rule: NOT players
    dealt in, NOT table seats, NOT players who saw an earlier street and then
    folded. A turn donk after a player folds the flop is 2-way, even though 3
    saw the flop.
    """
    dealt = set(a.get('player') for a in al)
    folded = set(a.get('player') for j, a in enumerate(al)
                 if j < upto_idx and a.get('action') == 'folds')
    return len(dealt - folded)


def detect_multiway_donk(hand, hero_name, aliases):
    """Detect: villain donk-bets into PFR in a pot that is STILL multiway at the
    donk (3+ players live at that street's decision, not merely 3+ to the flop).

    Signal: multiway_donk | Badge: note | Dimension: loose_passive
    Only fires when 3+ are still live at the donk; non-PFR villain.
    """
    atoms = []
    al = hand.get('action_ledger') or []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    _hpos, _hcards, _board_str = _hand_context(hand, hero_name)
    # Derive n_to_flop from action_ledger (count players who didn't fold preflop)
    n_to_flop = hand.get('n_players_flop', 0) or 0
    if not n_to_flop:
        _pf_players = set()
        _pf_folders = set()
        for a in al:
            if a['street'] != 'preflop':
                break
            if a['action'] == 'posts':
                continue
            _pf_players.add(a['player'])
            if a['action'] == 'folds':
                _pf_folders.add(a['player'])
        # Include posted players who didn't fold
        _all_pf = set(a['player'] for a in al if a['street'] == 'preflop')
        n_to_flop = len(_all_pf - _pf_folders)
    if n_to_flop < 3:
        return atoms

    # CALIBRATION FIX: find the PFR's position to enforce OOP requirement
    _pfr_player = None
    for a in al:
        if a['street'] != 'preflop' or a['action'] == 'posts':
            continue
        if a['action'] in ('raises', 'bets'):
            _pfr_player = a['player']
            break
    _pfr_position = ''
    if _pfr_player:
        _pfr_position = (hand.get('villains') or {}).get(_pfr_player, {}).get('position', '')
        if _pfr_player == hand.get('hero', 'Hero'):
            _pfr_position = hand.get('position', '')
    _pos_order = {'SB':0,'BB':1,'UTG':2,'UTG+1':3,'MP':4,'HJ':5,'CO':6,'BTN':7}
    _pfr_pos_n = _pos_order.get(_pfr_position, 99)

    for idx, a in enumerate(al):
        if a['street'] not in ('flop', 'turn'):
            continue
        if a['action'] != 'bets' or a['player'] == hero_name:
            continue
        if _is_pfr(al, a['player']):
            continue  # PFR betting is normal, not a donk
        # CALIBRATION: bettor must be OOP relative to PFR
        _bettor_pos_n = _pos_order.get(a.get('position', ''), 99)
        if _bettor_pos_n >= _pfr_pos_n:
            continue  # bettor is in position or same — stab, not donk
        # v8.14.1 xway-fix: the pot must STILL be multiway at THIS donk. n_to_flop
        # is the flop-START field count; a turn donk after a flop fold is HU, so
        # use the live count at the bet for both the gate and the message.
        _n_live = _live_players_at(al, idx)
        if _n_live < 3:
            continue
        vk = f"{tid}|{a['player']}"
        va = aliases.get(vk, {})
        _valias = va.get('alias', a['player'][:8])
        hero_in = _hero_active_at(al, hero_name, a['street'], idx)
        atom = _make_atom(
            hid, tid, vk, va.get('display', ''),
            a['street'], idx, 'multiway_donk', 'note', 'loose_passive',
            strength=2, same_hand_actionable=True,
            hero_involved=hero_in,
            evidence_text=(f"{_valias} donk-bet "
                           f"{a['street']} into PFR in {_n_live}-way pot."),
            read_impact='Loose-passive +2 (donk)',
            available_before=idx + 1,
            hero_position=_hpos,
            hero_cards=_hcards if hero_in else '',
            board=_board_str,
            villain_action=f"donk-bet {a['street']}",
            context_text=(f"Hero {_hpos}; {_valias} donk-bet into PFR in "
                          f"{_n_live}-way pot on {a['street']}."),
        )
        atom['villain_position'] = a.get('position', '?')
        atoms.append(atom)
        break  # one per hand per street is enough
    return atoms


def detect_weird_minbet(hand, hero_name, aliases):
    """Detect: villain bets <=33% pot (weird sizing / tiny donk).

    Signal: weird_minbet | Badge: note | Dimension: loose_passive
    """
    atoms = []
    al = hand.get('action_ledger') or []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    _hpos, _hcards, _board_str = _hand_context(hand, hero_name)

    running_pot = 0
    for idx, a in enumerate(al):
        if a['action'] == 'posts':
            running_pot += a.get('amount_bb', 0)
            continue
        if a['street'] == 'preflop':
            if a['action'] in ('calls', 'raises', 'bets'):
                running_pot += a.get('amount_bb', 0)
            continue
        # Postflop
        amt = a.get('amount_bb', 0)
        if a['action'] in ('calls', 'raises', 'bets'):
            running_pot += amt
        if (a['action'] == 'bets' and a['player'] != hero_name
                and running_pot > 3 and amt > 0 and amt / running_pot <= 0.20):
            vk = f"{tid}|{a['player']}"
            va = aliases.get(vk, {})
            _valias = va.get('alias', a['player'][:8])
            hero_in = _hero_active_at(al, hero_name, a['street'], idx)
            pct = amt / running_pot * 100
            atom = _make_atom(
                hid, tid, vk, va.get('display', ''),
                a['street'], idx, 'weird_minbet', 'note', 'loose_passive',
                strength=2, same_hand_actionable=True,
                hero_involved=hero_in,
                evidence_text=(f"{_valias} bet {amt:.1f}BB "
                               f"into {running_pot:.1f}BB pot ({pct:.0f}%) on {a['street']}."),
                read_impact='Loose-passive +2 (min-bet)',
                available_before=idx + 1,
                hero_position=_hpos,
                hero_cards=_hcards if hero_in else '',
                board=_board_str,
                villain_action=f"bet {amt:.1f}BB into {running_pot:.1f}BB",
                pot_size=f"{running_pot:.1f}BB",
                context_text=(f"Hero {_hpos}; {_valias} min-bet {amt:.1f}BB "
                              f"into {running_pot:.1f}BB pot on {a['street']}."),
            )
            atom['villain_position'] = a.get('position', '?')
            atoms.append(atom)
            break  # one per hand
    return atoms


def detect_cold_call_3bet_oop(hand, hero_name, aliases):
    """Detect: villain cold-calls a 3bet out of position.

    Signal: cold_call_3bet_oop | Badge: note | Dimension: loose_passive
    """
    atoms = []
    al = hand.get('action_ledger') or []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    _hpos, _hcards, _ = _hand_context(hand, hero_name)
    pf_raise_count = hand.get('pf_raise_count', 0) or 0
    if pf_raise_count < 2:
        return atoms  # no 3bet in hand

    pf = [a for a in al if a['street'] == 'preflop' and a['action'] != 'posts']
    raise_count = 0
    # CALIBRATION FIX: track original raiser to exclude them from cold-call
    original_raiser = None
    for idx, a in enumerate(pf):
        if a['action'] in ('raises', 'bets'):
            raise_count += 1
            if raise_count == 1:
                original_raiser = a['player']
        if (a['action'] == 'calls' and raise_count >= 2
                and a['player'] != hero_name
                and a['player'] != original_raiser  # exclude original raiser flatting 3bet
                and a['position'] in ('UTG', 'UTG+1', 'MP', 'HJ')):
            vk = f"{tid}|{a['player']}"
            va = aliases.get(vk, {})
            _valias = va.get('alias', a['player'][:8])
            hero_in = _hero_active_at(al, hero_name, 'preflop', idx)
            atom = _make_atom(
                hid, tid, vk, va.get('display', ''),
                'preflop', idx, 'cold_call_3bet_oop', 'note', 'loose_passive',
                strength=3, same_hand_actionable=True,
                hero_involved=hero_in,
                evidence_text=(f"{_valias} cold-called a 3bet "
                               f"OOP from {a['position']}."),
                read_impact='Loose-passive +3 (flat 3b OOP)',
                available_before=idx + 1,
                hero_position=_hpos,
                villain_action='cold-called 3bet OOP',
                context_text=f"Hero {_hpos}; {_valias} flatted 3bet OOP from {a['position']}.",
            )
            atom['villain_position'] = a['position']
            atoms.append(atom)
            break
    return atoms


def detect_river_bluff_shown(hand, hero_name, aliases):
    """Detect: villain bet/raised river and showed missed draw or air at showdown.

    Signal: river_bluff_shown | Badge: note | Dimension: aggressive
    """
    atoms = []
    if not hand.get('went_to_sd'):
        return atoms
    al = hand.get('action_ledger') or []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    board = hand.get('board') or []
    _hpos, _hcards, _board_str = _hand_context(hand, hero_name)

    for vname, vinfo in (hand.get('villains') or {}).items():
        vcards = vinfo.get('shown_cards')
        if not vcards or vname == hero_name:
            continue
        # Did villain bet/raise river?
        river_aggro = False
        river_idx = 0
        for idx, a in enumerate(al):
            if (a['player'] == vname and a['street'] == 'river'
                    and a['action'] in ('bets', 'raises')):
                river_aggro = True
                river_idx = idx
                break
        if not river_aggro:
            continue
        # Was the shown hand weak (bluff)?
        if _is_weak_showdown(vcards, board):
            vk = f"{tid}|{vname}"
            va = aliases.get(vk, {})
            _valias = va.get('alias', vname[:8])
            hero_in = _hero_active_at(al, hero_name, 'river', river_idx)
            cards_str = ' '.join(vcards) if isinstance(vcards, list) else str(vcards)
            atom = _make_atom(
                hid, tid, vk, va.get('display', ''),
                'river', river_idx, 'river_bluff_shown', 'note', 'aggressive',
                strength=4, same_hand_actionable=False,
                hero_involved=hero_in,
                evidence_text=(f"{_valias} bluffed river and showed "
                               f"{cards_str} (weak/missed draw)."),
                read_impact='Aggressive +4 (proven bluffer)',
                hero_position=_hpos,
                hero_cards=_hcards if hero_in else '',
                board=_board_str,
                villain_action='bluffed river',
                showdown_hand=cards_str,
                context_text=(f"Hero {_hpos}; board {_board_str}; "
                              f"{_valias} bluffed and showed {cards_str}."),
            )
            atom['villain_position'] = vinfo.get('position', '?')
            atoms.append(atom)
    return atoms


def detect_calldown_weak_pair(hand, hero_name, aliases):
    """Detect: villain called 2+ streets and showed weak pair or worse.

    Signal: calldown_weak_pair | Badge: note | Dimension: sticky
    """
    atoms = []
    if not hand.get('went_to_sd'):
        return atoms
    al = hand.get('action_ledger') or []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    board = hand.get('board') or []
    _hpos, _hcards, _board_str = _hand_context(hand, hero_name)

    for vname, vinfo in (hand.get('villains') or {}).items():
        vcards = vinfo.get('shown_cards')
        if not vcards or vname == hero_name:
            continue
        # Count calls across streets
        call_streets = set()
        last_call_idx = 0
        for idx, a in enumerate(al):
            if (a['player'] == vname and a['action'] == 'calls'
                    and a['street'] in ('flop', 'turn', 'river')):
                call_streets.add(a['street'])
                last_call_idx = idx
        if len(call_streets) < 2:
            continue
        if not _is_weak_showdown(vcards, board):
            continue
        vk = f"{tid}|{vname}"
        va = aliases.get(vk, {})
        _valias = va.get('alias', vname[:8])
        hero_in = _hero_active_at(al, hero_name, 'river', last_call_idx)
        cards_str = ' '.join(vcards) if isinstance(vcards, list) else str(vcards)
        _n_streets = len(call_streets)
        atom = _make_atom(
            hid, tid, vk, va.get('display', ''),
            'river', last_call_idx, 'calldown_weak_pair', 'note', 'sticky',
            strength=4, same_hand_actionable=False,
            hero_involved=hero_in,
            evidence_text=(f"{_valias} called down {_n_streets} "
                           f"streets and showed {cards_str} (weak holding)."),
            read_impact='Sticky +4 (multi-street call-down)',
            hero_position=_hpos,
            hero_cards=_hcards if hero_in else '',
            board=_board_str,
            villain_action=f"called down {_n_streets} streets",
            showdown_hand=cards_str,
            context_text=(f"Hero {_hpos}; board {_board_str}; "
                          f"{_valias} called {_n_streets} streets, showed {cards_str}."),
        )
        atom['villain_position'] = vinfo.get('position', '?')
        atoms.append(atom)
    return atoms


def extract_evidence_atoms(hands, hero_name, aliases):
    """Run all evidence detectors and return combined atoms.

    10 detectors:
    1-5 (PR3): open_limp, limp_call, weak_showdown_call, passive_aggro_pivot, repeated_blind_overfold
    6-10 (PR5): multiway_donk, weird_minbet, cold_call_3bet_oop, river_bluff_shown, calldown_weak_pair
    """
    all_atoms = []

    # Per-hand detectors
    # CALIBRATION FIX: resolve actual hero name per-hand (parser uses 'Hero',
    # analyzer may pass display name like 'Knockman')
    for h in hands:
        _hn = _resolve_hero(h, hero_name)
        all_atoms.extend(detect_open_limp(h, _hn, aliases))
        all_atoms.extend(detect_limp_call(h, _hn, aliases))
        all_atoms.extend(detect_weak_showdown_call(h, _hn, aliases))
        all_atoms.extend(detect_passive_aggro_pivot(h, _hn, aliases))
        # PR5 additions
        all_atoms.extend(detect_multiway_donk(h, _hn, aliases))
        all_atoms.extend(detect_weird_minbet(h, _hn, aliases))
        all_atoms.extend(detect_cold_call_3bet_oop(h, _hn, aliases))
        all_atoms.extend(detect_river_bluff_shown(h, _hn, aliases))
        all_atoms.extend(detect_calldown_weak_pair(h, _hn, aliases))

    # Cross-hand detectors (resolve hero per-hand inside)
    all_atoms.extend(detect_repeated_blind_overfold(hands, hero_name, aliases))

    return all_atoms


# ============================================================
# PR4: MVP EXPLOIT DETECTORS (spec §14.2, first 3)
# ============================================================

_STICKY_ARCHETYPES = {'CALLING_STATION', 'FISH', 'WHALE', 'FUN_REC'}
_PASSIVE_ARCHETYPES = {'CALLING_STATION', 'FISH', 'NIT', 'WHALE'}
_NIT_ARCHETYPES = {'NIT'}


# ============================================================
# Cross-hand temporal ordering — TIMESTAMP chronology (trust fix)
# ============================================================
# GG hand IDs are NOT a reliable chronological key. In the real 2026 sample
# (66 tournaments / 5,066 hands) a later hand carried a LOWER TM id in ~47% of
# adjacent-by-time pairs, and 29/44 tournaments were non-monotonic (table
# changes give each table its own id block). Ordering cross-hand villain
# evidence by hand id therefore let FUTURE-hand evidence grade an earlier Hero
# decision (look-ahead leakage). The only per-hand-correct chronological source
# is the parsed timestamp (hand_ts_date, hand_time) — the same key the canonical
# session-arc sort in gem_analyzer uses. Cross-hand grading is gated on a
# PROVABLE strict-earlier-by-timestamp relation; a missing or same-second-tied
# timestamp SAFE-DISABLES the comparison rather than falling back to unsafe
# hand-id order.

def _ts_key_of(hand):
    """Sortable (date, time) chronology key for a hand, or None when the true
    per-hand timestamp is absent.

    Requires BOTH hand_ts_date and hand_time (the per-hand HH-header stamp).
    Deliberately does NOT fall back to hand['date'] (the constant filename
    session-date) or to the hand id: an absent per-hand timestamp must DISABLE
    cross-hand grading for that hand, not be approximated. None => unorderable.
    """
    if not isinstance(hand, dict):
        return None
    date = hand.get('hand_ts_date') or ''
    tm = hand.get('hand_time') or ''
    return (date, tm) if (date and tm) else None


def _ts_strictly_before(a_key, b_key):
    """True iff hand A is PROVABLY strictly earlier than hand B by timestamp.

    Both keys must be present (non-None) AND a_key < b_key. A missing key (None)
    or an equal key (same-second tie, with no intra-table sequence available to
    break it) returns False: cross-hand grading is safe-disabled for that pair
    rather than guessed. This is the guard that stops future-hand evidence from
    grading an earlier Hero decision.
    """
    if a_key is None or b_key is None:
        return False
    return a_key < b_key


def build_hand_chronology(hands):
    """Build the timestamp chronology map used to gate cross-hand villain reads.

    Returns (ts_key_by_hid, diag):
      ts_key_by_hid: {hand_id: (date, time) | None}   # None => unorderable
      diag: {n_hands, n_valid, n_missing_ts, n_same_second_tied,
             tournaments_with_missing_ts, tournaments_with_same_second_ties,
             warnings: [QA/source warning strings]}

    The gate (_villain_has_read) admits a prior atom only when
    _ts_strictly_before(atom_hand_key, current_hand_key) is True, so this map is
    never "sorted": strict `<` on the (date, time) tuples both orders valid
    hands and refuses to order missing/tied ones. Same-second ties are detected
    PER TOURNAMENT (the villain scope) and surfaced as warnings so the report
    can state that some cross-hand grading was safe-disabled for an ambiguous
    cluster. GG hand ids are intentionally ignored here.
    """
    ts_key_by_hid = {}
    seen = {}                 # (tid, date, time) -> count, for tie detection
    missing_tids = set()
    n_valid = 0
    for h in hands:
        hid = h.get('id') or ''
        if not hid:
            continue
        tid = h.get('tournament_id') or ''
        key = _ts_key_of(h)
        ts_key_by_hid[hid] = key
        if key is None:
            missing_tids.add(tid)
        else:
            n_valid += 1
            sk = (tid, key[0], key[1])
            seen[sk] = seen.get(sk, 0) + 1
    tied = {k for k, n in seen.items() if n > 1}
    tied_tids = sorted({k[0] for k in tied})
    n_tied = sum(n for k, n in seen.items() if n > 1)
    warnings = []
    if missing_tids:
        _names = ', '.join(sorted(t for t in missing_tids if t)) or '(unknown tid)'
        warnings.append(
            'cross-hand villain grading disabled for %d tournament(s) with '
            'missing per-hand timestamps: %s' % (len(missing_tids), _names))
    if tied:
        warnings.append(
            'cross-hand villain grading safe-disabled for %d same-second tie '
            'cluster(s) in tournament(s) %s (no intra-table sequence to order '
            'them)' % (len(tied), ', '.join(tied_tids) or '(unknown tid)'))
    diag = {
        'n_hands': len(ts_key_by_hid),
        'n_valid': n_valid,
        'n_missing_ts': len(ts_key_by_hid) - n_valid,
        'n_same_second_tied': n_tied,
        'tournaments_with_missing_ts': sorted(t for t in missing_tids if t),
        'tournaments_with_same_second_ties': tied_tids,
        'warnings': warnings,
    }
    return ts_key_by_hid, diag


def _villain_has_read(hand, villain_key, dimension, atoms_by_villain,
                      min_atoms=2, archetype_set=None, read_states=None,
                      hand_order=None):
    """Check if a villain has sufficient read evidence for exploit detection.

    Uses TWO sources (in priority order):
    1. PR3 evidence atoms PRIOR to this hand (temporal gate + mapped scoring)
    2. Old profiler archetype on this hand (if medium+ confidence)

    v8.7.1 FIX: Source 1 now applies BOTH temporal gating AND mapped dimension
    scoring. The old Source-1 (full-session read_states) was removed because
    it bypassed the temporal gate — a villain's read was built from the whole
    session including current/future hands. Now atoms are filtered to prior-only,
    then scored through _DIMENSION_MAP to get mapped dimensions (so pivot atoms
    score into 'aggressive', etc.), solving both look-ahead and dead-gate bugs.

    Returns (has_read: bool, read_source: str, confidence: str)
    """
    # Source 1: PR3 atoms with temporal gate + mapped dimension scoring.
    # TEMPORAL GATE (timestamp trust fix): `hand_order` is now a TIMESTAMP
    # chronology map {hand_id: (date, time) | None} from build_hand_chronology
    # — NOT hand-id index order (GG hand ids are not chronological). Admit a
    # prior atom only when it is PROVABLY strictly earlier than this hand by
    # timestamp; a missing or same-second-tied timestamp safe-disables the
    # comparison (no id fallback), so future-hand evidence can never grade this
    # earlier Hero decision. A current hand with no timestamp (cur_key None)
    # admits nothing -> cross-hand grading disabled for it.
    current_hid = hand.get('id', '')
    v_atoms = atoms_by_villain.get(villain_key, [])
    # `hand_order is None` = caller opted out of the cross-hand gate (legacy /
    # same-hand-only callers). A PROVIDED chronology map (even empty) keeps the
    # gate ACTIVE: an unknown current-hand key (cur_key None) then admits nothing
    # -> safe-disable, never an unfiltered fallback.
    if hand_order is not None and current_hid:
        cur_key = hand_order.get(current_hid)
        v_atoms = [a for a in v_atoms
                   if _ts_strictly_before(
                       hand_order.get(a.get('hand_id', '')), cur_key)]

    if v_atoms:
        # Score prior atoms through _DIMENSION_MAP to get mapped dimensions
        # (so pivot atoms score into 'aggressive', etc.)
        _prior_dims = {}
        for a in v_atoms:
            adim = a.get('dimension', '')
            strength = a.get('strength', 1)
            mapping = _DIMENSION_MAP.get(adim, {})
            for k, weight in mapping.items():
                _prior_dims[k] = _prior_dims.get(k, 0) + weight * strength

        _dim_threshold = {'sticky': 8, 'tight': 6, 'aggressive': 6,
                          'loose_passive': 4, 'loose': 4, 'passive': 4}
        threshold = _dim_threshold.get(dimension, 6)
        score = _prior_dims.get(dimension, 0)
        if score >= threshold:
            n = len(v_atoms)
            conf = 'high' if n >= 8 else 'medium' if n >= 4 else 'low'
            return True, 'prior_atoms_mapped', conf, n

    # Source 3: old profiler archetype
    if archetype_set:
        va = hand.get('villain_archetype', '')
        vc = hand.get('villain_archetype_confidence', '')
        if va in archetype_set and vc in ('medium', 'high'):
            return True, 'profiler_archetype', vc, 0

    return False, '', '', 0


def detect_bluffed_sticky(hand, hero_name, aliases, atoms_by_villain,
                          read_states=None, hand_order=None):
    """Detect: Hero bluffed (bet/raised with likely air) vs known sticky villain.

    Signal: bluffed_sticky | Badge: miss | Severity: B
    Fires when: Hero bet/raised river, lost or didn't go to showdown,
    and primary villain has sticky read evidence.
    """
    exploits = []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    al = hand.get('action_ledger') or []
    hsa = hand.get('hero_street_actions', {}) or {}
    net = hand.get('net_bb', 0) or 0
    went_sd = hand.get('went_to_sd', False)
    pvk = hand.get('primary_villain_key', '')

    if not pvk or not hsa:
        return exploits

    # Hero bet or raised on river
    river_act = hsa.get('river', '')
    if river_act not in ('bet', 'raise', 'cbet'):
        return exploits

    # Outcome: Hero lost (net < 0) or villain called and Hero had weak hand
    # Conservative: only flag when net is clearly negative
    if net >= 0:
        return exploits

    # Check villain read
    has_read, source, conf, _n_atoms = _villain_has_read(
        hand, pvk, 'sticky', atoms_by_villain,
        min_atoms=2, archetype_set=_STICKY_ARCHETYPES,
                      read_states=read_states, hand_order=hand_order)
    if not has_read:
        # Also check loose_passive dimension (limp-callers are sticky)
        has_read, source, conf, _n_atoms = _villain_has_read(
            hand, pvk, 'loose_passive', atoms_by_villain,
            min_atoms=3, archetype_set=_STICKY_ARCHETYPES,
                      read_states=read_states, hand_order=hand_order)
    if not has_read:
        return exploits

    va = aliases.get(pvk, {})
    alias = va.get('alias', pvk.split('|')[1][:8] if '|' in pvk else '?')
    _exp = {
        'type': 'exploit_opportunity',
        'hand_id': hid,
        'villain_key': pvk,
        'villain_read_before_decision': 'Sticky / calling station',
        'hero_decision_street': 'river',
        'hero_action': f'Hero {river_act} river ({net:+.1f}BB)',
        'recommended_exploit': f'Check back — {alias} calls too wide to bluff profitably.',
        'auto_verdict': 'missed_exploit',
        'label': '❌ Miss',
        'badge': 'miss',
        'severity': 'B',
        'read_confidence': conf,
        'exploit_confidence': 'medium',
        'needs_llm_review': abs(net) > 20,
        'evidence_text': f'Hero bluffed river into {alias} (known sticky). '
                         f'Read source: {source}.',
    }
    _stamp_exploit_read(_exp, 'bluffed_sticky', source, confidence=conf, n_atoms=_n_atoms)
    exploits.append(_exp)
    return exploits


def detect_paid_off_passive_aggression(hand, hero_name, aliases, atoms_by_villain,
                                       read_states=None, hand_order=None):
    """Detect: Hero called a raise from a normally-passive villain who woke up.

    Signal: paid_off_passive | Badge: miss | Severity: B
    Fires when: passive villain raised/bet big, Hero called, Hero lost significantly.
    """
    exploits = []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    al = hand.get('action_ledger') or []
    hsa = hand.get('hero_street_actions', {}) or {}
    net = hand.get('net_bb', 0) or 0
    pvk = hand.get('primary_villain_key', '')

    if not pvk or not hsa:
        return exploits

    # Hero called on turn or river and lost significantly
    turn_act = hsa.get('turn', '')
    river_act = hsa.get('river', '')
    hero_called_late = (turn_act == 'call' or river_act == 'call')
    if not hero_called_late or net >= -5:
        return exploits

    # Villain raised or bet big (check for villain aggression on the call street)
    villain_raised = (hand.get('villain_xr_turn') or hand.get('villain_xr_river')
                      or hand.get('villain_xr_flop'))
    if not villain_raised:
        # Check action_ledger for villain raise
        pv_name = (hand.get('primary_villain') or {}).get('name', '')
        if pv_name:
            for a in al:
                if (a['player'] == pv_name
                        and a['action'] in ('raises', 'bets')
                        and a['street'] in ('turn', 'river')
                        and a.get('amount_bb', 0) > 5):
                    villain_raised = True
                    break

    if not villain_raised:
        return exploits

    # Check villain read — normally passive
    has_read, source, conf, _n_atoms = _villain_has_read(
        hand, pvk, 'loose_passive', atoms_by_villain,
        min_atoms=2, archetype_set=_PASSIVE_ARCHETYPES,
                      read_states=read_states, hand_order=hand_order)
    if not has_read:
        # Also check for pivot evidence — passive→aggro pivot on this hand
        # means villain normally passive but showed aggression
        hand_atoms = atoms_by_villain.get(pvk, [])
        pivot_here = [a for a in hand_atoms
                      if a['hand_id'] == hid and a['signal'] == 'passive_aggro_pivot']
        if pivot_here:
            has_read = True
            source = 'same_hand_pivot'
            conf = 'high'

    if not has_read:
        return exploits

    va = aliases.get(pvk, {})
    alias = va.get('alias', '?')
    call_street = 'river' if river_act == 'call' else 'turn'
    _exp = {
        'type': 'exploit_opportunity',
        'hand_id': hid,
        'villain_key': pvk,
        'villain_read_before_decision': 'Passive villain showing aggression',
        'hero_decision_street': call_street,
        'hero_action': f'Hero called {call_street} ({net:+.1f}BB)',
        'recommended_exploit': (f'Fold or raise for info — {alias} is normally passive, '
                                f'aggression from them is value-heavy.'),
        'auto_verdict': 'missed_exploit',
        'label': '❌ Miss',
        'badge': 'miss',
        'severity': 'B',
        'read_confidence': conf,
        'exploit_confidence': 'medium',
        'needs_llm_review': abs(net) > 25 or conf == 'low',
        'evidence_text': f'Hero called {alias}\'s aggression on {call_street} '
                         f'despite passive read. Read source: {source}.',
    }
    _stamp_exploit_read(_exp, 'paid_off_passive_aggression', source, confidence=conf, n_atoms=_n_atoms)
    exploits.append(_exp)
    return exploits


def detect_good_fold_vs_passive_aggro(hand, hero_name, aliases, atoms_by_villain,
                                       read_states=None, hand_order=None):
    """Detect: Hero correctly folded to a normally-passive villain's aggression.

    Signal: good_fold_vs_passive_aggro | Badge: good | Severity: C
    Fires when: passive villain raised/bet big, Hero FOLDED, and Hero had
    a hand that was plausibly in the calling range (not total air).

    Gate: exclude pure trash folds — only credit folds with real hands.
    """
    exploits = []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    al = hand.get('action_ledger') or []
    hsa = hand.get('hero_street_actions', {}) or {}
    pvk = hand.get('primary_villain_key', '')
    cards = hand.get('cards') or []

    if not pvk or not hsa:
        return exploits

    # Hero folded on turn or river (meaningful street — not preflop)
    turn_act = hsa.get('turn', '')
    river_act = hsa.get('river', '')
    flop_act = hsa.get('flop', '')
    fold_street = ''
    if river_act == 'fold':
        fold_street = 'river'
    elif turn_act == 'fold':
        fold_street = 'turn'
    elif flop_act == 'fold':
        fold_street = 'flop'
    if not fold_street:
        return exploits

    # Gate: Hero must have had a calling-range hand (not pure trash)
    # Require at least one card >= T, or a pocket pair, or suited connectors
    if not cards or len(cards) < 2:
        return exploits
    rank_values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
                   '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
    r1 = rank_values.get(cards[0][0], 0)
    r2 = rank_values.get(cards[1][0], 0)
    high = max(r1, r2)
    is_pair = r1 == r2
    suited = len(cards[0]) >= 2 and len(cards[1]) >= 2 and cards[0][1] == cards[1][1]
    # Calling range: pair, or high card >= T, or suited with 9+
    if not (is_pair or high >= 10 or (suited and high >= 9)):
        return exploits  # trash fold — don't credit

    # Villain raised or bet big (same check as paid_off_passive_aggression)
    villain_raised = (hand.get('villain_xr_turn') or hand.get('villain_xr_river')
                      or hand.get('villain_xr_flop'))
    if not villain_raised:
        pv_name = (hand.get('primary_villain') or {}).get('name', '')
        if pv_name:
            for a in al:
                if (a['player'] == pv_name
                        and a['action'] in ('raises', 'bets')
                        and a['street'] in ('flop', 'turn', 'river')
                        and a.get('amount_bb', 0) > 3):
                    villain_raised = True
                    break
    if not villain_raised:
        return exploits

    # Check villain read — normally passive
    has_read, source, conf, _n_atoms = _villain_has_read(
        hand, pvk, 'loose_passive', atoms_by_villain,
        min_atoms=2, archetype_set=_PASSIVE_ARCHETYPES,
                      read_states=read_states, hand_order=hand_order)
    if not has_read:
        # Also check pivot evidence
        hand_atoms = atoms_by_villain.get(pvk, [])
        pivot_here = [a for a in hand_atoms
                      if a['hand_id'] == hid and a['signal'] == 'passive_aggro_pivot']
        if pivot_here:
            has_read = True
            source = 'same_hand_pivot'
            conf = 'high'

    if not has_read:
        return exploits

    # Don't fire on same hand as missed exploit (paid_off)
    net = hand.get('net_bb', 0) or 0

    va = aliases.get(pvk, {})
    alias = va.get('alias', '?')
    cards_str = _chart_label(cards)
    _exp = {
        'type': 'exploit_opportunity',
        'hand_id': hid,
        'villain_key': pvk,
        'villain_read_before_decision': 'Passive villain showing aggression',
        'hero_decision_street': fold_street,
        'hero_action': f'Hero folded {cards_str} on {fold_street}',
        'recommended_exploit': (f'Correct — {alias} is normally passive. '
                                f'Aggression from them is value-heavy. Trust the fold.'),
        'auto_verdict': 'good_exploit',
        'label': '✅ Good',
        'badge': 'good',
        'severity': 'C',
        'read_confidence': conf,
        'exploit_confidence': 'medium',
        'needs_llm_review': False,
        'evidence_text': f'Hero correctly folded {cards_str} to {alias}\'s aggression '
                         f'on {fold_street}. Read source: {source}.',
    }
    _stamp_exploit_read(_exp, 'paid_off_passive_aggression', source, outcome='good', confidence=conf, n_atoms=_n_atoms)
    exploits.append(_exp)
    return exploits


def detect_missed_steal_vs_nit_blinds(hand, hero_name, aliases, atoms_by_villain,
                                      read_states=None, hand_order=None):
    """Detect: Hero folded from steal position when blinds are known nit/overfolder.

    Signal: missed_steal_nit | Badge: miss | Severity: C
    Fires when: Hero folded from CO/BTN/HJ with a playable hand,
    and blind villains have tight/overfold evidence.
    """
    exploits = []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    pos = hand.get('position', '')

    # Hero must be in steal position and have folded
    if pos not in ('CO', 'BTN', 'HJ'):
        return exploits
    if hand.get('vpip'):
        return exploits  # Hero played the hand — didn't fold

    # CALIBRATION FIX: Hero must be first-in (no prior open/limp/raise)
    al = hand.get('action_ledger') or []
    pf = [a for a in al if a['street'] == 'preflop' and a['action'] != 'posts']
    for a in pf:
        if a['player'] == hand.get('hero', 'Hero'):
            break  # reached Hero's action — they were first-in
        if a['action'] in ('raises', 'bets', 'calls'):
            return exploits  # someone acted before Hero — not first-in

    # Hero needs a stealable hand (not complete trash)
    cards = hand.get('cards') or []
    if not cards or len(cards) < 2:
        return exploits
    if not _is_stealable_hand(cards, pos):
        return exploits

    # Check blind villains for tight/overfold evidence
    for vname, vinfo in (hand.get('villains') or {}).items():
        vpos = vinfo.get('position', '')
        if vpos not in ('SB', 'BB'):
            continue
        vk = f"{tid}|{vname}"

        has_read, source, conf, _n_atoms = _villain_has_read(
            hand, vk, 'tight', atoms_by_villain,
            min_atoms=3, archetype_set=_NIT_ARCHETYPES,
                      read_states=read_states, hand_order=hand_order)
        if not has_read:
            continue

        va = aliases.get(vk, {})
        alias = va.get('alias', vname[:8])
        cards_str = _chart_label(cards)
        _exp = {
            'type': 'exploit_opportunity',
            'hand_id': hid,
            'villain_key': vk,
            'villain_read_before_decision': f'{alias} ({vpos}) is a known tight/overfolder',
            'hero_decision_street': 'preflop',
            'hero_action': f'Hero folded {cards_str} from {pos}',
            'recommended_exploit': f'Open-raise — {alias} overfolds blinds. Steal profitably.',
            'auto_verdict': 'missed_exploit',
            'label': '❌ Miss',
            'badge': 'miss',
            'severity': 'C',
            'read_confidence': conf,
            'exploit_confidence': 'medium',
            'needs_llm_review': False,
            'evidence_text': f'Hero folded {cards_str} from {pos} with {alias} '
                             f'({vpos}) who overfolds. Read source: {source}.',
        }
        # v8.12.8 (exploitation QA P0): a Miss VERDICT on a thin read is an
        # accusation the evidence can't carry — downgrade to candidate.
        if conf == 'low' or (_n_atoms or 0) < 2:
            _exp['auto_verdict'] = 'read_supported_candidate'
            _exp['label'] = '🟡 Possible miss — read is thin'
            _exp['badge'] = ''
            _exp['exploit_confidence'] = 'low'
            _stamp_exploit_read(_exp, 'missed_steal_vs_nit', source,
                                outcome='', confidence=conf,
                                n_atoms=_n_atoms)
        else:
            _stamp_exploit_read(_exp, 'missed_steal_vs_nit', source,
                                confidence=conf, n_atoms=_n_atoms)
        exploits.append(_exp)
        break  # one exploit per hand is enough

    return exploits


def _chart_label(cards):
    """v8.12.9 (GPT QA: 'JJo'): canonical chart notation from two cards —
    high rank first, s/o suffix ONLY for non-pairs (pairs are 'JJ', never
    'JJo'). Single owner for every label this module emits."""
    if not cards or len(cards) < 2 or len(cards[0]) < 2 or len(cards[1]) < 2:
        return ''.join(c[0] for c in (cards or []))
    r = sorted((cards[0][0], cards[1][0]),
               key=lambda x: _RANK_VAL.get(x, 0), reverse=True)
    if r[0] == r[1]:
        return r[0] + r[1]
    return r[0] + r[1] + ('s' if cards[0][1] == cards[1][1] else 'o')


def _is_baseline_open(cards, position):
    """v8.12.8 (exploitation QA P0): conservative ALWAYS-OPEN set for steal
    positions — hands every baseline chart opens regardless of the blinds'
    tendencies. Opening these into an overfolder is read-SUPPORTED, not an
    exploit-learning spot ("Good exploit: opened JJ" teaches the wrong
    lesson). Deliberately tight: pairs 88+, ATs+/AJo+, KQ, KJs, QJs."""
    if not cards or len(cards) < 2:
        return False
    rv = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
          '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
    r1 = rv.get(cards[0][0], 0)
    r2 = rv.get(cards[1][0], 0)
    high, low = max(r1, r2), min(r1, r2)
    suited = (len(cards[0]) >= 2 and len(cards[1]) >= 2
              and cards[0][1] == cards[1][1])
    if r1 == r2 and r1 >= 8:                      # 88+
        return True
    if high == 14 and (low >= 11 or (suited and low >= 10)):  # AJo+/ATs+
        return True
    if high == 13 and low == 12:                  # KQ
        return True
    if suited and ((high == 13 and low == 11)     # KJs
                   or (high == 12 and low == 11)):  # QJs
        return True
    return False


def _is_premium_hand(cards):
    """Check if cards are premium (AA/KK/QQ/AKs/AKo) — not a steal exploit."""
    if not cards or len(cards) < 2:
        return False
    rank_values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
                   '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
    r1 = rank_values.get(cards[0][0], 0)
    r2 = rank_values.get(cards[1][0], 0)
    high = max(r1, r2)
    low = min(r1, r2)
    # AA, KK, QQ
    if r1 == r2 and r1 >= 12:
        return True
    # AK (suited or offsuit)
    if high == 14 and low == 13:
        return True
    return False


def detect_good_steal_vs_nit(hand, hero_name, aliases, atoms_by_villain,
                              read_states=None, hand_order=None):
    """Detect: Hero correctly opened from steal position into nit blinds.

    Signal: good_steal_vs_nit | Badge: good | Severity: C
    Fires when: Hero opened from CO/BTN/HJ with a marginal steal hand,
    and blind villains have tight/overfold evidence.

    Gate: exclude premium hands (AA/KK/QQ/AK) — those are standard opens,
    not exploitation. Only credit marginal/wide steals that are specifically
    profitable because of the nit read.
    """
    exploits = []
    hid = hand.get('id', '')
    tid = hand.get('tournament_id', '')
    pos = hand.get('position', '')
    cards = hand.get('cards') or []

    # Hero must be in steal position and have OPENED (vpip=True, pfr=True)
    if pos not in ('CO', 'BTN', 'HJ'):
        return exploits
    if not hand.get('vpip') or not hand.get('pfr'):
        return exploits  # Hero didn't open-raise

    # Must be first-in (no prior open/limp/raise)
    al = hand.get('action_ledger') or []
    pf = [a for a in al if a['street'] == 'preflop' and a['action'] != 'posts']
    for a in pf:
        if a['player'] == hand.get('hero', 'Hero'):
            break  # reached Hero's action — they were first-in
        if a['action'] in ('raises', 'bets', 'calls'):
            return exploits  # someone acted before Hero

    # Gate: exclude premium hands
    if not cards or len(cards) < 2:
        return exploits
    if _is_premium_hand(cards):
        return exploits  # standard open, not exploitation

    # Must be a stealable hand (not total garbage that happened to work)
    if not _is_stealable_hand(cards, pos):
        return exploits

    # Check blind villains for tight/overfold evidence
    for vname, vinfo in (hand.get('villains') or {}).items():
        vpos = vinfo.get('position', '')
        if vpos not in ('SB', 'BB'):
            continue
        vk = f"{tid}|{vname}"

        has_read, source, conf, _n_atoms = _villain_has_read(
            hand, vk, 'tight', atoms_by_villain,
            min_atoms=3, archetype_set=_NIT_ARCHETYPES,
                      read_states=read_states, hand_order=hand_order)
        if not has_read:
            continue

        va = aliases.get(vk, {})
        alias = va.get('alias', vname[:8])
        cards_str = _chart_label(cards)
        _exp = {
            'type': 'exploit_opportunity',
            'hand_id': hid,
            'villain_key': vk,
            'villain_read_before_decision': f'{alias} ({vpos}) is a known tight/overfolder',
            'hero_decision_street': 'preflop',
            'hero_action': f'Hero opened {cards_str} from {pos}',
            'recommended_exploit': (f'Correct — {alias} overfolds blinds. '
                                    f'Stealing wider from {pos} is profitable.'),
            'auto_verdict': 'good_exploit',
            'label': '✅ Good',
            'badge': 'good',
            'severity': 'C',
            'read_confidence': conf,
            'exploit_confidence': 'medium',
            'needs_llm_review': False,
            'evidence_text': f'Hero opened {cards_str} from {pos} into overfolding '
                             f'{alias} ({vpos}). Read source: {source}.',
        }
        # v8.12.8 (exploitation QA P0): two gates before claiming Good.
        # (1) Baseline-standardness: JJ from HJ is normal poker, not an
        #     exploit — reclassify as read-supported standard (kept as
        #     evidence, dropped from Good counts).
        # (2) Read confidence: a 1-atom / low-confidence read is a
        #     hypothesis, not a verdict.
        _std_open = _is_baseline_open(cards, pos)
        _weak_read = (conf == 'low' or (_n_atoms or 0) < 2)
        if _std_open:
            _exp['auto_verdict'] = 'read_supported_standard'
            _exp['label'] = '➖ Standard (read-supported)'
            _exp['badge'] = ''
            _exp['recommended_exploit'] = (
                f'{cards_str} from {pos} is a baseline open — the {alias} '
                'overfold read adds EV, but this is not an '
                'exploit-learning spot.')
            _stamp_exploit_read(_exp, 'missed_steal_vs_nit', source,
                                outcome='', confidence=conf,
                                n_atoms=_n_atoms)
        elif _weak_read:
            _exp['auto_verdict'] = 'read_supported_candidate'
            _exp['label'] = '🟡 Possible read — do not over-adjust'
            _exp['badge'] = ''
            _exp['exploit_confidence'] = 'low'
            _exp['recommended_exploit'] = (
                f'Read on {alias} rests on thin evidence '
                f'({_n_atoms or 0} atom(s), {conf or "low"} confidence) — '
                'treat the wider steal as a hypothesis, not a verdict.')
            _stamp_exploit_read(_exp, 'missed_steal_vs_nit', source,
                                outcome='', confidence=conf,
                                n_atoms=_n_atoms)
        else:
            _stamp_exploit_read(_exp, 'missed_steal_vs_nit', source,
                                outcome='good', confidence=conf,
                                n_atoms=_n_atoms)
        exploits.append(_exp)
        break  # one exploit per hand

    return exploits


def _is_stealable_hand(cards, position):
    """Heuristic: is this hand worth opening from a steal position?

    Conservative — only flags clearly stealable hands that were folded.
    """
    if len(cards) < 2:
        return False
    rank_values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
                   '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
    try:
        r1 = rank_values.get(cards[0][0], 0)
        r2 = rank_values.get(cards[1][0], 0)
        high = max(r1, r2)
        low = min(r1, r2)
        suited = len(cards[0]) >= 2 and len(cards[1]) >= 2 and cards[0][1] == cards[1][1]
        gap = high - low

        # Pairs are always stealable
        if r1 == r2:
            return True
        # Suited connectors/one-gappers with a face card
        if suited and high >= 10 and gap <= 3:
            return True
        # Any ace
        if high == 14 and (suited or low >= 7):
            return True
        # King-x suited
        if high == 13 and suited:
            return True
        # BTN is wider
        if position == 'BTN':
            if high >= 12 and low >= 7:
                return True
            if suited and high >= 9:
                return True
        # CO slightly tighter
        if position == 'CO':
            if high >= 12 and low >= 9:
                return True
    except (IndexError, KeyError):
        pass
    return False


def detect_missed_thin_value_vs_sticky(hand, hero_name, aliases, atoms_by_villain,
                                       read_states=None, hand_order=None):
    """Detect: Hero checked back a value hand vs known sticky villain.

    Signal: missed_thin_value | Badge: miss | Severity: B
    """
    exploits = []
    hsa = hand.get('hero_street_actions', {}) or {}
    pvk = hand.get('primary_villain_key', '')
    net = hand.get('net_bb', 0) or 0
    if not pvk or not hsa:
        return exploits
    # Hero checked river (didn't bet)
    river_act = hsa.get('river', '')
    if river_act not in ('check', 'x'):
        return exploits
    # Hero won at showdown (had value to bet)
    if not hand.get('went_to_sd') or net <= 0:
        return exploits
    # Check villain is sticky
    has_read, source, conf, _n_atoms = _villain_has_read(
        hand, pvk, 'sticky', atoms_by_villain,
        min_atoms=2, archetype_set=_STICKY_ARCHETYPES,
                      read_states=read_states, hand_order=hand_order)
    if not has_read:
        has_read, source, conf, _n_atoms = _villain_has_read(
            hand, pvk, 'loose_passive', atoms_by_villain,
            min_atoms=3, archetype_set=_STICKY_ARCHETYPES,
                      read_states=read_states, hand_order=hand_order)
    if not has_read:
        return exploits
    va = aliases.get(pvk, {})
    alias = va.get('alias', '?')
    _exp = {
        'type': 'exploit_opportunity',
        'hand_id': hand.get('id', ''),
        'villain_key': pvk,
        'villain_read_before_decision': 'Sticky villain calls wide',
        'hero_decision_street': 'river',
        'hero_action': f'Hero checked river (won {net:+.1f}BB at SD)',
        'recommended_exploit': f'Value-bet — {alias} calls too wide. Thin value prints money.',
        'auto_verdict': 'missed_exploit',
        'label': '❌ Miss',
        'badge': 'miss',
        'severity': 'B',
        'read_confidence': conf,
        'exploit_confidence': 'medium',
        'needs_llm_review': False,
        'evidence_text': f'Hero checked back river with a winning hand vs {alias} '
                         f'(known sticky). Missed thin value. Source: {source}.',
    }
    _stamp_exploit_read(_exp, 'missed_thin_value_vs_sticky', source, confidence=conf, n_atoms=_n_atoms)
    exploits.append(_exp)
    return exploits


def detect_opened_too_loose_vs_aggro(hand, hero_name, aliases, atoms_by_villain,
                                     read_states=None, hand_order=None):
    """Detect: Hero opened too loose with known 3-bet threat behind.

    Signal: opened_loose_vs_aggro | Badge: miss | Severity: C
    """
    exploits = []
    pvk = hand.get('primary_villain_key', '')
    if not pvk:
        return exploits
    # Hero must have opened (vpip=True, pfr or open raise)
    if not hand.get('vpip') or not hand.get('pfr'):
        return exploits
    # Hero got 3bet and folded
    if not hand.get('fold_to_3bet'):
        return exploits
    net = hand.get('net_bb', 0) or 0
    if net >= 0:
        return exploits
    # Check if the 3bettor has aggressive evidence
    has_read, source, conf, _n_atoms = _villain_has_read(
        hand, pvk, 'aggressive', atoms_by_villain,
        min_atoms=2, archetype_set={'LAG', 'MANIAC', 'DANGER_REG'},
                      read_states=read_states, hand_order=hand_order)
    if not has_read:
        return exploits
    va = aliases.get(pvk, {})
    alias = va.get('alias', '?')
    pos = hand.get('position', '?')
    _exp = {
        'type': 'exploit_opportunity',
        'hand_id': hand.get('id', ''),
        'villain_key': pvk,
        'villain_read_before_decision': f'{alias} is known aggro 3-bet threat',
        'hero_decision_street': 'preflop',
        'hero_action': f'Hero opened from {pos}, folded to 3bet ({net:+.1f}BB)',
        'recommended_exploit': f'Tighten open range with {alias} behind, or plan to continue.',
        'auto_verdict': 'missed_exploit',
        'label': '❌ Miss',
        'badge': 'miss',
        'severity': 'C',
        'read_confidence': conf,
        'exploit_confidence': 'low',
        'needs_llm_review': True,
        'evidence_text': f'Hero opened from {pos} and folded to 3bet from {alias} '
                         f'(known aggro). Source: {source}.',
    }
    _stamp_exploit_read(_exp, 'opened_too_loose_vs_aggro', source, confidence=conf, n_atoms=_n_atoms)
    exploits.append(_exp)
    return exploits


def detect_overfolded_vs_aggro(hand, hero_name, aliases, atoms_by_villain,
                               read_states=None, hand_order=None):
    """Detect: Hero folded to normal-sized bet from known maniac/aggro.

    Signal: overfolded_vs_aggro | Badge: miss | Severity: C
    """
    exploits = []
    pvk = hand.get('primary_villain_key', '')
    hsa = hand.get('hero_street_actions', {}) or {}
    if not pvk or not hsa:
        return exploits
    # Hero folded postflop
    fold_street = None
    for s in ('flop', 'turn', 'river'):
        if hsa.get(s) in ('fold', 'xf'):
            fold_street = s
            break
    if not fold_street:
        return exploits
    net = hand.get('net_bb', 0) or 0
    # Only flag if pot was meaningful
    if abs(net) < 3:
        return exploits
    # Check villain is aggro/maniac
    has_read, source, conf, _n_atoms = _villain_has_read(
        hand, pvk, 'aggressive', atoms_by_villain,
        min_atoms=3, archetype_set={'MANIAC', 'LAG', 'FUN_REC'},
                      read_states=read_states, hand_order=hand_order)
    if not has_read:
        return exploits
    va = aliases.get(pvk, {})
    alias = va.get('alias', '?')
    _exp = {
        'type': 'exploit_opportunity',
        'hand_id': hand.get('id', ''),
        'villain_key': pvk,
        'villain_read_before_decision': f'{alias} is known aggro/maniac',
        'hero_decision_street': fold_street,
        'hero_action': f'Hero folded {fold_street} ({net:+.1f}BB)',
        'recommended_exploit': f'Widen call-down — {alias} over-bluffs.',
        'auto_verdict': 'missed_exploit',
        'label': '❌ Miss',
        'badge': 'miss',
        'severity': 'C',
        'read_confidence': conf,
        'exploit_confidence': 'low',
        'needs_llm_review': True,
        'evidence_text': f'Hero folded to {alias} on {fold_street}. '
                         f'{alias} is a known aggro/maniac. Source: {source}.',
    }
    _stamp_exploit_read(_exp, 'overfolded_vs_aggro', source, confidence=conf, n_atoms=_n_atoms)
    exploits.append(_exp)
    return exploits


def detect_ego_fought_maniac(hand, hero_name, aliases, atoms_by_villain,
                             read_states=None, hand_order=None):
    """Detect: Hero 3bet/4bet bluffed a known maniac (should trap instead).

    Signal: ego_fought_maniac | Badge: miss | Severity: B
    """
    exploits = []
    pvk = hand.get('primary_villain_key', '')
    if not pvk:
        return exploits
    # Hero 3bet or 4bet
    hero_3b = hand.get('hero_3bet', False)
    hero_4b = hand.get('hero_4bet', False)
    if not (hero_3b or hero_4b):
        return exploits
    net = hand.get('net_bb', 0) or 0
    if net >= 0:
        return exploits  # Hero won, not a mistake
    # Check villain is maniac
    has_read, source, conf, _n_atoms = _villain_has_read(
        hand, pvk, 'aggressive', atoms_by_villain,
        min_atoms=3, archetype_set={'MANIAC'},
                      read_states=read_states, hand_order=hand_order)
    if not has_read:
        return exploits
    va = aliases.get(pvk, {})
    alias = va.get('alias', '?')
    action = '4bet' if hero_4b else '3bet'
    _exp = {
        'type': 'exploit_opportunity',
        'hand_id': hand.get('id', ''),
        'villain_key': pvk,
        'villain_read_before_decision': f'{alias} is a known maniac',
        'hero_decision_street': 'preflop',
        'hero_action': f'Hero {action} ({net:+.1f}BB)',
        'recommended_exploit': f'Trap with strong hands — {alias} will hang themselves.',
        'auto_verdict': 'missed_exploit',
        'label': '❌ Miss',
        'badge': 'miss',
        'severity': 'B',
        'read_confidence': conf,
        'exploit_confidence': 'medium',
        'needs_llm_review': True,
        'evidence_text': f'Hero {action} bluffed {alias} (known maniac). '
                         f'Maniacs call too wide — trap instead. Source: {source}.',
    }
    _stamp_exploit_read(_exp, 'ego_fought_maniac', source, confidence=conf, n_atoms=_n_atoms)
    exploits.append(_exp)
    return exploits


def detect_pivot_overplayed(hand, hero_name, aliases, atoms_by_villain,
                            read_states=None, hand_order=None):
    """Detect: Hero ignored a same-hand passive→aggro pivot and jammed/called.

    Signal: pivot_overplayed | Badge: miss | Severity: A
    Uses same-hand pivot atoms from PR3 detector.
    """
    exploits = []
    pvk = hand.get('primary_villain_key', '')
    hsa = hand.get('hero_street_actions', {}) or {}
    net = hand.get('net_bb', 0) or 0
    if not pvk or not hsa or net >= 0:
        return exploits
    # Check for same-hand pivot evidence
    hand_atoms = atoms_by_villain.get(pvk, [])
    pivots = [a for a in hand_atoms
              if a['hand_id'] == hand.get('id', '')
              and a['signal'] == 'passive_aggro_pivot'
              and a['same_hand_actionable']]
    if not pivots:
        return exploits
    pivot = pivots[0]
    pivot_street = pivot['street']
    # Hero must have called/jammed AFTER the pivot
    hero_act_on_pivot_street = hsa.get(pivot_street, '')
    # Also check the street after the pivot
    street_order = ['flop', 'turn', 'river']
    pivot_idx = street_order.index(pivot_street) if pivot_street in street_order else -1
    hero_called_after = False
    for s in street_order[pivot_idx:]:
        act = hsa.get(s, '')
        if act in ('call', 'jam', 'raise', 'allin'):
            hero_called_after = True
            break
    if not hero_called_after:
        return exploits
    # Must lose significantly
    if abs(net) < 10:
        return exploits
    va = aliases.get(pvk, {})
    alias = va.get('alias', '?')
    _exp = {
        'type': 'exploit_opportunity',
        'hand_id': hand.get('id', ''),
        'villain_key': pvk,
        'villain_read_before_decision': f'{alias} pivoted from passive to aggressive',
        'hero_decision_street': pivot_street,
        'hero_action': f'Hero called/jammed after pivot ({net:+.1f}BB)',
        'recommended_exploit': (f'Respect the pivot — {alias} was passive then aggressive. '
                                f'Usually value-heavy. Fold one-pair hands.'),
        'auto_verdict': 'missed_exploit',
        'label': '❌ Miss',
        'badge': 'miss',
        'severity': 'A',
        'read_confidence': 'high',
        'exploit_confidence': 'medium',
        'needs_llm_review': abs(net) > 30,
        'evidence_text': f'Hero called/jammed after {alias} pivoted from passive to '
                         f'aggressive on {pivot_street}. Value-heavy line ignored.',
    }
    _stamp_exploit_read(_exp, 'pivot_overplayed', 'same_hand_pivot', confidence='high', n_atoms=len(pivots))
    exploits.append(_exp)
    return exploits


def detect_exploit_opportunities(hands, hero_name, aliases, atoms_by_villain,
                                  read_states=None):
    """Run all exploit detectors.

    8 detectors:
    1-3 (PR4): bluffed_sticky, paid_off_passive, missed_steal_nit
    4-8 (PR5): missed_thin_value, opened_loose_vs_aggro, overfolded_vs_aggro,
               ego_fought_maniac, pivot_overplayed

    FIX (v8.7.0 calibration): builds hand_order for temporal gating and
    passes read_states for mapped-dimension scoring.
    """
    # Build TIMESTAMP-based chronology for cross-hand temporal gating.
    # (timestamp trust fix) GG hand IDs are NOT chronological — in the real 2026
    # sample a later hand carried a lower TM id in ~47% of adjacent-by-time
    # pairs and 29/44 tournaments were non-monotonic (per-table id blocks).
    # Order strictly by parsed timestamp (hand_ts_date, hand_time); missing or
    # same-second-tied timestamps safe-disable cross-hand grading rather than
    # falling back to unsafe hand-id order. See build_hand_chronology /
    # _ts_strictly_before. (Passed through the detectors as the `hand_order`
    # kwarg position — the name is kept to avoid touching 10 signatures.)
    _hand_chrono, _chrono_diag = build_hand_chronology(hands)
    for _w in _chrono_diag.get('warnings', []):
        print('  [villain-chrono] %s' % _w)

    all_exploits = []
    for h in hands:
        _hn = _resolve_hero(h, hero_name)
        _ctx = (atoms_by_villain, read_states, _hand_chrono)
        all_exploits.extend(detect_bluffed_sticky(h, _hn, aliases, *_ctx))
        all_exploits.extend(detect_paid_off_passive_aggression(h, _hn, aliases, *_ctx))
        all_exploits.extend(detect_missed_steal_vs_nit_blinds(h, _hn, aliases, *_ctx))
        all_exploits.extend(detect_missed_thin_value_vs_sticky(h, _hn, aliases, *_ctx))
        all_exploits.extend(detect_opened_too_loose_vs_aggro(h, _hn, aliases, *_ctx))
        all_exploits.extend(detect_overfolded_vs_aggro(h, _hn, aliases, *_ctx))
        all_exploits.extend(detect_ego_fought_maniac(h, _hn, aliases, *_ctx))
        all_exploits.extend(detect_pivot_overplayed(h, _hn, aliases, *_ctx))
        # v8.8.4: good exploit paths
        all_exploits.extend(detect_good_fold_vs_passive_aggro(h, _hn, aliases, *_ctx))
        all_exploits.extend(detect_good_steal_vs_nit(h, _hn, aliases, *_ctx))
    return all_exploits


# ============================================================
# PR5: READ STATE AGGREGATION + LINE STORIES
# ============================================================

# CALIBRATION: diversified dimension map so signals route to distinct reads
# - overfold → tight only (was tight+loose_passive spillover)
# - limp/limp-call/donk/minbet/cold-call → loose_passive
# - showdown calls → sticky (not loose_passive)
# - pivot/bluff → aggressive
_DIMENSION_MAP = {
    'loose_passive': {'loose': 2, 'passive': 2},
    'sticky': {'sticky': 4},           # raised: showdown evidence is stronger
    'tight': {'tight': 3},             # raised: overfold is primary tight signal
    'pivot': {'aggressive': 3},        # raised: pivots are strong aggro signal
    'aggressive': {'aggressive': 4},   # raised: proven bluffs are strong
}

_READ_LABELS = {
    'sticky_passive': '📞 Sticky Passive',
    'loose_passive': '🐟 Loose Passive',
    'tight_passive': '🪨 Nit / Rock',
    'aggressive': '⚡ Aggressive',
    'unknown': '❓ Unknown',
}

# v8.8.3: canonical detector → Matrix read-label mapping
# Each detector knows which read dimension it exploits. Stable across outcomes.
_EXPLOIT_READ_MAP = {
    'bluffed_sticky': 'Sticky Passive',
    'paid_off_passive_aggression': 'Loose Passive',
    'missed_steal_vs_nit': 'Nit / Rock',
    'missed_thin_value_vs_sticky': 'Sticky Passive',
    'opened_too_loose_vs_aggro': 'Aggressive',
    'overfolded_vs_aggro': 'Aggressive',
    'ego_fought_maniac': 'Aggressive',
    'pivot_overplayed': 'Loose Passive',
}

# v8.8.6: emoji display lookup — canonical label → emoji prefix.
# Keeps display concern separate from canonical data fields.
_READ_EMOJI = {
    'Sticky Passive': '📞',
    'Loose Passive': '🐟',
    'Nit / Rock': '🪨',
    'Aggressive': '⚡',
    'Unknown': '❓',
}

VALID_EXPLOIT_READ_LABELS = {
    'Aggressive',
    'Loose Passive',
    'Nit / Rock',
    'Sticky Passive',
}

# v8.8.6: coaching map for exploit detectors — what the exploit means + Hero adjustment.
_EXPLOIT_COACHING = {
    'bluffed_sticky': {
        'suggests': 'Villain is sticky/station — calls down with marginal holdings.',
        'so_what': 'Do not bluff this player multi-street. Value-bet thinner instead.',
        'default_timing': 'Read should be established before Hero decides to bluff.',
    },
    'paid_off_passive_aggression': {
        'suggests': 'Normally passive villain showed sudden aggression — likely has it.',
        'so_what': 'Respect aggression from known passive players. Fold marginal hands to their raises.',
        'default_timing': 'Read should be established before Hero calls the raise.',
    },
    'missed_steal_vs_nit': {
        'suggests': 'Villain overfolds in the blinds — steal opportunity.',
        'so_what': 'Open wider from steal positions when this player is in the blinds.',
        'default_timing': 'Read should be established before Hero decides to fold/open.',
    },
    'missed_thin_value_vs_sticky': {
        'suggests': 'Villain calls down too light — thin value bet opportunity missed.',
        'so_what': 'Bet river for thin value; this player calls with weak pairs and worse.',
        'default_timing': 'Read should be established before Hero checks back.',
    },
    'opened_too_loose_vs_aggro': {
        'suggests': 'Villain 3-bets aggressively — Hero opened too loose into them.',
        'so_what': 'Tighten opening range when this player is behind and likely to 3-bet.',
        'default_timing': 'Read should be established before Hero opens.',
    },
    'overfolded_vs_aggro': {
        'suggests': 'Known aggressive villain — Hero folded too easily postflop.',
        'so_what': 'Call down lighter against known aggro players; their range is wider than it looks.',
        'default_timing': 'Read should be established before Hero folds.',
    },
    'ego_fought_maniac': {
        'suggests': 'Villain is a known maniac/aggro — Hero fought back and lost.',
        'so_what': 'Trap instead of re-raising; let the maniac bet into your strong hands.',
        'default_timing': 'Read should be established before Hero decides to 3-bet/4-bet.',
    },
    'pivot_overplayed': {
        'suggests': 'Normally passive villain pivoted to aggression in this hand — likely strong.',
        'so_what': 'When a passive player suddenly raises or bets big, respect it. This is not a bluff.',
        'default_timing': 'Pivot detected within the same hand, before Hero acted.',
    },
}


def _stamp_exploit_read(exp, detector, read_source, outcome='missed',
                        confidence='', n_atoms=0):
    """Stamp exploit dict with detector identity and canonical read label.

    v8.8.3: called by each detector after building the exploit dict.
    Keeps _EXPLOIT_READ_MAP as the single source of truth for grouping.
    v8.8.5: also stamps assumption transparency metadata.
    """
    exp['exploit_detector'] = detector
    exp['exploit_type'] = detector          # backward-compatible alias
    exp['exploit_outcome'] = outcome
    exp['read_source'] = read_source
    _label = _EXPLOIT_READ_MAP.get(detector, 'Unknown')
    exp['exploit_read_label'] = _label
    exp['exploit_read_display'] = f"{_READ_EMOJI.get(_label, '❓')} {_label}"
    # v8.8.5: assumption transparency
    _atom_word = 'atom' if n_atoms == 1 else 'atoms'
    _src_label = {'prior_atoms_mapped': f'prior evidence ({n_atoms} {_atom_word})',
                  'profiler_archetype': 'population tendency (no direct evidence)',
                  'same_hand_pivot': 'observed in this hand'}
    exp['assumption_source'] = _src_label.get(read_source, read_source or 'unknown')
    exp['assumption_confidence'] = confidence or (
        'high' if n_atoms >= 6 else 'medium' if n_atoms >= 3 else 'low')
    # v8.8.6: stamp coaching for exploit — what the read means + Hero adjustment
    _ec = _EXPLOIT_COACHING.get(detector, {})
    exp['suggests'] = _ec.get('suggests', '')
    exp['so_what'] = _ec.get('so_what', '')
    exp['default_timing'] = _ec.get('default_timing', '')
    return exp


def _build_read_states(aliases, atoms_by_villain):
    """Aggregate evidence atoms into per-villain read states (spec §13.3).

    CALIBRATION: scoring diversified so different signal types map to
    distinct reads instead of everything becoming Loose Passive.
    """
    read_states = {}
    for vk, va in aliases.items():
        va_atoms = atoms_by_villain.get(vk, [])
        if not va_atoms:
            continue

        dims = {'loose': 0, 'passive': 0, 'sticky': 0,
                'aggressive': 0, 'competence': 0, 'tight': 0}

        for atom in va_atoms:
            dim = atom.get('dimension', '')
            strength = atom.get('strength', 1)
            mapping = _DIMENSION_MAP.get(dim, {})
            for k, weight in mapping.items():
                dims[k] += weight * strength

        # Determine primary read — CALIBRATION: tighter thresholds,
        # prioritize tight/sticky/aggressive over generic loose_passive
        if dims['sticky'] >= 8:
            primary = 'sticky_passive'
        elif dims['tight'] >= 6:
            primary = 'tight_passive'
        elif dims['aggressive'] >= 8:
            primary = 'aggressive'
        elif dims['loose'] >= 4 and dims['passive'] >= 4:
            primary = 'loose_passive'
        elif dims['tight'] >= 3 and dims['tight'] > dims['loose']:
            primary = 'tight_passive'
        elif dims['aggressive'] >= 4 and dims['aggressive'] > dims['passive']:
            primary = 'aggressive'
        else:
            primary = 'unknown'

        # Confidence from atom count
        n = len(va_atoms)
        conf = 'high' if n >= 8 else 'medium' if n >= 4 else 'low'

        # Exceptions (pivots)
        exceptions = []
        pivot_atoms = [a for a in va_atoms if a['badge'] == 'pivot']
        if pivot_atoms and primary != 'aggressive':
            exceptions.append({
                'label': 'Passive → Aggro Pivot',
                'exploit': 'Respect turn/river raises from this villain.',
            })

        evidence_hids = sorted(set(a['hand_id'] for a in va_atoms))
        n_hero = sum(1 for a in va_atoms if a.get('hero_involved', False))
        n_sd = sum(1 for a in va_atoms if a.get('signal', '') in
                   ('weak_showdown_call', 'calldown_weak_pair', 'river_bluff_shown'))

        read_states[vk] = {
            'villain_key': vk,
            'villain_alias': va.get('display', ''),
            'primary_read': _READ_LABELS.get(primary, primary),
            'confidence': conf,
            'dimensions': dims,
            'exceptions': exceptions,
            'evidence_hand_ids': evidence_hids,
            'n_evidence': n,
            'n_hero_involved': n_hero,
            'n_showdowns': n_sd,
        }

    return read_states


def _build_line_stories(atoms_by_hand):
    """Build line stories from per-hand atoms (spec §13.2).

    Groups multi-street atoms for the same villain into narratives.
    """
    stories = []
    for hid, hand_atoms in atoms_by_hand.items():
        # Group by villain
        by_villain = {}
        for a in hand_atoms:
            by_villain.setdefault(a['villain_key'], []).append(a)

        for vk, vatoms in by_villain.items():
            if len(vatoms) < 2:
                continue  # need multi-action for a story
            # Sort by street order
            street_order = {'preflop': 0, 'flop': 1, 'turn': 2, 'river': 3}
            vatoms.sort(key=lambda a: street_order.get(a['street'], 9))

            sequence = [a['signal'] for a in vatoms]
            badges = [a['badge'] for a in vatoms]

            # Determine story type
            has_pivot = 'pivot' in badges
            if has_pivot:
                label = '⚠ Passive → Aggro Pivot'
                badge = 'pivot'
                interp = 'Villain showed passive line then escalated. Usually value-heavy.'
                adjust = 'Overfold one-pair hands when this villain raises after passive play.'
                conf = 'high'
            else:
                label = '❗ Multi-street pattern'
                badge = 'note'
                interp = 'Villain showed consistent pattern across multiple streets.'
                adjust = 'Adjust reads based on accumulated signals.'
                conf = 'medium'

            stories.append({
                'type': 'line_story',
                'hand_id': hid,
                'villain_key': vk,
                'label': label,
                'badge': badge,
                'sequence': sequence,
                'interpretation': interp,
                'recommended_adjustment': adjust,
                'confidence': conf,
            })

    return stories


# ============================================================
# ORCHESTRATOR
# ============================================================

def build_villain_intel(hands, hero_name, profiles=None):
    """Build the full opponent intelligence container.

    PR 1+3: assigns aliases, runs MVP evidence detectors, returns
    the intel container with populated evidence atoms.

    Args:
        hands: list of parsed hand dicts
        hero_name: Hero's player name
        profiles: dict from gem_opponent_profiler.profile_opponents()
                  (optional — used to enrich alias entries with archetype)

    Returns:
        dict with keys:
            villain_aliases: {villain_key: alias_record}
            evidence_atoms: list of atom dicts (10 detectors)
            line_stories: list of story dicts
            read_states: {villain_key: read_state_dict}
            exploit_opportunities: list (8 exploit detectors)
            queue_context_template: dict    # template for queue hooks
    """
    # B139: sort hands by ID for deterministic processing order
    hands = sorted(hands, key=lambda h: h.get('id', ''))

    # Step 1: Build villain keys from all hands
    vkeys_meta = build_villain_keys(hands)

    # Step 2: Assign stable aliases + V-numbers
    aliases = assign_aliases(vkeys_meta)

    # Step 3: Enrich with archetype data from existing profiler (if available)
    if profiles:
        # Map old profiler keys to new villain keys
        # Old key format: tournament_name[:30]|position
        # We need to cross-reference by matching hand data
        _enrich_aliases_with_archetypes(aliases, hands, profiles, hero_name)

    # Step 4: Build per-hand villain_key index
    _hand_villain_keys = {}
    for h in hands:
        tid = h.get('tournament_id') or ''
        pv = h.get('primary_villain') or {}
        pv_name = pv.get('name', '')
        if tid and pv_name:
            _hand_villain_keys[h.get('id', '')] = f"{tid}|{pv_name}"

    # Step 5 (PR3): Run MVP evidence detectors
    evidence_atoms = extract_evidence_atoms(hands, hero_name, aliases)

    # B139: sort atoms by stable key so all downstream indexing and
    # temporal gates produce identical results regardless of hand list order.
    def _atom_sort_key(a):
        return (a.get('hand_id', ''), a.get('street', ''),
                a.get('action_index') if a.get('action_index') is not None else 999999,
                a.get('signal', ''))
    evidence_atoms.sort(key=_atom_sort_key)

    # Index atoms by hand_id for per-hand tagging
    _atoms_by_hand = {}
    for atom in evidence_atoms:
        _atoms_by_hand.setdefault(atom['hand_id'], []).append(atom)

    # Index atoms by villain_key for evidence popup
    _atoms_by_villain = {}
    for atom in evidence_atoms:
        _atoms_by_villain.setdefault(atom['villain_key'], []).append(atom)

    # Step 7 (PR5): Build read states BEFORE exploit detection
    # so exploit gates can use mapped dimension scores
    read_states = _build_read_states(aliases, _atoms_by_villain)

    # Step 6 (PR4+calibration): Run exploit opportunity detectors
    # with read_states for mapped-dimension scoring
    exploit_opportunities = detect_exploit_opportunities(
        hands, hero_name, aliases, _atoms_by_villain, read_states=read_states)

    # B139: sort exploits by stable key for deterministic output
    exploit_opportunities.sort(key=lambda e: (
        e.get('hand_id', ''), e.get('hero_decision_street', ''),
        e.get('hero_decision_index') if e.get('hero_decision_index') is not None else 999999,
        e.get('exploit_detector', '')))

    # Index exploits by hand_id
    _exploits_by_hand = {}
    for exp in exploit_opportunities:
        _exploits_by_hand.setdefault(exp['hand_id'], []).append(exp)

    # Enrich alias records with evidence counts + slim popup atoms
    for vk, va in aliases.items():
        va_atoms = _atoms_by_villain.get(vk, [])
        va['n_evidence'] = len(va_atoms)
        va['evidence_hand_ids'] = sorted(set(a['hand_id'] for a in va_atoms))
        # Slim atoms for JS popup (avoid bloating HTML with full atom dicts)
        va['evidence_atoms_for_popup'] = [
            {
                'hand_id': a['hand_id'],
                'street': a['street'],
                'villain_position': a.get('villain_position', ''),
                'hero_involved': a.get('hero_involved', False),
                'signal': a.get('signal', ''),
                'signal_label': _signal_to_label(a.get('signal', '')),
                'label': a['label'],
                'badge': a['badge'],
                'evidence_text': a['evidence_text'],
                'read_impact': a['read_impact'],
                'dimension': a.get('dimension', ''),
                'villain_alias': va.get('alias', ''),
                # P0.3 context fields (v8.8.5)
                'hero_position': a.get('hero_position', ''),
                'hero_cards': a.get('hero_cards', ''),
                'board': a.get('board', ''),
                'villain_action': a.get('villain_action', ''),
                'trigger_action': a.get('trigger_action', ''),
                'pot_size': a.get('pot_size', ''),
                'showdown_hand': a.get('showdown_hand', ''),
                'context_text': a.get('context_text', ''),
                'detail_status': a.get('detail_status', 'evidence_only'),
                # v8.8.6 VH Phase 1: coaching fields
                'suggests': a.get('suggests', ''),
                'so_what': a.get('so_what', ''),
                'default_timing': a.get('default_timing', ''),
            }
            for a in va_atoms[:50]  # cap at 50 per villain for size
        ]

    # read_states already built above (before exploit detection)

    # Step 8 (PR5): Build line stories from per-hand atoms
    line_stories = _build_line_stories(_atoms_by_hand)

    return {
        'villain_aliases': aliases,
        'hand_villain_keys': _hand_villain_keys,
        'evidence_atoms': evidence_atoms,
        'atoms_by_hand': _atoms_by_hand,
        'atoms_by_villain': _atoms_by_villain,
        'line_stories': line_stories,
        'read_states': read_states,
        'exploit_opportunities': exploit_opportunities,
        'exploits_by_hand': _exploits_by_hand,
        'queue_context_template': _empty_queue_context(),
    }


def _enrich_aliases_with_archetypes(aliases, hands, profiles, hero_name):
    """Cross-reference old profiler output with new villain keys.

    The old profiler uses tournament_name[:30]|position as key.
    We map these to new tournament_id|player_hash keys by scanning
    hands where each player was the opener/primary villain.
    """
    # Build a reverse map: for each old-style profiler key, find the
    # new villain_key by looking at hands where this player was primary
    # and occupied that position.
    old_to_new = {}
    for h in hands:
        tid = h.get('tournament_id') or ''
        tournament = (h.get('tournament') or '')[:30]
        pv = h.get('primary_villain') or {}
        pv_name = pv.get('name', '')
        if not (tid and pv_name):
            continue

        # What position was the primary villain in?
        vinfo = (h.get('villains') or {}).get(pv_name, {})
        vpos = vinfo.get('position', '')
        if not vpos:
            continue

        old_key = f"{tournament}|{vpos}"
        new_key = f"{tid}|{pv_name}"
        if old_key not in old_to_new:
            old_to_new[old_key] = new_key

    # Now enrich aliases with archetype from profiler
    for old_key, profile in profiles.items():
        new_key = old_to_new.get(old_key)
        if new_key and new_key in aliases:
            aliases[new_key]['archetype'] = profile.get('archetype', '')
            aliases[new_key]['archetype_label'] = profile.get('archetype_label', '')
            aliases[new_key]['archetype_emoji'] = profile.get('archetype_emoji', '')
            aliases[new_key]['archetype_confidence'] = profile.get('confidence', '')
            aliases[new_key]['archetype_exploit'] = profile.get('exploit', '')
            aliases[new_key]['archetype_reason'] = profile.get('reason', '')


# ============================================================
# UTILITY
# ============================================================

def villain_key_for_hand(hand):
    """Return the primary villain_key for a hand, or '' if unavailable."""
    tid = hand.get('tournament_id') or ''
    pv = hand.get('primary_villain') or {}
    pv_name = pv.get('name', '')
    if tid and pv_name:
        return f"{tid}|{pv_name}"
    return ''


def format_villain_display(alias_record, include_archetype=False):
    """Format a villain alias record for display.

    Compact:  Ghost · V49   (or just V163 when alias == v_number)
    With archetype:  📞 Ghost · V49 · Sticky Passive
    """
    alias = alias_record.get('alias', '?')
    v_num = alias_record.get('v_number', '?')
    # v8.7.1 FIX: when villain has no name-pool alias, alias IS the v_number
    # (e.g. "V163"). Don't show "V163 · V163" — show just "V163".
    if alias == v_num:
        display_name = alias
    else:
        display_name = f"{alias} · {v_num}"
    if include_archetype:
        emoji = alias_record.get('archetype_emoji', '')
        label = alias_record.get('archetype_label', '')
        if emoji and label:
            return f"{emoji} {display_name} · {label}"
    return display_name
