"""Auto Narrative Draft — generate session summary from computed stats.

Produces a first-draft session narrative the analyst can edit.
NOT a replacement for human analysis — a starting point that saves
30 minutes of manual synthesis.

Batch 6: auto narrative generation.
"""


def generate_session_narrative(stats, rd, hands):
    """Generate a draft session narrative from stats + report data.

    Returns a dict with:
      headline: one-line session summary
      session_read: multi-paragraph analysis draft
      key_takeaway: single most important coaching point
    """
    vol = stats.get('volume', {})
    n_hands = vol.get('hands', 0)
    n_tourneys = vol.get('tournaments', 0)
    dt = rd.get('discipline_tier', {})
    ra = rd.get('results_attribution', {})
    wl = rd.get('leak_watchlist', {})

    # Headline: result + discipline + key number
    _net_bb = stats.get('core', {}).get('bb_per_100', 0)
    _punts = dt.get('canonical_punts_count', 0)
    _mistakes = dt.get('canonical_mistakes_count', 0)
    _label = dt.get('label', 'Unknown')

    if _net_bb > 5:
        _tone = 'Strong'
    elif _net_bb > 0:
        _tone = 'Positive'
    elif _net_bb > -5:
        _tone = 'Break-even'
    elif _net_bb > -15:
        _tone = 'Losing'
    else:
        _tone = 'Rough'

    headline = (f"{_tone} session: {_net_bb:+.1f} BB/100 across {n_hands} hands "
                f"({n_tourneys} tournaments). "
                f"Discipline: {_label} ({_mistakes} mistakes, {_punts} punts).")

    # Session read: multi-paragraph
    paras = []

    # Para 1: Result overview
    _surface = ra.get('surface_bb_per_100', _net_bb)
    _true_ev = ra.get('implied_true_ev_extended_per_100')
    if _true_ev is not None:
        paras.append(
            f"Surface result {_surface:+.1f} BB/100. After variance adjustment, "
            f"implied true EV is {_true_ev:+.1f} BB/100. "
            f"{'Ran well — results overstate skill.' if _surface > (_true_ev or 0) + 3 else ''}"
            f"{'Ran poorly — results understate skill.' if _surface < (_true_ev or 0) - 3 else ''}"
        )
    else:
        paras.append(f"Surface result {_surface:+.1f} BB/100 across {n_hands} hands.")

    # Para 2: Discipline assessment
    if _mistakes <= 5 and _punts <= 1:
        paras.append(
            f"Discipline was clean: {_mistakes} confirmed mistakes and {_punts} punts. "
            f"No emotional control concerns detected.")
    elif _mistakes <= 15:
        paras.append(
            f"Discipline was adequate: {_mistakes} confirmed mistakes and {_punts} punts. "
            f"Review the mistake list for patterns.")
    else:
        paras.append(
            f"Discipline needs work: {_mistakes} confirmed mistakes and {_punts} punts. "
            f"Focus on reducing preflop errors first (biggest leverage).")

    # Para 3: Key leaks
    _red_metrics = [a for a in (wl.get('top_actions') or []) if a.get('status') == 'red']
    if _red_metrics:
        _leak_names = [a.get('label', '?') for a in _red_metrics[:3]]
        paras.append(
            f"Key leaks this session: {', '.join(_leak_names)}. "
            f"These metrics are outside target range and should be the focus "
            f"of pre-session drills.")

    # Para 4: Variance
    _tilt = stats.get('tilt_cascades', [])
    _suckouts = sum(1 for e in stats.get('eai', {}).get('hands', [])
                    if e.get('suckout') == 'against_hero')
    if _suckouts >= 3:
        paras.append(
            f"Variance was unfavorable: {_suckouts} suckouts against Hero. "
            f"These are not skill issues — file under bad luck.")
    if _tilt:
        paras.append(
            f"Possible tilt cascade detected: {len(_tilt)} spike(s) in mistake "
            f"density following big losses. Review decision quality after losses.")

    # Key takeaway
    if _red_metrics:
        _top = _red_metrics[0]
        key_takeaway = (f"Priority #1: {_top.get('label', '?')} — "
                        f"{_top.get('action', 'review and correct')}.")
    elif _mistakes > 10:
        key_takeaway = "Focus on reducing confirmed mistakes — review the S2.2 list."
    else:
        key_takeaway = "Clean session. Maintain current approach."

    return {
        'headline': headline,
        'session_read': '\n\n'.join(paras),
        'key_takeaway': key_takeaway,
    }
