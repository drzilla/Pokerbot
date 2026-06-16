"""Utility functions and constants for gem_report_draft."""

from gem_report_draft import _state

import gem_made_hands as mh
from collections import defaultdict

_CI_Z_DEFAULT = 1.645

# Hard floor: below this n, we refuse to compute CI and show the value
# without a color signal. At n < 10 even Wilson CI is wide enough that
# any classification is basically guessing.
_MIN_N_FOR_SIGNAL = 10


def _wilson_ci(x, n, z=1.645):
    """Wilson score interval for a binomial proportion.

    Returns (ci_low_pct, ci_high_pct) in percentage (0-100).
    Far more accurate than Wald (naive p ± z*SE) for small n or
    values near 0/100. Default z=1.645 corresponds to 90% CI.
    """
    if n <= 0:
        return (0.0, 100.0)
    # Defensive: a count can exceed its denominator upstream (a metric-scope
    # bug elsewhere). phat>1 makes phat*(1-phat) negative -> the sqrt returns
    # a complex number and the >/< comparisons crash. Clamp to [0,1] and
    # floor the variance term at 0 so the CI degrades gracefully instead.
    phat = min(1.0, max(0.0, x / n))
    denom = 1 + z*z / n
    center = (phat + z*z / (2*n)) / denom
    _var = phat * (1 - phat) / n + z*z / (4*n*n)
    margin = z * (max(0.0, _var) ** 0.5) / denom
    lo = max(0.0, (center - margin) * 100)
    hi = min(100.0, (center + margin) * 100)
    return (lo, hi)


def _clr_naive(val, low, high, invert=False):
    """Legacy point-estimate coloring (no sample info available).

    No longer the default — callers should pass n to get CI-aware signals.
    Kept for backward compat and non-percentage metrics.
    """
    if invert:
        if val <= high: return f'🟢 {val}'
        elif val <= high * 1.5: return f'🟡 {val}'
        else: return f'🔴 {val}'
    if low <= val <= high: return f'🟢 {val}'
    elif (low * 0.85 <= val < low) or (high < val <= high * 1.15): return f'🟡 {val}'
    else: return f'🔴 {val}'


def _clr(val, low, high, invert=False, n=None, x=None,
         min_n=_MIN_N_FOR_SIGNAL, z=_CI_Z_DEFAULT):
    """Color-code a value with Wilson CI when sample is sufficient.

    SEMANTICS:
      🟢 = CI fully inside target (or point in target)
      🔴 = CI fully outside target (confident out)
      🟡 = CI overlaps target boundary (ambiguous)
      ⚪ = no signal (n < min_n)
    """
    if val is None or val == '': return str(val)
    if n is None:
        return _clr_naive(val, low, high, invert)
    if n < min_n:
        return f'⚪ {val}'
    if not (0 <= val <= 100):
        return _clr_naive(val, low, high, invert)
    if x is None:
        x = val * n / 100.0
    ci_low, ci_high = _wilson_ci(x, n, z=z)
    RED_MARGIN_PP = 1.0
    if invert:
        if val <= high: return f'🟢 {val}'
        if ci_low > high + RED_MARGIN_PP: return f'🔴 {val}'
        return f'🟡 {val}'
    if low <= val <= high: return f'🟢 {val}'
    if val < low:
        if ci_high < low - RED_MARGIN_PP: return f'🔴 {val}'
        return f'🟡 {val}'
    if ci_low > high + RED_MARGIN_PP: return f'🔴 {val}'
    return f'🟡 {val}'


def _clr_min(val, target, n=None, x=None,
             min_n=_MIN_N_FOR_SIGNAL, z=_CI_Z_DEFAULT):
    """Color-code a 'higher-is-better' metric (one-sided threshold)."""
    if val is None or val == '': return ''
    if n is None:
        if val >= target: return f'🟢 {val}'
        elif val >= target * 0.8: return f'🟡 {val}'
        else: return f'🔴 {val}'
    if n < min_n:
        return f'⚪ {val}'
    if not (0 <= val <= 100):
        if val >= target: return f'🟢 {val}'
        elif val >= target * 0.8: return f'🟡 {val}'
        else: return f'🔴 {val}'
    if x is None:
        x = val * n / 100.0
    ci_low, ci_high = _wilson_ci(x, n, z=z)
    RED_MARGIN_PP = 1.0
    if val >= target: return f'🟢 {val}'
    if ci_high < target - RED_MARGIN_PP: return f'🔴 {val}'
    return f'🟡 {val}'


def _pctc(n, d):
    """Format as '50.0% (5/10)'."""
    if d == 0: return '0.0% (0/0)'
    return f'{n/d*100:.1f}% ({n}/{d})'


def _stat_signal(observed, target_low, target_high, n,
                 conf_z=_CI_Z_DEFAULT, one_sided_min=False):
    """Classify a stat as green/red/yellow/neutral with Wilson CI.

    Four-state semantics:
      'green'   = CI fully inside target range
      'red'     = CI fully outside target range
      'yellow'  = CI overlaps exactly one target boundary
      'neutral' = no signal (n < min_n, or CI too wide)
    """
    if n < _MIN_N_FOR_SIGNAL:
        return 'neutral'
    if not (0 <= observed <= 100):
        return 'neutral'
    RED_MARGIN_PP = 1.0
    if one_sided_min:
        if observed >= target_low:
            return 'green'
        x = observed * n / 100.0
        ci_low, ci_high = _wilson_ci(x, n, z=conf_z)
        if ci_high < target_low - RED_MARGIN_PP:
            return 'red'
        return 'yellow'
    if target_low <= observed <= target_high:
        return 'green'
    x = observed * n / 100.0
    ci_low, ci_high = _wilson_ci(x, n, z=conf_z)
    if observed < target_low:
        if ci_high < target_low - RED_MARGIN_PP:
            return 'red'
        return 'yellow'
    if ci_low > target_high + RED_MARGIN_PP:
        return 'red'
    return 'yellow'


# ============================================================
# RENDERER BODY (v7.35 I-XIII outline)
# ============================================================


# VERSION removed — canonical source is draft.py:VERSION
# ============================================================
# UNIVERSAL HELPERS
# ============================================================

# (_wilson_ci is defined at the top of this file as part of the
# back-compat helper block — same implementation. Don't redefine.)


def _verdict_ci(x, n, target_lo, target_hi, n_min=10):
    """CI-based verdict with sample-size gate.
    BUG-O FIX: 🟢 ONLY when point estimate is inside band.
    CI overlap without point-in-band → 🟡 (thin sample, not confirmed on-target).
    🔴 if point > 1 spread outside; 🟡 between; ⚪ if n<n_min."""
    if n < n_min:
        return "⚪"
    if n == 0:
        return "⚪"
    rate = 100.0 * x / n
    ci_lo, ci_hi = _wilson_ci(x, n)
    # BUG-O: point estimate must be IN band for green.
    # CI overlap alone is not enough (42.9% vs 65-85% was showing green).
    if target_lo <= rate <= target_hi:
        return "🟢"
    spread = target_hi - target_lo
    if rate < target_lo - spread or rate > target_hi + spread:
        return "🔴"
    return "🟡"


def _verdict_pct(rate, target_lo, target_hi, n=None, n_min=10):
    """Pct-based verdict (when raw count not available)."""
    if n is not None and n < n_min:
        return "⚪"
    if rate is None:
        return "⚪"
    try:
        v = float(rate)
    except (TypeError, ValueError):
        return "⚪"
    if target_lo <= v <= target_hi:
        return "🟢"
    spread = target_hi - target_lo
    if v < target_lo - spread or v > target_hi + spread:
        return "🔴"
    return "🟡"


def _new_badge(feature_id):
    """Return a [New] badge if the feature was added within the last 14 days.

    Feature dates are hardcoded here. After 14 days the badge auto-expires.
    To add a badge: add the feature_id + date to _NEW_FEATURES below.
    """
    from datetime import datetime, timedelta
    _NEW_FEATURES = {
        # CP23 features (2026-06-03)
        'board_texture':        '2026-06-03',
        'pot_odds_all':         '2026-06-03',
        'ip_oop_badge':         '2026-06-03',
        'villain_exploit':      '2026-06-03',
        'cbet_by_texture':      '2026-06-03',
        'ev_impact':            '2026-06-03',
        'counterexamples':      '2026-06-03',
        'metric_drilldown':     '2026-06-03',
        'what_to_study':        '2026-06-03',
        'sizing_tell':          '2026-06-03',
        'tilt_cascade':         '2026-06-03',
        'lucky_mistakes':       '2026-06-03',
        'overfold':             '2026-06-03',
        'what_if_folds':        '2026-06-03',
        'detector_calibration': '2026-06-03',
        'icm_flag':             '2026-06-03',
        'coaching_tree':        '2026-06-03',
        'stack_trajectory':     '2026-06-03',
        'recurring_patterns':   '2026-06-03',
        'coverage_stats':       '2026-06-03',
        'population_exploit':   '2026-06-03',
        'auto_narrative':       '2026-06-03',
        'defend_per_opener':    '2026-06-03',
        'watchlist_linked':     '2026-06-03',
        'bustout_table':        '2026-06-03',
        'missed_bluff':         '2026-06-03',
        # v8.1.0 features (2026-06-03)
        'issue_explorer':       '2026-06-03',
    }
    date_str = _NEW_FEATURES.get(feature_id)
    if not date_str:
        return ''
    try:
        added = datetime.strptime(date_str, '%Y-%m-%d')
        if datetime.now() - added <= timedelta(days=14):
            return (' <span class="new-badge">New</span>')
    except Exception:
        pass
    return ''


def _thin_sample_marker(n, threshold=20):
    """Batch 2 (R10): Return a tooltip marker if sample is small.
    Append to any rate cell: '42.0% ⓘ' where ⓘ has a tooltip 'n=8, thin sample'.
    Returns empty string for adequate samples."""
    if n is None or n >= threshold:
        return ''
    return f' <span data-tip="n={n} — thin sample" style="opacity:0.5">ⓘ</span>'


_RANK_ORD = {'A':14,'K':13,'Q':12,'J':11,'T':10,'9':9,'8':8,
             '7':7,'6':6,'5':5,'4':4,'3':3,'2':2}


_RANK_SEQ = '23456789TJQKA'


def _compress_pair_ranks(rank_chars):
    """Compress pair ranks into run notation: a run reaching AA → 'XX+',
    a bounded run → 'HH-LL', singletons as-is. Highest run first."""
    idx = sorted({_RANK_SEQ.index(r) for r in rank_chars if r in _RANK_SEQ})
    out, i = [], 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1:
            j += 1
        lo, hi = idx[i], idx[j]
        lo_r, hi_r = _RANK_SEQ[lo], _RANK_SEQ[hi]
        if hi == len(_RANK_SEQ) - 1:          # run reaches AA
            out.append(f"{lo_r}{lo_r}+")
        elif lo == hi:
            out.append(f"{lo_r}{lo_r}")
        else:
            out.append(f"{hi_r}{hi_r}-{lo_r}{lo_r}")
        i = j + 1
    out.reverse()
    return out


def _compress_nonpairs(combos, suit):
    """Compress suited/offsuit combos. For each high card, a kicker run that
    reaches the card just below the high card → 'HXs+'; bounded run →
    'HKhi-HKlo'; singletons as-is."""
    from collections import defaultdict
    by_hi = defaultdict(list)
    for c in combos:
        if len(c) == 3 and c[0] in _RANK_SEQ and c[1] in _RANK_SEQ:
            by_hi[c[0]].append(c[1])
    out = []
    for hi in sorted(by_hi, key=lambda r: -_RANK_SEQ.index(r)):
        hi_i = _RANK_SEQ.index(hi)
        kid = sorted({_RANK_SEQ.index(k) for k in by_hi[hi]})
        toks, i = [], 0
        while i < len(kid):
            j = i
            while j + 1 < len(kid) and kid[j + 1] == kid[j] + 1:
                j += 1
            lo, khi = kid[i], kid[j]
            lo_r, khi_r = _RANK_SEQ[lo], _RANK_SEQ[khi]
            if khi == hi_i - 1:               # kicker run reaches top
                toks.append(f"{hi}{lo_r}{suit}+")
            elif lo == khi:
                toks.append(f"{hi}{lo_r}{suit}")
            else:
                toks.append(f"{hi}{khi_r}{suit}-{hi}{lo_r}{suit}")
            i = j + 1
        toks.reverse()
        out.extend(toks)
    return out


def _compact_range(hands):
    """B150/B164 (Ron 2026-05-23/24): render a flat hand collection as a
    readable range grouped into Pairs / Suited / Offsuit, COMPRESSED into
    standard +/run notation (22+, ATs+, K9s-K6s) — never a full combo dump.
    Ron's rule: whenever a range is shown, it must be compressed."""
    pair_ranks, suited, offsuit = [], [], []
    for h in (hands or []):
        h = str(h).strip()
        if len(h) == 2 and h[0] == h[1]:
            pair_ranks.append(h[0])
        elif len(h) == 3 and h[2] == 's':
            suited.append(h)
        elif len(h) == 3 and h[2] == 'o':
            offsuit.append(h)
    parts = []
    if pair_ranks:
        parts.append('<strong>Pairs</strong> ' + ', '.join(_compress_pair_ranks(pair_ranks)))
    if suited:
        parts.append('<strong>Suited</strong> ' + ', '.join(_compress_nonpairs(suited, 's')))
    if offsuit:
        parts.append('<strong>Offsuit</strong> ' + ', '.join(_compress_nonpairs(offsuit, 'o')))
    return ' · '.join(parts) if parts else '—'


def _emit_correct_ranges(doc, group, dev_charts, hands_by_id=None):
    """B150: for a position-group of deviations, emit the correct range for
    each distinct chart the group references (sourced from s['_dev_charts']).
    All hands in a group at the same depth share a chart, so this is usually
    one or two lines, not one per hand.

    v8.14.1 REV4 (72807590): when a chart is used as a short-table PROXY for a
    hand whose real seat differs (gem_analyzer._open_chart_pos maps e.g. 7-max
    MP onto the HJ chart), label it "(short-table proxy)" so the "Correct range"
    line never reads as Hero's actual-seat range — matching the hand card's
    canonical Range-evidence block."""
    if not dev_charts:
        return
    seen = []
    for d in group:
        cn = d.get('chart')
        if cn and cn in dev_charts and cn not in seen:
            seen.append(cn)
    # v8.14.1 rev-4 (Blocker C): show the human chart label, not the raw id
    # (e.g. "CO open-shove, 10BB", not PUSH_10BB_CO).
    from gem_chart_labels import chart_display_label as _cdl_h
    for cn in seen:
        hands = dev_charts.get(cn) or []
        if not hands:
            continue
        label = _cdl_h(cn)
        if hands_by_id:
            for d in group:
                if d.get('chart') != cn:
                    continue
                _h = hands_by_id.get(d.get('id')) or {}
                _seat = _h.get('position')
                if _seat and d.get('pos') and _seat != d.get('pos'):
                    label += ' (short-table proxy)'
                    break
        doc.w(f"**Correct range — {label}** ({len(hands)} hand classes): "
              f"{_compact_range(hands)}")
        doc.w("")


_OUTCOME_LABELS = {
    'suckout':      ('🤢', 'Suckout'),
    'lost_flip':    ('🪙', 'Lost coin-flip'),
    'top_of_range': ('🪤', 'vs Top of range'),
    # B161 (Ron 2026-05-24): Hero's play was correct AND villain made a
    # clear -EV call against Hero's range (a snap-fold spot, often with
    # players still to act behind). Distinct from suckout/flip — those are
    # variance after a correct play; spew-called specifically credits the
    # villain's mistake. Still routes III.3 (Hero cleared).
    'spew_called':  ('🤡', 'Spew-called'),
    # B213 (Ron review 2026-05-25): two more outcome labels.
    # semi_bluff_cooler — Hero's aggressive line had genuine fold equity AND
    # genuine real equity (a semi-bluff that was correct in expectation), but
    # it ran into the part of villain's range it could not get through and
    # lost. Distinct from a pure cooler (no decision) — here Hero CHOSE the
    # aggression and the choice was right.
    'semi_bluff_cooler': ('🥶', 'Semi-bluff cooler'),
    # whale_harvest — a play that looks insane in a vacuum but was correct
    # because Hero had a concrete read on the villain (a whale / massively
    # off-range opponent) and was right about it. Credits the read.
    'whale_harvest':     ('🐋', 'Whale harvest'),
    # B240 (Ron review 2026-05-26, greenlit): equity-driven all-in
    # classification labels, auto-tagged off the gem_eai_equity numbers so a
    # III.3-cleared all-in says WHY it was cleared instead of a generic clear.
    #   dominating   — Hero a clear, large favourite who won (🦁)
    #   coin_flip    — Hero ~45-60%, a genuine race, who won (🪙)
    #   multiway_fav — Hero the field favourite in a multiway pot but at a
    #                  lower absolute equity (e.g. AQs 38% three-way), who won
    'dominating':   ('🦁', 'Dominating'),
    'coin_flip':    ('🪙', 'Coin-flip'),
    'multiway_fav': ('🥇', 'Field favourite (multiway)'),
}


def _outcome_label(cmt, default=('👍', 'cleared')):
    """B149 (Ron 2026-05-23): a III.3-cleared hand can carry an `outcome`
    sub-label describing WHY it lost — 🤢 Suckout (got it in a clear
    favorite), 🪙 Lost flip, 🪤 vs Top of range (correct action, ran into
    the strongest part of villain's range), 🤡 Spew-called (villain made a
    clear -EV call vs Hero's range). All still route to III.3; this only
    changes the emoji + word shown. Returns (emoji, text)."""
    if isinstance(cmt, dict):
        oc = (cmt.get('outcome') or '').strip().lower()
        if oc in _OUTCOME_LABELS:
            return _OUTCOME_LABELS[oc]
    return default


# B161 (Ron 2026-05-24): VII.11 aggression-gate verdict → (emoji, label).
# Surfaced on appendix hand headers so a hand's gate verdict is visible at
# a glance, and used to label VII.11 per-cell example entries.
_AGG_GATE_LABELS = {
    'MISSED_AGGRESSION':    ('🙈', 'Missed'),
    'AMBIGUOUS':            ('🤷\u200d♂️', 'Ambiguous'),
    'AMBIGUOUS_AGGRESSIVE': ('🤷\u200d♂️', 'Ambiguous'),
    'CORRECTLY_PASSIVE':    ('🛡️', 'Correctly Passive'),
    'CORRECTLY_AGGRESSIVE': ('🎯', 'Correctly Aggressive'),
    'TOO_AGGRESSIVE':       ('🌋', 'Too Aggressive'),
}


def _agg_candidates(hid, rd):
    """Return ALL VII.11 aggression-gate candidate dicts for a hand. A hand
    can legitimately be in two buckets (e.g. ambiguous flop + too-aggressive
    river); returning only the first mislabels the appendix header."""
    if not hid:
        return []
    agg = (rd or {}).get('aggression_analysis', {}) or {}
    short = hid[-8:]
    out = []
    for bucket in ('missed_aggression', 'ambiguous', 'correctly_passive',
                   'too_aggressive', 'ambiguous_aggressive',
                   'correctly_aggressive'):
        for c in agg.get(bucket, []) or []:
            cid = c.get('hand_id') or ''
            if cid == hid or cid[-8:] == short:
                out.append(c)
    return out


def _agg_candidate(hid, rd):
    """First aggression-gate candidate for a hand (back-compat), or None."""
    cands = _agg_candidates(hid, rd)
    return cands[0] if cands else None


def _agg_one_label(c):
    """(emoji, label) for a single VIII.11 aggression candidate. B201 (Ron
    2026-05-25, asked twice): drop the word 'gate' — it means nothing to the
    player. Label is now a plain street-led phrase: 'Missed flop aggression',
    'Too aggressive on the river', 'Correctly aggressive (turn)'."""
    base = (_AGG_GATE_LABELS.get((c.get('verdict') or '').upper())
            if isinstance(c, dict) else None)
    if not base:
        return ('', '')
    emoji, _ = base
    v = (c.get('verdict') or '').upper()
    st = (c.get('street_of_interest') or '').strip().lower() or 'flop'
    if v == 'MISSED_AGGRESSION':
        label = f"Missed {st} aggression"
    elif v == 'TOO_AGGRESSIVE':
        label = f"Too aggressive on the {st}"
    elif v in ('AMBIGUOUS', 'AMBIGUOUS_AGGRESSIVE'):
        label = f"Borderline {st} decision"
    elif v == 'CORRECTLY_PASSIVE':
        # v8.16.1 Bug-2a: if Hero CALLED a bet (xc/call) the passive verdict is
        # about not RAISING — say "call", not "check". Only a literal check (x)
        # is a "check".
        _raw_pa = ((c.get('hsa', {}) or {}).get(st, '') or '').lower() if isinstance(c, dict) else ''
        _pa_verb = 'call' if (_raw_pa in ('xc', 'call') or 'call' in _raw_pa) else 'check'
        label = f"Correct {_pa_verb} on the {st}"
    elif v == 'CORRECTLY_AGGRESSIVE':
        label = f"Correct aggression on the {st}"
    else:
        label = f"{st.capitalize()} aggression review"
    return (emoji, label)


def _agg_gate_label(hid, rd):
    """Return (emoji, label) for a hand's VII.11 verdict(s). If the hand is
    in multiple buckets every verdict is shown, joined by ' · ' — B164
    (Ron 2026-05-24): a hand flagged ambiguous-flop AND too-aggressive-river
    must not show just one. The emoji returned is the first verdict's; the
    label string carries all of them with their own emoji."""
    pieces = []
    for c in _agg_candidates(hid, rd):
        emoji, label = _agg_one_label(c)
        if label:
            pieces.append((emoji, label))
    if not pieces:
        return None
    if len(pieces) == 1:
        return pieces[0]
    # Multi-bucket: caller prints "{emoji} {label}", so the first piece
    # contributes only its label (its emoji is the returned emoji); the
    # rest carry their own emoji inside the label string.
    first_e, first_l = pieces[0]
    rest = ' · '.join(f"{e} {l}" for e, l in pieces[1:])
    return (first_e, f"{first_l} · {rest}")


_AGG_ACTION_WORDS = {
    'cbet': 'c-bet', 'xr': 'check-raise', 'check-raise': 'check-raise',
    'bet': 'bet', 'raise': 'raise', 'jam': 'jam', 'donk': 'donk-lead',
    'check': 'check', 'call': 'call', '3bet': '3-bet', '4bet': '4-bet',
    # v8.16.1 Bug-2a: all-in / B253 composite codes must map to readable words
    # — otherwise the raw code leaked into prose ("Borderline bet-callai on the
    # turn"). The over-aggression verdict grades the BET portion of a
    # bet-then-call(-allin) composite, so those render as "bet".
    'callai': 'call', 'xc-ai': 'check-call', 'xr-ai': 'check-raise',
    'bet-call': 'bet', 'bet-callai': 'bet', 'x': 'check',
}


def auto_verdict_needs_review(verdict, is_auto_verdict, agg_label):
    """v8.16.1 Bug-2b: an AUTO Mistake/Punt verdict must be corroborated by an
    action-level mistake marker. When the hand's only postflop action signal is
    the VIII.11 aggression gate label and it shows ONLY correct/borderline play
    (no 'Missed …' / 'Too aggressive …'), the auto III.1/III.2 contradicts the
    hand's own action review — downgrade it to *Review* rather than asserting an
    unconfirmed Mistake.

    Example: 78024888 — HH10#1 auto-flagged "continue mistake" (III.2) while the
    aggression review said "Correct check on the river · Borderline turn
    decision". No action marker = no confirmed mistake → Review.

    Scope / safety:
      • Only AUTO verdicts (is_auto_verdict) — an analyst's verdict is never touched.
      • Only when an aggression label is PRESENT. Preflop mistakes (Missed Steal,
        Hero folded preflop) and weak river call-downs have no aggression label,
        so they are left alone — their marker lives elsewhere.
      • A label containing 'missed' or 'too aggressive' IS an action-level mistake
        marker → the auto verdict is corroborated and kept.

    Pure / testable. `agg_label` is the label STRING (second element of the
    _agg_gate_label tuple), or '' / None when absent.
    """
    if not is_auto_verdict:
        return False
    v = (verdict or '')
    if not (v.startswith('III.2') or v.startswith('III.1')):
        return False
    lbl = (agg_label or '').lower()
    if not lbl:
        return False  # no postflop action label (e.g. preflop punt) — leave it
    return ('missed' not in lbl) and ('too aggressive' not in lbl)


def monotone_overcommit_lesson(board, hsa, net_bb=None, spr=None):
    """v8.13.1 P2: monotone-board over-commit SEQUENCE leak. When the flop is
    monotone (a flush is already possible), Hero CHECKED the flop (skipped cheap
    protection), then OVER-COMMITTED the turn (jam / big bet), the real leak is
    the SEQUENCE — not merely 'missed flop aggression'. The turn jam folds out
    worse hands and only gets called by flushes. Returns the corrected lesson,
    or '' if the pattern does not apply. Pure / testable.

    (2026-06-13: TM6072950898 AQ two-pair jam into a monotone Qc8c3c board lost
    -40BB and was framed as 'missed flop aggression' — the connected error is
    skipped cheap flop protection -> over-committed turn.)"""
    cards = ([str(x) for x in board] if isinstance(board, (list, tuple))
             else str(board or '').split())
    if len(cards) < 3:
        return ''
    suits = [c[1] for c in cards[:3] if len(c) >= 2]
    if len(suits) < 3 or len(set(suits)) != 1:
        return ''   # flop is not monotone
    hsa = hsa or {}
    flop_a = str(hsa.get('flop', '')).lower()
    turn_a = str(hsa.get('turn', '')).lower()
    # Hero did NOT bet the flop (checked / check-called), then committed big on
    # the turn (jam / all-in / bet / raise).
    flop_checked = (('x' in flop_a or 'check' in flop_a or 'call' in flop_a)
                    and not ('cbet' in flop_a or flop_a in ('b', 'bet', 'raise')))
    turn_overcommit = ('jam' in turn_a or 'allin' in turn_a or 'all-in' in turn_a
                       or turn_a in ('b', 'bet', 'raise', 'r'))
    if not (flop_checked and turn_overcommit):
        return ''
    return ("The leak is the sequence, not just missed flop aggression: you "
            "skipped cheap flop protection on a monotone (flush) board, then "
            "used the turn jam as the first protection action when SPR was "
            "already too low. Bet a small flop with no flush card, and do not "
            "pot-jam the turn — the jam folds out worse hands and gets called "
            "by flushes.")


def range_evidence_md(ev):
    """v8.14.1 P0-2: render a chart-backed 'Range evidence' block from the
    structured object built by gem_ranges.build_range_evidence(). The block's
    IN/OUTSIDE line is the SINGLE SOURCE OF TRUTH for range membership — prose
    that contradicts it is corrected/linted elsewhere. Discloses proxy/closest
    coverage explicitly (never presents an aliased/adjacent chart as exact) and
    counts in 'hand classes' (chart cells), not combos.
    """
    if not ev or not isinstance(ev, dict):
        return ''
    from gem_chart_labels import chart_display_label as _cdl
    hero = ev.get('hero_hand', '?')
    pos = ev.get('position', '?')
    depth = ev.get('depth_bb', 0) or 0
    basis = ev.get('depth_basis', '')
    spot = ev.get('spot_label', '')
    cov = ev.get('coverage', 'none')
    key = ev.get('chart_key')
    if not key or cov == 'none' or ev.get('membership') == 'unknown':
        _note = ev.get('note') or ('no exact chart exists for this '
                                    'position/depth (estimated/closest unavailable)')
        return (f"> **Range evidence — {spot}, {depth:.0f}BB ({basis}).** "
                f"{hero}: {_note}.")
    label = _cdl(key)
    # Coverage disclosure — proxy/closest are NEVER presented as exact.
    if cov == 'exact':
        ref = f"Reference: {label}."
    elif cov == 'proxy':
        ref = (f"Reference: **{label}** — closest available; no exact {pos} "
               f"chart at this depth, using it as a position proxy (an earlier "
               f"seat plays slightly tighter).")
    else:  # closest (adjacent depth tier)
        ref = (f"Reference: **{label}** — closest available depth; no exact "
               f"chart at {depth:.0f}BB.")
    inside = ev.get('membership') == 'inside'
    mtag = ('INSIDE' if inside else 'OUTSIDE')
    bnd = ' (boundary cell)' if ev.get('boundary') else ''
    tops = ', '.join(ev.get('top_examples') or [])
    bex = ev.get('boundary_examples') or ''
    n_cells_line = ''
    lines = [
        f"> **Range evidence — {spot}, {depth:.0f}BB ({basis}).**",
        f"> {ref}",
        f"> {hero}: **{mtag} the {label} range{bnd}.**",
    ]
    if tops:
        lines.append(f"> Includes (top hand classes): {tops}.")
    if bex:
        lines.append(f"> Boundary hand classes: {bex}.")
    return '\n'.join(lines)


def _hand_preflop_range_role(h):
    """Classify Hero's preflop decision into a chartable range role, or None.
    Mirrors gem_coverage_builder._hero_role using hand-record fields so the
    renderer and the worklist agree on the spot type."""
    if not isinstance(h, dict):
        return None
    pa = (h.get('pf_action') or '').lower()
    first_in = bool(h.get('first_in'))
    pf_allin = bool(h.get('pf_allin'))
    # A 3-bet/4-bet jam is a re-jam/over-jam, NOT a first-in open-shove, even
    # when the record marks first_in (e.g. 73559949 ATs 4bet+ overjam over a
    # short jam). Route those to rejam so the open-shove chart is not misapplied.
    is_reraise = ('3bet' in pa) or ('4bet' in pa) or bool(h.get('hero_3bet'))
    if pf_allin and first_in and not is_reraise:
        return 'open_shove'
    if pf_allin and is_reraise:
        return 'rejam'
    if pf_allin and h.get('villain_jammed') and not first_in and pa == 'call':
        return 'call_jam'
    if first_in and not pf_allin and pa in ('raise', 'jam', 'fold', '', 'open'):
        # first-in open OR a first-in fold (missed-steal) — both are RFI claims
        return 'rfi'
    return None


_RANGES_CACHE = None


def get_ranges_cached():
    """Load the chart range tables once per process (static data)."""
    global _RANGES_CACHE
    if _RANGES_CACHE is None:
        try:
            from gem_ranges import load_ranges as _lr
            _RANGES_CACHE = _lr() or {}
        except Exception:
            _RANGES_CACHE = {}
    return _RANGES_CACHE


def hand_range_evidence(h, ranges=None):
    """Build the chart-backed range-evidence object for a hand's preflop
    decision (or None). RFI uses Hero's own open depth; shove/call/rejam use the
    decision-effective stack. Pure wrapper over gem_ranges.build_range_evidence."""
    if ranges is None:
        ranges = get_ranges_cached()
    role = _hand_preflop_range_role(h)
    if not role or not ranges:
        return None
    try:
        from gem_ranges import build_range_evidence as _bre
    except Exception:
        return None
    _eff = h.get('eff_stack_bb_at_decision') or h.get('eff_stack_bb') or h.get('stack_bb') or 0
    return _bre(role, h.get('position', '?'), h.get('cards', []),
                h.get('stack_bb') or 0, _eff, ranges,
                jammer_pos=(h.get('jammer_position') or h.get('opener_position') or ''),
                opener_pos=(h.get('opener_position') or ''))


def _agg_commentary(c):
    """One-line actionable read for a VII.11 candidate: which action, what
    should have happened, and why (failed-gate reasons). Shared by VII.11
    and the appendix hand-detail so a marked hand carries the same read in
    both places — B161 (Ron 2026-05-24)."""
    if not isinstance(c, dict):
        return ''
    verdict = (c.get('verdict') or '').upper()
    st = c.get('street_of_interest', 'flop')
    hsa = c.get('hsa', {}) or {}
    act = _AGG_ACTION_WORDS.get((hsa.get(st) or '').lower(),
                                (hsa.get(st) or '').lower() or 'action')
    gates = c.get('gates', {}) or {}
    failed = [g.get('reason', f'gate {gn}')
              for gn, g in sorted(gates.items())
              if isinstance(g, dict) and not g.get('pass')]
    rec = (c.get('recommended_action') or '').strip().rstrip('.')
    # B196 (Ron 2026-05-25): plain-language verdict lines. The "5 gates" are
    # internal scoring machinery — Ron asked to be told what to DO, in player
    # terms, not how many gates passed. The 5 checks, in plain words, are:
    # strong-enough hand · board favours betting · villain's range pays ·
    # the spot is value/mixed (not pure exploit) · a worse hand calls.
    # v8.13.1 P2: monotone-board over-commit takes precedence — the leak is the
    # sequence (skipped cheap flop protection -> over-committed turn), not
    # merely "missed flop aggression".
    _mono_lesson = monotone_overcommit_lesson(c.get('board'), hsa, c.get('net_bb'))
    if _mono_lesson:
        lead = _mono_lesson
    elif verdict == 'MISSED_AGGRESSION':
        lead = (f"Clear missed value-bet on the {st}: you had a strong "
                f"enough hand, the board and villain's range both favoured "
                f"betting, and worse hands would have paid. {act.capitalize()} "
                f"→ should have bet.")
    elif verdict == 'TOO_AGGRESSIVE':
        lead = (f"Over-aggressive {act} on the {st} — too many of the "
                f"value-bet conditions were missing here. Better line: "
                f"check/call, or bet much smaller.")
    elif verdict == 'AMBIGUOUS_AGGRESSIVE':
        lead = (f"Borderline {act} on the {st} — one value-bet condition is "
                f"shaky, so a smaller size or a check is equally defensible.")
    elif verdict == 'AMBIGUOUS':
        lead = (f"Borderline check on the {st} — betting and checking are "
                f"both fine here; one value-bet condition is shaky.")
    elif verdict == 'CORRECTLY_AGGRESSIVE':
        lead = f"The {st} {act} was the correct aggressive line."
    elif verdict == 'CORRECTLY_PASSIVE':
        # v8.16.1 Bug-2a: when Hero CALLED a bet (xc/call), the passive verdict
        # is about not RAISING, not about checking — say so. Only a literal
        # check (x) gets "Checking … was correct".
        _raw_pa2 = (hsa.get(st) or '').lower()
        if _raw_pa2 in ('xc', 'call') or 'call' in _raw_pa2:
            lead = (f"Calling the {st} was correct — raising for value "
                    f"wasn't justified here.")
        else:
            lead = (f"Checking the {st} was correct — a bet wasn't justified "
                    f"here.")
    else:
        lead = rec or 'See detail.'
    # BUG-11 (Ron review 2026-05-31): enumerate value-bet conditions
    # explicitly — each gate's pass/fail with its reason. The analyst must
    # see WHICH conditions were met/missing, not just "conditions missing."
    _GATE_NAMES = {
        1: 'Hand strength',
        2: 'Board texture',
        3: 'Villain range',
        4: 'Decision axis',
        5: 'Worse hand calls',
    }
    if verdict in ('TOO_AGGRESSIVE', 'CORRECTLY_PASSIVE',
                   'AMBIGUOUS', 'AMBIGUOUS_AGGRESSIVE') and gates:
        # Show which conditions failed
        cond_parts = []
        for gn in sorted(gates.keys()):
            g = gates[gn]
            if not isinstance(g, dict):
                continue
            # BUG-I: gate keys may be strings ("1") or ints (1) — normalize
            _gn_int = int(gn) if str(gn).isdigit() else gn
            gname = _GATE_NAMES.get(_gn_int, _GATE_NAMES.get(gn, f'Condition {gn}'))
            if g.get('pass'):
                cond_parts.append(f"<span class='cond-pass'>✓ {gname}</span>")
            else:
                reason = g.get('reason', '')
                # BUG-I / v8.8.6 B5: scrub internal jargon → plain English
                reason = reason.split(' — ')[0] if ' — ' in reason else reason
                for _sfx in ('_PREFLOP', '_FLOP', '_TURN', '_RIVER'):
                    reason = reason.replace(_sfx, '')
                # Map raw detector tokens to plain-English descriptions
                _reason_map = {
                    'HERO_AGGRESSIVE': 'villain may not call with enough worse hands',
                    'CORRECTLY_PASSIVE': 'checking was correct here',
                    'TOO_AGGRESSIVE': 'hero was over-aggressive',
                    'MISSED_AGGRESSION': 'missed a betting opportunity',
                    'UNKNOWN': 'insufficient evidence to determine',
                }
                _mapped = False
                for _tok, _plain in _reason_map.items():
                    if _tok in reason:
                        reason = _plain
                        _mapped = True
                        break
                if not _mapped:
                    reason = (reason.replace('Context ', '')
                             .replace(' unclear', ' — uncertain'))
                cond_parts.append(f"<span class='cond-fail'>✗ {gname}: {reason[:80]}</span>")
        if cond_parts:
            return lead + " Conditions: " + " · ".join(cond_parts) + "."
        return lead
    # For other verdicts, surface failed-check reasons (plain-language only)
    plain_failed = [f for f in failed
                    if 'unclear' not in f.lower()
                    and 'context ' not in f.lower()
                    and 'axis' not in f.lower()]
    if plain_failed:
        return lead + " Why: " + "; ".join(plain_failed[:2]) + "."
    return lead


def _run_emoji(actual, expected, higher_is_luckier=True, rel_threshold=0.20):
    """B147 (Ron 2026-05-23): run-hot / run-cold marker for variance metrics.

    Distinct from the 🟢/🟡/🔴 in-range verdict — that says "are you playing
    a correct frequency", this says "did the cards run for or against you".
    🔥 = ran hot (lucky), 🥶 = ran cold (unlucky), '' = near expectation.

    higher_is_luckier: True for made-hands / card-quality / EAI (more = lucky);
    False for cooler frequency (fewer coolers = lucky).
    """
    try:
        a, e = float(actual), float(expected)
    except (TypeError, ValueError):
        return ''
    if e == 0:
        return ''
    rel = (a - e) / abs(e)
    if not higher_is_luckier:
        rel = -rel
    if rel >= rel_threshold:
        return ' 🔥'
    if rel <= -rel_threshold:
        return ' 🥶'
    return ''


def _hand_ref(h):
    """CANONICAL hand citation. Use EVERYWHERE.
    Format: `id` • Tournament (date) • Pos StackBB

    B43 (v7.44): if the hand is in the current appendix set
    (_APPENDIX_HAND_IDS module var, set by render_md), the id-suffix is
    wrapped in a markdown link to its appendix anchor — making every hand
    reference a one-click jump to the full HH detail.
    """
    if not isinstance(h, dict):
        return str(h)
    hid = h.get('id', '?')
    hid_short = hid[-8:] if isinstance(hid, str) and len(hid) > 8 else hid
    tour = h.get('tournament', '—')
    if len(tour) > 32:
        tour = tour[:30] + "…"
    # B-V15: escape markdown-significant [] in tournament names AFTER truncation.
    # Unescaped brackets cause _md_inline's link regex to mis-pair across refs.
    tour = tour.replace('[', '\\[').replace(']', '\\]')
    date = h.get('date', '—')
    pos = h.get('position', h.get('pos', '—'))
    stack = h.get('stack_bb', h.get('stack', 0))
    try:
        stack_str = f"{float(stack):.0f}BB"
    except (TypeError, ValueError):
        stack_str = str(stack)
    # B43 + B-V10 STRUCTURAL: ALWAYS link to appendix when the ID is a
    # valid TM hand. The structural harvest guarantees every TM ID in
    # stats/rd gets an appendix card, so there's no reason NOT to link.
    # Also auto-add to the appendix set to ensure the card gets built.
    if isinstance(hid, str) and (hid.startswith('TM') or hid_short.isdigit()):
        _state._APPENDIX_HAND_IDS.add(hid)
        _state._register_hand_priority(hid, 2)  # P2: generic metric ref
        id_cell = f"[`{hid_short}`](#sec-app-hand-{hid_short})"
    else:
        id_cell = f"`{hid_short}`"
    # F2 (v7.49): register citation from current section for back-link emission
    _state._record_citation(hid)
    return f"{id_cell} • {tour} ({date}) • {pos} {stack_str}"


# B43 (v7.44): module-level appendix-hand-id set, populated by render_md
# before any sections are emitted. Read by _hand_ref to decide whether to
# wrap the id-suffix in a markdown link to the appendix anchor.
def _compute_pot_by_street(actions_dict, h):
    """F1 (v7.49, Ron 2026-05-13): compute pot size in BB at the START of
    each street. Returns dict {'preflop': X, 'flop': Y, 'turn': Z, 'river': W}.

    Pot tracking:
      - Preflop opens with SB + BB + (n_players × ante).
      - Each call/bet adds its amount_bb delta to running pot.
      - Each "raises X to Y" adds (Y − previous_commit_by_this_player_on_street)
        because amount_bb is the "to" total, not the delta.
      - Streets snapshot the running pot at street-end (= next-street start).

    h is the hand dict (used for sb_blind, bb_blind, ante, n_players when
    those help reconstruct the preflop start pot). actions_dict is the
    {street: [action_dicts]} structure from app_details['actions'].
    """
    bb = h.get('bb_blind') or 1
    sb = h.get('sb_blind') or (bb / 2)
    ante = h.get('ante') or 0
    n_players = h.get('n_players') or len(h.get('seat_stacks_bb') or []) or 8

    # Preflop start: SB + BB + total antes. Convert chips → BB.
    pot_start_chips = sb + bb + (ante * n_players)
    pot_start_bb = pot_start_chips / bb if bb else 0

    pots = {'preflop': pot_start_bb, 'flop': 0.0, 'turn': 0.0, 'river': 0.0}
    running = pot_start_bb

    ante_bb = (ante / bb) if bb else 0
    for street in ('preflop', 'flop', 'turn', 'river'):
        commit_on_street = {}  # name → cumulative BB committed on this street
        # v8.12.8 QA-GPT P0.1: the ledger stores a raise's INCREMENT over
        # the current bet (GG prints "raises X to Y", the parser keeps X),
        # but this walk treated it as the "to" total — every re-raised
        # street under-counted (66662469 rendered "76.3 BB pot" on a turn
        # whose true start is 115.0; this walk now reproduces GG's own
        # Total-pot line, 240.1, exactly). Track the current bet, convert
        # increments to totals, charge the raiser the full catch-up delta.
        # Blind posts seed the commit map (their chips are in pot_start
        # already); antes are skipped (GG bet-matching excludes them).
        current_bet = 1.0 if street == 'preflop' else 0.0
        for a in actions_dict.get(street, []) or []:
            name = a.get('name', '?')
            act = a.get('action', '')
            amt = a.get('amount_bb', 0) or 0
            if act == 'posts':
                if ante_bb and abs(amt - ante_bb) < 1e-6:
                    continue  # ante — not bet-matching commitment
                commit_on_street[name] = commit_on_street.get(name, 0) + amt
                continue
            if act in ('folds', 'checks'):
                continue
            elif act in ('calls', 'bets'):
                # amount_bb is the delta (chips committed by this action)
                running += amt
                commit_on_street[name] = commit_on_street.get(name, 0) + amt
                if act == 'bets':
                    current_bet = commit_on_street[name]
            elif act == 'raises':
                # amount_bb = increment; new street total = current_bet + amt
                new_total = current_bet + amt
                delta = max(0, new_total - commit_on_street.get(name, 0))
                running += delta
                commit_on_street[name] = new_total
                current_bet = new_total
        # UNCALLED-BET CORRECTION (A3, Aviel handoff 2026-05-25): the running
        # sum credits every chip committed on the street, but the uncalled
        # portion of the last aggressive action is returned, not collected.
        # Without this, the pot on the street AFTER an under-called all-in is
        # overstated. uncalled = top street-commit minus second-highest (full
        # bet when only one player put chips in). POSTFLOP ONLY: preflop
        # forced blinds are not tagged in commit_on_street, so a max-2nd
        # comparison would misfire; a genuine preflop uncalled bet also ends
        # the hand (no flop follows), so the flop snapshot is unaffected.
        if street != 'preflop' and commit_on_street:
            _commits = sorted(commit_on_street.values(), reverse=True)
            _uncalled = _commits[0] - (_commits[1] if len(_commits) >= 2 else 0)
            running -= _uncalled
        # Snapshot pot at end of this street (= start of next street)
        if street == 'preflop':
            pots['flop'] = running
        elif street == 'flop':
            pots['turn'] = running
        elif street == 'turn':
            pots['river'] = running

    return pots


def _render_action_lines(actions, doc):
    """v7.45 (Ron 2026-05-11, item C): render a list of action dicts as
    colored <span> lines with fold-run compression. Used by both XIV.A
    (per-street layout) and XIV.B (preflop-only stub). actions is a list of
    {position, stack_bb, action, amount_bb, all_in, is_hero} dicts."""
    i = 0
    while i < len(actions):
        if actions[i]['action'] == 'folds' and not actions[i].get('is_hero'):
            j = i
            fold_positions = []
            while (j < len(actions)
                   and actions[j]['action'] == 'folds'
                   and not actions[j].get('is_hero')):
                fold_positions.append(actions[j]['position'])
                j += 1
            if len(fold_positions) >= 2:
                doc.w(f'<span class="action-fold">— folds: '
                      f'{", ".join(fold_positions)}</span>')
                i = j
                continue
        a = actions[i]
        p, stk, amt, act, allin, is_h = (a['position'], a.get('stack_bb',0),
                                         a.get('amount_bb',0), a['action'],
                                         a.get('all_in',False), a.get('is_hero',False))
        if act == 'folds':
            cls = 'action-fold'; line = f'{p}({stk:.0f}BB) · fold'
        elif act == 'checks':
            cls = 'action-fold'; line = f'{p}({stk:.0f}BB) · check'
        elif act == 'calls':
            cls = 'action-call'; line = f'{p}({stk:.0f}BB) · calls {amt:.1f}BB'
        elif act == 'bets':
            cls = 'action-bet'; line = f'{p}({stk:.0f}BB) · bets {amt:.1f}BB'
        elif act == 'raises':
            if allin:
                cls = 'action-allin'; line = f'{p}({stk:.0f}BB) · ⚡ JAM {amt:.1f}BB all-in'
            else:
                cls = 'action-raise'; line = f'{p}({stk:.0f}BB) · raises to {amt:.1f}BB'
        else:
            cls = ''; line = f'{p}({stk:.0f}BB) · {act} {amt:.1f}BB'
        if is_h:
            cls = cls + ' action-hero'
            line = f'<strong>→ {line} ← HERO</strong>'
        doc.w(f'<span class="{cls}">{line}</span>')
        i += 1


def _street_cards(board, street):
    """Return the cards visible at street start (cumulative)."""
    if not board: return []
    if street == 'preflop': return []
    if street == 'flop':  return board[:3]
    if street == 'turn':  return board[:4]
    if street == 'river': return board[:5]
    return board


def _break_at_sentences(text, prefix='', max_sentence_len=180):
    """v7.45 (Ron 2026-05-11): break long prose at sentence boundaries with
    paragraph breaks for HTML scannability. Long blocks of analyst commentary
    were rendering as wall-of-text; this splits on '. ' boundaries and
    emits each sentence as its own paragraph.

    Returns a markdown-formatted string. Optional prefix prepended to first
    sentence (e.g. '*Reasoning:*').

    Short content (single sentence < max_sentence_len) returns as-is.
    """
    if not text:
        return prefix
    text = text.strip()
    # Split on '. ' but preserve the period
    # Also handle '? ' and '! ' as sentence boundaries
    import re as _re
    parts = _re.split(r'(?<=[.!?])\s+(?=[A-Z(])', text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) <= 1:
        # Single-sentence block — keep inline
        return f"{prefix} {text}" if prefix else text
    # Multi-sentence — first sentence with prefix, then each as its own line
    lines = []
    first = parts[0]
    if prefix:
        lines.append(f"{prefix} {first}")
    else:
        lines.append(first)
    for p in parts[1:]:
        lines.append("")  # blank line to force paragraph break
        lines.append(p)
    return "\n".join(lines)


def _emit_analyst_judgment(doc, judgment):
    """B169 (Ron 2026-05-24, anti-blob spec): emit a leak's analyst judgment.

    Per the Analyst Writing Checklist, judgment text is now authored as
    structured anti-blob markdown (emoji-callout paragraphs + bold anchors).
    A structured judgment (multi-line) is emitted verbatim under a bold
    lead-in; a legacy single-paragraph blob still falls back to
    sentence-splitting so old session files keep rendering."""
    judgment = (judgment or '').strip()
    if not judgment:
        return
    if '\n' in judgment:
        doc.w("**Analyst judgment:**")
        doc.w("")
        for ln in judgment.split('\n'):
            doc.w(ln)
    else:
        doc.w(_break_at_sentences(judgment, prefix='**Analyst judgment:**'))


def _href(d, hands_by_id=None):
    """Smart wrapper around _hand_ref: if entity has just `id` but missing
    tournament/date/position/stack, looks them up in hands_by_id and merges.

    Use this for deviation entries, sizing-deviation entries, etc. that come
    from analyzer subsystems that don't carry full hand metadata.
    """
    if not isinstance(d, dict):
        return str(d)
    hid = d.get('id', '')
    base = {
        'id': hid,
        'tournament': d.get('tournament'),
        'date': d.get('date'),
        'position': d.get('position', d.get('pos')),
        'stack_bb': d.get('stack_bb', d.get('stack')),
    }
    # Fill in missing fields from full-hand lookup
    if hands_by_id and hid in hands_by_id:
        full = hands_by_id[hid]
        for k, fk in [('tournament','tournament'), ('date','date'),
                       ('position','position'), ('stack_bb','stack_bb')]:
            if not base.get(k):
                base[k] = full.get(fk)
    # Defaults
    for k, default in [('tournament','—'), ('date','—'),
                        ('position','—'), ('stack_bb', 0)]:
        if base.get(k) is None:
            base[k] = default
    return _hand_ref(base)


def _hand_ref_id_only(h):
    """Minimal citation: just the linked hand ID pill, no tournament/date.
    Used in bustout table where tournament is already in a separate column."""
    if not isinstance(h, dict):
        return str(h)
    hid = h.get('id', '?')
    hid_short = hid[-8:] if isinstance(hid, str) and len(hid) > 8 else hid
    # Register in appendix + citation system
    if hid and hid.startswith('TM'):
        _state._APPENDIX_HAND_IDS.add(hid)
        _state._register_hand_priority(hid, 2)  # P2: generic inline ref
        _state._record_citation(hid)
    # Link to appendix
    if hid in _state._APPENDIX_HAND_IDS:
        return f"[`{hid_short}`](#sec-app-hand-{hid_short})"
    return f"`{hid_short}`"


def _hand_ref_short(h):
    """Compact citation for dense table cells.
    Format: id-suffix tour-short (date)"""
    if not isinstance(h, dict):
        return str(h)
    hid = h.get('id', '?')
    hid_short = hid[-8:] if isinstance(hid, str) and len(hid) > 8 else hid
    tour = h.get('tournament', '—')
    short = (tour.replace(' Thursday Heater', '')
                 .replace(' [Bounty Turbo 6-Max]', '')
                 .replace(' [Bounty Hyper 5-Max]', '')
                 .replace(' [Bounty Hyper]', '')
                 .replace(' [Rush]', '')
                 .replace(' Special', '')
                 .replace(', 50K GTD', '')
                 .replace(', 40K GTD', ''))
    if len(short) > 22:
        short = short[:20] + "…"
    date = h.get('date', '—')
    return f"`{hid_short}` {short} ({date})"


def _xref(section_id, label=None, icon=False):
    """Cross-section reference link.

    Returns MD-style `[label](#anchor)` which is preserved in the .md output and
    converted to `<a class="xref" href="#anchor">label</a>` in the .html output
    via _md_inline. Use everywhere we currently emit plain text "see I.7" /
    "III.4 review" so navigation works in both formats.

    section_id : str  — anchor target, e.g. "sec-i-7", "sec-iii-4",
                        or Phase 4 Arabic "sec-8-3"
    label      : str  — display text. If None, derived from section_id:
                        "sec-iii-4"  -> "III.4"
                        "sec-8-3"    -> "S8.3"   (Phase 4 Arabic)
                        "sec-iii-2-1" -> "III.2.1"
    icon       : bool — when True, append ↗ after the label so the link is
                        visible without coloring the prose itself.
    """
    if label is None:
        # sec-iii-4 -> [iii, 4] -> "III.4"
        # sec-i -> [i] -> "I"
        # Phase 4 Arabic: sec-8-3 -> [8, 3] -> "S8.3"
        parts = section_id.replace("sec-", "").split("-")
        if parts and parts[0].isdigit():
            # Phase 4 Arabic anchor: sec-8-3 -> "S8.3"
            rest = ".".join(parts[1:]) if len(parts) > 1 else ""
            label = f"S{parts[0]}.{rest}" if rest else f"S{parts[0]}"
        else:
            roman_part = parts[0].upper() if parts else ""
            rest = ".".join(parts[1:]) if len(parts) > 1 else ""
            label = f"{roman_part}.{rest}" if rest else roman_part
    if icon:
        label = f"{label} ↗"
    return f"[{label}](#{section_id})"


def _register_hids_for_appendix(hids, cap=50, priority=2):
    """Register hand IDs in the appendix set so they get cards built.
    Call this for EVERY hand-list-trigger data-hids emission.
    priority: 0=P0 must, 1=P1 should, 2=P2 optional, 3=P3 id-only.
    Returns the capped list of IDs (for use in data-hids CSV).
    """
    selected = list(hids)[:cap]
    for hid in selected:
        if isinstance(hid, str) and (hid.startswith('TM') or hid.replace('-','').isdigit()):
            _state._APPENDIX_HAND_IDS.add(hid)
            _state._register_hand_priority(hid, priority)
    return selected


def _popup_example_ids(pool_ids, want=5, cap=20, backfill_ids=None, priority=2):
    """Return up to `cap` IDs from pool_ids, with optional backfill.

    FEAT-C: if primary pool has < `want` IDs, backfill from `backfill_ids`
    (same-category wider pool) until `want` is reached. Backfill IDs are
    appended after primary IDs.

    priority: 0=P0 must, 1=P1 should, 2=P2 optional, 3=P3 id-only.

    Every returned ID is registered in the global appendix set so
    the popup JS can find the hand card.
    """
    # v8.6.1: dedupe IDs to prevent duplicate hand-list entries and inflated counts
    _seen = set(); _deduped = []
    for _pid in pool_ids:
        if _pid not in _seen:
            _seen.add(_pid); _deduped.append(_pid)
    selected = _deduped[:cap]
    # FEAT-C: backfill from wider pool if primary pool is thin
    if backfill_ids and len(selected) < want:
        _primary_set = set(selected)
        for _bf in backfill_ids:
            if _bf not in _primary_set:
                selected.append(_bf)
                _primary_set.add(_bf)
                if len(selected) >= want:
                    break
    selected = selected[:cap]
    for hid in selected:
        if isinstance(hid, str) and hid.startswith('TM'):
            _state._APPENDIX_HAND_IDS.add(hid)
            _state._register_hand_priority(hid, priority)
    return selected


def _clickable_count(count, ids, title, stats=None, id_key=None):
    """Make a count cell clickable if hand IDs exist.

    Args:
        count: the number to display
        ids: list of hand IDs (or None)
        title: popup title
        stats: optional stats dict to look up IDs from popup_hand_ids
        id_key: key in stats['popup_hand_ids'] to use

    Returns HTML string: either a clickable <a> or plain count text.
    """
    if ids is None and stats and id_key:
        ids = (stats.get('popup_hand_ids') or {}).get(id_key, [])
    if not ids or count == 0:
        return str(count)
    sel = _popup_example_ids(ids)
    hids_str = ','.join(sel)
    t = _popup_title_with_count(title, len(ids))
    return (f'<a class="hand-list-trigger" href="#" '
            f'data-hids="{hids_str}" '
            f'data-list-title="{t}">{count}</a>')


def _popup_title_with_count(base_title, pool_size, want=5):
    """Append '— only N this session' when pool is small."""
    if pool_size < want:
        return f"{base_title} — only {pool_size} this session"
    return base_title


def _stat_row(name, x, n, target_lo, target_hi, notes="", n_min=10, link_to=None, aim=None):
    """Universal stat-row renderer — §3 metric_status grammar.
    Returns: | Metric | Status | Value/Rate ⓘ | Target | Delta | Sample | Notes |

    CI rendered as ⓘ tooltip (HTML hover) / (CI 90%: lo-hi%) plaintext (MD).
    Delta = (Value/Target − 1) as %, not pp. Zero midpoint → "—".

    B70 (v7.49, Ron 2026-05-12): optional link_to (section anchor id) wraps
    the metric name as a link to its detail section. Bidirectional — detail
    sections render a 'back to KPIs' link via _back_to_kpis().

    B42 (v7.50, Ron 2026-05-17): optional aim (string) appends a watchlist-
    derived empirical-aim annotation to the target column, e.g.
    "6-12% · aim ≥9.6". Lets the row carry both the pool baseline band AND
    the Ron-cohort top-quartile aim in one cell.
    """
    name_cell = f"[{name}](#{link_to})" if link_to else name
    target_cell = f"{target_lo}-{target_hi}%"
    if aim:
        target_cell = f"{target_cell} · {aim}"
    if n == 0 or n is None:
        return f"| {name_cell} | ⚪ | — | {target_cell} | — | — | {notes} |"
    rate = 100.0 * x / n
    ci_lo, ci_hi = _wilson_ci(x, n)
    verdict = _verdict_ci(x, n, target_lo, target_hi, n_min=n_min)
    ci_tip = f'<span class="ci-tip" title="CI 90%: {ci_lo:.0f}-{ci_hi:.0f}%">ⓘ</span>'
    _tsm = _thin_sample_marker(n)  # Batch 2: dim if n < 20
    midpoint = (target_lo + target_hi) / 2
    # Item 4: delta as % of target midpoint (Value/Target − 1), not pp
    delta_str = f"{(rate / midpoint - 1) * 100:+.0f}%" if midpoint else "—"
    return (f"| {name_cell} | {verdict} | {rate:.1f}% {ci_tip}{_tsm} | "
            f"{target_cell} | {delta_str} | n={n} | {notes} |")


def _stat_row_pct(name, pct, n, target_lo, target_hi, notes="", n_min=10, link_to=None, aim=None):
    """When only pct + n known (no x). Synthesizes x for CI.
    §3 metric_status grammar — same 7-col output as _stat_row.
    B42: same aim annotation support as _stat_row."""
    name_cell = f"[{name}](#{link_to})" if link_to else name
    target_cell = f"{target_lo}-{target_hi}%"
    if aim:
        target_cell = f"{target_cell} · {aim}"
    if n is None or n == 0:
        return f"| {name_cell} | ⚪ | — | {target_cell} | — | — | {notes} |"
    x = round(pct * n / 100)
    ci_lo, ci_hi = _wilson_ci(x, n)
    verdict = _verdict_ci(x, n, target_lo, target_hi, n_min=n_min)
    ci_tip = f'<span class="ci-tip" title="CI 90%: {ci_lo:.0f}-{ci_hi:.0f}%">ⓘ</span>'
    midpoint = (target_lo + target_hi) / 2
    # Item 4: delta as % of target midpoint (Value/Target − 1), not pp
    delta_str = f"{(pct / midpoint - 1) * 100:+.0f}%" if midpoint else "—"
    return (f"| {name_cell} | {verdict} | {pct:.1f}% {ci_tip} | "
            f"{target_cell} | {delta_str} | n={n} | {notes} |")


def _aim_lookup_from_watchlist(rd):
    """B42 (v7.50, Ron 2026-05-17): build a {metric_key: short_aim_label} map
    from the leak watchlist. Used by KPI rows to surface watchlist aim
    alongside the pool-baseline target band.

    Returns dict like {'ThreeBet': '≥9.6 aim', 'AF': '≥2.7 aim', ...}.
    Short labels keep table rows readable; full target_range is in the
    Watchlist section."""
    out = {}
    wl = (rd or {}).get('leak_watchlist', {}) if isinstance(rd, dict) else {}
    metrics = wl.get('session_metrics', []) if isinstance(wl, dict) else []
    for m in metrics:
        if not isinstance(m, dict): continue
        key = m.get('metric')
        if not key: continue
        # Pull aim threshold from p75/top_avg depending on direction
        direction = m.get('direction', 'higher')
        p75 = m.get('p75')
        p25 = m.get('p25')
        # Use the boundary that matters: higher-is-better → p75 (cross to top quartile);
        # lower-is-better → p25 (cross under top quartile).
        if direction == 'higher' and p75 is not None:
            out[key] = f"≥{p75:.1f} aim"
        elif direction == 'lower' and p25 is not None:
            out[key] = f"≤{p25:.1f} aim"
    return out





def _back_to_kpis(doc):
    """B70 (v7.49): emit a compact 'back to KPIs' link at the top of a
    detail subsection. Companion to link_to= on _stat_row helpers.

    Phase 4: anchor will change from sec-ii-2 to sec-6-2 when the KPIs
    section moves to S6. The compat redirect layer ensures the old anchor
    still resolves during the transition. Updated to use the future anchor
    once ANCHOR_MAP is populated (commit 4); until then, sec-ii-2 is still
    the canonical anchor and this is a no-op change.
    """
    pass  # v8.3.0: removed — sidebar nav handles navigation


def _combo_to_chart(cards):
    """Convert raw card tokens to chart notation (B250-safe).
    Delegates to shared gem_nicknames.combo_to_chart."""
    from gem_nicknames import combo_to_chart
    return combo_to_chart(cards)


def pb_payload_js(name, json_str, item_count=None):
    """v8.12.0 R1: emit one PB_PAYLOADS registry entry (deflate-raw+base64).
    Single codec contract — wbits=-15 matches JS DecompressionStream
    ('deflate-raw') and the embedded PBInflateFallback. Emitted via
    json.dumps (never manual quoting; </script> made safe by JSON escaping
    of the forward slash sequence below)."""
    import zlib
    import base64
    import json as _json
    raw = json_str.encode('utf-8')
    co = zlib.compressobj(level=9, wbits=-15)
    comp = co.compress(raw) + co.flush()
    b64 = base64.b64encode(comp).decode('ascii')
    meta = {'encoding': 'deflate-raw+base64', 'version': 1,
            'rawBytes': len(raw), 'compressedBytes': len(comp), 'data': b64}
    if item_count is not None:
        meta['itemCount'] = item_count
    js = ('window.PB_PAYLOADS=window.PB_PAYLOADS||{};'
          'window.PB_PAYLOADS[' + _json.dumps(name) + ']='
          + _json.dumps(meta) + ';')
    return js.replace('</', '<\\/')


_SHORT_VERDICT = {
    'I.7': 'Cooler', 'III.0': 'Standard', 'III.1': 'Punt', 'III.2': 'Mistake',
    'III.3': 'Correct', 'III.4': 'Read-Dep', 'III.5': 'Justified',
    'III.8': 'Pick', 'III.9': 'Pick',
}


def short_verdict_pill(h, verdict_str, app_details=None):
    """v8.12.3 (Ron QA): 1-2 word verdict pill for the hand title bar.
    Pure display of existing upstream facts: the analyst/auto verdict code,
    or the EAI suckout/flip classification when no verdict exists."""
    label = ''
    _v = (verdict_str or '')
    for code, lbl in _SHORT_VERDICT.items():
        if code in _v:
            label = lbl
            break
    if not label:
        # humanized verdict words (post-R4 labels) and common variants
        _vl = _v.lower()
        for word, lbl in (('cooler', 'Cooler'), ('punt', 'Punt'),
                          ('mistake', 'Mistake'), ('cleared', 'Correct'),
                          ('justified', 'Justified'),
                          ('gto-standard', 'Standard'),
                          ('standard', 'Standard'),
                          ('read-dependent', 'Read-Dep'),
                          ('pick', 'Pick')):
            if word in _vl:
                label = lbl
                break
    if not label:
        _ad = app_details or {}
        _so = (_ad.get('eai_suckout') or h.get('eai_suckout') or '')
        if _so == 'hero_sucked_out':
            label = 'Suckout'
        elif _so == 'hero_got_sucked_out':
            label = 'Cooler'
        elif h.get('pf_allin'):
            _eq = (_ad.get('eai_hero_equity')
                   if _ad.get('eai_hero_equity') is not None
                   else h.get('eai_hero_equity'))
            if _eq is not None:
                _eqp = _eq * 100 if _eq <= 1.5 else _eq
                if 40 <= _eqp <= 60:
                    label = 'Flip'
    if not label:
        return ''
    return (f"<span class='verdict-pill' "
            f"data-verdict='{label}'>{label}</span>")


def render_count_cell(count, hand_ids, context_title):
    """v8.12.0 shared count-cell (PKO spec): the NUMBER is the control --
    no separate Hands column anywhere.
      0 -> muted plain text, not clickable
      N -> .hand-list-trigger popup (existing openHandListPopup infra);
           a 1-count popup row is itself the direct hand link, which keeps
           the cell presence-tolerant for hands without appendix cards.
    All attribute content is HTML-escaped; count == len(unique ids)."""
    import html as _h
    ids = []
    _seen = set()
    for x in (hand_ids or []):
        x = str(x)
        if x and x not in _seen:
            _seen.add(x)
            ids.append(x)
    n = len(ids)
    if n == 0:
        # plain text — the md-table cell escaper would render any markup
        # literally, and the stash whitelist only passes hand-list-trigger
        # anchors (see _html.py BUG-1 stash regex).
        return '0'
    title = _h.escape(str(context_title or 'Hands'), quote=True)
    hids = _h.escape(','.join(ids[:60]), quote=True)
    # class must be EXACTLY hand-list-trigger to match the renderer's stash
    # whitelist; extra classes get the anchor escaped to literal text.
    return (f'<a class="hand-list-trigger" href="#" '
            f'data-hids="{hids}" data-list-title="{title}">{n}</a>')


# ============================================================
# DOCUMENT BUILDER
# ============================================================

