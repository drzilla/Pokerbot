"""Hole-card nickname lookup  (v7.80, Ron 2026-05-24).

Loads `Cards_nicknames.txt` (CSV: Hand,Most Common Nickname,Explanation) and
maps a 2-card hero hand to its common nickname for inline display in the
hand-example grid header. Lookup is suit-agnostic — the nickname file keys
on rank pairs only (AK, AQ, T2, 72, ...), which covers all 26 entries.

Cosmetic feature only: every failure path returns None, so a missing or
malformed nickname file can never break a report render.
"""
import csv
import os

# Low → high. Index gives rank strength for ordering a non-pair hand.
_RANK_ORDER = '23456789TJQKA'
_RANK_VAL = {r: i for i, r in enumerate(_RANK_ORDER)}

_CACHE = None  # default-path load is cached; explicit-path loads are not


def _default_path():
    """Project copy first, then a copy sitting beside this module — mirrors
    the resolution order used by gem_ranges.load_ranges()."""
    p = '/mnt/project/Cards_nicknames.txt'
    if os.path.exists(p):
        return p
    local = os.path.join(os.path.dirname(__file__) or '.',
                         'Cards_nicknames.txt')
    return local if os.path.exists(local) else p


def _load(path=None):
    """Return {hand_key: nickname}. Caches the default-path load only, so a
    test passing an explicit path always gets a fresh parse."""
    global _CACHE
    explicit = path is not None
    if not explicit and _CACHE is not None:
        return _CACHE
    path = path or _default_path()
    table = {}
    try:
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                hand = (row.get('Hand') or '').strip().upper()
                nick = (row.get('Most Common Nickname') or '').strip()
                if len(hand) == 2 and nick:
                    table[hand] = nick
    except (OSError, csv.Error):
        table = {}
    if not explicit:
        _CACHE = table
    return table


def hand_key(cards):
    """Normalize a 2-card list (e.g. ['Ah', 'Kd']) to a suit-agnostic key
    ('AK'), higher rank first; a pair collapses to e.g. 'AA'. Returns None
    when the input is not a clean 2-card hand."""
    if not cards or len(cards) != 2:
        return None
    ranks = []
    for c in cards:
        if not c or len(c) < 2:
            return None
        r = c[0].upper()
        if r not in _RANK_VAL:
            return None
        ranks.append(r)
    ranks.sort(key=lambda r: _RANK_VAL[r], reverse=True)
    return ranks[0] + ranks[1]


def combo_to_chart(cards):
    """Convert raw card tokens to chart notation (B250-safe).
    ['Js','Ac'] → 'AJo', ['Ah','Ad'] → 'AA', 'JsAc' → 'AJo'.
    Shared function — used by both analyzer and renderer."""
    import re
    if isinstance(cards, str):
        m = re.findall(r'([2-9TJQKA])([shdc])', cards)
        if len(m) >= 2:
            cards = [m[0][0] + m[0][1], m[1][0] + m[1][1]]
        else:
            return cards
    if not isinstance(cards, (list, tuple)) or len(cards) < 2:
        return str(cards) if cards else '?'
    r0, s0 = cards[0][0], cards[0][1:] if len(cards[0]) > 1 else '?'
    r1, s1 = cards[1][0], cards[1][1:] if len(cards[1]) > 1 else '?'
    if _RANK_VAL.get(r0, 0) < _RANK_VAL.get(r1, 0):
        r0, r1 = r1, r0
        s0, s1 = s1, s0
    if r0 == r1:
        return f'{r0}{r1}'
    return f'{r0}{r1}{"s" if s0 == s1 else "o"}'


def nickname_for(cards, path=None):
    """Return the common nickname for a 2-card hero hand, or None if the
    hand has no listed nickname (or the input/file is unusable)."""
    key = hand_key(cards)
    if not key:
        return None
    return _load(path).get(key)
