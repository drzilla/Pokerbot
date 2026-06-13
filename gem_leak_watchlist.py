"""
gem_leak_watchlist.py — Daily leak watchlist for the GEM report.

Compares the current session's metrics against target ranges derived from
the 64-session analysis (May 2026 cohort). Produces a watchlist that gets
rendered as a section in the daily report under the TLDR.

Targets are stored in this module (constants) so the watchlist runs without
any external file. Re-run `gem_meta_analysis.py --refit` to update them.

Renderer wires through gem_report_data.py → rd['leak_watchlist'] →
gem_report_draft.py emit function.

Status logic:
  - For "higher is better" metrics: ≥ p75 → green ; ≤ p25 → red ; else amber
  - For "lower is better" metrics:  ≤ p25 → green ; ≥ p75 → red ; else amber

Targets are session-level, computed from the May 2026 calibration cohort.
"""

# Targets refit 2026-05-14 from 64-session cohort (Dec 31 2025 → May 13 2026).
# Each entry: (label, direction, p25, p75, top_quartile_avg, action_phrase)
# Direction "higher" means higher is better (raise green threshold above p75);
# "lower" means lower is better (raise green threshold below p25).
LEAK_TARGETS = {
    # ---- Same-session leverage (work on these mid-session) ----
    'Cold_Call_NB': {
        'label': 'Cold-call (non-blind) %',
        'direction': 'lower',
        'p25': 3.6, 'p75': 6.5,
        'top_avg': 4.4, 'bot_avg': 6.5,
        'action': "3-bet or fold; don't flat raises",
        'priority': 1,
    },
    'VPIP_PFR_Gap_Raw': {
        'label': 'VPIP–PFR gap (raw)',
        'direction': 'lower',
        'p25': 6.0, 'p75': 7.5,
        'top_avg': 6.2, 'bot_avg': 7.8,
        'action': 'shrink passive calling — 3-bet/fold instead of flat',
        'priority': 1,
    },
    'CR_Flop_Pct': {
        'label': 'Check-raise flop %',
        'direction': 'higher',
        'p25': 6.7, 'p75': 12.7,
        'top_avg': 11.1, 'bot_avg': 8.2,
        'action': 'check-raise the flop more',
        'priority': 1,
    },
    'AF': {
        'label': 'Aggression Factor',
        'direction': 'higher',
        'p25': 1.8, 'p75': 2.74,
        'top_avg': 2.56, 'bot_avg': 2.09,
        'action': 'keep AF up — bet/raise more, call less',
        'priority': 1,
    },
    'F2_Flop_CBet_Large': {
        'label': 'Large-tier flop CBet %',
        'direction': 'lower',
        'p25': 50.0, 'p75': 83.3,
        'top_avg': 57.2, 'bot_avg': 71.8,
        'action': 'use smaller flop c-bet sizing more',
        'priority': 2,
    },
    'F2_Flop_CBet_Small': {
        'label': 'Small-tier flop CBet %',
        'direction': 'higher',
        'p25': 47.1, 'p75': 63.2,
        'top_avg': 64.9, 'bot_avg': 53.0,
        'action': 'default to smaller flop c-bets',
        'priority': 2,
    },
    'VPIP': {
        'label': 'VPIP',
        'direction': 'lower',
        'p25': 21.0, 'p75': 23.5,
        'top_avg': 22.0, 'bot_avg': 23.8,
        'action': "tighten ranges; don't widen in-session",
        'priority': 2,
    },
    'BB_Iso_SB_Limp': {
        'label': 'BB iso vs SB limp %',
        'direction': 'higher',
        'p25': 14.3, 'p75': 37.5,
        'top_avg': 33.8, 'bot_avg': 19.4,
        'action': 'isolate SB limpers from BB',
        'priority': 2,
    },
    'F2_Turn_CBet_Small': {
        'label': 'Small turn CBet %',
        'direction': 'lower',
        'p25': 0.0, 'p75': 50.0,
        'top_avg': 27.3, 'bot_avg': 48.1,
        'action': 'avoid small turn c-bets (under-pressures draws)',
        'priority': 2,
    },
    'River_Bet_Avg_bb': {
        'label': 'River bet avg (BB)',
        'direction': 'higher',
        'p25': 2.84, 'p75': 12.1,
        'top_avg': 9.62, 'bot_avg': -1.99,
        'action': 'bigger river bets when value-betting',
        'priority': 2,
    },
    'Agg_React_Delta': {
        'label': 'Aggression reaction delta',
        'direction': 'higher',
        'p25': 3.74, 'p75': 7.74,
        'top_avg': 6.4, 'bot_avg': 4.0,
        'action': 'counter-aggress when villain bets back',
        'priority': 3,
    },

    # ---- Trajectory leverage (build into baseline style) ----
    'ATS_Raw': {
        'label': 'ATS (raw, aggregate)',
        'direction': 'higher',
        'p25': 32.0, 'p75': 40.4,
        'top_avg': 36.2, 'bot_avg': 33.5,
        'action': 'attempt more steals across CO/BTN/SB',
        'priority': 1,
        'window': 'trajectory',
    },
    'ThreeBet_OOP': {
        'label': '3-Bet from OOP',
        'direction': 'higher',
        'p25': 7.3, 'p75': 9.6,
        'top_avg': 8.6, 'bot_avg': 8.9,
        'action': '3-bet more from OOP (BB/SB vs late opens)',
        'priority': 1,
        'window': 'trajectory',
    },
    'Flop_CBet_HU_OOP': {
        'label': 'Flop CBet HU OOP %',
        'direction': 'higher',
        'p25': 50.0, 'p75': 72.0,
        'top_avg': 61.2, 'bot_avg': 52.1,
        'action': 'c-bet more when HU OOP',
        'priority': 2,
        'window': 'trajectory',
    },
    'CBet_3BP': {
        'label': 'CBet in 3-bet pots %',
        'direction': 'higher',
        'p25': 16.7, 'p75': 27.6,
        'top_avg': 22.1, 'bot_avg': 22.5,
        'action': 'c-bet 3-bet pots more aggressively',
        'priority': 2,
        'window': 'trajectory',
    },
    'Triple_Barrel': {
        'label': 'Triple-barrel %',
        'direction': 'lower',
        'p25': 0.0, 'p75': 6.7,
        'top_avg': 5.2, 'bot_avg': 5.7,
        'action': 'cut river bluffs — over-bluffing leak',
        'priority': 2,
        'window': 'trajectory',
    },
    'Pure_Bluff_Pct': {
        'label': 'Pure bluff %',
        'direction': 'higher',
        'p25': 14.3, 'p75': 21.6,
        'top_avg': 17.7, 'bot_avg': 15.2,
        'action': 'more bluffs on flop/turn',
        'priority': 3,
        'window': 'trajectory',
    },
    'Semi_Bluff_Pct': {
        'label': 'Semi-bluff %',
        'direction': 'higher',
        'p25': 18.5, 'p75': 22.0,
        'top_avg': 20.6, 'bot_avg': 21.0,
        'action': 'more semi-bluffs on flop/turn',
        'priority': 3,
        'window': 'trajectory',
    },
    'Hero_4Bet': {
        'label': 'Hero 4-bet %',
        'direction': 'higher',
        'p25': 4.8, 'p75': 10.4,
        'top_avg': 6.2, 'bot_avg': 6.8,
        'action': '4-bet more (mix value + bluff)',
        'priority': 3,
        'window': 'trajectory',
    },
    'PFR': {
        'label': 'PFR',
        'direction': 'higher',
        'p25': 14.6, 'p75': 16.9,
        'top_avg': 15.7, 'bot_avg': 16.0,
        'action': 'maintain aggressive baseline; raise more first-in',
        'priority': 2,
        'window': 'trajectory',
    },
}


# B-V10 FEATURE (2026-06-01): map each watchlist metric to its report
# section anchor so red/amber metrics can link to the drill-down.
# CP23: remapped dead-end sec-6-2 targets to sections with actual hand
# popups. sec-6-2 is a summary-only table (0 popups). The position
# analysis (sec-8-1) has 94+ popups for VPIP/PFR drill-down.
METRIC_SECTION_MAP = {
    'Cold_Call_NB':         'sec-8-4',      # S8.4 Cold-Call Defense (14 popups)
    'VPIP_PFR_Gap_Raw':     'sec-8-1',      # S8.1 Position Analysis (94 popups, VPIP/PFR by pos)
    'CR_Flop_Pct':          'sec-11-7',     # S11.7 Check-Raise Frequency (4 popups)
    'AF':                   'sec-11-11',    # S11.11 Bet/Check Decision (13 popups, AF detail)
    'F2_Flop_CBet_Large':   'tbl-cbet-split',  # C-Bet Split table (deep anchor)
    'F2_Flop_CBet_Small':   'tbl-cbet-split',  # C-Bet Split table (deep anchor)
    'VPIP':                 'sec-8-1',      # S8.1 Position Analysis (VPIP by pos, 94 popups)
    'BB_Iso_SB_Limp':       'sec-8-3',      # S8.3 BB vs SB Limp (22 popups)
    'F2_Turn_CBet_Small':   'tbl-cbet-split',  # C-Bet Split table — turn row
    'River_Bet_Avg_bb':     'sec-11-11',    # S11.11 Bet / Check Decision (13 popups)
    'Agg_React_Delta':      'sec-11-10',    # S11.10 Aggression Profile (AF breakdown)
    'ATS_Raw':              'sec-8-1',      # S8.1 Position Analysis (ATS by pos, 94 popups)
    'ThreeBet_OOP':         'tbl-squeeze-frequency',  # Squeeze/3-Bet table (deep anchor)
    'Flop_CBet_HU_OOP':     'tbl-cbet-split',  # C-Bet Split table — HU OOP row
    'CBet_3BP':             'sec-10',       # S10 Postflop 3BP/4BP (3BP c-bet inside)
    'Triple_Barrel':        'sec-11-11',    # S11.11 Bet / Check Decision
    'Pure_Bluff_Pct':       'tbl-bluff-profile',  # Bluff Profile table (deep anchor)
    'Semi_Bluff_Pct':       'tbl-bluff-profile',  # Bluff Profile table (deep anchor)
    'Hero_4Bet':            'tbl-4bet-frequency',  # 4-Bet table (deep anchor)
    'PFR':                  'sec-8-1',      # S8.1 Position Analysis (PFR by pos, 94 popups)
}


def _status_for(metric_key, value):
    """Classify a single metric value vs its target as green/amber/red."""
    t = LEAK_TARGETS.get(metric_key)
    if not t or value is None:
        return None
    direction = t['direction']
    p25, p75 = t['p25'], t['p75']
    if direction == 'higher':
        if value >= p75:
            return 'green'
        elif value <= p25:
            return 'red'
        else:
            return 'amber'
    else:  # lower
        if value <= p25:
            return 'green'
        elif value >= p75:
            return 'red'
        else:
            return 'amber'


def build_leak_watchlist(csv_row, prev_csv_row=None, hands=None):
    """Build the leak watchlist for one session.

    Args:
        csv_row: dict-like with session metric values (from stats['csv_row'])

    Returns:
        dict with keys:
          - 'session_metrics': list of dicts {metric, label, value, status, target_range, action, priority, window}
          - 'red_count', 'amber_count', 'green_count': summary tallies
          - 'top_actions': prioritized list of red/amber items with action phrases
          - 'verdict_line': one-line summary for sidebar
    """
    def fnum(x):
        try:
            return float(x) if x not in (None, '') else None
        except (TypeError, ValueError):
            return None

    items = []
    for metric_key, t in LEAK_TARGETS.items():
        value = fnum(csv_row.get(metric_key))
        status = _status_for(metric_key, value)
        if status is None:
            continue
        direction = t['direction']
        # v8.12.4 (QA item 16): a literal "≤0.0 (aim)" is a quartile-fit
        # artifact (bottom cohort quartile == 0), not an actionable target —
        # show the top-quartile average as the aim instead.
        if direction == 'higher':
            if t['p75'] <= 0 and t.get('top_avg'):
                target_range = f"aim ≈{t['top_avg']:.1f} · ≤{t['p25']:.1f} (warn)"
            else:
                target_range = f"≥{t['p75']:.1f} (aim) · ≤{t['p25']:.1f} (warn)"
        else:
            if t['p25'] <= 0 and t.get('top_avg'):
                target_range = f"aim ≈{t['top_avg']:.1f} · ≥{t['p75']:.1f} (warn)"
            else:
                target_range = f"≤{t['p25']:.1f} (aim) · ≥{t['p75']:.1f} (warn)"
        items.append({
            'metric': metric_key,
            'label': t['label'],
            'value': round(value, 2),
            'status': status,
            'direction': direction,
            'p25': t['p25'],
            'p75': t['p75'],
            'top_avg': t.get('top_avg'),
            'target_range': target_range,
            'action': t['action'],
            'priority': t.get('priority', 3),
            'window': t.get('window', 'session'),
            'section': METRIC_SECTION_MAP.get(metric_key, ''),
        })

    # Batch 5 (4F): session-over-session comparison
    # If prev_csv_row provided, add delta from previous session
    if prev_csv_row:
        for item in items:
            prev_val = fnum(prev_csv_row.get(item['metric']))
            if prev_val is not None:
                item['prev_value'] = round(prev_val, 2)
                item['delta_from_prev'] = round(item['value'] - prev_val, 2)
                _dir = item.get('direction', 'lower')
                if _dir == 'higher':
                    item['trend'] = 'improving' if item['value'] > prev_val else 'worsening'
                else:
                    item['trend'] = 'improving' if item['value'] < prev_val else 'worsening'

    # Batch 3 (#4): per-metric breakdowns for red/amber items
    # Attach sub_breakdowns to each flagged item so the renderer can show
    # "VPIP by position" or "Cold-call by opener" inline.
    if hands:
        _pos_list = ['UTG', 'UTG+1', 'MP', 'HJ', 'CO', 'BTN', 'SB', 'BB']
        for item in items:
            if item['status'] not in ('red', 'amber'):
                continue
            mk = item['metric']
            breakdowns = []
            if mk == 'VPIP':
                for pos in _pos_list:
                    _ph = [h for h in hands if h.get('position') == pos]
                    _pv = sum(1 for h in _ph if h.get('vpip'))
                    if _ph:
                        breakdowns.append({'dimension': pos, 'value': round(100*_pv/len(_ph), 1),
                                           'sample': len(_ph)})
            elif mk == 'PFR':
                for pos in _pos_list:
                    _ph = [h for h in hands if h.get('position') == pos]
                    _pv = sum(1 for h in _ph if h.get('pfr'))
                    if _ph:
                        breakdowns.append({'dimension': pos, 'value': round(100*_pv/len(_ph), 1),
                                           'sample': len(_ph)})
            elif mk == 'VPIP_PFR_Gap_Raw':
                for pos in _pos_list:
                    _ph = [h for h in hands if h.get('position') == pos]
                    _pv = sum(1 for h in _ph if h.get('vpip'))
                    _pp = sum(1 for h in _ph if h.get('pfr'))
                    if _ph and len(_ph) > 5:
                        _gap = 100*(_pv - _pp)/len(_ph)
                        breakdowns.append({'dimension': pos, 'value': round(_gap, 1),
                                           'sample': len(_ph)})
            elif mk == 'Cold_Call_NB':
                for pos in _pos_list:
                    if pos in ('SB', 'BB'):
                        continue
                    _ph = [h for h in hands if h.get('position') == pos and h.get('hero_faced_raise')]
                    _cc = sum(1 for h in _ph if h.get('cold_called'))
                    if _ph:
                        breakdowns.append({'dimension': pos, 'value': round(100*_cc/len(_ph), 1),
                                           'sample': len(_ph)})
            elif mk == 'AF':
                for st in ['flop', 'turn', 'river']:
                    _agg = sum(1 for h in hands for a in (h.get('action_ledger') or [])
                               if a.get('street') == st and a.get('player') == h.get('hero')
                               and a.get('action') in ('bets', 'raises'))
                    _pas = sum(1 for h in hands for a in (h.get('action_ledger') or [])
                               if a.get('street') == st and a.get('player') == h.get('hero')
                               and a.get('action') in ('calls', 'checks'))
                    if _pas > 0:
                        breakdowns.append({'dimension': st, 'value': round(_agg / _pas, 2),
                                           'sample': _agg + _pas})
            elif mk == 'ATS_Raw':
                for pos in ['CO', 'BTN', 'SB']:
                    _ph = [h for h in hands if h.get('position') == pos and h.get('first_in')]
                    _st = sum(1 for h in _ph if h.get('vpip'))
                    if _ph:
                        breakdowns.append({'dimension': pos, 'value': round(100*_st/len(_ph), 1),
                                           'sample': len(_ph)})
            if breakdowns:
                item['sub_breakdowns'] = breakdowns

    # v8.12.4 (QA item 16): a red row whose entire evidence base is under 5
    # spots is a hypothesis, not a leak — downgrade to amber and say why.
    # (Only possible when per-dimension breakdowns carry samples.)
    for item in items:
        if item['status'] == 'red' and item.get('sub_breakdowns'):
            _tot_n = sum(b.get('sample', 0) for b in item['sub_breakdowns'])
            if 0 < _tot_n < 5:
                item['status'] = 'amber'
                item['action'] = f"(thin sample, n={_tot_n}) " + item['action']

    # v8.12.4 (QA item 16): bluff-family coherence. When one bluff metric
    # says "bluff more" and another says "bluff less" in the same session,
    # the real finding is SPOT SELECTION — say it once instead of letting
    # the reader reconcile contradictory rows.
    _bluff_keys = [i for i in items
                   if i['status'] in ('red', 'amber')
                   and any(w in i['metric'].lower()
                           for w in ('bluff', 'barrel'))]
    _want_more = [i for i in _bluff_keys if i['direction'] == 'higher'
                  and i['value'] < i['p75']]
    _want_less = [i for i in _bluff_keys if i['direction'] == 'lower'
                  and i['value'] > i['p25']]
    synthesis_notes = []
    if _want_more and _want_less:
        synthesis_notes.append(
            "🧩 **Bluff rows point in opposite directions** ("
            + ', '.join(i['label'] for i in _want_more) + " say bluff MORE; "
            + ', '.join(i['label'] for i in _want_less) + " say bluff LESS). "
            "Read together this is a SPOT-SELECTION leak — under-bluffing "
            "good spots while over-bluffing bad ones — not a global "
            "frequency dial. Drill spot selection (board + range fit), "
            "not 'bluff more' or 'bluff less'.")

    # Sort: red first by priority, then amber by priority, then green
    status_rank = {'red': 0, 'amber': 1, 'green': 2}
    items.sort(key=lambda x: (status_rank[x['status']], x['priority']))

    red_items = [i for i in items if i['status'] == 'red']
    amber_items = [i for i in items if i['status'] == 'amber']
    green_items = [i for i in items if i['status'] == 'green']

    top_actions = []
    for item in (red_items + amber_items)[:5]:
        # Only include priority 1 + priority 2 in top_actions
        if item['priority'] <= 2:
            arrow = '↑' if item['direction'] == 'higher' else '↓'
            top_actions.append({
                'metric': item['metric'],
                'label': item['label'],
                'value': item['value'],
                'p25': item['p25'],
                'p75': item['p75'],
                'arrow': arrow,
                'status': item['status'],
                'action': item['action'],
                'section': item.get('section', ''),
            })

    n_red = len(red_items); n_amber = len(amber_items); n_green = len(green_items)
    n_total = n_red + n_amber + n_green
    if n_red == 0 and n_amber <= 3:
        verdict_summary = f"Leak watchlist: {n_green}/{n_total} green — solid session profile"
    elif n_red >= 4:
        verdict_summary = f"Leak watchlist: {n_red} red, {n_amber} amber — multiple actionable leaks"
    else:
        verdict_summary = f"Leak watchlist: {n_red} red, {n_amber} amber, {n_green} green"

    return {
        'session_metrics': items,
        'red_count': n_red,
        'amber_count': n_amber,
        'green_count': n_green,
        'top_actions': top_actions,
        'verdict_line': verdict_summary,
        'synthesis_notes': synthesis_notes,
    }
