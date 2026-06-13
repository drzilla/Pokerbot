# -*- coding: utf-8 -*-
"""Chart display-label registry (v8.12.11 / Slice-E minimum D prereq).

Single source that turns an internal chart id (REJAM_SBvsHJ, OPEN_20-40BB_SB,
PUSH_10BB_CO, 3BF_OOP, BBD_20BB_vsCO, ...) into human-readable teaching text.
The raw id stays available for a debug/source tooltip, but NEVER appears as
the primary user-facing label (trust-contract: no raw chart IDs in
worklist/report). Pattern-based so new ids degrade gracefully instead of
leaking the raw string.
"""
import re

_POS_WORD = {
    'UTG': 'UTG', 'UTG1': 'UTG+1', 'UTG2': 'UTG+2', 'LJ': 'LJ', 'MP': 'MP',
    'HJ': 'HJ', 'CO': 'CO', 'BTN': 'BTN', 'SB': 'SB', 'BB': 'BB',
}


def _pos(tok):
    return _POS_WORD.get(tok, tok)


def _depth_phrase(s):
    """'20-40BB' -> '20-40BB', '10BB' -> '10BB', '100BB' -> '~100BB'."""
    m = re.search(r'(\d+(?:-\d+)?)BB', s)
    if not m:
        return ''
    d = m.group(1)
    return ('~100BB' if d == '100' else d + 'BB')


def chart_display_label(chart_id):
    """Return a human label for an internal chart id. Falls back to a
    title-cased, underscore-stripped form so nothing leaks raw."""
    if not chart_id or not isinstance(chart_id, str):
        return ''
    cid = chart_id.strip()

    # REJAM_<hero>vs<opener>[_NNBB]  -> "<hero> re-jam vs <opener> open[, NNBB]"
    m = re.match(r'REJAM_([A-Z0-9+]+)vs([A-Z0-9+]+?)(?:_(\d+BB))?$', cid)
    if m:
        depth = (', ' + m.group(3)) if m.group(3) else ''
        return f"{_pos(m.group(1))} re-jam vs {_pos(m.group(2))} open{depth}"

    # PUSH_<NN>BB_<pos> / JAM_<NN>BB_<pos> -> "<pos> open-shove, NNBB"
    m = re.match(r'(?:PUSH|JAM)_(\d+)BB_([A-Z0-9+]+)$', cid)
    if m:
        return f"{_pos(m.group(2))} open-shove, {m.group(1)}BB"

    # CALLJAM_<NN>BB_vs<pos> -> "call a <pos> jam, NNBB"
    m = re.match(r'CALLJAM_(\d+)BB_vs([A-Z0-9+]+)$', cid)
    if m:
        return f"call a {_pos(m.group(2))} jam, {m.group(1)}BB"

    # OPEN_<depth>_<pos>[_RAISE|_LIMP] -> "<pos> open[ (raise|limp)], <depth>"
    m = re.match(r'OPEN_([\dA-Z-]+?)_([A-Z0-9+]+?)(?:_(RAISE|LIMP))?$', cid)
    if m:
        depth = _depth_phrase('OPEN_' + m.group(1))
        sub = {'RAISE': ' raise', 'LIMP': ' limp'}.get(m.group(3), '')
        depth_txt = (', ' + depth) if depth else ''
        return f"{_pos(m.group(2))} open{sub}{depth_txt}"

    # BBD_<NN>BB_vs<pos> / BB_DEF_vs<...>  -> "BB defend vs <pos>[, NNBB]"
    m = re.match(r'BBD_(\d+)BB_vs([A-Z0-9+]+)$', cid)
    if m:
        return f"BB defend vs {_pos(m.group(2))}, {m.group(1)}BB"
    m = re.match(r'BB_DEF_vs([A-Za-z0-9]+)', cid)
    if m:
        return f"BB defend vs {m.group(1)}"

    # 3BF_<pos>/3BF_OOP  -> "3-bet-or-fold (<pos>)"
    m = re.match(r'3BF_([A-Z]+)$', cid)
    if m:
        return f"3-bet-or-fold ({m.group(1)})"
    # SQF_<...> -> "squeeze-or-fold"
    if cid.startswith('SQF_'):
        return 'squeeze-or-fold ' + cid[4:].replace('_', ' ')
    # DONK_LEAD / RIVER_BET_INTO_HERO / CBET_INTO_HERO_OOP -> readable
    _named = {
        'DONK_LEAD': 'donk-lead spot',
        'RIVER_BET_INTO_HERO': 'river bet into Hero',
        'CBET_INTO_HERO_OOP': 'c-bet into Hero (OOP)',
    }
    if cid in _named:
        return _named[cid]

    # Fallback: strip underscores, keep it readable (never raw-looking)
    return cid.replace('_', ' ').strip().lower()
